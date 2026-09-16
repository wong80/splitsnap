from __future__ import annotations

import io

from PIL import Image, ImageOps

MAX_EDGE = 1568


def prepare_image(data: bytes) -> bytes:
    try:
        img = Image.open(io.BytesIO(data))
        img.verify()
        img = Image.open(io.BytesIO(data))
    except Exception:
        raise ValueError("Not a valid image file") from None

    img = ImageOps.exif_transpose(img) or img

    for key in ("exif", "icc_profile", "xmp"):
        img.info.pop(key, None)

    if img.mode in ("RGBA", "P", "LA"):
        img = img.convert("RGB")

    w, h = img.size
    longest = max(w, h)
    if longest > MAX_EDGE:
        scale = MAX_EDGE / longest
        img = img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)

    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    return buf.getvalue()
