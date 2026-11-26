import io

import pymupdf
import pytest
from PIL import Image

from template_loader import load_template


def image_bytes(mode, color, file_format):
    buffer = io.BytesIO()
    Image.new(mode, (200, 100), color).save(buffer, file_format)
    return buffer.getvalue()


def test_png_is_loaded_as_rgb():
    template = load_template("cert.png", image_bytes("RGB", "blue", "PNG"))
    assert template.mode == "RGB"
    assert template.size == (200, 100)


def test_jpg_extension_is_case_insensitive():
    template = load_template("CERT.JPEG", image_bytes("RGB", "blue", "JPEG"))
    assert template.size == (200, 100)


def test_transparent_png_becomes_white_not_black():
    template = load_template("cert.png", image_bytes("RGBA", (0, 0, 0, 0), "PNG"))
    assert template.getpixel((10, 10)) == (255, 255, 255)


def test_pdf_first_page_is_converted_at_300_dpi():
    document = pymupdf.open()
    document.new_page(width=842, height=595)  # A4 landscape, in points (1/72 inch)
    template = load_template("cert.pdf", document.tobytes())
    # 842 points / 72 * 300 DPI = about 3508 pixels
    assert abs(template.width - 3508) <= 2
    assert template.mode == "RGB"


def test_other_file_types_are_rejected_with_clear_message():
    with pytest.raises(ValueError, match="PNG, JPG or PDF"):
        load_template("cert.docx", b"anything")


def test_damaged_files_give_clear_message():
    with pytest.raises(ValueError, match="damaged"):
        load_template("cert.png", b"not really a png")
    with pytest.raises(ValueError, match="damaged"):
        load_template("cert.pdf", b"not really a pdf")
