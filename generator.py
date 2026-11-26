"""Draw a recipient's name on a certificate template and save it as a PDF.

The placement preview in app.py and the final certificates both call
draw_name(), so what HR sees on screen is exactly what recipients receive.
"""

import re
import unicodedata
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

FONTS_FOLDER = Path(__file__).parent / "fonts"

# Below this size a name becomes unreadable, so we stop shrinking.
MIN_FONT_SIZE = 20


def fit_font(name, font_path, font_size, max_width):
    """Return the font at the chosen size, smaller only if the name is too wide."""
    size = font_size
    font = ImageFont.truetype(str(font_path), size)
    while font.getlength(name) > max_width and size > MIN_FONT_SIZE:
        size -= 1
        font = ImageFont.truetype(str(font_path), size)
    return font


def draw_name(template, name, settings):
    """Return a new image with the name centred on the anchor point."""
    # convert() returns a copy, so the original template is never changed.
    # PDF has no transparency, so RGB is also what we need to save it later.
    certificate = template.convert("RGB")

    font_path = FONTS_FOLDER / settings["font_file"]
    font = fit_font(name, font_path, settings["font_size"], settings["max_width"])

    draw = ImageDraw.Draw(certificate)
    # anchor="mm" means the point we give is the middle of the text, both
    # horizontally and vertically, so every name is centred on that point.
    draw.text(
        tuple(settings["anchor"]),
        name,
        font=font,
        fill=settings["color"],
        anchor="mm",
    )
    return certificate


def safe_file_name(name):
    """Turn 'Hélène Muñoz' into 'Helene_Munoz.pdf'."""
    # NFKD splits 'é' into 'e' + an accent mark; encoding to ASCII drops the mark.
    plain_name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    words = re.findall(r"[A-Za-z0-9]+", plain_name)
    if not words:
        # Names in non-Latin scripts have no ASCII letters left.
        return "certificate.pdf"
    return "_".join(words) + ".pdf"


def save_certificate_pdf(certificate, output_path):
    """Save the image as a PDF at print quality."""
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    certificate.save(output_path, "PDF", resolution=300)


if __name__ == "__main__":
    # Quick manual check: python generator.py, then open the PDFs in output/
    sample_settings = {
        "anchor": [1754, 1300],
        "font_file": "GreatVibes-Regular.ttf",
        "font_size": 220,
        "color": "#1f3a5f",
        "max_width": 1900,
    }
    sample_template = Image.open("templates/sample_template.png")
    for sample_name in ["Amina Bello", "Hélène Muñoz", "Maximilian Alexander Konstantin von Hohenberg-Schwarzenfeld"]:
        certificate = draw_name(sample_template, sample_name, sample_settings)
        output_path = Path("output") / safe_file_name(sample_name)
        save_certificate_pdf(certificate, output_path)
        print("Saved", output_path)
