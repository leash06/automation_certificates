"""Font tests never use the internet: Google Fonts is replaced by fake answers."""

import pytest
import requests

import font_library
from generator import FONTS_FOLDER

REAL_FONT_BYTES = (FONTS_FOLDER / "Montserrat-Regular.ttf").read_bytes()


def test_display_names_are_readable():
    assert font_library.font_display_name("PlayfairDisplay[wght].ttf") == "Playfair Display"
    assert font_library.font_display_name("GreatVibes-Regular.ttf") == "Great Vibes"
    assert font_library.font_display_name("EBGaramond[wght].ttf") == "EBGaramond"


def test_uploaded_font_is_saved_and_listed(tmp_path):
    saved_name = font_library.add_font_file("My Font.ttf", REAL_FONT_BYTES, tmp_path)
    assert saved_name == "My_Font.ttf"
    assert font_library.available_fonts(tmp_path) == ["My_Font.ttf"]


def test_file_name_cannot_escape_the_fonts_folder(tmp_path):
    saved_name = font_library.add_font_file("../../evil.ttf", REAL_FONT_BYTES, tmp_path)
    assert (tmp_path / saved_name).exists()


def test_not_a_font_is_rejected(tmp_path):
    with pytest.raises(ValueError, match="not a font"):
        font_library.add_font_file("picture.png", b"anything", tmp_path)
    with pytest.raises(ValueError, match="could not be read"):
        font_library.add_font_file("broken.ttf", b"not really a font", tmp_path)


def test_regular_style_is_preferred():
    assert font_library.pick_regular_style(["Lato-Bold.ttf", "Lato-Regular.ttf"]) == "Lato-Regular.ttf"
    assert font_library.pick_regular_style(["Lora-Italic[wght].ttf", "Lora[wght].ttf"]) == "Lora[wght].ttf"


class FakeResponse:
    def __init__(self, status_code=200, json_data=None, content=b""):
        self.status_code = status_code
        self._json_data = json_data
        self.content = content

    def json(self):
        return self._json_data

    def raise_for_status(self):
        pass


def fake_google(url, timeout):
    if url.endswith("/ofl/playfairdisplay"):
        return FakeResponse(json_data=[
            {"name": "PlayfairDisplay[wght].ttf", "download_url": "font-url"},
            {"name": "OFL.txt", "download_url": "licence-url"},
        ])
    if url == "font-url":
        return FakeResponse(content=REAL_FONT_BYTES)
    if url == "licence-url":
        return FakeResponse(content=b"Open Font License")
    return FakeResponse(status_code=404)


def test_google_font_is_downloaded_with_its_licence(monkeypatch, tmp_path):
    monkeypatch.setattr(font_library.requests, "get", fake_google)
    saved_name = font_library.download_google_font("Playfair Display", tmp_path, tmp_path / "licenses")
    assert saved_name == "PlayfairDisplay[wght].ttf"
    assert (tmp_path / "licenses" / "playfairdisplay-OFL.txt").exists()


def test_unknown_google_font_gives_clear_message(monkeypatch, tmp_path):
    monkeypatch.setattr(font_library.requests, "get", fake_google)
    with pytest.raises(ValueError, match="No Google Font called"):
        font_library.download_google_font("Not A Real Font", tmp_path, tmp_path)


def test_no_internet_gives_clear_message(monkeypatch, tmp_path):
    def no_internet(url, timeout):
        raise requests.ConnectionError("offline")

    monkeypatch.setattr(font_library.requests, "get", no_internet)
    with pytest.raises(ValueError, match="Could not reach"):
        font_library.download_google_font("Lato", tmp_path, tmp_path)
