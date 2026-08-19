"""Backfill bilingual AI fields on document-type models.

Reads the legacy single-language `ai_summary` / `ai_recommendations` columns,
detects whether the existing text is Arabic or English by character heuristic,
copies it into the matching `_ar` / `_en` column, and translates it into the
opposite language via OpenAI.

Idempotent — rows whose `_ar` and `_en` are both non-empty are skipped, so
the command can be re-run safely.

Usage:
  python manage.py backfill_ai_translations --dry-run
  python manage.py backfill_ai_translations
  python manage.py backfill_ai_translations --models invoice,purchase_order
  python manage.py backfill_ai_translations --limit 100
"""
from __future__ import annotations

import json
import re
from typing import Iterable

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction


# Same dispatch table as ai_insights_service — keep them in sync.
DOC_MODELS: dict[str, str] = {
    "invoice":          "apps.invoices.models:Invoice",
    "purchase_order":   "apps.documents.typed_models:PurchaseOrder",
    "bank_statement":   "apps.documents.typed_models:BankStatement",
    "payroll":          "apps.documents.typed_models:PayrollSheet",
    "expense_report":   "apps.documents.typed_models:ExpenseReport",
    "vat_return":       "apps.documents.typed_models:VATReturn",
    "fixed_asset":      "apps.documents.typed_models:FixedAsset",
    "sales_receipt":    "apps.documents.typed_models:SalesReceipt",
}

_AR_RANGE = re.compile(r"[؀-ۿ]")


def _resolve(path: str):
    mod_path, cls = path.split(":")
    import importlib
    return getattr(importlib.import_module(mod_path), cls)


def _detect_lang(text: str) -> str:
    """Crude detector — 'ar' if any Arabic letters present, else 'en'."""
    if not text:
        return ""
    return "ar" if _AR_RANGE.search(text) else "en"


def _normalize_recommendations(value) -> list[str]:
    """Return a flat list of strings from whatever shape the column holds."""
    if value is None:
        return []
    if isinstance(value, str):
        s = value.strip()
        return [s] if s else []
    if isinstance(value, (list, tuple)):
        out = []
        for item in value:
            if isinstance(item, str) and item.strip():
                out.append(item.strip())
            elif isinstance(item, dict):
                txt = item.get("text") or item.get("recommendation") or item.get("message")
                if isinstance(txt, str) and txt.strip():
                    out.append(txt.strip())
        return out
    return []


class Command(BaseCommand):
    help = "Backfill ai_summary_ar/_en + ai_recommendations_ar/_en from legacy single-language columns."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true",
                            help="Count what would change; do not write or call OpenAI.")
        parser.add_argument("--models", default="",
                            help="Comma-separated subset (e.g. 'invoice,purchase_order'). Default: all.")
        parser.add_argument("--limit", type=int, default=0,
                            help="Process at most this many rows per model. 0 = no limit.")
        parser.add_argument("--openai-model", default="gpt-4o-mini",
                            help="OpenAI model to use for translation. Default: gpt-4o-mini.")
        parser.add_argument("--batch-size", type=int, default=20,
                            help="DB write batch size. Default: 20.")

    # ── translation ───────────────────────────────────────────────────────────

    def _make_translator(self, model_name: str):
        api_key = getattr(settings, "OPENAI_API_KEY", "") or ""
        if not api_key:
            raise CommandError(
                "OPENAI_API_KEY not configured. Set it in settings or environment."
            )
        def translate(document, text: str, target_lang: str) -> str:
            if not text or not text.strip():
                return ""
            organization = getattr(document, "organization", None)
            if organization is None:
                self.stderr.write(self.style.WARNING(
                    f"  skipped unowned {document.__class__.__name__}:{document.pk}"
                ))
                return ""
            target_label = "Arabic" if target_lang == "ar" else "English"
            try:
                from core.ai.gateway import chat_completion

                resp = chat_completion(
                    organization=organization,
                    operation="translation",
                    document_id=document.pk,
                    model=model_name,
                    messages=[
                        {"role": "system",
                         "content": (
                            f"You translate financial-audit text into {target_label}. "
                            "Preserve numbers, codes, and identifiers exactly. "
                            "Reply with the translation only, no preamble."
                         )},
                        {"role": "user", "content": text},
                    ],
                    temperature=0.1,
                    max_tokens=600,
                )
                return (resp.choices[0].message.content or "").strip()
            except Exception as exc:
                self.stderr.write(self.style.WARNING(f"  translate failed: {exc}"))
                return ""

        return translate

    # ── per-model worker ──────────────────────────────────────────────────────

    def _process_model(self, key: str, dotted: str, *, dry_run: bool, limit: int,
                       translate, batch_size: int) -> dict:
        Model = _resolve(dotted)
        field_names = {f.name for f in Model._meta.get_fields()}

        required = {"ai_summary_ar", "ai_summary_en",
                    "ai_recommendations_ar", "ai_recommendations_en"}
        if not required.issubset(field_names):
            self.stdout.write(f"  [{key}] missing bilingual columns — skipped (run migrations).")
            return {"skipped": True}

        qs = Model.objects.exclude(ai_summary="").select_related("organization").only(
            "id", "organization", "ai_summary", "ai_summary_ar", "ai_summary_en",
            "ai_recommendations", "ai_recommendations_ar", "ai_recommendations_en",
        )
        total = qs.count()
        if limit:
            qs = qs[:limit]

        stats = {
            "total":            total,
            "skipped_complete": 0,
            "summaries_filled": 0,
            "summaries_translated": 0,
            "recs_filled":      0,
            "recs_translated":  0,
            "errors":           0,
        }

        pending = []
        for doc in qs.iterator(chunk_size=200):
            existing_ar = (doc.ai_summary_ar or "").strip()
            existing_en = (doc.ai_summary_en or "").strip()
            recs_ar     = _normalize_recommendations(doc.ai_recommendations_ar)
            recs_en     = _normalize_recommendations(doc.ai_recommendations_en)

            # Already-bilingual rows get skipped.
            summary_complete = bool(existing_ar) and bool(existing_en)
            recs_complete    = bool(recs_ar) and bool(recs_en)
            legacy_recs      = _normalize_recommendations(doc.ai_recommendations)
            if summary_complete and (recs_complete or not legacy_recs):
                stats["skipped_complete"] += 1
                continue

            updates = {}

            # Summary
            legacy_summary = (doc.ai_summary or "").strip()
            if legacy_summary:
                src_lang = _detect_lang(legacy_summary)
                if src_lang == "ar" and not existing_ar:
                    updates["ai_summary_ar"] = legacy_summary
                    stats["summaries_filled"] += 1
                elif src_lang == "en" and not existing_en:
                    updates["ai_summary_en"] = legacy_summary
                    stats["summaries_filled"] += 1

                target_lang = "en" if src_lang == "ar" else "ar"
                target_field = f"ai_summary_{target_lang}"
                if not (getattr(doc, target_field, "") or "").strip():
                    if dry_run:
                        stats["summaries_translated"] += 1
                    else:
                        translated = translate(doc, legacy_summary, target_lang)
                        if translated:
                            updates[target_field] = translated
                            stats["summaries_translated"] += 1
                        else:
                            stats["errors"] += 1

            # Recommendations
            if legacy_recs:
                # Detect source language by sampling first non-empty recommendation
                src_lang = _detect_lang(legacy_recs[0])
                src_field = f"ai_recommendations_{src_lang}"
                tgt_lang = "en" if src_lang == "ar" else "ar"
                tgt_field = f"ai_recommendations_{tgt_lang}"

                if not getattr(doc, src_field):
                    updates[src_field] = legacy_recs
                    stats["recs_filled"] += 1

                if not getattr(doc, tgt_field):
                    if dry_run:
                        stats["recs_translated"] += 1
                    else:
                        joined = "\n".join(f"- {r}" for r in legacy_recs)
                        translated_block = translate(doc, joined, tgt_lang)
                        if translated_block:
                            translated_items = [
                                line.lstrip("- •*").strip()
                                for line in translated_block.splitlines()
                                if line.strip()
                            ]
                            if translated_items:
                                updates[tgt_field] = translated_items
                                stats["recs_translated"] += 1
                            else:
                                stats["errors"] += 1
                        else:
                            stats["errors"] += 1

            if updates and not dry_run:
                pending.append((doc.pk, updates))
                if len(pending) >= batch_size:
                    self._flush(Model, pending)
                    pending = []

        if pending and not dry_run:
            self._flush(Model, pending)

        return stats

    @staticmethod
    def _flush(Model, pending: list[tuple]):
        with transaction.atomic():
            for pk, updates in pending:
                Model.objects.filter(pk=pk).update(**updates)

    # ── command entry ─────────────────────────────────────────────────────────

    def handle(self, *args, **opts):
        dry_run    = opts["dry_run"]
        models_arg = (opts["models"] or "").strip()
        limit      = opts["limit"]
        batch_size = opts["batch_size"]
        oai_model  = opts["openai_model"]

        selected = (
            [k.strip() for k in models_arg.split(",") if k.strip()]
            if models_arg else list(DOC_MODELS.keys())
        )
        unknown = [k for k in selected if k not in DOC_MODELS]
        if unknown:
            raise CommandError(f"Unknown model keys: {', '.join(unknown)}. "
                               f"Allowed: {', '.join(DOC_MODELS)}")

        translate = (lambda text, target: "") if dry_run else self._make_translator(oai_model)

        if dry_run:
            self.stdout.write(self.style.WARNING("DRY RUN — no DB writes, no OpenAI calls."))
        else:
            self.stdout.write(self.style.NOTICE(f"Live run with OpenAI model: {oai_model}"))

        grand = {"summaries_filled": 0, "summaries_translated": 0,
                 "recs_filled": 0, "recs_translated": 0, "skipped_complete": 0, "errors": 0}

        for key in selected:
            self.stdout.write(f"\n=== {key} ===")
            try:
                stats = self._process_model(
                    key, DOC_MODELS[key],
                    dry_run=dry_run, limit=limit,
                    translate=translate, batch_size=batch_size,
                )
            except Exception as exc:
                self.stderr.write(self.style.ERROR(f"  {key}: {exc}"))
                continue
            if stats.get("skipped"):
                continue
            self.stdout.write(
                f"  rows={stats['total']}  "
                f"skipped={stats['skipped_complete']}  "
                f"summaries: filled={stats['summaries_filled']} translated={stats['summaries_translated']}  "
                f"recs: filled={stats['recs_filled']} translated={stats['recs_translated']}  "
                f"errors={stats['errors']}"
            )
            for k in grand:
                grand[k] += stats.get(k, 0)

        self.stdout.write("\n" + json.dumps(grand, indent=2))
