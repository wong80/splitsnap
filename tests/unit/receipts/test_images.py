import io

import pytest
from PIL import Image

from receipts.images import MAX_EDGE, prepare_image


def make_jpeg(width=100, height=100, exif=False) -> bytes:
    img = Image.new("RGB", (width, height), color="white")
    buf = io.BytesIO()
    if exif:
        from PIL.ExifTags import Base as ExifBase

        exif_data = img.getexif()
        exif_data[ExifBase.Make] = "TestCamera"
        exif_data[ExifBase.Software] = "TestSoftware"
        img.save(buf, format="JPEG", exif=exif_data.tobytes())
    else:
        img.save(buf, format="JPEG")
    return buf.getvalue()


def make_png(width=100, height=100) -> bytes:
    img = Image.new("RGB", (width, height), color="red")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


class TestPrepareImage:
    def test_jpeg_passthrough(self):
        data = make_jpeg()
        result = prepare_image(data)
        img = Image.open(io.BytesIO(result))
        assert img.format == "JPEG"

    def test_png_converted_to_jpeg(self):
        data = make_png()
        result = prepare_image(data)
        img = Image.open(io.BytesIO(result))
        assert img.format == "JPEG"

    def test_exif_stripped(self):
        data = make_jpeg(exif=True)
        original = Image.open(io.BytesIO(data))
        assert original.getexif()

        result = prepare_image(data)
        img = Image.open(io.BytesIO(result))
        assert not img.info.get("exif")

    def test_resize_large_image(self):
        data = make_jpeg(width=3000, height=2000)
        result = prepare_image(data)
        img = Image.open(io.BytesIO(result))
        assert max(img.size) <= MAX_EDGE

    def test_small_image_not_upscaled(self):
        data = make_jpeg(width=200, height=150)
        result = prepare_image(data)
        img = Image.open(io.BytesIO(result))
        assert img.size == (200, 150)

    def test_non_image_rejected(self):
        with pytest.raises(ValueError, match="Not a valid image"):
            prepare_image(b"not an image at all")

    def test_text_file_rejected(self):
        with pytest.raises(ValueError, match="Not a valid image"):
            prepare_image(b"Hello, this is a text file.\n")

    def test_rgba_converted(self):
        img = Image.new("RGBA", (50, 50), color=(255, 0, 0, 128))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        result = prepare_image(buf.getvalue())
        out = Image.open(io.BytesIO(result))
        assert out.mode == "RGB"
