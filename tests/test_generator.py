from PIL import Image, ImageDraw

from generator import FONTS_FOLDER, draw_name, fit_font, generate_certificates, safe_file_name

FONT_PATH = FONTS_FOLDER / "Montserrat-Regular.ttf"

SETTINGS = {
    "anchor": [1000, 500],
    "font_file": "Montserrat-Regular.ttf",
    "font_size": 100,
    "color": "black",
    "max_width": 800,
}


def ink_box(image):
    """Box around the dark pixels, i.e. where the name was drawn."""
    # Invert so the black text becomes white; getbbox() finds non-black pixels.
    inverted = Image.eval(image.convert("L"), lambda pixel: 255 - pixel)
    return inverted.getbbox()


def test_short_name_keeps_chosen_size():
    font = fit_font("Amina", FONT_PATH, 100, 800)
    assert font.size == 100


def test_long_name_shrinks_to_fit_max_width():
    long_name = "Maximilian Alexander Konstantin von Hohenberg-Schwarzenfeld"
    font = fit_font(long_name, FONT_PATH, 100, 800)
    assert font.size < 100
    assert font.getlength(long_name) <= 800


def test_short_and_long_names_share_the_same_centre():
    template = Image.new("RGB", (2000, 1000), "white")
    for name in ["Amina", "Maximilian Alexander Konstantin von Hohenberg-Schwarzenfeld"]:
        left, top, right, bottom = ink_box(draw_name(template, name, SETTINGS))
        horizontal_centre = (left + right) / 2
        # A few pixels of tolerance: letter shapes are not perfectly symmetric.
        assert abs(horizontal_centre - 1000) <= 5
        assert right - left <= 800


def test_template_is_not_changed():
    template = Image.new("RGB", (2000, 1000), "white")
    draw_name(template, "Amina", SETTINGS)
    assert ink_box(template) is None


def test_accented_name_draws_without_error():
    template = Image.new("RGB", (2000, 1000), "white")
    certificate = draw_name(template, "Hélène Muñoz François", SETTINGS)
    assert ink_box(certificate) is not None


def test_safe_file_name():
    assert safe_file_name("Amina Bello") == "Amina_Bello.pdf"
    assert safe_file_name("Hélène Muñoz") == "Helene_Munoz.pdf"
    assert safe_file_name("  Jean-Luc  O'Brien ") == "Jean_Luc_O_Brien.pdf"
    assert safe_file_name("李") == "certificate.pdf"


def test_one_pdf_per_person_and_same_names_do_not_overwrite(tmp_path):
    template = Image.new("RGB", (2000, 1000), "white")
    people = [
        {"name": "Amina Bello", "email": "amina@example.com", "status": "winner"},
        {"name": "Amina Bello", "email": "amina.b@example.com", "status": "participant"},
        {"name": "Hélène Muñoz", "email": "helene@example.com", "status": "participant"},
    ]
    generated, failed = generate_certificates(template, people, SETTINGS, tmp_path)
    assert failed == []
    assert sorted(path.name for path in tmp_path.iterdir()) == ["Amina_Bello.pdf", "Amina_Bello_2.pdf", "Helene_Munoz.pdf"]


def test_one_failure_does_not_stop_the_batch(tmp_path):
    template = Image.new("RGB", (2000, 1000), "white")
    people = [
        {"name": "Amina Bello", "email": "amina@example.com", "status": "winner"},
        {"name": "Kofi Mensah", "email": "kofi@example.com", "status": "participant"},
    ]
    broken_settings = {**SETTINGS, "color": "not-a-colour"}
    generated, failed = generate_certificates(template, people, broken_settings, tmp_path)
    assert generated == []
    assert len(failed) == 2
    assert "could not be created" in failed[0]["reason"]
