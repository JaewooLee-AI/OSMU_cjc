"""Deterministic format checks for the Instagram and X outputs.

The Naver path already follows this project's "verify, don't just instruct"
rule twice over (compliance guardrail, SEO density). The social writers did
not: `TWEET_MAX_CHARS` and the 125-character fold existed only as sentences
inside a system prompt, and nothing looked at what came back.

That gap matters more than the Naver one, because the failure is harder:
a missed keyword costs some ranking, but a 281-character tweet **cannot be
posted at all** — the marketer only finds out when X rejects the paste.

Everything here is deterministic. None of these checks needs a model: an
over-long tweet is split on sentence boundaries, an over-long hashtag list is
trimmed. Where a fix would require rewriting prose (a hook that runs past the
fold, too few hashtags), the issue is reported rather than guessed at, so the
marketer can decide — the same reason the compliance auditor explains instead
of silently rewriting.
"""
from __future__ import annotations

import re
from typing import Dict, List, Tuple

# X's hard limit is 280; the writers target 240 so emoji and link shortening
# can't push a tweet over between generation and posting.
TWEET_SOFT_MAX = 240
TWEET_HARD_MAX = 280

# Instagram collapses the caption after ~125 characters behind "더보기".
IG_FOLD = 125
IG_HASHTAG_MIN = 8
IG_HASHTAG_MAX = 15

# Korean sentence enders, kept with the sentence they close.
_SENTENCE_END_RE = re.compile(r"(?<=[.!?。？！])\s+|(?<=[다요])\.\s*")


def _split_sentences(text: str) -> List[str]:
    parts = [p.strip() for p in _SENTENCE_END_RE.split(text) if p and p.strip()]
    return parts or [text.strip()]


def _pack(sentences: List[str], limit: int) -> List[str]:
    """Greedily groups sentences into chunks within `limit`."""
    chunks: List[str] = []
    current = ""
    for sentence in sentences:
        candidate = f"{current} {sentence}".strip() if current else sentence
        if len(candidate) <= limit:
            current = candidate
            continue
        if current:
            chunks.append(current)
        # A single sentence longer than the limit has no clean break left;
        # hard-wrap it rather than emit something unpostable.
        while len(sentence) > limit:
            chunks.append(sentence[:limit])
            sentence = sentence[limit:]
        current = sentence
    if current:
        chunks.append(current)
    return chunks


def validate_tweets(tweets: List[str]) -> Tuple[List[str], List[Dict]]:
    """Returns (tweets, issues) with any over-limit tweet split in place."""
    fixed: List[str] = []
    issues: List[Dict] = []
    for idx, tweet in enumerate(tweets, start=1):
        if len(tweet) <= TWEET_SOFT_MAX:
            fixed.append(tweet)
            continue
        pieces = _pack(_split_sentences(tweet), TWEET_SOFT_MAX)
        issues.append(
            {
                "level": "fixed" if len(tweet) <= TWEET_HARD_MAX else "blocked",
                "message": (
                    f"{idx}번 트윗이 {len(tweet)}자로 한도"
                    f"({TWEET_SOFT_MAX}자 권장 / {TWEET_HARD_MAX}자 게시 불가)를 넘어 "
                    f"{len(pieces)}개로 나눴습니다."
                ),
            }
        )
        fixed.extend(pieces)
    return fixed, issues


def validate_instagram(caption: str, hashtags: List[str]) -> Tuple[str, List[str], List[Dict]]:
    """Returns (caption, hashtags, issues). The caption is never rewritten —
    only measured — because trimming prose to fit the fold would cut the hook
    this check exists to protect."""
    issues: List[Dict] = []
    caption = caption or ""

    if caption:
        first = _split_sentences(caption)[0]
        if len(first) > IG_FOLD:
            issues.append(
                {
                    "level": "warn",
                    "message": (
                        f"첫 문장이 {len(first)}자로 '더보기' 접힘({IG_FOLD}자)을 넘어갑니다. "
                        "훅이 잘린 채 노출되니 첫 문장을 짧게 끊으세요."
                    ),
                }
            )

    fixed_tags = list(hashtags or [])
    if len(fixed_tags) > IG_HASHTAG_MAX:
        issues.append(
            {
                "level": "fixed",
                "message": f"해시태그가 {len(fixed_tags)}개라 앞 {IG_HASHTAG_MAX}개만 남겼습니다.",
            }
        )
        fixed_tags = fixed_tags[:IG_HASHTAG_MAX]
    elif len(fixed_tags) < IG_HASHTAG_MIN:
        issues.append(
            {
                "level": "warn",
                "message": (
                    f"해시태그가 {len(fixed_tags)}개뿐입니다 "
                    f"({IG_HASHTAG_MIN}~{IG_HASHTAG_MAX}개 권장). 태그는 인스타의 주요 발견 경로입니다."
                ),
            }
        )

    return caption, fixed_tags, issues
