"""네이버 블로그 (스마트에디터 ONE) 시뮬레이터.

Reproduces the two things about Naver's render that actually change editing
decisions: the wide 880px desktop content column collapsing to a 390px phone
frame, and the generous typography (16px / 1.8 line-height, Nanum Myeongjo
body) that makes a paragraph look much longer on screen than it does in the
editor textarea.

`[IMAGE:]` markers become inline figures at the exact spot the model chose;
attached-but-untagged photos are appended as a trailing gallery, which is
the same fallback OSMU_web's NaverBlogView used — visible, just not
author-placed.
"""
from __future__ import annotations

from typing import List

from simulators.base import all_images, content_blocks, document, esc, image_src

CSS = """
.naver-wrap { background: #fff; border: 1px solid #E2E8F0; }
.naver-pc { width: 880px; height: 1040px; }
.naver-mobile { width: 390px; height: 780px; }
.naver-article { padding: 40px 56px; color: #333; }
.naver-mobile .naver-article { padding: 28px 20px; }
.naver-title {
    font-size: 32px; font-weight: 700; line-height: 1.4; color: #222;
    border-bottom: 1px solid #F1F5F9; padding-bottom: 24px; margin-bottom: 28px;
    word-break: keep-all;
}
.naver-mobile .naver-title { font-size: 24px; padding-bottom: 18px; margin-bottom: 20px; }
.naver-meta { display: flex; align-items: center; gap: 12px; margin-bottom: 44px; }
.naver-avatar { width: 44px; height: 44px; border-radius: 50%;
    background: linear-gradient(135deg, #A6224B, #C9A227); flex-shrink: 0; }
.naver-meta-name { font-size: 15px; font-weight: 700; color: #222; }
.naver-meta-sub { font-size: 13px; color: #888; }
.naver-body p {
    font-family: 'Nanum Myeongjo', serif;
    font-size: 16px; line-height: 1.8; letter-spacing: -0.02em;
    color: #333; margin-bottom: 20px; word-break: keep-all;
}
.naver-figure { margin: 28px 0; }
.naver-figure img { width: 100%; height: auto; border-radius: 2px; }
.naver-figcaption { text-align: center; font-size: 13px; color: #aaa; margin-top: 8px; }
.naver-tags { margin-top: 40px; padding-top: 20px; border-top: 1px solid #F1F5F9; }
.naver-tag { display: inline-block; font-size: 13px; color: #2B4C8C;
    background: #F3F6FB; border-radius: 999px; padding: 4px 12px; margin: 0 6px 6px 0; }
.naver-gallery-note { font-size: 12px; color: #C05621; background: #FFFAF0;
    border: 1px solid #FBD38D; border-radius: 6px; padding: 8px 12px; margin: 24px 0 8px; }
"""


def render(campaign: dict, is_mobile: bool = False, blog_name: str = "더봄봄 공식 블로그") -> str:
    title = campaign.get("title") or "(제목 없음)"
    content = campaign.get("content") or ""
    attached = campaign.get("storage_file_paths") or []
    hashtags: List[str] = campaign.get("naver_hashtags") or []

    blocks = content_blocks(content)
    tagged = {value for kind, value in blocks if kind == "image"}
    untagged = [p for p in attached if p not in tagged]

    body_parts = []
    for kind, value in blocks:
        if kind == "text":
            body_parts.append(f"<p>{esc(value)}</p>")
        else:
            body_parts.append(
                f'<figure class="naver-figure"><img src="{image_src(value)}" alt="">'
                f'<figcaption class="naver-figcaption">사진 설명을 입력하세요.</figcaption></figure>'
            )

    if untagged:
        body_parts.append(
            f'<div class="naver-gallery-note">본문에 배치되지 않은 사진 {len(untagged)}장이 '
            "글 끝에 붙습니다. 위치를 지정하려면 본문에서 <code>[IMAGE: 경로]</code>를 옮기세요.</div>"
        )
        for path in untagged:
            body_parts.append(f'<figure class="naver-figure"><img src="{image_src(path)}" alt=""></figure>')

    tag_html = ""
    if hashtags:
        chips = "".join(f'<span class="naver-tag">{esc(t)}</span>' for t in hashtags)
        tag_html = f'<div class="naver-tags">{chips}</div>'

    frame_class = "naver-mobile phone-frame" if is_mobile else "naver-pc"
    body = f"""
    <div class="naver-wrap sim-scroll {frame_class}">
        <article class="naver-article">
            <h1 class="naver-title">{esc(title)}</h1>
            <div class="naver-meta">
                <div class="naver-avatar"></div>
                <div>
                    <div class="naver-meta-name">{esc(blog_name)}</div>
                    <div class="naver-meta-sub">방금 전 · 이웃추가</div>
                </div>
            </div>
            <div class="naver-body">{''.join(body_parts) or '<p>본문이 비어 있습니다.</p>'}</div>
            {tag_html}
        </article>
    </div>"""
    return document(body, CSS)


def height(is_mobile: bool = False) -> int:
    return 830 if is_mobile else 1090


def image_count(campaign: dict) -> int:
    return len(all_images(campaign.get("content") or "", campaign.get("storage_file_paths") or []))
