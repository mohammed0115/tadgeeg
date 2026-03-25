"""
MinIO storage backend.
Extends the S3 backend with MinIO-specific behaviours.
MinIO uses the same S3 API but requires an explicit endpoint_url.
"""
import time
from typing import IO, Optional

from apps.storage_management.exceptions import StorageConnectionError, StorageConfigurationError
from .s3 import S3StorageBackend


class MinIOStorageBackend(S3StorageBackend):
    """
    Storage backend for MinIO object storage.
    MinIO is S3-compatible; this subclass enforces the endpoint_url
    requirement and overrides presigned URL generation for MinIO compatibility.
    """

    def __init__(
        self,
        bucket: str,
        endpoint_url: str,
        region: str = "us-east-1",
        access_key: str = "",
        secret_key: str = "",
        use_ssl: bool = True,
    ):
        if not endpoint_url:
            raise StorageConfigurationError(
                "MinIOStorageBackend requires an explicit endpoint_url (e.g. http://minio:9000)."
            )
        super().__init__(
            bucket=bucket,
            region=region,
            access_key=access_key,
            secret_key=secret_key,
            endpoint_url=endpoint_url,
            use_ssl=use_ssl,
        )

    def generate_download_url(self, path: str, expires_in: int = 300) -> str:
        """
        Generate a MinIO-compatible pre-signed URL.
        MinIO routes presigned requests through the configured endpoint_url,
        so we use the standard boto3 mechanism but rely on self.endpoint_url
        already being set on the client.
        """
        client = self._get_client()
        try:
            url = client.generate_presigned_url(
                "get_object",
                Params={"Bucket": self.bucket, "Key": path},
                ExpiresIn=expires_in,
            )
            return url
        except Exception as exc:
            self._handle_client_error(exc, operation="generate_presigned_url (minio)")

    def test_connection(self) -> dict:
        """
        Test MinIO connectivity by listing buckets and verifying
        the target bucket exists (or head_bucket).
        """
        start = time.monotonic()
        client = self._get_client()
        try:
            # list_buckets is a lightweight health check for MinIO
            response = client.list_buckets()
            bucket_names = [b["Name"] for b in response.get("Buckets", [])]
            latency_ms = int((time.monotonic() - start) * 1000)
            if self.bucket in bucket_names:
                message = (
                    f"MinIO endpoint '{self.endpoint_url}' is reachable. "
                    f"Bucket '{self.bucket}' exists."
                )
            else:
                message = (
                    f"MinIO endpoint '{self.endpoint_url}' is reachable, "
                    f"but bucket '{self.bucket}' was not found. "
                    f"Available buckets: {', '.join(bucket_names) or 'none'}."
                )
            return {
                "success": self.bucket in bucket_names,
                "message": message,
                "latency_ms": latency_ms,
            }
        except Exception as exc:
            latency_ms = int((time.monotonic() - start) * 1000)
            return {
                "success": False,
                "message": f"MinIO connection test failed: {exc}",
                "latency_ms": latency_ms,
            }
