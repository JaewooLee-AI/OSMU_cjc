"""브랜드 킷 — 회사 자료에서 채워 넣은 씨제이씨협동조합/키노피스 설정.

Everything on this page is pre-populated from company_info/ on first launch
(core/brand_seed.py) rather than left as empty placeholders, so the very
first generated draft already knows the brand's product names, specs,
certifications and voice. The prompts-to-fill-this-in helper expanders from
OSMU_admin are kept for fields the team will want to evolve.

The compliance section is 의료법/표시·광고법, not 환경성 표시·광고 — see the
rationale at the top of ai_workers/guardrail.py.
"""
from __future__ import annotations

import pandas as pd
import streamlit as st

from ai_workers import content_mode, keyword_research
from core import repo
from core.theme import palette_html

st.title("브랜드 킷")
st.caption("여기 등록한 내용은 매 생성마다 프롬프트에 그대로 주입됩니다 (유사도 검색이 아니라 전체 주입).")

existing = repo.get_brand_kit()
FEW_SHOT_DELIMITER = "\n---\n"

st.markdown("#### 🎨 브랜드 컬러")
st.markdown(palette_html(), unsafe_allow_html=True)
st.caption("조합 브랜드 컬러(네이비·골드) 팔레트입니다. 화면 테마(assets/custom.css)와 시뮬레이터에 동일하게 적용됩니다.")

with st.form("brand_kit_form"):
    st.markdown("#### 🏢 기업 · 채널")
    c1, c2 = st.columns(2)
    brand_name = c1.text_input("기업명", value=existing.get("brand_name") or "")
    sub_brand = c2.text_input("브랜드명", value=existing.get("sub_brand") or "")
    industry = st.text_input("업종", value=existing.get("industry") or "")
    c3, c4, c5 = st.columns(3)
    homepage = c3.text_input("홈페이지", value=existing.get("homepage") or "")
    naver_blog_id = c4.text_input(
        "네이버 블로그 아이디",
        value=existing.get("naver_blog_id") or "",
        help="blog.naver.com/<아이디>. 반자동 게시가 이 블로그로 글을 올립니다.",
    )
    instagram_handle = c5.text_input("인스타그램 핸들", value=existing.get("instagram_handle") or "")

    st.divider()
    guardrail_enabled = st.toggle(
        "🛡️ 의료법·표시광고법 컴플라이언스 가드레일",
        value=existing.get("guardrail_enabled", True),
        help="켜면 모든 초안이 (1) 금기어 사전 치환 + (2) LLM 법무 검토관 감사를 거칩니다.",
    )

    persona = st.text_area("브랜드 페르소나", value=existing.get("persona") or "", height=140)
    with st.expander("🤖 페르소나를 다시 뽑고 싶다면"):
        st.code(
            "우리 브랜드는 [업종]이고 주요 고객은 [타겟]입니다.\n"
            "브랜드만의 화자(페르소나)를 3~4문장으로 정의해줘. 무엇을 앞세우고 무엇은 말하지 않는지도 포함해서.",
            language=None,
        )

    tone_and_manner = st.text_area("톤앤매너 가이드", value=existing.get("tone_and_manner") or "", height=200)

    st.divider()
    st.markdown("#### 🏭 회사 핵심 팩트")
    st.caption(
        "AI가 매 초안마다 이 목록 중 2개 이상을 본문에 인용해서, 주제를 우리 제품/활동과 연결합니다. "
        "여기 없는 수치·인증·실적은 지어내지 말라고 지시되어 있습니다."
    )
    core_facts_text = st.text_area(
        "핵심 팩트 (한 줄에 하나씩)",
        value="\n".join(existing.get("core_facts") or []),
        height=260,
    )

    st.divider()
    st.markdown("#### 📖 회사 용어집")
    st.markdown(
        """<div class='tb-card'>
        💡 <b>매번 전체 주입:</b> 유사도 검색(RAG) 대신 등록된 용어 전체를 항상 프롬프트에 넣습니다.
        14개 남짓한 용어집은 전부 넣어도 ~600토큰이고, 검색이 한 번 빗나가 '키노피스'를 '키노 피스'로
        쓰는 초안이 나오는 쪽이 훨씬 비쌉니다.
        </div>""",
        unsafe_allow_html=True,
    )
    terminology = existing.get("terminology") or {}
    terminology_df = pd.DataFrame(
        [{"용어": k, "설명/올바른 표기": v} for k, v in terminology.items()],
        columns=["용어", "설명/올바른 표기"],
    )
    edited_terminology = st.data_editor(
        terminology_df, num_rows="dynamic", use_container_width=True, key="terminology_editor"
    )

    st.divider()
    st.markdown("#### 🎚️ 기본 콘텐츠 모드")
    st.caption(
        "검색 노출과 내용의 풍성함은 맞바꾸는 관계입니다. 글마다 워크벤치에서 바꿀 수 있고, "
        "여기서 정한 값은 따로 지정하지 않은 글에 적용됩니다."
    )
    mode_keys = content_mode.ORDER
    saved_mode = (existing.get("default_content_mode") or content_mode.DEFAULT_MODE)
    default_content_mode = st.radio(
        "기본 모드",
        options=mode_keys,
        index=mode_keys.index(saved_mode) if saved_mode in mode_keys else 1,
        horizontal=True,
        format_func=lambda k: f"{content_mode.MODES[k]['icon']} {content_mode.MODES[k]['label']}",
        label_visibility="collapsed",
    )
    for key in mode_keys:
        m = content_mode.MODES[key]
        st.caption(f"· {m['icon']} **{m['label']}** — {m['caption']}")

    st.divider()
    st.markdown("#### 🔍 SEO 키워드 (네이버 블로그 전용)")
    st.caption(
        "제목·본문에 3~5회 분산 배치되고, 생성 후 실제 밀도를 검증해 벗어나면 한 번 더 교정합니다. "
        "인스타그램·X·쇼츠는 키워드 밀도 방식이 아니라 훅 중심 구조라 이 키워드를 쓰지 않습니다."
    )
    st.markdown(
        """<div class='tb-card'>
        ⚖️ <b>전환 가중치</b>는 '이 검색어로 들어온 방문자가 우리에게 얼마짜리인가'입니다.
        검색량과 경쟁도는 네이버에서 측정되지만, 그 트래픽의 <b>가치</b>는 측정할 수 없어
        브랜드가 직접 넣어야 합니다. 넣지 않으면 <b>검색량이 가장 큰 키워드가 항상 이깁니다</b>
        — 대량·저단가 검색어가 고단가 문의 검색어를 영구히 밀어내는 이유입니다.<br>
        <code>1.0</code> 보통 · <code>2.0</code> 이 유입이 두 배 가치 · <code>0.3</code> 유입은 많지만 잘 안 팔림 ·
        <code>0</code> 타깃에서 제외(글에 등장은 가능)
        </div>""",
        unsafe_allow_html=True,
    )
    keyword_weights = existing.get("keyword_weights") or {}
    non_target = set(existing.get("non_target_keywords") or [])
    keywords_df = pd.DataFrame(
        [
            {
                "키워드": k,
                "전환 가중치": float(keyword_weights.get(k, 1.0)),
                "검색 타깃": k not in non_target,
            }
            for k in (existing.get("seo_keywords") or [])
        ],
        columns=["키워드", "전환 가중치", "검색 타깃"],
    )
    edited_keywords = st.data_editor(
        keywords_df,
        num_rows="dynamic",
        use_container_width=True,
        key="seo_keyword_editor",
        column_config={
            "전환 가중치": st.column_config.NumberColumn(
                min_value=0.0, max_value=10.0, step=0.1, format="%.1f", default=1.0
            ),
            "검색 타깃": st.column_config.CheckboxColumn(default=True),
        },
    )
    st.caption(
        "🏷️ **검색 타깃**을 끄면 그 키워드로는 검색 노출을 노리지 않습니다 — 초안 프롬프트의 "
        "키워드 목록에서 빠지고, 타깃 슬롯도 제목도 맡지 않습니다. 다만 풀에는 남아 있어 "
        "본문에는 계속 등장하고, 제목 반복 검사에서도 '반복돼도 되는 단어'로 계속 취급됩니다. "
        "**브랜드 어휘가 여기 해당합니다** — `키노피스`·`ATUM` 같은 고유명사는 검색량이 적어, "
        "이 단어로 제목을 지으면 그 글의 검색 노출을 사실상 포기하는 셈입니다. "
        "가중치를 낮추는 것과는 다릅니다: 가중치는 '이 유입이 얼마짜리인가'이고, 브랜드 유입은 "
        "비싸지만 양이 없는 것뿐입니다."
    )
    st.caption(
        "⚖️ 컴플라이언스 검수가 제거하는 표현(예: '탈모 완치')은 키워드로 두면 밀도를 "
        "영원히 채우지 못합니다. 리포트에 그런 키워드가 표시되면 '두피케어·스타일 보완' 계열로 바꾸세요."
    )

    # 만료는 조용히 일어나고, 조용히 가중치 체계를 끕니다 —
    # keyword_research.pool_freshness 참고.
    freshness = keyword_research.pool_freshness(existing.get("seo_keywords") or [])
    if freshness["stale"]:
        st.error(
            f"📉 경쟁도 측정이 만료된 키워드 {len(freshness['stale'])}개: "
            f"{', '.join(freshness['stale'][:6])}"
            + ("…" if len(freshness["stale"]) > 6 else "")
            + "  \n만료된 키워드는 **전환 가중치가 적용되지 않고**, 초안에 몇 번 나왔는지로만 "
            "순위가 정해집니다. ⚙️ 설정 페이지에서 재측정하세요."
        )
    elif freshness["days_left"] is not None:
        st.caption(
            f"📈 경쟁도 측정: 가장 오래된 것이 {freshness['oldest_document_age']:.0f}일 전 · "
            f"**{freshness['days_left']:.0f}일 후 만료**됩니다. 만료되면 전환 가중치가 "
            "조용히 꺼지므로, 그 전에 ⚙️ 설정에서 재측정하세요."
        )

    st.divider()
    st.markdown("#### 🚫 금기어 치환 사전 (의료법·표시광고법)")
    st.markdown(
        """<div class='tb-card'>
        🛡️ <b>결정론적 치환:</b> 아래 금기어는 AI가 무엇을 쓰든 발행 전 <b>100% 자동으로</b> 치환어로 바뀝니다.
        LLM 감사는 이 사전에 없는 새로운 과장 표현까지 추가로 잡아냅니다.<br>
        기준: 「의료법」 제56조 + 「표시·광고의 공정화에 관한 법률」.
        가발·두피 분야는 <b>치료·완치 약속</b>('탈모 완치')과 <b>절대적 안전 주장</b>('부작용 제로')이 가장 흔한 위반입니다.
        </div>""",
        unsafe_allow_html=True,
    )
    blacklist_map = existing.get("blacklist_map") or {}
    blacklist_df = pd.DataFrame(
        [{"금기어": k, "치환어": v} for k, v in blacklist_map.items()], columns=["금기어", "치환어"]
    )
    edited_blacklist = st.data_editor(
        blacklist_df, num_rows="dynamic", use_container_width=True, key="blacklist_editor"
    )

    st.divider()
    st.markdown("#### 우수 포스팅 샘플 (Few-shot)")
    st.caption("AI가 이 글의 어조와 문단 호흡을 그대로 모방합니다. 여러 개면 빈 줄에 `---` 로 구분하세요.")
    few_shot_text = st.text_area(
        "샘플", value=FEW_SHOT_DELIMITER.join(existing.get("few_shot_samples") or []), height=260
    )

    submitted = st.form_submit_button("저장", type="primary")

if submitted:
    core_facts = [line.strip() for line in core_facts_text.splitlines() if line.strip()]
    few_shot_samples = [s.strip() for s in few_shot_text.split(FEW_SHOT_DELIMITER.strip()) if s.strip()]
    new_terminology = {
        str(row["용어"]).strip(): str(row["설명/올바른 표기"]).strip()
        for _, row in edited_terminology.iterrows()
        if pd.notna(row.get("용어")) and str(row["용어"]).strip()
    }
    new_blacklist = {
        str(row["금기어"]).strip(): str(row["치환어"]).strip()
        for _, row in edited_blacklist.iterrows()
        if pd.notna(row.get("금기어")) and str(row["금기어"]).strip()
    }
    new_keywords, new_weights, new_non_targets = [], {}, []
    for _, row in edited_keywords.iterrows():
        keyword = str(row.get("키워드") or "").strip()
        if not keyword or not pd.notna(row.get("키워드")) or keyword in new_weights:
            continue
        new_keywords.append(keyword)
        weight = row.get("전환 가중치")
        # A blank cell in a newly added row means "no opinion yet", which is
        # the neutral weight — not zero, which would silently retire the
        # keyword the marketer just typed in.
        new_weights[keyword] = float(weight) if pd.notna(weight) else 1.0
        # Same reasoning for the checkbox: a blank cell on a row the marketer
        # just typed means they have not opted out, so the keyword competes.
        # Only an explicit uncheck retires it from targeting.
        is_target = row.get("검색 타깃")
        if pd.notna(is_target) and not bool(is_target):
            new_non_targets.append(keyword)

    repo.save_brand_kit(
        brand_name=brand_name,
        sub_brand=sub_brand,
        industry=industry,
        homepage=homepage,
        naver_blog_id=naver_blog_id,
        instagram_handle=instagram_handle,
        guardrail_enabled=guardrail_enabled,
        persona=persona,
        tone_and_manner=tone_and_manner,
        core_facts=core_facts,
        terminology=new_terminology,
        seo_keywords=new_keywords,
        keyword_weights=new_weights,
        non_target_keywords=new_non_targets,
        default_content_mode=default_content_mode,
        blacklist_map=new_blacklist,
        few_shot_samples=few_shot_samples,
    )
    st.success(
        f"저장했습니다. (핵심 팩트 {len(core_facts)} · 용어 {len(new_terminology)} · "
        f"SEO 키워드 {len(new_keywords)} · 금기어 {len(new_blacklist)} · 샘플 {len(few_shot_samples)})"
    )
    st.rerun()

if not existing.get("guardrail_enabled", True):
    st.warning("가드레일이 꺼져 있습니다. 치료·완치 약속 같은 위반 표현이 검수 없이 발행될 수 있습니다.")

# Outside the form above: this is stored in its own table and managed with its
# own button, and st.form only allows st.form_submit_button inside it.
st.divider()
st.markdown("#### 🎲 제목 반복 방지")
history_count = repo.title_history_count()
st.caption(
    f"지금까지 생성한 제목 {history_count}건을 기억해, 새 제목이 과거 제목과 문장 구조까지 "
    "겹치면 자동으로 다시 짓습니다. 이 이력은 **캠페인을 삭제해도 남습니다** — 지워진 글도 "
    "이미 발행된 글이라 제목은 계속 피해야 하기 때문입니다."
)
if history_count:
    with st.expander(f"기억 중인 제목 {history_count}건 보기"):
        for past_title in repo.recent_titles(50):
            st.caption(f"• {past_title}")
        if st.button("🗑️ 제목 이력 전체 삭제", key="clear_title_history"):
            repo.clear_title_history()
            st.rerun()
