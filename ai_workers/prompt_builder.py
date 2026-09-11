"""Shared Brand Kit -> system prompt assembly.

In OSMU_admin this logic was copy-pasted three times (news_scraper,
instagram_caption_writer, x_thread_writer), each with its own slightly
different subset of Brand Kit fields. Here the per-field blocks live once and
each channel picks the ones that apply, because the differences between
channels are real and worth keeping explicit:

- Naver blog wants keyword-density SEO; Instagram and X actively don't
  (a keyword-repeating paragraph is exactly wrong for a caption or a tweet).
- Every channel wants persona, tone and the glossary, since those define the
  brand voice regardless of format.

Brand Kit data is injected *in full* every time rather than retrieved by
similarity search. For a glossary of 14 terms and a fact list of 15 lines
that is both cheaper and more reliable than embedding + pgvector lookup: the
whole corpus costs ~600 tokens, and a retrieval miss on "더봄봄" would silently
produce a draft that misspells the brand's own product names.
"""
from __future__ import annotations

from typing import List

from ai_workers import content_mode


def persona_block(brand_kit: dict) -> List[str]:
    parts = []
    if brand_kit.get("industry"):
        parts.append(f"[업종] {brand_kit['industry']}")
    if brand_kit.get("brand_name"):
        sub = brand_kit.get("sub_brand")
        label = f"{brand_kit['brand_name']}" + (f" (브랜드: {sub})" if sub else "")
        parts.append(f"[기업/브랜드] {label}")
    if brand_kit.get("persona"):
        parts.append(f"[브랜드 페르소나] {brand_kit['persona']}")
    if brand_kit.get("tone_and_manner"):
        parts.append(f"[톤앤매너 가이드]\n{brand_kit['tone_and_manner']}")
    return parts


def core_facts_block(brand_kit: dict, minimum: int = 2) -> List[str]:
    facts = brand_kit.get("core_facts") or []
    if not facts:
        return []
    joined = "\n".join(f"- {fact}" for fact in facts)
    return [
        "[회사 핵심 팩트 — 다루는 주제를 우리 회사의 제품/활동과 자연스럽게 연결할 수 있도록, "
        f"아래 목록 중 최소 {minimum}개 이상을 본문 흐름에 맞춰 인용하세요. "
        "목록에 없는 수치나 실적은 절대 지어내지 마세요]\n" + joined
    ]


def terminology_block(brand_kit: dict) -> List[str]:
    terminology = brand_kit.get("terminology") or {}
    if not terminology:
        return []
    glossary = "\n".join(f"- {term}: {desc}" for term, desc in terminology.items())
    return [
        "[회사 용어집 — 아래 용어가 등장할 경우 반드시 이 표기와 의미로 정확히 사용하세요]\n" + glossary
    ]


def few_shot_block(brand_kit: dict) -> List[str]:
    samples = brand_kit.get("few_shot_samples") or []
    if not samples:
        return []
    joined = "\n---\n".join(samples)
    return [
        "[우수 포스팅 참조 샘플 — 아래의 어조, 문단 호흡, 정보 배치 순서를 최대한 동일하게 "
        "모방하세요. 내용을 그대로 베끼지는 마세요]\n" + joined
    ]


def seo_block(brand_kit: dict, hint: str = content_mode.HINT_RELEVANCE) -> List[str]:
    """Keyword pressure on the draft, at the level the content mode asks for.

    This is the pipeline's single creative call, and it used to be told to
    "pick 2~3 keywords and place each 2~4 times". That quota, not the later
    density pass, is what made every post converge: the pool's centre of
    gravity is the gift keywords, so a post about a teacher-training course
    was steered into 답례품 copy before a single SEO stage had run. Measured
    over one batch, the memo's own subject occupied 0~31% of the finished
    text, and every post landed on exactly the enforced density floor.

    What downstream still needs from this call is *which keywords the topic
    genuinely touches* — `select_target_keywords` reads that off the draft.
    A model free to use a keyword once, or not at all, gives a far more
    honest signal than one filling a quota. Enforcement stays where it can
    be measured and undone: `seo_optimizer`.
    """
    keywords = brand_kit.get("seo_keywords") or []
    if not keywords or hint == content_mode.HINT_NONE:
        # '내용 우선' never shows the pool at all. Naming keywords and then
        # saying "only if they fit" still anchors the draft toward them; the
        # only way to fully remove that pull is to not mention them.
        return []

    if hint == content_mode.HINT_PLACEMENT:
        return [
            "[네이버 블로그 SEO 지침] 이 글은 검색 노출을 우선 목표로 합니다. "
            "아래 키워드 후보 중 이 글의 주제에 맞는 2~3개를 골라, 제목과 본문에 걸쳐 "
            "각각 2~4회 자연스럽게 배치하세요. 다만 키워드를 넣으려고 글의 소재 자체를 "
            "바꾸지는 마세요 — 소재는 그대로 두고 표현을 키워드 쪽으로 맞추는 것입니다.\n"
            "키워드 후보: " + ", ".join(keywords)
        ]

    return [
        "[검색 키워드 참고] 이 글은 네이버 블로그 검색 노출도 고려합니다. 아래는 회사가 "
        "노리는 키워드 목록입니다. **이 글의 소재와 실제로 맞는 키워드가 있을 때만** "
        "본문에 자연스럽게 쓰고, 맞지 않으면 하나도 쓰지 마세요. 횟수를 채우려 하지 말고, "
        "글의 흐름이 그 단어를 필요로 하는 자리에만 쓰세요. 소재와 무관한 키워드를 끌어들이려고 "
        "글의 주제를 바꾸는 것은 절대 금지입니다.\n"
        "키워드 목록: " + ", ".join(keywords)
    ]


def length_block(length_hint: int | None) -> List[str]:
    """Asks for a longer piece when the mode has traded exposure for depth.

    Without it '내용 우선' produces the same ~800자 as the enforced modes —
    the keyword duty is gone but nothing tells the model to spend the freed
    space on the subject.
    """
    if not length_hint:
        return []
    return [
        f"[분량] 본문을 {length_hint}자 내외로 충분히 길게 쓰세요. 분량은 같은 말을 "
        "반복하거나 일반적인 브랜드 소개를 늘려서 채우는 것이 아니라, **소재 자체를 더 "
        "구체적으로** — 무엇을, 왜, 어떻게, 누구에게 — 풀어 써서 채웁니다. 제공된 자료에 "
        "없는 사실을 지어내서 분량을 늘리는 것은 금지입니다."
    ]


def notice_block(notice_fields: dict | None) -> List[str]:
    """The announcement's own facts, when the marketer supplied them.

    Placed with the source memo rather than in the system prompt: these are
    this post's subject, not standing brand configuration.

    The prohibition is the same one core_facts already carries, aimed at the
    other half of the post. A model asked to write a 모집 공고 with no fee in
    front of it will supply a plausible one — and a 수강료 invented by an LLM
    is a number the company then has to honour or retract. The same pull
    applies to shape, not just numbers: given a 추석 연휴 안내 carrying only a
    date, a model that has seen a thousand 모집 공고 will happily add a 신청
    방법 nobody asked for, so the absent fields are named and refused
    explicitly rather than just left out.
    """
    from ai_workers import notice

    present = notice.clean(notice_fields)
    if not present:
        return []

    lines = "\n".join(f"- {notice.LABELS[key]}: {value}" for key, value in present.items())
    absent = [label for key, label in notice.LABELS.items() if key not in present]

    block = (
        "[공지 정보 — 이 글은 공지 글입니다]\n"
        f"{lines}\n\n"
        "위 항목은 독자가 이 글을 읽는 이유입니다. **하나도 빠뜨리지 말고, 숫자와 "
        "날짜를 바꾸지 말고** 본문에 그대로 담으세요. 분위기 묘사로 시작하더라도 "
        "이 사실들이 본문 안에 분명히 자리 잡아야 합니다."
    )
    if absent:
        block += (
            "\n\n위에 적히지 않은 항목(" + ", ".join(absent) + ")은 이 공지에 "
            "해당하지 않거나 아직 정해지지 않은 것입니다. **절대 지어내지 마세요.** "
            "그럴듯한 날짜·금액·정원을 만들어 넣는 것은 회사가 지키지 못할 약속을 "
            "발행하는 것과 같습니다. 해당 없는 항목은 아예 언급하지 마세요 — "
            "연휴 안내에 신청 방법을, 휴무 안내에 정원을 끼워 넣지 마세요. "
            "독자가 더 알아야 할 것이 있으면 '자세한 내용은 문의해 주세요' 정도로만 "
            "넘기세요."
        )
    return [block]


SUBJECT_INSTRUCTION = (
    "**이 소재가 글의 중심입니다.** 독자가 이 글에서 가장 먼저, 가장 많이 알게 되어야 하는 "
    "것은 위 소재의 구체적인 내용입니다. 회사 소개·브랜드 철학·제품 라인업·환경 가치는 "
    "이 소재를 설명하는 데 필요한 만큼만 곁들이세요. 소재를 한두 문장으로 스치고 일반적인 "
    "브랜드 소개로 넘어가는 글은 실패한 글입니다. 소재가 교육·강의라면 교육 이야기를, "
    "행사라면 행사 이야기를 하세요 — 제품 판매 글로 바꾸지 마세요."
)


def brand_voice_blocks(brand_kit: dict) -> List[str]:
    """persona + tone + glossary — the subset every channel shares."""
    return persona_block(brand_kit) + terminology_block(brand_kit)


BLOG_SYSTEM_PROMPT_BASE = (
    "당신은 네이버 블로그 독자를 겨냥한 마케팅 카피라이터입니다. 제공된 자료를 바탕으로 "
    "첫 문단에서 독자를 붙잡는 정보성 블로그 포스트 본문을 한국어로 작성하세요. "
    "과장되거나 근거 없는 주장은 절대 쓰지 마세요. 제공된 자료에 없는 수치·인증·수상 이력을 "
    "지어내지 마세요. 마크다운 제목 기호(#)는 쓰지 말고, 문단으로만 구성하세요."
)


def build_blog_system_prompt(brand_kit: dict, mode: dict | None = None) -> str:
    """Full Naver-blog system prompt: base + persona + facts + few-shot +
    glossary + (mode-dependent) keyword pressure and length target."""
    profile = mode or content_mode.resolve(None, brand_kit)
    parts = [BLOG_SYSTEM_PROMPT_BASE]
    parts += persona_block(brand_kit)
    parts += core_facts_block(brand_kit)
    parts += few_shot_block(brand_kit)
    parts += terminology_block(brand_kit)
    parts += seo_block(brand_kit, profile.get("hint", content_mode.HINT_RELEVANCE))
    parts += length_block(profile.get("length_hint"))
    return "\n\n".join(parts)


def photo_instruction(captions: dict) -> str:
    """The `[IMAGE:]` placement instruction, shared by every pipeline.

    The worked example uses a real path from *this* call's attachment list
    rather than an abstract placeholder: models were observed echoing a
    `<경로>`-style metavariable back literally, producing `[IMAGE: 경로]` in
    the draft instead of substituting the actual path.
    """
    if not captions:
        return "첨부된 사진이 없으므로 `[IMAGE:]` 태그를 삽입하지 마세요."

    example_path = next(iter(captions))
    return (
        f"**중요: 위 목록의 사진 {len(captions)}장을 전부 빠짐없이 사용해야 합니다.** "
        "각 사진의 설명을 읽고, 그 내용과 가장 잘 맞는 본문 위치에 `[IMAGE: 경로]` 형식의 "
        "태그를 한 줄로 삽입하세요. '경로' 자리에는 위 목록에 적힌 실제 경로 문자열을 그대로 "
        "옮겨 적어야 하며, '경로'라는 글자 자체를 쓰면 절대 안 됩니다. 예를 들어 첫 번째 사진의 "
        f"경로가 정확히 {example_path} 이므로, 그 사진을 쓸 자리에는 반드시 "
        f"[IMAGE: {example_path}] 라고 그대로 적어야 합니다. 경로를 요약하거나 다른 글자로 "
        "바꾸지 마세요. 본문이 짧다면 문단을 늘려서라도 모든 사진이 들어갈 자리를 만드세요."
    )


def photo_context(captions: dict) -> str:
    if not captions:
        return "(첨부된 사진 없음)"
    return "\n".join(f"- [IMAGE: {path}] 설명: {caption}" for path, caption in captions.items())
