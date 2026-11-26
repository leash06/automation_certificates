"""List the fonts HR can choose from, and add new ones (file upload or Google Fonts).

New fonts are saved into fonts/, so once added they work offline and look
the same on every certificate.
"""

import io
import re
from pathlib import Path

import requests
from PIL import ImageFont

from generator import FONTS_FOLDER

FONT_EXTENSIONS = {".ttf", ".otf"}
LICENSES_FOLDER = FONTS_FOLDER / "licenses"

# Google publishes every Google Font on GitHub, sorted by licence.
GOOGLE_FONTS_FOLDER_URL = "https://api.github.com/repos/google/fonts/contents/{licence}/{family}"
GOOGLE_LICENCE_FOLDERS = ("ofl", "apache", "ufl")
LICENCE_FILE_NAMES = {"OFL.txt", "LICENSE.txt", "UFL.txt"}


def available_fonts(fonts_folder=FONTS_FOLDER):
    return sorted(path.name for path in fonts_folder.iterdir() if path.suffix.lower() in FONT_EXTENSIONS)


def font_display_name(file_name):
    """'PlayfairDisplay[wght].ttf' -> 'Playfair Display', 'GreatVibes-Regular.ttf' -> 'Great Vibes'."""
    stem = re.sub(r"\[.*?\]", "", Path(file_name).stem)
    stem = stem.replace("-Regular", "").replace("-", " ").replace("_", " ")
    # Put a space where a lowercase letter is followed by a capital.
    return re.sub(r"(?<=[a-z])(?=[A-Z])", " ", stem).strip()


def add_font_file(file_name, file_bytes, fonts_folder=FONTS_FOLDER):
    """Check the file is a real font, save it in fonts/, and return its saved name."""
    extension = Path(file_name).suffix.lower()
    if extension not in FONT_EXTENSIONS:
        raise ValueError(f"'{file_name}' is not a font. Please choose a .ttf or .otf file.")
    try:
        ImageFont.truetype(io.BytesIO(file_bytes), 20)
    except OSError:
        raise ValueError(f"'{file_name}' could not be read as a font. The file may be damaged.")

    # Keep only safe characters, so a strange file name cannot point outside fonts/.
    safe_name = re.sub(r"[^A-Za-z0-9_.\-\[\],]", "_", Path(file_name).name)
    (fonts_folder / safe_name).write_bytes(file_bytes)
    return safe_name


def pick_regular_style(file_names):
    """Choose the normal (not italic, not bold) file among a family's files."""
    for name in file_names:
        if name.endswith("-Regular.ttf"):
            return name
    # Variable fonts contain every weight in one file, e.g. 'Lora[wght].ttf'.
    for name in file_names:
        if "[" in name and "Italic" not in name:
            return name
    return file_names[0]


def download_google_font(family_name, fonts_folder=FONTS_FOLDER, licenses_folder=LICENSES_FOLDER):
    """Download one Google Font by its name (e.g. 'Playfair Display') into fonts/."""
    family_folder = re.sub(r"[^a-z0-9]", "", family_name.lower())
    if not family_folder:
        raise ValueError("Type the name of a font from fonts.google.com, for example 'Playfair Display'.")

    try:
        for licence in GOOGLE_LICENCE_FOLDERS:
            response = requests.get(GOOGLE_FONTS_FOLDER_URL.format(licence=licence, family=family_folder), timeout=15)
            if response.status_code == 404:
                continue  # not under this licence; try the next one
            if response.status_code == 403:
                raise ValueError("Google Fonts is limiting downloads right now. Please try again in an hour.")
            response.raise_for_status()

            files = {item["name"]: item["download_url"] for item in response.json()}
            font_names = sorted(name for name in files if name.endswith(".ttf"))
            if not font_names:
                break
            chosen_name = pick_regular_style(font_names)
            font_bytes = requests.get(files[chosen_name], timeout=30).content
            save_licence(files, family_folder, licenses_folder)
            return add_font_file(chosen_name, font_bytes, fonts_folder)
    except requests.RequestException:
        raise ValueError("Could not reach Google Fonts. Check the internet connection and try again.")

    raise ValueError(f"No Google Font called '{family_name}' was found. Check the spelling on fonts.google.com.")


def save_licence(files, family_folder, licenses_folder):
    # Free font licences require the licence text to travel with the font.
    for name, url in files.items():
        if name in LICENCE_FILE_NAMES:
            licenses_folder.mkdir(parents=True, exist_ok=True)
            (licenses_folder / f"{family_folder}-{name}").write_bytes(requests.get(url, timeout=30).content)
            return
