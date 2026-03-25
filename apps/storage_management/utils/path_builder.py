"""
Storage path builder utilities.
Constructs organised, unique filesystem/object-store paths for uploaded files.
"""
import re
import uuid
from datetime import date


def build_storage_path(organization_id, original_name: str, purpose: str = "uploads") -> str:
    """
    Build a structured storage path:
        org/{org_id}/{purpose}/{year}/{month:02d}/{uuid8}_{sanitized_name}

    Args:
        organization_id: The UUID (or string) of the owning organization.
        original_name: The original filename as supplied by the uploader.
        purpose: Logical purpose bucket — 'uploads', 'backup', 'archive', 'temp'.

    Returns:
        A relative path string safe for use with any storage backend.
    """
    sanitized = sanitize_filename(original_name)
    today = date.today()
    unique_id = str(uuid.uuid4())[:8]
    return (
        f"org/{organization_id}/{purpose}/"
        f"{today.year}/{today.month:02d}/"
        f"{unique_id}_{sanitized}"
    )


def sanitize_filename(name: str) -> str:
    """
    Sanitize a filename for safe storage:
    - Remove characters that are not word chars, spaces, hyphens, or dots.
    - Collapse whitespace into underscores.
    - Truncate to 100 characters.

    Args:
        name: The raw filename string.

    Returns:
        A filesystem-safe filename string.
    """
    name = re.sub(r"[^\w\s\-.]", "", name)
    name = re.sub(r"\s+", "_", name.strip())
    return name[:100]
