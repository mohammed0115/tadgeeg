"""
Tadgeeg AI Assistant — multi-turn chat endpoint backed by GPT-4o.

Features:
- Conversation memory: last N exchanges per (user, org) cached for 1h so
  follow-up questions ("and which one is highest?") work without re-asking.
- DB-grounded context: every turn re-injects a fresh snapshot of the org's
  KPIs so the model can answer factual questions accurately.
- Per-org daily token budget enforced via ai_budget; falls back gracefully
  when exceeded.

Endpoints:
    POST /api/v1/assistant/chat/   — body: {"message": "..."}
    POST /api/v1/assistant/reset/  — clears conversation history
    GET  /api/v1/assistant/history/ — returns recent turns
"""
from __future__ import annotations

import json
import logging

from django.conf import settings
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

logger = logging.getLogger("finai")

_SYSTEM_PROMPT = """\
أنت Tadgeeg AI — مساعد ذكي متخصص في التدقيق المالي والمحاسبة و ERP والمخاطر المالية والامتثال الضريبي (VAT/ZATCA).
دورك مساعدة المراجع المالي والمحاسب ومدير المالية على فهم نتائج التدقيق وتفسير المخاطر واقتراح إجراءات تصحيحية.

You are a bilingual expert. Match the user's language (Arabic ↔ English) and switch mid-conversation if they do.

═══════════════════════════════════════════════════════════════════════════
قواعد ذهبية لا تخالفها:
═══════════════════════════════════════════════════════════════════════════
1. اعتمد فقط على البيانات الموجودة في الـ context JSON الذي يصل مع رسالة المستخدم.
2. لا تخترع أرقام فواتير أو أسماء موردين أو مبالغ. لو ما عندك دليل، قل بوضوح:
   "لا أملك بيانات كافية من النظام للحكم على هذه الحالة."
3. لا تقل إن فاتورة مكررة إلا لو الـ context يثبتها (`is_duplicate: true` أو duplicate_invoice details).
4. لا تقل إن مورد خطير إلا لو فيه مؤشرات (high-risk count، fraud flag، duplicate count).
5. لا تعطِ حكم نهائي في حالات قانونية/ضريبية حساسة. قل: "يوصى بمراجعة المراجع المالي أو المستشار الضريبي."
6. كل ادعاء رقمي = اربطه بحقل من الـ context (مثلاً "حسب failed_rules: VAT-02").

═══════════════════════════════════════════════════════════════════════════
منهجية تحليل أي مستند (طبّقها بالترتيب):
═══════════════════════════════════════════════════════════════════════════
1) نوع المستند: Invoice / PO / Bank Statement / Journal / Contract / Payroll / Expense / Receipt
2) البيانات الأساسية: رقم، تاريخ، المورد/العميل، المبلغ، الضريبة، العملة، الحالة، المستندات المرتبطة
3) نتائج قواعد التدقيق: قواعد passed، failed، not-applicable، لم تعمل
4) مستوى الخطر: Low / Medium / High / Critical
5) سبب الخطر: مكرر؟ ضريبة خاطئة؟ غياب PO/GRN؟ قيد غير متوازن؟ مورد جديد؟ تلاعب؟
6) Evidence: رقم الفاتورة، رقم PO، الفرق، اسم القاعدة الكاشفة
7) التوصية: مراجعة يدوية / طلب مستند / إيقاف الدفع / إعادة احتساب VAT / تصعيد / رفض / قبول

═══════════════════════════════════════════════════════════════════════════
شكل الردّ المطلوب (للأسئلة عن مستند محدد أو حالة):
═══════════════════════════════════════════════════════════════════════════
**ملخص التدقيق**

1. **نتيجة الفحص**: سليم / فيه مخاطر — سطر واحد.
2. **مستوى الخطر**: Low / Medium / High / Critical
3. **سبب التصنيف**: شرح موجز بلغة بسيطة (سطر-سطرين).
4. **الأدلة**: أرقام الفواتير، الفروق، القواعد التي كشفت — كل دليل مع مرجعه من الـcontext.
5. **القواعد التي فشلت**: code + اسم (مثلاً VAT-02 — VAT Calculation).
6. **المستندات الناقصة**: PO؟ GRN؟ Contract؟
7. **التوصية**: إجراء عملي.
8. **القرار المقترح**: قبول / قبول مشروط / مراجعة يدوية / إيقاف الدفع / رفض.

للأسئلة العامة (إحصاءات، ملخص للإدارة، أكثر القواعد فشلاً): ردّ مختصر منظم.
لا تستخدم أكثر من ~250 كلمة إلا لو طُلب منك تقرير تفصيلي.

═══════════════════════════════════════════════════════════════════════════
المصطلحات التقنية (استخدمها واشرحها بساطة عند الحاجة):
═══════════════════════════════════════════════════════════════════════════
Risk Score · Audit Trail · Duplicate Check · 3-Way Matching · Anomaly Detection ·
VAT Compliance · ZATCA Phase 2 · Benford's Law · Evidence · Exception ·
Control Failure · Segregation of Duties · Materiality · PIH chain · TRN format
(Saudi TRN: 15 digits, starts AND ends with 3).
"""


def _build_fallback_answer(message: str, context: dict) -> str:
    """Return a deterministic, DB-grounded answer when the LLM is unavailable."""
    summary = context.get("invoice_summary") or {}
    totals = context.get("totals") or {}
    top_rules = context.get("top_failing_rules_30d") or []
    risky_vendors = context.get("top_risky_vendors") or []

    lines = [
        "ملخص سريع من بيانات النظام الحالية:",
        f"- عدد الفواتير: {summary.get('approved', 0) + summary.get('pending_review', 0) + summary.get('flagged', 0) + summary.get('rejected', 0)}",
        f"- الفواتير عالية/حرجة المخاطر: {summary.get('high_risk', 0)}",
        f"- الفواتير المكررة: {summary.get('duplicates', 0)}",
        f"- الفواتير قيد المراجعة: {summary.get('pending_review', 0)}",
        f"- إجمالي المستندات الأساسية: فواتير {totals.get('invoices', 0)}، أوامر شراء {totals.get('purchase_orders', 0)}، سندات دفع {totals.get('payment_vouchers', 0)}",
    ]
    if top_rules:
        top = ", ".join(f"{item.get('code')} ({item.get('count')})" for item in top_rules[:3])
        lines.append(f"- أكثر القواعد فشلاً آخر 30 يوم: {top}")
    if risky_vendors:
        top_vendor = risky_vendors[0]
        lines.append(
            f"- أعلى مورد خطورة حاليًا: {top_vendor.get('name')} بعدد {top_vendor.get('high_risk_invoices', 0)} فواتير عالية المخاطر"
        )
    lines.append("تعذر الوصول إلى خدمة الذكاء الاصطناعي الآن، لذا هذا الرد مبني فقط على بيانات النظام المتاحة بدون استنتاجات إضافية.")
    return "\n".join(lines)


# ── Conversation memory (cache-backed, per user) ──────────────────────────────
#
# Key shape: assistant:hist:<user_id>. Stores list[{"role","content"}], capped
# at MEMORY_TURNS exchanges (each = one user msg + one assistant reply).
# 1h TTL keeps short-term context without growing unbounded.

MEMORY_TURNS = 8         # → 16 messages stored max (8 user + 8 assistant)
MEMORY_TTL = 3600        # 1 hour


def _hist_key(user) -> str:
    return f"assistant:hist:{user.id}"


def _load_history(user) -> list:
    from django.core.cache import cache
    return cache.get(_hist_key(user)) or []


def _save_history(user, history: list) -> None:
    from django.core.cache import cache
    # Keep the trailing 2*MEMORY_TURNS messages so memory doesn't grow without bound.
    trimmed = history[-(MEMORY_TURNS * 2):]
    cache.set(_hist_key(user), trimmed, MEMORY_TTL)


def _clear_history(user) -> None:
    from django.core.cache import cache
    cache.delete(_hist_key(user))


def _build_context(user, focus_invoice_id: str | None = None,
                   focus_vendor: str | None = None,
                   focus_doc_type: str | None = None,
                   focus_doc_id: str | None = None) -> dict:
    """Snapshot of the org's current state to ground the model.

    The base snapshot is the same for every turn (totals + invoice summary).
    When the caller supplies ``focus_invoice_id`` or ``focus_vendor`` we add a
    deep-dive section so the assistant can answer "why is INV-1023 high risk?"
    accurately — listing failed rules, missing docs, evidence, and matched POs
    instead of guessing.
    """
    from collections import Counter
    from datetime import timedelta
    from django.db.models import Sum, Count, Q
    from django.utils import timezone

    org = getattr(user, "organization", None)
    if not org:
        return {"organization": None}

    from apps.invoices.models import Invoice
    from apps.documents.typed_models import (
        PurchaseOrder, BankStatement, PayrollSheet, ExpenseReport,
        VATReturn, FixedAsset, SalesReceipt,
        GoodsReceiptNote, PaymentVoucher,
    )
    from apps.documents.typed_models_v2 import (
        SalesOrder, Quotation, ProformaInvoice, ReceiptVoucher, CashVoucher,
        GeneralLedger, Ledger, Contract, SupplierStatement, CustomerStatement,
    )

    invs = Invoice.objects.filter(organization=org)

    ctx: dict = {
        "organization": str(org.name) if hasattr(org, "name") else str(org.id),
        "as_of": timezone.now().isoformat(),
        "totals": {
            # Phase 1
            "invoices":            invs.count(),
            "purchase_orders":     PurchaseOrder.objects.filter(organization=org).count(),
            "sales_receipts":      SalesReceipt.objects.filter(organization=org).count(),
            "bank_statements":     BankStatement.objects.filter(organization=org).count(),
            "payroll":             PayrollSheet.objects.filter(organization=org).count(),
            "expense_reports":     ExpenseReport.objects.filter(organization=org).count(),
            "vat_returns":         VATReturn.objects.filter(organization=org).count(),
            "fixed_assets":        FixedAsset.objects.filter(organization=org).count(),
            "goods_receipt_notes": GoodsReceiptNote.objects.filter(organization=org).count(),
            "payment_vouchers":    PaymentVoucher.objects.filter(organization=org).count(),
            # Phase 2
            "sales_orders":        SalesOrder.objects.filter(organization=org).count(),
            "quotations":          Quotation.objects.filter(organization=org).count(),
            "proforma_invoices":   ProformaInvoice.objects.filter(organization=org).count(),
            "receipt_vouchers":    ReceiptVoucher.objects.filter(organization=org).count(),
            "cash_vouchers":       CashVoucher.objects.filter(organization=org).count(),
            "general_ledgers":     GeneralLedger.objects.filter(organization=org).count(),
            "ledgers":             Ledger.objects.filter(organization=org).count(),
            "contracts":           Contract.objects.filter(organization=org).count(),
            "supplier_statements": SupplierStatement.objects.filter(organization=org).count(),
            "customer_statements": CustomerStatement.objects.filter(organization=org).count(),
        },
        "invoice_summary": {
            "total_amount":   float(invs.aggregate(s=Sum("total_amount"))["s"] or 0),
            "vat_total":      float(invs.aggregate(s=Sum("vat_amount"))["s"] or 0),
            "high_risk":      invs.filter(risk_level__in=["high", "critical"]).count(),
            "duplicates":     invs.filter(is_duplicate=True).count(),
            "missing_qr":     invs.filter(qr_code_valid=False).count(),
            "pending_review": invs.filter(status__in=["pending", "processing"]).count(),
            "approved":       invs.filter(status="approved").count(),
            "flagged":        invs.filter(status="flagged").count(),
            "rejected":       invs.filter(status="rejected").count(),
        },
    }

    # ── Top failing rules (last 30 days) ─────────────────────────────────────
    # Validation lives on the related InvoiceValidationResult — denoted via the
    # `validation` 1-to-1 relation. We pull failed_rule_codes via that join.
    cutoff = timezone.now() - timedelta(days=30)
    rule_counter: Counter = Counter()
    try:
        from apps.invoices.models import InvoiceValidationResult
        for codes in InvoiceValidationResult.objects.filter(
            invoice__organization=org,
            invoice__created_at__gte=cutoff,
        ).values_list("failed_rule_codes", flat=True):
            if codes:
                rule_counter.update(codes)
    except Exception:
        pass
    ctx["top_failing_rules_30d"] = [
        {"code": code, "count": n} for code, n in rule_counter.most_common(8)
    ]

    # ── Top high-risk vendors ────────────────────────────────────────────────
    vendor_risk = (
        invs.exclude(vendor_name="")
        .values("vendor_name")
        .annotate(
            invoice_count=Count("id"),
            high_risk_count=Count("id", filter=Q(risk_level__in=["high", "critical"])),
            duplicate_count=Count("id", filter=Q(is_duplicate=True)),
            total=Sum("total_amount"),
        )
        .filter(high_risk_count__gt=0)
        .order_by("-high_risk_count")[:5]
    )
    ctx["top_risky_vendors"] = [
        {
            "name": v["vendor_name"],
            "invoices": v["invoice_count"],
            "high_risk_invoices": v["high_risk_count"],
            "duplicates": v["duplicate_count"],
            "total_amount": float(v["total"] or 0),
        }
        for v in vendor_risk
    ]

    # ── Recent flagged invoices (so the model can answer "what needs review?") ──
    ctx["recent_flagged"] = [
        {
            "id": str(i["id"]),
            "invoice_number": i["invoice_number"],
            "vendor_name": i["vendor_name"],
            "total_amount": float(i["total_amount"] or 0),
            "risk_level": i["risk_level"],
            "status": i["status"],
            "is_duplicate": i["is_duplicate"],
        }
        for i in invs.filter(
            Q(risk_level__in=["high", "critical"]) | Q(is_duplicate=True)
        )
        .order_by("-created_at")
        .values("id", "invoice_number", "vendor_name", "total_amount",
                "risk_level", "status", "is_duplicate")[:10]
    ]

    # ── Deep-dive: focus on a specific invoice ───────────────────────────────
    if focus_invoice_id:
        try:
            inv = invs.select_related("approved_by", "validation").get(id=focus_invoice_id)
            # Validation fields live on inv.validation (InvoiceValidationResult) —
            # may not exist if the audit hasn't run yet.
            val = getattr(inv, "validation", None)
            failed_codes = (val.failed_rule_codes if val else []) or []
            details = ((val.validation_details if val else {}) or {})
            rule_details = details.get("rule_details") or details.get("validation_results") or []
            # Compact the rule details to just code + status + message + severity.
            compacted_rules = []
            if isinstance(rule_details, list):
                for r in rule_details[:30]:
                    if isinstance(r, dict):
                        compacted_rules.append({
                            "code":     r.get("code") or r.get("rule_code"),
                            "passed":   r.get("passed", r.get("status") == "pass"),
                            "severity": r.get("severity"),
                            "message":  (r.get("message") or r.get("explanation_en") or "")[:200],
                        })
            elif isinstance(rule_details, dict):
                for code, r in list(rule_details.items())[:30]:
                    compacted_rules.append({
                        "code":     code,
                        "passed":   bool(r.get("passed")) if isinstance(r, dict) else None,
                        "severity": r.get("severity") if isinstance(r, dict) else None,
                        "message":  (r.get("message") or "")[:200] if isinstance(r, dict) else "",
                    })

            # Cross-document linkage: PO ↔ GRN ↔ Invoice ↔ Payment + Contract.
            # Returns {purchase_order, goods_receipt_note, payment_voucher,
            # contract, _three_way_match}; consumers (e.g. the model) treat the
            # absence of a linked doc as "missing X".
            try:
                from core.services.cross_doc_linker import find_links
                cross_links = find_links("invoice", inv, org)
            except Exception as exc:
                logger.warning("[assistant] cross_doc_linker failed: %s", exc)
                cross_links = {}

            ctx["focus_invoice"] = {
                "id": str(inv.id),
                "invoice_number": inv.invoice_number,
                "vendor_name": inv.vendor_name,
                "vendor_vat_number": inv.vendor_vat_number,
                "invoice_date": str(inv.invoice_date) if inv.invoice_date else None,
                "due_date": str(inv.due_date) if inv.due_date else None,
                "currency": inv.currency,
                "subtotal": float(inv.subtotal or 0),
                "vat_amount": float(inv.vat_amount or 0),
                "vat_rate": float(inv.vat_rate or 0),
                "total_amount": float(inv.total_amount or 0),
                "status": inv.status,
                "risk_level": inv.risk_level,
                "is_duplicate": inv.is_duplicate,
                "duplicate_of": str(inv.duplicate_of_id) if inv.duplicate_of_id else None,
                "qr_code_valid": inv.qr_code_valid,
                "ocr_confidence": float(inv.ocr_confidence or 0),
                "validation_score": float(getattr(val, "validation_score", 0) or 0),
                "rules_passed": getattr(val, "rules_passed", 0) or 0,
                "rules_failed": getattr(val, "rules_failed", 0) or 0,
                "failed_rule_codes": failed_codes,
                "rule_evidence": compacted_rules,
                "approved_by": getattr(inv.approved_by, "email", None) if inv.approved_by else None,
                "rejected_reason": inv.rejected_reason or None,
                "ai_summary": (inv.ai_summary or "")[:400],
                "cross_doc_links": cross_links,
            }
        except Invoice.DoesNotExist:
            ctx["focus_invoice"] = {"error": "invoice_not_found"}

    # ── Deep-dive: focus on any non-invoice typed document (PO, GRN, …) ─────
    # The detail page passes (doc_type, doc_id); we resolve the model, build a
    # field summary, and add cross-doc links so the assistant can ground its
    # answer in concrete relationships rather than guesses.
    if focus_doc_type and focus_doc_id and focus_doc_type != "invoice":
        try:
            from core.services.cross_doc_linker import find_links, _models as _linker_models
            model_map = _linker_models()
            Model = model_map.get(focus_doc_type)
            if Model is None:
                ctx["focus_doc"] = {"error": "unsupported_doc_type", "doc_type": focus_doc_type}
            else:
                obj = Model.objects.filter(organization=org, id=focus_doc_id).first()
                if obj is None:
                    ctx["focus_doc"] = {"error": "doc_not_found",
                                        "doc_type": focus_doc_type}
                else:
                    # Summarise the doc as a flat dict of its meaningful fields.
                    summary: dict = {"doc_type": focus_doc_type, "id": str(obj.id)}
                    for f in obj._meta.get_fields():
                        if not getattr(f, "concrete", False) or f.is_relation:
                            continue
                        name = f.name
                        if name in ("organization", "uploaded_by", "document",
                                    "created_at", "updated_at"):
                            continue
                        val = getattr(obj, name, None)
                        if val in (None, "", []):
                            continue
                        # Coerce to JSON-safe primitives
                        if hasattr(val, "isoformat"):
                            val = val.isoformat()
                        elif isinstance(val, (list, dict)):
                            pass  # already JSON-safe (typed_models use JSONField)
                        else:
                            val = str(val)
                        summary[name] = val
                    summary["cross_doc_links"] = find_links(focus_doc_type, obj, org)
                    summary["audit_status"] = getattr(obj, "audit_status", None)
                    summary["risk_level"] = getattr(obj, "risk_level", None)
                    summary["failed_rule_codes"] = (
                        getattr(obj, "failed_rule_codes", None) or []
                    )
                    ctx["focus_doc"] = summary
        except Exception as exc:
            logger.warning("[assistant] focus_doc resolution failed: %s", exc)
            ctx["focus_doc"] = {"error": "resolver_failed", "detail": str(exc)[:200]}

    # ── Deep-dive: focus on a specific vendor ────────────────────────────────
    if focus_vendor:
        v_invs = invs.filter(vendor_name__iexact=focus_vendor)
        if v_invs.exists():
            ctx["focus_vendor"] = {
                "vendor_name": focus_vendor,
                "invoice_count": v_invs.count(),
                "total_amount": float(v_invs.aggregate(s=Sum("total_amount"))["s"] or 0),
                "high_risk_count": v_invs.filter(risk_level__in=["high", "critical"]).count(),
                "duplicate_count": v_invs.filter(is_duplicate=True).count(),
                "rejected_count": v_invs.filter(status="rejected").count(),
                "first_seen": str(v_invs.order_by("created_at").values_list("created_at", flat=True).first()),
                "last_seen": str(v_invs.order_by("-created_at").values_list("created_at", flat=True).first()),
                "vat_numbers_used": list(v_invs.values_list("vendor_vat_number", flat=True).distinct()[:5]),
            }
        else:
            ctx["focus_vendor"] = {"error": "vendor_not_found", "queried": focus_vendor}

    return ctx


class AssistantChatView(APIView):
    """POST /api/v1/assistant/chat/  — body: {"message": "..."}"""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        message = (request.data.get("message") or "").strip()
        if not message:
            return Response({"error": "empty message"}, status=400)
        if len(message) > 2000:
            return Response({"error": "message too long (max 2000 chars)"}, status=400)

        if not settings.OPENAI_API_KEY:
            return Response({
                "answer": "AI assistant is not configured (no OPENAI_API_KEY).",
                "fallback": True,
            }, status=200)

        from core.services import ai_budget
        org_id = getattr(getattr(request.user, "organization", None), "id", None)
        try:
            ai_budget.guard(org_id, projected_tokens=1500)
        except ai_budget.BudgetExceeded as exc:
            return Response({
                "answer": "تجاوزت الحد اليومي لاستخدام الذكاء الاصطناعي. حاول غداً.",
                "budget_exceeded": True,
                "used": exc.used, "cap": exc.cap,
            }, status=429)

        # Build the message list: system → recent history → fresh-context user turn.
        # Re-injecting the JSON context every turn means the model always sees
        # current numbers even if invoices changed mid-conversation. Callers
        # can pass `focus_invoice_id` or `focus_vendor` to make the assistant
        # answer questions about a specific document with full evidence.
        focus_invoice_id = (request.data.get("focus_invoice_id") or "").strip() or None
        focus_vendor     = (request.data.get("focus_vendor") or "").strip() or None
        focus_doc_type   = (request.data.get("focus_doc_type") or "").strip() or None
        focus_doc_id     = (request.data.get("focus_doc_id") or "").strip() or None
        context = _build_context(
            request.user, focus_invoice_id, focus_vendor,
            focus_doc_type=focus_doc_type, focus_doc_id=focus_doc_id,
        )
        history = _load_history(request.user)

        user_payload = (
            f"context (JSON, do NOT echo back):\n{json.dumps(context, ensure_ascii=False)}\n\n"
            f"user question:\n{message}"
        )

        messages = [{"role": "system", "content": _SYSTEM_PROMPT}]
        # Older history first, then the new turn.
        for prev in history:
            messages.append(prev)
        messages.append({"role": "user", "content": user_payload})

        try:
            from openai import OpenAI
            client = OpenAI(api_key=settings.OPENAI_API_KEY)
            resp = client.chat.completions.create(
                model=settings.OPENAI_MODEL,
                messages=messages,
                max_tokens=600,
                temperature=0.2,
            )
            answer = resp.choices[0].message.content.strip()
            if getattr(resp, "usage", None) and org_id:
                ai_budget.charge(org_id, int(resp.usage.total_tokens))

            # Persist this turn into memory. Store the *bare* user message
            # (without the context JSON) so context is fresh next turn.
            history.append({"role": "user",      "content": message})
            history.append({"role": "assistant", "content": answer})
            _save_history(request.user, history)

            return Response({
                "answer": answer,
                "tokens_used": int(getattr(resp.usage, "total_tokens", 0) or 0),
                "history_length": len(history),
            })
        except Exception as exc:
            logger.exception("assistant chat failed: %s", exc)
            return Response({
                "answer": _build_fallback_answer(message, context),
                "fallback": True,
                "error": str(exc)[:200],
            }, status=200)


class AssistantResetView(APIView):
    """POST /api/v1/assistant/reset/ — clear this user's chat memory."""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        _clear_history(request.user)
        return Response({"cleared": True})


class AssistantHistoryView(APIView):
    """GET /api/v1/assistant/history/ — return recent turns (for UI restore)."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response({"messages": _load_history(request.user)})
