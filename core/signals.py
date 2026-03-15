"""
Django signals for automatic cache invalidation on model changes.
Prevents stale cached data when models are created/updated/deleted.
"""

from django.db.models.signals import post_save, post_delete, pre_save
from django.dispatch import receiver
from django.core.cache import cache
from django.utils.decorators import disable_for_loaddata


@receiver(post_save, sender='documents.Document')
@disable_for_loaddata
def invalidate_document_cache(sender, instance, created, **kwargs):
    """
    Invalidate document caches when document is created/updated.
    
    Clears:
    - Document list caches for the organization
    - Document detail cache
    - Organization stats caches
    """
    from apps.documents.models import Document
    
    cache_patterns = [
        # List views
        f'doc_list:{instance.organization_id}:*',
        f'document_list:{instance.organization_id}:*',
        
        # Detail view
        f'doc_detail:{instance.id}',
        f'document_detail:{instance.id}',
        
        # Organization stats
        f'org_stats:{instance.organization_id}:*',
        
        # Search results
        f'doc_search:{instance.organization_id}:*',
        
        # Aggregations
        f'doc_aggregate:{instance.organization_id}:*',
    ]
    
    for pattern in cache_patterns:
        try:
            if hasattr(cache, 'delete_pattern'):
                cache.delete_pattern(f"{pattern}*")
            else:
                # For non-Redis backends, delete common variations
                cache.delete(pattern)
        except Exception as e:
            print(f"Warning: Failed to invalidate cache {pattern}: {e}")


@receiver(post_delete, sender='documents.Document')
@disable_for_loaddata
def invalidate_document_on_delete(sender, instance, **kwargs):
    """Invalidate caches when document is deleted"""
    from apps.documents.models import Document
    
    cache_patterns = [
        f'doc_list:{instance.organization_id}:*',
        f'document_list:{instance.organization_id}:*',
        f'doc_detail:{instance.id}',
        f'org_stats:{instance.organization_id}:*',
        f'doc_aggregate:{instance.organization_id}:*',
    ]
    
    for pattern in cache_patterns:
        try:
            if hasattr(cache, 'delete_pattern'):
                cache.delete_pattern(f"{pattern}*")
        except Exception:
            pass


@receiver(post_save, sender='invoices.Invoice')
@disable_for_loaddata
def invalidate_invoice_cache(sender, instance, created, **kwargs):
    """
    Invalidate invoice caches when invoice is created/updated.
    """
    cache_patterns = [
        # List views
        f'inv_list:{instance.organization_id}:*',
        f'invoice_list:{instance.organization_id}:*',
        
        # Detail view
        f'inv_detail:{instance.id}',
        f'invoice_detail:{instance.id}',
        
        # Organization invoices
        f'org_invoices:{instance.organization_id}:*',
        
        # Invoice by vendor
        f'inv_vendor:{instance.vendor_id}:*' if hasattr(instance, 'vendor_id') else None,
        
        # Approval queues
        f'inv_approvals:{instance.organization_id}:*',
        
        # Reports/Analytics
        f'org_analytics:{instance.organization_id}:*',
    ]
    
    for pattern in [p for p in cache_patterns if p]:
        try:
            if hasattr(cache, 'delete_pattern'):
                cache.delete_pattern(f"{pattern}*")
        except Exception:
            pass


@receiver(post_delete, sender='invoices.Invoice')
@disable_for_loaddata
def invalidate_invoice_on_delete(sender, instance, **kwargs):
    """Invalidate caches when invoice is deleted"""
    cache_patterns = [
        f'inv_list:{instance.organization_id}:*',
        f'invoice_list:{instance.organization_id}:*',
        f'inv_detail:{instance.id}',
        f'org_invoices:{instance.organization_id}:*',
        f'org_analytics:{instance.organization_id}:*',
    ]
    
    for pattern in cache_patterns:
        try:
            if hasattr(cache, 'delete_pattern'):
                cache.delete_pattern(f"{pattern}*")
        except Exception:
            pass


@receiver(post_save, sender='transactions.Transaction')
@disable_for_loaddata
def invalidate_transaction_cache(sender, instance, created, **kwargs):
    """
    Invalidate transaction caches when transaction is created/updated.
    """
    cache_patterns = [
        # List views
        f'txn_list:{instance.organization_id}:*',
        f'transaction_list:{instance.organization_id}:*',
        
        # By vendor
        f'txn_vendor:{instance.vendor_name}:*' if hasattr(instance, 'vendor_name') else None,
        
        # By date range
        f'txn_date_range:{instance.organization_id}:*',
        
        # Analytics
        f'org_analytics:{instance.organization_id}:*',
        f'org_reports:{instance.organization_id}:*',
    ]
    
    for pattern in [p for p in cache_patterns if p]:
        try:
            if hasattr(cache, 'delete_pattern'):
                cache.delete_pattern(f"{pattern}*")
        except Exception:
            pass


@receiver(post_save, sender='audit.AuditLog')
@disable_for_loaddata
def invalidate_audit_cache(sender, instance, created, **kwargs):
    """
    Invalidate audit caches when log is created.
    """
    if not created:
        return
    
    cache_patterns = [
        f'audit_logs:{instance.organization_id}:*',
        f'audit_user:{instance.user_id}:*' if hasattr(instance, 'user_id') else None,
        f'audit_entity:{instance.entity_type}:*' if hasattr(instance, 'entity_type') else None,
    ]
    
    for pattern in [p for p in cache_patterns if p]:
        try:
            if hasattr(cache, 'delete_pattern'):
                cache.delete_pattern(f"{pattern}*")
        except Exception:
            pass


def clear_all_caches():
    """
    DANGEROUS: Clear all caches. Use sparingly (e.g., after bulk operations).
    """
    cache.clear()
    print("All caches cleared")


def clear_org_caches(organization_id):
    """Clear all caches for a specific organization"""
    clear_patterns = [
        f'doc_list:{organization_id}:*',
        f'inv_list:{organization_id}:*',
        f'txn_list:{organization_id}:*',
        f'org_stats:{organization_id}:*',
        f'org_analytics:{organization_id}:*',
        f'org_reports:{organization_id}:*',
    ]
    
    for pattern in clear_patterns:
        try:
            if hasattr(cache, 'delete_pattern'):
                cache.delete_pattern(f"{pattern}*")
        except Exception:
            pass


# ─────────────────────────────────────────────────────────────────────────────
# Registration: Add to your app's apps.py
# ─────────────────────────────────────────────────────────────────────────────

"""
# In finai_backend/apps.py or wherever you define AppConfigs:

from django.apps import AppConfig

class CoreConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'core'
    
    def ready(self):
        # Import signals when app is ready
        import core.signals  # This file!
        # or from . import signals


# In apps/documents/apps.py:

from django.apps import AppConfig

class DocumentsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.documents'
    
    def ready(self):
        # Import signals when app is ready
        # Signal receivers defined in core.signals
        pass
"""
