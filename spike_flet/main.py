"""Spike entry point.

Answers two questions before the real Flet migration starts:

1. Does a `flet build windows` executable still have a working Playwright
   (driver + browser) after Flet's own packaging/cleanup step? — see
   playwright_check.py.
2. Does a from-scratch Windows CF_HTML clipboard writer round-trip
   correctly? (core/clipboard_utils.py in the main app only handles macOS
   today; pyperclip's Windows fallback writes plain text, which would paste
   raw "<p>" tags into Naver's editor.) — see clipboard_win.py.

Both checks run on startup and get written to results.txt next to wherever
the process's CWD is (CI sets this explicitly — see the workflow). The
process force-exits with a code reflecting pass/fail, since there is nobody
to click this window shut in CI and a live Flet UI would otherwise hang the
build job forever.

started.txt is written *before* anything else — including before `import
flet` even finishes running its own module-level setup — so a run that never
produces results.txt can still be told apart from a run whose Python code
never started at all (e.g. the Flutter engine itself failing to boot).
"""
from __future__ import annotations

import os
import sys
import threading
import time
import traceback
from pathlib import Path

CWD = Path.cwd()
(CWD / "started.txt").write_text(f"process started, cwd={CWD}", encoding="utf-8")

import flet as ft  # noqa: E402 — started.txt must be written first, see above

import playwright_check  # noqa: E402

RESULTS_PATH = CWD / "results.txt"


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
    try:
        page.title = "OSMU Flet Spike"
        results = run_checks()
        RESULTS_PATH.write_text("\n".join(results), encoding="utf-8")
        failed = any("FAIL" in line for line in results)

        try:
            page.add(ft.Text("\n".join(results), selectable=True))
            page.update()
        except Exception:  # noqa: BLE001 — UI failing shouldn't hide results.txt
            (CWD / "ui_error.txt").write_text(traceback.format_exc(), encoding="utf-8")
    except Exception:  # noqa: BLE001 — a crash here must still leave a trace behind
        (CWD / "crash.txt").write_text(traceback.format_exc(), encoding="utf-8")
        failed = True

    def _force_exit() -> None:
        time.sleep(1.5)  # let the UI paint and files flush before exiting
        os._exit(1 if failed else 0)

    threading.Thread(target=_force_exit, daemon=True).start()


if __name__ == "__main__":
    ft.run(main)
