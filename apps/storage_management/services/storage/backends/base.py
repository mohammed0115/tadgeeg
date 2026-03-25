"""
Abstract base class for all storage backends.
Every concrete backend must implement these methods.
"""
from abc import ABC, abstractmethod
from typing import IO, Optional


class BaseStorageBackend(ABC):
    """
    Contract that all storage backend implementations must fulfil.
    """

    @abstractmethod
    def save(self, file_obj: IO, path: str, metadata: Optional[dict] = None) -> str:
        """
        Persist a file-like object at the given logical path.

        Args:
            file_obj: An open file-like object (supports .read()).
            path: The relative storage path (as returned by path_builder).
            metadata: Optional dict with extra hints, e.g. {"content_type": "application/pdf"}.

        Returns:
            The final storage path (may differ from input for some backends).

        Raises:
            StorageUploadError: if the upload operation fails.
        """

    @abstractmethod
    def delete(self, path: str) -> bool:
        """
        Delete a stored file.

        Args:
            path: The storage path of the file to delete.

        Returns:
            True if the file was deleted, False if it did not exist.

        Raises:
            StorageConnectionError: if the backend is unreachable.
        """

    @abstractmethod
    def exists(self, path: str) -> bool:
        """
        Check whether a file exists at the given path.

        Args:
            path: The storage path to check.

        Returns:
            True if the file exists, False otherwise.
        """

    @abstractmethod
    def open(self, path: str) -> IO:
        """
        Open a stored file for reading.

        Args:
            path: The storage path of the file.

        Returns:
            A file-like object opened in binary-read mode.

        Raises:
            StorageNotFoundError: if the file does not exist.
        """

    @abstractmethod
    def generate_download_url(self, path: str, expires_in: int = 300) -> str:
        """
        Generate a (possibly pre-signed) URL to download the file.

        Args:
            path: The storage path of the file.
            expires_in: URL validity in seconds (used for pre-signed cloud URLs).

        Returns:
            A URL string the client can use to download the file.
        """

    @abstractmethod
    def test_connection(self) -> dict:
        """
        Verify that the backend is accessible and writable.

        Returns:
            A dict with keys:
                - success (bool)
                - message (str)
                - latency_ms (int)  — round-trip latency in milliseconds
        """

    @abstractmethod
    def get_file_metadata(self, path: str) -> dict:
        """
        Return metadata about a stored file.

        Args:
            path: The storage path of the file.

        Returns:
            A dict with at minimum: size (int), content_type (str),
            last_modified (datetime or str).

        Raises:
            StorageNotFoundError: if the file does not exist.
        """
