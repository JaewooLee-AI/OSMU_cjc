"""X (Twitter) 타래 시뮬레이터.

Two render behaviors worth seeing before posting:

1. **Thread splitting.** Any tweet over the character limit gets chopped, so
   the view splits it the way X would and shows the connector line, making an
   awkward mid-sentence break obvious.
2. **The media grid.** X lays 1–4 images out in four completely different
   geometries (full-width 16:9, side-by-side halves, one tall + two stacked,
   2x2) and silently drops anything past the 4th. Both facts are easy to miss
   in a text editor and impossible to miss here.
"""
from __future__ import annotations

from typing import List

from simulators.base import all_images, document, esc, image_src

TWEET_LIMIT = 140  # Korean-text working limit, matching ai_workers/x_thread_writer.py
MAX_MEDIA = 4

CSS = """
.x-frame { width: 600px; background: #fff; border-left: 1px solid #EFF3F4;
    border-right: 1px solid #EFF3F4; max-height: 900px; }
.x-tweet { display: flex; gap: 12px; padding: 12px 16px 4px; border-bottom: 1px solid #EFF3F4; }
.x-rail { display: flex; flex-direction: column; align-items: center; }
.x-avatar { width: 40px; height: 40px; border-radius: 50%; flex-shrink: 0;
    background: linear-gradient(135deg, #A6224B, #2B4C8C); }
.x-connector { width: 2px; flex: 1; background: #CFD9DE; margin-top: 4px; }
.x-main { flex: 1; min-width: 0; padding-bottom: 12px; }
.x-meta { display: flex; align-items: center; gap: 4px; margin-bottom: 2px;
    font-size: 15px; white-space: nowrap; }
.x-name { font-weight: 700; color: #0F1419; }
.x-handle, .x-time { color: #536471; }
.x-text { font-size: 15px; line-height: 1.35; color: #0F1419;
    white-space: pre-wrap; word-break: break-word; }
.x-media { margin-top: 12px; display: grid; gap: 2px; border-radius: 16px;
    overflow: hidden; border: 1px solid #CFD9DE; aspect-ratio: 16/9; }
.x-media img { width: 100%; height: 100%; object-fit: cover; }
.x-g1 { grid-template-columns: 1fr; }
.x-g2 { grid-template-columns: 1fr 1fr; }
.x-g3 { grid-template-columns: 1fr 1fr; grid-template-rows: 1fr 1fr; }
.x-g4 { grid-template-columns: 1fr 1fr; grid-template-rows: 1fr 1fr; }
.x-g3 .cell-0 { grid-row: span 2; }
.x-actions { display: flex; justify-content: space-between; max-width: 320px;
    margin-top: 12px; color: #536471; font-size: 13px; }
.x-tags { color: #1D9BF0; margin-top: 8px; font-size: 15px; }
.x-warn { margin: 10px 16px; font-size: 12px; color: #C05621;
    background: #FFFAF0; border: 1px solid #FBD38D; border-radius: 8px; padding: 8px 12px; }
.x-empty { padding: 40px 16px; text-align: center; color: #536471; font-size: 14px; }
"""


def _split_tweet(text: str) -> List[str]:
    """Chunks an over-length tweet the way X's composer would, preferring a
    sentence boundary so the break doesn't land mid-word."""
    text = (text or "").strip()
    if len(text) <= TWEET_LIMIT:
        return [text] if text else []

    chunks, remaining = [], text
    while len(remaining) > TWEET_LIMIT:
        window = remaining[:TWEET_LIMIT]
        cut = max(window.rfind("。"), window.rfind("."), window.rfind("!"), window.rfind("?"), window.rfind("\n"))
        if cut < TWEET_LIMIT // 2:
            cut = window.rfind(" ")
        if cut < TWEET_LIMIT // 2:
            cut = TWEET_LIMIT - 1
        chunks.append(remaining[:cut + 1].strip())
        remaining = remaining[cut + 1:].strip()
    if remaining:
        chunks.append(remaining)
    return chunks


def _media_grid(images: List[str]) -> str:
    count = min(len(images), MAX_MEDIA)
    if count == 0:
        return ""
    cells = "".join(
        f'<div class="cell-{i}"><img src="{image_src(p, 560)}" alt=""></div>'
        for i, p in enumerate(images[:MAX_MEDIA])
    )
    return f'<div class="x-media x-g{count}">{cells}</div>'


def render(campaign: dict, display_name: str = "키노피스", handle: str = "@cjc_coop") -> str:
    tweets: List[str] = campaign.get("x_content") or []
    hashtags = campaign.get("x_hashtags") or []
    images = all_images(campaign.get("content") or "", campaign.get("storage_file_paths") or [])

    chunks: List[str] = []
    for tweet in tweets:
        chunks.extend(_split_tweet(tweet))

    if not chunks:
        return document('<div class="x-frame x-empty">X 스레드가 아직 생성되지 않았습니다.</div>', CSS)

    if hashtags:
        chunks[-1] = chunks[-1] + "\n\n" + " ".join(hashtags)

    rows = []
    for idx, chunk in enumerate(chunks):
        connector = '<div class="x-connector"></div>' if idx != len(chunks) - 1 else ""
        media = _media_grid(images) if idx == 0 else ""
        rows.append(
            f"""<div class="x-tweet">
                <div class="x-rail"><div class="x-avatar"></div>{connector}</div>
                <div class="x-main">
                    <div class="x-meta">
                        <span class="x-name">{esc(display_name)}</span>
                        <span class="x-handle">{esc(handle)}</span>
                        <span class="x-time">· {idx * 1 + 1}분</span>
                    </div>
                    <div class="x-text">{esc(chunk)}</div>
                    {media}
                    <div class="x-actions"><span>💬 12</span><span>🔁 8</span><span>♡ 46</span><span>↥</span></div>
                </div>
            </div>"""
        )

    warning = ""
    if len(images) > MAX_MEDIA:
        warning = (
            f'<div class="x-warn">사진 {len(images)}장 중 X는 첫 {MAX_MEDIA}장만 첨부됩니다. '
            f"나머지 {len(images) - MAX_MEDIA}장은 표시되지 않습니다.</div>"
        )

    return document(f'<div class="x-frame sim-scroll">{warning}{"".join(rows)}</div>', CSS)


def height() -> int:
    return 860
