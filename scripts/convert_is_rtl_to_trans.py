"""Convert `{% if is_rtl %}AR{% else %}EN{% endif %}` patterns to `{% trans 'EN' %}`
in the report templates that historically used the bilingual if/else pattern.

CSS-only conditionals (font-family, direction blocks, ml-/mr- classes) are
preserved when the `else` branch is a CSS string with no Arabic, since those
are layout-specific and shouldn't be wrapped.

Translations harvested from this conversion are written to a JSON file the
caller can hand-merge into the .po dictionaries.
"""
import json
import re
from pathlib import Path

BASE = Path('/home/mohamed/tadgeeg')
TARGETS = [
    'templates/reports/invoice_audit_report_v2.html',
]

# Pattern: {% if is_rtl %}<ar>{% else %}<en>{% endif %}
# Both branches must be inline (no nested template tags) and not contain CSS.
RTL_PATTERN = re.compile(
    r'\{%\s*if is_rtl\s*%\}(.*?)\{%\s*else\s*%\}(.*?)\{%\s*endif\s*%\}',
    re.DOTALL,
)

# Heuristic: skip when either branch looks like CSS, contains '{{' (variable),
# or contains other template tags like {% trans %} or {% if %}.
CSS_HINTS = ('font-family', 'direction:', 'rtl', 'ltr', 'sans-serif', "'Tajawal'", "'Inter'", 'border-r-4', 'border-l-4', 'text-right', 'text-left', 'ml-auto', 'mr-auto')

def is_pure_text(s: str) -> bool:
    """Heuristic: branch is plain text (allows %(var)s, &nbsp;, basic punctuation)."""
    s = s.strip()
    if not s:
        return False
    # Reject if contains template tags or CSS markers
    if '{%' in s or '{{' in s:
        return False
    if any(h in s for h in CSS_HINTS):
        return False
    return True

def collect_translations(target_files):
    out = {}
    for rel in target_files:
        path = BASE / rel
        if not path.exists():
            continue
        text = path.read_text(encoding='utf-8')
        n = 0
        n_skip = 0

        def repl(m):
            nonlocal n, n_skip
            ar = m.group(1).strip()
            en = m.group(2).strip()
            if not is_pure_text(ar) or not is_pure_text(en):
                n_skip += 1
                return m.group(0)
            # Skip if branches contain `{{ var }}` (variable interpolation)
            if '{' in ar or '{' in en:
                n_skip += 1
                return m.group(0)
            out[en] = ar
            n += 1
            esc = en.replace("'", r"\'")
            return "{% trans '" + esc + r"' %}"

        new_text = RTL_PATTERN.sub(repl, text)
        if new_text != text:
            path.write_text(new_text, encoding='utf-8')
            print(f"[ok] {rel}: replaced={n} skipped(CSS/var)={n_skip}")
        else:
            print(f"[--] {rel}: no replacements")
    return out


def ensure_load_i18n(rel: str):
    path = BASE / rel
    text = path.read_text(encoding='utf-8')
    if '{% load i18n %}' in text:
        return
    # Insert after the first {% load ... %} tag, or at the very top.
    m = re.search(r'\{%\s*load[^%]*%\}', text)
    if m:
        new_text = text[:m.end()] + '\n{% load i18n %}' + text[m.end():]
    else:
        new_text = '{% load i18n %}\n' + text
    path.write_text(new_text, encoding='utf-8')


def main():
    for rel in TARGETS:
        ensure_load_i18n(rel)
    translations = collect_translations(TARGETS)
    out_file = BASE / 'scripts' / 'reports_translations.json'
    out_file.write_text(json.dumps(translations, ensure_ascii=False, indent=1), encoding='utf-8')
    print(f"\nHarvested {len(translations)} EN→AR pairs → scripts/reports_translations.json")


if __name__ == '__main__':
    main()
