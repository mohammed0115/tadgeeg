"""Final pass for the remaining is_rtl patterns in report templates that have
variable interpolations or severity chains.

Strategy:
  • `{% if is_rtl %}AR_with_var{% else %}EN_with_var{% endif %}` →
    `{% blocktrans with v=var %}EN_with_var{% endblocktrans %}`
    (only when there's exactly one matching variable in both branches)

  • `{% if priority=='critical' %}حرج{% elif ... %}عالي{% elif ... %}متوسط{% else %}منخفض{% endif %}` →
    Map each level to its risk_level value and use a single
    `{% trans severity %}` style placeholder fed by the level keyword.
    For now we use the lazy `with` capture and let the .po file deliver the
    translation; we always pass the English label.

The script writes JSON of new strings to harvest into .po.
"""
import json
import re
from pathlib import Path

BASE = Path('/home/mohamed/tadgeeg')
TARGETS = [
    'templates/reports/invoice_audit_report_v2.html',
]

# 1) Severity / priority chains like:
#    {% if X.priority == 'critical' %}حرج {% elif X.priority == 'high' %}عالي ...
#    Replace with the trans-aware pattern.
SEV_CHAIN = re.compile(
    r"\{%\s*if\s+([\w.]+)\s*==\s*'critical'\s*%\}\s*[^\n{]*?\s*"
    r"\{%\s*elif\s+\1\s*==\s*'high'\s*%\}\s*[^\n{]*?\s*"
    r"\{%\s*elif\s+\1\s*==\s*'medium'\s*%\}\s*[^\n{]*?\s*"
    r"\{%\s*(?:elif\s+\1\s*==\s*'low'\s*|else\s*)%\}\s*[^\n{]*?\s*"
    r"\{%\s*endif\s*%\}",
    re.DOTALL,
)

# 2) Bilingual ternary with a single variable interpolation; converts to blocktrans.
#    {% if is_rtl %}AR{{ x }}AR{% else %}EN{{ x }}EN{% endif %}
RTL_VAR = re.compile(
    r'\{%\s*if is_rtl\s*%\}(.*?)\{%\s*else\s*%\}(.*?)\{%\s*endif\s*%\}',
    re.DOTALL,
)

# 3) Standalone bilingual without vars but with HTML entities like &amp;
#    Already handled in the first script, keep as fallback.

# Track harvested EN strings so we can bulk-translate in .po.
harvested = {}  # en_with_placeholders -> ar_with_placeholders

VAR_REF_PATTERN = re.compile(r'\{\{\s*([^|}]+?)\s*(?:\|[^}]+)?\s*\}\}')


def normalize_for_blocktrans(s: str) -> tuple[str, list[str]]:
    """Replace {{ x.y|filter }} with `{{ var0 }}` etc. Return (template, vars)."""
    pieces = []
    def repl(m):
        full = m.group(0)
        pieces.append(full)
        return '__VAR__' + str(len(pieces) - 1) + '__'
    norm = VAR_REF_PATTERN.sub(repl, s)
    return norm, pieces


def convert_rtl_with_vars(text: str) -> tuple[str, int]:
    n = 0
    def repl(m):
        nonlocal n
        ar = m.group(1).strip()
        en = m.group(2).strip()
        # Only convert when both branches have variables AND at least one var
        # appears in identical filter form.
        ar_norm, ar_vars = normalize_for_blocktrans(ar)
        en_norm, en_vars = normalize_for_blocktrans(en)
        # Skip nested template tags
        if '{%' in ar or '{%' in en:
            return m.group(0)
        if not en_vars:
            return m.group(0)
        # The variables must align in count (we'll bind them with `with` clause).
        if len(ar_vars) != len(en_vars):
            return m.group(0)
        # Build blocktrans
        bind_pairs = []
        en_out = en_norm
        ar_out = ar_norm
        for i, var in enumerate(en_vars):
            placeholder = '__VAR__' + str(i) + '__'
            inner = re.sub(r'^\{\{\s*|\s*\}\}$', '', var)
            # Skip when the variable expression is too complex for a `with` clause
            if '|' in inner:
                # Need to alias filter expression: with v0=x.y|f
                bind_pairs.append((f'v{i}', inner))
                en_out = en_out.replace(placeholder, f'{{{{ v{i} }}}}')
                ar_out = ar_out.replace(placeholder, f'{{{{ v{i} }}}}')
            else:
                # Use original variable name (last segment) when possible
                seg = inner.strip().split('.')[-1].split()[0]
                # When the same name is referenced in EN and AR consistently we keep it
                bind_pairs.append((f'v{i}', inner.strip()))
                en_out = en_out.replace(placeholder, f'{{{{ v{i} }}}}')
                ar_out = ar_out.replace(placeholder, f'{{{{ v{i} }}}}')
        with_clause = ' '.join(f'{k}={v}' for k, v in bind_pairs)
        # Skip if either branch becomes empty
        if not en_out or not ar_out:
            return m.group(0)
        # Don't double-translate if branches have nested template tags
        if '{%' in en_out or '{%' in ar_out:
            return m.group(0)
        harvested[en_out] = ar_out
        n += 1
        return '{% blocktrans with ' + with_clause + ' %}' + en_out + '{% endblocktrans %}'

    new_text = RTL_VAR.sub(repl, text)
    return new_text, n


def collect_severity_chains(text: str) -> tuple[str, int]:
    """Replace severity-chain `{% if X.priority == 'critical' %}AR{% elif ... %}AR{% else %}AR{% endif %}`
    with a small inline `{% if %}` chain that calls trans on stable English keys.
    """
    n = 0
    # Two specific known chains (per user content), apply via str.replace.
    chains_to_replace = [
        # executive_report.html line ~551 (issue.applied_severity)
        ("                  {% if issue.applied_severity == 'critical' %}حرج\n"
         "                  {% elif issue.applied_severity == 'high' %}عالي\n"
         "                  {% elif issue.applied_severity == 'medium' %}متوسط\n"
         "                  {% else %}منخفض{% endif %}",
         "                  {% if issue.applied_severity == 'critical' %}{% trans \"Critical\" %}\n"
         "                  {% elif issue.applied_severity == 'high' %}{% trans \"High\" %}\n"
         "                  {% elif issue.applied_severity == 'medium' %}{% trans \"Medium\" %}\n"
         "                  {% else %}{% trans \"Low\" %}{% endif %}"),
        # executive_report.html line ~723 (rec.priority)
        ("                {% if rec.priority == 'critical' %}حرج\n"
         "                {% elif rec.priority == 'high' %}عالي\n"
         "                {% elif rec.priority == 'medium' %}متوسط\n"
         "                {% else %}منخفض{% endif %}",
         "                {% if rec.priority == 'critical' %}{% trans \"Critical\" %}\n"
         "                {% elif rec.priority == 'high' %}{% trans \"High\" %}\n"
         "                {% elif rec.priority == 'medium' %}{% trans \"Medium\" %}\n"
         "                {% else %}{% trans \"Low\" %}{% endif %}"),
        # document_audit_report.html line ~1391 (rec.priority — different indentation)
        ("              {% if rec.priority == 'critical' %}حرج\n"
         "              {% elif rec.priority == 'high' %}عالٍ\n"
         "              {% elif rec.priority == 'medium' %}متوسط\n"
         "              {% elif rec.priority == 'low' %}منخفض",
         "              {% if rec.priority == 'critical' %}{% trans \"Critical\" %}\n"
         "              {% elif rec.priority == 'high' %}{% trans \"High\" %}\n"
         "              {% elif rec.priority == 'medium' %}{% trans \"Medium\" %}\n"
         "              {% elif rec.priority == 'low' %}{% trans \"Low\" %}"),
    ]
    for old, new in chains_to_replace:
        if old in text:
            text = text.replace(old, new)
            n += 1
    return text, n


def main():
    grand = 0
    for rel in TARGETS:
        path = BASE / rel
        text = path.read_text(encoding='utf-8')
        new_text, n_var = convert_rtl_with_vars(text)
        new_text, n_sev = collect_severity_chains(new_text)
        if new_text != text:
            path.write_text(new_text, encoding='utf-8')
            print(f"[ok] {rel}: blocktrans={n_var} severity_chains={n_sev}")
            grand += n_var + n_sev
        else:
            print(f"[--] {rel}: nothing")

    out_file = BASE / 'scripts' / 'reports_blocktrans.json'
    out_file.write_text(json.dumps(harvested, ensure_ascii=False, indent=1), encoding='utf-8')
    print(f"\nHarvested {len(harvested)} blocktrans EN→AR pairs")


if __name__ == '__main__':
    main()
