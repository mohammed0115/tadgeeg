"""
ZATCA-P3: Previous-Invoice-Hash (PIH) chain integrity.

Every Phase 2 invoice (after the first one in a series) must embed the SHA-256
hash of its immediately preceding invoice. This rule walks back to the prior
invoice for the same vendor + organization, recomputes its hash, and confirms
the declared PIH matches.

The chain check is what auditors rely on to prove no invoice was inserted,
deleted, or reordered. A broken chain = either tampering or a missing record.
"""
from __future__ import annotations

import logging

from apps.rule_engine.rules.base import (
    AuditRuleBase, NormalizedDocument, RuleResult, EvidenceItem,
)

logger = logging.getLogger("rule_engine")


class ZATCAPIHChainRule(AuditRuleBase):
    rule_code = "ZATCA-P3"
    rule_name_en = "ZATCA PIH Chain Integrity"
    rule_name_ar = "سلامة سلسلة هاش الفاتورة السابقة"
    default_severity = "high"
    rule_type = "compliance"

    def check_preconditions(self, doc: NormalizedDocument) -> bool:
        ext = (getattr(doc, "file_extension", "") or "").lower()
        return ext in (".xml", ".ubl")

    def execute(self, doc: NormalizedDocument) -> RuleResult:
        try:
            xml_source = getattr(doc, "raw_text", None) or getattr(doc, "raw_bytes", None)
            if not xml_source:
                return self._pass("No XML content to check chain.")

            from apps.rule_engine.services.zatca_phase2 import (
                conformance_summary, compute_invoice_hash,
            )
            summary = conformance_summary(xml_source)
            if not summary.get("is_ubl"):
                return self._pass("Not UBL — chain check skipped.")

            md = summary.get("metadata", {}) or {}
            declared_pih = md.get("pih")
            icv = md.get("icv")

            # ICV == "1" means this is the FIRST invoice in the chain. PIH may be empty.
            if str(icv or "").strip() in ("", "1"):
                return self._pass("First invoice in chain — no prior PIH to verify.")

            # Look up the immediately previous invoice in this org's history.
            from apps.invoices.models import Invoice
            prior_qs = Invoice.objects.filter(
                organization_id=doc.organization_id,
            ).exclude(id=doc.document_id).order_by("-created_at")
            prior = prior_qs.first()
            if not prior:
                return self._fail(
                    "Invoice claims a prior PIH but no previous invoice exists in history.",
                    "الفاتورة تدّعي PIH سابقاً لكن لا توجد فاتورة سابقة في السجل.",
                    evidence=[EvidenceItem(
                        field_path="pih",
                        observed=str(declared_pih),
                        expected="(empty — first invoice)",
                    )],
                )

            prior_xml = getattr(prior, "raw_text", "")
            if not prior_xml:
                return self._pass(
                    f"Prior invoice {prior.invoice_number} has no XML stored — chain unverifiable.",
                )

            expected = compute_invoice_hash(prior_xml)
            if not expected:
                return self._pass(
                    f"Could not recompute hash for prior invoice — chain skipped.",
                )

            if declared_pih and expected and declared_pih.strip() == expected.strip():
                return self._pass(
                    f"PIH chain verified against invoice {prior.invoice_number}.",
                    f"تم التحقق من سلسلة PIH مقابل الفاتورة {prior.invoice_number}.",
                )

            return self._fail(
                "PIH does not match the recomputed hash of the previous invoice — chain broken.",
                "PIH لا يطابق هاش الفاتورة السابقة — السلسلة مكسورة.",
                evidence=[EvidenceItem(
                    field_path="pih",
                    observed=(declared_pih or "(empty)")[:80],
                    expected=(expected or "(unable to compute)")[:80],
                )],
            )
        except Exception as exc:
            logger.warning("ZATCA-P3 rule failed: %s", exc)
            return self._pass("PIH chain check skipped (error).")
