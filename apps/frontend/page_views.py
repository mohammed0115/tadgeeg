"""FinAI frontend page views."""

import secrets
from datetime import datetime
from decimal import Decimal, InvalidOperation
from urllib.parse import urlencode

from django.conf import settings as django_settings
from django.contrib.auth import logout
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.dateparse import parse_date
from django.views.decorators.csrf import ensure_csrf_cookie

from apps.authentication.forms import EmailOTPResendForm, EmailOTPVerifyForm
from apps.authentication.serializers import LoginSerializer, RegisterSerializer
from apps.authentication.services.email_otp import (
    EmailOTPError,
    clear_pending_verification,
    complete_verified_login,
    get_challenge_state,
    get_latest_pending_challenge,
    get_pending_verification_user,
    has_pending_verification,
    issue_email_otp,
    mask_email_address,
    resend_email_otp,
    verify_email_otp,
)
from apps.authentication.services.google_oauth import (
    GoogleOAuthError,
    build_google_oauth_authorization_url,
    exchange_google_code_for_tokens,
    fetch_google_user_profile,
    get_or_create_local_user_from_google_profile,
    is_google_oauth_configured,
)


GOOGLE_OAUTH_STATE_SESSION_KEY = "google_oauth_state"
POST_LOGIN_TOKENS_SESSION_KEY = "post_login_tokens"


def _consume_post_login_tokens(request):
    if not getattr(request.user, "is_authenticated", False):
        return None
    tokens = request.session.pop(POST_LOGIN_TOKENS_SESSION_KEY, None)
    if tokens is not None:
        request.session.modified = True
    return tokens


def _google_auth_error_message(code: str) -> str:
    return {
        "missing_code": "تعذر إكمال تسجيل الدخول عبر Google. حاول مرة أخرى.",
        "token_exchange_failed": "تعذر التحقق من جلسة Google حالياً. حاول مرة أخرى بعد قليل.",
        "invalid_client": "إعدادات Google OAuth غير صحيحة حالياً. تحقق من Client ID و Client Secret في الإعدادات.",
        "invalid_grant": "رمز تسجيل الدخول من Google انتهت صلاحيته أو تم استخدامه بالفعل. ابدأ المحاولة من جديد.",
        "redirect_uri_mismatch": "عنوان العودة من Google لا يطابق الإعداد الحالي. تحقق من GOOGLE_REDIRECT_URI في Google Cloud.",
        "userinfo_failed": "تعذر جلب بيانات حساب Google. حاول مرة أخرى.",
        "no_email": "حساب Google لا يحتوي على بريد إلكتروني متاح للتسجيل.",
        "invalid_state": "انتهت جلسة تسجيل الدخول عبر Google. ابدأ المحاولة من جديد.",
        "inactive_user": "هذا الحساب غير نشط حالياً. تواصل مع المسؤول.",
        "oauth_not_configured": "تسجيل الدخول عبر Google غير مهيأ حالياً.",
    }.get(code, "تعذر تسجيل الدخول عبر Google حالياً. حاول مرة أخرى.")


def _redirect_to_login_with_auth_error(code: str):
    return redirect(f"{reverse('frontend:login')}?{urlencode({'auth_error': code})}")


def _ctx(request, active="dashboard", **extra):
    pending_count = 0
    try:
        from apps.invoices.models import Invoice

        organization = getattr(request.user, "organization", None)
        if organization:
            pending_count = Invoice.objects.filter(organization=organization, status="flagged").count()
    except Exception:
        pass
    return {
        "pending_count": pending_count,
        "active": active,
        "bootstrap_tokens": _consume_post_login_tokens(request),
        **extra,
    }


def _report_types():
    return [
        {
            "type": "invoice_audit",
            "lang": "ar",
            "label": "تدقيق الفواتير",
            "desc": "البنود الـ 30 + مخاطر + موردون",
            "icon": "file-check-2",
            "bg": "bg-blue-100 dark:bg-blue-900/30",
            "color": "text-blue-600 dark:text-blue-400",
        },
        {
            "type": "executive_summary",
            "lang": "ar",
            "label": "ملخص تنفيذي",
            "desc": "نظرة عامة للإدارة العليا",
            "icon": "bar-chart-3",
            "bg": "bg-violet-100 dark:bg-violet-900/30",
            "color": "text-violet-600 dark:text-violet-400",
        },
        {
            "type": "risk_assessment",
            "lang": "ar",
            "label": "تقرير المخاطر",
            "desc": "الفواتير والموردون الخطرون",
            "icon": "shield-alert",
            "bg": "bg-red-100 dark:bg-red-900/30",
            "color": "text-red-600 dark:text-red-400",
        },
        {
            "type": "vendor_analysis",
            "lang": "ar",
            "label": "تحليل الموردين",
            "desc": "أنماط الإنفاق ومؤشرات الخطر",
            "icon": "building-2",
            "bg": "bg-emerald-100 dark:bg-emerald-900/30",
            "color": "text-emerald-600 dark:text-emerald-400",
        },
    ]


def _public_ctx(request, **extra):
    auth_error = (request.GET.get("auth_error") or "").strip()
    return {
        "google_client_id": getattr(django_settings, "GOOGLE_CLIENT_ID", ""),
        "google_oauth_enabled": is_google_oauth_configured(),
        "auth_error": auth_error,
        "auth_error_message": _google_auth_error_message(auth_error) if auth_error else "",
        **extra,
    }


def _post_auth_redirect(user):
    return "/verify-email/" if not getattr(user, "is_email_verified", False) else "/dashboard/"


def _otp_error_status(error: EmailOTPError) -> int:
    if error.code in {"resend_cooldown", "resend_limit", "attempts_exceeded"}:
        return 429
    if error.code == "send_failed":
        return 503
    if error.code == "already_verified":
        return 409
    return 400


def _otp_pending_payload(user, challenge, *, sent: bool):
    state = get_challenge_state(challenge)
    return {
        "success": True,
        "requires_verification": True,
        "redirect": "/verify-email/",
        "masked_email": mask_email_address(user.email),
        "message": (
            "تم إرسال رمز تحقق إلى بريدك الإلكتروني."
            if sent
            else "يوجد رمز تحقق نشط بالفعل. يرجى التحقق من بريدك الإلكتروني."
        ),
        "otp_expires_in_seconds": state["expires_in"],
        "resend_cooldown_seconds": state["resend_available_in"],
        "attempts_remaining": state["attempts_remaining"],
    }


def _verified_login_payload(request, user):
    return {
        "success": True,
        "redirect": "/dashboard/",
        "tokens": complete_verified_login(request, user),
    }


def _stringify_error(value):
    if isinstance(value, list):
        return str(value[0]) if value else ""
    return str(value)


def _first_error(errors, *, flow="generic"):
    if not errors:
        return "تعذر إكمال العملية حالياً."

    if isinstance(errors, dict):
        if flow == "login":
            if "email" in errors:
                first_email_error = _stringify_error(errors["email"])
                lowered = first_email_error.lower()
                if "valid email" in lowered:
                    return "البريد الإلكتروني غير صالح."
                return "البريد الإلكتروني أو كلمة المرور غير صحيحة."
            if "non_field_errors" in errors:
                first_non_field_error = _stringify_error(errors["non_field_errors"])
                lowered = first_non_field_error.lower()
                if "locked" in lowered:
                    return "تم إيقاف الحساب مؤقتًا. حاول مرة أخرى لاحقًا."
                if "inactive" in lowered:
                    return "هذا الحساب غير نشط حاليًا."
                return "البريد الإلكتروني أو كلمة المرور غير صحيحة."
        register_email_error = errors.get("email")
        if register_email_error:
            first_email_error = _stringify_error(register_email_error)
            lowered = first_email_error.lower()
            if "valid email" in lowered:
                return "البريد الإلكتروني غير صالح."
            return "هذا البريد الإلكتروني مستخدم بالفعل."
        if "email" in errors:
            return "هذا البريد الإلكتروني مستخدم بالفعل." if errors["email"] else "البريد الإلكتروني غير صالح."
        if "password" in errors:
            first_password_error = _stringify_error(errors["password"])
            if "match" in str(first_password_error).lower():
                return "كلمتا المرور غير متطابقتين."
            return "يرجى التحقق من كلمة المرور والمحاولة مرة أخرى."
        if "full_name" in errors:
            return "الاسم الكامل مطلوب."

        first_key = next(iter(errors))
        first_value = errors[first_key]
        return _stringify_error(first_value)

    if isinstance(errors, list) and errors:
        return str(errors[0])

    return str(errors)


def _first_present(*values):
    for value in values:
        if value is None:
            continue
        if isinstance(value, str):
            stripped = value.strip()
            if stripped:
                return stripped
            continue
        return value
    return None


def _to_decimal(value):
    if value in (None, "", False):
        return None
    try:
        decimal_value = Decimal(str(value).replace(",", "").strip())
    except (InvalidOperation, ValueError, TypeError, AttributeError):
        return None
    return decimal_value


def _first_non_zero_amount(*values):
    for value in values:
        decimal_value = _to_decimal(value)
        if decimal_value is not None and decimal_value > 0:
            return decimal_value
    return None


def _to_float(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _coerce_date(value):
    if not value:
        return None
    if hasattr(value, "isoformat"):
        return value

    text = str(value).strip()
    parsed = parse_date(text)
    if parsed:
        return parsed

    for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%d/%m/%y", "%d-%m-%y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _clean_ai_summary(summary):
    cleaned = str(summary or "").strip()
    if not cleaned:
        return ""

    lowered = cleaned.lower()
    if "openai unavailable" in lowered or "openai not configured" in lowered:
        return "تم استخراج البيانات تلقائياً عبر OCR المحلي، وقد تحتاج بعض الحقول إلى مراجعة بشرية للتأكد."
    return cleaned


def _risk_band(score):
    numeric_score = max(0.0, min(100.0, _to_float(score)))
    if numeric_score >= 70:
        return {
            "key": "high",
            "label_ar": "خطر مرتفع",
            "label_en": "High Risk",
            "badge_class": "badge-high",
            "text_class": "text-red-600 dark:text-red-400",
            "ring_color": "#ef4444",
        }
    if numeric_score >= 40:
        return {
            "key": "medium",
            "label_ar": "خطر متوسط",
            "label_en": "Medium Risk",
            "badge_class": "badge-medium",
            "text_class": "text-amber-600 dark:text-amber-400",
            "ring_color": "#f59e0b",
        }
    return {
        "key": "low",
        "label_ar": "خطر منخفض",
        "label_en": "Low Risk",
        "badge_class": "badge-low",
        "text_class": "text-emerald-600 dark:text-emerald-400",
        "ring_color": "#22c55e",
    }


def _status_meta(status):
    mapping = {
        "approved": ("معتمدة", "status-approved"),
        "rejected": ("مرفوضة", "status-rejected"),
        "flagged": ("تحتاج مراجعة", "status-flagged"),
        "validated": ("مدققة", "status-validated"),
        "processing": ("قيد المعالجة", "status-processing"),
        "pending": ("قيد الانتظار", "status-pending"),
    }
    return mapping.get(status, (status or "غير معروف", "status-pending"))


def _build_invoice_display(invoice):
    extracted = invoice.extracted_data or {}
    validation = getattr(invoice, "validation", None)
    text_fallback = {}

    if invoice.raw_text:
        try:
            from core.services.invoice_ai_service import _fallback_extraction

            text_fallback = _fallback_extraction(invoice.raw_text)
        except Exception:
            text_fallback = {}

    audit_score = _to_float(getattr(validation, "validation_score", 0) or extracted.get("validation_score") or 0)
    risk_score = _to_float(invoice.risk_score, 0.0)
    if risk_score <= 0 and audit_score > 0:
        risk_score = round(max(0.0, min(100.0, 100.0 - audit_score)), 2)

    risk = _risk_band(risk_score)
    effective_status = invoice.status
    if invoice.status not in {"approved", "rejected"} and risk_score >= 70:
        effective_status = "flagged"
    status_label, status_badge_class = _status_meta(effective_status)

    vendor_name = _first_present(
        invoice.vendor_name,
        invoice.vendor_name_ar,
        extracted.get("vendor_name"),
        extracted.get("vendor_name_ar"),
        extracted.get("supplier_name"),
        extracted.get("merchant_name"),
        text_fallback.get("vendor_name"),
        text_fallback.get("vendor_name_ar"),
        "غير محدد",
    )
    vendor_vat_number = _first_present(
        invoice.vendor_vat_number,
        extracted.get("vendor_vat_number"),
        text_fallback.get("vendor_vat_number"),
        "",
    )
    invoice_number = _first_present(
        invoice.invoice_number,
        extracted.get("invoice_number"),
        text_fallback.get("invoice_number"),
        invoice.original_filename,
        str(invoice.id),
    )
    issue_date = _coerce_date(
        _first_present(invoice.invoice_date, extracted.get("invoice_date"), text_fallback.get("invoice_date"))
    )
    due_date = _coerce_date(
        _first_present(invoice.due_date, extracted.get("due_date"), text_fallback.get("due_date"))
    )
    currency = _first_present(invoice.currency, extracted.get("currency"), text_fallback.get("currency"), "SAR")
    subtotal = _first_non_zero_amount(invoice.subtotal, extracted.get("subtotal"), text_fallback.get("subtotal"))
    vat_amount = _first_non_zero_amount(invoice.vat_amount, extracted.get("vat_amount"), text_fallback.get("vat_amount"))
    total_amount = _first_non_zero_amount(invoice.total_amount, extracted.get("total_amount"), text_fallback.get("total_amount"))
    discount = _first_non_zero_amount(invoice.discount, extracted.get("discount"), text_fallback.get("discount"))
    vat_rate = _first_present(invoice.vat_rate, extracted.get("vat_rate"), text_fallback.get("vat_rate"), 15)

    if total_amount is None and subtotal is not None and vat_amount is not None:
        total_amount = subtotal + vat_amount - (discount or Decimal("0"))
    if subtotal is None and total_amount is not None and vat_amount is not None:
        subtotal = total_amount - vat_amount + (discount or Decimal("0"))

    ai_summary = _first_present(
        _clean_ai_summary(invoice.ai_summary),
        _clean_ai_summary(extracted.get("ai_summary")),
        _clean_ai_summary(text_fallback.get("ai_summary")),
        "تم استخراج البيانات تلقائياً، ويُنصح بمراجعة الحقول الحساسة قبل الاعتماد النهائي.",
    )
    extraction_method = _first_present(
        extracted.get("_extraction_method"),
        extracted.get("method"),
        text_fallback.get("_extraction_method"),
        "tesseract_fallback",
    )
    extraction_method_label = {
        "pdf_text_layer":  "طبقة نص PDF",
        "openai_vision":   "رؤية ذكية (GPT-4o)",
        "ocr_fallback":    "OCR احتياطي (Tesseract)",
        "openai_text":      "استخراج ذكي (GPT-4o نص)",
        "openai_ocr":       "تعرف ضوئي ذكي (GPT-4o)",
        "tesseract_fallback": "تعرف ضوئي (Tesseract)",
        "ocr_fallback":     "تعرف ضوئي محلي",
        "image_ai_vision":  "رؤية ذكية (GPT-4o)",
        "image_ocr":        "تعرف ضوئي على صورة",
        "pdf_ocr":          "تعرف ضوئي على PDF",
        "excel_parser":     "تحليل ملف Excel",
        "json_parser":      "تحليل ملف JSON",
        "csv_parser":       "تحليل ملف CSV",
    }.get(extraction_method, "استخراج تلقائي")

    def _format_amount(amount):
        if amount is None:
            return "—"
        try:
            return f"{Decimal(str(amount)):.2f} {currency}"
        except (InvalidOperation, TypeError, ValueError):
            return "—"

    def _format_date(date_value):
        return date_value.strftime("%Y-%m-%d") if date_value else "—"

    return {
        "vendor_name": vendor_name,
        "vendor_vat_number": vendor_vat_number,
        "invoice_number": invoice_number,
        "invoice_date": issue_date,
        "invoice_date_display": _format_date(issue_date),
        "due_date": due_date,
        "due_date_display": _format_date(due_date),
        "currency": currency,
        "subtotal": subtotal,
        "subtotal_display": _format_amount(subtotal),
        "vat_amount": vat_amount,
        "vat_amount_display": _format_amount(vat_amount),
        "total_amount": total_amount,
        "total_amount_display": _format_amount(total_amount),
        "discount": discount,
        "discount_display": _format_amount(discount),
        "vat_rate": _to_float(vat_rate, 15),
        "ocr_confidence": _to_float(invoice.ocr_confidence, 0.0),
        "risk_score": round(risk_score, 2),
        "risk_label_ar": risk["label_ar"],
        "risk_label_en": risk["label_en"],
        "risk_badge_class": risk["badge_class"],
        "risk_text_class": risk["text_class"],
        "risk_ring_color": risk["ring_color"],
        "validation_score": round(audit_score, 2),
        "rules_passed": int(getattr(validation, "rules_passed", 0) or 0),
        "rules_failed": int(getattr(validation, "rules_failed", 0) or 0),
        "status_label": status_label,
        "status_badge_class": status_badge_class,
        "effective_status": effective_status,
        "status_mismatch": effective_status != invoice.status,
        "source_method": extraction_method,
        "source_method_label": extraction_method_label,
        "ai_summary": ai_summary,
    }


def landing(request):
    return render(request, "landing/index.html", _public_ctx(request))


@ensure_csrf_cookie
def login_view(request):
    if request.user.is_authenticated:
        if not getattr(request.user, "is_email_verified", False):
            return redirect("frontend:otp_verify")
        return redirect("frontend:dashboard")

    if request.method == "GET" and has_pending_verification(request):
        return redirect("frontend:otp_verify")

    if request.method == "POST":
        serializer = LoginSerializer(
            data={
                "email": request.POST.get("email", "").strip(),
                "password": request.POST.get("password", ""),
            }
        )
        if not serializer.is_valid():
            return JsonResponse({"success": False, "error": _first_error(serializer.errors, flow="login")}, status=400)

        user = serializer.validated_data["user"]
        if not user.is_email_verified:
            try:
                challenge, sent = issue_email_otp(user, request)
            except EmailOTPError as exc:
                return JsonResponse(
                    {"success": False, "error": exc.message, "redirect": "/verify-email/"},
                    status=_otp_error_status(exc),
                )
            return JsonResponse(_otp_pending_payload(user, challenge, sent=sent))

        return JsonResponse(_verified_login_payload(request, user))
        return JsonResponse({"success": False, "error": "البريد الإلكتروني أو كلمة المرور غير صحيحة"})

    return render(request, "auth/portal.html", _public_ctx(request, auth_mode="login"))


@ensure_csrf_cookie
def register_view(request):
    if request.user.is_authenticated:
        if not getattr(request.user, "is_email_verified", False):
            return redirect("frontend:otp_verify")
        return redirect("frontend:dashboard")

    if request.method == "GET" and has_pending_verification(request):
        return redirect("frontend:otp_verify")

    if request.method == "POST":
        payload = {
            "full_name": request.POST.get("full_name", "").strip(),
            "email": request.POST.get("email", "").strip(),
            "password": request.POST.get("password", ""),
            "password_confirm": request.POST.get("password_confirm", ""),
        }

        organization_name = request.POST.get("organization_name", "").strip()
        if organization_name:
            payload["organization_name"] = organization_name

        serializer = RegisterSerializer(data=payload)
        if not serializer.is_valid():
            return JsonResponse({"success": False, "error": _first_error(serializer.errors, flow="register")}, status=400)

        user = serializer.save()
        try:
            challenge, sent = issue_email_otp(user, request)
        except EmailOTPError as exc:
            return JsonResponse(
                {"success": False, "error": exc.message, "redirect": "/verify-email/"},
                status=_otp_error_status(exc),
            )

        return JsonResponse(_otp_pending_payload(user, challenge, sent=sent))

    return render(request, "auth/portal.html", _public_ctx(request, auth_mode="register"))


def logout_view(request):
    clear_pending_verification(request)
    logout(request)
    return redirect("frontend:home")


def google_oauth_login(request):
    if request.user.is_authenticated:
        return redirect(_post_auth_redirect(request.user))

    try:
        state = secrets.token_urlsafe(32)
        request.session[GOOGLE_OAUTH_STATE_SESSION_KEY] = state
        request.session.modified = True
        return redirect(build_google_oauth_authorization_url(state))
    except GoogleOAuthError as exc:
        return _redirect_to_login_with_auth_error(exc.code)


def google_oauth_callback(request):
    if request.user.is_authenticated:
        return redirect(_post_auth_redirect(request.user))

    code = (request.GET.get("code") or "").strip()
    state = (request.GET.get("state") or "").strip()
    expected_state = request.session.pop(GOOGLE_OAUTH_STATE_SESSION_KEY, "")

    if not code:
        return _redirect_to_login_with_auth_error("missing_code")
    if not state or not expected_state or state != expected_state:
        return _redirect_to_login_with_auth_error("invalid_state")

    try:
        token_payload = exchange_google_code_for_tokens(code)
        profile = fetch_google_user_profile(token_payload["access_token"])
        user, _ = get_or_create_local_user_from_google_profile(profile)
    except GoogleOAuthError as exc:
        return _redirect_to_login_with_auth_error(exc.code)

    if not user.is_active:
        return _redirect_to_login_with_auth_error("inactive_user")

    request.session[POST_LOGIN_TOKENS_SESSION_KEY] = complete_verified_login(request, user)
    request.session.modified = True
    return redirect("frontend:dashboard")


def google_pending(request):
    if request.user.is_authenticated and request.user.is_email_verified:
        return redirect("frontend:dashboard")
    if has_pending_verification(request) or (request.user.is_authenticated and not request.user.is_email_verified):
        return redirect("frontend:otp_verify")
    return redirect("frontend:login")


@ensure_csrf_cookie
def otp_verify(request):
    pending_user = get_pending_verification_user(request)
    if pending_user is None:
        return redirect("frontend:login")

    if pending_user.is_email_verified:
        clear_pending_verification(request)
        return redirect("frontend:dashboard")

    challenge = get_latest_pending_challenge(pending_user)
    initial_status = 200
    initial_error_message = ""
    if challenge is None:
        try:
            challenge, _ = issue_email_otp(pending_user, request)
        except EmailOTPError as exc:
            initial_status = _otp_error_status(exc)
            initial_error_message = exc.message
            challenge = None

    state = get_challenge_state(challenge)
    form = EmailOTPVerifyForm(request.POST or None)
    context = _public_ctx(
        request,
        auth_mode="otp",
        otp_form=form,
        otp_user=pending_user,
        masked_email=mask_email_address(pending_user.email),
        resend_cooldown_seconds=state["resend_available_in"],
        otp_expires_in_seconds=state["expires_in"],
        otp_attempts_remaining=state["attempts_remaining"],
        otp_resend_remaining=state["resend_remaining"],
        error_message=initial_error_message,
    )

    if request.method == "POST":
        if not form.is_valid():
            error_message = _first_error(form.errors)
            if request.headers.get("X-Requested-With") == "XMLHttpRequest":
                return JsonResponse({"success": False, "error": error_message}, status=400)
            context["error_message"] = error_message
            return render(request, "auth/otp_verify.html", context, status=400)

        try:
            verify_email_otp(pending_user, form.cleaned_data["otp_code"])
        except EmailOTPError as exc:
            if request.headers.get("X-Requested-With") == "XMLHttpRequest":
                return JsonResponse({"success": False, "error": exc.message}, status=_otp_error_status(exc))
            context["error_message"] = exc.message
            return render(request, "auth/otp_verify.html", context, status=_otp_error_status(exc))

        payload = _verified_login_payload(request, pending_user)
        payload["message"] = "تم التحقق من بريدك الإلكتروني بنجاح."
        return JsonResponse(payload)

    return render(request, "auth/otp_verify.html", context, status=initial_status)


@ensure_csrf_cookie
def otp_resend(request):
    if request.method != "POST":
        return redirect("frontend:otp_verify")

    pending_user = get_pending_verification_user(request)
    if pending_user is None:
        return JsonResponse({"success": False, "error": "انتهت جلسة التحقق. سجّل الدخول مجدداً."}, status=400)

    form = EmailOTPResendForm(request.POST)
    if not form.is_valid():
        return JsonResponse({"success": False, "error": "تعذر إعادة إرسال الرمز حالياً."}, status=400)

    try:
        challenge = resend_email_otp(pending_user, request)
    except EmailOTPError as exc:
        return JsonResponse(
            {
                "success": False,
                "error": exc.message,
                "retry_after": exc.wait_seconds,
            },
            status=_otp_error_status(exc),
        )

    state = get_challenge_state(challenge)
    return JsonResponse(
        {
            "success": True,
            "message": "تم إرسال رمز جديد إلى بريدك الإلكتروني.",
            "masked_email": mask_email_address(pending_user.email),
            "resend_cooldown_seconds": state["resend_available_in"],
            "otp_expires_in_seconds": state["expires_in"],
            "attempts_remaining": state["attempts_remaining"],
        }
    )


@login_required(login_url="/login/")
def dashboard(request):
    return render(request, "dashboard/index.html", _ctx(request, "dashboard", monthly_growth=12))


@login_required(login_url="/login/")
def upload(request):
    return render(request, "invoices/upload.html", _ctx(request, "upload"))


@login_required(login_url="/login/")
def invoices(request):
    return render(request, "invoices/list.html", _ctx(request, "invoices"))


@login_required(login_url="/login/")
def invoice_detail(request, pk):
    try:
        from apps.invoices.models import Invoice, InvoiceAuditEvent

        organization = getattr(request.user, "organization", None)
        invoice = Invoice.objects.select_related("approved_by", "duplicate_of", "validation").get(pk=pk)
        if organization and invoice.organization != organization:
            return redirect("frontend:invoices")
        audit_trail = InvoiceAuditEvent.objects.filter(invoice=invoice).select_related("user").order_by("-timestamp")[:40]
    except Exception:
        return redirect("frontend:invoices")

    invoice_display = _build_invoice_display(invoice)
    return render(
        request,
        "invoices/detail_premium.html",
        _ctx(request, "invoices", invoice=invoice, invoice_display=invoice_display, audit_trail=audit_trail),
    )


@login_required(login_url="/login/")
def batches(request):
    return render(request, "invoices/batches.html", _ctx(request, "batches"))


@login_required(login_url="/login/")
def batch_detail(request, pk):
    return render(request, "invoices/batch_detail.html", _ctx(request, "batches", batch_id=str(pk)))


@login_required(login_url="/login/")
def audit_session_detail(request, pk):
    return render(request, "invoices/session_detail.html", _ctx(request, "batches", audit_session_id=str(pk)))


@login_required(login_url="/login/")
def reports(request):
    return render(request, "reports/index.html", _ctx(request, "reports", report_types=_report_types()))


@login_required(login_url="/login/")
def vendors(request):
    return render(request, "vendors/index.html", _ctx(request, "vendors"))


@login_required(login_url="/login/")
def analytics(request):
    return render(request, "analytics/index.html", _ctx(request, "analytics"))


@login_required(login_url="/login/")
def audit(request):
    return render(request, "audit/index.html", _ctx(request, "audit"))


@login_required(login_url="/login/")
def audit_detail(request, pk):
    return render(request, "audit/detail.html", _ctx(request, "audit", case_id=str(pk)))


@login_required(login_url="/login/")
def compliance(request):
    return render(request, "compliance/index.html", _ctx(request, "compliance"))


@login_required(login_url="/login/")
def documents(request):
    return render(request, "documents/index.html", _ctx(request, "documents"))


@login_required(login_url="/login/")
def transactions(request):
    return render(request, "transactions.html", _ctx(request, "transactions"))


@login_required(login_url="/login/")
def users(request):
    return render(request, "users/index.html", _ctx(request, "users"))


@login_required(login_url="/login/")
def settings(request):
    return render(request, "settings/index.html", _ctx(request, "settings"))


@login_required(login_url="/login/")
def doc_upload(request):
    return render(request, "documents/upload.html", _ctx(request, "documents", selected_type=request.GET.get("type", "")))


@login_required(login_url="/login/")
def purchase_orders(request):
    return render(request, "documents/purchase_orders.html", _ctx(request, "purchase_orders"))


@login_required(login_url="/login/")
def bank_statements(request):
    return render(request, "documents/bank_statements.html", _ctx(request, "bank_statements"))


@login_required(login_url="/login/")
def payroll(request):
    return render(request, "documents/payroll.html", _ctx(request, "payroll"))


@login_required(login_url="/login/")
def expense_reports(request):
    return render(request, "documents/expense_reports.html", _ctx(request, "expense_reports"))


@login_required(login_url="/login/")
def vat_returns(request):
    return render(request, "documents/vat_returns.html", _ctx(request, "vat_returns"))


@login_required(login_url="/login/")
def fixed_assets(request):
    return render(request, "documents/fixed_assets.html", _ctx(request, "fixed_assets"))


@login_required(login_url="/login/")
def sales_receipts(request):
    return render(request, "documents/sales_receipts.html", _ctx(request, "sales_receipts"))


@login_required(login_url="/login/")
def purchase_order_detail(request, pk):
    return render(request, "documents/detail/purchase_order_detail.html", _ctx(request, "purchase_orders", doc_id=str(pk)))


@login_required(login_url="/login/")
def bank_statement_detail(request, pk):
    return render(request, "documents/detail/bank_statement_detail.html", _ctx(request, "bank_statements", doc_id=str(pk)))


@login_required(login_url="/login/")
def payroll_detail(request, pk):
    return render(request, "documents/detail/payroll_detail.html", _ctx(request, "payroll", doc_id=str(pk)))


@login_required(login_url="/login/")
def expense_report_detail(request, pk):
    return render(request, "documents/detail/expense_report_detail.html", _ctx(request, "expense_reports", doc_id=str(pk)))


@login_required(login_url="/login/")
def vat_return_detail(request, pk):
    return render(request, "documents/detail/vat_return_detail.html", _ctx(request, "vat_returns", doc_id=str(pk)))


@login_required(login_url="/login/")
def fixed_asset_detail(request, pk):
    return render(request, "documents/detail/fixed_asset_detail.html", _ctx(request, "fixed_assets", doc_id=str(pk)))


@login_required(login_url="/login/")
def sales_receipt_detail(request, pk):
    return render(request, "documents/detail/sales_receipt_detail.html", _ctx(request, "sales_receipts", doc_id=str(pk)))
