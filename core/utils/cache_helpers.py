"""
Query result caching utilities for Django REST Framework.
Provides smart caching with automatic invalidation.
"""

import hashlib
import json
from functools import wraps
from django.core.cache import cache
from django.utils.decorators import method_decorator
from rest_framework.decorators import api_view


def build_cache_key(prefix, **kwargs):
    """
    Generate a consistent cache key from a prefix and parameters.
    
    Example:
        key = build_cache_key('doc_list', org_id=5, status='processed')
        # Returns: 'doc_list:a7f3c9e2d1b4f6a8'
    """
    key_data = json.dumps(kwargs, sort_keys=True, default=str)
    hash_val = hashlib.md5(key_data.encode()).hexdigest()
    return f"{prefix}:{hash_val}"


def cache_api_response(
    timeout=300,  # 5 minutes
    key_prefix=None,
    cache_get_only=False  # Only cache GET requests
):
    """
    Decorator to cache API view responses.
    
    Args:
        timeout: Cache duration in seconds (default: 5 minutes)
        key_prefix: Custom prefix for cache key (auto-generated if None)
        cache_get_only: Only cache GET requests (True for read-only views)
    
    Example:
        @cache_api_response(timeout=600, cache_get_only=True)
        def document_list(request):
            documents = Document.objects.all()
            return Response(DocumentSerializer(documents, many=True).data)
    """
    def decorator(view_func):
        @wraps(view_func)
        def wrapper(request, *args, **kwargs):
            # Skip caching for non-GET requests if enabled
            if cache_get_only and request.method != 'GET':
                return view_func(request, *args, **kwargs)
            
            # Build cache key
            prefix = key_prefix or f"api:{view_func.__name__}"
            cache_key = build_cache_key(
                prefix,
                user_id=str(request.user.id) if request.user.is_authenticated else 'anonymous',
                path=request.path,
                method=request.method,
                params=json.dumps(request.GET.dict(), default=str)
            )
            
            # Try to get from cache
            cached_response = cache.get(cache_key)
            if cached_response is not None:
                return cached_response
            
            # Execute view
            response = view_func(request, *args, **kwargs)
            
            # Cache successful responses
            if hasattr(response, 'status_code') and response.status_code == 200:
                cache.set(cache_key, response, timeout)
            
            return response
        
        return wrapper
    return decorator


def cached_queryset(
    timeout=300,
    cache_key_builder=None
):
    """
    Decorator for methods that return querysets.
    Caches the evaluated queryset.
    
    Example:
        class MyViewSet(viewsets.ModelViewSet):
            @cached_queryset(timeout=600)
            def get_queryset(self):
                return Document.objects.select_related('uploaded_by')
    """
    def decorator(func):
        @wraps(func)
        def wrapper(self, *args, **kwargs):
            # Build cache key
            if cache_key_builder:
                cache_key = cache_key_builder(self, *args, **kwargs)
            else:
                cache_key = f"qs:{func.__name__}:{id(self)}"
            
            # Try cache
            cached_qs = cache.get(cache_key)
            if cached_qs is not None:
                return cached_qs
            
            # Execute and cache
            result = func(self, *args, **kwargs)
            cache.set(cache_key, list(result), timeout)
            
            return result
        
        return wrapper
    return decorator


def invalidate_cache_pattern(pattern):
    """
    Invalidate all cache keys matching a pattern.
    
    Only works with Redis backend.
    For other backends, requires manual key tracking.
    
    Example:
        # Clear all document-related caches
        invalidate_cache_pattern('doc_*')
    """
    try:
        if hasattr(cache, 'delete_pattern'):
            # Redis-specific
            cache.delete_pattern(f"{pattern}*")
        else:
            # For other backends, this is a no-op
            print(f"Warning: Cache backend doesn't support pattern deletion for {pattern}")
    except Exception as e:
        print(f"Error invalidating cache pattern {pattern}: {e}")


def invalidate_related_caches(model_instance, cache_patterns):
    """
    Invalidate multiple cache patterns related to a model instance.
    
    Example in Django signal:
        @receiver(post_save, sender=Document)
        def invalidate_on_save(sender, instance, **kwargs):
            invalidate_related_caches(instance, [
                f'doc_list:{instance.organization_id}:*',
                f'doc_detail:{instance.id}',
                'doc_aggregates:*'
            ])
    """
    for pattern in cache_patterns:
        invalidate_cache_pattern(pattern)


class CachedAPIView:
    """
    Mixin for ViewSets to add caching capability.
    
    Usage:
        class DocumentViewSet(CachedAPIView, viewsets.ModelViewSet):
            queryset = Document.objects.all()
            serializer_class = DocumentSerializer
            cache_timeout = 300  # 5 minutes
            
            def get_cache_key(self):
                return f"docs:{self.request.user.id}"
    """
    cache_timeout = 300
    
    def get_cache_key(self):
        """Override to customize cache key generation"""
        return build_cache_key(
            f"view:{self.__class__.__name__}",
            user_id=str(self.request.user.id),
            action=self.action,
            params=json.dumps(self.request.GET.dict(), default=str)
        )
    
    def get_cached_data(self):
        """Get data from cache if available"""
        cache_key = self.get_cache_key()
        return cache.get(cache_key)
    
    def set_cached_data(self, data):
        """Store data in cache"""
        cache_key = self.get_cache_key()
        cache.set(cache_key, data, self.cache_timeout)
    
    def invalidate_cache(self):
        """Clear this view's cache"""
        cache_key = self.get_cache_key()
        cache.delete(cache_key)


# ─────────────────────────────────────────────────────────────────────────────
# Query Monitor for Development
# ─────────────────────────────────────────────────────────────────────────────

def get_query_stats():
    """
    Get database query statistics.
    Only works in DEBUG mode.
    """
    from django.conf import settings
    from django.db import connection
    from django.test.utils import CaptureQueriesContext
    
    if not settings.DEBUG:
        return None
    
    queries = connection.queries
    
    stats = {
        'total_queries': len(queries),
        'total_time': sum(float(q.get('time', 0)) for q in queries),
        'queries': queries
    }
    
    return stats


def log_slow_queries(threshold=0.1):
    """
    Log queries that exceed threshold duration (in seconds).
    """
    from django.conf import settings
    import logging
    
    logger = logging.getLogger(__name__)
    
    if not settings.DEBUG:
        return
    
    from django.db import connection
    
    for query in connection.queries:
        query_time = float(query.get('time', 0))
        if query_time > threshold:
            logger.warning(
                f"Slow query ({query_time:.2f}s): {query['sql'][:200]}..."
            )


# ─────────────────────────────────────────────────────────────────────────────
# Configuration Example for settings.py
# ─────────────────────────────────────────────────────────────────────────────

"""
# Use Redis for caching (much faster than database cache)
CACHES = {
    'default': {
        'BACKEND': 'django_redis.cache.RedisCache',
        'LOCATION': 'redis://127.0.0.1:6379/1',
        'OPTIONS': {
            'CLIENT_CLASS': 'django_redis.client.DefaultClient',
            'SOCKET_CONNECT_TIMEOUT': 5,
            'SOCKET_TIMEOUT': 5,
            'COMPRESSOR': 'django_redis.compressors.zlib.ZlibCompressor',
            'CONNECTION_POOL_KWARGS': {
                'max_connections': 50,
                'retry_on_timeout': True
            }
        },
        'KEY_PREFIX': 'finai',
        'TIMEOUT': 300  # 5 minutes default
    }
}

# Or use in-memory for development:
# CACHES = {
#     'default': {
#         'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
#         'LOCATION': 'unique-snowflake',
#     }
# }
"""
