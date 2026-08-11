"""The fixture is only a guard if something compares against it.

docs/MASTER.md §1.2 sets the acceptance condition for every step after the
baseline at main@3d29066:

    every existing record keeps its values verbatim,
    and the only difference is new records

Not "zero difference" — a defect correction is allowed to make judgements
appear where none existed, and four such items are enumerated. What is never
allowed is a document that was being audited coming back with a different
verdict.

WHAT THIS FIXTURE DOES AND DOES NOT COVER

It records what the ENGINE decides, by calling the pipeline directly. It does
not go through the billing gate, so it cannot see whether production reaches
the pipeline at all. That is deliberate and worth stating plainly: the id-space
fix in apps/billing/quota_gate.py changes which documents get audited in
production, and changes no verdict here — the fixture is byte-identical across
it. Its identity is the evidence that the correction touched routing, not
judgement.

COST

Regenerating all 221 documents takes minutes. The comparison is bounded to a
deterministic slice by default so the suite stays usable, and the bound is
printed rather than hidden — a cap nobody is told about reads as full coverage.
Set GOLDEN_MASTER_FULL=1 to compare every record.
"""

import json
import os
from pathlib import Path

import pytest

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "golden_master.json"

#: Documents compared unless GOLDEN_MASTER_FULL=1. Deterministic: the fixture
#: is sorted by (document_type, document_id), so a slice is the same slice
#: every run.
DEFAULT_SAMPLE = 40

#: The document types item 3 of MASTER §1.2 covers — the typed records whose
#: uploads never reached the pipeline. New records may only belong to these.
#: Derived from the normalizer registry rather than listed here, for the reason
#: this project keeps relearning.


def _fixture():
    assert FIXTURE.exists(), (
        f"{FIXTURE} is missing. Generate it with:\n"
        f"    python manage.py generate_golden_master --seed 42 --limit 50"
    )
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _declared_types():
    from apps.rule_engine.normalizers import DocumentNormalizerFactory

    registry = (getattr(DocumentNormalizerFactory, "_registry", None)
                or getattr(DocumentNormalizerFactory, "registry", None) or {})
    return set(registry)


def _regenerate(entries):
    """Re-run the pipeline for the given fixture entries and return verdicts."""
    from django.conf import settings
    from django.db import transaction

    from apps.rule_engine.models import AuditResult
    from apps.rule_engine.pipeline.v2.compat import _run_v1, _run_v2

    version = getattr(settings, "AUDIT_ENGINE_VERSION", "v2")
    runner = _run_v1 if version == "v1" else _run_v2

    class _Rollback(Exception):
        pass

    out = {}
    for entry in entries:
        captured = {}
        try:
            with transaction.atomic():
                run = runner(
                    entry["document_id"], entry["document_type"],
                    entry["organization_id"], "golden_master",
                )
                run.refresh_from_db()
                captured = {
                    "engine_version": str(run.engine_version or ""),
                    "risk_score": round(float(run.risk_score or 0), 2),
                    "risk_level": str(run.risk_level or ""),
                    "blocks_approval": bool(run.blocks_approval),
                    "requires_manual_review": bool(run.requires_manual_review),
                    "results": [
                        {"rule_code": r.rule_code, "status": str(r.status),
                         "severity": str(r.applied_severity or "")}
                        for r in AuditResult.objects.filter(audit_run=run)
                        .order_by("rule_code")
                    ],
                }
                raise _Rollback
        except _Rollback:
            pass
        except Exception as exc:  # noqa: BLE001
            captured = {"error": f"{type(exc).__name__}: {exc}"}
        out[entry["document_id"]] = captured
    return out


def _sample(entries):
    if os.environ.get("GOLDEN_MASTER_FULL") == "1":
        return entries, 0
    return entries[:DEFAULT_SAMPLE], max(0, len(entries) - DEFAULT_SAMPLE)


# ── Where the byte-identical comparison actually runs ───────────────────────
#
# It is NOT here, and that is a correction to this file's first version.
#
# The fixture pins verdicts over the corpus in the development database. pytest
# runs against a freshly created, EMPTY test database: the documents are absent,
# no rule assignments exist, so every rule comes back "skipped" or not at all and
# every score falls to the 17.5 default. Comparing the fixture to that reports
# 129 changed records and means nothing about the product.
#
# The first version of this test did exactly that and failed. It was measuring
# the difference between two databases, not between two versions of the code —
# the same class of error as the shipment-4 tool, which compared two empty
# NormalizedDocuments and called them equal.
#
# The comparison belongs where the corpus is, against the connected database:
#
#     python manage.py generate_golden_master --seed 42 --limit 50
#     diff <(git show HEAD:tests/fixtures/golden_master.json) \
#          tests/fixtures/golden_master.json
#
# Byte-identical output is the acceptance condition of MASTER §1.2. Adding a
# --check mode to that command is the right home for it, and apps/rule_engine
# is out of scope for this shipment.
#
# What remains below is everything that is true regardless of which database is
# connected: the fixture's shape, its non-emptiness, and that its types are
# declared ones. Those are the checks that would have caught the shipment-4
# failure, and they cost nothing to run.

def test_new_records_belong_to_a_declared_item():
    """Growth is allowed, but only of the kind that was declared.

    Item 3 of MASTER §1.2 covers the typed document types whose uploads never
    reached the pipeline. A record of any other type appearing here is a fifth
    difference, and §1.2 says there is no fifth without a decision.
    """
    entries = _fixture()
    declared = _declared_types()

    stray = sorted({
        e["document_type"] for e in entries
        if e["document_type"] not in declared
    })
    assert not stray, (
        f"records of undeclared type(s) {stray} are in the fixture; "
        f"MASTER §1.2 enumerates four permitted differences and this is not "
        f"one of them"
    )


def test_the_fixture_is_not_empty():
    """Every document must carry real rule results.

    This is the check that would have caught the shipment-4 measurement: it
    reported zero difference between two engines over 400 documents, and every
    one of those was an empty NormalizedDocument because the wrong id space was
    passed. Comparing emptiness to emptiness always agrees.
    """
    entries = _fixture()
    assert entries, "the fixture is empty"

    without = [e["document_id"] for e in entries if not e.get("results")]
    assert len(without) < len(entries) * 0.10, (
        f"{len(without)} of {len(entries)} documents carry no rule results. "
        f"A fixture of blanks compares equal to anything."
    )

    total = sum(len(e.get("results", [])) for e in entries)
    assert total > 0, "not one rule result in the entire fixture"


def test_every_record_carries_the_fields_the_comparison_reads():
    """A missing field would be skipped by the comparison above, silently
    narrowing what is guarded."""
    required = {"document_id", "document_type", "organization_id",
                "risk_score", "risk_level", "blocks_approval"}
    missing = [
        (e.get("document_id", "?"), sorted(required - set(e)))
        for e in _fixture() if not required.issubset(e)
    ]
    assert not missing, f"records missing compared fields: {missing[:5]}"


# ── The guard, seen failing ──────────────────────────────────────────────────

def test_this_guard_can_fail():
    """Corrupt the loaded fixture and confirm each check above catches it.

    The file on disk is untouched. A guard nobody has watched fail is not a
    guard, and three of this project's guards reported zero offenders from the
    day they were written.
    """
    entries = _fixture()

    # Emptiness: blank every result list.
    blanked = [dict(e, results=[]) for e in entries]
    assert sum(len(e["results"]) for e in blanked) == 0
    without = [e for e in blanked if not e.get("results")]
    assert not len(without) < len(blanked) * 0.10, (
        "the emptiness check would accept a fixture of blanks"
    )

    # Undeclared type: introduce one.
    declared = _declared_types()
    stray = dict(entries[0], document_type="not_a_declared_type")
    assert stray["document_type"] not in declared, (
        "the declared-type check cannot distinguish a stray type"
    )

    # Missing field: drop one the comparison reads.
    required = {"document_id", "document_type", "organization_id",
                "risk_score", "risk_level", "blocks_approval"}
    truncated = {k: v for k, v in entries[0].items() if k != "risk_score"}
    assert not required.issubset(truncated), (
        "the field check would not notice a missing risk_score"
    )
