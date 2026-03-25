"""
Custom exceptions for storage management operations.
"""


class StorageBaseError(Exception):
    """Base class for all storage-related errors."""
    pass


class StorageConfigurationError(StorageBaseError):
    """Raised when a storage provider is misconfigured or configuration is missing."""
    pass


class StorageConnectionError(StorageBaseError):
    """Raised when a connection to a storage backend cannot be established."""
    pass


class StorageUploadError(StorageBaseError):
    """Raised when a file upload operation fails."""
    pass


class StorageValidationError(StorageBaseError):
    """Raised when a file fails policy validation (size, type, extension, etc.)."""
    pass


class StorageNotFoundError(StorageBaseError):
    """Raised when a requested file or resource does not exist in storage."""
    pass
