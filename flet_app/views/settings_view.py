"""탭 전부(LLM 벤더 / 생성 채널 / 네이버 API / 이미지 분석 / 사용량 / 데이터 옮기기),
그리고 글자 크기 조정 기능.

네이버 API 탭의 키워드 갱신 마법사는 4단계 상태머신인데, 그 상태(`stage`,
`candidates`, `scored`, `proposal`)는 원래부터 `core.repo.get_app_state`/
`set_app_state`로 **DB에 저장**된다 — Streamlit의 `st.session_state`가 아니다.
그래서 Flet 쪽도 새 상태관리를 만들지 않고, Streamlit의 "상태를 바꾸고
st.rerun()" 패턴을 그대로 흉내낸다: 마법사 섹션 전체를 `ft.Container` 하나에
담아두고, 각 단계 버튼이 로직 실행 → `set_app_state` 저장 → 그 컨테이너의
`content`를 통째로 다시 만들고 `.update()`. 나머지 3탭의 비즈니스 로직은
ai_workers.multi_llm_router / ai_workers.vision / ai_workers.keyword_research /
ai_workers.keyword_curator / core.repo에서 그대로 가져다 씁니다(원본 Streamlit
파일과 동일한 호출).

글자 크기 조정은 이 화면(⚙️ 설정)에서 고르지만 앱 전체에 적용됩니다 — 값은
`core.repo`의 범용 app_state 테이블에 저장되고, `flet_app/state.py`의
`AppState.font_scale` + `request_rerender`를 통해 페이지 테마와 현재 화면을
즉시 다시 그립니다. `flet_app/theme.py`의 `fs()`가 이 배율을 실제 숫자로
바꾼다.
"""
from __future__ import annotations

import flet as ft

from ai_workers import formatting, keyword_curator, keyword_research, vision
from ai_workers.content_writer import SNS_CHANNELS, enabled_channels
from ai_workers.multi_llm_router import (
    VENDORS,
    normalize_model_name,
    test_connection,
    vision_capable_vendors,
)
from core import repo, transfer
from core.db import DATA_DIR
from core.crypto_utils import decrypt_api_key, encrypt_api_key

from flet_app.kit_picker import kit_dropdown
from flet_app.state import FONT_SCALE_STATE_KEY, AppState
from flet_app.theme import BRAND_COLORS, MAX_FONT_SCALE, MIN_FONT_SCALE, fs, stat_card


def _saved_badge(encrypted_blob: str, updated_at: str | None) -> str:
    try:
        fingerprint = decrypt_api_key(encrypted_blob)[-4:]
    except Exception:  # noqa: BLE001
        fingerprint = "????"
    when = f" · {updated_at} 저장" if updated_at else ""
    return f"✅ 등록됨 ****{fingerprint}{when}"


def _warn_box(text: str, scale: float, color: str = "#8A6D3B", bg: str = "#FFF6E5") -> ft.Container:
    return ft.Container(
        content=ft.Text(text, size=fs(12, scale), color=color),
        bgcolor=bg,
        padding=10,
        border_radius=8,
    )


# views/06_settings.py의 두 st.expander("📄 키 발급 방법 ...") 안 markdown을 그대로 옮김.
API_HUB_GUIDE_MD = """**NAVER API HUB — 블로그/뉴스/카페 검색 + 검색어트렌드**

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
햄버거 버튼 > **[Application 수정]** 으로 검색·Data Lab을 체크하세요."""

SEARCHAD_GUIDE_MD = """1. `searchad.naver.com` 회원가입
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
> 아직 **서비스 신청 전**입니다."""


def _guide_toggle(label: str, markdown_text: str, scale: float) -> list[ft.Control]:
    """토글형 "키 발급 방법" 안내 — Streamlit의 st.expander 자리."""
    box = ft.Container(
        visible=False,
        padding=ft.Padding.only(top=8, bottom=8),
        content=ft.Markdown(
            value=markdown_text,
            selectable=True,
            extension_set=ft.MarkdownExtensionSet.GITHUB_WEB,
        ),
    )

    def toggle(e: ft.Event) -> None:
        box.visible = not box.visible
        box.update()

    return [ft.TextButton(label, on_click=toggle), box]


def _build_font_scale_section(state: AppState, scale: float) -> ft.Control:
    slider = ft.Slider(
        min=MIN_FONT_SCALE,
        max=MAX_FONT_SCALE,
        divisions=7,
        value=scale,
        label="{value}배",
        expand=True,
    )
    readout = ft.Text(f"{scale:.2f}배", size=fs(13, scale), weight=ft.FontWeight.BOLD)

    def on_change_end(e: ft.Event) -> None:
        new_scale = round(slider.value, 2)
        readout.value = f"{new_scale:.2f}배"
        readout.update()
        state.font_scale = new_scale
        repo.set_app_state(FONT_SCALE_STATE_KEY, {"value": new_scale})
        if state.request_rerender:
            state.request_rerender()

    slider.on_change_end = on_change_end

    return ft.Container(
        content=ft.Column(
            [
                ft.Text("🔠 글자 크기", weight=ft.FontWeight.BOLD, size=fs(14, scale)),
                ft.Text(
                    "화면 전체 글자 크기를 조정합니다. 저장되어 다음 실행에도 유지됩니다.",
                    size=fs(11, scale),
                    color=BRAND_COLORS["text_muted"],
                ),
                ft.Row([slider, readout]),
            ],
            spacing=6,
        ),
        border=ft.Border.all(1, "#14000000"),
        border_radius=10,
        padding=14,
    )


def _vendor_card(
    page: ft.Page,
    vendor_key: str,
    spec: dict,
    on_vendor_change,
    scale: float,
) -> ft.Control:
    saved = repo.get_llm_setting(vendor_key)

    model_field = ft.TextField(
        label="모델명", value=(saved or {}).get("model_name", spec["default_model"])
    )
    key_field = ft.TextField(
        label="🔒 API Key",
        password=True,
        can_reveal_password=True,
        hint_text="저장된 키가 있으면 비워두고 테스트해도 유지됩니다" if saved else "",
    )
    badge = ft.Text(
        _saved_badge(saved["encrypted_api_key"], saved.get("updated_at")) if saved else "",
        size=fs(11, scale),
        color=BRAND_COLORS["text_muted"],
        visible=bool(saved),
    )
    status = ft.Text("", size=fs(12, scale))
    delete_button = ft.IconButton(icon=ft.Icons.DELETE_OUTLINE, visible=bool(saved))

    def on_test(e: ft.Event) -> None:
        nonlocal saved
        key_to_test = key_field.value or ""
        reuse_saved = False
        if not key_to_test and saved:
            key_to_test = decrypt_api_key(saved["encrypted_api_key"])
            reuse_saved = True

        if not key_to_test:
            status.value = "❌ API Key를 입력하세요."
            status.color = "#B3261E"
            status.update()
            return

        normalized_model = normalize_model_name(vendor_key, model_field.value)
        if normalized_model != model_field.value:
            model_field.value = normalized_model
            model_field.update()

        test_button.disabled = True
        test_button.update()
        status.value = "⏳ 연결 테스트 중…"
        status.color = BRAND_COLORS["text_muted"]
        status.update()

        def _work() -> None:
            nonlocal saved
            # 전체를 try/except/finally로 감싼다 — 원래는 test_connection()
            # 호출만 감쌌는데, 그 아래 DB 저장·복호화 쪽에서 예외가 나면(락,
            # 암호화 키 문제 등) run_thread 스레드가 조용히 죽어서 버튼이
            # "⏳ 연결 테스트 중…" 상태로 영원히 멈춘 것처럼 남았다.
            try:
                ok, message = test_connection(vendor_key, normalized_model, key_to_test)
                if not ok:
                    status.value = f"❌ {message}"
                    status.color = "#B3261E"
                    return

                encrypted = saved["encrypted_api_key"] if reuse_saved else encrypt_api_key(key_to_test)
                repo.upsert_llm_setting(vendor_key, normalized_model, encrypted)
                # 아직 활성화된 기본 생성 모델이 없을 때만 자동으로 기본 지정합니다.
                # 이미 다른 벤더(예: 글 생성용 Claude)가 기본으로 지정돼 있는데
                # 이미지 분석용 Gemini를 추가로 등록했다고 기본 생성 모델이 덮어써지면 안 됩니다.
                cur_default = repo.get_app_settings().get("default_generation_vendor")
                cur_default_setting = repo.get_llm_setting(cur_default) if cur_default else None
                auto_set_default = not (cur_default and cur_default_setting and cur_default_setting.get("is_active"))
                if auto_set_default:
                    repo.save_app_settings(default_generation_vendor=vendor_key)

                saved = repo.get_llm_setting(vendor_key)
                badge.value = _saved_badge(saved["encrypted_api_key"], saved.get("updated_at"))
                badge.visible = True
                delete_button.visible = True
                key_field.value = ""
                if auto_set_default or cur_default == vendor_key:
                    status.value = f"✅ {message} · 기본 생성 모델로 지정됨"
                else:
                    status.value = f"✅ {message} · 저장됨 (기본 생성 모델 변경은 아래에서 선택)"
                status.color = "#1B6E3C"
                badge.update()
                delete_button.update()
                key_field.update()
                on_vendor_change()
            except Exception as exc:  # noqa: BLE001 — run_thread로 돌리므로 여기서 안 잡으면 조용히 사라진다
                status.value = f"❌ {exc}"
                status.color = "#B3261E"
            finally:
                test_button.disabled = False
                status.update()
                test_button.update()

        page.run_thread(_work)

    def on_delete(e: ft.Event) -> None:
        repo.delete_llm_setting(vendor_key)
        if repo.get_app_settings().get("default_generation_vendor") == vendor_key:
            remaining = [
                k for k in VENDORS
                if k != vendor_key and (repo.get_llm_setting(k) or {}).get("is_active")
            ]
            repo.save_app_settings(default_generation_vendor=remaining[0] if remaining else None)

        nonlocal saved
        saved = None
        badge.visible = False
        delete_button.visible = False
        status.value = "삭제했습니다."
        status.color = BRAND_COLORS["text_muted"]
        status.update()
        badge.update()
        delete_button.update()
        on_vendor_change()

    test_button = ft.FilledButton("연결 테스트 · 저장", on_click=on_test, expand=True)
    delete_button.on_click = on_delete

    header = [ft.Text(f"{spec['icon']} {spec['label']}", weight=ft.FontWeight.BOLD, size=fs(14, scale))]
    if spec.get("note"):
        header.append(ft.Text(spec["note"], size=fs(11, scale), color=BRAND_COLORS["text_muted"]))

    return ft.Container(
        content=ft.Column(
            [
                *header,
                model_field,
                key_field,
                badge,
                ft.Row([test_button, delete_button]),
                status,
            ],
            spacing=8,
            tight=True,
        ),
        border=ft.Border.all(1, "#14000000"),
        border_radius=10,
        padding=14,
        expand=True,
    )


def _build_llm_tab(page: ft.Page, scale: float, on_vendor_list_changed=None) -> ft.Control:
    default_status = ft.Text("", size=fs(13, scale))
    default_dropdown = ft.Dropdown(label="기본 생성 모델 (글 작성·검수)", width=360)

    def _sync_default_controls(live: bool = False) -> None:
        active_vendors = [
            (k, repo.get_llm_setting(k))
            for k in VENDORS
            if (repo.get_llm_setting(k) or {}).get("is_active")
        ]
        default_dropdown.options = [
            ft.DropdownOption(
                key=k,
                text=f"{VENDORS[k]['icon']} {VENDORS[k]['label']} ({s['model_name']})",
            )
            for k, s in active_vendors
        ]
        current = repo.get_app_settings().get("default_generation_vendor")
        setting = repo.get_llm_setting(current) if current else None
        if current and setting and setting.get("is_active"):
            cur_spec = VENDORS[current]
            default_dropdown.value = current
            default_dropdown.disabled = False
            default_status.value = f"{cur_spec['icon']} {cur_spec['label']} ({setting['model_name']}) 사용 중"
            default_status.color = "#1B6E3C"
        else:
            default_dropdown.value = None
            default_dropdown.disabled = not active_vendors
            default_status.value = (
                "아직 기본 생성 모델이 없습니다. 아래 카드에서 [연결 테스트 · 저장]을 누르면 등록됩니다."
            )
            default_status.color = "#B3261E"
        if live:
            default_dropdown.update()
            default_status.update()

    def on_default_select(e: ft.Event) -> None:
        if default_dropdown.value:
            repo.save_app_settings(default_generation_vendor=default_dropdown.value)
            _sync_default_controls(live=True)

    default_dropdown.on_select = on_default_select

    def _on_vendor_change() -> None:
        _sync_default_controls(live=True)
        if on_vendor_list_changed:
            on_vendor_list_changed()

    _sync_default_controls(live=False)

    cards = ft.Row(
        [_vendor_card(page, k, spec, _on_vendor_change, scale) for k, spec in VENDORS.items()],
        spacing=12,
    )

    return ft.Column(
        [
            ft.Text(
                "입력한 키는 AES-256-GCM으로 암호화되어 로컬 SQLite에 저장됩니다.",
                size=fs(12, scale),
                color=BRAND_COLORS["text_muted"],
            ),
            cards,
            ft.Divider(),
            ft.Text("기본 생성 모델", weight=ft.FontWeight.BOLD, size=fs(14, scale)),
            ft.Text(
                "블로그 초안, 컴플라이언스 감사, SEO 재조정, 채널별 카피에 실제로 사용할 모델입니다. "
                "이미지 분석 모델을 별도로 쓰려면 [🖼️ 이미지 분석 (토큰)] 탭에서 이미지 분석 벤더를 고르세요.",
                size=fs(12, scale),
                color=BRAND_COLORS["text_muted"],
            ),
            ft.Row([default_dropdown, default_status], spacing=12),
        ],
        spacing=10,
        scroll=ft.ScrollMode.AUTO,
        expand=True,
    )


def _build_api_hub_section(page: ft.Page, scale: float, rebuild) -> ft.Control:
    saved = repo.get_naver_api_settings()

    id_field = ft.TextField(
        label="Client ID",
        password=True,
        can_reveal_password=True,
        hint_text="저장된 값이 있으면 비워두고 테스트해도 유지됩니다" if saved else "",
        expand=True,
    )
    secret_field = ft.TextField(
        label="Client Secret",
        password=True,
        can_reveal_password=True,
        hint_text="저장된 값이 있으면 비워두고 테스트해도 유지됩니다" if saved else "",
        expand=True,
    )
    cap_field = ft.TextField(
        label="일일 호출 상한", value=str((saved or {}).get("daily_call_cap", 500))
    )
    badge = ft.Text(
        _saved_badge(saved["encrypted_client_secret"], saved.get("updated_at")) if saved else "",
        size=fs(11, scale), color=BRAND_COLORS["text_muted"], visible=bool(saved),
    )
    status = ft.Text("", size=fs(12, scale))
    delete_button = ft.IconButton(icon=ft.Icons.DELETE_OUTLINE, visible=bool(saved))
    stats_row = ft.Row(visible=bool(saved))

    def _refresh_stats() -> None:
        current = repo.get_naver_api_settings()
        if not current:
            stats_row.visible = False
            stats_row.controls = []
        else:
            cap = int(current.get("daily_call_cap") or 0)
            stats_row.visible = True
            stats_row.controls = [
                stat_card("오늘 호출", f"{repo.naver_calls_today():,}", f"상한 {cap:,}" if cap else "상한 없음", scale=scale),
                stat_card("남은 호출", f"{keyword_research.remaining_calls_today():,}" if cap else "—", scale=scale),
                stat_card("캐시된 키워드", f"{repo.keyword_cache_size():,}", "재조회 시 호출 0", scale=scale),
            ]
        stats_row.update()

    def on_test(e: ft.Event) -> None:
        nonlocal saved
        id_to_test = id_field.value or (decrypt_api_key(saved["encrypted_client_id"]) if saved else "")
        sec_to_test = secret_field.value or (decrypt_api_key(saved["encrypted_client_secret"]) if saved else "")
        if not (id_to_test and sec_to_test):
            status.value = "❌ Client ID와 Secret을 모두 입력하세요."
            status.color = "#B3261E"
            status.update()
            return

        # 저장이 먼저다: test_connection은 실제 과금되는 호출이라, 유효한 키가
        # 저장에 실패하면 다음 시도에서 또 한 번 값을 치르게 된다.
        try:
            cap = int(cap_field.value or 0)
        except ValueError:
            status.value = "❌ 일일 호출 상한은 숫자로 입력하세요."
            status.color = "#B3261E"
            status.update()
            return
        repo.save_naver_api_settings(encrypt_api_key(id_to_test), encrypt_api_key(sec_to_test), cap)

        test_button.disabled = True
        test_button.update()
        status.value = "⏳ 연결 테스트 중…"
        status.color = BRAND_COLORS["text_muted"]
        status.update()

        def _work() -> None:
            nonlocal saved
            try:
                ok, message = keyword_research.test_connection(id_to_test, sec_to_test)
                status.value = f"{'✅' if ok else '❌'} {message}"
                status.color = "#1B6E3C" if ok else "#B3261E"

                saved = repo.get_naver_api_settings()
                badge.value = _saved_badge(saved["encrypted_client_secret"], saved.get("updated_at"))
                badge.visible = True
                delete_button.visible = True
                id_field.value = ""
                secret_field.value = ""
                badge.update()
                delete_button.update()
                id_field.update()
                secret_field.update()
                _refresh_stats()
                # 아래 "SEO 키워드 새로 고르기" 마법사의 버튼은 이 탭이 처음 그려질 때의
                # keys_ok 값으로 disabled가 고정된다 — 여기서 키를 새로
                # 저장해도 마법사 쪽엔 반영이 안 돼서, 등록 직후엔 다른
                # 메뉴로 갔다 와야만 버튼이 눌리는 문제가 있었다. 저장에
                # 성공한 지금 마법사를 다시 그려서 바로 반영한다.
                rebuild()
            except Exception as exc:  # noqa: BLE001 — run_thread로 돌리므로 여기서 안 잡으면 조용히 사라진다
                status.value = f"❌ {exc}"
                status.color = "#B3261E"
            finally:
                test_button.disabled = False
                status.update()
                test_button.update()

        page.run_thread(_work)

    def on_delete(e: ft.Event) -> None:
        nonlocal saved
        repo.delete_naver_api_settings()
        saved = None
        badge.visible = False
        delete_button.visible = False
        status.value = "삭제했습니다."
        status.color = BRAND_COLORS["text_muted"]
        status.update()
        badge.update()
        delete_button.update()
        _refresh_stats()
        rebuild()

    delete_button.on_click = on_delete
    test_button = ft.FilledButton("연결 테스트 · 저장", on_click=on_test)

    if saved:
        cap = int((saved or {}).get("daily_call_cap") or 0)
        stats_row.controls = [
            stat_card("오늘 호출", f"{repo.naver_calls_today():,}", f"상한 {cap:,}" if cap else "상한 없음", scale=scale),
            stat_card("남은 호출", f"{keyword_research.remaining_calls_today():,}" if cap else "—", scale=scale),
            stat_card("캐시된 키워드", f"{repo.keyword_cache_size():,}", "재조회 시 호출 0", scale=scale),
        ]

    return ft.Column(
        [
            ft.Text("🔍 네이버 API HUB", weight=ft.FontWeight.BOLD, size=fs(14, scale)),
            ft.Text(
                "블로그·뉴스·카페 검색과 검색어트렌드를 담당합니다. 이 API는 유료 종량제입니다 — "
                "위 일일 상한은 이 앱이 스스로 지키는 방어선입니다.",
                size=fs(11, scale), color=BRAND_COLORS["text_muted"],
            ),
            *_guide_toggle("📄 키 발급 방법 (처음이라면 여기부터)", API_HUB_GUIDE_MD, scale),
            _warn_box(
                "💳 이 API는 유료 종량제입니다. 아래 일일 상한은 이 앱이 스스로 지키는 방어선으로, "
                "상한에 도달하면 요청을 보내기 전에 차단합니다. NCP 콘솔의 [한도 및 알림]도 함께 걸어두세요.",
                scale,
            ),
            ft.Row([id_field, secret_field]),
            cap_field,
            badge,
            ft.Row([test_button, delete_button]),
            status,
            stats_row,
        ],
        spacing=8,
    )


def _build_searchad_section(page: ft.Page, scale: float, rebuild) -> ft.Control:
    saved = repo.get_searchad_settings()

    cid_field = ft.TextField(label="CUSTOMER_ID", hint_text="저장됨" if saved else "7자리 숫자", expand=True)
    key_field = ft.TextField(
        label="액세스라이선스", password=True, can_reveal_password=True,
        hint_text="저장됨" if saved else "", expand=True,
    )
    secret_field = ft.TextField(
        label="비밀키", password=True, can_reveal_password=True,
        hint_text="저장됨" if saved else "", expand=True,
    )
    badge = ft.Text(
        _saved_badge(saved["encrypted_secret_key"], saved.get("updated_at")) if saved else "",
        size=fs(11, scale), color=BRAND_COLORS["text_muted"], visible=bool(saved),
    )
    status = ft.Text("", size=fs(12, scale))
    delete_button = ft.IconButton(icon=ft.Icons.DELETE_OUTLINE, visible=bool(saved))

    def on_test(e: ft.Event) -> None:
        nonlocal saved
        cid = cid_field.value or (decrypt_api_key(saved["encrypted_customer_id"]) if saved else "")
        akey = key_field.value or (decrypt_api_key(saved["encrypted_api_key"]) if saved else "")
        asec = secret_field.value or (decrypt_api_key(saved["encrypted_secret_key"]) if saved else "")
        if not (cid and akey and asec):
            status.value = "❌ 세 값을 모두 입력하세요."
            status.color = "#B3261E"
            status.update()
            return

        test_button.disabled = True
        test_button.update()
        status.value = "⏳ 연결 테스트 중…"
        status.color = BRAND_COLORS["text_muted"]
        status.update()

        def _work() -> None:
            nonlocal saved
            try:
                ok, message = keyword_research.test_searchad_connection(cid, akey, asec)
                if not ok:
                    status.value = f"❌ {message}"
                    status.color = "#B3261E"
                    return

                repo.save_searchad_settings(encrypt_api_key(cid), encrypt_api_key(akey), encrypt_api_key(asec))
                status.value = f"✅ {message}"
                status.color = "#1B6E3C"

                saved = repo.get_searchad_settings()
                badge.value = _saved_badge(saved["encrypted_secret_key"], saved.get("updated_at"))
                badge.visible = True
                delete_button.visible = True
                cid_field.value = ""
                key_field.value = ""
                secret_field.value = ""
                badge.update()
                delete_button.update()
                cid_field.update()
                key_field.update()
                secret_field.update()
                # 아래 "SEO 키워드 새로 고르기" 마법사의 버튼은 이 탭이 처음 그려질 때의
                # keys_ok 값으로 disabled가 고정된다 — 여기서 키를 새로
                # 저장해도 마법사 쪽엔 반영이 안 돼서, 등록 직후엔 다른
                # 메뉴로 갔다 와야만 버튼이 눌리는 문제가 있었다. 저장에
                # 성공한 지금 마법사를 다시 그려서 바로 반영한다.
                rebuild()
            except Exception as exc:  # noqa: BLE001 — run_thread로 돌리므로 여기서 안 잡으면 조용히 사라진다
                status.value = f"❌ {exc}"
                status.color = "#B3261E"
            finally:
                test_button.disabled = False
                status.update()
                test_button.update()

        page.run_thread(_work)

    def on_delete(e: ft.Event) -> None:
        nonlocal saved
        repo.delete_searchad_settings()
        saved = None
        badge.visible = False
        delete_button.visible = False
        status.value = "삭제했습니다."
        status.color = BRAND_COLORS["text_muted"]
        status.update()
        badge.update()
        delete_button.update()
        rebuild()

    delete_button.on_click = on_delete
    test_button = ft.FilledButton("연결 테스트 · 저장", on_click=on_test)

    return ft.Column(
        [
            ft.Text("📊 검색광고 API (광고주센터)", weight=ft.FontWeight.BOLD, size=fs(14, scale)),
            ft.Text(
                "절대 월간 검색량과 연관키워드 발굴을 담당합니다. 완전 무료이고 위 일일 상한과 무관합니다.",
                size=fs(11, scale), color=BRAND_COLORS["text_muted"],
            ),
            *_guide_toggle("📄 키 발급 방법 (CUSTOMER_ID · 액세스라이선스 · 비밀키)", SEARCHAD_GUIDE_MD, scale),
            ft.Row([cid_field, key_field, secret_field]),
            badge,
            ft.Row([test_button, delete_button]),
            status,
        ],
        spacing=8,
    )


def _build_sweep_wizard(page: ft.Page, scale: float, rebuild, kit_id: int) -> ft.Control:
    # 진행 상태도 킷마다 따로 — 한 킷의 스윕을 하다 다른 킷으로 바꿔도 서로 덮지 않습니다.
    sweep_key = repo.kit_state_key("sweep", kit_id)
    naver_saved = repo.get_naver_api_settings()
    ad_saved = repo.get_searchad_settings()
    keys_ok = bool(naver_saved and ad_saved)
    pool = repo.get_brand_kit(kit_id).get("seo_keywords") or []

    controls: list[ft.Control] = []

    if not keys_ok:
        controls.append(_warn_box("위에서 두 API 키를 모두 등록하면 아래 버튼이 활성화됩니다.", scale))

    maintain: list[ft.Control] = []
    if not pool:
        maintain.append(ft.Text("아직 SEO 키워드가 없습니다. 위 [🔑 SEO 키워드 새로 고르기]를 먼저 끝까지(4단계 적용) 진행하세요.", size=fs(12, scale)))
    else:
        freshness = keyword_research.pool_freshness(pool)
        if freshness["stale"]:
            maintain.append(_warn_box(
                f"📉 경쟁도 만료 {len(freshness['stale'])}/{len(pool)}개 — 아래 [🔄 숫자만 새로 재기]를 눌러주세요.",
                scale, color="#B3261E", bg="#FDECEA",
            ))
        else:
            maintain.append(ft.Text(
                f"✅ 키워드 {len(pool)}개 모두 측정돼 있습니다 · "
                f"{freshness['newest_document_age']:.0f}일 전 측정 · {freshness['days_left']:.0f}일 후 만료",
                size=fs(12, scale), color="#1B6E3C",
            ))

        need = keyword_research.pool_refresh_cost(pool)
        refresh_status = ft.Text("", size=fs(12, scale))

        def on_refresh(e: ft.Event) -> None:
            refresh_button.disabled = True
            refresh_button.update()
            refresh_status.value = "⏳ 재측정하는 중…"
            refresh_status.color = BRAND_COLORS["text_muted"]
            refresh_status.update()

            def _work() -> None:
                try:
                    result = keyword_research.refresh_pool(pool)
                except Exception as exc:  # noqa: BLE001
                    refresh_status.value = f"❌ {exc}"
                    refresh_status.color = "#B3261E"
                    refresh_button.disabled = not keys_ok
                    refresh_status.update()
                    refresh_button.update()
                    return
                refresh_status.value = f"{result['billed']}개 재측정 완료 ({keyword_research.DOCUMENT_CACHE_DAYS}일간 유효)."
                refresh_status.color = "#1B6E3C"
                refresh_status.update()
                rebuild()

            page.run_thread(_work)

        refresh_button = ft.FilledButton(
            f"🔄 숫자만 새로 재기 ({need}회 호출)" if need else "🔄 숫자만 새로 재기 (전부 최신 · 0회)",
            on_click=on_refresh,
            disabled=(not need) or (not keys_ok),
        )
        maintain.append(ft.Row([refresh_button, refresh_status]))


    seed_field = ft.TextField(
        label="씨앗 키워드 (쉼표로 최대 5개)",
        expand=True,
        helper="브랜드 이름이 아니라 네이버에서 실제로 검색되는 일반적인 말이어야 합니다.",
    )
    seed_error = ft.Text("", size=fs(12, scale), color="#B3261E")

    def on_suggest(e: ft.Event) -> None:
        suggest_button.disabled = True
        suggest_button.update()
        seed_error.value = "⏳ 추천 받는 중…"
        seed_error.color = BRAND_COLORS["text_muted"]
        seed_error.update()

        def _work() -> None:
            try:
                suggested = keyword_curator.suggest_seeds(kit_id=kit_id)
            except Exception as exc:  # noqa: BLE001
                seed_error.value = f"추천 실패: {exc}"
                seed_error.color = "#B3261E"
                suggest_button.disabled = False
                seed_error.update()
                suggest_button.update()
                return
            if suggested:
                seed_field.value = ", ".join(suggested)
                seed_error.value = ""
            else:
                seed_error.value = "추천 결과가 비어 있습니다. 직접 입력해주세요."
                seed_error.color = "#B3261E"
            suggest_button.disabled = False
            seed_field.update()
            seed_error.update()
            suggest_button.update()

        page.run_thread(_work)

    suggest_button = ft.OutlinedButton("🪄 브랜드에서 추천", on_click=on_suggest)
    controls.append(ft.Row([seed_field, suggest_button]))
    controls.append(seed_error)

    sweep = repo.get_app_state(sweep_key) or {}
    stage = sweep.get("stage", 0)
    age = repo.app_state_age_days(sweep_key)
    if stage and age is not None and age > 0.02:
        controls.append(ft.Text(
            f"↩️ 진행 중이던 작업을 이어서 표시합니다 ({age * 24:.0f}시간 전 중단).",
            size=fs(11, scale), color=BRAND_COLORS["text_muted"],
        ))

    steps = ["1. 후보 찾기", "2. 경쟁도 조사", "3. 브랜드 판정", "4. 적용"]
    controls.append(ft.Row([
        ft.Container(
            content=ft.Text(
                s, size=fs(11, scale),
                color=ft.Colors.WHITE if i < stage else BRAND_COLORS["text_muted"],
            ),
            bgcolor=BRAND_COLORS["primary"] if i < stage else "#EDE6DD",
            border_radius=10,
            padding=ft.Padding.symmetric(horizontal=10, vertical=4),
        )
        for i, s in enumerate(steps)
    ]))

    vol_min_field = ft.TextField(label="최소 검색량", value=str(keyword_research.DEFAULT_MIN_VOLUME), width=140)
    vol_max_field = ft.TextField(label="최대 검색량", value=str(keyword_research.DEFAULT_MAX_VOLUME), width=140)
    cap_slider = ft.Slider(min=10, max=200, divisions=19, value=100, label="{value}개")
    adv_status = ft.Text("", size=fs(12, scale))

    def on_clear_kw_cache(e: ft.Event) -> None:
        removed = repo.clear_keyword_cache()
        adv_status.value = f"{removed}건을 삭제했습니다. 다음 조회는 전부 실제 호출을 씁니다."
        adv_status.update()

    def on_reset_sweep(e: ft.Event) -> None:
        repo.clear_app_state(sweep_key)
        rebuild()

    advanced_box = ft.Container(
        visible=False,
        padding=ft.Padding.only(top=8),
        content=ft.Column(
            [
                ft.Row([vol_min_field, vol_max_field]),
                ft.Text(f"조사할 후보 수 (= 최대 유료 호출 수): {int(cap_slider.value)}개", size=fs(12, scale)),
                cap_slider,
                ft.Text(
                    f"오늘 남은 호출 {keyword_research.remaining_calls_today():,}회",
                    size=fs(11, scale), color=BRAND_COLORS["text_muted"],
                ),
                ft.Row([
                    ft.OutlinedButton("🧹 키워드 캐시 비우기", on_click=on_clear_kw_cache),
                    *([ft.OutlinedButton("↩️ 진행 중인 작업 버리기", on_click=on_reset_sweep)] if stage else []),
                ]),
                adv_status,
            ],
            spacing=8,
        ),
    )

    def toggle_advanced(e: ft.Event) -> None:
        advanced_box.visible = not advanced_box.visible
        advanced_box.update()

    controls.append(ft.TextButton("⚙️ 고급 설정 (건드리지 않아도 됩니다)", on_click=toggle_advanced))
    controls.append(advanced_box)

    find_status = ft.Text("", size=fs(12, scale), color="#B3261E")

    def on_find(e: ft.Event) -> None:
        seeds = [s.strip() for s in (seed_field.value or "").split(",") if s.strip()]
        if not seeds:
            find_status.value = "씨앗 키워드를 채우세요. [🪄 브랜드에서 추천]을 눌러도 됩니다."
            find_status.update()
            return
        try:
            min_v = int(vol_min_field.value or keyword_research.DEFAULT_MIN_VOLUME)
            max_v = int(vol_max_field.value or keyword_research.DEFAULT_MAX_VOLUME)
        except ValueError:
            find_status.value = "검색량 범위는 숫자로 입력하세요."
            find_status.color = "#B3261E"
            find_status.update()
            return

        find_button.disabled = True
        find_button.update()
        find_status.value = "⏳ 후보를 찾는 중…"
        find_status.color = BRAND_COLORS["text_muted"]
        find_status.update()

        def _work() -> None:
            try:
                found = keyword_research.sweep_candidates(seeds, min_volume=min_v, max_volume=max_v)
            except Exception as exc:  # noqa: BLE001
                find_status.value = f"❌ {exc}"
                find_status.color = "#B3261E"
                find_button.disabled = False
                find_status.update()
                find_button.update()
                return
            repo.set_app_state(sweep_key, {"stage": 1, "candidates": found})
            rebuild()

        page.run_thread(_work)

    find_button = ft.FilledButton("🔎 1단계 · 후보 찾기 (무료)", on_click=on_find, disabled=not keys_ok)
    controls.append(find_button)
    controls.append(find_status)

    candidates = sweep.get("candidates")
    cap_n = int(cap_slider.value)
    if stage >= 1 and candidates is not None:
        if not candidates:
            controls.append(ft.Text(
                "설정한 검색량 구간에 후보가 없습니다. 씨앗을 더 일반적인 검색어로 바꿔보세요.",
                size=fs(12, scale),
            ))
        else:
            if len(candidates) < 150:
                controls.append(_warn_box(
                    f"🌱 후보가 {len(candidates)}개뿐입니다. 씨앗 키워드에 수식어가 붙어 범위가 좁아졌을 "
                    "가능성이 큽니다 — 수식어 없는 카테고리 이름으로 바꿔보세요.",
                    scale,
                ))
            cost = keyword_research.estimate_sweep_cost(candidates, limit=cap_n)
            controls.append(ft.Text(
                f"후보 {len(candidates)}개 발견. 상위 {min(len(candidates), cap_n)}개를 조사하면 "
                f"유료 호출 {cost}회를 씁니다 (오늘 남은 {keyword_research.remaining_calls_today():,}회).",
                size=fs(12, scale), color="#1B6E3C",
            ))

            def on_score(e: ft.Event) -> None:
                score_button.disabled = True
                score_button.update()
                find_status.value = "⏳ 경쟁도를 조사하는 중…"
                find_status.color = BRAND_COLORS["text_muted"]
                find_status.update()

                def _work() -> None:
                    try:
                        scored = keyword_research.score_candidates(candidates, limit=cap_n)
                    except Exception as exc:  # noqa: BLE001
                        find_status.value = f"❌ {exc}"
                        find_status.color = "#B3261E"
                        score_button.disabled = False
                        find_status.update()
                        score_button.update()
                        return
                    repo.set_app_state(sweep_key, {"stage": 2, "candidates": candidates, "scored": scored})
                    rebuild()

                page.run_thread(_work)

            score_button = ft.FilledButton(
                f"💳 2단계 · 경쟁도 조사 ({cost}회 사용)", on_click=on_score, disabled=not keys_ok
            )
            controls.append(score_button)

    scored = sweep.get("scored")
    if stage >= 2 and scored:
        columns = ["키워드", "월간 검색량", "블로그 문서 수", "점수"]
        keys = ["keyword", "estimated_volume", "documents", "score"]
        controls.append(ft.Text(f"조사 결과 {len(scored)}개", weight=ft.FontWeight.BOLD, size=fs(13, scale)))
        controls.append(ft.Column([ft.DataTable(
            columns=[ft.DataColumn(ft.Text(c)) for c in columns],
            rows=[ft.DataRow(cells=[ft.DataCell(ft.Text(str(row.get(k) or ""))) for k in keys]) for row in scored],
        )], scroll=ft.ScrollMode.AUTO))

        propose_status = ft.Text("", size=fs(12, scale))

        def on_propose(e: ft.Event) -> None:
            propose_button.disabled = True
            propose_button.update()
            propose_status.value = "⏳ 브랜드에 맞게 고르는 중…"
            propose_status.color = BRAND_COLORS["text_muted"]
            propose_status.update()

            def _work() -> None:
                try:
                    result = keyword_curator.propose(scored, current=pool, kit_id=kit_id)
                except Exception as exc:  # noqa: BLE001
                    propose_status.value = f"❌ {exc}"
                    propose_status.color = "#B3261E"
                    propose_button.disabled = False
                    propose_status.update()
                    propose_button.update()
                    return
                repo.set_app_state(sweep_key, {**sweep, "stage": 3, "proposal": result})
                rebuild()

            page.run_thread(_work)

        propose_button = ft.FilledButton(
            "🤖 3단계 · 브랜드에 맞는 것만 고르기", on_click=on_propose, disabled=not keys_ok
        )
        controls.append(propose_button)
        controls.append(propose_status)

    proposal = sweep.get("proposal")
    revive_checkboxes: list[tuple] = []
    if stage >= 3 and proposal:
        if proposal.get("error"):
            controls.append(ft.Text(f"❌ 판정 실패: {proposal['error']}", color="#B3261E", size=fs(12, scale)))
        else:
            if proposal.get("focus"):
                controls.append(_warn_box(
                    f"🎯 주력 주제: {' · '.join(proposal['focus'])} — 이 축에서 벗어난 키워드는 "
                    "검색량이 커도 제외했습니다.",
                    scale, color="#1B6E3C", bg="#E8F5E9",
                ))

            for gkey, glabel in keyword_curator.INTENT_GROUPS.items():
                rows = proposal["groups"].get(gkey) or []
                if not rows:
                    continue
                note = (
                    " · 검색 타깃에서 제외됩니다 (본문에는 등장)" if gkey == "identity"
                    else f" · 전환 가중치 {keyword_curator.GROUP_DEFAULT_WEIGHT.get(gkey)} 부여"
                )
                controls.append(ft.Text(f"[{glabel}]{note}", weight=ft.FontWeight.BOLD, size=fs(12, scale)))
                for r in rows:
                    mark = "=" if r["keyword"] in proposal["kept"] else "+"
                    vol = f"{r['estimated_volume']:,}" if r.get("estimated_volume") else "—"
                    ratio = f" · 경쟁 {r['ratio']:.0f}배" if r.get("ratio") else ""
                    controls.append(ft.Text(
                        f"{mark} {r['keyword']}  {vol}{ratio}  {r.get('reason', '')}", size=fs(11, scale)
                    ))

            def _ratio_of(row: dict) -> float | None:
                vol, docs = row.get("estimated_volume"), row.get("documents")
                return (docs / vol) if (vol and docs) else None

            excluded = sorted(
                proposal["excluded"],
                key=lambda r: _ratio_of(r) if _ratio_of(r) is not None else 9e9,
            )
            if excluded:
                controls.append(ft.Text(
                    "[제외됨 — 되살릴 수 있습니다] 경쟁이 낮은 순입니다.",
                    weight=ft.FontWeight.BOLD, size=fs(12, scale),
                ))

                def _revive_row(row: dict) -> ft.Checkbox:
                    vol = f"{row['estimated_volume']:,}" if row.get("estimated_volume") else "—"
                    ratio = _ratio_of(row)
                    label = (
                        f"{row['keyword']} — 검색 {vol}"
                        + (f" · 경쟁 {ratio:.0f}배" if ratio is not None else " · 경쟁 미측정")
                        + f" · {row.get('reason', '')}"
                    )
                    cb = ft.Checkbox(label=label)
                    revive_checkboxes.append((row["keyword"], cb))
                    return cb

                for row in excluded[:15]:
                    controls.append(_revive_row(row))
                rest = excluded[15:]
                if rest:
                    rest_column = ft.Column([_revive_row(row) for row in rest], visible=False)

                    def toggle_rest(e: ft.Event) -> None:
                        rest_column.visible = not rest_column.visible
                        rest_column.update()

                    controls.append(ft.TextButton(f"나머지 {len(rest)}개 보기/숨기기", on_click=toggle_rest))
                    controls.append(rest_column)

            apply_status = ft.Text("", size=fs(12, scale))

            def on_apply(e: ft.Event) -> None:
                revived = [kw for kw, cb in revive_checkboxes if cb.value]
                final = proposal["accepted"] + revived

                apply_button.disabled = True
                apply_button.update()
                apply_status.value = "⏳ 적용하고 측정하는 중…"
                apply_status.color = BRAND_COLORS["text_muted"]
                apply_status.update()

                def _work() -> None:
                    try:
                        applied = keyword_curator.apply_and_measure(final, proposal, kit_id)
                        repo.clear_app_state(sweep_key)
                        apply_status.value = (
                            f"✅ SEO 키워드 {applied['pool']}개로 갱신하고 측정까지 마쳤습니다 "
                            f"(호출 {applied['calls']}회)."
                        )
                        apply_status.color = "#1B6E3C"
                        apply_status.update()
                        rebuild()
                    except Exception as exc:  # noqa: BLE001 — run_thread로 돌리므로 여기서 안 잡으면 조용히 사라진다
                        apply_status.value = f"❌ {exc}"
                        apply_status.color = "#B3261E"
                        apply_button.disabled = False
                        apply_status.update()
                        apply_button.update()

                page.run_thread(_work)

            def on_discard(e: ft.Event) -> None:
                repo.clear_app_state(sweep_key)
                rebuild()

            controls.append(ft.Text(
                f"적용하면 최소 {len(proposal['accepted'])}개 — 유지 {len(proposal['kept'])} · "
                f"추가 {len(proposal['added'])} · 제거 {len(proposal['removed'])} "
                "(위에서 되살린 항목은 여기에 더해집니다)",
                size=fs(12, scale),
            ))
            apply_button = ft.FilledButton("✅ 4단계 · 적용", on_click=on_apply, disabled=not keys_ok)
            controls.append(ft.Row([
                apply_button,
                ft.OutlinedButton("무시하고 버리기", on_click=on_discard),
            ]))
            controls.append(apply_status)

    # 두 기능을 제목부터 나눕니다. 예전엔 둘이 "키워드 갱신" 한 제목 아래 있었고
    # [숫자만 새로 재기]가 1~4단계 위에 놓여 있어서, "갱신"이 1~4단계와 별개의
    # (앞이나 뒤에 하는) 작업처럼 읽혔습니다. 실제로는 4단계 [적용]이 곧 SEO
    # 키워드 갱신이고, 숫자 재기는 목록을 건드리지 않는 유지 작업입니다.
    pick = ft.Column(
        [
            ft.Text("🔑 SEO 키워드 새로 고르기 (추천 → 1~4단계)", weight=ft.FontWeight.BOLD, size=fs(16, scale)),
            ft.Text(
                "위에서 고른 킷의 SEO 키워드 전체를 새로 정하는 곳입니다. 4단계 [✅ 적용]을 눌러야 "
                "바뀌고, 적용하면서 새 키워드의 수치도 함께 측정하므로 따로 할 일은 없습니다. "
                "처음 한 번, 그리고 사업 방향이 바뀌거나 몇 달에 한 번 새 검색어를 반영하고 싶을 때 돌리세요.",
                size=fs(12, scale), color=BRAND_COLORS["text_muted"],
            ),
            *controls,
        ],
        spacing=8,
    )
    keep = ft.Column(
        [
            ft.Text("🔄 현재 키워드 수치 유지 (30일마다)", weight=ft.FontWeight.BOLD, size=fs(16, scale)),
            ft.Text(
                "키워드 목록은 그대로 두고 검색량·경쟁도 숫자만 다시 잽니다. 측정값은 30일 동안만 유효하고, "
                "만료되면 글마다 타깃 키워드를 고르는 점수가 0으로 계산됩니다. 만료 경고가 뜰 때 누르세요.",
                size=fs(12, scale), color=BRAND_COLORS["text_muted"],
            ),
            *maintain,
        ],
        spacing=8,
    )
    add = _build_category_adder(page, scale, rebuild, keys_ok, pool, kit_id)
    return ft.Column([pick, ft.Divider(), add, ft.Divider(), keep], spacing=12)


def _build_category_adder(
    page: ft.Page, scale: float, rebuild, keys_ok: bool, pool: list[str], kit_id: int
) -> ft.Control:
    cat_key = repo.kit_state_key("category_sweep", kit_id)
    state = repo.get_app_state(cat_key) or {}
    stage = state.get("stage", 0)
    status = ft.Text("", size=fs(12, scale), color="#B3261E")

    def _busy(button: ft.Control, text: str) -> None:
        button.disabled = True
        button.update()
        status.value = text
        status.color = BRAND_COLORS["text_muted"]
        status.update()

    def _fail(button: ft.Control, exc: Exception) -> None:
        status.value = f"❌ {exc}"
        status.color = "#B3261E"
        button.disabled = not keys_ok
        status.update()
        button.update()

    category_field = ft.TextField(
        label="추가할 사업 분야",
        value=state.get("category", ""),
        hint_text="예: 교육, 체험 수업, 기업 강의, 단체 주문",
        expand=True,
    )

    def on_find(e: ft.Event) -> None:
        category = (category_field.value or "").strip()
        if not category:
            status.value = "분야 이름을 적어주세요. 평소 부르는 말 그대로면 됩니다 (예: 교육)."
            status.update()
            return
        _busy(find_button, f"⏳ '{category}' 분야 검색어를 만들고 후보를 고르는 중…")

        def _work() -> None:
            try:
                found = keyword_curator.find_category_candidates(category, current=pool, kit_id=kit_id)
            except Exception as exc:  # noqa: BLE001
                _fail(find_button, exc)
                return
            repo.set_app_state(cat_key, {"stage": 1, **found})
            rebuild()

        page.run_thread(_work)

    find_button = ft.FilledButton("🔎 이 분야 후보 찾기 (검색 무료)", on_click=on_find, disabled=not keys_ok)

    controls: list[ft.Control] = [
        ft.Text("➕ 사업 분야 추가 (기존 키워드는 그대로)", weight=ft.FontWeight.BOLD, size=fs(16, scale)),
        ft.Text(
            "교육·체험처럼 검색량이 작은 분야는 위의 [새로 고르기]에서 주력 상품에 밀려 빠집니다. "
            "분야 이름만 적으면 AI가 그 분야 고객이 실제로 검색하는 말로 바꿔 후보를 찾고, "
            f"그 분야 안에서만 비교해 최대 {keyword_curator.CATEGORY_KEYWORD_LIMIT}개를 기존 키워드에 더합니다. "
            "전환 가중치와 측정도 자동으로 처리됩니다.",
            size=fs(12, scale), color=BRAND_COLORS["text_muted"],
        ),
        _warn_box(
            "분야가 많아질수록 블로그 주제가 흩어져 네이버 노출 점수가 약해질 수 있습니다. "
            "실제로 글을 꾸준히 쓸 분야만 추가하세요.",
            scale,
        ),
    ]
    if not pool:
        controls.append(ft.Text(
            "먼저 위 [🔑 SEO 키워드 새로 고르기]로 주력 키워드를 정한 뒤 분야를 더하세요.",
            size=fs(12, scale),
        ))
        return ft.Column(controls, spacing=8)

    controls += [ft.Row([category_field, find_button]), status]
    if state.get("done"):
        controls.append(ft.Text(state["done"], size=fs(12, scale), color="#1B6E3C"))

    def on_discard(e: ft.Event) -> None:
        repo.clear_app_state(cat_key)
        rebuild()

    relevant = state.get("relevant")
    if stage >= 1 and relevant is not None:
        controls.append(ft.Text(
            f"AI가 만든 검색어: {', '.join(state.get('seeds') or [])} → 연관 후보 {state.get('found', 0)}개 중 "
            f"'{state.get('category')}' 분야에 맞는 것 {len(relevant)}개",
            size=fs(12, scale),
        ))
        if not relevant:
            controls.append(_warn_box(
                "이 분야에 맞는 후보가 없습니다. 분야 이름을 바꿔 보시고(예: '교육' → '체험 수업'), "
                "그래도 없으면 🧵 브랜드 킷의 핵심 사실에 이 분야에서 실제로 하는 일을 한두 줄 적어주세요. "
                "AI는 핵심 사실을 보고 검색어를 만듭니다.",
                scale,
            ))
            controls.append(ft.OutlinedButton("처음부터 다시", on_click=on_discard))
        elif stage == 1:
            for r in sorted(relevant, key=lambda r: r.get("volume") or 0, reverse=True):
                controls.append(ft.Text(
                    f"· {r['keyword']}  월 {r.get('volume', 0):,}회  {r.get('reason', '')}", size=fs(11, scale)
                ))
            cost = keyword_curator.category_score_cost(relevant)

            def on_score(e: ft.Event) -> None:
                _busy(score_button, "⏳ 경쟁도를 조사하고 고르는 중…")

                def _work() -> None:
                    try:
                        proposal = keyword_curator.propose_category(relevant)
                    except Exception as exc:  # noqa: BLE001
                        _fail(score_button, exc)
                        return
                    repo.set_app_state(cat_key, {**state, "stage": 2, "proposal": proposal})
                    rebuild()

                page.run_thread(_work)

            score_button = ft.FilledButton(
                f"💳 경쟁도 조사 후 {keyword_curator.CATEGORY_KEYWORD_LIMIT}개 고르기 ({cost}회 사용)",
                on_click=on_score, disabled=not keys_ok,
            )
            controls.append(ft.Text(
                f"오늘 남은 호출 {keyword_research.remaining_calls_today():,}회",
                size=fs(11, scale), color=BRAND_COLORS["text_muted"],
            ))
            controls.append(ft.Row([score_button, ft.OutlinedButton("버리기", on_click=on_discard)]))

    proposal = state.get("proposal")
    if stage >= 2 and proposal:
        revive: list[tuple[str, ft.Checkbox]] = []
        if not proposal["accepted"]:
            controls.append(_warn_box(
                "조사해 보니 노출을 노릴 만한 키워드가 없습니다 (검색량이 너무 적거나 경쟁이 너무 많음). "
                "아래에서 직접 되살릴 수는 있습니다.",
                scale,
            ))
        crowded = [
            r for rows in proposal["groups"].values() for r in rows
            if (r.get("ratio") or 0) > keyword_curator.MAX_DOCS_PER_SEARCH
        ]
        if crowded:
            controls.append(_warn_box(
                f"이 분야는 주력 키워드보다 경쟁이 높습니다 (검색 1회당 글 "
                f"{min(r['ratio'] for r in crowded):,.0f}개 이상, 주력 기준은 "
                f"{keyword_curator.MAX_DOCS_PER_SEARCH}개). 그중 가장 덜 붐비는 것을 골랐습니다. "
                "상위 노출은 쉽지 않지만, 이 분야 글이 엉뚱한 상품 키워드로 쓰이는 것은 막아줍니다.",
                scale,
            ))
        for gkey, glabel in keyword_curator.INTENT_GROUPS.items():
            for r in proposal["groups"].get(gkey) or []:
                weight = (
                    "검색 타깃 제외(본문에는 등장)" if gkey == "identity"
                    else f"전환 가중치 {keyword_curator.GROUP_DEFAULT_WEIGHT.get(gkey)}"
                )
                vol = f"{r['estimated_volume']:,}" if r.get("estimated_volume") else "—"
                ratio = f" · 경쟁 {r['ratio']:.0f}배" if r.get("ratio") else ""
                controls.append(ft.Text(
                    f"+ {r['keyword']}  검색 {vol}{ratio} · [{glabel}] {weight} · {r.get('reason', '')}",
                    size=fs(12, scale),
                ))
        if proposal["excluded"]:
            controls.append(ft.Text("[제외됨 — 체크하면 함께 추가합니다]", weight=ft.FontWeight.BOLD, size=fs(12, scale)))
            for r in proposal["excluded"]:
                vol = f"{r['estimated_volume']:,}" if r.get("estimated_volume") else "—"
                cb = ft.Checkbox(label=f"{r['keyword']} — 검색 {vol} · {r.get('reason', '')}")
                revive.append((r["keyword"], cb))
                controls.append(cb)

        def on_apply(e: ft.Event) -> None:
            added = proposal["accepted"] + [kw for kw, cb in revive if cb.value]
            if not added:
                status.value = "추가할 키워드가 없습니다."
                status.update()
                return
            _busy(apply_button, "⏳ 추가하고 측정하는 중…")

            def _work() -> None:
                try:
                    applied = keyword_curator.apply_and_measure(pool + added, proposal, kit_id)
                except Exception as exc:  # noqa: BLE001
                    _fail(apply_button, exc)
                    return
                repo.set_app_state(cat_key, {"done": (
                    f"✅ '{state.get('category')}' 분야 키워드 {len(added)}개({', '.join(added)})를 더했습니다 — "
                    f"SEO 키워드 총 {applied['pool']}개 (호출 {applied['calls']}회). 🧵 브랜드 킷에서 확인할 수 있습니다."
                )})
                rebuild()

            page.run_thread(_work)

        apply_button = ft.FilledButton("✅ 기존 키워드에 추가", on_click=on_apply, disabled=not keys_ok)
        controls.append(ft.Row([apply_button, ft.OutlinedButton("버리기", on_click=on_discard)]))

    return ft.Column(controls, spacing=8)


def _build_keyword_diagnostic_section(page: ft.Page, scale: float, kit_id: int) -> ft.Control:
    pool = repo.get_brand_kit(kit_id).get("seo_keywords") or []
    naver_saved = repo.get_naver_api_settings()
    result_box = ft.Container()
    status = ft.Text("", size=fs(12, scale), color="#B3261E")

    def on_run(e: ft.Event) -> None:
        run_button.disabled = True
        run_button.update()
        status.value = "⏳ 진단하는 중…"
        status.color = BRAND_COLORS["text_muted"]
        status.update()

        def _work() -> None:
            try:
                ranked = keyword_research.rank_keywords(pool)
            except Exception as exc:  # noqa: BLE001
                status.value = f"❌ {exc}"
                status.color = "#B3261E"
                run_button.disabled = False
                status.update()
                run_button.update()
                return
            status.value = ""
            run_button.disabled = False
            status.update()
            run_button.update()
            if not ranked:
                result_box.content = ft.Text("결과가 없습니다.", size=fs(12, scale))
            else:
                columns = ["키워드", "월간 검색량", "트렌드(상대)", "블로그 문서 수", "점수"]
                keys = ["keyword", "estimated_volume", "demand", "documents", "score"]
                result_box.content = ft.Column([ft.DataTable(
                    columns=[ft.DataColumn(ft.Text(c)) for c in columns],
                    rows=[
                        ft.DataRow(cells=[ft.DataCell(ft.Text(str(row.get(k) or ""))) for k in keys])
                        for row in ranked
                    ],
                )], scroll=ft.ScrollMode.AUTO)
            result_box.update()

        page.run_thread(_work)

    run_button = ft.OutlinedButton("키워드 진단 실행", on_click=on_run)

    body: list[ft.Control] = [
        ft.Text(
            "🔬 지금 키워드가 얼마나 좋은지만 보기 (아무것도 바뀌지 않습니다)",
            weight=ft.FontWeight.BOLD, size=fs(13, scale),
        )
    ]
    if not pool:
        body.append(ft.Text("이 킷에 SEO 키워드가 없습니다.", size=fs(12, scale)))
    elif not naver_saved:
        body.append(ft.Text("먼저 위에서 키를 등록하세요.", size=fs(12, scale)))
    else:
        body.append(ft.Text(f"대상 {len(pool)}개: {', '.join(pool)}", size=fs(12, scale)))
        body.append(run_button)
        body.append(status)
        body.append(result_box)
    return ft.Column(body, spacing=8)


# 설정 화면에서 마지막으로 고른 키워드 작업 대상 킷. 화면을 다시 열어도 같은 킷에서 이어가게 합니다.
_KEYWORD_KIT_STATE_KEY = "settings_keyword_kit"


def _initial_keyword_kit_id() -> int | None:
    saved = (repo.get_app_state(_KEYWORD_KIT_STATE_KEY) or {}).get("kit_id")
    active = {k["id"] for k in repo.list_brand_kits()}
    return saved if saved in active else repo.default_brand_kit_id()


def _build_naver_tab(page: ft.Page, scale: float) -> ft.Control:
    wizard_box = ft.Container()
    diag_box = ft.Container()
    selected = [_initial_keyword_kit_id()]

    def rebuild() -> None:
        wizard_box.content = _build_sweep_wizard(page, scale, rebuild, selected[0])
        diag_box.content = _build_keyword_diagnostic_section(page, scale, selected[0])
        wizard_box.update()
        diag_box.update()

    def on_kit(kit_id: int) -> None:
        selected[0] = kit_id
        repo.set_app_state(_KEYWORD_KIT_STATE_KEY, {"kit_id": kit_id})
        rebuild()

    wizard_box.content = _build_sweep_wizard(page, scale, rebuild, selected[0])
    diag_box.content = _build_keyword_diagnostic_section(page, scale, selected[0])

    kit_section = ft.Column(
        [
            ft.Text("🧵 키워드 작업 대상 킷", weight=ft.FontWeight.BOLD, size=fs(16, scale)),
            ft.Text(
                "아래 'SEO 키워드 새로 고르기'·'사업 분야 추가'·'현재 키워드 수치 유지'·진단은 모두 "
                "여기서 고른 킷에만 반영됩니다. 키워드 측정값(검색량·문서 수) 캐시는 킷끼리 함께 써서, "
                "같은 키워드를 두 킷에서 써도 호출이 두 번 나가지 않습니다.",
                size=fs(12, scale), color=BRAND_COLORS["text_muted"],
            ),
            kit_dropdown(selected[0], on_kit, label="대상 킷"),
        ],
        spacing=8,
    )

    return ft.Column(
        [
            ft.Text(
                "블로그·뉴스·카페 검색과 검색어트렌드, 절대 검색량·연관키워드 발굴을 담당합니다.",
                size=fs(12, scale), color=BRAND_COLORS["text_muted"],
            ),
            _build_api_hub_section(page, scale, rebuild),
            ft.Divider(),
            _build_searchad_section(page, scale, rebuild),
            ft.Divider(),
            kit_section,
            wizard_box,
            ft.Divider(),
            diag_box,
        ],
        spacing=10,
        scroll=ft.ScrollMode.AUTO,
        expand=True,
    )


def _build_vision_tab(scale: float) -> ft.Control:
    settings = repo.get_app_settings()

    vision_enabled = ft.Switch(
        label="이미지 분석 사용",
        value=settings.get("vision_enabled", True),
    )

    registered = [
        v for v in vision_capable_vendors() if (repo.get_llm_setting(v) or {}).get("is_active")
    ]
    default_label = "(기본 생성 모델과 동일)"
    current_vv = settings.get("vision_vendor")
    vendor_dropdown = ft.Dropdown(
        label="이미지 분석 벤더",
        value=current_vv if current_vv in registered else default_label,
        options=[ft.DropdownOption(key=default_label, text=default_label)]
        + [ft.DropdownOption(key=v, text=f"{VENDORS[v]['icon']} {VENDORS[v]['label']}") for v in registered],
        expand=True,
    )

    quality_keys = list(vision.QUALITY_PRESETS.keys())
    current_q = settings.get("vision_quality") or vision.DEFAULT_QUALITY
    quality_group = ft.RadioGroup(
        value=current_q if current_q in quality_keys else quality_keys[0],
        content=ft.Column(
            [
                ft.Radio(
                    value=k,
                    label=f"{vision.QUALITY_PRESETS[k]['label']} · {vision.QUALITY_PRESETS[k]['max_edge']}px",
                )
                for k in quality_keys
            ]
        ),
    )
    quality_hint = ft.Text(
        vision.QUALITY_PRESETS[current_q]["hint"] if current_q in quality_keys else "",
        size=fs(11, scale),
        color=BRAND_COLORS["text_muted"],
    )

    def on_quality_change(e: ft.Event) -> None:
        preset = vision.QUALITY_PRESETS.get(quality_group.value)
        quality_hint.value = preset["hint"] if preset else ""
        quality_hint.update()

    quality_group.on_change = on_quality_change

    save_status = ft.Text("", size=fs(12, scale), color="#1B6E3C")

    def on_save(e: ft.Event) -> None:
        chosen = vendor_dropdown.value
        repo.save_app_settings(
            vision_enabled=vision_enabled.value,
            vision_quality=quality_group.value,
            vision_vendor=None if chosen == default_label else chosen,
        )
        save_status.value = "✅ 저장했습니다."
        save_status.update()

    save_button = ft.FilledButton("이미지 분석 설정 저장", icon=ft.Icons.SAVE, on_click=on_save)

    # --- 벤더별 토큰 비용 표 ---
    cost_columns = ["벤더"] + [
        f"{preset['label']} ({preset['max_edge']}px)" for preset in vision.QUALITY_PRESETS.values()
    ] + ["원본 3024x4032 (미축소)"]
    cost_rows = []
    for v in ["google", "openai", "anthropic"]:
        cells = [ft.DataCell(ft.Text(v))]
        for preset in vision.QUALITY_PRESETS.values():
            edge = preset["max_edge"]
            cells.append(ft.DataCell(ft.Text(str(vision.estimate_image_tokens(v, edge, edge)))))
        cells.append(ft.DataCell(ft.Text(str(vision.estimate_image_tokens(v, 3024, 4032)))))
        cost_rows.append(ft.DataRow(cells=cells))
    cost_table = ft.DataTable(
        columns=[ft.DataColumn(ft.Text(c)) for c in cost_columns],
        rows=cost_rows,
    )

    cached_count = repo.vision_cache_size()
    cache_stat = stat_card("캐시된 사진 캡션", f"{cached_count:,}", "재사용 시 추가 토큰 0", scale=scale)
    clear_status = ft.Text("", size=fs(12, scale))

    def on_clear_cache(e: ft.Event) -> None:
        removed = repo.clear_vision_cache()
        clear_status.value = f"{removed}건을 삭제했습니다."
        clear_status.update()

    return ft.Column(
        [
            ft.Text(
                "사진 분석 토큰 최소화: 캡션 캐시 · 메모 분리 프롬프트 · 벤더별 최소 과금 해상도 · "
                "배치 호출 · 출력 상한.",
                size=fs(12, scale),
                color=BRAND_COLORS["text_muted"],
            ),
            ft.Row([vision_enabled]),
            vendor_dropdown,
            ft.Divider(),
            ft.Text("분석 화질", weight=ft.FontWeight.BOLD, size=fs(14, scale)),
            quality_group,
            quality_hint,
            ft.Row([save_button, save_status]),
            ft.Divider(),
            ft.Text("벤더별 사진 1장 토큰 비용", weight=ft.FontWeight.BOLD, size=fs(14, scale)),
            cost_table,
            ft.Divider(),
            ft.Row([cache_stat, ft.OutlinedButton("🧹 캐시 비우기", on_click=on_clear_cache)]),
            clear_status,
        ],
        spacing=10,
        scroll=ft.ScrollMode.AUTO,
        expand=True,
    )


# 단가 입력 칸 옆에 거는 각 벤더의 공식 가격 페이지. 단가는 여기서 확인해 직접 입력합니다.
PRICE_PAGES = {
    "google": "https://ai.google.dev/gemini-api/docs/pricing",
    "openai": "https://openai.com/api/pricing/",
    "anthropic": "https://www.anthropic.com/pricing",
}


def _won(value: float) -> str:
    return f"{value:,.0f}원"


def _usd(value: float) -> str:
    return f"${value:,.4f}" if value < 1 else f"${value:,.2f}"


def _money_card(label: str, summary: dict, scale: float) -> ft.Control:
    note = f"{_usd(summary['cost_usd'])} · {summary['calls']:,}회"
    if summary["unpriced_calls"]:
        note += f" · 단가 미등록 {summary['unpriced_calls']:,}회 제외"
    return stat_card(label, _won(summary["cost_krw"]), note, scale=scale)


def _parse_amount(text: str | None) -> float | None:
    cleaned = (text or "").replace(",", "").replace("원", "").replace("$", "").strip()
    if not cleaned:
        return None
    return float(cleaned)


def _build_cost_section(scale: float, rebuild) -> list[ft.Control]:
    """요청 3: 단가 표 · 환율 · 월 예산 · 누적 금액 · 벤더·모델별 표."""
    rate = repo.get_usd_krw()
    budget = repo.get_monthly_budget_krw()
    today, month, total = repo.cost_today(), repo.cost_this_month(), repo.cost_all_time()
    posts = repo.generated_post_count()
    status = ft.Text("", size=fs(12, scale))

    def say(msg: str, ok: bool = True) -> None:
        status.value = msg
        status.color = "#1B6E3C" if ok else "#B3261E"
        status.update()

    # --- 환율 · 예산 ---
    rate_field = ft.TextField(label="환율 (1달러 = ?원)", value=f"{rate:,.0f}", width=200, dense=True)
    budget_field = ft.TextField(
        label="월 예산 (원, 비우면 경고 끔)", value=f"{budget:,.0f}" if budget else "", width=240, dense=True,
    )

    def on_save_rate(e: ft.Event) -> None:
        try:
            repo.set_usd_krw(_parse_amount(rate_field.value) or 0)
            repo.set_monthly_budget_krw(_parse_amount(budget_field.value))
        except ValueError as exc:
            say(f"저장하지 못했습니다: {exc}", ok=False)
            return
        rebuild("✅ 환율·예산을 저장했습니다. 금액은 지금 환율로 다시 계산해 보여 줍니다(달러 금액은 그대로).")

    # --- 단가 표 ---
    prices = {(p["vendor"], p["model"]): p for p in repo.list_model_prices()}
    rows: list[ft.Control] = []

    def price_row(vendor: str, model: str) -> ft.Control:
        price = prices.get((vendor, model))

        def fmt(v):
            return "" if v is None else f"{v:g}"

        f_in = ft.TextField(label="입력 $/100만", value=fmt(price and price["input_per_mtok"]), width=130, dense=True)
        f_out = ft.TextField(label="출력 $/100만", value=fmt(price and price["output_per_mtok"]), width=130, dense=True)
        f_cache = ft.TextField(
            label="캐시 입력 $/100만", value=fmt(price and price["cached_input_per_mtok"]), width=150, dense=True,
            tooltip="비우면 캐시에서 읽은 입력도 일반 입력 단가로 계산합니다.",
        )

        def on_save(e: ft.Event) -> None:
            try:
                p_in, p_out = _parse_amount(f_in.value), _parse_amount(f_out.value)
                p_cache = _parse_amount(f_cache.value)
                if p_in is None or p_out is None:
                    raise ValueError("입력·출력 단가를 모두 넣어주세요.")
                filled = repo.save_model_price(vendor, model, p_in, p_out, p_cache)
            except ValueError as exc:
                say(f"{model}: {exc}", ok=False)
                return
            extra = f" 단가가 없던 지난 기록 {filled:,}건을 이 단가로 채웠습니다." if filled else ""
            rebuild(f"✅ {model} 단가를 저장했습니다.{extra} 앞으로의 호출은 호출할 때의 단가로 계산합니다.")

        def on_delete(e: ft.Event) -> None:
            repo.delete_model_price(vendor, model)
            rebuild(f"{model} 단가를 지웠습니다. 이미 계산된 지난 금액은 그대로입니다.")

        async def on_open_pricing(e: ft.Event) -> None:
            if vendor in PRICE_PAGES:
                await ft.UrlLauncher().launch_url(PRICE_PAGES[vendor])

        label = VENDORS.get(vendor, {}).get("label", vendor)
        return ft.Row([
            ft.Column([
                ft.Text(model, weight=ft.FontWeight.BOLD, size=fs(12, scale)),
                ft.Text(label + ("" if price else " · 단가 미등록"), size=fs(10, scale),
                        color=BRAND_COLORS["text_muted"] if price else "#B3261E"),
            ], spacing=0, width=220),
            f_in, f_out, f_cache,
            ft.FilledButton("저장", on_click=on_save),
            *([ft.IconButton(icon=ft.Icons.DELETE_OUTLINE, tooltip="단가 지우기", on_click=on_delete)] if price else []),
            *([ft.TextButton("공식 가격 보기", icon=ft.Icons.OPEN_IN_NEW, on_click=on_open_pricing)]
              if vendor in PRICE_PAGES else []),
        ], spacing=8, wrap=True)

    for m in repo.usage_models():
        rows.append(price_row(m["vendor"], m["model"]))
    if not rows:
        rows.append(ft.Text("아직 등록된 모델이 없습니다. 🔑 LLM 벤더 탭에서 모델을 등록하면 여기에 나옵니다.",
                            size=fs(11, scale), color=BRAND_COLORS["text_muted"]))

    new_vendor = ft.Dropdown(
        label="벤더", width=180, dense=True, value="google",
        options=[ft.DropdownOption(key=k, text=v["label"]) for k, v in VENDORS.items()],
    )
    new_model = ft.TextField(label="모델 이름 (호출 기록과 똑같이)", width=260, dense=True)

    def on_add_model(e: ft.Event) -> None:
        if not (new_model.value or "").strip():
            say("모델 이름을 적어주세요.", ok=False)
            return
        rows.insert(len(rows), price_row(new_vendor.value, new_model.value.strip()))
        price_box.controls = list(rows)
        price_box.update()
        say("아래 줄에 단가를 넣고 [저장]을 누르세요.")

    price_box = ft.Column(list(rows), spacing=6)

    # --- 벤더·모델별 표 ---
    by_model = repo.cost_by_model()
    if by_model:
        model_table: ft.Control = ft.DataTable(
            columns=[ft.DataColumn(ft.Text(c)) for c in ("벤더", "모델", "호출 수", "입력 토큰", "캐시 입력", "출력 토큰", "금액")],
            rows=[
                ft.DataRow(cells=[
                    ft.DataCell(ft.Text(VENDORS.get(r["vendor"] or "", {}).get("label", r["vendor"] or "-"))),
                    ft.DataCell(ft.Text(r["model"] or "-")),
                    ft.DataCell(ft.Text(f"{r['calls']:,}")),
                    ft.DataCell(ft.Text(f"{r['input_tokens']:,}")),
                    ft.DataCell(ft.Text(f"{r['cached_input_tokens']:,}")),
                    ft.DataCell(ft.Text(f"{r['output_tokens']:,}")),
                    ft.DataCell(ft.Text(
                        ("단가 미등록" if r["unpriced_calls"] == r["calls"] else
                         f"{_won(r['cost_krw'])} ({_usd(r['cost_usd'])})"
                         + (f" · 미등록 {r['unpriced_calls']}회" if r["unpriced_calls"] else "")),
                        color="#B3261E" if r["unpriced_calls"] else None,
                    )),
                ])
                for r in by_model
            ],
        )
    else:
        model_table = ft.Text("아직 호출 기록이 없습니다.", color=BRAND_COLORS["text_muted"])

    avg = (total["cost_krw"] / posts) if posts else 0
    budget_msg = repo.budget_message()
    controls: list[ft.Control] = [
        ft.Text("💰 AI 사용 금액 (추정)", weight=ft.FontWeight.BOLD, size=fs(16, scale)),
        ft.Container(
            content=ft.Text(
                "예산 참고용 추정값입니다 — 등록한 단가와 환율로 계산합니다. 실제 청구 금액은 각 벤더 콘솔에서 확인하세요. "
                "단가가 등록되지 않은 모델의 호출은 0원이 아니라 '단가 미등록'으로 따로 셉니다. "
                "캐시 입력 단가를 비워 두면 캐시에서 읽은 입력도 일반 입력 단가로 계산합니다.",
                size=fs(11, scale), color=BRAND_COLORS["text_muted"],
            ),
            bgcolor="#F3F1EC", padding=10, border_radius=8,
        ),
    ]
    if budget_msg:
        controls.append(ft.Container(
            content=ft.Text(budget_msg, size=fs(12, scale), color="#8A6D3B"),
            bgcolor="#FFF6E5", padding=10, border_radius=8,
        ))
    budget_note = ""
    if budget:
        used = repo.budget_status()
        budget_note = f"월 예산 {_won(budget)} 중 {used['ratio'] * 100:.0f}% 사용"
    controls += [
        ft.Row([
            _money_card("오늘", today, scale),
            _money_card("이번 달", month, scale),
            _money_card("전체 누적", total, scale),
            stat_card("글 1건당 평균", _won(avg) if posts else "-", f"생성 완료된 글 {posts:,}건 기준", scale=scale),
        ], spacing=12, wrap=True),
        *([ft.Text(budget_note, size=fs(12, scale))] if budget_note else []),
        ft.Row([rate_field, budget_field, ft.FilledButton("환율·예산 저장", on_click=on_save_rate)], spacing=8, wrap=True),
        ft.Text(f"환율 기본값은 {repo.DEFAULT_USD_KRW:,.0f}원입니다 — 실제 환율로 고쳐 쓰세요. 월 예산의 "
                f"{'%·'.join(str(x) for x in repo.BUDGET_WARN_LEVELS)}%에 이르면 대시보드·워크벤치에 안내합니다(생성을 막지는 않음).",
                size=fs(10, scale), color=BRAND_COLORS["text_muted"]),
        status,
        ft.Divider(),
        ft.Text("단가 표 (100만 토큰당 USD)", weight=ft.FontWeight.BOLD, size=fs(14, scale)),
        ft.Text("단가는 자주 바뀌므로 기본값을 넣어 두지 않았습니다. [공식 가격 보기]에서 확인해 넣으세요. "
                "이미지 분석도 입력 토큰으로 계산합니다. 처음 단가를 넣으면 그 모델의 지난 기록(금액 없음)을 이 단가로 한 번 채웁니다.",
                size=fs(11, scale), color=BRAND_COLORS["text_muted"]),
        price_box,
        ft.Row([new_vendor, new_model, ft.OutlinedButton("모델 줄 추가", on_click=on_add_model)], spacing=8, wrap=True),
        ft.Divider(),
        ft.Text("벤더·모델별 사용량", weight=ft.FontWeight.BOLD, size=fs(14, scale)),
        ft.Column([model_table], scroll=ft.ScrollMode.AUTO),
        ft.Divider(),
    ]
    return controls


def _build_usage_tab(scale: float) -> ft.Control:
    root = ft.Container()

    def rebuild(message: str | None = None) -> None:
        root.content = _usage_tab_body(scale, rebuild, message)
        root.update()

    root.content = _usage_tab_body(scale, rebuild, None)
    return root


def _usage_tab_body(scale: float, rebuild, message: str | None) -> ft.Control:
    totals = repo.usage_totals()
    spent = totals["input_tokens"] + totals["output_tokens"]
    saved = totals["saved_tokens"]
    saved_money = repo.cost_all_time()["saved_cost_krw"]

    stats = ft.Row(
        [
            stat_card("총 입력 토큰", f"{totals['input_tokens']:,}", scale=scale),
            stat_card("총 출력 토큰", f"{totals['output_tokens']:,}", scale=scale),
            stat_card("절약된 토큰", f"{saved:,}",
                      "캐시 적중 + 해상도 축소 + 배치" + (f" · 약 {_won(saved_money)}(추정)" if saved_money else ""),
                      scale=scale),
            stat_card("캐시 적중", f"{totals['cache_hits']:,}", f"분석한 사진 {totals['images']:,}장", scale=scale),
        ],
        spacing=12, wrap=True,
    )

    progress_section: list[ft.Control] = []
    if saved + spent:
        ratio = saved / (saved + spent)
        progress_section = [
            ft.ProgressBar(value=ratio, width=400),
            ft.Text(f"절감률 {ratio * 100:.1f}%", size=fs(12, scale)),
        ]

    recent = repo.recent_usage(50)
    rate = repo.get_usd_krw()
    if recent:
        columns = ["시각", "종류", "벤더", "모델", "사진", "입력", "캐시", "출력", "절약", "금액", "메모"]
        def cell(row, k):
            if k == "cost":
                if row.get("cost_usd") is None:
                    return "단가 미등록" if (row.get("est_input_tokens") or row.get("est_output_tokens")) else ""
                return _won(row["cost_usd"] * rate)
            return str(row.get(k) or "")
        keys = ["ts", "kind", "vendor", "model", "image_count", "est_input_tokens", "cached_input_tokens",
                "est_output_tokens", "est_saved_tokens", "cost", "note"]
        usage_table = ft.DataTable(
            columns=[ft.DataColumn(ft.Text(c)) for c in columns],
            rows=[
                ft.DataRow(cells=[ft.DataCell(ft.Text(cell(row, k))) for k in keys])
                for row in recent
            ],
        )
        usage_section: ft.Control = ft.Column([usage_table], scroll=ft.ScrollMode.AUTO)
    else:
        usage_section = ft.Text("아직 호출 기록이 없습니다.", color=BRAND_COLORS["text_muted"])

    cost_controls = _build_cost_section(scale, rebuild)
    if message:
        cost_controls.insert(1, ft.Text(message, size=fs(12, scale), color="#1B6E3C"))

    return ft.Column(
        [
            *cost_controls,
            ft.Text("📈 토큰 사용량", weight=ft.FontWeight.BOLD, size=fs(16, scale)),
            stats,
            *progress_section,
            ft.Text(
                "입력/출력 토큰은 각 프로바이더가 응답에 실어 보낸 실제 usage 값입니다(응답에 없으면 글자 수로 추정). "
                "캐시는 입력 토큰 중 프롬프트 캐시에서 읽은 양으로, 이 기능을 넣은 뒤의 기록부터 따로 셉니다. "
                "절약분은 저장된 사진을 축소·캐시·배치 없이 그대로 보냈을 때와의 차이(추정)입니다.",
                size=fs(11, scale),
                color=BRAND_COLORS["text_muted"],
            ),
            ft.Divider(),
            ft.Text("최근 호출", weight=ft.FontWeight.BOLD, size=fs(14, scale)),
            usage_section,
        ],
        spacing=10,
        scroll=ft.ScrollMode.AUTO,
        expand=True,
    )


def _naver_format_controls(scale: float) -> list[ft.Control]:
    """🎨 네이버 서식 붙여넣기 방식 (요청 4). 에디터가 HTML 인용·구분선·표를 살리지 않으면 기호로 바꿉니다."""
    saved = (repo.get_app_state(formatting.NAVER_FORMAT_STATE_KEY) or {}).get("value") or formatting.DEFAULT_NAVER_FORMAT_MODE
    group = ft.RadioGroup(value=saved, content=ft.Column([
        ft.Radio(value="editor", label="에디터 서식 우선 — 인용구·구분선·요약 박스를 HTML 서식으로 붙여 넣습니다"),
        ft.Radio(value="symbol", label="기호로 대체 — 인용구는 ❝ ❞, 구분선은 ────, 요약 박스는 📌 제목 + 선으로 넣습니다"),
    ], spacing=2))
    status = ft.Text("", size=fs(12, scale))

    def on_save(e: ft.Event) -> None:
        repo.set_app_state(formatting.NAVER_FORMAT_STATE_KEY, {"value": group.value})
        status.value = f"✅ 저장했습니다 — {formatting.NAVER_FORMAT_MODES[group.value]}. 다음 [지금 게시]부터 적용됩니다."
        status.color = "#1B6E3C"
        status.update()

    return [
        ft.Text("🎨 네이버 서식 붙여넣기", weight=ft.FontWeight.BOLD, size=fs(14, scale)),
        ft.Text("굵게·형광·소제목·목록은 어느 쪽이든 서식으로 붙여 넣습니다. 스마트에디터가 인용구·구분선·표를 "
                "제대로 바꾸지 못하면 '기호로 대체'를 고르세요. 인용구·구분선 모양(따옴표형·선형 등)은 에디터 툴바에서만 "
                "고를 수 있어 자동으로 바꾸지 않습니다.", size=fs(11, scale), color=BRAND_COLORS["text_muted"]),
        group,
        ft.FilledButton("서식 방식 저장", on_click=on_save),
        status,
    ]


def _build_channels_tab(scale: float) -> ft.Control:
    """📣 생성 채널 — 초안을 만들 때 함께 만들 SNS 채널을 고릅니다.

    네이버 블로그 본문은 항상 만듭니다: 인스타·X·쇼츠 글은 그 본문(검수까지 마친 사실)을
    원문으로 삼아 쓰기 때문입니다. 끈 채널은 작성·검수 호출을 아예 하지 않아, 운영하지 않는
    채널에 매 글마다 AI 비용이 나가지 않습니다. 이미 만들어 둔 내용은 지우지 않습니다.
    """
    active = set(enabled_channels(repo.get_app_settings()))
    checks = {key: ft.Checkbox(label=label, value=key in active) for key, label in SNS_CHANNELS.items()}
    status = ft.Text("", size=fs(12, scale))

    def on_save(e: ft.Event) -> None:
        chosen = [key for key, cb in checks.items() if cb.value]
        repo.save_app_settings(enabled_channels=chosen)
        names = ", ".join(SNS_CHANNELS[k] for k in chosen) if chosen else "SNS 채널 없음"
        status.value = f"✅ 저장했습니다 — 네이버 블로그 + {names}. 다음 초안 생성부터 적용됩니다."
        status.color = "#1B6E3C"
        status.update()

    return ft.Column(
        [
            ft.Text(
                "초안을 만들 때 함께 만들 채널을 고릅니다. 끈 채널은 AI 호출을 하지 않아 비용이 들지 않고, "
                "워크벤치 미리보기와 결과 탭에서도 빠집니다. 이미 만들어 둔 내용은 지우지 않습니다.",
                size=fs(12, scale), color=BRAND_COLORS["text_muted"],
            ),
            ft.Checkbox(label="📗 네이버 블로그 (항상 생성)", value=True, disabled=True),
            ft.Text(
                "네이버 블로그 본문은 끌 수 없습니다 — 인스타·X·쇼츠 글이 이 본문을 원문으로 삼아 만들어집니다.",
                size=fs(11, scale), color=BRAND_COLORS["text_muted"],
            ),
            *checks.values(),
            ft.FilledButton("저장", on_click=on_save),
            status,
            ft.Divider(),
            *_naver_format_controls(scale),
        ],
        spacing=10,
        scroll=ft.ScrollMode.AUTO,
        expand=True,
    )


def _build_transfer_tab(page: ft.Page, scale: float) -> ft.Control:
    """📦 데이터 옮기기 — 한 PC에서 세팅한 브랜드 킷·회사 설정·API 키·AI 단가·키워드 측정값·제목 이력을
    파일로 다른 PC에 옮긴다(core/transfer.py). 받는 PC의 글·사진·게시 기록·네이버 로그인은 건드리지 않는다."""
    local = transfer.summary_of_local()
    export_checks = {
        key: ft.Checkbox(
            label=f"{label}\n    이 PC: {local[key]}",
            value=not (key == "api_keys" and local[key].startswith("(")),  # 키가 없으면 기본 해제
        )
        for key, label in transfer.PARTS.items()
    }
    export_pw = ft.TextField(label=f"비밀번호 (API 키를 내보낼 때 필수, {transfer.MIN_PASSWORD_LENGTH}자 이상)",
                             password=True, can_reveal_password=True, width=420)
    export_pw2 = ft.TextField(label="비밀번호 확인", password=True, can_reveal_password=True, width=420)
    export_status = ft.Text("", size=fs(12, scale))

    def _show(text: ft.Text, message: str, ok: bool) -> None:
        text.value, text.color = message, ("#1B6E3C" if ok else "#B3261E")
        text.update()

    async def on_export(e: ft.Event) -> None:
        parts = [k for k, cb in export_checks.items() if cb.value]
        if "api_keys" in parts and (export_pw.value or "") != (export_pw2.value or ""):
            _show(export_status, "비밀번호와 확인이 다릅니다.", False)
            return
        try:
            data = transfer.export_bundle(parts, export_pw.value or None)
        except transfer.TransferError as exc:
            _show(export_status, f"❌ {exc}", False)
            return
        path = await ft.FilePicker().save_file(
            dialog_title="OSMU 데이터 내보내기", file_name=transfer.default_file_name(),
            file_type=ft.FilePickerFileType.CUSTOM, allowed_extensions=[transfer.FILE_EXTENSION],
        )
        if not path:
            return
        if not path.endswith("." + transfer.FILE_EXTENSION):
            path += "." + transfer.FILE_EXTENSION
        try:
            with open(path, "wb") as fh:
                fh.write(data)
        except OSError as exc:
            _show(export_status, f"❌ 저장하지 못했습니다: {exc}", False)
            return
        _show(export_status, f"✅ 저장했습니다: {path}", True)

    import_state: dict = {}
    import_info = ft.Text("", size=fs(12, scale))
    import_checks = {key: ft.Checkbox(label=label, value=True, visible=False) for key, label in transfer.PARTS.items()}
    import_pw = ft.TextField(label="내보낼 때 정한 비밀번호 (API 키를 가져올 때)", password=True,
                             can_reveal_password=True, width=420, visible=False)
    import_status = ft.Text("", size=fs(12, scale), selectable=True)
    import_button = ft.FilledButton("📥 이 PC에 가져오기", disabled=True)

    async def on_pick(e: ft.Event) -> None:
        files = await ft.FilePicker().pick_files(
            dialog_title="OSMU 데이터 파일 열기", with_data=True,
            file_type=ft.FilePickerFileType.CUSTOM, allowed_extensions=[transfer.FILE_EXTENSION],
        )
        if not files:
            return
        raw = files[0].bytes
        if raw is None and getattr(files[0], "path", None):
            with open(files[0].path, "rb") as fh:
                raw = fh.read()
        try:
            bundle = transfer.read_bundle(raw or b"")
        except transfer.TransferError as exc:
            import_info.value, import_info.color = f"❌ {exc}", "#B3261E"
            import_button.disabled = True
            for cb in import_checks.values():
                cb.visible = False
            import_pw.visible = False
            page.update()
            return
        import_state["raw"] = raw
        parts = set(bundle.get("parts") or [])
        preview = transfer.preview_bundle(bundle)
        for key, cb in import_checks.items():
            cb.visible = key in parts
            cb.value = key in parts
            cb.label = f"{transfer.PARTS[key]}\n    → {preview.get(key, '')}"
        import_pw.visible = "api_keys" in parts
        import_info.value = f"📄 {files[0].name} · 만든 시각 {bundle.get('created_at', '-')}"
        import_info.color = BRAND_COLORS["text"]
        import_button.disabled = False
        import_status.value = ""
        page.update()

    def on_import(e: ft.Event) -> None:
        parts = [k for k, cb in import_checks.items() if cb.visible and cb.value]
        try:
            result = transfer.import_bundle(import_state.get("raw") or b"", parts, import_pw.value or None)
        except transfer.TransferError as exc:
            _show(import_status, f"❌ {exc}", False)
            return
        backup = result.pop("backup", None)
        lines = ["✅ " + " / ".join(result.values())]
        if backup:
            lines.append(f"가져오기 전 DB를 복사해 두었습니다: {backup}")
        lines.append("다른 메뉴로 갔다 오면 바뀐 값이 보입니다.")
        _show(import_status, "\n".join(lines), True)

    import_button.on_click = on_import

    return ft.Column(
        [
            ft.Text(
                "담당자가 여러 명일 때, 한 PC에서 세팅한 내용을 파일 하나로 다른 PC에 옮깁니다. 가져와도 받는 PC의 "
                "글·사진·게시 기록·네이버 로그인은 바뀌지 않습니다. 브랜드 킷을 점검한 뒤 담당자에게 나눠 줄 때도 씁니다.",
                size=fs(12, scale), color=BRAND_COLORS["text_muted"],
            ),
            ft.Text(f"옮기지 않는 것: {transfer.NOT_TRANSFERRED}.", size=fs(11, scale), color=BRAND_COLORS["text_muted"]),
            ft.Text("📤 내보내기 (기준 PC)", weight=ft.FontWeight.BOLD, size=fs(14, scale)),
            *export_checks.values(),
            ft.Row([export_pw, export_pw2], wrap=True),
            _warn_box(
                "API 키는 이 비밀번호로 암호화되어 파일에 들어갑니다. 파일과 비밀번호를 모두 가진 사람은 키를 쓸 수 있으니, "
                "비밀번호는 파일과 다른 경로(전화·대면 등)로 알려 주세요. 브랜드 킷·회사 설정은 암호화하지 않습니다.", scale,
            ),
            ft.FilledButton("📤 파일로 내보내기", on_click=on_export),
            export_status,
            ft.Divider(),
            ft.Text("📥 가져오기 (받는 PC)", weight=ft.FontWeight.BOLD, size=fs(14, scale)),
            ft.Text(
                "브랜드 킷은 이름으로 맞춥니다 — 같은 이름의 킷은 내용을 바꾸고, 없는 킷은 새로 만듭니다. 이 PC에만 있는 "
                "킷은 그대로 둡니다. 가져오기 직전의 DB는 데이터 폴더의 backups에 복사해 둡니다(최근 5개).",
                size=fs(11, scale), color=BRAND_COLORS["text_muted"],
            ),
            ft.OutlinedButton("📂 .osmu 파일 열기", on_click=on_pick),
            import_info,
            *import_checks.values(),
            import_pw,
            import_button,
            import_status,
            ft.Divider(),
            ft.Text(
                "PC를 통째로 바꿀 때(글·사진까지 전부 옮길 때)는 이 기능 대신 앱을 닫고 데이터 폴더 "
                f"({DATA_DIR}) 전체를 새 PC의 같은 자리에 복사하세요.",
                size=fs(11, scale), color=BRAND_COLORS["text_muted"], selectable=True,
            ),
        ],
        spacing=8, scroll=ft.ScrollMode.AUTO, expand=True,
    )


def build(page: ft.Page, state: AppState) -> ft.Control:
    scale = state.font_scale
    vision_box = ft.Container(content=_build_vision_tab(scale), padding=10)

    def refresh_vision_tab() -> None:
        vision_box.content = _build_vision_tab(scale)
        vision_box.update()

    return ft.Column(
        [
            ft.Text("설정 · 토큰", size=fs(24, scale), weight=ft.FontWeight.BOLD),
            _build_font_scale_section(state, scale),
            ft.Tabs(
                length=6,
                expand=True,
                content=ft.Column(
                    expand=True,
                    controls=[
                        ft.TabBar(
                            tabs=[
                                ft.Tab(label="🔑 LLM 벤더"),
                                ft.Tab(label="📣 생성 채널"),
                                ft.Tab(label="🔍 네이버 API"),
                                ft.Tab(label="🖼️ 이미지 분석 (토큰)"),
                                ft.Tab(label="📈 사용량"),
                                ft.Tab(label="📦 데이터 옮기기"),
                            ]
                        ),
                        ft.TabBarView(
                            expand=True,
                            controls=[
                                ft.Container(content=_build_llm_tab(page, scale, refresh_vision_tab), padding=10),
                                ft.Container(content=_build_channels_tab(scale), padding=10),
                                ft.Container(content=_build_naver_tab(page, scale), padding=10),
                                vision_box,
                                ft.Container(content=_build_usage_tab(scale), padding=10),
                                ft.Container(content=_build_transfer_tab(page, scale), padding=10),
                            ],
                        ),
                    ],
                ),
            ),
        ],
        expand=True,
        spacing=10,
    )
