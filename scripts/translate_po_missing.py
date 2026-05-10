"""Backfill empty `msgstr` entries in a Django .po file via OpenAI.

One-off helper for the locale/<lang>/LC_MESSAGES/django.po file. Reads every
entry whose `msgstr` is empty, sends them to OpenAI in a single batched
JSON call, and writes the translations back. Skips entries that already
have a translation.

Usage:
    python scripts/translate_po_missing.py locale/ar/LC_MESSAGES/django.po
    python scripts/translate_po_missing.py locale/ar/LC_MESSAGES/django.po --dry-run
    python scripts/translate_po_missing.py locale/ar/LC_MESSAGES/django.po --batch-size 50

The script is idempotent: re-running over an already-populated .po
makes zero OpenAI calls.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Iterable

# Standard target languages
LANG_FROM_PATH = re.compile(r"locale/([a-z]{2})/LC_MESSAGES/")
LANG_NAME = {
    "ar": "Arabic (Modern Standard, formal business register)",
    "en": "English (US business register)",
    "fr": "French",
    "es": "Spanish",
}


def parse_po(path: Path) -> list[dict]:
    """Tiny .po parser sufficient for what Django emits.

    Returns a list of {start, end, msgid, msgstr, msgctxt, msgid_plural}.
    Each `start/end` is the line range so we can rewrite msgstr in-place.
    """
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    entries: list[dict] = []
    i = 0

    while i < len(lines):
        # Skip blank/comment lines until we hit msgctxt or msgid
        if not lines[i].lstrip().startswith(("msgid", "msgctxt")):
            i += 1
            continue

        start = i
        msgctxt = ""
        msgid = ""
        msgstr = ""
        msgid_plural = ""

        # msgctxt (optional)
        if lines[i].startswith("msgctxt "):
            msgctxt, i = _read_string(lines, i, prefix="msgctxt ")

        # msgid
        if lines[i].startswith("msgid "):
            msgid, i = _read_string(lines, i, prefix="msgid ")
        else:
            i += 1
            continue

        # msgid_plural (optional)
        if i < len(lines) and lines[i].startswith("msgid_plural "):
            msgid_plural, i = _read_string(lines, i, prefix="msgid_plural ")

        # msgstr (or msgstr[0] for plurals — we skip plural entries)
        if i < len(lines) and lines[i].startswith("msgstr "):
            msgstr_start = i
            msgstr, i = _read_string(lines, i, prefix="msgstr ")
            entries.append({
                "start":          start,
                "msgstr_start":   msgstr_start,
                "end":            i,
                "msgctxt":        msgctxt,
                "msgid":          msgid,
                "msgstr":         msgstr,
                "msgid_plural":   msgid_plural,
            })
        else:
            i += 1

    return entries


def _read_string(lines: list[str], i: int, prefix: str) -> tuple[str, int]:
    """Read a possibly-multiline PO string starting at lines[i]."""
    line = lines[i].rstrip("\n").rstrip("\r")
    s = _unquote(line[len(prefix):])
    i += 1
    while i < len(lines) and lines[i].lstrip().startswith('"'):
        s += _unquote(lines[i].strip())
        i += 1
    return s, i


def _unquote(s: str) -> str:
    s = s.strip()
    if s.startswith('"') and s.endswith('"'):
        s = s[1:-1]
    return (s.replace('\\"', '"').replace('\\n', '\n')
              .replace('\\t', '\t').replace('\\\\', '\\'))


def _quote(s: str) -> str:
    s = (s.replace('\\', '\\\\').replace('"', '\\"')
          .replace('\n', '\\n').replace('\t', '\\t'))
    return f'"{s}"'


def needs_translation(entry: dict) -> bool:
    if entry["msgid"] == "":
        return False  # header
    if entry["msgid_plural"]:
        return False  # skip plural — needs special handling
    return entry["msgstr"] == ""


def chunk(seq: list, size: int) -> Iterable[list]:
    for i in range(0, len(seq), size):
        yield seq[i:i + size]


def translate_batch(client, model: str, target_lang: str, batch: list[dict]) -> dict[str, str]:
    """Send one batch to OpenAI; return {msgid: msgstr}."""
    payload = [{"id": str(idx), "text": e["msgid"]} for idx, e in enumerate(batch)]
    system_prompt = (
        f"You are a translator. Translate the user's JSON list of UI strings "
        f"from English to {LANG_NAME.get(target_lang, target_lang)}. Preserve any "
        f"placeholders ({{var}}, %(var)s, %s, %d, HTML tags) verbatim. Keep the "
        f"register concise and professional. Return ONLY a strict JSON object "
        f"with the shape: {{\"translations\": [{{\"id\": \"...\", \"text\": \"...\"}}]}}. "
        f"Do not include any commentary."
    )
    user_prompt = json.dumps({"strings": payload}, ensure_ascii=False)

    resp = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": user_prompt},
        ],
        max_tokens=4096,
        temperature=0.0,
        response_format={"type": "json_object"},
    )
    content = resp.choices[0].message.content
    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        return {}

    out: dict[str, str] = {}
    for item in data.get("translations", []):
        try:
            i = int(item["id"])
            out[batch[i]["msgid"]] = item["text"]
        except (KeyError, ValueError, IndexError):
            continue
    return out


def write_po(path: Path, original_lines: list[str], updates: dict[str, str], entries: list[dict]) -> None:
    """Rewrite the .po file with new msgstrs filled in for matching msgids."""
    lines = list(original_lines)
    # Build a quick lookup: line index of msgstr "" that we should replace.
    # Apply replacements bottom-up to avoid index shift.
    edits = []
    for e in entries:
        if e["msgid"] in updates and e["msgstr"] == "" and updates[e["msgid"]]:
            edits.append((e["msgstr_start"], e["end"], updates[e["msgid"]]))
    edits.sort(key=lambda t: t[0], reverse=True)

    for start, end, new_text in edits:
        new_line = f"msgstr {_quote(new_text)}\n"
        lines[start:end] = [new_line]

    path.write_text("".join(lines), encoding="utf-8")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("po_path")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--batch-size", type=int, default=40)
    p.add_argument("--openai-model", default="gpt-4o-mini")
    p.add_argument("--limit", type=int, default=0,
                   help="Stop after N translations (0 = all).")
    args = p.parse_args()

    po = Path(args.po_path)
    if not po.exists():
        print(f"File not found: {po}", file=sys.stderr)
        return 2

    m = LANG_FROM_PATH.search(str(po))
    if not m:
        print(f"Could not detect language from path: {po}", file=sys.stderr)
        return 2
    target_lang = m.group(1)

    entries = parse_po(po)
    pending = [e for e in entries if needs_translation(e)]
    print(f"Total entries: {len(entries)}")
    print(f"Already translated: {len(entries) - len(pending) - 1}")  # -1 for header
    print(f"Pending (empty msgstr): {len(pending)}")

    if not pending:
        print("Nothing to do.")
        return 0

    if args.limit:
        pending = pending[:args.limit]
        print(f"--limit set: will process {len(pending)} entries")

    if args.dry_run:
        print("DRY RUN — first 5 strings that would be translated:")
        for e in pending[:5]:
            print(f"  {e['msgid'][:90]!r}")
        return 0

    api_key = os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        # Pull from Django settings as a courtesy.
        try:
            os.environ.setdefault("DJANGO_SETTINGS_MODULE", "finai_backend.settings")
            import django
            django.setup()
            from django.conf import settings as dj_settings
            api_key = getattr(dj_settings, "OPENAI_API_KEY", "")
        except Exception:
            pass
    if not api_key:
        print("OPENAI_API_KEY not set in env or settings.", file=sys.stderr)
        return 2

    from openai import OpenAI
    client = OpenAI(api_key=api_key)

    updates: dict[str, str] = {}
    for i, batch in enumerate(chunk(pending, args.batch_size), start=1):
        print(f"  batch {i}: translating {len(batch)} strings ...", flush=True)
        got = translate_batch(client, args.openai_model, target_lang, batch)
        updates.update(got)
        print(f"    got {len(got)}/{len(batch)} translations")

    print(f"\nTotal translations received: {len(updates)}")

    write_po(po, po.read_text(encoding="utf-8").splitlines(keepends=True), updates, entries)
    print(f"Wrote {po} with {len(updates)} new msgstr entries.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
