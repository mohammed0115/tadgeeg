"""
FinAI S3 Storage Backends — Phase 5

Two backends:
  PrivateDocumentStorage  — for uploaded financial documents (private, pre-signed URLs)
  PublicMediaStorage      — for profile pictures and other public-read assets

Activation (env vars):
  AWS_STORAGE_BUCKET_NAME=finai-documents
  AWS_S3_REGION_NAME=me-south-1      # Bahrain (closest to GCC)
  AWS_ACCESS_KEY_ID=...
  AWS_SECRET_ACCESS_KEY=...
  USE_S3=true                         # flip to activate (default: off)

When USE_S3 is not set the app falls back to local filesystem storage, so
development machines and CI pipelines with no S3 credentials continue to work.

Pre-signed URL expiry:
  DOCUMENT_URL_EXPIRY_SECONDS  — default 3600 (1 h)
  PUBLIC_MEDIA_URL_EXPIRY      — default 0 (public-read, no expiry)

Production note:
  Documents must NEVER be publicly accessible. The PrivateDocumentStorage
  backend enforces this: ACL is omitted (bucket policy controls access),
  and every URL is pre-signed with a short TTL.

  Configure the S3 bucket policy to block all public access and grant
  access only to the IAM role / user running the application.
"""

import os
from storages.backends.s3boto3 import S3Boto3Storage


# ── Shared base ───────────────────────────────────────────────────────────────

class _BaseS3Storage(S3Boto3Storage):
    """Common S3 config shared by both backends."""

    bucket_name          = os.environ.get("AWS_STORAGE_BUCKET_NAME", "finai-documents")
    region_name          = os.environ.get("AWS_S3_REGION_NAME", "me-south-1")
    # Use path-style addressing when MINIO_ENDPOINT is set (local dev with MinIO)
    endpoint_url         = os.environ.get("AWS_S3_ENDPOINT_URL") or None
    # Always transfer files with server-side encryption
    object_parameters    = {"ServerSideEncryption": "AES256"}
    # Never emit unsigned headers — required for pre-signed URL correctness
    signature_version    = "s3v4"


# ── Private document storage ──────────────────────────────────────────────────

class PrivateDocumentStorage(_BaseS3Storage):
    """
    Storage backend for uploaded financial documents.

    - No public ACL — bucket must block public access at policy level.
    - Every URL is pre-signed with a configurable short TTL.
    - Files are namespaced under documents/ to simplify IAM policies.
    """

    location     = "documents"
    file_overwrite = False                     # always keep original filename
    custom_domain  = None                      # never expose via CDN (use pre-signed URLs)
    querystring_auth = True                    # generate pre-signed URLs
    querystring_expire = int(
        os.environ.get("DOCUMENT_URL_EXPIRY_SECONDS", 3600)
    )


# ── Public media storage ──────────────────────────────────────────────────────

class PublicMediaStorage(_BaseS3Storage):
    """
    Storage backend for public-read media (avatars, logos, etc.).

    These files are served via CloudFront / the bucket's public URL.
    Do NOT store financial documents here.
    """

    location       = "media"
    file_overwrite = False
    querystring_auth = False    # public-read — no signature needed
    custom_domain    = os.environ.get("AWS_S3_CUSTOM_DOMAIN") or None
