"""
Custom exceptions for the file management app.
"""


class FileManagementBaseError(Exception):
    """Base class for all file management errors."""
    pass


class FileValidationError(FileManagementBaseError):
    """Raised when a file fails business-level validation (name, type, duplicates, etc.)."""
    pass


class FileProcessingError(FileManagementBaseError):
    """Raised when a file processing operation (versioning, profiling, etc.) fails."""
    pass


class FolderNotFoundError(FileManagementBaseError):
    """Raised when a requested folder does not exist or cannot be resolved."""
    pass


class FileMoveError(FileManagementBaseError):
    """Raised when a file cannot be moved to the requested folder."""
    pass
