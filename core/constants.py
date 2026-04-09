"""
core/constants.py
=================
Named constants shared across the invoice processing and validation domain.

Why a central constants module:
  Magic numbers scattered across validation_service.py, processor.py, and
  models.py make threshold changes error-prone (grep and pray) and obscure
  their business meaning. Centralising them here lets you change a threshold
  in one place and gives every number a name that explains *why* it exists.
"""

# ── Risk-level thresholds ─────────────────────────────────────────────────────
# risk_level_from_score() maps numeric scores to human-readable levels.
HIGH_RISK_THRESHOLD: float = 70.0   # score >= this → "high"
MEDIUM_RISK_THRESHOLD: float = 40.0  # score >= this (and < HIGH) → "medium"

# ── Fallback risk-score floor bumps ──────────────────────────────────────────
# When the AI engine is unavailable, the validation-based fallback score is
# bumped to at least these floors when specific high-signal rule groups fail.
DUP_RISK_FLOOR: float = 78.0   # Any DUP-* failure → score at least this
ANO_RISK_FLOOR: float = 72.0   # Any ANO-* failure → score at least this
VAT_RISK_FLOOR: float = 58.0   # Any VAT-* failure → score at least this

# ── VAT arithmetic tolerances ────────────────────────────────────────────────
# Invoice.vat_is_correct: |subtotal + vat - total| must be below this (1 SAR).
VAT_MATH_TOLERANCE: float = 1.0
# Invoice.vat_rate_is_correct: |actual_rate - nominal_rate| must be below this.
VAT_RATE_TOLERANCE: float = 0.5

# ── File-size thresholds ─────────────────────────────────────────────────────
# Single uploaded files larger than this are processed asynchronously via Celery.
AUTO_ASYNC_FILE_SIZE: int = 512 * 1024  # 512 KB
