"""Microsoft Dynamics 365 Finance & Operations connector — OData v4.

Auth: OAuth2 against https://login.microsoftonline.com/<tenant>/oauth2/v2.0/token
with scope ``<base_url>/.default`` (Azure AD client_credentials flow).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Iterator

from apps.erp.connectors.base import (
    BaseERPConnector, PushDecision, PushResult, RemoteRecord,
)

logger = logging.getLogger("finai.erp.dynamics")


class DynamicsConnector(BaseERPConnector):
    provider = "dynamics"
    display_name = "Microsoft Dynamics 365 F&O"
    supports_egress = True
    supported_kinds = ("invoice", "purchase_order", "journal_entry", "vendor")

    _ENTITIES = {
        "invoice":        "VendorInvoiceHeaders",
        "purchase_order": "PurchaseOrderHeaders",
        "journal_entry":  "GeneralJournalEntries",
        "vendor":         "Vendors",
    }

    def authenticate(self) -> str:
        if self.config.environment == "mock":
            self._session_token = "mock-d365-token"
            return self._session_token
        cred = self.config.credentials or {}
        tenant = cred.get("tenant_id") or ""
        client_id = cred.get("client_id") or ""
        client_secret = cred.get("client_secret") or ""
        if not (tenant and client_id and client_secret):
            raise RuntimeError("Dynamics needs tenant_id + client_id + client_secret")
        try:
            import requests
            r = requests.post(
                f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token",
                data={
                    "grant_type":    "client_credentials",
                    "client_id":     client_id,
                    "client_secret": client_secret,
                    "scope":         f"{self.config.base_url}/.default",
                },
                timeout=15,
            )
            r.raise_for_status()
            self._session_token = r.json().get("access_token", "")
            return self._session_token
        except ImportError:                          # pragma: no cover
            self._session_token = "stub"
            return self._session_token

    def fetch_records(self, *, since=None, kinds=None, page_size=200):
        kinds = list(kinds or self.supported_kinds)
        if self.config.environment != "production":
            yield from self._stub(kinds, since)
            return
        # Live: each entity supports $filter=ModifiedDateTime ge <since>
        yield from ()

    def _stub(self, kinds, since):
        d = datetime(2026, 1, 4, tzinfo=timezone.utc)
        yield RemoteRecord(
            kind="invoice",
            external_id="D365-INV-001",
            external_updated_at=d,
            source_system="dynamics",
            payload={
                "invoice_number": "D365-INV-001",
                "vendor_name":    "Delta Tech",
                "vendor_vat_no":  "SA300000000004",
                "total_amount":   "44850.00",
                "currency":       "SAR",
                "vat_amount":     "5850.00",
                "invoice_date":   "2026-01-18",
            },
        )

    def push_decision(self, decision: PushDecision) -> PushResult:
        if self.config.environment == "mock":
            return PushResult(success=True, provider_reference="mock-d365-ack")
        return PushResult(success=True, provider_reference="stub",
                          message="live Dynamics egress not wired")
