"""
Amazon S3 storage backend.
boto3 is imported lazily so the package is optional in environments that
only use local storage.
"""
import time
from typing import IO, Optional

from apps.storage_management.exceptions import (
    StorageConnectionError,
    StorageNotFoundError,
    StorageUploadError,
)
from .base import BaseStorageBackend


class S3StorageBackend(BaseStorageBackend):
    """
    Storage backend for Amazon S3 (and S3-compatible services).
    """

    def __init__(
        self,
        bucket: str,
        region: str = "us-east-1",
        access_key: str = "",
        secret_key: str = "",
        endpoint_url: str = "",
        use_ssl: bool = True,
    ):
        self.bucket = bucket
        self.region = region
        self.access_key = access_key
        self.secret_key = secret_key
        self.endpoint_url = endpoint_url or None
        self.use_ssl = use_ssl

    def _get_client(self):
        """Lazily import boto3 and return an S3 client."""
        try:
            import boto3
        except ImportError as exc:
            raise StorageConfigurationError(
                "boto3 is not installed. Install it with: pip install boto3"
            ) from exc

        kwargs = {
            "region_name": self.region,
            "use_ssl": self.use_ssl,
        }
        if self.access_key and self.secret_key:
            kwargs["aws_access_key_id"] = self.access_key
            kwargs["aws_secret_access_key"] = self.secret_key
        if self.endpoint_url:
            kwargs["endpoint_url"] = self.endpoint_url

        return boto3.client("s3", **kwargs)

    def save(self, file_obj: IO, path: str, metadata: Optional[dict] = None) -> str:
        metadata = metadata or {}
        client = self._get_client()
        extra_args = {}
        content_type = metadata.get("content_type", "")
        if content_type:
            extra_args["ContentType"] = content_type

        try:
            client.upload_fileobj(file_obj, self.bucket, path, ExtraArgs=extra_args)
        except Exception as exc:
            self._handle_client_error(exc, operation="upload")
        return path

    def delete(self, path: str) -> bool:
        client = self._get_client()
        try:
            client.delete_object(Bucket=self.bucket, Key=path)
            return True
        except Exception as exc:
            self._handle_client_error(exc, operation="delete")
            return False

    def exists(self, path: str) -> bool:
        client = self._get_client()
        try:
            client.head_object(Bucket=self.bucket, Key=path)
            return True
        except Exception:
            return False

    def open(self, path: str) -> IO:
        client = self._get_client()
        try:
            response = client.get_object(Bucket=self.bucket, Key=path)
            return response["Body"]
        except Exception as exc:
            try:
                import botocore.exceptions
                if isinstance(exc, botocore.exceptions.ClientError):
                    error_code = exc.response["Error"]["Code"]
                    if error_code in ("NoSuchKey", "404"):
                        raise StorageNotFoundError(f"File not found in S3: {path}") from exc
            except ImportError:
                pass
            self._handle_client_error(exc, operation="open")

    def generate_download_url(self, path: str, expires_in: int = 300) -> str:
        client = self._get_client()
        try:
            url = client.generate_presigned_url(
                "get_object",
                Params={"Bucket": self.bucket, "Key": path},
                ExpiresIn=expires_in,
            )
            return url
        except Exception as exc:
            self._handle_client_error(exc, operation="generate_presigned_url")

    def test_connection(self) -> dict:
        start = time.monotonic()
        client = self._get_client()
        try:
            client.head_bucket(Bucket=self.bucket)
            latency_ms = int((time.monotonic() - start) * 1000)
            return {
                "success": True,
                "message": f"S3 bucket '{self.bucket}' in region '{self.region}' is accessible.",
                "latency_ms": latency_ms,
            }
        except Exception as exc:
            latency_ms = int((time.monotonic() - start) * 1000)
            return {
                "success": False,
                "message": f"S3 connection test failed: {exc}",
                "latency_ms": latency_ms,
            }

    def get_file_metadata(self, path: str) -> dict:
        client = self._get_client()
        try:
            response = client.head_object(Bucket=self.bucket, Key=path)
            return {
                "size": response.get("ContentLength", 0),
                "content_type": response.get("ContentType", ""),
                "last_modified": response.get("LastModified", "").isoformat()
                if response.get("LastModified")
                else "",
                "etag": response.get("ETag", "").strip('"'),
                "path": path,
                "bucket": self.bucket,
            }
        except Exception as exc:
            try:
                import botocore.exceptions
                if isinstance(exc, botocore.exceptions.ClientError):
                    error_code = exc.response["Error"]["Code"]
                    if error_code in ("NoSuchKey", "404"):
                        raise StorageNotFoundError(f"File not found in S3: {path}") from exc
            except ImportError:
                pass
            self._handle_client_error(exc, operation="head_object")

    def _handle_client_error(self, exc: Exception, operation: str = "") -> None:
        """Translate botocore errors into our domain exceptions."""
        try:
            import botocore.exceptions
            if isinstance(exc, botocore.exceptions.ClientError):
                error_code = exc.response["Error"]["Code"]
                error_msg = exc.response["Error"]["Message"]
                if error_code in ("NoSuchBucket", "NoSuchKey", "404"):
                    raise StorageNotFoundError(
                        f"S3 resource not found during {operation}: {error_msg}"
                    ) from exc
                if error_code in ("AccessDenied", "403", "InvalidAccessKeyId", "SignatureDoesNotMatch"):
                    raise StorageConnectionError(
                        f"S3 access denied during {operation}: {error_msg}"
                    ) from exc
                raise StorageUploadError(
                    f"S3 client error during {operation} [{error_code}]: {error_msg}"
                ) from exc
            if isinstance(exc, botocore.exceptions.EndpointResolutionError):
                raise StorageConnectionError(
                    f"Cannot resolve S3 endpoint during {operation}: {exc}"
                ) from exc
        except ImportError:
            pass
        # Fallback for non-botocore exceptions
        raise StorageConnectionError(
            f"S3 operation '{operation}' failed: {exc}"
        ) from exc
