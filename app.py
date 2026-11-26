"""Streamlit interface for HR: upload, place the name, check the list, generate.

This file only collects choices and shows results. Drawing lives in
generator.py and reading files in the loaders, so the logic can be tested
without a browser.

Run with:  streamlit run app.py
"""

import logging
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st
from PIL import ImageDraw
from streamlit_image_coordinates import streamlit_image_coordinates

from generator import FONTS_FOLDER, MIN_FONT_SIZE, draw_name, generate_certificates
from people_loader import EMAIL_HEADERS, NAME_HEADERS, STATUS_HEADERS, clean_people, find_column, read_people_table
from settings_store import load_settings, save_settings, template_key
from template_loader import load_template

PROJECT_FOLDER = Path(__file__).parent
OUTPUT_FOLDER = PROJECT_FOLDER / "output"
LOG_FILE = PROJECT_FOLDER / "certificates.log"

# The template is about 3500 px wide; the screen shows a smaller copy.
PREVIEW_WIDTH = 1000

SAMPLE_NAMES = {
    "Short name": "Amina Bello",
    "Long name": "Maximilian Alexander Konstantin von Hohenberg-Schwarzenfeld",
    "Accents": "Hélène Muñoz François",
}

NO_COLUMN = "(none)"

logging.basicConfig(
    filename=LOG_FILE,
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    encoding="utf-8",
)
logger = logging.getLogger("app")


@st.cache_data(show_spinner="Reading the template...")
def read_template(file_name, file_bytes):
    # Streamlit reruns this whole script on every click; caching avoids
    # converting the same PDF at 300 DPI again each time.
    return load_template(file_name, file_bytes)


def available_fonts():
    return sorted(path.name for path in FONTS_FOLDER.iterdir() if path.suffix.lower() in (".ttf", ".otf"))


def default_settings(template):
    return {
        "anchor": [template.width // 2, template.height // 2],
        "font_file": available_fonts()[0],
        "font_size": template.height // 12,
        "color": "#1F3A5F",
        "max_width": int(template.width * 0.6),
    }


def start_placement(key, template):
    """Fill the controls with this template's saved settings, or defaults."""
    saved = load_settings(key)
    settings = saved or default_settings(template)
    if settings["font_file"] not in available_fonts():
        settings["font_file"] = available_fonts()[0]

    st.session_state.template_key = key
    st.session_state.saved_settings_found = saved is not None
    st.session_state.anchor = settings["anchor"]
    st.session_state.font_file = settings["font_file"]
    st.session_state.font_size = settings["font_size"]
    st.session_state.color = settings["color"]
    st.session_state.max_width = min(settings["max_width"], template.width)


def current_settings():
    return {
        "anchor": st.session_state.anchor,
        "font_file": st.session_state.font_file,
        "font_size": st.session_state.font_size,
        "color": st.session_state.color,
        "max_width": st.session_state.max_width,
    }


def screen_copy_with_guides(certificate, settings):
    """Small copy for the screen, with a red cross on the anchor point and
    lines at the edges of the maximum width. The guides exist only on screen;
    they are never drawn on real certificates."""
    scale = PREVIEW_WIDTH / certificate.width
    screen_copy = certificate.resize((PREVIEW_WIDTH, round(certificate.height * scale)))
    draw = ImageDraw.Draw(screen_copy)

    anchor_x = settings["anchor"][0] * scale
    anchor_y = settings["anchor"][1] * scale
    half_width = settings["max_width"] / 2 * scale
    draw.line([anchor_x - 8, anchor_y, anchor_x + 8, anchor_y], fill="red", width=2)
    draw.line([anchor_x, anchor_y - 8, anchor_x, anchor_y + 8], fill="red", width=2)
    for edge_x in (anchor_x - half_width, anchor_x + half_width):
        draw.line([edge_x, anchor_y - 25, edge_x, anchor_y + 25], fill="red", width=1)
    return screen_copy


def name_area(certificate, settings):
    """Crop around the name so the sample previews are big enough to read."""
    anchor_x, anchor_y = settings["anchor"]
    half_width = settings["max_width"] * 0.6
    half_height = settings["font_size"] * 1.2
    box = (
        max(0, anchor_x - half_width),
        max(0, anchor_y - half_height),
        min(certificate.width, anchor_x + half_width),
        min(certificate.height, anchor_y + half_height),
    )
    return certificate.crop(box)


def template_section():
    """Step 1: upload the template and place the name. Returns (template, settings)."""
    st.header("1. Certificate template")
    uploaded = st.file_uploader("Upload the template (PNG, JPG or PDF)", key="template_file")
    if uploaded is None:
        return None, None

    file_bytes = uploaded.getvalue()
    try:
        template = read_template(uploaded.name, file_bytes)
    except ValueError as error:
        st.error(str(error))
        return None, None

    key = template_key(file_bytes)
    if st.session_state.get("template_key") != key:
        start_placement(key, template)
    if st.session_state.saved_settings_found:
        st.info("The saved placement for this template was loaded.")

    controls, preview = st.columns([1, 3])
    with controls:
        st.selectbox("Font", available_fonts(), key="font_file")
        st.number_input("Font size", min_value=MIN_FONT_SIZE, max_value=2000, step=5, key="font_size")
        st.color_picker("Colour", key="color")
        st.slider("Maximum name width", min_value=100, max_value=template.width, step=10, key="max_width")
        test_name = st.text_input("Try any name", value="Amina Bello")
        if st.button("Save placement for this template"):
            save_settings(key, current_settings())
            st.session_state.saved_settings_found = True
            logger.info("Saved placement for template %s (%s)", uploaded.name, key)
            st.success("Placement saved. It will be loaded next time you use this template.")

    settings = current_settings()
    with preview:
        st.caption("Click on the template where the centre of the name should be.")
        certificate = draw_name(template, test_name or "Amina Bello", settings)
        click = streamlit_image_coordinates(
            screen_copy_with_guides(certificate, settings),
            key="anchor_click",
            width="stretch",
            image_format="JPEG",
            cursor="crosshair",
        )
        # The component returns the last click on every rerun, so we only act
        # on a click we have not handled yet.
        if click and click["unix_time"] != st.session_state.get("last_click_time"):
            st.session_state.last_click_time = click["unix_time"]
            # The click is in screen pixels; convert to template pixels.
            scale = template.width / click["width"]
            st.session_state.anchor = [round(click["x"] * scale), round(click["y"] * scale)]
            st.rerun()

    sample_columns = st.columns(len(SAMPLE_NAMES))
    for column, (label, sample_name) in zip(sample_columns, SAMPLE_NAMES.items()):
        sample = draw_name(template, sample_name, settings)
        column.image(name_area(sample, settings), caption=label)

    return template, settings


def choose_column(label, columns, detected_column):
    index = columns.index(detected_column) if detected_column in columns else None
    return st.selectbox(label, columns, index=index, placeholder="Choose the column...")


def people_section():
    """Step 2: upload and check the recipient list. Returns the valid people."""
    st.header("2. Recipient list")
    uploaded = st.file_uploader("Upload the list (Excel .xlsx, CSV, or Google Form export)", key="people_file")
    if uploaded is None:
        return []

    try:
        table = read_people_table(uploaded.name, uploaded.getvalue())
    except ValueError as error:
        st.error(str(error))
        return []

    columns = list(table.columns)
    name_box, email_box, status_box = st.columns(3)
    with name_box:
        name_column = choose_column("Name column", columns, find_column(columns, NAME_HEADERS))
    with email_box:
        email_column = choose_column("Email column", columns, find_column(columns, EMAIL_HEADERS))
    with status_box:
        status_column = choose_column(
            "Winner / participant column (optional)",
            [NO_COLUMN] + columns,
            find_column(columns, STATUS_HEADERS) or NO_COLUMN,
        )
    if name_column is None or email_column is None:
        st.warning("Choose which columns contain the names and the emails.")
        return []

    people, rejected = clean_people(table, name_column, email_column, None if status_column == NO_COLUMN else status_column)
    st.session_state.rejected_rows = rejected

    valid_count, skipped_count = st.columns(2)
    valid_count.metric("Valid recipients", len(people))
    skipped_count.metric("Skipped rows", len(rejected))
    if rejected:
        st.warning("These rows will be skipped. Fix them in your file and upload it again if needed.")
        st.dataframe(pd.DataFrame(rejected), hide_index=True)
    return people


def generation_section(template, settings, people):
    """Step 3: preview one certificate, then generate all of them."""
    st.header("3. Preview and generate")
    preview_column, generate_column = st.columns(2)

    if preview_column.button("Preview the first certificate"):
        first_person = people[0]
        st.image(draw_name(template, first_person["name"], settings), caption=f"Preview for {first_person['name']}")

    if generate_column.button(f"Generate {len(people)} certificates", type="primary"):
        # One folder per batch, so a new batch never overwrites an older one.
        batch_folder = OUTPUT_FOLDER / datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        with st.spinner("Creating certificates..."):
            generated, failed = generate_certificates(template, people, settings, batch_folder)
        st.session_state.generated = generated
        st.session_state.generation_failed = failed

        st.success(f"{len(generated)} certificates saved in {batch_folder}")
        if failed:
            st.error(f"{len(failed)} certificates could not be created.")
            st.dataframe(pd.DataFrame(failed), hide_index=True)


def main():
    st.set_page_config(page_title="Certificate Generator", layout="wide")
    st.title("Certificate Generator")

    template, settings = template_section()
    if template is None:
        return
    people = people_section()
    if not people:
        return
    generation_section(template, settings, people)


try:
    main()
except Exception:
    # HR sees a short message; the full technical details go to the log.
    logger.exception("Unexpected error in the app")
    st.error(f"Something unexpected went wrong. The details were saved in {LOG_FILE.name}.")
