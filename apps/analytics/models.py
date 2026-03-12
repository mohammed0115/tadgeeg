import uuid

from django.db import models

from apps.authentication.models import Organization, User


class NLQueryHistory(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="nl_query_history")
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name="nl_query_history")
    query = models.TextField()
    interpretation = models.TextField(blank=True)
    filters = models.JSONField(default=dict)
    excludes = models.JSONField(default=dict)
    order_by = models.JSONField(default=list)
    result_count = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "analytics_nl_query_history"
        ordering = ["-created_at"]

    def __str__(self):
        return self.query[:80]
