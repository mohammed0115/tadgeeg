"""
Bank-connector base interface.

Every Saudi bank exposes a different API surface — Mubasher Business
Connect (Al Rajhi), corporate REST (SNB), RB Connect (Riyad), open-banking
(SAB), BSF Direct (BSF). The ``BaseBankConnector`` flattens those into a
common contract so the rest of the app talks to one shape.

  • ``authenticate(credentials)`` — log in with whatever the bank requires
                                    (API key + secret, OAuth, mTLS cert)
                                    and return a session token.
  • ``fetch_accounts()``           — list of dicts: account_number, iban,
                                    currency, balance, nickname.
  • ``fetch_transactions(account_id, from_date, to_date)`` — list of dicts:
                                    external_id, posted_at, direction,
                                    amount, currency, reference,
                                    description, counterparty.

Mock connectors live next to the live ones; whether a connection runs
mock or live is a per-row choice on ``BankConnection.environment``.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Iterable


@dataclass
class AccountInfo:
    account_number: str
    iban:           str = ""
    currency:       str = "SAR"
    balance:        Decimal = Decimal("0")
    nickname:       str = ""

    def to_dict(self) -> dict:
        return {
            "account_number": self.account_number,
            "iban":           self.iban,
            "currency":       self.currency,
            "balance":        float(self.balance),
            "nickname":       self.nickname,
        }


@dataclass
class TransactionInfo:
    external_id:  str
    posted_at:    datetime
    direction:    str       # "debit" or "credit"
    amount:       Decimal
    currency:     str = "SAR"
    reference:    str = ""
    description:  str = ""
    counterparty: str = ""
    raw:          dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "external_id":  self.external_id,
            "posted_at":    self.posted_at.isoformat(),
            "direction":    self.direction,
            "amount":       float(self.amount),
            "currency":     self.currency,
            "reference":    self.reference,
            "description":  self.description,
            "counterparty": self.counterparty,
            "raw":          self.raw,
        }


class BaseBankConnector(abc.ABC):
    """Contract every bank-specific subclass implements."""

    bank_code: str = "base"
    display_name: str = "Base"

    def __init__(self, *, environment: str = "mock",
                 credentials: dict | None = None):
        self.environment = environment
        self.credentials = credentials or {}
        self._session_token: str = ""

    # ── Authentication ─────────────────────────────────────────────────────

    @abc.abstractmethod
    def authenticate(self) -> str:
        """Return an opaque session token; cache on the instance."""

    # ── Read paths ─────────────────────────────────────────────────────────

    @abc.abstractmethod
    def fetch_accounts(self) -> list[AccountInfo]:
        """Return every account the credentials can see."""

    @abc.abstractmethod
    def fetch_transactions(self, *, account_number: str,
                           from_date: datetime,
                           to_date: datetime) -> list[TransactionInfo]:
        """Return statement lines posted within ``[from_date, to_date]``."""

    # ── Sanity ─────────────────────────────────────────────────────────────

    def health_check(self) -> dict:
        """Try to authenticate and return a small dict the dashboard uses."""
        try:
            self.authenticate()
            return {"ok": True, "bank": self.bank_code,
                    "environment": self.environment}
        except Exception as exc:
            return {"ok": False, "bank": self.bank_code,
                    "environment": self.environment,
                    "error": str(exc)[:240]}
