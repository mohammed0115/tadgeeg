"""End-to-end test of the audit pipeline on sample files from Dataset/.

Picks one representative file per supported type, runs router + parser + AI,
then prints a per-file summary and a final gap report.
"""
from __future__ import annotations

import json
import os
import sys
import time
import traceback
from dataclasses import dataclass, field

import django
from dotenv import load_dotenv

load_dotenv("/home/mohamed/tadgeeg/.env", override=True)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "finai_backend.settings")
sys.path.insert(0, "/home/mohamed/tadgeeg")
django.setup()

from apps.auditing.services.ai_auditor_service import AIAuditorService
from apps.auditing.services.file_router import FileRouterService
from apps.auditing.services.parser_service import ParserService

DS = "/home/mohamed/tadgeeg/Dataset"

SAMPLES = [
    # (label, path, expected_family, expected_doc_type)
    ("text-pdf invoice", f"{DS}/invoice_Andy Reiter_35286.pdf", "pdf", "invoice"),
    ("image-based PDF (Arabic)", f"{DS}/Imag1/invice1.pdf", "pdf", "invoice"),
    ("invoice image (jpeg)", f"{DS}/imag5/WhatsApp Image 2026-04-08 at 10.30.28 AM.jpeg", "image", "invoice"),
    ("invoice image (png)", f"{DS}/Imag1/WhatsApp Image 2026-04-08 at 10.20.25 AM.png", "image", "invoice"),
    ("ZATCA invoice JSON", f"{DS}/imag5/New Text Document.json", "json", "invoice"),
    ("ZATCA invoice XML", f"{DS}/imag5/New Text Document.xml", "xml", "invoice"),
    ("Bank Statements xlsx", f"{DS}/01_Bank_Statements_كشوف_الحساب.xlsx", "excel", "bank_statement"),
    ("Purchase Orders xlsx", f"{DS}/02_Purchase_Orders_أوامر_الشراء.xlsx", "excel", "purchase_order"),
    ("Payroll xlsx", f"{DS}/04_Payroll_كشوف_الرواتب.xlsx", "excel", "payroll"),
    ("VAT Returns xlsx", f"{DS}/06_VAT_Returns_الإقرارات_الضريبية.xlsx", "excel", "tax_declaration"),
    ("plain ReadMe.txt", f"{DS}/ReadMe.txt", "text", "other"),
]


@dataclass
class Result:
    label: str
    path: str
    expected_family: str
    expected_doc_type: str
    actual_family: str = ""
    extracted_chars: int = 0
    extract_seconds: float = 0.0
    extract_error: str = ""
    used_vision: bool = False
    ai_seconds: float = 0.0
    ai_error: str = ""
    ai_doc_type: str = ""
    ai_doc_type_confidence: float = 0.0
    ai_overall_confidence: float = 0.0
    ai_risk: str = ""
    ai_summary: str = ""
    extracted_keys: list = field(default_factory=list)


def extract_text(parser: ParserService, family: str, path: str) -> str:
    if family == "pdf":
        text = parser.parse_pdf_text(path)
        # if text is sparse, we'll switch to Vision later
        return text or ""
    if family == "excel":
        return parser.parse_excel(path)
    if family == "csv":
        return parser.parse_csv(path)
    if family == "json":
        return parser.parse_json(path)
    if family == "xml":
        return parser.parse_xml(path)
    if family == "text":
        return parser.parse_text(path)
    if family == "image":
        return ""  # images go straight to Vision
    return ""


def should_use_vision(family: str, raw_text: str) -> bool:
    if family == "image":
        return True
    if family == "pdf" and (not raw_text or len(raw_text.strip()) < 200):
        return True
    return False


def collect_images(parser: ParserService, family: str, path: str):
    if family == "image":
        return [path]
    if family == "pdf":
        return parser.render_pdf_pages(path, max_pages=2, dpi=180)
    return []


def run_one(sample, router, parser, ai) -> Result:
    label, path, exp_family, exp_doc = sample
    r = Result(label=label, path=path, expected_family=exp_family, expected_doc_type=exp_doc)

    if not os.path.exists(path):
        r.extract_error = "FILE_NOT_FOUND"
        return r

    # Step 1: route
    r.actual_family = router.route(path)

    # Step 2: extract
    t0 = time.time()
    try:
        text = extract_text(parser, r.actual_family, path)
        r.extracted_chars = len(text or "")
    except Exception as exc:
        r.extract_error = f"{type(exc).__name__}: {exc}"
        text = ""
    r.extract_seconds = round(time.time() - t0, 2)

    # Step 3: AI (vision or text)
    r.used_vision = should_use_vision(r.actual_family, text)

    t0 = time.time()
    try:
        if r.used_vision:
            images = collect_images(parser, r.actual_family, path)
            if not images:
                ai_result = ai.audit(text or "(no extractable text)", doc_type_hint=exp_doc)
            else:
                ai_result = ai.audit_images(
                    images,
                    doc_type_hint=exp_doc,
                    language="auto",
                    ocr_text=text[:2000] if text else "",
                )
        else:
            # Cap text passed to AI so we don't blow tokens on huge xlsx
            ai_result = ai.audit((text or "")[:18000], doc_type_hint=exp_doc)
    except Exception as exc:
        r.ai_error = f"{type(exc).__name__}: {exc}\n{traceback.format_exc()[-400:]}"
        ai_result = {}
    r.ai_seconds = round(time.time() - t0, 2)

    if isinstance(ai_result, dict):
        if ai_result.get("_error"):
            r.ai_error = r.ai_error or str(ai_result["_error"])
        r.ai_doc_type = str(ai_result.get("document_type", ""))
        try:
            r.ai_doc_type_confidence = float(ai_result.get("document_type_confidence") or 0)
        except (TypeError, ValueError):
            r.ai_doc_type_confidence = 0.0
        try:
            r.ai_overall_confidence = float(ai_result.get("overall_confidence") or 0)
        except (TypeError, ValueError):
            r.ai_overall_confidence = 0.0
        r.ai_risk = str(ai_result.get("overall_risk_level", ""))
        r.ai_summary = (ai_result.get("executive_summary") or "")[:160]
        ed = ai_result.get("extracted_data") or {}
        if isinstance(ed, dict):
            r.extracted_keys = list(ed.keys())[:8]
    return r


def main():
    router = FileRouterService()
    parser = ParserService()
    ai = AIAuditorService()

    results: list[Result] = []
    for sample in SAMPLES:
        print(f"→ {sample[0]:32}  ({os.path.basename(sample[1])[:40]})")
        r = run_one(sample, router, parser, ai)
        results.append(r)

        family_ok = "✓" if r.actual_family == r.expected_family else "✗"
        type_ok = "✓" if (r.ai_doc_type == r.expected_doc_type or r.ai_doc_type_confidence > 0.6) else "✗"
        print(
            f"   route={family_ok} {r.actual_family:8} extract={r.extracted_chars:>7}c/{r.extract_seconds}s "
            f"vision={'Y' if r.used_vision else 'N'} "
            f"ai_type={r.ai_doc_type or '?':<14} type_match={type_ok} "
            f"conf={r.ai_overall_confidence:.2f} risk={r.ai_risk or '?'} "
            f"({r.ai_seconds}s)"
        )
        if r.extract_error:
            print(f"   ⚠ extract_error: {r.extract_error[:200]}")
        if r.ai_error:
            print(f"   ⚠ ai_error: {r.ai_error[:200]}")
        if r.extracted_keys:
            print(f"   keys: {r.extracted_keys}")
        if r.ai_summary:
            print(f"   summary: {r.ai_summary}")
        print()

    # ─────────── Gap report ───────────
    print("=" * 78)
    print("GAP REPORT")
    print("=" * 78)
    routing_failures = [r for r in results if r.actual_family != r.expected_family]
    extract_failures = [r for r in results if r.extract_error]
    ai_failures = [r for r in results if r.ai_error]
    type_mismatches = [r for r in results if r.ai_doc_type and r.ai_doc_type != r.expected_doc_type]
    no_keys = [r for r in results if not r.extracted_keys and not r.ai_error]

    def show(title: str, items: list[Result]):
        print(f"\n{title}: {len(items)}")
        for r in items:
            print(f"  - {r.label}: {r.actual_family or '?'} | "
                  f"err={r.extract_error or r.ai_error or '-'} | "
                  f"ai_type={r.ai_doc_type or '?'}")

    show("Routing mismatches", routing_failures)
    show("Extraction failures", extract_failures)
    show("AI failures", ai_failures)
    show("Doc-type mismatches (AI ≠ expected)", type_mismatches)
    show("No extracted_data keys returned", no_keys)

    # Summary stats
    total = len(results)
    full_success = sum(
        1 for r in results
        if r.actual_family == r.expected_family
        and not r.extract_error and not r.ai_error
        and r.ai_doc_type and r.extracted_keys
    )
    print(f"\n{full_success}/{total} files fully processed")


if __name__ == "__main__":
    main()
