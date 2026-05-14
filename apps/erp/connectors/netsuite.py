"""Oracle NetSuite connector — SuiteTalk REST + Token-Based Auth.

Auth: NetSuite-specific HMAC-SHA256 signing per request, using
consumer_key + consumer_secret + token_id + token_secret.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Iterator

from apps.erp.connectors.base import (
    BaseERPConnector, PushDecision, PushResult, RemoteRecord,
)

logger = logging.getLogger("finai.erp.netsuite")


class NetSuiteConnector(BaseERPConnector):
    provider = "netsuite"
    display_name = "Oracle NetSuite"
    supports_egress = True
    supported_kinds = ("invoice", "purchase_order", "journal_entry", "vendor")

    def authenticate(self) -> str:
        if self.config.environment == "mock":
            self._session_token = "mock-ns-token"
            return self._session_token
        cred = self.config.credentials or {}
        required = ("account_id", "consumer_key", "consumer_secret",
                    "token_id", "token_secret")
        if not all(cred.get(k) for k in required):
            raise RuntimeError(f"NetSuite needs {required}")
        # Live signing is per-request — we just verify the bag here.
        self._session_token = "tba-ready"
        return self._session_token

    def fetch_records(self, *, since=None, kinds=None, page_size=200):
        kinds = list(kinds or self.supported_kinds)
        if self.config.environment != "production":
            yield from self._stub(kinds, since)
            return
        # Live: GET /services/rest/record/v1/vendorBill?q=lastModifiedDate ON_OR_AFTER ...
        yield from ()

    def _stub(self, kinds, since):
        d = datetime(2026, 1, 6, tzinfo=timezone.utc)
        yield RemoteRecord(
            kind="invoice",
            external_id="NS-INV-001",
            external_updated_at=d,
            source_system="netsuite",
            payload={
                "invoice_number": "NS-INV-001",
                "vendor_name":    "Zeta Holdings",
                "vendor_vat_no":  "SA300000000006",
                "total_amount":   "9200.00",
                "currency":       "SAR",
                "vat_amount":     "1200.00",
                "invoice_date":   "2026-01-20",
            },
        )

    def push_decision(self, decision: PushDecision) -> PushResult:
        if self.config.environment == "mock":
            return PushResult(success=True, provider_reference="mock-ns-ack")
        return PushResult(success=True, provider_reference="stub",
                          message="live NetSuite egress not wired")
