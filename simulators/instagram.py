"""인스타그램 피드 시뮬레이터.

The one thing this view exists to catch is the **125-character fold**: the
caption is truncated behind "... 더보기", so anything that has to land before
a reader decides to scroll past has to fit in those first 125 characters. The
cut line is drawn explicitly rather than just truncating, so the marketer can
see exactly which word falls off the edge.

Media is a 4:5 carousel (1080x1350), Instagram's tallest permitted feed
ratio and the one 키노피스's product shots should be framed for.
"""
from __future__ import annotations

from simulators.base import all_images, document, esc, image_src

TRUNCATE_LENGTH = 125
MAX_CAROUSEL = 10  # Instagram's own per-post limit

CSS = """
.ig-frame { width: 390px; height: 780px; background: #fff; display: flex; flex-direction: column; }
.ig-header { display: flex; align-items: center; justify-content: space-between;
    padding: 10px 12px; border-bottom: 1px solid #F1F1F1; flex-shrink: 0; }
.ig-avatar { width: 32px; height: 32px; border-radius: 50%;
    background: linear-gradient(45deg, #F9CE34, #EE2A7B, #6228D7); padding: 2px; }
.ig-avatar-inner { width: 100%; height: 100%; border-radius: 50%; background: #fff; }
.ig-username { font-size: 13px; font-weight: 600; color: #262626; }
.ig-carousel { position: relative; width: 100%; aspect-ratio: 4/5; background: #FAFAFA;
    display: flex; overflow-x: auto; scroll-snap-type: x mandatory; flex-shrink: 0; }
.ig-carousel::-webkit-scrollbar { display: none; }
.ig-carousel img { width: 390px; height: 100%; object-fit: cover;
    scroll-snap-align: center; flex-shrink: 0; }
.ig-dots { position: absolute; bottom: 12px; left: 0; width: 100%;
    display: flex; justify-content: center; gap: 4px; }
.ig-dot { width: 6px; height: 6px; border-radius: 50%; background: #fff; opacity: .7; }
.ig-dot.active { background: #0095F6; opacity: 1; }
.ig-actions { display: flex; justify-content: space-between; padding: 10px 12px 6px; }
.ig-actions svg { width: 24px; height: 24px; stroke: #262626; fill: none; stroke-width: 1.6; }
.ig-actions .row { display: flex; gap: 16px; }
.ig-caption { padding: 0 12px 16px; font-size: 13px; line-height: 1.45; color: #262626;
    word-break: break-word; white-space: pre-wrap; }
.ig-caption .name { font-weight: 600; margin-right: 5px; }
.ig-fold { display: block; border-top: 1px dashed #EE2A7B; margin: 6px 0;
    font-size: 10px; color: #EE2A7B; padding-top: 3px; letter-spacing: .02em; }
.ig-more { color: #8E8E8E; }
.ig-tags { color: #00376B; }
.ig-empty-media { width: 100%; aspect-ratio: 4/5; background: #FAFAFA;
    display: flex; align-items: center; justify-content: center;
    color: #B0B0B0; font-size: 13px; }
.ig-warn { margin: 8px 12px; font-size: 11px; color: #C05621;
    background: #FFFAF0; border: 1px solid #FBD38D; border-radius: 6px; padding: 6px 10px; }
"""

_HEART = '<svg viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M4.318 6.318a4.5 4.5 0 000 6.364L12 20.364l7.682-7.682a4.5 4.5 0 00-6.364-6.364L12 7.636l-1.318-1.318a4.5 4.5 0 00-6.364 0z"/></svg>'
_COMMENT = '<svg viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M21 12c0 4.418-4.03 8-9 8a9.86 9.86 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z"/></svg>'
_SHARE = '<svg viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M12 19l9 2-9-18-9 18 9-2zm0 0v-8"/></svg>'
_SAVE = '<svg viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M5 5a2 2 0 012-2h10a2 2 0 012 2v16l-7-3.5L5 21V5z"/></svg>'


def render(campaign: dict, username: str = "cjc_coop") -> str:
    caption = campaign.get("instagram_caption") or ""
    hashtags = campaign.get("instagram_hashtags") or []
    images = all_images(campaign.get("content") or "", campaign.get("storage_file_paths") or [])

    if images:
        slides = "".join(f'<img src="{image_src(p, 620)}" alt="">' for p in images[:MAX_CAROUSEL])
        dots = ""
        if len(images) > 1:
            dots = '<div class="ig-dots">' + "".join(
                f'<div class="ig-dot{" active" if i == 0 else ""}"></div>'
                for i in range(min(len(images), MAX_CAROUSEL))
            ) + "</div>"
        media = f'<section class="ig-carousel">{slides}{dots}</section>'
    else:
        media = '<div class="ig-empty-media">사진을 첨부하면 4:5 캐러셀로 미리 보입니다</div>'

    overflow_warning = ""
    if len(images) > MAX_CAROUSEL:
        overflow_warning = (
            f'<div class="ig-warn">사진 {len(images)}장 중 인스타그램은 '
            f"{MAX_CAROUSEL}장까지만 올릴 수 있습니다. 뒤의 {len(images) - MAX_CAROUSEL}장은 잘립니다.</div>"
        )

    # The fold is drawn where Instagram actually cuts, so the marketer sees
    # which word ends up behind "더보기" instead of guessing at a length.
    if len(caption) > TRUNCATE_LENGTH:
        head, tail = caption[:TRUNCATE_LENGTH], caption[TRUNCATE_LENGTH:]
        caption_html = (
            f"{esc(head)}<span class=\"ig-more\">... 더보기</span>"
            f'<span class="ig-fold">▲ 여기까지만 노출됩니다 (125자)</span>{esc(tail)}'
        )
    else:
        caption_html = esc(caption) or '<span style="color:#B0B0B0;">캡션이 아직 생성되지 않았습니다.</span>'

    tags_html = ""
    if hashtags:
        tags_html = '<div class="ig-tags" style="margin-top:8px;">' + esc(" ".join(hashtags)) + "</div>"

    body = f"""
    <div class="ig-frame phone-frame sim-scroll">
        <header class="ig-header">
            <div style="display:flex;align-items:center;gap:8px;">
                <div class="ig-avatar"><div class="ig-avatar-inner"></div></div>
                <span class="ig-username">{esc(username)}</span>
            </div>
            <span style="font-weight:700;letter-spacing:2px;color:#262626;">···</span>
        </header>
        {media}
        {overflow_warning}
        <div class="ig-actions">
            <div class="row">{_HEART}{_COMMENT}{_SHARE}</div>{_SAVE}
        </div>
        <div class="ig-caption"><span class="name">{esc(username)}</span>{caption_html}{tags_html}</div>
    </div>"""
    return document(body, CSS)


def height() -> int:
    return 830
