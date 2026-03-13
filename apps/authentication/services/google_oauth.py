"""Helpers for server-side Google OAuth login flow."""

from __future__ import annotations

import logging
from urllib.parse import urlencode

import requests
from django.conf import settings
from django.utils import timezone

from apps.authentication.models import User

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"

logger = logging.getLogger("finai")


class GoogleOAuthError(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def is_google_oauth_configured() -> bool:
    return bool(
        getattr(settings, "GOOGLE_CLIENT_ID", "")
        and getattr(settings, "GOOGLE_CLIENT_SECRET", "")
        and getattr(settings, "GOOGLE_REDIRECT_URI", "")
    )


def build_google_oauth_authorization_url(state: str) -> str:
    if not is_google_oauth_configured():
        raise GoogleOAuthError("oauth_not_configured")

    params = {
        "client_id": settings.GOOGLE_CLIENT_ID,
        "redirect_uri": settings.GOOGLE_REDIRECT_URI,
        "response_type": "code",
        "scope": "openid email profile",
        "access_type": "online",
        "include_granted_scopes": "true",
        "prompt": "select_account",
        "state": state,
    }
    return f"{GOOGLE_AUTH_URL}?{urlencode(params)}"


def _client_id_suffix() -> str:
    client_id = (getattr(settings, "GOOGLE_CLIENT_ID", "") or "").strip()
    return client_id[-12:] if client_id else "missing"


def _normalize_google_token_error(error: str, error_description: str) -> str:
    normalized_error = (error or "").strip().lower()
    normalized_description = (error_description or "").strip().lower()

    if normalized_error == "invalid_client":
        return "invalid_client"
    if normalized_error == "invalid_grant":
        return "invalid_grant"
    if normalized_error == "redirect_uri_mismatch" or (
        "redirect_uri" in normalized_description and "mismatch" in normalized_description
    ):
        return "redirect_uri_mismatch"
    return "token_exchange_failed"


def exchange_google_code_for_tokens(code: str) -> dict:
    try:
        response = requests.post(
            GOOGLE_TOKEN_URL,
            data={
                "code": code,
                "client_id": settings.GOOGLE_CLIENT_ID,
                "client_secret": settings.GOOGLE_CLIENT_SECRET,
                "redirect_uri": settings.GOOGLE_REDIRECT_URI,
                "grant_type": "authorization_code",
            },
            timeout=10,
        )
    except requests.RequestException as exc:
        logger.exception(
            "Google token exchange request failed redirect_uri=%s client_id_suffix=%s",
            settings.GOOGLE_REDIRECT_URI,
            _client_id_suffix(),
        )
        raise GoogleOAuthError("token_exchange_failed") from exc

    try:
        payload = response.json()
    except ValueError:
        payload = {}

    if response.status_code != 200:
        google_error = payload.get("error", "") if isinstance(payload, dict) else ""
        google_error_description = payload.get("error_description", "") if isinstance(payload, dict) else ""
        error_code = _normalize_google_token_error(google_error, google_error_description)
        logger.warning(
            "Google token exchange rejected status=%s error=%s description=%s redirect_uri=%s client_id_suffix=%s",
            response.status_code,
            google_error or "unknown",
            google_error_description or response.text[:240],
            settings.GOOGLE_REDIRECT_URI,
            _client_id_suffix(),
        )
        raise GoogleOAuthError(error_code)

    if not isinstance(payload, dict) or not payload.get("access_token"):
        logger.warning(
            "Google token exchange succeeded without access token redirect_uri=%s client_id_suffix=%s keys=%s",
            settings.GOOGLE_REDIRECT_URI,
            _client_id_suffix(),
            sorted(payload.keys()) if isinstance(payload, dict) else type(payload).__name__,
        )
        raise GoogleOAuthError("token_exchange_failed")

    logger.info(
        "Google token exchange succeeded redirect_uri=%s client_id_suffix=%s scopes=%s",
        settings.GOOGLE_REDIRECT_URI,
        _client_id_suffix(),
        payload.get("scope", ""),
    )
    return payload


def fetch_google_user_profile(access_token: str) -> dict:
    try:
        response = requests.get(
            GOOGLE_USERINFO_URL,
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=10,
        )
    except requests.RequestException as exc:
        logger.exception("Google userinfo request failed")
        raise GoogleOAuthError("userinfo_failed") from exc

    try:
        payload = response.json()
    except ValueError as exc:
        logger.warning("Google userinfo returned non-JSON status=%s body=%s", response.status_code, response.text[:240])
        raise GoogleOAuthError("userinfo_failed") from exc

    if response.status_code != 200:
        logger.warning(
            "Google userinfo rejected status=%s error=%s body=%s",
            response.status_code,
            payload.get("error", "unknown") if isinstance(payload, dict) else "unknown",
            response.text[:240],
        )
        raise GoogleOAuthError("userinfo_failed")

    logger.info("Google userinfo retrieved email_present=%s", bool((payload.get("email") or "").strip()))
    return payload


def get_or_create_local_user_from_google_profile(profile: dict) -> tuple[User, bool]:
    email = (profile.get("email") or "").strip().lower()
    if not email:
        raise GoogleOAuthError("no_email")

    full_name = (profile.get("name") or "").strip() or email.split("@")[0]
    user = User.objects.filter(email__iexact=email).select_related("organization").first()
    is_new = user is None

    if is_new:
        user = User.objects.create_user(
            email=email,
            password=None,
            full_name=full_name,
            role=User.Role.JUNIOR_AUDITOR,
            organization=None,
            is_active=True,
            email_verified_at=timezone.now(),
        )
        return user, True

    updated_fields = []
    if not user.full_name and full_name:
        user.full_name = full_name
        updated_fields.append("full_name")
    if not user.email_verified_at:
        user.email_verified_at = timezone.now()
        updated_fields.append("email_verified_at")
    if updated_fields:
        user.save(update_fields=updated_fields)

    return user, False
