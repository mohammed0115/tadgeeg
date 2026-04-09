"""
core/domain/result.py
=====================
ServiceResult — standardized return type for all service layer functions.

Problem this solves:
  Each service in core/services/ returns a different shape (some return dicts,
  some return model instances, some raise exceptions). Callers must know the
  internal contract of each service. When a service changes its return shape,
  callers break silently.

Usage:

    # In a service:
    from core.domain.result import ServiceResult

    def validate_invoice(invoice_id: str) -> ServiceResult:
        try:
            invoice = Invoice.objects.get(pk=invoice_id)
            # ... do work ...
            return ServiceResult.ok(data={"risk_score": 0.3, "passed": True})
        except Invoice.DoesNotExist:
            return ServiceResult.fail("Invoice not found", code="NOT_FOUND")
        except Exception as exc:
            return ServiceResult.fail(str(exc), code="INTERNAL_ERROR")

    # In a view:
    result = validate_invoice(invoice_id)
    if not result.success:
        return Response({"error": result.error, "code": result.code}, status=400)
    return Response(result.data)

    # In a task:
    result = validate_invoice(invoice_id)
    if not result.success:
        logger.error("Validation failed: %s [%s]", result.error, result.code)
        raise ValueError(result.error)
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class ServiceResult:
    """
    Uniform return type for all service functions.

    Attributes:
        success (bool):  True if the operation completed without error.
        data    (Any):   Payload returned by the service on success.
                         None on failure.
        error   (str):   Human-readable error message. Empty string on success.
        code    (str):   Machine-readable error code for programmatic handling.
                         Empty string on success.
        meta    (dict):  Optional extra metadata (timing, warnings, debug info).
    """

    success: bool
    data: Any = None
    error: str = ""
    code: str = ""
    meta: dict = field(default_factory=dict)

    # ── Constructors ──────────────────────────────────────────────────────────

    @classmethod
    def ok(cls, data: Any = None, meta: Optional[dict] = None) -> "ServiceResult":
        """Return a successful result."""
        return cls(success=True, data=data, meta=meta or {})

    @classmethod
    def fail(
        cls,
        error: str,
        code: str = "ERROR",
        data: Any = None,
        meta: Optional[dict] = None,
    ) -> "ServiceResult":
        """Return a failed result."""
        return cls(success=False, data=data, error=error, code=code, meta=meta or {})

    # ── Helpers ───────────────────────────────────────────────────────────────

    def raise_if_failed(self) -> "ServiceResult":
        """Raise ValueError if this result is a failure. Returns self for chaining."""
        if not self.success:
            raise ValueError(f"[{self.code}] {self.error}")
        return self

    def to_dict(self) -> dict:
        """Serialize to a plain dict (useful for logging or API responses)."""
        return {
            "success": self.success,
            "data": self.data,
            "error": self.error,
            "code": self.code,
            "meta": self.meta,
        }

    def __bool__(self) -> bool:
        """Allow `if result:` as a shorthand for `if result.success:`."""
        return self.success

    def __repr__(self) -> str:
        if self.success:
            return f"ServiceResult.ok(data={self.data!r})"
        return f"ServiceResult.fail(error={self.error!r}, code={self.code!r})"
