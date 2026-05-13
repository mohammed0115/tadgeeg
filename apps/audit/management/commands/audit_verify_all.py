"""``manage.py audit_verify_all`` — single-command DB integrity self-test.

Runs every integrity check the platform has, in one place, so an
auditor or SRE can answer "is the data layer healthy?" with one shell
command. Counts:

  1. Hash-chain verify across every (HashChainMixin subclass × org).
  2. Document content-hash verify (re-read each file, compare to
     ``Document.file_sha256``).
  3. Balanced-entry verify (every POSTED JournalEntry has Σdebits == Σcredits).
  4. Orphaned-FK scan (rows whose org FK points to a deleted org).

Exits 1 if any check fails so it slots cleanly into CI/health probes.

Usage:
    manage.py audit_verify_all                   # full run
    manage.py audit_verify_all --skip files      # don't re-hash documents
    manage.py audit_verify_all --json            # machine-readable output
"""
from __future__ import annotations

import json
import logging
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db.models import Q, Sum

logger = logging.getLogger("audit.verify_all")


class Command(BaseCommand):
    help = "Run every DB-integrity check the platform has — single chokepoint."

    def add_arguments(self, parser):
        parser.add_argument("--skip", action="append", default=[],
                            choices=("chains", "files", "ledger", "orphans"),
                            help="skip a check (can repeat)")
        parser.add_argument("--json", action="store_true",
                            help="emit JSON instead of text")

    def handle(self, *args, **opts):
        skip = set(opts["skip"])
        report = {
            "chains":  self._check_chains() if "chains" not in skip else _skipped(),
            "files":   self._check_files()  if "files"  not in skip else _skipped(),
            "ledger":  self._check_ledger() if "ledger" not in skip else _skipped(),
            "orphans": self._check_orphans() if "orphans" not in skip else _skipped(),
        }
        ok = all(r.get("ok", True) for r in report.values())

        if opts["json"]:
            self.stdout.write(json.dumps({"ok": ok, "report": report},
                                         indent=2, sort_keys=True))
        else:
            for name, r in report.items():
                self.stdout.write(f"\n── {name} ───────")
                for k, v in r.items():
                    self.stdout.write(f"  {k:>14}: {v}")
            self.stdout.write(self.style.SUCCESS("\nOK") if ok
                              else self.style.ERROR("\nFAIL"))
        if not ok:
            raise SystemExit(1)

    # ─── checks ──────────────────────────────────────────────────────────────

    def _check_chains(self) -> dict:
        try:
            from apps.audit.tasks_chain_verify import verify_chains_nightly
        except ImportError as e:
            return {"ok": False, "error": f"chain-verify task missing: {e}"}
        result = verify_chains_nightly()
        return {
            "ok":       result.get("broken", 0) == 0,
            "checked":  result.get("checked", 0),
            "intact":   result.get("intact", 0),
            "broken":   result.get("broken", 0),
            "breaks":   result.get("breaks", []),
        }

    def _check_files(self) -> dict:
        try:
            from apps.documents.models import Document
            from apps.documents.services.integrity import (
                verify_document_integrity,
            )
        except ImportError as e:
            return {"ok": False, "error": str(e)}
        checked = ok = tampered = errors = 0
        bad: list[str] = []
        for doc in Document.objects.exclude(file_sha256=""):
            checked += 1
            try:
                status = verify_document_integrity(doc)
                if status.tampered:
                    tampered += 1
                    bad.append(str(doc.pk))
                else:
                    ok += 1
            except Exception as exc:        # pragma: no cover
                errors += 1
                logger.warning("integrity check failed for %s: %s", doc.pk, exc)
        return {
            "ok":       tampered == 0 and errors == 0,
            "checked":  checked,
            "intact":   ok,
            "tampered": tampered,
            "errors":   errors,
            "first_tampered": bad[:5],
        }

    def _check_ledger(self) -> dict:
        try:
            from apps.ledger.models import JournalEntry, JournalLine
        except ImportError as e:
            return {"ok": False, "error": str(e)}
        unbalanced: list[str] = []
        posted = JournalEntry.objects.filter(
            status=JournalEntry.Status.POSTED,
        )
        for entry in posted.iterator(chunk_size=200):
            agg = JournalLine.objects.filter(entry=entry).aggregate(
                d=Sum("debit"), c=Sum("credit"),
            )
            d = Decimal(str(agg["d"] or 0))
            c = Decimal(str(agg["c"] or 0))
            if d != c:
                unbalanced.append(entry.entry_number)
                if len(unbalanced) >= 10:
                    break
        return {
            "ok":         not unbalanced,
            "checked":    posted.count(),
            "unbalanced": len(unbalanced),
            "samples":    unbalanced[:5],
        }

    def _check_orphans(self) -> dict:
        """Spot-check models for FK pointing to a deleted parent that
        ``on_delete=CASCADE`` should have removed but didn't (DB drift)."""
        try:
            from apps.authentication.models import Organization
            from apps.invoices.models import Invoice
        except ImportError as e:
            return {"ok": False, "error": str(e)}
        valid_orgs = set(Organization.objects.values_list("pk", flat=True))
        orphan_invoices = Invoice.objects.exclude(
            organization_id__in=valid_orgs,
        ).count()
        return {
            "ok":             orphan_invoices == 0,
            "orphan_invoices": orphan_invoices,
        }


def _skipped() -> dict:
    return {"ok": True, "skipped": True}
