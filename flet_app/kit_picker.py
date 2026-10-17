"""브랜드 킷 선택 목록 — 워크벤치·뉴스 큐레이션·설정(네이버 API)이 같이 씁니다.

킷은 글마다(워크벤치), 검색 키워드마다(뉴스 큐레이션), 키워드 작업마다(설정) 고르므로
같은 목록이 여러 화면에 나옵니다. 목록에는 보관(삭제)되지 않은 킷만 나오지만, 지금 값이
보관된 킷이면 그 킷도 "(삭제됨)"을 붙여 남겨 둡니다 — 안 그러면 선택 칸이 비어 보여
어느 킷으로 쓴 글인지 알 수 없습니다.
"""
from __future__ import annotations

from typing import Callable, Optional

import flet as ft

from core import repo

ARCHIVED_SUFFIX = " (삭제됨)"


def kit_label(kit_id: Optional[int], snapshot_name: Optional[str] = None) -> str:
    """글 카드에 보여줄 킷 이름. 보관된 킷이면 "(삭제됨)"을 붙이고, 생성한 뒤 킷 이름이
    바뀌었으면 생성 당시 이름(글에 남은 스냅샷)도 같이 보여줍니다."""
    kits = {k["id"]: k for k in repo.list_brand_kits(include_archived=True)}
    kit = kits.get(kit_id)
    if kit is None:
        return snapshot_name or "기본 킷"
    label = kit["name"] + (ARCHIVED_SUFFIX if kit.get("is_archived") else "")
    if snapshot_name and snapshot_name != kit["name"]:
        label += f" · 생성 당시 이름 '{snapshot_name}'"
    return label


def kit_dropdown(
    value: Optional[int],
    on_change: Callable[[int], None],
    *,
    label: str = "브랜드 킷",
    width: Optional[int] = 260,
    disabled: bool = False,
) -> ft.Dropdown:
    """`value`가 None이면 기본 킷을 고른 상태로 시작합니다. `on_change`는 고른 킷 ID를 받습니다."""
    kits = repo.list_brand_kits()
    current = value if value is not None else repo.default_brand_kit_id()
    options = [ft.DropdownOption(key=str(k["id"]), text=k["name"]) for k in kits]
    if current is not None and all(k["id"] != current for k in kits):
        options.append(ft.DropdownOption(key=str(current), text=kit_label(current)))

    dropdown = ft.Dropdown(
        label=label,
        width=width,
        value=str(current) if current is not None else None,
        options=options,
        disabled=disabled,
    )

    def _on_select(e: ft.Event) -> None:
        if dropdown.value:
            on_change(int(dropdown.value))

    # 이 Flet 버전의 Dropdown에는 on_change가 없다 — 이벤트 이름은 on_select다.
    dropdown.on_select = _on_select
    return dropdown
