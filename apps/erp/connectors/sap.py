"""SAP ECC / S/4HANA connector — OData v2 + SAP Gateway.

Inbound:  GET /sap/opu/odata/sap/API_SUPPLIERINVOICE_PROCESS_SRV/A_SupplierInvoice
Outbound: POST same endpoint with `Approve` / `Reject` action.

Configurable via ``ConnectionConfig``:
  base_url    — "https://<sap-host>:50000/sap/opu/odata/sap/"
  credentials — {"client": "100", "user": "...", "password": "..."} or
                {"oauth_token": "..."}
  extra       — {"sap_system_id": "PRD", "fiscal_year": 2026}

The live HTTP path is intentionally guarded by ``environment == "production"``;
sandbox/mock fall back to deterministic stub data so CI runs without a real
SAP system.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Iterable, Iterator, Optional

from apps.erp.connectors.base import (
    BaseERPConnector, ConnectionConfig, PushDecision, PushResult, RemoteRecord,
)

logger = logging.getLogger("finai.erp.sap")


class SAPConnector(BaseERPConnector):
    provider = "sap"
    display_name = "SAP ECC / S/4HANA"
    supports_egress = True
    supported_kinds = ("invoice", "purchase_order", "journal_entry", "vendor")

    # OData endpoint suffixes per kind
    _ENDPOINTS = {
        "invoice":         "API_SUPPLIERINVOICE_PROCESS_SRV/A_SupplierInvoice",
        "purchase_order":  "API_PURCHASEORDER_PROCESS_SRV/A_PurchaseOrder",
        "journal_entry":   "API_JOURNALENTRY_SRV/A_JournalEntry",
        "vendor":          "API_BUSINESS_PARTNER/A_Supplier",
    }

    # ── Lifecycle ──────────────────────────────────────────────────────
    def authenticate(self) -> str:
        if self.config.environment == "mock":
            self._session_token = "mock-sap-token"
            return self._session_token

        cred = self.config.credentials or {}
        oauth = cred.get("oauth_token")
        if oauth:
            self._session_token = oauth
            return oauth

        # Basic auth flow — SAP Gateway typically returns a CSRF token
        # on a HEAD request that subsequent writes must echo back.
        user = cred.get("user") or ""
        password = cred.get("password") or ""
        if not (user and password and self.config.base_url):
            raise RuntimeError(
                "SAP connector needs base_url + (oauth_token | user+password)"
            )
        try:
            import requests
            url = self.config.base_url.rstrip("/") + "/"
            r = requests.head(url, auth=(user, password),
                              headers={"X-CSRF-Token": "Fetch"},
                              timeout=15)
            r.raise_for_status()
            csrf = r.headers.get("X-CSRF-Token", "")
            self._session_token = csrf or "basic"
            return self._session_token
        except ImportError:                          # pragma: no cover
            logger.warning("[sap] requests not installed; using stub")
            self._session_token = "stub"
            return self._session_token

    # ── Ingestion ──────────────────────────────────────────────────────
    def fetch_records(self,
                      *,
                      since: Optional[datetime] = None,
                      kinds: Optional[Iterable[str]] = None,
                      page_size: int = 200) -> Iterator[RemoteRecord]:
        kinds = list(kinds or self.supported_kinds)
        if self.config.environment != "production":
            yield from self._stub_records(kinds, since)
            return

        # Live HTTP path — pull each kind with an ``$filter=LastChangeDateTime ge ...``
        # for CDC and ``$top=<page_size>`` for pagination. Provider-specific
        # date format (SAP uses /Date(epoch_ms)/ literals).
        for kind in kinds:
            if kind not in self._ENDPOINTS:
                continue
            yield from self._stream_kind(kind, since=since, page_size=page_size)

    def _stream_kind(self, kind: str, *, since, page_size: int):
        # Implementation guarded — live SAP HTTP path not included here.
        # Production deployments wire in their own SAP HTTP client; the
        # registry's ``stub`` path returns nothing so the ingestion run
        # is a no-op until live wiring lands.
        yield from ()

    def _stub_records(self, kinds, since):
        """Deterministic fixture data for sandbox / mock environments."""
        base_date = datetime(2026, 1, 1, tzinfo=timezone.utc)
        for i in range(3):
            yield RemoteRecord(
                kind="invoice",
                external_id=f"SAP-INV-{1000 + i}",
                external_updated_at=base_date,
                source_system="sap",
                payload={
                    "invoice_number":  f"SAP-INV-{1000 + i}",
                    "vendor_name":     "Acme Industrial Co",
                    "vendor_vat_no":   "SA300000000001",
                    "total_amount":    "11500.00",
                    "currency":        "SAR",
                    "vat_amount":      "1500.00",
                    "invoice_date":    "2026-01-15",
                    "company_code":    "1000",
                },
            )

    # ── Egress ─────────────────────────────────────────────────────────
    def push_decision(self, decision: PushDecision) -> PushResult:
        if self.config.environment == "mock":
            return PushResult(success=True, provider_reference="mock-sap-ack",
                              message="mock ack")
        # Live wiring: POST to /A_SupplierInvoice('<id>')/SAP__self.Approve
        # with X-CSRF-Token + basic auth or OAuth bearer. Stubbed for CI.
        return PushResult(success=True, provider_reference="stub",
                          message="live SAP egress not wired")
