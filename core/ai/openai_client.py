"""Compatibility client: legacy ``OpenAI(...).chat.completions.create`` via gateway.

New code should call :func:`core.ai.gateway.chat_completion` directly so it can
name the operation and pass the user/document. This adapter exists to migrate
legacy services without leaving a second unmetered SDK path in production.
"""
from __future__ import annotations

from types import SimpleNamespace

from apps.authentication.models import Organization
from core.ai.gateway import AIOrganizationRequired, chat_completion
from core.services.ai_budget import get_current_org_id


class _Completions:
    def __init__(self, *, timeout=None):
        self._timeout = timeout

    def create(self, **kwargs):
        org_id = get_current_org_id()
        organization = Organization.objects.filter(pk=org_id).first() if org_id else None
        if organization is None:
            raise AIOrganizationRequired(
                "Legacy OpenAI caller has no organization context; set org_context before calling."
            )
        model = kwargs.pop("model", None)
        messages = kwargs.pop("messages", [])
        max_tokens = kwargs.pop("max_tokens", 2_000)
        return chat_completion(
            organization=organization,
            operation="legacy",
            model=model,
            messages=messages,
            max_tokens=max_tokens,
            timeout=self._timeout,
            **kwargs,
        )


class OpenAI:
    """Drop-in subset used during migration; all calls become metered."""

    def __init__(self, *, api_key=None, timeout=None, **_kwargs):
        # API key is intentionally accepted for compatibility but never stored.
        self.chat = SimpleNamespace(completions=_Completions(timeout=timeout))
