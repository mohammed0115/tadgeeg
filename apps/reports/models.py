import uuid
from django.db import models
from apps.authentication.models import User, Organization

class Report(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE)
    generated_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    title = models.CharField(max_length=255)
    report_type = models.CharField(max_length=50)
    language = models.CharField(max_length=5, default="en")
    period_from = models.CharField(max_length=10, blank=True)
    period_to = models.CharField(max_length=10, blank=True)
    data = models.JSONField(default=dict)
    narrative = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta:
        db_table = "reports"
        ordering = ["-created_at"]
    def __str__(self):
        return self.title
