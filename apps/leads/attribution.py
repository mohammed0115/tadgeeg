"""Auto-capture of trial-registration metadata (§A.4), bounded by §N privacy.

Everything here is deliberately *lossy*. Each helper reduces a rich request
artefact to the smallest value that answers the question we actually have:

* full Referer URL      → host only          ("where did they come from")
* full query string     → utm_source value   ("which campaign")
* full User-Agent       → one of four labels ("what device class")

The reduction happens at capture time, not at display time, so the discarded
detail is never written to the database in the first place. That is what §N
means by data minimisation — not "store it and hide it".

No external service is contacted. In particular there is NO IP geolocation
lookup: §N forbids it until a policy exists, and the country we care about is
the one the registrant selected, which is more reliable anyway.
"""

from __future__ import annotations

from urllib.parse import urlparse

from django.utils.translation import get_language

from core.utils.coerce import get_client_ip


#: Session key holding campaign attribution captured on an earlier page view.
#: A visitor typically lands on "/" or "/pricing/" carrying utm parameters and
#: only reaches "/register/" several clicks later, by which point the query
#: string is long gone — so it is stashed on first sight.
CAMPAIGN_SESSION_KEY = "_lead_campaign"

#: Query parameters we read, in priority order.
_CAMPAIGN_PARAMS = ("utm_source", "utm_campaign", "ref")

_MAX_LEN = 100


def _truncate(value: str) -> str:
    return (value or "").strip()[:_MAX_LEN]


def detect_device_type(user_agent: str) -> str:
    """Coarse device class from a User-Agent string.

    Four buckets, matching TrialLeadProfile.DeviceType. Intentionally naive:
    this feeds a marketing pie chart, not a security control, so a wrong guess
    costs nothing and a UA-parsing dependency would not earn its keep.
    Order matters — iPad advertises itself as Macintosh-like, and most Android
    tablets still say "Android", so tablet is tested before mobile.
    """
    ua = (user_agent or "").lower()
    if not ua:
        return "unknown"
    if "ipad" in ua or ("android" in ua and "mobile" not in ua) or "tablet" in ua:
        return "tablet"
    if any(token in ua for token in ("mobi", "iphone", "ipod", "android", "windows phone")):
        return "mobile"
    if any(token in ua for token in ("mozilla", "chrome", "safari", "firefox", "edge", "opera")):
        return "desktop"
    return "unknown"


def extract_referral_host(request) -> str:
    """Referring host only — never the full URL.

    A full Referer can carry search terms, session identifiers, or another
    site's private path. The host answers "which channel sent them", which is
    the whole question. Self-referrals are dropped: internal navigation is not
    acquisition data.
    """
    referer = request.META.get("HTTP_REFERER", "")
    if not referer:
        return ""
    try:
        host = (urlparse(referer).hostname or "").lower()
    except ValueError:
        return ""
    if not host:
        return ""
    if host == (request.get_host() or "").split(":")[0].lower():
        return ""
    return _truncate(host)


def remember_campaign(request) -> None:
    """Stash campaign attribution on first sight, if any.

    Called from the shared public-page context builder, so it runs on the
    landing page, pricing, and the auth portal alike. First value wins: an
    early touch is the acquisition source; later internal navigation must not
    overwrite it.
    """
    if not hasattr(request, "session"):
        return
    if request.session.get(CAMPAIGN_SESSION_KEY):
        return
    for param in _CAMPAIGN_PARAMS:
        value = request.GET.get(param)
        if value:
            request.session[CAMPAIGN_SESSION_KEY] = _truncate(value)
            request.session.modified = True
            return


def build_capture(request) -> dict:
    """Return the auto-captured block for a TrialLeadProfile.

    Never raises: a registration must not fail because a header was odd. Any
    field we cannot determine is simply blank.
    """
    if request is None:
        return {}

    campaign = ""
    if hasattr(request, "session"):
        campaign = _truncate(request.session.get(CAMPAIGN_SESSION_KEY, ""))
    if not campaign:
        # Direct hit on /register/ carrying the parameters.
        for param in _CAMPAIGN_PARAMS:
            if request.GET.get(param):
                campaign = _truncate(request.GET[param])
                break

    return {
        "registered_ip": get_client_ip(request) or None,
        "device_type": detect_device_type(request.META.get("HTTP_USER_AGENT", "")),
        "language": (get_language() or "")[:10],
        "referral_source": extract_referral_host(request),
        "campaign_source": campaign,
    }
