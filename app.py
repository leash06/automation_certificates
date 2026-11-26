"""Streamlit interface for HR: design the certificate, check the list,
preview every certificate, then send them by email or download them.

The steps are separate screens, chosen in the sidebar. This file only
collects choices and shows results. Drawing lives in generator.py, reading
files in the loaders and sending in mailer.py, so the logic can be tested
without a browser.

Run with:  streamlit run app.py
"""

import logging
import math
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st
from PIL import Image, ImageColor, ImageDraw

from font_library import add_font_file, available_fonts, download_google_font, font_display_name
from generator import MIN_FONT_SIZE, draw_name, generate_certificates, write_name, zip_certificates
from mailer import find_already_sent, send_certificates
from people_loader import EMAIL_HEADERS, NAME_HEADERS, clean_people, find_column, read_people_table
from placement_canvas import image_data_url, placement_canvas
from settings_store import load_settings, save_settings, template_key
from template_loader import load_template
from theme_toggle import theme_toggle

PROJECT_FOLDER = Path(__file__).parent
OUTPUT_FOLDER = PROJECT_FOLDER / "output"
LOG_FILE = PROJECT_FOLDER / "certificates.log"

# The template is about 3500 px wide. The live preview is drawn on a copy
# this wide, which is about 12 times fewer pixels, so it updates quickly.
PREVIEW_WIDTH = 1000
# The preview list shows small certificates, drawn on an even smaller copy.
THUMBNAIL_WIDTH = 360
ROWS_PER_PAGE = 8
# The full-size view is reduced to this width so it loads quickly.
FULL_VIEW_WIDTH = 1600
MAX_FONT_SIZE = 2000

DEFAULT_FONT = "GreatVibes-Regular.ttf"
DEFAULT_TEST_NAME = "Amina Bello"

MOVE_NAME = "Move name"
PICK_COLOUR = "Pick colour"
MOUSE_ICONS = {MOVE_NAME: ":material/open_with:", PICK_COLOUR: ":material/colorize:"}

# The screens, in order: (id, label in the sidebar, icon).
PAGES = [
    ("design", "Design", ":material/edit_square:"),
    ("recipients", "Recipients", ":material/group:"),
    ("preview", "Preview", ":material/photo_library:"),
    ("deliver", "Send or download", ":material/send:"),
    ("report", "Report", ":material/fact_check:"),
]

# Streamlit forgets a widget's value when its screen is not shown. These
# values are kept alive by keep_widget_values() so HR can switch screens.
KEPT_WIDGET_KEYS = (
    "font_file", "font_size", "color", "max_width", "test_name", "click_mode",
    "name_column", "email_column", "subject", "message_template", "preview_search",
)

DEFAULT_MESSAGES = {
    "subject": "Your certificate, {name}",
    "message_template": (
        "Dear {name},\n\n"
        "Thank you for taking part. Your certificate is attached.\n\n"
        "Best regards,\nThe HR team"
    ),
}

# Purely cosmetic: left-align the sidebar menu, like a normal navigation menu.
SIDEBAR_CSS = """
<style>
section[data-testid="stSidebar"] .stButton button { justify-content: flex-start; }
section[data-testid="stSidebar"] .stButton button > div { justify-content: flex-start; }
</style>
"""

logging.basicConfig(
    filename=LOG_FILE,
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    encoding="utf-8",
)
logger = logging.getLogger("app")


# ---------------------------------------------------------------- pictures

@st.cache_data(show_spinner="Reading the template...")
def read_template(file_name, file_bytes):
    # Streamlit reruns this whole script on every click; caching avoids
    # converting the same PDF at 300 DPI again each time.
    return load_template(file_name, file_bytes)


@st.cache_resource(max_entries=8)
def scaled_template(_template, key, scale):
    # The leading _ tells Streamlit not to hash the big image on every
    # rerun; the template key already identifies it.
    return _template.resize((round(_template.width * scale), round(_template.height * scale)))


@st.cache_resource(max_entries=4)
def background_url(_template, key):
    # The template picture never changes while HR places the name, so it is
    # encoded for the browser once, not on every change.
    return image_data_url(scaled_template(_template, key, PREVIEW_WIDTH / _template.width), "JPEG")


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


# ------------------------------------------------------------- app state

def show_unexpected_error():
    # HR sees a short message; the full technical details go to the log.
    # Streamlit's own "rerun" signal is not an Exception, so it never lands here.
    logger.exception("Unexpected error in the app")
    st.error(f"Something unexpected went wrong. The details were saved in {LOG_FILE.name}.")


def keep_widget_values():
    # Writing a value back into its own key tells Streamlit to keep it even
    # while the widget's screen is hidden.
    for widget_key in KEPT_WIDGET_KEYS:
        if widget_key in st.session_state:
            st.session_state[widget_key] = st.session_state[widget_key]


def go_to(page):
    st.session_state.page = page


def default_settings(template):
    fonts = available_fonts()
    return {
        "anchor": [template.width // 2, template.height // 2],
        "font_file": DEFAULT_FONT if DEFAULT_FONT in fonts else fonts[0],
        "font_size": template.height // 12,
        "color": "#1F3A5F",
        "max_width": int(template.width * 0.6),
    }


def clear_results():
    for name in ("email_sent", "email_failed", "generation_failed", "zip_file"):
        st.session_state.pop(name, None)


def start_placement(key, template):
    """Fill the controls with this template's saved settings, or defaults."""
    saved = load_settings(key)
    # Saved values win; defaults fill anything never saved (e.g. message
    # saved but placement not yet, or the reverse).
    settings = {**default_settings(template), **DEFAULT_MESSAGES, **(saved or {})}
    # Templates saved before there was a single message kept a separate
    # participant message; that one becomes the message template.
    if saved and "message_template" not in saved and "participant_body" in saved:
        settings["message_template"] = saved["participant_body"]
    if settings["font_file"] not in available_fonts():
        settings["font_file"] = available_fonts()[0]

    st.session_state.template_key = key
    # Results made with a previous template must not be sent by mistake.
    clear_results()
    st.session_state.anchor = settings["anchor"]
    # A template can be replaced from the editor, where these widgets are
    # already drawn, so they go through "pending" (see apply_pending_changes).
    st.session_state.pending_font_file = settings["font_file"]
    st.session_state.pending_font_size = settings["font_size"]
    st.session_state.pending_color = settings["color"]
    st.session_state.pending_max_width = min(settings["max_width"], template.width)
    st.session_state.subject = settings["subject"]
    st.session_state.message_template = settings["message_template"]
    st.session_state.setdefault("test_name", DEFAULT_TEST_NAME)
    st.session_state.setdefault("click_mode", MOVE_NAME)


def current_messages():
    return {
        "subject": st.session_state.subject,
        "message_template": st.session_state.message_template,
    }


def current_settings():
    return {
        "anchor": st.session_state.anchor,
        "font_file": st.session_state.font_file,
        "font_size": st.session_state.font_size,
        "color": st.session_state.color,
        "max_width": st.session_state.max_width,
    }


def apply_pending_changes():
    # Streamlit does not allow changing a widget's value after the widget is
    # drawn. A colour picked with the eyedropper, a new font or a size set by
    # dragging a corner, or a new template's settings, is therefore stored as
    # "pending" and applied here, before the widgets are drawn.
    for widget_key in ("color", "font_file", "font_size", "max_width"):
        pending_key = f"pending_{widget_key}"
        if pending_key in st.session_state:
            st.session_state[widget_key] = st.session_state.pop(pending_key)


def store_template(uploaded):
    """Check and keep an uploaded template. Returns True if it was accepted."""
    file_bytes = uploaded.getvalue()
    try:
        template = read_template(uploaded.name, file_bytes)
    except ValueError as error:
        st.error(str(error))
        return False
    # Uploaded files disappear when their screen is hidden, so the bytes are kept here.
    st.session_state.template_name = uploaded.name
    st.session_state.template_bytes = file_bytes
    key = template_key(file_bytes)
    logger.info("Template uploaded: %s (%s)", uploaded.name, key)
    start_placement(key, template)
    return True


def current_template():
    if "template_bytes" not in st.session_state:
        return None
    return read_template(st.session_state.template_name, st.session_state.template_bytes)


def store_people_list(uploaded):
    """Check and keep an uploaded recipient list. Returns True if it was accepted."""
    try:
        table = read_people_table(uploaded.name, uploaded.getvalue())
    except ValueError as error:
        st.error(str(error))
        return False
    st.session_state.people_name = uploaded.name
    st.session_state.people_bytes = uploaded.getvalue()
    columns = list(table.columns)
    st.session_state.name_column = find_column(columns, NAME_HEADERS)
    st.session_state.email_column = find_column(columns, EMAIL_HEADERS)
    return True


def current_people():
    """Return (table, people, rejected) for the stored list, or None if there
    is no list or its columns are not chosen yet."""
    if "people_bytes" not in st.session_state:
        return None
    table = read_people_table(st.session_state.people_name, st.session_state.people_bytes)
    name_column = st.session_state.get("name_column")
    email_column = st.session_state.get("email_column")
    if name_column not in table.columns or email_column not in table.columns:
        return table, [], []
    people, rejected = clean_people(table, name_column, email_column)
    return table, people, rejected


# ----------------------------------------------------------- page pieces

def top_bar(location):
    """Breadcrumb on the left; returns a container on the right for buttons."""
    crumb, actions = st.columns([2, 3], vertical_alignment="center")
    crumb.markdown(f":gray[:material/workspace_premium: Certificates]&nbsp;&nbsp;:gray[›]&nbsp;&nbsp;**{location}**")
    return actions.container(horizontal=True, horizontal_alignment="right", vertical_alignment="center")


def page_heading(title, subtitle):
    # Centred, like the page titles in the design; the text is fixed, never
    # typed by a user, so writing it as HTML is safe.
    st.markdown(
        f"<div style='text-align:center;padding:1.25rem 0 1.5rem'>"
        f"<h1 style='margin:0 0 .4rem'>{title}</h1>"
        f"<p style='opacity:.6;margin:0'>{subtitle}</p></div>",
        unsafe_allow_html=True,
    )


def sidebar(page, template_ready, people_ready):
    available = {
        "design": True,
        "recipients": template_ready,
        "preview": template_ready and people_ready,
        "deliver": template_ready and people_ready,
        "report": "email_sent" in st.session_state,
    }
    done = {
        "design": template_ready,
        "recipients": people_ready,
        "preview": False,
        "deliver": "email_sent" in st.session_state,
        "report": False,
    }
    with st.sidebar:
        st.html(SIDEBAR_CSS)
        with st.container(horizontal=True, vertical_alignment="center"):
            st.markdown("### :blue[:material/workspace_premium:] Certificates")
            st.space("stretch")
            theme_toggle()
        st.caption("Design, check and send certificates in a few steps.")
        for page_id, label, icon in PAGES:
            st.button(
                label,
                key=f"nav_{page_id}",
                icon=":material/check_circle:" if done[page_id] and page_id != page else icon,
                type="primary" if page_id == page else "tertiary",
                width="stretch",
                disabled=not available[page_id],
                on_click=go_to,
                args=(page_id,),
            )


# ------------------------------------------------------ screen 1: design

def upload_template_screen():
    top_bar("Design")
    page_heading("Create your certificate", "Upload your certificate design, then place the name on it.")
    _, middle, _ = st.columns([1, 3, 1])
    uploaded = middle.file_uploader("Certificate template: PNG, JPG or PDF", key="template_upload")
    if uploaded and store_template(uploaded):
        st.rerun()


def select_new_font(file_name):
    logger.info("Font added: %s", file_name)
    st.session_state.pending_font_file = file_name
    st.rerun(scope="fragment")


def add_font_popover():
    with st.popover("Add a font", icon=":material/add:", width="stretch"):
        google_name = st.text_input("Google Font name", placeholder="e.g. Playfair Display", help="Browse the free fonts at fonts.google.com")
        if st.button("Download from Google Fonts", icon=":material/cloud_download:", width="stretch"):
            try:
                with st.spinner("Downloading..."):
                    file_name = download_google_font(google_name)
                select_new_font(file_name)
            except ValueError as error:
                st.error(str(error))

        st.divider()
        uploaded_font = st.file_uploader("Or upload a font file (.ttf or .otf)", key="font_upload")
        if uploaded_font and st.button("Add this font", icon=":material/upload:", width="stretch"):
            try:
                select_new_font(add_font_file(uploaded_font.name, uploaded_font.getvalue()))
            except ValueError as error:
                st.error(str(error))


def placement_toolbar(template):
    """Mouse mode and centring buttons, in one row above the preview."""
    with st.container(horizontal=True, vertical_alignment="center"):
        click_mode = st.segmented_control(
            "Mouse",
            [MOVE_NAME, PICK_COLOUR],
            key="click_mode",
            format_func=lambda mode: f"{MOUSE_ICONS[mode]} {mode}",
            label_visibility="collapsed",
        )
        anchor_x, anchor_y = st.session_state.anchor
        if st.button("Centre horizontally", icon=":material/align_horizontal_center:"):
            st.session_state.anchor = [template.width // 2, anchor_y]
        if st.button("Centre vertically", icon=":material/align_vertical_center:"):
            st.session_state.anchor = [anchor_x, template.height // 2]
        if st.button("Centre both", icon=":material/filter_center_focus:"):
            st.session_state.anchor = [template.width // 2, template.height // 2]
    # The segmented control is empty if HR clicks the selected option again.
    return click_mode or MOVE_NAME


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


def placement_is_saved(key):
    saved = load_settings(key) or {}
    return all(saved.get(name) == value for name, value in current_settings().items())


@st.fragment
def design_editor(template, key):
    """The editor: settings on the left, the certificate on the right.

    A fragment reruns on its own: changing the placement redraws only this
    screen, not the whole app, so it stays fast.
    """
    # When a fragment reruns on its own, the try/except at the bottom of
    # this file does not run, so the fragment catches its own errors.
    try:
        design_editor_content(template, key)
    except Exception:
        show_unexpected_error()


def design_editor_content(template, key):
    apply_pending_changes()
    actions = top_bar("Design")
    with actions:
        if placement_is_saved(key):
            st.markdown(":green[:material/cloud_done: Saved]")
        elif st.button("Save", icon=":material/save:"):
            save_settings(key, current_settings())
            logger.info("Saved placement for template %s (%s)", st.session_state.template_name, key)
            st.rerun(scope="fragment")
        if st.button("Continue", icon=":material/arrow_forward:", icon_position="right", type="primary"):
            go_to("recipients")
            st.rerun()

    panel, canvas = st.columns([1, 3], gap="large")
    with panel:
        text_tab, template_tab = st.tabs(["Text", "Template"])
        with text_tab:
            st.selectbox("Font", available_fonts(), key="font_file", format_func=font_display_name)
            add_font_popover()
            size_box, colour_box = st.columns([3, 2], vertical_alignment="bottom")
            size_box.number_input("Size", min_value=MIN_FONT_SIZE, max_value=MAX_FONT_SIZE, step=5, key="font_size")
            colour_box.color_picker("Colour", key="color")
            st.slider("Maximum name width", min_value=100, max_value=template.width, step=10, key="max_width")
            st.text_input("Try a name", key="test_name", help="Try your longest name, and one with accents (é, ç, ñ), to check they fit.")
        with template_tab:
            st.markdown(f":material/image: **{st.session_state.template_name}**")
            st.caption(f"{template.width} × {template.height} pixels")
            replacement = st.file_uploader("Replace the template", key="template_replace")
            if replacement and replacement.getvalue() != st.session_state.template_bytes and store_template(replacement):
                st.rerun()

    with canvas:
        click_mode = placement_toolbar(template)
        settings = current_settings()
        layer, name_box = name_layer(template, key, st.session_state.test_name or DEFAULT_TEST_NAME, settings)
        gesture = placement_canvas(
            background_url(template, key),
            layer,
            anchor=[settings["anchor"][0] / template.width, settings["anchor"][1] / template.height],
            name_box=name_box,
            mode="colour" if click_mode == PICK_COLOUR else "move",
            key="placement_canvas",
        )
        st.caption("Drag the name to move it, drag a corner to resize it. Pink lines appear at the page centre.")
        if gesture:
            handle_canvas_gesture(gesture, template)
            st.rerun(scope="fragment")


def design_page(template):
    if template is None:
        upload_template_screen()
        return
    design_editor(template, st.session_state.template_key)


# -------------------------------------------------- screen 2: recipients

def recipients_page(people_state):
    people = people_state[1] if people_state else []
    actions = top_bar("Recipients")
    with actions:
        st.button("Back", icon=":material/arrow_back:", on_click=go_to, args=("design",))
        st.button("Continue", icon=":material/arrow_forward:", icon_position="right", type="primary",
                  disabled=not people, on_click=go_to, args=("preview",))
    page_heading("Recipients", "Upload the list of people who receive a certificate: a name and an email for each.")

    _, middle, _ = st.columns([1, 4, 1])
    with middle:
        label = "Replace the list" if people_state else "Excel (.xlsx), CSV, or Google Form export"
        uploaded = st.file_uploader(label, key="people_upload")
        if uploaded and uploaded.getvalue() != st.session_state.get("people_bytes") and store_people_list(uploaded):
            st.rerun()
        if not people_state:
            return

        table, people, rejected = people_state
        st.markdown(f":material/table: **{st.session_state.people_name}** · {len(table)} rows")
        columns = list(table.columns)
        name_box, email_box = st.columns(2)
        name_box.selectbox("Name column", columns, key="name_column", placeholder="Choose the column...")
        email_box.selectbox("Email column", columns, key="email_column", placeholder="Choose the column...")
        if st.session_state.name_column is None or st.session_state.email_column is None:
            st.warning("Choose which columns contain the names and the emails.")
            return

        # Streamlit reruns this on every click; log each list only once.
        list_summary = (st.session_state.people_name, st.session_state.name_column, st.session_state.email_column, len(people), len(rejected))
        if st.session_state.get("logged_list") != list_summary:
            st.session_state.logged_list = list_summary
            logger.info("Recipient list %s: %d valid, %d skipped", st.session_state.people_name, len(people), len(rejected))

        with st.container(border=True, horizontal=True):
            st.metric("Valid recipients", len(people))
            st.metric("Skipped rows", len(rejected))
        if rejected:
            with st.expander(f"Why {len(rejected)} rows will be skipped"):
                st.dataframe(pd.DataFrame(rejected), hide_index=True, width="stretch")
                st.caption("Fix them in your file and upload it again if needed.")


# ----------------------------------------------------- screen 3: preview

@st.dialog("Certificate", width="large")
def show_full_certificate(template, person, settings):
    # Drawn at full size with the same function as the PDFs, then reduced
    # only for the screen, so this is exactly what the person receives.
    certificate = draw_name(template, person["name"], settings)
    height = round(certificate.height * FULL_VIEW_WIDTH / certificate.width)
    st.image(certificate.resize((FULL_VIEW_WIDTH, height)), caption=f"{person['name']} · {person['email']}")


def change_preview_page(step):
    st.session_state.preview_page = st.session_state.get("preview_page", 1) + step


def reset_preview_page():
    # A new search starts again from the first page.
    st.session_state.preview_page = 1


@st.fragment
def preview_list(template, people):
    """Every certificate as a list, page by page, like the design's
    certificate list. A fragment, so turning pages redraws only the list."""
    # Same reason as in design_editor: a fragment catches its own errors.
    try:
        preview_list_content(template, people)
    except Exception:
        show_unexpected_error()


def preview_list_content(template, people):
    search_box, _ = st.columns([2, 3])
    search = search_box.text_input(
        "Search",
        placeholder="Search a name or email...",
        key="preview_search",
        label_visibility="collapsed",
        icon=":material/search:",
        on_change=reset_preview_page,
    ).strip().lower()
    shown = [person for person in people if search in person["name"].lower() or search in person["email"].lower()]
    if not shown:
        st.info("No one matches this search.")
        return

    page_count = math.ceil(len(shown) / ROWS_PER_PAGE)
    page = min(max(st.session_state.get("preview_page", 1), 1), page_count)
    first = (page - 1) * ROWS_PER_PAGE
    page_people = shown[first:first + ROWS_PER_PAGE]

    settings = current_settings()
    scale = THUMBNAIL_WIDTH / template.width
    small_template = scaled_template(template, st.session_state.template_key, scale)
    with st.container(border=True, gap="small"):
        for position, person in enumerate(page_people):
            if position > 0:
                st.divider()
            with st.container(horizontal=True, vertical_alignment="center", gap="medium"):
                st.image(draw_name(small_template, person["name"], settings, scale), width=180)
                with st.container(width="stretch"):
                    st.markdown(f"**{person['name']}**")
                    st.caption(person["email"])
                if st.button("Preview", key=f"preview_{first + position}", icon=":material/image:"):
                    show_full_certificate(template, person, settings)

    with st.container(horizontal=True, vertical_alignment="center"):
        st.button("", icon=":material/chevron_left:", key="previous_page", help="Previous page",
                  disabled=page <= 1, on_click=change_preview_page, args=(-1,))
        st.button("", icon=":material/chevron_right:", key="next_page", help="Next page",
                  disabled=page >= page_count, on_click=change_preview_page, args=(1,))
        st.space("stretch")
        st.markdown(f"Showing **{first + 1}–{first + len(page_people)}** of **{len(shown)}** certificates")


def preview_page(template, people):
    actions = top_bar("Preview")
    with actions:
        st.button("Back", icon=":material/arrow_back:", on_click=go_to, args=("recipients",))
        st.button("Continue", icon=":material/arrow_forward:", icon_position="right", type="primary",
                  on_click=go_to, args=("deliver",))
    page_heading("Preview all certificates", "Every certificate exactly as it will be created. Open one to see it full size.")
    preview_list(template, people)


# --------------------------------------------- screen 4: send or download

def create_certificates(template, people):
    """Create one PDF per person in a new dated folder. Returns the people with their PDF path."""
    # One folder per batch, so a new batch never overwrites an older one.
    batch_folder = OUTPUT_FOLDER / datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    with st.spinner(f"Creating {len(people)} certificates..."):
        generated, failed = generate_certificates(template, people, current_settings(), batch_folder)
    st.session_state.generation_failed = failed
    if failed:
        st.error(f"{len(failed)} certificates could not be created. See the report.")
    return generated


def send_emails(recipients):
    """Return (sent, failed), or None if sending could not start (message shown)."""
    try:
        with st.spinner(f"Sending {len(recipients)} emails... about 2 seconds per person."):
            return send_certificates(recipients, current_messages(), st.session_state.template_key)
    except ValueError as error:
        st.error(str(error))
        return None


def skip_people_already_sent(people):
    """Warn before sending the same certificate twice; return who to send to."""
    already_sent = find_already_sent(people, st.session_state.template_key)
    if not already_sent:
        return people

    st.warning(f"{len(already_sent)} of these people already received this certificate by email.")
    with st.expander("Show who"):
        st.dataframe(pd.DataFrame(already_sent)[["name", "email"]], hide_index=True, width="stretch")
    choice = st.radio("What should happen to them?", ["Skip them (recommended)", "Send it to them again"], horizontal=True)
    if choice == "Send it to them again":
        return people
    return [person for person in people if person not in already_sent]


def email_card(template, people):
    with st.container(border=True):
        st.markdown("#### :blue[:material/mail:] Send by email")
        st.caption("Each person gets their own certificate as a PDF attachment.")
        st.text_input("Subject", key="subject")
        st.text_area("Message template", key="message_template", height=180, help="{name} is replaced by each person's name.")
        recipients = skip_people_already_sent(people)
        if not recipients:
            st.info("Everyone in this list already received this certificate. Nothing to send.")

        with st.container(horizontal=True, horizontal_alignment="right"):
            if st.button("Save message", icon=":material/save:"):
                save_settings(st.session_state.template_key, current_messages())
                logger.info("Saved email message for template %s", st.session_state.template_key)
                st.toast("Message saved for this template.", icon=":material/check_circle:")
            send_clicked = st.button(f"Send {len(recipients)} emails", icon=":material/send:", type="primary", disabled=not recipients)
        if send_clicked:
            generated = create_certificates(template, recipients)
            result = send_emails(generated) if generated else None
            if result:
                st.session_state.email_sent, st.session_state.email_failed = result
                go_to("report")
                st.rerun()


def download_card(template, people):
    with st.container(border=True):
        st.markdown("#### :blue[:material/download:] Download")
        st.caption("Create every certificate as a PDF and download them all in one ZIP file, without sending any email.")
        if st.button(f"Create {len(people)} certificates", icon=":material/picture_as_pdf:", width="stretch"):
            generated = create_certificates(template, people)
            st.session_state.zip_file = zip_certificates(generated) if generated else None
            st.session_state.zip_count = len(generated)
        if st.session_state.get("zip_file"):
            st.download_button(
                f"Download {st.session_state.zip_count} certificates (ZIP)",
                data=st.session_state.zip_file,
                file_name="certificates.zip",
                mime="application/zip",
                icon=":material/download:",
                type="primary",
                width="stretch",
                # Downloading does not need to redraw the page.
                on_click="ignore",
            )


def deliver_page(template, people):
    actions = top_bar("Send or download")
    with actions:
        st.button("Back", icon=":material/arrow_back:", on_click=go_to, args=("preview",))
    page_heading("Send or download", f"{len(people)} certificates are ready. Email them to everyone, or download them all.")
    email_column, download_column = st.columns([3, 2], gap="large")
    with email_column:
        email_card(template, people)
    with download_column:
        download_card(template, people)


# ------------------------------------------------------ screen 5: report

def problem_rows():
    """Everyone who did not get a certificate by email, with the reason.

    The columns match what people_loader detects, so HR can fix this file
    and upload it again as the recipient list.
    """
    rows = []
    for row in st.session_state.get("rejected_rows", []):
        rows.append({"name": row["name"], "email": row["email"], "reason": f"Skipped (row {row['row']}): {row['reason']}"})
    for person in st.session_state.get("generation_failed", []) + st.session_state.get("email_failed", []):
        rows.append({"name": person["name"], "email": person["email"], "reason": person["reason"]})
    return rows


def report_page():
    top_bar("Report")
    page_heading("Report", "What happened to each certificate.")
    email_failed = st.session_state.email_failed

    with st.container(border=True, horizontal=True):
        st.metric("Sent", len(st.session_state.email_sent))
        st.metric("Failed", len(st.session_state.get("generation_failed", [])) + len(email_failed))
        st.metric("Skipped", len(st.session_state.get("rejected_rows", [])))

    rows = problem_rows()
    if not rows:
        st.success("Everyone received their certificate.", icon=":material/check_circle:")
        return

    problems = pd.DataFrame(rows)
    st.dataframe(problems, hide_index=True, width="stretch")
    st.caption("To fix skipped rows: correct them in failed.csv, then upload it as the recipient list.")
    with st.container(horizontal=True):
        # utf-8-sig adds a marker that tells Excel the file is UTF-8, so
        # names like Hélène are not shown as HÃ©lÃ¨ne when HR opens it.
        st.download_button(
            "Download failed.csv",
            data=problems.to_csv(index=False).encode("utf-8-sig"),
            file_name="failed.csv",
            mime="text/csv",
            icon=":material/download:",
            on_click="ignore",
        )
        resend_clicked = bool(email_failed) and st.button(
            f"Resend to the {len(email_failed)} failed emails", icon=":material/replay:", type="primary"
        )
    if resend_clicked:
        logger.info("Resending to %d failed recipients", len(email_failed))
        result = send_emails(email_failed)
        if result:
            newly_sent, still_failed = result
            st.session_state.email_sent = st.session_state.email_sent + newly_sent
            st.session_state.email_failed = still_failed
            # The counts above were drawn before the resend; redraw them.
            st.rerun()


# ------------------------------------------------------------------ main

def main():
    st.set_page_config(page_title="Certificates", page_icon=":material/workspace_premium:", layout="wide")
    keep_widget_values()

    template = current_template()
    people_state = current_people() if template is not None else None
    people = people_state[1] if people_state else []
    if people_state:
        st.session_state.rejected_rows = people_state[2]

    page = st.session_state.setdefault("page", "design")
    # A screen that is not available yet (e.g. after replacing the template)
    # falls back to the design screen.
    if page in ("recipients",) and template is None:
        page = "design"
    if page in ("preview", "deliver") and not people:
        page = "recipients" if template is not None else "design"
    if page == "report" and "email_sent" not in st.session_state:
        page = "deliver" if people else "design"
    st.session_state.page = page

    sidebar(page, template is not None, bool(people))
    if page == "design":
        design_page(template)
    elif page == "recipients":
        recipients_page(people_state)
    elif page == "preview":
        preview_page(template, people)
    elif page == "deliver":
        deliver_page(template, people)
    else:
        report_page()


try:
    main()
except Exception:
    show_unexpected_error()
