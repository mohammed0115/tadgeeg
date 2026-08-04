"""Pinned versions that a known CVE has already been published against.

`pip-audit` reported 42 vulnerabilities across 9 packages on 2026-08-02. Four
of them mattered to this product specifically rather than generically:

  · **PyJWT** (8) — this is the authentication path (core/utils/jwt_cookie_auth.py)
  · **cryptography** (1) — Fernet, which encrypts the banking and ZATCA fields
  · **pillow** (20) — reached by every user-uploaded document via OCR
  · **urllib3** (3) — the outbound HTTP client, including the payment gateway

The lock file now pins fixed versions. This file stops them drifting back and
records the one finding that was investigated and found not to apply, so nobody
has to re-derive that conclusion from a scanner report.

This is not a substitute for running pip-audit in CI. It is a floor: the four
packages whose CVEs were read, understood, and fixed cannot silently regress.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
LOCK = REPO / "requirements.lock.txt"

#: package → the version that first carried the fix. Anything lower is a known
#: vulnerable build, not a matter of taste.
MINIMUM_SAFE = {
    "pillow": (12, 3, 0),        # PYSEC-2026-2253 and 19 others
    "PyJWT": (2, 13, 0),         # PYSEC-2026-175/177/178/179 and 4 others
    "pyasn1": (0, 6, 4),         # PYSEC-2026-3455/3456/3457
    "urllib3": (2, 7, 0),        # PYSEC-2026-141/142
    "idna": (3, 15),             # PYSEC-2026-215
    "msgpack": (1, 2, 1),        # GHSA-6v7p-g79w-8964
    "cryptography": (48, 0, 1),  # GHSA-537c-gmf6-5ccf
}


def _pinned():
    versions = {}
    for line in LOCK.read_text(encoding="utf-8").splitlines():
        match = re.match(r"^([A-Za-z0-9_.\-]+)==([0-9][^\s;#]*)", line.strip())
        if match:
            versions[match.group(1).lower()] = match.group(2)
    return versions


def _tuple(version):
    parts = []
    for piece in version.split("."):
        digits = re.match(r"\d+", piece)
        if not digits:
            break
        parts.append(int(digits.group()))
    return tuple(parts)


def test_no_package_is_pinned_to_a_known_vulnerable_version():
    pinned = _pinned()
    behind = []
    for name, minimum in MINIMUM_SAFE.items():
        current = pinned.get(name.lower())
        if current is None:
            behind.append(f"{name} is not pinned at all — add it to the lock file")
            continue
        if _tuple(current)[: len(minimum)] < minimum:
            behind.append(
                f"{name}=={current} is below the fixed "
                f"{'.'.join(map(str, minimum))}"
            )
    assert not behind, "known-vulnerable pins:\n  " + "\n  ".join(behind)


def test_cryptography_is_pinned_because_fernet_protects_customer_data():
    """It was used but unpinned, so any environment could resolve any version.

    Fernet encrypts the banking and ZATCA fields; the version that performs
    that encryption is not something to leave to whatever pip resolves on the
    day a container is rebuilt.
    """
    assert "cryptography" in _pinned()


def test_weasyprint_css_injection_does_not_apply_here():
    """PYSEC-2026-3412 has no fixed release, so the exposure was checked instead.

    The issue needs `presentational_hints=True`; WeasyPrint's default is False
    and none of the four call sites passes it. If a call site ever enables
    them, this fails and the finding has to be re-assessed rather than
    rediscovered from a scanner report months later.
    """
    call_sites = [
        "apps/reports/views.py",
        "apps/leads/trial_exports.py",
        "apps/audit/services/audit_readiness_export.py",
        "apps/partners/exports.py",
    ]
    enabling = []
    for relpath in call_sites:
        path = REPO / relpath
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        if re.search(r"presentational_hints\s*=\s*True", text):
            enabling.append(relpath)
    assert not enabling, (
        "PYSEC-2026-3412 (WeasyPrint CSS injection) becomes exploitable once "
        "presentational hints are on, and there is no fixed release:\n  "
        + "\n  ".join(enabling)
    )


def test_the_pdf_call_sites_are_the_ones_this_file_claims_to_cover():
    """A call site added elsewhere would sit outside the check above."""
    found = set()
    for pattern in ("apps/**/*.py", "core/**/*.py"):
        for path in REPO.glob(pattern):
            if "/tests/" in str(path) or "/migrations/" in str(path):
                continue
            if re.search(r"\bHTML\(string=", path.read_text(encoding="utf-8")):
                found.add(str(path.relative_to(REPO)))
    known = {
        "apps/reports/views.py",
        "apps/leads/trial_exports.py",
        "apps/audit/services/audit_readiness_export.py",
        "apps/partners/exports.py",
    }
    assert found <= known, (
        f"new WeasyPrint call site(s) not covered by the check above: "
        f"{sorted(found - known)}"
    )
