"""네이버 블로그 시뮬레이터 — Flet 네이티브.

원본(`simulators/naver_blog.py`)이 잡는 문제 그대로: PC 880px ↔ 모바일 390px 폭
차이, 그리고 에디터 텍스트박스보다 실제 발행 화면에서 문단이 훨씬 길어 보이는
타이포(16px/1.8줄간격). `[IMAGE:]` 태그는 문서 순서 그대로 사진을 끼워 넣고,
태그되지 않은 첨부 사진은 경고 배너와 함께 끝에 갤러리로 붙인다 — 원본과 동일.
"""
from __future__ import annotations

import flet as ft

from ai_workers import formatting
from core import storage

from flet_app.theme import BRAND_COLORS

PC_WIDTH = 880
MOBILE_WIDTH = 390


def _avatar() -> ft.Container:
    return ft.Container(
        width=44, height=44, border_radius=22,
        gradient=ft.LinearGradient(
            begin=ft.Alignment.TOP_LEFT, end=ft.Alignment.BOTTOM_RIGHT,
            colors=[BRAND_COLORS["primary"], BRAND_COLORS["accent"]],
        ),
    )


def _figure(rel_path: str, caption: str | None = None) -> ft.Control:
    return ft.Column(
        [
            ft.Image(src=str(storage.abs_path(rel_path)), height=360, fit=ft.BoxFit.CONTAIN),
            ft.Text(caption or "사진 설명을 입력하세요.", size=13, color="#555555" if caption else "#AAAAAA",
                    text_align=ft.TextAlign.CENTER),
        ],
        spacing=6,
    )


def _spans(block: dict, size: int) -> list[ft.TextSpan]:
    """문단 글자에 굵게·형광을 입힌 조각들."""
    text = block["text"]
    style = block["style"]
    if style == "li":
        text = text[2:] if text.startswith("- ") else text
    offset = len(block["text"]) - len(text)
    out, pos = [], 0
    for a, b, kind, _iid in block["spans"]:
        a, b = a - offset, b - offset
        if a < pos or a < 0:
            continue
        if a > pos:
            out.append(ft.TextSpan(text[pos:a]))
        out.append(ft.TextSpan(
            text[a:b],
            style=ft.TextStyle(weight=ft.FontWeight.BOLD) if kind == "bold"
            else ft.TextStyle(bgcolor=formatting.HIGHLIGHT_COLOR),
        ))
        pos = b
    if pos < len(text):
        out.append(ft.TextSpan(text[pos:]))
    return out


def _divider(style: str) -> ft.Control:
    if style == "dotted":
        return ft.Text("· · · · · · · · · · · · · · ·", color="#AAAAAA", text_align=ft.TextAlign.CENTER)
    return ft.Divider(thickness=3 if style == "bold" else 1, color="#333333" if style == "bold" else "#CCCCCC")


def _hint(caption: str, size: int) -> ft.Control:
    return ft.Container(
        content=ft.Text(f"📷 사진 자리 — {caption}", size=size - 2, color="#C62828"),
        border=ft.Border.all(1, "#EF9A9A"), border_radius=6, padding=10, bgcolor="#FFF5F5",
    )


def _text_block(block: dict, size: int) -> ft.Control:
    style = block["style"]
    if style in ("h2", "h3"):
        return ft.Text(spans=_spans(block, size), size=size + (8 if style == "h2" else 4),
                       weight=ft.FontWeight.BOLD, color="#222222")
    body = ft.Text(spans=_spans(block, size), size=size, color="#333333")
    if style == "li":
        return ft.Row([ft.Text("•", size=size, color="#333333"), ft.Container(content=body, expand=True)],
                      vertical_alignment=ft.CrossAxisAlignment.START)
    if style == "quote":
        q = block.get("quote_style") or "quote"
        if q == "line":
            return ft.Container(content=body, border=ft.Border(left=ft.BorderSide(4, "#222222")),
                                padding=ft.Padding.only(left=14, top=4, bottom=4))
        if q == "bubble":
            return ft.Container(content=body, bgcolor="#F1F3F5", border_radius=14, padding=14)
        return ft.Column([
            ft.Text("❝", size=size + 14, color="#BBBBBB"),
            ft.Container(content=ft.Text(spans=_spans(block, size), size=size + 2, color="#333333",
                                         text_align=ft.TextAlign.CENTER), alignment=ft.Alignment.CENTER),
            ft.Text("❞", size=size + 14, color="#BBBBBB", text_align=ft.TextAlign.RIGHT),
        ], spacing=0, horizontal_alignment=ft.CrossAxisAlignment.STRETCH)
    return body


def render(campaign: dict, is_mobile: bool = False, blog_name: str = "공식 블로그") -> ft.Control:
    title = campaign.get("title") or "(제목 없음)"
    content = campaign.get("content") or ""
    attached = campaign.get("storage_file_paths") or []
    hashtags = campaign.get("naver_hashtags") or []

    blocks, unmatched = formatting.bind(content, campaign.get("content_format") or {})
    tagged = {b["path"] for b in blocks if b["kind"] == "image"}
    untagged = [p for p in attached if p not in tagged]
    size = 15 if is_mobile else 16

    body_controls: list[ft.Control] = []
    box_children: list[ft.Control] | None = None
    box_title = ""
    for block in blocks:
        if block["kind"] == "image":
            body_controls.append(_figure(block["path"], block.get("caption")))
            continue
        if block["kind"] == "hint":
            body_controls.append(_hint(block["caption"], size))
            continue
        if block["divider_before"]:
            body_controls.append(_divider(block["divider_before"]))
        control = _text_block(block, size)
        box = block.get("box")
        if box and box["first"]:
            box_children, box_title = [], box["title"]
        if box_children is not None:
            box_children.append(control)
        else:
            body_controls.append(control)
        for caption, _iid in block.get("hints_after") or []:
            (box_children if box_children is not None else body_controls).append(_hint(caption, size))
        if box and box["last"] and box_children is not None:
            body_controls.append(ft.Container(
                content=ft.Column([ft.Text(f"📌 {box_title}", size=size, weight=ft.FontWeight.BOLD)] + box_children, spacing=8),
                bgcolor="#F6F8FA", border=ft.Border.all(1, "#D0D7DE"), border_radius=8, padding=16,
            ))
            box_children = None
    if box_children:
        body_controls += box_children
    if unmatched:
        body_controls.insert(0, ft.Container(
            content=ft.Text(f"🎨 교정·수정으로 문장이 바뀌어 자리를 못 찾은 서식 {len(unmatched)}개는 빠져 있습니다.",
                            size=12, color="#8A6D3B"),
            bgcolor="#FFF6E5", border_radius=6, padding=8,
        ))

    if not body_controls:
        body_controls.append(ft.Text("본문이 비어 있습니다.", color="#999999"))

    if untagged:
        body_controls.append(ft.Container(
            content=ft.Text(
                f"본문에 배치되지 않은 사진 {len(untagged)}장이 글 끝에 붙습니다. "
                "위치를 지정하려면 본문에서 [IMAGE: 경로]를 옮기세요.",
                size=12, color="#C05621",
            ),
            bgcolor="#FFFAF0", border=ft.Border.all(1, "#FBD38D"), border_radius=6, padding=10,
        ))
        for path in untagged:
            body_controls.append(_figure(path))

    controls: list[ft.Control] = [
        ft.Text(title, size=24 if is_mobile else 32, weight=ft.FontWeight.BOLD, color="#222222"),
        ft.Divider(color="#F1F5F9"),
        ft.Row([
            _avatar(),
            ft.Column([
                ft.Text(blog_name, size=15, weight=ft.FontWeight.BOLD, color="#222222"),
                ft.Text("방금 전 · 이웃추가", size=13, color="#888888"),
            ], spacing=2),
        ]),
        ft.Column(body_controls, spacing=20),
    ]
    if hashtags:
        controls.append(ft.Container(
            content=ft.Row(
                [ft.Container(
                    content=ft.Text(t, size=13, color="#2B4C8C"),
                    bgcolor="#F3F6FB", border_radius=999,
                    padding=ft.Padding.symmetric(horizontal=12, vertical=4),
                ) for t in hashtags],
                wrap=True, spacing=6,
            ),
            padding=ft.Padding.only(top=20),
            border=ft.Border(top=ft.BorderSide(1, "#F1F5F9")),
        ))

    width = MOBILE_WIDTH if is_mobile else PC_WIDTH
    return ft.Container(
        width=width,
        height=780 if is_mobile else 1000,
        bgcolor=ft.Colors.WHITE,
        border=ft.Border.all(1, "#E2E8F0"),
        padding=ft.Padding.symmetric(horizontal=20 if is_mobile else 56, vertical=28 if is_mobile else 40),
        content=ft.Column(controls, spacing=16, scroll=ft.ScrollMode.AUTO),
    )


def height(is_mobile: bool = False) -> int:
    return 830 if is_mobile else 1090
