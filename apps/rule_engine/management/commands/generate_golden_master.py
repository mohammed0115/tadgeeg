"""Pin the pipeline's current verdicts so a refactor has to prove it changed nothing.

    same input + cleaner process = the same output, exactly

That is the acceptance test for every refactoring step that follows. A fixture
of current verdicts turns it from a claim into a comparison.

WHAT THIS SAMPLES, AND WHY IT IS NOT `Document`

The pipeline's `document_id` is the TYPED record's primary key, not a
`Document` row id. Every normalizer looks the record up that way —
`PurchaseOrder.objects.get(id=document_id)`, `Invoice.objects.get(id=...)` and
so on for all 21 registered types — and production agrees: documents/signals.py
passes `str(instance.pk)` from the typed instance.

The tool this replaces iterated `Document` rows and passed `Document.id`. Those
are different id spaces, so every lookup missed, every normalizer returned an
empty NormalizedDocument, and the resulting "zero difference between V1 and V2"
was the distance between two blanks. Sampling starts from the typed models here
for that reason, and tests/test_golden_master.py fails outright if the fixture
comes back without rule results — the check that would have caught it.

READ-ONLY

Both pipelines create and update an AuditRun; neither offers a dry run. Each
document is therefore processed inside a transaction that is rolled back, and
the command prints the AuditRun count before and after rather than asserting
its own cleanliness quietly.

Usage:
    python manage.py generate_golden_master --seed 42 --limit 50
"""

import hashlib
import json
import random
from pathlib import Path

from django.core.management.base import BaseCommand
from django.db import transaction

DEFAULT_OUT = "tests/fixtures/golden_master.json"


class _Rollback(Exception):
    """Unwinds the transaction once a run has been read."""


def _typed_models():
    """{document_type: model} for every registered normalizer.

    Derived from the normalizer registry and each normalizer's own lookup, so a
    new document type joins the golden master by being registered — not by
    someone remembering to add it to a list here. Hand-maintained lists are the
    defect this project keeps rediscovering.
    """
    import inspect
    import re

    from django.apps import apps as django_apps

    from apps.rule_engine.normalizers import DocumentNormalizerFactory

    registry = (getattr(DocumentNormalizerFactory, "_registry", None)
                or getattr(DocumentNormalizerFactory, "registry", None) or {})

    by_name = {m.__name__: m for m in django_apps.get_models()}
    out = {}
    for doc_type, normalizer in registry.items():
        try:
            source = inspect.getsource(normalizer.normalize)
        except (OSError, TypeError):
            continue
        match = re.search(r"([A-Z][A-Za-z0-9_]+)\.objects\.", source)
        if match and match.group(1) in by_name:
            out[doc_type] = by_name[match.group(1)]
    return out


def _run(document_id, document_type, organization_id):
    """Run the pipeline once and return its verdict; discard the AuditRun."""
    from django.conf import settings

    from apps.rule_engine.models import AuditResult
    from apps.rule_engine.pipeline.v2.compat import _run_v1, _run_v2

    # The engine is called directly rather than through run_audit_compat,
    # because the billing gate that wraps it reads `document_id` as a
    # Document primary key (quota_gate._resolve_document_and_org does
    # Document.objects.get(pk=document_id)) while every normalizer reads the
    # same argument as the TYPED record's key. Measured: over 500 rows each of
    # PurchaseOrder and FixedAsset, id == document_id zero times. The two
    # cannot both be satisfied by one value, and going through the gate here
    # returns Document.DoesNotExist for all 221 documents.
    #
    # That contradiction is reported, not fixed — apps/billing is out of scope
    # for this shipment. Skipping the gate is also correct for the fixture:
    # quota reservation is not part of the verdict being pinned.
    version = getattr(settings, "AUDIT_ENGINE_VERSION", "v2")
    runner = _run_v1 if version == "v1" else _run_v2

    captured = None
    try:
        with transaction.atomic():
            run = runner(
                str(document_id),
                document_type,
                str(organization_id),
                "golden_master",
            )
            # The risk_engine stage saves on its own instance, so the object
            # handed back here is stale and reads risk_score 0.00. Re-read the
            # row before believing any field a later stage writes.
            run.refresh_from_db()

            results = [
                {
                    "rule_code": r.rule_code,
                    "status": str(r.status),
                    "severity": str(r.applied_severity or ""),
                }
                for r in AuditResult.objects.filter(audit_run=run).order_by("rule_code")
            ]
            captured = {
                "engine_version": str(run.engine_version or ""),
                "risk_score": round(float(run.risk_score or 0), 2),
                "risk_level": str(run.risk_level or ""),
                "blocks_approval": bool(run.blocks_approval),
                "requires_manual_review": bool(run.requires_manual_review),
                "results": results,
            }
            raise _Rollback
    except _Rollback:
        return captured
    except Exception as exc:  # noqa: BLE001 — recorded, never swallowed
        return {"error": f"{type(exc).__name__}: {exc}"}


class Command(BaseCommand):
    help = "Record the pipeline's current verdicts as a golden-master fixture."

    def add_arguments(self, parser):
        parser.add_argument("--out", default=DEFAULT_OUT)
        parser.add_argument("--limit", type=int, default=50,
                            help="documents per type")
        parser.add_argument("--seed", type=int, required=True,
                            help="required: the fixture must be reproducible")

    def handle(self, *args, **options):
        from apps.rule_engine.models import AuditRun

        random.seed(options["seed"])          # fixed, though selection is by id
        before = AuditRun.objects.count()

        entries = []
        for doc_type, model in sorted(_typed_models().items()):
            fields = {f.name for f in model._meta.fields}
            if "organization" not in fields:
                continue
            # order_by("id"), never "?" — the sample must be the same on every
            # run or the fixture compares two different populations.
            rows = list(
                model.objects.order_by("id")
                .values_list("id", "organization_id")[:options["limit"]]
            )
            for doc_id, org_id in rows:
                if org_id is None:
                    continue
                verdict = _run(doc_id, doc_type, org_id)
                entry = {
                    "document_id": str(doc_id),
                    "document_type": doc_type,
                    "organization_id": str(org_id),
                }
                entry.update(verdict or {})
                entries.append(entry)
            if rows:
                self.stdout.write(f"  {doc_type:22} {len(rows)}")

        after = AuditRun.objects.count()

        entries.sort(key=lambda e: (e["document_type"], e["document_id"]))
        out = Path(options["out"])
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(
            json.dumps(entries, indent=2, sort_keys=True, ensure_ascii=False),
            encoding="utf-8",
        )

        digest = hashlib.sha256(out.read_bytes()).hexdigest()
        with_results = sum(1 for e in entries if e.get("results"))
        errored = sum(1 for e in entries if "error" in e)
        orgs = len({e["organization_id"] for e in entries})

        self.stdout.write("")
        self.stdout.write(f"documents      : {len(entries)}")
        self.stdout.write(f"with results   : {with_results}")
        self.stdout.write(f"errored        : {errored}")
        self.stdout.write(f"types          : {len({e['document_type'] for e in entries})}")
        self.stdout.write(f"organisations  : {orgs}")
        self.stdout.write(f"AuditRun before: {before}")
        self.stdout.write(f"AuditRun after : {after}"
                          f"{'   OK — read-only' if before == after else '   LEAK'}")
        self.stdout.write(f"sha256         : {digest}")

        if with_results == 0:
            self.stderr.write(
                "\nNo document produced a single rule result. The fixture would "
                "compare emptiness to emptiness — this is exactly the failure "
                "that invalidated the previous measurement tool."
            )
