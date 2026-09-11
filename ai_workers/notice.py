"""공지·모집 글이 반드시 담아야 하는 사실들.

The first batch run with content modes exposed a problem the modes cannot
solve. A 강사과정 모집 글 was generated three times — 내용 우선, 균형,
노출 우선 — and all three read well, stayed on subject, and were useless as
announcements: no date, no fee, no capacity, no way to apply. The memo was
one line ('전문가를 위한 패션미술 강사과정 - 홍보실장은 챗지피티'), so there
was nothing else to write.

Giving that post more room made it worse, not better. '내용 우선' raised the
length target to 1500자 and the model spent the extra space on brand facts —
1,000회 아동미술, 인증 4건, 사회적기업 — because those were the only concrete
things available to it. Measured over the batch, 내용 우선 carried the highest
brand-fact density of the three modes (5.1 per 1000자 against 균형's 3.4).

So the axis the modes model — keyword pressure against subject room — is the
wrong axis for this kind of post. The binding constraint is that the facts a
reader needs were never collected. This module collects them.

Nothing here is inferred or defaulted: an empty field stays empty and the
draft prompt is told, in the same terms core_facts uses, not to invent it.
A 공지 that quietly acquires a plausible-looking 수강료 is worse than one
that omits it.
"""
from __future__ import annotations

from typing import Dict, List, Tuple

# (key, 라벨, placeholder). 순서가 곧 입력 화면의 순서이자 프롬프트에 실리는
# 순서입니다.
FIELDS: List[Tuple[str, str, str]] = [
    ("when", "일시", "예: 2026년 10월 14일(화) ~ 10월 16일(목), 매일 10:00~13:00"),
    ("where", "장소", "예: 더스티치 성수 작업장 (서울 성동구 …)"),
    ("who", "대상", "예: 미술 강사, 공방 운영자, 관련 자격 취득 예정자"),
    ("capacity", "정원", "예: 12명 (선착순 마감)"),
    ("price", "비용", "예: 1인 18만원 (재료비·키트 포함)"),
    ("how", "신청 방법", "예: 네이버 폼으로 신청 후 안내 문자 수신"),
    ("link", "신청 링크", "예: https://…"),
    ("deadline", "마감", "예: 2026년 10월 7일(화) 18:00"),
    ("contact", "문의", "예: 02-000-0000 / thestitch@…"),
]

LABELS: Dict[str, str] = {key: label for key, label, _ in FIELDS}

# 이것들이 비어 있으면 공지로 성립하지 않습니다. 나머지는 있으면 좋은 정보.
ESSENTIAL = ("when", "how")

# 공지 항목이 본문에 살아남았다고 볼 토큰 일치 비율 — coverage() 참고.
MATCH_RATIO = 0.6


def clean(fields: Dict[str, str] | None) -> Dict[str, str]:
    """Drops blanks and unknown keys, preserving FIELDS order."""
    given = fields or {}
    out: Dict[str, str] = {}
    for key, _, _ in FIELDS:
        value = (given.get(key) or "").strip()
        if value:
            out[key] = value
    return out


def is_notice(fields: Dict[str, str] | None) -> bool:
    """A campaign is a 공지 because someone filled the 공지 fields in, not
    because of a separate type flag — one less thing to keep in sync."""
    return bool(clean(fields))


def missing_essentials(fields: Dict[str, str] | None) -> List[str]:
    """Essential fields left blank, as labels, for warning the marketer."""
    present = clean(fields)
    return [LABELS[key] for key in ESSENTIAL if key not in present]


def coverage(content: str, fields: Dict[str, str] | None) -> Dict[str, object]:
    """Which supplied facts actually survived into the finished post.

    Deterministic and report-only, in the same spirit as the keyword density
    check: the pipeline rewrites a body for keyword counts, but silently
    re-writing dates and prices is not something an LLM should be trusted
    with. The marketer is shown what went missing and fixes it in the editor.

    A value counts as present when it appears verbatim, or when most of its
    tokens do. Verbatim alone is too strict to be useful: a marketer types
    '더스티치 성수 작업장' and the draft writes '성수 작업장', which is the
    same fact and would otherwise be reported as dropped. Requiring *every*
    token is equally wrong in the other direction — '2026년 10월 14일(화)
    10:00~13:00' almost never survives whole.

    MATCH_RATIO is the line between those. It is a judgement call, tuned so
    that dropping the year or the time from a date reads as a real omission
    (a 공지 without a time is not a 공지) while dropping a qualifier from a
    place name does not.
    """
    present = clean(fields)
    if not present:
        return {"checked": False, "missing": [], "found": []}

    body = content or ""
    found, missing = [], []
    for key, value in present.items():
        tokens = set(_tokens(value))
        hit = value in body or (
            tokens and len([t for t in tokens if t in body]) / len(tokens) >= MATCH_RATIO
        )
        (found if hit else missing).append(key)

    return {
        "checked": True,
        "found": found,
        "missing": missing,
        "missing_labels": [LABELS[k] for k in missing],
    }


def _tokens(value: str) -> List[str]:
    out, buf = [], []
    for ch in value:
        if ch.isalnum():
            buf.append(ch)
        elif buf:
            out.append("".join(buf))
            buf = []
    if buf:
        out.append("".join(buf))
    return out
