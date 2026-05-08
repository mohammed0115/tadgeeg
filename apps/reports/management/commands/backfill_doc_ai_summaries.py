"""Backfill per-document AI insights for typed-doc models missing ai_summary.

Iterates the typed-doc models (PurchaseOrder, BankStatement, ...) for rows
whose `ai_summary` column is empty, pulls the OCR text from the linked
ExtractedData, and runs `AIAuditorService.audit()` to populate:

  - ai_summary
  - ai_recommendations  (list[str])
  - anomalies_found     (list[dict])

Idempotent — rows that already have any AI content are skipped, so the
command is safe to re-run. Use `--dry-run` to count what *would* be
processed without spending tokens.

Usage:
  python manage.py backfill_doc_ai_summaries --dry-run
  python manage.py backfill_doc_ai_summaries --doc-type purchase_order
  python manage.py backfill_doc_ai_summaries --organization-id <uuid>
  python manage.py backfill_doc_ai_summaries --limit 50
"""
from __future__ import annotations

import logging
from typing import Any

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

logger = logging.getLogger(__name__)


def _resolve(path: str):
    mod_path, cls = path.split(":")
    import importlib
    return getattr(importlib.import_module(mod_path), cls)


def _doc_text(typed_doc) -> str:
    """Return the OCR text for a row.

    Two storage shapes exist in this codebase:
      - Invoice has `raw_text` directly on the row (legacy schema).
      - Typed-doc models (PurchaseOrder, etc.) link to Document and the OCR
        text lives on Document.extracted_data.raw_text.
    """
    direct = getattr(typed_doc, "raw_text", None)
    if isinstance(direct, str) and direct.strip():
        return direct
    doc = getattr(typed_doc, "document", None)
    if doc is None:
        return ""
    extracted = getattr(doc, "extracted_data", None)
    return getattr(extracted, "raw_text", "") if extracted else ""


def _has_any_ai_content(typed_doc) -> bool:
    """True when any AI column is already populated (skip on backfill)."""
    summary = (getattr(typed_doc, "ai_summary", "") or "").strip()
    if summary:
        return True
    recs = getattr(typed_doc, "ai_recommendations", None)
    if isinstance(recs, (list, tuple)) and any(r for r in recs):
        return True
    if isinstance(recs, str) and recs.strip():
        return True
    anoms = getattr(typed_doc, "anomalies_found", None)
    if isinstance(anoms, (list, tuple)) and any(a for a in anoms):
        return True
    return False


def _coerce_recommendations(value: Any) -> list[str]:
    if not value:
        return []
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if isinstance(value, list):
        out: list[str] = []
        for item in value:
            if isinstance(item, str) and item.strip():
                out.append(item.strip())
            elif isinstance(item, dict):
                txt = item.get("text") or item.get("recommendation") or item.get("message")
                if isinstance(txt, str) and txt.strip():
                    out.append(txt.strip())
        return out
    return []


def _coerce_anomalies(value: Any) -> list[dict]:
    if not isinstance(value, list):
        return []
    out: list[dict] = []
    for item in value:
        if isinstance(item, dict):
            out.append(item)
        elif isinstance(item, str) and item.strip():
            out.append({"label": item.strip(), "severity": "medium"})
    return out


class Command(BaseCommand):
    help = "Backfill ai_summary / ai_recommendations / anomalies_found for typed docs."

    def add_arguments(self, parser):
        parser.add_argument("--doc-type", default="",
                            help="Limit to one type (e.g. purchase_order). Default: all in _AI_DOC_MAP.")
        parser.add_argument("--organization-id", default="",
                            help="Limit to one organization UUID.")
        parser.add_argument("--limit", type=int, default=0,
                            help="Stop after processing this many rows total. 0 = no limit.")
        parser.add_argument("--dry-run", action="store_true",
                            help="Count what would change; do not call OpenAI or write to DB.")
        parser.add_argument("--language", default="ar",
                            help="Language hint passed to the AI auditor (ar or en). Default: ar.")
        parser.add_argument("--skip-empty-text", action="store_true", default=True,
                            help="Skip docs whose extracted text is empty/missing. Default: on.")

    def handle(self, *args, **opts):
        from apps.reports.services.ai_insights_service import _AI_DOC_MAP

        only_type = (opts["doc_type"] or "").strip()
        org_id = (opts["organization_id"] or "").strip()
        limit = int(opts["limit"] or 0)
        language = opts["language"]
        dry = opts["dry_run"]

        if only_type and only_type not in _AI_DOC_MAP:
            raise CommandError(
                f"Unknown --doc-type {only_type!r}. Valid: {sorted(_AI_DOC_MAP)}"
            )

        # Lazy-import the auditor so --dry-run works without an API key.
        auditor = None
        if not dry:
            from apps.auditing.services.ai_auditor_service import AIAuditorService
            auditor = AIAuditorService()

        targets = (
            {only_type: _AI_DOC_MAP[only_type]}
            if only_type else _AI_DOC_MAP
        )

        grand_total = 0
        grand_updated = 0
        grand_skipped = 0
        grand_no_text = 0
        grand_errored = 0

        for doc_type, (model_path, _num_field) in targets.items():
            if limit and grand_updated >= limit:
                break

            try:
                Model = _resolve(model_path)
            except Exception as exc:
                self.stdout.write(self.style.WARNING(
                    f"  [{doc_type}] could not resolve {model_path}: {exc}"
                ))
                continue

            qs = Model.objects.all()
            if org_id:
                qs = qs.filter(organization_id=org_id)

            type_total = qs.count()
            type_updated = 0
            type_skipped = 0
            type_no_text = 0
            type_errored = 0

            self.stdout.write(self.style.NOTICE(
                f"\n[{doc_type}] {type_total} candidate row(s)"
            ))

            # Only typed-doc models go through Document.extracted_data; the
            # Invoice model carries `raw_text` on the row itself.
            field_names = {f.name for f in Model._meta.get_fields()}
            if "document" in field_names:
                qs = qs.select_related("document__extracted_data")
            for row in qs.iterator(chunk_size=50):
                if limit and grand_updated >= limit:
                    break
                if _has_any_ai_content(row):
                    type_skipped += 1
                    continue

                text = _doc_text(row)
                if not text or not text.strip():
                    type_no_text += 1
                    continue

                if dry:
                    type_updated += 1
                    grand_updated += 1
                    continue

                try:
                    result = auditor.audit(
                        text, doc_type_hint=doc_type, language=language
                    ) or {}
                    if result.get("_error"):
                        type_errored += 1
                        continue

                    summary = (result.get("executive_summary") or "").strip()
                    recs = _coerce_recommendations(result.get("recommendations"))
                    anoms = _coerce_anomalies(result.get("anomalies"))

                    if not (summary or recs or anoms):
                        type_skipped += 1
                        continue

                    with transaction.atomic():
                        if summary:
                            row.ai_summary = summary
                            # Populate the language-specific column too so the
                            # report renders without re-translation.
                            if language == "ar" and hasattr(row, "ai_summary_ar"):
                                row.ai_summary_ar = summary
                            elif language == "en" and hasattr(row, "ai_summary_en"):
                                row.ai_summary_en = summary
                        if recs:
                            row.ai_recommendations = recs
                            if language == "ar" and hasattr(row, "ai_recommendations_ar"):
                                row.ai_recommendations_ar = recs
                            elif language == "en" and hasattr(row, "ai_recommendations_en"):
                                row.ai_recommendations_en = recs
                        if anoms:
                            row.anomalies_found = anoms
                        row.save(update_fields=[
                            f for f in (
                                "ai_summary", "ai_summary_ar", "ai_summary_en",
                                "ai_recommendations", "ai_recommendations_ar", "ai_recommendations_en",
                                "anomalies_found",
                            ) if hasattr(row, f)
                        ])
                    type_updated += 1
                    grand_updated += 1
                except Exception as exc:
                    logger.exception("backfill failed for %s id=%s", doc_type, row.pk)
                    type_errored += 1

            grand_total += type_total
            grand_skipped += type_skipped
            grand_no_text += type_no_text
            grand_errored += type_errored

            self.stdout.write(
                f"  -> updated={type_updated}  skipped(has_ai)={type_skipped}  "
                f"no_text={type_no_text}  errors={type_errored}"
            )

        verb = "would update" if dry else "updated"
        self.stdout.write(self.style.SUCCESS(
            f"\nDone. Across {len(targets)} type(s): {verb}={grand_updated}  "
            f"skipped={grand_skipped}  no_text={grand_no_text}  errors={grand_errored}"
        ))
