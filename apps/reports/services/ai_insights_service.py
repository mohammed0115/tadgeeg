"""Aggregate per-document AI fields (`ai_summary`, `ai_recommendations`,
`anomalies_found`) into a single section ready for templates.

Each doc-type model carries its own AI columns populated by the upload /
analysis pipeline. The previous report was hardcoded for invoices and never
surfaced the AI work. This service unifies the read path so the report can
show one "AI Insights" section regardless of the doc type the user picked.
"""
from __future__ import annotations

import re
from collections import Counter
from typing import Iterable

from django.utils.translation import get_language


_AR_RANGE = re.compile(r"[؀-ۿ]")


def _is_arabic(text: str) -> bool:
    """Heuristic: at least one Arabic letter ⇒ treat as Arabic source."""
    return bool(text) and bool(_AR_RANGE.search(text))


def _pick_localized(doc, base_field: str, lang: str) -> object:
    """Return the field value matching `lang` (ar/en) with a graceful fallback.

    Resolution order:
      1. {base_field}_{lang}    — exact match for the active language
      2. {base_field}_{other}   — the other translated column, if populated
      3. {base_field}            — legacy single-language column
    """
    other = "en" if lang == "ar" else "ar"
    for suffix in (f"_{lang}", f"_{other}", ""):
        val = getattr(doc, f"{base_field}{suffix}", None)
        if isinstance(val, str) and val.strip():
            return val
        if isinstance(val, (list, tuple)) and any(v for v in val):
            return val
    return getattr(doc, base_field, None)


# Map selected_type → (model dotted-path, identifier-field). Derived from the
# audit adapter's _SPECS so any new doc type added there is picked up here
# automatically — every typed model already inherits AuditMixin which carries
# the ai_summary / ai_recommendations / anomalies_found columns.
def _build_doc_map() -> dict[str, tuple[str, str]]:
    from apps.reports.services.multi_doc_audit_adapter import _SPECS
    mapping: dict[str, tuple[str, str]] = {
        "invoice": ("apps.invoices.models:Invoice", "invoice_number"),
    }
    for doc_type, spec in _SPECS.items():
        mapping[doc_type] = (spec.model_path, spec.number_field)
    return mapping


_AI_DOC_MAP: dict[str, tuple[str, str]] = _build_doc_map()


def _resolve(path: str):
    mod_path, cls = path.split(":")
    import importlib
    return getattr(importlib.import_module(mod_path), cls)


def _to_text(val) -> str:
    """Normalize whatever the model gives us into a clean string."""
    if val is None:
        return ""
    if isinstance(val, str):
        return val.strip()
    if isinstance(val, (list, tuple)):
        # Join non-empty list items
        parts = [str(p).strip() for p in val if p]
        return "; ".join(parts)
    if isinstance(val, dict):
        # Sometimes JSONField holds an object with a 'text' or 'summary' key
        for k in ("text", "summary", "message"):
            if k in val:
                return str(val[k]).strip()
        return ""
    return str(val).strip()


def build_ai_insights(org, selected_type: str, *, sample_size: int = 5) -> dict:
    """Return aggregated AI insights for the report.

    Shape:
        {
            "has_data":         bool,
            "documents_with_ai": int,
            "total_documents":   int,
            "sample_summaries":  [{"id": "...", "number": "X", "summary": "..."}],
            "top_recommendations": [{"text": "...", "count": N}],
            "anomalies":           [{"label": "...", "count": N}],
        }

    Returns a "no data" payload (has_data=False) when the doc-type isn't
    supported or when no documents have any AI content.
    """
    spec = _AI_DOC_MAP.get(selected_type)
    empty = {
        "has_data":            False,
        "documents_with_ai":   0,
        "total_documents":     0,
        "sample_summaries":    [],
        "top_recommendations": [],
        "anomalies":           [],
    }
    if spec is None:
        return empty
    Model, num_field = _resolve(spec[0]), spec[1]

    # Some doc types call the field `ai_summary`; ensure the model has the
    # column before we filter on it (defensive — prevents schema errors).
    field_names = {f.name for f in Model._meta.get_fields()}
    if "ai_summary" not in field_names:
        return empty

    base_qs = Model.objects.filter(organization=org)
    total_docs = base_qs.count()

    lang = (get_language() or "ar")[:2]
    candidate_fields = (
        "ai_summary", "ai_summary_ar", "ai_summary_en",
        "ai_recommendations", "ai_recommendations_ar", "ai_recommendations_en",
        "anomalies_found", num_field,
    )
    only_fields = ["id"]
    for f in candidate_fields:
        if f in field_names:
            only_fields.append(f)
    qs = base_qs.only(*only_fields)

    sample_summaries: list[dict] = []
    rec_counter: Counter = Counter()
    anom_counter: Counter = Counter()
    docs_with_ai = 0

    for doc in qs.iterator():
        summary = _to_text(_pick_localized(doc, "ai_summary", lang))
        recs    = _pick_localized(doc, "ai_recommendations", lang)
        anoms   = getattr(doc, "anomalies_found", None)

        has_any = False
        if summary:
            has_any = True
            if len(sample_summaries) < sample_size:
                sample_summaries.append({
                    "id":      str(doc.id),
                    "number":  str(getattr(doc, num_field, "") or "").strip() or str(doc.id)[:8],
                    "summary": summary[:280],  # cap at 280 chars
                })

        if isinstance(recs, (list, tuple)):
            for r in recs:
                t = _to_text(r)
                if t:
                    has_any = True
                    rec_counter[t] += 1
        elif isinstance(recs, str) and recs.strip():
            has_any = True
            rec_counter[recs.strip()] += 1

        if isinstance(anoms, (list, tuple)):
            for a in anoms:
                t = _to_text(a) if not isinstance(a, dict) else _to_text(
                    a.get("label") or a.get("type") or a.get("name") or ""
                )
                if t:
                    has_any = True
                    anom_counter[t] += 1
        elif isinstance(anoms, dict):
            for key, val in anoms.items():
                if val:
                    has_any = True
                    anom_counter[str(key)] += int(val) if isinstance(val, int) else 1

        if has_any:
            docs_with_ai += 1

    # Top recommendations + anomalies, capped
    top_recs = [{"text": t, "count": c} for t, c in rec_counter.most_common(8)]
    top_anoms = [{"label": t, "count": c} for t, c in anom_counter.most_common(8)]

    return {
        "has_data":            docs_with_ai > 0 or bool(top_recs) or bool(top_anoms),
        "documents_with_ai":   docs_with_ai,
        "total_documents":     total_docs,
        "sample_summaries":    sample_summaries,
        "top_recommendations": top_recs,
        "anomalies":           top_anoms,
    }
