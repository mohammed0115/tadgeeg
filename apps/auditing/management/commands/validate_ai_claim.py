"""Compute precision / recall / F1 against a labeled CSV and persist the run.

Backs the AI validation harness in apps.auditing.models. The pack
docs say "every public accuracy claim needs evidence" — this command
turns a CSV of ground-truth labels into a persisted AIValidationRun
row so operators can answer "what's our measured F1 for duplicate
detection right now?" without doing it by hand each time.

Input CSV format (header row required):
    expected,actual

Both columns hold strings. Each row is one prediction:
  - For classifiers (duplicate / fraud / VAT-check / vendor-risk),
    use "1" / "0" or "true" / "false".
  - For multi-class (e.g. document_type), use the class label.

For OCR field-level accuracy, use --field-mode: each row is
(expected_field_value, actual_field_value) and we compute exact-match
field accuracy + character error rate.

For forecasting, use --forecast-mode: each row is
(actual_numeric, predicted_numeric) and we compute MAPE / MAE / RMSE.

Usage:
    python manage.py validate_ai_claim \\
        --component duplicate \\
        --model-version gpt-4o-2026-05 \\
        --dataset-name dup_eval_v1 \\
        --csv path/to/labels.csv

    python manage.py validate_ai_claim \\
        --component ocr --field-mode \\
        --model-version pyocr-tesseract-5.3 \\
        --dataset-name ocr_eval_v1 \\
        --csv path/to/ocr.csv

    python manage.py validate_ai_claim \\
        --component cash_forecast --forecast-mode \\
        --model-version prophet-1.1.5 \\
        --dataset-name cash_eval_v1 \\
        --csv path/to/forecast.csv

The resulting run is visible in /admin/auditing/aivalidationrun/.
"""
from __future__ import annotations

import csv
import math
from pathlib import Path
from typing import List

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.auditing.models import AIValidationDataset, AIValidationRun


# ── Helpers ───────────────────────────────────────────────────────────────────

def _to_bool(s: str) -> bool:
    return str(s).strip().lower() in ("1", "true", "yes", "y", "t")


def _classifier_metrics(rows: list[tuple[str, str]]) -> dict:
    """Binary classification metrics from (expected, actual)."""
    tp = fp = tn = fn = 0
    for exp, act in rows:
        e, a = _to_bool(exp), _to_bool(act)
        if e and a:        tp += 1
        elif e and not a:  fn += 1
        elif not e and a:  fp += 1
        else:              tn += 1
    total = tp + fp + tn + fn or 1
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall    = tp / (tp + fn) if (tp + fn) else 0.0
    f1        = (2 * precision * recall / (precision + recall)
                 if (precision + recall) else 0.0)
    accuracy  = (tp + tn) / total
    fpr       = fp / (fp + tn) if (fp + tn) else 0.0
    fnr       = fn / (fn + tp) if (fn + tp) else 0.0
    return {
        "precision":           round(precision, 4),
        "recall":              round(recall, 4),
        "f1_score":            round(f1, 4),
        "accuracy":            round(accuracy, 4),
        "false_positive_rate": round(fpr, 4),
        "false_negative_rate": round(fnr, 4),
        "true_positives":      tp,
        "false_positives":     fp,
        "true_negatives":      tn,
        "false_negatives":     fn,
    }


def _ocr_field_metrics(rows: list[tuple[str, str]]) -> dict:
    """Exact-match field accuracy + character error rate."""
    total = len(rows) or 1
    matches = sum(1 for e, a in rows if (e or "").strip() == (a or "").strip())
    field_accuracy = matches / total
    cer = sum(_char_error(e, a) for e, a in rows) / total
    return {
        "field_accuracy":       round(field_accuracy, 4),
        "character_error_rate": round(cer, 4),
        "document_accuracy":    round(field_accuracy, 4),  # 1:1 in single-field CSV
    }


def _char_error(a: str, b: str) -> float:
    """Normalised Levenshtein distance, clipped to [0, 1]."""
    a, b = (a or ""), (b or "")
    if not a and not b:
        return 0.0
    if not a or not b:
        return 1.0
    # iterative DP — fine for our short OCR strings
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j-1] + 1,
                           prev[j-1] + (0 if ca == cb else 1)))
        prev = cur
    return min(1.0, prev[-1] / max(len(a), len(b)))


def _forecast_metrics(rows: list[tuple[str, str]]) -> dict:
    """MAPE / MAE / RMSE / bias on (actual, predicted)."""
    pairs = []
    for exp, act in rows:
        try:
            pairs.append((float(exp), float(act)))
        except ValueError:
            continue
    if not pairs:
        return {"mape": None, "mae": None, "rmse": None, "bias": None}
    n = len(pairs)
    abs_err = [abs(a - p) for a, p in pairs]
    pct_err = [abs(a - p) / abs(a) for a, p in pairs if a != 0]
    sq_err  = [(a - p) ** 2 for a, p in pairs]
    bias    = sum(p - a for a, p in pairs) / n
    return {
        "mape": round(sum(pct_err) / len(pct_err), 4) if pct_err else None,
        "mae":  round(sum(abs_err) / n, 4),
        "rmse": round(math.sqrt(sum(sq_err) / n), 4),
        "bias": round(bias, 4),
    }


# ── Command ───────────────────────────────────────────────────────────────────

class Command(BaseCommand):
    help = "Score an AI component against a labeled CSV and persist the result."

    def add_arguments(self, parser):
        parser.add_argument("--component", required=True,
                            choices=[c.value for c in AIValidationRun.Component])
        parser.add_argument("--model-version", required=True)
        parser.add_argument("--dataset-name", required=True)
        parser.add_argument("--dataset-version", default="1.0")
        parser.add_argument("--csv", required=True,
                            help="Path to labels CSV with header 'expected,actual'.")
        parser.add_argument("--language", default="ar")
        parser.add_argument("--document-type", default="")
        parser.add_argument("--field-mode", action="store_true",
                            help="Compute OCR field-level metrics.")
        parser.add_argument("--forecast-mode", action="store_true",
                            help="Compute forecasting metrics (MAPE/MAE/RMSE/bias).")

    def handle(self, *args, **opts):
        csv_path = Path(opts["csv"])
        if not csv_path.exists():
            raise CommandError(f"CSV not found: {csv_path}")

        with csv_path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            if reader.fieldnames is None or "expected" not in reader.fieldnames \
                    or "actual" not in reader.fieldnames:
                raise CommandError(
                    "CSV must have header columns: expected,actual"
                )
            rows: List[tuple[str, str]] = [(r["expected"], r["actual"]) for r in reader]

        if not rows:
            raise CommandError("CSV is empty.")

        dataset, _ = AIValidationDataset.objects.update_or_create(
            name=opts["dataset_name"],
            version=opts["dataset_version"],
            defaults={
                "language":        opts["language"],
                "document_type":   opts["document_type"] or opts["component"],
                "source_uri":      str(csv_path),
                "document_count":  len(rows),
                "labeling_method": "manual",
            },
        )

        if opts["field_mode"]:
            metrics = _ocr_field_metrics(rows)
        elif opts["forecast_mode"]:
            metrics = _forecast_metrics(rows)
        else:
            metrics = _classifier_metrics(rows)

        run = AIValidationRun.objects.create(
            dataset=dataset,
            component=opts["component"],
            model_version=opts["model_version"],
            decision=AIValidationRun.Decision.PENDING,
            completed_at=timezone.now(),
            **{k: v for k, v in metrics.items()
               if k in {f.name for f in AIValidationRun._meta.get_fields()}},
            raw_metrics=metrics,
        )
        self.stdout.write(self.style.SUCCESS(
            f"AIValidationRun {run.id} created — component={run.component} "
            f"headline={run.headline_metric()}"
        ))
        for k, v in metrics.items():
            self.stdout.write(f"  {k}: {v}")
