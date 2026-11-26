from settings_store import load_settings, save_settings, template_key

SETTINGS = {"anchor": [100, 200], "font_file": "Montserrat-Regular.ttf", "font_size": 80, "color": "#000000", "max_width": 900}


def test_same_content_gives_same_key_whatever_the_file_name():
    assert template_key(b"template content") == template_key(b"template content")
    assert template_key(b"template content") != template_key(b"another template")


def test_saved_settings_are_loaded_again(tmp_path):
    settings_file = tmp_path / "settings.json"
    save_settings("template-a", SETTINGS, settings_file)
    assert load_settings("template-a", settings_file) == SETTINGS


def test_unknown_template_has_no_settings(tmp_path):
    assert load_settings("never-saved", tmp_path / "settings.json") is None


def test_saving_messages_keeps_the_placement(tmp_path):
    settings_file = tmp_path / "settings.json"
    save_settings("template-a", SETTINGS, settings_file)
    save_settings("template-a", {"subject": "Hello {name}"}, settings_file)
    saved = load_settings("template-a", settings_file)
    assert saved["anchor"] == [100, 200]
    assert saved["subject"] == "Hello {name}"


def test_saving_one_template_keeps_the_others(tmp_path):
    settings_file = tmp_path / "settings.json"
    save_settings("template-a", SETTINGS, settings_file)
    save_settings("template-b", {**SETTINGS, "font_size": 50}, settings_file)
    assert load_settings("template-a", settings_file) == SETTINGS
    assert load_settings("template-b", settings_file)["font_size"] == 50
