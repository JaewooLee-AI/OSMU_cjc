"""네이버 블로그 반자동 게시.

Naver actively blocks bot-driven posting into Smart Editor ONE, so this is
deliberately *semi*-automatic: a real Chrome window opens with the saved
login session, the worker types the title and pastes body/photos in document
order, and the marketer clicks [발행] themselves. The 발행 popup's tag field
can't be driven at all, so the generated tags are shown here to copy.
"""
from __future__ import annotations

import streamlit as st
import streamlit.components.v1 as components

import simulators
from ai_workers.naver_publisher import (
    clear_naver_session,
    naver_session_exists,
    open_naver_login_session,
    split_publish_error,
    trigger_naver_publish,
)
from core import repo

st.title("네이버 블로그 반자동 게시")
st.caption(
    "[지금 게시]를 누르면 Chrome 창이 열리고 제목·본문·사진이 자동으로 입력됩니다. "
    "내용을 확인한 뒤 마지막 [발행] 버튼만 그 창에서 직접 눌러주세요."
)

brand_kit = repo.get_brand_kit()
naver_blog_id = (brand_kit.get("naver_blog_id") or "").strip()

def _login_prompt() -> None:
    if st.button("🔓 네이버 로그인", disabled=not naver_blog_id, width='stretch'):
        with st.spinner("Chrome 창에서 네이버 로그인을 완료해주세요 (최대 2분 대기)…"):
            result = open_naver_login_session(naver_blog_id)
        st.success(result["message"]) if result["success"] else st.error(result["message"])
        st.rerun()


# Logged in is the normal state, so it collapses to a single status line with a
# logout button. The full block only appears when there's something to do —
# every row this section spends is a row the 게시 완료 목록 below is pushed off
# the first screen by.
if naver_session_exists():
    status_col, logout_col = st.columns([4, 1])
    status_col.success(f"🔑 네이버 로그인됨 (blog.naver.com/{naver_blog_id})")
    with logout_col:
        if st.button("🧹 로그아웃", width='stretch'):
            clear_naver_session()
            st.rerun()
else:
    st.markdown("#### 🔑 네이버 로그인")
    col1, col2 = st.columns([3, 1])
    with col1:
        st.warning("아직 로그인하지 않았습니다. 게시하려면 먼저 로그인해주세요.")
        if not naver_blog_id:
            st.info("브랜드 킷에서 네이버 블로그 아이디를 먼저 등록해주세요.")
        st.caption("로그인 정보는 이 컴퓨터에만 저장되며, 언제든 [로그아웃]으로 지울 수 있습니다.")
    with col2:
        _login_prompt()

st.divider()


def _card_actions(
    campaign: dict, key_prefix: str, publish_label: str, allow_manual_complete: bool = False
) -> None:
    """One fixed-height action row per card.

    Deleting asks first — the dashboard removes failed jobs on a single click,
    but a row here holds a finished draft, and one stray click would throw away
    a whole generation run. The confirmation *replaces* the buttons in place
    rather than adding a warning block below them: on a short window the card
    would otherwise grow past the bottom edge, putting the confirm buttons
    exactly where they can't be reached.

    Only the campaign row is deleted; attached photos stay on disk because
    core/storage.py stores them content-addressed and shares one file across
    every campaign that uploaded the same image.

    `allow_manual_complete` adds a second, independent way to reach
    'published': every other path to that status runs inside
    naver_paste_worker.py, which only exists once the marketer has logged in
    through this app's browser automation. A marketer who never logs in —
    copying title/body/tags out of [본문 보기] and pasting them into Naver by
    hand instead — had no way to ever move a campaign out of '게시 대기'. It
    sat there forever, and worse, it kept disappearing from nowhere: workbench
    hides only 'published' campaigns, so a hand-published one stayed visible
    there too, looking unfinished after it was already live.
    """
    campaign_id = campaign["id"]
    state_key = f"confirm_del_{key_prefix}_{campaign_id}"

    if st.session_state.get(state_key):
        left, right, note = st.columns([1, 1, 3])
        if left.button("🗑️ 삭제 확인", key=f"{state_key}_yes", type="primary", width='stretch'):
            repo.delete_campaign(campaign_id)
            st.session_state.pop(state_key, None)
            st.toast("삭제했습니다.")
            st.rerun()
        if right.button("취소", key=f"{state_key}_no", width='stretch'):
            st.session_state.pop(state_key, None)
            st.rerun()
        note.caption("삭제하면 되돌릴 수 없습니다.")
        return

    if allow_manual_complete:
        left, manual, right = st.columns([1, 1, 1])
    else:
        left, right = st.columns([1, 1])
        manual = None

    with left:
        if st.button(
            publish_label,
            key=f"{key_prefix}_{campaign_id}",
            width='stretch',
            disabled=not naver_session_exists(),
            help=None if naver_session_exists() else "먼저 네이버에 로그인해주세요.",
        ):
            result = trigger_naver_publish(campaign_id)
            st.success(result["message"]) if result["success"] else st.error(result["message"])
    if allow_manual_complete:
        with manual:
            if st.button(
                "✅ 수동으로 완료",
                key=f"manual_{campaign_id}",
                width='stretch',
                help="위 [본문 보기]에서 복사해 네이버에 직접 붙여넣고 발행했다면 여기를 눌러주세요.",
            ):
                repo.update_campaign(campaign_id, status="published", publish_error=None)
                st.toast("게시 완료로 표시했습니다.")
                st.rerun()
    if right.button("🗑️ 삭제", key=f"{state_key}_ask", width='stretch'):
        st.session_state[state_key] = True
        st.rerun()


def _render_publish_error(campaign: dict) -> None:
    summary, detail = split_publish_error(campaign.get("publish_error") or "")
    if not summary:
        return
    st.error(summary)
    if detail:
        with st.expander("자세한 오류 내용"):
            st.code(detail, language=None)


def _copy_field(label: str, text: str, help_text: str = "") -> None:
    """읽기 전용 블록 + Streamlit 기본 복사 버튼. 채널마다 별도 창을 만들지
    않고 이 화면 안에서 바로 복사해 다른 앱에 붙여넣을 수 있게 합니다."""
    st.caption(f"**{label}**" + (f" — {help_text}" if help_text else ""))
    st.code(text or "(비어 있음)", language=None, wrap_lines=True)


def _render_content_preview(campaign: dict) -> None:
    """이 캠페인의 네 채널을 전부 조회·복사할 수 있게 합니다.

    네이버 발행이 끝나면(published) 워크벤치 목록에서 이 캠페인이 사라지는데,
    인스타·X·쇼츠는 자동 발행이 없어 담당자가 여전히 손으로 옮겨야 한다 —
    그런데 옮길 재료를 볼 곳(워크벤치)이 이미 사라진 뒤였다. 워크벤치의 채널
    시뮬레이터를 그대로 재사용해 네이버 발행 여부와 무관하게 네 채널을 전부
    이 화면에서 볼 수 있게 한다.

    네이버 채널에는 제목·본문 복사 필드도 함께 둔다 — 로그인 자동화 없이
    수동으로 붙여넣는 담당자에게는 시각 미리보기만으로는 복사할 원문이
    없었다.
    """
    with st.expander("📄 콘텐츠 보기 (전체 채널)"):
        channel_keys = list(simulators.CHANNELS.keys())
        channel = st.radio(
            "채널",
            options=channel_keys,
            format_func=lambda k: f"{simulators.CHANNELS[k]['icon']} {simulators.CHANNELS[k]['label']}",
            horizontal=True,
            label_visibility="collapsed",
            key=f"preview_channel_{campaign['id']}",
        )
        html = simulators.render(channel, campaign, brand_kit=brand_kit)
        components.html(html, height=simulators.height(channel), scrolling=True)

        st.divider()
        if channel == "naver":
            _copy_field("제목", campaign.get("title") or "")
            _copy_field("본문", campaign.get("content") or "")
        elif channel == "instagram":
            _copy_field("캡션", campaign.get("instagram_caption") or "")
            tags = campaign.get("instagram_hashtags") or []
            if tags:
                _copy_field("해시태그", " ".join(tags))
        elif channel == "x":
            tweets = campaign.get("x_content") or []
            for i, tweet in enumerate(tweets, start=1):
                _copy_field(f"트윗 {i}/{len(tweets)}", tweet, f"{len(tweet)}자")
            tags = campaign.get("x_hashtags") or []
            if tags:
                _copy_field("해시태그", " ".join(tags))
        elif channel == "shorts":
            script = campaign.get("shorts_script") or {}
            if script.get("title"):
                _copy_field("제목", script["title"])
            if script.get("hook"):
                _copy_field("훅 (첫 3초)", script["hook"])
            if script.get("scenes"):
                _copy_field(
                    "자막 전체",
                    "\n".join(
                        f"CUT {i}. {s.get('caption', '')}"
                        for i, s in enumerate(script["scenes"], start=1)
                    ),
                )
            if script.get("hashtags"):
                _copy_field("해시태그", " ".join(script["hashtags"]))


pending = repo.list_campaigns(statuses=["ready_to_publish"])
# "게시 완료"는 브라우저에 제목·본문·사진을 모두 붙여넣었다는 뜻입니다. 담당자가 네이버
# 에디터의 [발행]을 실제로 눌렀는지는 외부 브라우저 창 안의 클릭이라 이 앱이 알 수
# 없으므로, 완료 건도 남겨두고 다시 게시할 수 있게 합니다.
published = repo.list_campaigns(statuses=["published"])

# Tabs, not two stacked sections: only one list is ever being worked on, and
# stacking them pushed the 게시 완료 카드의 버튼을 첫 화면 밖으로 밀어냈습니다.
# (A tab also survives a rerun, which the expander this used to be didn't —
# deleting one post collapsed the list every time.)
tab_pending, tab_published = st.tabs([f"게시 대기 {len(pending)}", f"게시 완료 {len(published)}"])

with tab_pending:
    if not pending:
        st.caption("게시 대기 중인 콘텐츠가 없습니다. 워크벤치에서 [네이버 게시 대기열로]를 눌러 보내세요.")
    for c in pending:
        with st.container(border=True):
            icon = "📰" if c["source_type"] == "news" else "✍️"
            st.markdown(f"**{icon} {c.get('title') or '(제목 없음)'}**")
            st.caption(f"업데이트: {c.get('updated_at', '')} · 사진 {len(c.get('storage_file_paths') or [])}장")
            if c.get("source_url"):
                st.caption(f"📰 원문: {c['source_url']}")
            _render_publish_error(c)
            _render_content_preview(c)
            hashtags = c.get("naver_hashtags") or []
            if hashtags:
                st.caption("🏷️ 태그는 자동으로 입력되지 않습니다. 아래를 복사해 [발행] 창의 태그 칸에 붙여넣어 주세요.")
                st.code(" ".join(hashtags), language=None)
            st.caption(
                "직접 로그인 없이 [📄 콘텐츠 보기]에서 복사해 네이버에 손으로 붙여넣었다면, "
                "아래 [✅ 수동으로 완료]를 눌러 이 목록에서 정리하세요."
            )
            _card_actions(c, "pending", "🚀 지금 게시", allow_manual_complete=True)

with tab_published:
    if not published:
        st.caption("게시 완료된 콘텐츠가 없습니다.")
    else:
        st.caption(
            "네이버 창에서 [발행]을 누르지 못했다면 [다시 게시]로 같은 내용을 다시 불러올 수 있습니다. "
            "더 이상 필요 없는 글은 [삭제]로 목록에서 지우세요."
        )
    for c in published:
        with st.container(border=True):
            st.markdown(f"**{c.get('title') or '(제목 없음)'}**")
            st.caption(f"게시: {c.get('updated_at', '')}")
            if c.get("source_url"):
                st.caption(f"📰 원문: {c['source_url']}")
            _render_publish_error(c)
            _render_content_preview(c)
            hashtags = c.get("naver_hashtags") or []
            if hashtags:
                st.caption("🏷️ [발행] 창 태그 칸에 붙여넣을 해시태그")
                st.code(" ".join(hashtags), language=None)
            _card_actions(c, "published", "🔁 다시 게시")
