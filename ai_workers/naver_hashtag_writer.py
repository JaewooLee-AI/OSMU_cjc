"""Naver Blog hashtag generator.

Naver's [발행] popup tag field just wants a flat list of search keywords —
no caption, no character limit, no hook — which makes this the simplest of
the three hashtag writers (compare instagram_caption_writer.py, which needs
a hook+caption, and x_thread_writer.py, which needs a whole thread).

Used by the single unified pipeline (ai_workers/content_writer.py). The
발행 popup itself can't be driven by Playwright, so pages/05_naver_publish.py
just displays these for the marketer to copy/paste at publish time.
"""
from __future__ import annotations

import json
import re

from ai_workers.multi_llm_router import generate_text

HASHTAG_SYSTEM_PROMPT = (
    "당신은 네이버 블로그 SEO 전문가입니다. 아래 블로그 글의 제목과 본문을 분석해서, "
    "네이버 블로그 [발행] 팝업의 태그 입력란에 등록할 검색 노출용 해시태그를 7~12개 "
    "추천하세요. 브랜드명, 업종, 핵심 주제 키워드를 골고루 섞되, 실제 검색에 쓰일 법한 "
    "구체적인 단어를 우선하세요. 반드시 아래 JSON 형식으로만 응답하고 다른 설명은 "
    "포함하지 마세요:\n"
    '{"hashtags": ["#태그1", "#태그2", ...]}'
)


def write_naver_hashtags(title: str, content: str, brand_kit: dict, vendor: str) -> list[str]:
    """Returns a list of "#tag" strings. Best-effort — callers must not let a
    failure here fail the whole draft, since these are a copy/paste aid for
    the publish popup, not the post body itself."""
    seo_keywords = brand_kit.get("seo_keywords") or []
    keyword_hint = f"\n\n[SEO 타깃 키워드 - 참고용] {', '.join(seo_keywords)}" if seo_keywords else ""
    prompt = f"[제목]\n{title}\n\n[본문]\n{content[:3000]}{keyword_hint}"
    raw = generate_text(vendor=vendor, prompt=prompt, system=HASHTAG_SYSTEM_PROMPT, max_tokens=400, note="naver-hashtags")
    try:
        cleaned = re.sub(r"```json\s*|```\s*$", "", raw.strip())
        match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        parsed = json.loads(match.group(0)) if match else {}
        tags = parsed.get("hashtags") or []
        return [t if str(t).startswith("#") else f"#{t}" for t in tags]
    except Exception:
        return []
