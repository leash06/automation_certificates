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
from mailer import find_already_sent, send_certificates
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
        logger.info("Template uploaded: %s (%s)", uploaded.name, key)
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

    template, settings = template_section()
    if template is None:
        return
    people = people_section()
    if not people:
        return
    generation_section(template, settings, people)
    email_section()
    report_section()


try:
    main()
except Exception:
    # HR sees a short message; the full technical details go to the log.
    logger.exception("Unexpected error in the app")
    st.error(f"Something unexpected went wrong. The details were saved in {LOG_FILE.name}.")
