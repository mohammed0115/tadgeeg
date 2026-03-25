"""
Local filesystem storage backend.
Stores files under MEDIA_ROOT/storage/ (or a configured base_path).
"""
import os
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import IO, Optional

from django.conf import settings

from apps.storage_management.exceptions import (
    StorageConnectionError,
    StorageNotFoundError,
    StorageUploadError,
)
from .base import BaseStorageBackend


class LocalStorageBackend(BaseStorageBackend):
    """
    Concrete backend that persists files on the local filesystem.
    Suitable for development and single-server deployments.
    """

    def __init__(self, base_path: Optional[str] = None):
        if base_path:
            self.base_path = Path(base_path)
        else:
            self.base_path = Path(settings.MEDIA_ROOT) / "storage"
        self.base_path.mkdir(parents=True, exist_ok=True)

    def _abs(self, path: str) -> Path:
        """Return absolute path, safely preventing directory traversal."""
        abs_path = (self.base_path / path).resolve()
        if not str(abs_path).startswith(str(self.base_path.resolve())):
            raise StorageUploadError(f"Unsafe path detected: {path}")
        return abs_path

    def save(self, file_obj: IO, path: str, metadata: Optional[dict] = None) -> str:
        abs_path = self._abs(path)
        abs_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with open(abs_path, "wb") as dest:
                chunk_size = 8192
                while True:
                    chunk = file_obj.read(chunk_size)
                    if not chunk:
                        break
                    dest.write(chunk)
        except OSError as exc:
            raise StorageUploadError(f"Failed to write file to local storage: {exc}") from exc
        return path

    def delete(self, path: str) -> bool:
        abs_path = self._abs(path)
        if not abs_path.exists():
            return False
        try:
            os.remove(abs_path)
            return True
        except OSError as exc:
            raise StorageConnectionError(f"Failed to delete file: {exc}") from exc

    def exists(self, path: str) -> bool:
        return self._abs(path).exists()

    def open(self, path: str) -> IO:
        abs_path = self._abs(path)
        if not abs_path.exists():
            raise StorageNotFoundError(f"File not found: {path}")
        return open(abs_path, "rb")

    def generate_download_url(self, path: str, expires_in: int = 300) -> str:
        """
        Return a relative URL under /media/storage/.
        The Django dev server (or a web server) must serve MEDIA_ROOT.
        """
        # Normalize slashes
        clean_path = path.lstrip("/")
        return f"/media/storage/{clean_path}"

    def test_connection(self) -> dict:
        """Write and immediately remove a temp file to verify write access."""
        start = time.monotonic()
        probe_name = f".probe_{uuid.uuid4().hex}"
        probe_path = self.base_path / probe_name
        try:
            with open(probe_path, "w") as f:
                f.write("ok")
            os.remove(probe_path)
            latency_ms = int((time.monotonic() - start) * 1000)
            return {
                "success": True,
                "message": f"Local storage at {self.base_path} is accessible and writable.",
                "latency_ms": latency_ms,
            }
        except OSError as exc:
            latency_ms = int((time.monotonic() - start) * 1000)
            return {
                "success": False,
                "message": f"Local storage test failed: {exc}",
                "latency_ms": latency_ms,
            }

    def get_file_metadata(self, path: str) -> dict:
        abs_path = self._abs(path)
        if not abs_path.exists():
            raise StorageNotFoundError(f"File not found: {path}")
        stat = abs_path.stat()
        return {
            "size": stat.st_size,
            "last_modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
            "content_type": "application/octet-stream",
            "path": path,
        }
