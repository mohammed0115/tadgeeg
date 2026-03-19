"""Auditing History View."""

import logging

from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.paginator import EmptyPage, PageNotAnInteger, Paginator
from django.shortcuts import render
from django.views import View

from apps.auditing.models import AuditDocument

logger = logging.getLogger(__name__)

PER_PAGE = 20


class AuditDocumentHistoryView(LoginRequiredMixin, View):
    """List all audit documents for the current user / organization."""

    login_url = "/login/"
    template_name = "auditing/history.html"

    def get(self, request):
        user = request.user
        organization = getattr(user, "organization", None)

        if organization is not None:
            qs = AuditDocument.objects.filter(organization=organization).select_related(
                "uploaded_by"
            )
        else:
            qs = AuditDocument.objects.filter(uploaded_by=user)

        qs = qs.order_by("-created_at")

        paginator = Paginator(qs, PER_PAGE)
        page_number = request.GET.get("page", 1)
        try:
            page_obj = paginator.page(page_number)
        except PageNotAnInteger:
            page_obj = paginator.page(1)
        except EmptyPage:
            page_obj = paginator.page(paginator.num_pages)

        context = {
            "page_obj": page_obj,
            "total_count": paginator.count,
        }
        return render(request, self.template_name, context)
