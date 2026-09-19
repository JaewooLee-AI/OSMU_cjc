"""Windows CF_HTML clipboard writer — the piece core/clipboard_utils.py is
missing.

That module puts rich HTML on the clipboard via `osascript` on macOS and
falls back to `pyperclip.copy()` everywhere else. pyperclip only ever writes
CF_UNICODETEXT (plain text); Windows' rich-paste path reads a *different*
clipboard format called "HTML Format" (aka CF_HTML), which is plain text
wrapped in a byte-offset header. Without it, pasting into Naver's Smart
Editor ONE on Windows would insert the literal "<p>...</p>" markup instead of
a formatted paragraph.

This file is the Windows-side fix, tested in isolation here before it gets
folded into core/clipboard_utils.py.
"""
from __future__ import annotations

import re

_HEADER_TEMPLATE = (
    "Version:0.9\r\n"
    "StartHTML:{start_html:09d}\r\n"
    "EndHTML:{end_html:09d}\r\n"
    "StartFragment:{start_fragment:09d}\r\n"
    "EndFragment:{end_fragment:09d}\r\n"
)
_FRAGMENT_PREFIX = "<html><body><!--StartFragment-->"
_FRAGMENT_SUFFIX = "<!--EndFragment--></body></html>"


def _build_cf_html(html_fragment: str) -> bytes:
    """CF_HTML is UTF-8 text whose header stores byte offsets into itself —
    the offsets have to be computed against the exact bytes being sent, so
    the header is built once with placeholder zeros purely to measure its
    own length, then rebuilt for real."""
    header_len = len(_HEADER_TEMPLATE.format(
        start_html=0, end_html=0, start_fragment=0, end_fragment=0
    ).encode("utf-8"))
    start_html = header_len
    start_fragment = start_html + len(_FRAGMENT_PREFIX.encode("utf-8"))
    fragment_bytes = html_fragment.encode("utf-8")
    end_fragment = start_fragment + len(fragment_bytes)
    end_html = end_fragment + len(_FRAGMENT_SUFFIX.encode("utf-8"))

    header = _HEADER_TEMPLATE.format(
        start_html=start_html, end_html=end_html,
        start_fragment=start_fragment, end_fragment=end_fragment,
    )
    body = _FRAGMENT_PREFIX + html_fragment + _FRAGMENT_SUFFIX
    return (header + body).encode("utf-8")


def copy_html_to_clipboard_windows(html_fragment: str) -> None:
    import win32clipboard  # noqa: PLC0415 — Windows-only import, kept local

    cf_html_format = win32clipboard.RegisterClipboardFormat("HTML Format")
    payload = _build_cf_html(html_fragment)
    plain_fallback = re.sub(r"<[^>]+>", "", html_fragment)

    win32clipboard.OpenClipboard()
    try:
        win32clipboard.EmptyClipboard()
        win32clipboard.SetClipboardData(cf_html_format, payload)
        win32clipboard.SetClipboardData(win32clipboard.CF_UNICODETEXT, plain_fallback)
    finally:
        win32clipboard.CloseClipboard()


def self_test() -> tuple[bool, str]:
    """Writes a known fragment, reads the CF_HTML data back, and checks the
    header markers and fragment text survived the round trip."""
    import win32clipboard  # noqa: PLC0415

    sample = "<p>테스트 문단입니다</p>"
    try:
        copy_html_to_clipboard_windows(sample)

        win32clipboard.OpenClipboard()
        try:
            cf_html_format = win32clipboard.RegisterClipboardFormat("HTML Format")
            raw = win32clipboard.GetClipboardData(cf_html_format)
        finally:
            win32clipboard.CloseClipboard()

        raw_text = raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else str(raw)
        ok = "StartHTML:" in raw_text and "StartFragment:" in raw_text and sample in raw_text
        return ok, f"round-trip {'OK' if ok else 'FAILED'}: {raw_text[:250]!r}"
    except Exception as exc:  # noqa: BLE001
        return False, f"clipboard self-test raised: {exc!r}"
