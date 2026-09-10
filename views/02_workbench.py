"""통합 워크벤치 — OSMU_web의 2분할 에디터/시뮬레이터를 Streamlit으로 옮긴 화면.

Left pane edits the single source (memo + photos, then the generated body);
right pane renders it through each channel's real layout. In OSMU_web the two
panes were bound by a Zustand store for zero-latency typing; here Streamlit's
rerun model gives a keystroke-to-render round trip instead, which is the one
genuine downgrade from merging the apps. It's an acceptable trade for this
team's actual workflow: the simulators are used to *check* a finished draft
before publishing, not to watch text reflow while typing.

Generation runs inline (ai_workers/content_writer.run_pipeline) with a
`st.status` panel driven by the pipeline's progress callback — no queue, no
separate worker process, no polling.
"""
from __future__ import annotations

import streamlit as st
import streamlit.components.v1 as components

import simulators
from ai_workers import content_mode, vision
from ai_workers.content_writer import LENGTH_MODES, revise_content, run_pipeline
from core import repo, storage

st.title("워크벤치")

brand_kit = repo.get_brand_kit()
campaigns = repo.list_campaigns()
editable = [c for c in campaigns if c["status"] != "published"]


# --- campaign selection -----------------------------------------------------

def _label(c: dict) -> str:
    icon = "📰" if c["source_type"] == "news" else "✍️"
    # Falls back to the source headline so a news campaign is still
    # recognisable before the AI has written its own title.
    title = c.get("title") or c.get("source_title") or c.get("source_url") or "(제목 없음)"
    return f"{icon} {title[:44]} · {c['status']}"


def refresh_editor_state(campaign_id: str) -> None:
    """Drops cached widget values so the editors re-read from the database.

    Streamlit's `value=` is only an *initial* value: once a widget key exists
    in session_state it wins on every later rerun. The pipeline rewrites the
    title and body behind the widgets' backs, so without this the 제목 box
    keeps whatever it was showing before the run (empty, for a news campaign
    queued before generation) — and pressing 저장 would then write that stale
    value back over the generated one.
    """
    for prefix in ("title", "memo", "body", "ntags", "igcap", "igtags", "xbody", "xtags", "revreq"):
        key = f"{prefix}_{campaign_id}"
        if key in st.session_state:
            del st.session_state[key]


def copy_field(label: str, text: str, help_text: str = "") -> None:
    """A read-only block with Streamlit's built-in copy button.

    `st.code` renders that button in the browser, so copying works from any
    machine viewing the app — unlike core.clipboard_utils, which drives the
    clipboard of the host running Streamlit and exists for the Naver
    automation's rich-HTML paste. Here the marketer is pasting plain text into
    Naver/Instagram/X by hand, so the browser button is the right tool.
    """
    st.caption(f"**{label}**" + (f" — {help_text}" if help_text else ""))
    st.code(text or "(비어 있음)", language=None, wrap_lines=True)


def _is_untouched_draft(c: dict) -> bool:
    """A manual draft the marketer never actually put anything into — safe
    to hand back on the next '새 콘텐츠' click instead of piling up another
    empty row every time the button is clicked with nothing written yet."""
    return (
        c["source_type"] == "manual"
        and c["status"] == "awaiting_media"
        and not (c.get("title") or "").strip()
        and not (c.get("memo") or "").strip()
        and not c.get("storage_file_paths")
    )


top_left, top_mid, top_right = st.columns([3, 1, 1])
with top_left:
    if editable:
        options = [c["id"] for c in editable]
        lookup = {c["id"]: c for c in editable}
        default_idx = 0
        if st.session_state.get("wb_campaign_id") in options:
            default_idx = options.index(st.session_state["wb_campaign_id"])
        selected_id = st.selectbox(
            "작업할 콘텐츠",
            options=options,
            index=default_idx,
            format_func=lambda cid: _label(lookup[cid]),
            label_visibility="collapsed",
        )
        st.session_state["wb_campaign_id"] = selected_id
    else:
        selected_id = None
        st.info("작업 중인 콘텐츠가 없습니다. 오른쪽에서 새로 시작하거나, 뉴스 큐레이션에서 기사를 가져오세요.")
with top_mid:
    # Deletion lives next to the dropdown, not gated behind a generated draft
    # or a publish action — a campaign stuck empty from a past error (no
    # content, never reaching '게시 대기') still needs a way out.
    if selected_id and st.button("🗑️ 삭제", width='stretch', key="delete_selected_campaign"):
        repo.delete_campaign(selected_id)
        st.session_state.pop("wb_campaign_id", None)
        st.rerun()
with top_right:
    if st.button("➕ 새 콘텐츠", width='stretch', type="primary"):
        reusable = next((c for c in editable if _is_untouched_draft(c)), None)
        if reusable:
            st.session_state["wb_campaign_id"] = reusable["id"]
        else:
            created = repo.insert_campaign(source_type="manual", status="awaiting_media")
            st.session_state["wb_campaign_id"] = created["id"]
        st.rerun()

if not selected_id:
    st.stop()

campaign = repo.get_campaign(selected_id)
if not campaign:
    st.session_state.pop("wb_campaign_id", None)
    st.rerun()

editor_col, sim_col = st.columns([1, 1], gap="large")


# --- left pane: the single source ------------------------------------------

with editor_col:
    if campaign.get("source_url"):
        st.caption(f"📰 원문: [{campaign['source_url'][:70]}]({campaign['source_url']})")
    if campaign.get("source_title"):
        st.caption(
            f"🗞️ 원 기사 제목: *{campaign['source_title']}* — 참고용입니다. "
            "네이버는 블로그와 뉴스를 같은 유사문서 판정 대상으로 보므로, "
            "이 제목을 그대로 쓰면 원본 기사에 밀려 검색에서 빠집니다."
        )

    title = st.text_input(
        "제목",
        value=campaign.get("title") or "",
        placeholder="비워두면 AI가 25자 이내로 지어줍니다",
        key=f"title_{selected_id}",
    )
    memo = st.text_area(
        "담당자 메모 (초안의 씨앗)",
        value=campaign.get("memo") or "",
        height=150,
        placeholder="예: 성수동 팝업 3일차. 리본핀이 제일 먼저 팔림. 20대 손님이 색감 보고 골랐다가 새활용인 걸 나중에 알고 좋아함.",
        key=f"memo_{selected_id}",
    )

    st.markdown("##### 🎚️ 콘텐츠 모드")
    brand_default = content_mode.resolve(None, brand_kit)
    mode_keys = content_mode.ORDER
    current_mode = campaign.get("content_mode")
    mode_index = mode_keys.index(current_mode) if current_mode in mode_keys else mode_keys.index(brand_default["key"])
    chosen_mode = st.radio(
        "콘텐츠 모드",
        options=mode_keys,
        index=mode_index,
        horizontal=True,
        format_func=lambda k: f"{content_mode.MODES[k]['icon']} {content_mode.MODES[k]['label']}",
        key=f"mode_{selected_id}",
        label_visibility="collapsed",
    )
    st.caption(content_mode.MODES[chosen_mode]["caption"])
    if current_mode is None:
        st.caption(
            f"· 이 글은 아직 개별 지정 없이 브랜드 기본값({brand_default['icon']} "
            f"{brand_default['label']})을 따릅니다. 저장하면 이 글에 고정됩니다."
        )

    st.markdown("##### 📷 사진")
    uploads = st.file_uploader(
        "사진 첨부 (업로드 시 1280px JPEG로 자동 축소 저장)",
        type=["jpg", "jpeg", "png", "webp", "heic"],
        accept_multiple_files=True,
        key=f"upload_{selected_id}",
        label_visibility="collapsed",
    )
    attached = list(campaign.get("storage_file_paths") or [])

    if uploads:
        added = []
        for upload in uploads:
            rel = storage.save_upload(upload.getvalue(), upload.name)
            if rel not in attached:
                attached.append(rel)
                added.append(rel)
        if added:
            repo.update_campaign(selected_id, storage_file_paths=attached)
            st.rerun()

    if attached:
        # A square-cropped HTML strip rather than st.image in columns: photos
        # arrive in mixed portrait/landscape orientations, and st.image sizes
        # each to its own aspect ratio, which left the per-photo 제거 buttons
        # at different vertical offsets and unmatched to their thumbnail.
        thumbs = "".join(
            f"<div style='flex:1;min-width:0;'>"
            f"<div style='aspect-ratio:1;border-radius:8px;overflow:hidden;border:1px solid #E8DFD4;'>"
            f"<img src='{storage.data_uri(rel, 260)}' "
            f"style='width:100%;height:100%;object-fit:cover;display:block;'></div>"
            f"<div style='font-size:.65rem;color:#8A7B6B;text-align:center;margin-top:3px;'>{idx + 1}</div>"
            f"</div>"
            for idx, rel in enumerate(attached)
        )
        st.markdown(
            f"<div style='display:flex;gap:8px;margin-bottom:8px;'>{thumbs}</div>",
            unsafe_allow_html=True,
        )
        remove_cols = st.columns(len(attached))
        for idx, rel in enumerate(attached):
            if remove_cols[idx].button(f"🗑️ {idx + 1}", key=f"rm_{selected_id}_{idx}", width="stretch"):
                repo.update_campaign(selected_id, storage_file_paths=[p for p in attached if p != rel])
                st.rerun()
    else:
        st.caption("첨부된 사진이 없습니다.")

    # --- token cost preview, before committing to a run ---
    if attached:
        est = vision.preview_cost(attached)
        preset = vision.QUALITY_PRESETS.get(est["quality"], {})
        st.markdown(
            f"""<div class='tb-card'>
            🪙 <b>이미지 분석 예상 비용</b> — 사진 {est['images']}장 중
            <b>{est['cached']}장은 캐시 적중(추가 비용 0)</b>, {est['to_analyze']}장만 분석합니다.<br>
            예상 입력 토큰 <b>약 {est['est_tokens']:,}</b>
            (화질 <code>{preset.get('label', est['quality'])}</code>, 장당 {est.get('per_image', 0)}토큰,
            {vision.MAX_IMAGES_PER_CALL}장씩 한 번에 묶어 호출)
            </div>""",
            unsafe_allow_html=True,
        )

    save_col, gen_col = st.columns([1, 1])
    if save_col.button("💾 저장", width='stretch'):
        repo.update_campaign(
            selected_id, title=title.strip() or None, memo=memo, content_mode=chosen_mode
        )
        st.toast("저장했습니다.")

    can_generate = bool(memo.strip() or campaign.get("source_url"))
    if gen_col.button("🪄 초안 생성", type="primary", width='stretch', disabled=not can_generate):
        repo.update_campaign(
            selected_id, title=title.strip() or None, memo=memo, content_mode=chosen_mode
        )
        with st.status("초안을 만드는 중…", expanded=True) as status_box:
            try:
                run_pipeline(selected_id, progress=lambda msg: status_box.write(msg))
                status_box.update(label="초안 생성 완료", state="complete")
            except Exception as exc:  # noqa: BLE001
                status_box.update(label=f"실패: {exc}", state="error")
        refresh_editor_state(selected_id)
        st.rerun()

    if not can_generate:
        st.caption("메모를 입력하거나 뉴스 기사를 연결해야 초안을 생성할 수 있습니다.")

    # --- generated output, editable ---
    if campaign.get("content"):
        st.divider()
        st.markdown("##### ✏️ 생성된 콘텐츠")

        tab_naver, tab_ig, tab_x, tab_shorts = st.tabs(["네이버 본문", "인스타 캡션", "X 스레드", "쇼츠 자막"])

        with tab_naver:
            # Shows the title input at the top of this pane rather than adding
            # a second editable one: two inputs bound to the same column mean
            # saving from one silently reverts an unsaved edit in the other.
            st.caption(f"**제목** · {len(title)}자")
            st.markdown(f"### {title or '(제목 없음)'}")
            body = st.text_area(
                "본문 (`[IMAGE: 경로]` 위치를 옮기면 사진 배치가 바뀝니다)",
                value=campaign.get("content") or "",
                height=340,
                key=f"body_{selected_id}",
            )
            tags = st.text_input(
                "발행 태그",
                value=" ".join(campaign.get("naver_hashtags") or []),
                key=f"ntags_{selected_id}",
            )
            if st.button("본문 저장", key=f"save_body_{selected_id}"):
                repo.update_campaign(
                    selected_id,
                    title=title.strip() or None,
                    content=body,
                    naver_hashtags=[t for t in tags.split() if t.strip()],
                )
                st.rerun()

            with st.expander("📋 복사해서 네이버에 직접 붙여넣기"):
                st.caption(
                    "각 칸 오른쪽 위 복사 아이콘을 눌러 네이버 에디터에 순서대로 붙여넣으세요. "
                    "저장하지 않은 편집 내용도 그대로 복사됩니다."
                )
                copy_field("제목", title)
                copy_field(
                    "본문", body,
                    "`[IMAGE: …]` 자리에 해당 순서의 사진을 넣으면 됩니다",
                )
                copy_field("발행 태그", tags)

            st.markdown("###### ✏️ 수정 요청해서 다시 쓰기")
            st.caption(
                f"현재 {len(body)}자. 위 편집창의 내용을 그대로 이어받아 고쳐 씁니다 "
                "— 메모부터 새로 쓰는 '초안 다시 생성'과 달리 담당자 수정분이 유지됩니다."
            )
            revise_instruction = st.text_area(
                "수정 요청",
                placeholder="예: 도입부를 더 친근한 말투로 바꾸고, 가격 이야기는 빼주세요.",
                height=80,
                key=f"revreq_{selected_id}",
                label_visibility="collapsed",
            )
            len_col, btn_col = st.columns([2, 1])
            length_label = len_col.radio(
                "분량",
                options=[spec["label"] for spec in LENGTH_MODES.values()],
                horizontal=True,
                key=f"revlen_{selected_id}",
                label_visibility="collapsed",
            )
            length_mode = next(k for k, v in LENGTH_MODES.items() if v["label"] == length_label)

            if btn_col.button("✏️ 수정 반영", type="primary", width="stretch", key=f"revbtn_{selected_id}"):
                # Persist the editor's current text first, so the revision
                # starts from what the marketer sees rather than from the last
                # saved version. Runs even with no request —맞춤법 교정만으로도
                # 의미가 있습니다.
                repo.update_campaign(selected_id, content=body)
                with st.status("수정 반영 중…", expanded=True) as status_box:
                    try:
                        revise_content(
                            selected_id,
                            instruction=revise_instruction,
                            length_mode=length_mode,
                            progress=lambda msg: status_box.write(msg),
                        )
                        status_box.update(label="수정 완료", state="complete")
                    except Exception as exc:  # noqa: BLE001
                        status_box.update(label=f"실패: {exc}", state="error")
                refresh_editor_state(selected_id)
                st.rerun()
            st.caption("요청 없이 눌러도 맞춤법·오탈자 교정은 항상 실행됩니다.")

        with tab_ig:
            caption = st.text_area(
                "캡션 (첫 125자가 '더보기' 앞에 노출됩니다)",
                value=campaign.get("instagram_caption") or "",
                height=220,
                key=f"igcap_{selected_id}",
            )
            st.caption(f"현재 {len(caption)}자 — 훅은 앞 125자 안에 들어가야 합니다.")
            ig_tags = st.text_input(
                "해시태그",
                value=" ".join(campaign.get("instagram_hashtags") or []),
                key=f"igtags_{selected_id}",
            )
            if st.button("캡션 저장", key=f"save_ig_{selected_id}"):
                repo.update_campaign(
                    selected_id,
                    instagram_caption=caption,
                    instagram_hashtags=[t for t in ig_tags.split() if t.strip()],
                )
                st.rerun()

            with st.expander("📋 복사해서 인스타그램에 직접 붙여넣기"):
                copy_field("캡션", caption)
                copy_field("해시태그", ig_tags)
                copy_field(
                    "캡션 + 해시태그 (한 번에)",
                    f"{caption}\n\n{ig_tags}".strip(),
                    "해시태그를 캡션 본문에 함께 넣을 때",
                )

        with tab_x:
            tweets = campaign.get("x_content") or []
            joined = st.text_area(
                "트윗 (빈 줄로 구분하면 각각 하나의 트윗이 됩니다)",
                value="\n\n".join(tweets),
                height=220,
                key=f"xbody_{selected_id}",
            )
            x_tags = st.text_input(
                "해시태그 (1~2개 권장)",
                value=" ".join(campaign.get("x_hashtags") or []),
                key=f"xtags_{selected_id}",
            )
            if st.button("스레드 저장", key=f"save_x_{selected_id}"):
                repo.update_campaign(
                    selected_id,
                    x_content=[t.strip() for t in joined.split("\n\n") if t.strip()],
                    x_hashtags=[t for t in x_tags.split() if t.strip()],
                )
                st.rerun()

            with st.expander("📋 복사해서 X에 직접 붙여넣기"):
                st.caption(
                    "X는 트윗을 하나씩 이어 올려야 하므로 트윗별로 나눠 복사합니다. "
                    "해시태그는 보통 마지막 트윗에 붙입니다."
                )
                current_tweets = [t.strip() for t in joined.split("\n\n") if t.strip()]
                for idx, tweet in enumerate(current_tweets, start=1):
                    copy_field(f"트윗 {idx}/{len(current_tweets)}", tweet, f"{len(tweet)}자")
                copy_field("해시태그", x_tags)

        with tab_shorts:
            script = campaign.get("shorts_script") or {}
            if script.get("scenes"):
                st.write(f"**{script.get('title', '')}**")
                for i, scene in enumerate(script["scenes"], start=1):
                    st.markdown(f"**CUT {i}** — {scene.get('caption', '')}")
                    st.caption(scene.get("shot", ""))

                with st.expander("📋 복사해서 영상 편집기에 붙여넣기"):
                    copy_field("제목", script.get("title", ""))
                    if script.get("hook"):
                        copy_field("훅 (첫 3초)", script["hook"])
                    copy_field(
                        "자막 전체",
                        "\n".join(
                            f"CUT {i}. {s.get('caption', '')}"
                            for i, s in enumerate(script["scenes"], start=1)
                        ),
                    )
                    if script.get("hashtags"):
                        copy_field("해시태그", " ".join(script["hashtags"]))
            else:
                st.caption("쇼츠 구성안이 아직 없습니다.")

        st.divider()
        act_a, act_b = st.columns(2)
        if act_a.button("🚀 네이버 게시 대기열로", type="primary", width='stretch'):
            repo.update_campaign(selected_id, status="ready_to_publish")
            st.success("게시 대기열에 넣었습니다. [네이버 게시] 페이지에서 진행하세요.")
        if act_b.button("🔁 초안 다시 생성", width='stretch'):
            with st.status("다시 생성 중…", expanded=True) as status_box:
                try:
                    run_pipeline(selected_id, progress=lambda msg: status_box.write(msg))
                    status_box.update(label="완료", state="complete")
                except Exception as exc:  # noqa: BLE001
                    status_box.update(label=f"실패: {exc}", state="error")
            refresh_editor_state(selected_id)
            st.rerun()

        report = campaign.get("guardrail_report")
        if report:
            with st.expander("🛡️ 컴플라이언스 / SEO 리포트"):
                if report.get("compliance_pass") is None:
                    st.caption("가드레일이 꺼진 상태로 생성되어 검수를 건너뛰었습니다.")
                else:
                    icon = "✅" if report.get("compliance_pass") else "⚠️"
                    st.markdown(f"{icon} **환경성 표시·광고 검수 점수: {report.get('score', '-')}/100**")
                    for strength in report.get("strengths") or []:
                        st.caption(f"👍 {strength}")
                    for hit in report.get("dictionary_hits") or []:
                        st.caption(f"🚫 자동 치환(이미 반영됨): {hit['forbidden']} → {hit['replacement']}")
                    for issue in report.get("llm_issues") or []:
                        st.caption(f"🤖 {issue}")
                    for issue in report.get("resolved_issues") or []:
                        st.caption(f"✅ (교정되어 이미 해결됨) {issue}")
                    for issue in report.get("unverified_issues") or []:
                        st.caption(f"❓ (검증 안 됨, 참고용) {issue}")
                used_mode = report.get("content_mode")
                if used_mode:
                    st.caption(f"🎚️ 생성 모드: **{content_mode.label_of(used_mode)}**")
                for hit in report.get("title_dictionary_hits") or []:
                    st.caption(
                        f"🛡️ 제목 금기어 치환: '{hit['forbidden']}' → '{hit['replacement']}'"
                    )

                density = report.get("seo_density")
                if density and density.get("enforced") is False:
                    counts = density.get("counts") or {}
                    st.caption(
                        "📖 내용 우선 모드 — 키워드 밀도를 강제하지 않았습니다. "
                        + (
                            f"자연스럽게 등장한 횟수: {counts}"
                            if counts
                            else "이 글에는 브랜드 키워드가 등장하지 않았습니다."
                        )
                    )
                elif report.get("seo_targets") == [] and (report.get("seo_pool") or []) and used_mode != "rich":
                    # Not an error in this draft — the pool has no keyword for
                    # what this post is about. See select_target_keywords.
                    st.caption(
                        "🎯 SEO 타깃 없음 — 이 글의 소재에 맞는 키워드가 브랜드 킷 목록에 "
                        "없습니다. 키워드를 억지로 끼워 넣는 대신 소재에 충실하게 썼습니다. "
                        "이 주제로 검색 노출을 노리시려면 🧵 브랜드 킷에 해당 분야 키워드를 "
                        "추가하세요 (예: 교육·강의 소재라면 교육 계열 키워드)."
                    )
                if (
                    density
                    and density.get("status") != "no_keywords"
                    and density.get("enforced") is not False
                ):
                    icon = {"optimal": "✅", "low": "📉", "high": "📈"}.get(density["status"], "•")
                    targets = report.get("seo_targets") or []
                    label = f" — 이번 글 타깃: {', '.join(targets)}" if targets else ""
                    st.caption(f"{icon} SEO 키워드 밀도: {density['status']}{label}")
                    st.json(density.get("counts") or {}, expanded=False)
                    skipped = report.get("seo_skipped") or []
                    if skipped:
                        st.caption(
                            "· 이번 글 주제와 맞지 않아 타깃에서 제외한 키워드: "
                            + ", ".join(skipped)
                        )
                intent = report.get("search_intent")
                if intent and intent.get("checked"):
                    coverage, missing = intent.get("coverage"), intent.get("missing") or []
                    icon = "✅" if not missing else ("⚠️" if (coverage or 0) >= 50 else "🔴")
                    st.caption(
                        f"{icon} 검색 의도 충족도: **{coverage}%** "
                        f"(‘{intent.get('keyword')}’로 검색한 사람 기준)"
                    )
                    if missing:
                        # Not auto-written on purpose — these are facts only the
                        # marketer has. See ai_workers/search_intent.py.
                        st.caption(
                            "· 아래 정보를 본문에 직접 채우시면 체류시간이 늘어 노출 순위가 올라갑니다:"
                        )
                        for item in missing:
                            st.caption(f"　　🔸 **{item.get('item')}** — {item.get('why','')}")
                regressed = report.get("seo_regression_fixed")
                if regressed:
                    st.caption(
                        "🔒 SEO 키워드 보정이 되살린 컴플라이언스 문구를 감지해 다시 교정했습니다: "
                        + ", ".join(regressed)
                    )
                title_seo = report.get("title_seo")
                if title_seo and title_seo.get("checked"):
                    if title_seo.get("fixed"):
                        st.caption("✏️ 제목에 타깃 키워드가 없어 AI가 자동으로 보강했습니다.")
                    else:
                        st.caption("✅ 제목에 타깃 키워드가 이미 포함되어 있습니다.")
                sns = report.get("sns_checks")
                if sns:
                    all_issues = (sns.get("x") or []) + (sns.get("instagram") or [])
                    if all_issues:
                        for issue in all_issues:
                            icon = {"fixed": "🔧", "warn": "⚠️", "blocked": "⛔"}.get(issue["level"], "•")
                            st.caption(f"{icon} SNS 형식: {issue['message']}")
                    else:
                        st.caption("✅ SNS 형식(트윗 길이·해시태그·훅): 문제 없음")
                pf = report.get("proofread")
                if pf is not None:
                    applied, rejected = pf.get("applied") or [], pf.get("rejected") or []
                    if applied:
                        st.caption(f"🔤 맞춤법·오탈자 {len(applied)}건 교정")
                        for fix in applied:
                            times = f" ×{fix['count']}" if fix.get("count", 1) > 1 else ""
                            st.caption(
                                f"　• [{fix.get('kind', '교정')}] "
                                f"~~{fix['before']}~~ → **{fix['after']}**{times}"
                            )
                    else:
                        st.caption("🔤 맞춤법·오탈자: 발견된 오류 없음")
                    for bad in rejected:
                        st.caption(f"　• ⛔ 교정 보류 ({bad['reason']}): {bad['before']} → {bad['after']}")
                revision = report.get("revision")
                if revision:
                    before, after = revision["before_chars"], revision["after_chars"]
                    delta = f"{(after - before) / before:+.0%}" if before else "-"
                    mode_label = LENGTH_MODES.get(revision["length_mode"], {}).get("label", "")
                    st.caption(
                        f"✏️ 수정 반영: {before:,}자 → {after:,}자 ({delta}, 요청 '{mode_label}')"
                    )
                variety = report.get("title_variety")
                if variety and variety.get("checked"):
                    if variety.get("rewritten"):
                        st.caption(
                            f"🎲 과거 제목과 유사도 {variety.get('score', 0):.0%} "
                            f"(\"{variety.get('similar_to', '')}\") — 다른 제목으로 다시 지었습니다."
                        )
                    else:
                        st.caption(
                            f"✅ 과거 제목과 충분히 다릅니다 (최대 유사도 {variety.get('score', 0):.0%})."
                        )

                recommendation = report.get("recommendation")
                if recommendation:
                    st.divider()
                    verdict = recommendation["verdict"]
                    if verdict == "ok":
                        st.success("✅ 종합 판정: 그대로 게시해도 좋습니다.")
                    elif verdict == "regenerate":
                        st.warning(
                            "🔁 종합 판정: 다시 생성을 고려하세요 — " + " / ".join(recommendation["reasons"])
                        )
                    else:
                        st.info("📝 종합 판정: 본문은 게시해도 좋습니다. 다만 설정 조정이 필요합니다.")

                    if recommendation.get("no_targets"):
                        st.caption(
                            "🎯 이 글에 맞는 SEO 키워드가 브랜드 킷에 없어 타깃 없이 발행됩니다. "
                            "다시 생성해도 같습니다 — 키워드를 추가해야 해결됩니다."
                        )

                    conflicts = recommendation.get("conflicts") or []
                    if conflicts:
                        st.caption(
                            f"⚖️ 타깃 키워드 {', '.join(conflicts)} 는 컴플라이언스 검수에서 "
                            "제거되는 표현이라 다시 생성해도 채워지지 않습니다. "
                            "⚙️ 설정에서 '새활용' 계열 표현으로 교체하세요."
                        )


# --- right pane: channel simulators ----------------------------------------

with sim_col:
    st.markdown("##### 📱 채널 시뮬레이터")
    channel_keys = list(simulators.CHANNELS.keys())
    channel = st.radio(
        "채널",
        options=channel_keys,
        format_func=lambda k: f"{simulators.CHANNELS[k]['icon']} {simulators.CHANNELS[k]['label']}",
        horizontal=True,
        label_visibility="collapsed",
        key=f"chan_{selected_id}",
    )

    is_mobile = False
    show_dead_zone = True
    if channel == "naver":
        is_mobile = st.toggle("모바일 뷰 (390px)", value=False, key=f"mob_{selected_id}")
    elif channel == "shorts":
        show_dead_zone = st.toggle("데드존 가이드", value=True, key=f"dz_{selected_id}")

    fresh = repo.get_campaign(selected_id)
    html = simulators.render(
        channel, fresh, is_mobile=is_mobile, brand_kit=brand_kit, show_dead_zone=show_dead_zone
    )
    components.html(html, height=simulators.height(channel, is_mobile), scrolling=True)
