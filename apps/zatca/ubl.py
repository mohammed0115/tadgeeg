"""
UBL 2.1 invoice generator for ZATCA Phase 2.

Produces the XML envelope ZATCA's Fatoora API expects for both Clearance
(B2B, ``InvoiceTypeCode = 0100``) and Reporting (B2C, ``0200``).

The generator is deliberately string-templated rather than DOM-built —
ZATCA's required canonicalisation order is brittle, and a hand-tuned
template is easier to keep in lock-step with the spec than a tree
manipulation. ``apps/zatca/crypto.canonicalise_xml`` re-parses with
lxml when computing the hash, so any whitespace drift is normalised
before signing.

Reference: ZATCA Phase-2 Technical Specifications v2.0, sections 5–7
("Standard Tax Invoice" + "Simplified Tax Invoice").
"""

from __future__ import annotations

import base64
import binascii
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Iterable, Optional


XMLNS_INVOICE = "urn:oasis:names:specification:ubl:schema:xsd:Invoice-2"
XMLNS_CAC     = "urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2"
XMLNS_CBC     = "urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2"
XMLNS_EXT     = "urn:oasis:names:specification:ubl:schema:xsd:CommonExtensionComponents-2"


@dataclass
class InvoiceLine:
    line_id:      str
    description:  str
    quantity:     Decimal
    unit_price:   Decimal
    line_total:   Decimal
    vat_rate:     Decimal = Decimal("15")
    vat_amount:   Decimal = Decimal("0")


@dataclass
class InvoicePayload:
    """The data the generator turns into UBL XML."""

    # Required.
    uuid:                str   # ZATCA Invoice UUID (must match qr + hash chain)
    invoice_number:      str
    issue_date:          datetime
    invoice_type_code:   str   # "0100" B2B / "0200" B2C
    currency:            str = "SAR"

    # Seller (the org issuing the invoice).
    seller_name:         str = ""
    seller_vat_number:   str = ""
    seller_cr_number:    str = ""
    seller_address:      str = ""

    # Buyer.
    buyer_name:          str = ""
    buyer_vat_number:    str = ""
    buyer_address:       str = ""

    # Money.
    line_extension_total: Decimal = Decimal("0")
    tax_exclusive_total:  Decimal = Decimal("0")
    tax_inclusive_total:  Decimal = Decimal("0")
    vat_amount:           Decimal = Decimal("0")
    payable_amount:       Decimal = Decimal("0")

    lines: list[InvoiceLine] = field(default_factory=list)

    # Chain link — empty for the first invoice in the chain.
    previous_invoice_hash: str = ""


# ─────────────────────────────────────────────────────────────────────────────
# Generators
# ─────────────────────────────────────────────────────────────────────────────

def _amt(v) -> str:
    """Format a Decimal as a 2-dp string ZATCA accepts."""
    if v is None:
        v = Decimal("0")
    return str(Decimal(v).quantize(Decimal("0.01")))


def _esc(s: str) -> str:
    """Escape XML-significant characters in user-supplied strings."""
    return (str(s or "")
            .replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def render_invoice_xml(p: InvoicePayload) -> str:
    """Serialise an InvoicePayload to UBL 2.1 XML (unsigned)."""
    lines_xml = "\n".join(_render_line(li) for li in p.lines)

    return (
        f'<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<Invoice xmlns="{XMLNS_INVOICE}"\n'
        f'         xmlns:cac="{XMLNS_CAC}"\n'
        f'         xmlns:cbc="{XMLNS_CBC}"\n'
        f'         xmlns:ext="{XMLNS_EXT}">\n'
        f'  <cbc:ProfileID>reporting:1.0</cbc:ProfileID>\n'
        f'  <cbc:ID>{_esc(p.invoice_number)}</cbc:ID>\n'
        f'  <cbc:UUID>{_esc(str(p.uuid))}</cbc:UUID>\n'
        f'  <cbc:IssueDate>{p.issue_date.strftime("%Y-%m-%d")}</cbc:IssueDate>\n'
        f'  <cbc:IssueTime>{p.issue_date.strftime("%H:%M:%S")}</cbc:IssueTime>\n'
        f'  <cbc:InvoiceTypeCode name="{_esc(p.invoice_type_code)}">388</cbc:InvoiceTypeCode>\n'
        f'  <cbc:DocumentCurrencyCode>{_esc(p.currency)}</cbc:DocumentCurrencyCode>\n'
        f'  <cbc:TaxCurrencyCode>{_esc(p.currency)}</cbc:TaxCurrencyCode>\n'
        f'  <!-- KSA-13 Previous Invoice Hash chain -->\n'
        f'  <cac:AdditionalDocumentReference>\n'
        f'    <cbc:ID>PIH</cbc:ID>\n'
        f'    <cac:Attachment>\n'
        f'      <cbc:EmbeddedDocumentBinaryObject mimeCode="text/plain">'
        f'{_esc(p.previous_invoice_hash or "0" * 64)}'
        f'</cbc:EmbeddedDocumentBinaryObject>\n'
        f'    </cac:Attachment>\n'
        f'  </cac:AdditionalDocumentReference>\n'
        f'{_render_party("AccountingSupplierParty", p.seller_name, p.seller_vat_number, p.seller_cr_number, p.seller_address)}\n'
        f'{_render_party("AccountingCustomerParty", p.buyer_name,  p.buyer_vat_number,  "",                    p.buyer_address)}\n'
        f'  <cac:TaxTotal>\n'
        f'    <cbc:TaxAmount currencyID="{_esc(p.currency)}">{_amt(p.vat_amount)}</cbc:TaxAmount>\n'
        f'  </cac:TaxTotal>\n'
        f'  <cac:LegalMonetaryTotal>\n'
        f'    <cbc:LineExtensionAmount currencyID="{_esc(p.currency)}">{_amt(p.line_extension_total)}</cbc:LineExtensionAmount>\n'
        f'    <cbc:TaxExclusiveAmount currencyID="{_esc(p.currency)}">{_amt(p.tax_exclusive_total)}</cbc:TaxExclusiveAmount>\n'
        f'    <cbc:TaxInclusiveAmount currencyID="{_esc(p.currency)}">{_amt(p.tax_inclusive_total)}</cbc:TaxInclusiveAmount>\n'
        f'    <cbc:PayableAmount currencyID="{_esc(p.currency)}">{_amt(p.payable_amount or p.tax_inclusive_total)}</cbc:PayableAmount>\n'
        f'  </cac:LegalMonetaryTotal>\n'
        f'{lines_xml}\n'
        f'</Invoice>\n'
    )


def _render_party(party_role: str, name: str, vat_number: str,
                  registration_number: str, address: str) -> str:
    return (
        f'  <cac:{party_role}>\n'
        f'    <cac:Party>\n'
        f'      <cac:PartyIdentification><cbc:ID schemeID="VAT">{_esc(vat_number)}</cbc:ID></cac:PartyIdentification>\n'
        f'      <cac:PartyName><cbc:Name>{_esc(name)}</cbc:Name></cac:PartyName>\n'
        f'      <cac:PostalAddress><cbc:StreetName>{_esc(address)}</cbc:StreetName></cac:PostalAddress>\n'
        f'      <cac:PartyTaxScheme>\n'
        f'        <cbc:CompanyID>{_esc(vat_number)}</cbc:CompanyID>\n'
        f'        <cac:TaxScheme><cbc:ID>VAT</cbc:ID></cac:TaxScheme>\n'
        f'      </cac:PartyTaxScheme>\n'
        f'    </cac:Party>\n'
        f'  </cac:{party_role}>'
    )


def _render_line(li: InvoiceLine) -> str:
    return (
        f'  <cac:InvoiceLine>\n'
        f'    <cbc:ID>{_esc(li.line_id)}</cbc:ID>\n'
        f'    <cbc:InvoicedQuantity>{_amt(li.quantity)}</cbc:InvoicedQuantity>\n'
        f'    <cbc:LineExtensionAmount currencyID="SAR">{_amt(li.line_total)}</cbc:LineExtensionAmount>\n'
        f'    <cac:Item><cbc:Name>{_esc(li.description)}</cbc:Name></cac:Item>\n'
        f'    <cac:Price><cbc:PriceAmount currencyID="SAR">{_amt(li.unit_price)}</cbc:PriceAmount></cac:Price>\n'
        f'    <cac:TaxTotal>\n'
        f'      <cbc:TaxAmount currencyID="SAR">{_amt(li.vat_amount)}</cbc:TaxAmount>\n'
        f'      <cac:TaxSubtotal>\n'
        f'        <cbc:TaxableAmount currencyID="SAR">{_amt(li.line_total)}</cbc:TaxableAmount>\n'
        f'        <cbc:TaxAmount currencyID="SAR">{_amt(li.vat_amount)}</cbc:TaxAmount>\n'
        f'        <cac:TaxCategory>\n'
        f'          <cbc:ID>S</cbc:ID>\n'
        f'          <cbc:Percent>{_amt(li.vat_rate)}</cbc:Percent>\n'
        f'          <cac:TaxScheme><cbc:ID>VAT</cbc:ID></cac:TaxScheme>\n'
        f'        </cac:TaxCategory>\n'
        f'      </cac:TaxSubtotal>\n'
        f'    </cac:TaxTotal>\n'
        f'  </cac:InvoiceLine>'
    )


# ─────────────────────────────────────────────────────────────────────────────
# TLV-encoded QR (ZATCA Phase 2 — 8 fields)
# ─────────────────────────────────────────────────────────────────────────────

def _tlv(tag: int, value: bytes) -> bytes:
    if len(value) > 0xFF:
        raise ValueError(f"TLV value for tag 0x{tag:02x} exceeds 255 bytes")
    return bytes([tag, len(value)]) + value


def build_tlv_qr(*,
                 seller_name: str,
                 seller_vat: str,
                 timestamp: datetime,
                 invoice_total: Decimal,
                 vat_total: Decimal,
                 invoice_hash: str = "",
                 stamp_signature_b64: str = "",
                 public_key_pem: bytes = b"",
                 stamp_certificate_signature_b64: str = "") -> str:
    """Encode the 8 ZATCA tags as TLV → base64.

    Tags 1-5 are mandatory for both B2B and B2C. Tags 6-8 are required only
    for the cleared / reported response (signatures + public key). When the
    optional fields are blank we omit them entirely — strict-mode ZATCA
    sandbox accepts the truncated form for unsigned previews."""
    out = b""
    out += _tlv(1, seller_name.encode("utf-8"))
    out += _tlv(2, seller_vat.encode("utf-8"))
    out += _tlv(3, timestamp.strftime("%Y-%m-%dT%H:%M:%SZ").encode("utf-8"))
    out += _tlv(4, _amt(invoice_total).encode("utf-8"))
    out += _tlv(5, _amt(vat_total).encode("utf-8"))

    if invoice_hash:
        try:
            hash_bytes = bytes.fromhex(invoice_hash)
        except (ValueError, binascii.Error):
            hash_bytes = invoice_hash.encode("utf-8")
        out += _tlv(6, hash_bytes[:32])  # SHA-256 = 32 bytes

    if stamp_signature_b64:
        try:
            sig_bytes = base64.b64decode(stamp_signature_b64)
        except Exception:
            sig_bytes = stamp_signature_b64.encode("utf-8")
        out += _tlv(7, sig_bytes[:255])

    if public_key_pem:
        # ZATCA expects DER-encoded SubjectPublicKeyInfo, not PEM. Strip the
        # PEM headers + decode if present, otherwise pass through.
        pem = public_key_pem.decode("utf-8") if isinstance(public_key_pem, bytes) else public_key_pem
        b64 = "".join(line for line in pem.splitlines() if "----" not in line)
        try:
            der = base64.b64decode(b64)
        except Exception:
            der = public_key_pem if isinstance(public_key_pem, bytes) else public_key_pem.encode("utf-8")
        # 255-byte cap per TLV — production keys (~270 bytes for RSA-2048
        # SubjectPublicKeyInfo) overflow the single TLV; ZATCA's actual
        # spec uses extended-length TLV for tag 8. We truncate here for the
        # in-app sandbox preview.
        out += _tlv(8, der[:255])

    if stamp_certificate_signature_b64:
        try:
            cert_sig = base64.b64decode(stamp_certificate_signature_b64)
        except Exception:
            cert_sig = stamp_certificate_signature_b64.encode("utf-8")
        out += _tlv(9, cert_sig[:255])

    return base64.b64encode(out).decode("ascii")


def decode_tlv_qr(b64_payload: str) -> list[dict]:
    """Inverse of ``build_tlv_qr`` — useful for debugging the dashboard."""
    raw = base64.b64decode(b64_payload)
    out = []
    i = 0
    while i + 2 <= len(raw):
        tag = raw[i]
        length = raw[i + 1]
        value = raw[i + 2 : i + 2 + length]
        out.append({"tag": tag, "length": length, "value": value})
        i += 2 + length
    return out
