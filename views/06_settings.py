"""설정 — LLM 벤더 등록, 이미지 분석 토큰 정책, 사용량 리포트.

The LLM panel is unchanged in spirit from OSMU_admin: model names and keys
live in the DB (AES-256-GCM encrypted) so the brain can be swapped without a
code change. The image-analysis section is new — it's where the token
minimization strategy is configured and where its measured effect is shown.
"""
from __future__ import annotations

import pandas as pd
import streamlit as st

from ai_workers import keyword_curator, keyword_research, vision
from ai_workers.multi_llm_router import VENDORS, test_connection, vision_capable_vendors
from core import repo, storage
from core.crypto_utils import decrypt_api_key, encrypt_api_key
from core.theme import stat_card

st.title("설정 · 토큰")

tab_llm, tab_naver, tab_vision, tab_usage = st.tabs(
    ["🔑 LLM 벤더", "🔍 네이버 API", "🖼️ 이미지 분석 (토큰)", "📈 사용량"]
)


def _saved_badge(encrypted_blob: str, updated_at: str | None = None) -> str:
    """Unmistakable 'saved' indicator: masked fingerprint + timestamp.

    Password inputs always render empty after a save (by design — the key
    is never echoed back), which reads as 'not saved'. This badge proves
    the row exists, which key it is (last 4 chars), and when it was stored.
    """
    try:
        fingerprint = decrypt_api_key(encrypted_blob)[-4:]
    except Exception:
        fingerprint = "????"
    when = f" · {updated_at} 저장" if updated_at else ""
    return f"✅ 등록됨 `****{fingerprint}`{when}"


# ---------------------------------------------------------------- LLM vendors
with tab_llm:
    st.caption("입력한 키는 AES-256-GCM으로 암호화되어 로컬 SQLite에 저장됩니다. 마스터 키는 data/.master_key (0600).")

    def render_vendor_card(col, key: str, spec: dict, saved) -> None:
        with col:
            with st.container(border=True):
                st.subheader(f"{spec['icon']} {spec['label']}")
                if spec.get("note"):
                    st.caption(spec["note"])

                model_name = st.text_input(
                    "모델명", value=(saved or {}).get("model_name", spec["default_model"]), key=f"{key}_model"
                )
                api_key = st.text_input(
                    "🔒 API Key",
                    type="password",
                    key=f"{key}_key",
                    placeholder="저장된 키가 있으면 비워두고 테스트해도 유지됩니다" if saved else "",
                )
                if saved:
                    st.caption(_saved_badge(saved["encrypted_api_key"], saved.get("updated_at")))

                delete_clicked = False
                if saved:
                    b1, b2 = st.columns([2, 1])
                    test_clicked = b1.button("연결 테스트 · 저장", key=f"{key}_test")
                    delete_clicked = b2.button("🗑️", key=f"{key}_delete")
                else:
                    test_clicked = st.button("연결 테스트 · 저장", key=f"{key}_test")

                if test_clicked:
                    # A blank input plus an already-saved key means "test/keep
                    # the existing key" — that's what the placeholder promises,
                    # so decrypt and test with it rather than erroring.
                    key_to_test, reuse_saved = api_key, False
                    if not key_to_test and saved:
                        key_to_test, reuse_saved = decrypt_api_key(saved["encrypted_api_key"]), True

                    if not key_to_test:
                        st.error("API Key를 입력하세요.")
                    else:
                        with st.spinner("연결 테스트 중…"):
                            ok, message = test_connection(key, model_name, key_to_test)
                        if not ok:
                            st.error(f"❌ {message}")
                        else:
                            encrypted = saved["encrypted_api_key"] if reuse_saved else encrypt_api_key(key_to_test)
                            repo.upsert_llm_setting(key, model_name, encrypted)
                            # 연결이 확인된 벤더를 그 자리에서 바로 기본 생성 모델로
                            # 지정합니다. 예전에는 등록과 "기본으로 지정"이 별개 버튼
                            # 이었는데, 소상공인 고객이 키만 넣고 이 두 번째 단계를
                            # 빠뜨리면 글쓰기 시점에 "기본 생성 모델이 지정되지
                            # 않았습니다" 오류를 처음 봅니다 — 이미 등록했다고 믿는
                            # 상태에서 나오는 오류라 원인을 짐작하기 어렵습니다.
                            # 벤더를 여러 개 등록해두고 쓰는 사용자는, 되돌아가고 싶은
                            # 벤더의 카드에서 이 버튼을 한 번 더 누르면 됩니다(키를
                            # 비워두면 저장된 키를 그대로 재검증합니다).
                            repo.save_brand_kit(default_generation_vendor=key)
                            st.success(f"✅ {message} · 기본 생성 모델로 지정했습니다.")
                            st.rerun()

                if delete_clicked:
                    repo.delete_llm_setting(key)
                    # 지금 기본으로 쓰이던 벤더를 지웠다면, 남은 벤더 중 하나로
                    # 넘기거나(있으면) 아예 비웁니다 — 지운 벤더를 계속 기본으로
                    # 가리키게 두면 다음 생성 시도에서야 실패로 드러납니다.
                    if repo.get_brand_kit().get("default_generation_vendor") == key:
                        remaining = [
                            k for k in VENDORS
                            if k != key and (repo.get_llm_setting(k) or {}).get("is_active")
                        ]
                        repo.save_brand_kit(
                            default_generation_vendor=remaining[0] if remaining else None
                        )
                    st.rerun()

    all_keys = list(VENDORS.keys())
    saved_settings = {k: repo.get_llm_setting(k) for k in all_keys}

    cols = st.columns(3)
    for col, (key, spec) in zip(cols, VENDORS.items()):
        render_vendor_card(col, key, spec, saved_settings.get(key))

    st.divider()
    st.subheader("기본 생성 모델")
    st.caption("블로그 초안, 컴플라이언스 감사, SEO 재조정, 채널별 카피에 실제로 사용할 모델입니다.")

    # 별도 선택 UI를 두지 않습니다 — 위 카드에서 연결 테스트가 성공하는 순간
    # 그 벤더가 바로 기본으로 지정되므로(render_vendor_card 참고), 여기는
    # "지금 뭐가 쓰이고 있는지"만 보여주는 읽기 전용 상태입니다. 다른 벤더로
    # 바꾸고 싶으면 그 카드에서 연결 테스트를 다시 누르면 됩니다.
    current = repo.get_brand_kit().get("default_generation_vendor")
    if current and (saved_settings.get(current) or {}).get("is_active"):
        spec = VENDORS[current]
        st.success(
            f"{spec['icon']} **{spec['label']}** ({saved_settings[current]['model_name']}) 사용 중"
        )
    else:
        st.warning(
            "아직 기본 생성 모델이 없습니다. 위 카드에서 [연결 테스트 · 저장]을 누르면 "
            "그 벤더가 바로 기본으로 지정됩니다."
        )
    st.caption("다른 벤더로 바꾸려면, 그 벤더 카드에서 [연결 테스트 · 저장]을 다시 누르세요.")


# -------------------------------------------------------------- naver api hub
with tab_naver:
    st.caption(
        "블로그·뉴스·카페 검색과 검색어트렌드를 담당합니다. "
        "LLM 키와 같은 AES-256-GCM으로 암호화 저장됩니다."
    )

    with st.expander("📄 키 발급 방법 (처음이라면 여기부터)"):
        st.markdown(
            """
**NAVER API HUB — 블로그/뉴스/카페 검색 + 검색어트렌드**

1. `console.ncloud.com` 로그인 (네이버 클라우드 플랫폼 계정)
2. **Menu > All Services > Application Services > NAVER API HUB > Subscription** → 약관 동의
   · 종량제 유료 서비스라 결제수단 등록이 필요합니다
3. **Application > [Application 등록]**
   · API 카테고리에서 **검색**(블로그·뉴스·카페)과 **Data Lab**(검색어트렌드)을 모두 선택
   · 이름은 영문·숫자·하이픈 20자 이내
4. 목록에서 **[인증 정보]** → 아래 두 값을 복사
   · `X-NCP-APIGW-API-KEY-ID` → **Client ID**
   · `X-NCP-APIGW-API-KEY` → **Client Secret**
5. **[한도 및 알림]** 에서 일·월 상한과 70%/90% 알림을 걸어두세요

> ⚠️ **`developers.naver.com`의 키는 여기서 동작하지 않습니다.** 인증 헤더 이름이 아예 다릅니다.
> 이미 그쪽 키가 있어도 위 절차로 새로 발급받으셔야 합니다.

**"요청한 API가 이 Application에서 활성화되어 있지 않습니다" 오류가 나면**
→ 구독은 됐지만 3번의 API 선택이 빠진 것입니다. 콘솔에서 해당 Application의
햄버거 버튼 > **[Application 수정]** 으로 검색·Data Lab을 체크하세요.
            """
        )
    st.warning(
        "이 API는 **유료 종량제**입니다. 아래 일일 상한은 이 앱이 스스로 지키는 방어선으로, "
        "상한에 도달하면 요청을 보내기 전에 차단합니다. NCP 콘솔의 [한도 및 알림]도 함께 걸어두세요.",
        icon="💳",
    )

    naver_saved = repo.get_naver_api_settings()

    c1, c2 = st.columns(2)
    nv_id = c1.text_input(
        "Client ID",
        type="password",
        key="naver_id",
        placeholder="저장된 값이 있으면 비워두고 테스트해도 유지됩니다" if naver_saved else "",
    )
    nv_secret = c2.text_input(
        "Client Secret",
        type="password",
        key="naver_secret",
        placeholder="저장된 값이 있으면 비워두고 테스트해도 유지됩니다" if naver_saved else "",
    )
    cap = st.number_input(
        "일일 호출 상한",
        min_value=0,
        max_value=25_000,
        step=50,
        value=int((naver_saved or {}).get("daily_call_cap", 500)),
        help="0으로 두면 상한 없음. 키워드 10개를 새로 조사할 때 약 13회를 씁니다.",
    )

    if naver_saved:
        st.caption(_saved_badge(naver_saved["encrypted_client_secret"], naver_saved.get("updated_at")))
        used = repo.naver_calls_today()
        m1, m2, m3 = st.columns(3)
        m1.markdown(stat_card("오늘 호출", f"{used:,}", f"상한 {cap:,}" if cap else "상한 없음"),
                    unsafe_allow_html=True)
        m2.markdown(stat_card("남은 호출", f"{keyword_research.remaining_calls_today():,}" if cap else "—"),
                    unsafe_allow_html=True)
        m3.markdown(stat_card("캐시된 키워드", f"{repo.keyword_cache_size():,}", "재조회 시 호출 0"),
                    unsafe_allow_html=True)

    # 캐시 비우기는 여기 있었는데, 옆에 '누르지 마세요'라고 써 두어야 하는
    # 버튼이었습니다. 키워드 갱신의 고급 설정으로 옮겼습니다.
    b1, b3 = st.columns([3, 1])
    if b1.button("연결 테스트 · 저장", key="naver_test", type="primary"):
        # Same "blank means keep" contract as the LLM cards above.
        id_to_test = nv_id or (decrypt_api_key(naver_saved["encrypted_client_id"]) if naver_saved else "")
        sec_to_test = nv_secret or (
            decrypt_api_key(naver_saved["encrypted_client_secret"]) if naver_saved else ""
        )
        if not (id_to_test and sec_to_test):
            st.error("Client ID와 Secret을 모두 입력하세요.")
        else:
            # Saved first: test_connection spends a real (billed) request, and
            # a valid key that fails to persist would make the user spend
            # another one on the next attempt.
            repo.save_naver_api_settings(
                encrypt_api_key(id_to_test), encrypt_api_key(sec_to_test), int(cap)
            )
            with st.spinner("호출 1회로 테스트 중…"):
                ok, message = keyword_research.test_connection(id_to_test, sec_to_test)
            st.success(f"✅ {message}") if ok else st.error(f"❌ {message}")

    if naver_saved and b3.button("🗑️ 키 삭제", key="naver_delete"):
        repo.delete_naver_api_settings()
        st.rerun()

    st.divider()
    st.subheader("검색광고 API (광고주센터)")
    st.caption(
        "절대 월간 검색량과 연관키워드 발굴을 담당합니다. **완전 무료**이고 위 호출 상한과 무관합니다."
    )

    with st.expander("📄 키 발급 방법 (CUSTOMER_ID · 액세스라이선스 · 비밀키)"):
        st.markdown(
            """
1. `searchad.naver.com` 회원가입
   · **개인 광고주·개인사업자·법인 모두 가능**합니다. 광고를 집행하지 않아도 됩니다
2. 로그인 후 **우측 상단 [광고시스템]** 클릭
   · ⚠️ 첫 화면(광고주센터 메인)에는 "도구" 탭이 **없습니다.** 이 버튼을 눌러
     `manage.searchad.naver.com`으로 들어가야 상단에 정보관리·보고서·도구 탭이 생깁니다
3. 상단 **도구 > API 사용 관리**
4. 처음이면 안내 화면만 보입니다. 가운데 **[네이버 검색광고 API 서비스 신청]** 버튼을 누르세요
   · 심사·승인 절차는 없습니다. 약관 동의하면 즉시 발급됩니다
5. 세 값을 복사
   · **CUSTOMER_ID** — 고객번호, 7자리 숫자 (로그인 ID가 아닙니다)
   · **액세스라이선스** — `01000000...`으로 시작하는 긴 문자열
   · **비밀키** — `AQAAAA...`로 시작하는 문자열

> 💡 **계정 책임자(마스터) 계정**으로 로그인해야 보입니다.
> 운영관리 권한만 위임받은 계정에서는 키가 표시되지 않습니다.

> 💡 4번에서 막히는 경우가 많습니다. "API 사용 관리"에 들어갔는데 키가 안 보인다면
> 아직 **서비스 신청 전**입니다.
            """
        )
    ad_saved = repo.get_searchad_settings()
    if ad_saved:
        st.caption(_saved_badge(ad_saved["encrypted_secret_key"], ad_saved.get("updated_at")))
    a1, a2, a3 = st.columns(3)
    ad_cid = a1.text_input("CUSTOMER_ID", key="ad_cid", placeholder="저장됨" if ad_saved else "7자리 숫자")
    ad_key = a2.text_input("액세스라이선스", type="password", key="ad_key",
                           placeholder="저장됨" if ad_saved else "")
    ad_sec = a3.text_input("비밀키", type="password", key="ad_sec",
                           placeholder="저장됨" if ad_saved else "")

    d1, d2 = st.columns([2, 1])
    if d1.button("연결 테스트 · 저장", key="ad_test"):
        cid = ad_cid or (decrypt_api_key(ad_saved["encrypted_customer_id"]) if ad_saved else "")
        akey = ad_key or (decrypt_api_key(ad_saved["encrypted_api_key"]) if ad_saved else "")
        asec = ad_sec or (decrypt_api_key(ad_saved["encrypted_secret_key"]) if ad_saved else "")
        if not (cid and akey and asec):
            st.error("세 값을 모두 입력하세요.")
        else:
            ok, message = keyword_research.test_searchad_connection(cid, akey, asec)
            if ok:
                repo.save_searchad_settings(
                    encrypt_api_key(cid), encrypt_api_key(akey), encrypt_api_key(asec)
                )
                st.success(f"✅ {message}")
            else:
                st.error(f"❌ {message}")
    if ad_saved and d2.button("🗑️ 키 삭제", key="ad_delete"):
        repo.delete_searchad_settings()
        st.rerun()
    st.divider()
    # ================================================================
    # 월간 키워드 갱신 — 한 흐름
    # ================================================================
    # 이전에는 ①진단 / ②연관키워드 / ③스윕이 각각 독립 버튼이었고, 어느 것이
    # 브랜드 킷을 바꾸는지, 어떤 주기로 돌려야 하는지를 사용자가 표를 읽고
    # 지켜야 했습니다. 실제로는 ③만이 브랜드 킷을 바꾸고, ②는 ③의 1단계와
    # 같은 호출이며, ①은 ③이 어차피 다시 재는 값을 보여줄 뿐입니다.
    #
    # 셋을 한 줄기로 묶고 끝에서 경쟁도 캐시까지 채웁니다. "월 1회 이걸 끝까지
    # 하면 된다"가 실제로 성립해야, 4주 중 3주를 만료된 숫자로 글 쓰는 일이
    # 생기지 않습니다 — keyword_research.DOCUMENT_CACHE_DAYS 주석 참고.
    st.subheader("🔑 키워드 갱신")
    st.caption(
        "**SEO 키워드를 바꾸는 곳은 여기 하나뿐입니다.** 승인하기 전에는 아무것도 바뀌지 않습니다."
    )

    pool = repo.get_brand_kit().get("seo_keywords") or []
    freshness = keyword_research.pool_freshness(pool) if pool else None

    # 키가 없어도 아래 기능 골격은 보여주고 실행 버튼만 잠급니다 —
    # 통째로 숨기면 기능 자체가 없는 것처럼 보이기 때문입니다.
    keys_ok = bool(naver_saved and ad_saved)
    if not keys_ok:
        st.warning("위에서 **두 API 키를 모두 등록**하면 아래 버튼이 활성화됩니다.", icon="🔑")
    if True:
        # --- 지금 상태 한 줄 ------------------------------------------------
        if not pool:
            st.info("브랜드 킷에 SEO 키워드가 없습니다. 아래 갱신을 한 번 돌리면 채워집니다.")
        elif freshness["stale"]:
            st.error(
                f"📉 **경쟁도 만료 {len(freshness['stale'])}/{len(pool)}개** — 지금 만드는 초안은 "
                "전환 가중치 없이 '초안에 몇 번 나왔는지'로만 키워드를 고릅니다. "
                "아래 [숫자만 새로 재기]를 눌러주세요."
            )
        else:
            st.success(
                f"✅ 키워드 {len(pool)}개 모두 측정돼 있습니다 · 마지막 측정 "
                f"{freshness['newest_document_age']:.0f}일 전 · "
                f"**{freshness['days_left']:.0f}일 후 만료**",
                icon="✅",
            )

        # --- 가벼운 유지: 같은 키워드로 숫자만 새로 --------------------------
        if pool:
            # 과금되는 것은 만료된 것뿐입니다 — 살아 있는 값은 캐시에서 읽고
            # 호출이 나가지 않습니다.
            need = keyword_research.pool_refresh_cost(pool)
            r1, r2 = st.columns([2, 3])
            label = (
                f"🔄 숫자만 새로 재기 ({need}회 호출)" if need
                else "🔄 숫자만 새로 재기 (전부 최신 · 0회)"
            )
            if r1.button(label, key="pool_refresh", disabled=(not need or not keys_ok)):
                try:
                    with st.spinner(f"{need}개 재측정 중…"):
                        result = keyword_research.refresh_pool(pool)
                except keyword_research.NaverApiError as exc:
                    st.error(f"❌ {exc}")
                else:
                    st.success(
                        f"{result['billed']}개 재측정 완료 (나머지는 캐시에서 읽어 호출 0). "
                        f"{keyword_research.DOCUMENT_CACHE_DAYS}일간 유효합니다."
                    )
                    st.rerun()
            r2.caption(
                "키워드 목록은 그대로 두고 만료된 검색량·경쟁도만 다시 잽니다. "
                "**평소 달에는 이것만 누르면 됩니다.**"
            )

        st.divider()

        # --- 본 흐름: 새 키워드 찾아 교체 ------------------------------------
        st.markdown("##### 🔎 새 키워드까지 찾아 교체하기")
        st.caption(
            "분기에 한 번 정도. 연관 검색어를 대량 발굴해 이길 만한 것만 남기고, 브랜드에 맞는지 "
            "판정한 뒤, 승인하면 브랜드 킷 반영과 측정까지 한 번에 끝냅니다."
        )

        # The text box's own key is the single source of truth for the seeds:
        # keeping a parallel copy and passing it as `value=` would not survive
        # the 🪄 button, because Streamlit gives a keyed widget's stored state
        # priority over `value` on rerun and the suggestion would be discarded.
        if "kw_seed_box" not in st.session_state:
            st.session_state["kw_seed_box"] = ""

        def _fill_seeds() -> None:
            """Overwrites the seed box from the brand kit.

            Runs as an on_click callback rather than inline after the button,
            because assigning to a widget's own key is only legal before that
            widget is instantiated for the run — and the text input below has
            already been created by the time an inline handler would fire.
            Callbacks execute ahead of the rerun, so this is the one place the
            box can be set programmatically.
            """
            try:
                suggested = keyword_curator.suggest_seeds()
            except Exception as exc:
                st.session_state["kw_seed_error"] = f"추천 실패: {exc}"
                return
            if suggested:
                st.session_state["kw_seed_box"] = ", ".join(suggested)
                st.session_state.pop("kw_seed_error", None)
            else:
                st.session_state["kw_seed_error"] = "추천 결과가 비어 있습니다. 직접 입력해주세요."

        z1, z2 = st.columns([3, 1])
        seed = z1.text_input(
            "씨앗 키워드 (쉼표로 최대 5개)",
            key="kw_seed_box",
             help="브랜드 이름이 아니라 네이버에서 실제로 검색되는 일반적인 말이어야 합니다. "
                  "'키노피스'처럼 검색량이 없는 말에는 연관키워드가 없습니다.",
        )
        with z2:
            st.write("")
            st.button("🪄 브랜드에서 추천", key="kw_suggest", on_click=_fill_seeds)
        if st.session_state.get("kw_seed_error"):
            st.error(st.session_state["kw_seed_error"])

        SWEEP_STATE = "sweep"
        saved_sweep = repo.get_app_state(SWEEP_STATE) or {}
        stage = saved_sweep.get("stage", 0)
        state_age = repo.app_state_age_days(SWEEP_STATE)
        if stage and state_age is not None and state_age > 0.02:
            st.caption(
                f"↩️ 진행 중이던 작업을 이어서 표시합니다 ({state_age * 24:.0f}시간 전 중단). "
                "유료로 조사한 결과는 새로고침해도 남습니다."
            )

        steps = ["1. 후보 찾기", "2. 경쟁도 조사", "3. 브랜드 판정", "4. 적용"]
        st.markdown(
            " ".join(
                f"<span style='padding:2px 10px;border-radius:10px;font-size:.82rem;"
                f"background:{'#A6224B' if i < stage else '#EDE6DD'};"
                f"color:{'#fff' if i < stage else '#8A7B6B'}'>{s}</span>"
                for i, s in enumerate(steps)
            ),
            unsafe_allow_html=True,
        )
        st.write("")

        with st.expander("⚙️ 고급 설정 (건드리지 않아도 됩니다)"):
            # 세 값 모두 기본값이 곧 권장값입니다. 사용자가 답할 근거가 없는
            # 질문을 첫 화면에 놓지 않기 위해 여기로 내렸습니다.
            g1, g2 = st.columns(2)
            vol_min = g1.number_input(
                "최소 검색량", min_value=0, step=50,
                value=keyword_research.DEFAULT_MIN_VOLUME, key="sw_min_v3",
                help="이보다 적으면 1위를 해도 유입이 없습니다.",
            )
            vol_max = g2.number_input(
                "최대 검색량", min_value=100, step=500,
                value=keyword_research.DEFAULT_MAX_VOLUME, key="sw_max_v3",
                help="이보다 크면 대형 쇼핑몰·언론사와 경쟁하게 됩니다.",
            )
            cap_n = st.slider(
                "조사할 후보 수 (= 최대 유료 호출 수)", 10, 200, 100, step=10, key="sw_cap_v2",
                help="넓게 조사할수록 경쟁이 낮은 키워드를 찾을 확률이 올라갑니다.",
            )
            st.caption(f"오늘 남은 호출 {keyword_research.remaining_calls_today():,}회")
            if st.button("🧹 키워드 캐시 비우기", key="naver_cache_clear"):
                st.info(
                    f"{repo.clear_keyword_cache()}건을 삭제했습니다. 다음 조회는 전부 실제 "
                    "호출을 씁니다 — 평소에는 누를 일이 없습니다."
                )
            if stage and st.button("↩️ 진행 중인 작업 버리기", key="sw_reset"):
                repo.clear_app_state(SWEEP_STATE)
                st.rerun()

        # --- 1단계: 후보 찾기 (무료) -----------------------------------------
        if st.button("🔎 1단계 · 후보 찾기 (무료)", key="sw_find", type="primary", disabled=not keys_ok):
            seeds = [s for s in seed.split(",") if s.strip()]
            if not seeds:
                st.error("씨앗 키워드를 채우세요. [🪄 브랜드에서 추천]을 눌러도 됩니다.")
            else:
                try:
                    with st.spinner("연관키워드 발굴 중…"):
                        found = keyword_research.sweep_candidates(
                            seeds, min_volume=int(vol_min), max_volume=int(vol_max)
                        )
                except keyword_research.NaverApiError as exc:
                    st.error(f"❌ {exc}")
                else:
                    repo.set_app_state(SWEEP_STATE, {"stage": 1, "candidates": found})
                    st.rerun()

        candidates = saved_sweep.get("candidates")
        if stage >= 1 and candidates is not None:
            if not candidates:
                st.info(
                    "설정한 검색량 구간에 후보가 없습니다. 씨앗을 더 일반적인 검색어로 바꿔보세요."
                )
            else:
                if len(candidates) < 150:
                    st.warning(
                        f"후보가 {len(candidates)}개뿐입니다. 씨앗 키워드에 수식어가 붙어 범위가 "
                        "좁아졌을 가능성이 큽니다 — '친환경 답례품' 대신 **'답례품'** 처럼 수식어 "
                        "없는 카테고리 이름으로 바꿔보세요.",
                        icon="🌱",
                    )
                cost = keyword_research.estimate_sweep_cost(candidates, limit=int(cap_n))
                st.success(
                    f"후보 **{len(candidates)}개** 발견. 상위 {min(len(candidates), int(cap_n))}개를 "
                    f"조사하면 유료 호출 **{cost}회**를 씁니다 "
                    f"(오늘 남은 {keyword_research.remaining_calls_today():,}회)."
                )

                # --- 2단계: 경쟁도 조사 (유료) --------------------------------
                if st.button(f"💳 2단계 · 경쟁도 조사 ({cost}회 사용)", key="sw_score", type="primary", disabled=not keys_ok):
                    try:
                        with st.spinner("블로그 경쟁 문서 수 조회 중…"):
                            scored = keyword_research.score_candidates(candidates, limit=int(cap_n))
                    except keyword_research.NaverApiError as exc:
                        st.error(f"❌ {exc}")
                    else:
                        repo.set_app_state(
                            SWEEP_STATE,
                            {"stage": 2, "candidates": candidates, "scored": scored},
                        )
                        st.rerun()

        scored = saved_sweep.get("scored")
        if stage >= 2 and scored:
            with st.expander(f"조사 결과 {len(scored)}개 보기"):
                df = pd.DataFrame(scored)[["keyword", "estimated_volume", "documents", "score"]]
                df.columns = ["키워드", "월간 검색량", "블로그 문서 수", "점수"]
                st.dataframe(df, use_container_width=True, hide_index=True)

            # --- 3단계: 브랜드 판정 -------------------------------------------
            if st.button("🤖 3단계 · 브랜드에 맞는 것만 고르기", key="cu_propose", type="primary", disabled=not keys_ok):
                with st.spinner("브랜드 기준으로 판정 중…"):
                    result = keyword_curator.propose(scored, current=pool)
                repo.set_app_state(SWEEP_STATE, {**saved_sweep, "stage": 3, "proposal": result})
                st.rerun()

        proposal = saved_sweep.get("proposal")
        if stage >= 3 and proposal:
            if proposal.get("error"):
                st.error(f"❌ 판정 실패: {proposal['error']}")
            else:
                if proposal.get("focus"):
                    st.success(
                        f"**주력 주제: {' · '.join(proposal['focus'])}** — 네이버 C-Rank는 "
                        "블로그가 한 주제를 얼마나 일관되게 다루는지를 봅니다. 이 축에서 벗어난 "
                        "키워드는 검색량이 커도 제외했습니다.",
                        icon="🎯",
                    )
                for gkey, glabel in keyword_curator.INTENT_GROUPS.items():
                    rows = proposal["groups"].get(gkey) or []
                    if not rows:
                        continue
                    note = (
                        " · 검색 타깃에서 제외됩니다 (본문에는 등장)"
                        if gkey == "identity"
                        else f" · 전환 가중치 {keyword_curator.GROUP_DEFAULT_WEIGHT.get(gkey)} 부여"
                    )
                    st.markdown(
                        f"**[{glabel}]**<span style='opacity:.55'>{note}</span>",
                        unsafe_allow_html=True,
                    )
                    for r in rows:
                        mark = "=" if r["keyword"] in proposal["kept"] else "+"
                        vol = f"{r['estimated_volume']:,}" if r.get("estimated_volume") else "—"
                        ratio = f" · 경쟁 {r['ratio']:.0f}배" if r.get("ratio") else ""
                        st.markdown(
                            f"<code>{mark}</code> **{r['keyword']}** &nbsp; {vol}{ratio}"
                            f" &nbsp; <span style='opacity:.6'>{r.get('reason','')}</span>",
                            unsafe_allow_html=True,
                        )

                # 제외 목록은 경쟁배수가 낮은 순으로 보여줍니다. 모델이 판정하지
                # 않은 후보까지 전부 여기 오기 때문에 수십 개가 되는데, 그중
                # 쓸 만한 것은 '경쟁이 낮은 것'이고 그건 정렬로 위에 올릴 수
                # 있습니다 — 담당자가 수십 개를 다 읽을 필요가 없어집니다.
                revived = []

                def _ratio_of(row):
                    vol, docs = row.get("estimated_volume"), row.get("documents")
                    return (docs / vol) if (vol and docs) else None

                excluded = sorted(
                    proposal["excluded"],
                    key=lambda r: _ratio_of(r) if _ratio_of(r) is not None else 9e9,
                )
                if excluded:
                    st.markdown("**[제외됨 — 되살릴 수 있습니다]**")
                    st.caption("경쟁이 낮은 순입니다. 위쪽일수록 이기기 쉬운 키워드입니다.")

                    def _revive_row(row, idx):
                        vol = f"{row['estimated_volume']:,}" if row.get("estimated_volume") else "—"
                        ratio = _ratio_of(row)
                        label = f"{row['keyword']} — 검색 {vol}"
                        label += f" · 경쟁 {ratio:.0f}배" if ratio is not None else " · 경쟁 미측정"
                        label += f" · {row.get('reason', '')}"
                        if st.checkbox(label, key=f"cu_revive_{idx}"):
                            revived.append(row["keyword"])

                    for i, row in enumerate(excluded[:15]):
                        _revive_row(row, i)
                    if len(excluded) > 15:
                        with st.expander(f"나머지 {len(excluded) - 15}개"):
                            for i, row in enumerate(excluded[15:], start=15):
                                _revive_row(row, i)

                # --- 4단계: 적용 + 측정 ---------------------------------------
                final = proposal["accepted"] + revived
                st.divider()
                st.caption(
                    f"적용하면 **{len(final)}개** — 유지 {len(proposal['kept'])} · "
                    f"추가 {len(proposal['added'])} · 제거 {len(proposal['removed'])}"
                    + (f" · 되살림 {len(revived)}" if revived else "")
                    + ". 그룹에 따라 전환 가중치와 검색 타깃 여부가 함께 저장되고, "
                    "이어서 경쟁도 측정까지 끝납니다."
                )
                a1, a2 = st.columns([1, 3])
                if a1.button("✅ 4단계 · 적용", key="cu_apply", type="primary", disabled=not keys_ok):
                    with st.spinner("브랜드 킷 반영 후 측정 중…"):
                        applied = keyword_curator.apply_and_measure(final, proposal)
                    repo.clear_app_state(SWEEP_STATE)
                    st.success(
                        f"SEO 키워드 {applied['pool']}개로 갱신하고 측정까지 마쳤습니다 "
                        f"(추가 호출 {applied['calls']}회). "
                        f"{keyword_research.DOCUMENT_CACHE_DAYS}일간 유효합니다. "
                        "가중치는 🧵 브랜드 킷에서 조정할 수 있습니다."
                    )
                    st.rerun()
                if a2.button("무시하고 버리기", key="cu_discard"):
                    repo.clear_app_state(SWEEP_STATE)
                    st.rerun()

    st.divider()
    with st.expander("🔬 지금 키워드가 얼마나 좋은지만 보기 (아무것도 바뀌지 않습니다)"):
        if not pool:
            st.caption("브랜드 킷에 SEO 키워드가 없습니다.")
        elif not naver_saved:
            st.caption("먼저 위에서 키를 등록하세요.")
        else:
            st.caption(f"대상 {len(pool)}개: {', '.join(pool)}")
            if st.button("키워드 진단 실행", key="naver_rank"):
                try:
                    with st.spinner("조회 중… (캐시된 키워드는 호출하지 않습니다)"):
                        ranked = keyword_research.rank_keywords(pool)
                except keyword_research.NaverApiError as exc:
                    st.error(f"❌ {exc}")
                else:
                    if not ranked:
                        st.info("결과가 없습니다.")
                    else:
                        df = pd.DataFrame(ranked)[
                            ["keyword", "estimated_volume", "demand", "documents", "score"]
                        ]
                        df.columns = ["키워드", "월간 검색량", "트렌드(상대)", "블로그 문서 수", "점수"]
                        st.dataframe(df, use_container_width=True, hide_index=True)
                        st.caption("점수가 높을수록 '찾는 사람은 많은데 경쟁 글은 적은' 키워드입니다.")

# ------------------------------------------------------------- vision / tokens
with tab_vision:
    brand_kit = repo.get_brand_kit()
    st.markdown(
        """<div class='tb-card'>
        사진 분석은 이 파이프라인에서 토큰을 가장 많이 먹는 지점이었습니다. 다섯 가지로 줄였습니다:<br><br>
        <b>1. 캡션 캐시</b> — 사진의 내용 해시(sha256)로 캐싱합니다. 같은 제품 컷을 몇 번을 다시 써도
        분석은 <b>평생 한 번</b>, 재사용은 토큰 <b>0</b>입니다.<br>
        <b>2. 메모와 분리된 프롬프트</b> — 기존에는 "이 사진을 설명하고 <i>이 글의 어디에</i> 넣을지 판단하라"고
        물어서 캡션이 글마다 달라져 캐시가 불가능했습니다. 지금은 비전 호출에 "보이는 것"만 묻고,
        배치 판단은 어차피 메모·본문을 모두 가진 텍스트 호출이 합니다.<br>
        <b>3. 벤더별 최소 과금 해상도</b> — Gemini는 384px 이하 <b>258토큰 고정</b>,
        OpenAI는 detail=low <b>85토큰 고정</b>입니다. 딱 그 경계까지만 축소해 보냅니다.<br>
        <b>4. 배치 호출</b> — 사진 N장을 한 번에 보내 지시 프롬프트를 N번이 아니라 1번만 냅니다.<br>
        <b>5. 출력 상한</b> — 캡션 1장당 40~45토큰으로 제한합니다.
        </div>""",
        unsafe_allow_html=True,
    )

    c1, c2 = st.columns(2)
    with c1:
        vision_enabled = st.toggle(
            "이미지 분석 사용",
            value=brand_kit.get("vision_enabled", True),
            help="끄면 비전 호출을 완전히 생략하고 담당자 메모만으로 사진을 배치합니다 (토큰 0).",
        )
        vision_vendors = vision_capable_vendors()
        registered = [v for v in vision_vendors if (repo.get_llm_setting(v) or {}).get("is_active")]
        current_vv = brand_kit.get("vision_vendor")
        options = ["(기본 생성 모델과 동일)"] + registered
        idx = options.index(current_vv) if current_vv in options else 0
        chosen_vv = st.selectbox(
            "이미지 분석 벤더",
            options=options,
            index=idx,
            help="캡션은 작고 잦은 작업이라 글쓰기 모델과 분리해 더 싼 모델로 돌리는 편이 유리합니다.",
        )
    with c2:
        quality_keys = list(vision.QUALITY_PRESETS.keys())
        current_q = brand_kit.get("vision_quality") or vision.DEFAULT_QUALITY
        quality = st.radio(
            "분석 화질",
            options=quality_keys,
            index=quality_keys.index(current_q) if current_q in quality_keys else 0,
            format_func=lambda k: (
                f"{vision.QUALITY_PRESETS[k]['label']} · {vision.QUALITY_PRESETS[k]['max_edge']}px"
            ),
        )
        st.caption(vision.QUALITY_PRESETS[quality]["hint"])

    if st.button("이미지 분석 설정 저장", type="primary"):
        repo.save_brand_kit(
            vision_enabled=vision_enabled,
            vision_quality=quality,
            vision_vendor=None if chosen_vv.startswith("(") else chosen_vv,
        )
        st.success("저장했습니다.")
        st.rerun()

    st.divider()
    st.subheader("벤더별 사진 1장 토큰 비용")
    rows = []
    for vendor in ["google", "openai", "anthropic"]:
        row = {"벤더": vendor}
        for qkey, preset in vision.QUALITY_PRESETS.items():
            edge = preset["max_edge"]
            row[f"{preset['label']} ({edge}px)"] = vision.estimate_image_tokens(vendor, edge, edge)
        row["원본 3024x4032 (미축소)"] = vision.estimate_image_tokens("google" if vendor == "google" else vendor, 3024, 4032)
        rows.append(row)
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
    st.caption(
        "'원본' 열은 축소 없이 폰 사진을 그대로 보냈을 때입니다. OpenAI는 detail=low가 해상도와 무관하게 "
        "고정 과금이라 값이 같습니다."
    )

    st.divider()
    cached_count = repo.vision_cache_size()
    col_a, col_b = st.columns([3, 1])
    col_a.markdown(stat_card("캐시된 사진 캡션", f"{cached_count:,}", "재사용 시 추가 토큰 0"), unsafe_allow_html=True)
    with col_b:
        st.write("")
        if st.button("🧹 캐시 비우기", use_container_width=True):
            removed = repo.clear_vision_cache()
            st.success(f"{removed}건을 삭제했습니다.")
            st.rerun()


# ------------------------------------------------------------------ usage log
with tab_usage:
    totals = repo.usage_totals()
    spent = totals["input_tokens"] + totals["output_tokens"]
    saved = totals["saved_tokens"]

    c1, c2, c3, c4 = st.columns(4)
    c1.markdown(stat_card("총 입력 토큰", f"{totals['input_tokens']:,}"), unsafe_allow_html=True)
    c2.markdown(stat_card("총 출력 토큰", f"{totals['output_tokens']:,}"), unsafe_allow_html=True)
    c3.markdown(
        stat_card("절약된 토큰", f"{saved:,}", "캐시 적중 + 해상도 축소 + 배치"), unsafe_allow_html=True
    )
    c4.markdown(
        stat_card("캐시 적중", f"{totals['cache_hits']:,}", f"분석한 사진 {totals['images']:,}장"),
        unsafe_allow_html=True,
    )

    if saved + spent:
        st.progress(saved / (saved + spent), text=f"절감률 {saved / (saved + spent) * 100:.1f}%")

    st.caption(
        "입력/출력 토큰은 각 프로바이더가 응답에 실어 보낸 실제 usage 값입니다 "
        "(제공하지 않는 경우에만 글자 수 기반 추정). "
        "절약분은 **저장된 사진을 축소·캐시·배치 없이 그대로 보냈을 때**와의 차이입니다. "
        f"업로드 시점에 이미 {storage.STORE_MAX_EDGE}px JPEG로 정규화해 저장하므로, "
        "폰 원본(예: 3024×4032) 대비 실제 절감폭은 이 숫자보다 더 큽니다."
    )

    st.divider()
    st.subheader("최근 호출")
    recent = repo.recent_usage(50)
    if recent:
        df = pd.DataFrame(recent)[
            ["ts", "kind", "vendor", "model", "image_count", "est_input_tokens", "est_output_tokens",
             "est_saved_tokens", "note"]
        ]
        df.columns = ["시각", "종류", "벤더", "모델", "사진", "입력", "출력", "절약", "메모"]
        st.dataframe(df, use_container_width=True, hide_index=True)
    else:
        st.caption("아직 호출 기록이 없습니다.")
