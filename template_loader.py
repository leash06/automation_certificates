"""Turn an uploaded template (PNG, JPG or PDF) into one standard RGB image."""

import io
from pathlib import Path

import pymupdf
from PIL import Image, UnidentifiedImageError

ACCEPTED_EXTENSIONS = {".png", ".jpg", ".jpeg", ".pdf"}

# 300 DPI is print quality: an A4 page becomes about 3508 x 2480 pixels.
PDF_DPI = 300


def load_template(file_name, file_bytes):
    """Return the template as an RGB image, or raise ValueError with a message for HR."""
    extension = Path(file_name).suffix.lower()
    if extension not in ACCEPTED_EXTENSIONS:
        raise ValueError(
            f"'{file_name}' is not a supported template. "
            "Please upload a PNG, JPG or PDF file."
        )
    if extension == ".pdf":
        return pdf_first_page_to_image(file_name, file_bytes)
    return open_image(file_name, file_bytes)


def pdf_first_page_to_image(file_name, file_bytes):
    try:
        document = pymupdf.open(stream=file_bytes, filetype="pdf")
    except pymupdf.FileDataError:
        raise ValueError(f"'{file_name}' could not be opened. The PDF may be damaged.")
    if document.page_count == 0:
        raise ValueError(f"'{file_name}' has no pages.")

    # Certificates are one page, so only the first page is used.
    pixmap = document[0].get_pixmap(dpi=PDF_DPI)
    return Image.frombytes("RGB", (pixmap.width, pixmap.height), pixmap.samples)


def open_image(file_name, file_bytes):
    try:
        image = Image.open(io.BytesIO(file_bytes))
        image.load()
    except (UnidentifiedImageError, OSError):
        raise ValueError(f"'{file_name}' could not be opened. The image may be damaged.")

    if image.mode in ("RGBA", "LA", "P"):
        # A plain RGB conversion turns transparent areas black; a printed
        # certificate should be white there instead.
        image = image.convert("RGBA")
        white_background = Image.new("RGB", image.size, "white")
        white_background.paste(image, mask=image.getchannel("A"))
        return white_background
    return image.convert("RGB")
