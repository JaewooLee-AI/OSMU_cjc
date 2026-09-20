"""Flet port of views/05_naver_publish.py — 네이버 블로그 반자동 게시.

네이버가 봇의 Smart Editor ONE 게시를 적극적으로 막기 때문에 이 화면은
"반"자동이다 — 저장된 로그인 세션으로 실제 Chrome 창을 열어 제목·본문·사진을
순서대로 붙여넣어주고, 담당자가 직접 [발행]을 눌러야 한다. `발행` 팝업의 태그
칸은 자동화가 아예 닿지 않아, 여기서 태그를 보여주고 복사만 시킨다.

`open_naver_login_session()`은 최대 2분까지 블로킹되는 호출이라 워크벤치의
초안 생성과 같은 이유로 `page.run_thread()`로 돌린다 — 그러지 않으면 로그인
창이 열려 있는 동안 앱 전체가 멈춘 것처럼 보인다. 반면 `trigger_naver_publish`
는 원본처럼 detached subprocess를 띄우고 바로 반환하는 non-blocking 호출이라
별도 스레드가 필요 없다.
"""
from __future__ import annotations

import flet as ft

import flet_app.simulators as sim
from ai_workers.naver_publisher import (
    clear_naver_session,
    naver_session_exists,
    open_naver_login_session,
    split_publish_error,
    trigger_naver_publish,
)
from core import repo

from flet_app.components.collapsible import collapsible
from flet_app.state import AppState
from flet_app.theme import BRAND_COLORS, fs
from flet_app.views.workbench_view import _copy_field


def _publish_error_box(campaign: dict, scale: float) -> list[ft.Control]:
    summary, detail = split_publish_error(campaign.get("publish_error") or "")
    if not summary:
        return []
    out: list[ft.Control] = [
        ft.Container(
            content=ft.Text(summary, size=fs(12, scale), color="#B3261E"),
            bgcolor="#FDECEA", padding=10, border_radius=8,
        )
    ]
    if detail:
        out += collapsible(
            "자세한 오류 내용",
            ft.Text(detail, size=fs(11, scale), selectable=True, font_family="monospace"),
        )
    return out


def _fields_for_channel(page: ft.Page, scale: float, campaign: dict, channel: str) -> ft.Control:
    if channel == "naver":
        return ft.Column([
            _copy_field("제목", campaign.get("title") or "", page, scale),
            _copy_field("본문", campaign.get("content") or "", page, scale),
        ], spacing=8)
    if channel == "instagram":
        controls: list[ft.Control] = [
            _copy_field("캡션", campaign.get("instagram_caption") or "", page, scale),
        ]
        tags = campaign.get("instagram_hashtags") or []
        if tags:
            controls.append(_copy_field("해시태그", " ".join(tags), page, scale))
        return ft.Column(controls, spacing=8)
    if channel == "x":
        controls = []
        tweets = campaign.get("x_content") or []
        for i, tweet in enumerate(tweets, start=1):
            controls.append(_copy_field(f"트윗 {i}/{len(tweets)}", tweet, page, scale, f"{len(tweet)}자"))
        tags = campaign.get("x_hashtags") or []
        if tags:
            controls.append(_copy_field("해시태그", " ".join(tags), page, scale))
        return ft.Column(controls, spacing=8)
    if channel == "shorts":
        script = campaign.get("shorts_script") or {}
        controls = []
        if script.get("title"):
            controls.append(_copy_field("제목", script["title"], page, scale))
        if script.get("hook"):
            controls.append(_copy_field("훅 (첫 3초)", script["hook"], page, scale))
        if script.get("scenes"):
            text = "\n".join(
                f"CUT {i}. {s.get('caption', '')}" for i, s in enumerate(script["scenes"], start=1)
            )
            controls.append(_copy_field("자막 전체", text, page, scale))
        if script.get("hashtags"):
            controls.append(_copy_field("해시태그", " ".join(script["hashtags"]), page, scale))
        return ft.Column(controls, spacing=8)
    return ft.Column()


def _build_content_preview(page: ft.Page, scale: float, brand_kit: dict, campaign: dict) -> list[ft.Control]:
    initial_channel = "naver"
    preview_box = ft.Container(content=sim.render(initial_channel, campaign, brand_kit=brand_kit))
    fields_box = ft.Container(content=_fields_for_channel(page, scale, campaign, initial_channel))

    channel_group = ft.RadioGroup(
        value=initial_channel,
        content=ft.Row(
            [ft.Radio(value=k, label=f"{v['icon']} {v['label']}") for k, v in sim.CHANNELS.items()],
            wrap=True,
        ),
    )

    def on_channel_change(e: ft.Event) -> None:
        channel = channel_group.value
        preview_box.content = sim.render(channel, campaign, brand_kit=brand_kit)
        fields_box.content = _fields_for_channel(page, scale, campaign, channel)
        preview_box.update()
        fields_box.update()

    channel_group.on_change = on_channel_change

    return collapsible(
        "📄 콘텐츠 보기 (전체 채널)",
        ft.Column([
            channel_group,
            ft.Container(content=preview_box, padding=ft.Padding.only(top=8)),
            ft.Divider(),
            fields_box,
        ], spacing=8),
    )


def _build_card(
    page: ft.Page, scale: float, brand_kit: dict, campaign: dict,
    key_prefix: str, publish_label: str, allow_manual_complete: bool, refresh_all,
) -> ft.Control:
    campaign_id = campaign["id"]
    confirm_delete = {"value": False}
    action_box = ft.Container()
    publish_status = ft.Text("", size=fs(12, scale))

    def build_actions() -> ft.Control:
        if confirm_delete["value"]:
            def on_confirm(e: ft.Event) -> None:
                repo.delete_campaign(campaign_id)
                refresh_all()

            def on_cancel(e: ft.Event) -> None:
                confirm_delete["value"] = False
                action_box.content = build_actions()
                action_box.update()

            return ft.Row([
                ft.FilledButton("🗑️ 삭제 확인", on_click=on_confirm, expand=True),
                ft.OutlinedButton("취소", on_click=on_cancel, expand=True),
                ft.Text("삭제하면 되돌릴 수 없습니다.", size=fs(11, scale), color=BRAND_COLORS["text_muted"]),
            ], spacing=8)

        def on_publish(e: ft.Event) -> None:
            result = trigger_naver_publish(campaign_id)
            publish_status.value = result["message"]
            publish_status.color = "#1B6E3C" if result["success"] else "#B3261E"
            publish_status.update()

        buttons: list[ft.Control] = [
            ft.FilledButton(
                publish_label, on_click=on_publish, expand=True,
                disabled=not naver_session_exists(),
                tooltip=None if naver_session_exists() else "먼저 네이버에 로그인해주세요.",
            ),
        ]
        if allow_manual_complete:
            def on_manual(e: ft.Event) -> None:
                repo.update_campaign(campaign_id, status="published", publish_error=None)
                refresh_all()

            buttons.append(ft.OutlinedButton("✅ 수동으로 완료", on_click=on_manual, expand=True))

        def on_ask_delete(e: ft.Event) -> None:
            confirm_delete["value"] = True
            action_box.content = build_actions()
            action_box.update()

        buttons.append(ft.OutlinedButton("🗑️ 삭제", on_click=on_ask_delete, expand=True))

        return ft.Column([ft.Row(buttons, spacing=8), publish_status], spacing=6)

    action_box.content = build_actions()

    icon = "📰" if campaign["source_type"] == "news" else "✍️"
    card_children: list[ft.Control] = [
        ft.Text(f"{icon} {campaign.get('title') or '(제목 없음)'}", size=fs(15, scale), weight=ft.FontWeight.BOLD),
    ]
    if key_prefix == "pending":
        photo_count = len(campaign.get("storage_file_paths") or [])
        card_children.append(ft.Text(
            f"업데이트: {campaign.get('updated_at', '')} · 사진 {photo_count}장",
            size=fs(11, scale), color=BRAND_COLORS["text_muted"],
        ))
    else:
        card_children.append(ft.Text(
            f"게시: {campaign.get('updated_at', '')}", size=fs(11, scale), color=BRAND_COLORS["text_muted"],
        ))
    if campaign.get("source_url"):
        card_children.append(ft.Text(
            f"📰 원문: {campaign['source_url']}", size=fs(11, scale), color=BRAND_COLORS["text_muted"],
        ))

    card_children += _publish_error_box(campaign, scale)
    card_children += _build_content_preview(page, scale, brand_kit, campaign)

    hashtags = campaign.get("naver_hashtags") or []
    if hashtags:
        hint = (
            "🏷️ 태그는 자동으로 입력되지 않습니다. 아래를 복사해 [발행] 창의 태그 칸에 붙여넣어 주세요."
            if key_prefix == "pending" else "🏷️ [발행] 창 태그 칸에 붙여넣을 해시태그"
        )
        card_children += [
            ft.Text(hint, size=fs(11, scale), color=BRAND_COLORS["text_muted"]),
            ft.Container(
                content=ft.Text(" ".join(hashtags), size=fs(12, scale), selectable=True),
                bgcolor="#F3F1EC", padding=8, border_radius=6,
            ),
        ]

    if key_prefix == "pending":
        card_children.append(ft.Text(
            "직접 로그인 없이 [📄 콘텐츠 보기]에서 복사해 네이버에 손으로 붙여넣었다면, "
            "아래 [✅ 수동으로 완료]를 눌러 이 목록에서 정리하세요.",
            size=fs(11, scale), color=BRAND_COLORS["text_muted"],
        ))

    card_children.append(action_box)

    return ft.Container(
        content=ft.Column(card_children, spacing=8),
        border=ft.Border.all(1, "#E4DCC8"), border_radius=10, padding=14,
    )


def _build_login_section(page: ft.Page, scale: float, naver_blog_id: str, refresh_all) -> ft.Control:
    if naver_session_exists():
        def on_logout(e: ft.Event) -> None:
            clear_naver_session()
            refresh_all()

        return ft.Row([
            ft.Container(
                content=ft.Text(
                    f"🔑 네이버 로그인됨 (blog.naver.com/{naver_blog_id})",
                    size=fs(12, scale), color="#1B6E3C",
                ),
                bgcolor="#E8F5E9", padding=10, border_radius=8, expand=True,
            ),
            ft.OutlinedButton("🧹 로그아웃", on_click=on_logout),
        ])

    login_status = ft.Text("", size=fs(12, scale))
    login_button = ft.FilledButton("🔓 네이버 로그인", disabled=not naver_blog_id)

    def on_login(e: ft.Event) -> None:
        # 최대 2분 블로킹되는 호출이라 별도 스레드로 — 그러지 않으면 로그인 창이
        # 열려 있는 동안 앱 전체가 멈춘 것처럼 보인다(초안 생성과 같은 문제).
        login_button.disabled = True
        login_button.update()
        login_status.value = "⏳ Chrome 창에서 네이버 로그인을 완료해주세요 (최대 2분 대기)…"
        login_status.color = BRAND_COLORS["text_muted"]
        login_status.update()

        def _work() -> None:
            result = open_naver_login_session(naver_blog_id)
            if result["success"]:
                refresh_all()
            else:
                login_status.value = result["message"]
                login_status.color = "#B3261E"
                login_button.disabled = False
                login_status.update()
                login_button.update()

        page.run_thread(_work)

    login_button.on_click = on_login

    info_children: list[ft.Control] = [
        ft.Text("아직 로그인하지 않았습니다. 게시하려면 먼저 로그인해주세요.", size=fs(12, scale), color="#8A6D3B"),
    ]
    if not naver_blog_id:
        info_children.append(ft.Text(
            "브랜드 킷에서 네이버 블로그 아이디를 먼저 등록해주세요.", size=fs(12, scale), color="#2F6B7A",
        ))
    info_children.append(ft.Text(
        "로그인 정보는 이 컴퓨터에만 저장되며, 언제든 [로그아웃]으로 지울 수 있습니다.",
        size=fs(10, scale), color=BRAND_COLORS["text_muted"],
    ))

    return ft.Column([
        ft.Text("🔑 네이버 로그인", weight=ft.FontWeight.BOLD, size=fs(14, scale)),
        ft.Row([
            ft.Container(content=ft.Column(info_children, spacing=4), expand=3),
            ft.Column([login_button, login_status], expand=1),
        ]),
    ], spacing=8)


def _build_tabs(page: ft.Page, scale: float, brand_kit: dict, pending: list, published: list, refresh_all) -> ft.Control:
    if pending:
        pending_controls: list[ft.Control] = [
            _build_card(page, scale, brand_kit, c, "pending", "🚀 지금 게시", True, refresh_all) for c in pending
        ]
    else:
        pending_controls = [ft.Text(
            "게시 대기 중인 콘텐츠가 없습니다. 워크벤치에서 [네이버 게시 대기열로]를 눌러 보내세요.",
            size=fs(12, scale), color=BRAND_COLORS["text_muted"],
        )]

    published_controls: list[ft.Control] = []
    if published:
        published_controls.append(ft.Text(
            "네이버 창에서 [발행]을 누르지 못했다면 [다시 게시]로 같은 내용을 다시 불러올 수 있습니다. "
            "더 이상 필요 없는 글은 [삭제]로 목록에서 지우세요.",
            size=fs(11, scale), color=BRAND_COLORS["text_muted"],
        ))
        published_controls += [
            _build_card(page, scale, brand_kit, c, "published", "🔁 다시 게시", False, refresh_all) for c in published
        ]
    else:
        published_controls = [ft.Text(
            "게시 완료된 콘텐츠가 없습니다.", size=fs(12, scale), color=BRAND_COLORS["text_muted"],
        )]

    return ft.Tabs(
        length=2,
        expand=True,
        content=ft.Column(
            expand=True,
            controls=[
                ft.TabBar(tabs=[
                    ft.Tab(label=f"게시 대기 {len(pending)}"),
                    ft.Tab(label=f"게시 완료 {len(published)}"),
                ]),
                ft.TabBarView(
                    expand=True,
                    controls=[
                        ft.Container(
                            content=ft.Column(pending_controls, spacing=10, scroll=ft.ScrollMode.AUTO),
                            padding=ft.Padding.only(top=10),
                        ),
                        ft.Container(
                            content=ft.Column(published_controls, spacing=10, scroll=ft.ScrollMode.AUTO),
                            padding=ft.Padding.only(top=10),
                        ),
                    ],
                ),
            ],
        ),
    )


def build(page: ft.Page, state: AppState) -> ft.Control:
    scale = state.font_scale
    brand_kit = repo.get_brand_kit()
    naver_blog_id = (brand_kit.get("naver_blog_id") or "").strip()

    login_box = ft.Container()
    lists_box = ft.Container(expand=True)

    def refresh_all() -> None:
        login_box.content = _build_login_section(page, scale, naver_blog_id, refresh_all)
        pending = repo.list_campaigns(statuses=["ready_to_publish"])
        published = repo.list_campaigns(statuses=["published"])
        lists_box.content = _build_tabs(page, scale, brand_kit, pending, published, refresh_all)
        login_box.update()
        lists_box.update()

    login_box.content = _build_login_section(page, scale, naver_blog_id, refresh_all)
    pending = repo.list_campaigns(statuses=["ready_to_publish"])
    published = repo.list_campaigns(statuses=["published"])
    lists_box.content = _build_tabs(page, scale, brand_kit, pending, published, refresh_all)

    return ft.Column(
        [
            ft.Text("네이버 블로그 반자동 게시", size=fs(24, scale), weight=ft.FontWeight.BOLD),
            ft.Text(
                "[지금 게시]를 누르면 Chrome 창이 열리고 제목·본문·사진이 자동으로 입력됩니다. "
                "내용을 확인한 뒤 마지막 [발행] 버튼만 그 창에서 직접 눌러주세요.",
                size=fs(12, scale), color=BRAND_COLORS["text_muted"],
            ),
            login_box,
            ft.Divider(),
            lists_box,
        ],
        spacing=10, scroll=ft.ScrollMode.AUTO, expand=True,
    )
