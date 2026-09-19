"""Keeps generated titles from converging on each other.

Every post is drafted from the same brand kit and the same company facts, so
the title model gravitates to the same handful of shapes ("ATUM 3D 측정으로
완성한 ...", "... 키노피스의 특별한 ..."). Two layers, matching the
verify-don't-just-instruct pattern used for compliance and SEO density:

1. Recent titles go into the drafting prompt as "avoid these".
2. The result is scored against history deterministically, and only a title
   that's still too close costs a corrective LLM call.

The comparison deliberately ignores the brand name and the SEO keywords.
Those are *required* to repeat — `title_keyword_coverage` exists to force a
target keyword into every title — so scoring raw strings would rate every
compliant title as a near-duplicate and fire a rewrite every single time.
What actually needs to vary is the phrasing around them.
"""
from __future__ import annotations

import re
from typing import List, Optional, Tuple

from ai_workers.multi_llm_router import generate_text

# Above this, two titles read as the same headline with words swapped.
SIMILARITY_THRESHOLD = 0.55

# Bigram overlap alone misses the failure this module was written for: real
# titles from this project ("ATUM 3D 측정으로 완성한 특별한 키노피스 가발" vs
# "ATUM 3D 측정으로 완성한 일상의 자신감, 키노피스") score only ~27% because
# their distinctive tails genuinely differ — yet a reader scanning the blog
# index sees the same headline template every time. A shared verbatim run of
# this many characters, over and above the mandated brand/keyword terms, is
# that template showing through.
SHARED_RUN_CHARS = 7

# How many past titles to show the model. Titles are short; 20 is a few
# hundred tokens and covers well beyond what a reader would remember.
PROMPT_HISTORY_LIMIT = 20

_NON_WORD_RE = re.compile(r"[^0-9A-Za-z가-힣]+")

REWRITE_SYSTEM_PROMPT = (
    "당신은 네이버 블로그 편집자입니다. 새로 쓴 제목이 과거에 발행한 제목들과 너무 비슷합니다. "
    "같은 소재를 다루되 문장 구조와 표현을 확실히 다르게 바꾼 제목을 하나만 출력하세요. "
    "지정된 타깃 키워드는 반드시 그대로 유지하고, 25자 이내로 씁니다. "
    "따옴표나 다른 설명 없이 제목 한 줄만 출력하세요."
)


def _distinctive_part(title: str, ignore_terms: List[str]) -> str:
    """The title with mandated repeats (brand, SEO keywords) removed."""
    reduced = title.lower()
    # Longest first so "맞춤가발" is consumed before "가발" can fragment it.
    for term in sorted((t or "" for t in ignore_terms), key=len, reverse=True):
        if term:
            reduced = reduced.replace(term.lower(), " ")
    return _NON_WORD_RE.sub("", reduced)


def _bigrams(text: str) -> set:
    """Character bigrams — no Korean tokenizer needed, and they capture the
    particle/ending changes ('완성한' vs '완성하는') that word-level matching
    would treat as entirely different tokens."""
    return {text[i:i + 2] for i in range(len(text) - 1)} if len(text) > 1 else {text}


def similarity(a: str, b: str, ignore_terms: Optional[List[str]] = None) -> float:
    """Jaccard overlap of the distinctive parts, 0.0~1.0."""
    ignore_terms = ignore_terms or []
    set_a = _bigrams(_distinctive_part(a, ignore_terms))
    set_b = _bigrams(_distinctive_part(b, ignore_terms))
    if not set_a or not set_b:
        # Nothing distinctive left on either side means the title is made up
        # entirely of mandated terms — that IS a duplicate, not a novel title.
        return 1.0 if set_a == set_b else 0.0
    return len(set_a & set_b) / len(set_a | set_b)


def shared_run(a: str, b: str, ignore_terms: Optional[List[str]] = None) -> str:
    """Longest verbatim run common to both titles that isn't just a mandated
    term. The brand name and every SEO keyword are required in each title, so
    a run contained inside one of those carries no information about
    repetition — only a run that reaches beyond them is real template reuse.
    """
    ignore_terms = ignore_terms or []
    norm_a, norm_b = " ".join(a.split()).lower(), " ".join(b.split()).lower()
    lowered_ignore = [t.lower() for t in ignore_terms if t]

    # Classic DP longest-common-substring; titles are ~25 chars, so the
    # quadratic cost is irrelevant here.
    best = ""
    prev = [0] * (len(norm_b) + 1)
    for i in range(1, len(norm_a) + 1):
        cur = [0] * (len(norm_b) + 1)
        for j in range(1, len(norm_b) + 1):
            if norm_a[i - 1] == norm_b[j - 1]:
                cur[j] = prev[j - 1] + 1
                if cur[j] > len(best):
                    candidate = norm_a[i - cur[j]:i]
                    # A run that fits inside a mandated term proves nothing.
                    if not any(candidate.strip() in term for term in lowered_ignore):
                        best = candidate
        prev = cur
    return best.strip()


def closest_previous(
    title: str, history: List[str], ignore_terms: Optional[List[str]] = None
) -> Tuple[Optional[str], float]:
    """The most repetitive past title and a 0.0~1.0 score.

    Scores the two independent signals — lexical overlap and template reuse —
    and reports whichever is worse, so a title that dodges one but not the
    other is still caught.
    """
    best, best_score = None, 0.0
    for past in history:
        lexical = similarity(title, past, ignore_terms)
        run = shared_run(title, past, ignore_terms)
        # Map the run length onto the same scale, so one threshold governs
        # both signals: exactly SHARED_RUN_CHARS lands on the threshold.
        template = (
            SIMILARITY_THRESHOLD * len(run) / SHARED_RUN_CHARS
            if len(run) >= SHARED_RUN_CHARS
            else 0.0
        )
        score = min(1.0, max(lexical, template))
        if score > best_score:
            best, best_score = past, score
    return best, best_score


def avoidance_instruction(history: List[str]) -> str:
    """Prompt block listing recent titles to steer away from."""
    if not history:
        return ""
    listed = "\n".join(f"- {t}" for t in history[:PROMPT_HISTORY_LIMIT])
    return (
        "\n\n[과거 발행 제목 — 아래와 문장 구조·표현이 겹치지 않게 새로운 형태로 쓰세요]\n"
        f"{listed}"
    )


def rewrite_for_variety(
    title: str,
    similar_to: str,
    keywords: List[str],
    vendor: str,
    history: Optional[List[str]] = None,
) -> str:
    """One corrective pass. Best-effort — any failure keeps the original,
    since a repetitive title still beats a blank or mangled one."""
    prompt = (
        f"[새로 쓴 제목]\n{title}\n\n[너무 비슷한 과거 제목]\n{similar_to}\n\n"
        f"[반드시 유지할 키워드]\n{', '.join(keywords) if keywords else '(없음)'}"
        + avoidance_instruction(history or [])
    )
    try:
        raw = generate_text(
            vendor=vendor, prompt=prompt, system=REWRITE_SYSTEM_PROMPT,
            max_tokens=60, note="title-variety",
        )
    except Exception:
        return title
    candidate = raw.strip().strip('"').strip("'").splitlines()[0] if raw.strip() else ""
    return candidate or title
