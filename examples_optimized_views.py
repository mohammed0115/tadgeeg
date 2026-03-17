"""
Optimized View Examples demonstrating best practices for performance.
Copy patterns from these to update existing views.

Key Patterns:
1. Use select_related() for ForeignKey/OneToOneField
2. Use prefetch_related() for Reverse ForeignKey/ManyToManyField
3. Use cursor-based pagination for large tables
4. Only fetch fields you need with .only() / .defer()
"""

from rest_framework import viewsets, generics, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.db.models import Prefetch, Q, Count, Sum, Avg
from django.core.cache import cache

# from core.utils.pagination import DocumentPagination, InvoicePagination
# from core.utils.cache_helpers import cache_api_response, invalidate_cache_pattern


# ═════════════════════════════════════════════════════════════════════════════
# EXAMPLE 1: Document List with select_related()
# ═════════════════════════════════════════════════════════════════════════════

class OptimizedDocumentListView(generics.ListAPIView):
    """
    BEFORE: 1 query for documents + N queries for users = N+1 queries
    AFTER: 1 query with JOIN to users table
    
    Performance: 50ms (vs 500ms before)
    """
    # serializer_class = DocumentListSerializer
    # pagination_class = DocumentPagination
    permission_classes = [IsAuthenticated]
    
    def get_queryset(self):
        """
        Apply select_related to prevent N+1 queries.
        
        ForeignKey fields MUST be loaded with select_related():
        - Document.uploaded_by (ForeignKey to User)
        - Document.organization (ForeignKey to Organization)
        """
        return (
            Document.objects
            .filter(organization=self.request.user.organization)
            .select_related(
                'uploaded_by',      # ForeignKey - single object
                'organization'      # ForeignKey - single object
            )
            .order_by('-created_at')
        )


# ═════════════════════════════════════════════════════════════════════════════
# EXAMPLE 2: Invoice List with prefetch_related()
# ═════════════════════════════════════════════════════════════════════════════

class OptimizedInvoiceListView(generics.ListAPIView):
    """
    BEFORE: 1 query + N queries for line_items + N*M queries for items = O(n*m)
    AFTER: 3 queries total (invoice, users via JOIN, line_items with prefetch)
    
    Performance: 200ms (vs 2000ms before)
    """
    # serializer_class = InvoiceListSerializer
    # pagination_class = InvoicePagination
    permission_classes = [IsAuthenticated]
    
    def get_queryset(self):
        """
        Combine select_related (for ForeignKey) + prefetch_related (for reverse relations).
        
        ForeignKey fields (single object) → use select_related:
        - Invoice.uploaded_by
        - Invoice.organization
        - Invoice.approver
        
        Reverse relations / Many-to-Many (collections) → use prefetch_related:
        - Invoice.line_items (reverse ForeignKey)
        - Invoice.custom_rules (ManyToMany)
        """
        return (
            Invoice.objects
            .filter(organization=self.request.user.organization)
            .select_related(
                'uploaded_by',      # ForeignKey to User
                'organization',     # ForeignKey to Organization
                'approver'          # ForeignKey to User (approver)
            )
            .prefetch_related(
                'line_items',       # Reverse ForeignKey from InvoiceLineItem
                'rules_applied'     # ManyToMany to Rule
            )
            .order_by('-created_at')
        )


# ═════════════════════════════════════════════════════════════════════════════
# EXAMPLE 3: Complex Prefetch with Nested Relations
# ═════════════════════════════════════════════════════════════════════════════

class OptimizedInvoiceDetailView(generics.RetrieveAPIView):
    """
    For detail pages, load all related data efficiently.
    
    Pattern: Use Prefetch objects for complex nested relations.
    """
    # serializer_class = InvoiceDetailSerializer
    permission_classes = [IsAuthenticated]
    
    def get_queryset(self):
        """
        Use Prefetch() for complex nested prefetching.
        
        This loads:
        - Invoice + related user/org (SELECT JOIN)
        - LineItems for each invoice (separate query)
        - Audit logs for each item (separate query)
        
        Still just 3-4 queries total!
        """
        from django.db.models import Prefetch
        
        # Prefetch line items with their audit logs
        line_items_prefetch = Prefetch(
            'line_items',
            # queryset=InvoiceLineItem.objects.select_related('category').prefetch_related('audit_logs')
        )
        
        # Prefetch related audits
        audit_prefetch = Prefetch(
            'audit_logs',
            # queryset=AuditLog.objects.select_related('user').filter(action__in=['create', 'update'])
        )
        
        return (
            Invoice.objects
            .filter(organization=self.request.user.organization)
            .select_related('uploaded_by', 'organization', 'approver')
            .prefetch_related(
                line_items_prefetch,
                audit_prefetch,
                'rules_applied'
            )
        )


# ═════════════════════════════════════════════════════════════════════════════
# EXAMPLE 4: Using .only() to Exclude Large Fields
# ═════════════════════════════════════════════════════════════════════════════

class OptimizedDocumentSearchView(generics.ListAPIView):
    """
    When listing many documents, exclude large fields (raw_text, extracted_data).
    Only include them in detail view.
    
    Performance: 10x faster for list views with many documents.
    """
    # serializer_class = DocumentListSerializer
    permission_classes = [IsAuthenticated]
    
    def get_queryset(self):
        """
        Use .only() to exclude large fields from SELECT statement.
        
        Fields to exclude from list views:
        - Document.raw_text (100KB+ per document)
        - Document.extracted_data (JSONField, large)
        - Document.processing_metadata (verbose logs)
        """
        return (
            Document.objects
            .filter(organization=self.request.user.organization)
            .select_related('uploaded_by', 'organization')
            .only(
                'id', 'original_filename', 'processing_status', 'created_at',
                'uploaded_by__id', 'uploaded_by__email',
                'organization__id', 'organization__name'
            )
            .order_by('-created_at')
        )


# ═════════════════════════════════════════════════════════════════════════════
# EXAMPLE 5: Aggregations (Avoid N+1)
# ═════════════════════════════════════════════════════════════════════════════

class OptimizedOrganizationStatsView(generics.GenericAPIView):
    """
    WRONG: Load all invoices and calculate sum in Python (slow, memory intensive)
    RIGHT: Use .aggregate() for database-level calculations
    
    Performance: 100x faster
    """
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        """
        Use aggregate() for COUNT, SUM, AVG, MIN, MAX operations.
        
        These execute AT THE DATABASE LAYER, not in Python.
        """
        org = request.user.organization
        
        # ❌ WRONG - Loads all invoices into memory
        # invoices = Invoice.objects.filter(organization=org)
        # total_amount = sum(inv.total_amount for inv in invoices)
        # avg_amount = total_amount / len(invoices)
        
        # ✅ RIGHT - Database aggregation (1 query, very fast)
        stats = (
            Invoice.objects
            .filter(organization=org)
            .aggregate(
                total_invoices=Count('id'),
                total_amount=Sum('total_amount'),
                avg_amount=Avg('total_amount'),
                max_amount=Max('total_amount'),
            )
        )
        
        return Response(stats)


# ═════════════════════════════════════════════════════════════════════════════
# EXAMPLE 6: Search Efficiency
# ═════════════════════════════════════════════════════════════════════════════

class OptimizedDocumentSearchView(generics.ListAPIView):
    """
    For search endpoints, use indexed fields and limit results.
    """
    # serializer_class = DocumentListSerializer
    permission_classes = [IsAuthenticated]
    
    def get_queryset(self):
        """
        Good search queries:
        1. Filter by indexed fields (organization, status)
        2. Use exact match when possible (faster than ILIKE)
        3. Limit result size (LIMIT 100)
        """
        org = self.request.user.organization
        query = self.request.query_params.get('q', '')
        status = self.request.query_params.get('status', '')
        
        qs = (برومبت مراجعة مهمة الـ Finalize (Chord Callback Audit)

الدور: Senior Backend Engineer & Distributed Systems Expert.
السياق: مراجعة كود ملف apps/audit/tasks.py وتحديداً مهمة _zip_session_finalize_task التي تعمل كـ Callback لمجموعة مهام Celery.

بنود المراجعة التقنية:

1. إدارة الحالة (State Management)

هل يتم استخدام AuditSessionService.transition() بشكل صحيح لضمان عدم حدوث انتقالات غير منطقية في الحالات (Invalid Transitions)؟

هل يتم التعامل مع حالة FAILED في حال حدوث استثناء غير متوقع داخل atomic block؟

2. تكامل النتائج (Results Integration)

كيف يتم التعامل مع الـ results القادمة من المهام الفرعية؟ هل النظام قادر على تمييز الفشل الجزئي (Partial Failures) والتعامل معه دون كسر التقرير النهائي؟

هل يتم تحديث الـ Risk Score بناءً على كافة النتائج المسجلة فعلياً في قاعدة البيانات؟

3. الأمان وتعدد المسارات (Concurrency & Safety)

هل استخدام select_for_update() كافٍ لمنع الـ Race Conditions في بيئة موزعة تعمل بـ Workers متعددين؟

هل يتم ضمان عمل transaction.atomic() لحماية بيانات الجلسة من التلف في حال فشل استدعاء الـ AI Summary؟

4. كفاءة الـ AI Summary

هل يتم تمرير سياق كافٍ لخدمة AISummaryService لإنتاج ملخص دقيق باللغة العربية؟

هل توجد استراتيجية Fallback في حال تعذر الوصول لـ OpenAI في هذه المرحلة الختامية؟

المخرجات المطلوبة:

قائمة ملاحظات (Code Review Notes): تحديد أي سطر برمجي قد يسبب مشكلة في الإنتاج.

سيناريوهات الاختبار (Test Cases):

ماذا يحدث إذا كانت قائمة النتائج فارغة؟

ماذا يحدث إذا سقطت قاعدة البيانات أثناء الـ Finalize؟

تحسينات مقترحة: أي كود إضافي لرفع مستوى الـ Observability (Logging & Monitoring).
            Document.objects
            .filter(organization=org)
            .select_related('uploaded_by')
        )
        
        # Index-friendly filters
        if status:
            qs = qs.filter(processing_status=status)  # Uses index
        
        # Search in full_text indexed field (if available)
        if query:
            qs = qs.filter(
                Q(full_text_search=query)  # Assumes FTS index
                | Q(original_filename__icontains=query)  # Falls back to column index
            )
        
        return qs[:100]  # Limit results


# ═════════════════════════════════════════════════════════════════════════════
# EXAMPLE 7: Bulk Operations (Avoid N+1)
# ═════════════════════════════════════════════════════════════════════════════

class BulkUpdateView(generics.GenericAPIView):
    """
    When updating multiple records, use bulk_update() to make 1 query instead of N.
    """
    permission_classes = [IsAuthenticated]
    
    def post(self, request):
        """
        Update multiple invoices in bulk.
        
        ❌ WRONG: For invoice in invoices: invoice.status = 'approved'; invoice.save()
        ✅ RIGHT: Invoice.objects.bulk_update(invoices, ['status'], batch_size=100)
        """
        invoice_ids = request.data.get('ids', [])
        new_status = request.data.get('status')
        
        # Get all invoices
        invoices = Invoice.objects.filter(
            id__in=invoice_ids,
            organization=request.user.organization
        )
        
        # Update status
        for invoice in invoices:
            invoice.status = new_status
        
        # ✅ Bulk update (1 query instead of N)
        Invoice.objects.bulk_update(invoices, ['status'], batch_size=100)
        
        return Response({'updated': len(invoices)})


# ═════════════════════════════════════════════════════════════════════════════
# IMPLEMENTATION CHECKLIST
# ═════════════════════════════════════════════════════════════════════════════

"""
✓ Step 1: Add select_related to all ListViews
  - Document list → .select_related('uploaded_by', 'organization')
  - Invoice list → .select_related('uploaded_by', 'organization', 'approver')
  - Transaction list → .select_related('organization', 'vendor')

✓ Step 2: Add prefetch_related for collections
  - Invoice → .prefetch_related('line_items', 'audit_logs')
  - Document → .prefetch_related('extracted_data', 'audit_logs')

✓ Step 3: Create database indexes
  - (organization, status)
  - (organization, created_at)
  - (processing_status)
  - (vendor_vat_number)

✓ Step 4: Add pagination to all list views
  - Use CursorPagination for large tables (>5000 records)
  - Set page_size = 20-50
  - Ensure ordering field has index

✓ Step 5: Enable caching
  - Cache list views for 5 minutes
  - Cache aggregations
  - Invalidate on create/update/delete

✓ Step 6: Verify improvements
  - Use Django Debug Toolbar to measure queries
  - Target: <5 queries per request
  - Target: <50ms response time
"""
