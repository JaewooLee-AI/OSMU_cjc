"""Verifies Playwright's driver + a browser can actually launch from inside a
`flet build`-produced executable.

Flet doesn't package with PyInstaller — it bundles a real CPython plus your
site-packages into the Flutter app shell (see flet.dev/docs/updates/…/
default-bundled-python-3-14). Playwright's own PyInstaller bundling recipe
(`PLAYWRIGHT_BROWSERS_PATH=0 playwright install chromium` before packaging)
is documented for PyInstaller specifically, not for Flet, so whether the
driver executable and the Chromium binary survive Flet's packaging/cleanup
step and are still reachable at runtime is exactly what this checks.
"""
from __future__ import annotations


def _launch(p):
    """Mirrors ai_workers/naver_publisher.py's launch_browser(): system Chrome
    first (what the real feature actually uses — GitHub's windows-latest
    runner ships Chrome preinstalled, so this exercises the real code path),
    falling back to Playwright's own bundled Chromium if that's unavailable."""
    try:
        return p.chromium.launch(headless=False, channel="chrome"), "channel=chrome"
    except Exception as exc:  # noqa: BLE001
        print(f"[playwright_check] channel=chrome failed, falling back to bundled chromium: {exc}")
    return p.chromium.launch(headless=False), "bundled chromium"


def self_test() -> tuple[bool, str]:
    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:  # noqa: BLE001
        return False, f"playwright import failed: {exc!r}"

    try:
        with sync_playwright() as p:
            browser, via = _launch(p)
            page = browser.new_page()
            page.set_content("<title>flet-playwright-spike</title>")
            title = page.title()
            browser.close()
        ok = title == "flet-playwright-spike"
        return ok, f"playwright launch {'OK' if ok else 'FAILED'} via {via} (title={title!r})"
    except Exception as exc:  # noqa: BLE001
        return False, f"playwright launch raised: {exc!r}"
