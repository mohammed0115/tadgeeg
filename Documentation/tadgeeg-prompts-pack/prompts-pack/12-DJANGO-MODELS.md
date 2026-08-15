# 🗄️ 12 — نماذج Django (Models)

> Prompts لتطوير النماذج وقاعدة البيانات

---

## 🎯 Prompt 12.1 — إنشاء Model جديد

```
في مشروع Tadgeeg AI، أحتاج إنشاء model جديد:

# مثال: Model لـ "تنبيهات النظام"

# المطلوب:

## 1. الـ Model:
```python
# apps/notifications/models.py
import uuid
from django.db import models
from django.utils.translation import gettext_lazy as _
from core.mixins import SoftDeleteModel
from apps.authentication.models import User, Organization

class SystemAlert(SoftDeleteModel):
    """تنبيهات النظام للمنظمة"""
    
    class Severity(models.TextChoices):
        INFO = 'info', _('Info')
        SUCCESS = 'success', _('Success')
        WARNING = 'warning', _('Warning')
        ERROR = 'error', _('Error')
        CRITICAL = 'critical', _('Critical')
    
    class Type(models.TextChoices):
        SECURITY = 'security', _('Security')
        COMPLIANCE = 'compliance', _('Compliance')
        FRAUD = 'fraud', _('Fraud Detection')
        SYSTEM = 'system', _('System')
        BILLING = 'billing', _('Billing')
        AUDIT = 'audit', _('Audit')
    
    # Identity
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name='system_alerts',
        verbose_name=_('Organization'),
    )
    
    # Content
    type = models.CharField(_('Type'), max_length=20, choices=Type.choices, db_index=True)
    severity = models.CharField(_('Severity'), max_length=20, choices=Severity.choices, db_index=True)
    title = models.CharField(_('Title'), max_length=200)
    title_ar = models.CharField(_('Title (Arabic)'), max_length=200, blank=True)
    message = models.TextField(_('Message'))
    message_ar = models.TextField(_('Message (Arabic)'), blank=True)
    
    # Metadata
    icon = models.CharField(_('Icon'), max_length=50, blank=True, help_text='Lucide icon name')
    link = models.URLField(_('Link'), blank=True, help_text='URL to alert details')
    metadata = models.JSONField(_('Metadata'), default=dict, blank=True)
    
    # State
    is_read = models.BooleanField(_('Read'), default=False, db_index=True)
    read_at = models.DateTimeField(_('Read At'), null=True, blank=True)
    is_dismissed = models.BooleanField(_('Dismissed'), default=False)
    dismissed_at = models.DateTimeField(_('Dismissed At'), null=True, blank=True)
    
    # Recipients
    recipients = models.ManyToManyField(
        User,
        related_name='received_alerts',
        blank=True,
        verbose_name=_('Recipients'),
    )
    
    # Source
    source_type = models.CharField(
        _('Source Type'), max_length=50, blank=True,
        help_text='e.g., "invoice", "audit_session"'
    )
    source_id = models.UUIDField(_('Source ID'), null=True, blank=True)
    
    # Actions
    actions = models.JSONField(
        _('Actions'), default=list, blank=True,
        help_text='[{label, url, type}, ...]'
    )
    
    # Expiry
    expires_at = models.DateTimeField(_('Expires At'), null=True, blank=True)
    
    class Meta:
        verbose_name = _('System Alert')
        verbose_name_plural = _('System Alerts')
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['organization', 'is_read', '-created_at']),
            models.Index(fields=['type', 'severity']),
            models.Index(fields=['source_type', 'source_id']),
        ]
    
    def __str__(self):
        return f"[{self.severity}] {self.title}"
    
    def mark_read(self, user=None):
        if not self.is_read:
            self.is_read = True
            self.read_at = timezone.now()
            self.save(update_fields=['is_read', 'read_at'])
    
    def dismiss(self):
        self.is_dismissed = True
        self.dismissed_at = timezone.now()
        self.save(update_fields=['is_dismissed', 'dismissed_at'])
    
    @property
    def is_expired(self):
        return self.expires_at and self.expires_at < timezone.now()
    
    @property
    def severity_color(self):
        colors = {
            'info': '#3b82f6',
            'success': '#10B981',
            'warning': '#f59e0b',
            'error': '#ef4444',
            'critical': '#dc2626',
        }
        return colors.get(self.severity, '#64748b')
```

## 2. الـ Manager (اختياري):
```python
class SystemAlertManager(models.Manager):
    def for_user(self, user):
        return self.filter(
            organization=user.organization,
            recipients=user,
            is_dismissed=False,
        )
    
    def unread_count(self, user):
        return self.for_user(user).filter(is_read=False).count()
    
    def critical(self, organization):
        return self.filter(
            organization=organization,
            severity__in=['critical', 'error'],
            is_dismissed=False,
        )

# في Model:
class SystemAlert(SoftDeleteModel):
    # ... الحقول
    
    objects = SystemAlertManager()
```

## 3. الـ Migration:
```bash
python manage.py makemigrations notifications
python manage.py migrate
```

## 4. الـ Admin:
```python
# apps/notifications/admin.py
from django.contrib import admin
from .models import SystemAlert

@admin.register(SystemAlert)
class SystemAlertAdmin(admin.ModelAdmin):
    list_display = ['title', 'type', 'severity', 'organization', 'is_read', 'created_at']
    list_filter = ['type', 'severity', 'is_read', 'created_at']
    search_fields = ['title', 'message', 'organization__name']
    raw_id_fields = ['organization']
    filter_horizontal = ['recipients']
    readonly_fields = ['id', 'created_at', 'updated_at']
```

## 5. الـ Tests:
```python
# tests/test_notifications.py
import pytest
from apps.notifications.models import SystemAlert
from tests.factories import OrganizationFactory, UserFactory

@pytest.mark.django_db
def test_create_alert():
    org = OrganizationFactory()
    alert = SystemAlert.objects.create(
        organization=org,
        type='compliance',
        severity='warning',
        title='Test Alert',
        message='Test message',
    )
    assert alert.id is not None
    assert not alert.is_read

@pytest.mark.django_db
def test_mark_read():
    alert = SystemAlertFactory()
    alert.mark_read()
    assert alert.is_read
    assert alert.read_at is not None
```

أعطني الـ Model + Manager + Admin + Migration + Tests.
```

---

## 🎯 Prompt 12.2 — تعديل Model موجود (Migration)

```
في مشروع Tadgeeg AI، أحتاج إضافة حقول جديدة لـ Invoice model:

# المطلوب:

## 1. التعديلات على Model:
```python
# apps/invoices/models.py
class Invoice(SoftDeleteModel):
    # ... الحقول الموجودة
    
    # New fields
    purchase_order = models.ForeignKey(
        'documents.PurchaseOrder',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='related_invoices',
        verbose_name=_('Purchase Order'),
    )
    
    received_at = models.DateField(
        _('Received Date'), null=True, blank=True,
        help_text='Actual delivery/service date'
    )
    
    payment_terms_days = models.IntegerField(
        _('Payment Terms (Days)'), default=30
    )
    
    is_recurring = models.BooleanField(_('Recurring'), default=False)
    recurring_frequency = models.CharField(
        _('Recurring Frequency'), max_length=20, blank=True,
        choices=[('weekly', 'Weekly'), ('monthly', 'Monthly'), ('quarterly', 'Quarterly'), ('yearly', 'Yearly')]
    )
    
    tags = models.JSONField(_('Tags'), default=list, blank=True)
```

## 2. إنشاء Migration:
```bash
python manage.py makemigrations invoices --name add_invoice_extended_fields
```

## 3. مراجعة الـ Migration المُولّد:
```python
# apps/invoices/migrations/0XXX_add_invoice_extended_fields.py
from django.db import migrations, models

class Migration(migrations.Migration):
    dependencies = [
        ('invoices', '0XXX_previous'),
        ('documents', '0XXX_purchase_order'),
    ]
    
    operations = [
        migrations.AddField(
            model_name='invoice',
            name='purchase_order',
            field=models.ForeignKey(
                blank=True, null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='related_invoices',
                to='documents.purchaseorder',
            ),
        ),
        # ... etc
    ]
```

## 4. Data Migration (إذا احتجت):
```python
# apps/invoices/migrations/0XXX_data_migration.py
from django.db import migrations

def populate_payment_terms(apps, schema_editor):
    Invoice = apps.get_model('invoices', 'Invoice')
    for invoice in Invoice.objects.filter(payment_terms_days__isnull=True):
        # default 30 days
        invoice.payment_terms_days = 30
        invoice.save(update_fields=['payment_terms_days'])

def reverse(apps, schema_editor):
    pass

class Migration(migrations.Migration):
    dependencies = [
        ('invoices', '0XXX_add_invoice_extended_fields'),
    ]
    
    operations = [
        migrations.RunPython(populate_payment_terms, reverse),
    ]
```

## 5. اختبر قبل التطبيق:
```bash
# اختبر على نسخة من DB
python manage.py migrate --plan
python manage.py migrate invoices --fake-initial  # إذا لزم
python manage.py migrate
```

## 6. تحديث الـ Serializers والـ Forms:
```python
# apps/invoices/serializers.py
class InvoiceSerializer(serializers.ModelSerializer):
    class Meta:
        model = Invoice
        fields = '__all__'  # أو حدّد الحقول
```

# نقاط مهمة:
1. **النسخ الاحتياطية**: خذ نسخة من `db_runtime.sqlite3` قبل الـ migration
2. **Reversibility**: تأكد من إمكانية الـ reverse migration
3. **Default Values**: حدّد defaults للحقول الجديدة
4. **NULL vs Blank**: NULL في DB، blank في الـ admin/forms
5. **Indexes**: أضف indexes على الحقول التي تُستخدم في filters
6. **Multi-tenant**: الحقل `organization` موجود ويعمل

أعطني:
1. الـ Model updates
2. الـ Migration files
3. الـ Data migration إذا احتجت
4. تحديثات الـ Serializers
5. خطة rollback
```

---

## 🎯 Prompt 12.3 — Mixins وأنماط شائعة

```
في مشروع Tadgeeg AI، الـ `core/mixins.py` يحتوي على mixins مشتركة.

# المطلوب: مراجعة وتطوير الـ mixins:

## 1. SoftDeleteModel:
```python
# core/mixins.py
import uuid
from django.db import models
from django.utils import timezone

class SoftDeleteQuerySet(models.QuerySet):
    def delete(self):
        return super().update(is_deleted=True, deleted_at=timezone.now())
    
    def hard_delete(self):
        return super().delete()
    
    def alive(self):
        return self.filter(is_deleted=False)
    
    def deleted(self):
        return self.filter(is_deleted=True)

class SoftDeleteManager(models.Manager):
    def get_queryset(self):
        return SoftDeleteQuerySet(self.model, using=self._db).alive()
    
    def all_with_deleted(self):
        return SoftDeleteQuerySet(self.model, using=self._db)
    
    def deleted_only(self):
        return SoftDeleteQuerySet(self.model, using=self._db).deleted()

class TimestampedModel(models.Model):
    """Adds created_at and updated_at"""
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        abstract = True

class SoftDeleteModel(TimestampedModel):
    """Soft delete with manager"""
    is_deleted = models.BooleanField(default=False, db_index=True)
    deleted_at = models.DateTimeField(null=True, blank=True)
    deleted_by = models.ForeignKey(
        'authentication.User',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='+',
    )
    
    objects = SoftDeleteManager()
    all_objects = models.Manager()  # includes deleted
    
    class Meta:
        abstract = True
    
    def delete(self, using=None, keep_parents=False, user=None):
        self.is_deleted = True
        self.deleted_at = timezone.now()
        if user:
            self.deleted_by = user
        self.save(update_fields=['is_deleted', 'deleted_at', 'deleted_by'])
    
    def hard_delete(self, using=None):
        super().delete(using=using)
    
    def restore(self):
        self.is_deleted = False
        self.deleted_at = None
        self.deleted_by = None
        self.save(update_fields=['is_deleted', 'deleted_at', 'deleted_by'])
```

## 2. AuditableModel:
```python
class AuditableModel(models.Model):
    """Tracks who created and updated"""
    created_by = models.ForeignKey(
        'authentication.User',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='+',
    )
    updated_by = models.ForeignKey(
        'authentication.User',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='+',
    )
    
    class Meta:
        abstract = True
```

## 3. UUIDModel:
```python
class UUIDModel(models.Model):
    """Use UUID as primary key"""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    
    class Meta:
        abstract = True
```

## 4. OrganizationOwnedModel:
```python
class OrganizationOwnedModel(models.Model):
    """Multi-tenant: belongs to an organization"""
    organization = models.ForeignKey(
        'authentication.Organization',
        on_delete=models.CASCADE,
        related_name='+',
    )
    
    class Meta:
        abstract = True
        indexes = [models.Index(fields=['organization'])]
```

## 5. Combining:
```python
# مثال على الاستخدام
class Invoice(UUIDModel, OrganizationOwnedModel, SoftDeleteModel, AuditableModel):
    """All mixins combined"""
    invoice_number = models.CharField(max_length=100)
    # ... etc
```

## 6. GDPR Hard Delete:
```python
# core/services/gdpr.py
from django.db import transaction

class GDPRService:
    """GDPR-compliant data deletion"""
    
    @transaction.atomic
    def hard_delete_user_data(self, user):
        """Permanently delete all user data (GDPR Right to Erasure)"""
        # Delete owned records (hard)
        for model_class in [Invoice, Document, Notification, ...]:
            model_class.all_objects.filter(uploaded_by=user).hard_delete()
        
        # Anonymize records that can't be deleted
        AuditLog.objects.filter(user=user).update(
            user=None,
            user_email_anonymized=hash_email(user.email)
        )
        
        # Delete the user
        user.delete()  # hard delete
        
        # Log the deletion (without PII)
        GDPRDeletionLog.objects.create(
            user_id_hash=hash_user_id(user.id),
            deleted_at=timezone.now(),
            requested_by_ip=...
        )
```

أعطني:
1. الـ Mixins الكاملة
2. الـ GDPR service
3. أمثلة على استخدامها
4. Tests
5. انظر `Documentation/GDPR_HARD_DELETE_IMPLEMENTATION.md` للمرجع
```

---

## ✅ Checklist

- [ ] Models تستخدم SoftDeleteModel
- [ ] Migrations تعمل في الاتجاهين (forward & reverse)
- [ ] Indexes صحيحة على الحقول الـ filtered
- [ ] Multi-tenant filtering مطبّق
- [ ] GDPR hard delete متاح
- [ ] Admin محدّث
- [ ] Tests تغطي الـ models

---

**📌 انتقل لـ `13-AI-OCR-PIPELINE.md`**
