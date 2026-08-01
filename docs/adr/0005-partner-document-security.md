# ADR 0005 — Security posture for partner application documents

- **Status:** Accepted, with one stated limitation (no antivirus)
- **Date:** 2026-07-30
- **Phase:** 2B
- **Governs:** `apps/partners/uploads.py`, `PartnerApplicationAttachment`, the
  staff-only download endpoint

## Context

`POST /api/v1/partners/applications/` is the only unauthenticated write path in
the product that accepts files. Submitters are strangers. The files include
commercial registration documents and certificates — third-party commercial
data the company is now custodian of.

## Decisions

### 1. Content is evidence; the extension is a claim

A positive magic-byte match against `{PDF, PNG, JPEG}` is required. There is no
extension-based fallback.

This is stricter than `core/utils/file_validation.validate_mime_type`, and
deliberately so: without `python-magic` installed — and it is **not** installed
here — that function seeds its detected type from
`mimetypes.guess_type(filename)`, i.e. from the name. A `.pdf` containing HTML
passes it. `apps/partners/uploads.py` rejects an unrecognised header outright.

### 2. Private storage, outside `MEDIA_ROOT`

The existing private-media approach gates `/media/(documents|invoices|batches)`
at nginx (`Docs/PHASE_4_PRIVATE_MEDIA_SECURITY_FIX.md`). That works in a correct
deployment but depends on web-server configuration, and is absent under
`runserver` and in tests.

Partner documents live under `PARTNER_DOCS_ROOT`, outside the web root, so no
server configuration can expose them. `private_media/` is gitignored — these
must never reach the repository.

### 3. `.url` raises, on purpose

`PartnerDocumentStorage.url()` raises `ValueError`.

**This was got wrong first.** The original implementation passed
`base_url=None` and documented that it made the file unaddressable. It does not:
`FileSystemStorage._value_or_setting` treats `None` as "fall back to
`settings.MEDIA_URL`", so `.url` happily returned `/media/<name>`. The file was
not actually there, so it 404'd — but the guarantee written in the docstring was
false. `test_attachment_has_no_url_at_all` caught it.

The storage now overrides `url()` to raise, so rendering one of these in a
template fails loudly instead of silently publishing a commercial registration.

### 4. Location resolves per access, not at import

`FileSystemStorage.location` is a `cached_property`, which froze the root at
module import. Tests overriding `settings.PARTNER_DOCS_ROOT` had no effect, and
hostile fixture files were written into the developer's real `private_media/`
directory. `PartnerDocumentStorage` reads the setting on every access.

### 5. The client filename never touches the filesystem

Stored names are `uuid4().hex + validated_extension`. The submitted name is kept
only as a display string, path-stripped and length-bounded.

Generation rather than sanitisation: sanitising is a blocklist in disguise, and
the interesting inputs (`../../etc/passwd`, `x.pdf.exe`, null bytes, RTL
override characters) keep arriving in new shapes.

### 6. Download is staff-only, per request, and logged

One endpoint, `IsPlatformAdmin`, serving `application/octet-stream` with
`Content-Disposition: attachment` and `X-Content-Type-Options: nosniff` — never
the detected type, which would invite inline rendering. Every access is logged
with user, attachment, application and IP (§N).

### 7. Limits are configuration, not constants

Per-file size, per-submission total, attachment count, throttle rate and the
duplicate window are all settings with environment overrides.

## Limitation: there is NO antivirus scanning

**Stated plainly because implying otherwise would be worse than the gap
itself.**

- No ClamAV, no scanning service, no `clamd` — verified: `import clamd` →
  `ModuleNotFoundError`.
- `python-magic` is also absent; type detection uses the magic-byte table in
  `apps/partners/uploads.py`.

Files are **validated, not scanned**. A PDF that is genuinely a PDF but carries
a malicious payload will be accepted and stored. The controls above stop type
confusion, path traversal, resource exhaustion and web reachability. They do not
stop malware.

Mitigating factors: files are never executed, never served inline, never
reachable without staff authority, and stored outside the web root.

**Recommendation:** add scanning at the ingest boundary before this surface sees
significant volume. Until then, staff downloading a partner document should
treat it as an untrusted attachment from an unknown sender — because it is.

## Consequences

- Any new upload surface should reuse `apps/partners/uploads.py` rather than the
  broader general-purpose validator.
- Adding a field to `PartnerApplication` does not expose it: `PUBLIC_FIELDS` is
  empty and the payload is built by iterating it.
- The rejection matrix in `tests/test_partner_applications_security.py` is the
  control. Each case asserts nothing was persisted, not merely that a 400 came
  back — a rejection that still wrote bytes is still a foothold.
