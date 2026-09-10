"""Shared plumbing for the channel simulators.

OSMU_web rendered these as React components inside a Next.js app with
Tailwind. Ported to Python string templates rendered through
`st.components.v1.html`, which drops them into a sandboxed iframe — that
sandbox is why images are inlined as base64 `data:` URIs (see
core/storage.data_uri) rather than referenced by path: the iframe has no
route back to Streamlit's static file server.

The point of these views is unchanged: catch, before publishing, the things
that only show up at render time — a caption whose hook falls after
Instagram's 125-character fold, a 5th photo X will silently drop, on-screen
text that lands under the Shorts button cluster.
"""
from __future__ import annotations

import html
import re
from typing import List, Tuple

from ai_workers.photo_placement import split_segments
from core import storage

FONT_IMPORT = (
    "@import url('https://fonts.googleapis.com/css2?"
    "family=Noto+Sans+KR:wght@400;500;700&family=Nanum+Myeongjo:wght@400;700&display=swap');"
)

RESET_CSS = """
* { box-sizing: border-box; margin: 0; padding: 0; }
body {
    font-family: 'Noto Sans KR', -apple-system, BlinkMacSystemFont, sans-serif;
    background: #F1F5F9;
    padding: 16px;
    display: flex;
    justify-content: center;
}
img { display: block; max-width: 100%; }
.phone-frame {
    border: 8px solid #1F2937;
    border-radius: 32px;
    overflow: hidden;
    box-shadow: 0 12px 32px rgba(15, 23, 42, 0.18);
}
.sim-scroll { overflow-y: auto; overflow-x: hidden; background: #fff; }
.sim-scroll::-webkit-scrollbar { width: 6px; }
.sim-scroll::-webkit-scrollbar-thumb { background: #CBD5E1; border-radius: 3px; }
"""


def esc(text: str) -> str:
    return html.escape(text or "", quote=True)


def paragraphs(text: str) -> List[str]:
    return [p for p in (text or "").split("\n") if p.strip()]


def content_blocks(content: str) -> List[Tuple[str, str]]:
    """('text', paragraph) / ('image', rel_path) in document order."""
    blocks: List[Tuple[str, str]] = []
    for kind, value in split_segments(content):
        if kind == "image":
            blocks.append(("image", value))
        else:
            for para in paragraphs(value):
                blocks.append(("text", para))
    return blocks


def image_src(rel_path: str, max_edge: int = 720) -> str:
    if re.match(r"^https?://", rel_path or ""):
        return rel_path
    return storage.data_uri(rel_path, max_edge=max_edge)


def all_images(content: str, storage_file_paths: List[str]) -> List[str]:
    """Every photo the post will show, tagged ones first in document order,
    then any attached-but-untagged ones (which the blog view appends as a
    trailing gallery)."""
    tagged = [value for kind, value in split_segments(content) if kind == "image"]
    extras = [p for p in (storage_file_paths or []) if p not in tagged]
    return tagged + extras


def document(body_html: str, extra_css: str = "") -> str:
    return f"""<!doctype html>
<html lang="ko"><head><meta charset="utf-8">
<style>{FONT_IMPORT}{RESET_CSS}{extra_css}</style>
</head><body>{body_html}</body></html>"""


def empty_state(message: str) -> str:
    return document(
        f"""<div style="width:100%;max-width:520px;padding:48px 24px;text-align:center;
        background:#fff;border:1px dashed #CBD5E1;border-radius:12px;color:#64748B;font-size:14px;">
        {esc(message)}</div>"""
    )
