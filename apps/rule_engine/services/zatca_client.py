"""
ZATCA E-invoicing API client (CSID issuance + Compliance + Production).

Production endpoint:
    https://gw-fatoora.zatca.gov.sa/e-invoicing/core
Simulation endpoint:
    https://gw-fatoora.zatca.gov.sa/e-invoicing/simulation
Developer endpoint:
    https://gw-fatoora.zatca.gov.sa/e-invoicing/developer-portal

All flows ZATCA exposes:
    POST /compliance              — issue CCSID (compliance CSID) using OTP
    POST /compliance/invoices     — submit a sample invoice for compliance check
    POST /production/csids        — exchange CCSID + signed payload for PCSID
    POST /invoices/reporting/single   — submit a Standard invoice
    POST /invoices/clearance/single   — submit a Simplified invoice for clearance

This module wraps the HTTP plumbing. The actual onboarding wizard (UI for
generating CSR + entering OTP) is a separate job; this code is what that
wizard will call. All methods return ``{"ok": bool, "data": ..., "error": ...}``
so callers don't have to catch HTTPError everywhere.
"""
from __future__ import annotations

import base64
import json
import logging
from urllib import error as _err
from urllib import request as _req

logger = logging.getLogger("finai")

ENDPOINTS = {
    "production":  "https://gw-fatoora.zatca.gov.sa/e-invoicing/core",
    "simulation":  "https://gw-fatoora.zatca.gov.sa/e-invoicing/simulation",
    "sandbox":     "https://gw-fatoora.zatca.gov.sa/e-invoicing/developer-portal",
}


class ZATCAClientError(RuntimeError):
    pass


class ZATCAClient:
    """Stateful client — instantiate once per organization with their CSID."""

    def __init__(self, environment: str = "sandbox", csid: str | None = None,
                 secret: str | None = None, timeout: float = 12.0):
        if environment not in ENDPOINTS:
            raise ValueError(f"unknown environment {environment!r}")
        self.base_url = ENDPOINTS[environment]
        self.environment = environment
        self.csid = csid
        self.secret = secret
        self.timeout = timeout

    # ── Authentication header ────────────────────────────────────────────────

    def _auth_header(self) -> dict:
        if not (self.csid and self.secret):
            return {}
        token = base64.b64encode(f"{self.csid}:{self.secret}".encode("utf-8")).decode()
        return {"Authorization": f"Basic {token}"}

    # ── Low-level HTTP ───────────────────────────────────────────────────────

    def _request(self, path: str, payload: dict | None = None,
                 method: str = "POST", extra_headers: dict | None = None) -> dict:
        url = self.base_url.rstrip("/") + "/" + path.lstrip("/")
        body = json.dumps(payload or {}).encode("utf-8") if payload is not None else None
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Accept-Version": "V2",
            "Accept-Language": "en",
            **self._auth_header(),
            **(extra_headers or {}),
        }
        req = _req.Request(url, data=body, headers=headers, method=method)
        try:
            with _req.urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read()
                try:
                    return {"ok": True, "status": resp.status, "data": json.loads(raw)}
                except json.JSONDecodeError:
                    return {"ok": True, "status": resp.status, "data": raw.decode("utf-8", errors="replace")}
        except _err.HTTPError as e:
            try:
                err_body = json.loads(e.read())
            except Exception:
                err_body = None
            return {"ok": False, "status": e.code, "error": err_body or str(e)}
        except Exception as exc:
            return {"ok": False, "status": 0, "error": str(exc)[:200]}

    # ── Onboarding flows ─────────────────────────────────────────────────────

    def request_compliance_csid(self, csr_b64: str, otp: str) -> dict:
        """Step 1: exchange CSR + ZATCA portal OTP for a CCSID.

        Returns ``{"ok": True, "data": {"binarySecurityToken": "...", "secret": "..."}}``
        on success. The merchant stores those for subsequent compliance calls.
        """
        return self._request(
            "/compliance",
            payload={"csr": csr_b64},
            extra_headers={"OTP": otp},
        )

    def submit_compliance_invoice(self, signed_invoice_b64: str,
                                  invoice_hash: str, uuid: str) -> dict:
        """Step 2: submit a sample signed invoice during compliance phase."""
        return self._request("/compliance/invoices", payload={
            "invoice":     signed_invoice_b64,
            "invoiceHash": invoice_hash,
            "uuid":        uuid,
        })

    def upgrade_to_production_csid(self, compliance_request_id: str) -> dict:
        """Step 3: after passing compliance, exchange for the production CSID."""
        return self._request("/production/csids", payload={
            "compliance_request_id": compliance_request_id,
        })

    # ── Reporting / clearance ────────────────────────────────────────────────

    def report_standard_invoice(self, signed_invoice_b64: str,
                                 invoice_hash: str, uuid: str) -> dict:
        """Reporting flow — Standard (B2B) tax invoices."""
        return self._request("/invoices/reporting/single", payload={
            "invoice":     signed_invoice_b64,
            "invoiceHash": invoice_hash,
            "uuid":        uuid,
        })

    def clear_simplified_invoice(self, signed_invoice_b64: str,
                                  invoice_hash: str, uuid: str) -> dict:
        """Clearance flow — Simplified (B2C) invoices, must be cleared BEFORE issuance."""
        return self._request("/invoices/clearance/single", payload={
            "invoice":     signed_invoice_b64,
            "invoiceHash": invoice_hash,
            "uuid":        uuid,
        })


def generate_csr(common_name: str, organization: str, country: str = "SA",
                 city: str = "Riyadh") -> tuple[str, str]:
    """Generate a P-256 keypair + CSR suitable for the CSID issuance call.

    Returns ``(csr_pem, private_key_pem)`` — the caller stores the private key
    locally (never sent to ZATCA) and base64-encodes the CSR for transmission.
    Requires the ``cryptography`` package.
    """
    from cryptography import x509
    from cryptography.x509.oid import NameOID
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec

    private_key = ec.generate_private_key(ec.SECP256R1())
    csr = (
        x509.CertificateSigningRequestBuilder()
        .subject_name(x509.Name([
            x509.NameAttribute(NameOID.COMMON_NAME, common_name),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, organization),
            x509.NameAttribute(NameOID.COUNTRY_NAME, country),
            x509.NameAttribute(NameOID.LOCALITY_NAME, city),
        ]))
        .sign(private_key, hashes.SHA256())
    )
    csr_pem = csr.public_bytes(serialization.Encoding.PEM).decode("ascii")
    key_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("ascii")
    return csr_pem, key_pem
