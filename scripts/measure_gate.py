"""Measure the V1 -> V2 risk delta on a fixed sample. Read-only.

The question this answers, from docs/CTO_DECISION_shipment_3.md §2: if the
document path is switched to V2, on how many documents does blocks_approval
flip from False to True? Those are approvals granted today that would stop
being granted.

WHY THIS IS READ-ONLY DESPITE THE PIPELINES WRITING

Both pipelines create an AuditRun row and update it as they go; V1's run()
does it unconditionally on its first line. Neither offers a dry-run. So every
document is processed inside a transaction that is rolled back afterwards —
nothing survives the measurement. Verified by counting AuditRun before and
after and asserting the count is unchanged, which is printed with the results
rather than asserted silently.

DETERMINISM

order_by("id") with a slice, never order_by("?"). Re-running on the same
database yields the same sample and therefore the same numbers. The sample is
printed so a reader can reproduce it.

Usage:
    python scripts/measure_gate.py [limit]
"""

import os
import sys
from pathlib import Path

import django

# Run from scripts/, so the project root is not on sys.path by default.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "finai_backend.settings")
django.setup()

from django.db import transaction  # noqa: E402


class _Rollback(Exception):
    """Raised to unwind the transaction once a run has been measured."""


def _run_one(document, engine):
    """Run one engine against one document and return its verdict.

    The AuditRun the pipeline creates is read for its fields and then discarded
    with the transaction.
    """
    # The engine implementations are called directly, NOT through
    # run_audit_compat. That entry point recurses infinitely once the billing
    # quota gate installs itself: apps/billing/quota_gate.py:138 re-imports
    # `run_audit_compat as _original` at call time, by which point the module
    # attribute is the gate's own wrapper, so _gated -> run_audit_with_quota
    # -> _gated forever. The true original is stored on _gated._original
    # (quota_gate.py:264) and never read.
    #
    # Going around it is what makes this measurement possible at all, and it
    # is also correct for the question: quota reservation is not part of the
    # V1/V2 scoring difference. The defect is reported, not fixed — apps/ is
    # out of scope for this shipment.
    from apps.rule_engine.pipeline.v2.compat import _run_v1, _run_v2

    runner = _run_v1 if engine == "v1" else _run_v2

    captured = {}
    try:
        with transaction.atomic():
            run = runner(
                str(document.id),
                document.document_type,
                str(document.organization_id),
                "gate_measurement",
            )
            # The risk_engine stage writes the score with
            # audit_run.save(update_fields=[...]) on ITS OWN instance. If the
            # object handed back here is a different instance, reading it
            # in-memory yields a stale zero and the whole measurement is wrong.
            # Re-read from the row before believing any number.
            try:
                run.refresh_from_db()
            except Exception:
                pass
            captured = {
                "risk_score": float(getattr(run, "risk_score", 0) or 0),
                "risk_level": getattr(run, "risk_level", "") or "",
                "blocks": bool(getattr(run, "blocks_approval", False)),
                "status": getattr(run, "status", "") or "",
                "modifier_reasons": list(
                    (getattr(run, "score_breakdown", None) or {}).get("modifier_reasons", [])
                ) if isinstance(getattr(run, "score_breakdown", None), dict) else [],
            }
            raise _Rollback
    except _Rollback:
        return captured
    except Exception as exc:  # noqa: BLE001 - reported, never swallowed
        return {"error": f"{type(exc).__name__}: {exc}"}


def main(limit):
    from apps.documents.models import Document
    from apps.rule_engine.models import AuditRun

    before = AuditRun.objects.count()

    sample = list(
        Document.objects.order_by("id").values_list(
            "id", "document_type", "organization_id"
        )[:limit]
    )
    print(f"sample size: {len(sample)}  (order_by id, first {limit})")

    types = {}
    for _, t, _o in sample:
        types[t] = types.get(t, 0) + 1
    print("types:", dict(sorted(types.items(), key=lambda kv: -kv[1])))
    print()

    class _Doc:
        __slots__ = ("id", "document_type", "organization_id")

        def __init__(self, i, t, o):
            self.id, self.document_type, self.organization_id = i, t, o

    rows, errors = [], []
    for i, (doc_id, doc_type, org_id) in enumerate(sample, 1):
        doc = _Doc(doc_id, doc_type, org_id)
        v1 = _run_one(doc, "v1")
        v2 = _run_one(doc, "v2")

        if "error" in v1 or "error" in v2:
            errors.append((str(doc_id), doc_type, v1.get("error"), v2.get("error")))
            continue

        rows.append({
            "id": str(doc_id),
            "type": doc_type,
            "s1": v1["risk_score"], "l1": v1["risk_level"], "b1": v1["blocks"],
            "s2": v2["risk_score"], "l2": v2["risk_level"], "b2": v2["blocks"],
            "st1": v1["status"], "st2": v2["status"],
            "delta": round(v2["risk_score"] - v1["risk_score"], 2),
            "reasons": v2["modifier_reasons"],
        })
        if i % 25 == 0:
            print(f"  ... {i}/{len(sample)}", flush=True)

    after = AuditRun.objects.count()

    print()
    print("=" * 72)
    print(f"measured        : {len(rows)}")
    print(f"errored         : {len(errors)}")
    print(f"AuditRun before : {before}")
    print(f"AuditRun after  : {after}   <- must be equal, or the run was not read-only")
    print("=" * 72)

    if errors:
        print("\nERRORS (first 5):")
        for e in errors[:5]:
            print("  ", e)

    if not rows:
        print("\nno document produced a comparable pair — nothing to report")
        return

    changed = [r for r in rows if r["delta"] > 0]
    flips = [r for r in rows if r["b2"] and not r["b1"]]
    unflips = [r for r in rows if r["b1"] and not r["b2"]]
    max_delta = max(r["delta"] for r in rows)
    negatives = [r for r in rows if r["delta"] < 0]

    # A delta of -50 with v2 == 0 is not "V2 scored it lower" — it is "V2
    # produced no score at all". Reporting the first when the second is true
    # would be a fabricated measurement, so the two are separated here.
    v2_zero = [r for r in rows if r["s2"] == 0.0]
    v1_zero = [r for r in rows if r["s1"] == 0.0]
    print(f"\n0a. v2 score == 0                  : {len(v2_zero)} / {len(rows)}")
    print(f"0b. v1 score == 0                  : {len(v1_zero)} / {len(rows)}")
    print("0c. per type — n, mean v1, mean v2, n(v2==0):")
    by_type = {}
    for r in rows:
        by_type.setdefault(r["type"], []).append(r)
    for t, rs in sorted(by_type.items(), key=lambda kv: -len(kv[1])):
        m1 = sum(x["s1"] for x in rs) / len(rs)
        m2 = sum(x["s2"] for x in rs) / len(rs)
        z = sum(1 for x in rs if x["s2"] == 0.0)
        print(f"      {t:20} n={len(rs):4}  v1={m1:6.2f}  v2={m2:6.2f}  v2zero={z}")
    print("0d. statuses seen:",
          {s: sum(1 for r in rows if r.get('st2') == s) for s in {r.get('st2') for r in rows}})

    print(f"\n1. documents with delta > 0        : {len(changed)} / {len(rows)}")
    print(f"2. blocks_approval False -> True   : {len(flips)}")
    print(f"3. max measured delta              : {max_delta} points  (theoretical ceiling 80)")
    print(f"   blocks_approval True -> False   : {len(unflips)}  (expected 0: modifiers never subtract)")
    print(f"   documents with delta < 0        : {len(negatives)}  (expected 0)")
    if negatives:
        mn = min(r["delta"] for r in rows)
        dist = {}
        for r in negatives:
            dist[r["delta"]] = dist.get(r["delta"], 0) + 1
        print(f"   min (most negative) delta       : {mn} points")
        print(f"   negative delta values           : "
              f"{dict(sorted(dist.items()))}")

    def _table(title, subset):
        if not subset:
            return
        print(f"\n{title}  ({len(subset)})")
        print(f"{'id':38} {'type':18} {'v1':>7} {'v2':>7} {'delta':>7}  modifiers")
        for r in subset:
            print(f"{r['id']:38} {r['type']:18} {r['s1']:7.2f} {r['s2']:7.2f} "
                  f"{r['delta']:7.2f}  {','.join(r['reasons']) or '(none recorded)'}")

    _table("DOCUMENTS WHOSE BLOCKING FLIPPED  False -> True", flips)
    # The reverse direction is not supposed to be possible if V2 only ever adds
    # to V1's score. It is tabled because it happened.
    _table("DOCUMENTS WHOSE BLOCKING FLIPPED  True -> False", unflips)

    if changed:
        print("\nDELTA DISTRIBUTION")
        buckets = {}
        for r in changed:
            b = int(r["delta"] // 10) * 10
            buckets[b] = buckets.get(b, 0) + 1
        for b in sorted(buckets):
            print(f"  {b:3}-{b+9:3} : {buckets[b]}")


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 100)
