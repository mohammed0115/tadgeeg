"""عدّ الصفوف التي تخالف قيودًا لا يبنيها MySQL وسيبنيها PostgreSQL.

MySQL يتجاهل UniqueConstraint ذا condition بصمت — يطبع models.W036 ويمضي. فهذه
القيود **غير موجودة في قاعدة الإنتاج اليوم**. وPostgreSQL يبنيها، فأي صفوف
تخالفها تُفشل الاستيراد.

قراءة فقط: لا كتابة ولا DDL. والشرط يُطبَّق عبر ORM لا بترجمة يدوية للـSQL —
ترجمة الشرط بيد كانت ستَعُدّ صفوفًا لا يشملها القيد أصلًا.

    docker compose -f deployment/docker/docker-compose.yml run --rm \
      --entrypoint sh web_live -c \
      'python deployment/postgres/measure_constraint_violations.py'
"""

import os
import sys

import django

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "finai_backend.settings")
django.setup()

from django.apps import apps                      # noqa: E402
from django.db.models import Count, UniqueConstraint  # noqa: E402

rows, checked, unmeasurable = [], 0, []

for model in sorted(apps.get_models(), key=lambda m: m._meta.label):
    for constraint in getattr(model._meta, "constraints", []):
        if not isinstance(constraint, UniqueConstraint):
            continue
        if constraint.condition is None:
            continue          # MySQL builds these already — nothing new appears
        checked += 1
        try:
            groups = (
                model.objects.filter(constraint.condition)
                .values(*constraint.fields)
                .annotate(n=Count("pk"))
                .filter(n__gt=1)
            )
            violating = groups.count()
            extra = sum(g["n"] - 1 for g in groups) if violating else 0
        except Exception as exc:
            unmeasurable.append((constraint.name, f"{type(exc).__name__}: {exc}"))
            continue
        rows.append((constraint.name, model._meta.db_table, violating, extra))

assert checked, "no conditional unique constraints found — the scan is broken, not the tree"

rows.sort(key=lambda r: (-r[2], r[0]))
print()
print(f"{'constraint':<46} {'table':<40} {'groups':>7} {'extra rows':>11}")
print("-" * 108)
for name, table, violating, extra in rows:
    print(f"{name:<46} {table:<40} {violating:>7} {extra:>11}")

total_groups = sum(r[2] for r in rows)
total_extra = sum(r[3] for r in rows)
print("-" * 108)
print(f"{'المجموع':<46} {'':<40} {total_groups:>7} {total_extra:>11}")
print()
print(f"قيود شرطية مفحوصة: {checked}")
if unmeasurable:
    print(f"تعذّر قياسها: {len(unmeasurable)}")
    for name, why in unmeasurable:
        print(f"  · {name}: {why}")
print()
print("صفر في كل سطر  ⇒  لا شيء يمنع بناء هذه القيود على PostgreSQL.")
print("أي رقم غير صفر ⇒  صفوف تعمل بلا حراسة اليوم، وتحتاج قرارًا قبل الترحيل.")
