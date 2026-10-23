"""요청 4(원고 서식 레이어) 시험 — LLM 없이."""
from __future__ import annotations

import json

from ai_workers import formatting as F
from ai_workers.prompt_builder import build_blog_system_prompt

DRAFT = """첫 인사 문단입니다. 가발 관리는 **세척 주기**가 가장 중요합니다.

## 세척은 이렇게

미지근한 물에 ==전용 샴푸==를 풀어 주세요.
- 빗질을 먼저 합니다
- 물기는 수건으로 눌러 닦습니다
[IMAGE: assets/a.jpg]
[사진 설명: 세척 전 빗질하는 모습]
> 가발도 피부처럼 순하게 다뤄야 오래 씁니다.

---

## 보관법

통풍이 잘되는 곳에 거치대로 보관하세요.
[사진 제안: 거치대에 걸어 둔 가발]

[요약 박스]
- 세척은 미지근한 물로
- 보관은 거치대에
[/요약 박스]"""


def test_extract_strips_markup_and_keeps_text():
    plain, items = F.extract(DRAFT)
    assert "**" not in plain and "==" not in plain and "##" not in plain and "---" not in plain
    assert "[요약 박스]" not in plain and "[사진 제안" not in plain and "[사진 설명" not in plain
    assert "> " not in plain
    assert "[IMAGE: assets/a.jpg]" in plain
    assert "가발 관리는 세척 주기가 가장 중요합니다." in plain
    assert "- 빗질을 먼저 합니다" in plain  # 목록은 평문에 남김
    kinds = [i["type"] for i in items]
    assert kinds.count("heading") == 2 and "bold" in kinds and "highlight" in kinds
    assert {"quote", "divider", "box", "photo_hint", "photo_caption"} <= set(kinds)
    cap = next(i for i in items if i["type"] == "photo_caption")
    assert cap["path"] == "assets/a.jpg"
    div = next(i for i in items if i["type"] == "divider")
    assert div["before"] == "보관법"
    box = next(i for i in items if i["type"] == "box")
    assert box["start"] == "- 세척은 미지근한 물로" and box["end"] == "- 보관은 거치대에"


def test_extract_plain_draft_unchanged():
    text = "그냥 문단입니다.\n\n둘째 문단."
    plain, items = F.extract(text)
    assert plain == text and items == []
    assert not F.has_markup(text) and F.has_markup("이건 **굵게**")


def test_finalize_limits_and_per_paragraph_cap():
    many = "한 문단에 **하나** **둘** **셋** 강조가 있습니다."
    plain, items = F.extract(many)
    fmt = F.finalize(plain, items, "standard", "basic")
    assert len([i for i in fmt["items"] if i["type"] == "bold"]) == F.PER_PARAGRAPH_EMPHASIS
    fmt_none = F.finalize(plain, items, "none", "basic")
    assert fmt_none["items"] == []
    assert [i["id"] for i in fmt["items"]] == list(range(1, len(fmt["items"]) + 1))


def test_quote_limit_by_length():
    short = "> 하나\n\n> 둘\n\n> 셋"
    plain, items = F.extract(short)
    assert len([i for i in F.finalize(plain, items, "standard", "basic")["items"] if i["type"] == "quote"]) == 1
    assert len([i for i in F.finalize(plain, items, "rich", "basic")["items"] if i["type"] == "quote"]) == 2


def test_bind_survives_proofreading_and_drops_lost_anchors():
    plain, items = F.extract(DRAFT)
    fmt = F.finalize(plain, items, "rich", "info")
    # 교정: 띄어쓰기 하나 바뀜(찾아야 함), 인용 문장이 완전히 바뀜(못 찾아야 함)
    edited = plain.replace("세척 주기가", "세척주기가").replace("가발도 피부처럼 순하게 다뤄야 오래 씁니다.", "전혀 다른 문장으로 교체되었습니다 완전히.")
    blocks, unmatched = F.bind(edited, fmt)
    assert any(i["type"] == "quote" for i in unmatched)
    first = next(b for b in blocks if b["kind"] == "text")
    assert first["spans"] and first["spans"][0][2] == "bold"
    img = next(b for b in blocks if b["kind"] == "image")
    assert img["caption"] == "세척 전 빗질하는 모습"
    styles = [b["style"] for b in blocks if b["kind"] == "text"]
    assert styles.count("h2") == 2 and "li" in styles


def test_naver_html_editor_and_symbol_modes():
    plain, items = F.extract(DRAFT)
    fmt = F.finalize(plain, items, "rich", "info")
    segs = F.naver_segments(plain, fmt, "editor")
    kinds = [k for k, _ in segs]
    assert kinds == ["html", "image", "html"]
    first, second = segs[0][1], segs[2][1]
    assert "<b>세척 주기</b>" in first and "background-color" in first and "font-size:24px" in first
    assert "<ul><li>빗질을 먼저 합니다</li>" in first
    assert "<blockquote>" in second and "<hr>" in second and "<table" in second and "📷 사진 자리" in second
    sym = F.naver_segments(plain, fmt, "symbol")[2][1]
    assert "<blockquote>" not in sym and "<hr" not in sym and "<table" not in sym and "❝" in sym
    exp = F.expected_components(plain, fmt)
    assert exp == {"quote": 1, "divider": 1, "box": 1, "hint": 1}


def test_naver_html_without_format_matches_old_paragraphs():
    text = "첫 문단 & <브랜드>\n둘째"
    segs = F.naver_segments(text, {})
    assert segs == [("html", "<p>첫 문단 &amp; &lt;브랜드&gt;</p><p>둘째</p>")]


def test_html_escapes_inside_spans():
    plain, items = F.extract("이건 **A&B <특가>** 입니다")
    html = F.naver_segments(plain, F.finalize(plain, items, "standard", "basic"))[0][1]
    assert "<b>A&amp;B &lt;특가&gt;</b>" in html


def test_parse_apply_response_never_changes_text():
    content = "소제목\n본문 첫 문장입니다. 핵심은 세척입니다.\n마지막 문단."
    raw = json.dumps({
        "headings": [{"para": 0, "level": 2}, {"para": 1, "level": 2}],  # 1번은 너무 김 → 제외
        "bold": [{"para": 1, "text": "핵심은 세척"}, {"para": 1, "text": "본문에 없는 구절"}],
        "highlight": [], "quotes": [2, 99], "dividers_before": [0, 2],
        "box": None, "photo_hints": [{"after": 1, "caption": "세척 장면"}],
    }, ensure_ascii=False)
    items = F.parse_apply_response("설명 없이 " + raw, content)
    kinds = sorted(i["type"] for i in items)
    assert kinds == ["bold", "divider", "heading", "photo_hint", "quote"]
    assert next(i for i in items if i["type"] == "divider")["before"] == "마지막 문단."
    fmt = F.finalize(content, items, "standard", "basic", source="apply")
    blocks, unmatched = F.bind(content, fmt)
    assert not unmatched
    assert "\n".join(b["text"] for b in blocks if b["kind"] == "text") == content


def test_remove_and_update_items():
    plain, items = F.extract("**굵게** 문단")
    fmt = F.finalize(plain, items, "standard", "basic")
    iid = fmt["items"][0]["id"]
    assert F.update_item(fmt, iid, type="highlight")["items"][0]["type"] == "highlight"
    assert F.remove_item(fmt, iid)["items"] == []


def test_instruction_and_system_prompt_swap():
    assert F.instruction("basic", "none", False) is None
    instr = F.instruction("review", "standard", False)
    assert "지어내지 마세요" in instr and "[사진 제안" in instr
    assert "[사진 설명" in F.instruction("basic", "standard", True)
    kit = {"name": "k"}
    plain_prompt = build_blog_system_prompt(kit)
    fmt_prompt = build_blog_system_prompt(kit, None, instr)
    assert "마크다운 제목 기호(#)는 쓰지 말고" in plain_prompt
    assert "마크다운 제목 기호(#)는 쓰지 말고" not in fmt_prompt and instr in fmt_prompt


def test_resolve_prefers_campaign_then_kit():
    kit = {"design_strength": "minimal", "design_template": "info"}
    assert F.resolve(None, kit) == {"strength": "minimal", "template": "info"}
    assert F.resolve("rich", kit)["strength"] == "rich"
    assert F.resolve("bogus", {}) == {"strength": F.DEFAULT_STRENGTH, "template": F.DEFAULT_TEMPLATE}


def test_fill_photo_hints_places_in_order_and_removes_hints():
    content = "도입 문단.\n\n둘째 문단.\n[IMAGE: old.jpg]\n셋째 문단."
    fmt = {"items": [
        {"id": 1, "type": "photo_hint", "after": "둘째 문단.", "caption": "둘째 뒤"},
        {"id": 2, "type": "photo_hint", "after": "", "caption": "맨 앞"},
        {"id": 3, "type": "photo_hint", "after": "사라진 문단", "caption": "못 찾음"},
        {"id": 4, "type": "bold", "text": "셋째"},
    ]}
    new, new_fmt, placed = F.fill_photo_hints(content, fmt, ["old.jpg", "a.jpg", "b.jpg", "c.jpg"])
    assert placed == 2
    assert new.split("\n")[0] == "[IMAGE: a.jpg]"
    assert "둘째 문단.\n[IMAGE: b.jpg]" in new
    assert new.replace("[IMAGE: a.jpg]\n", "").replace("[IMAGE: b.jpg]\n", "") == content  # 글자는 그대로
    assert [i["id"] for i in new_fmt["items"]] == [3, 4]  # 쓴 자리만 지움
    assert F.unplaced_photos(new, ["old.jpg", "a.jpg", "b.jpg", "c.jpg"]) == ["c.jpg"]


def test_fill_photo_hints_noop_without_hints_or_new_photos():
    content = "문단.\n[IMAGE: a.jpg]"
    fmt = {"items": [{"id": 1, "type": "photo_hint", "after": "문단.", "caption": "x"}]}
    assert F.fill_photo_hints(content, fmt, ["a.jpg"])[2] == 0
    assert F.fill_photo_hints(content, {"items": []}, ["a.jpg", "b.jpg"])[2] == 0
