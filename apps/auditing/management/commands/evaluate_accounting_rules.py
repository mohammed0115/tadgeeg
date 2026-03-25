"""Management command to evaluate accounting rules and persist results."""

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from apps.authentication.models import Organization
from apps.auditing.accounting_rules.services import (
    evaluate_and_persist_invoice_rules,
    evaluate_and_persist_report_rules,
)
from apps.invoices.models import Invoice
from apps.reports.models import Report


class Command(BaseCommand):
    """Evaluate accounting rules (GAAP/IFRS) and persist results."""

    help = "Evaluate accounting rules for invoices or reports and save results to database"

    def add_arguments(self, parser):
        parser.add_argument(
            "--organization-id",
            type=str,
            help="Organization UUID",
            required=True,
        )
        parser.add_argument(
            "--invoice-id",
            type=str,
            help="Invoice UUID (optional)",
            default=None,
        )
        parser.add_argument(
            "--report-id",
            type=str,
            help="Report UUID (optional)",
            default=None,
        )
        parser.add_argument(
            "--standard",
            type=str,
            choices=["GAAP", "IFRS", "BOTH"],
            default="BOTH",
            help="Accounting standard to evaluate (GAAP, IFRS, or BOTH)",
        )
        parser.add_argument(
            "--all-invoices",
            action="store_true",
            help="Evaluate all invoices in the organization",
        )
        parser.add_argument(
            "--all-reports",
            action="store_true",
            help="Evaluate all reports in the organization",
        )

    def handle(self, *args, **options):
        organization_id = options["organization_id"]
        invoice_id = options["invoice_id"]
        report_id = options["report_id"]
        standard = options["standard"]
        all_invoices = options["all_invoices"]
        all_reports = options["all_reports"]

        try:
            org = Organization.objects.get(id=organization_id)
        except Organization.DoesNotExist:
            raise CommandError(f"Organization {organization_id} not found")

        standards = ["GAAP", "IFRS"] if standard == "BOTH" else [standard]
        total_evaluated = 0
        total_persisted = 0

        if invoice_id:
            total_evaluated, total_persisted = self._evaluate_invoice(
                invoice_id, organization_id, standards
            )

        elif report_id:
            total_evaluated, total_persisted = self._evaluate_report(
                report_id, organization_id, standards
            )

        elif all_invoices:
            total_evaluated, total_persisted = self._evaluate_all_invoices(
                organization_id, standards
            )

        elif all_reports:
            total_evaluated, total_persisted = self._evaluate_all_reports(
                organization_id, standards
            )

        else:
            raise CommandError(
                "Please specify --invoice-id, --report-id, --all-invoices, or --all-reports"
            )

        self.stdout.write(
            self.style.SUCCESS(
                f"✓ Evaluated {total_evaluated} rules and persisted {total_persisted} results"
            )
        )

    def _evaluate_invoice(self, invoice_id: str, org_id: str, standards: list) -> tuple:
        """Evaluate a single invoice and return (evaluated_count, persisted_count)."""
        try:
            invoice = Invoice.objects.get(id=invoice_id, organization_id=org_id)
        except Invoice.DoesNotExist:
            raise CommandError(f"Invoice {invoice_id} not found in organization {org_id}")

        total_persisted = 0

        for standard in standards:
            with transaction.atomic():
                result = evaluate_and_persist_invoice_rules(
                    invoice_id=invoice_id,
                    organization_id=org_id,
                    standard=standard,
                    persist=True,
                )
                persisted = result["persisted_count"]
                total_persisted += persisted
                self.stdout.write(
                    f"  Invoice {invoice_id}: {standard} = {persisted} rules persisted"
                )

        return 8 if "GAAP" in standards else 9 if "IFRS" in standards else 17, total_persisted

    def _evaluate_report(self, report_id: str, org_id: str, standards: list) -> tuple:
        """Evaluate a single report and return (evaluated_count, persisted_count)."""
        try:
            report = Report.objects.get(id=report_id, organization_id=org_id)
        except Report.DoesNotExist:
            raise CommandError(f"Report {report_id} not found in organization {org_id}")

        total_evaluated = 0
        total_persisted = 0

        for standard in standards:
            with transaction.atomic():
                result = evaluate_and_persist_report_rules(
                    report_id=report_id,
                    organization_id=org_id,
                    standard=standard,
                    persist=True,
                )
                persisted = result["persisted_count"]
                total_persisted += persisted
                # Rough estimate of rules evaluated (number of invoices * rules per standard)
                invoice_count = len(result["results"])
                total_evaluated += invoice_count
                self.stdout.write(
                    f"  Report {report_id}: {standard} = {persisted} rules persisted for {invoice_count} invoices"
                )

        return total_evaluated, total_persisted

    def _evaluate_all_invoices(self, org_id: str, standards: list) -> tuple:
        """Evaluate all invoices in organization."""
        invoices = Invoice.objects.filter(organization_id=org_id)
        total_evaluated = 0
        total_persisted = 0

        self.stdout.write(f"Evaluating {invoices.count()} invoices...")

        for invoice in invoices:
            for standard in standards:
                with transaction.atomic():
                    result = evaluate_and_persist_invoice_rules(
                        invoice_id=str(invoice.id),
                        organization_id=org_id,
                        standard=standard,
                        persist=True,
                    )
                    total_evaluated += result["summary"].get("total_rules", 0)
                    total_persisted += result["persisted_count"]

        return total_evaluated, total_persisted

    def _evaluate_all_reports(self, org_id: str, standards: list) -> tuple:
        """Evaluate all reports in organization."""
        reports = Report.objects.filter(organization_id=org_id)
        total_evaluated = 0
        total_persisted = 0

        self.stdout.write(f"Evaluating {reports.count()} reports...")

        for report in reports:
            for standard in standards:
                with transaction.atomic():
                    result = evaluate_and_persist_report_rules(
                        report_id=str(report.id),
                        organization_id=org_id,
                        standard=standard,
                        persist=True,
                    )
                    total_evaluated += result["summary"].get("total_rules", 0)
                    total_persisted += result["persisted_count"]

        return total_evaluated, total_persisted
