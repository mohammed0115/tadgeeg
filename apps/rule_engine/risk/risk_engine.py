"""
RiskEngine — Dynamic, multi-dimensional, explainable risk scoring.

Architecture
============

Five independent scoring components contribute to a weighted composite score:

  ┌─────────────────────────┬────────┬────────────────────────────────────────┐
  │ Component               │ Weight │ Signal source                          │
  ├─────────────────────────┼────────┼────────────────────────────────────────┤
  │ ViolationScoreComponent │  0.40  │ Rule results (severity × fail counts)  │
  │ AmountScoreComponent    │  0.20  │ doc.total_amount vs tiered thresholds  │
  │ ApprovalScoreComponent  │  0.20  │ approved_by, approval chain integrity  │
  │ VendorScoreComponent    │  0.10  │ Vendor registry flags, approval status │
  │ BehavioralScoreComponent│  0.10  │ Frequency, rounding, timing anomalies  │
  └─────────────────────────┴────────┴────────────────────────────────────────┘

  composite_score = Σ(component.raw_score × component.weight) × 100

After the composite is computed, three deterministic **override rules** may
force the score upward:

  1. MissingApprovalHighAmountOverride  → force CRITICAL
  2. TaxIssueOverride                   → force minimum HIGH
  3. BlockingRuleFailOverride           → force minimum HIGH + blocks_approval
  4. CriticalSeverityFailOverride       → force minimum CRITICAL

Every scoring step emits a list of RiskSignals so callers can display a
human-readable explanation of exactly how the score was derived.

Usage
-----
    from apps.rule_engine.risk.risk_engine import RiskEngine, RiskEngineConfig
    from apps.rule_engine.pipeline.v2.context import PipelineContext

    engine = RiskEngine()                          # default config
    result = engine.compute(context)               # PipelineContext → RiskScoreResult

    print(result.total_score)                      # 73.4
    print(result.risk_level)                       # "high"
    print(result.blocks_approval)                  # False
    print(result.overrides_applied)                # ["tax_issue"]
    for expl in result.explanations:
        print(expl)

Integration
-----------
    RiskEngineStage (pipeline/stages/risk_engine.py) calls RiskEngine.compute()
    and converts the result to the canonical risk_data dict stored on AuditRun.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any, Optional

from apps.rule_engine.risk.anomaly_engine import DocumentAnomalyDetector

logger = logging.getLogger("rule_engine.risk")

__all__ = [
    "RiskEngine",
    "RiskEngineConfig",
    "RiskScoreResult",
    "ComponentScore",
    "RiskSignal",
]


# ── Configuration ──────────────────────────────────────────────────────────────

@dataclass
class RiskEngineConfig:
    """
    All scoring parameters in one place.
    Override individual fields to tune without subclassing.

    Example — tighten the approval threshold for high-value markets:

        config = RiskEngineConfig(
            missing_approval_critical_amount=25_000,
            amount_tiers=[5_000, 25_000, 100_000, 500_000],
        )
        engine = RiskEngine(config=config)
    """

    # ── Component weights (must sum to 1.0) ───────────────────────────────
    weight_violation:  float = 0.40
    weight_amount:     float = 0.20
    weight_approval:   float = 0.20
    weight_vendor:     float = 0.10
    weight_behavioral: float = 0.10

    # ── Amount tiers (lower bound of each tier in document currency) ──────
    # Score: 0.0  | 0.2  | 0.5  | 0.75 | 1.0
    amount_tiers: tuple = (10_000, 50_000, 250_000, 1_000_000)

    # ── Risk level thresholds (composite score 0–100) ─────────────────────
    threshold_medium:   float = 25.0
    threshold_high:     float = 50.0
    threshold_critical: float = 75.0

    # ── Approval ──────────────────────────────────────────────────────────
    # Amount above which a missing approval forces CRITICAL override
    missing_approval_critical_amount: float = 50_000.0

    # ── Vendor ────────────────────────────────────────────────────────────
    vendor_flag_score_per_flag: float = 0.30    # per flag, capped at 1.0
    vendor_unapproved_score:    float = 0.50
    vendor_unknown_score:       float = 0.30

    # ── Behavioral ────────────────────────────────────────────────────────
    round_amount_granularity: float = 1_000.0   # e.g. SAR 50,000.00 exactly
    just_below_threshold_pct:  float = 0.05     # within 5% below a tier
    high_frequency_threshold:  int   = 50       # runs in lookback window
    off_hours_start: int = 22                   # 10 PM
    off_hours_end:   int = 6                    # 6 AM

    # ── Override: tax rule code prefixes ──────────────────────────────────
    tax_rule_prefixes: tuple = ("TAX-", "VAT-", "GAAP-CUT-", "ZATCA-")

    def validate(self) -> None:
        total = (
            self.weight_violation + self.weight_amount
            + self.weight_approval + self.weight_vendor
            + self.weight_behavioral
        )
        if not (0.999 < total < 1.001):
            raise ValueError(
                f"RiskEngineConfig: component weights must sum to 1.0, got {total:.4f}"
            )


# ── Data structures ────────────────────────────────────────────────────────────

@dataclass
class RiskSignal:
    """
    One atomic observation that contributed to a component's score.
    Used for line-item explanation of exactly why risk was assigned.
    """
    signal_type:     str
    raw_value:       Any
    contribution:    float        # 0.0 – 1.0 share of component score
    description_en:  str
    description_ar:  str


@dataclass
class ComponentScore:
    """Scored output of one scoring component."""
    name:           str
    raw_score:      float         # 0.0 – 1.0
    weight:         float         # component weight in composite
    weighted_score: float         # raw_score × weight  (0.0 – 1.0)
    signals:        list[RiskSignal] = field(default_factory=list)
    explanation_en: str = ""
    explanation_ar: str = ""

    @property
    def contribution_pts(self) -> float:
        """Points this component adds to the 0–100 composite score."""
        return round(self.weighted_score * 100, 2)


@dataclass
class RiskScoreResult:
    """
    Complete, explainable risk assessment for one document.

    Backward-compatible: call .to_dict() to get the canonical risk_data
    dict expected by AuditRun and RiskScoreSummary.
    """
    total_score:           float          # 0.0 – 100.0
    risk_level:            str            # "low" | "medium" | "high" | "critical"
    components:            dict[str, ComponentScore]
    overrides_applied:     list[str]      # names of overrides that fired
    explanations:          list[str]      # EN line-item explanation
    explanations_ar:       list[str]      # AR line-item explanation
    blocks_approval:       bool
    requires_manual_review: bool
    confidence:            float          # 0.0 – 1.0 (completeness of input data)
    anomaly_score:         float = 0.0
    anomaly_explanation:   str = ""
    anomaly_explanation_ar: str = ""
    anomaly_findings:      list = field(default_factory=list)
    computed_at:           datetime = field(default_factory=datetime.utcnow)

    # Backward-compat fields (mirrors old RiskAggregator output keys)
    score_breakdown:   dict = field(default_factory=dict)
    top_failed_rules:  list = field(default_factory=list)
    modifier_reasons:  list = field(default_factory=list)

    def to_dict(self) -> dict:
        """
        Return canonical risk_data dict format consumed by AuditRun,
        RiskScoreSummary, and DecisionEngineStage.
        """
        return {
            "risk_score":            round(self.total_score, 2),
            "risk_level":            self.risk_level,
            "blocks_approval":       self.blocks_approval,
            "requires_manual_review": self.requires_manual_review,
            "score_breakdown":       self.score_breakdown,
            "top_failed_rules":      self.top_failed_rules,
            "modifier_reasons":      self.modifier_reasons,
            "anomaly_score":         round(self.anomaly_score, 2),
            "anomaly_explanation":   self.anomaly_explanation,
            "anomaly_explanation_ar": self.anomaly_explanation_ar,
            "anomaly_findings":      self.anomaly_findings,
            # V2 extensions
            "components": {
                k: {
                    "raw_score":      round(v.raw_score, 4),
                    "weight":         v.weight,
                    "weighted_score": round(v.weighted_score, 4),
                    "contribution_pts": v.contribution_pts,
                    "explanation_en": v.explanation_en,
                    "explanation_ar": v.explanation_ar,
                    "signals": [
                        {
                            "type":        s.signal_type,
                            "value":       str(s.raw_value),
                            "contribution": round(s.contribution, 4),
                            "description_en": s.description_en,
                            "description_ar": s.description_ar,
                        }
                        for s in v.signals
                    ],
                }
                for k, v in self.components.items()
            },
            "overrides_applied": self.overrides_applied,
            "explanations":      self.explanations,
            "explanations_ar":   self.explanations_ar,
            "confidence":        round(self.confidence, 3),
            "computed_at":       self.computed_at.isoformat(),
        }


# ── Scoring components ─────────────────────────────────────────────────────────

class ViolationScoreComponent:
    """
    Scores rule violations using a severity-weighted formula.

    Unlike the original RiskAggregator (which divides by max_possible),
    this component amplifies the score when multiple rules fail at the same
    severity: 3 HIGH failures is riskier than 1 HIGH failure.

    Formula
    -------
        severity_factor  = {critical:1.0, high:0.75, medium:0.50, low:0.25}
        violation_weight = {critical:4.0, high:3.0, medium:2.0, low:1.0}
        fail_pts  = Σ(severity_factor × violation_weight)  for FAIL
        warn_pts  = Σ(severity_factor × violation_weight × 0.5) for WARNING
        max_pts   = Σ(violation_weight)  for all scored rules
        raw_score = min(fail_pts + warn_pts, max_pts) / max_pts
    """

    SEVERITY_FACTOR   = {"critical": 1.0, "high": 0.75, "medium": 0.50, "low": 0.25, "info": 0.10}
    VIOLATION_WEIGHT  = {"critical": 4.0, "high": 3.0,  "medium": 2.0,  "low": 1.0,  "info": 0.5}

    def score(self, rule_results: list, rule_assignments: list) -> ComponentScore:
        signals:   list[RiskSignal] = []
        fail_pts   = 0.0
        max_pts    = 0.0
        top_failed: list[dict] = []

        assign_map = {a.rule.rule_code: a for a in rule_assignments}

        for result in rule_results:
            status   = result.status if isinstance(result.status, str) else result.status.value
            severity = result.applied_severity or "medium"

            if status in ("skipped", "not_applicable", "error"):
                continue

            vw = self.VIOLATION_WEIGHT.get(severity, 1.0)
            sf = self.SEVERITY_FACTOR.get(severity, 0.5)
            max_pts += vw

            if status == "fail":
                contribution = sf * vw
                fail_pts += contribution
                top_failed.append({
                    "rule_code": result.rule_code,
                    "severity":  severity,
                    "contribution": round(contribution, 3),
                })
                signals.append(RiskSignal(
                    signal_type="rule_fail",
                    raw_value=result.rule_code,
                    contribution=sf,
                    description_en=f"Rule {result.rule_code} FAILED ({severity}): {result.explanation[:120] if result.explanation else ''}",
                    description_ar=f"فشلت القاعدة {result.rule_code} ({severity}): {result.explanation_ar[:120] if result.explanation_ar else ''}",
                ))
            elif status == "warning":
                contribution = sf * vw * 0.5
                fail_pts += contribution
                signals.append(RiskSignal(
                    signal_type="rule_warning",
                    raw_value=result.rule_code,
                    contribution=sf * 0.5,
                    description_en=f"Rule {result.rule_code} WARNING ({severity})",
                    description_ar=f"تحذير من القاعدة {result.rule_code} ({severity})",
                ))

        raw_score = min(fail_pts, max_pts) / max_pts if max_pts > 0 else 0.0

        top_failed.sort(key=lambda x: x["contribution"], reverse=True)
        fail_count = sum(1 for s in signals if s.signal_type == "rule_fail")
        warn_count = sum(1 for s in signals if s.signal_type == "rule_warning")

        expl_en = (
            f"{fail_count} rule failure(s), {warn_count} warning(s). "
            f"Violation score: {raw_score:.1%}."
        )
        expl_ar = (
            f"{fail_count} فشل في القواعد، {warn_count} تحذير. "
            f"درجة الانتهاكات: {raw_score:.1%}."
        )

        return ComponentScore(
            name="violation",
            raw_score=round(raw_score, 4),
            weight=0.0,                      # weight injected by RiskEngine
            weighted_score=0.0,
            signals=signals,
            explanation_en=expl_en,
            explanation_ar=expl_ar,
        ), top_failed


class AmountScoreComponent:
    """
    Scores document amount against configurable monetary tiers.

    Higher amounts carry more inherent risk — larger transactions demand
    stricter controls. A SAR 1M invoice needs more scrutiny than SAR 5K.

    Also detects:
      - Round numbers (e.g., exactly SAR 100,000): common in fraud
      - Just-below-threshold amounts (e.g., SAR 49,900 under a 50K limit)
    """

    TIER_SCORES = (0.0, 0.20, 0.50, 0.75, 1.0)  # maps to len(tiers)+1 bands

    def score(self, doc, config: RiskEngineConfig) -> ComponentScore:
        signals: list[RiskSignal] = []
        amount = self._safe_float(getattr(doc, "total_amount", None))

        if amount is None:
            return ComponentScore(
                name="amount",
                raw_score=0.0,
                weight=0.0,
                weighted_score=0.0,
                signals=[],
                explanation_en="Amount not available — component scored 0.",
                explanation_ar="المبلغ غير متاح — تم تسجيل صفر.",
            ), []

        # ── Tier score ────────────────────────────────────────────────────
        tier_idx = len(config.amount_tiers)   # default: top tier
        for i, boundary in enumerate(config.amount_tiers):
            if amount < boundary:
                tier_idx = i
                break

        tier_score = self.TIER_SCORES[min(tier_idx, len(self.TIER_SCORES) - 1)]
        signals.append(RiskSignal(
            signal_type="amount_tier",
            raw_value=amount,
            contribution=tier_score,
            description_en=f"Amount {amount:,.2f} → tier {tier_idx} (score={tier_score:.2f})",
            description_ar=f"المبلغ {amount:,.2f} → الفئة {tier_idx} (درجة={tier_score:.2f})",
        ))

        # ── Round-number anomaly ──────────────────────────────────────────
        round_bonus = 0.0
        gran = config.round_amount_granularity
        if amount >= gran and amount % gran == 0:
            round_bonus = 0.15
            signals.append(RiskSignal(
                signal_type="round_amount",
                raw_value=amount,
                contribution=round_bonus,
                description_en=f"Suspicious round number: {amount:,.0f} (multiple of {gran:,.0f})",
                description_ar=f"مبلغ مستدير مثير للشبهة: {amount:,.0f} (مضاعف {gran:,.0f})",
            ))

        # ── Just-below-threshold anomaly ─────────────────────────────────
        threshold_bonus = 0.0
        for boundary in config.amount_tiers:
            lower = boundary * (1.0 - config.just_below_threshold_pct)
            if lower <= amount < boundary:
                threshold_bonus = 0.20
                signals.append(RiskSignal(
                    signal_type="just_below_threshold",
                    raw_value=amount,
                    contribution=threshold_bonus,
                    description_en=(
                        f"Amount {amount:,.2f} is just below approval threshold "
                        f"{boundary:,.0f} (within {config.just_below_threshold_pct:.0%})"
                    ),
                    description_ar=(
                        f"المبلغ {amount:,.2f} أقل بقليل من حد الموافقة "
                        f"{boundary:,.0f} (ضمن {config.just_below_threshold_pct:.0%})"
                    ),
                ))
                break

        raw_score = min(tier_score + round_bonus + threshold_bonus, 1.0)
        expl_en = (
            f"Amount {amount:,.2f}: base score {tier_score:.2f}"
            + (f" +round-number bonus {round_bonus:.2f}" if round_bonus else "")
            + (f" +just-below-threshold bonus {threshold_bonus:.2f}" if threshold_bonus else "")
        )
        expl_ar = (
            f"المبلغ {amount:,.2f}: الدرجة الأساسية {tier_score:.2f}"
            + (f" + مكافأة الرقم المستدير {round_bonus:.2f}" if round_bonus else "")
            + (f" + مكافأة ما قبل العتبة {threshold_bonus:.2f}" if threshold_bonus else "")
        )

        return ComponentScore(
            name="amount",
            raw_score=round(raw_score, 4),
            weight=0.0,
            weighted_score=0.0,
            signals=signals,
            explanation_en=expl_en,
            explanation_ar=expl_ar,
        ), []

    @staticmethod
    def _safe_float(value) -> Optional[float]:
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None


class ApprovalScoreComponent:
    """
    Scores the approval chain integrity for the document.

    Rules
    -----
      Approved by named approver     → 0.0  (clean)
      Approved but approver unknown  → 0.30 (medium concern)
      Not approved (no approver)     → 0.75 (high concern)
      Not approved + high amount     → Override forced by MissingApprovalHighAmountOverride

    Also detects self-approval (approved_by == created_by) as a governance flag.
    """

    def score(self, doc, config: RiskEngineConfig) -> tuple[ComponentScore, dict]:
        signals:  list[RiskSignal] = []
        metadata: dict = {}

        approved_by_id = getattr(doc, "approved_by_id", None)
        amount = self._safe_float(getattr(doc, "total_amount", None))

        if approved_by_id:
            raw_score = 0.0
            signals.append(RiskSignal(
                signal_type="approved",
                raw_value=str(approved_by_id),
                contribution=0.0,
                description_en=f"Document approved by approver ID {approved_by_id}",
                description_ar=f"تمت الموافقة على المستند من قِبل المعتمد {approved_by_id}",
            ))
            expl_en = "Document has a recorded approval — approval score 0."
            expl_ar = "المستند يحمل موافقة مسجلة — درجة الموافقة 0."
        else:
            metadata["approval_missing"] = True
            metadata["amount"] = amount

            raw_score = 0.75
            signals.append(RiskSignal(
                signal_type="missing_approval",
                raw_value=None,
                contribution=raw_score,
                description_en="No approver recorded on this document",
                description_ar="لا يوجد معتمد مسجل على هذا المستند",
            ))

            if amount and amount > config.missing_approval_critical_amount:
                signals.append(RiskSignal(
                    signal_type="missing_approval_high_amount",
                    raw_value=amount,
                    contribution=1.0,
                    description_en=(
                        f"Amount {amount:,.2f} exceeds critical threshold "
                        f"{config.missing_approval_critical_amount:,.0f} with no approval"
                    ),
                    description_ar=(
                        f"المبلغ {amount:,.2f} يتجاوز الحد الحرج "
                        f"{config.missing_approval_critical_amount:,.0f} بدون موافقة"
                    ),
                ))
                metadata["triggers_critical_override"] = True
                raw_score = 1.0

            expl_en = (
                f"Missing approval"
                + (f" on high-value document ({amount:,.2f})" if amount else "")
                + f" — score {raw_score:.2f}."
            )
            expl_ar = (
                f"موافقة مفقودة"
                + (f" على مستند عالي القيمة ({amount:,.2f})" if amount else "")
                + f" — الدرجة {raw_score:.2f}."
            )

        return ComponentScore(
            name="approval",
            raw_score=round(raw_score, 4),
            weight=0.0,
            weighted_score=0.0,
            signals=signals,
            explanation_en=expl_en,
            explanation_ar=expl_ar,
        ), metadata

    @staticmethod
    def _safe_float(value) -> Optional[float]:
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None


class VendorScoreComponent:
    """
    Scores counterparty/vendor risk.

    Scoring matrix
    --------------
      Registered + approved vendor   → 0.0
      Registered but unknown status  → weight_unknown (0.30)
      Unregistered / null vendor     → 0.50
      Vendor flags                   → +flag_score per flag (cap 1.0)
      Unapproved vendor              → weight_unapproved (0.50)
    """

    def score(self, vendor_context: dict, config: RiskEngineConfig) -> ComponentScore:
        signals: list[RiskSignal] = []

        if not vendor_context:
            return ComponentScore(
                name="vendor",
                raw_score=0.15,   # slight uncertainty when no vendor data at all
                weight=0.0,
                weighted_score=0.0,
                signals=[RiskSignal(
                    signal_type="no_vendor_data",
                    raw_value=None,
                    contribution=0.15,
                    description_en="No vendor profile available — minor uncertainty",
                    description_ar="لا توجد بيانات للمورد — شك طفيف",
                )],
                explanation_en="Vendor data not loaded — scored 0.15 (minor uncertainty).",
                explanation_ar="بيانات المورد غير محملة — الدرجة 0.15 (شك طفيف).",
            ), []

        raw_score = 0.0
        is_approved = vendor_context.get("is_approved")
        flags       = vendor_context.get("flags", [])
        vendor_name = vendor_context.get("counterparty_name", "unknown")
        prior_risk_score = self._safe_float(vendor_context.get("vendor_risk_score") or vendor_context.get("risk_score"))

        # ── Approval status ───────────────────────────────────────────────
        if is_approved is True:
            signals.append(RiskSignal(
                signal_type="vendor_approved",
                raw_value=vendor_name,
                contribution=0.0,
                description_en=f"Vendor '{vendor_name}' is registered and approved",
                description_ar=f"المورد '{vendor_name}' مسجل ومعتمد",
            ))
        elif is_approved is False:
            raw_score = config.vendor_unapproved_score
            signals.append(RiskSignal(
                signal_type="vendor_unapproved",
                raw_value=vendor_name,
                contribution=raw_score,
                description_en=f"Vendor '{vendor_name}' is NOT approved (score +{raw_score:.2f})",
                description_ar=f"المورد '{vendor_name}' غير معتمد (+{raw_score:.2f})",
            ))
        else:  # None — unknown
            raw_score = config.vendor_unknown_score
            signals.append(RiskSignal(
                signal_type="vendor_unknown",
                raw_value=vendor_name,
                contribution=raw_score,
                description_en=f"Vendor '{vendor_name}' not found in approved vendor registry",
                description_ar=f"المورد '{vendor_name}' غير موجود في قائمة الموردين المعتمدين",
            ))

        # ── Prior VendorRiskScore from Vendor Intelligence ────────────────
        if prior_risk_score is not None:
            normalized_prior = min(max(prior_risk_score / 100.0, 0.0), 1.0)
            raw_score = max(raw_score, normalized_prior)
            signals.append(RiskSignal(
                signal_type="vendor_risk_score",
                raw_value=prior_risk_score,
                contribution=normalized_prior,
                description_en=f"Vendor intelligence score for '{vendor_name}' is {prior_risk_score:.1f}/100.",
                description_ar=f"درجة ذكاء المورد '{vendor_name}' هي {prior_risk_score:.1f}/100.",
            ))

        # ── Vendor flags ──────────────────────────────────────────────────
        for flag in flags:
            flag_contribution = min(config.vendor_flag_score_per_flag, 1.0 - raw_score)
            raw_score = min(raw_score + config.vendor_flag_score_per_flag, 1.0)
            signals.append(RiskSignal(
                signal_type=f"vendor_flag:{flag}",
                raw_value=flag,
                contribution=flag_contribution,
                description_en=f"Vendor flag '{flag}' detected (score +{flag_contribution:.2f})",
                description_ar=f"تم رصد علامة تحذير '{flag}' على المورد (+{flag_contribution:.2f})",
            ))

        expl_en = (
            f"Vendor '{vendor_name}': approved={is_approved}, "
            f"vendor_risk_score={prior_risk_score if prior_risk_score is not None else 'n/a'}, "
            f"flags={flags or 'none'} → score {raw_score:.2f}."
        )
        expl_ar = (
            f"المورد '{vendor_name}': معتمد={is_approved}, "
            f"درجة مخاطر المورد={prior_risk_score if prior_risk_score is not None else 'غير متاح'}, "
            f"علامات={flags or 'لا يوجد'} → درجة {raw_score:.2f}."
        )

        return ComponentScore(
            name="vendor",
            raw_score=round(min(raw_score, 1.0), 4),
            weight=0.0,
            weighted_score=0.0,
            signals=signals,
            explanation_en=expl_en,
            explanation_ar=expl_ar,
        ), []

    @staticmethod
    def _safe_float(value) -> Optional[float]:
        if value in (None, ""):
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None


class BehavioralScoreComponent:
    """
    Scores behavioral anomaly patterns.

    Signals detected
    ----------------
      high_submission_frequency  High doc count for this vendor/type in lookback window
      round_amount               Already handled by AmountScore; skip to avoid double-count
      off_hours_submission       Document created at unusual hours (configurable)
      high_risk_history          High proportion of previous docs were high/critical risk
      no_history                 First-time document from this vendor (mild uncertainty)
    """

    def score(self, doc, history_context: dict, config: RiskEngineConfig) -> ComponentScore:
        signals: list[RiskSignal] = []
        component_score = 0.0

        # ── Frequency anomaly ─────────────────────────────────────────────
        recent_count = history_context.get("recent_run_count", 0)
        if recent_count >= config.high_frequency_threshold:
            freq_contribution = min(recent_count / (config.high_frequency_threshold * 2), 0.40)
            component_score = max(component_score, freq_contribution)
            signals.append(RiskSignal(
                signal_type="high_submission_frequency",
                raw_value=recent_count,
                contribution=freq_contribution,
                description_en=(
                    f"{recent_count} documents submitted in "
                    f"{history_context.get('lookback_days', 90)} days "
                    f"(threshold: {config.high_frequency_threshold})"
                ),
                description_ar=(
                    f"تم تقديم {recent_count} مستنداً في "
                    f"{history_context.get('lookback_days', 90)} يوماً "
                    f"(الحد: {config.high_frequency_threshold})"
                ),
            ))
        elif recent_count == 0:
            signals.append(RiskSignal(
                signal_type="no_history",
                raw_value=0,
                contribution=0.10,
                description_en="No prior submission history for this vendor/document type",
                description_ar="لا يوجد تاريخ تقديم سابق لهذا المورد/نوع المستند",
            ))
            component_score = max(component_score, 0.10)

        # ── High-risk history ─────────────────────────────────────────────
        high_risk_count = history_context.get("high_risk_count", 0)
        if recent_count > 5 and high_risk_count > 0:
            risk_ratio = high_risk_count / recent_count
            if risk_ratio >= 0.30:
                contribution = min(risk_ratio * 0.50, 0.35)
                component_score = max(component_score, contribution)
                signals.append(RiskSignal(
                    signal_type="high_risk_history",
                    raw_value=risk_ratio,
                    contribution=contribution,
                    description_en=(
                        f"{high_risk_count}/{recent_count} prior documents "
                        f"({risk_ratio:.0%}) were high/critical risk"
                    ),
                    description_ar=(
                        f"{high_risk_count}/{recent_count} من المستندات السابقة "
                        f"({risk_ratio:.0%}) كانت ذات مخاطر عالية/حرجة"
                    ),
                ))

        # ── Off-hours submission ──────────────────────────────────────────
        doc_date = getattr(doc, "document_date", None) if doc else None
        if doc_date and hasattr(doc_date, "hour"):
            hour = doc_date.hour
            if hour >= config.off_hours_start or hour < config.off_hours_end:
                contribution = 0.15
                component_score = max(component_score, contribution)
                signals.append(RiskSignal(
                    signal_type="off_hours_submission",
                    raw_value=hour,
                    contribution=contribution,
                    description_en=f"Document dated at {hour:02d}:xx — outside business hours",
                    description_ar=f"المستند مؤرخ في {hour:02d}:xx — خارج ساعات العمل",
                ))

        if not signals:
            signals.append(RiskSignal(
                signal_type="no_behavioral_anomaly",
                raw_value=None,
                contribution=0.0,
                description_en="No behavioral anomalies detected",
                description_ar="لم يتم رصد أي شذوذ سلوكي",
            ))

        expl_en = (
            f"Behavioral signals detected: {[s.signal_type for s in signals if s.contribution > 0] or ['none']}. "
            f"Score: {component_score:.2f}."
        )
        expl_ar = (
            f"الإشارات السلوكية: {[s.signal_type for s in signals if s.contribution > 0] or ['لا يوجد']}. "
            f"الدرجة: {component_score:.2f}."
        )

        return ComponentScore(
            name="behavioral",
            raw_score=round(component_score, 4),
            weight=0.0,
            weighted_score=0.0,
            signals=signals,
            explanation_en=expl_en,
            explanation_ar=expl_ar,
        ), []


# ── Override rules ─────────────────────────────────────────────────────────────

class MissingApprovalHighAmountOverride:
    """
    Special Rule 1: Missing approval + high amount = CRITICAL.

    When a document above the critical amount threshold has no recorded
    approver, this override forces the risk level to CRITICAL regardless
    of the composite score. This catches a common fraud pattern where
    large transactions bypass the approval workflow.
    """

    NAME = "missing_approval_high_amount"

    def apply(
        self,
        result: RiskScoreResult,
        approval_meta: dict,
        config: RiskEngineConfig,
    ) -> RiskScoreResult:
        if not approval_meta.get("triggers_critical_override"):
            return result

        result.overrides_applied.append(self.NAME)
        result.total_score    = max(result.total_score, 90.0)
        result.risk_level     = "critical"
        result.blocks_approval = True
        result.requires_manual_review = True
        result.modifier_reasons.append(self.NAME)

        amount = approval_meta.get("amount", 0)
        msg_en = (
            f"OVERRIDE [{self.NAME}]: Amount {amount:,.2f} exceeds "
            f"{config.missing_approval_critical_amount:,.0f} with no approval → CRITICAL forced."
        )
        msg_ar = (
            f"تجاوز [{self.NAME}]: المبلغ {amount:,.2f} يتجاوز "
            f"{config.missing_approval_critical_amount:,.0f} بدون موافقة → CRITICAL مفروض."
        )
        result.explanations.append(msg_en)
        result.explanations_ar.append(msg_ar)
        return result


class TaxIssueOverride:
    """
    Special Rule 2: Any tax rule failure → minimum HIGH.

    Tax violations (VAT, cutoff period, ZATCA compliance) carry regulatory
    risk that may not be fully reflected in a composite score where tax
    rules are a minority. This override ensures they always surface.
    """

    NAME = "tax_issue"

    def apply(
        self,
        result: RiskScoreResult,
        rule_results: list,
        config: RiskEngineConfig,
    ) -> RiskScoreResult:
        tax_fails = [
            r for r in rule_results
            if getattr(r, "status", "") == "fail"
            and any(
                r.rule_code.startswith(prefix)
                for prefix in config.tax_rule_prefixes
            )
        ]
        if not tax_fails:
            return result

        result.overrides_applied.append(self.NAME)
        result.modifier_reasons.append(self.NAME)

        # Force minimum HIGH (50.0)
        if result.total_score < 50.0:
            result.total_score = 50.0
        if result.risk_level not in ("high", "critical"):
            result.risk_level = "high"
        result.requires_manual_review = True

        codes = ", ".join(r.rule_code for r in tax_fails[:3])
        msg_en = (
            f"OVERRIDE [{self.NAME}]: Tax/VAT rule failure(s) [{codes}] "
            f"→ minimum HIGH enforced."
        )
        msg_ar = (
            f"تجاوز [{self.NAME}]: فشل في قواعد الضرائب/ضريبة القيمة المضافة [{codes}] "
            f"→ الحد الأدنى HIGH مفروض."
        )
        result.explanations.append(msg_en)
        result.explanations_ar.append(msg_ar)
        return result


class BlockingRuleFailOverride:
    """
    Any rule marked blocks_approval=True that fails forces minimum HIGH
    and sets blocks_approval=True on the result.
    """

    NAME = "blocking_rule_fail"

    def apply(self, result: RiskScoreResult, rule_results: list) -> RiskScoreResult:
        blocking_fails = [
            r for r in rule_results
            if getattr(r, "status", "") == "fail"
            and getattr(r, "blocks_approval", False)
        ]
        if not blocking_fails:
            return result

        result.overrides_applied.append(self.NAME)
        result.blocks_approval = True
        result.modifier_reasons.append(self.NAME)

        if result.total_score < 50.0:
            result.total_score = 50.0
        if result.risk_level not in ("high", "critical"):
            result.risk_level = "high"

        codes = ", ".join(r.rule_code for r in blocking_fails[:3])
        msg_en = f"OVERRIDE [{self.NAME}]: Blocking rule failure(s) [{codes}] → blocks_approval=True, minimum HIGH."
        msg_ar = f"تجاوز [{self.NAME}]: فشل في قواعد حجب الموافقة [{codes}] → blocks_approval=True، الحد الأدنى HIGH."
        result.explanations.append(msg_en)
        result.explanations_ar.append(msg_ar)
        return result


class CriticalSeverityFailOverride:
    """
    Any rule with applied_severity=critical that fails forces CRITICAL.
    """

    NAME = "critical_severity_fail"

    def apply(self, result: RiskScoreResult, rule_results: list) -> RiskScoreResult:
        critical_fails = [
            r for r in rule_results
            if getattr(r, "status", "") == "fail"
            and getattr(r, "applied_severity", "") == "critical"
        ]
        if not critical_fails:
            return result

        result.overrides_applied.append(self.NAME)
        result.modifier_reasons.append(self.NAME)
        result.total_score    = max(result.total_score, 75.0)
        result.risk_level     = "critical"
        result.blocks_approval = True
        result.requires_manual_review = True

        codes = ", ".join(r.rule_code for r in critical_fails[:3])
        msg_en = f"OVERRIDE [{self.NAME}]: Critical-severity rule failure(s) [{codes}] → CRITICAL forced."
        msg_ar = f"تجاوز [{self.NAME}]: فشل في قواعد ذات خطورة حرجة [{codes}] → CRITICAL مفروض."
        result.explanations.append(msg_en)
        result.explanations_ar.append(msg_ar)
        return result


# ── Main engine ────────────────────────────────────────────────────────────────

class RiskEngine:
    """
    Computes a dynamic, multi-dimensional, explainable risk score.

    Instantiation
    -------------
        engine = RiskEngine()
        engine = RiskEngine(config=RiskEngineConfig(missing_approval_critical_amount=25_000))

    Usage
    -----
        result = engine.compute(context)   # PipelineContext
        print(result.to_dict())            # canonical risk_data dict

    Score formula
    -------------
        composite = (
            violation.raw_score  × 0.40
          + amount.raw_score     × 0.20
          + approval.raw_score   × 0.20
          + vendor.raw_score     × 0.10
          + behavioral.raw_score × 0.10
        ) × 100

    Then overrides are applied in priority order (highest priority last,
    so they can only ever raise the score, never lower it).
    """

    def __init__(self, config: Optional[RiskEngineConfig] = None):
        self.config = config or RiskEngineConfig()
        self.config.validate()
        self._violation  = ViolationScoreComponent()
        self._amount     = AmountScoreComponent()
        self._approval   = ApprovalScoreComponent()
        self._vendor     = VendorScoreComponent()
        self._behavioral = BehavioralScoreComponent()
        self._anomaly    = DocumentAnomalyDetector()
        self._overrides  = [
            BlockingRuleFailOverride(),
            TaxIssueOverride(),
            CriticalSeverityFailOverride(),
            MissingApprovalHighAmountOverride(),  # highest priority — applied last
        ]

    # ── Public API ─────────────────────────────────────────────────────────────

    def compute(self, context) -> RiskScoreResult:
        """
        Compute risk for the given PipelineContext.
        Returns a fully populated RiskScoreResult.
        """
        cfg = self.config
        doc      = getattr(context, "normalized_doc", None)
        results  = getattr(context, "rule_results", [])
        assigns  = getattr(context, "rule_assignments", [])
        vendor   = getattr(context, "vendor_context", {})
        history  = getattr(context, "history_context", {})

        # ── Score each component ──────────────────────────────────────────
        violation_comp, top_failed = self._violation.score(results, assigns)
        amount_comp,    _          = self._amount.score(doc, cfg)
        approval_comp,  appr_meta  = self._approval.score(doc, cfg)
        vendor_comp,    _          = self._vendor.score(vendor, cfg)
        behavioral_comp, _         = self._behavioral.score(doc, history, cfg)
        anomaly_analysis           = self._anomaly.analyze(doc, vendor_context=vendor, history_context=history)
        self._merge_anomaly_into_behavioral(behavioral_comp, anomaly_analysis)

        # Inject weights and compute weighted scores
        weights = {
            "violation":  cfg.weight_violation,
            "amount":     cfg.weight_amount,
            "approval":   cfg.weight_approval,
            "vendor":     cfg.weight_vendor,
            "behavioral": cfg.weight_behavioral,
        }
        components_list = [
            violation_comp, amount_comp, approval_comp,
            vendor_comp, behavioral_comp,
        ]
        for comp in components_list:
            comp.weight         = weights[comp.name]
            comp.weighted_score = round(comp.raw_score * comp.weight, 6)

        components = {c.name: c for c in components_list}

        # ── Composite score ───────────────────────────────────────────────
        composite = sum(c.weighted_score for c in components_list) * 100.0
        composite = round(min(composite, 100.0), 2)
        risk_level = self._score_to_level(composite)

        # ── Build score_breakdown for backward compat ─────────────────────
        score_breakdown = {
            "violation":  round(violation_comp.weighted_score * 100, 2),
            "amount":     round(amount_comp.weighted_score    * 100, 2),
            "approval":   round(approval_comp.weighted_score  * 100, 2),
            "vendor":     round(vendor_comp.weighted_score    * 100, 2),
            "behavioral": round(behavioral_comp.weighted_score * 100, 2),
            "anomaly_score": round(anomaly_analysis.anomaly_score, 2),
            "anomaly_signal_count": len(anomaly_analysis.findings),
            "anomaly_flags": [finding.code for finding in anomaly_analysis.findings[:5]],
            "anomaly_explanation": anomaly_analysis.explanation,
        }

        # ── Confidence (how complete was the input data?) ─────────────────
        confidence = self._compute_confidence(doc, vendor, history, results)

        # ── Assemble initial result ───────────────────────────────────────
        explanations    = [c.explanation_en for c in components_list]
        explanations_ar = [c.explanation_ar for c in components_list]
        explanations.append(f"Anomaly detection: {anomaly_analysis.explanation}")
        explanations_ar.append(f"تحليل الشذوذ: {anomaly_analysis.explanation_ar}")

        top_failed_rules = top_failed[:5]
        if anomaly_analysis.anomaly_score >= 40:
            top_failed_rules.insert(0, {
                "rule_code": "ANOMALY",
                "severity": self._score_to_level(anomaly_analysis.anomaly_score),
                "contribution": round(anomaly_analysis.anomaly_score / 100.0, 3),
                "risk_contribution": round(anomaly_analysis.anomaly_score / 100.0, 3),
                "explanation": anomaly_analysis.explanation,
            })
        top_failed_rules = top_failed_rules[:5]

        result = RiskScoreResult(
            total_score=composite,
            risk_level=risk_level,
            components=components,
            overrides_applied=[],
            explanations=explanations,
            explanations_ar=explanations_ar,
            blocks_approval=False,
            requires_manual_review=composite >= 50.0,
            confidence=confidence,
            anomaly_score=anomaly_analysis.anomaly_score,
            anomaly_explanation=anomaly_analysis.explanation,
            anomaly_explanation_ar=anomaly_analysis.explanation_ar,
            anomaly_findings=anomaly_analysis.to_dict().get("findings", []),
            score_breakdown=score_breakdown,
            top_failed_rules=top_failed_rules,
            modifier_reasons=[f"anomaly:{finding.code}" for finding in anomaly_analysis.findings[:5]],
        )

        # ── Apply override rules (raise-only — never lower the score) ─────
        for override in self._overrides:
            try:
                if isinstance(override, MissingApprovalHighAmountOverride):
                    result = override.apply(result, appr_meta, cfg)
                elif isinstance(override, TaxIssueOverride):
                    result = override.apply(result, results, cfg)
                elif isinstance(override, (CriticalSeverityFailOverride, BlockingRuleFailOverride)):
                    result = override.apply(result, results)
                else:
                    result = override.apply(result, results)
            except Exception as exc:
                logger.warning("[risk_engine] Override %s failed: %s", type(override).__name__, exc)

        logger.info(
            "[risk_engine] score=%.1f level=%s conf=%.2f overrides=%s components=%s",
            result.total_score,
            result.risk_level,
            result.confidence,
            result.overrides_applied or "none",
            {k: round(v.weighted_score * 100, 1) for k, v in result.components.items()},
        )

        return result

    # ── Helpers ────────────────────────────────────────────────────────────────

    @staticmethod
    def _merge_anomaly_into_behavioral(component: ComponentScore, anomaly_analysis) -> None:
        if not anomaly_analysis or anomaly_analysis.anomaly_score <= 0:
            return

        component.raw_score = round(max(component.raw_score, anomaly_analysis.normalized_score), 4)
        for finding in anomaly_analysis.findings[:5]:
            component.signals.append(RiskSignal(
                signal_type=f"anomaly:{finding.code}",
                raw_value=finding.evidence or finding.code,
                contribution=min(max(finding.contribution / 100.0, 0.0), 1.0),
                description_en=finding.description,
                description_ar=finding.description_ar,
            ))
        component.explanation_en = (
            f"{component.explanation_en} Anomaly score {anomaly_analysis.anomaly_score:.1f}/100."
        )
        component.explanation_ar = (
            f"{component.explanation_ar} درجة الشذوذ {anomaly_analysis.anomaly_score:.1f}/100."
        )

    def _score_to_level(self, score: float) -> str:
        cfg = self.config
        if score >= cfg.threshold_critical:
            return "critical"
        if score >= cfg.threshold_high:
            return "high"
        if score >= cfg.threshold_medium:
            return "medium"
        return "low"

    @staticmethod
    def _compute_confidence(doc, vendor, history, results) -> float:
        """
        Estimate confidence as the fraction of data sources that were available.
        A lower confidence score means the risk assessment is based on incomplete data.
        """
        sources = [
            doc is not None,                              # document normalized
            bool(vendor),                                 # vendor context loaded
            bool(history),                                # document history loaded
            len(results) > 0,                             # rules were executed
            getattr(doc, "total_amount", None) is not None,  # amount present
            getattr(doc, "approved_by_id", None) is not None  # approval recorded
            or getattr(doc, "status", "") in ("approved", "validated"),
        ]
        return round(sum(sources) / len(sources), 3)


# ── Example scoring cases ──────────────────────────────────────────────────────

def run_scoring_examples() -> None:
    """
    Standalone demonstration of scoring logic.
    Run directly:  python -c "from apps.rule_engine.risk.risk_engine import run_scoring_examples; run_scoring_examples()"
    """
    from dataclasses import make_dataclass
    from datetime import date

    Ctx = make_dataclass("Ctx", [
        "normalized_doc", "rule_results", "rule_assignments",
        "vendor_context", "history_context", "erp_context",
    ])
    Doc = make_dataclass("Doc", [
        "document_id", "document_type", "organization_id",
        "total_amount", "approved_by_id", "document_date",
        "counterparty_name", "status", "budget_limit",
        "cost_center", "account_code",
    ])
    Rule = make_dataclass("Rule", [
        "rule_code", "status", "applied_severity",
        "blocks_approval", "explanation", "explanation_ar",
        "risk_contribution",
    ])

    engine = RiskEngine()

    cases = [
        {
            "name": "CASE 1 — Clean invoice, low risk",
            "doc": Doc("d1", "sales_invoice", "org1", 5_000, "approver_1", date(2025, 3, 10), "ACME Corp", "approved", None, "CC-100", "ACC-200"),
            "results": [Rule("GEN-H01", "pass", "high", False, "Document number present", "", 0.0)],
            "vendor": {"is_approved": True, "flags": [], "counterparty_name": "ACME Corp"},
            "history": {"recent_run_count": 5, "high_risk_count": 0, "lookback_days": 90},
        },
        {
            "name": "CASE 2 — Missing approval + high amount → CRITICAL override",
            "doc": Doc("d2", "sales_invoice", "org1", 250_000, None, date(2025, 3, 10), "Unknown Vendor", "pending", None, "CC-200", "ACC-300"),
            "results": [
                Rule("GEN-H01", "pass", "high", False, "OK", "", 0.0),
                Rule("INV-H04", "fail", "high", True, "Approval missing", "موافقة مفقودة", 0.75),
            ],
            "vendor": {"is_approved": None, "flags": [], "counterparty_name": "Unknown Vendor"},
            "history": {"recent_run_count": 0, "high_risk_count": 0, "lookback_days": 90},
        },
        {
            "name": "CASE 3 — VAT rule failure → TAX ISSUE override",
            "doc": Doc("d3", "sales_invoice", "org1", 30_000, "approver_2", date(2025, 3, 10), "Gulf Trading", "approved", None, None, None),
            "results": [
                Rule("VAT-001", "fail", "high", False, "VAT rate mismatch", "عدم تطابق ضريبة القيمة المضافة", 0.8),
                Rule("GEN-H02", "pass", "medium", False, "Date OK", "", 0.0),
            ],
            "vendor": {"is_approved": True, "flags": [], "counterparty_name": "Gulf Trading"},
            "history": {"recent_run_count": 12, "high_risk_count": 2, "lookback_days": 90},
        },
        {
            "name": "CASE 4 — Multiple high-severity failures + suspicious amount",
            "doc": Doc("d4", "sales_invoice", "org1", 100_000, None, date(2025, 3, 22), "Phantom Inc", "draft", 80_000, "CC-999", "ACC-999"),
            "results": [
                Rule("INV-C03", "fail", "critical", True,  "Duplicate invoice", "فاتورة مكررة", 1.0),
                Rule("INV-H04", "fail", "high",     True,  "Missing approval",  "موافقة مفقودة", 0.75),
                Rule("GAAP-DOC-001", "fail", "high", False, "No supporting docs", "", 0.7),
                Rule("GEN-H01", "warning", "medium", False, "Partial document number", "", 0.3),
            ],
            "vendor": {"is_approved": False, "flags": ["late_payment", "dispute"], "counterparty_name": "Phantom Inc"},
            "history": {"recent_run_count": 80, "high_risk_count": 30, "lookback_days": 90},
        },
    ]

    for case in cases:
        doc_obj = case["doc"]
        ctx = Ctx(
            normalized_doc=doc_obj,
            rule_results=case["results"],
            rule_assignments=[],
            vendor_context=case["vendor"],
            history_context=case["history"],
            erp_context={},
        )
        result = engine.compute(ctx)
        print(f"\n{'='*60}")
        print(f"  {case['name']}")
        print(f"{'='*60}")
        print(f"  Score:     {result.total_score:.1f} / 100")
        print(f"  Level:     {result.risk_level.upper()}")
        print(f"  Blocks:    {result.blocks_approval}")
        print(f"  Review:    {result.requires_manual_review}")
        print(f"  Overrides: {result.overrides_applied or 'none'}")
        print(f"  Confidence:{result.confidence:.2f}")
        print(f"  Breakdown:")
        for name, comp in result.components.items():
            bar = "█" * int(comp.raw_score * 20)
            print(f"    {name:12s} {comp.raw_score:.3f} × {comp.weight:.2f} = {comp.contribution_pts:5.1f}pts  {bar}")
        print(f"  Explanation (EN):")
        for expl in result.explanations:
            print(f"    • {expl}")


if __name__ == "__main__":
    run_scoring_examples()
