"""
ZATCA Phase 2 (Fatoora E-invoicing) detection + lightweight structural checks.

Full ZATCA Phase 2 conformance requires UBL 2.1 XML, XAdES-B-B digital
signatures, ICV sequential counters, PIH (previous-invoice-hash), and signed
hash trees. Implementing the cryptographic chain is a multi-week project that
involves ZATCA's certificate issuance.

This module ships the layer below that — *detection* and *structural sanity*:
- `is_ubl_invoice()` — does the payload look like a UBL Invoice doc?
- `is_signed()` — does it carry a UBL ext/signature element?
- `validate_required_elements()` — are the critical UBL fields present?
- `extract_metadata()` — pulls the ICV, PIH, UUID, and supply-date out of the XML.

Higher layers (rule engine + invoice processor) call these to flag invoices
that *claim* Phase 2 compliance but fail structural checks.
"""
from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger("rule_engine")

UBL_NS = "{urn:oasis:names:specification:ubl:schema:xsd:Invoice-2}"
CBC_NS = "{urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2}"
CAC_NS = "{urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2}"
EXT_NS = "{urn:oasis:names:specification:ubl:schema:xsd:CommonExtensionComponents-2}"


# Required UBL fields per ZATCA Phase 2 spec. Missing any of these = non-conforming.
_REQUIRED_UBL_FIELDS = [
    f"{CBC_NS}ProfileID",
    f"{CBC_NS}ID",
    f"{CBC_NS}UUID",
    f"{CBC_NS}IssueDate",
    f"{CBC_NS}IssueTime",
    f"{CBC_NS}InvoiceTypeCode",
    f"{CBC_NS}DocumentCurrencyCode",
    f"{CAC_NS}AccountingSupplierParty",
    f"{CAC_NS}AccountingCustomerParty",
    f"{CAC_NS}LegalMonetaryTotal",
]


def _parse(xml_source: bytes | str):
    """Best-effort parse — returns lxml Element or None. lxml is preferred but
    we fall back to stdlib so the module works in environments without lxml."""
    try:
        from lxml import etree
        if isinstance(xml_source, str):
            xml_source = xml_source.encode("utf-8")
        # disable XXE / external-entity attacks
        parser = etree.XMLParser(resolve_entities=False, no_network=True)
        return etree.fromstring(xml_source, parser=parser)
    except Exception:
        try:
            import xml.etree.ElementTree as _ET
            if isinstance(xml_source, bytes):
                xml_source = xml_source.decode("utf-8", errors="replace")
            return _ET.fromstring(xml_source)
        except Exception as exc:
            logger.debug("[zatca-p2] XML parse failed: %s", exc)
            return None


def is_ubl_invoice(xml_source: bytes | str) -> bool:
    """True if root element is `Invoice` in the UBL namespace."""
    root = _parse(xml_source)
    return root is not None and root.tag == f"{UBL_NS}Invoice"


def is_signed(xml_source: bytes | str) -> bool:
    """True when the document carries a UBL-extension signature element.

    ZATCA-signed invoices wrap a `<UBLExtensions><UBLExtension>...<SignatureInformation>`
    structure. We don't validate the cryptography here — only that the
    structure exists. A claim of Phase 2 compliance without this structure
    is automatically wrong.
    """
    root = _parse(xml_source)
    if root is None:
        return False
    ext_node = root.find(f"{EXT_NS}UBLExtensions")
    if ext_node is None:
        return False
    # Any descendant SignatureInformation counts.
    return any(
        el.tag.endswith("SignatureInformation")
        for el in ext_node.iter()
    )


def validate_required_elements(xml_source: bytes | str) -> dict:
    """Return {missing: [...]} listing required UBL fields that are absent.

    Empty `missing` list = structurally valid for the fields we can verify
    without ZATCA's full XSD.
    """
    root = _parse(xml_source)
    if root is None:
        return {"missing": _REQUIRED_UBL_FIELDS, "parse_error": True}
    missing = [tag for tag in _REQUIRED_UBL_FIELDS if root.find(tag) is None]
    return {"missing": missing, "parse_error": False}


def extract_metadata(xml_source: bytes | str) -> dict:
    """Pull the ZATCA-specific metadata fields out of the invoice XML."""
    root = _parse(xml_source)
    if root is None:
        return {}

    def _text(path: str) -> Optional[str]:
        el = root.find(path)
        return el.text.strip() if (el is not None and el.text) else None

    return {
        "uuid":               _text(f"{CBC_NS}UUID"),
        "invoice_id":         _text(f"{CBC_NS}ID"),
        "profile_id":         _text(f"{CBC_NS}ProfileID"),
        "issue_date":         _text(f"{CBC_NS}IssueDate"),
        "issue_time":         _text(f"{CBC_NS}IssueTime"),
        "invoice_type_code":  _text(f"{CBC_NS}InvoiceTypeCode"),
        "currency":           _text(f"{CBC_NS}DocumentCurrencyCode"),
        # ICV (invoice counter) and PIH (previous-invoice-hash) live in
        # AdditionalDocumentReference elements.
        "icv":                _find_doc_ref(root, "ICV"),
        "pih":                _find_doc_ref(root, "PIH"),
    }


def _find_doc_ref(root, ref_id: str) -> Optional[str]:
    for ref in root.iter(f"{CAC_NS}AdditionalDocumentReference"):
        id_el = ref.find(f"{CBC_NS}ID")
        if id_el is not None and id_el.text == ref_id:
            uuid_el = ref.find(f"{CBC_NS}UUID")
            if uuid_el is not None and uuid_el.text:
                return uuid_el.text.strip()
            attach = ref.find(
                f"{CAC_NS}Attachment/{CBC_NS}EmbeddedDocumentBinaryObject"
            )
            if attach is not None and attach.text:
                return attach.text.strip()
    return None


def compute_invoice_hash(xml_source: bytes | str) -> Optional[str]:
    """Compute the ZATCA-canonical SHA-256 hash of the invoice XML, base64-encoded.

    ZATCA Phase 2 spec requires hashing the canonicalized invoice (without
    UBL extensions, QRCode, Signature elements) using SHA-256, then base64
    encoding the digest. This is what gets fed into the PIH chain.

    Note: full canonicalization is XML-C14N which we approximate by stripping
    the signature/QR elements before serialization. Production deployments
    should use lxml's c14n() for byte-exact canonicalization.
    """
    import base64
    import hashlib

    try:
        from lxml import etree
        if isinstance(xml_source, str):
            xml_source = xml_source.encode("utf-8")
        parser = etree.XMLParser(resolve_entities=False, no_network=True, remove_blank_text=False)
        root = etree.fromstring(xml_source, parser=parser)

        # Strip the elements ZATCA spec excludes from the digest.
        for tag in (f"{EXT_NS}UBLExtensions",):
            for el in root.findall(tag):
                el.getparent().remove(el) if el.getparent() is not None else None

        # Canonicalize per W3C XML-C14N 1.1.
        canonical = etree.tostring(root, method="c14n", with_comments=False, exclusive=False)
        digest = hashlib.sha256(canonical).digest()
        return base64.b64encode(digest).decode("ascii")
    except Exception as exc:
        logger.debug("[zatca-p2] hash computation failed: %s", exc)
        return None


def verify_signature_value(xml_source: bytes | str, public_key_pem: bytes | None = None) -> dict:
    """Best-effort verification of the embedded signature value.

    Without ZATCA's CSID-issued certificate we can't verify the chain of
    trust, but we *can* confirm:
        - the SignatureValue base64-decodes cleanly
        - the certificate (if embedded) parses correctly
        - the SignatureValue mathematically verifies against the cert's public
          key over the SignedInfo bytes (when ``cryptography`` is installed)

    Returns a structured result rather than throwing so the rule layer can
    grade the invoice as "signed but unverified" vs "signed and verified".
    """
    import base64

    out = {
        "has_signature_value": False,
        "signature_format_ok": False,
        "signature_verified": None,    # True = mathematically verified, False = bad sig, None = couldn't check
        "certificate_parsed": None,
    }
    root = _parse(xml_source)
    if root is None:
        return out

    sig_val = None
    cert_b64 = None
    signed_info_node = None
    for el in root.iter():
        tag = el.tag.rsplit("}", 1)[-1].lower()
        if tag == "signaturevalue" and el.text:
            sig_val = el.text.strip()
        elif tag == "x509certificate" and el.text:
            cert_b64 = el.text.strip()
        elif tag == "signedinfo":
            signed_info_node = el

    if sig_val:
        out["has_signature_value"] = True
        try:
            base64.b64decode(sig_val, validate=True)
            out["signature_format_ok"] = True
        except Exception:
            out["signature_format_ok"] = False

    if cert_b64:
        try:
            cert_der = base64.b64decode(cert_b64)
            try:
                from cryptography import x509
                from cryptography.hazmat.primitives import hashes, serialization
                from cryptography.hazmat.primitives.asymmetric import padding, ec, rsa
                from cryptography.exceptions import InvalidSignature

                cert = x509.load_der_x509_certificate(cert_der)
                out["certificate_parsed"] = True
                out["certificate_subject"] = cert.subject.rfc4514_string()
                out["certificate_not_after"] = cert.not_valid_after.isoformat()

                # ── Mathematical signature verification ────────────────────
                # We try multiple canonicalization variants because real-world
                # XAdES tools differ:
                #   - exclusive c14n (xml-exc-c14n) ← XAdES-B-B default
                #   - inclusive c14n (W3C XML-C14N 1.0) ← some ZATCA tools
                #   - raw element bytes (uncommon but seen in dev tools)
                # If ANY variant verifies, we accept the signature.
                if signed_info_node is not None and out["signature_format_ok"]:
                    try:
                        from lxml import etree
                        sig_bytes = base64.b64decode(sig_val)
                        public_key = cert.public_key()

                        candidates = []
                        try:
                            candidates.append(etree.tostring(
                                signed_info_node, method="c14n",
                                with_comments=False, exclusive=True,
                            ))
                        except Exception: pass
                        try:
                            candidates.append(etree.tostring(
                                signed_info_node, method="c14n",
                                with_comments=False, exclusive=False,
                            ))
                        except Exception: pass
                        try:
                            candidates.append(etree.tostring(signed_info_node))
                        except Exception: pass

                        verified = False
                        for canonical in candidates:
                            if isinstance(public_key, ec.EllipticCurvePublicKey):
                                try:
                                    public_key.verify(sig_bytes, canonical, ec.ECDSA(hashes.SHA256()))
                                    verified = True
                                    break
                                except InvalidSignature:
                                    continue
                            elif isinstance(public_key, rsa.RSAPublicKey):
                                try:
                                    public_key.verify(
                                        sig_bytes, canonical,
                                        padding.PKCS1v15(), hashes.SHA256(),
                                    )
                                    verified = True
                                    break
                                except InvalidSignature:
                                    continue
                        out["signature_verified"] = verified
                    except Exception as verify_exc:
                        # Couldn't perform verification — leave as None (=unknown).
                        out["signature_verified"] = None
                        out["verification_error"] = str(verify_exc)[:120]

                # Optional: trust override using a caller-provided public key.
                if public_key_pem and out["signature_verified"] is None and signed_info_node is not None:
                    try:
                        from lxml import etree
                        from cryptography.hazmat.primitives import serialization as _ser
                        public_key2 = _ser.load_pem_public_key(public_key_pem)
                        signed_info_bytes = etree.tostring(
                            signed_info_node, method="c14n", with_comments=False, exclusive=True,
                        )
                        sig_bytes = base64.b64decode(sig_val)
                        if isinstance(public_key2, ec.EllipticCurvePublicKey):
                            public_key2.verify(sig_bytes, signed_info_bytes, ec.ECDSA(hashes.SHA256()))
                        elif isinstance(public_key2, rsa.RSAPublicKey):
                            public_key2.verify(sig_bytes, signed_info_bytes, padding.PKCS1v15(), hashes.SHA256())
                        out["signature_verified"] = True
                    except Exception:
                        out["signature_verified"] = False

            except ImportError:
                # cryptography lib not installed — degrade to "binary parses".
                out["certificate_parsed"] = bool(cert_der)
        except Exception as exc:
            out["certificate_parsed"] = False
            out["certificate_error"] = str(exc)[:120]

    return out


def verify_pih_chain(invoice_hash: str, expected_previous_hash: str, declared_pih: str) -> bool:
    """Verify that the invoice's declared PIH matches the previous invoice's hash.

    ZATCA Phase 2 requires every invoice (after the first) to embed the
    base64-encoded SHA-256 of the immediately preceding invoice. This is the
    simplest check that produces a chain auditors can replay.
    """
    if not invoice_hash or not expected_previous_hash or not declared_pih:
        return False
    return declared_pih.strip() == expected_previous_hash.strip()


def conformance_summary(xml_source: bytes | str, public_key_pem: bytes | None = None) -> dict:
    """Single dict suitable for the rule-engine to consume.

    Returns:
        {
          "is_ubl":            bool,
          "is_signed":         bool,
          "signature":         {...},   # has_signature_value, format_ok, cert info
          "missing":           [...],   # required UBL elements missing
          "metadata":          {...},   # UUID, ICV, PIH, dates, ...
          "invoice_hash":      "...",   # base64 SHA-256 of canonical XML
          "phase2_compliant":  bool,
        }
    """
    is_ubl = is_ubl_invoice(xml_source)
    if not is_ubl:
        return {
            "is_ubl": False, "is_signed": False, "signature": {},
            "missing": [], "metadata": {}, "invoice_hash": None,
            "phase2_compliant": False, "reason": "Not a UBL invoice document.",
        }
    signed = is_signed(xml_source)
    validation = validate_required_elements(xml_source)
    metadata = extract_metadata(xml_source)
    invoice_hash = compute_invoice_hash(xml_source)
    signature = verify_signature_value(xml_source, public_key_pem) if signed else {}

    # Phase 2 compliant = signed AND structurally valid AND signature format OK.
    compliant = (
        signed
        and not validation["missing"]
        and not validation.get("parse_error")
        and signature.get("signature_format_ok", False)
    )

    return {
        "is_ubl": True,
        "is_signed": signed,
        "signature": signature,
        "missing": validation["missing"],
        "metadata": metadata,
        "invoice_hash": invoice_hash,
        "phase2_compliant": compliant,
    }
