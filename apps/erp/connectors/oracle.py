"""Oracle Fusion / Oracle Financials Cloud connector — REST API.

Endpoint family: /fscmRestApi/resources/<version>/...
Auth: OAuth2 client_credentials (preferred) or HTTP Basic + JWT.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Iterable, Iterator, Optional

from apps.erp.connectors.base import (
    BaseERPConnector, PushDecision, PushResult, RemoteRecord,
)

logger = logging.getLogger("finai.erp.oracle")


class OracleConnector(BaseERPConnector):
    provider = "oracle"
    display_name = "Oracle Fusion Cloud"
    supports_egress = True
    supported_kinds = ("invoice", "purchase_order", "journal_entry", "vendor")

    _ENDPOINTS = {
        "invoice":        "invoices",
        "purchase_order": "purchaseOrders",
        "journal_entry":  "journalEntries",
        "vendor":         "suppliers",
    }

    def authenticate(self) -> str:
        if self.config.environment == "mock":
            self._session_token = "mock-oracle-token"
            return self._session_token
        cred = self.config.credentials or {}
        if cred.get("oauth_token"):
            self._session_token = cred["oauth_token"]
            return self._session_token
        client_id = cred.get("client_id") or ""
        client_secret = cred.get("client_secret") or ""
        if not (client_id and client_secret):
            raise RuntimeError("Oracle connector needs client_id + client_secret")
        try:
            import requests
            r = requests.post(
                f"{self.config.base_url.rstrip('/')}/oauth2/v1/token",
                data={"grant_type": "client_credentials"},
                auth=(client_id, client_secret),
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
        # Live: each endpoint supports ?q=LastUpdateDate>=:since
        for kind in kinds:
            if kind not in self._ENDPOINTS:
                continue
            # Stubbed; production deployments wire the live HTTP loop.
            yield from ()

    def _stub(self, kinds, since):
        d = datetime(2026, 1, 2, tzinfo=timezone.utc)
        for i in range(2):
            yield RemoteRecord(
                kind="invoice",
                external_id=f"ORA-INV-{2000 + i}",
                external_updated_at=d,
                source_system="oracle",
                payload={
                    "invoice_number": f"ORA-INV-{2000 + i}",
                    "vendor_name":    "Beta Trading LLC",
                    "vendor_vat_no":  "SA300000000002",
                    "total_amount":   "23000.00",
                    "currency":       "SAR",
                    "vat_amount":     "3000.00",
                    "invoice_date":   "2026-01-16",
                },
            )

    def push_decision(self, decision: PushDecision) -> PushResult:
        if self.config.environment == "mock":
            return PushResult(success=True, provider_reference="mock-oracle-ack")
        return PushResult(success=True, provider_reference="stub",
                          message="live Oracle egress not wired")
