from django.test import TestCase, override_settings

from apps.billing.services.retention import retention_due_summary
from apps.billing.tasks import report_retention_candidates


class RetentionCandidateTaskTests(TestCase):
    def test_empty_catalogue_is_non_destructive(self):
        summary = retention_due_summary()
        assert summary["subscriptions_checked"] == 0
        assert summary["destructive_action"] is False
        assert summary["due_attachments_by_organization"] == {}

    def test_task_returns_non_destructive_summary(self):
        summary = report_retention_candidates()
        assert summary["destructive_action"] is False

    def test_task_is_scheduled(self):
        from django.conf import settings
        assert settings.CELERY_BEAT_SCHEDULE["billing-report-retention-candidates"]["task"] == "billing.report_retention_candidates"
