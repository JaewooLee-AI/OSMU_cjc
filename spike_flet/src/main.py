"""Spike entry point.

Answers two questions before the real Flet migration starts:

1. Does a `flet build windows` executable still have a working Playwright
   (driver + browser) after Flet's own packaging/cleanup step? — see
   playwright_check.py.
2. Does a from-scratch Windows CF_HTML clipboard writer round-trip
   correctly? (core/clipboard_utils.py in the main app only handles macOS
   today; pyperclip's Windows fallback writes plain text, which would paste
   raw "<p>" tags into Naver's editor.) — see clipboard_win.py.

Both checks run on startup, get written to results.txt next to wherever the
process's CWD is (CI sets this explicitly — see the workflow), and the
process force-exits with a code reflecting pass/fail. There is nobody to
click this window shut in CI, and a live Flet UI would otherwise hang the
build job forever.
"""
from __future__ import annotations

import os
import sys
import threading
import time
from pathlib import Path

import flet as ft

import playwright_check

RESULTS_PATH = Path.cwd() / "results.txt"


def run_checks() -> list[str]:
    lines: list[str] = []

    if sys.platform == "win32":
        import clipboard_win

        ok, msg = clipboard_win.self_test()
        lines.append(f"[clipboard] {'PASS' if ok else 'FAIL'}: {msg}")
    else:
        lines.append("[clipboard] SKIPPED (not Windows)")

    ok, msg = playwright_check.self_test()
    lines.append(f"[playwright] {'PASS' if ok else 'FAIL'}: {msg}")

    return lines


def main(page: ft.Page) -> None:
    page.title = "OSMU Flet Spike"
    results = run_checks()
    RESULTS_PATH.write_text("\n".join(results), encoding="utf-8")

    page.add(ft.Text("\n".join(results), selectable=True))
    page.update()

    failed = any("FAIL" in line for line in results)

    def _force_exit() -> None:
        time.sleep(1.5)  # let the UI paint and results.txt flush before exiting
        os._exit(1 if failed else 0)

    threading.Thread(target=_force_exit, daemon=True).start()


if __name__ == "__main__":
    ft.run(main)
