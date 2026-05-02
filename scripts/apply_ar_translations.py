"""Apply Arabic translations from ar_translations_part{1,2,3,4}.py to the AR po file.

For every entry that is fuzzy OR has empty msgstr:
- Look up its msgid in the merged translation dict.
- If found: set msgstr, clear fuzzy flag, clear previous_msgid markers.
- If not found: leave it (will be reported as a remaining gap).
"""
import sys
sys.path.insert(0, '/home/mohamed/tadgeeg/scripts')

import polib
import importlib

# Load all 4 parts
parts = []
for i in (1, 2, 3, 4):
    mod = importlib.import_module(f'ar_translations_part{i}')
    parts.append(mod.TRANSLATIONS)

translations = {}
for p in parts:
    translations.update(p)

print(f"Loaded {len(translations)} unique translation entries")

PATH = '/home/mohamed/tadgeeg/locale/ar/LC_MESSAGES/django.po'
po = polib.pofile(PATH)

applied = 0
skipped_not_found = []
fuzzy_kept = 0  # If translation matches what's already there, just clear fuzzy flag

for entry in po:
    if entry.obsolete:
        continue
    if entry.msgid_plural:
        continue  # No plural entries reported as needing attention
    is_fuzzy = 'fuzzy' in entry.flags
    is_empty = not entry.msgstr and entry.msgid != ""

    if not is_fuzzy and not is_empty:
        continue

    if entry.msgid in translations:
        new_translation = translations[entry.msgid]
        entry.msgstr = new_translation
        if is_fuzzy:
            entry.flags = [f for f in entry.flags if f != 'fuzzy']
            entry.previous_msgid = None
            entry.previous_msgctxt = None
        applied += 1
    else:
        skipped_not_found.append(entry.msgid)

po.save(PATH)
print(f"Applied: {applied}")
print(f"Skipped (no translation in dict): {len(skipped_not_found)}")
if skipped_not_found:
    print("First 20 missing:")
    for m in skipped_not_found[:20]:
        print(f"  - {m!r}")

# Final stats
po2 = polib.pofile(PATH)
remaining_empty = [e for e in po2 if not e.msgstr and not e.obsolete and e.msgid != "" and not e.msgid_plural]
remaining_fuzzy = [e for e in po2 if 'fuzzy' in e.flags and not e.obsolete]
print(f"\nFinal AR stats: empty={len(remaining_empty)}, fuzzy={len(remaining_fuzzy)}")
