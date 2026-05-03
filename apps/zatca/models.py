"""
ZATCA Phase 2 — persistence models.

  • EGSDevice         — one row per E-Invoicing Generation System device.
                        Holds the CSR + signed certificate + encrypted
                        private key + lifecycle state.
  • InvoiceSubmission — one row per invoice submitted to ZATCA. Stores the
                        UBL XML, TLV-QR, hash chain pointer, clearance /
                        reporting response, and rejection codes.
  • RejectionCode     — translatable lookup table for ZATCA error codes
                        (BR-KSA-*, KSA-*, BR-CO-*).

Private keys are encrypted with Fernet before they touch the DB. We
deliberately avoid storing plaintext PEM at rest — leaks of the EGS key
let a third party stamp invoices in the org's name.
"""

from __future__ import annotations

import uuid

from django.db import models
from django.utils import timezone


class EGSDevice(models.Model):
    """E-Invoicing Generation System device — one per business location.

    ZATCA issues two flavours of certificate:
      • Compliance CSID (sandbox-only) — used to pass the 24 test scenarios
      • Production CSID — issued after compliance, valid 1 year, auto-renewed
    """

    class Status(models.TextChoices):
        PENDING       = "pending",       "Pending CSR generation"
        CSR_READY     = "csr_ready",     "CSR ready for submission"
        COMPLIANCE    = "compliance",    "Compliance CSID active (sandbox)"
        ACTIVE        = "active",        "Production CSID active"
        EXPIRING      = "expiring",      "Cert expiring within 30 days"
        EXPIRED       = "expired",       "Cert expired"
        REVOKED       = "revoked",       "Revoked"

    class Environment(models.TextChoices):
        SANDBOX    = "sandbox",    "Sandbox (Fatoora)"
        SIMULATION = "simulation", "Simulation"
        PRODUCTION = "production", "Production"

    id            = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization  = models.ForeignKey(
        "authentication.Organization", on_delete=models.CASCADE,
        related_name="egs_devices",
    )

    # Stable identifier — ZATCA EGS Common Name format:
    # 1-XXX|2-YYY|3-ZZZ where X=brand, Y=model, Z=device-serial.
    common_name        = models.CharField(max_length=255)
    serial_number      = models.CharField(max_length=64, db_index=True)
    branch_name        = models.CharField(max_length=200, blank=True)
    environment        = models.CharField(max_length=16, choices=Environment.choices,
                                          default=Environment.SANDBOX)

    csr_pem            = models.TextField(blank=True,
                                          help_text="Base64 PEM-encoded Certificate Signing Request.")
    certificate_pem    = models.TextField(blank=True,
                                          help_text="Base64 PEM-encoded X.509 cert from ZATCA CA.")
    private_key_encrypted = models.BinaryField(null=True, blank=True,
                                               help_text="Fernet-encrypted PEM private key.")
    csid_secret_encrypted = models.BinaryField(null=True, blank=True,
                                               help_text="Fernet-encrypted CSID secret used to sign API requests.")

    status             = models.CharField(max_length=20, choices=Status.choices,
                                          default=Status.PENDING, db_index=True)
    valid_from         = models.DateTimeField(null=True, blank=True)
    valid_until        = models.DateTimeField(null=True, blank=True, db_index=True)
    last_renewed_at    = models.DateTimeField(null=True, blank=True)

    created_at         = models.DateTimeField(auto_now_add=True)
    updated_at         = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "zatca_egs_devices"
        ordering = ["-updated_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "serial_number"],
                name="zatca_egs_unique_serial_per_org",
            ),
        ]
        indexes = [
            models.Index(fields=["organization", "status"]),
        ]

    def __str__(self) -> str:
        return f"{self.common_name} [{self.environment}/{self.status}]"


class InvoiceSubmission(models.Model):
    """Tracks the lifecycle of one ZATCA submission per invoice."""

    class SubmissionType(models.TextChoices):
        CLEARANCE = "clearance", "B2B clearance (synchronous)"
        REPORTING = "reporting", "B2C reporting (asynchronous)"

    class Status(models.TextChoices):
        DRAFT       = "draft",       "Draft"
        SIGNED      = "signed",      "Signed XML ready"
        SUBMITTED   = "submitted",   "Submitted, waiting"
        CLEARED     = "cleared",     "Cleared by ZATCA"
        REPORTED    = "reported",    "Reported (B2C)"
        REJECTED    = "rejected",    "Rejected by ZATCA"
        WARNING     = "warning",     "Accepted with warnings"
        ERROR       = "error",       "Local error before submit"

    id            = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization  = models.ForeignKey(
        "authentication.Organization", on_delete=models.CASCADE,
        related_name="zatca_submissions",
    )
    egs_device    = models.ForeignKey(EGSDevice, on_delete=models.SET_NULL,
                                      null=True, blank=True,
                                      related_name="submissions")
    invoice       = models.ForeignKey(
        "invoices.Invoice", on_delete=models.SET_NULL,
        null=True, blank=True, related_name="zatca_submissions",
    )

    # ZATCA's required Invoice UUID (different from our internal pk).
    zatca_uuid    = models.UUIDField(default=uuid.uuid4, db_index=True)

    submission_type = models.CharField(max_length=12, choices=SubmissionType.choices,
                                       default=SubmissionType.CLEARANCE)
    status          = models.CharField(max_length=12, choices=Status.choices,
                                       default=Status.DRAFT, db_index=True)

    # UBL 2.1 XML payload + parsed canonical hash.
    xml_unsigned    = models.TextField(blank=True)
    xml_signed      = models.TextField(blank=True,
                                       help_text="UBL XML with cryptographic stamp + Previous Invoice Hash chain.")
    invoice_hash    = models.CharField(max_length=128, blank=True, db_index=True,
                                       help_text="SHA-256 of the canonicalised signed XML — input for the next invoice's PIH.")
    previous_invoice_hash = models.CharField(max_length=128, blank=True,
                                             help_text="The invoice_hash of the previous submission in this org's chain (PIH).")
    chain_position  = models.PositiveBigIntegerField(default=0, db_index=True)

    # TLV-encoded QR — base64.
    qr_tlv_base64   = models.TextField(blank=True)

    # Response from ZATCA Fatoora API.
    response_code        = models.CharField(max_length=20, blank=True, db_index=True)
    response_status      = models.CharField(max_length=24, blank=True)
    response_warnings    = models.JSONField(default=list, blank=True)
    response_errors      = models.JSONField(default=list, blank=True)
    response_payload     = models.JSONField(default=dict, blank=True)
    cleared_xml          = models.TextField(blank=True,
                                            help_text="Returned cleared XML (B2B only) — what we must keep for legal evidence.")

    submitted_at         = models.DateTimeField(null=True, blank=True)
    cleared_at           = models.DateTimeField(null=True, blank=True)

    created_at           = models.DateTimeField(auto_now_add=True)
    updated_at           = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "zatca_invoice_submissions"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["organization", "status", "created_at"]),
            models.Index(fields=["organization", "chain_position"]),
        ]

    def __str__(self) -> str:
        return f"submission {self.zatca_uuid} [{self.status}]"


class RejectionCode(models.Model):
    """Lookup of ZATCA rejection codes with translated explanations.

    Pre-seeded via management command using ZATCA's published list of
    BR-KSA-*, KSA-*, BR-CO-*, BR-* codes. The dashboard joins against this
    table to show human-readable Arabic text instead of opaque codes.
    """

    code           = models.CharField(max_length=32, primary_key=True)
    category       = models.CharField(max_length=32, blank=True,
                                      help_text="BR-KSA / KSA / BR-CO / BR / Schema")
    severity       = models.CharField(max_length=12, default="error",
                                      help_text="error | warning | info")
    title_en       = models.CharField(max_length=255)
    title_ar       = models.CharField(max_length=255, blank=True)
    description_en = models.TextField(blank=True)
    description_ar = models.TextField(blank=True)
    fix_hint_en    = models.TextField(blank=True,
                                      help_text="Concrete suggestion the auditor can apply.")
    fix_hint_ar    = models.TextField(blank=True)
    is_active      = models.BooleanField(default=True)
    created_at     = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "zatca_rejection_codes"
        ordering = ["code"]
        indexes = [
            models.Index(fields=["category", "severity"]),
        ]

    def __str__(self) -> str:
        return f"{self.code}: {self.title_en[:48]}"
