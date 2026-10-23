"""📦 데이터 옮기기 (core/transfer.py) — 다른 PC(다른 DB·다른 마스터 키)로 옮겨지는지.

'다른 PC'는 같은 임시 데이터 폴더에서 DB와 .master_key를 지우고 다시 만들어 흉내 냅니다.
실제 data/ 폴더는 쓰지 않습니다(conftest.py).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from core import crypto_utils as c
from core import db, repo, transfer
from core.brand_seed import seed_if_empty

ALL_PARTS = list(transfer.PARTS)


def _new_pc() -> None:
    """DB와 마스터 키를 지워 처음 설치한 PC처럼 만든다."""
    for suffix in ("", "-wal", "-shm"):
        path = Path(str(db.DB_PATH) + suffix)
        if path.exists():
            path.unlink()
    key = db.DATA_DIR / ".master_key"
    if key.exists():
        key.unlink()
    db._initialized = False
    db.init_db()


def _kit_id(name: str) -> int:
    return next(k["id"] for k in repo.list_brand_kits() if k["name"] == name)


@pytest.fixture
def sender():
    """보내는 PC: 킷 둘(하나는 보관 킷 하나 더), 키, 단가, 측정값, 제목 이력."""
    seed_if_empty()
    wig = repo.create_brand_kit("가발관리")
    repo.save_brand_kit(wig, tone_and_manner="짧게 씁니다.", seo_keywords=["가발 세척"], design_strength="rich")
    old = repo.create_brand_kit("옛 킷")
    repo.archive_brand_kit(old)
    repo.save_company_profile(naver_blog_id="cjc_blog", blacklist_map={"완치": "개선"})
    repo.upsert_llm_setting("google", "gemini-3.8-flash", c.encrypt_api_key("AIza-SECRET"))
    repo.save_naver_api_settings(c.encrypt_api_key("cid-1"), c.encrypt_api_key("csec-1"), 300)
    repo.save_searchad_settings(c.encrypt_api_key("cust"), c.encrypt_api_key("ak"), c.encrypt_api_key("sk"))
    repo.save_app_settings(default_generation_vendor="google", vision_vendor="google", enabled_channels=["instagram"])
    repo.set_app_state("naver_format_mode", {"value": "symbol"})
    repo.set_app_state("ui_font_scale", {"value": 1.4})
    repo.set_app_state(repo.kit_state_key("sweep", wig), {"stage": 2})
    repo.save_model_price("google", "gemini-3.8-flash", 0.3, 2.5, 0.075)
    repo.set_usd_krw(1380)
    repo.set_monthly_budget_krw(50000)
    repo.put_cached_metric("가발 세척", "blog_total", "1234")
    repo.record_title("가발 세척 방법 5가지")
    camp = repo.insert_campaign(source_type="manual", title="보낸 PC의 글")
    return {"wig": wig, "campaign": camp}


def test_every_table_is_classified():
    """새 테이블을 만들면 옮길지 말지 transfer.TABLE_PARTS에 정해야 합니다."""
    with db.get_conn() as conn:
        tables = {r[0] for r in conn.execute("select name from sqlite_master where type = 'table' "
                                             "and name not like 'sqlite_%'")}
    assert tables == set(transfer.TABLE_PARTS)
    assert set(v for v in transfer.TABLE_PARTS.values() if v) <= set(transfer.PARTS)


def test_format_state_key_matches():
    from ai_workers import formatting
    assert formatting.NAVER_FORMAT_STATE_KEY in transfer.APP_STATE_PARTS


def test_round_trip_to_new_pc(sender):
    raw = transfer.export_bundle(ALL_PARTS, "pw1234")
    text = raw.decode("utf-8")
    for secret in ("AIza-SECRET", "cid-1", "csec-1"):
        assert secret not in text  # 키는 평문으로 남지 않는다
    assert "옛 킷" not in text  # 보관한 킷은 옮기지 않는다
    assert "보낸 PC의 글" not in text
    assert "ui_font_scale" not in text and "sweep:" not in text

    _new_pc()
    seed_if_empty()
    mine = repo.insert_campaign(source_type="manual", title="받는 PC의 글")
    repo.log_usage("text", vendor="google", model="gemini-3.8-flash", est_input_tokens=1_000_000)
    assert repo.recent_usage(1)[0]["cost_usd"] is None  # 이 PC에는 아직 단가가 없다

    with pytest.raises(transfer.TransferError):
        transfer.import_bundle(raw, ALL_PARTS, "wrong!")
    assert repo.list_llm_settings() == []  # 틀린 비밀번호면 아무것도 바꾸지 않는다
    assert [k["name"] for k in repo.list_brand_kits()] == ["기본"]

    result = transfer.import_bundle(raw, ALL_PARTS, "pw1234")
    assert set(ALL_PARTS) <= set(result)
    assert Path(result["backup"]).exists() and Path(result["backup"]).parent.name == "backups"

    assert c.decrypt_api_key(repo.get_llm_setting("google")["encrypted_api_key"]) == "AIza-SECRET"
    naver = repo.get_naver_api_settings()
    assert c.decrypt_api_key(naver["encrypted_client_secret"]) == "csec-1" and naver["daily_call_cap"] == 300
    assert c.decrypt_api_key(repo.get_searchad_settings()["encrypted_secret_key"]) == "sk"

    names = [k["name"] for k in repo.list_brand_kits()]
    assert names == ["기본", "가발관리"]
    wig = repo.get_brand_kit(_kit_id("가발관리"))
    assert wig["tone_and_manner"] == "짧게 씁니다." and wig["seo_keywords"] == ["가발 세척"]
    assert wig["design_strength"] == "rich"

    profile = repo.get_company_profile()
    assert profile["naver_blog_id"] == "cjc_blog" and profile["blacklist_map"] == {"완치": "개선"}
    app = repo.get_app_settings()
    assert app["default_generation_vendor"] == "google" and app["enabled_channels"] == ["instagram"]
    assert repo.get_app_state("naver_format_mode") == {"value": "symbol"}

    assert repo.get_model_price("google", "gemini-3.8-flash")["cached_input_per_mtok"] == 0.075
    assert repo.get_usd_krw() == 1380 and repo.get_monthly_budget_krw() == 50000
    assert repo.recent_usage(1)[0]["cost_usd"] == pytest.approx(0.3)  # 단가 미등록 기록을 채운다

    assert repo.get_cached_metric("가발 세척", "blog_total", 30) == "1234"
    assert repo.recent_titles() == ["가발 세척 방법 5가지"]

    # 받는 PC의 글과 PC별 값은 그대로
    assert [x["title"] for x in repo.list_campaigns()] == ["받는 PC의 글"]
    assert repo.get_campaign(mine["id"])["title"] == "받는 PC의 글"
    assert repo.get_app_state("ui_font_scale") is None


def test_import_twice_is_safe(sender):
    raw = transfer.export_bundle(ALL_PARTS, "pw1234")
    _new_pc()
    transfer.import_bundle(raw, ALL_PARTS, "pw1234")
    transfer.import_bundle(raw, ALL_PARTS, "pw1234")
    assert [k["name"] for k in repo.list_brand_kits()] == ["기본", "가발관리"]
    assert repo.title_history_count() == 1
    assert len(repo.list_model_prices()) == 1


def test_kits_match_by_name_and_keep_local_ids(sender):
    raw = transfer.export_bundle(["brand_kits"])
    _new_pc()
    seed_if_empty()
    local_only = repo.create_brand_kit("받는 PC 전용")
    wig = repo.create_brand_kit("가발관리")
    repo.save_brand_kit(wig, tone_and_manner="옛 톤")
    camp = repo.insert_campaign(source_type="manual", title="x")
    repo.set_campaign_brand_kit(camp["id"], wig)

    preview = transfer.preview_bundle(transfer.read_bundle(raw))
    assert "가발관리" in preview["brand_kits"] and "내용을 바꿈" in preview["brand_kits"]

    transfer.import_bundle(raw, ["brand_kits"])
    assert _kit_id("가발관리") == wig  # 같은 이름의 킷은 ID를 유지하고 내용만 바뀐다
    assert repo.get_brand_kit(wig)["tone_and_manner"] == "짧게 씁니다."
    assert repo.get_campaign(camp["id"])["brand_kit_id"] == wig
    assert _kit_id("받는 PC 전용") == local_only  # 받는 PC에만 있는 킷은 그대로


def test_only_chosen_parts_change(sender):
    raw = transfer.export_bundle(ALL_PARTS, "pw1234")
    _new_pc()
    seed_if_empty()
    repo.save_company_profile(naver_blog_id="mine")
    transfer.import_bundle(raw, ["keyword_cache"])
    assert repo.get_company_profile()["naver_blog_id"] == "mine"
    assert repo.list_llm_settings() == []
    assert repo.get_cached_metric("가발 세척", "blog_total", 30) == "1234"


def test_company_keeps_vendor_without_local_key(sender):
    """키 없이 회사·앱 설정만 가져오면, 이 PC에 키가 없는 벤더로 모델 선택을 바꾸지 않는다."""
    raw = transfer.export_bundle(["company"])
    _new_pc()
    repo.upsert_llm_setting("openai", "gpt-x", c.encrypt_api_key("sk-local"))
    repo.save_app_settings(default_generation_vendor="openai")
    result = transfer.import_bundle(raw, ["company"])
    assert repo.get_app_settings()["default_generation_vendor"] == "openai"
    assert "그대로 둠" in result["company"]
    assert repo.get_company_profile()["naver_blog_id"] == "cjc_blog"


def test_keys_only_sets_default_vendor_when_missing(sender):
    raw = transfer.export_bundle(["api_keys"], "pw1234")
    _new_pc()
    transfer.import_bundle(raw, ["api_keys"], "pw1234")
    assert repo.get_app_settings()["default_generation_vendor"] == "google"


def test_newer_local_metric_is_kept(sender):
    raw = transfer.export_bundle(["keyword_cache"])
    _new_pc()
    with db.get_conn() as conn:
        conn.execute("insert into keyword_cache (keyword, metric, value, fetched_at) "
                     "values ('가발 세척', 'blog_total', '9999', datetime('now', '+1 day'))")
    transfer.import_bundle(raw, ["keyword_cache"])
    with db.get_conn() as conn:
        value = conn.execute("select value from keyword_cache where keyword = '가발 세척'").fetchone()[0]
    assert value == "9999"


def test_export_requires_password_for_keys():
    with pytest.raises(transfer.TransferError):
        transfer.export_bundle(["api_keys"], "")
    with pytest.raises(transfer.TransferError):
        transfer.export_bundle(["api_keys"], "12345")
    with pytest.raises(transfer.TransferError):
        transfer.export_bundle([])


def test_rejects_other_files():
    with pytest.raises(transfer.TransferError, match="다른 회사"):
        transfer.read_bundle(json.dumps({"format": "osmu-transfer", "version": 1}).encode())
    with pytest.raises(transfer.TransferError):
        transfer.read_bundle(b"not json")
    with pytest.raises(transfer.TransferError, match="새 버전"):
        transfer.read_bundle(json.dumps({"format": transfer.FORMAT, "version": 99}).encode())


def test_backups_are_pruned(sender):
    raw = transfer.export_bundle(["title_history"])
    for _ in range(transfer._BACKUP_KEEP + 2):
        transfer.import_bundle(raw, ["title_history"])
    backups = list((db.DATA_DIR / transfer.BACKUP_DIR_NAME).glob("osmu-before-import-*.db"))
    assert len(backups) == transfer._BACKUP_KEEP
