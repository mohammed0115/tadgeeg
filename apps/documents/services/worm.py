"""WORM (Write-Once-Read-Many) attestation service.

The audit-review flagged that locked working papers and document
attachments need an explicit *immutability attestation* that a SOC2 /
ISA 230 reviewer can point at — "show me proof this document hasn't
been altered since it was sealed."

We already capture per-row content hashes (Document.file_sha256 from
F-8) and chain working papers via :class:`HashChainMixin`. This
module adds the third leg: an **attestation manifest** that bundles
those into one signed declaration with a wall-clock timestamp and an
auditor's wallet address (KID — key identifier — only; we don't
manage the wallet itself, just record what signed).

The implementation is deliberately storage-agnostic. It does NOT push
the document to object-lock-enabled S3 — that's a deployment concern
the team can wire up separately. What this module provides is the
**attestation surface** that the auditor will reference regardless of
where the bytes physically live.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class WORMAttestation:
    """One immutability declaration for a single artifact."""
    object_kind:    str               # "working_paper" | "document" | "report"
    object_id:      str
    content_sha256: str
    sealed_at:      str               # ISO timestamp
    sealed_by:      str               # user id or "system"
    signer_kid:     str = ""          # key identifier (X.509 SKI / KMS arn / "")
    storage_uri:    str = ""          # informational, e.g. "s3://...?versionid=..."
    manifest_sha256: str = ""         # SHA-256 of the canonical manifest (see below)
    metadata:       dict = field(default_factory=dict)

    def manifest(self) -> dict:
        """Canonical manifest used for the signature, deterministically ordered."""
        return {
            "object_kind":    self.object_kind,
            "object_id":      self.object_id,
            "content_sha256": self.content_sha256,
            "sealed_at":      self.sealed_at,
            "sealed_by":      self.sealed_by,
            "signer_kid":     self.signer_kid,
            "storage_uri":    self.storage_uri,
            "metadata":       _canonical(self.metadata),
        }

    def to_dict(self) -> dict:
        d = self.manifest()
        d["manifest_sha256"] = self.manifest_sha256
        return d


def _canonical(obj: Any) -> Any:
    """Recursive deterministic canonical form (sorted keys at all levels)."""
    if isinstance(obj, dict):
        return {k: _canonical(obj[k]) for k in sorted(obj)}
    if isinstance(obj, (list, tuple)):
        return [_canonical(v) for v in obj]
    return obj


def _manifest_sha(manifest: dict) -> str:
    body = json.dumps(_canonical(manifest), sort_keys=True,
                      separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(body).hexdigest()


def attest_working_paper(paper, *, sealed_by_user_id: str = "system",
                         signer_kid: str = "") -> WORMAttestation:
    """Build an attestation for a LOCKED working paper.

    Requires the paper to be in status=LOCKED — chains aren't sealed
    before then, so any earlier attestation would be premature.
    """
    if not getattr(paper, "is_locked", False):
        raise ValueError(
            f"working paper {paper.pk} is not locked — cannot attest"
        )
    chain_hash = getattr(paper, "event_hash", "") or ""
    content_sha = chain_hash.lower()
    sealed_at = (paper.locked_at or datetime.utcnow()).isoformat()
    raw = WORMAttestation(
        object_kind="working_paper",
        object_id=str(paper.pk),
        content_sha256=content_sha,
        sealed_at=sealed_at,
        sealed_by=str(sealed_by_user_id),
        signer_kid=signer_kid,
        metadata={
            "reference":     getattr(paper, "reference", ""),
            "title":         getattr(paper, "title", ""),
            "paper_type":    getattr(paper, "paper_type", ""),
            "organization":  str(getattr(paper, "organization_id", "")),
            "partner_signed_by": str(getattr(paper, "partner_signed_by_id", "") or ""),
        },
    )
    return _seal(raw)


def attest_document(document, *, sealed_by_user_id: str = "system",
                    signer_kid: str = "") -> WORMAttestation:
    """Build an attestation for a Document.

    Requires :attr:`file_sha256` to be set (F-8 captures it on upload).
    """
    sha = (getattr(document, "file_sha256", "") or "").lower()
    if not sha:
        raise ValueError(
            f"document {document.pk} has no file_sha256 — run "
            f"capture_file_hash() first"
        )
    sealed_at = getattr(document, "created_at", None)
    if hasattr(sealed_at, "isoformat"):
        sealed_at = sealed_at.isoformat()
    else:
        sealed_at = datetime.utcnow().isoformat()
    raw = WORMAttestation(
        object_kind="document",
        object_id=str(document.pk),
        content_sha256=sha,
        sealed_at=sealed_at,
        sealed_by=str(sealed_by_user_id),
        signer_kid=signer_kid,
        storage_uri=getattr(document, "storage_uri", "") or "",
        metadata={
            "filename":      getattr(document, "filename", "") or "",
            "document_type": getattr(document, "document_type", "") or "",
            "organization":  str(getattr(document, "organization_id", "") or ""),
        },
    )
    return _seal(raw)


def _seal(raw: WORMAttestation) -> WORMAttestation:
    """Recompute and bind ``manifest_sha256`` to the row."""
    digest = _manifest_sha(raw.manifest())
    return WORMAttestation(
        object_kind=raw.object_kind,
        object_id=raw.object_id,
        content_sha256=raw.content_sha256,
        sealed_at=raw.sealed_at,
        sealed_by=raw.sealed_by,
        signer_kid=raw.signer_kid,
        storage_uri=raw.storage_uri,
        manifest_sha256=digest,
        metadata=dict(raw.metadata),
    )


def verify_attestation(att: WORMAttestation) -> bool:
    """Recompute the manifest hash and compare to the bound value."""
    return _manifest_sha(att.manifest()) == att.manifest_sha256
