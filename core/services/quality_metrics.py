"""
OCR Quality Metrics & Document Scoring System
=============================================
Calculates confidence scores and risk levels based on OCR output and validation.
"""

import logging
from decimal import Decimal
from typing import Optional

from django.conf import settings

logger = logging.getLogger("finai")


class QualityMetrics:
    """Calculate document quality metrics and scoring"""

    # Score thresholds
    CONFIDENCE_WEIGHT = 0.3  # 30% of final score
    VALIDATION_WEIGHT = 0.5  # 50% of final score
    QUALITY_WEIGHT = 0.2  # 20% of final score

    # Risk level thresholds
    RISK_CRITICAL_THRESHOLD = 39  # 0-39: Critical
    RISK_HIGH_THRESHOLD = 59  # 40-59: High
    RISK_MEDIUM_THRESHOLD = 79  # 60-79: Medium
    # 80-100: Low

    class RiskLevel:
        LOW = "low"
        MEDIUM = "medium"
        HIGH = "high"
        CRITICAL = "critical"

    @staticmethod
    def calculate_ocr_confidence(tesseract_result: dict) -> float:
        """
        Calculate average word-level confidence from Tesseract OCR.

        Args:
            tesseract_result: Dict with 'confidence' key from extract_text_tesseract()

        Returns:
            Confidence score 0-100
        """
        confidence = tesseract_result.get("confidence", 0.0)
        return min(100, max(0, float(confidence)))

    @staticmethod
    def calculate_image_quality(image_path: str) -> float:
        """
        Score image quality based on contrast, brightness, and sharpness.

        Args:
            image_path: Path to image file

        Returns:
            Quality score 0-100
        """
        try:
            from PIL import Image, ImageStat

            img = Image.open(image_path)

            # Convert to grayscale for analysis
            if img.mode != "L":
                img = img.convert("L")

            stat = ImageStat.Stat(img)

            # Extract metrics
            mean_brightness = stat.mean[0]  # 0-255
            stddev_contrast = stat.stddev[0]  # Higher = better contrast

            # Contrast score: optimal range 30-50 stddev
            # Below 20: poor contrast, Above 80: too harsh
            if stddev_contrast < 20:
                contrast_score = (stddev_contrast / 20) * 50
            elif stddev_contrast > 80:
                contrast_score = 100 - ((stddev_contrast - 80) / 100) * 30
            else:
                contrast_score = 50 + ((stddev_contrast - 20) / 60) * 50

            # Brightness score: optimal range 80-180
            if mean_brightness < 50:
                brightness_score = (mean_brightness / 50) * 30
            elif mean_brightness > 230:
                brightness_score = 100 - ((mean_brightness - 230) / 25) * 30
            else:
                brightness_score = 50 + ((mean_brightness - 50) / 130) * 50

            # Combined score
            quality_score = (contrast_score * 0.6) + (brightness_score * 0.4)

            return min(100, max(0, quality_score))

        except Exception as e:
            logger.warning(f"Image quality calculation failed: {e}")
            return 50  # Neutral default

    @staticmethod
    def calculate_validation_score(validation_results: dict, total_rules: int = 30) -> float:
        """
        Calculate validation score based on rules passed.

        Args:
            validation_results: Dict with validation results
            total_rules: Total validation rules (default: 30 for invoices)

        Returns:
            Validation score 0-100
        """
        if not validation_results:
            return 0.0

        passed_rules = sum(
            1 for rule in validation_results.values()
            if isinstance(rule, dict) and rule.get("passed", False)
        )

        if not validation_results:
            passed_rules = 0

        return (passed_rules / total_rules) * 100 if total_rules > 0 else 0.0

    @classmethod
    def calculate_final_score(
        cls,
        ocr_confidence: float,
        validation_score: float,
        quality_score: float,
    ) -> float:
        """
        Calculate weighted final score.

        Score = (OCR_Confidence × 0.3) + (Validation_Score × 0.5) + (Quality_Score × 0.2)

        Args:
            ocr_confidence: 0-100
            validation_score: 0-100
            quality_score: 0-100

        Returns:
            Final score 0-100
        """
        final = (
            (ocr_confidence * cls.CONFIDENCE_WEIGHT)
            + (validation_score * cls.VALIDATION_WEIGHT)
            + (quality_score * cls.QUALITY_WEIGHT)
        )

        return min(100, max(0, final))

    @classmethod
    def assign_risk_level(cls, score: float, critical_rules_failed: bool = False) -> str:
        """
        Assign risk level based on score and critical rule failures.

        Args:
            score: Final document score 0-100
            critical_rules_failed: If any critical validation rule failed

        Returns:
            Risk level: 'low', 'medium', 'high', 'critical'
        """
        # Critical rule failures override score
        if critical_rules_failed:
            return cls.RiskLevel.CRITICAL

        if score >= 80:
            return cls.RiskLevel.LOW
        elif score >= cls.RISK_MEDIUM_THRESHOLD:
            return cls.RiskLevel.MEDIUM
        elif score >= cls.RISK_HIGH_THRESHOLD:
            return cls.RiskLevel.HIGH
        else:
            return cls.RiskLevel.CRITICAL

    @staticmethod
    def get_action_for_risk_level(risk_level: str) -> dict:
        """
        Get recommended action based on risk level.

        Returns:
            Dict with action, auto_process, review_required, flags
        """
        actions = {
            "low": {
                "action": "auto_approve",
                "description": "Auto-approved, process immediately",
                "auto_process": True,
                "review_required": False,
                "flags": [],
            },
            "medium": {
                "action": "review_suggested",
                "description": "Review suggested before processing",
                "auto_process": False,
                "review_required": True,
                "flags": ["needs_review"],
            },
            "high": {
                "action": "manual_review_required",
                "description": "Manual review required before processing",
                "auto_process": False,
                "review_required": True,
                "flags": ["needs_manual_review", "high_risk"],
            },
            "critical": {
                "action": "escalate",
                "description": "Escalate to compliance team",
                "auto_process": False,
                "review_required": True,
                "flags": ["escalated", "critical_risk", "compliance_review_needed"],
            },
        }
        return actions.get(risk_level, actions["critical"])

    @staticmethod
    def calculate_confidence_stats(page_results: list) -> dict:
        """
        Calculate confidence statistics across multiple pages.

        Args:
            page_results: List of page result dicts with 'confidence' key

        Returns:
            Dict with stats: avg, min, max, pages_low_confidence
        """
        if not page_results:
            return {"average": 0, "minimum": 0, "maximum": 0, "pages_low_confidence": 0}

        confidences = [p.get("confidence", 0) for p in page_results]
        low_conf_count = sum(1 for c in confidences if c < 60)

        return {
            "average": sum(confidences) / len(confidences) if confidences else 0,
            "minimum": min(confidences) if confidences else 0,
            "maximum": max(confidences) if confidences else 0,
            "pages_low_confidence": low_conf_count,
            "total_pages": len(confidences),
        }


class DocumentScorer:
    """Complete document scoring pipeline"""

    def __init__(self):
        self.metrics = QualityMetrics()

    def score_document(
        self,
        ocr_result: dict,
        validation_results: dict = None,
        image_path: str = None,
    ) -> dict:
        """
        End-to-end document scoring.

        Args:
            ocr_result: Result from process_document_hybrid()
            validation_results: Validation rule results (optional)
            image_path: Path to first page image for quality analysis (optional)

        Returns:
            Score result dict
        """
        # Get component scores
        ocr_confidence = self.metrics.calculate_ocr_confidence(ocr_result)

        validation_score = (
            self.metrics.calculate_validation_score(validation_results)
            if validation_results
            else 50.0
        )

        quality_score = 50.0
        if image_path:
            quality_score = self.metrics.calculate_image_quality(image_path)

        # Calculate final score
        final_score = self.metrics.calculate_final_score(
            ocr_confidence, validation_score, quality_score
        )

        # Assign risk level
        risk_level = self.metrics.assign_risk_level(final_score)

        # Get action
        action = self.metrics.get_action_for_risk_level(risk_level)

        # Build result
        result = {
            "final_score": round(final_score, 2),
            "component_scores": {
                "ocr_confidence": round(ocr_confidence, 2),
                "validation_score": round(validation_score, 2),
                "quality_score": round(quality_score, 2),
            },
            "risk_level": risk_level,
            "risk_action": action["action"],
            "auto_processable": action["auto_process"],
            "review_required": action["review_required"],
            "flags": action["flags"],
            "recommendation": action["description"],
        }

        return result


def score_document_simple(
    ocr_confidence: float,
    validation_passed: int,
    validation_total: int = 30,
    quality_score: float = 50,
) -> dict:
    """Quick scoring helper for simple use cases"""
    scorer = DocumentScorer()
    return scorer.score_document(
        ocr_result={"confidence": ocr_confidence},
        validation_results={f"rule_{i}": {"passed": i < validation_passed} for i in range(validation_total)},
    )
