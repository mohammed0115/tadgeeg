"""Document Detection Service — heuristic document type detection."""

import re


class DocumentDetectionService:
    """Heuristic document type detection from text before AI call."""

    KEYWORDS = {
        "purchase_order": [
            "purchase order", "po number", "po#", "p.o.", "order number",
            "أمر شراء", "طلب شراء", "مشتريات", "رقم الأمر", "أوامر الشراء",
        ],
        "bank_statement": [
            "bank statement", "opening balance", "closing balance", "account number",
            "transaction date", "debit", "credit", "balance brought forward",
            "كشف حساب", "رصيد", "كشف بنكي", "رصيد افتتاحي", "رصيد ختامي",
            "حساب جاري", "مديونية", "دائن", "مدين",
        ],
        "payroll": [
            "payroll", "salary", "employee", "net salary", "gross salary",
            "basic salary", "allowance", "deduction", "pay slip", "payslip",
            "راتب", "رواتب", "موظف", "موظفون", "صافي الراتب", "الراتب الأساسي",
            "مسير الرواتب", "بدلات", "خصومات", "كشف الرواتب",
        ],
        "expense_report": [
            "expense report", "expense claim", "reimbursement", "out of pocket",
            "travel expense", "entertainment", "petty cash",
            "مصروفات", "مصاريف", "تسوية", "سلفة", "مطالبة المصروفات",
            "تقرير المصروفات", "مصاريف السفر", "عهدة",
        ],
        "vat_return": [
            "vat return", "tax declaration", "value added tax", "zatca",
            "taxable supplies", "input tax", "output tax", "net vat",
            "ضريبة القيمة المضافة", "إقرار ضريبي", "الضريبة المستحقة",
            "ضريبة المدخلات", "ضريبة المخرجات", "هيئة الزكاة والضريبة",
        ],
        "fixed_asset": [
            "fixed asset", "depreciation", "net book value", "acquisition cost",
            "asset register", "useful life", "residual value", "amortization",
            "أصول ثابتة", "إهلاك", "استهلاك", "القيمة الدفترية", "سجل الأصول",
            "تكلفة الاقتناء", "العمر الإنتاجي",
        ],
        "sales_receipt": [
            "receipt", "sales receipt", "payment received", "cash receipt",
            "إيصال", "فاتورة مبيعات", "وصل", "إيصال الدفع",
        ],
        "invoice": [
            "invoice", "tax invoice", "bill to", "invoice number", "inv#",
            "فاتورة", "فاتورة ضريبية", "رقم الفاتورة",
        ],
    }

    def detect(self, text: str, hint: str = "auto") -> tuple:
        """
        Return (doc_type, confidence) using keyword scoring.
        If hint is not 'auto', it biases the score.
        """
        if not text:
            if hint and hint != "auto":
                return (hint, 0.5)
            return ("other", 0.0)

        text_lower = text.lower()
        scores = {}

        for doc_type, keywords in self.KEYWORDS.items():
            hits = 0
            for kw in keywords:
                # Count occurrences (case-insensitive)
                count = len(re.findall(re.escape(kw.lower()), text_lower))
                if count > 0:
                    # More matches = higher weight, diminishing returns
                    hits += min(count, 3)
            scores[doc_type] = hits

        if not any(scores.values()):
            # No keywords matched
            if hint and hint != "auto":
                return (hint, 0.4)
            return ("other", 0.1)

        best_type = max(scores, key=scores.get)
        best_score = scores[best_type]
        total_hits = sum(scores.values())

        # Raw confidence: ratio of best type hits to total hits
        raw_confidence = best_score / total_hits if total_hits > 0 else 0.0

        # Apply hint bias: if hint matches detected, boost confidence
        if hint and hint != "auto" and hint == best_type:
            confidence = min(raw_confidence + 0.15, 1.0)
        elif hint and hint != "auto" and hint != best_type:
            # Conflicting hint: return detected type but reduce confidence slightly
            confidence = max(raw_confidence - 0.1, 0.1)
        else:
            confidence = raw_confidence

        # Normalize confidence: minimum 0.3 if we have any hit
        confidence = max(confidence, 0.3)
        confidence = min(confidence, 0.95)

        return (best_type, round(confidence, 3))
