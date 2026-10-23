"""날짜·시각 입력 칸 — 직접 입력(YYYY-MM-DD / HH:MM)하거나 달력·시계 버튼으로 고릅니다.

워크벤치(발행 예정일·자동 작성 예약)와 📅 캘린더(주제 예정일)가 같이 씁니다. 직접 입력도
받는 이유: 달력 대화상자는 마우스로 여러 번 눌러야 해서, 날짜를 아는 담당자에게는 타이핑이 빠릅니다.
값의 형식 검사는 core.repo(_valid_date/_valid_datetime)가 저장할 때 한 번 더 합니다.
"""
from __future__ import annotations

from datetime import date, datetime, time
from typing import Callable, Optional

import flet as ft


def _picked_date(value) -> Optional[date]:
    """DatePicker 값 → 로컬 날짜. 시간대가 붙어 오면 로컬로 바꾼 뒤 날짜만 씁니다."""
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is not None:
            value = value.astimezone()
        return value.date()
    if isinstance(value, date):
        return value
    return None


def date_field(
    page: ft.Page,
    value: Optional[str],
    *,
    label: str = "날짜",
    width: int = 150,
    on_change: Optional[Callable[[Optional[str]], None]] = None,
) -> tuple[ft.TextField, ft.Control]:
    """(입력 칸, 화면에 넣을 컨트롤)을 돌려줍니다. 값은 입력 칸의 `.value`('YYYY-MM-DD' 또는 '')."""
    field = ft.TextField(label=label, value=value or "", width=width, dense=True, hint_text="YYYY-MM-DD")

    def on_pick(e: ft.Event) -> None:
        picked = _picked_date(e.control.value)
        if picked:
            field.value = picked.isoformat()
            field.update()
            if on_change:
                on_change(field.value)

    def open_picker(e: ft.Event) -> None:
        try:
            current = date.fromisoformat((field.value or "")[:10])
        except ValueError:
            current = date.today()
        page.show_dialog(ft.DatePicker(
            value=datetime.combine(current, time(12, 0)),
            first_date=datetime(2020, 1, 1), last_date=datetime(2035, 12, 31),
            help_text=label, cancel_text="취소", confirm_text="선택",
            on_change=on_pick,
        ))

    def on_clear(e: ft.Event) -> None:
        field.value = ""
        field.update()
        if on_change:
            on_change(None)

    if on_change:
        field.on_blur = lambda e: on_change(field.value or None)

    row = ft.Row([
        field,
        ft.IconButton(icon=ft.Icons.CALENDAR_MONTH, tooltip="달력에서 고르기", on_click=open_picker),
        ft.IconButton(icon=ft.Icons.CLEAR, tooltip="비우기", icon_size=16, on_click=on_clear),
    ], spacing=0, tight=True)
    return field, row


def time_field(page: ft.Page, value: Optional[str], *, label: str = "시각", width: int = 100) -> tuple[ft.TextField, ft.Control]:
    """(입력 칸, 컨트롤). 값은 'HH:MM' 또는 ''."""
    field = ft.TextField(label=label, value=value or "", width=width, dense=True, hint_text="HH:MM")

    def on_pick(e: ft.Event) -> None:
        picked = e.control.value
        if isinstance(picked, time):
            field.value = picked.strftime("%H:%M")
            field.update()

    def open_picker(e: ft.Event) -> None:
        try:
            current = datetime.strptime((field.value or "")[:5], "%H:%M").time()
        except ValueError:
            current = time(9, 0)
        page.show_dialog(ft.TimePicker(
            value=current, help_text=label, cancel_text="취소", confirm_text="선택", on_change=on_pick,
        ))

    row = ft.Row([
        field,
        ft.IconButton(icon=ft.Icons.SCHEDULE, tooltip="시계에서 고르기", on_click=open_picker),
    ], spacing=0, tight=True)
    return field, row
