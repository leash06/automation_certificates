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
from PIL import Image, ImageColor, ImageDraw

from font_library import add_font_file, available_fonts, download_google_font, font_display_name
from generator import MIN_FONT_SIZE, draw_name, generate_certificates, write_name
from placement_canvas import image_data_url, placement_canvas
from mailer import find_already_sent, send_certificates
from people_loader import EMAIL_HEADERS, NAME_HEADERS, STATUS_HEADERS, clean_people, find_column, read_people_table
from settings_store import load_settings, save_settings, template_key
from template_loader import load_template

PROJECT_FOLDER = Path(__file__).parent
OUTPUT_FOLDER = PROJECT_FOLDER / "output"
LOG_FILE = PROJECT_FOLDER / "certificates.log"

# The template is about 3500 px wide. The live preview is drawn on a copy
# this wide, which is about 12 times fewer pixels, so it updates quickly.
PREVIEW_WIDTH = 1000
MAX_FONT_SIZE = 2000

DEFAULT_FONT = "GreatVibes-Regular.ttf"

MOVE_NAME = "Places or drags the name"
PICK_COLOUR = "Picks the text colour (eyedropper)"

NO_COLUMN = "(none)"

DEFAULT_MESSAGES = {
    "subject": "Your certificate, {name}",
    "winner_body": (
        "Congratulations {name}!\n\n"
        "You are one of our winners. Your certificate is attached.\n\n"
        "Best regards,\nThe HR team"
    ),
    "participant_body": (
        "Dear {name},\n\n"
        "Thank you for taking part. Your certificate is attached.\n\n"
        "Best regards,\nThe HR team"
    ),
}

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


@st.cache_resource(max_entries=4)
def scaled_template(_template, key, scale):
    # The leading _ tells Streamlit not to hash the big image on every
    # rerun; the template key already identifies it.
    return _template.resize((round(_template.width * scale), round(_template.height * scale)))


@st.cache_resource(max_entries=4)
def background_url(_template, key):
    # The template picture never changes while HR places the name, so it is
    # encoded for the browser once, not on every change.
    return image_data_url(scaled_template(_template, key, PREVIEW_WIDTH / _template.width), "JPEG")


def name_layer(template, key, name, settings):
    """A transparent picture, the size of the screen preview, holding only
    the name and the guides. The browser slides it when HR drags the name.

    Returns (layer, name_box): name_box is [left, top, right, bottom] around
    the letters, as fractions of the picture, for the selection box.
    """
    scale = PREVIEW_WIDTH / template.width
    size = scaled_template(template, key, scale).size
    # Transparent pixels in the text colour (alpha 0), not transparent black:
    # the soft edges of the letters blend with this, so black would give
    # light text a dark outline.
    layer = Image.new("RGBA", size, ImageColor.getrgb(settings["color"])[:3] + (0,))
    write_name(layer, name, settings, scale)

    # Measured before the guides are added, so the box fits the letters only.
    letters = layer.getchannel("A").getbbox()
    name_box = None
    if letters:
        padding = 6  # screen pixels around the letters, like Canva's box
        left, top, right, bottom = letters
        name_box = [
            (left - padding) / size[0], (top - padding) / size[1],
            (right + padding) / size[0], (bottom + padding) / size[1],
        ]
    add_guides(layer, settings, scale)
    return layer, name_box


def default_settings(template):
    fonts = available_fonts()
    return {
        "anchor": [template.width // 2, template.height // 2],
        "font_file": DEFAULT_FONT if DEFAULT_FONT in fonts else fonts[0],
        "font_size": template.height // 12,
        "color": "#1F3A5F",
        "max_width": int(template.width * 0.6),
    }


def clear_email_results():
    for name in ("email_sent", "email_failed", "email_dry_run"):
        st.session_state.pop(name, None)


def start_placement(key, template):
    """Fill the controls with this template's saved settings, or defaults."""
    saved = load_settings(key)
    # Saved values win; defaults fill anything never saved (e.g. messages
    # saved but placement not yet, or the reverse).
    settings = {**default_settings(template), **DEFAULT_MESSAGES, **(saved or {})}
    if settings["font_file"] not in available_fonts():
        settings["font_file"] = available_fonts()[0]

    st.session_state.template_key = key
    st.session_state.saved_settings_found = saved is not None
    # Certificates made with a previous template must not be emailed by mistake.
    st.session_state.pop("generated", None)
    clear_email_results()
    st.session_state.anchor = settings["anchor"]
    st.session_state.font_file = settings["font_file"]
    st.session_state.font_size = settings["font_size"]
    st.session_state.color = settings["color"]
    st.session_state.max_width = min(settings["max_width"], template.width)
    st.session_state.subject = settings["subject"]
    st.session_state.winner_body = settings["winner_body"]
    st.session_state.participant_body = settings["participant_body"]


def current_messages():
    return {
        "subject": st.session_state.subject,
        "winner_body": st.session_state.winner_body,
        "participant_body": st.session_state.participant_body,
    }


def current_settings():
    return {
        "anchor": st.session_state.anchor,
        "font_file": st.session_state.font_file,
        "font_size": st.session_state.font_size,
        "color": st.session_state.color,
        "max_width": st.session_state.max_width,
    }


def add_guides(screen_copy, settings, scale):
    """Draw a red cross on the anchor point and lines at the edges of the
    maximum width. Only on the screen copy; never on real certificates."""
    draw = ImageDraw.Draw(screen_copy)
    anchor_x = settings["anchor"][0] * scale
    anchor_y = settings["anchor"][1] * scale
    half_width = settings["max_width"] / 2 * scale
    draw.line([anchor_x - 8, anchor_y, anchor_x + 8, anchor_y], fill="red", width=2)
    draw.line([anchor_x, anchor_y - 8, anchor_x, anchor_y + 8], fill="red", width=2)
    for edge_x in (anchor_x - half_width, anchor_x + half_width):
        draw.line([edge_x, anchor_y - 25, edge_x, anchor_y + 25], fill="red", width=1)
    return screen_copy


def template_section():
    """Step 1: upload the template and place the name. Returns the template."""
    st.header("1. Certificate template")
    uploaded = st.file_uploader("Upload the template (PNG, JPG or PDF)", key="template_file")
    if uploaded is None:
        return None

    file_bytes = uploaded.getvalue()
    try:
        template = read_template(uploaded.name, file_bytes)
    except ValueError as error:
        st.error(str(error))
        return None

    key = template_key(file_bytes)
    if st.session_state.get("template_key") != key:
        logger.info("Template uploaded: %s (%s)", uploaded.name, key)
        start_placement(key, template)
    if st.session_state.saved_settings_found:
        st.info("The saved placement for this template was loaded.")

    placement_editor(template, key, uploaded.name)
    return template


def apply_pending_changes():
    # Streamlit does not allow changing a widget's value after the widget is
    # drawn. A colour picked with the eyedropper or a newly added font is
    # therefore stored as "pending" and applied here, before the widgets.
    for widget_key in ("color", "font_file", "font_size"):
        pending_key = f"pending_{widget_key}"
        if pending_key in st.session_state:
            st.session_state[widget_key] = st.session_state.pop(pending_key)


def select_new_font(file_name):
    logger.info("Font added: %s", file_name)
    st.session_state.pending_font_file = file_name
    st.rerun(scope="fragment")


def font_controls():
    st.selectbox("Font", available_fonts(), key="font_file", format_func=font_display_name)
    with st.expander("Add a font"):
        google_name = st.text_input("Google Font name", placeholder="e.g. Playfair Display", help="Browse the free fonts at fonts.google.com")
        if st.button("Download from Google Fonts"):
            try:
                with st.spinner("Downloading..."):
                    file_name = download_google_font(google_name)
                select_new_font(file_name)
            except ValueError as error:
                st.error(str(error))

        uploaded_font = st.file_uploader("Or upload a font file (.ttf or .otf)", key="font_upload")
        if uploaded_font and st.button("Add this font"):
            try:
                select_new_font(add_font_file(uploaded_font.name, uploaded_font.getvalue()))
            except ValueError as error:
                st.error(str(error))


def centre_buttons(template):
    horizontal, vertical, both = st.columns(3)
    anchor_x, anchor_y = st.session_state.anchor
    if horizontal.button("Centre horizontally", use_container_width=True):
        st.session_state.anchor = [template.width // 2, anchor_y]
    if vertical.button("Centre vertically", use_container_width=True):
        st.session_state.anchor = [anchor_x, template.height // 2]
    if both.button("Centre both", use_container_width=True):
        st.session_state.anchor = [template.width // 2, template.height // 2]


def handle_canvas_gesture(gesture, template):
    """Apply what HR did on the preview (see placement_canvas.py for the messages)."""
    if gesture["action"] == "resize":
        new_size = round(st.session_state.font_size * gesture["factor"])
        st.session_state.pending_font_size = min(max(new_size, MIN_FONT_SIZE), MAX_FONT_SIZE)
        return

    # Positions are fractions of the picture (0 to 1); convert to template
    # pixels, keeping the point inside the template if the mouse left it.
    x = round(min(max(gesture["x"], 0), 1) * (template.width - 1))
    y = round(min(max(gesture["y"], 0), 1) * (template.height - 1))
    if gesture["action"] == "pick":
        red, green, blue = template.getpixel((x, y))
        st.session_state.pending_color = f"#{red:02X}{green:02X}{blue:02X}"
    else:
        # "move" (dragged, maybe snapped to the centre) or "click" (placed).
        st.session_state.anchor = [x, y]


@st.fragment
def placement_editor(template, key, template_name):
    """Font, size, colour, position and live preview.

    A fragment reruns on its own: changing the placement redraws only this
    part, not the recipient list and everything below, so it stays fast.
    """
    apply_pending_changes()
    controls, preview = st.columns([1, 3])
    with controls:
        font_controls()
        st.number_input("Font size", min_value=MIN_FONT_SIZE, max_value=MAX_FONT_SIZE, step=5, key="font_size")
        st.color_picker("Colour", key="color")
        st.slider("Maximum name width", min_value=100, max_value=template.width, step=10, key="max_width")
        test_name = st.text_input(
            "Try any name",
            value="Amina Bello",
            key="test_name",
            help="Try your longest name, and one with accents (é, ç, ñ), to check they fit.",
        )
        if st.button("Save placement for this template"):
            save_settings(key, current_settings())
            st.session_state.saved_settings_found = True
            logger.info("Saved placement for template %s (%s)", template_name, key)
            st.success("Placement saved. It will be loaded next time you use this template.")

    with preview:
        click_mode = st.radio("Clicking on the template:", [MOVE_NAME, PICK_COLOUR], horizontal=True, key="click_mode")
        centre_buttons(template)
        settings = current_settings()

        st.caption("Drag the name to move it, drag a corner to resize it. Pink lines show the page centre.")
        layer, name_box = name_layer(template, key, test_name or "Amina Bello", settings)
        gesture = placement_canvas(
            background_url(template, key),
            layer,
            anchor=[settings["anchor"][0] / template.width, settings["anchor"][1] / template.height],
            name_box=name_box,
            mode="colour" if click_mode == PICK_COLOUR else "move",
            key="placement_canvas",
        )
        if gesture:
            handle_canvas_gesture(gesture, template)
            st.rerun(scope="fragment")


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
    # Streamlit reruns this on every click; log each list only once.
    list_summary = (uploaded.name, name_column, email_column, len(people), len(rejected))
    if st.session_state.get("logged_list") != list_summary:
        st.session_state.logged_list = list_summary
        logger.info("Recipient list %s: %d valid, %d skipped", uploaded.name, len(people), len(rejected))

    valid_count, skipped_count = st.columns(2)
    valid_count.metric("Valid recipients", len(people))
    skipped_count.metric("Skipped rows", len(rejected))
    if rejected:
        st.warning("These rows will be skipped. Fix them in your file and upload it again if needed.")
        st.dataframe(pd.DataFrame(rejected), hide_index=True)
    return people


def generation_section(template, people):
    """Step 3: preview one certificate, then generate all of them."""
    st.header("3. Preview and generate")
    settings = current_settings()
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
        # A new batch starts a new report.
        clear_email_results()

        st.success(f"{len(generated)} certificates saved in {batch_folder}")
        if failed:
            st.error(f"{len(failed)} certificates could not be created.")
            st.dataframe(pd.DataFrame(failed), hide_index=True)


def send_emails(recipients, dry_run):
    """Return (sent, failed), or None if sending could not start (message shown)."""
    try:
        with st.spinner("Preparing emails..." if dry_run else "Sending emails... this takes a few seconds per person."):
            return send_certificates(recipients, current_messages(), st.session_state.template_key, dry_run)
    except ValueError as error:
        st.error(str(error))
        return None


def skip_people_already_sent(generated):
    """Warn before sending the same certificate twice; return who to send to."""
    already_sent = find_already_sent(generated, st.session_state.template_key)
    if not already_sent:
        return generated

    st.warning(f"{len(already_sent)} of these people already received this certificate by email.")
    with st.expander("Show who"):
        st.dataframe(pd.DataFrame(already_sent)[["name", "email"]], hide_index=True)
    choice = st.radio("What should happen to them?", ["Skip them (recommended)", "Send it to them again"])
    if choice == "Send it to them again":
        return generated
    return [person for person in generated if person not in already_sent]


def email_section():
    """Step 4: write the messages and send (or dry-run) the emails."""
    generated = st.session_state.get("generated")
    if not generated:
        return

    st.header("4. Send by email")
    st.text_input("Subject", key="subject")
    winner_box, participant_box = st.columns(2)
    winner_box.text_area("Message for winners", key="winner_body", height=200)
    participant_box.text_area("Message for participants", key="participant_body", height=200)
    st.caption("{name} is replaced by each person's name.")
    if st.button("Save messages for this template"):
        save_settings(st.session_state.template_key, current_messages())
        logger.info("Saved email messages for template %s", st.session_state.template_key)
        st.success("Messages saved for this template.")

    # On by default: a real send cannot be undone, a dry run is harmless.
    dry_run = st.checkbox("Dry run: prepare every email but send nothing", value=True)
    if dry_run:
        st.warning("Dry run is ON: no email will be sent. Untick the box above to send for real.")
    recipients = generated if dry_run else skip_people_already_sent(generated)
    if not recipients:
        st.info("Everyone in this batch already received this certificate. Nothing to send.")
        return

    button_label = f"Dry run for {len(recipients)} emails" if dry_run else f"Send {len(recipients)} emails"
    if st.button(button_label, type="primary"):
        result = send_emails(recipients, dry_run)
        if result:
            st.session_state.email_sent, st.session_state.email_failed = result
            st.session_state.email_dry_run = dry_run


def problem_rows():
    """Everyone who did not get a certificate by email, with the reason.

    The columns match what people_loader detects, so HR can fix this file
    and upload it again as the recipient list.
    """
    rows = []
    for row in st.session_state.get("rejected_rows", []):
        rows.append({"name": row["name"], "email": row["email"], "status": "", "reason": f"Skipped (row {row['row']}): {row['reason']}"})
    for person in st.session_state.get("generation_failed", []) + st.session_state.get("email_failed", []):
        rows.append({"name": person["name"], "email": person["email"], "status": person["status"], "reason": person["reason"]})
    return rows


def report_section():
    """Step 5: counts, failed.csv, and resending to the failed emails."""
    if "email_sent" not in st.session_state:
        return

    dry_run = st.session_state.email_dry_run
    email_failed = st.session_state.email_failed
    st.header("5. Report" + (" (dry run)" if dry_run else ""))
    if dry_run:
        st.info("This was a dry run: no email was sent. Untick 'Dry run' in step 4 to send for real.")

    generated_count, sent_count, failed_count, skipped_count = st.columns(4)
    generated_count.metric("Generated", len(st.session_state.generated))
    sent_count.metric("Prepared (not sent)" if dry_run else "Sent", len(st.session_state.email_sent))
    failed_count.metric("Failed", len(st.session_state.get("generation_failed", [])) + len(email_failed))
    skipped_count.metric("Skipped", len(st.session_state.get("rejected_rows", [])))

    rows = problem_rows()
    if not rows:
        st.success("No problems: everyone was handled.")
        return

    problems = pd.DataFrame(rows)
    st.dataframe(problems, hide_index=True)
    # utf-8-sig adds a marker that tells Excel the file is UTF-8, so names
    # like Hélène are not shown as HÃ©lÃ¨ne when HR opens it.
    st.download_button(
        "Download failed.csv",
        data=problems.to_csv(index=False).encode("utf-8-sig"),
        file_name="failed.csv",
        mime="text/csv",
    )
    st.caption("To fix skipped rows: correct them in failed.csv, then upload it as the recipient list.")

    if email_failed and not dry_run and st.button(f"Resend to the {len(email_failed)} failed emails"):
        logger.info("Resending to %d failed recipients", len(email_failed))
        result = send_emails(email_failed, dry_run=False)
        if result:
            newly_sent, still_failed = result
            st.session_state.email_sent = st.session_state.email_sent + newly_sent
            st.session_state.email_failed = still_failed
            # The counts above were drawn before the resend; redraw them.
            st.rerun()


def main():
    st.set_page_config(page_title="Certificate Generator", layout="wide")
    st.title("Certificate Generator")

    template = template_section()
    if template is None:
        return
    people = people_section()
    if not people:
        return
    generation_section(template, people)
    email_section()
    report_section()


try:
    main()
except Exception:
    # HR sees a short message; the full technical details go to the log.
    logger.exception("Unexpected error in the app")
    st.error(f"Something unexpected went wrong. The details were saved in {LOG_FILE.name}.")
