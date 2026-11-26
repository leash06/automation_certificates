"""A button that switches the app between light and dark mode, with animation.

How it works: .streamlit/config.toml defines a light and a dark theme, and
Streamlit picks one by asking the browser whether the computer is in dark
mode. At the start the browser's real answer is used, so the app opens in the
computer's mode. When HR clicks the button, the browser is made to answer
with HR's choice instead, and Streamlit is told to check again (it listens
for the browser's "afterprint" event for exactly this). Nothing reloads, so
nothing HR has done is lost.

All of this happens in the browser, so the Python side only shows the button.
"""

import streamlit as st

CSS = """
button {
    display: flex; align-items: center; gap: .5rem; width: 100%;
    padding: .5rem .75rem; border-radius: 10px; cursor: pointer;
    font: inherit; font-size: .9rem;
    color: var(--st-text-color, inherit);
    background: transparent;
    border: 1px solid var(--st-border-color, rgba(128, 128, 128, .3));
    transition: background-color .2s ease;
}
button:hover { background: var(--st-secondary-background-color, rgba(128, 128, 128, .1)); }
svg { width: 18px; height: 18px; flex: none; }
"""

JS = """
const DARK_QUERY = "(prefers-color-scheme: dark)";
const ANIMATION_MS = 600;

const SUN = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/></svg>';
const MOON = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z"/></svg>';

// Runs once per browser tab: remember the computer's mode and make the
// browser report HR's choice to Streamlit from now on.
function setUpThemeSwitching() {
    if (window.certificatesTheme) return;

    // If a fixed theme was once picked in Streamlit's old settings menu,
    // Streamlit keeps it and would ignore this button. Go back (once) to
    // following the computer's mode; this needs one reload.
    const savedThemeKey = `stActiveTheme-${window.location.pathname}-v2`;
    const savedTheme = localStorage.getItem(savedThemeKey);
    if (savedTheme && savedTheme !== '"System"') {
        localStorage.setItem(savedThemeKey, '"System"');
        window.location.reload();
        return;
    }

    const realMatchMedia = window.matchMedia.bind(window);
    window.certificatesTheme = { mode: realMatchMedia(DARK_QUERY).matches ? "dark" : "light" };
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

    // The animation styles must live in the main page, not inside this button.
    const style = document.createElement("style");
    style.textContent = `
        ::view-transition-old(root), ::view-transition-new(root) { animation: none; mix-blend-mode: normal; }
        html.theme-fading * { transition: background-color ${ANIMATION_MS}ms ease, color ${ANIMATION_MS}ms ease, border-color ${ANIMATION_MS}ms ease !important; }
    `;
    document.head.appendChild(style);
}

function applyTheme(mode) {
    window.certificatesTheme.mode = mode;
    // Streamlit re-checks light or dark when this event happens.
    window.dispatchEvent(new Event("afterprint"));
}

function waitForRedraw() {
    return new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)));
}

function switchWithAnimation(mode, clickX, clickY) {
    if (!document.startViewTransition) {
        // Older browsers: fade the colours instead of the circle.
        document.documentElement.classList.add("theme-fading");
        applyTheme(mode);
        setTimeout(() => document.documentElement.classList.remove("theme-fading"), ANIMATION_MS);
        return;
    }
    // The browser takes a picture of the page, switches the theme, then
    // reveals the new colours as a circle growing from the button.
    const transition = document.startViewTransition(() => {
        applyTheme(mode);
        return waitForRedraw();
    });
    transition.ready.then(() => {
        const radius = Math.hypot(Math.max(clickX, innerWidth - clickX), Math.max(clickY, innerHeight - clickY));
        document.documentElement.animate(
            { clipPath: [`circle(0px at ${clickX}px ${clickY}px)`, `circle(${radius}px at ${clickX}px ${clickY}px)`] },
            { duration: ANIMATION_MS, easing: "ease-in-out", pseudoElement: "::view-transition-new(root)" },
        );
    });
}

export default function (component) {
    const { parentElement } = component;
    setUpThemeSwitching();

    let button = parentElement.querySelector("button");
    if (!button) {
        button = document.createElement("button");
        parentElement.appendChild(button);
    }
    // The button offers the other mode: in dark mode it says "Light mode".
    const showLabel = () => {
        const dark = window.certificatesTheme.mode === "dark";
        button.innerHTML = dark ? `${SUN}<span>Light mode</span>` : `${MOON}<span>Dark mode</span>`;
    };
    showLabel();
    button.onclick = (event) => {
        const nextMode = window.certificatesTheme.mode === "dark" ? "light" : "dark";
        switchWithAnimation(nextMode, event.clientX, event.clientY);
        showLabel();
    };
}
"""

_mount_toggle = st.components.v2.component("theme_toggle", css=CSS, js=JS)


def theme_toggle():
    """Show the light/dark switch button."""
    _mount_toggle(key="theme_toggle")
