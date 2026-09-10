"""Does this post answer what its target keyword actually asks?

Naver's D.I.A.+ layer ranks on whether a document satisfies the *intent*
behind a query, not merely whether it contains the words. A post targeting
'결혼답례품' that is a well-written brand story still loses to a thinner post
that says what the thing costs, how many you can order and how long it takes
— because the second one is what the searcher came for, and the bounce back
to the results page is the signal Naver reads.

Everything upstream of this module optimises for *getting seen*: the sweep
finds winnable keywords, `seo_optimizer` places them in the title and body.
None of it asks whether the article deserves to hold the reader once they
arrive. This does.

This module only *reports*. An automatic fill pass was built and removed:
given the brand's core facts as its sole permitted source and told plainly
not to invent figures, it still produced "가격대는 1만~3만 원대의 핵심 라인,
5천~1만 원대의 엔트리 라인" — a price list that exists nowhere — and minted
`[IMAGE: assets/sample2.jpg]` tags for photos that were never uploaded.

That is not a fixable prompt. The gaps a search-intent audit finds are, by
their nature, facts the article does not contain — price, lead time, minimum
order — and a model asked to supply missing facts will supply them. The
brand's own tone rules forbid exactly this ("수치와 인증은 확인된 것만"),
which is why this codebase already runs a compliance guardrail.

So the missing items go to the marketer as a checklist. Only they know what
the price actually is.
"""
from __future__ import annotations

import json
import re
from typing import List

from ai_workers.multi_llm_router import generate_text

# Below this, the article is answering less than half of what its own keyword
# promises. Not a hard gate — a photo-led brand post can legitimately score
# low — but it is the threshold at which the fill pass is worth its call.
COVERAGE_TARGET = 70

AUDIT_SYSTEM_PROMPT = (
    "당신은 네이버 블로그 검색 품질 분석가입니다. 어떤 키워드를 노리는 블로그 글을 받아, "
    "그 키워드로 검색한 사람이 **기대하는 정보**를 이 글이 실제로 담고 있는지 점검합니다.\n\n"
    "절차:\n"
    "1. 그 키워드를 검색창에 친 사람이 무엇을 알고 싶어 하는지 4~6가지로 적으세요. "
    "가격대·수량·제작 기간·실물 사진·후기·주문 방법처럼 **구체적으로** 적어야 합니다. "
    "'브랜드 소개' 같은 막연한 항목은 쓰지 마세요.\n"
    "2. 각 항목이 글에 실제로 답이 있는지 covered로 표시하세요. "
    "스치듯 언급만 하고 답이 없으면 covered=false입니다.\n"
    "3. covered=false인 항목마다, 그 정보가 없으면 독자가 왜 이탈하는지 한 문장으로 쓰세요.\n\n"
    "반드시 아래 JSON만 출력하세요. 설명이나 코드펜스를 붙이지 마세요.\n"
    '{"expectations": [{"item": "...", "covered": true, "why": "미충족 시 이탈 이유 30자 이내"}]}'
)

def _parse(raw: str) -> dict:
    cleaned = re.sub(r"```json\s*|```\s*$", "", raw.strip())
    match = re.search(r"\{.*\}", cleaned, re.DOTALL)
    return json.loads(match.group(0)) if match else {}


def audit(title: str, content: str, keyword: str, vendor: str) -> dict:
    """What a searcher for `keyword` expects, and what this post is missing.

    Failure returns an empty audit rather than raising: a missing quality
    signal must not cost the marketer a draft that is otherwise finished.
    """
    prompt = f"[노리는 키워드]\n{keyword}\n\n[제목]\n{title}\n\n[본문]\n{content}"
    try:
        raw = generate_text(
            vendor=vendor, prompt=prompt, system=AUDIT_SYSTEM_PROMPT,
            max_tokens=1200, note="search-intent-audit",
        )
        expectations = _parse(raw).get("expectations", [])
    except Exception:
        return {"checked": False, "keyword": keyword, "expectations": [], "missing": [], "coverage": None}

    expectations = [e for e in expectations if isinstance(e, dict) and e.get("item")]
    missing = [e for e in expectations if not e.get("covered")]
    coverage = (
        round((len(expectations) - len(missing)) / len(expectations) * 100) if expectations else None
    )
    return {
        "checked": True,
        "keyword": keyword,
        "expectations": expectations,
        "missing": missing,
        "coverage": coverage,
    }


def run(title: str, content: str, target_keywords: List[str], vendor: str) -> dict:
    """Audit the post against its best keyword.

    Only the first target keyword is audited. The others are secondary by
    construction — `select_target_keywords` ranks by opportunity — and
    auditing all three would pull the article in three directions at once,
    which is the same over-optimization that keyword stuffing was.

    Returns a report only; the content is never modified here. See the module
    docstring for why writing the answers is the marketer's job.
    """
    if not target_keywords:
        return {"checked": False}
    return audit(title, content, target_keywords[0], vendor)
