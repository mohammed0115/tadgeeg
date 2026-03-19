"""
Tadgeeg AI email notification service.
"""

import logging

from celery import shared_task
from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.utils import timezone

from core.branding import get_branding_context

logger = logging.getLogger("finai")


def _send(to: list[str], subject: str, html_body: str, text_body: str = "") -> bool:
    """Send email with HTML + plain-text fallback."""
    try:
        msg = EmailMultiAlternatives(
            subject=subject,
            body=text_body or _strip_html(html_body),
            from_email=getattr(settings, "DEFAULT_FROM_EMAIL", "noreply@tadgeeg.com"),
            to=to,
        )
        msg.attach_alternative(html_body, "text/html")
        msg.send(fail_silently=False)
        logger.info("Email sent to %s: %s", to, subject)
        return True
    except Exception as exc:
        logger.error("Email send failed to %s: %s", to, exc)
        return False


def _strip_html(html: str) -> str:
    import re

    return re.sub(r"<[^>]+>", "", html).strip()


def _branding(language: str = "ar") -> dict[str, str]:
    return get_branding_context(language)


def _base_html(title: str, body_html: str, color: str = "#2563eb") -> str:
    """Minimal inline-styled HTML email template."""
    branding = _branding("ar")
    return f"""
<!DOCTYPE html>
<html dir="rtl" lang="ar">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background:#f1f5f9;font-family:Arial,sans-serif;direction:rtl;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#f1f5f9;padding:40px 20px;">
    <tr><td align="center">
      <table width="600" cellpadding="0" cellspacing="0"
             style="background:#fff;border-radius:12px;overflow:hidden;box-shadow:0 2px 12px rgba(0,0,0,.08);">
        <tr>
          <td style="background:{color};padding:28px 32px;">
            <span style="color:#fff;font-size:22px;font-weight:bold;">{branding['product_name']}</span>
            <span style="color:rgba(255,255,255,.75);font-size:14px;margin-right:12px;">{branding['product_tagline_ar']}</span>
          </td>
        </tr>
        <tr>
          <td style="padding:28px 32px 0;">
            <h1 style="margin:0;font-size:20px;color:#0f172a;">{title}</h1>
          </td>
        </tr>
        <tr>
          <td style="padding:16px 32px 32px;">
            {body_html}
          </td>
        </tr>
        <tr>
          <td style="background:#f8fafc;padding:16px 32px;border-top:1px solid #e2e8f0;">
            <p style="margin:0;font-size:12px;color:#94a3b8;text-align:center;">
              {branding['product_name']} — {branding['company_byline']} | هذه الرسالة تلقائية، لا ترد عليها
            </p>
          </td>
        </tr>
      </table>
    </td></tr>
  </table>
</body>
</html>"""


def _kv_row(key: str, val: str, bg: str = "#fff") -> str:
    return f"""<tr style="background:{bg};">
      <td style="padding:10px 16px;color:#64748b;font-size:14px;width:40%;border-bottom:1px solid #f1f5f9;">{key}</td>
      <td style="padding:10px 16px;color:#0f172a;font-size:14px;font-weight:600;border-bottom:1px solid #f1f5f9;">{val}</td>
    </tr>"""


def _btn(label: str, url: str, color: str = "#2563eb") -> str:
    return f"""<a href="{url}" style="display:inline-block;background:{color};color:#fff;
      padding:12px 28px;border-radius:8px;text-decoration:none;font-weight:bold;
      font-size:15px;margin-top:20px;">{label}</a>"""


def notify_invoice_flagged(invoice, recipients: list[str]):
    """Alert when an invoice is flagged as high/critical risk."""
    branding = _branding("ar")
    risk_color = {"critical": "#dc2626", "high": "#ea580c"}.get(invoice.risk_level, "#f59e0b")
    risk_label = {
        "critical": "حرج",
        "high": "عالٍ",
        "medium": "متوسط",
        "low": "منخفض",
    }.get(invoice.risk_level, invoice.risk_level)

    rows = "".join(
        [
            _kv_row("رقم الفاتورة", invoice.invoice_number or "—"),
            _kv_row("المورد", invoice.vendor_name or "—", "#f8fafc"),
            _kv_row("المبلغ", f"{invoice.total_amount:,.2f} {invoice.currency}"),
            _kv_row("مستوى الخطر", f'<span style="color:{risk_color};font-weight:bold;">{risk_label}</span>', "#f8fafc"),
            _kv_row("نقاط التحقق", f"{invoice.risk_score:.0f}%"),
            _kv_row("التاريخ", str(invoice.invoice_date or "—"), "#f8fafc"),
        ]
    )

    rules_failed = ""
    if invoice.extracted_data.get("failed_rule_codes"):
        codes = invoice.extracted_data["failed_rule_codes"]
        badges = "".join(
            f'<span style="background:#fee2e2;color:#991b1b;padding:3px 8px;border-radius:4px;font-size:12px;margin:2px;display:inline-block;">{code}</span>'
            for code in codes[:8]
        )
        rules_failed = f'<p style="margin:16px 0 4px;color:#64748b;font-size:13px;">القواعد المخفقة:</p>{badges}'

    body = f"""
<p style="color:#64748b;margin:0 0 20px;">تم اكتشاف فاتورة تستوجب المراجعة الفورية:</p>
<table width="100%" cellpadding="0" cellspacing="0" style="border:1px solid #e2e8f0;border-radius:8px;overflow:hidden;">
  {rows}
</table>
{rules_failed}
<p style="margin:20px 0 4px;">{_btn("مراجعة الفاتورة", f"{settings.SITE_URL}/invoices/{invoice.id}/", risk_color)}</p>
"""
    html = _base_html(f"فاتورة معلقة — {invoice.invoice_number or 'بدون رقم'}", body, risk_color)
    return _send(recipients, f"[{branding['product_name']}] فاتورة معلقة: {invoice.invoice_number or invoice.vendor_name}", html)


def notify_audit_case_created(case, recipients: list[str]):
    """Alert when a new audit case is opened."""
    branding = _branding("ar")
    priority_color = {"critical": "#dc2626", "high": "#ea580c", "medium": "#f59e0b", "low": "#16a34a"}.get(case.priority, "#64748b")
    priority_label = {"critical": "حرج", "high": "عالٍ", "medium": "متوسط", "low": "منخفض"}.get(case.priority, case.priority)

    rows = "".join(
        [
            _kv_row("رقم القضية", case.case_number),
            _kv_row("العنوان", case.title, "#f8fafc"),
            _kv_row("النوع", case.get_case_type_display()),
            _kv_row("الأولوية", f'<span style="color:{priority_color};font-weight:bold;">{priority_label}</span>', "#f8fafc"),
            _kv_row("المسند إليه", case.assigned_to.full_name if case.assigned_to else "غير مسندة"),
            _kv_row("تاريخ الإنشاء", case.created_at.strftime("%Y-%m-%d %H:%M"), "#f8fafc"),
        ]
    )

    body = f"""
<p style="color:#64748b;margin:0 0 20px;">تم فتح قضية تدقيق جديدة:</p>
<table width="100%" cellpadding="0" cellspacing="0" style="border:1px solid #e2e8f0;border-radius:8px;overflow:hidden;">
  {rows}
</table>
<p style="margin:12px 0 0;color:#64748b;font-size:14px;">{case.description[:300]}</p>
{_btn("فتح القضية", f"{settings.SITE_URL}/audit/{case.id}/", priority_color)}
"""
    html = _base_html(f"قضية تدقيق جديدة — {case.case_number}", body, priority_color)
    return _send(recipients, f"[{branding['product_name']}] قضية تدقيق: {case.case_number} — {case.title[:50]}", html)


def notify_audit_case_escalated(case, recipients: list[str]):
    """Alert when an audit case is escalated."""
    branding = _branding("ar")
    body = f"""
<p style="color:#64748b;margin:0 0 20px;">تمت إحالة قضية التدقيق للمستوى الأعلى:</p>
<table width="100%" cellpadding="0" cellspacing="0" style="border:1px solid #e2e8f0;border-radius:8px;overflow:hidden;">
  {"".join([
      _kv_row("رقم القضية", case.case_number),
      _kv_row("العنوان", case.title, "#f8fafc"),
      _kv_row("الأولوية", case.priority.upper()),
  ])}
</table>
{_btn("مراجعة القضية", f"{settings.SITE_URL}/audit/{case.id}/", "#dc2626")}
"""
    html = _base_html(f"إحالة قضية — {case.case_number}", body, "#dc2626")
    return _send(recipients, f"[{branding['product_name']}] إحالة عاجلة: {case.case_number}", html)


def notify_payroll_anomaly(payroll, anomaly_type: str, details: str, recipients: list[str]):
    """Alert for payroll anomalies."""
    branding = _branding("ar")
    labels = {
        "ghost_employee": ("موظف وهمي محتمل", "#dc2626"),
        "duplicate_id": ("تكرار الهوية الوطنية", "#ea580c"),
        "salary_spike": ("زيادة راتب مفاجئة", "#f59e0b"),
        "calculation_error": ("خطأ في حساب الراتب", "#7c3aed"),
    }
    title_ar, color = labels.get(anomaly_type, ("شذوذ في الرواتب", "#64748b"))

    body = f"""
<p style="color:#64748b;margin:0 0 20px;">تم اكتشاف شذوذ في كشف الرواتب:</p>
<table width="100%" cellpadding="0" cellspacing="0" style="border:1px solid #e2e8f0;border-radius:8px;overflow:hidden;">
  {"".join([
      _kv_row("الشركة / القسم", payroll.company_name or payroll.department or "—"),
      _kv_row("الفترة", f"{payroll.payroll_period_from} — {payroll.payroll_period_to}", "#f8fafc"),
      _kv_row("عدد الموظفين", str(payroll.employee_count)),
      _kv_row("التفاصيل", details, "#f8fafc"),
  ])}
</table>
{_btn("مراجعة كشف الرواتب", f"{settings.SITE_URL}/documents/payroll/{payroll.id}/", color)}
"""
    html = _base_html(title_ar, body, color)
    return _send(recipients, f"[{branding['product_name']}] شذوذ في الرواتب: {title_ar}", html)


def notify_vat_late_filing(vat_return, recipients: list[str]):
    """Alert for late VAT filing."""
    branding = _branding("ar")
    body = f"""
<p style="color:#64748b;margin:0 0 20px;">الإقرار الضريبي تأخر عن الموعد المحدد:</p>
<table width="100%" cellpadding="0" cellspacing="0" style="border:1px solid #e2e8f0;border-radius:8px;overflow:hidden;">
  {"".join([
      _kv_row("الممول", vat_return.taxpayer_name),
      _kv_row("الرقم الضريبي", vat_return.vat_number, "#f8fafc"),
      _kv_row("الفترة", f"{vat_return.period_from} — {vat_return.period_to}"),
      _kv_row("تاريخ الاستحقاق", str(vat_return.due_date), "#f8fafc"),
      _kv_row("التأخير", f"{vat_return.late_days} يوم", "#fee2e2"),
      _kv_row("صافي الضريبة المستحقة", f"{vat_return.net_vat_payable:,.2f} ر.س", "#f8fafc"),
  ])}
</table>
{_btn("مراجعة الإقرار", f"{settings.SITE_URL}/documents/vat-returns/{vat_return.id}/", "#dc2626")}
"""
    html = _base_html("تأخر في تقديم الإقرار الضريبي", body, "#dc2626")
    return _send(recipients, f"[{branding['product_name']}] تأخر إقرار ضريبي: {vat_return.vat_number}", html)


def send_welcome_email(user, temp_password: str = ""):
    """Welcome email for new users."""
    branding = _branding("ar")
    temp_password_row = (
        _kv_row(
            "كلمة المرور المؤقتة",
            f'<code style="background:#f1f5f9;padding:2px 8px;border-radius:4px;">{temp_password}</code>',
            "#f8fafc",
        )
        if temp_password
        else ""
    )
    password_note = (
        "<p style='color:#dc2626;font-size:13px;'>يرجى تغيير كلمة المرور فور تسجيل الدخول الأول.</p>"
        if temp_password
        else ""
    )
    body = f"""
<p style="color:#0f172a;font-size:16px;margin:0 0 16px;">أهلًا <strong>{user.full_name}</strong>،</p>
<p style="color:#64748b;margin:0 0 20px;">تم إنشاء حسابك في {branding['product_name']}، {branding['company_byline']}.</p>
<table width="100%" cellpadding="0" cellspacing="0" style="border:1px solid #e2e8f0;border-radius:8px;overflow:hidden;margin:0 0 20px;">
  {"".join([
      _kv_row("البريد الإلكتروني", user.email),
      _kv_row("الدور", user.get_role_display() if hasattr(user, "get_role_display") else user.role, "#f8fafc"),
      _kv_row("المؤسسة", user.organization.name if user.organization else "—"),
      temp_password_row,
  ])}
</table>
{password_note}
{_btn("تسجيل الدخول", f"{settings.SITE_URL}/login/")}
"""
    html = _base_html(f"مرحبًا بك في {branding['product_name']} 🎉", body, "#2563eb")
    return _send([user.email], f"[{branding['product_name']}] مرحبًا بك في نظام التدقيق المالي", html)


def send_weekly_summary(org, summary_data: dict, recipients: list[str]):
    """Weekly audit summary email."""
    branding = _branding("ar")
    data = summary_data
    rows = "".join(
        [
            _kv_row("الفواتير المرفوعة", str(data.get("invoices_total", 0))),
            _kv_row("فواتير معلقة", str(data.get("invoices_flagged", 0)), "#fff7ed"),
            _kv_row("قضايا تدقيق جديدة", str(data.get("cases_new", 0)), "#f8fafc"),
            _kv_row("قضايا مغلقة", str(data.get("cases_closed", 0))),
            _kv_row("إجمالي المعاملات", f"{data.get('tx_total', 0):,} ر.س", "#f8fafc"),
            _kv_row("وثائق أخرى رُفعت", str(data.get("docs_uploaded", 0))),
        ]
    )

    body = f"""
<p style="color:#64748b;margin:0 0 20px;">ملخص نشاط التدقيق للأسبوع المنتهي {timezone.now().strftime('%Y-%m-%d')}:</p>
<table width="100%" cellpadding="0" cellspacing="0" style="border:1px solid #e2e8f0;border-radius:8px;overflow:hidden;">
  {rows}
</table>
{_btn("عرض التقرير الكامل", f"{settings.SITE_URL}/reports/")}
"""
    html = _base_html(f"ملخص أسبوعي — {org.name}", body)
    return _send(recipients, f"[{branding['product_name']}] الملخص الأسبوعي — {org.name}", html)


@shared_task(name="notifications.send_invoice_flagged_alert")
def task_notify_invoice_flagged(invoice_id: str):
    """Async task: send alert for flagged invoice."""
    try:
        from apps.authentication.models import User
        from apps.invoices.models import Invoice

        invoice = Invoice.objects.select_related("organization").get(pk=invoice_id)
        recipients = list(
            User.objects.filter(
                organization=invoice.organization,
                role__in=["admin", "cao", "senior_auditor"],
                is_active=True,
            ).values_list("email", flat=True)
        )
        if recipients:
            notify_invoice_flagged(invoice, recipients)
    except Exception as exc:
        logger.error("task_notify_invoice_flagged failed: %s", exc)


@shared_task(name="notifications.weekly_summary")
def task_weekly_summary():
    """Async task: send weekly summary to all active organisations."""
    try:
        from datetime import timedelta

        from django.db.models import Sum

        from apps.audit.models import AuditCase
        from apps.authentication.models import Organization, User
        from apps.invoices.models import Invoice

        one_week_ago = timezone.now() - timedelta(days=7)

        for org in Organization.objects.filter(is_active=True):
            summary = {
                "invoices_total": Invoice.objects.filter(organization=org, created_at__gte=one_week_ago).count(),
                "invoices_flagged": Invoice.objects.filter(organization=org, created_at__gte=one_week_ago, status="flagged").count(),
                "cases_new": AuditCase.objects.filter(organization=org, created_at__gte=one_week_ago).count(),
                "cases_closed": AuditCase.objects.filter(organization=org, resolved_at__gte=one_week_ago).count(),
                "tx_total": 0,
                "docs_uploaded": 0,
            }
            recipients = list(
                User.objects.filter(organization=org, role__in=["admin", "cao"], is_active=True).values_list("email", flat=True)
            )
            if recipients:
                send_weekly_summary(org, summary, recipients)
    except Exception as exc:
        logger.error("task_weekly_summary failed: %s", exc)
