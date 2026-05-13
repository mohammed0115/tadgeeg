"""Document file-integrity helpers (F-8).

Closes the audit-review gap: "A swapped file on disk doesn't change
the Document row, so the audit trail says nothing." Every Document
captures a SHA-256 of its file bytes at upload time; verification
re-reads the file and compares.

Usage:
    from apps.documents.services.integrity import (
        capture_file_hash, verify_document_integrity,
    )

    # on upload
    doc.file_sha256 = capture_file_hash(doc.file)
    doc.save(update_fields=["file_sha256"])

    # on retrieval / nightly audit
    status = verify_document_integrity(doc)
    if status.tampered:
        alert(...)
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass


_CHUNK = 64 * 1024


def capture_file_hash(file_obj) -> str:
    """Return hex SHA-256 of the file content. Resets the file pointer."""
    file_obj.seek(0)
    h = hashlib.sha256()
    for chunk in iter(lambda: file_obj.read(_CHUNK), b""):
        h.update(chunk)
    file_obj.seek(0)
    return h.hexdigest()


@dataclass(frozen=True)
class IntegrityStatus:
    document_id: str
    stored_hash: str
    recomputed_hash: str
    tampered: bool

    def to_dict(self) -> dict:
        return {
            "document_id":     self.document_id,
            "stored_hash":     self.stored_hash,
            "recomputed_hash": self.recomputed_hash,
            "tampered":        self.tampered,
        }


def verify_document_integrity(document) -> IntegrityStatus:
    """Recompute the file hash and compare to ``document.file_sha256``."""
    stored = (document.file_sha256 or "").lower()
    if not stored:
        # Legacy row from before F-8 — populate retroactively.
        recomputed = capture_file_hash(document.file)
        document.file_sha256 = recomputed
        document.save(update_fields=["file_sha256"])
        return IntegrityStatus(
            document_id=str(document.pk),
            stored_hash=recomputed,
            recomputed_hash=recomputed,
            tampered=False,
        )
    recomputed = capture_file_hash(document.file).lower()
    return IntegrityStatus(
        document_id=str(document.pk),
        stored_hash=stored,
        recomputed_hash=recomputed,
        tampered=(stored != recomputed),
    )
