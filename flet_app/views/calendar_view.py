"""📅 콘텐츠 캘린더 (요청 2).

"이번 주에 무엇을 올릴지"를 한눈에 봅니다. 글은 발행 예정일(campaigns.scheduled_date) 칸에
상태별 색 칩으로, 아직 글로 만들지 않은 주제(topics)는 점선 칩으로 보입니다.

- 칩을 누르면 워크벤치에서 그 글을 엽니다(대시보드와 같은 연결).
- 빈 날짜를 누르면 그 날짜로 새 글을 만들거나, 예정일 없는 글·주제를 그 날짜에 둡니다.
- 칩을 다른 날짜로 끌어 놓으면 예정일이 바뀝니다. 오른쪽 주제 목록의 주제도 날짜 칸으로 끌어 놓을 수 있습니다.
  끌기가 불편하면 칩 옆 📅 버튼으로 날짜를 고릅니다.
- 반복 규칙("매주 화요일 · 가발관리 킷 · 균형 모드")은 앞으로 4주의 빈 자리(주제)를 만듭니다.
  화면을 열 때마다 자동으로 만들지 않습니다 — 담당자가 지운 자리가 되살아나지 않게(core/repo.apply_rules).
"""
from __future__ import annotations

import calendar as pycal
from datetime import date, datetime, timedelta, time

import flet as ft

from ai_workers import content_mode
from core import repo

from flet_app.components.date_field import date_field
from flet_app.kit_picker import kit_dropdown
from flet_app.state import AppState
from flet_app.theme import BRAND_COLORS, STATUS_LABELS, fs

# 요청서의 상태 색: 소재 대기(회색) · 생성 중(파랑) · 초안(노랑) · 게시 대기(주황) · 게시 완료(초록) · 실패(빨강)
STATUS_COLORS = {
    "awaiting_media": ("#9E9E9E", ft.Colors.WHITE),
    "queued": ("#1E88E5", ft.Colors.WHITE),
    "processing": ("#1E88E5", ft.Colors.WHITE),
    "draft": ("#FBC02D", "#3E2E00"),
    "ready_to_publish": ("#FB8C00", ft.Colors.WHITE),
    "published": ("#43A047", ft.Colors.WHITE),
    "failed": ("#E53935", ft.Colors.WHITE),
}
LEGEND = [
    ("awaiting_media", "소재 대기"), ("processing", "생성 중"), ("draft", "초안"),
    ("ready_to_publish", "게시 대기"), ("published", "게시 완료"), ("failed", "실패"),
]
DRAG_GROUP = "calendar"
MAX_CHIPS_MONTH = 4


def month_weeks(year: int, month: int) -> list[list[date]]:
    """월요일부터 시작하는 주 단위 날짜 목록(앞뒤 달의 날짜 포함)."""
    return pycal.Calendar(firstweekday=0).monthdatescalendar(year, month)


def week_of(anchor: date) -> list[date]:
    start = anchor - timedelta(days=anchor.weekday())
    return [start + timedelta(days=i) for i in range(7)]


def _campaign_title(c: dict) -> str:
    return c.get("title") or (c.get("memo") or "").split("\n")[0][:30] or c.get("source_title") or "(제목 없음)"


def build(page: ft.Page, state: AppState) -> ft.Control:
    scale = state.font_scale
    view = {"anchor": date.today().replace(day=1), "week_anchor": date.today(), "mode": "month", "kit": None}
    root = ft.Container(expand=True)

    def refresh() -> None:
        root.content = _body()
        root.update()

    def snack(text: str) -> None:
        page.show_dialog(ft.SnackBar(ft.Text(text)))

    def open_campaign(campaign_id: str) -> None:
        state.pending_workbench_campaign_id = campaign_id
        if state.navigate_to_workbench:
            state.navigate_to_workbench()

    # --- 날짜 바꾸기 (끌기 대신) ------------------------------------------------
    def pick_new_date(current: str | None, on_pick) -> None:
        try:
            start = date.fromisoformat((current or "")[:10])
        except ValueError:
            start = date.today()

        def changed(e: ft.Event) -> None:
            value = e.control.value
            if isinstance(value, datetime):
                if value.tzinfo is not None:
                    value = value.astimezone()
                value = value.date()
            if isinstance(value, date):
                on_pick(value.isoformat())

        page.show_dialog(ft.DatePicker(
            value=datetime.combine(start, time(12, 0)), first_date=datetime(2020, 1, 1),
            last_date=datetime(2035, 12, 31), help_text="새 날짜", cancel_text="취소", confirm_text="옮기기",
            on_change=changed,
        ))

    def move_payload(payload: str, day: str) -> None:
        kind, _, ident = (payload or "").partition(":")
        if kind == "c":
            repo.move_campaign_date(ident, day)
        elif kind == "t":
            repo.update_topic(int(ident), planned_date=day)
        refresh()

    # --- 칩 ---------------------------------------------------------------------
    def campaign_chip(c: dict, compact: bool) -> ft.Control:
        bg, fg = STATUS_COLORS.get(c["status"], ("#757575", ft.Colors.WHITE))
        overdue = repo.is_overdue(c)
        label = ("⚠️ " if overdue else "") + _campaign_title(c)
        series = f" · {c['series_name']}" if c.get("series_name") and not compact else ""
        chip = ft.Container(
            content=ft.Row([
                ft.Text(label + series, size=fs(10 if compact else 11, scale), color=fg, max_lines=1,
                        overflow=ft.TextOverflow.ELLIPSIS, expand=True),
                ft.IconButton(icon=ft.Icons.EVENT, icon_size=12, icon_color=fg, tooltip="날짜 바꾸기",
                              style=ft.ButtonStyle(padding=0), width=20, height=20,
                              on_click=lambda e, c=c: pick_new_date(
                                  c.get("scheduled_date"), lambda d, cid=c["id"]: (repo.move_campaign_date(cid, d), refresh()))),
            ], spacing=2, tight=True),
            bgcolor=bg, border_radius=6, padding=ft.Padding.only(left=6, right=2, top=1, bottom=1),
            border=ft.Border.all(2, "#B71C1C") if overdue else None,
            tooltip=f"{STATUS_LABELS.get(c['status'], c['status'])} · {c.get('brand_kit_name') or ''}"
                    + (" · 예정일이 지났습니다" if overdue else "") + " — 누르면 워크벤치에서 엽니다",
            ink=True, on_click=lambda e, cid=c["id"]: open_campaign(cid),
        )
        return ft.Draggable(group=DRAG_GROUP, data=f"c:{c['id']}", content=chip,
                            content_when_dragging=ft.Container(content=chip, opacity=0.3))

    def topic_dialog(t: dict) -> None:
        def make(e: ft.Event) -> None:
            page.pop_dialog()
            created = repo.topic_to_campaign(t["id"])
            open_campaign(created["id"])

        def remove(e: ft.Event) -> None:
            page.pop_dialog()
            repo.delete_topic(t["id"])
            refresh()

        def redate(e: ft.Event) -> None:
            page.pop_dialog()
            pick_new_date(t.get("planned_date"), lambda d: (repo.update_topic(t["id"], planned_date=d), refresh()))

        page.show_dialog(ft.AlertDialog(
            title=ft.Text(f"📝 주제: {t.get('title') or '(제목 없음)'}"),
            content=ft.Text((t.get("memo") or "메모 없음") + (f"\n예정일 {t['planned_date']}" if t.get("planned_date") else "")),
            actions=[
                ft.FilledButton("글로 만들기", on_click=make),
                ft.OutlinedButton("날짜 바꾸기", on_click=redate),
                ft.TextButton("주제 삭제", on_click=remove),
                ft.TextButton("닫기", on_click=lambda e: page.pop_dialog()),
            ],
        ))

    def topic_chip(t: dict, compact: bool) -> ft.Control:
        chip = ft.Container(
            content=ft.Text("📝 " + (t.get("title") or "주제"), size=fs(10 if compact else 11, scale),
                            color=BRAND_COLORS["text"], max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
            bgcolor="#FFFFFF", border_radius=6, padding=ft.Padding.symmetric(horizontal=6, vertical=2),
            border=ft.Border.all(1, "#9E9E9E"), tooltip="아직 글로 만들지 않은 주제 — 누르면 글로 만들기",
            ink=True, on_click=lambda e, t=t: topic_dialog(t),
        )
        return ft.Draggable(group=DRAG_GROUP, data=f"t:{t['id']}", content=chip,
                            content_when_dragging=ft.Container(content=chip, opacity=0.3))

    # --- 빈 날짜 대화상자 ---------------------------------------------------------
    def day_dialog(day: date) -> None:
        iso = day.isoformat()
        kit_id = view["kit"]
        unscheduled = repo.unscheduled_campaigns(kit_id)
        free_topics = [t for t in repo.list_topics(include_linked=False, brand_kit_id=kit_id) if not t.get("planned_date")]
        pick_c = ft.Dropdown(label="예정일 없는 글", width=380, dense=True,
                             options=[ft.DropdownOption(key=c["id"], text=_campaign_title(c)) for c in unscheduled])
        pick_t = ft.Dropdown(label="날짜 미정 주제", width=380, dense=True,
                             options=[ft.DropdownOption(key=str(t["id"]), text=t.get("title") or "(제목 없음)") for t in free_topics])

        def new_post(e: ft.Event) -> None:
            page.pop_dialog()
            created = repo.insert_campaign(source_type="manual", status="awaiting_media", brand_kit_id=kit_id)
            repo.move_campaign_date(created["id"], iso)
            open_campaign(created["id"])

        def assign_c(e: ft.Event) -> None:
            if pick_c.value:
                page.pop_dialog()
                repo.move_campaign_date(pick_c.value, iso)
                refresh()

        def assign_t(e: ft.Event) -> None:
            if pick_t.value:
                page.pop_dialog()
                repo.update_topic(int(pick_t.value), planned_date=iso)
                refresh()

        body: list[ft.Control] = [ft.FilledButton("➕ 이 날짜로 새 글 만들기 (워크벤치로 이동)", on_click=new_post)]
        if unscheduled:
            body += [ft.Divider(), ft.Row([pick_c, ft.OutlinedButton("이 날짜로", on_click=assign_c)], wrap=True)]
        if free_topics:
            body += [ft.Row([pick_t, ft.OutlinedButton("이 날짜에 두기", on_click=assign_t)], wrap=True)]
        page.show_dialog(ft.AlertDialog(
            title=ft.Text(f"📅 {day.month}월 {day.day}일 ({repo.WEEKDAY_LABELS[day.weekday()]})"),
            content=ft.Column(body, tight=True, spacing=10, width=520),
            actions=[ft.TextButton("닫기", on_click=lambda e: page.pop_dialog())],
        ))

    # --- 날짜 칸 -----------------------------------------------------------------
    def day_cell(day: date, items_c: list, items_t: list, in_month: bool, compact: bool, height: int) -> ft.Control:
        today = date.today()
        chips: list[ft.Control] = [campaign_chip(c, compact) for c in items_c] + [topic_chip(t, compact) for t in items_t]
        shown = chips[:MAX_CHIPS_MONTH] if compact else chips
        more = len(chips) - len(shown)
        header = ft.Row([
            ft.Text(str(day.day) if compact else f"{day.month}/{day.day} ({repo.WEEKDAY_LABELS[day.weekday()]})",
                    size=fs(11, scale), weight=ft.FontWeight.BOLD if day == today else None,
                    color=BRAND_COLORS["secondary"] if day == today else (BRAND_COLORS["text"] if in_month else "#BDBDBD")),
            *([ft.Text("오늘", size=fs(9, scale), color=BRAND_COLORS["secondary"])] if day == today else []),
        ], spacing=4)
        cell = ft.Container(
            content=ft.Column([header, *shown, *([ft.Text(f"+{more}건 더", size=fs(9, scale), color=BRAND_COLORS["text_muted"])] if more else [])],
                              spacing=3, scroll=ft.ScrollMode.AUTO if not compact else None),
            height=height, padding=4, expand=True,
            bgcolor="#FFFFFF" if in_month else "#FAFAFA",
            border=ft.Border.all(2 if day == today else 1, BRAND_COLORS["secondary"] if day == today else "#E0E0E0"),
            ink=True, on_click=lambda e, d=day: day_dialog(d),
            tooltip="빈 곳을 누르면 이 날짜로 새 글 만들기·글 배치",
        )

        def accept(e: ft.Event, d=day) -> None:
            payload = getattr(getattr(e, "src", None), "data", None)
            if payload:
                move_payload(payload, d.isoformat())

        return ft.DragTarget(group=DRAG_GROUP, content=cell, on_accept=accept, expand=True)

    # --- 오른쪽 패널: 주제 목록 · 반복 규칙 ------------------------------------------
    def side_panel() -> ft.Control:
        kit_id = view["kit"]
        topics = repo.list_topics(include_linked=False, brand_kit_id=kit_id)
        kits = {k["id"]: k["name"] for k in repo.list_brand_kits(include_archived=True)}
        topic_cards: list[ft.Control] = []
        for t in topics:
            def make(e: ft.Event, tid=t["id"]) -> None:
                created = repo.topic_to_campaign(tid)
                open_campaign(created["id"])

            def remove(e: ft.Event, tid=t["id"]) -> None:
                repo.delete_topic(tid)
                refresh()

            meta = " · ".join(x for x in (
                kits.get(t.get("brand_kit_id")) or "", content_mode.label_of(t["content_mode"]) if t.get("content_mode") else "",
                t.get("planned_date") or "날짜 미정", t.get("series_name") or "",
            ) if x)
            card = ft.Container(
                content=ft.Column([
                    ft.Text(t.get("title") or "(제목 없음)", weight=ft.FontWeight.BOLD, size=fs(12, scale)),
                    *([ft.Text(t["memo"], size=fs(10, scale), max_lines=2, overflow=ft.TextOverflow.ELLIPSIS)] if t.get("memo") else []),
                    ft.Text(meta, size=fs(10, scale), color=BRAND_COLORS["text_muted"]),
                    ft.Row([
                        ft.FilledButton("글로 만들기", on_click=make, height=30),
                        ft.IconButton(icon=ft.Icons.DELETE_OUTLINE, icon_size=16, tooltip="주제 삭제", on_click=remove),
                    ], spacing=4),
                ], spacing=3),
                bgcolor="#FFFFFF", border=ft.Border.all(1, "#E0E0E0"), border_radius=8, padding=8,
            )
            topic_cards.append(ft.Draggable(group=DRAG_GROUP, data=f"t:{t['id']}", content=card,
                                            content_feedback=ft.Container(
                                                content=ft.Text("📝 " + (t.get("title") or "주제")),
                                                bgcolor="#FFFFFF", padding=6, border_radius=6,
                                                border=ft.Border.all(1, "#9E9E9E"))))
        if not topic_cards:
            topic_cards.append(ft.Text("쌓아 둔 주제가 없습니다. 아래에서 추가하세요.", size=fs(11, scale), color=BRAND_COLORS["text_muted"]))

        # 주제 추가
        new_title = ft.TextField(label="주제 제목", dense=True)
        new_memo = ft.TextField(label="메모 (초안의 씨앗)", dense=True, multiline=True, min_lines=2, max_lines=4)
        chosen_kit = {"id": kit_id}
        mode_dd = ft.Dropdown(label="콘텐츠 모드", dense=True, width=150, value=None,
                              options=[ft.DropdownOption(key="", text="킷 기본")] +
                                      [ft.DropdownOption(key=k, text=content_mode.MODES[k]["label"]) for k in content_mode.ORDER])
        date_tf, date_row = date_field(page, None, label="예정일 (선택)", width=140)
        series_tf = ft.TextField(label="시리즈 (선택)", dense=True)
        add_status = ft.Text("", size=fs(11, scale), color="#B3261E")

        def on_add(e: ft.Event) -> None:
            try:
                repo.add_topic(new_title.value, memo=new_memo.value, brand_kit_id=chosen_kit["id"],
                               content_mode=mode_dd.value or None, planned_date=date_tf.value, series_name=series_tf.value)
            except ValueError as exc:
                add_status.value = str(exc)
                add_status.update()
                return
            refresh()

        # 반복 규칙
        rules = repo.list_rules()
        rule_rows: list[ft.Control] = []
        for r in rules:
            def del_rule(e: ft.Event, rid=r["id"]) -> None:
                removed = repo.delete_rule(rid)
                refresh()
                snack(f"규칙을 지웠습니다. 아직 글로 만들지 않은 자리 {removed}개도 지웠습니다.")

            desc = f"매주 {repo.WEEKDAY_LABELS[r['weekday']]}요일 · {kits.get(r.get('brand_kit_id')) or '기본 킷'}"
            if r.get("content_mode"):
                desc += f" · {content_mode.label_of(r['content_mode'])}"
            if r.get("title"):
                desc += f" · '{r['title']}'"
            rule_rows.append(ft.Row([
                ft.Text(desc, size=fs(11, scale), expand=True),
                ft.IconButton(icon=ft.Icons.DELETE_OUTLINE, icon_size=16, tooltip="규칙 삭제", on_click=del_rule),
            ], spacing=2))
        weekday_dd = ft.Dropdown(label="요일", dense=True, width=90, value="1",
                                 options=[ft.DropdownOption(key=str(i), text=f"{d}요일") for i, d in enumerate(repo.WEEKDAY_LABELS)])
        rule_kit = {"id": kit_id}
        rule_mode = ft.Dropdown(label="모드", dense=True, width=120, value="",
                                options=[ft.DropdownOption(key="", text="킷 기본")] +
                                        [ft.DropdownOption(key=k, text=content_mode.MODES[k]["label"]) for k in content_mode.ORDER])
        rule_title = ft.TextField(label="자리 이름 (예: 가발 관리 팁)", dense=True)

        def on_add_rule(e: ft.Event) -> None:
            repo.add_rule(int(weekday_dd.value or 0), brand_kit_id=rule_kit["id"], content_mode=rule_mode.value or None,
                          title=rule_title.value)
            made = repo.apply_rules()
            refresh()
            snack(f"규칙을 추가하고 앞으로 {repo.RULE_WEEKS_AHEAD}주의 빈 자리 {made}개를 만들었습니다.")

        def on_apply(e: ft.Event) -> None:
            made = repo.apply_rules()
            refresh()
            snack(f"앞으로 {repo.RULE_WEEKS_AHEAD}주 안에 비어 있던 자리 {made}개를 만들었습니다." if made else "새로 만들 자리가 없습니다.")

        return ft.Container(
            width=330,
            content=ft.Column([
                ft.Text("📝 쓸 주제", weight=ft.FontWeight.BOLD, size=fs(14, scale)),
                ft.Text("주제를 달력 날짜로 끌어 놓으면 예정일이 됩니다. [글로 만들기]는 메모·킷·모드·예정일이 채워진 새 글을 워크벤치에 엽니다.",
                        size=fs(10, scale), color=BRAND_COLORS["text_muted"]),
                *topic_cards,
                ft.Divider(),
                ft.Text("➕ 주제 추가", weight=ft.FontWeight.BOLD, size=fs(12, scale)),
                new_title, new_memo,
                kit_dropdown(kit_id, lambda k: chosen_kit.update(id=k), label="브랜드 킷", width=None),
                ft.Row([mode_dd], wrap=True), date_row, series_tf,
                ft.FilledButton("주제 추가", on_click=on_add), add_status,
                ft.Divider(),
                ft.Text("🔁 반복 규칙", weight=ft.FontWeight.BOLD, size=fs(12, scale)),
                ft.Text(f"정해 둔 요일마다 앞으로 {repo.RULE_WEEKS_AHEAD}주의 빈 자리(주제)를 만듭니다.",
                        size=fs(10, scale), color=BRAND_COLORS["text_muted"]),
                *rule_rows,
                ft.Row([weekday_dd, rule_mode], wrap=True),
                kit_dropdown(kit_id, lambda k: rule_kit.update(id=k), label="규칙 킷", width=None),
                rule_title,
                ft.Row([ft.FilledButton("규칙 추가", on_click=on_add_rule),
                        ft.OutlinedButton(f"규칙으로 {repo.RULE_WEEKS_AHEAD}주 자리 만들기", on_click=on_apply)], wrap=True),
            ], spacing=8, scroll=ft.ScrollMode.AUTO),
            padding=ft.Padding.only(left=10),
        )

    # --- 본문 ----------------------------------------------------------------------
    def _body() -> ft.Control:
        kit_id = view["kit"]
        if view["mode"] == "month":
            weeks = month_weeks(view["anchor"].year, view["anchor"].month)
            title = f"{view['anchor'].year}년 {view['anchor'].month}월"
        else:
            weeks = [week_of(view["week_anchor"])]
            first, last = weeks[0][0], weeks[0][-1]
            title = f"{first.year}년 {first.month}월 {first.day}일 ~ {last.month}월 {last.day}일"
        start, end = weeks[0][0].isoformat(), weeks[-1][-1].isoformat()
        campaigns = repo.scheduled_campaigns(start, end, kit_id)
        topics = [t for t in repo.list_topics(include_linked=False, brand_kit_id=kit_id)
                  if t.get("planned_date") and start <= t["planned_date"] <= end]
        by_day_c: dict = {}
        for c in campaigns:
            by_day_c.setdefault(c["scheduled_date"], []).append(c)
        by_day_t: dict = {}
        for t in topics:
            by_day_t.setdefault(t["planned_date"], []).append(t)

        compact = view["mode"] == "month"
        height = 118 if compact else 420
        grid_rows: list[ft.Control] = [ft.Row(
            [ft.Container(content=ft.Text(f"{d}", size=fs(11, scale), weight=ft.FontWeight.BOLD,
                                          color="#C62828" if i == 6 else BRAND_COLORS["text"]),
                          expand=True, alignment=ft.Alignment.CENTER)
             for i, d in enumerate(repo.WEEKDAY_LABELS)], spacing=4)]
        for week in weeks:
            grid_rows.append(ft.Row([
                day_cell(d, by_day_c.get(d.isoformat(), []), by_day_t.get(d.isoformat(), []),
                         (d.month == view["anchor"].month) if compact else True, compact, height)
                for d in week
            ], spacing=4, vertical_alignment=ft.CrossAxisAlignment.START))

        def shift(delta: int) -> None:
            if view["mode"] == "month":
                y, m = view["anchor"].year, view["anchor"].month + delta
                y, m = y + (m - 1) // 12, (m - 1) % 12 + 1
                view["anchor"] = date(y, m, 1)
            else:
                view["week_anchor"] = view["week_anchor"] + timedelta(weeks=delta)
                view["anchor"] = view["week_anchor"].replace(day=1)
            refresh()

        def go_today(e: ft.Event) -> None:
            view["anchor"] = date.today().replace(day=1)
            view["week_anchor"] = date.today()
            refresh()

        def set_mode(e: ft.Event) -> None:
            view["mode"] = mode_group.value
            if view["mode"] == "week" and view["anchor"].month != view["week_anchor"].month:
                view["week_anchor"] = view["anchor"]
            refresh()

        def set_kit(e: ft.Event) -> None:
            view["kit"] = int(kit_filter.value) if kit_filter.value else None
            refresh()

        mode_group = ft.RadioGroup(value=view["mode"], on_change=set_mode, content=ft.Row([
            ft.Radio(value="month", label="월간"), ft.Radio(value="week", label="주간")]))
        kit_filter = ft.Dropdown(
            label="브랜드 킷", width=200, dense=True, value=str(kit_id) if kit_id else "",
            options=[ft.DropdownOption(key="", text="전체 킷")] +
                    [ft.DropdownOption(key=str(k["id"]), text=k["name"]) for k in repo.list_brand_kits()],
        )
        kit_filter.on_select = set_kit

        overdue = repo.overdue_count(kit_id)
        legend = ft.Row([
            ft.Container(content=ft.Text(label, size=fs(10, scale), color=STATUS_COLORS[key][1]),
                         bgcolor=STATUS_COLORS[key][0], border_radius=6, padding=ft.Padding.symmetric(horizontal=6, vertical=2))
            for key, label in LEGEND
        ] + [ft.Container(content=ft.Text("📝 주제", size=fs(10, scale)), border=ft.Border.all(1, "#9E9E9E"),
                          border_radius=6, padding=ft.Padding.symmetric(horizontal=6, vertical=2))], spacing=6, wrap=True)

        header = ft.Row([
            ft.IconButton(icon=ft.Icons.CHEVRON_LEFT, tooltip="이전", on_click=lambda e: shift(-1)),
            ft.Text(title, size=fs(18, scale), weight=ft.FontWeight.BOLD),
            ft.IconButton(icon=ft.Icons.CHEVRON_RIGHT, tooltip="다음", on_click=lambda e: shift(1)),
            ft.OutlinedButton("오늘", on_click=go_today),
            mode_group, kit_filter,
            *([ft.Container(content=ft.Text(f"⚠️ 지연 {overdue}건", size=fs(12, scale), color="#B3261E"),
                            bgcolor="#FDECEA", padding=ft.Padding.symmetric(horizontal=8, vertical=4), border_radius=8,
                            tooltip="예정일이 지났는데 아직 게시되지 않은 글")] if overdue else []),
        ], spacing=8, wrap=True, vertical_alignment=ft.CrossAxisAlignment.CENTER)

        return ft.Column([
            ft.Text("📅 콘텐츠 캘린더", size=fs(24, scale), weight=ft.FontWeight.BOLD),
            ft.Text("글은 발행 예정일 칸에 상태 색으로 보입니다. 칩을 누르면 워크벤치에서 열리고, 다른 날짜로 끌어 놓으면 예정일이 바뀝니다. "
                    "빈 날짜를 누르면 그 날짜로 새 글을 만들 수 있습니다.",
                    size=fs(11, scale), color=BRAND_COLORS["text_muted"]),
            header, legend,
            ft.Row([
                ft.Container(content=ft.Column(grid_rows, spacing=4, scroll=ft.ScrollMode.AUTO), expand=True),
                ft.VerticalDivider(width=1),
                side_panel(),
            ], expand=True, vertical_alignment=ft.CrossAxisAlignment.START),
        ], expand=True, spacing=8)

    root.content = _body()
    return root
