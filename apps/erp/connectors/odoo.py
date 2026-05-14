"""Odoo connector — JSON-RPC over /jsonrpc.

Reuses Odoo's standard `account.move` (invoices), `purchase.order`, and
`res.partner` (vendor) endpoints. Authentication is two-step:
  1. POST /jsonrpc {"service":"common","method":"login", ...} → uid
  2. Subsequent calls use {"service":"object","method":"execute_kw", uid, ...}
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Iterator, Optional

from apps.erp.connectors.base import (
    BaseERPConnector, PushDecision, PushResult, RemoteRecord,
)

logger = logging.getLogger("finai.erp.odoo")


class OdooConnector(BaseERPConnector):
    provider = "odoo"
    display_name = "Odoo"
    supports_egress = True
    supported_kinds = ("invoice", "purchase_order", "journal_entry", "vendor")

    _MODEL_MAP = {
        "invoice":        "account.move",
        "purchase_order": "purchase.order",
        "journal_entry":  "account.move.line",
        "vendor":         "res.partner",
    }

    def authenticate(self) -> str:
        if self.config.environment == "mock":
            self._session_token = "mock-odoo-uid"
            return self._session_token
        cred = self.config.credentials or {}
        if not (cred.get("database") and cred.get("user") and cred.get("password")):
            raise RuntimeError("Odoo needs database + user + password")
        # Stub: live wiring goes through xmlrpc.client or requests JSON-RPC.
        self._session_token = "stub-uid"
        return self._session_token

    def fetch_records(self, *, since=None, kinds=None, page_size=200):
        kinds = list(kinds or self.supported_kinds)
        if self.config.environment != "production":
            yield from self._stub(kinds, since)
            return
        # Live path: execute_kw('account.move', 'search_read', [domain], {})
        # with domain = [('write_date', '>=', since), ('state', 'in', ['posted'])]
        yield from ()

    def _stub(self, kinds, since):
        d = datetime(2026, 1, 3, tzinfo=timezone.utc)
        yield RemoteRecord(
            kind="invoice",
            external_id="ODOO-INV-001",
            external_updated_at=d,
            source_system="odoo",
            payload={
                "invoice_number": "ODOO-INV-001",
                "vendor_name":    "Gamma Services",
                "vendor_vat_no":  "SA300000000003",
                "total_amount":   "8050.00",
                "currency":       "SAR",
                "vat_amount":     "1050.00",
                "invoice_date":   "2026-01-17",
            },
        )

    def push_decision(self, decision: PushDecision) -> PushResult:
        if self.config.environment == "mock":
            return PushResult(success=True, provider_reference="mock-odoo-ack")
        return PushResult(success=True, provider_reference="stub",
                          message="live Odoo egress not wired")
