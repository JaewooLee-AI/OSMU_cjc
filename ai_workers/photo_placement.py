"""`[IMAGE: path]` tag placement helpers.

Photos are captioned *before* generation and the LLM is asked to place
`[IMAGE:]` markers inline; the simulators and the Naver paste worker then
swap those markers for real images.

Unchanged from OSMU_admin except for where captions come from: the old
version asked the vision model to both describe the photo *and* judge where
it belonged in this particular article, which made captions campaign-specific
and therefore impossible to cache. Placement judgment now happens in the
text-only drafting call (which sees the memo, the article, and every caption
at once — strictly more context than a single-photo vision call had), and the
vision call answers only "what is in this picture". See ai_workers/vision.py.
"""
from __future__ import annotations

import re
from typing import Dict, List

from ai_workers.vision import describe_images

IMAGE_TAG_RE = re.compile(r"\[IMAGE:\s*([^\]]+)\]")


def caption_attachments(storage_file_paths: List[str], note: str = "") -> Dict[str, str]:
    """Returns {rel_path: objective description}.

    `note` is accepted for call-site compatibility but intentionally unused —
    keeping the memo out of the vision prompt is what makes the caption cache
    effective across campaigns (ai_workers/vision.py, layer 2).
    """
    if not storage_file_paths:
        return {}
    return describe_images(storage_file_paths)


def ensure_image_tags_preserved(original: str, rewritten: str) -> str:
    """The guardrail audit and the SEO rebalance both ask an LLM to reproduce
    the *entire* text, and neither is guaranteed to treat a custom
    `[IMAGE: path]` marker as something to keep verbatim rather than prose to
    edit. Their system prompts say to preserve it; this is the deterministic
    backstop for when one is dropped anyway."""
    original_tags = IMAGE_TAG_RE.findall(original)
    if not original_tags:
        return rewritten
    rewritten_tags = set(IMAGE_TAG_RE.findall(rewritten))
    missing = [tag for tag in original_tags if tag not in rewritten_tags]
    if not missing:
        return rewritten
    return rewritten.rstrip() + "\n\n" + "\n".join(f"[IMAGE: {tag}]" for tag in missing)


def strip_unresolvable_image_tags(content: str, storage_file_paths: List[str]) -> str:
    """Removes any `[IMAGE: tag]` whose tag isn't a real attached photo (or an
    http(s) URL) — a backstop for the observed case where a model emits an
    image marker even with zero photos attached, echoing a placeholder token
    from the prompt. Left in place, the simulator renders a permanent broken
    placeholder; dropping the marker and letting the prose flow is safer."""
    valid = set(storage_file_paths)

    def _replace(match):
        tag = match.group(1).strip()
        if tag in valid or re.match(r"^https?://", tag):
            return match.group(0)
        return ""

    cleaned = IMAGE_TAG_RE.sub(_replace, content)
    return re.sub(r"\n{3,}", "\n\n", cleaned).strip()


def ensure_all_photos_tagged(content: str, storage_file_paths: List[str]) -> str:
    """The above only stops a tag from being *dropped* between stages — it
    does nothing if the drafting model worked only a subset of the attached
    photos into its first draft (observed: 4 attached, 2 tagged). The
    simulator still renders an untagged photo, just appended as a gallery
    image rather than at an author-chosen spot, so this is a quality backstop
    rather than a data-loss one."""
    used = set(IMAGE_TAG_RE.findall(content))
    missing = [p for p in storage_file_paths if p not in used]
    if not missing:
        return content
    print(
        f"[photo_placement] model tagged {len(used)}/{len(storage_file_paths)} attached "
        f"photos — appending the rest: {missing}"
    )
    return content.rstrip() + "\n\n" + "\n".join(f"[IMAGE: {tag}]" for tag in missing)


def split_segments(content: str):
    """Splits a draft into ('text', block) / ('image', rel_path) segments in
    document order. Shared by the simulators and the Naver paste worker."""
    segments = []
    last_end = 0
    for match in IMAGE_TAG_RE.finditer(content or ""):
        text_part = content[last_end:match.start()]
        if text_part.strip():
            segments.append(("text", text_part))
        segments.append(("image", match.group(1).strip()))
        last_end = match.end()
    tail = (content or "")[last_end:]
    if tail.strip():
        segments.append(("text", tail))
    return segments
