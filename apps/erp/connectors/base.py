"""Base ERP connector contract.

Every supported ERP (SAP, Oracle, Odoo, Dynamics, NetSuite, QuickBooks)
implements this interface. The rest of the platform talks to ``BaseERPConnector``
and never imports a vendor-specific module directly.

Concrete connectors live in this package; they are registered in
``apps.erp.connectors.registry`` and discovered by ``ERPConnection.provider``.

Three contracts:

  • ``authenticate()`` — establish session / refresh OAuth / mount mTLS.
  • ``fetch_records(since)`` — yield ``RemoteRecord`` for changes since the
    last watermark. Implementations should be CDC-aware: only return rows
    that genuinely changed.
  • ``push_decision(decision)`` — outbound. After Tadgeeg approves /
    rejects / flags an invoice, push the decision to the ERP so the ERP
    workflow continues. Optional — connectors that don't support it
    raise ``NotImplementedError`` and the egress layer routes the
    decision to an alternative channel (email, webhook).
"""
from __future__ import annotations

import abc
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Iterable, Iterator, Optional


# ─── Common record shapes ───────────────────────────────────────────────────
@dataclass(slots=True, frozen=True)
class RemoteRecord:
    """One row pulled from an ERP. Provider-agnostic."""
    kind:                 str               # "invoice" | "purchase_order" | "journal_entry" | "vendor"
    external_id:          str               # ERP's primary key
    external_updated_at:  datetime          # ERP's last-modified — used as watermark
    payload:              dict              # the row's fields, mapped to Tadgeeg's vocabulary
    source_system:        str               # "sap" | "oracle" | "odoo" | ...
    raw:                  dict = field(default_factory=dict)   # original record for forensics


@dataclass(slots=True, frozen=True)
class PushDecision:
    """A Tadgeeg decision sent back to the ERP."""
    invoice_external_id:  str
    decision:             str               # "approved" | "rejected" | "flagged" | "reposted"
    risk_score:           int               # 0-100
    audit_findings:       list              # List of finding codes
    decided_by:           str               # user id
    decided_at:           datetime
    reason:               str = ""
    extra:                dict = field(default_factory=dict)


@dataclass(slots=True, frozen=True)
class PushResult:
    success:              bool
    provider_reference:   str = ""          # if ERP returns a ticket / event id
    message:              str = ""


# ─── Connection / credentials envelope ──────────────────────────────────────
@dataclass(slots=True)
class ConnectionConfig:
    """What every connector needs to bootstrap.

    The plain `credentials` dict is **decrypted** by the caller before
    construction — connectors only ever see plaintext, never the
    `EncryptedJSONField` envelope.
    """
    organization_id: str
    provider:        str          # canonical id ("sap", "oracle", "odoo", ...)
    environment:    str           # "production" | "sandbox" | "mock"
    base_url:       str = ""
    credentials:    dict = field(default_factory=dict)
    extra:          dict = field(default_factory=dict)


# ─── Contract ───────────────────────────────────────────────────────────────
class BaseERPConnector(abc.ABC):
    """Every concrete connector subclasses this and implements the three methods."""

    provider:     str = ""              # set by subclass
    display_name: str = ""

    # Which record kinds this provider can fetch — restrict the ingestion
    # loop to what's actually supported. SAP B1 doesn't expose vendor
    # masterfile via REST, for instance, so it would set:
    #   supported_kinds = ("invoice", "purchase_order", "journal_entry")
    supported_kinds: tuple[str, ...] = (
        "invoice", "purchase_order", "journal_entry", "vendor",
    )
    supports_egress: bool = False       # True if push_decision is implemented

    def __init__(self, config: ConnectionConfig):
        if not self.provider:
            raise NotImplementedError("subclass must set `provider`")
        self.config = config
        self._session_token: Optional[str] = None

    # ── Lifecycle ───────────────────────────────────────────────────────
    @abc.abstractmethod
    def authenticate(self) -> str:
        """Establish session. Returns an opaque token for logging."""

    # ── Ingestion ───────────────────────────────────────────────────────
    @abc.abstractmethod
    def fetch_records(self,
                      *,
                      since: Optional[datetime] = None,
                      kinds: Optional[Iterable[str]] = None,
                      page_size: int = 200) -> Iterator[RemoteRecord]:
        """Yield records changed in the ERP since ``since`` (CDC watermark).

        ``kinds`` filters by record type. ``page_size`` is a hint to
        chunked APIs — connectors are free to ignore it. Connector
        implementations MUST be streaming (yield from a generator) so
        a 100K-row pull doesn't hold the full result set in memory.
        """

    # ── Egress (optional) ───────────────────────────────────────────────
    def push_decision(self, decision: PushDecision) -> PushResult:
        """Push a Tadgeeg decision back to the ERP. Default: not supported."""
        raise NotImplementedError(
            f"{self.provider} does not implement push_decision"
        )

    # ── Health ──────────────────────────────────────────────────────────
    def healthcheck(self) -> dict:
        """Optional. Returns ``{ok, latency_ms, message}``."""
        return {"ok": True, "latency_ms": 0, "message": "no-op"}
