"""
Document Processing Celery Tasks

All heavy document I/O (OCR, OpenAI calls, audit rule evaluation) runs here,
off the request thread.

Task hierarchy:
  process_document_task          — Full Financial AI + Audit pipeline (v2.0)
  reprocess_document_task        — Force-reprocess an existing document
  process_zip_task               — Extract ZIP → create Document records → chord dispatch
  _process_zip_child_task        — Per-file worker task (chord member, never raises)
  _zip_session_finalize_task     — Chord callback: finalize AuditSession after all files done
  run_nightly_anomaly_scan       — Nightly scheduled scan for all orgs
  generate_weekly_kpi_report     — Weekly KPI reports
"""

import logging
import random

from celery import shared_task

logger = logging.getLogger("finai")


# ── Retry helpers ─────────────────────────────────────────────────────────────

# Retry schedule for AI/OCR tasks:
#   attempt 0 → 30s base
#   attempt 1 → 60s base
#   attempt 2 → 120s base
# ± up to 20% jitter to prevent thundering-herd when many workers fail at once.
_RETRY_BASE_DELAY    = 30    # seconds
_RETRY_MAX_DELAY     = 300   # cap at 5 minutes
_RETRY_JITTER_PCT    = 0.20  # ±20%


def _retry_countdown(attempt: int) -> int:
    """
    Exponential backoff with ±jitter.

    Args:
        attempt: Zero-based retry attempt number (self.request.retries).

    Returns:
        Integer seconds to wait before re-queuing.
    """
    base  = min(_RETRY_BASE_DELAY * (2 ** attempt), _RETRY_MAX_DELAY)
    jitter = base * _RETRY_JITTER_PCT * (random.random() * 2 - 1)   # ±jitter_pct * base
    return max(1, int(base + jitter))


# ── Idempotency helpers ───────────────────────────────────────────────────────
#
# Prevents double-processing when Celery re-delivers a message (at-least-once
# delivery guarantee means the same task can arrive twice).
#
# Strategy:
#   1. Check if the Document is already PROCESSING or COMPLETED (DB check, free).
#   2. Set a Redis lock key for the task (TTL > max task time_limit).
#      If the key already exists another worker is handling it → skip.
#   3. On task completion (success or permanent failure) the Document status
#      is updated to a terminal state, so subsequent deliveries hit check 1.
#
# Redis is used opportunistically; if Redis is unavailable, the task proceeds
# without idempotency (the DB-status check still catches most duplicates).

_IDEMPOTENCY_TTL = 360  # seconds (6 min — longer than process_document time_limit=300)
_IDEMPOTENCY_PREFIX = "finai:idempotency"


def _acquire_idempotency_lock(task_name: str, document_id: str) -> bool:
    """
    Try to acquire an idempotency lock for this (task, document) pair.

    Returns True if the lock was acquired (caller should proceed).
    Returns False if a lock already exists (caller should skip / return early).
    """
    key = f"{_IDEMPOTENCY_PREFIX}:{task_name}:{document_id}"
    try:
        from django.core.cache import cache
        # SET NX (set if not exists) — atomic; returns True only when set
        acquired = cache.add(key, "1", timeout=_IDEMPOTENCY_TTL)
        return bool(acquired)
    except Exception as exc:
        # Cache unavailable — proceed without lock (best-effort)
        logger.debug("[Idempotency] Cache unavailable, proceeding without lock: %s", exc)
        return True


def _release_idempotency_lock(task_name: str, document_id: str) -> None:
    """Release the idempotency lock early (e.g. after permanent failure)."""
    key = f"{_IDEMPOTENCY_PREFIX}:{task_name}:{document_id}"
    try:
        from django.core.cache import cache
        cache.delete(key)
    except Exception:
        pass


def _document_already_processed(document_id: str) -> bool:
    """
    Fast DB check: is this document already in a terminal state?
    Catches duplicates even when Redis has been flushed.
    """
    try:
        from apps.documents.models import Document
        terminal = {
            Document.ProcessingStatus.COMPLETED,
            Document.ProcessingStatus.NEEDS_REVIEW,
        }
        status = (
            Document.objects
            .filter(pk=document_id)
            .values_list("processing_status", flat=True)
            .first()
        )
        return status in {s.value for s in terminal}
    except Exception:
        return False


# ── Document processing ───────────────────────────────────────────────────────

@shared_task(
    bind=True,
    max_retries=3,
    default_retry_delay=30,
    time_limit=300,        # 5-minute hard limit
    soft_time_limit=270,   # Soft limit: allow clean shutdown
    name="documents.process_document_task",
)
def process_document_task(self, document_id: str, session_id: str = None) -> dict:
    """
    Full pipeline for one document (v2.0):
      1. DocumentEngine.ingest()         — MIME detection, parsing, OCR
      2. FinancialAIEngine.analyse()     — classification, extraction, fraud/dup/risk
      3.5. NormalizationService          — field unification + type coercion
          + ValidationEngine             — 5 financial rules (V001–V005)
          + ValidationService            — persist AuditFinding records
      3. AuditEngine.evaluate()          — modular rule evaluation
      4. Persist DocumentAnalysisResult

    :param document_id: UUID string of the Document to process.
    :param session_id:  Optional UUID string of an AuditSession (for finding persistence).

    Retries up to 3 times on transient failures (network, OpenAI timeouts).
    Permanent failures (file missing, unsupported type) are NOT retried.
    """
    logger.info(
        "[Task:process_document] Starting pipeline for document=%s session=%s",
        document_id, session_id,
    )

    # ── Idempotency guard ─────────────────────────────────────────────────────
    # Fast DB check first (no Redis round-trip needed for terminal docs)
    if _document_already_processed(document_id):
        logger.info(
            "[Task:process_document] Skipping already-processed document=%s",
            document_id,
        )
        return {"document_id": document_id, "success": True, "skipped": True,
                "reason": "already_processed"}

    if not _acquire_idempotency_lock("process_document", document_id):
        logger.info(
            "[Task:process_document] Duplicate delivery — another worker is "
            "processing document=%s. Skipping.",
            document_id,
        )
        return {"document_id": document_id, "success": True, "skipped": True,
                "reason": "duplicate_delivery"}

    try:
        # Signal OpenAI extractor to raise immediately on transient errors
        # instead of blocking this worker with time.sleep().
        import core.services.ai.openai_extractor as _oai_mod
        _oai_mod._IN_CELERY_CONTEXT = True

        from core.services.pipeline import run_full_pipeline
        result = run_full_pipeline(document_id=document_id, session_id=session_id)

        if result.get("success"):
            logger.info(
                "[Task:process_document] DONE document=%s risk=%s time=%dms",
                document_id,
                result.get("risk_level", "?"),
                result.get("processing_time_ms", 0),
            )
        else:
            logger.warning(
                "[Task:process_document] FAILED document=%s error=%s",
                document_id,
                result.get("error", "unknown"),
            )

        return {
            "document_id": document_id,
            "success": result.get("success", False),
            "risk_level": result.get("risk_level"),
            "risk_score": result.get("risk_score"),
            "processing_time_ms": result.get("processing_time_ms"),
        }

    except Exception as exc:
        logger.error("[Task:process_document] Exception for %s: %s", document_id, exc)

        # Permanent errors → mark failed immediately, do NOT retry
        permanent_errors = (
            FileNotFoundError,
            PermissionError,
            IsADirectoryError,
        )
        if isinstance(exc, permanent_errors):
            logger.warning(
                "[Task:process_document] Permanent error for %s — no retry: %s",
                document_id, exc,
            )
            _safe_mark_failed(document_id, str(exc))
            # Release lock: permanent failure allows manual re-trigger
            _release_idempotency_lock("process_document", document_id)
            return {"document_id": document_id, "success": False, "error": str(exc)}

        # Transient errors → retry with backoff (keep lock during retry window)
        _safe_mark_failed(document_id, str(exc))
        raise self.retry(exc=exc, countdown=_retry_countdown(self.request.retries))


@shared_task(
    bind=True,
    max_retries=2,
    default_retry_delay=10,
    time_limit=300,
    name="documents.reprocess_document_task",
)
def reprocess_document_task(self, document_id: str) -> dict:
    """
    Force-reprocess an already-processed document.
    Resets processing_status to PENDING before calling the pipeline.
    """
    from apps.documents.models import Document

    logger.info("[Task:reprocess_document] Reprocessing document %s", document_id)

    try:
        Document.objects.filter(pk=document_id).update(
            processing_status=Document.ProcessingStatus.PENDING,
            processing_error="",
        )
    except Exception:
        pass

    # Dispatch as a new async task — do NOT call synchronously.
    process_document_task.apply_async(args=[document_id])
    return {"document_id": document_id, "requeued": True}


# ── ZIP Parallel Processing ───────────────────────────────────────────────────

@shared_task(
    bind=True,
    max_retries=1,
    time_limit=120,         # Extraction only — child tasks have their own limits
    soft_time_limit=100,
    name="documents.process_zip_task",
)
def process_zip_task(self, document_id: str, session_id: str = None) -> dict:
    """
    Stage-1 ZIP handler: extract archive → create one Document per file →
    dispatch all files in parallel via celery.chord.

    Workflow:
      1. Validate ZIP integrity (path-traversal, size, file count)
      2. Extract to a secure temp directory
      3. Create Document(status=PENDING) for every supported file
      4. Update AuditSession.total_count
      5. Dispatch chord(group([process_zip_child_task × N]))(finalize_callback)
      6. Return immediately — workers process files in parallel

    The chord callback (_zip_session_finalize_task) fires only after ALL child
    tasks complete (success or exhausted retries), then finalises the session.

    :param document_id: UUID of the ZIP Document record.
    :param session_id:  UUID of the AuditSession to track progress.
    """
    import mimetypes
    import os
    import shutil
    import tempfile
    import zipfile

    from celery import chord, group
    from django.core.files.base import ContentFile

    from apps.audit.models import AuditSession
    from apps.audit.session_service import AuditSessionService
    from apps.documents.models import Document
    from core.services.document_engine import ALLOWED_MIMES

    # ── Load ZIP document ─────────────────────────────────────────────────────
    try:
        zip_doc = Document.objects.get(pk=document_id)
    except Document.DoesNotExist:
        logger.error("[Task:process_zip] Document %s not found", document_id)
        return {"success": False, "error": "Document not found", "document_id": document_id}

    # ── Load + transition AuditSession ────────────────────────────────────────
    session = None
    if session_id:
        try:
            session = AuditSession.objects.get(pk=session_id)
            svc = AuditSessionService(session)
            if session.can_transition_to(AuditSession.State.EXTRACTING):
                svc.transition(AuditSession.State.EXTRACTING)
        except Exception as exc:
            logger.warning("[Task:process_zip] Session %s load/transition failed: %s", session_id, exc)

    # Mark ZIP document as processing
    Document.objects.filter(pk=document_id).update(
        processing_status=Document.ProcessingStatus.PROCESSING
    )

    # ── Resolve file path ─────────────────────────────────────────────────────
    try:
        zip_path = zip_doc.file.path
    except Exception as exc:
        _safe_mark_failed(document_id, f"Cannot resolve ZIP path: {exc}")
        _safe_mark_session_failed(session_id, f"Cannot resolve ZIP path: {exc}")
        return {"success": False, "error": str(exc), "document_id": document_id}

    # ── Security: validate ZIP before extraction ──────────────────────────────
    _MAX_UNCOMPRESSED = 500 * 1024 * 1024   # 500 MB
    _MAX_FILES        = 500
    _SKIP_NAMES       = {"__MACOSX", ".DS_Store", "Thumbs.db", ".gitkeep"}

    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            bad = zf.testzip()
            if bad is not None:
                raise ValueError(f"Corrupted file in ZIP: {bad}")

            names = zf.namelist()
            if len(names) > _MAX_FILES:
                raise ValueError(f"ZIP contains {len(names)} files (max {_MAX_FILES})")

            total_uncompressed = 0
            for info in zf.infolist():
                if ".." in info.filename or info.filename.startswith("/"):
                    raise ValueError(f"Path-traversal attempt: {info.filename}")
                total_uncompressed += info.file_size
                if total_uncompressed > _MAX_UNCOMPRESSED:
                    raise ValueError("ZIP exceeds 500 MB uncompressed limit")

    except (zipfile.BadZipFile, ValueError) as exc:
        _safe_mark_failed(document_id, str(exc))
        _safe_mark_session_failed(session_id, str(exc))
        logger.error("[Task:process_zip] Validation failed for %s: %s", document_id, exc)
        return {"success": False, "error": str(exc), "document_id": document_id}

    # ── Extract + create Document records ─────────────────────────────────────
    tmp_dir = tempfile.mkdtemp(prefix="finai_zip_")
    child_document_ids: list[str] = []
    skipped = 0

    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            zf.extractall(tmp_dir)

        for root, _dirs, files in os.walk(tmp_dir):
            for filename in sorted(files):
                # Skip OS artefacts
                if any(skip in filename for skip in _SKIP_NAMES):
                    skipped += 1
                    continue

                full_path = os.path.join(root, filename)
                file_size = os.path.getsize(full_path)

                if file_size == 0:
                    skipped += 1
                    continue

                # MIME detection: stdlib first, then extension map
                mime_type, _ = mimetypes.guess_type(filename)
                if not mime_type:
                    ext = os.path.splitext(filename)[1].lower()
                    from core.services.document_engine import EXTENSION_TO_MIME
                    mime_type = EXTENSION_TO_MIME.get(ext, "application/octet-stream")

                if mime_type not in ALLOWED_MIMES:
                    logger.debug(
                        "[Task:process_zip] Skipping unsupported file %s (%s)",
                        filename, mime_type,
                    )
                    skipped += 1
                    continue

                # Create Document record + save file via Django storage
                try:
                    child_doc = Document(
                        organization=zip_doc.organization,
                        uploaded_by=zip_doc.uploaded_by,
                        original_filename=filename,
                        file_size=file_size,
                        mime_type=mime_type,
                        processing_status=Document.ProcessingStatus.PENDING,
                        tags=["zip_extracted", f"source_zip:{document_id}"],
                    )
                    with open(full_path, "rb") as fh:
                        child_doc.file.save(
                            f"documents/zip_extracted/{zip_doc.id}/{filename}",
                            ContentFile(fh.read()),
                            save=False,   # We call full save below
                        )
                    child_doc.save()
                    child_document_ids.append(str(child_doc.id))

                except Exception as exc:
                    logger.error(
                        "[Task:process_zip] Failed to create Document for %s: %s",
                        filename, exc,
                    )

    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    if not child_document_ids:
        msg = "No processable files found in ZIP"
        _safe_mark_failed(document_id, msg)
        _safe_mark_session_failed(session_id, msg)
        return {"success": False, "error": msg, "document_id": document_id}

    logger.info(
        "[Task:process_zip] ZIP %s → %d files dispatched | %d skipped | session=%s",
        document_id, len(child_document_ids), skipped, session_id,
    )

    # ── Update AuditSession.total_count ───────────────────────────────────────
    if session_id:
        try:
            AuditSession.objects.filter(pk=session_id).update(
                total_count=len(child_document_ids)
            )
        except Exception as exc:
            logger.warning("[Task:process_zip] Could not update session total_count: %s", exc)

    # Mark the ZIP document itself as completed (extraction phase done)
    Document.objects.filter(pk=document_id).update(
        processing_status=Document.ProcessingStatus.COMPLETED
    )

    # ── Build + dispatch Celery chord ─────────────────────────────────────────
    #
    # chord(group)(callback) fires callback ONLY after ALL group tasks finish.
    # _process_zip_child_task never raises — it always returns a result dict —
    # so the chord callback is guaranteed to execute regardless of per-file errors.
    #
    task_group = group(
        _process_zip_child_task.s(doc_id, session_id)
        for doc_id in child_document_ids
    )
    finalize_callback = _zip_session_finalize_task.s(
        session_id=session_id,
        zip_document_id=document_id,
        total_files=len(child_document_ids),
    )

    chord(task_group)(finalize_callback)

    return {
        "success":             True,
        "document_id":         document_id,
        "session_id":          session_id,
        "files_dispatched":    len(child_document_ids),
        "files_skipped":       skipped,
        "child_document_ids":  child_document_ids,
    }


@shared_task(
    bind=True,
    max_retries=3,
    default_retry_delay=30,
    time_limit=300,
    soft_time_limit=270,
    name="documents.process_zip_child_task",
)
def _process_zip_child_task(self, document_id: str, session_id: str = None) -> dict:
    """
    Per-file worker task — member of a ZIP chord group.

    Identical pipeline to process_document_task but with two critical differences:
      1. NEVER raises after max retries — always returns a result dict so the
         chord callback is guaranteed to fire even if this file fails.
      2. Records its result to the AuditSession counters atomically before returning.

    :param document_id: UUID of the child Document to process.
    :param session_id:  UUID of the parent AuditSession (for counter updates).
    """
    from celery.exceptions import MaxRetriesExceededError

    # Signal OpenAI extractor to raise immediately on transient errors
    # instead of blocking this worker with time.sleep().
    import core.services.ai.openai_extractor as _oai_mod
    _oai_mod._IN_CELERY_CONTEXT = True

    logger.info(
        "[Task:zip_child] Starting doc=%s session=%s",
        document_id, session_id,
    )

    # ── Idempotency guard ─────────────────────────────────────────────────────
    if _document_already_processed(document_id):
        logger.info("[Task:zip_child] Already processed doc=%s — skipping", document_id)
        return {
            "document_id": document_id, "success": True, "skipped": True,
            "reason": "already_processed",
            "risk_level": "low", "risk_score": 0,
            "is_duplicate": False, "requires_review": False, "compliance_score": 1.0,
        }

    if not _acquire_idempotency_lock("zip_child", document_id):
        logger.info(
            "[Task:zip_child] Duplicate delivery for doc=%s — skipping", document_id
        )
        return {
            "document_id": document_id, "success": True, "skipped": True,
            "reason": "duplicate_delivery",
            "risk_level": "low", "risk_score": 0,
            "is_duplicate": False, "requires_review": False, "compliance_score": 1.0,
        }

    task_result: dict = {
        "document_id":      document_id,
        "success":          False,
        "risk_level":       "high",
        "risk_score":       60,
        "is_duplicate":     False,
        "requires_review":  False,
        "compliance_score": 1.0,
        "error":            None,
    }

    try:
        from core.services.pipeline import run_full_pipeline

        result = run_full_pipeline(document_id=document_id, session_id=session_id)

        task_result.update({
            "success":          result.get("success", False),
            "risk_level":       result.get("risk_level", "high"),
            "risk_score":       result.get("risk_score", 60),
            "is_duplicate":     result.get("is_duplicate", False),
            "requires_review":  result.get("requires_review", False),
            "compliance_score": result.get("compliance_score", 1.0),
        })

        logger.info(
            "[Task:zip_child] DONE doc=%s risk=%s",
            document_id, task_result["risk_level"],
        )

    except Exception as exc:
        logger.error("[Task:zip_child] Exception for doc=%s: %s", document_id, exc)

        task_result["error"] = str(exc)
        _safe_mark_failed(document_id, str(exc))

        # Permanent errors: no retry, return error dict immediately
        if isinstance(exc, (FileNotFoundError, PermissionError, IsADirectoryError)):
            _release_idempotency_lock("zip_child", document_id)
            _record_session_result(session_id, task_result)
            return task_result

        # Transient errors: retry. After max retries, return error dict (do NOT raise)
        # so the chord callback is still guaranteed to fire.
        try:
            raise self.retry(exc=exc, countdown=_retry_countdown(self.request.retries))
        except MaxRetriesExceededError:
            logger.warning(
                "[Task:zip_child] Max retries reached for doc=%s — returning error result",
                document_id,
            )
            _release_idempotency_lock("zip_child", document_id)
            _record_session_result(session_id, task_result)
            return task_result

    # Record result to session counters (both success and failure paths reach here
    # except the retry path above, which records before returning)
    _record_session_result(session_id, task_result)
    return task_result


@shared_task(
    bind=True,
    max_retries=2,
    default_retry_delay=10,
    time_limit=120,          # ↑ was 60 — must accommodate DB writes + risk computation
    soft_time_limit=100,     # Raise SoftTimeLimitExceeded before hard kill
    name="documents.zip_session_finalize_task",
)
def _zip_session_finalize_task(
    self,
    results: list,
    *,
    session_id: str = None,
    zip_document_id: str = None,
    total_files: int = 0,
) -> dict:
    """
    Chord callback: executes ONLY after every _process_zip_child_task finishes.

    Responsibilities:
      1. Lock AuditSession with select_for_update() to prevent race conditions
         from Celery message re-delivery (at-least-once delivery guarantee).
      2. Use DB-authoritative counters (session.success_count / failed_count)
         rather than in-memory results list — the latter is informational only.
      3. Transition AuditSession to COMPLETED / REVIEW_REQUIRED inside an
         atomic block.  Mark FAILED if unrecoverable error occurs.
      4. Fix risk summary to include DocumentAnalysisResult scores (not only
         Invoice records).
      5. Dispatch executive summary as a separate Celery task to avoid
         blocking this callback with an OpenAI call.

    :param results:         List of return dicts from every child task (may
                            contain None if a result backend entry was lost).
    :param session_id:      UUID of the AuditSession to finalise.
    :param zip_document_id: UUID of the original ZIP Document (informational).
    :param total_files:     Expected file count (used only for log validation).
    """
    import time as _time

    from django.db import transaction

    from apps.audit.models import AuditSession
    from apps.audit.session_service import AuditSessionService

    t_start = _time.monotonic()

    # ── 1. Validate inputs ────────────────────────────────────────────────────
    if not session_id:
        logger.warning("[Task:zip_finalize] No session_id — skipping finalisation")
        return {"finalized": False, "reason": "no session_id"}

    # Informational counts from child results (for logging cross-check only).
    # The authoritative numbers come from the DB counters below.
    mem_total   = len(results or [])
    mem_success = sum(1 for r in (results or []) if isinstance(r, dict) and r.get("success"))
    mem_failed  = mem_total - mem_success
    mem_none    = sum(1 for r in (results or []) if r is None)

    logger.info(
        "[Task:zip_finalize] Chord arrived — "
        "mem_total=%d mem_success=%d mem_failed=%d mem_none=%d "
        "total_files_expected=%d session=%s",
        mem_total, mem_success, mem_failed, mem_none, total_files, session_id,
    )

    # ── 2. Load + lock session ────────────────────────────────────────────────
    try:
        session = (
            AuditSession.objects
            .select_for_update(nowait=False)  # Block until lock acquired
            .get(pk=session_id)
        )
    except AuditSession.DoesNotExist:
        logger.error("[Task:zip_finalize] Session %s not found — cannot finalise", session_id)
        return {"finalized": False, "reason": "session_not_found", "session_id": session_id}
    except Exception as exc:
        logger.error("[Task:zip_finalize] DB error loading session %s: %s", session_id, exc)
        try:
            raise self.retry(exc=exc)
        except Exception:
            _safe_mark_session_failed(session_id, f"Finalize load error: {exc}")
            return {"finalized": False, "session_id": session_id, "error": str(exc)}

    # Guard: idempotency — if session is already terminal, do nothing
    if session.is_terminal:
        logger.info(
            "[Task:zip_finalize] Session %s already in terminal state %s — skipping",
            session_id, session.state,
        )
        return {
            "finalized":     False,
            "reason":        "already_terminal",
            "session_id":    session_id,
            "session_state": session.state,
        }

    svc = AuditSessionService(session)

    # ── 3. Read authoritative counters from DB ────────────────────────────────
    # select_for_update above ensures we see the final committed values from
    # all _record_session_result() calls that completed before this callback.
    db_processed = session.processed_count
    db_success   = session.success_count
    db_failed    = session.failed_count
    db_total     = session.total_count

    logger.info(
        "[Task:zip_finalize] DB counters — "
        "total=%d processed=%d success=%d failed=%d review=%d | "
        "cross-check mem_success=%d mem_failed=%d",
        db_total, db_processed, db_success, db_failed,
        session.review_required_count,
        mem_success, mem_failed,
    )

    # Warn if DB counters diverge from in-memory results (signals a lost
    # _record_session_result() call, e.g., due to a worker crash mid-flight)
    if db_processed != mem_total and mem_total > 0:
        logger.warning(
            "[Task:zip_finalize] Counter mismatch: db_processed=%d != mem_total=%d "
            "for session=%s — DB is authoritative",
            db_processed, mem_total, session_id,
        )

    # ── 4. Advance state machine + finalise (atomic block) ───────────────────
    finalized   = False
    final_state = session.state

    try:
        with transaction.atomic():
            # Re-acquire lock inside atomic block (required for proper MVCC)
            session = (
                AuditSession.objects
                .select_for_update()
                .get(pk=session_id)
            )
            svc = AuditSessionService(session)

            # Walk forward through intermediate states the pipeline may have
            # skipped (e.g., documents that failed before NORMALIZING/VALIDATING)
            for target_state in (
                AuditSession.State.NORMALIZING,
                AuditSession.State.VALIDATING,
            ):
                session.refresh_from_db(fields=["state"])
                if session.can_transition_to(target_state):
                    svc.transition(target_state, save=True)
                    logger.debug(
                        "[Task:zip_finalize] Transitioned session %s → %s",
                        session_id, target_state,
                    )

            # Recompute risk summary from DocumentAnalysisResult records
            # (more accurate than Invoice-only query for ZIP uploads)
            _recompute_zip_risk_summary(session)

            # Trigger final state machine step
            session.refresh_from_db()
            finalized = svc.maybe_complete()
            final_state = session.state

    except Exception as exc:
        logger.error(
            "[Task:zip_finalize] Atomic finalise failed for session=%s: %s",
            session_id, exc,
        )
        # Retry on transient DB errors (e.g., deadlock, connection drop)
        try:
            raise self.retry(exc=exc)
        except Exception:
            # Max retries exhausted — mark session FAILED so it doesn't hang
            _safe_mark_session_failed(
                session_id,
                f"Finalize atomic block failed after {self.max_retries} retries: {exc}",
            )
            return {
                "finalized":   False,
                "session_id":  session_id,
                "session_state": final_state,
                "error":       str(exc),
            }

    # ── 5. Post-finalise observability ───────────────────────────────────────
    elapsed_ms = int((_time.monotonic() - t_start) * 1000)

    if finalized:
        logger.info(
            "[Task:zip_finalize] Session %s finalised → %s | "
            "docs=%d ok=%d fail=%d review=%d risk=%s(%.1f) | %dms",
            session_id,
            session.state,
            db_total,
            db_success,
            db_failed,
            session.review_required_count,
            session.overall_risk_level,
            session.overall_risk_score,
            elapsed_ms,
        )
        # Dispatch executive summary as a separate task to avoid blocking
        # this callback with an OpenAI call that could hit soft_time_limit.
        _generate_session_summary_task.apply_async(
            args=[session_id],
            countdown=5,   # Brief delay to let DB writes propagate
        )
    else:
        # maybe_complete() returned False — session not yet fully processed
        session.refresh_from_db()
        logger.warning(
            "[Task:zip_finalize] maybe_complete() returned False for session=%s "
            "(state=%s processed=%d/%d). "
            "Possible cause: _record_session_result() dropped for some workers.",
            session_id,
            session.state,
            session.processed_count,
            session.total_count,
        )
        # Force-complete if all results are accounted for in-memory
        # but DB counters didn't catch up (defensive recovery)
        if mem_total > 0 and mem_total == total_files and session.processed_count < total_files:
            logger.warning(
                "[Task:zip_finalize] Forcing processed_count=%d for session=%s "
                "(mem confirms all tasks finished)",
                total_files, session_id,
            )
            AuditSession.objects.filter(pk=session_id).update(
                processed_count=total_files,
                success_count=mem_success,
                failed_count=mem_failed,
            )
            session.refresh_from_db()
            finalized = svc.maybe_complete()
            final_state = session.state
            if finalized:
                _generate_session_summary_task.apply_async(args=[session_id], countdown=5)

    return {
        "finalized":              finalized,
        "session_id":             session_id,
        "session_state":          session.state,
        "db_total":               db_total,
        "db_success":             db_success,
        "db_failed":              db_failed,
        "mem_total":              mem_total,
        "mem_success":            mem_success,
        "mem_failed":             mem_failed,
        "overall_risk_level":     session.overall_risk_level,
        "overall_risk_score":     session.overall_risk_score,
        "processing_time_ms":     elapsed_ms,
    }


@shared_task(
    bind=True,
    max_retries=2,
    default_retry_delay=30,
    time_limit=120,
    name="documents.generate_session_summary_task",
)
def _generate_session_summary_task(self, session_id: str) -> dict:
    """
    Generate an AI executive summary for a completed AuditSession.

    Separated from _zip_session_finalize_task to:
      - Avoid blocking the finalize callback with an OpenAI call
      - Allow independent retry if OpenAI is temporarily unavailable
      - Keep the finalize task within its time_limit

    Fallback: if OpenAI fails after all retries, writes a structured
    rule-based summary from DB counters so the field is never left as {}.
    """
    from apps.audit.models import AuditSession
    from apps.audit.session_service import AuditSessionService

    try:
        session = AuditSession.objects.get(pk=session_id)
    except AuditSession.DoesNotExist:
        logger.warning("[Task:session_summary] Session %s not found", session_id)
        return {"success": False, "reason": "session_not_found"}

    svc = AuditSessionService(session)

    try:
        narrative = svc.generate_executive_summary(language="ar")
        logger.info(
            "[Task:session_summary] AI summary generated for session=%s keys=%s",
            session_id, list(narrative.keys()) if narrative else [],
        )
        return {"success": True, "session_id": session_id}

    except Exception as exc:
        logger.warning(
            "[Task:session_summary] OpenAI failed for session=%s: %s",
            session_id, exc,
        )
        # Retry on transient errors
        try:
            raise self.retry(exc=exc)
        except Exception:
            # Max retries exhausted — write rule-based fallback summary
            _write_fallback_summary(session)
            return {"success": False, "session_id": session_id, "fallback_used": True}


def _write_fallback_summary(session) -> None:
    """
    Write a structured fallback executive summary from DB counters
    when OpenAI is unavailable.  Ensures executive_summary is never {}.
    """
    from apps.audit.models import AuditSession

    s = session
    total = s.total_count or 1   # Avoid division by zero
    success_rate = round(s.success_count / total * 100, 1)

    risk_label = {
        "low":      "منخفض",
        "medium":   "متوسط",
        "high":     "مرتفع",
        "critical": "حرج",
    }.get(s.overall_risk_level, s.overall_risk_level)

    fallback = {
        "summary_type":   "rule_based_fallback",
        "language":       "ar",
        "generated_by":   "system",
        "overview": (
            f"تمت معالجة {s.total_count} مستنداً في هذه الجلسة. "
            f"نجح {s.success_count} مستنداً ({success_rate}٪) "
            f"وفشل {s.failed_count} مستنداً. "
            f"مستوى المخاطر الإجمالي: {risk_label} ({s.overall_risk_score:.1f}/100)."
        ),
        "stats": {
            "total":           s.total_count,
            "success":         s.success_count,
            "failed":          s.failed_count,
            "review_required": s.review_required_count,
            "duplicates":      s.duplicate_count,
            "compliance_issues": s.compliance_issues,
            "high_risk":       s.high_risk_count,
        },
        "risk": {
            "overall_score": s.overall_risk_score,
            "overall_level": s.overall_risk_level,
        },
    }

    AuditSession.objects.filter(pk=s.pk).update(executive_summary=fallback)
    logger.info(
        "[Task:session_summary] Fallback summary written for session=%s", s.pk
    )


# ── High-Risk Reprocessing ────────────────────────────────────────────────────

@shared_task(
    bind=True,
    max_retries=1,
    time_limit=120,
    soft_time_limit=100,
    name="documents.reprocess_high_risk_task",
)
def reprocess_high_risk_task(
    self,
    organization_id: int = None,
    risk_levels: list = None,
    session_id: str = None,
    dry_run: bool = False,
) -> dict:
    """
    Re-queue all high/critical risk documents for reprocessing.

    Discovers DocumentAnalysisResult records with risk_level in `risk_levels`,
    resets their Document status to PENDING, then dispatches a
    process_document_task for each one via a Celery group (parallel).

    Args:
        organization_id: Scope to a single org (None = all orgs — admin only).
        risk_levels:     List of risk levels to target. Default: ["high", "critical"].
        session_id:      Optional AuditSession UUID to scope the search.
        dry_run:         If True, discover and log but do NOT dispatch tasks.

    Returns:
        Summary dict with counts and dispatched document IDs.
    """
    from django.db import transaction
    from django.db.models import Q
    from celery import group

    from apps.documents.models import Document, DocumentAnalysisResult

    risk_levels = risk_levels or ["high", "critical"]
    t_start = __import__("time").monotonic()

    logger.info(
        "[Task:reprocess_high_risk] Starting — org=%s levels=%s session=%s dry_run=%s",
        organization_id, risk_levels, session_id, dry_run,
    )

    # ── 1. Discover target documents (single query, no N+1) ──────────────────
    try:
        qs = (
            DocumentAnalysisResult.objects
            .filter(risk_level__in=risk_levels)
            .select_related("document")
            .only(
                "document_id",
                "risk_level",
                "risk_score",
                "document__processing_status",
                "document__original_filename",
                "document__organization_id",
            )
        )

        if organization_id:
            qs = qs.filter(document__organization_id=organization_id)

        if session_id:
            # Filter by documents linked to an AuditSession via AuditFinding
            from apps.audit.models import AuditFinding
            doc_ids_in_session = AuditFinding.objects.filter(
                session_id=session_id
            ).values_list("document_id", flat=True).distinct()
            qs = qs.filter(document_id__in=doc_ids_in_session)

        # Exclude already-processing documents to avoid double dispatch
        qs = qs.exclude(
            document__processing_status=Document.ProcessingStatus.PROCESSING
        )

        targets = list(qs.values(
            "document_id",
            "risk_level",
            "risk_score",
            "document__original_filename",
        ))

    except Exception as exc:
        logger.error("[Task:reprocess_high_risk] Discovery query failed: %s", exc)
        raise self.retry(exc=exc)

    total_found = len(targets)
    logger.info(
        "[Task:reprocess_high_risk] Found %d documents to reprocess | dry_run=%s",
        total_found, dry_run,
    )

    if total_found == 0:
        return {
            "success":         True,
            "total_found":     0,
            "total_dispatched": 0,
            "dry_run":         dry_run,
            "processing_time_ms": int((__import__("time").monotonic() - t_start) * 1000),
        }

    if dry_run:
        return {
            "success":     True,
            "dry_run":     True,
            "total_found": total_found,
            "targets":     [
                {
                    "document_id": str(t["document_id"]),
                    "filename":    t["document__original_filename"],
                    "risk_level":  t["risk_level"],
                    "risk_score":  t["risk_score"],
                }
                for t in targets
            ],
        }

    # ── 2. Reset statuses atomically (bulk update — one DB round-trip) ───────
    doc_ids = [t["document_id"] for t in targets]

    try:
        with transaction.atomic():
            updated = Document.objects.filter(
                pk__in=doc_ids,
            ).exclude(
                # Double-check: never reset a document that started processing
                # between our discovery query and this update
                processing_status=Document.ProcessingStatus.PROCESSING,
            ).update(
                processing_status=Document.ProcessingStatus.PENDING,
                processing_error="",
            )
            logger.info(
                "[Task:reprocess_high_risk] Reset %d/%d documents to PENDING",
                updated, total_found,
            )
    except Exception as exc:
        logger.error("[Task:reprocess_high_risk] Bulk status reset failed: %s", exc)
        raise self.retry(exc=exc)

    # Record state transitions in history (bulk insert)
    try:
        from apps.documents.services import DocumentStateHistoryService
        from apps.documents.models import Document as _Doc

        docs_to_record = _Doc.objects.filter(pk__in=doc_ids).only("id", "processing_status")
        DocumentStateHistoryService.record_bulk([
            {
                "document":   doc,
                "from_state": "failed_or_completed",  # approximate; exact state was reset
                "to_state":   Document.ProcessingStatus.PENDING,
                "reason":     f"Reprocess high-risk — risk_level in {risk_levels}",
                "metadata":   {"triggered_by": "reprocess_high_risk_task"},
            }
            for doc in docs_to_record
        ])
    except Exception as exc:
        logger.warning("[Task:reprocess_high_risk] State history write failed: %s", exc)

    # ── 3. Dispatch parallel reprocessing tasks (Celery group) ───────────────
    str_doc_ids = [str(d) for d in doc_ids]
    task_group  = group(
        process_document_task.s(doc_id, session_id)
        for doc_id in str_doc_ids
    )

    try:
        task_group.apply_async()
    except Exception as exc:
        logger.error("[Task:reprocess_high_risk] Group dispatch failed: %s", exc)
        raise self.retry(exc=exc)

    elapsed_ms = int((__import__("time").monotonic() - t_start) * 1000)

    logger.info(
        "[Task:reprocess_high_risk] Dispatched %d tasks | levels=%s | %dms",
        len(str_doc_ids), risk_levels, elapsed_ms,
    )

    return {
        "success":              True,
        "dry_run":              False,
        "organization_id":      organization_id,
        "risk_levels_targeted": risk_levels,
        "total_found":          total_found,
        "total_dispatched":     len(str_doc_ids),
        "document_ids":         str_doc_ids,
        "processing_time_ms":   elapsed_ms,
    }


# ── Scheduled tasks ───────────────────────────────────────────────────────────

@shared_task(name="documents.run_nightly_anomaly_scan")
def run_nightly_anomaly_scan():
    """
    Nightly scheduled task: scan all active organisations for transaction anomalies.

    Runs at 2:00 AM Asia/Riyadh (configured in CELERY_BEAT_SCHEDULE).
    Flags high/critical transactions and updates their risk scores.
    """
    import datetime
    from django.utils import timezone
    from apps.authentication.models import Organization
    from apps.transactions.models import Transaction
    from core.services.ai_service import detect_anomalies_ai

    yesterday = timezone.now().date() - datetime.timedelta(days=1)
    total_anomalies = 0

    for org in Organization.objects.filter(is_active=True):
        try:
            txs = list(
                Transaction.objects.filter(
                    organization=org,
                    transaction_date=yesterday,
                ).values(
                    "id", "transaction_type", "amount", "currency",
                    "vendor_name", "description", "transaction_date",
                )[:500]
            )

            if not txs:
                continue

            # Serialise for AI service
            for t in txs:
                t["id"]               = str(t["id"])
                t["amount"]           = float(t["amount"])
                t["transaction_date"] = str(t["transaction_date"])

            result = detect_anomalies_ai(txs)
            anomalies = result.get("anomalies", [])

            for anomaly in anomalies:
                if anomaly.get("severity") not in ("high", "critical"):
                    continue
                try:
                    tx = Transaction.objects.get(pk=anomaly["transaction_id"])
                    tx.is_flagged  = True
                    tx.risk_score  = anomaly.get("risk_score", 0)
                    tx.risk_level  = anomaly.get("severity", "low")
                    tx.flag_reason = anomaly.get("description", "")
                    tx.save(update_fields=["is_flagged", "risk_score", "risk_level", "flag_reason"])
                    total_anomalies += 1
                except Transaction.DoesNotExist:
                    pass

            logger.info(
                "[Task:nightly_scan] org=%s txs=%d anomalies=%d",
                org.name, len(txs), len(anomalies),
            )

        except Exception as exc:
            logger.error("[Task:nightly_scan] Failed for org %s: %s", org.name, exc)

    logger.info("[Task:nightly_scan] Complete. Total flagged: %d", total_anomalies)
    return {"total_anomalies_flagged": total_anomalies}


@shared_task(name="documents.generate_weekly_kpi_report")
def generate_weekly_kpi_report():
    """
    Weekly scheduled task: generate KPI reports for all active organisations.
    Runs Monday 6:00 AM Asia/Riyadh.
    """
    import datetime
    from apps.authentication.models import Organization
    from apps.reports.models import Report

    today    = datetime.date.today()
    week_ago = today - datetime.timedelta(days=7)
    created  = 0

    for org in Organization.objects.filter(is_active=True):
        try:
            Report.objects.create(
                organization=org,
                report_type="weekly_kpi",
                language="en",
                period_from=str(week_ago),
                period_to=str(today),
                title=f"Weekly KPI Report — {today}",
                data={},
                narrative={},
            )
            created += 1
            logger.info("[Task:weekly_kpi] Report created for %s", org.name)
        except Exception as exc:
            logger.error("[Task:weekly_kpi] Failed for %s: %s", org.name, exc)

    return {"reports_created": created}


# ── Internal helpers ──────────────────────────────────────────────────────────

def _safe_mark_failed(document_id: str, error: str):
    """Mark a document as FAILED without raising."""
    try:
        from apps.documents.models import Document
        Document.objects.filter(pk=document_id).update(
            processing_status=Document.ProcessingStatus.FAILED,
            processing_error=error[:2000],
        )
    except Exception as exc:
        logger.warning("[Task] Could not mark document %s as failed: %s", document_id, exc)


def _safe_mark_session_failed(session_id: str, error: str) -> None:
    """Transition AuditSession → FAILED and append the error to error_log."""
    if not session_id:
        return
    try:
        from apps.audit.models import AuditSession
        from apps.audit.session_service import AuditSessionService

        session = AuditSession.objects.get(pk=session_id)
        svc = AuditSessionService(session)
        if session.can_transition_to(AuditSession.State.FAILED):
            svc.transition(AuditSession.State.FAILED)
        # Append error to log regardless of transition success
        session.refresh_from_db(fields=["error_log"])
        session.error_log = (session.error_log or []) + [error[:500]]
        session.save(update_fields=["error_log"])
    except Exception as exc:
        logger.warning(
            "[Task] _safe_mark_session_failed: session=%s error=%s exc=%s",
            session_id, error, exc,
        )


def _recompute_zip_risk_summary(session) -> None:
    """
    Recompute overall_risk_score / overall_risk_level for a ZIP session
    using DocumentAnalysisResult records — because ZIP-extracted files are
    stored as Documents, not Invoices, and AuditSessionService._compute_risk_summary()
    only queries Invoice records (BUG-5 fix).

    Falls back to the existing Invoice-based computation if no analysis
    results are found (handles mixed sessions).
    """
    from django.db.models import Avg, Count
    from apps.audit.models import AuditSession
    from apps.documents.models import Document, DocumentAnalysisResult

    try:
        # Query DocumentAnalysisResult for all Documents in this session
        # that were created as zip_extracted children
        doc_qs = Document.objects.filter(
            organization=session.organization,
            tags__contains=f"source_zip:",   # tagged by process_zip_task
        )
        agg = DocumentAnalysisResult.objects.filter(
            document__in=doc_qs,
        ).aggregate(
            avg_risk=Avg("risk_score"),
            total=Count("id"),
        )

        total_results = agg.get("total") or 0
        avg_score     = float(agg.get("avg_risk") or 0)

        if total_results == 0:
            # No DocumentAnalysisResult found — fall back to Invoice-based query
            from apps.audit.session_service import AuditSessionService
            AuditSessionService(session)._compute_risk_summary()
            logger.debug(
                "[_recompute_zip_risk_summary] No DocumentAnalysisResult for session=%s "
                "— fell back to Invoice query",
                session.pk,
            )
            return

        # Map score to level
        if avg_score >= 75:
            level = "critical"
        elif avg_score >= 50:
            level = "high"
        elif avg_score >= 25:
            level = "medium"
        else:
            level = "low"

        AuditSession.objects.filter(pk=session.pk).update(
            overall_risk_score=avg_score,
            overall_risk_level=level,
        )
        session.refresh_from_db()

        logger.info(
            "[_recompute_zip_risk_summary] session=%s avg_risk=%.1f level=%s "
            "computed from %d DocumentAnalysisResult records",
            session.pk, avg_score, level, total_results,
        )

    except Exception as exc:
        logger.warning(
            "[_recompute_zip_risk_summary] Failed for session=%s: %s — "
            "overall_risk_score may be inaccurate",
            session.pk, exc,
        )


def _record_session_result(session_id: str, task_result: dict) -> None:
    """
    Atomically update AuditSession counters after one child task finishes.
    Uses F() expressions inside AuditSessionService.record_document_result()
    to handle concurrent updates from multiple workers safely.
    """
    if not session_id:
        return
    try:
        from apps.audit.models import AuditSession
        from apps.audit.session_service import AuditSessionService

        session = AuditSession.objects.get(pk=session_id)
        svc = AuditSessionService(session)
        svc.record_document_result(
            success=bool(task_result.get("success")),
            requires_review=bool(task_result.get("requires_review")),
            risk_score=float(task_result.get("risk_score") or 0),
            is_duplicate=bool(task_result.get("is_duplicate")),
            has_compliance_issue=float(task_result.get("compliance_score", 1.0)) < 0.8,
            error_msg=(task_result.get("error") or "")[:500],
        )
    except Exception as exc:
        logger.warning(
            "[Task] _record_session_result failed for session=%s: %s",
            session_id, exc,
        )
