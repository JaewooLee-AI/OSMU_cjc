"""쇼츠 / 릴스 (9:16) 시뮬레이터 — 데드존 확인용.

The failure this catches: the player's right-hand button cluster (like,
comment, share) and its bottom caption/profile bar cover roughly the outer
quarter of the frame. Any on-screen text or key subject that lands there is
invisible to the viewer even though it looks fine in the editing timeline.

The dead-zone overlay is drawn over the first attached photo as a stand-in
for the video, alongside the scene-by-scene script from
ai_workers/shorts_writer.py, so the caption for each cut can be checked
against the safe band before anything is shot.
"""
from __future__ import annotations

from simulators.base import all_images, document, esc, image_src

CSS = """
/* Stacked, not side-by-side: the workbench's simulator pane is roughly half
   the window (~600px), and a 340px phone next to a readable script panel
   doesn't fit — side-by-side clipped the script off the right edge. */
.sh-wrap { display: flex; flex-direction: column; align-items: center; gap: 16px; width: 100%; }
.sh-frame { width: 340px; height: 604px; position: relative;
    background: #0F0F0F; overflow: hidden; border-radius: 24px; flex-shrink: 0; }
.sh-bg { width: 100%; height: 100%; object-fit: cover; opacity: .92; }
.sh-bg-empty { width: 100%; height: 100%; display: flex; align-items: center;
    justify-content: center; color: #555; font-size: 13px;
    background: repeating-linear-gradient(45deg,#191919,#191919 12px,#1f1f1f 12px,#1f1f1f 24px); }
.sh-zone { position: absolute; background: rgba(239,68,68,.28);
    border: 1px solid rgba(239,68,68,.55); pointer-events: none; }
.sh-zone-right { right: 0; bottom: 96px; width: 68px; height: 280px; }
.sh-zone-bottom { left: 0; bottom: 0; width: 100%; height: 150px; }
.sh-zone-label { position: absolute; color: #fff; font-size: 10px; font-weight: 700;
    background: #DC2626; padding: 1px 6px; border-radius: 3px; }
.sh-safe { position: absolute; left: 16px; right: 84px; top: 84px; bottom: 158px;
    border: 1px dashed rgba(134,193,179,.9); border-radius: 6px; pointer-events: none; }
.sh-safe-label { position: absolute; top: -9px; left: 8px; font-size: 10px;
    color: #0F172A; background: #86C1B3; padding: 1px 6px; border-radius: 3px; font-weight: 700; }
.sh-hook { position: absolute; left: 24px; right: 92px; top: 120px; color: #fff;
    font-size: 21px; font-weight: 700; line-height: 1.3; text-align: center;
    text-shadow: 0 2px 8px rgba(0,0,0,.85); word-break: keep-all; }
.sh-bottom { position: absolute; bottom: 0; left: 0; width: 100%; padding: 16px 14px 24px;
    background: linear-gradient(to top, rgba(0,0,0,.9), transparent); }
.sh-channel { display: flex; align-items: center; gap: 8px; margin-bottom: 8px; }
.sh-avatar { width: 30px; height: 30px; border-radius: 50%; background: #fff; }
.sh-handle { color: #fff; font-size: 14px; font-weight: 700; }
.sh-sub { background: #fff; color: #000; font-size: 12px; font-weight: 700;
    padding: 4px 12px; border-radius: 999px; }
.sh-title { color: #fff; font-size: 14px; line-height: 1.35;
    display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
.sh-script { width: 100%; max-width: 420px; background: #fff; border: 1px solid #E2E8F0;
    border-radius: 12px; padding: 18px 20px; }
.sh-script h3 { font-size: 14px; color: #0F172A; margin-bottom: 4px; }
.sh-script .legend { font-size: 11px; color: #64748B; margin-bottom: 14px; }
.sh-cut { border-left: 3px solid #A6224B; padding: 8px 0 8px 12px; margin-bottom: 12px; }
.sh-cut-no { font-size: 11px; font-weight: 700; color: #A6224B; letter-spacing: .04em; }
.sh-cut-caption { font-size: 14px; font-weight: 700; color: #0F172A; margin: 3px 0; }
.sh-cut-shot { font-size: 12px; color: #64748B; line-height: 1.5; }
.sh-over { font-size: 11px; color: #B91C1C; margin-top: 2px; }
.sh-tags { margin-top: 8px; font-size: 12px; color: #2B4C8C; }
.sh-empty { color: #64748B; font-size: 13px; }
"""

CAPTION_SAFE_CHARS = 20  # matches the writer's per-cut limit


def render(campaign: dict, handle: str = "@cjc_coop", show_dead_zone: bool = True) -> str:
    script = campaign.get("shorts_script") or {}
    if isinstance(script, str):
        script = {}

    images = all_images(campaign.get("content") or "", campaign.get("storage_file_paths") or [])
    bg = (
        f'<img class="sh-bg" src="{image_src(images[0], 700)}" alt="">'
        if images
        else '<div class="sh-bg-empty">첨부 사진이 없어 배경을 미리 볼 수 없습니다</div>'
    )

    hook = (script.get("hook") or "").strip()
    title = (script.get("title") or campaign.get("title") or "").strip()
    scenes = script.get("scenes") or []
    hashtags = script.get("hashtags") or []

    zones = ""
    if show_dead_zone:
        zones = """
        <div class="sh-zone sh-zone-right"><span class="sh-zone-label"
            style="top:50%;left:-14px;transform:rotate(-90deg);">BUTTONS</span></div>
        <div class="sh-zone sh-zone-bottom"><span class="sh-zone-label"
            style="top:6px;left:12px;">TEXT & META</span></div>
        <div class="sh-safe"><span class="sh-safe-label">SAFE AREA</span></div>"""

    hook_html = f'<div class="sh-hook">{esc(hook)}</div>' if hook else ""

    if scenes:
        cuts = []
        for i, scene in enumerate(scenes, start=1):
            caption = (scene.get("caption") or "").strip()
            over = ""
            if len(caption) > CAPTION_SAFE_CHARS:
                over = (
                    f'<div class="sh-over">⚠️ 자막 {len(caption)}자 — '
                    f"{CAPTION_SAFE_CHARS}자를 넘으면 세로 화면에서 두 줄로 깨지거나 UI에 가립니다.</div>"
                )
            cuts.append(
                f"""<div class="sh-cut">
                    <div class="sh-cut-no">CUT {i}</div>
                    <div class="sh-cut-caption">{esc(caption) or '—'}</div>
                    <div class="sh-cut-shot">{esc(scene.get('shot') or '')}</div>
                    {over}
                </div>"""
            )
        tags = f'<div class="sh-tags">{esc(" ".join(hashtags))}</div>' if hashtags else ""
        script_html = (
            f'<h3>{esc(title) or "쇼츠 구성안"}</h3>'
            f'<div class="legend">자막은 위 SAFE AREA(초록 점선) 안에 들어가야 합니다.</div>'
            + "".join(cuts)
            + tags
        )
    else:
        script_html = '<div class="sh-empty">쇼츠 구성안이 아직 생성되지 않았습니다.</div>'

    body = f"""
    <div class="sh-wrap">
        <div class="sh-frame phone-frame">
            {bg}{zones}{hook_html}
            <div class="sh-bottom">
                <div class="sh-channel">
                    <div class="sh-avatar"></div>
                    <span class="sh-handle">{esc(handle)}</span>
                    <span class="sh-sub">구독</span>
                </div>
                <div class="sh-title">{esc(title)}</div>
            </div>
        </div>
        <div class="sh-script">{script_html}</div>
    </div>"""
    return document(body, CSS)


def height() -> int:
    # phone frame (604) + stacked script panel + gutters
    return 1080
