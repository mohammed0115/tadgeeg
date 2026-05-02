"""
Additional health checks not covered by ``core.services.monitoring`` —
storage writability, pending migrations, and cache reachability.

The shipping ``HealthCheckView`` calls into ``get_health_check_report`` which
covers DB, Redis, Tesseract, and OpenAI. This module fills the operational
gaps auditors and on-call engineers ask about most:

    - "Can we still write uploaded files?"  → storage write probe
    - "Is the schema in sync?"               → migration plan check
    - "Is the cache layer responding?"        → cache get/set probe
"""
from __future__ import annotations

import os
import time
from typing import Any, Dict


def check_storage(read_only: bool = False) -> Dict[str, Any]:
    """Try to write a tiny probe file under MEDIA_ROOT and read it back.

    A read-only check (`read_only=True`) just confirms the directory exists
    and is readable.
    """
    from django.conf import settings

    media_root_raw = getattr(settings, "MEDIA_ROOT", None)
    # Always coerce to str so the JSON serializer doesn't choke on a PosixPath.
    media_root = str(media_root_raw) if media_root_raw else None
    if not media_root:
        return {"status": "unknown", "error": "MEDIA_ROOT not configured"}
    if not os.path.isdir(media_root):
        return {"status": "unhealthy", "error": "MEDIA_ROOT does not exist", "media_root": media_root}

    if read_only:
        return {
            "status": "healthy",
            "writable": False,
            "media_root": media_root,
        }

    probe = os.path.join(media_root, ".health_probe")
    started = time.time()
    try:
        with open(probe, "wb") as f:
            f.write(b"health-probe")
        with open(probe, "rb") as f:
            assert f.read() == b"health-probe"
        os.remove(probe)
        return {
            "status": "healthy",
            "writable": True,
            "media_root": media_root,
            "latency_ms": int((time.time() - started) * 1000),
        }
    except Exception as exc:
        return {
            "status": "unhealthy",
            "error": f"storage write/read failed: {str(exc)[:200]}",
            "media_root": media_root,
        }


def check_migrations() -> Dict[str, Any]:
    """Detect any unapplied migrations — schema-drift early-warning."""
    try:
        from django.db.migrations.executor import MigrationExecutor
        from django.db import connection

        executor = MigrationExecutor(connection)
        targets = executor.loader.graph.leaf_nodes()
        plan = executor.migration_plan(targets)
        if plan:
            pending = [(name, str(migration)) for migration, name in plan]
            return {
                "status": "degraded",
                "pending": len(pending),
                "first_few": [m[1] for m in pending[:5]],
            }
        return {"status": "healthy", "pending": 0}
    except Exception as exc:
        return {"status": "unknown", "error": str(exc)[:200]}


def check_cache() -> Dict[str, Any]:
    """Round-trip a value through Django's cache layer."""
    try:
        from django.core.cache import cache
        key = "_health_probe"
        value = f"probe-{int(time.time())}"
        started = time.time()
        cache.set(key, value, 30)
        echoed = cache.get(key)
        if echoed != value:
            return {"status": "unhealthy", "error": "cache round-trip mismatch"}
        cache.delete(key)
        return {"status": "healthy", "latency_ms": int((time.time() - started) * 1000)}
    except Exception as exc:
        return {"status": "unhealthy", "error": str(exc)[:200]}


def check_openai_key() -> Dict[str, Any]:
    """Confirm the OpenAI key is present (without making an API call)."""
    from django.conf import settings
    key = getattr(settings, "OPENAI_API_KEY", "") or ""
    if not key:
        return {"status": "unconfigured", "configured": False}
    if not key.startswith("sk-"):
        return {"status": "degraded", "configured": True, "note": "key format unusual"}
    return {"status": "healthy", "configured": True, "key_prefix": key[:8] + "…"}


def comprehensive_report() -> Dict[str, Any]:
    """Combined report — pluggable into the existing health-check view."""
    return {
        "storage":     check_storage(read_only=False),
        "migrations":  check_migrations(),
        "cache":       check_cache(),
        "openai_key":  check_openai_key(),
    }
