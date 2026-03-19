"""Document Selector — query layer for AuditDocument."""

import logging

from django.core.paginator import Paginator
from django.http import Http404

logger = logging.getLogger(__name__)


class DocumentSelector:
    """Query layer for AuditDocument — keeps views clean."""

    def get_for_user(self, user, pk):
        """
        Retrieve a single AuditDocument accessible by the given user.
        Raises Http404 if not found or no access.
        """
        from apps.auditing.models import AuditDocument

        try:
            doc = AuditDocument.objects.prefetch_related("findings").get(pk=pk)
        except AuditDocument.DoesNotExist:
            raise Http404("المستند غير موجود.")

        user_org = getattr(user, "organization", None)
        owns = doc.uploaded_by_id == user.pk
        same_org = (
            user_org is not None
            and doc.organization_id is not None
            and str(doc.organization_id) == str(user_org.pk)
        )

        if not (owns or same_org or user.is_staff):
            raise Http404("المستند غير موجود.")

        return doc

    def list_for_user(self, user, page: int = 1, per_page: int = 20):
        """List documents for a specific user (paginated)."""
        from apps.auditing.models import AuditDocument

        qs = AuditDocument.objects.filter(uploaded_by=user).order_by("-created_at")
        paginator = Paginator(qs, per_page)
        return paginator.get_page(page)

    def list_for_organization(self, org, page: int = 1, per_page: int = 20):
        """List documents for an organization (paginated)."""
        from apps.auditing.models import AuditDocument

        qs = AuditDocument.objects.filter(organization=org).order_by("-created_at")
        paginator = Paginator(qs, per_page)
        return paginator.get_page(page)
