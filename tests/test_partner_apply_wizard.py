"""The partner application is a six-step wizard — and the server still decides.

§L.3 specifies six numbered sections; they now render one at a time with a
progress indicator, step gating, inline validation, a client-side file
pre-check, and draft persistence.

The security-relevant property is what this file spends most of its assertions
on: **client-side gating is convenience, not authority.** A wizard that lets the
browser decide what is valid is a security regression, so the tests below prove
the API still refuses the same things it refused in 2B — including a submission
that never went near the wizard.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.django_db

TEMPLATE = Path(__file__).resolve().parent.parent / "templates" / "landing" / "partner_apply.html"
APPLY_URL = "/partners/apply/"
API_URL = "/api/v1/partners/applications/"


def _src() -> str:
    return TEMPLATE.read_text(encoding="utf-8")


# ── structure ────────────────────────────────────────────────────────────────

def test_all_six_sections_are_step_scoped():
    """§L.3's six sections, each bound to its own step."""
    src = _src()
    scoped = re.findall(r'<div class="section" x-show="step === (\d)"', src)
    assert scoped == ["1", "2", "3", "4", "5", "6"], (
        f"expected six step-scoped sections in order, found {scoped}"
    )


def test_sections_are_cloaked_until_alpine_boots():
    """Without x-cloak every step renders at once for a frame — the exact
    all-on-one-page layout the wizard replaces."""
    src = _src()
    assert src.count("x-cloak") >= 7, "sections are not cloaked"
    assert "[x-cloak] { display: none !important; }" in src, (
        "x-cloak is used but never given its CSS rule, so it does nothing"
    )


def test_progress_indicator_reports_step_and_completion():
    src = _src()
    assert 'x-text="`{% trans "Step" %} ${step} / ${TOTAL}`"' in src
    assert "completedCount()" in src, "no completion count is shown"
    assert 'class="steps"' in src, "no visible step indicator"


def test_page_renders_and_shows_the_wizard(client):
    body = client.get(APPLY_URL).content.decode()
    assert 'x-show="step === 1"' in body
    assert 'class="steps"' in body
    assert "partnerApply()" in body


# ── gating ───────────────────────────────────────────────────────────────────

def test_step_gating_blocks_advance_with_invalid_required_fields():
    """`next()` must refuse and surface the errors, not silently advance."""
    src = _src()
    m = re.search(r"next\(\) \{(.*?)\n      \},", src, re.S)
    assert m, "next() not found"
    body = m.group(1)
    assert "stepErrors(this.step)" in body, "next() does not validate the step"
    assert "return false" in body, "next() does not refuse on invalid input"
    assert "this.step++" in body


def test_back_never_validates_so_input_is_never_lost():
    src = _src()
    m = re.search(r"back\(\) \{(.*?)\n      \},", src, re.S)
    assert m, "back() not found"
    assert "stepErrors" not in m.group(1), (
        "back() validates — moving backwards must not punish a half-filled step"
    )


def test_stepper_cannot_be_used_to_skip_the_gate():
    """Clicking ahead in the indicator must honour the same rule as Next."""
    src = _src()
    m = re.search(r"goTo\(n\) \{(.*?)\n      \},", src, re.S)
    assert m, "goTo() not found"
    assert "isValid(i)" in m.group(1), (
        "goTo() jumps forward without checking the steps in between, which "
        "makes the Next-button gate decorative"
    )


def test_submit_is_gated_on_the_declaration():
    src = _src()
    assert ':disabled="sending || !f.declaration_accepted"' in src, (
        "submit is not disabled until the declaration is ticked"
    )


def test_required_fields_validate_on_blur_not_only_on_submit():
    src = _src()
    for field in ("company_name", "contact_name", "email", "mobile", "country"):
        assert f"blur('{field}')" in src, f"{field} has no blur validation"
        assert f"showError('{field}')" in src, f"{field} has no inline error slot"


# ── files ────────────────────────────────────────────────────────────────────

def test_file_precheck_mirrors_the_server_allow_list(client):
    """The limits are rendered from the server's own settings.

    Restating them in JavaScript is how a client check drifts from the rule it
    claims to mirror; this asserts they arrive from the server instead.
    """
    from django.conf import settings

    from apps.partners.uploads import ALLOWED_EXTENSIONS

    body = client.get(APPLY_URL).content.decode()
    assert f"MAX_MB: {settings.PARTNER_DOC_MAX_FILE_MB}" in body
    assert f"MAX_FILES: {settings.PARTNER_DOC_MAX_FILES}" in body
    for ext in ALLOWED_EXTENSIONS:
        assert ext in body, f"allow-list entry {ext} not rendered into the page"


def test_rejected_files_never_start_an_upload():
    src = _src()
    m = re.search(r"pick\(field, event\) \{(.*?)\n      \},", src, re.S)
    assert m, "pick() not found"
    body = m.group(1)
    assert "this.files[field] = []" in body, "a rejected file is still queued"
    assert "event.target.value = ''" in body, "the input is not cleared on reject"


# ── draft persistence ────────────────────────────────────────────────────────

def test_draft_persists_values_but_never_file_contents():
    src = _src()
    assert "localStorage.setItem(this.DRAFT_KEY, JSON.stringify(this.f))" in src
    # `this.f` holds field values only; `this.files` is a separate object and
    # must never be written to storage.
    assert "JSON.stringify(this.files)" not in src, (
        "file contents are being persisted to localStorage — a commercial "
        "register would be left behind in the browser of a shared machine"
    )


def test_declaration_is_not_restored_from_a_draft():
    src = _src()
    m = re.search(r"restoreDraft\(\) \{(.*?)\n      \},", src, re.S)
    assert m, "restoreDraft() not found"
    assert "this.f.declaration_accepted = false" in m.group(1), (
        "a declaration restored from storage is consent nobody gave"
    )


def test_a_successful_submission_clears_the_draft():
    src = _src()
    assert "this.clearDraft();" in src


# ── the wizard is still ONE submission, and the server is still the authority ─

def test_the_wizard_still_posts_once_to_the_existing_endpoint():
    src = _src()
    assert src.count("fetch(") == 1, "the wizard makes more than one request"
    assert API_URL in src, "the wizard no longer posts to the 2B endpoint"


def test_no_ui_library_was_added():
    """Alpine was already loaded; a wizard package is a refusal condition."""
    src = _src()
    for banned in ("wizard", "stepper.js", "formik", "vue", "react", "jquery"):
        assert f"cdn.jsdelivr.net/npm/{banned}" not in src.lower()
    assert "safe_static 'vendor/alpine.min.js'" in src, (
        "Alpine must load from safe_static with the CDN only as fallback — 2B "
        "shipped a CDN-only load on this page and corrected it"
    )


def test_server_still_rejects_a_submission_that_skips_the_wizard(client):
    """The decisive one: bypass the browser entirely.

    If the wizard's gating were the real rule, this empty POST would land.
    """
    resp = client.post(API_URL, {}, format="json")
    assert resp.status_code in (400, 401, 403, 415), (
        f"an empty application was not refused (got {resp.status_code})"
    )


def test_server_still_rejects_a_submission_without_the_declaration(client):
    """The declaration gate exists in the UI *and* in the API."""
    payload = {
        "company_name": "Bypass Co",
        "contact_name": "Someone",
        "email": "bypass@example.com",
        "mobile": "+966500000000",
        "country": "SA",
        "requested_partner_type": "technical",
        # declaration_accepted deliberately omitted
    }
    resp = client.post(API_URL, payload)
    assert resp.status_code in (400, 401, 403, 415), (
        f"an application without the declaration was accepted ({resp.status_code})"
    )


def test_unvisited_steps_are_not_marked_complete():
    """Steps 3-5 have no required fields, so they are valid immediately.

    Showing them ticked before the visitor has opened them claims they did
    something they did not — the progress indicator would be reporting the
    form's state, not theirs.
    """
    src = _src()
    assert "isComplete(n) { return !!this.visited[n] && this.isValid(n); }" in src, (
        "completion does not distinguish 'valid' from 'visited'"
    )
    assert "visited: { 1: true }" in src, "the starting step is not marked visited"
