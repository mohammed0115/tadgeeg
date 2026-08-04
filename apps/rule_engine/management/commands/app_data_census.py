"""Row counts per app, so "is this app dead?" is measured rather than assumed.

    python manage.py app_data_census
    python manage.py app_data_census --apps audit auditing audit_engine rule_engine

Written because the question came up as "can we delete these three legacy
apps", and the answer turned on numbers nobody had. On a development database
`apps.audit_engine` holds zero rows and `apps.audit` holds 387 — but a
development database proves nothing about production, and deleting an app is
not reversible by `git revert`: the migration that drops the tables takes the
rows with it.

An app with no rows is a deletion candidate. An app with rows is a domain, no
matter what its name suggests.
"""

from __future__ import annotations

from django.apps import apps as django_apps
from django.core.management.base import BaseCommand
from django.db import DatabaseError


class Command(BaseCommand):
    help = "Count rows per model per app — the evidence for keeping or deleting an app."

    def add_arguments(self, parser):
        parser.add_argument(
            "--apps", nargs="*", default=None,
            help="App labels to census. Default: every installed app under apps/.",
        )
        parser.add_argument(
            "--empty-only", action="store_true",
            help="Show only apps with zero rows — the deletion candidates.",
        )

    def handle(self, *args, **options):
        wanted = options.get("apps")
        configs = [
            config for config in django_apps.get_app_configs()
            if (config.label in wanted if wanted else config.name.startswith("apps."))
        ]

        if not configs:
            self.stderr.write(self.style.ERROR("No matching apps."))
            return

        report = []
        for config in sorted(configs, key=lambda c: c.label):
            models = list(config.get_models())
            counts = []
            for model in models:
                try:
                    counts.append((model.__name__, model.objects.count()))
                except DatabaseError as exc:
                    # A model whose table is missing is itself a finding: the
                    # app is installed but never migrated.
                    counts.append((model.__name__, f"NO TABLE ({exc.__class__.__name__})"))
            numeric = [c for _, c in counts if isinstance(c, int)]
            report.append((config.label, len(models), sum(numeric), counts))

        for label, model_count, total, counts in report:
            if options["empty_only"] and total:
                continue

            style = self.style.WARNING if total == 0 else self.style.SUCCESS
            self.stdout.write(style(
                f"\n{label}  —  {model_count} model(s), {total} row(s)"
            ))
            if total == 0:
                self.stdout.write(
                    "   no data. A deletion candidate — confirm no code imports it, "
                    "then remove the app and its migrations."
                )
            for name, count in sorted(counts, key=lambda c: -(c[1] if isinstance(c[1], int) else 0)):
                if count:
                    self.stdout.write(f"   {name:38} {count}")

        self.stdout.write(self.style.HTTP_INFO(
            "\nRun this on PRODUCTION before deleting anything. A development "
            "database proves nothing about live data, and the migration that "
            "drops a table takes the rows with it."
        ))
