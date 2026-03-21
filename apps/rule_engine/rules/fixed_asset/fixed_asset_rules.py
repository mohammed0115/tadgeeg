"""AST-M01, AST-M02, AST-M04, AST-M06: Fixed asset audit rules"""
from decimal import Decimal
from apps.rule_engine.rules.base import AuditRuleBase, NormalizedDocument, RuleResult, EvidenceItem


class DepreciationCalculationRule(AuditRuleBase):
    rule_code = "AST-M01"
    rule_name_en = "Depreciation Calculation Error"
    rule_name_ar = "خطأ في حساب الإهلاك"
    default_severity = "critical"
    rule_type = "validation"

    TOLERANCE = Decimal("1.00")

    def check_preconditions(self, doc: NormalizedDocument) -> bool:
        assets = doc.get("assets", [])
        return isinstance(assets, list) and len(assets) > 0

    def execute(self, doc: NormalizedDocument) -> RuleResult:
        assets = doc.get("assets", [])
        errors = []
        evidence = []

        for asset in assets:
            method = str(asset.get("method", "straight_line")).lower()
            if "straight" not in method:
                continue  # Only validate straight-line for now

            cost = self.safe_decimal(asset.get("cost", 0))
            useful_life = self.safe_decimal(asset.get("useful_life_years", 0))
            annual_dep = self.safe_decimal(asset.get("annual_depreciation", 0))

            if useful_life <= 0 or cost <= 0:
                continue

            expected_dep = (cost / useful_life).quantize(Decimal("0.01"))
            discrepancy = abs(expected_dep - annual_dep)

            if discrepancy > self.TOLERANCE:
                asset_name = asset.get("name", asset.get("asset_id", "Unknown"))
                errors.append(asset_name)
                evidence.append(EvidenceItem(
                    evidence_type="calculation",
                    field_name="annual_depreciation",
                    field_name_ar="الإهلاك السنوي",
                    expected_value=float(expected_dep),
                    actual_value=float(annual_dep),
                    description=f"Asset '{asset_name}': Cost({cost})/Life({useful_life}) = {expected_dep}, actual = {annual_dep}",
                    description_ar=f"أصل '{asset_name}': التكلفة({cost})/العمر({useful_life}) = {expected_dep}، الفعلي = {annual_dep}",
                ))

        if errors:
            return self._fail(
                f"Depreciation calculation errors in {len(errors)} asset(s): {', '.join(errors[:3])}",
                f"أخطاء في حساب الإهلاك لـ {len(errors)} أصل: {', '.join(errors[:3])}",
                evidence=evidence,
            )
        return self._pass(
            "All straight-line depreciation calculations are correct.",
            "جميع حسابات الإهلاك بطريقة القسط الثابت صحيحة.",
        )


class NegativeBookValueRule(AuditRuleBase):
    rule_code = "AST-M02"
    rule_name_en = "Negative Book Value Detected"
    rule_name_ar = "قيمة دفترية سالبة"
    default_severity = "critical"
    rule_type = "validation"

    def check_preconditions(self, doc: NormalizedDocument) -> bool:
        return doc.get("negative_book_value_count") is not None or bool(doc.get("assets"))

    def execute(self, doc: NormalizedDocument) -> RuleResult:
        neg_count = doc.get("negative_book_value_count", 0) or 0

        if neg_count == 0:
            assets = doc.get("assets", [])
            negative_assets = [
                a for a in assets
                if self.safe_decimal(a.get("book_value", 0)) < 0
            ]
            neg_count = len(negative_assets)

        if neg_count > 0:
            return self._fail(
                f"{neg_count} asset(s) have a negative book value (accumulated depreciation exceeds cost).",
                f"{neg_count} أصل ذو قيمة دفترية سالبة (الإهلاك المتراكم يتجاوز التكلفة).",
                evidence=[EvidenceItem(
                    evidence_type="calculation",
                    field_name="book_value",
                    field_name_ar="القيمة الدفترية",
                    expected_value=">= 0",
                    actual_value=f"{neg_count} assets with negative book value",
                    description="Negative book value = accumulated depreciation > original cost.",
                    description_ar="القيمة الدفترية السالبة = الإهلاك المتراكم > التكلفة الأصلية.",
                )]
            )
        return self._pass(
            "All assets have non-negative book values.",
            "جميع الأصول ذات قيمة دفترية غير سالبة.",
        )


class DuplicateAssetIDRule(AuditRuleBase):
    rule_code = "AST-M04"
    rule_name_en = "Duplicate Asset Registration"
    rule_name_ar = "تسجيل أصل مكرر"
    default_severity = "high"
    rule_type = "validation"

    def check_preconditions(self, doc: NormalizedDocument) -> bool:
        assets = doc.get("assets", [])
        return isinstance(assets, list) and len(assets) > 1

    def execute(self, doc: NormalizedDocument) -> RuleResult:
        dup_count = doc.get("duplicate_asset_id_count", 0) or 0

        if dup_count == 0:
            assets = doc.get("assets", [])
            seen = {}
            duplicates = []
            for asset in assets:
                aid = asset.get("asset_id")
                if not aid:
                    continue
                if aid in seen:
                    duplicates.append(aid)
                else:
                    seen[aid] = True
            dup_count = len(duplicates)

        if dup_count > 0:
            return self._fail(
                f"{dup_count} duplicate asset ID(s) detected in the register.",
                f"تم اكتشاف {dup_count} معرّف أصل مكرر في السجل.",
                evidence=[EvidenceItem(
                    evidence_type="validation",
                    field_name="asset_id",
                    field_name_ar="معرّف الأصل",
                    expected_value="All unique",
                    actual_value=f"{dup_count} duplicates",
                    description="Duplicate asset IDs found in register.",
                    description_ar="معرّفات أصول مكررة في السجل.",
                )]
            )
        return self._pass(
            "All asset IDs are unique.",
            "جميع معرّفات الأصول فريدة.",
        )
