from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components

try:
    from local_wisp import ensure_wisp_server
    local_wisp_url = ensure_wisp_server()
except Exception as e:
    local_wisp_url = None

ROOT = Path(__file__).resolve().parent
html = (ROOT / "index.html").read_text(encoding="utf-8")

runtime_parent = "const parent = window.top;"
if html.count(runtime_parent) != 1:
    raise RuntimeError("Could not find GUST's proxy frame runtime")

wisp_script = f"<script>window.__gustStreamlitRoot = window; window.__gustLocalWisp = {repr(local_wisp_url)};</script>"
html = html.replace(
    "<head>",
    f"<head>{wisp_script}",
    1,
)
html = html.replace(
    runtime_parent,
    """const parent = (() => {
    let frame = window;
    try {
        while (frame !== frame.parent) {
            if (frame.__gustStreamlitRoot === frame) return frame;
            frame = frame.parent;
        }
    } catch (_) {}
    return window.top;
})();""",
    1,
)

resize_script = """
<script>
(() => {
    const fit = () => {
        try {
            if (window.frameElement) {
                window.frameElement.style.height = `${window.top.innerHeight}px`;
            }
        } catch (_) {}
    };
    fit();
    try {
        window.top.addEventListener("resize", fit);
    } catch (_) {}

    // Keepalive to ensure session remains active at any time
    setInterval(() => {
        try {
            if (window.top && window.top.document) {
                window.top.dispatchEvent(new Event('mousemove'));
            }
        } catch (_) {}
    }, 45000);
})();
</script>
"""
html, closing_body, rest = html.rpartition("</body>")
if not closing_body:
    raise RuntimeError("Could not find the end of index.html")
html += resize_script + closing_body + rest

st.set_page_config(page_title="Strike — Weather Reports", page_icon="⚡", layout="wide")
st.markdown(
    """
    <style>
    [data-testid="stHeader"], [data-testid="stToolbar"], footer, header { display: none !important; }
    html, body, [data-testid="stAppViewContainer"], [data-testid="stAppViewBlockContainer"], .main, .block-container, [data-testid="stVerticalBlock"] {
        width: 100vw !important;
        height: 100vh !important;
        max-width: 100vw !important;
        max-height: 100vh !important;
        padding: 0 !important;
        margin: 0 !important;
        overflow: hidden !important;
    }
    iframe {
        position: fixed !important;
        inset: 0 !important;
        width: 100vw !important;
        height: 100vh !important;
        max-width: 100vw !important;
        max-height: 100vh !important;
        border: none !important;
        z-index: 999999 !important;
    }
    </style>
    """,
    unsafe_allow_html=True,
)
components.html(html, height=900, scrolling=False)
