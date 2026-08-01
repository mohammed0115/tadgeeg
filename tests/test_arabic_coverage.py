"""Arabic is this product's primary language, not a translation of English.

Every customer- and operator-facing string added by phases 1-3A rendered in
English on the Arabic site until this was caught by screenshotting the running
app: 102 strings across the partner pages, the trial-users dashboard, the
partner-application review console, the platform navigation, and the pricing
page. They were all correctly wrapped in ``{% trans %}`` / ``_()`` — the wrapper
is not the point. The catalogue entry is.

A rendering test can only cover the pages it thinks to visit. This one is
static: it reads the source of the surfaces these phases own and asserts every
extracted msgid has a non-empty Arabic msgstr, so a *new* string fails here the
moment it is written, without anyone remembering to screenshot anything.

Scope is deliberately the file list below rather than the whole repo: those are
the files these phases authored. Widening it to every template would fail on
pre-existing gaps this phase did not create and is not fixing.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
CATALOGUE = REPO / "locale" / "ar" / "LC_MESSAGES" / "django.po"

# Surfaces authored by phases 1 (trial capture), 2A/2B (partners) and 3A
# (plan catalogue), plus the navigation that links them.
OWNED = [
    "templates/landing/pricing.html",
    "templates/landing/partners.html",
    "templates/landing/partner_detail.html",
    "templates/landing/partner_apply.html",
    "templates/platform_admin/partner_applications.html",
    "templates/platform_admin/partner_applications_export.html",
    "templates/platform_admin/partners.html",
    "templates/platform_admin/trial_users.html",
    "templates/platform_admin/trial_users_export.html",
    "templates/platform_admin/feature_unavailable.html",
    "navigation/platform_menu.py",
    # STEP 0.2 — partner type/tier labels rendered "Strategic Partner" in the
    # Arabic card meta line. Model choice labels are user-facing strings too.
    "apps/partners/models.py",
    # The partners hero subtitle lives here and rendered in English on the
    # Arabic page. It is a multi-line implicit concatenation, which is why the
    # regex-based extractor above could not see it — see _gettext_calls_in_python.
    "apps/partners/selectors.py",
    # The registration form is the first screen a lead sees. Its §A.2/§A.3
    # choice labels live on the model and rendered in English inside an
    # otherwise-Arabic form ("Use it in my own company", "Select an option"),
    # with the question mark landing at the wrong end of the line.
    "apps/leads/models.py",
    "templates/auth/portal.html",
    "apps/authentication/serializers.py",
]

_TRANS = re.compile(r'{%\s*trans\s+(["\'])(.*?)\1\s*%}')
_GETTEXT = re.compile(r'_\(\s*(["\'])(.*?)\1\s*\)')
# NOTE: do NOT parse the catalogue with a regex. gettext wraps long strings
# across continuation lines (`msgid ""` followed by quoted fragments), which a
# single-line pattern cannot see. The earlier version of this file used one and
# reported 12 already-translated strings as missing — a false alarm that sent
# someone appending duplicate entries until `msgfmt` refused the file with
# "duplicate message definition". polib reads both forms.


def _translated() -> set[str]:
    """msgids that have a non-empty Arabic translation."""
    import polib

    return {
        e.msgid for e in polib.pofile(str(CATALOGUE))
        if e.msgstr.strip() and "fuzzy" not in e.flags
    }


def _gettext_calls_in_python(src: str) -> list[str]:
    """Extract `_("...")` arguments by parsing, not by regex.

    Python joins adjacent string literals implicitly, so a message wrapped
    across lines —

        _("The Tadgeeg partner ecosystem — strategic partners, tiered "
          "partners, and authorized distributors.")

    — is ONE msgid, and a single-literal regex sees neither half of it. That is
    exactly how the partners hero subtitle stayed English on the Arabic page
    while this file reported full coverage. `ast` resolves the concatenation
    the same way the interpreter and `makemessages` do.
    """
    import ast

    found: list[str] = []
    try:
        tree = ast.parse(src)
    except SyntaxError:                       # not importable; nothing to check
        return found

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        name = getattr(fn, "id", None) or getattr(fn, "attr", None)
        if name not in {"_", "gettext", "gettext_lazy", "ugettext",
                        "ugettext_lazy", "pgettext", "pgettext_lazy"}:
            continue
        if not node.args:
            continue
        arg = node.args[-1] if name.startswith("pgettext") else node.args[0]
        if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
            found.append(arg.value)
    return found


def _strings_in(path: Path) -> list[str]:
    src = path.read_text(encoding="utf-8")
    if path.suffix == ".py":
        # Templates cannot concatenate implicitly; Python can, so it is parsed.
        return [m.group(2) for m in _TRANS.finditer(src)] + _gettext_calls_in_python(src)
    return [m.group(2) for m in _TRANS.finditer(src)] + [
        m.group(2) for m in _GETTEXT.finditer(src)
    ]


def test_arabic_catalogue_exists():
    assert CATALOGUE.exists(), f"missing Arabic catalogue at {CATALOGUE}"


@pytest.mark.parametrize("relpath", OWNED)
def test_every_string_has_an_arabic_translation(relpath):
    path = REPO / relpath
    if not path.exists():                       # file removed by a later phase
        pytest.skip(f"{relpath} does not exist")

    have = _translated()
    missing = sorted({s for s in _strings_in(path) if s not in have})
    assert not missing, (
        f"{relpath} has {len(missing)} string(s) with no Arabic translation:\n"
        + "\n".join(f"  · {s}" for s in missing)
        + "\n\nAdd them to locale/ar/LC_MESSAGES/django.po and run "
          "`manage.py compilemessages -l ar`."
    )


def test_compiled_catalogue_is_not_stale():
    """A .po edit that was never compiled changes nothing at runtime.

    This is the failure mode that makes a translation look done in review and
    still ship in English: .mo is what Django actually loads.
    """
    mo = CATALOGUE.with_suffix(".mo")
    assert mo.exists(), "django.mo is missing — run `manage.py compilemessages -l ar`"
    assert mo.stat().st_mtime >= CATALOGUE.stat().st_mtime, (
        "locale/ar/LC_MESSAGES/django.po is newer than django.mo — the Arabic "
        "site is still serving the previously compiled strings. Run "
        "`manage.py compilemessages -l ar`."
    )


# ── the scope problem, made measurable ───────────────────────────────────────
#
# OWNED above is a hand-maintained list, and twice in one session English
# reached a user from a file nobody had remembered to add to it. A guard whose
# scope is a manual list will keep missing what nobody thought of.
#
# Widening it to the whole repository would fail immediately on ~101 strings
# that predate this work, and a permanently red test is a test people learn to
# ignore. So the gap is measured instead: it is allowed to exist, it is not
# allowed to GROW. Lowering this number is the only permitted direction.
UNTRANSLATED_BUDGET = 105


def _repo_scan_paths():
    repo = Path(__file__).resolve().parent.parent
    seen: set[Path] = set()
    for pattern in ("templates/**/*.html", "apps/**/*.py",
                    "navigation/*.py", "core/**/*.py"):
        for path in repo.glob(pattern):
            rel = str(path.relative_to(repo))
            # Migrations carry historical verbose_names nobody reads, and test
            # files are not user-facing.
            if "/migrations/" in rel or "/tests/" in rel or rel.startswith("tests/"):
                continue
            seen.add(path)
    return sorted(seen)


def test_untranslated_strings_outside_the_guard_do_not_grow():
    """A ratchet on the strings the explicit list does not cover.

    This does not assert the repository is fully translated — it is not. It
    asserts the untranslated surface is no larger than it was when measured,
    so a new English string in an uncovered file fails here even though nobody
    added that file to OWNED.
    """
    repo = Path(__file__).resolve().parent.parent
    covered = {str(repo / rel) for rel in OWNED}
    have = _translated()

    total = 0
    offenders: list[tuple[int, str]] = []
    for path in _repo_scan_paths():
        if str(path) in covered:
            continue
        try:
            missing = {s for s in _strings_in(path) if s not in have}
        except (UnicodeDecodeError, OSError):
            continue
        if missing:
            total += len(missing)
            offenders.append((len(missing), str(path.relative_to(repo))))

    offenders.sort(reverse=True)
    worst = "\n".join(f"    {n:>4}  {rel}" for n, rel in offenders[:10])
    assert total <= UNTRANSLATED_BUDGET, (
        f"untranslated strings outside the guard grew to {total} "
        f"(budget {UNTRANSLATED_BUDGET}).\n"
        f"Translate the new string, or add its file to OWNED.\n"
        f"Largest offenders:\n{worst}"
    )

    # Ratchet: if the number has come down, the budget follows it down.
    assert total >= UNTRANSLATED_BUDGET - 25, (
        f"only {total} untranslated strings remain (budget {UNTRANSLATED_BUDGET}). "
        f"Lower UNTRANSLATED_BUDGET to {total} so the gap cannot silently reopen."
    )
