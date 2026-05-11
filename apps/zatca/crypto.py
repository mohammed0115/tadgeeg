"""
ZATCA Phase 2 cryptography helpers — ECC P-256 / ECDSA-SHA256.

ZATCA Phase 2 production mandates:
  • Asymmetric keypair: ECC SECP256R1 (a.k.a. P-256, prime256v1, NIST P-256).
  • Cryptographic stamp signature: ECDSA over SHA-256.
  • Canonical XML: strict C14N (lxml). UTF-8 byte fallback is NOT acceptable —
    it produces a different invoice_hash than what ZATCA's verifier computes,
    which breaks the PIH chain.
  • Encryption-at-rest of EGS private keys with a key SEPARATE from
    ``settings.SECRET_KEY``. A SECRET_KEY leak must not implicitly compromise
    every customer's signing key.

This module is a hard rewrite of the previous RSA-2048 / RSA-PSS-SHA256
helpers. The old functions had explicit "production deployments swap to ECC"
comments — this module makes the swap, since the project is shipping for
production-bound enterprise clients.

Public API:
  • ``generate_csr_and_key``  — ECC P-256 keypair + ZATCA-shaped CSR (PEM bytes).
  • ``encrypt_secret`` / ``decrypt_secret`` — Fernet wrapper for at-rest secrets.
  • ``canonicalise_xml`` + ``hash_invoice_xml`` — strict C14N + SHA-256.
  • ``stamp_payload``        — ECDSA-SHA256 signature, base64-encoded.
  • ``public_key_pem_from_private`` — extracts the matching public key.
  • ``cert_validity_dates``  — for EGS lifecycle UI.

The module deliberately fails LOUDLY in production paths when its hard
dependencies (``lxml``, ``ZATCA_FERNET_KEY``) are missing. A silent
fallback is fine for a developer's local hack but not for a system that
signs real tax invoices.
"""

from __future__ import annotations

import base64
import hashlib
import logging
from datetime import datetime
from typing import Tuple

from django.conf import settings

logger = logging.getLogger("finai.zatca")


# ─────────────────────────────────────────────────────────────────────────────
# CSR + keypair (ECC P-256)
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
    """Build an ECC P-256 CSR shaped for ZATCA's Compliance / Production APIs.

    Returns ``(csr_pem_bytes, private_key_pem_bytes)``.

    The CSR carries:
      • Subject — CN = ``common_name`` (must follow EGS spec format),
                  OU, O, C, serialNumber, organizationIdentifier (15-digit VAT).
      • SAN extension with ZATCA's custom OIDs:
          1.3.6.1.4.1.311.20.2.3 → invoice_type      ("1100" = B2B)
          1.3.6.1.4.1.311.20.2.4 → location_address
          1.3.6.1.4.1.311.20.2.5 → industry
          1.3.6.1.4.1.311.20.2.6 → environment       ("0"=sandbox, "1"=prod)

    The private key is returned as PKCS#8 PEM. Callers MUST encrypt it via
    ``encrypt_secret`` before persisting — never store the raw bytes.
    """
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID

    # ZATCA Phase 2 production: SECP256R1 / NIST P-256.
    private_key = ec.generate_private_key(ec.SECP256R1())

    subject = x509.Name([
        x509.NameAttribute(NameOID.COUNTRY_NAME,             country),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME,        organization_name),
        x509.NameAttribute(NameOID.ORGANIZATIONAL_UNIT_NAME, organizational_unit),
        x509.NameAttribute(NameOID.COMMON_NAME,              common_name),
        x509.NameAttribute(NameOID.SERIAL_NUMBER,            serial_number),
        x509.NameAttribute(x509.ObjectIdentifier("2.5.4.97"),
                           organization_identifier),  # organizationIdentifier
    ])

    # ZATCA's custom-OID values must be DER-encoded UTF8String (tag 0x0C).
    # The cryptography library doesn't ship a UTF8String helper for OtherName,
    # so we encode the TLV by hand: 0x0C + len + utf-8 bytes.
    def _utf8_der(value: str) -> bytes:
        b = value.encode("utf-8")
        if len(b) > 0x7F:
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
        .sign(private_key, hashes.SHA256())  # signature on the CSR itself
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
    """Return a Fernet instance using ``settings.ZATCA_FERNET_KEY``.

    Behavior:
      • Production (``DEBUG=False``): the key MUST be set. Missing key raises
        RuntimeError — refusing to silently derive from SECRET_KEY, because a
        SECRET_KEY leak would otherwise expose every EGS private key.
      • Development (``DEBUG=True``): falls back to a SECRET_KEY-derived key
        so local dev / unit tests don't need extra config.
    """
    from cryptography.fernet import Fernet

    key = getattr(settings, "ZATCA_FERNET_KEY", "") or ""
    if not key:
        if not getattr(settings, "DEBUG", False):
            raise RuntimeError(
                "ZATCA_FERNET_KEY is not configured. Production must provide a "
                "Fernet key SEPARATE from SECRET_KEY for EGS private-key "
                "encryption. Generate one via "
                "`python -c \"from cryptography.fernet import Fernet; "
                "print(Fernet.generate_key().decode())\"`."
            )
        # Dev-only fallback. Never reached in production after this commit.
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
    """Return the C14N 1.1 canonical form of the XML.

    Hard dependency on ``lxml``. The previous fallback to a UTF-8
    byte-encoding produced a different ``invoice_hash`` than ZATCA's
    verifier, which would break the PIH chain on the very first
    submission. We refuse to fall back silently — fix the deployment
    by installing ``lxml``.
    """
    try:
        from lxml import etree
    except ImportError as exc:
        # Surface a clear ImportError rather than a downstream "ZATCA
        # rejected my invoice for hash mismatch" mystery a week later.
        raise ImportError(
            "ZATCA invoice canonicalisation requires lxml. Install with "
            "`pip install lxml` (already declared in requirements.txt)."
        ) from exc

    parser = etree.XMLParser(remove_blank_text=False)
    root = etree.fromstring(xml_str.encode("utf-8"), parser=parser)
    return etree.tostring(root, method="c14n", exclusive=False, with_comments=False)


def hash_invoice_xml(xml_str: str) -> str:
    """SHA-256 hex digest of the canonical XML — used for the invoice_hash
    field and as the next invoice's Previous Invoice Hash."""
    return hashlib.sha256(canonicalise_xml(xml_str)).hexdigest()


# ─────────────────────────────────────────────────────────────────────────────
# Cryptographic stamp (ECDSA-SHA256)
# ─────────────────────────────────────────────────────────────────────────────

def stamp_payload(private_key_pem: bytes, payload: bytes) -> str:
    """Sign ``payload`` with the EGS private key and return base64-encoded
    ECDSA-SHA256 signature.

    This is the algorithm ZATCA's UBL signature block expects for Phase 2
    production. The previous RSA-PSS-SHA256 implementation was rejected
    by the production verifier.
    """
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec

    key = serialization.load_pem_private_key(private_key_pem, password=None)
    if not isinstance(key, ec.EllipticCurvePrivateKey):
        # Defensive: a legacy RSA key file would silently sign with the wrong
        # algorithm. Make the mismatch loud so operators rotate the key.
        raise TypeError(
            f"ZATCA stamp_payload expected an ECC private key (P-256); got "
            f"{type(key).__name__}. Re-issue the EGS keypair via "
            f"generate_csr_and_key() and re-onboard with ZATCA."
        )
    signature = key.sign(payload, ec.ECDSA(hashes.SHA256()))
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

    Used by the EGS-status dashboard to flip a row to EXPIRING / EXPIRED
    without a cron job — validity is read on each render.
    """
    from cryptography import x509

    cert = x509.load_pem_x509_certificate(certificate_pem)
    return cert.not_valid_before_utc, cert.not_valid_after_utc
