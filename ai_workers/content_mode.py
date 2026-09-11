"""How hard this post chases search exposure, at the cost of how much room
the subject gets.

The two are genuinely in tension, and three rounds of testing measured the
shape of it. Under full SEO enforcement the memo's own subject occupied 19%
of the finished text on average and one post about a teacher-training course
contained the word "교육" zero times; with enforcement relaxed the same five
memos and the same photos produced 51%, and that course post became 85% about
the course. The exposure side is real too: keyword-in-title placement and
body density are what Naver actually ranks on, and a post that mentions its
keyword once is not competing for it.

There is no correct global answer, because it depends on the post. A product
launch aimed at buyers searching '돌잔치답례품' wants the keyword machinery.
A festival announcement or a course opening is read by people who already
follow the brand, and grinding keywords into it costs the subject and buys
a ranking nobody will convert from.

So it is a per-post choice with a brand-level default, and every knob that
creates the tension is bound to it in one place rather than scattered across
prompt_builder, seo_optimizer and content_writer as fixed constants.
"""
from __future__ import annotations

from typing import Dict

# Draft-prompt keyword pressure, weakest to strongest.
#   none      — the system prompt never mentions the keyword pool
#   relevance — the pool is shown; use only what genuinely fits, no quota
#   placement — pick 2~3 and place each 2~4 times (the original instruction)
HINT_NONE = "none"
HINT_RELEVANCE = "relevance"
HINT_PLACEMENT = "placement"

DEFAULT_MODE = "balanced"

MODES: Dict[str, dict] = {
    "rich": {
        "label": "내용 우선",
        "icon": "📖",
        # The caption used to promise "키워드를 넣지 않으므로 검색 노출은 포기합니다".
        # The draft prompt genuinely never shows the pool, but the brand name
        # is itself a keyword and recurs naturally: measured over five posts
        # this mode still landed 더봄봄 three to five times. Nothing is being
        # inserted — the claim was just wrong, and a marketer who reads it and
        # then sees the keyword in the report has been told the wrong thing.
        "caption": "소재를 깊게 풀어 씁니다. 키워드를 맞추려는 교정을 하지 않아 검색 노출은 기대하지 않습니다.",
        "hint": HINT_NONE,
        # Targets are still *measured* and reported — the marketer should be
        # able to see which keywords the post happened to land on — but
        # nothing is rewritten to hit them.
        "max_targets": 2,
        "min_mentions": 2,
        "enforce_density": False,
        "rewrite_title": False,
        # Freed from keyword duty, the draft has room to actually develop the
        # subject; without a target it tends to stop at the same ~800자 as the
        # enforced modes and the extra room goes unused.
        "length_hint": 1500,
    },
    "balanced": {
        # '(기본)'을 라벨에 박아두지 않습니다. 기본 모드는 브랜드 킷에서 바꿀 수
        # 있는 값이라, 라벨에 고정하면 대표가 기본값을 노출 우선으로 바꾼 뒤에도
        # 균형이 계속 '(기본)'이라고 주장하게 됩니다. 표시는 화면에서 붙입니다.
        "label": "균형",
        "icon": "⚖️",
        "caption": "소재를 중심에 두되, 주제와 맞는 키워드는 자연스럽게 살립니다.",
        "hint": HINT_RELEVANCE,
        "max_targets": 3,
        "min_mentions": 2,
        "enforce_density": True,
        "density_min": 2,
        "density_max": 6,
        "rewrite_title": True,
        "length_hint": None,
    },
    "seo": {
        "label": "노출 우선",
        "icon": "🔍",
        "caption": "키워드를 제목 앞쪽과 본문에 확실히 배치합니다. 소재 설명은 그만큼 줄어듭니다.",
        "hint": HINT_PLACEMENT,
        "max_targets": 3,
        # Was 1, on the theory that a marketer who asked for the keyword
        # machinery wants a brushed-past keyword amplified rather than
        # dropped. The first batch run with modes showed what that actually
        # buys: a single passing mention of 결혼답례품 in a DDP festival post
        # promoted it to a target and then inflated it to a density of 4. One
        # mention is not evidence the post is about the keyword — it is the
        # noise floor of a brand that sells gifts. Two is the same bar every
        # other mode uses, and the exposure this mode adds comes from
        # placement and density, not from a lower bar for what counts.
        "min_mentions": 2,
        "enforce_density": True,
        "density_min": 3,
        "density_max": 6,
        "rewrite_title": True,
        "length_hint": None,
    },
}

ORDER = ["rich", "balanced", "seo"]


def resolve(mode: str | None, brand_kit: dict | None = None) -> dict:
    """Mode profile for a campaign, falling back to the brand default.

    Always returns a valid profile: an unknown or missing value must not fail
    a generation run, and the balanced profile is the behaviour every caller
    had before modes existed.
    """
    candidate = (mode or "").strip()
    if candidate not in MODES:
        candidate = ((brand_kit or {}).get("default_content_mode") or "").strip()
    if candidate not in MODES:
        candidate = DEFAULT_MODE
    return {"key": candidate, **MODES[candidate]}


def label_of(mode: str | None) -> str:
    profile = resolve(mode)
    return f"{profile['icon']} {profile['label']}"
