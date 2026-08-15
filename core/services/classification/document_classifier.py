"""
Document Classifier

Determines the financial document type from raw text or structured data.

Classification strategy (in order):
  1. Structural signals from parsed data (line_items present → invoice)
  2. Keyword-based heuristics (fast, deterministic)
  3. OpenAI classification (accurate, tolerant of messy text)
  4. Default → "other"

Document types:
  invoice | purchase_order | bank_statement | receipt
  expense_report | payroll | vat_return | other
"""

import logging
import re
from typing import Optional

logger = logging.getLogger("finai")

#: Values that mean "nobody determined this", written by normalization.py when
#: no parser produced a type. They are not document types and must never be
#: certified as one — see _classify_structural.
_UNDETERMINED = frozenset({"unknown", "", None})

DOCUMENT_TYPES = [
    "invoice",
    "purchase_order",
    "bank_statement",
    "receipt",
    "expense_report",
    "payroll",
    "vat_return",
    "other",
]

# ── Keyword maps ──────────────────────────────────────────────────────────────
# Each list contains strong signal words for that document type.
KEYWORD_MAP: dict[str, list[str]] = {
    "invoice": [
        "invoice", "فاتورة", "inv no", "invoice number", "invoice #",
        "bill to", "sold to", "payment terms", "due date",
        "vat invoice", "tax invoice", "e-invoice",
    ],
    "purchase_order": [
        "purchase order", "أمر شراء", "p.o.", "po number", "po #",
        "order confirmation", "purchase requisition", "vendor order",
    ],
    "bank_statement": [
        "bank statement", "كشف حساب", "account statement", "statement of account",
        "opening balance", "closing balance", "debit", "credit", "balance",
        "iban", "swift", "transaction history",
    ],
    "receipt": [
        "receipt", "إيصال", "cash receipt", "payment receipt",
        "received from", "payment received", "pos receipt", "till receipt",
    ],
    "expense_report": [
        "expense report", "تقرير مصروفات", "expense claim",
        "reimbursement", "travel expense", "business expense",
        "expenses submitted by",
    ],
    "payroll": [
        "payroll", "كشف الرواتب", "salary", "pay slip", "payslip",
        "wage", "compensation", "net pay", "gross pay", "deduction",
        "employee id", "department", "basic salary",
    ],
    "vat_return": [
        "vat return", "إقرار ضريبة القيمة المضافة", "tax return",
        "zatca", "vat declaration", "tax period", "output vat", "input vat",
        "vat refund", "tax registration number",
    ],
}


class DocumentClassifier:
    """
    Multi-strategy document type classifier.

    Usage:
        clf = DocumentClassifier()
        result = clf.classify(raw_text="فاتورة ضريبية ...", structured={...})
        print(result)  # {'document_type': 'invoice', 'confidence': 0.92}
    """

    def classify(
        self,
        raw_text: str = "",
        structured: dict = None,
        use_ai: bool = True,
    ) -> dict:
        """
        Classify the document type.

        Args:
            raw_text:   Raw OCR or parsed text.
            structured: Structured fields extracted by a parser.
            use_ai:     Whether to call OpenAI if heuristics are inconclusive.

        Returns:
            {
              document_type: str,
              confidence: float (0–1),
              method: str ('structural' | 'keyword' | 'ai' | 'default')
            }
        """
        structured = structured or {}

        # ── 1. Structural signals ─────────────────────────────────────────────
        result = self._classify_structural(structured)
        if result and result["confidence"] >= 0.85:
            logger.debug("[Classifier] Structural match: %s", result)
            return result

        # ── 2. Keyword heuristics ─────────────────────────────────────────────
        keyword_result = self._classify_keywords(raw_text, structured)
        if keyword_result and keyword_result["confidence"] >= 0.70:
            logger.debug("[Classifier] Keyword match: %s", keyword_result)
            return keyword_result

        # ── 3. AI classification ──────────────────────────────────────────────
        if use_ai and raw_text:
            ai_result = self._classify_ai(raw_text)
            if ai_result and ai_result["confidence"] >= 0.50:
                logger.debug("[Classifier] AI match: %s", ai_result)
                return ai_result

        # ── 4. Best heuristic or default ─────────────────────────────────────
        if keyword_result:
            return keyword_result

        return {"document_type": "other", "confidence": 0.0, "method": "default"}

    # ── Structural classifier ─────────────────────────────────────────────────

    def _classify_structural(self, structured: dict) -> Optional[dict]:
        """Use structural keys to determine document type."""
        if not structured:
            return None

        # Explicit type field already set by parser/AI.
        #
        # This branch certifies a value at 0.90 as a *structural determination*.
        # That claim is only honest when something upstream actually determined
        # it. It was not: normalization.py defaulted the field to "invoice", and
        # this branch read that default back and stamped it 0.90 — 17 of 34
        # measured documents, every one of them by this path, none of them by
        # keyword or by AI. A guess entered the system and left it a
        # measurement.
        #
        # The sentinels below are what "nobody determined this" looks like, and
        # they are refused here rather than certified. Refusing lets the value
        # fall through to the keyword and AI branches, which are the parts of
        # this method that actually look at the document.
        #
        # "unknown" is already outside DOCUMENT_TYPES, so it would fall through
        # anyway. It is named explicitly so that adding it to that list later
        # cannot silently re-open this hole.
        dtype = structured.get("document_type", "")
        if (dtype and dtype not in _UNDETERMINED
                and dtype in DOCUMENT_TYPES and dtype != "other"):
            return {"document_type": dtype, "confidence": 0.90, "method": "structural"}

        # Presence of line_items → invoice or purchase order
        if structured.get("line_items"):
            doc_type = "invoice"
            if "purchase_order" in str(structured.get("notes", "")).lower():
                doc_type = "purchase_order"
            return {"document_type": doc_type, "confidence": 0.80, "method": "structural"}

        # Bank statement signals
        if "opening_balance" in structured or "closing_balance" in structured:
            return {"document_type": "bank_statement", "confidence": 0.85, "method": "structural"}

        # Records array → likely bank statement or expense report
        records = structured.get("records", [])
        if len(records) > 5:  # Multiple rows suggest a statement/report
            keys = set()
            for r in records[:3]:
                keys.update(r.keys())
            if "debit" in keys or "credit" in keys or "balance" in keys:
                return {"document_type": "bank_statement", "confidence": 0.80, "method": "structural"}

        return None

    # ── Keyword classifier ────────────────────────────────────────────────────

    def _classify_keywords(self, raw_text: str, structured: dict) -> Optional[dict]:
        """
        Score each document type by keyword frequency in the text.

        Returns the highest-scoring type with normalised confidence.
        """
        combined_text = (raw_text or "").lower()
        # Also include vendor name, notes from structured
        for field in ("vendor_name", "notes", "description"):
            val = structured.get(field, "")
            if val:
                combined_text += " " + str(val).lower()

        scores: dict[str, int] = {}
        for doc_type, keywords in KEYWORD_MAP.items():
            score = sum(
                2 if kw in combined_text else 0
                for kw in keywords
            )
            # Exact phrase bonus
            for kw in keywords:
                if re.search(r"\b" + re.escape(kw) + r"\b", combined_text):
                    score += 1
            scores[doc_type] = score

        if not scores or max(scores.values()) == 0:
            return None

        best_type = max(scores, key=scores.get)
        best_score = scores[best_type]
        ranked_scores = sorted((score for score in scores.values() if score), reverse=True)
        second_score = ranked_scores[1] if len(ranked_scores) > 1 else 0

        # Confidence must represent both *how much* evidence we saw and how
        # clearly it identifies one type.  `best / total` measured only share:
        # one weak receipt keyword became 1.0 while six invoice signals plus
        # three competing signals became 0.667.  Blend absolute support (six
        # keyword points is sufficient saturation) with the winner/runner-up
        # margin so scarcity is never mistaken for certainty.
        absolute_support = min(1.0, best_score / 6)
        discrimination = best_score / max(best_score + second_score, 1)
        confidence = round(0.5 * absolute_support + 0.5 * discrimination, 3)

        return {
            "document_type": best_type,
            "confidence": confidence,
            "method": "keyword",
            "scores": scores,
        }

    # ── AI classifier ─────────────────────────────────────────────────────────

    def _classify_ai(self, raw_text: str) -> Optional[dict]:
        """Delegate to OpenAI extractor for classification.

        **"We don't know" is not "we couldn't look."** That distinction is the
        one apps/audit_platform/status.py exists to keep, and this method was
        losing it: when the API key is rejected, `classify_document` swallows
        the 401 and returns `{"document_type": "other", "confidence": 0.0}` —
        indistinguishable from a model that read the document and had no
        opinion. Measured on this machine: five of five documents, ~1 second of
        billed latency each, and every one reported as an answer.

        So the branch now says which of the two happened. `ai_unavailable`
        marks a call that did not complete; a caller reading it knows the AI
        was never consulted, rather than believing it was consulted and found
        nothing.

        Never raises. A classifier that cannot reach its provider must not stop
        an upload — the document still gets the heuristics and, failing those,
        an honest "undetermined".
        """
        try:
            from core.services.ai.openai_extractor import classify_document
            result = classify_document(raw_text)
        except Exception as exc:
            logger.error(
                "[Classifier] AI classification could not run: %s: %s — "
                "the document was NOT classified by AI, and this is not the "
                "same as the AI finding nothing.",
                type(exc).__name__, exc,
            )
            return {"document_type": "other", "confidence": 0.0,
                    "method": "ai", "ai_unavailable": True,
                    "ai_error": f"{type(exc).__name__}: {exc}"}

        # The call returned, but `classify_document` maps every internal
        # failure — auth, network, unparseable body — onto this same shape, so
        # a returned dict is not proof the model answered. An empty reason with
        # zero confidence is what a swallowed failure looks like.
        if not result or (float(result.get("confidence", 0.0)) == 0.0
                          and not str(result.get("reason", "")).strip()):
            logger.error(
                "[Classifier] AI returned no classification and no reason — "
                "treating as unavailable, not as 'no opinion'. Check the "
                "provider credentials and the log above for the HTTP status."
            )
            return {"document_type": "other", "confidence": 0.0,
                    "method": "ai", "ai_unavailable": True,
                    "ai_error": "empty response"}

        result["method"] = "ai"
        result["ai_unavailable"] = False
        return result
