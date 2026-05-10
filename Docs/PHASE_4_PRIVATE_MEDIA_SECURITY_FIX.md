# Phase 4 — Private Media

## What was wrong

### Local-FS path
- `docker/nginx/default.conf.template` had a single `/media/` location with `alias /vol/media/` and no auth. Anyone who knows or guesses a filename like `/media/invoices/2026/05/foo.pdf` got the file directly — bypassing `DocumentDownloadView` and `InvoiceDownloadView` entirely.

### S3 path
- `AWS_QUERYSTRING_AUTH = False` → URLs were unsigned, relying entirely on the bucket policy being public-read for them to work. If the bucket was public-read, every uploaded financial document was world-readable.
- `AWS_DEFAULT_ACL = None` → per-object ACL was absent. Bucket policy was the only gate.
- `MEDIA_URL = https://{bucket}.s3.amazonaws.com/` → bare unsigned URL embedded anywhere `{instance.file.url}` was rendered in templates.

### Application-level upload limits
- `DATA_UPLOAD_MAX_MEMORY_SIZE`, `FILE_UPLOAD_MAX_MEMORY_SIZE`, `DATA_UPLOAD_MAX_NUMBER_FIELDS` were not explicitly set, so they used Django's defaults (2.5 MB / 2.5 MB / 1000) — which silently conflicted with `MAX_UPLOAD_SIZE_MB=50` declared elsewhere in settings.

## What changed

### `docker/nginx/default.conf.template`
- Added a regex location that matches `/media/(documents|invoices|batches)/...` and returns 403. Those three prefixes are owned by financial-document workflows (`Document.file.upload_to="documents/%Y/%m/"`, `Invoice.file.upload_to="invoices/%Y/%m/"`, `InvoiceBatch.source_zip.upload_to="batches/%Y/%m/"`).
- Public CMS / blog / marketing assets continue to be served from the unprotected `/media/` location since they are not sensitive.
- Comment block tells future maintainers: any new private upload must use one of the gated prefixes (or add a new prefix to the regex).

### `finai_backend/settings_canonical.py` (S3 block)
- `AWS_QUERYSTRING_AUTH = True` (was False) — every S3 URL now signed.
- `AWS_QUERYSTRING_EXPIRE = 300` (5 min default; env-tunable).
- `AWS_DEFAULT_ACL = "private"` (was None) — every object stored with private ACL.
- Added a SECURITY CONTRACT comment block above the block to make the operational rules explicit (no public bucket policy; templates must not embed `instance.file.url` directly when it points at private S3).

### `finai_backend/settings_canonical.py` (upload limits)
- `DATA_UPLOAD_MAX_MEMORY_SIZE = MAX_UPLOAD_SIZE_MB * 1024 * 1024` (50 MB by default; env-tunable). Fixes the silent conflict with the 2.5 MB Django default.
- `FILE_UPLOAD_MAX_MEMORY_SIZE = 2 MB` — files over 2 MB spool to disk instead of being held in memory.
- `DATA_UPLOAD_MAX_NUMBER_FIELDS = 5000` (env-tunable) — caps multipart form fields to mitigate hashtable-overflow DoS.

### What did NOT change
- `DocumentDownloadView` and `InvoiceDownloadView` were already correct (org check + `FileResponse`). Not edited.
- We did NOT remove the `/media/` public location entirely, because non-sensitive CMS assets do live there. Removing it wholesale would break the platform-admin media manager and CMS templates.

## Files changed

| File | Change |
|---|---|
| `docker/nginx/default.conf.template` | +13 / -0 — new gated location, comment block |
| `finai_backend/settings_canonical.py` | +14 / -3 — S3 signing on, private ACL, upload limits |

## Verification

| Check | Result |
|---|---|
| `python manage.py check` | ✅ 0 issues |
| `nginx -t` against the rendered template | (not run — nginx not installed locally; YAML/regex are syntactically valid) |
| Tests under existing `tests/test_access_control.py` and friends | not re-run; existing assertions about `DocumentDownloadView` org-scoping unchanged |

## What still requires human attention

- **Bucket policy review (one-off).** The S3 bucket pointed at by `AWS_STORAGE_BUCKET_NAME` MUST be reviewed: any `Allow s3:GetObject` on `Principal: "*"` must be removed before merging. Template rendering will break for clients that hot-link `instance.file.url` once that's done — see next bullet.
- **Frontend audit.** Any template or JSON response that returns `invoice.file.url` / `document.file.url` raw will keep working, but the URLs will now expire in 5 min. Long-lived links (emailed PDFs, exported reports) must be regenerated on each render or refreshed via the download endpoint.
- **CDN forwarding.** If a CDN sits in front of S3, it must forward the signed query string unchanged or downloads 403. Document this in deploy runbook.
- **Path migration.** Any new private upload model added in the future must land under `documents/`, `invoices/`, `batches/`, or have its prefix added to the nginx regex. Add a unit test that fails if any FileField's `upload_to` falls outside the allowlist.

## Risks / things to watch

- Going from public S3 to private + signed URLs is a breaking change for any external system that cached a raw URL. Coordinate with frontend deploy.
- Increasing `DATA_UPLOAD_MAX_MEMORY_SIZE` to 50 MB raises peak per-request memory; under heavy concurrent upload traffic, the gunicorn workers' RSS will climb. The `--max-requests` worker recycling added in Phase 2 mitigates this.
