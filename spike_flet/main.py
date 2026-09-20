"""Spike entry point.

Answers two questions before the real Flet migration starts:

1. Does a `flet build windows` executable still have a working Playwright
   (driver + browser) after Flet's own packaging/cleanup step? — see
   playwright_check.py.
2. Does a from-scratch Windows CF_HTML clipboard writer round-trip
   correctly? (core/clipboard_utils.py in the main app only handles macOS
   today; pyperclip's Windows fallback writes plain text, which would paste
   raw "<p>" tags into Naver's editor.) — see clipboard_win.py.

Checks run and get written to results.txt *before* `ft.run()` is ever
called, deliberately. Earlier iterations of this spike called `ft.run()`
first and the packaged exe died before a single line of this script ran
(no started.txt, no Windows Application-log crash entry — a clean,
near-instant exit(1)), even with `view=ft.AppView.FLET_APP_HIDDEN`. That
points at GitHub's windows-latest runner having no real display for Flet's
native window layer to initialize against — an artifact of headless CI, not
something an actual end-user's PC (which has a monitor) would ever hit. The
two questions this spike actually cares about don't need a window at all, so
this version never calls `ft.run()` — it just runs the checks, writes the
results, and exits. If you need to reintroduce a UI, do the checks first and
treat `ft.run()` as best-effort afterward (wrapped so a crash there can't
erase results.txt).
"""
from __future__ import annotations

import os
import sys
import traceback
from pathlib import Path

CWD = Path.cwd()
(CWD / "started.txt").write_text(f"process started, cwd={CWD}", encoding="utf-8")

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


if __name__ == "__main__":
    try:
        results = run_checks()
        RESULTS_PATH.write_text("\n".join(results), encoding="utf-8")
        failed = any("FAIL" in line for line in results)
    except Exception:  # noqa: BLE001 — a crash here must still leave a trace behind
        (CWD / "crash.txt").write_text(traceback.format_exc(), encoding="utf-8")
        failed = True

    os._exit(1 if failed else 0)
