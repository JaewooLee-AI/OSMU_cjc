"""Channel simulators — the OSMU_web workbench's right-hand pane, in Python.

`render(channel, campaign, ...)` returns a complete HTML document for
`st.components.v1.html`; `height(channel, ...)` returns the iframe height it
needs, since Streamlit can't size an iframe to its content automatically.
"""
from __future__ import annotations

from simulators import instagram, naver_blog, shorts, x_thread

CHANNELS = {
    "naver": {"label": "네이버 블로그", "icon": "📗"},
    "instagram": {"label": "인스타그램", "icon": "📸"},
    "x": {"label": "X (트위터)", "icon": "𝕏"},
    "shorts": {"label": "쇼츠 / 릴스", "icon": "🎬"},
}


def render(channel: str, campaign: dict, is_mobile: bool = False, brand_kit: dict = None, **kwargs) -> str:
    brand_kit = brand_kit or {}
    if channel == "naver":
        blog_name = (brand_kit.get("sub_brand") or brand_kit.get("brand_name") or "공식 블로그") + " 공식 블로그"
        return naver_blog.render(campaign, is_mobile=is_mobile, blog_name=blog_name)
    if channel == "instagram":
        return instagram.render(campaign, username=brand_kit.get("instagram_handle") or "cjc_coop")
    if channel == "x":
        return x_thread.render(campaign, display_name=brand_kit.get("sub_brand") or "키노피스")
    if channel == "shorts":
        return shorts.render(
            campaign,
            handle="@" + (brand_kit.get("instagram_handle") or "cjc_coop"),
            show_dead_zone=kwargs.get("show_dead_zone", True),
        )
    raise ValueError(f"Unknown channel: {channel}")


def height(channel: str, is_mobile: bool = False) -> int:
    if channel == "naver":
        return naver_blog.height(is_mobile)
    if channel == "instagram":
        return instagram.height()
    if channel == "x":
        return x_thread.height()
    if channel == "shorts":
        return shorts.height()
    return 700
