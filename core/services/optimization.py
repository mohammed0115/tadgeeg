"""
Performance Optimization Utilities
===================================
Batch processing, caching, and query optimization for OCR pipeline.
"""

import logging
from typing import List, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed

from django.core.cache import cache
from django.conf import settings

logger = logging.getLogger("finai")


class BatchProcessor:
    """Process documents in optimized batches"""

    def __init__(self, batch_size: int = 10, use_priority_queue: bool = True):
        self.batch_size = batch_size
        self.use_priority_queue = use_priority_queue

    def process_document_batch(self, document_ids: List[str]) -> dict:
        """
        Process multiple documents efficiently with priority routing.

        Args:
            document_ids: List of document UUIDs to process

        Returns:
            Dict with batch results and statistics
        """
        from apps.documents.tasks import process_document_task

        results = {
            "total": len(document_ids),
            "queued": 0,
            "failed": 0,
            "tasks": [],
        }

        try:
            for i, doc_id in enumerate(document_ids):
                # Route to priority queue every Nth document
                queue_name = "default"
                priority = 5
                
                if self.use_priority_queue and i % 3 == 0:
                    queue_name = "priority"
                    priority = 10

                try:
                    task = process_document_task.apply_async(
                        (doc_id,),
                        queue=queue_name,
                        priority=priority,
                    )
                    results["tasks"].append({
                        "document_id": doc_id,
                        "task_id": task.id,
                        "queue": queue_name,
                    })
                    results["queued"] += 1
                except Exception as e:
                    logger.error(f"Failed to queue document {doc_id}: {e}")
                    results["failed"] += 1

            logger.info(
                f"Batch processing: Queued {results['queued']}/{results['total']} documents"
            )
            return results

        except Exception as e:
            logger.error(f"Batch processing error: {e}")
            return {**results, "error": str(e)}

    @staticmethod
    def process_documents_parallel(document_ids: List[str], max_workers: int = 4) -> list:
        """
        Process OCR results in parallel (for data that's already extracted)

        Args:
            document_ids: List of document IDs
            max_workers: Number of parallel workers

        Returns:
            List of results
        """
        def process_single(doc_id):
            try:
                from apps.documents.models import Document
                return Document.objects.get(pk=doc_id)
            except Exception as e:
                logger.error(f"Error processing {doc_id}: {e}")
                return None

        results = []
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(process_single, doc_id): doc_id for doc_id in document_ids}

            for future in as_completed(futures):
                try:
                    result = future.result()
                    if result:
                        results.append(result)
                except Exception as e:
                    logger.error(f"Future execution error: {e}")

        return results


class CacheManager:
    """Manage caching for OCR pipeline data"""

    CACHE_KEYS = {
        "ocr_result": "ocr_result:{doc_id}",
        "extracted_data": "extracted_data:{doc_id}",
        "score_result": "score_result:{doc_id}",
        "health_check": "ocr_pipeline_health",
    }

    @staticmethod
    def cache_ocr_result(document_id: str, result: dict, timeout: int = 3600) -> bool:
        """Cache OCR processing result"""
        try:
            key = CacheManager.CACHE_KEYS["ocr_result"].format(doc_id=document_id)
            cache.set(key, result, timeout)
            return True
        except Exception as e:
            logger.warning(f"Failed to cache OCR result: {e}")
            return False

    @staticmethod
    def get_ocr_result(document_id: str) -> Optional[dict]:
        """Retrieve cached OCR result"""
        try:
            key = CacheManager.CACHE_KEYS["ocr_result"].format(doc_id=document_id)
            return cache.get(key)
        except Exception as e:
            logger.warning(f"Failed to get cached OCR result: {e}")
            return None

    @staticmethod
    def cache_extracted_data(document_id: str, data: dict, timeout: int = 7200) -> bool:
        """Cache extracted structured data"""
        try:
            key = CacheManager.CACHE_KEYS["extracted_data"].format(doc_id=document_id)
            cache.set(key, data, timeout)
            return True
        except Exception as e:
            logger.warning(f"Failed to cache extracted data: {e}")
            return False

    @staticmethod
    def get_extracted_data(document_id: str) -> Optional[dict]:
        """Retrieve cached extracted data"""
        try:
            key = CacheManager.CACHE_KEYS["extracted_data"].format(doc_id=document_id)
            return cache.get(key)
        except Exception as e:
            logger.warning(f"Failed to get cached extracted data: {e}")
            return None

    @staticmethod
    def invalidate_document_cache(document_id: str) -> bool:
        """Remove all cache entries for a document"""
        try:
            keys = [
                CacheManager.CACHE_KEYS["ocr_result"].format(doc_id=document_id),
                CacheManager.CACHE_KEYS["extracted_data"].format(doc_id=document_id),
                CacheManager.CACHE_KEYS["score_result"].format(doc_id=document_id),
            ]
            for key in keys:
                cache.delete(key)
            return True
        except Exception as e:
            logger.warning(f"Failed to invalidate cache: {e}")
            return False


class QueryOptimizer:
    """Optimize database queries for documents"""

    @staticmethod
    def get_documents_optimized(filters: dict = None, limit: int = 100):
        """
        Get documents with optimized queries (select_related, only)
        
        Args:
            filters: Dict of filter criteria
            limit: Max results
        """
        from apps.documents.models import Document

        qs = Document.objects.select_related(
            "organization",
            "uploaded_by",
            "extracted_data",
        ).prefetch_related(
            "page_results",
        ).only(
            "id",
            "organization_id",
            "uploaded_by_id",
            "original_filename",
            "processing_status",
            "ocr_confidence",
            "language",
            "created_at",
            "updated_at",
        )

        if filters:
            if "organization_id" in filters:
                qs = qs.filter(organization_id=filters["organization_id"])
            if "status" in filters:
                qs = qs.filter(processing_status=filters["status"])
            if "document_type" in filters:
                qs = qs.filter(document_type=filters["document_type"])

        return qs[:limit]

    @staticmethod
    def get_extracted_data_bulk(document_ids: List[str]) -> dict:
        """
        Fetch extracted data for multiple documents efficiently

        Args:
            document_ids: List of document IDs

        Returns:
            Dict mapping document_id to extracted data
        """
        from apps.documents.models import ExtractedData

        data_map = {}
        try:
            extracted_items = ExtractedData.objects.filter(
                document_id__in=document_ids
            ).only(
                "document_id",
                "raw_text",
                "structured_data",
                "validation_status",
            )

            for item in extracted_items:
                data_map[str(item.document_id)] = {
                    "raw_text": item.raw_text,
                    "structured_data": item.structured_data,
                    "validation_status": item.validation_status,
                }
        except Exception as e:
            logger.error(f"Bulk extraction fetch error: {e}")

        return data_map


def optimize_processing_pipeline(use_cache: bool = True, batch_size: int = 10) -> dict:
    """
    Get optimization recommendations for current system state

    Returns:
        Dict with recommendations and current metrics
    """
    from apps.documents.models import Document
    from django.utils import timezone
    from datetime import timedelta

    recommendations = {}

    try:
        # Check recent processing load
        one_hour_ago = timezone.now() - timedelta(hours=1)
        recent_processing = Document.objects.filter(
            processing_status=Document.ProcessingStatus.PROCESSING,
            updated_at__gte=one_hour_ago,
        ).count()

        if recent_processing > 50:
            recommendations["high_load"] = "Consider increasing worker concurrency"

        # Check for stuck documents
        stuck_threshold = timezone.now() - timedelta(minutes=30)
        stuck_docs = Document.objects.filter(
            processing_status=Document.ProcessingStatus.PROCESSING,
            updated_at__lt=stuck_threshold,
        ).count()

        if stuck_docs > 5:
            recommendations["stuck_documents"] = f"Investigate {stuck_docs} stuck documents"

        # Check failed documents
        failed_24h = Document.objects.filter(
            processing_status=Document.ProcessingStatus.FAILED,
            created_at__gte=timezone.now() - timedelta(hours=24),
        ).count()

        if failed_24h > 10:
            recommendations["high_failure_rate"] = f"High failure rate: {failed_24h} in 24h"

    except Exception as e:
        logger.error(f"Pipeline optimization analysis error: {e}")

    return {
        "use_cache_enabled": use_cache,
        "batch_size": batch_size,
        "recommendations": recommendations,
        "timestamp": timezone.now().isoformat(),
    }
