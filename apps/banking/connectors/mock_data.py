"""Deterministic transaction generator for the mock connectors.

Same seed → same transactions, so two QA runs produce identical fixtures
and reconciliation tests stay stable. The dataset mirrors the kind of
mix a Saudi SME sees: a handful of vendor payments, a payroll batch, a
few VAT refunds, and the usual fees.
"""

from __future__ import annotations

import hashlib
import random
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Iterable

from apps.banking.connectors.base import AccountInfo, TransactionInfo


def _seed_for(bank_code: str, account_number: str) -> int:
    """Stable seed so the same (bank, account) always yields the same rows."""
    h = hashlib.sha256(f"{bank_code}:{account_number}".encode("utf-8")).digest()
    return int.from_bytes(h[:4], "big")


_VENDOR_NAMES = [
    "AL-MOQAWILON CONTRACTING",  "RAYAN OIL & GAS",      "GULF STATIONERY",
    "ARAMCO PROCUREMENT",        "TADGEEG TECHNOLOGIES", "AL-FAYSAL TRADING",
    "SAUDI POWER LIMITED",       "RIYADH FOOD CO.",       "MAERSK SAUDI",
    "STC BUSINESS",              "OMNISYS LOGISTICS",     "KSA OFFICE SUPPLIES",
]

_DESCRIPTIONS = [
    "VENDOR PAYMENT",  "PAYROLL TRANSFER",  "VAT RETURN — ZATCA",
    "BANK CHARGES",    "WIRE TRANSFER",     "STC INVOICE",
    "RENT PAYMENT",    "INSURANCE PREMIUM", "CASH DEPOSIT",
]


def mock_accounts(bank_code: str) -> list[AccountInfo]:
    """Two demo accounts per bank — main + savings."""
    base = abs(_seed_for(bank_code, "")) % 10_000_000
    return [
        AccountInfo(
            account_number=f"{base:010d}001",
            iban=f"SA{(base % 90 + 10):02d}9000{base:010d}001",
            currency="SAR",
            balance=Decimal("100000.00") + Decimal(base % 50000),
            nickname="Main operating",
        ),
        AccountInfo(
            account_number=f"{base:010d}002",
            iban=f"SA{(base % 90 + 10):02d}9000{base:010d}002",
            currency="SAR",
            balance=Decimal("250000.00") + Decimal(base % 80000),
            nickname="VAT settlement",
        ),
    ]


def mock_transactions(*, bank_code: str, account_number: str,
                      from_date: datetime, to_date: datetime,
                      max_rows: int = 60) -> list[TransactionInfo]:
    """Synthesize a deterministic list of transactions in the window."""
    if from_date >= to_date:
        return []

    rng = random.Random(_seed_for(bank_code, account_number))
    span_seconds = int((to_date - from_date).total_seconds())
    rows: list[TransactionInfo] = []

    for i in range(max_rows):
        offset = rng.randint(0, span_seconds)
        ts = from_date + timedelta(seconds=offset)
        direction = rng.choice(["debit", "credit", "debit", "debit"])    # debits more common
        amount = Decimal(str(round(rng.uniform(50, 25_000), 2)))
        vendor = rng.choice(_VENDOR_NAMES)
        desc   = rng.choice(_DESCRIPTIONS)
        ref    = f"INV-{rng.randint(10000, 99999)}"
        rows.append(TransactionInfo(
            external_id=f"{bank_code.upper()}-{account_number[-4:]}-{i:04d}",
            posted_at=ts,
            direction=direction,
            amount=amount,
            currency="SAR",
            reference=ref,
            description=f"{desc} — {vendor}",
            counterparty=vendor,
            raw={"bank": bank_code, "seq": i},
        ))

    rows.sort(key=lambda t: t.posted_at)
    return rows
