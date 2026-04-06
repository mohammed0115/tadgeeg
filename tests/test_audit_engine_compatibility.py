from unittest.mock import MagicMock, patch

from django.test import TestCase


class AuditEngineCompatibilityTests(TestCase):
    @patch("apps.audit_engine.tasks.LegacyAuditOrchestratorAdapter")
    @patch("apps.audit_engine.tasks.AuditJob")
    def test_run_audit_task_uses_legacy_adapter(self, mock_job_model, mock_adapter):
        from apps.audit_engine.tasks import run_audit_task

        job = MagicMock()
        job.id = "job-123"
        job.document_id = "doc-1"
        job.organization_id = "org-1"
        job.status = "pending"
        mock_job_model.objects.get.return_value = job

        adapter_instance = mock_adapter.return_value
        adapter_instance.run.return_value = job

        run_audit_task(job.id)

        mock_adapter.assert_called_once()
        adapter_instance.run.assert_called_once_with(job)
