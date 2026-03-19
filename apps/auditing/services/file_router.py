"""File Router Service — detect file family from extension."""

import os


class FileRouterService:
    """Detect file family from extension."""

    FAMILY_MAP = {
        "pdf": {"pdf"},
        "image": {"jpg", "jpeg", "png", "tiff", "tif"},
        "excel": {"xlsx", "xls"},
        "csv": {"csv"},
        "json": {"json", "jsonl"},
        "zip": {"zip"},
    }

    def route(self, filename: str) -> str:
        """Return file family: pdf | image | excel | csv | json | zip | unknown"""
        if not filename:
            return "unknown"
        ext = os.path.splitext(filename)[1].lstrip(".").lower()
        for family, extensions in self.FAMILY_MAP.items():
            if ext in extensions:
                return family
        return "unknown"
