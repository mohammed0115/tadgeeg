"""Auditing History View."""

from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.paginator import Paginator
from django.shortcuts import render
from django.views import View

from ..selectors.document_selector import DocumentSelector


class AuditDocumentHistoryView(LoginRequiredMixin, View):
    template_name = "auditing/history.html"
    login_url = "/login/"
    PAGE_SIZE = 20

    def get(self, request):
        qs = DocumentSelector.get_user_documents(request.user)
        paginator = Paginator(qs, self.PAGE_SIZE)
        page = paginator.get_page(request.GET.get("page", 1))
        return render(
            request,
            self.template_name,
            {
                "page": page,
                "page_obj": page,  # alias for backward compat
                "total_count": paginator.count,
            },
        )
