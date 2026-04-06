"""Tadgeeg AI frontend page views."""

import secrets
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from urllib.parse import urlencode

from django.conf import settings as django_settings
from django.contrib.auth import logout
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.dateparse import parse_date
from django.utils.translation import gettext as _
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
        "missing_code": _("Unable to complete Google sign-in. Please try again."),
        "token_exchange_failed": _("Unable to validate the Google session right now. Please try again shortly."),
        "invalid_client": _("Google OAuth settings are currently invalid. Check the Client ID and Client Secret."),
        "invalid_grant": _("The Google sign-in code has expired or was already used. Start the flow again."),
        "redirect_uri_mismatch": _("The Google redirect URI does not match the current configuration. Verify GOOGLE_REDIRECT_URI."),
        "userinfo_failed": _("Unable to fetch the Google account profile. Please try again."),
        "no_email": _("The Google account does not provide an email address for registration."),
        "invalid_state": _("The Google sign-in session has expired. Please start again."),
        "inactive_user": _("This account is currently inactive. Contact your administrator."),
        "oauth_not_configured": _("Google sign-in is not configured right now."),
    }.get(code, _("Unable to sign in with Google right now. Please try again."))


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
        "can_manage_users": getattr(request.user, "can_manage_users", False),
        "can_generate_reports": getattr(request.user, "can_generate_reports", False),
        **extra,
    }


def _report_types():
    return [
        {
            "type": "invoice_audit",
            "lang": "ar",
            "label": _("Invoice Audit"),
            "desc": _("30 rules + risks + vendors"),
            "icon": "file-check-2",
            "bg": "bg-blue-100 dark:bg-blue-900/30",
            "color": "text-blue-600 dark:text-blue-400",
        },
        {
            "type": "executive_summary",
            "lang": "ar",
            "label": _("Executive Summary"),
            "desc": _("A concise view for leadership"),
            "icon": "bar-chart-3",
            "bg": "bg-violet-100 dark:bg-violet-900/30",
            "color": "text-violet-600 dark:text-violet-400",
        },
        {
            "type": "risk_assessment",
            "lang": "ar",
            "label": _("Risk Assessment"),
            "desc": _("High-risk invoices and vendors"),
            "icon": "shield-alert",
            "bg": "bg-red-100 dark:bg-red-900/30",
            "color": "text-red-600 dark:text-red-400",
        },
        {
            "type": "vendor_analysis",
            "lang": "ar",
            "label": _("Vendor Analysis"),
            "desc": _("Spending patterns and risk indicators"),
            "icon": "building-2",
            "bg": "bg-emerald-100 dark:bg-emerald-900/30",
            "color": "text-emerald-600 dark:text-emerald-400",
        },
        # ── Document-level audit report cards (one per document type) ──────────
        {
            "type": "document_audit_sales_invoice",
            "lang": "ar",
            "label": _("Sales Invoice Audit"),
            "desc": _("VAT, totals, and ZATCA compliance"),
            "icon": "receipt",
            "bg": "bg-indigo-100 dark:bg-indigo-900/30",
            "color": "text-indigo-600 dark:text-indigo-400",
        },
        {
            "type": "document_audit_purchase_order",
            "lang": "ar",
            "label": _("Purchase Order Audit"),
            "desc": _("Vendor, budget, and approval flow"),
            "icon": "package",
            "bg": "bg-orange-100 dark:bg-orange-900/30",
            "color": "text-orange-600 dark:text-orange-400",
        },
        {
            "type": "document_audit_bank_statement",
            "lang": "ar",
            "label": _("Bank Statement Audit"),
            "desc": _("Transactions, reconciliation, and Benford analysis"),
            "icon": "landmark",
            "bg": "bg-teal-100 dark:bg-teal-900/30",
            "color": "text-teal-600 dark:text-teal-400",
        },
        {
            "type": "document_audit_payroll",
            "lang": "ar",
            "label": _("Payroll Audit"),
            "desc": _("Salaries, deductions, and insurance compliance"),
            "icon": "users",
            "bg": "bg-pink-100 dark:bg-pink-900/30",
            "color": "text-pink-600 dark:text-pink-400",
        },
        {
            "type": "document_audit_expense_report",
            "lang": "ar",
            "label": _("Expense Report Audit"),
            "desc": _("Policy compliance, receipts, and categories"),
            "icon": "credit-card",
            "bg": "bg-amber-100 dark:bg-amber-900/30",
            "color": "text-amber-600 dark:text-amber-400",
        },
        {
            "type": "document_audit_vat_return",
            "lang": "ar",
            "label": _("VAT Return Audit"),
            "desc": _("Input/output tax and reconciliation"),
            "icon": "percent",
            "bg": "bg-cyan-100 dark:bg-cyan-900/30",
            "color": "text-cyan-600 dark:text-cyan-400",
        },
        {
            "type": "document_audit_fixed_asset",
            "lang": "ar",
            "label": _("Fixed Asset Audit"),
            "desc": _("Depreciation, disposal, and register checks"),
            "icon": "hard-drive",
            "bg": "bg-stone-100 dark:bg-stone-900/30",
            "color": "text-stone-600 dark:text-stone-400",
        },
        {
            "type": "document_audit_sales_receipt",
            "lang": "ar",
            "label": _("Sales Receipt Audit"),
            "desc": _("Payment, cash limits, and ZATCA QR"),
            "icon": "scroll-text",
            "bg": "bg-fuchsia-100 dark:bg-fuchsia-900/30",
            "color": "text-fuchsia-600 dark:text-fuchsia-400",
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
            _("A verification code has been sent to your email address.")
            if sent
            else _("An active verification code already exists. Please check your email.")
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
        return _("Unable to complete the request right now.")

    if isinstance(errors, dict):
        if flow == "login":
            if "email" in errors:
                first_email_error = _stringify_error(errors["email"])
                lowered = first_email_error.lower()
                if "valid email" in lowered:
                    return _("The email address is invalid.")
                if "no account found" in lowered or "not found" in lowered:
                    return _("No account was found for this email address.")
                return _("The email address or password is incorrect.")
            if "non_field_errors" in errors:
                first_non_field_error = _stringify_error(errors["non_field_errors"])
                lowered = first_non_field_error.lower()
                if "locked" in lowered:
                    return _("The account has been temporarily locked. Please try again later.")
                if "inactive" in lowered:
                    return _("This account is currently inactive.")
                return _("The email address or password is incorrect.")
        register_email_error = errors.get("email")
        if register_email_error:
            first_email_error = _stringify_error(register_email_error)
            lowered = first_email_error.lower()
            if "valid email" in lowered:
                return _("The email address is invalid.")
            return _("This email address is already in use.")
        if "email" in errors:
            return _("This email address is already in use.") if errors["email"] else _("The email address is invalid.")
        if "password" in errors:
            first_password_error = _stringify_error(errors["password"])
            if "match" in str(first_password_error).lower():
                return _("Passwords do not match.")
            return _("Please review the password and try again.")
        if "full_name" in errors:
            return _("Full name is required.")

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
        return _("Data was extracted automatically using local OCR. Some fields may still need human review.")
    return cleaned


def _risk_band(score):
    numeric_score = max(0.0, min(100.0, _to_float(score)))
    if numeric_score >= 70:
        return {
            "key": "high",
            "label_ar": _("High Risk"),
            "label_en": "High Risk",
            "badge_class": "badge-high",
            "text_class": "text-red-600 dark:text-red-400",
            "ring_color": "#ef4444",
        }
    if numeric_score >= 40:
        return {
            "key": "medium",
            "label_ar": _("Medium Risk"),
            "label_en": "Medium Risk",
            "badge_class": "badge-medium",
            "text_class": "text-amber-600 dark:text-amber-400",
            "ring_color": "#f59e0b",
        }
    return {
        "key": "low",
        "label_ar": _("Low Risk"),
        "label_en": "Low Risk",
        "badge_class": "badge-low",
        "text_class": "text-emerald-600 dark:text-emerald-400",
        "ring_color": "#22c55e",
    }


def _status_meta(status):
    mapping = {
        "approved": (_("Approved"), "status-approved"),
        "rejected": (_("Rejected"), "status-rejected"),
        "flagged": (_("Needs Review"), "status-flagged"),
        "validated": (_("Validated"), "status-validated"),
        "processing": (_("Processing"), "status-processing"),
        "pending": (_("Pending"), "status-pending"),
    }
    return mapping.get(status, (status or _("Unknown"), "status-pending"))


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
        _("Unspecified"),
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
        _("Data was extracted automatically. Review sensitive fields before final approval."),
    )
    extraction_method = _first_present(
        extracted.get("_extraction_method"),
        extracted.get("method"),
        text_fallback.get("_extraction_method"),
        "tesseract_fallback",
    )
    extraction_method_label = {
        "pdf_text_layer": _("PDF Text Layer"),
        "openai_vision": _("AI Vision (GPT-4o)"),
        "ocr_fallback": _("OCR Fallback (Tesseract)"),
        "openai_text": _("AI Text Extraction (GPT-4o)"),
        "openai_ocr": _("AI OCR (GPT-4o)"),
        "tesseract_fallback": _("OCR (Tesseract)"),
        "image_ai_vision": _("AI Vision (GPT-4o)"),
        "image_ocr": _("Image OCR"),
        "pdf_ocr": _("PDF OCR"),
        "excel_parser": _("Excel Parsing"),
        "json_parser": _("JSON Parsing"),
        "csv_parser": _("CSV Parsing"),
    }.get(extraction_method, _("Automatic Extraction"))

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


def _render_marketing_page(request, *, page_key, title, eyebrow, description, bullets):
    return render(
        request,
        "landing/page.html",
        _public_ctx(
            request,
            page_key=page_key,
            page_title=title,
            page_eyebrow=eyebrow,
            page_description=description,
            page_bullets=bullets,
        ),
    )


def pricing(request):
    return _render_marketing_page(
        request,
        page_key="pricing",
        title=_("Flexible plans for auditing and compliance teams"),
        eyebrow=_("Pricing"),
        description=_("Start quickly with a plan sized for your team, with a clear path to expand as document volume and workflows grow."),
        bullets=[
            _("Starter plan for small and mid-sized audit teams."),
            _("Enterprise plan with stronger tenant isolation and broader review workflows."),
            _("Gradual activation of advanced features such as executive reporting and integrations."),
        ],
    )


def about(request):
    return _render_marketing_page(
        request,
        page_key="about",
        title=_("A financial auditing platform built for the GCC market"),
        eyebrow=_("About %(product)s") % {"product": django_settings.PRODUCT_NAME},
        description=_("%(product)s focuses on auditing invoices and financial documents with tax and financial compliance support across GCC business environments.") % {"product": django_settings.PRODUCT_NAME},
        bullets=[
            _("Arabic and English support throughout the product journey."),
            _("A focus on ZATCA, VAT, and document review."),
            _("A practical experience for finance, audit, and compliance teams."),
        ],
    )


def contact(request):
    return _render_marketing_page(
        request,
        page_key="contact",
        title=_("Talk to the %(product)s team") % {"product": django_settings.PRODUCT_NAME},
        eyebrow=_("Contact"),
        description=_("If you need a tailored demo, enterprise onboarding, or technical guidance, our team can arrange an introductory session and rollout plan."),
        bullets=[
            _("Tailored responses for finance and compliance teams."),
            _("Support for pilot and enterprise launches."),
            _("Technical assistance and onboarding guidance."),
        ],
    )


def privacy(request):
    return _render_marketing_page(
        request,
        page_key="privacy",
        title=_("Privacy and data protection"),
        eyebrow=_("Privacy"),
        description=_("We handle financial data with a high standard of care, including clear tenant isolation and audit trails for sensitive actions."),
        bullets=[
            _("Organization-level data isolation."),
            _("Audit logs for sensitive operations."),
            _("Access controls based on organizational roles."),
        ],
    )


def blog(request):
    return _render_marketing_page(
        request,
        page_key="blog",
        title=_("Audit and compliance insights"),
        eyebrow=_("Insights"),
        description=_("A place to share operating insights and practical guidance on financial auditing, tax compliance, and digital transformation for finance teams."),
        bullets=[
            _("Best practices for reviewing invoices and vendors."),
            _("Updates on GCC compliance requirements."),
            _("Operational guides for enabling AI inside finance teams."),
        ],
    )


def integrations(request):
    return _render_marketing_page(
        request,
        page_key="integrations",
        title=_("Integrations that are ready and scalable"),
        eyebrow=_("Integrations"),
        description=_("Integration plans cover email, approval flows, and connectivity with your current finance operating environment."),
        bullets=[
            _("Gradual connectivity with your existing company systems."),
            _("Internal APIs that can be extended for integrations."),
            _("Tailored setup for organizations with specialized workflows."),
        ],
    )


def api_page(request):
    return _render_marketing_page(
        request,
        page_key="api",
        title=_("APIs ready for enterprise integration"),
        eyebrow=_("API"),
        description=_("%(product)s provides secure, organization-scoped APIs for document upload, session tracking, and access to audit results and reports.")
        % {"product": django_settings.PRODUCT_NAME},
        bullets=[
            _("API authentication with clear tenant isolation."),
            _("Endpoints for uploads, tracking, and reports."),
            _("Suitable for ERP systems and internal business portals."),
        ],
    )


def careers(request):
    return _render_marketing_page(
        request,
        page_key="careers",
        title=_("Working at %(product)s") % {"product": django_settings.PRODUCT_NAME},
        eyebrow=_("Careers"),
        description=_("We are building a financial product that demands precise execution, and we look for teams that combine technical depth with financial and regulatory understanding."),
        bullets=[
            _("Opportunities in engineering, product, and user experience."),
            _("A focus on trust-sensitive B2B products."),
            _("A practical environment for shipping real operational products."),
        ],
    )


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
            challenge, _sent = issue_email_otp(pending_user, request)
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
        payload["message"] = _("Your email address has been verified successfully.")
        return JsonResponse(payload)

    return render(request, "auth/otp_verify.html", context, status=initial_status)


@ensure_csrf_cookie
def otp_resend(request):
    if request.method != "POST":
        return redirect("frontend:otp_verify")

    pending_user = get_pending_verification_user(request)
    if pending_user is None:
        return JsonResponse({"success": False, "error": _("The verification session has expired. Please sign in again.")}, status=400)

    form = EmailOTPResendForm(request.POST)
    if not form.is_valid():
        return JsonResponse({"success": False, "error": _("Unable to resend the code right now.")}, status=400)

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
            "message": _("A new verification code has been sent to your email address."),
            "masked_email": mask_email_address(pending_user.email),
            "resend_cooldown_seconds": state["resend_available_in"],
            "otp_expires_in_seconds": state["expires_in"],
            "attempts_remaining": state["attempts_remaining"],
        }
    )


# ✅ PHASE 1 FIX: MFA Login Verification View 
@ensure_csrf_cookie
def mfa_login_verify(request):
    """
    Handle MFA verification during login flow.
    POST with temp_token + code → Issue full JWT tokens
    """
    if request.method != "POST":
        return JsonResponse({"error": _("Method not allowed")}, status=405)
    
    try:
        import json
        import pyotp
        from datetime import timedelta
        from django.utils import timezone
        from rest_framework_simplejwt.tokens import RefreshToken
        from apps.authentication.models import User, AuditLog
        from core.utils.audit import log_action
        
        data = json.loads(request.body)
        temp_token_str = data.get("temp_token", "").strip()
        totp_code = str(data.get("code", "")).strip()
        
        if not temp_token_str or not totp_code or len(totp_code) != 6:
            return JsonResponse(
                {"error": _("Temporary token and 6-digit TOTP code are required")},
                status=400
            )
        
        # Verify temporary token and get user
        try:
            temp_token = RefreshToken(temp_token_str)
            user_id = temp_token.get("user_id")
            user = User.objects.get(id=user_id)
        except Exception:
            return JsonResponse(
                {"error": _("Invalid or expired temporary token")},
                status=401
            )
        
        # Verify TOTP code
        if not user.mfa_enabled or not user.mfa_secret:
            return JsonResponse(
                {"error": _("MFA not enabled for this user")},
                status=400
            )
        
        totp = pyotp.TOTP(user.mfa_secret)
        if not totp.verify(totp_code, valid_window=1):
            # Track failed MFA attempts
            user.failed_login_attempts = (user.failed_login_attempts or 0) + 1
            if user.failed_login_attempts >= 5:
                user.locked_until = timezone.now() + timedelta(minutes=30)
            user.save()
            
            return JsonResponse(
                {"error": _("Invalid or expired TOTP code")},
                status=401
            )
        
        # MFA successful - issue full tokens
        user.failed_login_attempts = 0
        user.last_login = timezone.now()
        user.save()
        
        # Log the action
        log_action(request, AuditLog.Action.LOGIN, "user", str(user.id), details={"mfa": "verified"})
        
        # Generate JWT tokens
        refresh = RefreshToken.for_user(user)
        payload = {
            "success": True,
            "access": str(refresh.access_token),
            "refresh": str(refresh),
            "redirect": reverse("frontend:dashboard"),
            "message": _("Login successful!")
        }
        return JsonResponse(payload, status=200)
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return JsonResponse(
            {"error": _("An error occurred during MFA verification")},
            status=500
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


def _weight_for_rule(rule_code):
    prefix = (rule_code or "").split("-", 1)[0]
    if prefix in {"DUP", "VAT", "ANO"}:
        return "مرتفع"
    if prefix in {"INV", "CTL"}:
        return "متوسط"
    return "منخفض"


def _failed_rules_with_invoice_refs(top_failed_rules, validations):
    top_codes = [r.get("rule_code") for r in (top_failed_rules or []) if r.get("rule_code")]
    top_codes_set = set(top_codes)
    buckets = {code: [] for code in top_codes}

    for vr in validations:
        inv_no = vr.invoice.invoice_number or str(vr.invoice_id)[:8]
        for code in (vr.failed_rule_codes or []):
            if code not in top_codes_set:
                continue
            if inv_no not in buckets[code]:
                buckets[code].append(inv_no)

    enriched = []
    for rule in (top_failed_rules or []):
        code = rule.get("rule_code")
        invoice_numbers = buckets.get(code, [])
        enriched.append({
            "rule_code": code,
            "description": rule.get("description") or code,
            "failure_count": int(rule.get("failures") or 0),
            "invoice_numbers": invoice_numbers,
            "invoice_count": len(invoice_numbers),
        })
    return enriched


def _build_high_risk_violations(invoice_rows, validation_map, rule_catalog):
    rows = []
    for row in (invoice_rows or []):
        inv_id = row.get("id")
        vr = validation_map.get(inv_id)
        violations = []

        if vr:
            details = vr.validation_details or {}
            for code in (vr.failed_rule_codes or [])[:4]:
                detail = details.get(code, {}) if isinstance(details, dict) else {}
                reason = (
                    detail.get("reason")
                    or detail.get("message")
                    or detail.get("note")
                    or "تم رصد مخالفة لهذه القاعدة وتحتاج مراجعة تفصيلية."
                )
                violations.append({
                    "rule_code": code,
                    "description": rule_catalog.get(code, code),
                    "reason": reason,
                })

        score = float(row.get("risk_score") or 0)
        rows.append({
            "id": inv_id,
            "invoice_number": row.get("invoice_number") or "-",
            "amount": row.get("total_amount") or 0,
            "date": row.get("invoice_date") or "-",
            "risk_level": row.get("risk_level") or "low",
            "risk_score": score,
            "violations": violations,
        })

    return rows


@login_required(login_url="/login/")
def invoice_audit_report(request):
    from django.db.models import Avg, Count, Sum
    from apps.reports.models import Report
    from apps.invoices.models import InvoiceValidationResult
    from core.services.invoice_validator import RULES

    org = getattr(request.user, "organization", None)
    if not org:
        return redirect("frontend:reports")

    report_id = request.GET.get("report_id")
    report_obj = None
    base_qs = Report.objects.filter(organization=org, report_type="invoice_audit").order_by("-created_at")

    if report_id:
        report_obj = base_qs.filter(id=report_id).first()
    if not report_obj:
        report_obj = base_qs.first()

    # v2 reports (generated by InvoiceAuditReportService) have a "report_header" key
    # at the root of data — redirect to the dedicated v2 HTML view.
    if report_id and report_obj and isinstance(report_obj.data, dict) and "report_header" in report_obj.data:
        from django.shortcuts import redirect as _redirect
        return _redirect(f"/api/v1/reports/invoice-audit/{report_obj.id}/html/")

    raw_data = (report_obj.data or {}) if report_obj else {}
    source_data = raw_data.get("invoice_audit") if isinstance(raw_data.get("invoice_audit"), dict) else raw_data
    narrative = (report_obj.narrative or {}) if report_obj else {}

    validations = list(
        InvoiceValidationResult.objects.filter(invoice__organization=org)
        .select_related("invoice")
        .only("invoice_id", "invoice__invoice_number", "failed_rule_codes", "validation_details")
    )
    validation_map = {str(vr.invoice_id): vr for vr in validations}

    overall = source_data.get("overall_stats", {})
    validation_summary = source_data.get("validation_summary", {})
    top_risk = source_data.get("top_risk_invoices", [])
    vendor_rows = source_data.get("vendor_analysis", [])
    top_failed = source_data.get("top_failed_rules", [])

    compliance_agg = InvoiceValidationResult.objects.filter(invoice__organization=org).aggregate(
        invoices=Count("id"),
        rules_applied=Sum("total_rules"),
        rules_passed=Sum("rules_passed"),
        rules_failed=Sum("rules_failed"),
        avg_score=Avg("validation_score"),
    )
    rules_applied = int(compliance_agg.get("rules_applied") or 0)
    rules_passed = int(compliance_agg.get("rules_passed") or 0)
    rules_failed = int(compliance_agg.get("rules_failed") or 0)
    compliance_pct = round((rules_passed / rules_applied) * 100, 1) if rules_applied else 0

    risk_avg = float(overall.get("avg_risk_score") or 0)
    high_risk_count = int((overall.get("critical_count") or 0) + (overall.get("high_count") or 0))
    report_status = "عالي المخاطر" if risk_avg >= 70 or high_risk_count > 0 else "يحتاج مراجعة" if risk_avg >= 40 else "متوافق"

    failed_rules = _failed_rules_with_invoice_refs(top_failed, validations)
    high_risk_invoices = _build_high_risk_violations(top_risk, validation_map, RULES)

    dominant_vendor = vendor_rows[0] if vendor_rows else {}
    duplicate_count = int(overall.get("duplicate_count") or 0)
    missing_qr_count = int(overall.get("missing_qr_count") or 0)
    handwritten_count = int(overall.get("handwritten_count") or 0)
    new_vendor_count = int(overall.get("new_vendor_count") or 0)

    compliance_matrix = []
    for row in top_failed[:6]:
        compliance_matrix.append({
            "rule_code": row.get("rule_code"),
            "status": "مخالف",
            "weight": _weight_for_rule(row.get("rule_code")),
            "note": row.get("description") or "فشل متكرر يتطلب إجراء فوري.",
        })

    if not compliance_matrix:
        compliance_matrix = [
            {"rule_code": "INV-001", "status": "ممتثل", "weight": "متوسط", "note": "توفر رقم الفاتورة في معظم العينات."},
            {"rule_code": "VAT-002", "status": "ممتثل", "weight": "مرتفع", "note": "نسبة جيدة من صحة حساب الضريبة."},
            {"rule_code": "DUP-001", "status": "مخالف", "weight": "مرتفع", "note": "ظهرت حالات تكرار تحتاج تحقيق."},
        ]

    report_payload = {
        "title": "تقرير تدقيق الفواتير",
        "organization_name": getattr(org, "name", "-") or "-",
        "generated_at": report_obj.created_at if report_obj else datetime.now(),
        "report_type": "Invoice Audit Report",
        "status": report_status,
        "summary": {
            "total_invoices": int(overall.get("total_invoices") or 0),
            "total_amount": float(overall.get("total_amount") or 0),
            "compliance_rate": float(validation_summary.get("vat_compliance_pct") or compliance_pct),
            "avg_risk_score": risk_avg,
            "high_risk_invoices": high_risk_count,
            "duplicate_count": duplicate_count,
        },
        "executive_summary": {
            "conclusion": narrative.get("executive_summary") or "الصورة العامة تشير إلى ارتفاع نسبي في مخاطر الامتثال وتحتاج تدخل رقابي سريع.",
            "key_findings": [
                f"عدد الفواتير عالية المخاطر: {high_risk_count}",
                f"عدد الفواتير المكررة: {duplicate_count}",
                f"متوسط درجة المخاطر: {risk_avg:.1f}",
            ],
            "recommendations": [
                "إغلاق المخالفات ذات الأولوية العالية خلال دورة المراجعة الحالية.",
                "تفعيل مراجعة استباقية على قواعد التكرار وضريبة القيمة المضافة.",
                "رفع جودة بيانات الموردين لتقليل الإخفاقات المتكررة.",
            ],
        },
        "compliance_engine": {
            "rules_applied": rules_applied,
            "rules_passed": rules_passed,
            "rules_failed": rules_failed,
            "compliance_rate": compliance_pct,
            "rules_matrix": compliance_matrix,
        },
        "high_risk_invoices": high_risk_invoices,
        "failed_rules": failed_rules,
        "risk_analysis": {
            "avg_risk_score": risk_avg,
            "high": int((overall.get("critical_count") or 0) + (overall.get("high_count") or 0)),
            "review": int(overall.get("medium_count") or 0),
            "safe": int(overall.get("low_count") or 0),
        },
        "duplicates_anomalies": {
            "duplicates": duplicate_count,
            "dominant_vendor": dominant_vendor.get("vendor_name") or "-",
            "vendor_dependency_pct": float(dominant_vendor.get("spend_share_pct") or 0),
            "patterns": [
                {"label": "غياب رمز QR", "count": missing_qr_count, "severity": "high" if missing_qr_count else "low"},
                {"label": "فواتير بخط يدوي", "count": handwritten_count, "severity": "review" if handwritten_count else "low"},
                {"label": "موردون جدد غير معروفين", "count": new_vendor_count, "severity": "review" if new_vendor_count else "low"},
            ],
        },
        "vendor_analysis": vendor_rows,
        "recommendations": {
            "immediate": [
                "تصحيح فواتير QR غير المتوافقة قبل الإقفال المالي.",
                "مراجعة المورد المسيطر وتدقيق معاملات العينة عالية القيمة.",
                "التحقق من الرقم الضريبي للفواتير المرفوضة رقابيا.",
            ],
            "future": [
                "تطبيق مراقبة لحظية لقواعد التكرار قبل اعتماد الفاتورة.",
                "تحسين جودة الإدخال وتدريب الفريق على متطلبات الامتثال.",
                "إضافة حدود تنبيه تلقائية عند ارتفاع تركز الإنفاق على مورد واحد.",
            ],
        },
    }

    context = _ctx(
        request,
        "reports",
        report=report_payload,
        report_record=report_obj,
        today=date.today(),
    )
    return render(request, "reports/invoice_audit_report.html", context)


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
    if not getattr(request.user, "can_manage_users", False):
        return redirect("frontend:dashboard")
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


def robots_txt(request):
    from django.http import HttpResponse
    admin_url = getattr(django_settings, "ADMIN_URL", "admin/")
    content = (
        "User-agent: *\n"
        f"Disallow: /{admin_url}\n"
        "Disallow: /api/\n"
        "Disallow: /media/\n"
        "Allow: /\n\n"
        "Sitemap: https://www.tadgeeg.com/sitemap.xml\n"
    )
    return HttpResponse(content, content_type="text/plain")


def sitemap_xml(request):
    from django.http import HttpResponse
    content = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://www.tadgeeg.com/</loc><changefreq>weekly</changefreq><priority>1.0</priority></url>
  <url><loc>https://www.tadgeeg.com/login/</loc><changefreq>monthly</changefreq><priority>0.8</priority></url>
  <url><loc>https://www.tadgeeg.com/register/</loc><changefreq>monthly</changefreq><priority>0.8</priority></url>
  <url><loc>https://www.tadgeeg.com/about/</loc><changefreq>monthly</changefreq><priority>0.6</priority></url>
  <url><loc>https://www.tadgeeg.com/contact/</loc><changefreq>monthly</changefreq><priority>0.6</priority></url>
</urlset>"""
    return HttpResponse(content, content_type="application/xml")


def page_not_found(request, exception=None):
    return render(request, "404.html", status=404)


def server_error(request):
    return render(request, "500.html", status=500)
