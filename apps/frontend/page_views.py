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


def _paginate(qs, request, per_page=25):
    """Return (page_obj, page_kwargs) for any list view.

    `page_kwargs` carries the keys list templates expect:
      - rows / invoices: page-bound iterable (so `{% for r in rows %}` works)
      - page_obj:        Django Page object for pagination controls
      - paginator:       Paginator (also exposed for partials that want it)
      - per_page:        the size we used (so the template can show "showing N of M")
      - querystring:     the request querystring with `page` removed
                          (handy for keeping filters when changing page)
      - total_count:     paginator.count
    """
    from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger

    paginator = Paginator(qs, per_page)
    page_num = request.GET.get("page") or 1
    try:
        page_obj = paginator.page(page_num)
    except PageNotAnInteger:
        page_obj = paginator.page(1)
    except EmptyPage:
        page_obj = paginator.page(paginator.num_pages or 1)

    # Build a querystring without the `page` parameter so pagination links
    # preserve other filters (q/status/risk).
    qd = request.GET.copy()
    qd.pop("page", None)
    qs_str = qd.urlencode()

    return {
        "page_obj":     page_obj,
        "paginator":    paginator,
        "per_page":     per_page,
        "querystring":  qs_str,
        "total_count":  paginator.count,
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
    # (label_en, label_ar, badge_class)
    mapping = {
        "approved":   (_("Approved"),   "تمت الموافقة",  "status-approved"),
        "rejected":   (_("Rejected"),   "مرفوض",         "status-rejected"),
        "flagged":    (_("Needs Review"), "تحتاج مراجعة", "status-flagged"),
        "validated":  (_("Validated"),  "تم التحقق",     "status-validated"),
        "processing": (_("Processing"), "قيد المعالجة",  "status-processing"),
        "pending":    (_("Pending"),    "قيد الانتظار",  "status-pending"),
    }
    label_en, label_ar, badge = mapping.get(
        status, (status or _("Unknown"), status or "", "status-pending")
    )
    return label_en, label_ar, badge


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
    status_label, status_label_ar, status_badge_class = _status_meta(effective_status)

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

    # ── Risk-gate fields for approval scenarios ───────────────────────────────
    from apps.rule_engine.models import RiskScoreSummary  # lazy to avoid circular
    _risk_summary   = RiskScoreSummary.objects.filter(document_id=invoice.id).first()
    _has_blocking   = _risk_summary.blocks_approval   if _risk_summary else False
    _blocking_count = _risk_summary.blocking_failures if _risk_summary else 0
    _fraud_score    = float(_risk_summary.score_breakdown.get("fraud_score", 0)) if _risk_summary else 0.0
    _risk_level_key = _risk_summary.risk_level        if _risk_summary else "low"
    _blocking_rules = (
        [r for r in _risk_summary.top_failed_rules if r.get("rule_code")]
        if _risk_summary else []
    )
    _rules_passed_n = int(getattr(validation, "rules_passed", 0) or 0)
    _rules_failed_n = int(getattr(validation, "rules_failed", 0) or 0)
    _has_real_audit = (_rules_passed_n + _rules_failed_n) > 0
    _has_warnings   = _rules_failed_n > 0 and not _has_blocking
    _needs_senior   = not _has_blocking and (
        _fraud_score > 70 or _risk_level_key in ("high", "critical")
    )

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
        "rules_passed": _rules_passed_n,
        "rules_failed": _rules_failed_n,
        # ── Approval gate fields (7-scenario logic) ───────────────────────────
        "has_blocking":    _has_blocking,
        "blocking_count":  _blocking_count,
        "fraud_score":     _fraud_score,
        "risk_level":      _risk_level_key,
        "has_warnings":    _has_warnings,
        "needs_senior":    _needs_senior,
        "has_real_audit":  _has_real_audit,
        "blocking_rules":  _blocking_rules,
        # ─────────────────────────────────────────────────────────────────────
        "status_label": status_label,
        "status_label_ar": status_label_ar,
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
    if request.method == "GET" and request.GET.get("cancel") == "1":
        clear_pending_verification(request)
        return redirect("frontend:login")

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
    if request.method == "GET" and request.GET.get("cancel") == "1":
        clear_pending_verification(request)
        return redirect("frontend:register")

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
    """
    Wire the KPI cards / charts to real per-org aggregations instead of the
    hardcoded marketing copy that used to ship by default.
    """
    from datetime import timedelta
    from django.db.models import Count, Sum, Q
    from django.utils import timezone
    from apps.invoices.models import Invoice
    from apps.documents.typed_models import (
        PurchaseOrder, BankStatement, PayrollSheet, ExpenseReport,
        VATReturn, FixedAsset, SalesReceipt,
    )

    org = getattr(request.user, "organization", None)
    now = timezone.now()
    cutoff_30d = now - timedelta(days=30)
    cutoff_60d = now - timedelta(days=60)

    kpis = {
        "total_invoices": 0, "total_pos": 0, "total_amount": 0,
        "high_risk_count": 0, "fraud_alerts": 0, "compliance_alerts": 0,
        "pending_review": 0, "automation_pct": 0, "extraction_accuracy_pct": 0,
        "monthly_growth": 0, "vat_total": 0,
        "doc_counts": {},
    }
    recent_invoices = []
    risk_breakdown = {"low": 0, "medium": 0, "high": 0, "critical": 0}

    if org:
        inv_qs = Invoice.objects.filter(organization=org)
        po_qs  = PurchaseOrder.objects.filter(organization=org)

        inv_total = inv_qs.count()
        inv_30 = inv_qs.filter(created_at__gte=cutoff_30d).count()
        inv_prev30 = inv_qs.filter(created_at__gte=cutoff_60d, created_at__lt=cutoff_30d).count()

        kpis["total_invoices"] = inv_total
        kpis["total_pos"] = po_qs.count()
        kpis["total_amount"] = float(inv_qs.aggregate(s=Sum("total_amount"))["s"] or 0)
        kpis["vat_total"] = float(inv_qs.aggregate(s=Sum("vat_amount"))["s"] or 0)
        kpis["high_risk_count"] = inv_qs.filter(risk_level__in=["high", "critical"]).count()
        kpis["fraud_alerts"] = inv_qs.filter(Q(is_duplicate=True) | Q(status="flagged")).count()
        kpis["pending_review"] = inv_qs.filter(status__in=["pending", "processing"]).count()

        # Compliance alerts = anything failing structural validation
        kpis["compliance_alerts"] = inv_qs.filter(qr_code_valid=False).count()

        # Automation % — invoices that completed AI extraction without human edits
        # Approx: invoices with non-empty ai_summary AND no processing_error.
        automated = inv_qs.exclude(ai_summary="").filter(processing_error="").count()
        kpis["automation_pct"] = int((automated / inv_total) * 100) if inv_total else 0

        # Average extraction OCR confidence (0-100 scaled)
        avg_ocr = inv_qs.exclude(ocr_confidence=0).aggregate(a=Sum("ocr_confidence"))["a"] or 0
        with_ocr = inv_qs.exclude(ocr_confidence=0).count() or 1
        kpis["extraction_accuracy_pct"] = int(avg_ocr / with_ocr) if with_ocr else 0

        # Month-over-month growth
        if inv_prev30 > 0:
            kpis["monthly_growth"] = int(((inv_30 - inv_prev30) / inv_prev30) * 100)
        elif inv_30 > 0:
            kpis["monthly_growth"] = 100

        # Risk distribution for the chart
        for level, count in inv_qs.values_list("risk_level").annotate(c=Count("id")):
            if level in risk_breakdown:
                risk_breakdown[level] = count

        # Recent activity (last 8 invoices)
        recent_invoices = list(
            inv_qs.order_by("-created_at")[:8].values(
                "id", "invoice_number", "vendor_name", "total_amount",
                "currency", "status", "risk_level", "created_at",
            )
        )

        # Document type counts (so the dashboard cards line up with /documents/)
        kpis["doc_counts"] = {
            "invoices":         inv_total,
            "purchase_orders":  kpis["total_pos"],
            "bank_statements":  BankStatement.objects.filter(organization=org).count(),
            "payroll":          PayrollSheet.objects.filter(organization=org).count(),
            "expense_reports":  ExpenseReport.objects.filter(organization=org).count(),
            "vat_returns":      VATReturn.objects.filter(organization=org).count(),
            "fixed_assets":     FixedAsset.objects.filter(organization=org).count(),
            "sales_receipts":   SalesReceipt.objects.filter(organization=org).count(),
        }

    return render(request, "dashboard/index.html", _ctx(
        request, "dashboard",
        kpis=kpis,
        risk_breakdown=risk_breakdown,
        recent_invoices=recent_invoices,
        monthly_growth=kpis["monthly_growth"],
    ))


@login_required(login_url="/login/")
def upload(request):
    return render(request, "invoices/upload.html", _ctx(request, "upload"))


@login_required(login_url="/login/")
def invoices(request):
    """List invoices for the current user's organization, with optional filters."""
    from apps.invoices.models import Invoice

    org = getattr(request.user, "organization", None)
    qs = Invoice.objects.all()
    if org:
        qs = qs.filter(organization=org)
    qs = qs.select_related("organization").order_by("-created_at")

    # Optional filters
    status_filter = (request.GET.get("status") or "").strip().lower()
    if status_filter and status_filter != "all":
        qs = qs.filter(status=status_filter)

    risk_filter = (request.GET.get("risk") or "").strip().lower()
    if risk_filter and risk_filter != "all":
        qs = qs.filter(risk_level=risk_filter)

    search = (request.GET.get("q") or "").strip()
    if search:
        from django.db.models import Q
        qs = qs.filter(
            Q(invoice_number__icontains=search)
            | Q(vendor_name__icontains=search)
            | Q(vendor_name_ar__icontains=search)
        )

    # Paginate — 25 per page is a good balance for a dense table.
    page_kwargs = _paginate(qs, request, per_page=25)
    invoices_list = list(page_kwargs["page_obj"].object_list)

    # Status counters for the tab pills (full org scope, not filtered)
    counters = {"all": 0, "pending": 0, "approved": 0, "flagged": 0, "rejected": 0}
    counter_qs = Invoice.objects.filter(organization=org) if org else Invoice.objects.all()
    counters["all"] = counter_qs.count()
    for s in ("pending", "approved", "flagged", "rejected"):
        counters[s] = counter_qs.filter(status=s).count()

    return render(
        request,
        "invoices/list.html",
        _ctx(
            request,
            "invoices",
            invoices=invoices_list,
            counters=counters,
            search=search,
            status_filter=status_filter or "all",
            risk_filter=risk_filter or "all",
            **page_kwargs,
        ),
    )


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

    invoice_display   = _build_invoice_display(invoice)
    user_can_override = request.user.has_perm("invoices.can_override_approval")
    return render(
        request,
        "invoices/detail_premium.html",
        _ctx(
            request, "invoices",
            invoice=invoice,
            invoice_display=invoice_display,
            audit_trail=audit_trail,
            user_can_override=user_can_override,
        ),
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
    return render(request, "reports/index.html", _ctx(request, "reports", report_types=_report_types(), selected_type=request.GET.get("type", "invoice")))


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
    """Enrich each high-risk invoice with its full violation list (severity-aware).

    Each invoice row carries every failed rule (not just the first 4) so an
    auditor can see the complete picture for the document. Violations include
    severity so the template can color-code per-row severity badges.
    """
    from apps.reports.services.findings_service import severity_for, recommendation_for

    rows = []
    for row in (invoice_rows or []):
        inv_id = row.get("id")
        vr = validation_map.get(inv_id)
        violations = []

        if vr:
            details = vr.validation_details or {}
            for code in (vr.failed_rule_codes or []):  # ALL violations, not just first 4
                detail = details.get(code, {}) if isinstance(details, dict) else {}
                reason = (
                    detail.get("reason")
                    or detail.get("message")
                    or detail.get("note")
                    or str(rule_catalog.get(code, code))
                )
                violations.append({
                    "rule_code": code,
                    "description": rule_catalog.get(code, code),
                    "reason": reason,
                    "severity": severity_for(code),
                    "recommendation": str(recommendation_for(code)),
                })

        score = float(row.get("risk_score") or 0)
        rows.append({
            "id": inv_id,
            "invoice_number": row.get("invoice_number") or "-",
            "vendor_name": row.get("vendor_name") or "",
            "amount": row.get("total_amount") or 0,
            "currency": row.get("currency") or "SAR",
            "date": row.get("invoice_date") or "-",
            "risk_level": row.get("risk_level") or "low",
            "risk_score": score,
            "violations": violations,
            "violation_count": len(violations),
        })

    return rows


# Sections that each report kind should expose. Used by the template to
# conditionally render content. "audit_summary" is the canonical full report.
_REPORT_KIND_SECTIONS = {
    "audit_summary": {"executive", "compliance", "high_risk", "failed_rules", "risk", "duplicates", "vendor", "recommendations", "rule_engine"},
    "risk_analysis": {"executive", "risk", "high_risk", "duplicates"},
    "compliance":    {"executive", "compliance", "rule_engine"},
    "vendor":        {"executive", "vendor", "high_risk"},
    "trend":         {"executive", "risk", "vendor"},
    "isa700":        {"executive", "isa700", "compliance", "recommendations"},
}

# Pretty labels for each kind, shown in the report header.
_REPORT_KIND_LABELS = {
    "audit_summary": ("تقرير التدقيق الشامل", "Full Audit Summary"),
    "risk_analysis": ("تحليل المخاطر", "Risk Analysis"),
    "compliance":    ("تقرير الامتثال", "Compliance Report"),
    "vendor":        ("تحليل الموردين", "Vendor Analysis"),
    "trend":         ("تحليل الاتجاهات", "Trend Analysis"),
    "isa700":        ("ISA 700 Opinion", "ISA 700 Opinion"),
}

# Document type → display label. Used when type ≠ invoice to show a friendly
# banner. Wrapped in gettext_lazy so the localized form is picked up on
# dereference — this keeps strings like "Total Purchase Orders" properly
# translated in narrative text. Use the canonical name `gettext_lazy` so
# Django's makemessages xgettext pass recognises the call.
from django.utils.translation import gettext_lazy
_DOC_TYPE_LABELS = {
    # Original 8 types
    "invoice":            gettext_lazy("Invoices"),
    "purchase_order":     gettext_lazy("Purchase Orders"),
    "bank_statement":     gettext_lazy("Bank Statements"),
    "payroll":            gettext_lazy("Payroll"),
    "expense_report":     gettext_lazy("Expense Reports"),
    "vat_return":         gettext_lazy("VAT Returns"),
    "tax_declaration":    gettext_lazy("VAT Returns"),
    "fixed_asset":        gettext_lazy("Fixed Assets"),
    "sales_receipt":      gettext_lazy("Sales Receipts"),
    # Phase-1 additions (10 new types)
    "sales_invoice":      gettext_lazy("Sales Invoices"),
    "purchase_invoice":   gettext_lazy("Purchase Invoices"),
    "sales_order":        gettext_lazy("Sales Orders"),
    "quotation":          gettext_lazy("Quotations"),
    "proforma_invoice":   gettext_lazy("Proforma Invoices"),
    "grn":                gettext_lazy("Goods Receipt Notes"),
    "payment_voucher":    gettext_lazy("Payment Vouchers"),
    "receipt_voucher":    gettext_lazy("Receipt Vouchers"),
    "cash_voucher":       gettext_lazy("Cash Vouchers"),
    "journal_entry":      gettext_lazy("Journal Entries"),
    "general_ledger":     gettext_lazy("General Ledgers"),
    "ledger":             gettext_lazy("Ledgers"),
    "contract":           gettext_lazy("Contracts"),
    "tax_vat_document":   gettext_lazy("Tax / VAT Documents"),
    "supplier_statement": gettext_lazy("Supplier Statements"),
    "customer_statement": gettext_lazy("Customer Statements"),
}

# Singular noun for "Total {type}" KPI / heading copy. Wrapped in
# gettext_lazy (already imported above) so makemessages picks them up and
# the template gets the right localized form via `{{ type_singular }}`.
_DOC_TYPE_SINGULAR = {
    # Original 8 types
    "invoice":            gettext_lazy("Invoice"),
    "purchase_order":     gettext_lazy("Purchase Order"),
    "bank_statement":     gettext_lazy("Bank Statement"),
    "payroll":            gettext_lazy("Payroll Sheet"),
    "expense_report":     gettext_lazy("Expense Report"),
    "vat_return":         gettext_lazy("VAT Return"),
    "tax_declaration":    gettext_lazy("VAT Return"),
    "fixed_asset":        gettext_lazy("Fixed Asset"),
    "sales_receipt":      gettext_lazy("Sales Receipt"),
    # Phase-1 additions
    "sales_invoice":      gettext_lazy("Sales Invoice"),
    "purchase_invoice":   gettext_lazy("Purchase Invoice"),
    "sales_order":        gettext_lazy("Sales Order"),
    "quotation":          gettext_lazy("Quotation"),
    "proforma_invoice":   gettext_lazy("Proforma Invoice"),
    "grn":                gettext_lazy("Goods Receipt Note"),
    "payment_voucher":    gettext_lazy("Payment Voucher"),
    "receipt_voucher":    gettext_lazy("Receipt Voucher"),
    "cash_voucher":       gettext_lazy("Cash Voucher"),
    "journal_entry":      gettext_lazy("Journal Entry"),
    "general_ledger":     gettext_lazy("General Ledger"),
    "ledger":             gettext_lazy("Ledger"),
    "contract":           gettext_lazy("Contract"),
    "tax_vat_document":   gettext_lazy("Tax / VAT Document"),
    "supplier_statement": gettext_lazy("Supplier Statement"),
    "customer_statement": gettext_lazy("Customer Statement"),
}

# Per-type report title for <title>, breadcrumb, and report header.
_DOC_TYPE_REPORT_TITLE = {
    # Original 8 types
    "invoice":            gettext_lazy("Invoice Audit Report"),
    "purchase_order":     gettext_lazy("Purchase Order Audit Report"),
    "bank_statement":     gettext_lazy("Bank Statement Audit Report"),
    "payroll":            gettext_lazy("Payroll Audit Report"),
    "expense_report":     gettext_lazy("Expense Report Audit"),
    "vat_return":         gettext_lazy("VAT Return Audit Report"),
    "tax_declaration":    gettext_lazy("VAT Return Audit Report"),
    "fixed_asset":        gettext_lazy("Fixed Asset Audit Report"),
    "sales_receipt":      gettext_lazy("Sales Receipt Audit Report"),
    # Phase-1 additions
    "sales_invoice":      gettext_lazy("Sales Invoice Audit Report"),
    "purchase_invoice":   gettext_lazy("Purchase Invoice Audit Report"),
    "sales_order":        gettext_lazy("Sales Order Audit Report"),
    "quotation":          gettext_lazy("Quotation Audit Report"),
    "proforma_invoice":   gettext_lazy("Proforma Invoice Audit Report"),
    "grn":                gettext_lazy("Goods Receipt Note Audit Report"),
    "payment_voucher":    gettext_lazy("Payment Voucher Audit Report"),
    "receipt_voucher":    gettext_lazy("Receipt Voucher Audit Report"),
    "cash_voucher":       gettext_lazy("Cash Voucher Audit Report"),
    "journal_entry":      gettext_lazy("Journal Entry Audit Report"),
    "general_ledger":     gettext_lazy("General Ledger Audit Report"),
    "ledger":             gettext_lazy("Ledger Audit Report"),
    "contract":           gettext_lazy("Contract Audit Report"),
    "tax_vat_document":   gettext_lazy("Tax / VAT Document Audit Report"),
    "supplier_statement": gettext_lazy("Supplier Statement Audit Report"),
    "customer_statement": gettext_lazy("Customer Statement Audit Report"),
}


@login_required(login_url="/login/")
def invoice_audit_report(request):
    from django.db.models import Avg, Count, Sum
    from apps.reports.models import Report
    from apps.invoices.models import InvoiceValidationResult
    from core.services.invoice_validator import RULES

    org = getattr(request.user, "organization", None)
    if not org:
        return redirect("frontend:reports")

    # ── Read query params ──────────────────────────────────────────────────
    selected_kind = request.GET.get("kind", "audit_summary").lower()
    if selected_kind not in _REPORT_KIND_SECTIONS:
        selected_kind = "audit_summary"

    selected_type = (request.GET.get("type") or "invoice").lower()
    type_label = _DOC_TYPE_LABELS.get(selected_type, "Documents")
    is_invoice_report = selected_type in ("invoice", "")

    # Per-doc-type detail URL prefix. The Findings Register and high-risk
    # invoices table use this to deep-link to the right detail page —
    # /invoices/<uuid>/ for invoices, /documents/<slug>/<uuid>/ for everything
    # else. Always end with a trailing slash since the views expect it.
    _DOC_DETAIL_PREFIX = {
        # Original 8
        "invoice":            "/invoices/",
        "purchase_order":     "/documents/purchase-orders/",
        "bank_statement":     "/documents/bank-statements/",
        "payroll":            "/documents/payroll/",
        "expense_report":     "/documents/expense-reports/",
        "vat_return":         "/documents/vat-returns/",
        "fixed_asset":        "/documents/fixed-assets/",
        "sales_receipt":      "/documents/sales-receipts/",
        # Phase-2 — list pages don't exist yet (Phase 4); detail URLs will be
        # added when each type gets its UI surface. For now the deep-link
        # falls back to the audit-cases page so users always land somewhere
        # sensible.
        "sales_invoice":      "/invoices/",
        "purchase_invoice":   "/invoices/",
        "sales_order":        "/audit/",
        "quotation":          "/audit/",
        "proforma_invoice":   "/audit/",
        "grn":                "/audit/",
        "payment_voucher":    "/audit/",
        "receipt_voucher":    "/audit/",
        "cash_voucher":       "/audit/",
        "journal_entry":      "/audit/",
        "general_ledger":     "/audit/",
        "ledger":             "/audit/",
        "contract":           "/audit/",
        "tax_vat_document":   "/audit/",
        "supplier_statement": "/audit/",
        "customer_statement": "/audit/",
    }
    detail_url_prefix = _DOC_DETAIL_PREFIX.get(selected_type, "/audit/")
    # `is_first_class_report` covers any doc type whose data source we can
    # fully populate — invoices natively, plus every type the multi-doc
    # adapter knows how to handle. The "coming soon" banner only renders
    # when neither path is available.
    from apps.reports.services.multi_doc_audit_adapter import is_supported as _multi_doc_supported
    is_first_class_report = is_invoice_report or _multi_doc_supported(selected_type)

    sections = _REPORT_KIND_SECTIONS[selected_kind]
    kind_label_ar, kind_label_en = _REPORT_KIND_LABELS[selected_kind]

    # ── Find latest report record for this org ─────────────────────────────
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

    # ── Pick data source based on doc type ────────────────────────────────
    # Invoices use the rich `InvoiceValidationResult` (failed_rule_codes array
    # + validation_details map). Other doc types use per-type validation
    # models with boolean fields, surfaced through the multi-doc adapter.
    from apps.reports.services.multi_doc_audit_adapter import build_for_doc_type, is_supported

    multi_doc_payload = None
    if selected_type and selected_type != "invoice" and is_supported(selected_type):
        multi_doc_payload = build_for_doc_type(org, selected_type)

    if multi_doc_payload is not None:
        # Multi-doc path: synthesize the same shape `_failed_rules_with_invoice_refs`
        # and `_build_high_risk_violations` already consume.
        validations = multi_doc_payload["validations"]
        validation_map = {str(v.invoice.id): v for v in validations}
        top_risk = multi_doc_payload["top_risk"]
        top_failed = multi_doc_payload["top_failed"]
        rules_applied = multi_doc_payload["rules_applied"]
        rules_passed = multi_doc_payload["rules_passed"]
        rules_failed = multi_doc_payload["rules_failed"]
        compliance_pct = multi_doc_payload["compliance_pct"]
        total_invoices = multi_doc_payload["documents"]
        # Use the doc-type-specific rule catalog so high-risk violation
        # tooltips render the right title (e.g. PO-008 → "يوجد موافق على الأمر").
        active_rule_catalog = multi_doc_payload["rule_catalog"]
        risk_avg = round(
            sum(r.get("risk_score", 0) for r in top_risk) / len(top_risk), 1
        ) if top_risk else 0
        high_risk_count = sum(1 for r in top_risk if r["risk_level"] in ("high", "critical"))
        overall = {}
        validation_summary = {}
        # Live counterparty/vendor analysis from the doc model — replaces the
        # previous hardcoded empty list so the "Vendor Analysis" section shows
        # real spend distribution per vendor for PO/Receipt/etc.
        vendor_rows = multi_doc_payload.get("vendor_analysis", [])
    else:
        # Invoice path (default).
        validations = list(
            InvoiceValidationResult.objects.filter(invoice__organization=org)
            .select_related("invoice")
            .only(
                "invoice_id", "invoice__invoice_number", "invoice__total_amount",
                "invoice__vendor_name", "invoice__invoice_date",
                "failed_rule_codes", "validation_details",
            )
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

        total_invoices = int(overall.get("total_invoices") or 0)
        risk_avg = float(overall.get("avg_risk_score") or 0)
        high_risk_count = int((overall.get("critical_count") or 0) + (overall.get("high_count") or 0))
        active_rule_catalog = RULES

    # ── Live risk distribution + duplicates (works on both paths) ──────────
    # The saved report's `overall_stats` is often empty / stale. Compute the
    # risk-level distribution and the duplicate count directly from the
    # active doc model so the "Risk Analysis" and "Duplicates" sections
    # always reflect what's actually in the database.
    risk_dist_live = {"critical": 0, "high": 0, "medium": 0, "low": 0}
    duplicate_count_live = 0
    if multi_doc_payload is not None:
        # Sum across the multi-doc validation rows we already loaded.
        for v in validations:
            lvl = (v.invoice.risk_level or "low").lower()
            if lvl in risk_dist_live:
                risk_dist_live[lvl] += 1
        # Document models other than Invoice don't have an `is_duplicate`
        # boolean — count duplicate rule codes (DUP-* / *DUPLICATE*) instead.
        for v in validations:
            if any("DUP" in (c or "").upper() for c in (v.failed_rule_codes or [])):
                duplicate_count_live += 1
    else:
        # Invoice path — query the live tables.
        from apps.invoices.models import Invoice
        risk_qs = Invoice.objects.filter(organization=org).values("risk_level").annotate(n=Count("id"))
        for r in risk_qs:
            lvl = (r["risk_level"] or "low").lower()
            if lvl in risk_dist_live:
                risk_dist_live[lvl] += int(r["n"])
        duplicate_count_live = Invoice.objects.filter(organization=org, is_duplicate=True).count()

    # Live average risk score (across all docs in the active path).
    if multi_doc_payload is not None:
        scores = [v.invoice.risk_score for v in validations
                  if getattr(v.invoice, "risk_score", None) is not None]
        risk_avg_live = round(sum(scores) / len(scores), 1) if scores else 0
    else:
        from apps.invoices.models import Invoice
        risk_avg_live = float(
            Invoice.objects.filter(organization=org).aggregate(a=Avg("risk_score")).get("a") or 0
        )

    # Promote live values when the saved report didn't carry them.
    if not high_risk_count:
        high_risk_count = risk_dist_live["high"] + risk_dist_live["critical"]
    if not risk_avg:
        risk_avg = risk_avg_live

    # ── Real-time fallback (INVOICE PATH ONLY) ────────────────────────────
    # If we're on the invoice path and the saved report's top_failed_rules /
    # top_risk_invoices are empty but live validation data shows failures,
    # rebuild from the database so KPIs and tables stay in sync.
    # We must NOT touch top_failed/top_risk on the multi-doc path — those
    # already reflect the correct doc type and overwriting with Invoice data
    # would re-introduce the very bug this guard prevents.
    if multi_doc_payload is None:
        if not top_failed and rules_failed > 0:
            rule_failure_counts = {}
            for vr in validations:
                for code in (vr.failed_rule_codes or []):
                    rule_failure_counts[code] = rule_failure_counts.get(code, 0) + 1
            top_failed = [
                {"rule_code": code, "failures": cnt, "description": RULES.get(code, code)}
                for code, cnt in sorted(rule_failure_counts.items(), key=lambda kv: -kv[1])[:15]
            ]

        if not top_risk:
            from apps.invoices.models import Invoice
            risky_qs = (
                Invoice.objects.filter(organization=org, risk_level__in=["high", "critical"])
                .order_by("-risk_score")
                .values(
                    "id", "invoice_number", "vendor_name", "total_amount", "currency",
                    "invoice_date", "risk_level", "risk_score",
                )[:15]
            )
            top_risk = []
            for r in risky_qs:
                r["id"] = str(r["id"])
                r["total_amount"] = float(r["total_amount"] or 0)
                r["invoice_date"] = str(r["invoice_date"]) if r["invoice_date"] else "-"
                top_risk.append(r)

        # Refresh totals from real-time when the saved report is empty
        if total_invoices == 0:
            from apps.invoices.models import Invoice
            live_inv_count = Invoice.objects.filter(organization=org).count()
            if live_inv_count:
                total_invoices = live_inv_count
                high_risk_count = Invoice.objects.filter(
                    organization=org, risk_level__in=["high", "critical"]
                ).count()

    # ── Empty-state detection ──────────────────────────────────────────────
    # The page is "empty" only when there is genuinely no live data anywhere.
    is_empty = (total_invoices == 0 and rules_applied == 0 and not vendor_rows and not top_failed)

    if total_invoices == 0:
        report_status = "بدون بيانات"
    elif risk_avg >= 70 or high_risk_count > 0:
        report_status = "عالي المخاطر"
    elif risk_avg >= 40:
        report_status = "يحتاج مراجعة"
    else:
        report_status = "متوافق"

    failed_rules = _failed_rules_with_invoice_refs(top_failed, validations)
    high_risk_invoices = _build_high_risk_violations(top_risk, validation_map, active_rule_catalog)

    # ── Senior-auditor-grade Findings Register ────────────────────────────
    # Groups every failed rule by severity, attaches financial impact and
    # clickable invoice references. Drives the new "Findings Register" section
    # which is the canonical place reviewers act from.
    from apps.reports.services.findings_service import build_findings_register, build_narrative
    findings_register = build_findings_register(
        top_failed_rules=top_failed,
        validations=validations,
        rule_catalog=active_rule_catalog,
    )
    # Derive executive narrative + recommendations from the findings register
    # so they always reflect the actual data and current doc type — replaces
    # the previous hardcoded invoice-flavoured copy.
    narrative_payload = build_narrative(
        findings_register=findings_register,
        type_label=str(_DOC_TYPE_LABELS.get(selected_type, "Documents")),
        type_singular=str(_DOC_TYPE_SINGULAR.get(selected_type, "Document")),
    )

    # Aggregate the per-document AI fields (`ai_summary`, `ai_recommendations`,
    # `anomalies_found`) into a single section so reports surface the AI work
    # the upload pipeline already does. Empty when no docs have AI content.
    from apps.reports.services.ai_insights_service import build_ai_insights
    ai_insights = build_ai_insights(org, selected_type)

    dominant_vendor = vendor_rows[0] if vendor_rows else {}
    # Prefer the saved-report aggregate when present, otherwise fall back to
    # the live count we just computed. Same approach for missing-QR /
    # handwritten / new-vendor — these come from the saved report only since
    # the live invoice schema doesn't carry them.
    duplicate_count = int(overall.get("duplicate_count") or duplicate_count_live or 0)
    missing_qr_count = int(overall.get("missing_qr_count") or 0)
    handwritten_count = int(overall.get("handwritten_count") or 0)
    new_vendor_count = int(overall.get("new_vendor_count") or 0)

    # ── Compliance rule matrix — only real data, NO mock fallback ──────────
    compliance_matrix = []
    for row in top_failed[:6]:
        compliance_matrix.append({
            "rule_code": row.get("rule_code"),
            "status": "مخالف",
            "weight": _weight_for_rule(row.get("rule_code")),
            "note": row.get("description") or "فشل متكرر يتطلب إجراء فوري.",
        })

    # ── Smart Audit Rule Engine summary (from rule_engine.AuditRun) ────────
    rule_engine_summary = None
    try:
        from apps.rule_engine.models import AuditRun
        runs = AuditRun.objects.filter(organization=org)
        if selected_type and selected_type != "invoice":
            runs = runs.filter(document_type=selected_type)
        runs_total = runs.count()
        if runs_total > 0:
            agg = runs.aggregate(
                total_rules=Sum("total_rules"),
                passed=Sum("passed_rules"),
                failed=Sum("failed_rules"),
                warnings=Sum("warning_rules"),
                avg_risk=Avg("risk_score"),
            )
            risk_dist = {
                "critical": runs.filter(risk_level="critical").count(),
                "high":     runs.filter(risk_level="high").count(),
                "medium":   runs.filter(risk_level="medium").count(),
                "low":      runs.filter(risk_level="low").count(),
            }
            re_total_rules = int(agg.get("total_rules") or 0)
            re_passed = int(agg.get("passed") or 0)
            re_compliance = round((re_passed / re_total_rules) * 100, 1) if re_total_rules else 0
            rule_engine_summary = {
                "total_runs": runs_total,
                "total_rules_applied": re_total_rules,
                "passed_rules": re_passed,
                "failed_rules": int(agg.get("failed") or 0),
                "warning_rules": int(agg.get("warnings") or 0),
                "compliance_pct": re_compliance,
                "avg_risk_score": float(agg.get("avg_risk") or 0),
                "risk_distribution": risk_dist,
            }
    except Exception:  # pragma: no cover — defensive
        rule_engine_summary = None

    # ── ISA 700 opinion (real if rule_engine has data, else None) ──────────
    isa700_opinion = None
    if rule_engine_summary and "isa700" in sections:
        crit = rule_engine_summary["risk_distribution"]["critical"]
        high = rule_engine_summary["risk_distribution"]["high"]
        comp = rule_engine_summary["compliance_pct"]
        if crit > 0:
            opinion, opinion_ar = "Adverse", "رأي معاكس"
        elif high > 5 or comp < 70:
            opinion, opinion_ar = "Disclaimer", "إخلاء مسؤولية"
        elif high > 0 or comp < 95:
            opinion, opinion_ar = "Qualified", "رأي متحفظ"
        else:
            opinion, opinion_ar = "Unqualified", "رأي غير متحفظ"
        isa700_opinion = {
            "opinion": opinion,
            "opinion_ar": opinion_ar,
            "compliance_pct": comp,
            "critical_findings": crit,
            "high_findings": high,
            "basis": (
                "Based on automated audit runs across all uploaded documents using the "
                "Tadgeeg AI rule engine — covering ZATCA Phase 2, VAT validation, fraud "
                "detection, and document quality controls."
            ),
            "basis_ar": (
                "بناءً على التشغيل الآلي لقواعد التدقيق على جميع المستندات المرفوعة عبر "
                "محرك Tadgeeg الذكي — بما يشمل ZATCA Phase 2، صحة الضريبة، كشف الاحتيال، "
                "وضوابط جودة المستندات."
            ),
        }

    # ── Build the report payload ───────────────────────────────────────────
    report_payload = {
        "title": kind_label_ar,
        "title_en": kind_label_en,
        "organization_name": getattr(org, "name", "-") or "-",
        "generated_at": report_obj.created_at if report_obj else datetime.now(),
        "report_type": kind_label_en,
        "status": report_status,
        "summary": {
            "total_invoices": total_invoices,
            "total_amount": float(overall.get("total_amount") or 0),
            "compliance_rate": float(validation_summary.get("vat_compliance_pct") or compliance_pct),
            "avg_risk_score": risk_avg,
            "high_risk_invoices": high_risk_count,
            "duplicate_count": duplicate_count,
        },
        "executive_summary": {
            # When narrative explicitly came from the saved report, prefer it;
            # otherwise build dynamically from the findings register so
            # conclusions/recommendations always reflect real data + doc type.
            "conclusion": narrative.get("executive_summary") or narrative_payload["conclusion"],
            "key_findings": narrative_payload["key_findings"],
            "recommendations": narrative_payload["exec_recs"],
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
            # Use the saved-report aggregate when it carries data, otherwise
            # the live distribution we computed above. This guarantees the
            # "Risk Analysis" section always reflects what's in the DB.
            "avg_risk_score": risk_avg,
            "high":   int((overall.get("critical_count") or 0) + (overall.get("high_count") or 0)) or (risk_dist_live["critical"] + risk_dist_live["high"]),
            "review": int(overall.get("medium_count") or 0) or risk_dist_live["medium"],
            "safe":   int(overall.get("low_count") or 0) or risk_dist_live["low"],
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
        # Action plan derived from real findings — `immediate` collects the
        # recommendations from critical/high findings; `future` collects the
        # rest (or generic improvements when there are no non-blocking ones).
        "recommendations": {
            "immediate": narrative_payload["immediate"],
            "future":    narrative_payload["future"],
        },
        "rule_engine": rule_engine_summary,
        "isa700": isa700_opinion,
        "findings_register": findings_register,
        "ai_insights": ai_insights,
    }

    context = _ctx(
        request,
        "reports",
        report=report_payload,
        report_record=report_obj,
        today=date.today(),
        # New context flags for the template:
        is_empty=is_empty,
        selected_kind=selected_kind,
        selected_type=selected_type,
        type_label=type_label,
        is_invoice_report=is_invoice_report,
        is_first_class_report=is_first_class_report,
        detail_url_prefix=detail_url_prefix,
        report_title=_DOC_TYPE_REPORT_TITLE.get(selected_type, "Audit Report"),
        type_singular=_DOC_TYPE_SINGULAR.get(selected_type, "Document"),
        type_plural=type_label,
        sections=sections,
        kind_label=kind_label_ar,
    )
    return render(request, "reports/invoice_audit_report.html", context)


@login_required(login_url="/login/")
def vendors(request):
    """
    Aggregate every distinct vendor we've seen across invoices and purchase
    orders, even if no `VendorProfile` row exists yet (auto-extraction lags
    behind multi-record uploads). Each row shows volume + VAT number + last
    activity, computed on the fly.
    """
    from collections import defaultdict
    from apps.invoices.models import Invoice, VendorProfile
    from apps.documents.typed_models import PurchaseOrder

    org = getattr(request.user, "organization", None)
    rows = []
    stats = {"total": 0, "verified": 0, "needs_review": 0}

    if org:
        # Aggregate by vendor_name from both invoice + PO tables.
        agg = defaultdict(lambda: {
            "vendor_name": "",
            "vendor_vat_number": "",
            "invoice_count": 0,
            "po_count": 0,
            "total_invoice_amount": 0,
            "total_po_amount": 0,
            "last_activity": None,
            "country": "",
        })

        for inv in Invoice.objects.filter(organization=org).exclude(vendor_name="").only(
            "vendor_name", "vendor_vat_number", "total_amount", "invoice_date", "created_at",
        ):
            key = (inv.vendor_name or "").strip()
            if not key:
                continue
            row = agg[key]
            row["vendor_name"] = key
            if inv.vendor_vat_number and not row["vendor_vat_number"]:
                row["vendor_vat_number"] = inv.vendor_vat_number
            row["invoice_count"] += 1
            row["total_invoice_amount"] += float(inv.total_amount or 0)
            ts = inv.invoice_date or inv.created_at
            if ts and (not row["last_activity"] or ts > row["last_activity"]):
                row["last_activity"] = ts

        for po in PurchaseOrder.objects.filter(organization=org).exclude(vendor_name="").only(
            "vendor_name", "vendor_vat_number", "total_amount", "po_date", "created_at",
        ):
            key = (po.vendor_name or "").strip()
            if not key:
                continue
            row = agg[key]
            row["vendor_name"] = key
            if po.vendor_vat_number and not row["vendor_vat_number"]:
                row["vendor_vat_number"] = po.vendor_vat_number
            row["po_count"] += 1
            row["total_po_amount"] += float(po.total_amount or 0)
            ts = po.po_date or po.created_at
            if ts and (not row["last_activity"] or ts > row["last_activity"]):
                row["last_activity"] = ts

        # Filter by search query
        q = (request.GET.get("q") or "").strip().lower()
        if q:
            agg = {k: v for k, v in agg.items() if q in k.lower() or q in v["vendor_vat_number"].lower()}

        # Saudi ZATCA TRN format: 15 digits starting with 3 and ending with 3.
        def _is_zatca_valid(vat: str) -> bool:
            return bool(vat) and len(vat) == 15 and vat.isdigit() and vat.startswith("3") and vat.endswith("3")

        rows = sorted(agg.values(), key=lambda r: r["invoice_count"] + r["po_count"], reverse=True)
        for r in rows:
            r["total_doc_count"] = r["invoice_count"] + r["po_count"]
            r["total_amount"] = r["total_invoice_amount"] + r["total_po_amount"]
            r["is_verified"] = _is_zatca_valid(r["vendor_vat_number"])
            r["needs_review"] = not r["vendor_vat_number"] or not r["is_verified"]
            r["initials"] = "".join(w[0] for w in r["vendor_name"].split()[:2]).upper() or "?"

        stats["total"] = len(rows)
        stats["verified"] = sum(1 for r in rows if r["is_verified"])
        stats["needs_review"] = sum(1 for r in rows if r["needs_review"])

        # Cap at 200 rows on the page (matches the typed-list pages).
        rows = rows[:200]

    return render(request, "vendors/index.html", _ctx(
        request, "vendors",
        rows=rows, stats=stats, search=request.GET.get("q", ""),
    ))


@login_required(login_url="/login/")
def analytics(request):
    """Time-series + breakdown charts of invoice volume / VAT / vendor concentration."""
    from datetime import timedelta
    from django.utils import timezone
    from django.db.models import Count, Sum
    from django.db.models.functions import TruncMonth
    from apps.invoices.models import Invoice
    from apps.documents.typed_models import PurchaseOrder

    org = getattr(request.user, "organization", None)
    monthly = []
    risk_dist = []
    top_vendors = []
    summary = {"total_invoices": 0, "total_pos": 0, "total_amount": 0, "avg_invoice": 0}

    if org:
        cutoff = timezone.now() - timedelta(days=365)
        inv_qs = Invoice.objects.filter(organization=org, created_at__gte=cutoff)

        # Monthly invoice + amount series for the last 12 months.
        by_month = (
            inv_qs.annotate(m=TruncMonth("created_at"))
            .values("m").annotate(c=Count("id"), s=Sum("total_amount"))
            .order_by("m")
        )
        monthly = [
            {"month": r["m"].strftime("%Y-%m") if r["m"] else "?",
             "count": r["c"], "amount": float(r["s"] or 0)}
            for r in by_month
        ]

        # Risk distribution (current snapshot, not just last 12mo)
        all_inv = Invoice.objects.filter(organization=org)
        risk_dist = [
            {"level": level,
             "count": all_inv.filter(risk_level=level).count()}
            for level in ("low", "medium", "high", "critical")
        ]

        # Top 10 vendors by invoice + PO total
        from collections import defaultdict
        agg = defaultdict(float)
        for v, t in all_inv.exclude(vendor_name="").values_list("vendor_name", "total_amount"):
            agg[v] += float(t or 0)
        for v, t in PurchaseOrder.objects.filter(organization=org).exclude(vendor_name="").values_list("vendor_name", "total_amount"):
            agg[v] += float(t or 0)
        top_vendors = sorted(
            ({"name": k, "total": v} for k, v in agg.items()),
            key=lambda r: r["total"], reverse=True,
        )[:10]

        summary["total_invoices"] = all_inv.count()
        summary["total_pos"] = PurchaseOrder.objects.filter(organization=org).count()
        summary["total_amount"] = float(all_inv.aggregate(s=Sum("total_amount"))["s"] or 0)
        summary["avg_invoice"] = round(summary["total_amount"] / summary["total_invoices"], 2) if summary["total_invoices"] else 0

    return render(request, "analytics/index.html", _ctx(
        request, "analytics",
        monthly=monthly, risk_dist=risk_dist,
        top_vendors=top_vendors, summary=summary,
    ))


@login_required(login_url="/login/")
def audit(request):
    """Audit cases / runs list page — aggregates audit activity from every
    document model that carries validation results (Invoice + the 7 typed
    document models). The legacy `rule_engine.AuditRun` table is mostly
    empty, so we read from where the data actually lives.
    """
    org = getattr(request.user, "organization", None)
    rows: list[dict] = []
    counts = {"total": 0, "completed": 0, "running": 0, "failed": 0}
    if not org:
        return render(request, "audit/index.html", _ctx(
            request, "audit", rows=rows, counts=counts,
        ))

    # ── Pull AuditRun first (when present) ────────────────────────────────
    try:
        from apps.rule_engine.models import AuditRun
        run_qs = AuditRun.objects.filter(organization=org)
        if run_qs.exists():
            counts["total"]     += run_qs.count()
            counts["completed"] += run_qs.filter(status="completed").count()
            counts["running"]   += run_qs.filter(status__in=["pending", "running"]).count()
            counts["failed"]    += run_qs.filter(status="failed").count()
            rows.extend(run_qs.order_by("-started_at")[:50].values(
                "id", "document_type", "document_id", "status", "started_at",
                "completed_at", "rules_passed", "rules_failed", "risk_level",
            ))
    except Exception:  # AuditRun may not be migrated
        pass

    # ── Aggregate per-document validation activity ────────────────────────
    # Each typed model writes `failed_rule_codes`, `rules_passed`,
    # `rules_failed`, `validation_score`, `risk_level` directly. A row is
    # treated as "completed" when validation has happened (score>0 OR any
    # rule was applied), and "failed" when at least one rule failed AND it
    # wasn't completed yet (we won't double-count those that completed).
    from apps.invoices.models import Invoice
    from apps.documents.models import (
        PurchaseOrder, BankStatement, PayrollSheet, ExpenseReport,
        VATReturn, FixedAsset, SalesReceipt,
    )
    DOC_SOURCES = [
        ("invoice",        Invoice,        "invoice_number",        "created_at"),
        ("purchase_order", PurchaseOrder,  "po_number",             "created_at"),
        ("bank_statement", BankStatement,  "account_number",        "created_at"),
        ("payroll",        PayrollSheet,   "payroll_period_from",   "created_at"),
        ("expense_report", ExpenseReport,  "report_number",         "created_at"),
        ("vat_return",     VATReturn,      "vat_number",            "created_at"),
        ("fixed_asset",    FixedAsset,     "fiscal_year",           "created_at"),
        ("sales_receipt",  SalesReceipt,   "receipt_number",        "created_at"),
    ]

    from django.db.models import Q

    for doc_type, Model, num_field, ts_field in DOC_SOURCES:
        fields = {f.name for f in Model._meta.get_fields()}
        if "validation_score" not in fields or "rules_failed" not in fields:
            continue
        base = Model.objects.filter(organization=org)
        # "Completed" = something was actually validated (score recorded OR
        # at least one rule applied). Catches both clean (rules_failed=0)
        # and flagged docs.
        completed_q = Q(validation_score__gt=0) | Q(rules_passed__gt=0) | Q(rules_failed__gt=0)
        completed_n = base.filter(completed_q).count()
        # "Failed" — completed AND at least one rule failed
        failed_n = base.filter(completed_q & Q(rules_failed__gt=0)).count()
        total_n = base.count()
        running_n = max(0, total_n - completed_n)  # uploaded but not yet validated
        counts["total"]     += total_n
        counts["completed"] += completed_n
        counts["running"]   += running_n
        counts["failed"]    += failed_n

        # Append recent rows for the activity table — newest 30 per type.
        only_fields = [
            "id", "validation_score", "rules_passed", "rules_failed",
            "risk_level", num_field,
        ]
        if ts_field in fields:
            only_fields.append(ts_field)
        for d in base.only(*only_fields).order_by(f"-{ts_field}" if ts_field in fields else "-id")[:30]:
            score = float(getattr(d, "validation_score", 0) or 0)
            r_failed = int(getattr(d, "rules_failed", 0) or 0)
            r_passed = int(getattr(d, "rules_passed", 0) or 0)
            if r_failed or r_passed or score:
                status = "failed" if r_failed > 0 else "completed"
            else:
                status = "running"
            rows.append({
                "id":          str(d.id),
                "document_type": doc_type,
                "document_id":   str(getattr(d, num_field, "") or "")[:24] or str(d.id)[:8],
                "status":        status,
                "started_at":    getattr(d, ts_field, None),
                "completed_at":  getattr(d, ts_field, None) if status == "completed" else None,
                "rules_passed":  r_passed,
                "rules_failed":  r_failed,
                "risk_level":    getattr(d, "risk_level", None) or "low",
            })

    # Sort all rows by started_at desc (None last) and keep the most recent 200
    def _sort_key(r):
        ts = r.get("started_at")
        return ts or 0
    rows.sort(key=_sort_key, reverse=True)
    rows = rows[:200]

    return render(request, "audit/index.html", _ctx(
        request, "audit", rows=rows, counts=counts,
    ))


@login_required(login_url="/login/")
def audit_detail(request, pk):
    return render(request, "audit/detail.html", _ctx(request, "audit", case_id=str(pk)))


@login_required(login_url="/login/")
def compliance(request):
    """ZATCA / VAT / regulatory health dashboard for the org."""
    org = getattr(request.user, "organization", None)
    health = {
        "total_invoices": 0,
        "qr_valid_pct": 0,
        "vat_validated_pct": 0,
        "missing_vat_count": 0,
        "high_risk_count": 0,
        "duplicate_count": 0,
        "compliance_score": 0,
    }
    issues = []
    if org:
        from apps.invoices.models import Invoice
        qs = Invoice.objects.filter(organization=org)
        n = qs.count()
        health["total_invoices"] = n
        if n:
            qr_ok = qs.filter(qr_code_valid=True).count()
            vat_ok = qs.exclude(vendor_vat_number="").count()
            health["qr_valid_pct"] = int((qr_ok / n) * 100)
            health["vat_validated_pct"] = int((vat_ok / n) * 100)
            health["missing_vat_count"] = qs.filter(vendor_vat_number="").count()
            health["high_risk_count"] = qs.filter(risk_level__in=["high", "critical"]).count()
            health["duplicate_count"] = qs.filter(is_duplicate=True).count()
            # Composite score: average of the three health signals.
            health["compliance_score"] = int(
                (health["qr_valid_pct"] + health["vat_validated_pct"] +
                 (100 - int(health["high_risk_count"] / n * 100))) / 3
            )

        # Surface the actual problem invoices so the user can drill down.
        issues = list(
            qs.filter(qr_code_valid=False).order_by("-created_at")[:10].values(
                "id", "invoice_number", "vendor_name", "total_amount", "created_at",
            )
        )

    return render(request, "compliance/index.html", _ctx(
        request, "compliance", health=health, issues=issues,
    ))


@login_required(login_url="/login/")
def documents(request):
    org = getattr(request.user, "organization", None)
    counts = {
        # Phase 1
        "invoices": 0, "bank_statements": 0, "vat_returns": 0, "payroll": 0,
        "purchase_orders": 0, "expense_reports": 0, "fixed_assets": 0, "sales_receipts": 0,
        # Phase 2
        "sales_orders": 0, "quotations": 0, "proforma_invoices": 0,
        "receipt_vouchers": 0, "cash_vouchers": 0,
        "general_ledgers": 0, "ledgers": 0,
        "contracts": 0, "supplier_statements": 0, "customer_statements": 0,
        # Late additions to complete the 20-doc-type catalog
        "goods_receipt_notes": 0, "payment_vouchers": 0, "journal_entries": 0,
    }
    if org:
        from apps.invoices.models import Invoice
        from apps.documents.typed_models import (
            PurchaseOrder, BankStatement, PayrollSheet, ExpenseReport,
            VATReturn, FixedAsset, SalesReceipt,
        )
        from apps.documents.typed_models_v2 import (
            SalesOrder, Quotation, ProformaInvoice, ReceiptVoucher, CashVoucher,
            GeneralLedger, Ledger, Contract, SupplierStatement, CustomerStatement,
            JournalEntry,
        )
        from apps.documents.typed_models import GoodsReceiptNote, PaymentVoucher
        counts["invoices"]            = Invoice.objects.filter(organization=org).count()
        counts["purchase_orders"]     = PurchaseOrder.objects.filter(organization=org).count()
        counts["bank_statements"]     = BankStatement.objects.filter(organization=org).count()
        counts["payroll"]             = PayrollSheet.objects.filter(organization=org).count()
        counts["expense_reports"]     = ExpenseReport.objects.filter(organization=org).count()
        counts["vat_returns"]         = VATReturn.objects.filter(organization=org).count()
        counts["fixed_assets"]        = FixedAsset.objects.filter(organization=org).count()
        counts["sales_receipts"]      = SalesReceipt.objects.filter(organization=org).count()
        # Phase 2 — typed-models v2
        counts["sales_orders"]        = SalesOrder.objects.filter(organization=org).count()
        counts["quotations"]          = Quotation.objects.filter(organization=org).count()
        counts["proforma_invoices"]   = ProformaInvoice.objects.filter(organization=org).count()
        counts["receipt_vouchers"]    = ReceiptVoucher.objects.filter(organization=org).count()
        counts["cash_vouchers"]       = CashVoucher.objects.filter(organization=org).count()
        counts["general_ledgers"]     = GeneralLedger.objects.filter(organization=org).count()
        counts["ledgers"]             = Ledger.objects.filter(organization=org).count()
        counts["contracts"]           = Contract.objects.filter(organization=org).count()
        counts["supplier_statements"] = SupplierStatement.objects.filter(organization=org).count()
        counts["customer_statements"] = CustomerStatement.objects.filter(organization=org).count()
        # GRN, Payment Voucher, Journal Entry — late additions completing the 20
        counts["goods_receipt_notes"] = GoodsReceiptNote.objects.filter(organization=org).count()
        counts["payment_vouchers"]    = PaymentVoucher.objects.filter(organization=org).count()
        counts["journal_entries"]     = JournalEntry.objects.filter(organization=org).count()
    response = render(request, "documents/index.html", _ctx(request, "documents", doc_counts=counts))
    # Force the browser to fetch fresh markup whenever counts change rather than
    # serving a stale cached page where the grid layout looks broken.
    response["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response["Pragma"] = "no-cache"
    response["Expires"] = "0"
    return response


@login_required(login_url="/login/")
def transactions(request):
    """Unified transactions feed across invoices + POs + bank lines."""
    org = getattr(request.user, "organization", None)
    rows = []
    if org:
        from apps.invoices.models import Invoice
        from apps.documents.typed_models import PurchaseOrder

        for inv in Invoice.objects.filter(organization=org).order_by("-created_at")[:100]:
            rows.append({
                "id": str(inv.id),
                "type": "invoice",
                "ref": inv.invoice_number or "—",
                "party": inv.vendor_name or "—",
                "amount": float(inv.total_amount or 0),
                "currency": inv.currency or "SAR",
                "date": inv.invoice_date or inv.created_at.date(),
                "status": inv.status,
                "url": f"/invoices/{inv.id}/",
            })
        for po in PurchaseOrder.objects.filter(organization=org).order_by("-created_at")[:100]:
            rows.append({
                "id": str(po.id),
                "type": "purchase_order",
                "ref": po.po_number or "—",
                "party": po.vendor_name or "—",
                "amount": float(po.total_amount or 0),
                "currency": po.currency or "SAR",
                "date": po.po_date or po.created_at.date(),
                "status": po.audit_status,
                "url": f"/documents/purchase-orders/{po.id}/",
            })
        rows.sort(key=lambda r: r["date"] or "", reverse=True)
        rows = rows[:200]
    return render(request, "transactions.html", _ctx(request, "transactions", rows=rows))


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


# ── Helpers used by the typed-document list views ────────────────────────────

def _typed_list_qs(request, Model):
    """Return the doc list queryset filtered by org + optional search/status/date.

    Always pulls related Document + uploaded_by FKs in a single JOIN so the
    list templates (which render uploader name + filename next to each row)
    don't issue an N+1 query per record. With 1000 rows that's the difference
    between 1 query and 2001.
    """
    org = getattr(request.user, "organization", None)
    if not org:
        return Model.objects.none()
    qs = (
        Model.objects.filter(organization=org)
        .select_related("document", "uploaded_by", "organization")
        .order_by("-created_at")
    )

    p = request.GET
    if v := p.get("q"):
        # Most typed models have one of these "name-like" fields. Try them in order.
        from django.db.models import Q
        text_fields = [
            f.name for f in Model._meta.get_fields()
            if hasattr(f, "max_length") and f.max_length and f.get_internal_type() == "CharField"
        ]
        if text_fields:
            cond = Q()
            for fn in text_fields:
                cond |= Q(**{f"{fn}__icontains": v})
            qs = qs.filter(cond)
    if v := p.get("status"):
        if hasattr(Model, "audit_status") and v in {c[0] for c in Model._meta.get_field("audit_status").choices}:
            qs = qs.filter(audit_status=v)
    return qs


@login_required(login_url="/login/")
def _typed_list_render(request, Model, template_name, active_key, per_page=25):
    """Shared render path for the 7 typed-document list views.

    Builds the queryset, paginates, then hands the standard kwargs to the
    template. Replaces the duplicated 7-function block we used to have.
    """
    qs = _typed_list_qs(request, Model)
    page_kwargs = _paginate(qs, request, per_page=per_page)
    rows = list(page_kwargs["page_obj"].object_list)
    return render(request, template_name, _ctx(
        request, active_key,
        rows=rows,
        search=request.GET.get("q", ""),
        status_filter=request.GET.get("status", ""),
        **page_kwargs,
    ))


def purchase_orders(request):
    from apps.documents.typed_models import PurchaseOrder
    return _typed_list_render(request, PurchaseOrder,
                              "documents/purchase_orders.html", "purchase_orders")


@login_required(login_url="/login/")
def bank_statements(request):
    from apps.documents.typed_models import BankStatement
    return _typed_list_render(request, BankStatement,
                              "documents/bank_statements.html", "bank_statements")


@login_required(login_url="/login/")
def payroll(request):
    from apps.documents.typed_models import PayrollSheet
    return _typed_list_render(request, PayrollSheet,
                              "documents/payroll.html", "payroll")


@login_required(login_url="/login/")
def expense_reports(request):
    from apps.documents.typed_models import ExpenseReport
    return _typed_list_render(request, ExpenseReport,
                              "documents/expense_reports.html", "expense_reports")


@login_required(login_url="/login/")
def vat_returns(request):
    from apps.documents.typed_models import VATReturn
    return _typed_list_render(request, VATReturn,
                              "documents/vat_returns.html", "vat_returns")


@login_required(login_url="/login/")
def fixed_assets(request):
    from apps.documents.typed_models import FixedAsset
    return _typed_list_render(request, FixedAsset,
                              "documents/fixed_assets.html", "fixed_assets")


@login_required(login_url="/login/")
def sales_receipts(request):
    from apps.documents.typed_models import SalesReceipt
    return _typed_list_render(request, SalesReceipt,
                              "documents/sales_receipts.html", "sales_receipts")


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


# ──────────────────────────────────────────────────────────────────────────────
# Phase-4 generic list/detail views for the 10 new doc types
# ──────────────────────────────────────────────────────────────────────────────

def _phase4_list(request, doc_type, Model, *,
                 columns, label, subtitle, icon, list_url_name, detail_url_name):
    """Render a typed-doc list page using the generic _typed_list.html template."""
    qs = (
        Model.objects.filter(organization=request.user.organization)
        .order_by("-created_at")
        if request.user.organization else Model.objects.none()
    )
    # Apply optional filters
    risk = (request.GET.get("risk") or "").strip().lower()
    if risk in ("low", "medium", "high", "critical"):
        qs = qs.filter(risk_level=risk)
    search = (request.GET.get("q") or "").strip()
    if search and columns:
        from django.db.models import Q
        # Search the first text column we know about
        first_text_col = next(
            (c["key"] for c in columns if c.get("kind") not in ("amount", "date")),
            None,
        )
        if first_text_col:
            qs = qs.filter(**{f"{first_text_col}__icontains": search})

    page_kwargs = _paginate(qs, request, per_page=25)
    rows = list(page_kwargs["page_obj"].object_list)
    return render(request, "documents/_typed_list.html", _ctx(
        request, "documents",
        doc_type_label=label,
        doc_type_subtitle=subtitle,
        doc_type_icon=icon,
        upload_url=f"/documents/upload/?type={doc_type}",
        report_url=f"/reports/invoice-audit/?type={doc_type}&kind=audit_summary",
        detail_url_name=detail_url_name,
        rows=rows,
        columns=columns,
        search=search,
        **page_kwargs,
    ))


def _phase4_detail(request, doc_type, Model, pk, *,
                   field_groups, label, icon, list_url_name):
    """Render the generic _typed_detail.html for a single typed-doc instance."""
    from django.shortcuts import get_object_or_404
    from apps.rule_engine.catalog.document_rules import ALL_RULES
    org = request.user.organization
    doc = get_object_or_404(Model, pk=pk, organization=org)

    # Enrich `failed_rule_codes` with catalog metadata for display
    rules_index = {r["rule_id"]: r for r in ALL_RULES}
    failed_rules = []
    for code in (doc.failed_rule_codes or []):
        meta = rules_index.get(code, {})
        failed_rules.append({
            "rule_code":      code,
            "name":           meta.get("name_ar") or meta.get("name_en") or code,
            "description":    meta.get("fail_message_ar") or meta.get("description_ar") or "",
            "recommendation": meta.get("recommendation_ar") or "",
            "severity":       meta.get("severity", "medium"),
        })

    # Reverse the list-url-name to a concrete path for back-link
    from django.urls import reverse
    try:
        list_url = reverse(f"frontend:{list_url_name}")
    except Exception:
        list_url = "/documents/"

    # Cross-doc links (PO ↔ GRN ↔ Invoice ↔ Payment + Phase-2 chains).
    # Returns {} for doc types the linker doesn't handle, so the panel hides
    # itself gracefully on those pages.
    try:
        from core.services.cross_doc_linker import find_links
        cross_links = find_links(doc_type, doc, org)
    except Exception:
        cross_links = {}

    return render(request, "documents/_typed_detail.html", _ctx(
        request, "documents",
        doc=doc,
        doc_type=doc_type,
        doc_type_label=label,
        doc_type_icon=icon,
        list_url=list_url,
        field_groups=field_groups,
        failed_rules=failed_rules,
        cross_links=cross_links,
    ))


# Per-type column / field-group schemas — drive the generic templates.
from django.utils.translation import gettext_lazy as _gl4

_SO_COLUMNS = [
    {"key": "so_number",     "label": _gl4("SO No.")},
    {"key": "so_date",       "label": _gl4("Date"),     "kind": "date"},
    {"key": "customer_name", "label": _gl4("Customer")},
    {"key": "total_amount",  "label": _gl4("Total"),    "kind": "amount"},
]
_SO_FIELDS = [
    {"title": _gl4("Header"), "fields": [
        {"key": "so_number",   "label": _gl4("SO Number")},
        {"key": "so_date",     "label": _gl4("Date"),     "kind": "date"},
        {"key": "customer_name",        "label": _gl4("Customer")},
        {"key": "customer_vat_number",  "label": _gl4("VAT Number")},
        {"key": "expected_delivery_date","label": _gl4("Expected Delivery"), "kind": "date"},
        {"key": "status",      "label": _gl4("Status")},
    ]},
    {"title": _gl4("Financials"), "fields": [
        {"key": "subtotal",        "label": _gl4("Subtotal"),     "kind": "amount"},
        {"key": "vat_amount",      "label": _gl4("VAT"),          "kind": "amount"},
        {"key": "total_amount",    "label": _gl4("Total"),        "kind": "amount"},
        {"key": "discount_amount", "label": _gl4("Discount"),     "kind": "amount"},
        {"key": "customer_credit_limit","label": _gl4("Credit Limit"), "kind": "amount"},
        {"key": "customer_outstanding", "label": _gl4("Outstanding"),  "kind": "amount"},
    ]},
]

_QT_COLUMNS = [
    {"key": "quotation_number", "label": _gl4("Quote No.")},
    {"key": "quotation_date",   "label": _gl4("Date"),    "kind": "date"},
    {"key": "expiry_date",      "label": _gl4("Expires"), "kind": "date"},
    {"key": "party_name",       "label": _gl4("Party")},
    {"key": "total_amount",     "label": _gl4("Total"),   "kind": "amount"},
]
_QT_FIELDS = [
    {"title": _gl4("Header"), "fields": [
        {"key": "quotation_number", "label": _gl4("Quote Number")},
        {"key": "quotation_date",   "label": _gl4("Date"),    "kind": "date"},
        {"key": "expiry_date",      "label": _gl4("Expiry"),  "kind": "date"},
        {"key": "party_type",       "label": _gl4("Party Type")},
        {"key": "party_name",       "label": _gl4("Party")},
        {"key": "status",           "label": _gl4("Status")},
    ]},
    {"title": _gl4("Financials"), "fields": [
        {"key": "subtotal",      "label": _gl4("Subtotal"),    "kind": "amount"},
        {"key": "discount_pct",  "label": _gl4("Discount %")},
        {"key": "vat_amount",    "label": _gl4("VAT"),         "kind": "amount"},
        {"key": "total_amount",  "label": _gl4("Total"),       "kind": "amount"},
    ]},
]

_PF_COLUMNS = [
    {"key": "proforma_number", "label": _gl4("Proforma No.")},
    {"key": "proforma_date",   "label": _gl4("Date"),     "kind": "date"},
    {"key": "customer_name",   "label": _gl4("Customer")},
    {"key": "total_amount",    "label": _gl4("Total"),    "kind": "amount"},
]
_PF_FIELDS = [
    {"title": _gl4("Header"), "fields": [
        {"key": "proforma_number",   "label": _gl4("Proforma Number")},
        {"key": "proforma_date",     "label": _gl4("Date"),       "kind": "date"},
        {"key": "validity_date",     "label": _gl4("Validity"),   "kind": "date"},
        {"key": "customer_name",     "label": _gl4("Customer")},
        {"key": "customer_vat_number","label": _gl4("VAT Number")},
        {"key": "is_marked_proforma","label": _gl4("Marked Proforma"), "kind": "bool"},
    ]},
    {"title": _gl4("Financials"), "fields": [
        {"key": "subtotal",     "label": _gl4("Subtotal"), "kind": "amount"},
        {"key": "vat_amount",   "label": _gl4("VAT"),      "kind": "amount"},
        {"key": "total_amount", "label": _gl4("Total"),    "kind": "amount"},
    ]},
]

_RV_COLUMNS = [
    {"key": "receipt_number", "label": _gl4("Receipt No.")},
    {"key": "receipt_date",   "label": _gl4("Date"),  "kind": "date"},
    {"key": "payer_name",     "label": _gl4("Payer")},
    {"key": "amount",         "label": _gl4("Amount"), "kind": "amount"},
]
_RV_FIELDS = [
    {"title": _gl4("Header"), "fields": [
        {"key": "receipt_number", "label": _gl4("Receipt Number")},
        {"key": "receipt_date",   "label": _gl4("Date"),       "kind": "date"},
        {"key": "payer_name",     "label": _gl4("Payer")},
        {"key": "receipt_method", "label": _gl4("Method")},
        {"key": "amount",         "label": _gl4("Amount"),     "kind": "amount"},
    ]},
    {"title": _gl4("References"), "fields": [
        {"key": "linked_invoice_number", "label": _gl4("Invoice No.")},
        {"key": "bank_reference",        "label": _gl4("Bank Reference")},
        {"key": "is_reconciled",         "label": _gl4("Reconciled"), "kind": "bool"},
        {"key": "is_duplicate",          "label": _gl4("Duplicate"),  "kind": "bool"},
    ]},
]

_CV_COLUMNS = [
    {"key": "voucher_number",    "label": _gl4("Voucher No.")},
    {"key": "voucher_date",      "label": _gl4("Date"), "kind": "date"},
    {"key": "movement_type",     "label": _gl4("Type")},
    {"key": "counterparty_name", "label": _gl4("Counterparty")},
    {"key": "amount",            "label": _gl4("Amount"), "kind": "amount"},
]
_CV_FIELDS = [
    {"title": _gl4("Header"), "fields": [
        {"key": "voucher_number",   "label": _gl4("Voucher Number")},
        {"key": "voucher_date",     "label": _gl4("Date"),  "kind": "date"},
        {"key": "movement_type",    "label": _gl4("Type")},
        {"key": "amount",           "label": _gl4("Amount"), "kind": "amount"},
        {"key": "reason",           "label": _gl4("Reason")},
        {"key": "has_attachment",   "label": _gl4("Has Attachment"), "kind": "bool"},
        {"key": "approval_status",  "label": _gl4("Approval")},
    ]},
]

_GL_COLUMNS = [
    {"key": "fiscal_year",   "label": _gl4("Fiscal Year")},
    {"key": "period_to",     "label": _gl4("Period End"),  "kind": "date"},
    {"key": "total_debit",   "label": _gl4("Total Debit"), "kind": "amount"},
    {"key": "total_credit",  "label": _gl4("Total Credit"),"kind": "amount"},
]
_GL_FIELDS = [
    {"title": _gl4("Period"), "fields": [
        {"key": "fiscal_year",     "label": _gl4("Fiscal Year")},
        {"key": "period_from",     "label": _gl4("Period From"), "kind": "date"},
        {"key": "period_to",       "label": _gl4("Period To"),   "kind": "date"},
    ]},
    {"title": _gl4("Totals"), "fields": [
        {"key": "total_debit",     "label": _gl4("Total Debit"),  "kind": "amount"},
        {"key": "total_credit",    "label": _gl4("Total Credit"), "kind": "amount"},
        {"key": "accounts_count",  "label": _gl4("Accounts")},
        {"key": "movements_count", "label": _gl4("Movements")},
        {"key": "is_balanced",     "label": _gl4("Balanced"), "kind": "bool"},
    ]},
]

_LDG_COLUMNS = [
    {"key": "account_number",    "label": _gl4("Account No.")},
    {"key": "account_name",      "label": _gl4("Account Name")},
    {"key": "period_to",         "label": _gl4("Period End"), "kind": "date"},
    {"key": "closing_balance",   "label": _gl4("Closing"),    "kind": "amount"},
]
_LDG_FIELDS = [
    {"title": _gl4("Account"), "fields": [
        {"key": "account_number", "label": _gl4("Account Number")},
        {"key": "account_name",   "label": _gl4("Account Name")},
        {"key": "account_type",   "label": _gl4("Type")},
        {"key": "period_from",    "label": _gl4("Period From"), "kind": "date"},
        {"key": "period_to",      "label": _gl4("Period To"),   "kind": "date"},
    ]},
    {"title": _gl4("Balances"), "fields": [
        {"key": "opening_balance", "label": _gl4("Opening Balance"), "kind": "amount"},
        {"key": "total_debit",     "label": _gl4("Total Debit"),     "kind": "amount"},
        {"key": "total_credit",    "label": _gl4("Total Credit"),    "kind": "amount"},
        {"key": "closing_balance", "label": _gl4("Closing Balance"), "kind": "amount"},
        {"key": "movements_count", "label": _gl4("Movements")},
    ]},
]

_CTR_COLUMNS = [
    {"key": "contract_number", "label": _gl4("Contract No.")},
    {"key": "title",           "label": _gl4("Title")},
    {"key": "party_b",         "label": _gl4("Counterparty")},
    {"key": "start_date",      "label": _gl4("Start"),  "kind": "date"},
    {"key": "end_date",        "label": _gl4("End"),    "kind": "date"},
    {"key": "contract_value",  "label": _gl4("Value"),  "kind": "amount"},
]
_CTR_FIELDS = [
    {"title": _gl4("Header"), "fields": [
        {"key": "contract_number", "label": _gl4("Contract Number")},
        {"key": "title",           "label": _gl4("Title")},
        {"key": "party_a",         "label": _gl4("Party A")},
        {"key": "party_b",         "label": _gl4("Party B")},
        {"key": "party_b_type",    "label": _gl4("Party Type")},
        {"key": "party_b_vat_number","label": _gl4("VAT Number")},
        {"key": "status",          "label": _gl4("Status")},
        {"key": "is_signed",       "label": _gl4("Signed"), "kind": "bool"},
    ]},
    {"title": _gl4("Dates & Value"), "fields": [
        {"key": "start_date",       "label": _gl4("Start Date"),  "kind": "date"},
        {"key": "end_date",         "label": _gl4("End Date"),    "kind": "date"},
        {"key": "signing_date",     "label": _gl4("Signed On"),   "kind": "date"},
        {"key": "contract_value",   "label": _gl4("Value"),       "kind": "amount"},
        {"key": "invoiced_to_date", "label": _gl4("Invoiced"),    "kind": "amount"},
        {"key": "payment_terms",    "label": _gl4("Payment Terms")},
    ]},
]

_SS_COLUMNS = [
    {"key": "supplier_name",   "label": _gl4("Supplier")},
    {"key": "period_to",       "label": _gl4("Period End"),    "kind": "date"},
    {"key": "opening_balance", "label": _gl4("Opening"),       "kind": "amount"},
    {"key": "closing_balance", "label": _gl4("Closing"),       "kind": "amount"},
    {"key": "balance_variance","label": _gl4("Variance"),      "kind": "amount"},
]
_SS_FIELDS = [
    {"title": _gl4("Supplier"), "fields": [
        {"key": "supplier_name",     "label": _gl4("Supplier")},
        {"key": "supplier_id",       "label": _gl4("Supplier ID")},
        {"key": "supplier_vat_number","label": _gl4("VAT Number")},
    ]},
    {"title": _gl4("Period"), "fields": [
        {"key": "period_from", "label": _gl4("From"), "kind": "date"},
        {"key": "period_to",   "label": _gl4("To"),   "kind": "date"},
    ]},
    {"title": _gl4("Balances"), "fields": [
        {"key": "opening_balance", "label": _gl4("Opening Balance"), "kind": "amount"},
        {"key": "total_invoiced",  "label": _gl4("Total Invoiced"),  "kind": "amount"},
        {"key": "total_paid",      "label": _gl4("Total Paid"),      "kind": "amount"},
        {"key": "closing_balance", "label": _gl4("Closing Balance"), "kind": "amount"},
        {"key": "balance_variance","label": _gl4("Variance"),        "kind": "amount"},
        {"key": "duplicate_count", "label": _gl4("Duplicate Count")},
    ]},
]

_CS_COLUMNS = [
    {"key": "customer_name",   "label": _gl4("Customer")},
    {"key": "period_to",       "label": _gl4("Period End"), "kind": "date"},
    {"key": "opening_balance", "label": _gl4("Opening"),    "kind": "amount"},
    {"key": "closing_balance", "label": _gl4("Closing"),    "kind": "amount"},
    {"key": "balance_variance","label": _gl4("Variance"),   "kind": "amount"},
]
_CS_FIELDS = [
    {"title": _gl4("Customer"), "fields": [
        {"key": "customer_name",     "label": _gl4("Customer")},
        {"key": "customer_id",       "label": _gl4("Customer ID")},
        {"key": "customer_vat_number","label": _gl4("VAT Number")},
    ]},
    {"title": _gl4("Period"), "fields": [
        {"key": "period_from", "label": _gl4("From"), "kind": "date"},
        {"key": "period_to",   "label": _gl4("To"),   "kind": "date"},
    ]},
    {"title": _gl4("Balances"), "fields": [
        {"key": "opening_balance",  "label": _gl4("Opening Balance"), "kind": "amount"},
        {"key": "total_invoiced",   "label": _gl4("Total Invoiced"),  "kind": "amount"},
        {"key": "total_received",   "label": _gl4("Total Received"),  "kind": "amount"},
        {"key": "closing_balance",  "label": _gl4("Closing Balance"), "kind": "amount"},
        {"key": "balance_variance", "label": _gl4("Variance"),        "kind": "amount"},
        {"key": "duplicate_count",  "label": _gl4("Duplicate Count")},
    ]},
]

# ── GRN (Goods Receipt Note) ──
_GRN_COLUMNS = [
    {"key": "grn_number",   "label": _gl4("GRN No.")},
    {"key": "grn_date",     "label": _gl4("Date"),    "kind": "date"},
    {"key": "po_number",    "label": _gl4("PO No.")},
    {"key": "vendor_name",  "label": _gl4("Vendor")},
    {"key": "total_amount", "label": _gl4("Total"),   "kind": "amount"},
]
_GRN_FIELDS = [
    {"title": _gl4("Header"), "fields": [
        {"key": "grn_number",   "label": _gl4("GRN Number")},
        {"key": "grn_date",     "label": _gl4("Date"),     "kind": "date"},
        {"key": "po_number",    "label": _gl4("PO Number")},
        {"key": "invoice_number","label": _gl4("Invoice Number")},
        {"key": "department",   "label": _gl4("Department")},
        {"key": "received_by",  "label": _gl4("Received By")},
        {"key": "warehouse_location", "label": _gl4("Warehouse")},
    ]},
    {"title": _gl4("Vendor"), "fields": [
        {"key": "vendor_name",       "label": _gl4("Vendor")},
        {"key": "vendor_vat_number", "label": _gl4("VAT Number")},
    ]},
    {"title": _gl4("Quantities"), "fields": [
        {"key": "total_ordered_qty",  "label": _gl4("Ordered Qty")},
        {"key": "total_received_qty", "label": _gl4("Received Qty")},
        {"key": "total_rejected_qty", "label": _gl4("Rejected Qty")},
        {"key": "rejection_rate_pct", "label": _gl4("Rejection %")},
    ]},
    {"title": _gl4("Amounts"), "fields": [
        {"key": "total_amount",   "label": _gl4("Total"),          "kind": "amount"},
        {"key": "invoice_amount", "label": _gl4("Invoice Amount"), "kind": "amount"},
        {"key": "currency",       "label": _gl4("Currency")},
    ]},
    {"title": _gl4("Status"), "fields": [
        {"key": "delivery_date",     "label": _gl4("Delivery Date"),     "kind": "date"},
        {"key": "delivery_overdue",  "label": _gl4("Overdue"),           "kind": "bool"},
        {"key": "quality_inspection_done", "label": _gl4("QC Done"),     "kind": "bool"},
        {"key": "approval_status",   "label": _gl4("Approval")},
    ]},
]

# ── Payment Voucher ──
_PV_COLUMNS = [
    {"key": "payment_number", "label": _gl4("Voucher No.")},
    {"key": "payment_date",   "label": _gl4("Date"),    "kind": "date"},
    {"key": "payee_name",     "label": _gl4("Payee")},
    {"key": "payment_method", "label": _gl4("Method")},
    {"key": "total_amount",   "label": _gl4("Total"),   "kind": "amount"},
]
_PV_FIELDS = [
    {"title": _gl4("Header"), "fields": [
        {"key": "payment_number", "label": _gl4("Voucher Number")},
        {"key": "payment_date",   "label": _gl4("Date"),     "kind": "date"},
        {"key": "payment_method", "label": _gl4("Method")},
    ]},
    {"title": _gl4("Payee"), "fields": [
        {"key": "payee_name",       "label": _gl4("Payee")},
        {"key": "payee_vat_number", "label": _gl4("VAT Number")},
        {"key": "payee_iban",       "label": _gl4("IBAN")},
    ]},
    {"title": _gl4("Amounts"), "fields": [
        {"key": "amount",       "label": _gl4("Amount"),     "kind": "amount"},
        {"key": "vat_amount",   "label": _gl4("VAT Amount"), "kind": "amount"},
        {"key": "total_amount", "label": _gl4("Total"),      "kind": "amount"},
        {"key": "currency",     "label": _gl4("Currency")},
    ]},
    {"title": _gl4("References"), "fields": [
        {"key": "linked_invoice_number", "label": _gl4("Invoice Number")},
        {"key": "linked_po_number",      "label": _gl4("PO Number")},
        {"key": "bank_reference",        "label": _gl4("Bank Reference")},
    ]},
    {"title": _gl4("Control"), "fields": [
        {"key": "approval_status",     "label": _gl4("Approval Status")},
        {"key": "is_duplicate",        "label": _gl4("Duplicate"),         "kind": "bool"},
        {"key": "exceeds_threshold",   "label": _gl4("Exceeds Threshold"), "kind": "bool"},
        {"key": "is_advance_payment",  "label": _gl4("Advance"),           "kind": "bool"},
        {"key": "days_since_invoice",  "label": _gl4("Days vs. Invoice")},
    ]},
]

# ── Journal Entry (lightweight model — Phase 6 addition) ──
_JE_COLUMNS = [
    {"key": "entry_number",  "label": _gl4("Entry No.")},
    {"key": "entry_date",    "label": _gl4("Date"),    "kind": "date"},
    {"key": "description",   "label": _gl4("Description")},
    {"key": "total_debit",   "label": _gl4("Debit"),   "kind": "amount"},
    {"key": "total_credit",  "label": _gl4("Credit"),  "kind": "amount"},
]
_JE_FIELDS = [
    {"title": _gl4("Header"), "fields": [
        {"key": "entry_number",     "label": _gl4("Entry Number")},
        {"key": "entry_date",       "label": _gl4("Entry Date"), "kind": "date"},
        {"key": "description",      "label": _gl4("Description")},
        {"key": "fiscal_period",    "label": _gl4("Fiscal Period")},
    ]},
    {"title": _gl4("Totals"), "fields": [
        {"key": "total_debit",  "label": _gl4("Total Debit"),  "kind": "amount"},
        {"key": "total_credit", "label": _gl4("Total Credit"), "kind": "amount"},
        {"key": "is_balanced",  "label": _gl4("Balanced"),     "kind": "bool"},
        {"key": "lines_count",  "label": _gl4("Lines")},
    ]},
    {"title": _gl4("Control"), "fields": [
        {"key": "is_manual",        "label": _gl4("Manual Entry"), "kind": "bool"},
        {"key": "has_attachment",   "label": _gl4("Attachment"),   "kind": "bool"},
        {"key": "is_period_close",  "label": _gl4("Period Close"), "kind": "bool"},
        {"key": "approval_status",  "label": _gl4("Approval")},
    ]},
]


# ── Phase-4 list views ─────────────────────────────────────────────────────
@login_required(login_url="/login/")
def sales_orders(request):
    from apps.documents.models import SalesOrder
    return _phase4_list(request, "sales_order", SalesOrder,
        columns=_SO_COLUMNS, label=_gl4("Sales Orders"),
        subtitle=_gl4("Customer purchase orders, fulfilment status, credit checks."),
        icon="shopping-cart",
        list_url_name="sales_orders", detail_url_name="frontend:sales_order_detail")

@login_required(login_url="/login/")
def quotations(request):
    from apps.documents.models import Quotation
    return _phase4_list(request, "quotation", Quotation,
        columns=_QT_COLUMNS, label=_gl4("Quotations"),
        subtitle=_gl4("Price quotations issued to customers or received from suppliers."),
        icon="file-text",
        list_url_name="quotations", detail_url_name="frontend:quotation_detail")

@login_required(login_url="/login/")
def proforma_invoices(request):
    from apps.documents.models import ProformaInvoice
    return _phase4_list(request, "proforma_invoice", ProformaInvoice,
        columns=_PF_COLUMNS, label=_gl4("Proforma Invoices"),
        subtitle=_gl4("Pre-tax / preliminary invoices, not yet posted as revenue."),
        icon="file-text",
        list_url_name="proforma_invoices", detail_url_name="frontend:proforma_invoice_detail")

@login_required(login_url="/login/")
def receipt_vouchers(request):
    from apps.documents.models import ReceiptVoucher
    return _phase4_list(request, "receipt_voucher", ReceiptVoucher,
        columns=_RV_COLUMNS, label=_gl4("Receipt Vouchers"),
        subtitle=_gl4("Cash + bank receipts collected from customers / payers."),
        icon="receipt",
        list_url_name="receipt_vouchers", detail_url_name="frontend:receipt_voucher_detail")

@login_required(login_url="/login/")
def cash_vouchers(request):
    from apps.documents.models import CashVoucher
    return _phase4_list(request, "cash_voucher", CashVoucher,
        columns=_CV_COLUMNS, label=_gl4("Cash Vouchers"),
        subtitle=_gl4("Petty-cash and on-the-spot cash movements."),
        icon="banknote",
        list_url_name="cash_vouchers", detail_url_name="frontend:cash_voucher_detail")

@login_required(login_url="/login/")
def general_ledgers(request):
    from apps.documents.models import GeneralLedger
    return _phase4_list(request, "general_ledger", GeneralLedger,
        columns=_GL_COLUMNS, label=_gl4("General Ledgers"),
        subtitle=_gl4("Period-level GL snapshots — debit/credit totals + balanced check."),
        icon="book-open",
        list_url_name="general_ledgers", detail_url_name="frontend:general_ledger_detail")

@login_required(login_url="/login/")
def ledgers(request):
    from apps.documents.models import Ledger
    return _phase4_list(request, "ledger", Ledger,
        columns=_LDG_COLUMNS, label=_gl4("Ledgers"),
        subtitle=_gl4("Account-level ledgers with movements + closing balance."),
        icon="book",
        list_url_name="ledgers", detail_url_name="frontend:ledger_detail")

@login_required(login_url="/login/")
def contracts(request):
    from apps.documents.models import Contract
    return _phase4_list(request, "contract", Contract,
        columns=_CTR_COLUMNS, label=_gl4("Contracts"),
        subtitle=_gl4("Vendor / customer contracts — value, signing status, modifications."),
        icon="file-signature",
        list_url_name="contracts", detail_url_name="frontend:contract_detail")

@login_required(login_url="/login/")
def supplier_statements(request):
    from apps.documents.models import SupplierStatement
    return _phase4_list(request, "supplier_statement", SupplierStatement,
        columns=_SS_COLUMNS, label=_gl4("Supplier Statements"),
        subtitle=_gl4("Reconcile our payables ledger against the supplier's statement."),
        icon="users",
        list_url_name="supplier_statements", detail_url_name="frontend:supplier_statement_detail")

@login_required(login_url="/login/")
def customer_statements(request):
    from apps.documents.models import CustomerStatement
    return _phase4_list(request, "customer_statement", CustomerStatement,
        columns=_CS_COLUMNS, label=_gl4("Customer Statements"),
        subtitle=_gl4("Reconcile our receivables ledger against the customer's view."),
        icon="user-check",
        list_url_name="customer_statements", detail_url_name="frontend:customer_statement_detail")


# ── Phase-4 detail views ───────────────────────────────────────────────────
@login_required(login_url="/login/")
def sales_order_detail(request, pk):
    from apps.documents.models import SalesOrder
    return _phase4_detail(request, "sales_order", SalesOrder, pk,
        field_groups=_SO_FIELDS, label=_gl4("Sales Order"),
        icon="shopping-cart", list_url_name="sales_orders")

@login_required(login_url="/login/")
def quotation_detail(request, pk):
    from apps.documents.models import Quotation
    return _phase4_detail(request, "quotation", Quotation, pk,
        field_groups=_QT_FIELDS, label=_gl4("Quotation"),
        icon="file-text", list_url_name="quotations")

@login_required(login_url="/login/")
def proforma_invoice_detail(request, pk):
    from apps.documents.models import ProformaInvoice
    return _phase4_detail(request, "proforma_invoice", ProformaInvoice, pk,
        field_groups=_PF_FIELDS, label=_gl4("Proforma Invoice"),
        icon="file-text", list_url_name="proforma_invoices")

@login_required(login_url="/login/")
def receipt_voucher_detail(request, pk):
    from apps.documents.models import ReceiptVoucher
    return _phase4_detail(request, "receipt_voucher", ReceiptVoucher, pk,
        field_groups=_RV_FIELDS, label=_gl4("Receipt Voucher"),
        icon="receipt", list_url_name="receipt_vouchers")

@login_required(login_url="/login/")
def cash_voucher_detail(request, pk):
    from apps.documents.models import CashVoucher
    return _phase4_detail(request, "cash_voucher", CashVoucher, pk,
        field_groups=_CV_FIELDS, label=_gl4("Cash Voucher"),
        icon="banknote", list_url_name="cash_vouchers")

@login_required(login_url="/login/")
def general_ledger_detail(request, pk):
    from apps.documents.models import GeneralLedger
    return _phase4_detail(request, "general_ledger", GeneralLedger, pk,
        field_groups=_GL_FIELDS, label=_gl4("General Ledger"),
        icon="book-open", list_url_name="general_ledgers")

@login_required(login_url="/login/")
def ledger_detail(request, pk):
    from apps.documents.models import Ledger
    return _phase4_detail(request, "ledger", Ledger, pk,
        field_groups=_LDG_FIELDS, label=_gl4("Ledger"),
        icon="book", list_url_name="ledgers")

@login_required(login_url="/login/")
def contract_detail(request, pk):
    from apps.documents.models import Contract
    return _phase4_detail(request, "contract", Contract, pk,
        field_groups=_CTR_FIELDS, label=_gl4("Contract"),
        icon="file-signature", list_url_name="contracts")

@login_required(login_url="/login/")
def supplier_statement_detail(request, pk):
    from apps.documents.models import SupplierStatement
    return _phase4_detail(request, "supplier_statement", SupplierStatement, pk,
        field_groups=_SS_FIELDS, label=_gl4("Supplier Statement"),
        icon="users", list_url_name="supplier_statements")

@login_required(login_url="/login/")
def customer_statement_detail(request, pk):
    from apps.documents.models import CustomerStatement
    return _phase4_detail(request, "customer_statement", CustomerStatement, pk,
        field_groups=_CS_FIELDS, label=_gl4("Customer Statement"),
        icon="user-check", list_url_name="customer_statements")


# ── GRN, Payment Voucher, Journal Entry — Phase-1 + new Phase-2 page wiring ──
@login_required(login_url="/login/")
def goods_receipt_notes(request):
    from apps.documents.typed_models import GoodsReceiptNote
    return _phase4_list(request, "goods_receipt_note", GoodsReceiptNote,
        columns=_GRN_COLUMNS, label=_gl4("Goods Receipts"),
        subtitle=_gl4("GRN matching with PO and invoice — quantity and quality checks."),
        icon="package-check",
        list_url_name="goods_receipt_notes",
        detail_url_name="frontend:goods_receipt_note_detail")

@login_required(login_url="/login/")
def goods_receipt_note_detail(request, pk):
    from apps.documents.typed_models import GoodsReceiptNote
    return _phase4_detail(request, "goods_receipt_note", GoodsReceiptNote, pk,
        field_groups=_GRN_FIELDS, label=_gl4("Goods Receipt"),
        icon="package-check", list_url_name="goods_receipt_notes")

@login_required(login_url="/login/")
def payment_vouchers(request):
    from apps.documents.typed_models import PaymentVoucher
    return _phase4_list(request, "payment_voucher", PaymentVoucher,
        columns=_PV_COLUMNS, label=_gl4("Payment Vouchers"),
        subtitle=_gl4("Vendor payments, approvals, three-way match."),
        icon="banknote",
        list_url_name="payment_vouchers",
        detail_url_name="frontend:payment_voucher_detail")

@login_required(login_url="/login/")
def payment_voucher_detail(request, pk):
    from apps.documents.typed_models import PaymentVoucher
    return _phase4_detail(request, "payment_voucher", PaymentVoucher, pk,
        field_groups=_PV_FIELDS, label=_gl4("Payment Voucher"),
        icon="banknote", list_url_name="payment_vouchers")

@login_required(login_url="/login/")
def journal_entries(request):
    from apps.documents.models import JournalEntry
    return _phase4_list(request, "journal_entry", JournalEntry,
        columns=_JE_COLUMNS, label=_gl4("Journal Entries"),
        subtitle=_gl4("Double-entry postings — debit/credit balance and approvals."),
        icon="book-open",
        list_url_name="journal_entries",
        detail_url_name="frontend:journal_entry_detail")

@login_required(login_url="/login/")
def journal_entry_detail(request, pk):
    from apps.documents.models import JournalEntry
    return _phase4_detail(request, "journal_entry", JournalEntry, pk,
        field_groups=_JE_FIELDS, label=_gl4("Journal Entry"),
        icon="book-open", list_url_name="journal_entries")


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


def permission_denied(request, exception=None):
    return render(request, "403.html", status=403)
