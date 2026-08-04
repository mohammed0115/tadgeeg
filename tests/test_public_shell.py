"""Every public page must render the same shell, and /partners/ must be reachable.

The public pages each carried their own header and had drifted apart. The
visible consequences: `/partners/` and `/partners/apply/` offered no language
switcher and no trial CTA, and **nothing on any page linked to `/partners/`** —
it shipped in 2A and was reachable only by typing the URL. Its own tests call
the URL directly, so nothing ever failed.

That is the gap this file closes: a page reachable only by typing its URL is
not shipped, and no existing test could tell. These assertions run against the
rendered HTML of every public URL, not against the template source, because the
question is what a visitor receives.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.django_db

# Every page a visitor can reach without authenticating.
PUBLIC_URLS = [
    "/",
    "/pricing/",
    "/partners/",
    "/partners/apply/",
    "/about/",
    "/contact/",
]


def _html(client, url):
    resp = client.get(url)
    assert resp.status_code == 200, f"{url} returned {resp.status_code}"
    return resp.content.decode()


@pytest.mark.parametrize("url", PUBLIC_URLS)
def test_public_page_renders_the_shared_shell(client, url):
    body = _html(client, url)

    # The language switcher: its form action is the stable marker, not the
    # label, which changes with the active language.
    assert "/i18n/setlang/" in body, (
        f"{url} has no language switcher — a visitor landing here cannot "
        f"change language."
    )

    # The trial CTA is the primary conversion action on every public page.
    assert "frontend:register" in body or "/register/" in body, (
        f"{url} offers no route to the free trial."
    )

    # One logo lockup, not a bare wordmark.
    assert "site-header__logo" in body, f"{url} is not using the shared header"
    assert "تدقيق" in body, f"{url} renders no Arabic wordmark"


@pytest.mark.parametrize("url", PUBLIC_URLS)
def test_every_public_page_links_to_partners(client, url):
    """The 2A regression: a shipped page nothing linked to."""
    body = _html(client, url)
    assert "/partners/" in body, (
        f"{url} does not link to /partners/. That page is only reachable by "
        f"typing its URL, which is how it went unnoticed after 2A shipped it."
    )


def test_the_homepage_reaches_partners_specifically(client):
    """Called out separately because the homepage is where visitors start."""
    body = _html(client, "/")
    assert "/partners/" in body, (
        "navigation was one-way: partners → home worked, home → partners did not"
    )


def test_public_pages_do_not_use_the_stale_navy(client):
    """§L.1.1 — the public pages rendered #073763 while the identity is #003366.

    The shared header settles it. This guards the settlement rather than
    leaving it to drift back on the next page someone adds.
    """
    for url in PUBLIC_URLS:
        body = _html(client, url)
        assert "#073763" not in body, (
            f"{url} still renders the off-identity navy #073763 — see §L.1.1"
        )


def test_shell_is_one_template_not_copies():
    """The point is a single header, not several that happen to agree today."""
    from pathlib import Path

    repo = Path(__file__).resolve().parent.parent
    partial = repo / "templates" / "partials" / "public_header.html"
    assert partial.exists(), "the shared header partial is missing"

    landing = repo / "templates" / "landing"
    for name in ("index.html", "pricing.html", "partners.html",
                 "partner_detail.html", "partner_apply.html"):
        src = (landing / name).read_text(encoding="utf-8")
        assert "partials/public_header.html" in src, (
            f"landing/{name} does not include the shared header — a second "
            f"header implementation is how they drifted apart the first time."
        )


def test_partner_supplied_text_is_bidi_isolated():
    """A partner's own words carry their own direction, not the page's.

    A partner writes an Arabic description; the English page renders LTR, so
    the trailing full stop jumped to the left edge and Latin runs like "ERP"
    reordered around it. The text was never wrong — it inherited the wrong base
    direction. `unicode-bidi: plaintext` resolves direction from the content's
    own first strong character, which is what user-supplied text requires.

    Asserted on the template rather than the render because the defect is a
    styling rule; a DOM assertion cannot see whether the rule is applied.
    """
    from pathlib import Path

    landing = Path(__file__).resolve().parent.parent / "templates" / "landing"

    for name in ("partners.html", "partner_detail.html"):
        src = (landing / name).read_text(encoding="utf-8")
        assert "unicode-bidi: plaintext" in src, (
            f"landing/{name} declares no bidi isolation rule"
        )

    partners = (landing / "partners.html").read_text(encoding="utf-8")
    assert 'class="desc bidi-auto"' in partners, (
        "partner descriptions are not isolated — an Arabic description on the "
        "English page will scramble its punctuation"
    )
    # display_name, not company_name: the card picks the Arabic or the Latin
    # name by active language, so the isolation has to wrap whichever it
    # resolves to. Pinning the field name keeps this from silently drifting
    # onto a raw, unisolated value.
    assert '<h2 class="bidi-auto">{{ partner.display_name }}</h2>' in partners

    detail = (landing / "partner_detail.html").read_text(encoding="utf-8")
    # display_* rather than the raw columns: the page resolves name and
    # description by active language, so the isolation must wrap the resolved
    # value. Pinning the exact expression keeps a future edit from dropping the
    # class while the page still looks right in whichever language was tested.
    for needle in ('<h1 class="bidi-auto">',
                   'class="bidi-auto">{{ partner_public.display_long_description }}'):
        assert needle in detail, f"partner_detail.html missing isolation: {needle}"

    # Both directions matter here, and the reason is asymmetric: an Arabic name
    # inside an English page scrambles its punctuation, and a Latin name inside
    # an Arabic page does the same in reverse. Neither is visible unless the
    # tester happens to read the language they did not write the test in.
    assert 'class="bidi-auto">{{ partner_public.display_short_description }}' in detail \
        or 'bidi-auto"' in detail.split("display_short_description")[0][-200:], (
        "the short description is rendered without bidi isolation"
    )
