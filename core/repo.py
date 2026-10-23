"""Data access layer over SQLite.

Keeps the same call shapes OSMU_admin's `core/db_client.py` exposed
(get_brand_kit / list_campaigns / update_campaign / ...) so the ported
ai_workers needed no rewiring, while hiding the JSON-in-TEXT column encoding
from every caller.
"""
from __future__ import annotations

import contextvars
import uuid
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from typing import Any, Dict, Iterator, List, Optional

from core.db import (
    _APP_SETTINGS_COLUMNS,
    _COMPANY_COLUMNS,
    DEFAULT_KIT_NAME,
    dumps,
    get_conn,
    loads,
)

# --- column encoding map ----------------------------------------------------
# name -> default value when the column is empty/absent.
_CAMPAIGN_JSON_COLS = {
    "notice_fields": {},
    "product_fields": {},
    "storage_file_paths": [],
    "guardrail_report": None,
    "instagram_hashtags": [],
    "x_content": [],
    "x_hashtags": [],
    "naver_hashtags": [],
    "shorts_script": None,
    "content_format": {},
}

_BRAND_KIT_JSON_COLS = {
    "core_facts": [],
    "few_shot_samples": [],
    "terminology": {},
    "seo_keywords": [],
    "keyword_weights": {},
    "non_target_keywords": [],
}
_COMPANY_JSON_COLS = {"blacklist_map": {}}
_APP_SETTINGS_JSON_COLS = {"enabled_channels": ["instagram", "x", "shorts"]}

_CAMPAIGN_BOOL_COLS = ("guardrail_passed",)
_BRAND_KIT_BOOL_COLS = ("is_archived",)
_COMPANY_BOOL_COLS = ("guardrail_enabled",)
_APP_SETTINGS_BOOL_COLS = ("vision_enabled",)

# 킷마다 따로 두는 값. 이 밖의 값은 회사 공통(company_profile)이거나 앱 설정(app_settings)입니다.
BRAND_KIT_FIELDS = (
    "name", "industry", "persona", "tone_and_manner", "core_facts", "few_shot_samples",
    "terminology", "seo_keywords", "keyword_weights", "non_target_keywords",
    "default_content_mode", "design_template", "design_strength",
)
# 킷을 복제할 때 옮기는 값 — 이름만 빼고 전부.
_KIT_COPY_FIELDS = tuple(f for f in BRAND_KIT_FIELDS if f != "name")
COMPANY_FIELDS = _COMPANY_COLUMNS
APP_SETTINGS_FIELDS = _APP_SETTINGS_COLUMNS


def _decode(row, json_cols: Dict[str, Any], bool_cols) -> Optional[Dict[str, Any]]:
    if row is None:
        return None
    data = dict(row)
    for col, default in json_cols.items():
        if col in data:
            data[col] = loads(data[col], default)
    for col in bool_cols:
        if col in data and data[col] is not None:
            data[col] = bool(data[col])
    return data


def _encode(fields: Dict[str, Any], json_cols: Dict[str, Any], bool_cols) -> Dict[str, Any]:
    out = {}
    for key, value in fields.items():
        if key in json_cols and not isinstance(value, (str, type(None))):
            out[key] = dumps(value)
        elif key in json_cols and value is None:
            out[key] = None
        elif key in bool_cols and value is not None:
            out[key] = int(bool(value))
        else:
            out[key] = value
    return out


# --- llm_settings -----------------------------------------------------------

def get_llm_setting(vendor: str) -> Optional[Dict[str, Any]]:
    with get_conn() as conn:
        row = conn.execute("select * from llm_settings where vendor = ?", (vendor,)).fetchone()
    if row is None:
        return None
    data = dict(row)
    data["is_active"] = bool(data["is_active"])
    return data


def list_llm_settings() -> List[Dict[str, Any]]:
    with get_conn() as conn:
        rows = conn.execute("select * from llm_settings order by vendor").fetchall()
    return [dict(r) for r in rows]


def upsert_llm_setting(vendor: str, model_name: str, encrypted_api_key: str) -> None:
    with get_conn() as conn:
        conn.execute(
            """
            insert into llm_settings (vendor, model_name, encrypted_api_key, is_active, updated_at)
            values (?, ?, ?, 1, datetime('now'))
            on conflict(vendor) do update set
                model_name = excluded.model_name,
                encrypted_api_key = excluded.encrypted_api_key,
                is_active = 1,
                updated_at = datetime('now')
            """,
            (vendor, model_name, encrypted_api_key),
        )


def delete_llm_setting(vendor: str) -> None:
    with get_conn() as conn:
        conn.execute("delete from llm_settings where vendor = ?", (vendor,))


# --- brand_kit · company_profile · app_settings -----------------------------
# 브랜드 킷은 여러 개이고(사업 분야별), 회사 공통 값과 앱 설정은 한 줄씩입니다.
# get_brand_kit()은 셋을 합친 dict를 돌려줍니다 — 생성 파이프라인은 "이 글을 쓸 때
# 필요한 모든 값"을 한 번에 받으면 되고, 어느 값이 어느 테이블에 있는지 몰라도 됩니다.

class BrandKitError(ValueError):
    """킷 보관·이름 규칙 위반 — 화면에 그대로 보여줄 수 있는 문장을 담습니다."""


def get_company_profile() -> Dict[str, Any]:
    with get_conn() as conn:
        row = conn.execute("select * from company_profile where id = 1").fetchone()
    data = _decode(row, _COMPANY_JSON_COLS, _COMPANY_BOOL_COLS) or {}
    data.pop("id", None)
    data.pop("updated_at", None)
    return data


def save_company_profile(**fields) -> None:
    _save_single_row("company_profile", COMPANY_FIELDS, _COMPANY_JSON_COLS, _COMPANY_BOOL_COLS, fields)


def get_app_settings() -> Dict[str, Any]:
    with get_conn() as conn:
        row = conn.execute("select * from app_settings where id = 1").fetchone()
    data = _decode(row, _APP_SETTINGS_JSON_COLS, _APP_SETTINGS_BOOL_COLS) or {}
    data.pop("id", None)
    data.pop("updated_at", None)
    return data


def save_app_settings(**fields) -> None:
    _save_single_row("app_settings", APP_SETTINGS_FIELDS, _APP_SETTINGS_JSON_COLS, _APP_SETTINGS_BOOL_COLS, fields)


def _save_single_row(table: str, allowed, json_cols, bool_cols, fields: Dict[str, Any]) -> None:
    unknown = set(fields) - set(allowed)
    if unknown:
        raise KeyError(f"{table}에 없는 항목: {sorted(unknown)}")
    if not fields:
        return
    encoded = _encode(fields, json_cols, bool_cols)
    assignments = ", ".join(f"{k} = ?" for k in encoded)
    with get_conn() as conn:
        conn.execute(f"insert or ignore into {table} (id) values (1)")
        conn.execute(
            f"update {table} set {assignments}, updated_at = datetime('now') where id = 1",
            tuple(encoded.values()),
        )


def list_brand_kits(include_archived: bool = False) -> List[Dict[str, Any]]:
    """킷 목록(킷 값만, 공통 값은 합치지 않음). 보관된 킷은 뒤에 옵니다."""
    sql = "select * from brand_kit"
    if not include_archived:
        sql += " where is_archived = 0"
    sql += " order by is_archived, sort_order, id"
    with get_conn() as conn:
        rows = conn.execute(sql).fetchall()
    return [_decode(r, _BRAND_KIT_JSON_COLS, _BRAND_KIT_BOOL_COLS) for r in rows]


def default_brand_kit_id() -> Optional[int]:
    """목록 맨 앞의(보관되지 않은) 킷 — 킷을 고르지 않은 곳이 쓰는 킷입니다."""
    with get_conn() as conn:
        row = conn.execute(
            "select id from brand_kit order by is_archived, sort_order, id limit 1"
        ).fetchone()
    return row["id"] if row else None


def _get_kit_row(kit_id: Optional[int]) -> Optional[Dict[str, Any]]:
    with get_conn() as conn:
        row = None
        if kit_id is not None:
            row = conn.execute("select * from brand_kit where id = ?", (kit_id,)).fetchone()
        if row is None:
            row = conn.execute(
                "select * from brand_kit order by is_archived, sort_order, id limit 1"
            ).fetchone()
    return _decode(row, _BRAND_KIT_JSON_COLS, _BRAND_KIT_BOOL_COLS)


def get_brand_kit(kit_id: Optional[int] = None) -> Dict[str, Any]:
    """킷 값 + 회사 공통 값 + 앱 설정을 합친 dict.

    `kit_id`가 None이거나 없는 킷이면 기본 킷(default_brand_kit_id)을 씁니다.
    보관된 킷도 ID로 직접 부르면 그대로 돌려줍니다 — 그 킷으로 쓰던 글은 계속
    그 킷으로 다시 생성할 수 있어야 하기 때문입니다.
    """
    merged: Dict[str, Any] = {}
    merged.update(get_app_settings())
    merged.update(get_company_profile())
    kit = _get_kit_row(kit_id) or {}
    merged.update(kit)
    return merged


def get_campaign_brand_kit(campaign: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """글에 연결된 킷으로 get_brand_kit()을 부릅니다."""
    return get_brand_kit((campaign or {}).get("brand_kit_id"))


def save_brand_kit(kit_id: Optional[int] = None, **fields) -> None:
    """값마다 맞는 테이블에 저장합니다 — 킷 값은 `kit_id` 킷에(None이면 기본 킷),
    회사 공통 값은 company_profile에, 앱 설정은 app_settings에."""
    kit_fields = {k: v for k, v in fields.items() if k in BRAND_KIT_FIELDS}
    company_fields = {k: v for k, v in fields.items() if k in COMPANY_FIELDS}
    app_fields = {k: v for k, v in fields.items() if k in APP_SETTINGS_FIELDS}
    unknown = set(fields) - set(kit_fields) - set(company_fields) - set(app_fields)
    if unknown:
        raise KeyError(f"브랜드 킷에 없는 항목: {sorted(unknown)}")
    if company_fields:
        save_company_profile(**company_fields)
    if app_fields:
        save_app_settings(**app_fields)
    if not kit_fields:
        return
    if "name" in kit_fields:
        kit_fields["name"] = _clean_kit_name(kit_fields["name"], exclude_id=kit_id)
    target = kit_id if kit_id is not None else default_brand_kit_id()
    encoded = _encode(kit_fields, _BRAND_KIT_JSON_COLS, _BRAND_KIT_BOOL_COLS)
    assignments = ", ".join(f"{k} = ?" for k in encoded)
    with get_conn() as conn:
        conn.execute(
            f"update brand_kit set {assignments}, updated_at = datetime('now') where id = ?",
            tuple(encoded.values()) + (target,),
        )


def _clean_kit_name(name: Optional[str], exclude_id: Optional[int] = None) -> str:
    """앞뒤 공백을 지우고, 빈 이름과 (보관되지 않은 킷끼리) 같은 이름을 막습니다.
    선택 목록에서 같은 이름 두 개는 구별할 수 없기 때문입니다."""
    cleaned = " ".join((name or "").split())
    if not cleaned:
        raise BrandKitError("킷 이름을 입력해주세요.")
    with get_conn() as conn:
        row = conn.execute(
            "select id from brand_kit where name = ? and is_archived = 0 and id != ?",
            (cleaned, exclude_id if exclude_id is not None else -1),
        ).fetchone()
    if row:
        raise BrandKitError(f"'{cleaned}' 이름의 킷이 이미 있습니다. 다른 이름을 써주세요.")
    return cleaned


def unique_kit_name(base: str) -> str:
    """'기본 복사본', '기본 복사본 2' … 처럼 겹치지 않는 이름을 만듭니다."""
    existing = {k["name"] for k in list_brand_kits()}
    if base not in existing:
        return base
    n = 2
    while f"{base} {n}" in existing:
        n += 1
    return f"{base} {n}"


def create_brand_kit(
    name: str,
    copy_from: Optional[int] = None,
    preset_key: Optional[str] = None,
) -> int:
    """새 킷을 만들고 ID를 돌려줍니다.
    `preset_key`를 주면 분야별 프리셋(core.brand_seed.KIT_PRESETS)으로 채우고,
    아니면 `copy_from` 킷(None이면 기본 킷)을 그대로 복사합니다."""
    cleaned = _clean_kit_name(name)
    source = _get_kit_row(copy_from) or {}
    values = {k: source.get(k) for k in _KIT_COPY_FIELDS if source.get(k) is not None}
    if preset_key:
        from core.brand_seed import KIT_PRESETS

        preset = KIT_PRESETS.get(preset_key)
        if preset:
            values["keyword_weights"] = {}
            values["non_target_keywords"] = []
            for k in _KIT_COPY_FIELDS:
                if k in preset:
                    values[k] = preset[k]
    encoded = _encode(values, _BRAND_KIT_JSON_COLS, _BRAND_KIT_BOOL_COLS)
    cols = ["name", "sort_order", *encoded.keys()]
    with get_conn() as conn:
        next_order = conn.execute("select coalesce(max(sort_order), 0) + 1 as n from brand_kit").fetchone()["n"]
        cur = conn.execute(
            f"insert into brand_kit ({', '.join(cols)}) values ({', '.join('?' * len(cols))})",
            (cleaned, next_order, *encoded.values()),
        )
        return cur.lastrowid


def count_campaigns_using_kit(kit_id: int, unpublished_only: bool = True) -> int:
    sql = "select count(*) as n from campaigns where brand_kit_id = ?"
    if unpublished_only:
        sql += " and status != 'published'"
    with get_conn() as conn:
        return conn.execute(sql, (kit_id,)).fetchone()["n"]


def archive_brand_kit(kit_id: int, move_unpublished_to: Optional[int] = None) -> int:
    """킷을 보관(화면 표기 '삭제')합니다. 행은 지우지 않으므로 restore_brand_kit으로 되살릴 수 있습니다.

    `move_unpublished_to`를 주면 그 킷을 쓰던, 아직 게시되지 않은 글을 그 킷으로 옮기고
    옮긴 글 수를 돌려줍니다. 보관되지 않은 마지막 킷은 보관할 수 없습니다.
    """
    with get_conn() as conn:
        conn.execute("begin immediate")
        active = [r["id"] for r in conn.execute("select id from brand_kit where is_archived = 0")]
        if kit_id not in active:
            return 0
        if len(active) <= 1:
            raise BrandKitError("마지막 남은 브랜드 킷은 삭제할 수 없습니다. 새 킷을 먼저 만들어주세요.")
        moved = 0
        if move_unpublished_to is not None:
            target = conn.execute(
                "select id, name from brand_kit where id = ? and is_archived = 0", (move_unpublished_to,)
            ).fetchone()
            if target is None or target["id"] == kit_id:
                raise BrandKitError("글을 옮길 킷을 다시 골라주세요.")
            moved = conn.execute(
                "update campaigns set brand_kit_id = ?, brand_kit_name = ?, updated_at = datetime('now') "
                "where brand_kit_id = ? and status != 'published'",
                (target["id"], target["name"], kit_id),
            ).rowcount
        conn.execute(
            "update brand_kit set is_archived = 1, updated_at = datetime('now') where id = ?", (kit_id,)
        )
        return moved


def restore_brand_kit(kit_id: int) -> str:
    """보관한 킷을 되살리고 최종 이름을 돌려줍니다. 그 사이 같은 이름의 킷이
    생겼으면 '(되살림)'을 붙여 겹치지 않게 합니다."""
    kit = _get_kit_row(kit_id)
    if not kit or kit.get("id") != kit_id:
        raise BrandKitError("되살릴 킷을 찾지 못했습니다.")
    name = kit.get("name") or DEFAULT_KIT_NAME
    if name in {k["name"] for k in list_brand_kits()}:
        name = unique_kit_name(f"{name} (되살림)")
    with get_conn() as conn:
        conn.execute(
            "update brand_kit set is_archived = 0, name = ?, updated_at = datetime('now') where id = ?",
            (name, kit_id),
        )
    return name


def kit_state_key(base: str, kit_id: int) -> str:
    """킷마다 따로 두는 app_state 키 — 예: kit_state_key("sweep", 3) == "sweep:3"."""
    return f"{base}:{kit_id}"


def append_tone_rule(rule: str, kit_id: Optional[int] = None) -> bool:
    """Adds `rule` as a new "- " bullet at the end of the kit's tone guide.

    Returns False (and changes nothing) if the guide already contains it.
    Backs the workbench's "이 요청을 브랜드 킷에 저장" button: a revision
    request applies to one post only, and marketers were retyping the same
    style request ("문장은 짧게") on every draft.
    """
    rule = " ".join((rule or "").split()).lstrip("-• ").strip()
    if not rule:
        return False
    kit = get_brand_kit(kit_id)
    current = (kit.get("tone_and_manner") or "").rstrip()
    if rule in current:
        return False
    updated = f"{current}\n- {rule}" if current else f"- {rule}"
    save_brand_kit(kit.get("id"), tone_and_manner=updated)
    return True


# --- campaigns --------------------------------------------------------------

def list_campaigns(source_type: Optional[str] = None, statuses: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    sql = "select * from campaigns"
    clauses, params = [], []
    if source_type:
        clauses.append("source_type = ?")
        params.append(source_type)
    if statuses:
        clauses.append("status in (%s)" % ", ".join("?" * len(statuses)))
        params.extend(statuses)
    if clauses:
        sql += " where " + " and ".join(clauses)
    sql += " order by created_at desc"
    with get_conn() as conn:
        rows = conn.execute(sql, tuple(params)).fetchall()
    return [_decode(r, _CAMPAIGN_JSON_COLS, _CAMPAIGN_BOOL_COLS) for r in rows]


def get_campaign(campaign_id: str) -> Optional[Dict[str, Any]]:
    with get_conn() as conn:
        row = conn.execute("select * from campaigns where id = ?", (campaign_id,)).fetchone()
    return _decode(row, _CAMPAIGN_JSON_COLS, _CAMPAIGN_BOOL_COLS)


def recent_posts(
    exclude_id: Optional[str] = None,
    limit: int = 10,
    brand_kit_id: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """Title + body of the most recently touched campaigns that have a body,
    newest first — the history ai_workers/body_variety.py compares against.
    Excludes the campaign being generated, which would match itself.
    When `brand_kit_id` is passed, filters to posts written with that kit so
    cross-domain opening/closing sentences aren't injected into the draft prompt."""
    sql = """
        select id, title, content from campaigns
        where content is not null and trim(content) != '' and id != ?
          and status != 'processing'
    """
    params: list[Any] = [exclude_id or ""]
    if brand_kit_id is not None:
        sql += " and brand_kit_id = ?"
        params.append(brand_kit_id)
    sql += " order by updated_at desc limit ?"
    params.append(limit)
    with get_conn() as conn:
        rows = conn.execute(sql, tuple(params)).fetchall()
    return [dict(r) for r in rows]


def list_known_source_urls() -> set:
    """Every source_url already in the pipeline — used to dedup keyword news
    search results so the same article isn't re-suggested on every search."""
    with get_conn() as conn:
        rows = conn.execute("select source_url from campaigns where source_url is not null").fetchall()
    return {r["source_url"] for r in rows if r["source_url"]}


def insert_campaign(
    source_type: str,
    source_url: Optional[str] = None,
    title: Optional[str] = None,
    memo: Optional[str] = None,
    status: str = "awaiting_media",
    source_title: Optional[str] = None,
    brand_kit_id: Optional[int] = None,
) -> Dict[str, Any]:
    """`brand_kit_id`가 None이면 기본 킷에 연결합니다."""
    campaign_id = uuid.uuid4().hex
    kit = _get_kit_row(brand_kit_id) or {}
    with get_conn() as conn:
        conn.execute(
            """
            insert into campaigns (id, source_type, source_url, source_title, title, memo, status,
                                   brand_kit_id, brand_kit_name)
            values (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (campaign_id, source_type, source_url, source_title, title, memo, status,
             kit.get("id"), kit.get("name")),
        )
    return get_campaign(campaign_id)


def set_campaign_brand_kit(campaign_id: str, kit_id: int) -> None:
    """글의 킷을 바꾸고 이름 스냅샷도 그 킷의 지금 이름으로 맞춥니다."""
    kit = _get_kit_row(kit_id) or {}
    update_campaign(campaign_id, brand_kit_id=kit.get("id"), brand_kit_name=kit.get("name"))


def update_campaign(campaign_id: str, **fields) -> None:
    if not fields:
        return
    encoded = _encode(fields, _CAMPAIGN_JSON_COLS, _CAMPAIGN_BOOL_COLS)
    assignments = ", ".join(f"{k} = ?" for k in encoded)
    with get_conn() as conn:
        conn.execute(
            f"update campaigns set {assignments}, updated_at = datetime('now') where id = ?",
            tuple(encoded.values()) + (campaign_id,),
        )


class CampaignBusyError(RuntimeError):
    """Another generation/revision is already running for this campaign."""


def begin_processing(campaign_id: str) -> str:
    """Atomically flips a campaign to 'processing' and returns its previous
    status. Raises CampaignBusyError if it is already processing.

    The workbench view is rebuilt from scratch on every navigation, so its
    own "button disabled while running" state doesn't survive leaving the
    screen and coming back — without this check the same campaign could be
    generated twice at once, each run overwriting the other's result.
    `begin immediate` takes the write lock before reading, so two threads
    can't both see a non-processing status.
    """
    with get_conn() as conn:
        conn.execute("begin immediate")
        row = conn.execute("select status from campaigns where id = ?", (campaign_id,)).fetchone()
        if row is None:
            raise RuntimeError(f"campaign {campaign_id} not found")
        if row["status"] == "processing":
            raise CampaignBusyError("이 콘텐츠는 이미 생성·수정 작업이 진행 중입니다. 끝날 때까지 기다려주세요.")
        conn.execute(
            "update campaigns set status = 'processing', publish_error = null, "
            "updated_at = datetime('now') where id = ?",
            (campaign_id,),
        )
        return row["status"]


def recover_interrupted_processing() -> int:
    """Marks campaigns left in 'processing' by a previous app session as
    failed. Generation runs in-process, so at startup nothing can still be
    working on them — without this they would stay 'processing' forever and
    begin_processing would refuse to ever run them again."""
    with get_conn() as conn:
        return conn.execute(
            "update campaigns set status = 'failed', publish_error = ?, updated_at = datetime('now') "
            "where status = 'processing'",
            ("앱이 생성 도중 종료되어 작업이 중단되었습니다. 다시 생성해주세요.",),
        ).rowcount


def mark_sns_stale(campaign_id: str) -> None:
    """Flags the SNS channels as describing an older body — used when the
    marketer edits the body by hand. regenerate_sns clears it."""
    campaign = get_campaign(campaign_id)
    if not campaign:
        return
    report = dict(campaign.get("guardrail_report") or {})
    if not (campaign.get("instagram_caption") or campaign.get("x_content") or campaign.get("shorts_script")):
        return
    if report.get("sns_stale"):
        return
    report["sns_stale"] = True
    update_campaign(campaign_id, guardrail_report=report)


def delete_campaign(campaign_id: str) -> None:
    with get_conn() as conn:
        conn.execute("delete from campaigns where id = ?", (campaign_id,))
        # 주제 목록의 주제는 남기고 연결만 끊습니다 — 다시 [글로 만들기]를 할 수 있게.
        conn.execute("update topics set campaign_id = null, updated_at = datetime('now') where campaign_id = ?",
                     (campaign_id,))


def mark_published(campaign_id: str, url: Optional[str] = None) -> None:
    """게시 완료로 바꾸고 게시 시각을 남깁니다. `url`이 있으면 네이버 글 주소도 저장합니다.

    이미 게시 완료인 글을 다시 게시한 경우에도 시각은 이번 게시로 갱신합니다.
    """
    fields: Dict[str, Any] = {
        "status": "published",
        "publish_error": None,
        "published_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    cleaned = normalize_post_url(url)
    if cleaned:
        fields["published_url"] = cleaned
    update_campaign(campaign_id, **fields)


def normalize_post_url(url: Optional[str]) -> Optional[str]:
    """담당자가 붙여 넣은 주소를 정리합니다. 주소처럼 보이지 않으면 None."""
    cleaned = (url or "").strip()
    if not cleaned:
        return None
    if not cleaned.lower().startswith(("http://", "https://")):
        if cleaned.lower().startswith(("blog.naver.com", "m.blog.naver.com")):
            cleaned = "https://" + cleaned
        else:
            return None
    return cleaned


def set_published_url(campaign_id: str, url: Optional[str]) -> bool:
    """게시 완료 글의 주소를 고칩니다. 빈 값이면 지웁니다. 주소 형식이 아니면 False."""
    if not (url or "").strip():
        update_campaign(campaign_id, published_url=None)
        return True
    cleaned = normalize_post_url(url)
    if not cleaned:
        return False
    update_campaign(campaign_id, published_url=cleaned)
    return True


def reset_generated_content() -> Dict[str, int]:
    """Deletes every campaign, its uploaded-photo records, and the title-
    repetition memory — everything 워크벤치/뉴스 큐레이션/네이버 게시 produce.

    Brand kit, LLM/네이버 API keys, and the keyword/vision caches are
    configuration and infrastructure, not generated content, and are
    deliberately left untouched — this is the counterpart to the brand-kit
    page's now-removed '기준값으로 되돌리기', scoped to content instead of
    settings so it can't silently erase tuning work the way that button did.

    Asset *rows* are cleared here; the files backing them live under
    data/assets and are removed separately by core.storage.clear_all(), which
    the caller is expected to run alongside this — kept apart because one is
    a DB operation and the other touches the filesystem.
    """
    with get_conn() as conn:
        counts = {
            "campaigns": conn.execute("select count(*) as n from campaigns").fetchone()["n"],
            "assets": conn.execute("select count(*) as n from assets").fetchone()["n"],
            "titles": conn.execute("select count(*) as n from title_history").fetchone()["n"],
        }
        conn.execute("delete from campaigns")
        conn.execute("delete from assets")
        conn.execute("delete from title_history")
        conn.execute("update topics set campaign_id = null where campaign_id is not null")
    return counts


# --- title history ----------------------------------------------------------
# Outlives the campaigns it came from — see the schema comment in core/db.py.

def record_title(title: str, campaign_id: Optional[str] = None) -> None:
    """Records a produced title, replacing this campaign's previous entry.

    Regeneration would otherwise stack one row per attempt, and the variety
    check would end up steering away from titles that were never published.
    Ignores blanks and the 'no title' placeholder so neither pollutes it.
    """
    cleaned = (title or "").strip()
    if not cleaned or cleaned == "제목 미정":
        return
    with get_conn() as conn:
        if campaign_id:
            conn.execute("delete from title_history where campaign_id = ?", (campaign_id,))
        conn.execute(
            "insert into title_history (campaign_id, title) values (?, ?)", (campaign_id, cleaned)
        )


def recent_titles(limit: int = 40) -> List[str]:
    with get_conn() as conn:
        rows = conn.execute(
            "select title from title_history order by id desc limit ?", (limit,)
        ).fetchall()
    return [r["title"] for r in rows]


def title_history_count() -> int:
    with get_conn() as conn:
        return conn.execute("select count(*) as n from title_history").fetchone()["n"]


def clear_title_history() -> None:
    with get_conn() as conn:
        conn.execute("delete from title_history")


def campaign_status_counts() -> Dict[str, int]:
    with get_conn() as conn:
        rows = conn.execute("select status, count(*) as n from campaigns group by status").fetchall()
    return {r["status"]: r["n"] for r in rows}


# --- assets -----------------------------------------------------------------

def register_asset(rel_path: str, filename: str, sha256: str, width: int, height: int, byte_size: int) -> str:
    asset_id = uuid.uuid4().hex
    with get_conn() as conn:
        conn.execute(
            """
            insert into assets (id, rel_path, filename, sha256, width, height, byte_size)
            values (?, ?, ?, ?, ?, ?, ?)
            on conflict(rel_path) do nothing
            """,
            (asset_id, rel_path, filename, sha256, width, height, byte_size),
        )
    return asset_id


def list_assets(limit: int = 200) -> List[Dict[str, Any]]:
    with get_conn() as conn:
        rows = conn.execute(
            "select * from assets order by created_at desc limit ?", (limit,)
        ).fetchall()
    return [dict(r) for r in rows]


def find_asset_by_rel_path(rel_path: str) -> Optional[Dict[str, Any]]:
    # rel_path is UNIQUE (core/db.py), so this is an index lookup.
    with get_conn() as conn:
        row = conn.execute("select * from assets where rel_path = ?", (rel_path,)).fetchone()
    return dict(row) if row else None


def find_asset_by_sha256(sha256: str) -> Optional[Dict[str, Any]]:
    with get_conn() as conn:
        row = conn.execute("select * from assets where sha256 = ? limit 1", (sha256,)).fetchone()
    return dict(row) if row else None


# --- vision cache -----------------------------------------------------------

def get_cached_caption(image_sha256: str, prompt_version: str, quality: str) -> Optional[str]:
    with get_conn() as conn:
        row = conn.execute(
            "select caption from vision_cache where image_sha256 = ? and prompt_version = ? and quality = ?",
            (image_sha256, prompt_version, quality),
        ).fetchone()
    return row["caption"] if row else None


def put_cached_caption(image_sha256: str, prompt_version: str, quality: str, caption: str) -> None:
    with get_conn() as conn:
        conn.execute(
            """
            insert into vision_cache (image_sha256, prompt_version, quality, caption)
            values (?, ?, ?, ?)
            on conflict(image_sha256, prompt_version, quality) do update set caption = excluded.caption
            """,
            (image_sha256, prompt_version, quality, caption),
        )


def clear_vision_cache() -> int:
    with get_conn() as conn:
        cur = conn.execute("delete from vision_cache")
        return cur.rowcount


def vision_cache_size() -> int:
    with get_conn() as conn:
        return conn.execute("select count(*) as n from vision_cache").fetchone()["n"]


# --- naver api hub ----------------------------------------------------------

def get_naver_api_settings() -> Optional[Dict[str, Any]]:
    with get_conn() as conn:
        row = conn.execute("select * from naver_api_settings where id = 1").fetchone()
    return dict(row) if row else None


def save_naver_api_settings(
    encrypted_client_id: str, encrypted_client_secret: str, daily_call_cap: int
) -> None:
    with get_conn() as conn:
        conn.execute(
            """
            insert into naver_api_settings
                (id, encrypted_client_id, encrypted_client_secret, daily_call_cap, updated_at)
            values (1, ?, ?, ?, datetime('now'))
            on conflict(id) do update set
                encrypted_client_id = excluded.encrypted_client_id,
                encrypted_client_secret = excluded.encrypted_client_secret,
                daily_call_cap = excluded.daily_call_cap,
                updated_at = datetime('now')
            """,
            (encrypted_client_id, encrypted_client_secret, daily_call_cap),
        )


def delete_naver_api_settings() -> None:
    with get_conn() as conn:
        conn.execute("delete from naver_api_settings where id = 1")


def get_searchad_settings() -> Optional[Dict[str, Any]]:
    with get_conn() as conn:
        row = conn.execute("select * from searchad_settings where id = 1").fetchone()
    return dict(row) if row else None


def save_searchad_settings(
    encrypted_customer_id: str, encrypted_api_key: str, encrypted_secret_key: str
) -> None:
    with get_conn() as conn:
        conn.execute(
            """
            insert into searchad_settings
                (id, encrypted_customer_id, encrypted_api_key, encrypted_secret_key, updated_at)
            values (1, ?, ?, ?, datetime('now'))
            on conflict(id) do update set
                encrypted_customer_id = excluded.encrypted_customer_id,
                encrypted_api_key = excluded.encrypted_api_key,
                encrypted_secret_key = excluded.encrypted_secret_key,
                updated_at = datetime('now')
            """,
            (encrypted_customer_id, encrypted_api_key, encrypted_secret_key),
        )


def delete_searchad_settings() -> None:
    with get_conn() as conn:
        conn.execute("delete from searchad_settings where id = 1")


def get_cached_metric(keyword: str, metric: str, max_age_days: int) -> Optional[str]:
    """Cached value, or None if absent or older than `max_age_days`.

    Expiry is applied in SQL rather than by deleting rows on a schedule: a
    miss on a stale row is immediately overwritten by put_cached_metric, so
    the table self-prunes without a background job.
    """
    with get_conn() as conn:
        row = conn.execute(
            """
            select value from keyword_cache
            where keyword = ? and metric = ?
              and fetched_at > datetime('now', ?)
            """,
            (keyword, metric, f"-{max_age_days} days"),
        ).fetchone()
    return row["value"] if row else None


def get_app_state(key: str, default: Any = None) -> Any:
    """JSON blob parked by a multi-step screen — see the app_state DDL."""
    with get_conn() as conn:
        row = conn.execute("select value from app_state where key = ?", (key,)).fetchone()
    if not row:
        return default
    return loads(row["value"], default)


def set_app_state(key: str, value: Any) -> None:
    with get_conn() as conn:
        conn.execute(
            """
            insert into app_state (key, value) values (?, ?)
            on conflict(key) do update set value = excluded.value,
                                           updated_at = datetime('now')
            """,
            (key, dumps(value)),
        )


def clear_app_state(key: str) -> None:
    with get_conn() as conn:
        conn.execute("delete from app_state where key = ?", (key,))


def app_state_age_days(key: str) -> Optional[float]:
    with get_conn() as conn:
        row = conn.execute(
            "select (julianday('now') - julianday(updated_at)) as age from app_state where key = ?",
            (key,),
        ).fetchone()
    return float(row["age"]) if row and row["age"] is not None else None


def cached_metric_age_days(keyword: str, metric: str) -> Optional[float]:
    """How old the cached value is, in days, or None if it was never fetched.

    `get_cached_metric` deliberately can't answer this: it returns None for
    "absent" and "stale" alike, which is right for a reader that just wants a
    usable number but useless for telling the marketer *why* scoring stopped
    working. Expiry is silent everywhere else in this pipeline, and silence is
    exactly the failure mode — see keyword_research.pool_freshness.
    """
    with get_conn() as conn:
        row = conn.execute(
            """
            select (julianday('now') - julianday(fetched_at)) as age
            from keyword_cache where keyword = ? and metric = ?
            """,
            (keyword, metric),
        ).fetchone()
    return float(row["age"]) if row and row["age"] is not None else None


def put_cached_metric(keyword: str, metric: str, value: str) -> None:
    with get_conn() as conn:
        conn.execute(
            """
            insert into keyword_cache (keyword, metric, value, fetched_at)
            values (?, ?, ?, datetime('now'))
            on conflict(keyword, metric) do update set
                value = excluded.value,
                fetched_at = datetime('now')
            """,
            (keyword, metric, value),
        )


def clear_keyword_cache() -> int:
    with get_conn() as conn:
        return conn.execute("delete from keyword_cache").rowcount


def keyword_cache_size() -> int:
    with get_conn() as conn:
        return conn.execute("select count(*) as n from keyword_cache").fetchone()["n"]


def log_naver_call(path: str, ok: bool) -> None:
    with get_conn() as conn:
        conn.execute(
            "insert into naver_api_calls (path, ok) values (?, ?)", (path, int(ok))
        )


def naver_calls_today() -> int:
    """Calls made since local midnight — the number the daily cap is checked against."""
    with get_conn() as conn:
        return conn.execute(
            "select count(*) as n from naver_api_calls where date(ts, 'localtime') = date('now', 'localtime')"
        ).fetchone()["n"]


# --- usage log --------------------------------------------------------------

# 지금 돌고 있는 생성 작업의 글 ID. content_writer가 usage_scope()로 감싸 두면, 그 안에서
# 일어난 LLM 호출이 어느 글의 비용인지 기록됩니다. 스레드풀로 넘길 때는 호출하는 쪽이
# contextvars.copy_context()로 넘겨야 합니다(ThreadPoolExecutor는 컨텍스트를 물려주지 않음).
_USAGE_CAMPAIGN: contextvars.ContextVar = contextvars.ContextVar("usage_campaign", default=None)


@contextmanager
def usage_scope(campaign_id: Optional[str]) -> Iterator[None]:
    token = _USAGE_CAMPAIGN.set(campaign_id)
    try:
        yield
    finally:
        _USAGE_CAMPAIGN.reset(token)


def current_usage_campaign() -> Optional[str]:
    return _USAGE_CAMPAIGN.get()


def _price_row(conn, vendor: Optional[str], model: Optional[str]):
    if not vendor or not model:
        return None
    return conn.execute(
        "select * from model_prices where vendor = ? and model = ?", (vendor, model)
    ).fetchone()


def compute_cost_usd(price, input_tokens: int, output_tokens: int, cached_input_tokens: int = 0) -> Optional[float]:
    """100만 토큰당 단가로 계산한 금액. 단가가 없으면 None ('단가 미등록' — 0원이 아닙니다).

    `input_tokens`는 캐시 입력을 포함한 전체 입력입니다. 캐시 단가가 비어 있으면
    캐시 입력도 일반 입력 단가로 셉니다.
    """
    if price is None:
        return None
    cached = max(0, min(int(cached_input_tokens or 0), int(input_tokens or 0)))
    fresh = max(0, int(input_tokens or 0) - cached)
    cached_rate = price["cached_input_per_mtok"]
    if cached_rate is None:
        cached_rate = price["input_per_mtok"]
    return (
        fresh * price["input_per_mtok"]
        + cached * cached_rate
        + int(output_tokens or 0) * price["output_per_mtok"]
    ) / 1_000_000


def log_usage(
    kind: str,
    vendor: Optional[str] = None,
    model: Optional[str] = None,
    image_count: int = 0,
    cache_hits: int = 0,
    est_input_tokens: int = 0,
    est_output_tokens: int = 0,
    est_saved_tokens: int = 0,
    note: Optional[str] = None,
    cached_input_tokens: int = 0,
    campaign_id: Optional[str] = None,
) -> None:
    campaign_id = campaign_id or current_usage_campaign()
    with get_conn() as conn:
        price = _price_row(conn, vendor, model)
        cost = compute_cost_usd(price, est_input_tokens, est_output_tokens, cached_input_tokens)
        # 절감 토큰은 '안 보낸 입력'이라 입력 단가로 셉니다.
        saved_cost = (est_saved_tokens * price["input_per_mtok"] / 1_000_000) if (price and est_saved_tokens) else None
        conn.execute(
            """
            insert into usage_log (kind, vendor, model, image_count, cache_hits,
                                   est_input_tokens, est_output_tokens, est_saved_tokens, note,
                                   campaign_id, cached_input_tokens, cost_usd, saved_cost_usd)
            values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (kind, vendor, model, image_count, cache_hits,
             est_input_tokens, est_output_tokens, est_saved_tokens, note,
             campaign_id, cached_input_tokens, cost, saved_cost),
        )


# --- prices · exchange rate · budget ----------------------------------------

USD_KRW_STATE_KEY = "usd_krw"
BUDGET_STATE_KEY = "usage_budget"
# 환율 기본값. 실제 환율이 아니라 시작값이며, 화면에서 고쳐 쓰라고 안내합니다.
DEFAULT_USD_KRW = 1400.0
BUDGET_WARN_LEVELS = (70, 90)


def list_model_prices() -> List[Dict[str, Any]]:
    with get_conn() as conn:
        rows = conn.execute("select * from model_prices order by vendor, model").fetchall()
    return [dict(r) for r in rows]


def get_model_price(vendor: str, model: str) -> Optional[Dict[str, Any]]:
    with get_conn() as conn:
        row = _price_row(conn, vendor, model)
    return dict(row) if row else None


def save_model_price(
    vendor: str,
    model: str,
    input_per_mtok: float,
    output_per_mtok: float,
    cached_input_per_mtok: Optional[float] = None,
) -> int:
    """단가를 저장하고, 그 모델의 '단가 미등록'(금액 없음) 기록을 이 단가로 한 번 채웁니다.

    이미 금액이 있는 기록은 그때 단가로 계산한 값이라 건드리지 않습니다 — 단가를 바꿔도
    과거 금액이 바뀌지 않게. 돌려주는 값은 새로 채운 기록 수입니다.
    """
    vendor, model = (vendor or "").strip(), (model or "").strip()
    if not vendor or not model:
        raise ValueError("벤더와 모델 이름이 필요합니다.")
    for value in (input_per_mtok, output_per_mtok, cached_input_per_mtok):
        if value is not None and value < 0:
            raise ValueError("단가는 0 이상이어야 합니다.")
    with get_conn() as conn:
        conn.execute(
            """
            insert into model_prices (vendor, model, input_per_mtok, output_per_mtok, cached_input_per_mtok)
            values (?, ?, ?, ?, ?)
            on conflict (vendor, model) do update set
                input_per_mtok = excluded.input_per_mtok,
                output_per_mtok = excluded.output_per_mtok,
                cached_input_per_mtok = excluded.cached_input_per_mtok,
                updated_at = datetime('now')
            """,
            (vendor, model, float(input_per_mtok), float(output_per_mtok),
             None if cached_input_per_mtok is None else float(cached_input_per_mtok)),
        )
        price = _price_row(conn, vendor, model)
        rows = conn.execute(
            "select id, est_input_tokens, est_output_tokens, cached_input_tokens, est_saved_tokens "
            "from usage_log where vendor = ? and model = ? and cost_usd is null",
            (vendor, model),
        ).fetchall()
        for r in rows:
            cost = compute_cost_usd(price, r["est_input_tokens"], r["est_output_tokens"], r["cached_input_tokens"])
            saved = (r["est_saved_tokens"] * price["input_per_mtok"] / 1_000_000) if r["est_saved_tokens"] else None
            conn.execute("update usage_log set cost_usd = ?, saved_cost_usd = ? where id = ?", (cost, saved, r["id"]))
    return len(rows)


def delete_model_price(vendor: str, model: str) -> None:
    """단가만 지웁니다. 이미 계산된 과거 금액은 그대로 둡니다."""
    with get_conn() as conn:
        conn.execute("delete from model_prices where vendor = ? and model = ?", (vendor, model))


def usage_models() -> List[Dict[str, Any]]:
    """단가 표에 보여 줄 (벤더, 모델) — 실제로 호출된 모델 + 등록된 LLM 모델 + 단가가 있는 모델."""
    with get_conn() as conn:
        seen = conn.execute(
            "select distinct vendor, model from usage_log where vendor is not null and model is not null"
        ).fetchall()
        registered = conn.execute("select vendor, model_name as model from llm_settings").fetchall()
        priced = conn.execute("select vendor, model from model_prices").fetchall()
    out, keys = [], set()
    for r in list(seen) + list(registered) + list(priced):
        key = (r["vendor"], r["model"])
        if key not in keys and key[0] and key[1]:
            keys.add(key)
            out.append({"vendor": key[0], "model": key[1]})
    return sorted(out, key=lambda x: (x["vendor"], x["model"]))


def get_usd_krw() -> float:
    value = (get_app_state(USD_KRW_STATE_KEY) or {}).get("value")
    try:
        rate = float(value)
    except (TypeError, ValueError):
        return DEFAULT_USD_KRW
    return rate if rate > 0 else DEFAULT_USD_KRW


def set_usd_krw(rate: float) -> None:
    if rate is None or float(rate) <= 0:
        raise ValueError("환율은 0보다 커야 합니다.")
    set_app_state(USD_KRW_STATE_KEY, {"value": float(rate)})


def get_monthly_budget_krw() -> Optional[float]:
    value = (get_app_state(BUDGET_STATE_KEY) or {}).get("monthly_krw")
    try:
        budget = float(value)
    except (TypeError, ValueError):
        return None
    return budget if budget > 0 else None


def set_monthly_budget_krw(amount: Optional[float]) -> None:
    """월 예산(원). None이나 0이면 예산 경고를 끕니다."""
    if not amount or float(amount) <= 0:
        set_app_state(BUDGET_STATE_KEY, {"monthly_krw": None})
        return
    set_app_state(BUDGET_STATE_KEY, {"monthly_krw": float(amount)})


_COST_SELECT = """
    count(*)                                        as calls,
    coalesce(sum(est_input_tokens), 0)              as input_tokens,
    coalesce(sum(est_output_tokens), 0)             as output_tokens,
    coalesce(sum(cached_input_tokens), 0)           as cached_input_tokens,
    coalesce(sum(est_saved_tokens), 0)              as saved_tokens,
    coalesce(sum(cost_usd), 0)                      as cost_usd,
    coalesce(sum(saved_cost_usd), 0)                as saved_cost_usd,
    coalesce(sum(case when cost_usd is null and (est_input_tokens + est_output_tokens) > 0
                      then 1 else 0 end), 0)        as unpriced_calls
"""


def _cost_summary(where: str = "", params: tuple = ()) -> Dict[str, Any]:
    with get_conn() as conn:
        row = conn.execute(f"select {_COST_SELECT} from usage_log {where}", params).fetchone()
    out = dict(row)
    rate = get_usd_krw()
    out["cost_krw"] = out["cost_usd"] * rate
    out["saved_cost_krw"] = out["saved_cost_usd"] * rate
    return out


def cost_today() -> Dict[str, Any]:
    return _cost_summary("where date(ts, 'localtime') = date('now', 'localtime')")


def cost_this_month() -> Dict[str, Any]:
    return _cost_summary("where strftime('%Y-%m', ts, 'localtime') = strftime('%Y-%m', 'now', 'localtime')")


def cost_all_time() -> Dict[str, Any]:
    return _cost_summary()


def cost_for_campaign(campaign_id: str, since_id: Optional[int] = None) -> Dict[str, Any]:
    """한 글의 비용. `since_id`를 주면 그 기록 뒤의 호출만(=이번 생성 실행만) 셉니다."""
    if since_id is None:
        return _cost_summary("where campaign_id = ?", (campaign_id,))
    return _cost_summary("where campaign_id = ? and id > ?", (campaign_id, since_id))


def last_usage_id() -> int:
    with get_conn() as conn:
        return conn.execute("select coalesce(max(id), 0) as n from usage_log").fetchone()["n"]


def cost_by_model() -> List[Dict[str, Any]]:
    with get_conn() as conn:
        rows = conn.execute(
            f"select vendor, model, {_COST_SELECT} from usage_log group by vendor, model "
            "order by cost_usd desc, calls desc"
        ).fetchall()
    rate = get_usd_krw()
    out = []
    for r in rows:
        d = dict(r)
        d["cost_krw"] = d["cost_usd"] * rate
        out.append(d)
    return out


def generated_post_count() -> int:
    """생성이 끝난 글 수(초안 이후 단계) — 글 1건당 평균 금액의 분모."""
    with get_conn() as conn:
        return conn.execute(
            "select count(*) as n from campaigns where status in ('draft', 'ready_to_publish', 'published')"
        ).fetchone()["n"]


def budget_status() -> Dict[str, Any]:
    """이번 달 사용액이 월 예산의 몇 %인지. 예산이 없으면 level=None.

    level: None(예산 없음 또는 70% 미만) · 70 · 90 · 100(초과).
    """
    budget = get_monthly_budget_krw()
    month = cost_this_month()
    spent = month["cost_krw"]
    out = {"budget_krw": budget, "spent_krw": spent, "ratio": None, "level": None,
           "unpriced_calls": month["unpriced_calls"]}
    if not budget:
        return out
    ratio = spent / budget
    out["ratio"] = ratio
    if ratio >= 1:
        out["level"] = 100
    else:
        for lvl in reversed(BUDGET_WARN_LEVELS):
            if ratio * 100 >= lvl:
                out["level"] = lvl
                break
    return out


def budget_message(status: Optional[Dict[str, Any]] = None) -> Optional[str]:
    """예산 경고 문구 (경고할 것이 없으면 None). 대시보드·워크벤치·사용량 탭이 같은 문구를 씁니다."""
    st = status or budget_status()
    if not st.get("level"):
        return None
    pct = st["ratio"] * 100
    head = "⛔ 이번 달 AI 사용 예산을 넘었습니다" if st["level"] >= 100 else f"⚠️ 이번 달 AI 사용 예산의 {st['level']}%를 넘었습니다"
    return (f"{head} — 약 {st['spent_krw']:,.0f}원 / 예산 {st['budget_krw']:,.0f}원 ({pct:.0f}%). "
            "생성은 계속할 수 있습니다. 금액은 등록한 단가로 계산한 추정값입니다.")


def usage_totals() -> Dict[str, int]:
    with get_conn() as conn:
        row = conn.execute(
            """
            select
                coalesce(sum(est_input_tokens), 0)  as input_tokens,
                coalesce(sum(est_output_tokens), 0) as output_tokens,
                coalesce(sum(est_saved_tokens), 0)  as saved_tokens,
                coalesce(sum(image_count), 0)       as images,
                coalesce(sum(cache_hits), 0)        as cache_hits,
                count(*)                            as calls
            from usage_log
            """
        ).fetchone()
    return dict(row)


def recent_usage(limit: int = 30) -> List[Dict[str, Any]]:
    with get_conn() as conn:
        rows = conn.execute("select * from usage_log order by id desc limit ?", (limit,)).fetchall()
    return [dict(r) for r in rows]


# --- calendar: schedule · topics · recurring rules ---------------------------

RULE_WEEKS_AHEAD = 4
WEEKDAY_LABELS = ("월", "화", "수", "목", "금", "토", "일")


def _valid_date(value: Optional[str]) -> Optional[str]:
    """'YYYY-MM-DD'로 정리합니다. 비었거나 날짜가 아니면 None."""
    text = (value or "").strip()[:10]
    if not text:
        return None
    try:
        return date.fromisoformat(text).isoformat()
    except ValueError:
        return None


def _valid_datetime(value: Optional[str]) -> Optional[str]:
    """'YYYY-MM-DD HH:MM'로 정리합니다(로컬 시각). 날짜만 있으면 09:00."""
    text = (value or "").strip().replace("T", " ")
    if not text:
        return None
    for fmt, width in (("%Y-%m-%d %H:%M:%S", 19), ("%Y-%m-%d %H:%M", 16), ("%Y-%m-%d", 10)):
        try:
            parsed = datetime.strptime(text[:width], fmt)
        except ValueError:
            continue
        if fmt == "%Y-%m-%d":
            parsed = parsed.replace(hour=9)
        return parsed.strftime("%Y-%m-%d %H:%M")
    return None


def set_campaign_schedule(
    campaign_id: str,
    scheduled_date: Optional[str] = None,
    series_name: Optional[str] = None,
    auto_generate_at: Optional[str] = None,
) -> Dict[str, Optional[str]]:
    """예정일·시리즈·자동 작성 시각을 한 번에 저장합니다. 형식이 틀린 값은 비웁니다."""
    fields = {
        "scheduled_date": _valid_date(scheduled_date),
        "series_name": (series_name or "").strip() or None,
        "auto_generate_at": _valid_datetime(auto_generate_at),
    }
    update_campaign(campaign_id, **fields)
    return fields


def move_campaign_date(campaign_id: str, new_date: Optional[str]) -> None:
    update_campaign(campaign_id, scheduled_date=_valid_date(new_date))


def scheduled_campaigns(start: str, end: str, brand_kit_id: Optional[int] = None) -> List[Dict[str, Any]]:
    """[start, end] 사이에 예정일이 있는 글 (날짜 문자열 비교 — 'YYYY-MM-DD')."""
    sql = "select * from campaigns where scheduled_date between ? and ?"
    params: list = [start, end]
    if brand_kit_id is not None:
        sql += " and brand_kit_id = ?"
        params.append(brand_kit_id)
    sql += " order by scheduled_date, created_at"
    with get_conn() as conn:
        rows = conn.execute(sql, tuple(params)).fetchall()
    return [_decode(r, _CAMPAIGN_JSON_COLS, _CAMPAIGN_BOOL_COLS) for r in rows]


def unscheduled_campaigns(brand_kit_id: Optional[int] = None) -> List[Dict[str, Any]]:
    """예정일이 없고 아직 게시되지 않은 글 — 캘린더 빈 날짜에 배치할 후보."""
    sql = "select * from campaigns where scheduled_date is null and status != 'published'"
    params: list = []
    if brand_kit_id is not None:
        sql += " and brand_kit_id = ?"
        params.append(brand_kit_id)
    sql += " order by created_at desc"
    with get_conn() as conn:
        rows = conn.execute(sql, tuple(params)).fetchall()
    return [_decode(r, _CAMPAIGN_JSON_COLS, _CAMPAIGN_BOOL_COLS) for r in rows]


def is_overdue(campaign: Dict[str, Any], today: Optional[date] = None) -> bool:
    """예정일이 지났는데 아직 게시되지 않은 글."""
    when = _valid_date(campaign.get("scheduled_date"))
    if not when or campaign.get("status") == "published":
        return False
    return date.fromisoformat(when) < (today or date.today())


def overdue_count(brand_kit_id: Optional[int] = None) -> int:
    sql = "select count(*) as n from campaigns where scheduled_date < ? and status != 'published'"
    params: list = [date.today().isoformat()]
    if brand_kit_id is not None:
        sql += " and brand_kit_id = ?"
        params.append(brand_kit_id)
    with get_conn() as conn:
        return conn.execute(sql, tuple(params)).fetchone()["n"]


def due_auto_generation(now: Optional[datetime] = None) -> List[Dict[str, Any]]:
    """자동 작성 시각이 지났고, 아직 초안이 없는 글.

    생성 중·게시된 글은 제외합니다. 메모도 뉴스 원문도 없는 글은 쓸 재료가 없어
    여기서 거르지 않고 실행기가 실패로 기록합니다(왜 안 됐는지 보이게).
    """
    stamp = (now or datetime.now()).strftime("%Y-%m-%d %H:%M")
    with get_conn() as conn:
        rows = conn.execute(
            """
            select * from campaigns
            where auto_generate_at is not null and auto_generate_at <= ?
              and status in ('awaiting_media', 'queued', 'failed')
              and (content is null or trim(content) = '')
            order by auto_generate_at
            """,
            (stamp,),
        ).fetchall()
    return [_decode(r, _CAMPAIGN_JSON_COLS, _CAMPAIGN_BOOL_COLS) for r in rows]


def list_topics(include_linked: bool = True, brand_kit_id: Optional[int] = None) -> List[Dict[str, Any]]:
    sql = "select * from topics"
    clauses, params = [], []
    if not include_linked:
        clauses.append("campaign_id is null")
    if brand_kit_id is not None:
        clauses.append("brand_kit_id = ?")
        params.append(brand_kit_id)
    if clauses:
        sql += " where " + " and ".join(clauses)
    sql += " order by case when planned_date is null then 1 else 0 end, planned_date, id"
    with get_conn() as conn:
        rows = conn.execute(sql, tuple(params)).fetchall()
    return [dict(r) for r in rows]


def get_topic(topic_id: int) -> Optional[Dict[str, Any]]:
    with get_conn() as conn:
        row = conn.execute("select * from topics where id = ?", (topic_id,)).fetchone()
    return dict(row) if row else None


def add_topic(
    title: str,
    memo: Optional[str] = None,
    brand_kit_id: Optional[int] = None,
    content_mode: Optional[str] = None,
    planned_date: Optional[str] = None,
    series_name: Optional[str] = None,
) -> int:
    cleaned = (title or "").strip()
    if not cleaned and not (memo or "").strip():
        raise ValueError("주제 제목이나 메모 중 하나는 적어주세요.")
    with get_conn() as conn:
        cur = conn.execute(
            "insert into topics (title, memo, brand_kit_id, content_mode, planned_date, series_name) "
            "values (?, ?, ?, ?, ?, ?)",
            (cleaned, (memo or "").strip() or None, brand_kit_id, content_mode or None,
             _valid_date(planned_date), (series_name or "").strip() or None),
        )
        return cur.lastrowid


_TOPIC_FIELDS = ("title", "memo", "brand_kit_id", "content_mode", "planned_date", "series_name")


def update_topic(topic_id: int, **fields) -> None:
    clean = {k: v for k, v in fields.items() if k in _TOPIC_FIELDS}
    if "planned_date" in clean:
        clean["planned_date"] = _valid_date(clean["planned_date"])
    if not clean:
        return
    assignments = ", ".join(f"{k} = ?" for k in clean)
    with get_conn() as conn:
        conn.execute(
            f"update topics set {assignments}, updated_at = datetime('now') where id = ?",
            tuple(clean.values()) + (topic_id,),
        )


def delete_topic(topic_id: int) -> None:
    """주제를 지웁니다. 이미 만든 글은 그대로 남습니다."""
    with get_conn() as conn:
        conn.execute("delete from topics where id = ?", (topic_id,))


def topic_to_campaign(topic_id: int) -> Dict[str, Any]:
    """주제로 새 글을 만들고(메모·킷·모드·예정일·시리즈를 채워) 주제에 연결합니다.

    이미 연결된 글이 있으면 그 글을 돌려줍니다 — 두 번 눌러도 글이 두 개 생기지 않게.
    """
    topic = get_topic(topic_id)
    if not topic:
        raise ValueError("주제를 찾을 수 없습니다.")
    if topic.get("campaign_id"):
        existing = get_campaign(topic["campaign_id"])
        if existing:
            return existing
    memo_parts = [p for p in ((topic.get("title") or "").strip(), (topic.get("memo") or "").strip()) if p]
    created = insert_campaign(
        source_type="manual", status="awaiting_media",
        memo="\n".join(memo_parts) or None,
        brand_kit_id=topic.get("brand_kit_id"),
    )
    update_campaign(
        created["id"], content_mode=topic.get("content_mode") or None,
        scheduled_date=_valid_date(topic.get("planned_date")),
        series_name=topic.get("series_name") or None,
    )
    with get_conn() as conn:
        conn.execute("update topics set campaign_id = ?, updated_at = datetime('now') where id = ?",
                     (created["id"], topic_id))
    return get_campaign(created["id"])


def list_rules() -> List[Dict[str, Any]]:
    with get_conn() as conn:
        rows = conn.execute("select * from schedule_rules order by weekday, id").fetchall()
    return [dict(r) for r in rows]


def add_rule(
    weekday: int,
    brand_kit_id: Optional[int] = None,
    content_mode: Optional[str] = None,
    title: str = "",
    series_name: Optional[str] = None,
) -> int:
    if not 0 <= int(weekday) <= 6:
        raise ValueError("요일이 올바르지 않습니다.")
    with get_conn() as conn:
        cur = conn.execute(
            "insert into schedule_rules (weekday, brand_kit_id, content_mode, title, series_name) values (?, ?, ?, ?, ?)",
            (int(weekday), brand_kit_id, content_mode or None, (title or "").strip(),
             (series_name or "").strip() or None),
        )
        return cur.lastrowid


def delete_rule(rule_id: int, remove_empty_slots: bool = True) -> int:
    """규칙을 지웁니다. `remove_empty_slots`면 그 규칙이 만든 자리 중 아직 글로 만들지 않은 것도 지웁니다."""
    with get_conn() as conn:
        removed = 0
        if remove_empty_slots:
            removed = conn.execute(
                "delete from topics where rule_id = ? and campaign_id is null", (rule_id,)
            ).rowcount
        conn.execute("update topics set rule_id = null where rule_id = ?", (rule_id,))
        conn.execute("delete from schedule_rules where id = ?", (rule_id,))
    return removed


def rule_dates(weekday: int, start: Optional[date] = None, weeks: int = RULE_WEEKS_AHEAD) -> List[str]:
    """오늘(포함)부터 `weeks`주 안의 그 요일 날짜들."""
    start = start or date.today()
    first = start + timedelta(days=(int(weekday) - start.weekday()) % 7)
    return [(first + timedelta(weeks=i)).isoformat() for i in range(weeks)]


def apply_rules(start: Optional[date] = None, weeks: int = RULE_WEEKS_AHEAD) -> int:
    """켜져 있는 규칙마다 앞으로 `weeks`주의 빈 자리(주제)를 만듭니다.

    같은 규칙·같은 날짜의 자리가 이미 있으면 건너뛰므로 여러 번 불러도 겹치지 않습니다.
    담당자가 지운 자리는 다음에 이 함수를 부를 때 다시 생깁니다 — 그래서 캘린더는 화면을 열 때마다
    부르지 않고, 규칙을 추가할 때와 [규칙으로 자리 만들기]를 누를 때만 부릅니다. 만든 자리 수를 돌려줍니다.
    """
    created = 0
    for rule in list_rules():
        if not rule.get("is_active"):
            continue
        label = rule.get("title") or f"매주 {WEEKDAY_LABELS[rule['weekday']]}요일 글"
        for day in rule_dates(rule["weekday"], start, weeks):
            with get_conn() as conn:
                cur = conn.execute(
                    "insert or ignore into topics (title, brand_kit_id, content_mode, planned_date, series_name, rule_id) "
                    "values (?, ?, ?, ?, ?, ?)",
                    (label, rule.get("brand_kit_id"), rule.get("content_mode"), day,
                     rule.get("series_name"), rule["id"]),
                )
                created += cur.rowcount
    return created
