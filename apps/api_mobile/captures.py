"""
Multi-photo capture → server-side PDF builder — Phase 2.1.

The mobile app captures N photos of an invoice / receipt and posts them to
``/api/v1/mobile/captures/`` in a single multipart request. This module
turns them into a single PDF (one image per page), saves it to the same
``MEDIA_ROOT`` the desktop uploader uses, and returns the path so the
auditor can route it through the normal upload pipeline.

Pillow does the image work; we keep PDFs readable on phones (≤ 1600px on
the long edge) so the generated file stays small enough for review.
"""

from __future__ import annotations

import io
import logging
import os
import uuid
from datetime import datetime
from typing import Iterable

from django.conf import settings

logger = logging.getLogger("finai")


def build_pdf_from_images(files: Iterable, *, max_long_edge: int = 1600) -> bytes:
    """Combine ``files`` (uploaded image-like objects) into a single PDF blob.

    Each image is auto-rotated by EXIF, downscaled if larger than
    ``max_long_edge`` on the long side, and converted to RGB so Pillow
    can write a multi-page PDF. Raises ``ValueError`` if no usable image
    is provided.
    """
    try:
        from PIL import Image, ImageOps
    except ImportError as exc:  # pragma: no cover — Pillow ships with the project
        raise RuntimeError("Pillow is required for multi-photo capture") from exc

    pages: list = []
    for f in files:
        try:
            img = Image.open(f)
            img = ImageOps.exif_transpose(img)
            if img.mode != "RGB":
                img = img.convert("RGB")

            w, h = img.size
            long_edge = max(w, h)
            if long_edge > max_long_edge:
                scale = max_long_edge / long_edge
                img = img.resize((int(w * scale), int(h * scale)))

            pages.append(img)
        except Exception as exc:
            # Skip unreadable photos but log so the mobile team sees them.
            logger.warning("[captures] skipping unreadable image: %s", exc)

    if not pages:
        raise ValueError("No usable images supplied")

    buf = io.BytesIO()
    head, *rest = pages
    head.save(buf, format="PDF", save_all=True, append_images=rest)
    return buf.getvalue()


def save_capture_pdf(user, files) -> dict:
    """Build a PDF from the uploaded photos and persist it under MEDIA_ROOT.

    Returns a dict with ``pdf_path``, ``pdf_url`` (relative URL the front-end
    can show), ``page_count``, and ``size_bytes``.
    """
    pdf_bytes = build_pdf_from_images(files)

    media_root = settings.MEDIA_ROOT
    today = datetime.utcnow().strftime("%Y/%m")
    rel_dir = os.path.join("mobile_captures", today)
    abs_dir = os.path.join(media_root, rel_dir)
    os.makedirs(abs_dir, exist_ok=True)

    filename = f"capture_{uuid.uuid4().hex}.pdf"
    rel_path = os.path.join(rel_dir, filename)
    abs_path = os.path.join(abs_dir, filename)

    with open(abs_path, "wb") as fh:
        fh.write(pdf_bytes)

    return {
        "pdf_path":   abs_path,
        "pdf_url":    settings.MEDIA_URL.rstrip("/") + "/" + rel_path.replace(os.sep, "/"),
        "page_count": pdf_bytes.count(b"/Type /Page") if pdf_bytes else 0,
        "size_bytes": len(pdf_bytes),
        "filename":   filename,
    }
