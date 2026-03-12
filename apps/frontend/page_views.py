"""FinAI frontend page views."""

from datetime import datetime
from decimal import Decimal, InvalidOperation

from django.conf import settings as django_settings
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.utils.dateparse import parse_date
from django.views.decorators.csrf import ensure_csrf_cookie
from rest_framework_simplejwt.tokens import RefreshToken

from apps.authentication.serializers import RegisterSerializer


def _ctx(request, active="dashboard", **extra):
    pending_count = 0
    try:
        from apps.invoices.models import Invoice

        organization = getattr(request.user, "organization", None)
        if organization:
            pending_count = Invoice.objects.filter(organization=organization, status="flagged").count()
    except Exception:
        pass
    return {"pending_count": pending_count, "active": active, **extra}


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
    return {
        "google_client_id": getattr(django_settings, "GOOGLE_CLIENT_ID", ""),
        **extra,
    }


def _issue_tokens(user):
    refresh = RefreshToken.for_user(user)
    return {
        "access": str(refresh.access_token),
        "refresh": str(refresh),
    }


def _post_auth_redirect(user):
    return "/google-pending/" if not getattr(user, "organization_id", None) else "/dashboard/"


def _first_error(errors):
    if not errors:
        return "تعذر إكمال العملية حالياً."

    if isinstance(errors, dict):
        if "email" in errors:
            return "هذا البريد الإلكتروني مستخدم بالفعل." if errors["email"] else "البريد الإلكتروني غير صالح."
        if "password" in errors:
            first_password_error = errors["password"][0] if isinstance(errors["password"], list) else errors["password"]
            if "match" in str(first_password_error).lower():
                return "كلمتا المرور غير متطابقتين."
            return "يرجى التحقق من كلمة المرور والمحاولة مرة أخرى."
        if "full_name" in errors:
            return "الاسم الكامل مطلوب."

        first_key = next(iter(errors))
        first_value = errors[first_key]
        if isinstance(first_value, list) and first_value:
            return str(first_value[0])
        return str(first_value)

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
        "openai_vision": "OpenAI GPT + OCR",
        "tesseract_fallback": "Tesseract OCR",
        "ocr_fallback": "OCR محلي",
    }.get(extraction_method, extraction_method)

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
        if not getattr(request.user, "organization_id", None):
            return redirect("frontend:google_pending")
        return redirect("frontend:dashboard")

    if request.method == "POST":
        email = request.POST.get("email", "").strip()
        password = request.POST.get("password", "")
        user = authenticate(request, email=email, password=password)
        if user:
            login(request, user)
            return JsonResponse({"success": True, "redirect": _post_auth_redirect(user), "tokens": _issue_tokens(user)})
        return JsonResponse({"success": False, "error": "البريد الإلكتروني أو كلمة المرور غير صحيحة"})

    return render(request, "auth/portal.html", _public_ctx(request, auth_mode="login"))


@ensure_csrf_cookie
def register_view(request):
    if request.user.is_authenticated:
        if not getattr(request.user, "organization_id", None):
            return redirect("frontend:google_pending")
        return redirect("frontend:dashboard")

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
            return JsonResponse({"success": False, "error": _first_error(serializer.errors)}, status=400)

        user = serializer.save()
        login(request, user, backend="django.contrib.auth.backends.ModelBackend")
        return JsonResponse({
            "success": True,
            "redirect": _post_auth_redirect(user),
            "tokens": _issue_tokens(user),
        })

    return render(request, "auth/portal.html", _public_ctx(request, auth_mode="register"))


def logout_view(request):
    logout(request)
    return redirect("frontend:home")


@login_required(login_url="/login/")
def google_pending(request):
    if request.user.organization:
        return redirect("frontend:dashboard")
    return render(request, "auth/google_pending.html", {"user": request.user})


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
        "invoices/detail.html",
        _ctx(request, "invoices", invoice=invoice, invoice_display=invoice_display, audit_trail=audit_trail),
    )


@login_required(login_url="/login/")
def batches(request):
    return render(request, "invoices/batches.html", _ctx(request, "batches"))


@login_required(login_url="/login/")
def batch_detail(request, pk):
    return render(request, "invoices/batch_detail.html", _ctx(request, "batches", batch_id=str(pk)))


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
