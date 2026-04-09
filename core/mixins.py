"""
core/mixins.py
==============
Reusable abstract model mixins and DRF view mixins for the Tadgeeg platform.

Provides:
  - SoftDeleteModel   — abstract model with is_deleted/deleted_at/deleted_by +
                        SoftDeleteManager that auto-filters deleted rows.
  - SoftDeleteManager — default manager that excludes is_deleted=True rows.
  - OrganizationQuerySetMixin — DRF ViewSet mixin that auto-scopes querysets
                                to request.user.organization.
"""

import uuid
from django.db import models
from django.utils import timezone


# ─── Soft Delete ──────────────────────────────────────────────────────────────

class SoftDeleteQuerySet(models.QuerySet):
    """QuerySet with soft-delete helpers."""

    def delete(self, user=None):
        """Bulk soft-delete: set is_deleted=True on all rows in the queryset."""
        now = timezone.now()
        update_kwargs = {"is_deleted": True, "deleted_at": now}
        if user is not None:
            update_kwargs["deleted_by"] = user
        return self.update(**update_kwargs)

    def hard_delete(self):
        """Permanently delete rows — use only when legally required (GDPR erasure)."""
        return super().delete()

    def alive(self):
        return self.filter(is_deleted=False)

    def dead(self):
        return self.filter(is_deleted=True)


class SoftDeleteManager(models.Manager):
    """
    Default manager for soft-delete models.
    Automatically excludes rows where is_deleted=True.

    Usage:
        Model.objects.all()          → live rows only
        Model.all_objects.all()      → all rows including deleted
        Model.objects.dead()         → deleted rows only (via SoftDeleteQuerySet)
    """

    def get_queryset(self):
        return SoftDeleteQuerySet(self.model, using=self._db).filter(is_deleted=False)

    def alive(self):
        return self.get_queryset()

    def dead(self):
        return SoftDeleteQuerySet(self.model, using=self._db).filter(is_deleted=True)


class AllObjectsManager(models.Manager):
    """Bypass manager that returns ALL rows including soft-deleted ones."""

    def get_queryset(self):
        return SoftDeleteQuerySet(self.model, using=self._db)


class SoftDeleteModel(models.Model):
    """
    Abstract base for all models that use soft-delete instead of hard-delete.

    Subclasses should NOT redefine is_deleted / deleted_at / deleted_by.
    If they need to customize deleted_by FK (different related_name per model),
    override just the `deleted_by` field.

    Example:
        class Invoice(SoftDeleteModel):
            deleted_by = models.ForeignKey(
                User, on_delete=models.SET_NULL, null=True, blank=True,
                related_name="deleted_invoices",
            )
            ...
    """

    is_deleted = models.BooleanField(default=False, db_index=True)
    deleted_at = models.DateTimeField(null=True, blank=True)
    # deleted_by is intentionally omitted here — each subclass defines its own
    # FK with the correct related_name to avoid reverse accessor clashes.

    objects = SoftDeleteManager()
    all_objects = AllObjectsManager()

    class Meta:
        abstract = True

    def delete(self, user=None, *args, **kwargs):
        """
        Soft-delete this instance.

        Args:
            user: The User performing the delete (stored in deleted_by if the
                  subclass defines that field).
        """
        self.is_deleted = True
        self.deleted_at = timezone.now()

        update_fields = ["is_deleted", "deleted_at"]

        if user is not None and hasattr(self, "deleted_by_id"):
            self.deleted_by = user
            update_fields.append("deleted_by")

        if hasattr(self, "updated_at"):
            update_fields.append("updated_at")

        self.save(update_fields=update_fields)

    def restore(self, user=None):
        """Undo soft-delete."""
        self.is_deleted = False
        self.deleted_at = None

        update_fields = ["is_deleted", "deleted_at"]

        if hasattr(self, "updated_at"):
            update_fields.append("updated_at")

        self.save(update_fields=update_fields)


# ─── Organization Queryset Mixin ─────────────────────────────────────────────

class OrganizationQuerySetMixin:
    """
    DRF ViewSet mixin that automatically scopes all querysets to the
    request user's organization.

    Eliminates the recurring pattern:
        queryset.filter(organization=self.request.user.organization)

    Usage:
        class InvoiceViewSet(OrganizationQuerySetMixin, ModelViewSet):
            queryset = Invoice.objects.all()  # mixin narrows to org
            ...

    The mixin respects is_deleted via SoftDeleteManager automatically
    as long as the model uses SoftDeleteManager as its default manager.
    """

    organization_field = "organization"  # Override if FK has different name

    def get_queryset(self):
        qs = super().get_queryset()
        user = self.request.user

        if not user or not user.is_authenticated:
            return qs.none()

        org = getattr(user, "organization", None)
        if org is None:
            return qs.none()

        return qs.filter(**{self.organization_field: org})
