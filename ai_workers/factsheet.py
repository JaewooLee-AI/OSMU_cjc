"""글이 담아야 하는데 메모에는 없는 사실들.

Two separate failures, three weeks apart, turned out to be the same failure.

The first: a 강사과정 모집 글 generated three times — 내용 우선, 균형, 노출
우선 — read well, stayed on subject, and was useless as an announcement. No
date, no fee, no capacity, no way to apply. The memo was one line, so there
was nothing else to write. Giving the post more room made it worse: '내용
우선' raised the length target to 1500자 and the model spent the space on
brand facts, because those were the only concrete things available to it.
Measured over the batch it carried the highest brand-fact density of the
three modes (5.1 per 1000자 against 균형's 3.4).

The second: a 돌답례품 post scored 0% on search-intent coverage. The buyer
searching 돌답례품 wants a price, a minimum order quantity, a lead time, a
size, and a way to order. The post had none of them — again because the memo
had none of them. This one is worse than it looks, because the goal is search
exposure: Naver's DIA weighs how long a reader stays, so a post that ranks
for 돌답례품 and answers nothing gets its ranking taken back.

Neither is fixable by the content modes, which trade keyword pressure against
subject room. The binding constraint in both is that facts the reader needs
were never collected. This module collects them.

Nothing here is inferred or defaulted: an empty field stays empty and the
draft prompt is told, in the same terms core_facts uses, not to invent it. A
공지 that quietly acquires a plausible 수강료, or a product post that invents
a 최소 주문 수량, is worse than one that omits it — an LLM's number becomes a
promise the company has to honour or retract.

Fields are never required. '2026년 9월 24일부터 27일까지 추석 연휴입니다' is a
finished 공지 carrying one field; a 임시 휴무, a 배송 지연, a 팝업 종료 each
carry a different two or three. Which fields a post needs is decided by what
kind of post it is, and the only one who knows that is the person writing it.
"""
from __future__ import annotations

import re

from typing import Dict, List, Tuple

Field = Tuple[str, str, str]  # (key, 라벨, placeholder)


class Sheet:
    """One set of structured facts — 공지용, 제품용."""

    def __init__(self, key: str, title: str, hint: str, fields: List[Field]):
        self.key = key
        self.title = title
        self.hint = hint
        self.fields = fields
        self.labels: Dict[str, str] = {k: label for k, label, _ in fields}


NOTICE = Sheet(
    key="notice",
    title="📣 공지 정보",
    hint=(
        "연휴·휴무 안내, 강좌 모집, 행사·팝업 공지처럼 **독자에게 알려야 할 사실이 있는 "
        "글**에 채우세요. **해당하는 항목만** 채우면 됩니다 — 전부 채울 필요도, 정해진 "
        "조합도 없습니다. 예를 들어 추석 연휴 안내는 일시 하나로 충분합니다."
    ),
    fields=[
        ("when", "일시", "예: 2026년 9월 24일(목) ~ 9월 27일(일) / 10월 14일 10:00~13:00"),
        ("where", "장소", "예: 더스티치 성수 작업장 (서울 성동구 …)"),
        ("who", "대상", "예: 미술 강사, 공방 운영자, 관련 자격 취득 예정자"),
        ("capacity", "정원", "예: 12명 (선착순 마감)"),
        ("price", "비용", "예: 1인 18만원 (재료비·키트 포함)"),
        ("how", "신청 방법", "예: 네이버 폼으로 신청 후 안내 문자 수신"),
        ("link", "신청 링크", "예: https://…"),
        ("deadline", "마감", "예: 2026년 10월 7일(화) 18:00"),
        ("contact", "문의", "예: 02-000-0000 / thestitch@…"),
    ],
)

# 항목 구성은 search_intent 감사가 답례품·굿즈 글에서 반복해서 비었다고 지적한
# 것들입니다 — 가격대, 최소 주문 수량, 제작·배송 기간, 규격, 구매 경로.
# 추측이 아니라 실제 리포트에서 나온 목록입니다.
PRODUCT = Sheet(
    key="product",
    title="🛍️ 제품·주문 정보",
    hint=(
        "답례품·굿즈·키링처럼 **독자가 사려고 검색해서 들어오는 글**에 채우세요. "
        "검색으로 들어온 사람이 가격과 주문 방법을 못 찾으면 바로 나가고, 네이버는 그 "
        "이탈을 순위에 반영합니다. **해당하는 항목만** 채우면 됩니다."
    ),
    fields=[
        ("price", "가격대", "예: 1만~3만원 (사이즈·구성에 따라)"),
        ("moq", "최소 주문 수량", "예: 30개부터 / 낱개 구매 가능"),
        ("lead_time", "제작·배송 기간", "예: 주문 후 제작 7~10일 + 배송 2일"),
        ("size", "규격·크기", "예: 행복인형 약 8cm, 키링 고리 포함 12cm"),
        ("options", "구성·옵션", "예: 색동/단색 2종, 개별 포장 파우치 포함"),
        ("custom", "맞춤 제작", "예: 기관 로고 라벨·패키지 제작 가능"),
        ("order", "주문 방법·구매처", "예: 스마트스토어 https://… / 전화 주문"),
    ],
)

SHEETS: Dict[str, Sheet] = {s.key: s for s in (NOTICE, PRODUCT)}

# 항목이 본문에 살아남았다고 볼 토큰 일치 비율 — coverage() 참고.
MATCH_RATIO = 0.6

# 이 개수 미만이면 '알릴 것이 적은 글'로 봅니다 — is_brief() 참고.
BRIEF_FIELD_COUNT = 4


def clean(sheet: Sheet, fields: Dict[str, str] | None) -> Dict[str, str]:
    """Drops blanks and unknown keys, preserving the sheet's field order."""
    given = fields or {}
    out: Dict[str, str] = {}
    for key, _, _ in sheet.fields:
        value = (given.get(key) or "").strip()
        if value:
            out[key] = value
    return out


def filled(sheet: Sheet, fields: Dict[str, str] | None) -> bool:
    """A post carries a sheet because someone filled it in, not because of a
    separate type flag — one less thing to keep in sync."""
    return bool(clean(sheet, fields))


def is_brief(sheet: Sheet, fields: Dict[str, str] | None) -> bool:
    """Too little to say to justify a length target?

    '내용 우선' asks for 1500자. That is right for a 모집 공고 carrying nine
    facts and wrong for a 연휴 안내 carrying one: the first 추석 연휴 안내
    generated this way came out at 848자, of which the actual announcement was
    three sentences and the rest was 한복 새활용 소개 and the 2023·2024
    육성지원사업 선정 이력 — the brand-padding failure these fields exist to
    fix, reappearing from the other direction.

    A 연휴·휴무 안내 carries one to three fields; a 모집·행사 공고 carries five
    or more. BRIEF_FIELD_COUNT sits in that gap. It is a threshold, so it will
    occasionally be wrong, but the cost of the other error — a two-line notice
    inflated to 1500자 of brand copy — is the one that actually gets published.
    """
    return 0 < len(clean(sheet, fields)) < BRIEF_FIELD_COUNT


def is_brief_overall(pairs) -> bool:
    """`is_brief` across every sheet a post carries.

    A post with two notice fields and five product fields has plenty to say;
    judging each sheet on its own would call it brief on the notice side and
    strip the length target from a post that needed it.
    """
    total = sum(len(clean(sheet, given)) for sheet, given in pairs)
    return 0 < total < BRIEF_FIELD_COUNT


def coverage(sheet: Sheet, content: str, fields: Dict[str, str] | None) -> Dict[str, object]:
    """Which supplied facts actually survived into the finished post.

    Deterministic and report-only, in the same spirit as the keyword density
    check: the pipeline rewrites a body for keyword counts, but silently
    re-writing dates and prices is not something an LLM should be trusted
    with. The marketer is shown what went missing and fixes it in the editor.

    A value counts as present when it appears verbatim, or when most of its
    tokens do. Verbatim alone is too strict: a marketer types '더스티치 성수
    작업장' and the draft writes '성수 작업장', the same fact. Requiring every
    token is wrong the other way — '2026년 10월 14일(화) 10:00~13:00' almost
    never survives whole. MATCH_RATIO is the line between those, tuned so that
    dropping the year or the time from a date reads as a real omission while
    dropping a qualifier from a place name does not.
    """
    present = clean(sheet, fields)
    if not present:
        return {"checked": False, "missing": [], "found": [], "missing_labels": []}

    body = content or ""
    # 공백을 지우고 맞춰봅니다. 담당자는 '1만원 미만', '5만원'이라고 적고 모델은
    # '1만 원 미만', '5만 원'이라고 쓰는데, 한국어에서 이건 표기 차이일 뿐 다른
    # 사실이 아닙니다. 첫 5건 테스트에서 누락으로 잡힌 항목의 절반이 이것 하나
    # 때문이었고, 본문에 멀쩡히 들어 있는 가격을 빠졌다고 경고하고 있었습니다.
    squeezed = re.sub(r"\s", "", body)
    found, missing = [], []
    for key, value in present.items():
        tokens = {t for t in _tokens(value) if len(t) > 1}
        if not tokens:
            # 한 글자짜리만 남는 값은 판정할 근거가 없습니다. 조사·단위 한 글자는
            # 아무 본문에나 걸려서 있으나 없으나 '있음'이 됩니다.
            found.append(key)
            continue
        hit = value in body or (
            len([t for t in tokens if _token_in(t, squeezed)]) / len(tokens) >= MATCH_RATIO
        )
        (found if hit else missing).append(key)

    return {
        "checked": True,
        "found": found,
        "missing": missing,
        "missing_labels": [sheet.labels[k] for k in missing],
    }


def _token_in(token: str, squeezed_body: str) -> bool:
    """토큰이 본문에 있는가. 조사가 붙은 형태도 같은 말로 봅니다.

    담당자는 '한복에 관심있는 누구나'처럼 조사를 붙여 적고, 본문은 '한복'으로
    씁니다. 마지막 한 글자를 떼고 한 번 더 보는 것으로 대부분의 조사(에, 를,
    의, 로…)를 흡수합니다. 두 글자 토큰까지 자르면 한 글자가 되어 아무 데나
    걸리므로 세 글자부터만 자릅니다.
    """
    if token in squeezed_body:
        return True
    return len(token) >= 3 and token[:-1] in squeezed_body


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
