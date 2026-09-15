from __future__ import annotations

import streamlit as st

from core import repo, storage
from core.theme import stat_card, status_chip

st.title("파이프라인 대시보드")
st.caption("소재 수집 → 초안 생성 → 게시까지의 진행 상황과, 이번까지 절약된 토큰을 한눈에 봅니다.")

campaigns = repo.list_campaigns()
counts = repo.campaign_status_counts()
usage = repo.usage_totals()
file_count, total_bytes = storage.storage_usage()

active = counts.get("awaiting_media", 0) + counts.get("queued", 0) + counts.get("processing", 0)
drafts = counts.get("draft", 0)
published = counts.get("published", 0)
saved = usage["saved_tokens"]
spent = usage["input_tokens"] + usage["output_tokens"]

col1, col2, col3, col4 = st.columns(4)
with col1:
    st.markdown(stat_card("작업 중", str(active), "소재 대기 + 생성 중"), unsafe_allow_html=True)
with col2:
    st.markdown(stat_card("초안 완료", str(drafts), "검수 후 게시 가능"), unsafe_allow_html=True)
with col3:
    st.markdown(stat_card("게시 완료", str(published), f"사진 {file_count}장 · {total_bytes / 1_048_576:.1f}MB"),
                unsafe_allow_html=True)
with col4:
    ratio = f"절감률 {saved / (saved + spent) * 100:.0f}%" if (saved + spent) else "아직 호출 없음"
    st.markdown(stat_card("절약된 토큰", f"{saved:,}", ratio), unsafe_allow_html=True)

st.markdown("<br>", unsafe_allow_html=True)

COLUMNS = [
    ("awaiting_media", "소재 대기"),
    ("processing", "생성 중"),
    ("draft", "초안 완료"),
    ("ready_to_publish", "게시 대기"),
    ("published", "게시 완료"),
]

board_cols = st.columns(len(COLUMNS))
for board_col, (status_key, column_title) in zip(board_cols, COLUMNS):
    with board_col:
        jobs = [c for c in campaigns if c["status"] == status_key]
        st.markdown(f"<div class='tb-col-title'>{column_title} ({len(jobs)})</div>", unsafe_allow_html=True)
        if not jobs:
            st.caption("항목 없음")
        for job in jobs[:12]:
            icon = "📰" if job.get("source_type") == "news" else "✍️"
            title = job.get("title") or job.get("source_url") or job["id"][:8]
            photos = len(job.get("storage_file_paths") or [])
            st.markdown(
                f"""<div class='tb-job-card'>
                    <div class='tb-job-title'>{icon} {title}</div>
                    <div class='tb-job-meta'>{job.get('created_at', '')} · 사진 {photos}장</div>
                    {status_chip(job['status'])}
                </div>""",
                unsafe_allow_html=True,
            )

failed = [c for c in campaigns if c["status"] == "failed"]
if failed:
    st.divider()
    st.subheader("⚠️ 실패한 작업")
    for job in failed:
        with st.container(border=True):
            st.markdown(f"**{job.get('title') or job.get('source_url') or job['id'][:8]}**")
            st.caption(job.get("publish_error") or "원인 미기록")
            col_a, col_b = st.columns([1, 5])
            if col_a.button("🔁 다시 시도", key=f"retry_{job['id']}"):
                repo.update_campaign(job["id"], status="awaiting_media", publish_error=None)
                st.rerun()
            if col_b.button("🗑️ 삭제", key=f"del_{job['id']}"):
                repo.delete_campaign(job["id"])
                st.rerun()

st.divider()
if st.button("🔄 새로고침"):
    st.rerun()

st.divider()
with st.expander("⚠️ 콘텐츠 초기화"):
    st.caption(
        "워크벤치·뉴스 큐레이션·네이버 게시로 만들어진 것만 지웁니다 — 캠페인(초안·인스타/X/쇼츠·"
        "컴플라이언스 리포트), 업로드한 사진, 제목 반복 방지 이력. **브랜드 킷, API 키, LLM 설정, "
        "키워드·이미지 분석 캐시는 그대로 남습니다.**"
    )
    st.markdown(
        f"- 캠페인 **{len(campaigns)}건**\n"
        f"- 업로드 사진 **{file_count}장** ({total_bytes / 1_048_576:.1f}MB)\n"
        f"- 제목 이력 **{repo.title_history_count()}건**"
    )

    if "confirm_content_reset" not in st.session_state:
        st.session_state["confirm_content_reset"] = False

    if not st.session_state["confirm_content_reset"]:
        if st.button("🗑️ 콘텐츠 초기화", key="ask_content_reset"):
            st.session_state["confirm_content_reset"] = True
            st.rerun()
    else:
        st.warning(
            "정말 삭제할까요? **되돌릴 수 없습니다.** 위에 적힌 캠페인·사진·제목 이력이 "
            "전부 사라집니다."
        )
        c1, c2 = st.columns(2)
        if c1.button("네, 초기화합니다", key="confirm_content_reset_btn", type="primary"):
            removed = repo.reset_generated_content()
            files_removed = storage.clear_all()
            st.session_state["confirm_content_reset"] = False
            st.success(
                f"초기화했습니다 — 캠페인 {removed['campaigns']}건, 사진 {files_removed}장, "
                f"제목 이력 {removed['titles']}건 삭제됨."
            )
            st.rerun()
        if c2.button("취소", key="cancel_content_reset"):
            st.session_state["confirm_content_reset"] = False
            st.rerun()
