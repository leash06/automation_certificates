"""A round sun/moon icon that switches the app between light and dark mode.

How it works: .streamlit/config.toml defines a light and a dark theme, and
Streamlit picks one by asking the browser whether the computer is in dark
mode. At the start the browser's real answer is used, so the app opens in the
computer's mode. When HR clicks the icon, the browser is made to answer with
HR's choice instead, and Streamlit is told to check again (it listens for the
browser's "afterprint" event for exactly this). Nothing reloads, so nothing
HR has done is lost.

The animation, like Venom's symbiote: the new mode spreads from the icon as a
living goo. Thin tendrils shoot out first, then the body follows with a
rippling edge and swallows the page. The page stays readable the whole time:
inside the goo you see it in the new colours, outside it in the old ones.

This uses the browser's "view transition": the browser takes a picture of the
page before the switch and one after, and shows the "after" picture only
inside the goo shape, on top of the "before" picture. Browsers without view
transitions, and people who turned off animations, just get the switch.

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
const SPREAD_MS = 900;
// Time for Streamlit to repaint in the new colours before the browser takes
// the "after" picture. Nothing moves on screen during this short wait.
const THEME_SETTLE_MS = 100;
const TENDRIL_COUNT = 7;
// Points around the goo's edge: enough that the outline looks like a curve.
const EDGE_POINTS = 120;
// Shapes computed along the way; the browser blends smoothly between them.
const SHAPE_STEPS = 40;

const SUN = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/></svg>';
const MOON = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z"/></svg>';

// The browser's default view transition fades the two pictures into each
// other. We want both fully visible, the goo shape alone doing the change.
// This must be in the page itself, not in this component's own CSS.
const NO_FADE_CSS = "::view-transition-old(root), ::view-transition-new(root) { animation: none; mix-blend-mode: normal; }";

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

    const style = document.createElement("style");
    style.textContent = NO_FADE_CSS;
    document.head.appendChild(style);
}

function applyTheme(mode) {
    window.certificatesTheme.mode = mode;
    // Streamlit re-checks light or dark when this event happens.
    window.dispatchEvent(new Event("afterprint"));
}

// Shortest distance between two angles, so a tendril at angle 0 also
// reaches the edge points just below a full turn.
function angleDistance(a, b) {
    const difference = Math.abs(a - b) % (2 * Math.PI);
    return Math.min(difference, 2 * Math.PI - difference);
}

// A new random goo for each switch, so it never looks exactly the same.
function randomGoo(maxRadius) {
    const tendrils = Array.from({ length: TENDRIL_COUNT }, () => ({
        angle: Math.random() * 2 * Math.PI,
        length: maxRadius * (0.2 + Math.random() * 0.3),
        thickness: 0.08 + Math.random() * 0.1,  // in radians: how wide the tendril's base is
    }));
    return { tendrils, ripplePhase: Math.random() * 2 * Math.PI };
}

// How far the goo's edge reaches from the icon in one direction (angle),
// at one moment of the animation (progress, from 0 to 1).
function gooReach(goo, angle, progress, maxRadius) {
    // progress squared: a slow start, then it floods, like goo gathering
    // itself before it pounces. 1.15 makes sure the ripples still cover
    // the farthest corner at the end.
    const body = maxRadius * 1.15 * progress * progress;
    // Two waves around the edge that drift while it grows, so it looks alive.
    const ripple = 0.06 * Math.sin(3 * angle + goo.ripplePhase + progress * 8)
                 + 0.03 * Math.sin(7 * angle - progress * 11);
    let reach = body * (1 + ripple);
    // Tendrils reach full length in the first third, then the body catches up
    // and swallows them. The bell curve makes each one taper to a point.
    for (const tendril of goo.tendrils) {
        const distance = angleDistance(angle, tendril.angle) / tendril.thickness;
        reach += tendril.length * Math.min(1, progress * 3) * Math.exp(-distance * distance);
    }
    return reach;
}

// The goo's outline at one moment, as a CSS shape the browser can cut with.
function gooShape(goo, progress, center, maxRadius) {
    const points = [];
    for (let point = 0; point < EDGE_POINTS; point++) {
        const angle = (point / EDGE_POINTS) * 2 * Math.PI;
        const reach = gooReach(goo, angle, progress, maxRadius);
        const x = center.x + Math.cos(angle) * reach;
        const y = center.y + Math.sin(angle) * reach;
        points.push(`${x.toFixed(1)}px ${y.toFixed(1)}px`);
    }
    return `polygon(${points.join(", ")})`;
}

async function switchWithAnimation(mode, centerX, centerY) {
    const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (!document.startViewTransition || reduceMotion) {
        applyTheme(mode);
        return;
    }

    // The browser takes the "before" picture, runs this function to change
    // the theme, then takes the "after" picture.
    const transition = document.startViewTransition(async () => {
        applyTheme(mode);
        await new Promise((resolve) => setTimeout(resolve, THEME_SETTLE_MS));
    });
    await transition.ready;

    // Big enough to reach the farthest corner of the window from the icon.
    const maxRadius = Math.hypot(Math.max(centerX, innerWidth - centerX), Math.max(centerY, innerHeight - centerY));
    const goo = randomGoo(maxRadius);
    const center = { x: centerX, y: centerY };
    const shapes = Array.from({ length: SHAPE_STEPS + 1 }, (_, step) => ({
        clipPath: gooShape(goo, step / SHAPE_STEPS, center, maxRadius),
    }));
    // Show the "after" picture only inside the goo, as it grows.
    document.documentElement.animate(shapes, {
        duration: SPREAD_MS,
        easing: "linear",  // the slow start and fast flood are already in gooReach
        pseudoElement: "::view-transition-new(root)",
    });
    await transition.finished;
}

export default function (component) {
    const { parentElement } = component;
    setUpThemeSwitching();
    // The page is reloading to clear an old saved theme: there is nothing to
    // show yet, and window.certificatesTheme does not exist until it reloads.
    if (!window.certificatesTheme) return;

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
