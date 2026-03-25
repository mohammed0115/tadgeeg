import logging
import os
import time

from django.conf import settings
from django.utils import timezone

from apps.audit_engine.exceptions import AuditJobError
from apps.audit_engine.models import AuditIssue, AuditJob, AuditResult
from apps.audit_engine.services.parsers.dispatcher import ParserDispatcher
from apps.audit_engine.services.rules.registry import RuleRegistry
from apps.audit_engine.services.scoring.service import AuditScoringService
from apps.storage_management.models import FileStorageMapping

logger = logging.getLogger(__name__)


class AuditOrchestrator:
    """
    Master pipeline coordinator.

    Pipeline:
      1. Mark job RUNNING
      2. Resolve file path from FileStorageMapping
      3. Parse file with ParserDispatcher
      4. Apply all matching rules via RuleRegistry
      5. Score via AuditScoringService
      6. Persist AuditResult + AuditIssue records
      7. Mark job COMPLETED (or FAILED on error)
    """

    def __init__(self):
        self.dispatcher = ParserDispatcher()
        self.scorer = AuditScoringService()

    def run(self, audit_job: AuditJob) -> AuditResult:
        """
        Execute the full audit pipeline for the given AuditJob.

        Returns:
            AuditResult instance on success.

        Raises:
            AuditJobError: on any fatal failure (job is marked FAILED before raising).
        """
        start_ms = int(time.time() * 1000)

        # Step 1: Mark job as RUNNING
        audit_job.status = AuditJob.Status.RUNNING
        audit_job.started_at = timezone.now()
        audit_job.save(update_fields=["status", "started_at", "updated_at"])
        logger.info("AuditJob %s started.", audit_job.id)

        try:
            # Step 2: Resolve file path
            audit_file = audit_job.audit_file
            mapping = (
                FileStorageMapping.objects.filter(file=audit_file)
                .order_by("-version_number")
                .first()
            )

            if not mapping:
                raise AuditJobError(
                    f"No FileStorageMapping found for AuditFile {audit_file.id} "
                    f"({audit_file.original_name}). Cannot locate file on storage."
                )

            file_path = mapping.storage_path

            # Normalise to absolute path for local storage providers
            if not os.path.isabs(file_path):
                file_path = os.path.join(str(settings.MEDIA_ROOT), file_path)

            if not os.path.exists(file_path):
                raise AuditJobError(
                    f"File not found on disk at '{file_path}'. "
                    "Ensure the storage provider has correctly written the file."
                )

            ext = os.path.splitext(audit_file.original_name)[-1].lower()
            logger.info(
                "AuditJob %s: parsing '%s' (ext=%s, path=%s)",
                audit_job.id,
                audit_file.original_name,
                ext,
                file_path,
            )

            # Step 3: Parse
            parse_result = self.dispatcher.parse(file_path, ext)

            if not parse_result.success:
                logger.warning(
                    "AuditJob %s: parser returned failure: %s",
                    audit_job.id,
                    parse_result.error,
                )
                # A failed parse still proceeds — the rules will surface the issue

            # Step 4: Apply rules
            issues = RuleRegistry.apply_all(parse_result, audit_job.audit_type)
            logger.info(
                "AuditJob %s: %d issue(s) raised by rules.", audit_job.id, len(issues)
            )

            # Step 5: Score
            scoring = self.scorer.calculate(issues)
            logger.info(
                "AuditJob %s: score=%.2f risk=%s",
                audit_job.id,
                scoring["overall_score"],
                scoring["risk_level"],
            )

            # Step 6a: Persist AuditResult
            audit_result = AuditResult.objects.create(
                audit_job=audit_job,
                overall_score=scoring["overall_score"],
                risk_level=scoring["risk_level"],
                summary=(
                    f"Audit completed. Score: {scoring['overall_score']}/100. "
                    f"Issues found: {scoring['issue_count']}. "
                    f"Risk level: {scoring['risk_level'].upper()}."
                ),
                extracted_text=parse_result.text[:50_000],
                extracted_entities={
                    "page_count": parse_result.page_count,
                    "row_count": parse_result.row_count,
                    "column_names": parse_result.column_names,
                    "sheet_names": parse_result.sheet_names,
                    "metadata": parse_result.metadata,
                    "parse_error": parse_result.error,
                },
                model_used="rule_engine_v1",
                tokens_used=0,
            )

            # Step 6b: Persist AuditIssues (bulk for performance)
            issue_objs = [
                AuditIssue(
                    audit_result=audit_result,
                    issue_code=iss.get("issue_code", ""),
                    issue_type=iss.get("issue_type", "rule_violation"),
                    severity=iss.get("severity", "low"),
                    title=iss.get("title", ""),
                    description=iss.get("description", ""),
                    page_number=iss.get("page_number"),
                    row_reference=iss.get("row_reference", ""),
                    suggested_fix=iss.get("suggested_fix", ""),
                    confidence_score=iss.get("confidence_score", 1.0),
                    metadata=iss.get("metadata", {}),
                )
                for iss in issues
            ]
            AuditIssue.objects.bulk_create(issue_objs)

            # Step 7: Mark COMPLETED
            end_ms = int(time.time() * 1000)
            audit_job.status = AuditJob.Status.COMPLETED
            audit_job.completed_at = timezone.now()
            audit_job.processing_time_ms = end_ms - start_ms
            audit_job.save(
                update_fields=["status", "completed_at", "processing_time_ms", "updated_at"]
            )

            # Update AuditFile status to stored
            audit_file.status = "stored"
            audit_file.save(update_fields=["status", "updated_at"])

            logger.info(
                "AuditJob %s completed in %dms.", audit_job.id, end_ms - start_ms
            )
            return audit_result

        except Exception as exc:
            logger.exception("AuditJob %s FAILED: %s", audit_job.id, exc)
            audit_job.status = AuditJob.Status.FAILED
            audit_job.failed_at = timezone.now()
            audit_job.error_message = str(exc)
            audit_job.save(
                update_fields=["status", "failed_at", "error_message", "updated_at"]
            )
            raise AuditJobError(str(exc)) from exc
