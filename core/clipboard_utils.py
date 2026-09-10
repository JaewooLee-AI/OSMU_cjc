"""OS clipboard helper for the Naver semi-auto publisher.

Naver's Smart Editor ONE only accepts rich content via an actual paste
(Cmd/Ctrl+V) — there's no API to inject HTML into its DOM directly — so the
publish automation has to put real HTML on the OS clipboard first, exactly
like cjc_blog_v2/clipboard_manager.py does. Scoped down to macOS only (via
`osascript`) since that's the only platform this admin engine currently runs
on (OSMU_admin/Task.md §1: App 3 is a local always-on machine, not a server).
"""
from __future__ import annotations

import re
import subprocess
import sys

# Naver's editor sometimes auto-applies strikethrough to pasted text that
# happens to contain certain characters — strip any pre-existing strike
# markup so it can't compound with that quirk.
_STRIKE_TAG_RE = re.compile(r"</?(?:del|s|strike)\b[^>]*>", re.IGNORECASE)
_STRIKE_STYLE_RE = re.compile(r"text-decoration\s*:\s*line-through\s*;?", re.IGNORECASE)


def _sanitize_html(html_content: str) -> str:
    html_content = _STRIKE_TAG_RE.sub("", html_content)
    html_content = _STRIKE_STYLE_RE.sub("", html_content)
    return html_content


def copy_html_to_clipboard(html_content: str) -> bool:
    """Puts rich HTML on the system clipboard so a subsequent Cmd/Ctrl+V
    pastes formatted content (not literal HTML tags as plain text)."""
    html_content = _sanitize_html(html_content)

    if sys.platform == "darwin":
        try:
            hex_data = html_content.encode("utf-8").hex()
            applescript = f"set the clipboard to {{«class HTML»:«data HTML{hex_data}»}}"
            proc = subprocess.Popen(["osascript", "-e", applescript], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            proc.communicate()
            return proc.returncode == 0
        except Exception as exc:  # noqa: BLE001
            print(f"[clipboard_utils] osascript HTML clipboard failed, falling back to plain text: {exc}")

    try:
        import pyperclip

        pyperclip.copy(html_content)
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"[clipboard_utils] pyperclip fallback failed: {exc}")
        return False
