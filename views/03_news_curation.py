"""뉴스 큐레이션 — 뉴스잭킹 소재 선택.

This page only *selects* an article. The generation itself happens in the
Workbench, after the marketer attaches photos and a memo, because a 더스티치
post about a trend piece is worth far more with a shot of the actual product
in it than without. That News/Manual unification (both tracks are the same
shape, differing only in the seed material) is why there's one pipeline in
ai_workers/content_writer.py instead of two.
"""
from __future__ import annotations

import streamlit as st

from ai_workers.news_search import search_news_by_keywords
from core import repo
from core.theme import status_chip

st.title("뉴스 큐레이션")
st.caption(
    "브랜드 키워드로 기사를 찾아 워크벤치로 보냅니다. 사진과 메모를 붙인 뒤 초안을 생성하면 "
    "뉴스를 우리 브랜드 관점으로 재해석한 글이 나옵니다."
)

brand_kit = repo.get_brand_kit()
seo_keywords = brand_kit.get("seo_keywords") or []

if not seo_keywords:
    st.info("브랜드 킷에 SEO 키워드가 없습니다. 아래에 직접 검색어를 입력하거나 먼저 키워드를 등록하세요.")

col1, col2 = st.columns([3, 1])
with col1:
    selected_keywords = st.multiselect(
        "검색 키워드 (브랜드 킷의 SEO 키워드)",
        options=seo_keywords,
        default=seo_keywords[:3],
    )
    extra_text = st.text_input(
        "추가 검색어 (쉼표로 구분)",
        placeholder="예: 새활용 산업, 펫 휴머니제이션, 텀블벅 친환경",
    )
with col2:
    limit_per_keyword = st.slider("키워드별 기사 수", min_value=1, max_value=5, value=2)

if st.button("🔍 뉴스 검색", type="primary"):
    extras = [k.strip() for k in extra_text.split(",") if k.strip()]
    all_keywords = list(dict.fromkeys(selected_keywords + extras))
    if not all_keywords:
        st.warning("키워드를 하나 이상 선택하거나 입력하세요.")
    else:
        with st.spinner("Google News / 네이버 뉴스 검색 중…"):
            st.session_state["news_results"] = search_news_by_keywords(all_keywords, limit_per_keyword)
        if not st.session_state["news_results"]:
            st.warning("검색 결과가 없거나, 이미 모두 큐에 등록된 기사입니다.")

results = st.session_state.get("news_results", [])
if results:
    st.caption(f"검색 결과 {len(results)}건 (이미 등록된 기사는 자동 제외)")
    for idx, article in enumerate(results):
        with st.expander(f"📌 [{article['source']}] {article['title']}"):
            if article.get("summary"):
                st.write(article["summary"])
            st.caption(f"검색 키워드: {article.get('matched_keyword', '-')} · [원문 링크]({article['url']})")
            if st.button("➕ 워크벤치로 보내기", key=f"queue_{idx}"):
                # The headline goes to `source_title`, not `title`: Naver
                # treats blog and news as one duplicate-detection space, so a
                # post carrying the publisher's headline is filtered out in
                # favour of the original article. The AI writes its own
                # brand-angle title from the article's content instead.
                created = repo.insert_campaign(
                    source_type="news",
                    source_url=article["url"],
                    source_title=article["title"],
                    status="awaiting_media",
                )
                st.session_state["wb_campaign_id"] = created["id"]
                st.success("워크벤치로 보냈습니다. 사진과 메모를 붙인 뒤 초안을 생성하세요.")

st.divider()
with st.expander("🔗 직접 URL 입력"):
    with st.form("manual_url_form"):
        url = st.text_input("뉴스 URL", placeholder="https://news.example.com/article/123")
        memo = st.text_area("메모 (선택)", placeholder="이 뉴스와 엮고 싶은 자사 맥락")
        submitted = st.form_submit_button("워크벤치로 보내기", type="primary")
    if submitted:
        if not url.strip():
            st.warning("뉴스 URL을 입력하세요.")
        else:
            created = repo.insert_campaign(
                source_type="news", source_url=url.strip(), memo=memo.strip() or None, status="awaiting_media"
            )
            st.session_state["wb_campaign_id"] = created["id"]
            st.success("워크벤치로 보냈습니다.")

st.divider()
st.subheader("뉴스 기반 콘텐츠")
news_campaigns = repo.list_campaigns(source_type="news")
if not news_campaigns:
    st.caption("등록된 뉴스 콘텐츠가 없습니다.")
for c in news_campaigns:
    with st.container(border=True):
        st.markdown(
            f"**{c.get('title') or c.get('source_title') or c.get('source_url')}** "
        f"&nbsp; {status_chip(c['status'])}",
            unsafe_allow_html=True,
        )
        st.caption(f"{c.get('created_at', '')} · 사진 {len(c.get('storage_file_paths') or [])}장")
        if c["status"] == "awaiting_media":
            st.caption("📸 워크벤치에서 사진/메모를 붙이고 초안을 생성하세요.")
