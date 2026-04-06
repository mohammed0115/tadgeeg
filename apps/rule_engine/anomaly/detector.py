"""
AnomalyDetector — Statistical anomaly detection for financial documents.

Detects four categories of anomaly:
  1. Price anomalies     Z-score and IQR against the organisation's historical amounts
                         for the same document type. Optional Isolation Forest when
                         scikit-learn is installed.
  2. Duplicate patterns  Exact file-hash match, same vendor+amount+date fingerprint,
                         and repeated document number.
  3. Unusual frequency   Submission-rate spike for the same org/type within a rolling
                         window (sourced from history_context).
  4. Vendor anomalies    Unapproved, unknown, or flagged counterparties.

Public API
----------
    from apps.rule_engine.anomaly.detector import AnomalyDetector, AnomalyResult

    result = AnomalyDetector().detect(
        doc=normalized_doc,
        historical_amounts=[1200.0, 980.0, 1100.0, ...],   # same org+type, recent
        history_context=context.history_context,
        vendor_context=context.vendor_context,
    )
    print(result.anomaly_score)      # 0–100
    print(result.explanation)        # English prose
    print(result.findings)           # list[dict] with code/severity/detail
    print(result.methods_used)       # ["z_score", "iqr", ...]

Integration points
------------------
  • RiskEngineStage  — calls detect() and merges into risk_data / score_breakdown.
  • ReportService    — reads anomaly_score / anomaly_explanation from
                       RiskScoreSummary.score_breakdown (written by the pipeline).
  • DocumentAnalysisResultSerializer — reads from DocumentAnalysisResult.analysis_data.
"""
from __future__ import annotations

import logging
import statistics
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Optional

logger = logging.getLogger("rule_engine.anomaly")

if TYPE_CHECKING:
    from apps.rule_engine.rules.base import NormalizedDocument

# ── Severity thresholds ────────────────────────────────────────────────────────
_ZSCORE_LOW      = 1.5   # |z| ≥ 1.5 → low
_ZSCORE_MEDIUM   = 2.0   # |z| ≥ 2.0 → medium
_ZSCORE_HIGH     = 3.0   # |z| ≥ 3.0 → high
_ZSCORE_CRITICAL = 4.0   # |z| ≥ 4.0 → critical

_IQR_OUTER = 3.0         # outside 3 × IQR fence → stronger signal

# Score contributions per signal (additive, final capped at 100)
_CONTRIB = {
    "zscore_low":          8,
    "zscore_medium":      18,
    "zscore_high":        35,
    "zscore_critical":    55,
    "iqr_outlier":        15,
    "iqr_extreme":        28,
    "isolation_forest":   20,
    "duplicate_hash":     50,
    "duplicate_fingerprint": 35,
    "duplicate_docnum":   25,
    "frequency_spike":    15,
    "vendor_unapproved":  10,
    "vendor_unknown":      5,
    "vendor_flag":         5,   # per flag, capped at 20
}

_SEVERITY_ORDER = {"critical": 4, "high": 3, "medium": 2, "low": 1, "info": 0}

MIN_SAMPLE_SIZE = 5      # fewer samples → skip statistical methods


# ── Result dataclass ───────────────────────────────────────────────────────────

@dataclass
class AnomalyResult:
    """
    Output of a single AnomalyDetector.detect() call.

    anomaly_score   Composite score 0–100. Higher = more anomalous.
    explanation     Human-readable English summary of what was flagged.
    explanation_ar  Arabic summary (mirrors English when not translated).
    findings        Ordered list of individual signals, each a dict with keys:
                      code      identifier, e.g. "price_zscore_critical"
                      severity  "critical" | "high" | "medium" | "low" | "info"
                      detail    one-sentence description with values
    methods_used    Techniques that produced at least one finding.
    """
    anomaly_score:  float = 0.0
    explanation:    str   = ""
    explanation_ar: str   = ""
    findings:       list  = field(default_factory=list)
    methods_used:   list  = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "anomaly_score":       round(self.anomaly_score, 2),
            "anomaly_explanation": self.explanation,
            "anomaly_explanation_ar": self.explanation_ar,
            "anomaly_findings":    self.findings,
            "anomaly_methods":     self.methods_used,
        }


# ── Main detector ──────────────────────────────────────────────────────────────

class AnomalyDetector:
    """
    Stateless anomaly detector for financial documents.

    Usage
    -----
        detector = AnomalyDetector()
        result   = detector.detect(doc, historical_amounts, history_context, vendor_context)
        # or fetch historical amounts automatically from the DB:
        result   = detector.detect_with_db_history(doc, history_context, vendor_context)
    """

    # ── Public entry points ────────────────────────────────────────────────────

    def detect(
        self,
        doc: "NormalizedDocument",
        historical_amounts: list[float],
        history_context: Optional[dict] = None,
        vendor_context:  Optional[dict] = None,
    ) -> AnomalyResult:
        """
        Run all enabled detectors and return a consolidated AnomalyResult.

        Parameters
        ----------
        doc                 NormalizedDocument being audited.
        historical_amounts  Peer amounts for the same org + document type.
                            Pass an empty list when history is unavailable.
        history_context     Dict from ContextBuilderStage (recent_run_count, etc.)
        vendor_context      Dict from ContextBuilderStage (is_approved, flags, etc.)
        """
        history_context = history_context or {}
        vendor_context  = vendor_context  or {}

        findings:     list[dict] = []
        methods_used: set[str]   = set()

        amount = float(doc.total_amount or 0)

        # 1. Price anomalies
        price_findings, price_methods = self._detect_price_anomalies(
            amount, historical_amounts
        )
        findings.extend(price_findings)
        methods_used.update(price_methods)

        # 2. Duplicate patterns
        dup_findings, dup_methods = self._detect_duplicate_patterns(doc, history_context)
        findings.extend(dup_findings)
        methods_used.update(dup_methods)

        # 3. Frequency spike
        freq_findings, freq_methods = self._detect_frequency_anomaly(history_context)
        findings.extend(freq_findings)
        methods_used.update(freq_methods)

        # 4. Vendor anomalies
        vendor_findings, vendor_methods = self._detect_vendor_anomalies(vendor_context)
        findings.extend(vendor_findings)
        methods_used.update(vendor_methods)

        # Sort by severity descending
        findings.sort(key=lambda f: _SEVERITY_ORDER.get(f["severity"], 0), reverse=True)

        # Compute composite score
        raw_score = sum(
            _CONTRIB.get(f["code"].replace("price_", ""), _CONTRIB.get(f["code"], 0))
            for f in findings
        )
        anomaly_score = min(float(raw_score), 100.0)

        explanation    = self._build_explanation(findings, anomaly_score, amount)
        explanation_ar = self._build_explanation_ar(findings, anomaly_score)

        return AnomalyResult(
            anomaly_score  = anomaly_score,
            explanation    = explanation,
            explanation_ar = explanation_ar,
            findings       = findings,
            methods_used   = sorted(methods_used),
        )

    def detect_with_db_history(
        self,
        doc: "NormalizedDocument",
        history_context: Optional[dict] = None,
        vendor_context:  Optional[dict] = None,
        lookback_days:   int = 180,
    ) -> AnomalyResult:
        """
        Convenience wrapper that fetches historical amounts from the DB
        before calling detect().  Fails gracefully if the DB is unavailable.
        """
        historical_amounts = self._fetch_historical_amounts(doc, lookback_days)
        return self.detect(doc, historical_amounts, history_context, vendor_context)

    # ── Method 1: Price anomalies (z-score + IQR + optional Isolation Forest) ─

    def _detect_price_anomalies(
        self,
        amount: float,
        historical_amounts: list[float],
    ) -> tuple[list[dict], set[str]]:
        findings: list[dict] = []
        methods:  set[str]   = set()

        if amount <= 0 or len(historical_amounts) < MIN_SAMPLE_SIZE:
            return findings, methods

        # Z-score
        z_finding = self._zscore_finding(amount, historical_amounts)
        if z_finding:
            findings.append(z_finding)
            methods.add("z_score")

        # IQR
        iqr_finding = self._iqr_finding(amount, historical_amounts)
        if iqr_finding:
            findings.append(iqr_finding)
            methods.add("iqr")

        # Isolation Forest (optional — requires scikit-learn)
        if_finding = self._isolation_forest_finding(amount, historical_amounts)
        if if_finding:
            findings.append(if_finding)
            methods.add("isolation_forest")

        return findings, methods

    def _zscore_finding(self, amount: float, amounts: list[float]) -> Optional[dict]:
        try:
            mean = statistics.mean(amounts)
            std  = statistics.stdev(amounts)
        except Exception:
            return None

        if std == 0:
            return None

        z = abs((amount - mean) / std)

        if z >= _ZSCORE_CRITICAL:
            code, severity = "price_zscore_critical", "critical"
            detail = (
                f"Amount {amount:,.2f} is {z:.1f} standard deviations from the "
                f"historical mean {mean:,.2f} — extreme outlier."
            )
        elif z >= _ZSCORE_HIGH:
            code, severity = "price_zscore_high", "high"
            detail = (
                f"Amount {amount:,.2f} is {z:.1f} standard deviations from the "
                f"historical mean {mean:,.2f} — significant price spike."
            )
        elif z >= _ZSCORE_MEDIUM:
            code, severity = "price_zscore_medium", "medium"
            detail = (
                f"Amount {amount:,.2f} deviates {z:.1f}σ from the "
                f"historical mean {mean:,.2f}."
            )
        elif z >= _ZSCORE_LOW:
            code, severity = "price_zscore_low", "low"
            detail = (
                f"Amount {amount:,.2f} shows a mild z-score of {z:.1f} "
                f"(mean {mean:,.2f})."
            )
        else:
            return None

        return {"code": code, "severity": severity, "detail": detail, "z_score": round(z, 3)}

    def _iqr_finding(self, amount: float, amounts: list[float]) -> Optional[dict]:
        try:
            sorted_a = sorted(amounts)
            n  = len(sorted_a)
            q1 = sorted_a[n // 4]
            q3 = sorted_a[3 * n // 4]
            iqr = q3 - q1
        except Exception:
            return None

        if iqr == 0:
            return None

        lower_outer = q1 - _IQR_OUTER * iqr
        upper_outer = q3 + _IQR_OUTER * iqr
        lower_inner = q1 - 1.5 * iqr
        upper_inner = q3 + 1.5 * iqr

        is_extreme = amount < lower_outer or amount > upper_outer
        is_outlier = amount < lower_inner or amount > upper_inner

        if is_extreme:
            return {
                "code":     "iqr_extreme",
                "severity": "high",
                "detail": (
                    f"Amount {amount:,.2f} lies outside the extreme IQR fence "
                    f"[{lower_outer:,.2f}, {upper_outer:,.2f}] (3×IQR)."
                ),
                "iqr": round(iqr, 2),
            }
        if is_outlier:
            return {
                "code":     "iqr_outlier",
                "severity": "medium",
                "detail": (
                    f"Amount {amount:,.2f} lies outside the standard IQR fence "
                    f"[{lower_inner:,.2f}, {upper_inner:,.2f}] (1.5×IQR)."
                ),
                "iqr": round(iqr, 2),
            }
        return None

    def _isolation_forest_finding(
        self, amount: float, amounts: list[float]
    ) -> Optional[dict]:
        """
        Optional Isolation Forest check.  Silently skipped if scikit-learn
        is not installed (the rest of the pipeline is unaffected).
        """
        if len(amounts) < 20:
            return None
        try:
            from sklearn.ensemble import IsolationForest  # type: ignore[import]
            import numpy as np  # type: ignore[import]

            X = np.array(amounts + [amount]).reshape(-1, 1)
            clf = IsolationForest(contamination=0.05, random_state=42)
            preds = clf.fit_predict(X)
            # -1 means anomaly; last element is the current document
            if preds[-1] == -1:
                return {
                    "code":     "isolation_forest",
                    "severity": "medium",
                    "detail": (
                        f"Isolation Forest flags amount {amount:,.2f} as an outlier "
                        f"within the peer distribution (n={len(amounts)})."
                    ),
                }
        except ImportError:
            logger.debug("[anomaly] scikit-learn not installed — Isolation Forest skipped.")
        except Exception as exc:
            logger.debug("[anomaly] Isolation Forest failed: %s", exc)
        return None

    # ── Method 2: Duplicate patterns ──────────────────────────────────────────

    def _detect_duplicate_patterns(
        self,
        doc: "NormalizedDocument",
        history_context: dict,
    ) -> tuple[list[dict], set[str]]:
        findings: list[dict] = []
        methods:  set[str]   = set()

        typed = doc.typed_data or {}

        # Signal A: duplicate file hash (exact binary copy)
        if typed.get("duplicate_file_hash") or typed.get("is_duplicate"):
            findings.append({
                "code":     "duplicate_hash",
                "severity": "critical",
                "detail":   "File hash matches a previously submitted document — exact duplicate.",
            })
            methods.add("duplicate_pattern")

        # Signal B: same vendor + amount + date fingerprint
        if typed.get("duplicate_invoice_number") or typed.get("duplicate_claims"):
            findings.append({
                "code":     "duplicate_fingerprint",
                "severity": "high",
                "detail":   "Vendor + amount + date combination was seen in a prior submission.",
            })
            methods.add("duplicate_pattern")

        # Signal C: same document number reused
        dup_doc_num = typed.get("duplicate_document_number") or typed.get("duplicate_doc_num")
        if dup_doc_num:
            findings.append({
                "code":     "duplicate_docnum",
                "severity": "high",
                "detail":   f"Document number '{doc.document_number}' appears in a prior record.",
            })
            methods.add("duplicate_pattern")

        return findings, methods

    # ── Method 3: Unusual frequency ───────────────────────────────────────────

    def _detect_frequency_anomaly(
        self,
        history_context: dict,
    ) -> tuple[list[dict], set[str]]:
        findings: list[dict] = []
        methods:  set[str]   = set()

        recent_count  = history_context.get("recent_run_count", 0)
        lookback_days = history_context.get("lookback_days", 90)
        high_risk_cnt = history_context.get("high_risk_count", 0)

        # Frequency spike: > 50 docs of same type in lookback window
        if recent_count >= 50:
            findings.append({
                "code":     "frequency_spike",
                "severity": "medium",
                "detail": (
                    f"Unusual submission rate: {recent_count} documents of this type "
                    f"were processed in the past {lookback_days} days."
                ),
            })
            methods.add("frequency_analysis")

        # Elevated risk history: > 30 % of recent docs were high/critical risk
        if recent_count >= 10 and high_risk_cnt > 0:
            ratio = high_risk_cnt / recent_count
            if ratio > 0.30:
                findings.append({
                    "code":     "elevated_risk_history",
                    "severity": "low",
                    "detail": (
                        f"{high_risk_cnt} of {recent_count} recent documents "
                        f"({ratio:.0%}) were flagged as high or critical risk."
                    ),
                })
                methods.add("frequency_analysis")

        return findings, methods

    # ── Method 4: Vendor anomalies ────────────────────────────────────────────

    def _detect_vendor_anomalies(
        self,
        vendor_context: dict,
    ) -> tuple[list[dict], set[str]]:
        findings: list[dict] = []
        methods:  set[str]   = set()

        if not vendor_context:
            return findings, methods

        is_approved  = vendor_context.get("is_approved")
        flags        = vendor_context.get("flags", []) or []
        vendor_name  = vendor_context.get("counterparty_name", "Unknown vendor")

        if is_approved is False:
            findings.append({
                "code":     "vendor_unapproved",
                "severity": "high",
                "detail":   f"Vendor '{vendor_name}' is not on the approved vendor list.",
            })
            methods.add("vendor_analysis")
        elif is_approved is None:
            findings.append({
                "code":     "vendor_unknown",
                "severity": "low",
                "detail":   f"Vendor '{vendor_name}' is not registered in the vendor master.",
            })
            methods.add("vendor_analysis")

        flag_findings = 0
        for flag in flags[:4]:  # cap at 4 flags to limit score inflation
            if flag_findings >= 4:
                break
            findings.append({
                "code":     "vendor_flag",
                "severity": "medium",
                "detail":   f"Vendor '{vendor_name}' carries risk flag: {flag}.",
                "flag":     flag,
            })
            methods.add("vendor_analysis")
            flag_findings += 1

        return findings, methods

    # ── DB history helper ──────────────────────────────────────────────────────

    def _fetch_historical_amounts(
        self,
        doc: "NormalizedDocument",
        lookback_days: int,
    ) -> list[float]:
        """
        Fetch historical total_amount values from DocumentAnalysisResult for
        the same organisation and AI-detected document type.

        Returns an empty list on any failure so the price checks are simply
        skipped rather than crashing the pipeline.
        """
        try:
            from datetime import timedelta

            from django.utils import timezone

            from apps.documents.models import DocumentAnalysisResult

            cutoff = timezone.now() - timedelta(days=lookback_days)
            # Map rule_engine document_type → AI document type string
            doc_type = str(doc.document_type or "").lower()
            qs = (
                DocumentAnalysisResult.objects
                .filter(
                    document__organization_id=doc.organization_id,
                    ai_document_type__icontains=doc_type.replace("_", " "),
                    created_at__gte=cutoff,
                    total_amount__isnull=False,
                )
                .exclude(document_id=doc.document_id)
                .values_list("total_amount", flat=True)
                .order_by("-created_at")[:500]
            )
            return [float(a) for a in qs if a is not None]
        except Exception as exc:
            logger.debug("[anomaly] _fetch_historical_amounts failed: %s", exc)
            return []

    # ── Explanation builders ───────────────────────────────────────────────────

    @staticmethod
    def _build_explanation(findings: list[dict], score: float, amount: float) -> str:
        if not findings:
            return (
                f"No anomalies detected. Amount {amount:,.2f} is within expected "
                "historical range."
            )

        critical = [f for f in findings if f["severity"] == "critical"]
        high     = [f for f in findings if f["severity"] == "high"]

        parts: list[str] = []

        if critical:
            parts.append(critical[0]["detail"])
        elif high:
            parts.append(high[0]["detail"])

        if len(findings) > 1:
            extras = findings[1:3]
            for extra in extras:
                parts.append(extra["detail"])

        summary = " ".join(parts)

        if score >= 70:
            prefix = "High-risk anomaly detected. "
        elif score >= 40:
            prefix = "Anomaly indicators present. "
        else:
            prefix = "Mild anomaly signal. "

        return prefix + summary

    @staticmethod
    def _build_explanation_ar(findings: list[dict], score: float) -> str:
        if not findings:
            return "لم يتم اكتشاف شذوذات. المبلغ ضمن النطاق المتوقع."

        if score >= 70:
            return "تم اكتشاف شذوذ عالي الخطورة. يُنصح بمراجعة يدوية فورية."
        if score >= 40:
            return "توجد مؤشرات شذوذ تستوجب الفحص الدقيق."
        return "إشارة شذوذ خفيفة — يُنصح بالمتابعة."
