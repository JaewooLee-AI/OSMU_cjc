"""Korean spelling / spacing correction for text a human has edited.

`revise_content`'s system prompt tells the model to leave anything the
marketer didn't ask about untouched — which is right for tone and structure,
and exactly wrong for typos: a mistake typed into the editor is preserved
verbatim by that same rule. So proofreading is its own pass with its own
instruction, and it runs on every generation rather than only when asked.

Two design choices carry the risk here:

1. **Corrections are applied deterministically, not by swapping in the
   model's rewritten text.** The model returns a list of (before -> after)
   pairs; each one is verified against the actual text and applied as a
   targeted replacement. A proofreader handed a whole article will otherwise
   quietly restyle sentences it was never asked to touch, and the marketer
   would have no way to see what moved. This also produces the exact
   before/after list shown in the report.

2. **Brand vocabulary is protected.** '키노피스', 'ATUM', '두피창업교육'
   all look like errors to a general Korean proofreader —
   and the company glossary explicitly forbids "correcting" 키노피스 spacing
   or splitting 두피창업교육. Any correction that would alter a protected term is
   rejected before it is applied.
"""
from __future__ import annotations

import json
import re
from typing import Dict, List, Optional, Tuple

from ai_workers.multi_llm_router import generate_text

SYSTEM_PROMPT = (
    "당신은 한국어 교정 전문가입니다. 아래 글에서 **명백한 오탈자, 맞춤법 오류, 띄어쓰기 오류, "
    "조사 오류**만 찾아 교정하세요.\n\n"
    "다음은 절대 건드리지 마세요:\n"
    "- 문체·어투·표현을 더 좋게 다듬는 일 (요청받지 않았습니다)\n"
    "- 문장 구조 변경, 문장 추가·삭제\n"
    "- `[IMAGE: 경로]` 형식의 태그\n"
    "- 아래 [보호 용어] 목록에 있는 단어 — 브랜드 고유 표기이므로 오타처럼 보여도 그대로 둡니다\n\n"
    "before에는 글에 실제로 등장하는 문자열을 그대로 옮기고, after에는 고친 문자열을 넣으세요. "
    "before가 글에 없으면 안 됩니다. 오류가 없으면 corrections를 빈 배열로 두세요.\n\n"
    "반드시 아래 JSON 형식으로만 응답하세요:\n"
    '{"corrections": [{"before": "틀린 표기", "after": "고친 표기", '
    '"kind": "오타|맞춤법|띄어쓰기|조사"}]}'
)

# A correction spanning more than this is a rewrite, not a typo fix.
MAX_SPAN_CHARS = 40


def _protected_terms(brand_kit: dict) -> List[str]:
    terms = list((brand_kit.get("terminology") or {}).keys())
    terms += brand_kit.get("seo_keywords") or []
    if brand_kit.get("brand_name"):
        terms.append(brand_kit["brand_name"])
    return [t for t in terms if t]


def _violates_protected(before: str, after: str, protected: List[str]) -> bool:
    """True when applying this correction would damage a brand term."""
    for term in protected:
        # The term is being edited directly...
        if term in before and term not in after:
            return True
        # ...or the "fix" splits/merges a term that must keep its spacing,
        # e.g. 키노피스 -> 키노 피스, which the glossary explicitly forbids.
        squashed = term.replace(" ", "")
        if squashed and squashed in before.replace(" ", "") and term not in after:
            return True
    return False


def proofread(
    text: str, brand_kit: dict, vendor: str
) -> Tuple[str, List[Dict], List[Dict]]:
    """Returns (corrected_text, applied, rejected).

    Best-effort: any failure returns the text untouched, because a proofreading
    outage must never block or corrupt a draft.
    """
    protected = _protected_terms(brand_kit)
    prompt = (
        f"[보호 용어 — 교정 대상에서 제외]\n{', '.join(protected)}\n\n[교정할 글]\n{text}"
        if protected
        else f"[교정할 글]\n{text}"
    )

    try:
        raw = generate_text(
            vendor=vendor,
            prompt=prompt,
            system=SYSTEM_PROMPT,
            max_tokens=1200,
            note="proofread",
        )
        cleaned = re.sub(r"```json\s*|```\s*$", "", (raw or "").strip())
        match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        corrections = json.loads(match.group(0)).get("corrections", []) if match else []
    except Exception as exc:  # noqa: BLE001
        print(f"[proofreader] skipped: {exc}")
        return text, [], []

    corrected = text
    applied: List[Dict] = []
    rejected: List[Dict] = []

    for item in corrections:
        if not isinstance(item, dict):
            continue
        before = (item.get("before") or "").strip()
        after = (item.get("after") or "").strip()
        kind = (item.get("kind") or "교정").strip()
        if not before or before == after:
            continue

        entry = {"before": before, "after": after, "kind": kind}

        # The model cited something that isn't in the text — a hallucinated
        # correction, the same failure mode the compliance audit has.
        if before not in corrected:
            rejected.append({**entry, "reason": "본문에 없는 문구"})
            continue
        if len(before) > MAX_SPAN_CHARS or len(after) > MAX_SPAN_CHARS:
            rejected.append({**entry, "reason": "교정 범위가 너무 넓음"})
            continue
        if "[IMAGE" in before or "[IMAGE" in after:
            rejected.append({**entry, "reason": "사진 태그 훼손"})
            continue
        if _violates_protected(before, after, protected):
            rejected.append({**entry, "reason": "브랜드 보호 용어"})
            continue

        entry["count"] = corrected.count(before)
        corrected = corrected.replace(before, after)
        applied.append(entry)

    return corrected, applied, rejected
