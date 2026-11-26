"""The template preview where HR drags the name.

Dragging happens in the browser: the template is a background picture and
the name is a transparent picture laid over it. While the mouse moves, the
browser only slides that layer, which is instant. When the mouse is released,
the start and end points are sent to Python once, and Python redraws.
"""

import base64
import io

import streamlit as st

CSS = """
.stage { position: relative; user-select: none; touch-action: none; }
.stage img { display: block; width: 100%; }
.name-layer { position: absolute; left: 0; top: 0; pointer-events: none; }
"""

JS = """
export default function (component) {
    const { data, parentElement, setTriggerValue } = component;

    // Streamlit calls this function again whenever Python sends new pictures,
    // so build the page elements once and reuse them afterwards.
    let stage = parentElement.querySelector(".stage");
    if (!stage) {
        stage = document.createElement("div");
        stage.className = "stage";
        stage.innerHTML = '<img class="background" draggable="false"><img class="name-layer" draggable="false">';
        parentElement.appendChild(stage);
    }
    const background = stage.querySelector(".background");
    const nameLayer = stage.querySelector(".name-layer");
    stage.style.cursor = data.mode === "colour" ? "crosshair" : "move";

    background.src = data.background;
    // Keep the dragged name where it was dropped until the new picture has
    // loaded, so it does not jump back for a moment.
    const resetPosition = () => { nameLayer.style.transform = ""; };
    if (nameLayer.src !== data.name_layer) {
        nameLayer.onload = resetPosition;
        nameLayer.src = data.name_layer;
    } else {
        resetPosition();
    }

    // Positions are sent as fractions (0 to 1) of the picture's width and
    // height, so Python does not need to know how big it is on screen.
    const pointerPosition = (event) => {
        const box = stage.getBoundingClientRect();
        return { x: (event.clientX - box.left) / box.width, y: (event.clientY - box.top) / box.height, box };
    };

    let start = null;
    stage.onpointerdown = (event) => {
        start = pointerPosition(event);
        // Keep receiving the mouse even if it leaves the picture while
        // dragging. Some browsers can refuse; dragging still works without it.
        try { stage.setPointerCapture(event.pointerId); } catch (error) {}
        event.preventDefault();
    };
    stage.onpointermove = (event) => {
        if (!start || data.mode === "colour") return;
        const now = pointerPosition(event);
        const moveX = (now.x - start.x) * now.box.width;
        const moveY = (now.y - start.y) * now.box.height;
        nameLayer.style.transform = `translate(${moveX}px, ${moveY}px)`;
    };
    stage.onpointerup = (event) => {
        if (!start) return;
        const end = pointerPosition(event);
        setTriggerValue("pointer_up", { x1: start.x, y1: start.y, x2: end.x, y2: end.y });
        start = null;
    };
}
"""

_mount_canvas = st.components.v2.component("placement_canvas", css=CSS, js=JS)


def image_data_url(image, image_format):
    """Put a picture inside a text string the browser can display directly."""
    buffer = io.BytesIO()
    image.save(buffer, image_format)
    mime_type = "image/jpeg" if image_format == "JPEG" else "image/png"
    return f"data:{mime_type};base64," + base64.b64encode(buffer.getvalue()).decode("ascii")


def placement_canvas(background_url, name_layer, mode, key):
    """Show the template with a draggable name.

    Returns {x1, y1, x2, y2} (fractions of the picture) on the rerun right
    after the mouse is released, and None otherwise.
    """
    result = _mount_canvas(
        data={"background": background_url, "name_layer": image_data_url(name_layer, "PNG"), "mode": mode},
        key=key,
        # Streamlit needs a callback to know this trigger exists; the value
        # itself is read below, so the callback has nothing to do.
        on_pointer_up_change=lambda: None,
    )
    return getattr(result, "pointer_up", None)
