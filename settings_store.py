"""Save and reload the placement settings of each template in settings.json."""

import hashlib
import json
from pathlib import Path

SETTINGS_FILE = Path(__file__).parent / "settings.json"


def template_key(file_bytes):
    """Identify a template by its content, not its file name.

    HR may rename the file or upload it from another folder; the content
    stays the same, so the saved placement is still found.
    """
    return hashlib.sha256(file_bytes).hexdigest()[:16]


def read_all_settings(settings_file):
    if not settings_file.exists():
        return {}
    return json.loads(settings_file.read_text(encoding="utf-8"))


def load_settings(key, settings_file=SETTINGS_FILE):
    """Return the saved settings for this template, or None if there are none."""
    return read_all_settings(settings_file).get(key)


def save_settings(key, settings, settings_file=SETTINGS_FILE):
    # Read first so saving one template keeps the settings of all the others.
    all_settings = read_all_settings(settings_file)
    all_settings[key] = settings
    settings_file.write_text(json.dumps(all_settings, indent=2, ensure_ascii=False), encoding="utf-8")
