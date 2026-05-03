"""
ZATCA Fatoora API client.

End-to-end live integration requires:

  • a registered EGS device (one-time onboarding via `compliance/csids` for the
    sandbox CSID, then `production/csids` for the real one)
  • Basic-Auth header where username = base64(certificate) and password =
    decrypted CSID secret
  • per-environment base URL

This client implements all of the request shaping. When ``ZATCA_LIVE_MODE``
is False (the default in dev / CI), every method short-circuits to a
recorded mock response so we can exercise the dashboard, persistence, and
rejection-code paths without needing a Fatoora portal account.

Reference:
  https://zatca.gov.sa/en/E-Invoicing/SystemsDevelopers/
"""

from __future__ import annotations

import base64
import logging
import uuid
from dataclasses import dataclass, field
from typing import Optional

from django.conf import settings

logger = logging.getLogger("finai.zatca")


_BASE_URLS = {
    "sandbox":    "https://gw-fatoora.zatca.gov.sa/e-invoicing/developer-portal",
    "simulation": "https://gw-fatoora.zatca.gov.sa/e-invoicing/simulation",
    "production": "https://gw-fatoora.zatca.gov.sa/e-invoicing/core",
}


@dataclass
class ZATCAResponse:
    """Normalised response — both real Fatoora calls and mock paths return this."""
    ok:        bool
    status:    str = ""
    code:      str = ""
    cleared_xml: str = ""
    warnings:  list = field(default_factory=list)
    errors:    list = field(default_factory=list)
    raw:       dict = field(default_factory=dict)
    http_status: int = 0

    def to_dict(self) -> dict:
        return {
            "ok":          self.ok,
            "status":      self.status,
            "code":        self.code,
            "warnings":    self.warnings,
            "errors":      self.errors,
            "http_status": self.http_status,
        }


class ZATCAClient:
    """Stateless wrapper around the Fatoora REST endpoints."""

    def __init__(self, *, environment: str = "sandbox",
                 certificate_pem: Optional[bytes] = None,
                 csid_secret: Optional[bytes] = None,
                 timeout: int = 30):
        self.environment = environment if environment in _BASE_URLS else "sandbox"
        self.base_url    = _BASE_URLS[self.environment]
        self.cert_pem    = certificate_pem or b""
        self.csid_secret = csid_secret or b""
        self.timeout     = timeout

    # ── Auth ────────────────────────────────────────────────────────────────

    def _auth_header(self) -> dict:
        if not (self.cert_pem and self.csid_secret):
            return {}
        username = base64.b64encode(self.cert_pem).decode("ascii")
        password = self.csid_secret.decode("ascii") if isinstance(self.csid_secret, bytes) else str(self.csid_secret)
        token = base64.b64encode(f"{username}:{password}".encode("utf-8")).decode("ascii")
        return {"Authorization": f"Basic {token}"}

    # ── Onboarding ──────────────────────────────────────────────────────────

    def request_compliance_csid(self, csr_pem: bytes, *, otp: str) -> ZATCAResponse:
        """Submit the CSR to ``/compliance` to get a sandbox-scoped CSID
        signed by the ZATCA Compliance CA."""
        return self._post_or_mock(
            path="/compliance",
            payload={"csr": base64.b64encode(csr_pem).decode("ascii")},
            extra_headers={"OTP": otp},
            mock=lambda: ZATCAResponse(
                ok=True, status="sandbox_csid_issued", http_status=200,
                raw={
                    "binarySecurityToken": base64.b64encode(b"-----BEGIN CERTIFICATE-----\nMOCK\n-----END CERTIFICATE-----").decode("ascii"),
                    "secret":              "MOCK_CSID_SECRET_" + uuid.uuid4().hex[:12],
                    "requestID":           uuid.uuid4().hex,
                },
            ),
        )

    def request_production_csid(self, compliance_request_id: str) -> ZATCAResponse:
        """After the 24 sandbox tests pass, exchange the compliance request id
        for a Production CSID (the real cert)."""
        return self._post_or_mock(
            path="/production/csids",
            payload={"compliance_request_id": compliance_request_id},
            mock=lambda: ZATCAResponse(
                ok=True, status="production_csid_issued", http_status=200,
                raw={
                    "binarySecurityToken": base64.b64encode(b"-----BEGIN CERTIFICATE-----\nMOCK_PROD\n-----END CERTIFICATE-----").decode("ascii"),
                    "secret": "MOCK_PROD_SECRET_" + uuid.uuid4().hex[:12],
                },
            ),
        )

    # ── Submission ──────────────────────────────────────────────────────────

    def clear_invoice(self, *, signed_xml: str,
                      invoice_uuid: str, invoice_hash: str) -> ZATCAResponse:
        """B2B clearance — synchronous. ZATCA returns the cleared XML on success."""
        return self._post_or_mock(
            path="/invoices/clearance/single",
            payload={
                "invoiceHash": invoice_hash,
                "uuid":        str(invoice_uuid),
                "invoice":     base64.b64encode(signed_xml.encode("utf-8")).decode("ascii"),
            },
            extra_headers={"Clearance-Status": "1"},
            mock=lambda: ZATCAResponse(
                ok=True, status="cleared", http_status=200,
                cleared_xml=signed_xml,    # fake "echo cleared" for previews
                code="CLEARED",
                raw={"clearanceStatus": "CLEARED",
                     "clearedInvoice":  base64.b64encode(signed_xml.encode("utf-8")).decode("ascii")},
            ),
        )

    def report_invoice(self, *, signed_xml: str,
                       invoice_uuid: str, invoice_hash: str) -> ZATCAResponse:
        """B2C reporting — asynchronous. Acknowledged immediately, validated later."""
        return self._post_or_mock(
            path="/invoices/reporting/single",
            payload={
                "invoiceHash": invoice_hash,
                "uuid":        str(invoice_uuid),
                "invoice":     base64.b64encode(signed_xml.encode("utf-8")).decode("ascii"),
            },
            mock=lambda: ZATCAResponse(
                ok=True, status="reported", http_status=200,
                code="REPORTED",
                raw={"reportingStatus": "REPORTED"},
            ),
        )

    # ── Internals ───────────────────────────────────────────────────────────

    def _post_or_mock(self, *, path: str, payload: dict,
                      extra_headers: Optional[dict] = None,
                      mock=None) -> ZATCAResponse:
        live = bool(getattr(settings, "ZATCA_LIVE_MODE", False))
        if not live:
            logger.info("[zatca.client.mock] %s %s", self.environment, path)
            return mock() if callable(mock) else ZATCAResponse(ok=True, status="mock")

        try:
            import requests
            url = self.base_url.rstrip("/") + path
            headers = {"Content-Type": "application/json", "Accept-Version": "V2",
                       **(extra_headers or {}), **self._auth_header()}
            r = requests.post(url, json=payload, headers=headers, timeout=self.timeout)
            data = {}
            try:
                data = r.json()
            except Exception:
                data = {"raw": r.text[:1000]}
            return self._parse(r.status_code, data)
        except ImportError:
            return ZATCAResponse(ok=False, status="error",
                                 errors=[{"code": "REQUESTS_MISSING",
                                          "message": "requests library required for live mode"}])
        except Exception as exc:
            logger.exception("[zatca.client] %s failed", path)
            return ZATCAResponse(ok=False, status="error",
                                 errors=[{"code": "TRANSPORT_ERROR",
                                          "message": str(exc)[:240]}])

    def _parse(self, http_status: int, data: dict) -> ZATCAResponse:
        validation_results = data.get("validationResults", {}) or {}
        warnings = validation_results.get("warningMessages", []) or []
        errors   = validation_results.get("errorMessages", [])   or []

        is_cleared  = (data.get("clearanceStatus")  in {"CLEARED", "CLEARED_WITH_WARNINGS"}
                       or http_status in (200, 202)) and not errors
        is_reported = (data.get("reportingStatus") in {"REPORTED", "REPORTED_WITH_WARNINGS"}) \
                      and not errors

        cleared_xml = ""
        if data.get("clearedInvoice"):
            try:
                cleared_xml = base64.b64decode(data["clearedInvoice"]).decode("utf-8")
            except Exception:
                pass

        ok = (is_cleared or is_reported) and (http_status < 400) and not errors
        if errors:
            status = "rejected"
            code = errors[0].get("code", "REJECTED") if isinstance(errors[0], dict) else "REJECTED"
        elif warnings and ok:
            status = "warning"
            code = "WARNINGS"
        elif is_cleared:
            status, code = "cleared", "CLEARED"
        elif is_reported:
            status, code = "reported", "REPORTED"
        else:
            status, code = "error", f"HTTP_{http_status}"

        return ZATCAResponse(
            ok=ok, status=status, code=code,
            cleared_xml=cleared_xml,
            warnings=warnings, errors=errors, raw=data,
            http_status=http_status,
        )
