"""
Invoice Upload Pipeline — Class-Based Architecture
===================================================

Applies SOLID principles to the invoice upload workflow:

  SRP  — each class has exactly one reason to change
  OCP  — new file types are added by subclassing FileHandlerBase only
  LSP  — all handlers are drop-in replacements for FileHandlerBase
  ISP  — FileHandlerBase exposes only what concrete handlers need
  DIP  — InvoiceUploadOrchestrator depends on FileHandlerBase (abstract), not on
         ZipFileHandler / CsvFileHandler (concrete)

Class map:
  FileProcessingContext        — immutable shared context per upload request
  FileHandlerResult            — typed return value (replaces dict guessing)
  FileHandlerBase (ABC)        — Strategy interface
    ├── SingleFileHandler      — .pdf / .jpg / .png / .xlsx / ...
    ├── ZipFileHandler         — .zip  (zip-slip protected)
    ├── CsvFileHandler         — .csv / .tsv  (multi-row expansion)
    └── JsonFileHandler        — .json  (list-expansion + single-dict)
  FileHandlerFactory           — maps extension → handler instance
  RiskAssessor                 — risk-score computation, merging, status updates
  VendorProfileManager         — vendor history lookup and profile aggregation
  InvoiceUploadOrchestrator    — public API consumed by InvoiceUploadView
"""

from __future__ import annotations

import io
import logging
import os
import zipfile
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import IO, TYPE_CHECKING

if TYPE_CHECKING:
    from apps.authentication.models import Organization, User
    from apps.invoices.models import Invoice, InvoiceBatch

logger = logging.getLogger("finai")


# ── Allowed sets ───────────────────────────────────────────────────────────────

ALLOWED_EXTENSIONS: frozenset[str] = frozenset({
    ".pdf", ".jpg", ".jpeg", ".png", ".tiff", ".tif",
    ".xlsx", ".xls", ".csv", ".tsv", ".json", ".zip",
})

ALLOWED_MIME_TYPES: frozenset[str] = frozenset({
    "application/pdf", "image/jpeg", "image/png", "image/tiff",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.ms-excel",
    "text/csv", "text/plain", "text/tab-separated-values",
    "application/csv", "application/zip", "application/x-zip-compressed",
    "application/json", "application/octet-stream",
})

_MIME_MAP: dict[str, str] = {
    ".pdf":   "application/pdf",
    ".jpg":   "image/jpeg",
    ".jpeg":  "image/jpeg",
    ".png":   "image/png",
    ".tiff":  "image/tiff",
    ".tif":   "image/tiff",
    ".xlsx":  "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".xls":   "application/vnd.ms-excel",
    ".csv":   "text/csv",
    ".tsv":   "text/tab-separated-values",
    ".json":  "application/json",
    ".zip":   "application/zip",
}


# ── Shared context ─────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class FileProcessingContext:
    """
    Immutable shared context passed to every FileHandler.

    Using a frozen dataclass guarantees that no handler accidentally
    mutates shared state — all handlers read from it but never write to it.
    """
    organization: "Organization"
    user: "User"
    batch: "InvoiceBatch"
    request: object  # Django HttpRequest — kept generic to avoid circular import


# ── Result type ────────────────────────────────────────────────────────────────

@dataclass
class FileHandlerResult:
    """
    Typed return value from every FileHandler.process() call.

    Replaces the raw dicts that were scattered across the old module-level
    functions — enables static analysis and removes string-key guessing.
    """
    results: list[dict] = field(default_factory=list)
    errors:  list[dict] = field(default_factory=list)

    # Expansion flag: True when the handler produced multiple logical documents
    # from a single physical file (ZIP, CSV, JSON array).
    was_expanded: bool = False

    @property
    def success_count(self) -> int:
        return len(self.results)

    @property
    def error_count(self) -> int:
        return len(self.errors)

    def merge(self, other: "FileHandlerResult") -> None:
        """In-place merge another result set into this one."""
        self.results.extend(other.results)
        self.errors.extend(other.errors)


# ── Abstract Strategy (Interface) ─────────────────────────────────────────────

class FileHandlerBase(ABC):
    """
    Abstract base class — the Strategy interface for file processing.

    Every concrete handler MUST implement process() and CAN override validate().
    Nothing else is assumed about the handler.

    OCP: adding a new file type = adding a new subclass here + one line in
    FileHandlerFactory. The orchestrator and the view never change.
    """

    # Subclasses declare which extensions they handle (used by factory).
    handled_extensions: frozenset[str] = frozenset()

    def __init__(self, ctx: FileProcessingContext) -> None:
        self._ctx = ctx

    @abstractmethod
    def process(self, file_obj: IO[bytes], filename: str) -> FileHandlerResult:
        """
        Process a file and return structured results + errors.

        Args:
            file_obj: File-like object (seekable bytes stream).
            filename: Original filename including extension.

        Returns:
            FileHandlerResult with populated results and/or errors.
        """

    def validate(self, filename: str, file_obj: IO[bytes]) -> str | None:
        """
        Optional pre-processing validation hook.

        Returns an error message string if validation fails, None if OK.
        Subclasses may override; default implementation checks extension only.
        """
        ext = os.path.splitext(filename)[1].lower()
        if ext not in ALLOWED_EXTENSIONS:
            return f"نوع الملف غير مدعوم: {ext}"
        return None

    # ── Protected helpers ──────────────────────────────────────────────────────

    def _run_invoice_pipeline(self, file_obj: IO[bytes], filename: str) -> dict:
        """
        Delegate to the existing _process_single_file function.

        This bridge method is intentionally thin: it lets us replace the
        legacy function with a proper class later without touching each handler.
        """
        from apps.invoices.views import _process_single_file
        return _process_single_file(
            file_obj, filename,
            self._ctx.organization,
            self._ctx.user,
            self._ctx.batch,
            self._ctx.request,
        )

    @staticmethod
    def _mime_for_ext(ext: str) -> str:
        return _MIME_MAP.get(ext, "application/octet-stream")


# ── Concrete Handlers ──────────────────────────────────────────────────────────

class SingleFileHandler(FileHandlerBase):
    """
    Handles a single invoice document (.pdf, .jpg, .xlsx, etc.).

    SRP: one responsibility — run exactly one document through the pipeline.
    """

    handled_extensions: frozenset[str] = frozenset({
        ".pdf", ".jpg", ".jpeg", ".png", ".tiff", ".tif",
        ".xlsx", ".xls", ".txt",
    })

    def process(self, file_obj: IO[bytes], filename: str) -> FileHandlerResult:
        """Process a single invoice file through the full AI pipeline."""
        result = FileHandlerResult()
        try:
            r = self._run_invoice_pipeline(file_obj, filename)
            result.results.append(r)
            self._ctx.batch.processed_files += 1
        except Exception as exc:
            logger.error("[SingleFileHandler] %s failed: %s", filename, exc)
            result.errors.append({"filename": filename, "error": str(exc)})
            self._ctx.batch.failed_files += 1
        return result


class ZipFileHandler(FileHandlerBase):
    """
    Handles ZIP archives — extracts each member and delegates to SingleFileHandler.

    Security guarantees (Phase 5 / Phase 12):
      - Zip-slip protection: rejects members with '..' or absolute paths
      - Member count cap: MAX_MEMBERS (500)
      - Member size cap:  MAX_MEMBER_BYTES (50 MB)
    """

    handled_extensions: frozenset[str] = frozenset({".zip"})

    MAX_MEMBERS: int = 500
    MAX_MEMBER_BYTES: int = 50 * 1024 * 1024  # 50 MB

    # Extensions accepted inside a ZIP (narrower than top-level to avoid recursion)
    _INNER_EXTENSIONS: frozenset[str] = frozenset({
        ".pdf", ".jpg", ".jpeg", ".png", ".tiff", ".tif",
        ".xlsx", ".xls", ".json", ".csv",
    })

    def process(self, file_obj: IO[bytes], filename: str) -> FileHandlerResult:
        """Extract ZIP and process each eligible member."""
        result = FileHandlerResult(was_expanded=True)

        try:
            archive_bytes = file_obj.read()
            with zipfile.ZipFile(io.BytesIO(archive_bytes), "r") as zf:
                members = [m for m in zf.infolist() if not m.is_dir()]

                if len(members) > self.MAX_MEMBERS:
                    result.errors.append({
                        "filename": filename,
                        "error": f"الأرشيف يحتوي على أكثر من {self.MAX_MEMBERS} ملف.",
                    })
                    return result

                for member in members:
                    member_result = self._process_member(zf, member, filename)
                    result.merge(member_result)

        except zipfile.BadZipFile:
            result.errors.append({"filename": filename, "error": "ملف ZIP تالف أو غير صالح."})
        except Exception as exc:
            logger.exception("[ZipFileHandler] Unexpected error for %s: %s", filename, exc)
            result.errors.append({"filename": filename, "error": str(exc)})

        return result

    def _process_member(
        self,
        zf: zipfile.ZipFile,
        member: zipfile.ZipInfo,
        archive_name: str,
    ) -> FileHandlerResult:
        """Process one member inside a ZIP archive."""
        result = FileHandlerResult()
        raw_path = member.filename

        # ── Zip-slip guard ─────────────────────────────────────────────────────
        if ".." in raw_path or raw_path.startswith(("/", "\\")):
            logger.warning("[ZipFileHandler] Zip-slip attempt blocked: %s", raw_path)
            result.errors.append({
                "filename": raw_path,
                "error":    "محاولة Path Traversal محظورة.",
            })
            return result

        name = os.path.basename(raw_path)
        if not name:
            return result

        ext = os.path.splitext(name)[1].lower()
        if ext not in self._INNER_EXTENSIONS:
            return result  # silently skip unsupported members

        # ── Size guard ─────────────────────────────────────────────────────────
        if member.file_size > self.MAX_MEMBER_BYTES:
            size_mb = member.file_size // (1024 * 1024)
            result.errors.append({
                "filename": name,
                "error":    f"الملف كبير جداً ({size_mb} MB). الحد الأقصى 50 MB.",
            })
            self._ctx.batch.failed_files += 1
            return result

        try:
            data = zf.read(member)
            inner = io.BytesIO(data)
            inner.name = name
            inner.content_type = self._mime_for_ext(ext)  # type: ignore[attr-defined]
            sub_result = self._run_invoice_pipeline(inner, name)
            result.results.append(sub_result)
            self._ctx.batch.processed_files += 1
        except Exception as exc:
            logger.error("[ZipFileHandler] Member %s failed: %s", name, exc)
            result.errors.append({"filename": name, "error": str(exc)})
            self._ctx.batch.failed_files += 1

        return result


class CsvFileHandler(FileHandlerBase):
    """
    Handles CSV / TSV files by expanding each data row into a separate invoice.

    Falls back to SingleFileHandler semantics (returns empty FileHandlerResult)
    when the file has ≤1 data row — the orchestrator then re-routes to
    SingleFileHandler, preserving the original behaviour.

    SRP: this class only knows how to split CSV rows; it delegates actual
    invoice processing to _run_invoice_pipeline().
    """

    handled_extensions: frozenset[str] = frozenset({".csv", ".tsv"})

    def process(self, file_obj: IO[bytes], filename: str) -> FileHandlerResult:
        """Parse CSV rows and process each as an independent invoice."""
        result = FileHandlerResult(was_expanded=True)

        try:
            import pandas as pd

            raw = file_obj.read()
            file_obj.seek(0)

            delimiter = self._detect_delimiter(raw)
            df = pd.read_csv(
                io.BytesIO(raw),
                sep=delimiter,
                dtype=str,
                keep_default_na=False,
            )

            if len(df) <= 1:
                # Signal: caller should treat as single file
                return FileHandlerResult(was_expanded=False)

            base_name = os.path.splitext(filename)[0]

            for idx, row in df.iterrows():
                row_filename = f"{base_name}_row{idx + 1}.json"
                row_dict = {k: v for k, v in row.items() if v}
                row_bytes = io.BytesIO(
                    __import__("json").dumps(row_dict, ensure_ascii=False).encode("utf-8")
                )
                row_bytes.name = row_filename
                row_bytes.content_type = "application/json"  # type: ignore[attr-defined]

                try:
                    r = self._run_invoice_pipeline(row_bytes, row_filename)
                    result.results.append(r)
                    self._ctx.batch.processed_files += 1
                except Exception as exc:
                    logger.error("[CsvFileHandler] Row %d failed: %s", idx + 1, exc)
                    result.errors.append({"filename": row_filename, "error": str(exc)})
                    self._ctx.batch.failed_files += 1

        except ImportError:
            result.errors.append({"filename": filename, "error": "مكتبة pandas غير مثبتة."})
        except Exception as exc:
            logger.exception("[CsvFileHandler] Failed for %s: %s", filename, exc)
            result.errors.append({"filename": filename, "error": str(exc)})

        return result

    @staticmethod
    def _detect_delimiter(raw: bytes) -> str:
        """Auto-detect CSV delimiter from the first 4 KB of file content."""
        sample = raw[:4096].decode("utf-8", errors="replace")
        counts = {d: sample.count(d) for d in (",", ";", "\t", "|")}
        return max(counts, key=counts.get)  # type: ignore[arg-type]


class JsonFileHandler(FileHandlerBase):
    """
    Handles JSON files.

    - JSON array  → each dict element becomes a separate invoice.
    - JSON object → single dict, falls back to SingleFileHandler.
    """

    handled_extensions: frozenset[str] = frozenset({".json", ".jsonl"})

    def process(self, file_obj: IO[bytes], filename: str) -> FileHandlerResult:
        """Expand JSON arrays into per-item invoices."""
        result = FileHandlerResult(was_expanded=True)

        try:
            import json
            raw = file_obj.read()
            parsed = json.loads(raw.decode("utf-8", errors="replace"))

            if not isinstance(parsed, list):
                # Single dict — signal caller to treat as single file
                return FileHandlerResult(was_expanded=False)

            base_name = os.path.splitext(filename)[0]

            for idx, item in enumerate(parsed):
                if not isinstance(item, dict):
                    continue
                item_filename = f"{base_name}_item{idx + 1}.json"
                item_bytes = io.BytesIO(
                    json.dumps(item, ensure_ascii=False).encode("utf-8")
                )
                item_bytes.name = item_filename
                item_bytes.content_type = "application/json"  # type: ignore[attr-defined]

                try:
                    r = self._run_invoice_pipeline(item_bytes, item_filename)
                    result.results.append(r)
                    self._ctx.batch.processed_files += 1
                except Exception as exc:
                    logger.error("[JsonFileHandler] Item %d failed: %s", idx + 1, exc)
                    result.errors.append({"filename": item_filename, "error": str(exc)})
                    self._ctx.batch.failed_files += 1

        except Exception as exc:
            logger.exception("[JsonFileHandler] Failed for %s: %s", filename, exc)
            result.errors.append({"filename": filename, "error": str(exc)})

        return result


# ── Factory ────────────────────────────────────────────────────────────────────

class FileHandlerFactory:
    """
    Resolves the correct FileHandler for a given file extension.

    OCP in action: registering a new handler = one entry in _REGISTRY.
    The orchestrator never needs to change its import list.

    DIP: callers depend on FileHandlerBase, not on concrete classes.
    """

    _REGISTRY: dict[str, type[FileHandlerBase]] = {}

    @classmethod
    def _build_registry(cls) -> None:
        """Lazily populate the registry from handler declarations."""
        if cls._REGISTRY:
            return
        for handler_cls in (
            SingleFileHandler,
            ZipFileHandler,
            CsvFileHandler,
            JsonFileHandler,
        ):
            for ext in handler_cls.handled_extensions:
                cls._REGISTRY[ext] = handler_cls

    @classmethod
    def create(cls, extension: str, ctx: FileProcessingContext) -> FileHandlerBase:
        """
        Return the correct handler for the given extension.

        Falls back to SingleFileHandler for unknown extensions so the
        pipeline never raises a KeyError.
        """
        cls._build_registry()
        handler_cls = cls._REGISTRY.get(extension.lower(), SingleFileHandler)
        return handler_cls(ctx)

    @classmethod
    def is_supported(cls, extension: str) -> bool:
        """Return True if the extension has a registered handler."""
        cls._build_registry()
        return extension.lower() in cls._REGISTRY


# ── Risk Assessor ──────────────────────────────────────────────────────────────

class RiskAssessor:
    """
    Encapsulates all risk score logic.

    SRP: the only class responsible for computing, merging, and persisting
    risk signals on an Invoice.  Previously this was split across three
    module-level functions (_fallback_risk_score, _merge_risk_assessment,
    _risk_level_from_score).
    """

    # Category-specific minimum risk floors
    _CATEGORY_FLOORS: dict[str, int] = {
        "duplicate":   60,
        "compliance":  40,
        "fraud":       70,
    }

    @staticmethod
    def risk_level_from_score(score: float) -> str:
        """Map numeric score (0–100) to a human-readable risk level."""
        if score >= 75:
            return "critical"
        if score >= 50:
            return "high"
        if score >= 25:
            return "medium"
        return "low"

    def fallback_score(self, validation_result) -> int:
        """
        Compute a rule-based fallback risk score when the AI pipeline
        produces no score.  Uses the validation result flags to infer risk.
        """
        if validation_result is None:
            return 0

        score = 0

        if getattr(validation_result, "duplicate_invoice_number", False):
            score = max(score, self._CATEGORY_FLOORS["duplicate"])
        if getattr(validation_result, "duplicate_vendor_amount_date", False):
            score = max(score, self._CATEGORY_FLOORS["duplicate"])
        if not getattr(validation_result, "vat_rate_correct", True):
            score = max(score, self._CATEGORY_FLOORS["compliance"])
        if not getattr(validation_result, "vat_calculation_correct", True):
            score = max(score, self._CATEGORY_FLOORS["compliance"])
        if getattr(validation_result, "amount_unusually_high", False):
            score = max(score, self._CATEGORY_FLOORS["fraud"])

        # Small penalty per missing required field
        missing_penalties = [
            "has_invoice_number", "has_invoice_date",
            "has_vendor_name", "has_vendor_vat",
            "has_total_amount",
        ]
        for attr in missing_penalties:
            if not getattr(validation_result, attr, True):
                score = min(score + 8, 100)

        return score

    def merge_and_persist(
        self,
        invoice: "Invoice",
        validation_result,
        ai_risk_result: dict | None,
    ) -> None:
        """
        Merge AI-computed and rule-based risk scores, then persist to Invoice.

        The final score is max(ai_score, fallback_score) to ensure the
        worst-case risk is always surfaced.
        """
        from decimal import Decimal, InvalidOperation

        ai_score = 0
        if ai_risk_result:
            try:
                ai_score = int(float(ai_risk_result.get("risk_score") or 0))
            except (TypeError, ValueError):
                ai_score = 0

        fallback = self.fallback_score(validation_result)
        final_score = max(ai_score, fallback)
        final_level = self.risk_level_from_score(final_score)

        invoice.risk_score = final_score
        invoice.risk_level = final_level

        # Propagate status from risk
        if final_level in ("high", "critical"):
            invoice.status = "flagged"
        elif invoice.status == "pending":
            invoice.status = "approved"

        invoice.save(update_fields=["risk_score", "risk_level", "status", "updated_at"])
        logger.debug(
            "[RiskAssessor] Invoice %s — score=%d level=%s",
            invoice.id, final_score, final_level,
        )


# ── Vendor Profile Manager ─────────────────────────────────────────────────────

class VendorProfileManager:
    """
    Handles all vendor history lookups and profile updates.

    SRP: the only class responsible for maintaining VendorProfile records.
    Previously this was split across _get_vendor_history() and
    _update_vendor_profile() module-level functions.
    """

    def __init__(self, organization: "Organization") -> None:
        self._org = organization

    def get_history(self, vendor_name: str) -> dict:
        """
        Retrieve aggregated vendor history.

        Returns a dict with avg_invoice_amount, invoice_count, risk_tier,
        and is_new_vendor flag.  Falls back to sane defaults on any error.
        """
        if not vendor_name:
            return self._default_history()

        try:
            from apps.invoices.models import VendorProfile

            profile = VendorProfile.objects.filter(
                organization=self._org,
                vendor_name__iexact=vendor_name,
            ).first()

            if not profile:
                return {**self._default_history(), "is_new_vendor": True}

            return {
                "vendor_name":        profile.vendor_name,
                "avg_invoice_amount": float(profile.avg_invoice_amount or 0),
                "invoice_count":      profile.invoice_count,
                "risk_tier":          profile.risk_tier,
                "is_new_vendor":      False,
            }
        except Exception as exc:
            logger.debug("[VendorProfileManager] History lookup failed: %s", exc)
            return self._default_history()

    def update_profile(self, invoice: "Invoice") -> None:
        """
        Recompute aggregate stats for the vendor on the given invoice and
        persist them to VendorProfile.  Safe to call after every upload.
        """
        vendor_name = (invoice.vendor_name or "").strip()
        if not vendor_name:
            return

        try:
            from django.db.models import Avg, Count, Max
            from apps.invoices.models import Invoice, VendorProfile

            agg = Invoice.objects.filter(
                organization=self._org,
                vendor_name__iexact=vendor_name,
            ).aggregate(
                count=Count("id"),
                avg_amount=Avg("total_amount"),
                max_risk=Max("risk_score"),
            )

            profile, _ = VendorProfile.objects.get_or_create(
                organization=self._org,
                vendor_name=vendor_name,
                defaults={"vendor_vat_number": invoice.vendor_vat_number or ""},
            )

            profile.invoice_count       = agg["count"] or 0
            profile.avg_invoice_amount  = agg["avg_amount"] or 0
            profile.last_invoice_date   = invoice.invoice_date

            # Promote risk tier based on max risk score seen
            max_risk = agg["max_risk"] or 0
            if max_risk >= 75:
                profile.risk_tier = VendorProfile.RiskTier.HIGH
            elif max_risk >= 50:
                profile.risk_tier = VendorProfile.RiskTier.MEDIUM
            else:
                profile.risk_tier = VendorProfile.RiskTier.LOW

            profile.save()
            logger.debug("[VendorProfileManager] Updated profile for '%s'", vendor_name)

        except Exception as exc:
            logger.warning("[VendorProfileManager] Profile update failed for '%s': %s", vendor_name, exc)

    @staticmethod
    def _default_history() -> dict:
        return {
            "vendor_name":        "",
            "avg_invoice_amount": 0.0,
            "invoice_count":      0,
            "risk_tier":          "low",
            "is_new_vendor":      True,
        }


# ── Upload Orchestrator ────────────────────────────────────────────────────────

class InvoiceUploadOrchestrator:
    """
    Public API for the invoice upload workflow.

    Responsibilities:
      1. Create InvoiceBatch + AuditSession (if session service available)
      2. Route each uploaded file to the correct FileHandler via Factory
      3. Handle single-file fallback for CSV/JSON that didn't expand
      4. Finalize batch status
      5. Dispatch async AuditSession processing

    DIP: depends on FileHandlerBase (abstract), not on any concrete handler.

    Usage:
        orchestrator = InvoiceUploadOrchestrator(request)
        response_data = orchestrator.process(uploaded_files, batch_name)
    """

    def __init__(self, request) -> None:
        self._request = request
        self._org = request.user.organization
        self._user = request.user
        self._risk_assessor = RiskAssessor()
        self._vendor_manager = VendorProfileManager(self._org)

    # ── Public entry point ─────────────────────────────────────────────────────

    def process(
        self,
        uploaded_files: list,
        batch_name: str,
    ) -> dict:
        """
        Process a list of uploaded files and return the upload summary.

        Args:
            uploaded_files: List of Django InMemoryUploadedFile objects.
            batch_name:     Human-readable name for this upload batch.

        Returns:
            Dict suitable for a DRF Response containing batch_id, session_id,
            processed count, errors, and per-file results.
        """
        audit_session = self._create_audit_session(len(uploaded_files), batch_name)
        batch = self._create_batch(batch_name, len(uploaded_files), audit_session)

        ctx = FileProcessingContext(
            organization=self._org,
            user=self._user,
            batch=batch,
            request=self._request,
        )

        all_results: list[dict] = []
        all_errors:  list[dict] = []

        for uploaded_file in uploaded_files:
            filename = uploaded_file.name
            ext = os.path.splitext(filename)[1].lower()

            if not FileHandlerFactory.is_supported(ext):
                all_errors.append({"filename": filename, "error": f"نوع الملف غير مدعوم: {ext}"})
                batch.failed_files += 1
                continue

            handler = FileHandlerFactory.create(ext, ctx)
            file_result = handler.process(uploaded_file, filename)

            # Expansion fallback: CSV/JSON that didn't expand → reprocess as single file
            if not file_result.was_expanded and not file_result.results and not file_result.errors:
                uploaded_file.seek(0)
                single_handler = SingleFileHandler(ctx)
                file_result = single_handler.process(uploaded_file, filename)
            else:
                # Update batch total if expansion changed the file count
                expansion_delta = (file_result.success_count + file_result.error_count) - 1
                if file_result.was_expanded and expansion_delta != 0:
                    batch.total_files += expansion_delta

            all_results.extend(file_result.results)
            all_errors.extend(file_result.errors)

        self._finalize_batch(batch, all_results, all_errors)
        self._update_audit_session(audit_session, all_results, all_errors)

        return {
            "batch_id":    str(batch.id),
            "batch_name":  batch_name,
            "session_id":  str(audit_session.id) if audit_session else None,
            "total_files": len(all_results) + len(all_errors),
            "processed":   len(all_results),
            "failed":      len(all_errors),
            "status":      batch.status,
            "results":     all_results,
            "errors":      all_errors,
        }

    # ── Private helpers ────────────────────────────────────────────────────────

    def _create_batch(
        self,
        batch_name: str,
        file_count: int,
        audit_session,
    ) -> "InvoiceBatch":
        """Create and persist an InvoiceBatch for this upload."""
        from apps.invoices.models import InvoiceBatch
        return InvoiceBatch.objects.create(
            organization=self._org,
            uploaded_by=self._user,
            audit_session=audit_session,
            batch_name=batch_name,
            total_files=file_count,
        )

    def _create_audit_session(self, file_count: int, name: str):
        """Create an AuditSession — silently returns None on failure."""
        try:
            from apps.audit.session_service import AuditSessionService
            svc = AuditSessionService.create_session(
                organization=self._org,
                created_by=self._user,
                total_count=file_count,
                session_name=name,
            )
            return svc.session
        except Exception as exc:
            logger.warning("[InvoiceUploadOrchestrator] AuditSession creation failed: %s", exc)
            return None

    def _finalize_batch(
        self,
        batch: "InvoiceBatch",
        results: list[dict],
        errors: list[dict],
    ) -> None:
        """Set batch final status and persist."""
        from apps.invoices.models import InvoiceBatch
        from django.utils import timezone

        if not errors:
            batch.status = InvoiceBatch.BatchStatus.COMPLETED
        elif results:
            batch.status = InvoiceBatch.BatchStatus.PARTIAL
        else:
            batch.status = InvoiceBatch.BatchStatus.FAILED

        batch.completed_at   = timezone.now()
        batch.processing_log = results + errors
        batch.save()

    def _update_audit_session(
        self,
        audit_session,
        results: list[dict],
        errors: list[dict],
    ) -> None:
        """Record per-document outcomes on the AuditSession and dispatch task."""
        if not audit_session:
            return

        try:
            from apps.audit.models import AuditSession
            from apps.audit.session_service import AuditSessionService
            from apps.audit.tasks import process_audit_session

            svc = AuditSessionService(audit_session)
            actual_total = len(results) + len(errors)

            if actual_total != audit_session.total_count:
                AuditSession.objects.filter(pk=audit_session.pk).update(
                    total_count=actual_total
                )

            for r in results:
                svc.record_document_result(
                    success=True,
                    requires_review=r.get("risk_level") in ("high", "critical"),
                    risk_score=float(r.get("risk_score") or 0),
                    is_duplicate=bool(r.get("is_duplicate")),
                    has_compliance_issue=bool(r.get("compliance_issues")),
                )

            for _ in errors:
                svc.record_document_result(
                    success=False,
                    error_msg=_.get("error", ""),
                )

            process_audit_session.delay(session_id=str(audit_session.id))

        except Exception as exc:
            logger.warning("[InvoiceUploadOrchestrator] AuditSession update failed: %s", exc)
