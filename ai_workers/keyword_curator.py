"""Turns raw keyword metrics into a brand-specific SEO keyword proposal.

`keyword_research` answers two objective questions — how many people search
a term, how many posts already compete for it — and both are brand-agnostic.
What it cannot answer is whether *this* company has anything honest to say
about the term. Left to the numbers alone, a sweep seeded with '한복,
업사이클링, 리폼' returns `자갈` at rank 8 with a perfectly good score,
because Naver's related-keyword data is drawn from ad co-occurrence rather
than topical meaning. No threshold removes that; it needs a reader.

The brand kit already holds everything a reader would need (industry, core
facts, persona), so the judgment runs there: candidates plus brand kit go to
the configured model, which drops the irrelevant ones and files the rest by
search intent. The intent groups are fixed and deliberately generic — they
describe why someone typed the query, not what the company sells, so they
hold for the next tenant of this app without a code change.

Nothing here writes to the brand kit. `propose()` returns a proposal; the
settings screen renders it as a diff and the human applies it.
"""
from __future__ import annotations

import json
import re
from typing import Dict, List, Optional

from ai_workers import keyword_research
from ai_workers.multi_llm_router import generate_text, get_configured_vendor
from core import repo

# Ordered by how directly the traffic converts, which is also the order the
# proposal is rendered in. `exclude` is not a group — it's the absence of one.
INTENT_GROUPS = {
    "purchase": "구매 직결",
    "prospect": "잠재 고객",
    "division": "사업 부문",
    "identity": "브랜드 정체성",
}

# Above this, the results page belongs to established publishers and a new
# post will not surface no matter how well it is written. Applied after the
# model has judged relevance so that the exclusion reason stays specific:
# 'irrelevant' and 'unwinnable' call for different follow-up.
MAX_DOCS_PER_SEARCH = 100

# Naver masks any per-device count under ten, which `_parse_count` records as
# 5 — so a keyword nobody searches on either device lands at exactly 10, not
# 0. Anything at or below that floor is unmeasurable rather than small, and
# ranking first for it wins nothing.
MIN_VIABLE_VOLUME = 20

# Both thresholds above are waived for the identity group, which exists to
# hold exactly the keywords they reject: a brand's own vocabulary is low
# volume and often crowded, and dropping it means the company disappears
# from search for the thing it actually does. Applying the guards to this
# group would leave it permanently empty. The cap is what keeps the waiver
# from becoming a loophole the model can route everything through.
IDENTITY_LIMIT = 3

# Naver's C-Rank scores a blog on how consistently it covers one subject, so
# a pool spread across five unrelated categories suppresses every post in it
# no matter how well each one is written — the blog never reads as an
# authority on anything. Keeping the two heaviest topics is what turns a
# scattered list into a focused one; the model only labels the topics, and
# the arithmetic below decides which survive, because "which subject does
# this brand have the most demand in" is a sum, not a judgment.
TOPIC_LIMIT = 2

SYSTEM_PROMPT = (
    "당신은 네이버 블로그 SEO 전략가입니다. 브랜드 정보와 키워드 후보 목록을 받아, "
    "각 키워드가 이 브랜드에게 쓸모 있는지 판정하고 검색 의도와 주제로 분류합니다.\n\n"
    "판정 기준:\n"
    "- **검색한 사람이 원하는 것을 이 브랜드가 줄 수 있어야 합니다.** 예를 들어 대여 서비스를 "
    "찾는 검색어인데 브랜드가 대여업을 하지 않는다면, 소재나 업종이 비슷해 보여도 제외하세요. "
    "그 사람은 브랜드가 팔지 않는 것을 찾고 있으므로 유입되어도 아무 의미가 없습니다.\n"
    "- 이 브랜드가 그 키워드로 **정직하게** 글 한 편을 쓸 수 있어야 합니다. "
    "브랜드가 실제로 하지 않는 일에 대한 키워드는 검색량이 아무리 커도 제외하세요.\n"
    "- **검색 의도가 여러 갈래로 갈리는 광범위한 일반어는 제외하세요.** 예를 들어 어떤 분야의 "
    "이름 자체(업계 용어 한 단어)는 그 분야의 취업·뉴스·학습 정보를 찾는 사람이 대부분이라 "
    "브랜드 고객과 연결되지 않습니다.\n"
    "- 지금 당장 제품을 사려는 검색이 아니어도, 그 사람이 언젠가 이 브랜드의 고객이나 "
    "공급자가 될 수 있다면 'prospect'로 채택하세요.\n"
    "- 검색량이 적어도 브랜드가 무엇을 하는 회사인지 드러내는 말이면 'identity'로 남기세요.\n\n"
    "그룹(검색 의도):\n"
    "- purchase: 제품·서비스를 사려는 검색\n"
    "- prospect: 아직 구매 의사는 없지만 브랜드와 접점이 되는 검색\n"
    "- division: 본 제품과 별개인 사업 부문(교육·B2B 등)에 해당하는 검색\n"
    "- identity: 검색량은 적지만 브랜드 정체성상 지켜야 하는 말\n\n"
    "topic(주제): 그 키워드가 속한 **상품·서비스 카테고리**를 2~6글자로 붙이세요. "
    "같은 카테고리의 키워드에는 반드시 완전히 똑같은 문자열을 쓰세요 "
    "(예: '돌답례품'과 '결혼답례품'은 둘 다 '답례품'). "
    "검색 의도(group)가 아니라 무엇에 관한 검색인지로 묶어야 합니다.\n\n"
    "반드시 아래 JSON만 출력하세요. 설명이나 코드펜스를 붙이지 마세요.\n"
    '{"keywords": [{"keyword": "...", "group": "purchase|prospect|division|identity", '
    '"topic": "...", "reason": "채택 이유 25자 이내"}], '
    '"excluded": [{"keyword": "...", "reason": "제외 이유 25자 이내"}]}'
)


def _brand_context() -> str:
    kit = repo.get_brand_kit()
    facts = kit.get("core_facts") or []
    return (
        f"브랜드명: {kit.get('brand_name') or '-'}\n"
        f"서브브랜드: {kit.get('sub_brand') or '-'}\n"
        f"업종: {kit.get('industry') or '-'}\n"
        f"핵심 사실:\n" + "\n".join(f"- {f}" for f in facts[:15])
    )


def _cached_int(keyword: str, metric: str, max_age_days: int) -> Optional[int]:
    hit = repo.get_cached_metric(keyword, metric, max_age_days)
    return int(hit) if hit is not None else None


def _parse(raw: str) -> dict:
    cleaned = re.sub(r"```json\s*|```\s*$", "", raw.strip())
    match = re.search(r"\{.*\}", cleaned, re.DOTALL)
    return json.loads(match.group(0)) if match else {}


def propose(
    scored: List[dict], *, current: Optional[List[str]] = None, vendor: Optional[str] = None
) -> dict:
    """Group `keyword_research` output into an applyable proposal.

    `scored` is rank_keywords/score_candidates output (keyword, estimated_
    volume, documents, score). `current` is the brand kit's existing pool,
    which is judged alongside the candidates rather than preserved blindly —
    a keyword nobody searches has to be able to leave the list too.

    On a model or parse failure the whole thing is reported as unjudged
    rather than guessed at: silently proposing an unfiltered list is exactly
    the failure this module exists to prevent.
    """
    current = current or []
    by_keyword = {r["keyword"]: r for r in scored}
    for kw in current:
        if kw in by_keyword:
            continue
        # Incumbents have to face the same numbers as the candidates or they
        # survive on brand fit alone — which is how a pool of unsearched
        # terms perpetuates itself. Read from cache rather than calling out:
        # a prior 키워드 진단 has almost always measured these already, and a
        # curation step should never surprise the user with a metered request.
        by_keyword[kw] = {
            "keyword": kw,
            "estimated_volume": _cached_int(
                keyword_research.normalize(kw), "ad_volume", keyword_research.VOLUME_CACHE_DAYS
            ),
            "documents": _cached_int(kw, "blog_total", keyword_research.DOCUMENT_CACHE_DAYS) or 0,
            "score": 0,
        }

    metrics_lines = []
    for kw, row in by_keyword.items():
        volume = row.get("estimated_volume")
        docs = row.get("documents") or 0
        line = f"- {kw} | 월검색량 {volume if volume is not None else '미조회'} | 블로그문서 {docs:,}"
        if volume:
            line += f" | 문서/검색 {docs / volume:.0f}"
        metrics_lines.append(line)

    prompt = (
        f"{_brand_context()}\n\n"
        f"현재 SEO 키워드: {', '.join(current) if current else '(없음)'}\n\n"
        f"키워드 후보와 지표:\n" + "\n".join(metrics_lines)
    )

    try:
        raw = generate_text(
            vendor=vendor or get_configured_vendor(),
            prompt=prompt,
            system=SYSTEM_PROMPT,
            max_tokens=3000,
            note="keyword-curation",
        )
        parsed = _parse(raw)
    except Exception as exc:
        return {"error": str(exc), "groups": {}, "excluded": [], "current": current}

    groups: Dict[str, List[dict]] = {key: [] for key in INTENT_GROUPS}
    excluded: List[dict] = []

    for item in parsed.get("keywords", []):
        keyword = (item.get("keyword") or "").strip()
        row = by_keyword.get(keyword)
        if not keyword or row is None:
            continue  # the model invented a keyword that wasn't offered
        volume = row.get("estimated_volume") or 0
        docs = row.get("documents") or 0
        ratio = (docs / volume) if volume else None

        # Unrecognised group names fall to "prospect", not "identity" — the
        # latter waives the thresholds below, so a malformed response must
        # not be able to land there.
        group = item.get("group") if item.get("group") in INTENT_GROUPS else "prospect"

        # A relevance verdict doesn't override the arithmetic: the model has
        # no way to know that 370만 competing posts make a term unreachable.
        if group != "identity":
            if volume and volume <= MIN_VIABLE_VOLUME:
                excluded.append({**row, "reason": f"검색량 없음({volume}회 이하)"})
                continue
            if ratio is not None and ratio > MAX_DOCS_PER_SEARCH:
                excluded.append({**row, "reason": f"경쟁 과다(문서/검색 {ratio:.0f})"})
                continue

        groups[group].append(
            {
                **row,
                "reason": item.get("reason", ""),
                "ratio": ratio,
                "topic": (item.get("topic") or "기타").strip(),
            }
        )

    for item in parsed.get("excluded", []):
        keyword = (item.get("keyword") or "").strip()
        row = by_keyword.get(keyword)
        if row is not None:
            excluded.append({**row, "reason": item.get("reason") or "브랜드 무관"})

    # A keyword can be rejected twice — once by the numbers above, once by
    # the model — and listing it twice makes the revive checkboxes collide.
    excluded = list({r["keyword"]: r for r in excluded}.values())

    # --- topic concentration (C-Rank) ---------------------------------------
    # Weight by search volume rather than keyword count: five niche terms in
    # one category shouldn't outrank two high-demand ones in another just by
    # being numerous. Identity is exempt — it is the brand's own vocabulary
    # and belongs in the pool whatever the dominant commercial topic is.
    weights: Dict[str, int] = {}
    for gkey, rows in groups.items():
        if gkey == "identity":
            continue
        for row in rows:
            weights[row["topic"]] = weights.get(row["topic"], 0) + (row.get("estimated_volume") or 0)

    focus = [t for t, _ in sorted(weights.items(), key=lambda kv: kv[1], reverse=True)[:TOPIC_LIMIT]]
    for gkey, rows in groups.items():
        if gkey == "identity":
            continue
        kept_rows = []
        for row in rows:
            if row["topic"] in focus:
                kept_rows.append(row)
            else:
                excluded.append(
                    {**row, "reason": f"주제 분산 — '{'·'.join(focus)}'에 집중"}
                )
        groups[gkey] = kept_rows

    for group in groups.values():
        group.sort(key=lambda r: r.get("score") or 0, reverse=True)

    # Identity is capped by volume rather than score, since score divides by
    # competition and these are the terms with no competition to speak of.
    if len(groups["identity"]) > IDENTITY_LIMIT:
        overflow = sorted(
            groups["identity"], key=lambda r: r.get("estimated_volume") or 0, reverse=True
        )
        groups["identity"] = overflow[:IDENTITY_LIMIT]
        excluded.extend(
            {**r, "reason": f"브랜드 정체성 키워드 {IDENTITY_LIMIT}개 초과"}
            for r in overflow[IDENTITY_LIMIT:]
        )

    accepted = [r["keyword"] for g in groups.values() for r in g]
    return {
        "groups": groups,
        "focus": focus,
        "excluded": excluded,
        "current": current,
        "accepted": accepted,
        "added": [k for k in accepted if k not in current],
        "removed": [k for k in current if k not in accepted],
        "kept": [k for k in accepted if k in current],
    }


SEED_SYSTEM_PROMPT = (
    "당신은 네이버 블로그 SEO 전략가입니다. 브랜드 정보를 읽고, 연관키워드 발굴에 쓸 "
    "**씨앗 키워드 5개**를 제안하세요.\n\n"
    "씨앗 키워드는 그 자체로 쓸 키워드가 아니라, **연관검색어를 최대한 많이 끌어오기 위한 "
    "그물**입니다. 넓을수록 좋습니다.\n\n"
    "절대 규칙:\n"
    "- **수식어를 붙이지 마세요.** '친환경', '업사이클링', '수제', '맞춤', '프리미엄', "
    "'소량' 같은 형용사가 붙는 순간 검색량이 거의 0이 되어 연관검색어가 나오지 않습니다. "
    "'친환경 답례품'이 아니라 그냥 **'답례품'** 이라고 쓰세요.\n"
    "- **브랜드명·자체 용어·업계 전문용어를 쓰지 마세요.** 같은 이유로 결과가 비어버립니다.\n"
    "- 누구나 아는 **순수한 카테고리 이름 한 단어**를 쓰세요. 2~5글자가 적당합니다.\n"
    "- 브랜드가 다루는 서로 다른 카테고리를 5개 고르세요. "
    "한 카테고리에 몰면 그 축의 연관어만 나옵니다.\n\n"
    "좋은 예시의 형태: '답례품', '기념품', '굿즈제작', '공예키트', '한복'\n"
    "나쁜 예시의 형태: '친환경 답례품', '한복 업사이클링', '기업 ESG 행사'\n\n"
    '반드시 아래 JSON만 출력하세요: {"seeds": ["...", "...", "...", "...", "..."]}'
)


def suggest_seeds(vendor: Optional[str] = None) -> List[str]:
    """Seed keywords for a sweep, derived from the brand kit.

    Defaulting the seed box to the brand's own SEO pool was a dead end: that
    pool is exactly what a sweep exists to replace, and a term with no search
    volume has no related keywords to discover, so the sweep returned the
    seeds back and nothing else. The brand kit's industry and core facts
    describe the business in ordinary words, which is what Naver can match.
    """
    try:
        raw = generate_text(
            vendor=vendor or get_configured_vendor(),
            prompt=_brand_context(),
            system=SEED_SYSTEM_PROMPT,
            max_tokens=500,
            note="keyword-seeds",
        )
        seeds = _parse(raw).get("seeds", [])
    except Exception:
        return []
    return [s.strip() for s in seeds if isinstance(s, str) and s.strip()][:5]


def apply(keywords: List[str]) -> None:
    """Write the approved list to the brand kit. Deliberately the only
    function here that mutates anything, and never called by `propose`."""
    repo.save_brand_kit(seo_keywords=[k for k in dict.fromkeys(keywords) if k.strip()])
