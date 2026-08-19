"""Repair `chain_actor` rows a migration wrote in the wrong representation.

`verify_chain()` reports tampering on rows nobody touched. Measured on
production 2026-08-19: one chain in audit_logs, position 1, previous_hash the
genesis value, and the stored event_hash simply not equal to the recomputed
one. Eleven rows on a development database, and the same shape.

Two migrations in one batch disagreed about how a UUID is spelled:

    authentication/0010  hashed str(row.user_id)         -> "085f9a13-0915-..."
    authentication/0011  backfilled chain_actor with
                         models.F("user_id")             -> "085f9a13091546..."

`F()` copies the column, and MySQL stores a UUIDField as char(32) with no
hyphens. `_chain_payload()` reads chain_actor, so the verifier hashes a
different string from the one the stored hash commits to. activity_logs/0006
carries the identical backfill.

So the audit record is intact and the derived field is wrong. This corrects the
field. **No event_hash, previous_hash or chain_position is written, and no
payload changes** — after the correction the existing hash verifies, which is
the proof the row was never altered.

Conservative by construction: a row is written only if it fails verification
now and passes with the corrected value. A row that fails both ways is left
alone and reported — that one is not this defect and must not be quietly
rewritten.

A command rather than a migration: verifying each row needs compute_hash, and a
historical migration must not import live application code. Inlining the hash
is what let 0010 and 0011 drift apart in the first place.

    python manage.py repair_chain_actor              # يفحص ولا يكتب
    python manage.py repair_chain_actor --apply
"""

import uuid

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.audit.integrity import HashChainMixin


def _dashed(value: str) -> str | None:
    """The hyphenated spelling of a 32-character hex actor, or None."""
    try:
        return str(uuid.UUID(value))
    except (ValueError, AttributeError, TypeError):
        return None


class Command(BaseCommand):
    help = "Correct chain_actor rows written by a migration in the column's raw spelling."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true",
                            help="Write the corrections. Without it, nothing is written.")

    def handle(self, *args, **options):
        from django.apps import apps as django_apps

        models = [
            m for m in django_apps.get_models()
            if issubclass(m, HashChainMixin)
            and any(f.name == "chain_actor" for f in m._meta.concrete_fields)
        ]
        if not models:
            raise SystemExit("no chain model carries chain_actor — the scan is broken, not the tree")

        apply = options["apply"]
        totals = {"checked": 0, "already": 0, "repairable": 0, "unexplained": 0}
        unexplained = []

        for model in models:
            repairable = []
            for row in model.objects.exclude(chain_actor="").iterator():
                totals["checked"] += 1
                if row.event_hash == row.compute_hash(row.previous_hash):
                    totals["already"] += 1
                    continue

                candidate = _dashed(row.chain_actor)
                if candidate is None or candidate == row.chain_actor:
                    totals["unexplained"] += 1
                    unexplained.append((model._meta.label, row.pk))
                    continue

                original, row.chain_actor = row.chain_actor, candidate
                verifies = row.event_hash == row.compute_hash(row.previous_hash)
                row.chain_actor = original

                if verifies:
                    totals["repairable"] += 1
                    repairable.append((row.pk, candidate))
                else:
                    totals["unexplained"] += 1
                    unexplained.append((model._meta.label, row.pk))

            self.stdout.write(f"  {model._meta.db_table:<32} {len(repairable):>5} قابلة للتصحيح")

            if apply and repairable:
                # Printed before the write, and printed in full: "we have a
                # backup" is not a reversal plan when the backup predates eight
                # migrations. These lines are the reversal — one UPDATE each.
                self.stdout.write("  -- للتراجع، إن لزم:")
                for pk, candidate in repairable:
                    former = model.objects.filter(pk=pk).values_list("chain_actor", flat=True)[0]
                    self.stdout.write(
                        f"  --   UPDATE {model._meta.db_table} SET chain_actor='{former}' "
                        f"WHERE id='{pk}';"
                    )
                with transaction.atomic():
                    for pk, candidate in repairable:
                        # .update(), not .save(): the pre_save signal owns the
                        # chain fields and refuses a re-hash. Only the derived
                        # column is written here.
                        model.objects.filter(pk=pk).update(chain_actor=candidate)

        self.stdout.write("")
        self.stdout.write(
            f"فُحص: {totals['checked']}   "
            f"يتحقّق أصلًا: {totals['already']}   "
            f"قابل للتصحيح: {totals['repairable']}   "
            f"غير مفسَّر: {totals['unexplained']}"
        )
        for label, pk in unexplained[:10]:
            self.stdout.write(f"  !! {label} {pk} — لا يتحقّق قبل التصحيح ولا بعده")
        if unexplained:
            self.stdout.write("     هذه ليست هذا العيب. تُبلَّغ ولا تُكتَب.")
        if not apply:
            self.stdout.write("\nفحص فقط. للكتابة: --apply")
