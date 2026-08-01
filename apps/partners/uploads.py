"""Upload security for partner application documents (§E.5 / §N).

This is the only place in the product where an **unauthenticated stranger**
writes a file. Everything here assumes the submitter is hostile.

Why this is stricter than ``core.utils.file_validation``
--------------------------------------------------------
That module is the general-purpose validator and accepts a broad set
(zip, csv, xlsx, …) because the audit pipeline needs them. Two properties make
it unsuitable as-is for this surface:

1. Its allow-list is far wider than partner documents need.
2. Without ``python-magic`` installed — and it is **not** installed here — its
   fallback seeds the detected type from ``mimetypes.guess_type(filename)``,
   i.e. from the **extension**. A ``.pdf`` full of HTML can therefore pass. The
   spec is explicit that an extension is a claim, not evidence.

So this module requires a **positive magic-byte match** against a short list
and never infers type from the name. It reuses the project's
``DANGEROUS_SIGNATURES`` and the ``upload_guard`` extension helper rather than
restating them.

No antivirus
------------
There is no AV scanner in this project — no ClamAV, no scanning service, and
``python-magic`` is absent too. These files are validated, not scanned. That
limitation is stated in the Phase 2B report rather than implied away.
"""

from __future__ import annotations

import os
import uuid

from django.conf import settings
from django.core.files.storage import FileSystemStorage
from django.utils.translation import gettext_lazy as _

from core.utils.file_validation import DANGEROUS_SIGNATURES


class UploadRejected(ValueError):
    """A submitted file failed validation. The message is safe to show a user."""


#: Extensions accepted for partner documents. Everything else is rejected —
#: including svg (a script vector), html, and every archive format.
ALLOWED_EXTENSIONS = frozenset({".pdf", ".png", ".jpg", ".jpeg"})

#: Extensions called out explicitly so the rejection message can be specific
#: and so the intent survives a future edit to ALLOWED_EXTENSIONS.
EXPLICITLY_REJECTED = frozenset({
    ".svg", ".html", ".htm", ".xhtml", ".js", ".mjs",
    ".zip", ".rar", ".7z", ".tar", ".gz", ".bz2",
    ".exe", ".dll", ".so", ".sh", ".bat", ".cmd", ".com", ".msi",
    ".php", ".jsp", ".asp", ".aspx", ".py", ".rb", ".pl",
})

#: (magic prefix, canonical content type, allowed extensions for it).
#: A file must match one of these on its ACTUAL BYTES. There is no
#: extension-based fallback: an unrecognised header is a rejection.
_MAGIC = (
    (b"%PDF-", "application/pdf", {".pdf"}),
    (b"\x89PNG\r\n\x1a\n", "image/png", {".png"}),
    (b"\xff\xd8\xff", "image/jpeg", {".jpg", ".jpeg"}),
)

#: Bytes read for sniffing. Enough for every signature above plus slack.
_SNIFF_BYTES = 4096


class PartnerDocumentStorage(FileSystemStorage):
    """Private storage for partner documents. Two guarantees, both enforced.

    **1. There is no URL.** ``FileSystemStorage`` treats ``base_url=None`` as
    "fall back to ``settings.MEDIA_URL``" (see ``_value_or_setting``), so simply
    passing None does NOT make the file unaddressable — it hands back a
    ``/media/...`` path. An earlier version of this class relied on that and was
    wrong; the test asserting ``.url`` raises is what caught it. ``url()`` now
    raises explicitly, so rendering one of these in a template fails loudly
    instead of quietly publishing a commercial registration.

    **2. The location is resolved on every access**, not captured at import.
    ``FileSystemStorage.location`` is a ``cached_property``, which meant the
    root was frozen at module import and ``settings.PARTNER_DOCS_ROOT`` could
    not be redirected afterwards — including in tests, which wrote hostile
    fixtures into the developer's real private directory. Reading the setting
    each time keeps deployment (env var) and tests (override) both working.
    """

    def __init__(self):
        super().__init__(location=str(settings.PARTNER_DOCS_ROOT), base_url=None)

    @property
    def base_location(self):
        return str(settings.PARTNER_DOCS_ROOT)

    @property
    def location(self):
        return os.path.abspath(self.base_location)

    def url(self, name):
        raise ValueError(
            "Partner application documents have no public URL by design. "
            "Serve them through the staff-only download endpoint "
            "(apps/partners/views.PartnerApplicationAttachmentDownloadView), "
            "which checks permission per request and logs the access."
        )


def get_private_storage() -> FileSystemStorage:
    """Storage for partner documents — private, and not URL-addressable."""
    return PartnerDocumentStorage()


def safe_stored_name(original_name: str, extension: str) -> str:
    """Generate the on-disk name. The client's filename is NEVER reused.

    A submitted name can carry path traversal (``../../etc/passwd``), null
    bytes, control characters, or a second extension (``x.pdf.exe``). Rather
    than sanitising — which is a blocklist in disguise — the stored name is
    generated from a UUID plus the extension we ourselves validated. The
    original is kept only as a display string on the model.
    """
    return f"{uuid.uuid4().hex}{extension}"


def display_name(original_name: str) -> str:
    """The client filename, reduced to something safe to render.

    Path components are stripped so a traversal attempt cannot even be echoed
    back into a page or a report, and the result is length-bounded.
    """
    name = (original_name or "").replace("\x00", "")
    # Both separators: a Windows client may send backslashes.
    name = name.replace("\\", "/").split("/")[-1]
    name = "".join(ch for ch in name if ch.isprintable()).strip()
    return name[:200] or "unnamed"


def _extension_of(filename: str) -> str:
    return os.path.splitext(filename or "")[1].lower()


def validate_upload(uploaded_file, *, max_bytes: int | None = None) -> dict:
    """Validate one submitted file. Returns metadata, or raises UploadRejected.

    Order matters: cheap checks first, so a hostile 500 MB upload is refused on
    size before anything reads its content.

    Nothing is written to storage by this function. The caller persists only
    after every file in the submission has passed.
    """
    original = getattr(uploaded_file, "name", "") or ""
    extension = _extension_of(original)
    size = getattr(uploaded_file, "size", 0) or 0

    if size <= 0:
        raise UploadRejected(_("The file %(name)s is empty.") % {"name": display_name(original)})

    limit = max_bytes if max_bytes is not None else settings.PARTNER_DOC_MAX_FILE_MB * 1024 * 1024
    if size > limit:
        raise UploadRejected(
            _("%(name)s exceeds the %(mb)s MB per-file limit.")
            % {"name": display_name(original), "mb": settings.PARTNER_DOC_MAX_FILE_MB}
        )

    if extension in EXPLICITLY_REJECTED:
        raise UploadRejected(
            _("%(ext)s files are not accepted. Allowed types: PDF, PNG, JPG.")
            % {"ext": extension}
        )

    if extension not in ALLOWED_EXTENSIONS:
        raise UploadRejected(
            _("%(name)s has an unsupported type. Allowed types: PDF, PNG, JPG.")
            % {"name": display_name(original)}
        )

    # ── content check — the extension has told us nothing yet ───────────────
    uploaded_file.seek(0)
    head = uploaded_file.read(_SNIFF_BYTES)
    uploaded_file.seek(0)

    for signature, description in DANGEROUS_SIGNATURES:
        if head.startswith(signature):
            raise UploadRejected(
                _("%(name)s was detected as %(kind)s and cannot be accepted.")
                % {"name": display_name(original), "kind": description}
            )

    detected = None
    for magic, content_type, valid_extensions in _MAGIC:
        if head.startswith(magic):
            if extension not in valid_extensions:
                raise UploadRejected(
                    _("%(name)s claims to be %(ext)s but its contents are %(actual)s.")
                    % {
                        "name": display_name(original),
                        "ext": extension,
                        "actual": content_type,
                    }
                )
            detected = content_type
            break

    if detected is None:
        # No positive match. Deliberately NOT falling back to the extension —
        # that is the hole this module exists to close.
        raise UploadRejected(
            _("%(name)s does not appear to be a genuine PDF or image.")
            % {"name": display_name(original)}
        )

    return {
        "original_name": display_name(original),
        "stored_name": safe_stored_name(original, extension),
        "extension": extension,
        "content_type": detected,
        "size": size,
    }


def validate_submission(files) -> list[dict]:
    """Validate every file in one submission against the collective limits.

    Raises on the first failure so nothing is persisted from a submission that
    contains even one bad file — partial acceptance would leave the reviewer
    with an incomplete application and no signal that anything was dropped.
    """
    files = list(files or [])

    if len(files) > settings.PARTNER_DOC_MAX_FILES:
        raise UploadRejected(
            _("Too many files: at most %(n)s attachments are allowed.")
            % {"n": settings.PARTNER_DOC_MAX_FILES}
        )

    total = sum(getattr(f, "size", 0) or 0 for f in files)
    if total > settings.PARTNER_DOC_MAX_TOTAL_MB * 1024 * 1024:
        raise UploadRejected(
            _("The attachments total more than the %(mb)s MB limit for one submission.")
            % {"mb": settings.PARTNER_DOC_MAX_TOTAL_MB}
        )

    return [validate_upload(f) for f in files]
