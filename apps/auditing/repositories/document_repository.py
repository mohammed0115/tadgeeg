"""Document Repository — data access layer for AuditDocument."""

import logging

logger = logging.getLogger(__name__)


class DocumentRepository:
    """Data access layer for AuditDocument model."""

    def create(self, **kwargs):
        """Create and save a new AuditDocument."""
        from apps.auditing.models import AuditDocument
        doc = AuditDocument(**kwargs)
        doc.save()
        return doc

    def update(self, doc, **kwargs):
        """Update fields on an existing AuditDocument."""
        for field, value in kwargs.items():
            setattr(doc, field, value)
        doc.save()
        return doc

    def get_by_id(self, pk):
        """Retrieve an AuditDocument by primary key. Returns None if not found."""
        from apps.auditing.models import AuditDocument
        try:
            return AuditDocument.objects.get(pk=pk)
        except AuditDocument.DoesNotExist:
            logger.warning("DocumentRepository: AuditDocument not found: %s", pk)
            return None
