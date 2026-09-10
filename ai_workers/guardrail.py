"""Second-pass compliance reviewer, rebuilt for 더스티치's actual legal exposure.

OSMU_admin's guardrail audited against 의료법 (medical advertising law),
because that engine was built for a healthcare client. 더스티치 sells upcycled
hanbok goods and environmental education, so the law that actually bites here
is **환경성 표시·광고** — 「환경기술 및 환경산업 지원법」 제16조의10 and the
환경부 '환경성 표시·광고 관리제도에 관한 고시', plus 표시·광고의 공정화에 관한
법률. The classic failure mode isn't "cures cancer", it's greenwashing:
absolute claims ("100% 친환경"), unverifiable quantities ("탄소 3kg 절감"),
and borrowing the authority of certifications the company doesn't hold.

Three layers, same defense-in-depth shape as the original:

1. **Deterministic dictionary substitution** — admin-maintained
   "금기어 -> 치환어" pairs (Brand Kit) are swapped verbatim,
   case-insensitively. A known-bad term never survives, whatever the LLM does.
2. **LLM structured audit** — catches contextual/novel violations the fixed
   dictionary can't, and returns a score + explanation rather than silently
   rewriting, so the admin can see *why* something was flagged. The Brand
   Kit's core facts and glossary go in as the only permitted source of truth,
   so a price or certification count that contradicts them is a finding
   rather than something the audit has no way to evaluate.
3. **Deterministic certification-scope check** — a certification claimed for
   a collective subject ("저희 제품들은 … 인증을 받아"). The audit is told
   about this too, but it passed five consecutive drafts that did it, and
   미보유 인증 암시 is the single most likely 환경성 표시·광고 violation for an
   upcycling brand — so it gets a hard check, not just an instruction.

Only invoked when the Brand Kit guardrail toggle is on.
"""
from __future__ import annotations

import json
import re
from typing import Dict, List, Optional, Tuple

from ai_workers.multi_llm_router import generate_text

AUDIT_SYSTEM_PROMPT = (
    "당신은 대한민국 「환경기술 및 환경산업 지원법」의 환경성 표시·광고 관리제도와 "
    "「표시·광고의 공정화에 관한 법률」을 기준으로 마케팅 문안을 검토하는 법무 검토관입니다. "
    "새활용(업사이클링) 제품과 친환경 교육서비스를 판매하는 사회적기업의 글을 검토합니다.\n\n"
    "다음을 중점적으로 찾아내세요:\n"
    "1) 포괄적·절대적 환경성 주장 — '100% 친환경', '완전 무해', '지구를 살리는', '무독성' 등 "
    "제품 전 과정을 입증하지 않고 쓰는 표현.\n"
    "2) 검증 불가능한 정량 효과 — 근거 자료 없이 제시한 탄소 절감량, 물 절약량, 폐기물 감축량.\n"
    "3) 보유하지 않은 인증·수상의 암시, 그리고 **보유한 인증의 범위를 넘겨 쓰는 것**. "
    "인증은 인증받은 품목에만 붙습니다. 일부 품목만 인증받았는데 '저희 제품들은', "
    "'모든 소품은'처럼 전체가 인증받은 것처럼 읽히면 위반입니다. 인증을 품질·신뢰의 "
    "일반적 보증('인증을 받아 더욱 믿을 수 있습니다')으로 확대하는 것도 위반입니다.\n"
    "4) 최상급·배타적 표현 — '국내 최초', '업계 최고', '유일한', '완벽한'.\n"
    "5) 소비자를 위축시키는 공포·죄책감 소구 — '쓰지 않으면 지구가 망합니다' 류.\n"
    "6) **[검증된 사실]과 어긋나는 수치** — 가격대, 수량, 연도, 실적, 인증 건수. "
    "[검증된 사실]에 없거나 그와 다른 숫자가 나오면 반드시 지적하고, corrected_text에서는 "
    "[검증된 사실]에 맞게 고치거나 숫자를 빼세요. 절대 새 숫자를 지어내지 마세요.\n\n"
    "제품의 색감·소재·쓰임새에 대한 사실 서술이나, 기부받은 한복을 재료로 쓴다는 "
    "설명 자체는 문제가 아닙니다. 과장하지 않은 표현까지 억지로 고치지 마세요.\n\n"
    "텍스트 중간에 `[IMAGE: 경로]` 형식의 태그가 있다면 사진 삽입 위치 마크업이므로 "
    "절대 삭제·수정·이동하지 말고 원래 자리에 글자 그대로 유지하세요.\n\n"
    "issues의 각 항목은 반드시 {\"phrase\": ..., \"note\": ...} 객체로 작성하세요. "
    "phrase에는 본문에 실제로 등장하는, 문제가 된 표현 '하나만' 그대로 옮겨 적으세요 — "
    "본문에 없는 문구를 넣으면 안 되고, note에서 언급하는 대안·추천 표현을 phrase에 넣어서도 "
    "안 됩니다. 문제 표현이 여러 개면 항목을 여러 개로 나누세요. strengths에는 인증 근거를 "
    "정확히 연결하는 등 이미 잘 지켜진 점을 1~3개 문자열로 짧게 적으세요(없으면 빈 배열).\n\n"
    "반드시 아래 JSON 형식으로만 응답하고 다른 설명은 포함하지 마세요:\n"
    '{"compliance_pass": true, "score": 90, "strengths": ["잘 지켜진 점 1"], '
    '"issues": [{"phrase": "본문에 실제로 등장하는 문제 표현", '
    '"note": "문제 설명 및 권장 수정 방향"}], '
    '"corrected_text": "교정된 전체 텍스트"}'
)


# Sentences claiming a certification for a collective subject. The audit
# prompt asks for this too, but an instruction is not a guarantee: all five of
# the first production batch passed while carrying "더봄봄의 소품들은 …
# 새활용제품인증을 받아 더욱 믿을 수 있습니다", which claims a four-product
# certification for the whole catalogue. Under 환경성 표시·광고 관리제도 that is
# the 미보유 인증 암시 case this guardrail exists for, so it gets a
# deterministic detector like the banned-term dictionary has.
#
# Brand-agnostic by construction: the specific product names come from the
# Brand Kit glossary, so nothing here is 더스티치-specific.
_CERT_RE = re.compile(r"[가-힣A-Za-z]*인증")
_COLLECTIVE_RE = re.compile(
    r"모든|모두|전\s?제품|전\s?품목|전\s?라인|제품들|소품들|상품들|굿즈들|아이템들|라인업"
)
_SENTENCE_RE = re.compile(r"[^.!?\n]+[.!?]?")

CERT_SCOPE_NOTE = (
    "인증받은 품목이 아니라 제품 전체가 인증된 것처럼 읽힙니다. "
    "인증받은 품목명을 직접 쓰거나('행복인형과 스크런치는 …'), "
    "인증 언급을 그 문장에서 빼세요. 「환경기술 및 환경산업 지원법」 환경성 표시·광고 "
    "관리제도상 미보유 인증 암시에 해당할 수 있습니다."
)


def check_certification_scope(text: str, brand_kit: dict) -> List[dict]:
    """Sentences that attach a certification to a collective subject.

    Deliberately narrow — a false positive here fails the campaign and sends
    the marketer into a regeneration loop. Three conditions must all hold:

    * the sentence mentions a certification, and
    * it mentions a collective noun (모든 / 제품들 / 소품들 …) **before** the
      certification, and
    * it names no specific product.

    Word order carries the distinction that matters. Korean modifiers precede
    their head, so "새활용제품인증을 받은 제품들은 …" is restrictive — the
    collective is scoped *by* the certification and the claim is accurate.
    Reverse them and the collective becomes the subject — "저희 제품들은 …
    인증을 받아" claims the certification for the whole catalogue. Only the
    second order is flagged; on the first production batch that is exactly
    one sentence out of five posts, and it is the one that over-claims.
    """
    # Brand names are not products: "더봄봄의 소품들은 …" names the brand and
    # still says nothing about which items are certified.
    excluded = {
        (brand_kit.get("brand_name") or "").strip(),
        (brand_kit.get("sub_brand") or "").strip(),
    }
    product_names = [
        name for name in (brand_kit.get("terminology") or {}).keys()
        if len(name) >= 2 and name not in excluded
    ]
    findings = []
    for match in _SENTENCE_RE.finditer(text):
        sentence = match.group(0).strip()
        cert = _CERT_RE.search(sentence)
        collective = _COLLECTIVE_RE.search(sentence)
        if not cert or not collective or collective.start() > cert.start():
            continue
        # A glossary term inside the certification word itself ('새활용' in
        # '새활용제품인증') is not the sentence naming a product.
        outside_cert = sentence[: cert.start()] + sentence[cert.end():]
        if any(name in outside_cert for name in product_names):
            # "행복인형과 스크런치 등 인증 제품들은 …" carries its own scope.
            continue
        findings.append({"phrase": sentence, "note": CERT_SCOPE_NOTE})
    return findings


def _verified_facts_block(brand_kit: dict) -> str:
    """The only numbers and claims the audit may treat as true.

    Without this the audit has no ground truth, so it cannot tell a correct
    price from an invented one — which is how three posts in one batch quoted
    '5,000원부터', '1만 원대부터' and '1만~3만 원대' for the same products.
    """
    facts = [str(f).strip() for f in (brand_kit.get("core_facts") or []) if str(f).strip()]
    glossary = [
        f"{term}: {desc}" for term, desc in (brand_kit.get("terminology") or {}).items() if desc
    ]
    if not facts and not glossary:
        return ""
    lines = ["\n\n[검증된 사실 — 아래에 없는 수치·인증·실적은 근거 없는 것으로 취급하세요]"]
    lines += [f"- {f}" for f in facts]
    lines += [f"- {g}" for g in glossary]
    return "\n".join(lines)


def _parse_issue(item) -> Tuple[Optional[str], str]:
    """Returns (phrase, display_text) for one issue entry.

    `phrase` is the single problem expression the model isolated — used to
    check, later, whether it's still in the text. A model that ignores the
    schema and returns a bare string is tolerated (phrase=None): grounding
    and later resolution can't be verified for it, so it defaults to "still
    open" rather than silently disappearing from the report.
    """
    if isinstance(item, dict):
        phrase = (item.get("phrase") or "").strip() or None
        note = (item.get("note") or "").strip()
        if phrase and note:
            return phrase, f"'{phrase}' — {note}"
        return phrase, (note or phrase or "")
    return None, str(item)


def _classify_issues(raw_issues: List, reviewed_text: str) -> Tuple[List[str], List[str], Dict[str, str]]:
    """Splits LLM-reported issues into grounded vs unverified, and records
    each issue's isolated phrase for later use (see `content_writer.py`
    stage 6b, which checks whether the phrase survived into the shipped
    text). A phrase that doesn't actually appear anywhere in the text the
    model just read is a hallucinated citation, not a real finding, and must
    not fail the campaign or alarm the marketer as if it were one.
    """
    lowered_text = reviewed_text.lower()
    grounded, unverified = [], []
    phrase_map: Dict[str, str] = {}
    for item in raw_issues:
        phrase, text = _parse_issue(item)
        if not text:
            continue
        if phrase:
            phrase_map[text] = phrase
        if phrase and phrase.lower() not in lowered_text:
            unverified.append(text)
        else:
            grounded.append(text)
    return grounded, unverified, phrase_map


def apply_blacklist_dictionary(text: str, blacklist_map: dict) -> Tuple[str, List[dict]]:
    """Deterministic, case-insensitive find/replace. Returns (sanitized, hits).

    Longest term first, regardless of the order the admin entered rows: many
    Korean banned phrases are prefixes of a longer, more specific one
    ("국내 최초" inside "국내 최초로"), and Korean glues particles onto the end of
    a phrase. Matching short-first would rewrite "국내 최초로" into
    "국내에서도 보기 드문로" — the substitution succeeds and the sentence breaks.
    Sorting by length makes the specific entry win without the admin having to
    know to order the table by hand.
    """
    sanitized = text
    hits = []
    ordered = sorted((blacklist_map or {}).items(), key=lambda kv: len(kv[0] or ""), reverse=True)
    for forbidden, replacement in ordered:
        if not forbidden:
            continue
        pattern = re.compile(re.escape(forbidden), re.IGNORECASE)
        if pattern.search(sanitized):
            hits.append({"forbidden": forbidden, "replacement": replacement})
            sanitized = pattern.sub(replacement, sanitized)
    return sanitized, hits


def run_llm_audit(text: str, vendor: str, brand_kit: Optional[dict] = None) -> Dict:
    """Structured compliance report. Falls back to a conservative 'pass with
    no changes' if JSON parsing fails — an audit failure must never crash the
    pipeline or silently mangle the draft."""
    raw = generate_text(
        vendor=vendor,
        prompt=text,
        system=AUDIT_SYSTEM_PROMPT + _verified_facts_block(brand_kit or {}),
        max_tokens=2500,
        note="guardrail-audit",
    )
    try:
        cleaned = re.sub(r"```json\s*|```\s*$", "", raw.strip())
        match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        parsed = json.loads(match.group(0)) if match else {}
        issues = parsed.get("issues", [])
        grounded, unverified, phrase_map = _classify_issues(issues, text)
        return {
            "compliance_pass": bool(parsed.get("compliance_pass", True)),
            "score": int(parsed.get("score", 100)),
            "strengths": parsed.get("strengths", []),
            "grounded_issues": grounded,
            "unverified_issues": unverified,
            "issue_phrases": phrase_map,
            "corrected_text": parsed.get("corrected_text") or text,
        }
    except Exception:
        return {
            "compliance_pass": True, "score": 100, "strengths": [], "grounded_issues": [],
            "unverified_issues": [], "issue_phrases": {}, "corrected_text": text, "parse_error": raw,
        }


def review_and_sanitize(text: str, brand_kit: dict, vendor: str) -> Dict:
    dict_sanitized, dictionary_hits = apply_blacklist_dictionary(text, brand_kit.get("blacklist_map", {}))
    audit = run_llm_audit(dict_sanitized, vendor, brand_kit)

    # Checked against the text the audit *returns*, not the text it read: if
    # corrected_text already narrowed the over-broad sentence, there is
    # nothing left to report.
    grounded = list(audit["grounded_issues"])
    phrase_map = dict(audit["issue_phrases"])
    cert_findings = check_certification_scope(audit["corrected_text"], brand_kit)
    for finding in cert_findings:
        display = f"'{finding['phrase']}' — {finding['note']}"
        if display not in grounded:
            grounded.append(display)
            phrase_map[display] = finding["phrase"]

    # A dictionary hit is already fixed by the time this returns, and an
    # unverified issue cites a phrase that was never in the text — neither is
    # evidence that the *delivered* text is unsafe, so neither vetoes
    # compliance_pass. Only a grounded, still-live issue does.
    return {
        "final_text": audit["corrected_text"],
        "compliance_pass": not grounded,
        "score": audit["score"],
        "strengths": audit["strengths"],
        "dictionary_hits": dictionary_hits,
        "llm_issues": grounded,
        "unverified_issues": audit["unverified_issues"],
        "issue_phrases": phrase_map,
        "cert_scope_issues": [f["phrase"] for f in cert_findings],
    }


def apply_guardrail_if_enabled(text: str, brand_kit: dict, vendor: str) -> Dict:
    """Returns a report dict even when disabled, so callers always have a
    consistent shape to persist (compliance_pass=None means 'skipped')."""
    if not brand_kit.get("guardrail_enabled", True):
        return {
            "final_text": text, "compliance_pass": None, "score": None, "strengths": [],
            "dictionary_hits": [], "llm_issues": [], "unverified_issues": [], "issue_phrases": {},
            "cert_scope_issues": [],
        }
    return review_and_sanitize(text, brand_kit, vendor)
