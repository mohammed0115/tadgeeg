"""QuickBooks Online connector — Intuit API v3.

Auth: OAuth2 (Intuit's Account Sciences flow).
Base: https://quickbooks.api.intuit.com/v3/company/<realm_id>/
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Iterator

from apps.erp.connectors.base import (
    BaseERPConnector, PushDecision, PushResult, RemoteRecord,
)

logger = logging.getLogger("finai.erp.quickbooks")


class QuickBooksConnector(BaseERPConnector):
    provider = "quickbooks"
    display_name = "QuickBooks Online"
    supports_egress = False                  # QBO has limited writeback for approvals
    supported_kinds = ("invoice", "purchase_order", "journal_entry", "vendor")

    def authenticate(self) -> str:
        if self.config.environment == "mock":
            self._session_token = "mock-qbo-token"
            return self._session_token
        cred = self.config.credentials or {}
        token = cred.get("access_token")
        if not token:
            raise RuntimeError("QuickBooks needs access_token from the Intuit OAuth dance")
        self._session_token = token
        return token

    def fetch_records(self, *, since=None, kinds=None, page_size=200):
        kinds = list(kinds or self.supported_kinds)
        if self.config.environment != "production":
            yield from self._stub(kinds, since)
            return
        # Live: /v3/company/<realm>/query?query=SELECT * FROM Bill WHERE MetaData.LastUpdatedTime>='<since>'
        yield from ()

    def _stub(self, kinds, since):
        d = datetime(2026, 1, 5, tzinfo=timezone.utc)
        yield RemoteRecord(
            kind="invoice",
            external_id="QBO-INV-001",
            external_updated_at=d,
            source_system="quickbooks",
            payload={
                "invoice_number": "QBO-INV-001",
                "vendor_name":    "Epsilon Supplies",
                "vendor_vat_no":  "SA300000000005",
                "total_amount":   "1725.00",
                "currency":       "SAR",
                "vat_amount":     "225.00",
                "invoice_date":   "2026-01-19",
            },
        )
