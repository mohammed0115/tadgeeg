"""Fix English .po: for every fuzzy or empty entry, set msgstr = msgid and clear fuzzy flag.

Source language is English, so msgid IS the correct English text. This is a safe
mechanical fix for the EN locale only — do not run on the AR file.
"""
import polib
import sys

PATH = '/home/mohamed/tadgeeg/locale/en/LC_MESSAGES/django.po'

po = polib.pofile(PATH)

fixed_fuzzy = 0
fixed_empty = 0
plural_fixed = 0

for entry in po:
    if entry.obsolete:
        continue
    is_fuzzy = 'fuzzy' in entry.flags
    is_empty = not entry.msgstr and entry.msgid != ""

    if entry.msgid_plural:
        # Plural entry: msgstr_plural[0] = msgid (singular), msgstr_plural[1] = msgid_plural
        if is_fuzzy or not entry.msgstr_plural.get(0):
            entry.msgstr_plural[0] = entry.msgid
            entry.msgstr_plural[1] = entry.msgid_plural
            plural_fixed += 1
            if is_fuzzy:
                entry.flags = [f for f in entry.flags if f != 'fuzzy']
            entry.previous_msgid = None
            entry.previous_msgid_plural = None
            entry.previous_msgctxt = None
        continue

    if is_fuzzy:
        entry.msgstr = entry.msgid
        entry.flags = [f for f in entry.flags if f != 'fuzzy']
        entry.previous_msgid = None
        entry.previous_msgctxt = None
        fixed_fuzzy += 1
    elif is_empty:
        entry.msgstr = entry.msgid
        fixed_empty += 1

po.save(PATH)
print(f"EN: fixed {fixed_fuzzy} fuzzy, {fixed_empty} empty, {plural_fixed} plurals")
print(f"   Total entries: {len([e for e in po if not e.obsolete])}")
print(f"   Remaining empty: {len([e for e in po if not e.msgstr and not e.obsolete and e.msgid != '' and not e.msgid_plural])}")
print(f"   Remaining fuzzy: {len([e for e in po if 'fuzzy' in e.flags and not e.obsolete])}")
