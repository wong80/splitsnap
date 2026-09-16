from __future__ import annotations

import uuid

from django.conf import settings
from django.core.files.storage import default_storage


def receipt_upload_path(_instance, filename: str) -> str:
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "jpg"
    return f"receipts/{uuid.uuid4().hex}.{ext}"


def get_receipt_url(name: str) -> str | None:
    if not name:
        return None
    if hasattr(default_storage, "url"):
        try:
            params = getattr(settings, "AWS_PRESIGNED_URL_PARAMS", {})
            expiry = getattr(settings, "AWS_PRESIGNED_EXPIRY", 300)
            return default_storage.url(name, parameters=params, expire=expiry)
        except TypeError:
            return default_storage.url(name)
    return None
