"""The template preview where HR moves and resizes the name, like in Canva.

Everything that must feel instant happens in the browser: the template is a
background picture and the name is a transparent picture laid over it.
While HR drags, the browser only slides or scales that layer, shows the
selection box, and shows pink alignment lines when the name reaches the
centre of the page. When the mouse is released, one message goes to Python,
which then redraws the real name.

Messages sent to Python (positions are fractions 0-1 of the picture):
    {"action": "move",   "x": ..., "y": ...}   name dragged to a new centre
    {"action": "click",  "x": ..., "y": ...}   click outside the name
    {"action": "resize", "factor": ...}        corner handle dragged
    {"action": "pick",   "x": ..., "y": ...}   eyedropper click
"""

import base64
import io

import streamlit as st

CSS = """
.stage { position: relative; user-select: none; touch-action: none; overflow: hidden; }
.stage img { display: block; width: 100%; }
.name-layer { position: absolute; left: 0; top: 0; pointer-events: none; }
.name-box { position: absolute; border: 1px dashed #8b3dff; box-sizing: border-box; pointer-events: none; }
.handle {
    position: absolute; width: 14px; height: 14px; box-sizing: border-box;
    background: white; border: 2px solid #8b3dff; border-radius: 50%; pointer-events: auto;
}
.handle[data-corner="top-left"] { left: -8px; top: -8px; cursor: nwse-resize; }
.handle[data-corner="top-right"] { right: -8px; top: -8px; cursor: nesw-resize; }
.handle[data-corner="bottom-left"] { left: -8px; bottom: -8px; cursor: nesw-resize; }
.handle[data-corner="bottom-right"] { right: -8px; bottom: -8px; cursor: nwse-resize; }
.snap-line { position: absolute; background: #ff3ec9; pointer-events: none; }
.snap-line.vertical { left: 50%; top: 0; bottom: 0; width: 1px; }
.snap-line.horizontal { top: 50%; left: 0; right: 0; height: 1px; }
[hidden] { display: none !important; }
"""

JS = """
// How close (as a fraction of the picture) the name's centre must come to
// the page centre before it snaps onto it.
const SNAP_DISTANCE = 0.012;
// Mouse movements shorter than this many screen pixels count as a click.
const CLICK_DISTANCE = 4;

export default function (component) {
    const { data, parentElement, setTriggerValue } = component;

    // Streamlit calls this function again whenever Python sends new pictures,
    // so build the page elements once and reuse them afterwards.
    let stage = parentElement.querySelector(".stage");
    if (!stage) {
        stage = document.createElement("div");
        stage.className = "stage";
        stage.innerHTML = `
            <img class="background" draggable="false">
            <img class="name-layer" draggable="false">
            <div class="snap-line vertical" hidden></div>
            <div class="snap-line horizontal" hidden></div>
            <div class="name-box">
                <div class="handle" data-corner="top-left"></div>
                <div class="handle" data-corner="top-right"></div>
                <div class="handle" data-corner="bottom-left"></div>
                <div class="handle" data-corner="bottom-right"></div>
            </div>`;
        parentElement.appendChild(stage);
    }
    const background = stage.querySelector(".background");
    const nameLayer = stage.querySelector(".name-layer");
    const nameBox = stage.querySelector(".name-box");
    const verticalLine = stage.querySelector(".snap-line.vertical");
    const horizontalLine = stage.querySelector(".snap-line.horizontal");
    const colourMode = data.mode === "colour";
    const [anchorX, anchorY] = data.anchor;

    stage.style.cursor = colourMode ? "crosshair" : "move";
    nameBox.hidden = colourMode || !data.box;

    // Draw the selection box around the name, optionally scaled around the anchor.
    const placeBox = (factor = 1) => {
        if (!data.box) return;
        const [left, top, right, bottom] = data.box;
        nameBox.style.left = `${(anchorX - (anchorX - left) * factor) * 100}%`;
        nameBox.style.top = `${(anchorY - (anchorY - top) * factor) * 100}%`;
        nameBox.style.width = `${(right - left) * factor * 100}%`;
        nameBox.style.height = `${(bottom - top) * factor * 100}%`;
        nameBox.style.transform = "";
    };
    const resetPosition = () => {
        nameLayer.style.transform = "";
        placeBox();
        verticalLine.hidden = true;
        horizontalLine.hidden = true;
    };

    background.src = data.background;
    // Keep the name where it was dropped until the new picture has loaded,
    // so it does not jump back for a moment.
    if (nameLayer.src !== data.name_layer) {
        nameLayer.onload = resetPosition;
        nameLayer.src = data.name_layer;
    } else {
        resetPosition();
    }

    const pointerPosition = (event) => {
        const box = stage.getBoundingClientRect();
        return { x: (event.clientX - box.left) / box.width, y: (event.clientY - box.top) / box.height, box };
    };
    const insideName = (point) => {
        if (!data.box) return false;
        const [left, top, right, bottom] = data.box;
        return point.x >= left && point.x <= right && point.y >= top && point.y <= bottom;
    };

    const moveName = (gesture, now) => {
        let newX = anchorX + now.x - gesture.start.x;
        let newY = anchorY + now.y - gesture.start.y;
        // Snap to the page centre, like Canva's pink alignment lines.
        const snapX = Math.abs(newX - 0.5) < SNAP_DISTANCE;
        const snapY = Math.abs(newY - 0.5) < SNAP_DISTANCE;
        if (snapX) newX = 0.5;
        if (snapY) newY = 0.5;
        verticalLine.hidden = !snapX;
        horizontalLine.hidden = !snapY;

        const shift = `translate(${(newX - anchorX) * now.box.width}px, ${(newY - anchorY) * now.box.height}px)`;
        nameLayer.style.transform = shift;
        nameBox.style.transform = shift;
        gesture.message = { action: "move", x: newX, y: newY };
    };

    const resizeName = (gesture, now) => {
        // The name stays centred on its anchor, so it grows and shrinks
        // around that point. The size follows how far the mouse is from it.
        const distance = (point) => Math.hypot(
            (point.x - anchorX) * now.box.width, (point.y - anchorY) * now.box.height);
        const factor = Math.max(0.1, distance(now) / Math.max(1, distance(gesture.start)));
        nameLayer.style.transformOrigin = `${anchorX * 100}% ${anchorY * 100}%`;
        nameLayer.style.transform = `scale(${factor})`;
        placeBox(factor);
        gesture.message = { action: "resize", factor };
    };

    let gesture = null;
    stage.onpointerdown = (event) => {
        const onHandle = event.target.classList && event.target.classList.contains("handle");
        gesture = { type: onHandle && !colourMode ? "resize" : "move", start: pointerPosition(event), message: null };
        // Keep receiving the mouse even if it leaves the picture while
        // dragging. Some browsers can refuse; dragging still works without it.
        try { stage.setPointerCapture(event.pointerId); } catch (error) {}
        event.preventDefault();
    };
    stage.onpointermove = (event) => {
        if (!gesture || colourMode) return;
        const now = pointerPosition(event);
        if (gesture.type === "resize") {
            resizeName(gesture, now);
        } else {
            moveName(gesture, now);
        }
    };
    stage.onpointerup = (event) => {
        if (!gesture) return;
        const end = pointerPosition(event);
        const travelled = Math.hypot(
            (end.x - gesture.start.x) * end.box.width, (end.y - gesture.start.y) * end.box.height);

        // The alignment lines are only for while dragging.
        verticalLine.hidden = true;
        horizontalLine.hidden = true;

        let message = gesture.message;
        if (colourMode) {
            message = { action: "pick", x: end.x, y: end.y };
        } else if (travelled < CLICK_DISTANCE) {
            // A click on the name itself (or a handle) does nothing; a click
            // elsewhere places the name there.
            const isPlainClick = gesture.type === "move" && !insideName(gesture.start);
            message = isPlainClick ? { action: "click", x: end.x, y: end.y } : null;
        }
        gesture = null;
        if (message) {
            setTriggerValue("gesture", message);
        } else {
            resetPosition();
        }
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


def placement_canvas(background_url, name_layer, anchor, name_box, mode, key):
    """Show the template with the name HR can drag and resize.

    anchor and name_box are fractions (0-1) of the picture: anchor is
    [x, y], name_box is [left, top, right, bottom] or None.
    Returns one of the messages described at the top of this file on the
    rerun right after the mouse is released, and None otherwise.
    """
    # Streamlit skips the browser code when the data is identical to last
    # time, e.g. when the name is dropped exactly where it was. A counter
    # that changes on every redraw makes sure the browser always resets.
    redraw_key = f"{key}_redraws"
    st.session_state[redraw_key] = st.session_state.get(redraw_key, 0) + 1
    result = _mount_canvas(
        data={
            "background": background_url,
            "name_layer": image_data_url(name_layer, "PNG"),
            "anchor": anchor,
            "box": name_box,
            "mode": mode,
            "redraw": st.session_state[redraw_key],
        },
        key=key,
        # Streamlit needs a callback to know this trigger exists; the value
        # itself is read below, so the callback has nothing to do.
        on_gesture_change=lambda: None,
    )
    return getattr(result, "gesture", None)
