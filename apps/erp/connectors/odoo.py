"""Odoo JSON-2 connector.

Production uses Odoo's `/json/2/<model>/<method>` bearer-key API. Legacy
JSON-RPC is intentionally not used because Odoo has scheduled its removal.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Iterator

import requests

from apps.erp.connectors.base import BaseERPConnector, PushDecision, PushResult, RemoteRecord

logger = logging.getLogger("finai.erp.odoo")


class OdooConnector(BaseERPConnector):
    provider = "odoo"
    display_name = "Odoo"
    supports_egress = True
    supported_kinds = ("invoice", "purchase_order", "journal_entry", "vendor")
    _MODEL_MAP = {"invoice": "account.move", "purchase_order": "purchase.order", "journal_entry": "account.move.line", "vendor": "res.partner"}

    def authenticate(self) -> str:
        if self.config.environment == "mock":
            self._api_key = "mock-odoo-key"
            return self._api_key
        cred = self.config.credentials or {}
        key = cred.get("api_key")
        if not key:
            raise RuntimeError("Odoo JSON-2 requires an API key stored in encrypted credentials.")
        self._api_key = key
        return key

    def _headers(self) -> dict[str, str]:
        headers = {"Authorization": f"bearer {self._api_key}", "Content-Type": "application/json", "User-Agent": "Tadgeeg ERP connector"}
        database = (self.config.credentials or {}).get("database")
        if database:
            headers["X-Odoo-Database"] = database
        return headers

    def _call(self, model: str, method: str, payload: dict) -> object:
        url = self.config.base_url.rstrip("/") + f"/json/2/{model}/{method}"
        response = requests.post(url, headers=self._headers(), json=payload, timeout=20)
        response.raise_for_status()
        return response.json()

    def fetch_records(self, *, since=None, kinds=None, page_size=200) -> Iterator[RemoteRecord]:
        kinds = list(kinds or self.supported_kinds)
        if self.config.environment == "mock":
            yield from self._stub(kinds)
            return
        for kind in kinds:
            model = self._MODEL_MAP[kind]
            domain = [["write_date", ">=", since.isoformat()]] if since else []
            if kind == "invoice":
                domain.append(["move_type", "in", ["in_invoice", "in_refund"]])
            rows = self._call(model, "search_read", {"domain": domain, "fields": ["id", "name", "write_date", "amount_total", "amount_tax", "currency_id", "invoice_date", "partner_id"], "limit": page_size})
            for row in rows:
                changed = datetime.fromisoformat(row["write_date"].replace(" ", "T")).replace(tzinfo=timezone.utc)
                yield RemoteRecord(kind=kind, external_id=str(row["id"]), external_updated_at=changed, source_system="odoo", payload={"invoice_number": row.get("name", ""), "total_amount": str(row.get("amount_total", 0)), "vat_amount": str(row.get("amount_tax", 0)), "invoice_date": row.get("invoice_date"), "vendor_name": (row.get("partner_id") or [None, ""])[1]})

    def _stub(self, kinds):
        if "invoice" in kinds:
            yield RemoteRecord(kind="invoice", external_id="ODOO-INV-001", external_updated_at=datetime(2026, 1, 3, tzinfo=timezone.utc), source_system="odoo", payload={"invoice_number": "ODOO-INV-001", "vendor_name": "Gamma Services", "total_amount": "8050.00", "vat_amount": "1050.00", "invoice_date": "2026-01-17"})

    def push_decision(self, decision: PushDecision) -> PushResult:
        if self.config.environment == "mock":
            return PushResult(success=True, provider_reference="mock-odoo-ack")
        try:
            self._call("account.move", "write", {"ids": [int(decision.external_id)], "values": {"x_tadgeeg_decision": decision.status}})
        except (requests.RequestException, ValueError) as exc:
            logger.warning("Odoo decision push failed: %s", exc)
            return PushResult(success=False, message=str(exc)[:500])
        return PushResult(success=True, provider_reference=decision.external_id)
