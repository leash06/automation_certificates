"""A round sun/moon icon that switches the app between light and dark mode.

How it works: .streamlit/config.toml defines a light and a dark theme, and
Streamlit picks one by asking the browser whether the computer is in dark
mode. At the start the browser's real answer is used, so the app opens in the
computer's mode. When HR clicks the icon, the browser is made to answer with
HR's choice instead, and Streamlit is told to check again (it listens for the
browser's "afterprint" event for exactly this). Nothing reloads, so nothing
HR has done is lost.

The animation: a circle in the new background colour grows from the icon and
covers the page. Growing one circle is very light work for the browser, so it
stays smooth. Streamlit repaints the app in the new colours underneath it,
out of sight, and then the circle fades away.

All of this happens in the browser, so the Python side only shows the icon.
"""

import streamlit as st

CSS = """
button {
    display: flex; align-items: center; justify-content: center;
    width: 36px; height: 36px; padding: 0; border-radius: 50%; cursor: pointer;
    color: var(--st-text-color, inherit);
    background: transparent;
    border: 1px solid var(--st-border-color, rgba(128, 128, 128, .3));
    transition: background-color .2s ease, transform .2s ease;
}
button:hover { background: var(--st-secondary-background-color, rgba(128, 128, 128, .1)); }
button:active { transform: scale(.92); }
svg { width: 18px; height: 18px; }
"""

JS = """
const DARK_QUERY = "(prefers-color-scheme: dark)";
// Must match backgroundColor of [theme.light] and [theme.dark] in config.toml,
// so the growing circle is exactly the colour the page is about to become.
const BACKGROUND = { light: "#FFFFFF", dark: "#0F1115" };
const GROW_MS = 450;
const FADE_MS = 250;

const SUN = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/></svg>';
const MOON = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z"/></svg>';

// Runs once per browser tab: remember the computer's mode and make the
// browser report HR's choice to Streamlit from now on.
function setUpThemeSwitching() {
    if (window.certificatesTheme) return;

    // If a fixed theme was once picked in Streamlit's old settings menu,
    // Streamlit keeps it and would ignore this icon. Go back (once) to
    // following the computer's mode; this needs one reload.
    const savedThemeKey = `stActiveTheme-${window.location.pathname}-v2`;
    const savedTheme = localStorage.getItem(savedThemeKey);
    if (savedTheme && savedTheme !== '"System"') {
        localStorage.setItem(savedThemeKey, '"System"');
        window.location.reload();
        return;
    }

    const realMatchMedia = window.matchMedia.bind(window);
    window.certificatesTheme = { mode: realMatchMedia(DARK_QUERY).matches ? "dark" : "light", switching: false };
    window.matchMedia = (query) => {
        const answer = realMatchMedia(query);
        if (query !== DARK_QUERY) return answer;
        return new Proxy(answer, {
            get(target, property) {
                if (property === "matches") return window.certificatesTheme.mode === "dark";
                const value = target[property];
                return typeof value === "function" ? value.bind(target) : value;
            },
        });
    };
}

function applyTheme(mode) {
    window.certificatesTheme.mode = mode;
    // Streamlit re-checks light or dark when this event happens.
    window.dispatchEvent(new Event("afterprint"));
}

function waitForRepaint() {
    return new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)));
}

async function switchWithAnimation(mode, centerX, centerY) {
    // Big enough to reach the farthest corner of the window from the icon.
    const radius = Math.hypot(Math.max(centerX, innerWidth - centerX), Math.max(centerY, innerHeight - centerY));
    const circle = document.createElement("div");
    Object.assign(circle.style, {
        position: "fixed", zIndex: 2147483647, pointerEvents: "none", borderRadius: "50%",
        left: `${centerX - radius}px`, top: `${centerY - radius}px`,
        width: `${radius * 2}px`, height: `${radius * 2}px`,
        background: BACKGROUND[mode], transform: "scale(0)", willChange: "transform, opacity",
    });
    document.body.appendChild(circle);

    // Growing with "transform" is done by the graphics card, so it stays smooth.
    await circle.animate([{ transform: "scale(0)" }, { transform: "scale(1)" }],
        { duration: GROW_MS, easing: "cubic-bezier(.4, 0, .2, 1)", fill: "forwards" }).finished;

    // The page is now covered: switch the colours underneath, out of sight.
    applyTheme(mode);
    await waitForRepaint();

    await circle.animate([{ opacity: 1 }, { opacity: 0 }],
        { duration: FADE_MS, easing: "ease-out", fill: "forwards" }).finished;
    circle.remove();
}

export default function (component) {
    const { parentElement } = component;
    setUpThemeSwitching();

    let button = parentElement.querySelector("button");
    if (!button) {
        button = document.createElement("button");
        parentElement.appendChild(button);
    }
    // The icon shows the mode it switches to: a sun while dark, a moon while light.
    const showIcon = () => {
        const dark = window.certificatesTheme.mode === "dark";
        button.innerHTML = dark ? SUN : MOON;
        button.title = dark ? "Switch to light mode" : "Switch to dark mode";
        button.setAttribute("aria-label", button.title);
    };
    showIcon();
    button.onclick = async () => {
        // Ignore extra clicks while a switch is still animating.
        if (window.certificatesTheme.switching) return;
        window.certificatesTheme.switching = true;
        const box = button.getBoundingClientRect();
        const nextMode = window.certificatesTheme.mode === "dark" ? "light" : "dark";
        try {
            await switchWithAnimation(nextMode, box.left + box.width / 2, box.top + box.height / 2);
        } finally {
            window.certificatesTheme.switching = false;
        }
        showIcon();
    };
}
"""

_mount_toggle = st.components.v2.component("theme_toggle", css=CSS, js=JS)


def theme_toggle():
    """Show the round light/dark switch icon."""
    _mount_toggle(key="theme_toggle", width=36)
