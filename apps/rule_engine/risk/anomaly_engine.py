"""
Explainable anomaly detection for financial audit documents.

The detector combines deterministic statistical techniques with an optional
machine-learning pass:

- Price anomalies vs historical peer averages (z-score + IQR)
- Duplicate submission patterns (same number / same amount-date-vendor)
- Unusual frequency bursts
- Vendor anomalies (unapproved / flagged / blocked)
- Optional Isolation Forest when `scikit-learn` is available

Output is intentionally explainable and audit-friendly.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import timedelta
from importlib import import_module
from statistics import fmean, pstdev
from typing import Any, Optional

from django.utils import timezone

logger = logging.getLogger("rule_engine.anomaly")


@dataclass
class AnomalyFinding:
    code: str
    severity: str
    contribution: float  # points added to anomaly_score (0–100)
    description: str
    description_ar: str
    evidence: dict[str, Any] = field(default_factory=dict)


@dataclass
class AnomalyAnalysis:
    anomaly_score: float
    normalized_score: float
    explanation: str
    explanation_ar: str
    findings: list[AnomalyFinding] = field(default_factory=list)
    methods_used: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "anomaly_score": round(self.anomaly_score, 2),
            "normalized_score": round(self.normalized_score, 4),
            "explanation": self.explanation,
            "explanation_ar": self.explanation_ar,
            "methods_used": self.methods_used,
            "metadata": self.metadata,
            "findings": [
                {
                    "code": f.code,
                    "severity": f.severity,
                    "contribution": round(f.contribution, 2),
                    "description": f.description,
                    "description_ar": f.description_ar,
                    "evidence": f.evidence,
                }
                for f in self.findings
            ],
        }


class DocumentAnomalyDetector:
    """Context-aware anomaly detection for invoices, POs, payments, and peers."""

    PEER_LOOKBACK_DAYS = 180
    MIN_HISTORY_FOR_STATS = 5
    MIN_HISTORY_FOR_ML = 12
    HIGH_FREQUENCY_THRESHOLD = 50

    MODEL_CONFIG = {
        "sales_invoice": {
            "module": "apps.invoices.models",
            "model": "Invoice",
            "organization_field": "organization_id",
            "party_field": "vendor_name",
            "number_field": "invoice_number",
            "amount_field": "total_amount",
            "date_field": "invoice_date",
            "extra_filters": {"is_deleted": False},
        },
        "purchase_order": {
            "module": "apps.documents.typed_models",
            "model": "PurchaseOrder",
            "organization_field": "organization_id",
            "party_field": "vendor_name",
            "number_field": "po_number",
            "amount_field": "total_amount",
            "date_field": "po_date",
        },
        "payment": {
            "module": "apps.documents.typed_models",
            "model": "PaymentVoucher",
            "organization_field": "organization_id",
            "party_field": "payee_name",
            "number_field": "payment_number",
            "amount_field": "amount",
            "date_field": "payment_date",
        },
        "bank_statement": {
            "module": "apps.documents.typed_models",
            "model": "BankStatement",
            "organization_field": "organization_id",
            "party_field": "bank_name",
            "number_field": "statement_number",
            "amount_field": "closing_balance",
            "date_field": "statement_date",
        },
    }

    def __init__(self, enable_ml: bool = True):
        self.enable_ml = enable_ml

    def analyze(
        self,
        doc,
        vendor_context: Optional[dict] = None,
        history_context: Optional[dict] = None,
    ) -> AnomalyAnalysis:
        vendor_context = vendor_context or {}
        history = dict(history_context or {})
        findings: list[AnomalyFinding] = []
        methods_used: list[str] = []

        if doc is None:
            return AnomalyAnalysis(
                anomaly_score=0.0,
                normalized_score=0.0,
                explanation="No normalized document provided for anomaly analysis.",
                explanation_ar="لا يوجد مستند قانوني مهيأ لتحليل الشذوذ.",
                findings=[],
                methods_used=[],
                metadata={},
            )

        history = self._enrich_history(doc, history)
        current_amount = self._safe_float(getattr(doc, "total_amount", None))
        peer_amounts = self._coerce_amounts(
            history.get("peer_amounts")
            or history.get("historical_amounts")
            or []
        )

        # 1) Price anomalies vs historical average (z-score + IQR)
        if current_amount is not None and len(peer_amounts) >= self.MIN_HISTORY_FOR_STATS:
            methods_used.extend(["z_score", "iqr"])
            findings.extend(self._detect_price_anomalies(current_amount, peer_amounts))

        # 2) Duplicate patterns
        findings.extend(self._detect_duplicate_patterns(doc, history))
        if any(f.code.startswith("duplicate") for f in findings):
            methods_used.append("duplicate_pattern")

        # 3) Unusual frequency
        findings.extend(self._detect_frequency_anomalies(history))
        if any(f.code.startswith("frequency") for f in findings):
            methods_used.append("frequency")

        # 4) Vendor anomalies
        findings.extend(self._detect_vendor_anomalies(vendor_context))
        if any(f.code.startswith("vendor") for f in findings):
            methods_used.append("vendor_profile")

        # 5) Optional ML — Isolation Forest on peer amounts
        ml_finding = self._detect_ml_outlier(current_amount, peer_amounts)
        if ml_finding:
            findings.append(ml_finding)
            methods_used.append("isolation_forest")

        anomaly_score = min(round(sum(f.contribution for f in findings), 2), 100.0)
        normalized_score = round(anomaly_score / 100.0, 4)

        if findings:
            findings_sorted = sorted(findings, key=lambda item: item.contribution, reverse=True)
            top_codes = ", ".join(f.code for f in findings_sorted[:4])
            explanation = (
                f"Anomaly score {anomaly_score:.1f}/100 based on: {top_codes}. "
                f"Top driver: {findings_sorted[0].description}"
            )
            explanation_ar = (
                f"درجة الشذوذ {anomaly_score:.1f}/100 بناءً على: {top_codes}. "
                f"أهم سبب: {findings_sorted[0].description_ar}"
            )
        else:
            explanation = "No statistically significant anomalies detected for this document."
            explanation_ar = "لم يتم رصد شذوذات ذات دلالة إحصائية لهذا المستند."

        return AnomalyAnalysis(
            anomaly_score=anomaly_score,
            normalized_score=normalized_score,
            explanation=explanation,
            explanation_ar=explanation_ar,
            findings=sorted(findings, key=lambda item: item.contribution, reverse=True),
            methods_used=list(dict.fromkeys(methods_used)),
            metadata={
                "peer_sample_size": len(peer_amounts),
                "recent_run_count": history.get("recent_run_count", 0),
                "high_risk_count": history.get("high_risk_count", 0),
                "duplicate_documents": history.get("duplicate_documents", 0),
            },
        )

    def _enrich_history(self, doc, history: dict) -> dict:
        history = dict(history)
        if history.get("peer_amounts") and history.get("duplicate_documents") is not None:
            return history

        config = self.MODEL_CONFIG.get(getattr(doc, "document_type", ""))
        if not config:
            return history

        try:
            model = getattr(import_module(config["module"]), config["model"])
            qs = model.objects.all()

            org_field = config.get("organization_field")
            if org_field:
                qs = qs.filter(**{org_field: getattr(doc, "organization_id", None)})

            for key, value in (config.get("extra_filters") or {}).items():
                qs = qs.filter(**{key: value})

            if getattr(doc, "document_id", None):
                qs = qs.exclude(pk=getattr(doc, "document_id"))

            party_field = config.get("party_field")
            if party_field and getattr(doc, "counterparty_name", None):
                qs = qs.filter(**{f"{party_field}__iexact": doc.counterparty_name})

            amount_field = config.get("amount_field")
            number_field = config.get("number_field")
            date_field = config.get("date_field")
            current_amount = self._safe_float(getattr(doc, "total_amount", None))
            current_number = getattr(doc, "document_number", None)
            current_date = getattr(doc, "document_date", None)

            if not history.get("peer_amounts"):
                history["peer_amounts"] = [
                    self._safe_float(value)
                    for value in qs.order_by("-id").values_list(amount_field, flat=True)[:100]
                    if self._safe_float(value) is not None
                ]

            if history.get("duplicate_documents") is None:
                duplicate_count = 0
                if current_number:
                    duplicate_count += qs.filter(**{number_field: current_number}).count()
                if current_amount is not None and current_date is not None:
                    tolerance = 1.0
                    duplicate_count += qs.filter(
                        **{
                            f"{amount_field}__gte": current_amount - tolerance,
                            f"{amount_field}__lte": current_amount + tolerance,
                            date_field: current_date,
                        }
                    ).count()
                history["duplicate_documents"] = duplicate_count

            if not history.get("recent_run_count") and date_field and current_date:
                lookback_start = current_date - timedelta(days=90)
                history["recent_run_count"] = qs.filter(**{f"{date_field}__gte": lookback_start}).count()

        except Exception as exc:
            logger.debug("[anomaly_engine] History enrichment skipped for %s: %s", getattr(doc, "document_type", "?"), exc)

        history.setdefault("recent_run_count", 0)
        history.setdefault("high_risk_count", 0)
        history.setdefault("lookback_days", 90)
        history.setdefault("duplicate_documents", 0)
        return history

    def _detect_price_anomalies(self, current_amount: float, peer_amounts: list[float]) -> list[AnomalyFinding]:
        findings: list[AnomalyFinding] = []
        if len(peer_amounts) < self.MIN_HISTORY_FOR_STATS:
            return findings

        avg_amount = fmean(peer_amounts)
        std_amount = pstdev(peer_amounts) if len(peer_amounts) > 1 else 0.0

        if std_amount > 0:
            z_score = abs((current_amount - avg_amount) / std_amount)
            if z_score >= 3.0:
                findings.append(AnomalyFinding(
                    code="price_zscore_critical",
                    severity="high",
                    contribution=30.0,
                    description=f"Amount {current_amount:,.2f} is {z_score:.2f} standard deviations away from the historical average {avg_amount:,.2f}.",
                    description_ar=f"المبلغ {current_amount:,.2f} يبتعد بمقدار {z_score:.2f} انحراف معياري عن المتوسط التاريخي {avg_amount:,.2f}.",
                    evidence={"z_score": round(z_score, 3), "historical_avg": round(avg_amount, 2)},
                ))
            elif z_score >= 2.0:
                findings.append(AnomalyFinding(
                    code="price_zscore_warning",
                    severity="medium",
                    contribution=18.0,
                    description=f"Amount {current_amount:,.2f} materially deviates from the historical average {avg_amount:,.2f} (z={z_score:.2f}).",
                    description_ar=f"المبلغ {current_amount:,.2f} ينحرف مادياً عن المتوسط التاريخي {avg_amount:,.2f} (z={z_score:.2f}).",
                    evidence={"z_score": round(z_score, 3), "historical_avg": round(avg_amount, 2)},
                ))

        q1 = self._percentile(peer_amounts, 25)
        q3 = self._percentile(peer_amounts, 75)
        iqr = q3 - q1
        if iqr > 0:
            lower = q1 - 1.5 * iqr
            upper = q3 + 1.5 * iqr
            if current_amount < lower or current_amount > upper:
                findings.append(AnomalyFinding(
                    code="price_iqr_outlier",
                    severity="high",
                    contribution=22.0,
                    description=f"Amount {current_amount:,.2f} falls outside the IQR band [{lower:,.2f}, {upper:,.2f}].",
                    description_ar=f"المبلغ {current_amount:,.2f} يقع خارج نطاق IQR [{lower:,.2f}, {upper:,.2f}].",
                    evidence={"iqr_lower": round(lower, 2), "iqr_upper": round(upper, 2)},
                ))

        return findings

    def _detect_duplicate_patterns(self, doc, history: dict) -> list[AnomalyFinding]:
        findings: list[AnomalyFinding] = []
        duplicate_count = int(history.get("duplicate_documents") or 0)
        is_duplicate = bool(doc.get("is_duplicate", False) or duplicate_count > 0)
        duplicate_of = doc.get("duplicate_of_id") or doc.get("duplicate_of") or ""

        if is_duplicate:
            findings.append(AnomalyFinding(
                code="duplicate_pattern",
                severity="critical",
                contribution=35.0,
                description=(
                    f"Duplicate submission pattern detected"
                    + (f" (matches {duplicate_count} peer record(s))" if duplicate_count else "")
                    + (f"; linked duplicate: {duplicate_of}" if duplicate_of else "")
                ),
                description_ar=(
                    f"تم رصد نمط تقديم مكرر"
                    + (f" (يطابق {duplicate_count} سجل/سجلات)" if duplicate_count else "")
                    + (f"؛ المستند المرتبط: {duplicate_of}" if duplicate_of else "")
                ),
                evidence={"duplicate_documents": duplicate_count, "duplicate_of": duplicate_of},
            ))

        same_amount_count = int(history.get("same_amount_count") or 0)
        if same_amount_count >= 3:
            findings.append(AnomalyFinding(
                code="duplicate_amount_cluster",
                severity="medium",
                contribution=12.0,
                description=f"The same or nearly identical amount has repeated {same_amount_count} times recently.",
                description_ar=f"تم تكرار نفس المبلغ أو مبلغ قريب منه {same_amount_count} مرات مؤخراً.",
                evidence={"same_amount_count": same_amount_count},
            ))

        return findings

    def _detect_frequency_anomalies(self, history: dict) -> list[AnomalyFinding]:
        findings: list[AnomalyFinding] = []
        recent_count = int(history.get("recent_run_count") or 0)
        high_risk_count = int(history.get("high_risk_count") or 0)
        lookback_days = int(history.get("lookback_days") or 90)

        if recent_count >= self.HIGH_FREQUENCY_THRESHOLD:
            contribution = min(10.0 + (recent_count / max(self.HIGH_FREQUENCY_THRESHOLD, 1)) * 8.0, 24.0)
            findings.append(AnomalyFinding(
                code="frequency_spike",
                severity="medium",
                contribution=round(contribution, 2),
                description=f"Submission frequency is unusually high: {recent_count} similar documents in {lookback_days} days.",
                description_ar=f"تكرار التقديم مرتفع بشكل غير معتاد: {recent_count} مستندات مشابهة خلال {lookback_days} يوماً.",
                evidence={"recent_run_count": recent_count, "lookback_days": lookback_days},
            ))

        if recent_count > 0 and high_risk_count / max(recent_count, 1) >= 0.30:
            risk_ratio = high_risk_count / max(recent_count, 1)
            findings.append(AnomalyFinding(
                code="frequency_high_risk_ratio",
                severity="high",
                contribution=min(round(risk_ratio * 20.0, 2), 20.0),
                description=f"Historical peer set has an elevated high-risk ratio ({risk_ratio:.0%}).",
                description_ar=f"مجموعة الأقران التاريخية لديها نسبة مرتفعة من المخاطر العالية ({risk_ratio:.0%}).",
                evidence={"high_risk_ratio": round(risk_ratio, 3)},
            ))

        return findings

    def _detect_vendor_anomalies(self, vendor_context: dict) -> list[AnomalyFinding]:
        findings: list[AnomalyFinding] = []
        if not vendor_context:
            return findings

        vendor_name = vendor_context.get("counterparty_name") or "unknown vendor"
        is_approved = vendor_context.get("is_approved")
        flags = vendor_context.get("flags") or []
        prior_risk = self._safe_float(vendor_context.get("risk_score"))

        if is_approved is False:
            findings.append(AnomalyFinding(
                code="vendor_unapproved",
                severity="high",
                contribution=18.0,
                description=f"Vendor '{vendor_name}' is not approved in the master/vendor controls.",
                description_ar=f"المورد '{vendor_name}' غير معتمد ضمن ضوابط/سجل الموردين.",
                evidence={"vendor": vendor_name},
            ))

        if flags:
            findings.append(AnomalyFinding(
                code="vendor_flags",
                severity="high",
                contribution=min(10.0 + len(flags) * 4.0, 20.0),
                description=f"Vendor '{vendor_name}' carries risk flags: {', '.join(str(flag) for flag in flags)}.",
                description_ar=f"المورد '{vendor_name}' يحمل إشارات مخاطر: {', '.join(str(flag) for flag in flags)}.",
                evidence={"flags": list(flags)},
            ))

        if prior_risk is not None and prior_risk >= 70:
            findings.append(AnomalyFinding(
                code="vendor_prior_risk",
                severity="medium",
                contribution=10.0,
                description=f"Vendor '{vendor_name}' already has a high prior risk profile ({prior_risk:.1f}/100).",
                description_ar=f"المورد '{vendor_name}' لديه ملف مخاطر سابق مرتفع ({prior_risk:.1f}/100).",
                evidence={"prior_risk_score": prior_risk},
            ))

        return findings

    def _detect_ml_outlier(self, current_amount: Optional[float], peer_amounts: list[float]) -> Optional[AnomalyFinding]:
        if not self.enable_ml or current_amount is None or len(peer_amounts) < self.MIN_HISTORY_FOR_ML:
            return None

        try:
            from sklearn.ensemble import IsolationForest
        except Exception:
            return None

        try:
            samples = [[float(value)] for value in peer_amounts]
            model = IsolationForest(contamination=0.10, random_state=42)
            model.fit(samples)
            prediction = model.predict([[float(current_amount)]])[0]
            score = float(model.score_samples([[float(current_amount)]])[0])
            if prediction == -1:
                return AnomalyFinding(
                    code="ml_isolation_forest",
                    severity="high",
                    contribution=16.0,
                    description=f"Isolation Forest classified the amount as an outlier (score={score:.4f}).",
                    description_ar=f"صنّف نموذج Isolation Forest المبلغ كقيمة شاذة (score={score:.4f}).",
                    evidence={"ml_score": round(score, 4), "algorithm": "IsolationForest"},
                )
        except Exception as exc:
            logger.debug("[anomaly_engine] Isolation Forest skipped: %s", exc)

        return None

    @staticmethod
    def _coerce_amounts(values: list[Any]) -> list[float]:
        output: list[float] = []
        for value in values or []:
            try:
                output.append(float(value))
            except (TypeError, ValueError):
                continue
        return output

    @staticmethod
    def _percentile(values: list[float], percentile: float) -> float:
        if not values:
            return 0.0
        ordered = sorted(float(v) for v in values)
        if len(ordered) == 1:
            return ordered[0]
        rank = (len(ordered) - 1) * (percentile / 100.0)
        lower = int(rank)
        upper = min(lower + 1, len(ordered) - 1)
        fraction = rank - lower
        return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction

    @staticmethod
    def _safe_float(value) -> Optional[float]:
        if value in (None, ""):
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None
