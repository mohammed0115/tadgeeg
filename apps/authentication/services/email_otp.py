"""Email OTP generation, delivery, and verification services."""

from __future__ import annotations

import logging
import secrets
from dataclasses import dataclass
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import login as django_login
from django.contrib.auth.hashers import check_password, make_password
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.utils import timezone
from rest_framework_simplejwt.tokens import RefreshToken

from apps.authentication.models import EmailOTPVerification, User

PENDING_EMAIL_VERIFICATION_SESSION_KEY = "pending_email_verification_user_id"
logger = logging.getLogger("finai")


@dataclass(frozen=True)
class OTPConfig:
    length: int
    expiry_minutes: int
    resend_cooldown_seconds: int
    max_resend_attempts: int
    max_verify_attempts: int


class EmailOTPError(Exception):
    def __init__(self, message: str, code: str = "otp_error", wait_seconds: int = 0):
        super().__init__(message)
        self.message = message
        self.code = code
        self.wait_seconds = wait_seconds


def get_otp_config() -> OTPConfig:
    return OTPConfig(
        length=int(getattr(settings, "EMAIL_OTP_LENGTH", 6)),
        expiry_minutes=int(getattr(settings, "EMAIL_OTP_EXPIRY_MINUTES", 10)),
        resend_cooldown_seconds=int(getattr(settings, "EMAIL_OTP_RESEND_COOLDOWN_SECONDS", 60)),
        max_resend_attempts=int(getattr(settings, "EMAIL_OTP_MAX_RESEND_ATTEMPTS", 3)),
        max_verify_attempts=int(getattr(settings, "EMAIL_OTP_MAX_VERIFY_ATTEMPTS", 5)),
    )


def generate_otp_code(length: int | None = None) -> str:
    otp_length = length or get_otp_config().length
    return "".join(str(secrets.randbelow(10)) for _ in range(otp_length))


def _is_truthy(value) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _is_async_email_requested() -> bool:
    return _is_truthy(getattr(settings, "WASSLA_EMAIL_ASYNC_ENABLED", False))


def mask_email_address(email: str) -> str:
    local, _, domain = email.partition("@")
    if not domain:
        return email

    if len(local) <= 2:
        masked_local = f"{local[:1]}*"
    else:
        masked_local = f"{local[:2]}{'*' * max(2, len(local) - 2)}"

    return f"{masked_local}@{domain}"


def remember_pending_verification(request, user: User) -> None:
    request.session[PENDING_EMAIL_VERIFICATION_SESSION_KEY] = str(user.id)
    request.session.modified = True


def clear_pending_verification(request) -> None:
    if PENDING_EMAIL_VERIFICATION_SESSION_KEY in request.session:
        del request.session[PENDING_EMAIL_VERIFICATION_SESSION_KEY]
        request.session.modified = True


def get_pending_verification_user(request) -> User | None:
    if getattr(request, "user", None) and request.user.is_authenticated:
        if not getattr(request.user, "is_email_verified", False):
            return request.user
        clear_pending_verification(request)
        return None

    user_id = request.session.get(PENDING_EMAIL_VERIFICATION_SESSION_KEY)
    if not user_id:
        return None

    user = User.objects.filter(pk=user_id).first()
    if user is None:
        clear_pending_verification(request)
        return None
    if user.is_email_verified:
        clear_pending_verification(request)
        return None
    return user


def has_pending_verification(request) -> bool:
    return get_pending_verification_user(request) is not None


def get_latest_pending_challenge(user: User) -> EmailOTPVerification | None:
    return user.email_otp_verifications.filter(is_used=False).order_by("-created_at").first()


def get_challenge_state(challenge: EmailOTPVerification | None) -> dict:
    config = get_otp_config()
    now = timezone.now()

    resend_available_in = 0
    expires_in = 0
    resend_count = 0
    attempts_count = 0
    expires_at = None

    if challenge is not None:
        resend_count = challenge.resend_count
        attempts_count = challenge.attempts_count
        expires_at = challenge.expires_at
        resend_available_in = max(
            0,
            int((challenge.last_sent_at + timedelta(seconds=config.resend_cooldown_seconds) - now).total_seconds()),
        )
        expires_in = max(0, int((challenge.expires_at - now).total_seconds()))

    return {
        "challenge": challenge,
        "resend_available_in": resend_available_in,
        "expires_in": expires_in,
        "expires_at": expires_at,
        "resend_remaining": max(0, config.max_resend_attempts - resend_count),
        "attempts_remaining": max(0, config.max_verify_attempts - attempts_count),
    }


def reset_login_failures(user: User) -> None:
    user.failed_login_attempts = 0
    user.locked_until = None
    user.save(update_fields=["failed_login_attempts", "locked_until"])


def complete_verified_login(request, user: User) -> dict:
    user.last_login_ip = request.META.get("REMOTE_ADDR")
    user.last_login = timezone.now()
    user.failed_login_attempts = 0
    user.locked_until = None
    user.save(update_fields=["last_login_ip", "last_login", "failed_login_attempts", "locked_until"])

    django_login(request, user, backend="django.contrib.auth.backends.ModelBackend")
    clear_pending_verification(request)

    refresh = RefreshToken.for_user(user)
    return {
        "access": str(refresh.access_token),
        "refresh": str(refresh),
    }


def _invalidate_unused_challenges(user: User) -> None:
    user.email_otp_verifications.filter(is_used=False).update(
        is_used=True,
        used_at=timezone.now(),
    )


def _send_otp_email(user: User, otp_code: str, expires_at) -> None:
    config = get_otp_config()
    if _is_async_email_requested():
        logger.warning(
            "WASSLA_EMAIL_ASYNC_ENABLED is enabled, but OTP email delivery is falling back to synchronous send to guarantee delivery before returning success. user_id=%s email=%s",
            user.id,
            user.email,
        )

    logger.info(
        "Preparing OTP email for user_id=%s email=%s expires_at=%s",
        user.id,
        user.email,
        expires_at.isoformat(),
    )
    context = {
        "user": user,
        "otp_code": otp_code,
        "expires_minutes": config.expiry_minutes,
        "expires_at": expires_at,
        "product_name": "Tadgeeg",
    }
    html_body = render_to_string("auth/otp_email.html", context)
    text_body = (
        f"مرحباً {user.full_name or user.email}\n\n"
        f"رمز التحقق الخاص بك هو: {otp_code}\n"
        f"تنتهي صلاحية هذا الرمز خلال {config.expiry_minutes} دقائق.\n\n"
        "إذا لم تطلب هذا الرمز، يمكنك تجاهل هذه الرسالة بأمان."
    )
    email = EmailMultiAlternatives(
        subject="رمز التحقق من البريد الإلكتروني - Tadgeeg",
        body=text_body,
        from_email=getattr(settings, "DEFAULT_FROM_EMAIL", "noreply@finai.sa"),
        to=[user.email],
    )
    email.attach_alternative(html_body, "text/html")
    sent_count = email.send(fail_silently=False)
    if sent_count < 1:
        raise RuntimeError("OTP email backend reported zero messages sent.")

    logger.info(
        "OTP email sent successfully for user_id=%s email=%s sent_count=%s",
        user.id,
        user.email,
        sent_count,
    )


def issue_email_otp(user: User, request, *, allow_recent_reuse: bool = True) -> tuple[EmailOTPVerification, bool]:
    if user.is_email_verified:
        clear_pending_verification(request)
        raise EmailOTPError("تم التحقق من هذا البريد الإلكتروني بالفعل.", code="already_verified")

    config = get_otp_config()
    now = timezone.now()
    current = get_latest_pending_challenge(user)
    logger.info(
        "OTP issuance requested for user_id=%s email=%s allow_recent_reuse=%s has_current_challenge=%s",
        user.id,
        user.email,
        allow_recent_reuse,
        current is not None,
    )
    if (
        allow_recent_reuse
        and current is not None
        and not current.is_expired
        and (now - current.last_sent_at).total_seconds() < config.resend_cooldown_seconds
    ):
        logger.info(
            "Reusing existing OTP challenge challenge_id=%s user_id=%s email=%s",
            current.id,
            user.id,
            user.email,
        )
        remember_pending_verification(request, user)
        return current, False

    resend_count = current.resend_count if current is not None else 0
    _invalidate_unused_challenges(user)

    otp_code = generate_otp_code(config.length)
    challenge = EmailOTPVerification.objects.create(
        user=user,
        otp_code_hash=make_password(otp_code),
        expires_at=now + timedelta(minutes=config.expiry_minutes),
        resend_count=resend_count,
    )
    logger.info(
        "Created OTP challenge challenge_id=%s user_id=%s email=%s expires_at=%s resend_count=%s",
        challenge.id,
        user.id,
        user.email,
        challenge.expires_at.isoformat(),
        challenge.resend_count,
    )

    try:
        _send_otp_email(user, otp_code, challenge.expires_at)
    except Exception as exc:
        logger.exception(
            "OTP issue send failed for challenge_id=%s user_id=%s email=%s",
            challenge.id,
            user.id,
            user.email,
        )
        challenge.delete()
        raise EmailOTPError(
            "تعذر إرسال رمز التحقق حالياً. يرجى المحاولة مرة أخرى بعد قليل.",
            code="send_failed",
        ) from exc

    logger.info(
        "OTP issuance completed for challenge_id=%s user_id=%s email=%s",
        challenge.id,
        user.id,
        user.email,
    )
    remember_pending_verification(request, user)
    return challenge, True


def resend_email_otp(user: User, request) -> EmailOTPVerification:
    if user.is_email_verified:
        clear_pending_verification(request)
        raise EmailOTPError("تم التحقق من البريد الإلكتروني بالفعل.", code="already_verified")

    config = get_otp_config()
    current = get_latest_pending_challenge(user)
    resend_count = current.resend_count if current is not None else 0
    logger.info(
        "OTP resend requested for user_id=%s email=%s has_current_challenge=%s resend_count=%s",
        user.id,
        user.email,
        current is not None,
        resend_count,
    )

    if resend_count >= config.max_resend_attempts:
        raise EmailOTPError(
            "تم بلوغ الحد الأقصى لإعادة إرسال الرمز. حاول لاحقاً أو تواصل مع الدعم.",
            code="resend_limit",
        )

    if current is not None:
        wait_seconds = max(
            0,
            int((current.last_sent_at + timedelta(seconds=config.resend_cooldown_seconds) - timezone.now()).total_seconds()),
        )
        if wait_seconds > 0:
            raise EmailOTPError(
                f"يمكنك إعادة الإرسال بعد {wait_seconds} ثانية.",
                code="resend_cooldown",
                wait_seconds=wait_seconds,
            )

    _invalidate_unused_challenges(user)

    otp_code = generate_otp_code(config.length)
    challenge = EmailOTPVerification.objects.create(
        user=user,
        otp_code_hash=make_password(otp_code),
        expires_at=timezone.now() + timedelta(minutes=config.expiry_minutes),
        resend_count=resend_count + 1,
    )
    logger.info(
        "Created OTP resend challenge challenge_id=%s user_id=%s email=%s expires_at=%s resend_count=%s",
        challenge.id,
        user.id,
        user.email,
        challenge.expires_at.isoformat(),
        challenge.resend_count,
    )

    try:
        _send_otp_email(user, otp_code, challenge.expires_at)
    except Exception as exc:
        logger.exception(
            "OTP resend send failed for challenge_id=%s user_id=%s email=%s",
            challenge.id,
            user.id,
            user.email,
        )
        challenge.delete()
        raise EmailOTPError(
            "تعذر إعادة إرسال الرمز حالياً. يرجى المحاولة مرة أخرى بعد قليل.",
            code="send_failed",
        ) from exc

    logger.info(
        "OTP resend completed for challenge_id=%s user_id=%s email=%s",
        challenge.id,
        user.id,
        user.email,
    )
    remember_pending_verification(request, user)
    return challenge


def verify_email_otp(user: User, otp_code: str) -> User:
    if user.is_email_verified:
        return user

    config = get_otp_config()
    challenge = get_latest_pending_challenge(user)
    if challenge is None:
        raise EmailOTPError(
            "لا يوجد رمز تحقق نشط. أعد إرسال الرمز للمتابعة.",
            code="missing_otp",
        )

    if challenge.is_expired:
        challenge.is_used = True
        challenge.used_at = timezone.now()
        challenge.save(update_fields=["is_used", "used_at"])
        raise EmailOTPError(
            "انتهت صلاحية رمز التحقق. أعد إرسال رمز جديد للمتابعة.",
            code="otp_expired",
        )

    if challenge.attempts_count >= config.max_verify_attempts:
        challenge.is_used = True
        challenge.used_at = timezone.now()
        challenge.save(update_fields=["is_used", "used_at"])
        raise EmailOTPError(
            "تم تجاوز عدد المحاولات المسموح بها. أعد إرسال رمز جديد.",
            code="attempts_exceeded",
        )

    normalized_code = (otp_code or "").strip()
    if not check_password(normalized_code, challenge.otp_code_hash):
        challenge.attempts_count += 1
        update_fields = ["attempts_count"]
        if challenge.attempts_count >= config.max_verify_attempts:
            challenge.is_used = True
            challenge.used_at = timezone.now()
            update_fields.extend(["is_used", "used_at"])
            challenge.save(update_fields=update_fields)
            raise EmailOTPError(
                "الرمز غير صحيح وتم استنفاد جميع المحاولات. أعد إرسال رمز جديد.",
                code="attempts_exceeded",
            )

        challenge.save(update_fields=update_fields)
        remaining = config.max_verify_attempts - challenge.attempts_count
        raise EmailOTPError(
            f"رمز التحقق غير صحيح. تبقى لديك {remaining} محاولات.",
            code="otp_invalid",
        )

    challenge.is_used = True
    challenge.used_at = timezone.now()
    challenge.save(update_fields=["is_used", "used_at"])

    user.email_verified_at = timezone.now()
    user.save(update_fields=["email_verified_at"])
    return user
