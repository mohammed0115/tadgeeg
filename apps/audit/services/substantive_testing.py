"""Substantive Testing service (TADGEEG-FIN-AUDIT-9D).

Create test items, derive the independent "tested" value via deterministic
recompute helpers (straight-line depreciation for fixed assets; net pay for
payroll; counted quantity × unit cost for inventory), record the tested value,
and reconcile against the books (matched / variance by tolerance).

Deterministic (no AI); never writes to ``apps.ledger``; a variance is flagged,
never auto-corrected.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation

from django.db import IntegrityError, transaction
from django.db.models import Count, Q, Sum

from apps.audit.substantive_test_models import SubstantiveTestItem

_I = SubstantiveTestItem
_Area = _I.Area
_St = _I.Status
_ZERO = Decimal("0")


class SubstantiveTestError(Exception):
    """Invalid input or scoping violation."""


def _dec(value, default=_ZERO):
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return default


# ─────────────────────────────────────────────────────────────────────────────
# Deterministic recompute helpers (ISA 500/540 auditor re-performance)
# ─────────────────────────────────────────────────────────────────────────────
def straight_line_nbv(*, cost, salvage, useful_life_years, elapsed_years) -> dict:
    """Recompute accumulated depreciation + net book value (straight-line)."""
    cost = _dec(cost); salvage = _dec(salvage)
    life = _dec(useful_life_years); elapsed = _dec(elapsed_years)
    if life <= 0:
        raise SubstantiveTestError("useful_life_years must be > 0.")
    depreciable = max(cost - salvage, _ZERO)
    annual = (depreciable / life)
    accumulated = min(annual * elapsed, depreciable)
    nbv = cost - accumulated
    return {
        "annual_depreciation": annual.quantize(Decimal("0.0001")),
        "accumulated_depreciation": accumulated.quantize(Decimal("0.0001")),
        "net_book_value": nbv.quantize(Decimal("0.0001")),
    }


def net_pay(*, gross, deductions) -> Decimal:
    """Recompute net pay = gross − total deductions."""
    return (_dec(gross) - _dec(deductions)).quantize(Decimal("0.0001"))


def inventory_value(*, quantity, unit_cost) -> Decimal:
    """Recompute inventory value = counted quantity × unit cost."""
    return (_dec(quantity) * _dec(unit_cost)).quantize(Decimal("0.0001"))


def _tested_from_inputs(area, inputs) -> Decimal | None:
    """Derive the tested value from area-specific inputs (or None)."""
    if not inputs:
        return None
    try:
        if area == _Area.FIXED_ASSETS and "cost" in inputs:
            return straight_line_nbv(
                cost=inputs.get("cost", 0), salvage=inputs.get("salvage", 0),
                useful_life_years=inputs.get("useful_life_years", 0),
                elapsed_years=inputs.get("elapsed_years", 0))["net_book_value"]
        if area == _Area.PAYROLL and "gross" in inputs:
            return net_pay(gross=inputs.get("gross", 0),
                           deductions=inputs.get("deductions", 0))
        if area == _Area.INVENTORY and "unit_cost" in inputs and "quantity" in inputs:
            return inventory_value(quantity=inputs.get("quantity", 0),
                                   unit_cost=inputs.get("unit_cost", 0))
    except SubstantiveTestError:
        return None
    return None


# ─────────────────────────────────────────────────────────────────────────────
# Workflow
# ─────────────────────────────────────────────────────────────────────────────
def _next_reference(organization) -> str:
    count = SubstantiveTestItem.objects.filter(organization=organization).count()
    return f"SUB-{count + 1:05d}"


def create_item(*, engagement, actor, area, book_value, item_reference="",
                description="", tested_value=None, tolerance=0, inputs=None,
                quantity_book=None, quantity_counted=None) -> SubstantiveTestItem:
    """Create a substantive-test item. Derives tested_value from inputs if given."""
    organization = engagement.organization
    inputs = inputs or {}
    derived = _tested_from_inputs(area, inputs)
    if derived is not None:
        tested_value = derived
    obj = SubstantiveTestItem(
        engagement=engagement, organization=organization, area=area,
        item_reference=item_reference, description=description,
        book_value=_dec(book_value),
        tested_value=_dec(tested_value) if tested_value not in (None, "") else None,
        tolerance=_dec(tolerance), inputs=inputs,
        quantity_book=_dec(quantity_book) if quantity_book not in (None, "") else None,
        quantity_counted=_dec(quantity_counted) if quantity_counted not in (None, "") else None,
        created_by=actor if getattr(actor, "pk", None) else None,
        status=_St.OPEN)
    obj.full_clean(exclude=["created_by", "reference"])
    with transaction.atomic():
        for attempt in range(5):
            obj.reference = _next_reference(organization)
            try:
                with transaction.atomic():
                    obj.save()
                break
            except IntegrityError:
                if attempt == 4:
                    raise
    # If a tested value is already present, classify immediately.
    if obj.tested_value is not None:
        _classify(obj)
    return obj


def record_tested(*, item, actor, tested_value, note="") -> SubstantiveTestItem:
    """Record the independently tested value and classify matched/variance."""
    if item.status == _St.CANCELLED:
        raise SubstantiveTestError("cannot test a cancelled item.")
    item.tested_value = _dec(tested_value)
    if note:
        item.notes = note
    item.save(update_fields=["tested_value", "notes", "updated_at"])
    return _classify(item)


def _classify(item) -> SubstantiveTestItem:
    within = item.is_within_tolerance
    item.status = _St.MATCHED if within else _St.VARIANCE
    item.save(update_fields=["status", "updated_at"])
    return item


def cancel(*, item, actor) -> SubstantiveTestItem:
    item.status = _St.CANCELLED
    item.save(update_fields=["status", "updated_at"])
    return item


def area_summary(*, organization, engagement=None) -> dict:
    """Per-area counts + total absolute variance for the dashboard."""
    qs = SubstantiveTestItem.objects.filter(organization=organization)
    if engagement is not None:
        qs = qs.filter(engagement=engagement)
    out = {}
    for area in _Area:
        aq = qs.filter(area=area.value)
        agg = aq.aggregate(
            total=Count("id"),
            matched=Count("id", filter=Q(status=_St.MATCHED)),
            variance=Count("id", filter=Q(status=_St.VARIANCE)),
            book=Sum("book_value"), tested=Sum("tested_value"))
        book = agg["book"] or _ZERO
        tested = agg["tested"] or _ZERO
        out[area.value] = {
            "total": agg["total"] or 0,
            "matched": agg["matched"] or 0,
            "variance": agg["variance"] or 0,
            "book_total": str(book),
            "tested_total": str(tested),
            "net_variance": str(book - tested),
        }
    totals = qs.aggregate(
        total=Count("id"),
        variance=Count("id", filter=Q(status=_St.VARIANCE)),
        matched=Count("id", filter=Q(status=_St.MATCHED)))
    out["_totals"] = {k: (v or 0) for k, v in totals.items()}
    return out
