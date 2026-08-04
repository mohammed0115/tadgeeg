"""WCAG AA, computed rather than asserted.

The platform assessment said the brand green "may not pass AA". It does not
pass, and not marginally: #10B981 on white measures 2.54:1 where AA asks 4.5:1
for body text and 3.0:1 even for large text. Every white-on-green button and
every green link on the product was below the bar — for all users, not only for
users with low vision.

These tests compute the contrast ratio from the palette rather than hard-coding
a verdict, so a future colour change is checked instead of assumed. The formula
is WCAG 2.1's relative luminance and contrast ratio, implemented here rather
than pulled in as a dependency: it is fifteen lines, and a colour check that
itself needs an uninstalled package would be the fourth instance of that
failure in this repository.
"""

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
TOKENS = REPO / "static/src/css/tokens.css"

WHITE = "#FFFFFF"
AA_NORMAL = 4.5
AA_LARGE = 3.0


def _relative_luminance(hex_colour):
    """WCAG 2.1 §relative luminance."""
    raw = hex_colour.lstrip("#")
    channels = [int(raw[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    linear = [
        c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
        for c in channels
    ]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def contrast_ratio(foreground, background):
    lighter = max(_relative_luminance(foreground), _relative_luminance(background))
    darker = min(_relative_luminance(foreground), _relative_luminance(background))
    return (lighter + 0.05) / (darker + 0.05)


def token(name):
    source = TOKENS.read_text(encoding="utf-8")
    match = re.search(rf"--{re.escape(name)}:\s*(#[0-9a-fA-F]{{6}})", source)
    assert match, f"token --{name} not found in tokens.css"
    return match.group(1)


# ── The formula itself, against WCAG's own published values ──────────────────

def test_the_contrast_formula_matches_known_values():
    """Black on white is 21:1 and white on white is 1:1, by definition.

    Without this, a bug in the maths would make every other test in the file
    agree with itself and be wrong.
    """
    assert round(contrast_ratio("#000000", WHITE), 2) == 21.0
    assert round(contrast_ratio(WHITE, WHITE), 2) == 1.0


# ── The palette ──────────────────────────────────────────────────────────────

def test_the_text_accent_passes_aa_on_white():
    """Green text on a white page, and white text on a green button."""
    accent = token("color-accent-text")
    assert contrast_ratio(accent, WHITE) >= AA_NORMAL, (
        f"--color-accent-text {accent} measures {contrast_ratio(accent, WHITE):.2f}:1 "
        f"on white; AA needs {AA_NORMAL}:1"
    )


def test_the_primary_navy_passes_aa_on_white():
    navy = token("color-primary-500") if "color-primary-500" in TOKENS.read_text(encoding="utf-8") \
        else token("color-primary-600")
    assert contrast_ratio(navy, WHITE) >= AA_NORMAL


def test_the_decorative_brand_green_is_documented_as_failing():
    """#10B981 stays in the palette for fills — the point is that it is not used
    for text, and that nobody re-reads it as safe.

    This asserts the failure on purpose: if a future palette change makes the
    brand green accessible, this test fails and the separate text token can be
    retired.
    """
    brand = token("color-accent-500")
    assert contrast_ratio(brand, WHITE) < AA_LARGE, (
        "the brand green now passes AA — retire --color-accent-text and simplify"
    )


def test_the_dark_mode_accent_passes_on_a_dark_surface():
    accent = token("color-accent-text-on-dark")
    for dark in ("#0F172A", "#1E293B"):
        assert contrast_ratio(accent, dark) >= AA_NORMAL, (
            f"{accent} on {dark} is {contrast_ratio(accent, dark):.2f}:1"
        )


@pytest.mark.parametrize("risk_token", ["risk-medium", "risk-high", "risk-critical"])
def test_risk_colours_are_readable_where_they_carry_meaning(risk_token):
    """Risk severity is conveyed by colour. If the colour cannot be read, the
    severity is not conveyed — and severity is the one thing an auditor scans
    a list for.

    Large-text threshold: these appear as badge labels, not body copy.
    """
    colour = token(risk_token)
    assert contrast_ratio(colour, WHITE) >= AA_LARGE, (
        f"--{risk_token} {colour} is {contrast_ratio(colour, WHITE):.2f}:1 on white"
    )


# ── Markup-level basics ──────────────────────────────────────────────────────

def test_every_page_declares_a_language_and_direction():
    """A screen reader with no lang attribute reads Arabic with English
    phonetics. On an Arabic-first product that is not a minor defect."""
    offenders = []
    for template in (REPO / "templates").rglob("*.html"):
        source = template.read_text(encoding="utf-8")
        for match in re.finditer(r"<html\b[^>]*>", source):
            tag = match.group(0)
            if "lang=" not in tag or "dir=" not in tag:
                offenders.append(f"{template.relative_to(REPO)}: {tag[:70]}")
    assert not offenders, "<html> without lang/dir:\n  " + "\n  ".join(offenders)


def test_images_carry_alt_text():
    """An <img> with no alt is announced as its filename, or skipped."""
    offenders = []
    for template in (REPO / "templates").rglob("*.html"):
        source = template.read_text(encoding="utf-8")
        for match in re.finditer(r"<img\b[^>]*>", source):
            if "alt=" not in match.group(0):
                line = source[:match.start()].count("\n") + 1
                offenders.append(f"{template.relative_to(REPO)}:{line}")
    assert not offenders, "<img> without alt:\n  " + "\n  ".join(offenders)


def test_the_manual_review_inputs_are_labelled():
    """The panel restored in this session — every input needs a name a screen
    reader can announce, and a placeholder is not one."""
    source = (REPO / "templates/invoices/detail.html").read_text(encoding="utf-8")
    panel = source.split('id="manual-review"')[1].split("</section>")[0]

    inputs = re.findall(r'<input\b[^>]*data-field=[^>]*>', panel)
    assert inputs, "the manual review panel has no correction inputs"
    for tag in inputs:
        assert "id=" in tag, f"input has no id to bind a label to: {tag[:80]}"
    assert panel.count('class="sr-only"') >= 1, "no screen-reader label in the panel"


def test_error_regions_are_announced():
    """A validation error that only appears visually is invisible to a screen
    reader; aria-live is what makes it spoken."""
    for path in ("templates/billing/plans.html", "templates/invoices/detail.html"):
        source = (REPO / path).read_text(encoding="utf-8")
        assert 'role="alert"' in source, f"{path} has no role=alert region"
