"""Shared UI chrome: brand CSS injection and small HTML render helpers."""
from __future__ import annotations

from pathlib import Path

import streamlit as st

from core.brand_seed import BRAND_COLORS

_CSS_PATH = Path(__file__).resolve().parent.parent / "assets" / "custom.css"

STATUS_LABELS = {
    "awaiting_media": "소재 대기",
    "queued": "대기열",
    "processing": "생성 중",
    "draft": "초안 완료",
    "ready_to_publish": "게시 대기",
    "published": "게시 완료",
    "failed": "실패",
}


def inject_theme() -> None:
    css = _CSS_PATH.read_text(encoding="utf-8")
    st.markdown(f"<style>{css}</style>", unsafe_allow_html=True)


def render_sidebar_brand(brand_kit: dict) -> None:
    name = brand_kit.get("sub_brand") or "키노피스"
    company = brand_kit.get("brand_name") or "씨제이씨협동조합"
    st.sidebar.markdown(
        f"<div class='tb-brand'>🧵 {name} OSMU</div>"
        f"<div class='tb-brand-sub'>{company} · 원소스 멀티유즈 워크벤치</div>",
        unsafe_allow_html=True,
    )


def status_chip(status: str) -> str:
    label = STATUS_LABELS.get(status, status)
    return f"<span class='tb-chip tb-chip-{status}'>{label}</span>"


def stat_card(label: str, value: str, note: str = "") -> str:
    note_html = f"<div class='tb-stat-note'>{note}</div>" if note else ""
    return (
        "<div class='tb-stat-card'>"
        f"<div class='tb-stat-label'>{label}</div>"
        f"<div class='tb-stat-value'>{value}</div>"
        f"{note_html}</div>"
    )


def palette_html() -> str:
    names = {
        "primary": "자주",
        "secondary": "쪽빛",
        "accent": "금박",
        "mint": "옥색",
        "bg": "한지",
        "text": "먹",
    }
    swatches = "".join(
        f"<div class='tb-swatch'><div class='chip' style='background:{BRAND_COLORS[key]}'></div>"
        f"{label}<br>{BRAND_COLORS[key]}</div>"
        for key, label in names.items()
    )
    return f"<div class='tb-palette'>{swatches}</div>"
