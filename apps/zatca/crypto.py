"""
ZATCA Phase 2 cryptography helpers.

  • ``generate_csr_and_key`` — produces an RSA-2048 keypair + a ZATCA-compliant
    CSR (PEM bytes). The CSR carries the ZATCA-mandated Subject DN and the
    custom OID extensions ZATCA's compliance API expects.
  • ``encrypt_secret`` / ``decrypt_secret`` — wrap arbitrary bytes (private key,
    CSID secret) with the project's Fernet key. Falls back to a process-local
    key in dev so tests don't need any extra config; production must set
    ``settings.ZATCA_FERNET_KEY``.
  • ``canonicalise_xml`` + ``hash_invoice_xml`` — SHA-256 over the C14N XML so
    chain integrity matches ZATCA's expected algorithm.

These primitives are deliberately stateless. The lifecycle (DB persistence,
status transitions) lives in ``apps/zatca/services.py``.
"""

from __future__ import annotations

import base64
import hashlib
import logging
import os
from datetime import datetime, timedelta
from typing import Tuple

from django.conf import settings

logger = logging.getLogger("finai.zatca")


# ─────────────────────────────────────────────────────────────────────────────
# CSR + keypair
# ─────────────────────────────────────────────────────────────────────────────

def generate_csr_and_key(
    *,
    organization_name: str,
    organizational_unit: str,
    common_name: str,
    serial_number: str,
    organization_identifier: str,
    invoice_type: str = "1100",
    location_address: str = "",
    industry: str = "Audit Software",
    country: str = "SA",
    is_production: bool = False,
) -> Tuple[bytes, bytes]:
    """Build an RSA-2048 CSR shaped for ZATCA's Compliance / Production APIs.

    Returns ``(csr_pem_bytes, private_key_pem_bytes)``.

    The CSR carries:
      • Subject — CN = ``common_name`` (must follow EGS spec format),
                  OU, O, C, serialNumber, organizationIdentifier (15-digit VAT).
      • SAN extension with the issuer-required custom OIDs:
          1.3.6.1.4.1.311.20.2.3  → invoice_type   (e.g. "1100" for B2B)
          1.3.6.1.4.1.311.20.2.4  → location_address
          1.3.6.1.4.1.311.20.2.5  → industry
          1.3.6.1.4.1.311.20.2.6  → environment    ("0"=sandbox, "1"=prod)

    Real production CSRs use ECC P-256 by ZATCA's mandate; we keep RSA-2048
    here for portability — swap by changing the key generation if your
    deployment receives the production-only schema.
    """
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    subject = x509.Name([
        x509.NameAttribute(NameOID.COUNTRY_NAME,             country),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME,        organization_name),
        x509.NameAttribute(NameOID.ORGANIZATIONAL_UNIT_NAME, organizational_unit),
        x509.NameAttribute(NameOID.COMMON_NAME,              common_name),
        x509.NameAttribute(NameOID.SERIAL_NUMBER,            serial_number),
        x509.NameAttribute(x509.ObjectIdentifier("2.5.4.97"),
                           organization_identifier),  # organizationIdentifier
    ])

    # ZATCA's custom-OID values must be DER-encoded UTF8String (tag 0x0C),
    # not raw bytes. ``cryptography`` doesn't ship a UTF8String helper for
    # OtherName, so we encode the TLV by hand: 0x0C + len + utf-8 bytes.
    def _utf8_der(value: str) -> bytes:
        b = value.encode("utf-8")
        if len(b) > 0x7F:                       # short-form length only
            raise ValueError("OtherName value too long for short-form DER length")
        return bytes([0x0C, len(b)]) + b

    san = x509.SubjectAlternativeName([
        x509.OtherName(x509.ObjectIdentifier("1.3.6.1.4.1.311.20.2.3"),
                       _utf8_der(invoice_type)),
        x509.OtherName(x509.ObjectIdentifier("1.3.6.1.4.1.311.20.2.4"),
                       _utf8_der(location_address or "—")),
        x509.OtherName(x509.ObjectIdentifier("1.3.6.1.4.1.311.20.2.5"),
                       _utf8_der(industry)),
        x509.OtherName(x509.ObjectIdentifier("1.3.6.1.4.1.311.20.2.6"),
                       _utf8_der("1" if is_production else "0")),
    ])

    csr = (
        x509.CertificateSigningRequestBuilder()
        .subject_name(subject)
        .add_extension(san, critical=False)
        .sign(private_key, hashes.SHA256())
    )

    csr_pem = csr.public_bytes(serialization.Encoding.PEM)
    key_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    return csr_pem, key_pem


# ─────────────────────────────────────────────────────────────────────────────
# Fernet encryption for private key + CSID secret at rest
# ─────────────────────────────────────────────────────────────────────────────

def _fernet():
    """Return a Fernet instance using ``settings.ZATCA_FERNET_KEY`` if set,
    otherwise a process-local fallback. The fallback is deterministic per
    ``SECRET_KEY`` so the same Django process can decrypt what it wrote in
    dev / CI without explicit config."""
    from cryptography.fernet import Fernet

    key = getattr(settings, "ZATCA_FERNET_KEY", "") or ""
    if not key:
        # Derive a 32-byte key from SECRET_KEY — base64-encode for Fernet.
        digest = hashlib.sha256(settings.SECRET_KEY.encode("utf-8")).digest()
        key = base64.urlsafe_b64encode(digest)
    elif isinstance(key, str):
        key = key.encode("utf-8")
    return Fernet(key)


def encrypt_secret(plaintext: bytes) -> bytes:
    return _fernet().encrypt(plaintext)


def decrypt_secret(ciphertext: bytes) -> bytes:
    return _fernet().decrypt(bytes(ciphertext))


# ─────────────────────────────────────────────────────────────────────────────
# XML canonicalisation + hashing (for invoice_hash + PIH chain)
# ─────────────────────────────────────────────────────────────────────────────

def canonicalise_xml(xml_str: str) -> bytes:
    """Return the canonical (C14N 1.1) form of the XML, which is what the
    invoice_hash + cryptographic stamp commit to.

    Falls back to a UTF-8 byte-encoding of the raw XML when ``lxml`` isn't
    installed — that's enough for chain-determinism inside the app, but a
    real ZATCA submission needs lxml for a strict C14N round-trip."""
    try:
        from lxml import etree
    except ImportError:
        logger.warning("[zatca.crypto] lxml not installed — falling back to "
                       "UTF-8 byte canonicalisation")
        return xml_str.strip().encode("utf-8")

    parser = etree.XMLParser(remove_blank_text=False)
    root = etree.fromstring(xml_str.encode("utf-8"), parser=parser)
    out_bytes = etree.tostring(root, method="c14n", exclusive=False, with_comments=False)
    return out_bytes


def hash_invoice_xml(xml_str: str) -> str:
    """SHA-256 hex digest of the canonical XML — used for both the invoice
    hash field on the row and as the next invoice's Previous Invoice Hash."""
    return hashlib.sha256(canonicalise_xml(xml_str)).hexdigest()


# ─────────────────────────────────────────────────────────────────────────────
# Cryptographic stamp
# ─────────────────────────────────────────────────────────────────────────────

def stamp_payload(private_key_pem: bytes, payload: bytes) -> str:
    """Sign ``payload`` with the EGS private key and return base64.

    Used for the Cryptographic Stamp ZATCA expects in the UBL signature
    block. RSA-PSS-SHA256 is the algorithm; production deployments using
    ECDSA P-256 should swap in ``ec.ECDSA(hashes.SHA256())`` instead.
    """
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding

    key = serialization.load_pem_private_key(private_key_pem, password=None)
    signature = key.sign(
        payload,
        padding.PSS(mgf=padding.MGF1(hashes.SHA256()),
                    salt_length=padding.PSS.MAX_LENGTH),
        hashes.SHA256(),
    )
    return base64.b64encode(signature).decode("ascii")


def public_key_pem_from_private(private_key_pem: bytes) -> bytes:
    """Extract the matching public key as PEM."""
    from cryptography.hazmat.primitives import serialization

    key = serialization.load_pem_private_key(private_key_pem, password=None)
    return key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Validity helpers
# ─────────────────────────────────────────────────────────────────────────────

def cert_validity_dates(certificate_pem: bytes) -> Tuple[datetime, datetime]:
    """Return ``(not_before, not_after)`` for a PEM certificate.

    Used to drive the EGS device status (``ACTIVE`` → ``EXPIRING`` →
    ``EXPIRED``) without an explicit cron — the dashboard reads validity
    on each request.
    """
    from cryptography import x509

    cert = x509.load_pem_x509_certificate(certificate_pem)
    return cert.not_valid_before_utc, cert.not_valid_after_utc
