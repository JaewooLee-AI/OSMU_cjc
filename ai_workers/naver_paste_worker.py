"""Subprocess entrypoint spawned by ai_workers.naver_publisher.trigger_naver_publish.
Run as: python -m ai_workers.naver_paste_worker <campaign_id>

DOM automation against Naver's Smart Editor ONE, adapted from
the prior cjc_blog_v2 project's paste_worker.py's draft-popup and strikethrough cleanup quirks.
Image placement, however, is NOT ported from cjc: that project pastes the whole HTML
body at once with visible `[PHOTO_LOCATION_MARKER_N]` text markers and then
searches the rendered DOM for each marker to know where to insert a photo.
That approach was tried here twice (matching its marker text, TreeWalker
logic, and popup selectors byte-for-byte) and still failed against this
account's live editor — the marker text could not be reliably found after
paste. Instead, this worker inserts content *sequentially*, one segment at a
time, in document order: paste a text paragraph, then upload the next photo,
then paste the next paragraph, and so on. Each insertion lands wherever the
editor's own cursor already is (exactly like a human typing/uploading in
order), so there is no DOM search step to fail.

This is a *human-in-the-loop* finish line, not full automation: once the
title/body/images are pasted in, the browser is left open for the admin to
review and click Naver's own [발행] button themselves. Never run this
headless — Naver's anti-bot detection and the final publish click both
assume a real person is at the keyboard.
"""
from __future__ import annotations

import html
import sys
import time
import traceback
from pathlib import Path
from tempfile import TemporaryDirectory

# 이 워커는 detached subprocess로 별도 실행된다(naver_publisher.trigger_naver_publish가
# `sys.executable -m ai_workers.naver_paste_worker`로 띄움) — flet_app/main.py의
# stdout 재설정은 그 GUI 프로세스에만 적용되고 이 프로세스는 물려받지 않는다.
# Windows 콘솔의 기본 코드페이지(한국어 환경은 cp949)가 이모지·em dash 같은 문자를
# 못 찍으면 아래 곳곳의 print()가 UnicodeEncodeError로 죽는데, 그게 하필
# `repo.update_campaign(status="published")` 바로 다음 줄(예: "완료 — ...")에서
# 나면 방금 성공한 게시가 그 자리에서 실패로 덮어써지고 브라우저도 조기에 닫혀버린다
# — 실제로 재현됨. 콘솔 로그 한 줄 때문에 성공한 게시가 실패로 둔갑하는 일이 없도록
# 다른 곳에서 이미 쓴 것과 같은 방식으로 프로세스 시작 시점에 한 번 막아둔다.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

from ai_workers.naver_publisher import NAVER_STATE_FILE, format_publish_error, launch_browser
from ai_workers.photo_placement import split_segments
from core import repo, storage
from core.clipboard_utils import copy_html_to_clipboard

_HUMAN_DELAY = (0.15, 0.35)


def _human_delay(lo: float = _HUMAN_DELAY[0], hi: float = _HUMAN_DELAY[1]) -> None:
    import random

    time.sleep(random.uniform(lo, hi))


def _text_segment_to_html(text: str) -> str:
    """Wraps each line in a <p> for the rich-HTML clipboard paste.

    Escapes first: the body is Korean marketing prose, but an unescaped "&" or
    "<" (a stray "<브랜드>" or "A&B") would be parsed as markup by Naver's
    editor and silently swallow the surrounding text.
    """
    paragraphs = [p.strip() for p in text.split("\n") if p.strip()]
    return "".join(f"<p>{html.escape(p)}</p>" for p in paragraphs)


def _stage_images(rel_paths: list, dest_dir: Path) -> list:
    """Copies attached photos into a temp dir so Playwright's file chooser has
    real paths to hand Naver. (In OSMU_admin this downloaded each file from
    Supabase Storage; with local storage it's a straight read, and the copy
    exists only because the upload dialog wants a stable path.)"""
    local_paths = []
    for i, rel_path in enumerate(rel_paths):
        try:
            data = storage.read_bytes(rel_path)
            local_path = dest_dir / f"photo_{i}{Path(rel_path).suffix or '.jpg'}"
            local_path.write_bytes(data)
            local_paths.append(local_path)
        except Exception as exc:  # noqa: BLE001
            print(f"[naver_paste_worker] failed to stage {rel_path}: {exc}")
            local_paths.append(None)  # keep index alignment with markers
    return local_paths


def _find_editor_frame(page):
    try:
        frame = page.frame(name="mainFrame")
        if not frame:
            page.wait_for_selector("#mainFrame", timeout=4000)
            frame = page.frame(name="mainFrame")
        return frame or page
    except Exception:
        return page


_CANCEL_SELECTORS = [
    ".se-popup-button-cancel",
    "button.se-popup-button-cancel",
    ".se-popup-button.se-popup-button-cancel",
    ".se-help-panel-close-button",
    "button:has-text('취소')",
    "button:has-text('아니오')",
    ".se-popup-container button:nth-child(1)",
]


def _popup_still_visible(page, editor_frame) -> bool:
    """True if a button matching our own dismiss list is still visible.

    Deliberately reuses the same narrow, Naver-specific selectors we click
    with, rather than a broader "any dialog-role element" check — an earlier
    version of this checked generic containers like
    [role='dialog']/.se-help-panel, which can legitimately be present as
    ordinary Smart Editor chrome unrelated to the resume-draft popup (a
    notice banner, a help panel) and would make every publish fail with a
    false "there's a popup" reading. Used both as a fast-path skip (nothing
    to do at all) and, after retrying, to tell "nothing was ever showing"
    apart from "something was showing and we failed to close it".
    """
    for context in (page, editor_frame):
        for sel in _CANCEL_SELECTORS:
            try:
                el = context.query_selector(sel)
                if el and el.is_visible():
                    return True
            except Exception:
                pass
    return False


def _dismiss_draft_restore_popup(page, editor_frame) -> None:
    """The '이어서 작성하시겠습니까?' resume-draft dialog isn't guaranteed to
    render inside #mainFrame — Naver has moved editor chrome between the top
    page and the iframe across redesigns before. Check both contexts each
    pass rather than assuming one.

    Raises if a popup is still visible after every attempt, instead of
    silently moving on — clicking into the title/body fields "under" a still
    -open modal doesn't raise on its own (force=True skips Playwright's
    actionability/obscured checks), it just quietly lands on the modal
    instead of the editor, so the marketer used to get a blank or garbled
    post with no explanation. Now that produces a clear publish_error
    instead. The upfront visibility check skips the whole routine (no
    Escape presses, no clicks) on the common case where no popup ever
    appeared, instead of always burning through retries first.
    """
    if not _popup_still_visible(page, editor_frame):
        return

    for attempt in range(20):
        for context in (page, editor_frame):
            for sel in _CANCEL_SELECTORS:
                try:
                    btn = context.query_selector(sel)
                    if btn and btn.is_visible():
                        btn.click(force=True)
                        print(f"[naver_paste_worker] dismissed draft-restore popup via '{sel}' (attempt {attempt + 1})")
                        _human_delay(1.0, 1.5)
                except Exception:
                    pass
        if not _popup_still_visible(page, editor_frame):
            return
        # 버튼 셀렉터가 이번에도 하나도 안 맞았을 수 있으니, 많은 웹 모달이
        # 반응하는 Escape도 매 시도마다 같이 눌러본다.
        try:
            page.keyboard.press("Escape")
        except Exception:
            pass
        time.sleep(0.5)

    if _popup_still_visible(page, editor_frame):
        # 이 시점엔 with sync_playwright()의 finally에서 브라우저가 곧 닫히므로
        # "지금 열린 Chrome 창에서 닫아달라"고 안내하면 이미 창이 없어진 뒤라
        # 앞뒤가 안 맞는다 — 다시 시도해보라는 안내로 대신한다.
        raise RuntimeError(
            "네이버가 '이어서 작성하시겠습니까?' 같은 팝업을 띄웠는데 자동으로 닫지 못했습니다. "
            "[다시 게시]로 한 번 더 시도해주세요. 계속 실패하면 네이버 블로그에 직접 로그인해 "
            "임시저장된 글이 있는지 확인해주세요."
        )
    print("[naver_paste_worker] draft-restore popup dismiss: no popup found after 20 attempts (fine if none was showing)")


def _strip_strikethrough(editor_frame) -> None:
    """Naver's editor sometimes auto-applies strikethrough on paste — force it off."""
    try:
        editor_frame.evaluate(
            """() => {
                const editor = document.querySelector('.se-main-container, .se-content, body');
                if (!editor) return;
                editor.querySelectorAll('s, del, strike, [style*="line-through"]').forEach((el) => {
                    el.style.textDecoration = 'none';
                    const parent = el.parentNode;
                    if (parent) {
                        while (el.firstChild) parent.insertBefore(el.firstChild, el);
                        parent.removeChild(el);
                    }
                });
            }"""
        )
    except Exception as exc:  # noqa: BLE001
        print(f"[naver_paste_worker] strikethrough cleanup note: {exc}")


def _upload_photo_at_cursor(page, editor_frame, file_path: Path) -> bool:
    photo_selectors = [
        "button.se-image-toolbar-button",
        "button.se-document-toolbar-image-button",
        "button[data-name='image']",
        ".se-toolbar-button-image",
    ]
    for sel in photo_selectors:
        try:
            btn = editor_frame.query_selector(sel)
            if btn and btn.is_visible():
                with page.expect_file_chooser(timeout=3000) as fc_info:
                    btn.click(force=True)
                fc_info.value.set_files([str(file_path)])
                _human_delay(1.5, 2.5)
                return True
        except Exception:
            continue

    try:
        file_inputs = editor_frame.query_selector_all('input[type="file"]')
        if file_inputs:
            file_inputs[0].set_input_files([str(file_path)])
            _human_delay(1.5, 2.5)
            return True
    except Exception as exc:  # noqa: BLE001
        print(f"[naver_paste_worker] direct file input upload failed: {exc}")
    return False


def run(campaign_id: str) -> None:
    from playwright.sync_api import sync_playwright

    campaign = repo.get_campaign(campaign_id)
    if not campaign:
        print(f"[naver_paste_worker] campaign {campaign_id} not found")
        return

    brand_kit = repo.get_brand_kit()
    blog_id = (brand_kit.get("naver_blog_id") or "").strip()
    if not blog_id:
        repo.update_campaign(campaign_id, publish_error="네이버 블로그 아이디가 없습니다. [브랜드 킷] 페이지에서 먼저 등록해주세요.")
        return

    title = (campaign.get("title") or "").strip() or "(제목 없음)"
    content = campaign.get("content") or ""
    segments = split_segments(content)
    image_tags = [value for kind, value in segments if kind == "image"]

    with TemporaryDirectory() as tmp_dir_str:
        tmp_dir = Path(tmp_dir_str)
        local_images = _stage_images(image_tags, tmp_dir) if image_tags else []
        local_by_tag = dict(zip(image_tags, local_images))

        state_option = {"storage_state": str(NAVER_STATE_FILE)} if NAVER_STATE_FILE.exists() else {}
        target_url = f"https://blog.naver.com/{blog_id}?Redirect=Write"

        browser = None
        try:
            with sync_playwright() as p:
                browser = launch_browser(p, headless=False)
                context = browser.new_context(viewport={"width": 1280, "height": 900}, **state_option)
                page = context.new_page()
                page.on("dialog", lambda dialog: dialog.accept())

                page.goto(target_url, wait_until="domcontentloaded")
                _human_delay(1.0, 1.5)

                if "nidlogin" in page.url:
                    repo.update_campaign(
                        campaign_id,
                        publish_error="네이버 로그인이 풀렸습니다. [네이버 게시] 페이지에서 다시 로그인한 뒤 게시해주세요.",
                    )
                    browser.close()
                    return

                editor_frame = _find_editor_frame(page)
                _dismiss_draft_restore_popup(page, editor_frame)

                modifier = "Meta" if sys.platform == "darwin" else "Control"

                # --- Title ---
                title_selectors = [
                    ".se-component-title .se-text-paragraph",
                    ".se-document-title .se-text-paragraph",
                    ".se-title-text",
                    "div.se-component-title p",
                ]
                title_el = None
                for sel in title_selectors:
                    el = editor_frame.query_selector(sel)
                    if el and el.is_visible():
                        title_el = el
                        break
                if title_el:
                    title_el.click(force=True)
                    _human_delay(0.3, 0.5)
                    page.keyboard.press(f"{modifier}+a")
                    page.keyboard.press("Backspace")
                    page.keyboard.type(title, delay=15)
                    _human_delay(0.4, 0.6)

                # --- Body: clear, then insert text/image segments in order ---
                body_el = editor_frame.query_selector(".se-main-container, .se-component-text, .se-content")
                if body_el:
                    body_el.click(force=True)
                    _human_delay(0.5, 0.8)
                    page.keyboard.press(f"{modifier}+a")
                    page.keyboard.press("Delete")
                    _human_delay(0.5, 0.8)

                for kind, value in segments:
                    if kind == "text":
                        segment_html = _text_segment_to_html(value)
                        if not segment_html:
                            continue
                        copy_html_to_clipboard(segment_html)
                        page.keyboard.press(f"{modifier}+v")
                        # Naver's editor is still re-parsing the pasted HTML into
                        # its own component structure for a moment after paste —
                        # give it time to settle before the next action (paste or
                        # upload) touches the same area, instead of racing it.
                        _human_delay(1.5, 2.0)
                        _strip_strikethrough(editor_frame)
                    else:
                        local_path = local_by_tag.get(value)
                        if local_path is None:
                            print(f"[naver_paste_worker] no local file for image '{value}' — skipping")
                            continue
                        uploaded = _upload_photo_at_cursor(page, editor_frame, local_path)
                        if not uploaded:
                            print(f"[naver_paste_worker] photo upload failed for '{value}'")
                        _human_delay(1.5, 2.0)

                repo.update_campaign(campaign_id, status="published", publish_error=None)
                print("[naver_paste_worker] paste complete — waiting for admin to review and click 발행")

                # Keep the browser open so the admin can review/publish by hand.
                for _ in range(300):
                    try:
                        if page.is_closed() or len(context.pages) == 0:
                            break
                    except Exception:
                        break
                    time.sleep(1)
        except Exception as exc:  # noqa: BLE001
            traceback.print_exc()
            repo.update_campaign(campaign_id, publish_error=format_publish_error(exc))
        finally:
            try:
                if browser is not None:
                    browser.close()
            except Exception:
                pass


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python -m ai_workers.naver_paste_worker <campaign_id>")
        sys.exit(1)
    run(sys.argv[1])
