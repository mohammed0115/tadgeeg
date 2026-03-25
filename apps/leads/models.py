import uuid
from django.db import models
from django.conf import settings


class ContactLead(models.Model):
    class Status(models.TextChoices):
        NEW = 'new', 'New'
        IN_PROGRESS = 'in_progress', 'In Progress'
        QUALIFIED = 'qualified', 'Qualified'
        CONVERTED = 'converted', 'Converted'
        CLOSED = 'closed', 'Closed'
        SPAM = 'spam', 'Spam'

    class Source(models.TextChoices):
        CONTACT_FORM = 'contact_form', 'Contact Form'
        PRICING_INQUIRY = 'pricing_inquiry', 'Pricing Inquiry'
        DEMO_REQUEST = 'demo_request', 'Demo Request'
        PARTNERSHIP = 'partnership', 'Partnership'
        OTHER = 'other', 'Other'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    full_name = models.CharField(max_length=200)
    email = models.EmailField()
    phone = models.CharField(max_length=30, blank=True)
    company = models.CharField(max_length=200, blank=True)
    country = models.CharField(max_length=100, blank=True, default='Saudi Arabia')
    subject = models.CharField(max_length=300)
    message = models.TextField()
    source = models.CharField(max_length=30, choices=Source.choices, default=Source.CONTACT_FORM)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.NEW)
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='assigned_leads',
    )
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Contact Lead'
        verbose_name_plural = 'Contact Leads'

    def __str__(self):
        return f"{self.full_name} ({self.email}) — {self.status}"


class LeadNote(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    lead = models.ForeignKey(ContactLead, on_delete=models.CASCADE, related_name='notes')
    note = models.TextField()
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name='lead_notes',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']
        verbose_name = 'Lead Note'

    def __str__(self):
        return f"Note on {self.lead.full_name}"
