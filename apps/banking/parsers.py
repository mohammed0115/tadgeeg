"""
Statement-upload fallback — Phase 5.4.

When a bank has no live API (or onboarding is stuck), the user uploads a
PDF / CSV / XLSX bank statement and we feed it through the same
reconciliation engine. This module turns the file into a list of
``TransactionInfo`` rows the connector framework already knows how to
persist.

Coverage right now:

  • CSV  — comma + tab + semicolon separators, header-row autodetect.
  • XLSX — first worksheet, header in row 1.
  • PDF  — best-effort line-by-line regex against the most common Saudi
           statement layouts (date, debit, credit, description). Falls
           back to a no-op when ``pdfplumber`` isn't installed.

The output format mirrors live connector output so ``services.sync_connection``-style
persistence works without branching.
"""

from __future__ import annotations

import csv
import io
import logging
import re
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Iterable

from apps.banking.connectors.base import TransactionInfo

logger = logging.getLogger("finai.banking")


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _parse_decimal(v) -> Decimal:
    if v is None:
        return Decimal("0")
    s = str(v).replace(",", "").strip()
    if not s:
        return Decimal("0")
    try:
        return Decimal(s)
    except InvalidOperation:
        return Decimal("0")


_DATE_FORMATS = [
    "%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%m/%d/%Y", "%d/%m/%y",
    "%d %b %Y", "%d %B %Y",
]


def _parse_date(v) -> datetime:
    if isinstance(v, datetime):
        return v
    s = str(v or "").strip()
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return datetime.utcnow()


def _normalise_header(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


# Header-name → output-field mapping. Each output field accepts a list of
# aliases; whichever the file uses, we pick.
_HEADER_ALIASES = {
    "external_id":  ["transactionid", "txnid", "ref", "reference", "id"],
    "date":         ["date", "postingdate", "valuedate", "txndate", "transactiondate"],
    "debit":        ["debit", "withdrawal", "amountdebit", "out"],
    "credit":       ["credit", "deposit", "amountcredit", "in"],
    "amount":       ["amount", "value"],
    "description":  ["description", "narration", "details", "memo", "particulars"],
    "counterparty": ["counterparty", "beneficiary", "merchant", "name", "payee"],
    "balance":      ["balance", "runningbalance"],
}


def _resolve_columns(header_row: list[str]) -> dict:
    """Return a {column_index: field_name} mapping by walking the aliases."""
    norm = [_normalise_header(c) for c in header_row]
    out: dict[int, str] = {}
    for field, aliases in _HEADER_ALIASES.items():
        for alias in aliases:
            try:
                idx = norm.index(_normalise_header(alias))
            except ValueError:
                continue
            out[idx] = field
            break
    return out


# ─────────────────────────────────────────────────────────────────────────────
# CSV
# ─────────────────────────────────────────────────────────────────────────────

def parse_csv(content: bytes | str) -> list[TransactionInfo]:
    text = content.decode("utf-8-sig") if isinstance(content, bytes) else content
    # Sniff dialect.
    try:
        dialect = csv.Sniffer().sniff(text[:1024], delimiters=",\t;|")
    except csv.Error:
        dialect = csv.excel
    reader = list(csv.reader(io.StringIO(text), dialect))
    if not reader:
        return []

    cols = _resolve_columns(reader[0])
    out: list[TransactionInfo] = []
    for row_idx, row in enumerate(reader[1:], start=2):
        rec: dict = {}
        for idx, field in cols.items():
            if idx < len(row):
                rec[field] = row[idx]
        ti = _row_to_transaction(rec, row_idx)
        if ti is not None:
            out.append(ti)
    return out


# ─────────────────────────────────────────────────────────────────────────────
# Excel
# ─────────────────────────────────────────────────────────────────────────────

def parse_xlsx(file_path: str) -> list[TransactionInfo]:
    try:
        import openpyxl
    except ImportError:
        logger.warning("[banking.parsers] openpyxl not installed — skipping XLSX")
        return []

    wb = openpyxl.load_workbook(file_path, data_only=True, read_only=True)
    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        return []

    cols = _resolve_columns([str(c) if c is not None else "" for c in rows[0]])
    out: list[TransactionInfo] = []
    for row_idx, row in enumerate(rows[1:], start=2):
        rec: dict = {}
        for idx, field in cols.items():
            if idx < len(row):
                rec[field] = row[idx]
        ti = _row_to_transaction(rec, row_idx)
        if ti is not None:
            out.append(ti)
    return out


# ─────────────────────────────────────────────────────────────────────────────
# PDF
# ─────────────────────────────────────────────────────────────────────────────

_PDF_LINE_RE = re.compile(
    r"(?P<date>\d{1,2}[-/]\d{1,2}[-/]\d{2,4})\s+"
    r"(?P<desc>.+?)\s+"
    r"(?P<amount>-?\d{1,3}(?:[,\s]?\d{3})*(?:\.\d{1,2})?)"
    r"(?:\s+(?P<balance>-?\d{1,3}(?:[,\s]?\d{3})*(?:\.\d{1,2})?))?$"
)


def parse_pdf(file_path: str) -> list[TransactionInfo]:
    try:
        import pdfplumber
    except ImportError:
        logger.warning("[banking.parsers] pdfplumber not installed — skipping PDF")
        return []

    out: list[TransactionInfo] = []
    with pdfplumber.open(file_path) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            for ln, line in enumerate(text.split("\n"), start=1):
                m = _PDF_LINE_RE.match(line.strip())
                if not m:
                    continue
                amount = _parse_decimal(m.group("amount"))
                direction = "debit" if amount < 0 else "credit"
                out.append(TransactionInfo(
                    external_id=f"PDF-{ln}-{abs(int(amount * 100))}",
                    posted_at=_parse_date(m.group("date")),
                    direction=direction,
                    amount=abs(amount),
                    currency="SAR",
                    reference="",
                    description=m.group("desc").strip(),
                    counterparty=m.group("desc").strip()[:80],
                    raw={"source": "pdf", "line": line[:200]},
                ))
    return out


# ─────────────────────────────────────────────────────────────────────────────
# Row → TransactionInfo
# ─────────────────────────────────────────────────────────────────────────────

def _row_to_transaction(rec: dict, row_idx: int) -> TransactionInfo | None:
    date_v = rec.get("date")
    if not date_v:
        return None

    debit  = _parse_decimal(rec.get("debit"))
    credit = _parse_decimal(rec.get("credit"))

    if debit > 0:
        direction, amount = "debit", debit
    elif credit > 0:
        direction, amount = "credit", credit
    else:
        amt = _parse_decimal(rec.get("amount"))
        if amt == 0:
            return None
        direction = "debit" if amt < 0 else "credit"
        amount = abs(amt)

    return TransactionInfo(
        external_id=str(rec.get("external_id") or f"ROW-{row_idx}"),
        posted_at=_parse_date(date_v),
        direction=direction,
        amount=amount,
        currency="SAR",
        reference=str(rec.get("external_id") or ""),
        description=str(rec.get("description") or ""),
        counterparty=str(rec.get("counterparty") or rec.get("description") or "")[:255],
        raw={"row": row_idx, **{k: str(v) for k, v in rec.items() if v is not None}},
    )
