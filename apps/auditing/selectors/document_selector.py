"""Document Selector — query layer for AuditDocument."""

import logging

from django.contrib.auth import get_user_model

from ..models import AuditDocument

logger = logging.getLogger(__name__)

User = get_user_model()


class DocumentSelector:
    @staticmethod
    def get_user_documents(user):
        return AuditDocument.objects.filter(uploaded_by=user).order_by("-created_at")

    @staticmethod
    def get_user_document_by_id(user, pk):
        return AuditDocument.objects.filter(uploaded_by=user, pk=pk).first()
