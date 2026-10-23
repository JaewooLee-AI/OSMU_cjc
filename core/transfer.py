"""데이터 옮기기 — 한 PC에서 세팅한 브랜드 킷·회사 설정·API 키·AI 단가·키워드 측정값·제목 이력을
파일 하나(.osmu)로 내보내고 다른 담당자 PC에서 가져온다.

같은 엔진을 쓰는 OSMU_osw의 📦 데이터 옮기기(2026-10-21)를 이 앱의 구조에 맞춰 옮긴 것이다.
이 앱은 서버 없이 PC마다 데이터를 따로 저장하므로, 담당자가 여럿이면 각자 키를 넣고 브랜드 킷을
맞춰야 한다. 데이터 폴더를 통째로 복사하면 받는 PC의 글·사진·사용 기록까지 덮어쓰므로, 이 파일은
고른 항목만 담고 가져올 때도 그 항목만 바꾼다.

OSMU_osw와 다른 점:
- 브랜드 킷이 여러 개다. 보관하지 않은 킷을 전부 담고, 받는 PC에서는 **킷 이름**으로 맞춘다
  (같은 이름의 킷은 내용을 바꾸고, 없으면 새로 만든다). 킷 ID는 PC마다 다르므로 옮기지 않는다 —
  받는 PC의 글·주제·반복 규칙이 들고 있는 킷 ID가 그대로 유효해야 한다. 받는 PC에만 있는 킷은 그대로 둔다.
- 회사 공통 값(company_profile)과 앱 설정(app_settings)은 브랜드 킷과 테이블이 다르므로 따로 고른다.
- 기능 보완 v2의 AI 단가(model_prices)·환율·월 예산, 제목 이력(title_history)도 고를 수 있다.
- 가져오기는 한 트랜잭션이다. 중간에 실패하면 아무것도 바뀌지 않고, 바꾸기 직전에 받는 PC의
  DB를 데이터 폴더의 backups/에 복사해 둔다.
- 다른 앱(OSMU_osw 등)이 만든 파일은 형식 이름이 달라 받지 않는다 — 다른 회사의 브랜드 킷이 섞이면 안 된다.

API 키는 각 PC의 마스터 키(데이터 폴더의 .master_key)로 암호화되어 있어 그대로 옮기면 다른 PC에서
열리지 않는다. 그래서 내보낼 때 평문으로 풀어 **내보내는 사람이 정한 비밀번호**로 다시 암호화하고
(PBKDF2-HMAC-SHA256 → AES-256-GCM), 가져올 때 그 비밀번호로 풀어 받는 PC의 마스터 키로 다시
암호화해 저장한다. 마스터 키 파일 자체는 절대 옮기지 않는다.
"""
from __future__ import annotations

import base64
import json
import os
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

from core import crypto_utils, repo
from core.db import DATA_DIR, DB_PATH, DEFAULT_KIT_NAME, dumps, get_conn

FORMAT = "osmu-cjc-transfer"
# 같은 엔진을 쓰는 다른 앱이 만든 파일 — 형식은 비슷하지만 다른 회사의 데이터다.
_OTHER_APP_FORMATS = {"osmu-transfer"}
VERSION = 1
FILE_EXTENSION = "osmu"
_KDF_ITERATIONS = 390_000
MIN_PASSWORD_LENGTH = 6
BACKUP_DIR_NAME = "backups"
_BACKUP_KEEP = 5

PARTS = {
    "brand_kits": "브랜드 킷 — 사업 분야별 킷 전부 (페르소나·톤앤매너·핵심 팩트·샘플·용어집·SEO 키워드·서식 기본값)",
    "company": "회사 공통·앱 설정 — 계정·금기어 사전·가드레일·기본 생성 모델·사진 분석·생성 채널·네이버 서식 방식",
    "api_keys": "API 키 — LLM 벤더·네이버 API HUB·검색광고 (비밀번호로 암호화)",
    "cost_settings": "AI 비용 설정 — 모델 단가·환율·월 예산",
    "keyword_cache": "키워드 측정값 — 검색량·경쟁도 (받는 PC에서 다시 재지 않아도 됨)",
    "title_history": "제목 이력 — 같은 블로그에 겹치는 제목을 피하는 데 씀",
}

# app_state 중 옮기는 키와 그 키가 속한 항목. 나머지 키(키워드 화면 진행 상태 sweep:{킷 ID}·
# category_sweep:{킷 ID}, 키워드 화면에서 고른 킷, 글자 크기, 시드 수정 적용 기록)는 PC마다 다르다.
# naver_format_mode는 ai_workers.formatting.NAVER_FORMAT_STATE_KEY와 같은 값이다(core가 ai_workers를
# import하지 않도록 여기 적는다 — 시험이 둘이 같은지 확인한다).
APP_STATE_PARTS = {
    "naver_format_mode": "company",
    repo.USD_KRW_STATE_KEY: "cost_settings",
    repo.BUDGET_STATE_KEY: "cost_settings",
}

# DB의 모든 테이블이 어느 항목으로 옮겨지는지(None = 옮기지 않음). 새 테이블을 만들면 여기에도
# 넣어야 tests/test_transfer.py가 통과한다 — 새 데이터를 옮길지 말지 한 번은 정하게 하려는 것이다.
TABLE_PARTS: Dict[str, Optional[str]] = {
    "brand_kit": "brand_kits",
    "company_profile": "company",
    "app_settings": "company",
    "app_state": "company",  # APP_STATE_PARTS의 키만
    "llm_settings": "api_keys",
    "naver_api_settings": "api_keys",
    "searchad_settings": "api_keys",
    "model_prices": "cost_settings",
    "keyword_cache": "keyword_cache",
    "title_history": "title_history",
    # 글과 그 글에 딸린 것 — 받는 PC의 작업을 덮어쓰면 안 된다.
    "campaigns": None,       # 글 본문·서식·캘린더 일정(scheduled_date 등)·게시 기록(published_url)
    "assets": None,          # 사진 목록 — 사진 파일(assets/)과 함께 PC에 남는다
    "vision_cache": None,    # 사진 분석 결과 — 그 PC의 사진에 묶인다
    "topics": None,          # 캘린더 주제 — 받는 PC의 글·킷 ID에 연결된다
    "schedule_rules": None,  # 반복 규칙 — 받는 PC의 킷 ID에 연결된다
    "usage_log": None,       # AI 사용 기록 — 그 PC에서 쓴 비용이다
    "naver_api_calls": None,  # API HUB 호출 기록 — 그 PC의 일일 상한 계산용
}

# 화면과 문서에 보여 줄 '옮기지 않는 것'.
NOT_TRANSFERRED = (
    "글(본문·서식·캘린더 일정·게시 기록)·사진·사진 분석 캐시·주제 목록·반복 규칙·AI 사용 기록·"
    "네이버 API 호출 기록·키워드 화면 진행 상태·글자 크기·네이버 로그인 세션·API 키 암호화 마스터 키"
)


class TransferError(Exception):
    """사용자에게 그대로 보여 줄 수 있는 오류."""


# --- 비밀번호 암호화 ---------------------------------------------------------

def _derive(password: str, salt: bytes, iterations: int = _KDF_ITERATIONS) -> bytes:
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=iterations)
    return kdf.derive(password.encode("utf-8"))


def _seal(payload: dict, password: str) -> dict:
    salt, nonce = os.urandom(16), os.urandom(12)
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    ct = AESGCM(_derive(password, salt)).encrypt(nonce, data, FORMAT.encode())
    b64 = lambda b: base64.b64encode(b).decode("ascii")  # noqa: E731
    return {"kdf": "pbkdf2-sha256", "iterations": _KDF_ITERATIONS, "salt": b64(salt), "nonce": b64(nonce), "ciphertext": b64(ct)}


def _open(sealed: dict, password: str) -> dict:
    try:
        salt = base64.b64decode(sealed["salt"])
        nonce = base64.b64decode(sealed["nonce"])
        ct = base64.b64decode(sealed["ciphertext"])
        key = _derive(password, salt, int(sealed["iterations"]))
        data = AESGCM(key).decrypt(nonce, ct, FORMAT.encode())
    except Exception as exc:  # noqa: BLE001 — 틀린 비밀번호는 InvalidTag로 온다
        raise TransferError("비밀번호가 맞지 않거나 파일이 손상되었습니다.") from exc
    return json.loads(data.decode("utf-8"))


def _plain_secrets() -> dict:
    """이 PC에 저장된 키를 평문으로 — 내보내기 직전에만, 메모리 안에서만 쓴다."""
    dec = crypto_utils.decrypt_api_key
    out: dict = {"llm": [], "naver_api": None, "searchad": None}
    for row in repo.list_llm_settings():
        out["llm"].append({
            "vendor": row["vendor"], "model_name": row["model_name"],
            "api_key": dec(row["encrypted_api_key"]), "is_active": bool(row["is_active"]),
        })
    naver = repo.get_naver_api_settings()
    if naver:
        out["naver_api"] = {
            "client_id": dec(naver["encrypted_client_id"]),
            "client_secret": dec(naver["encrypted_client_secret"]),
            "daily_call_cap": naver.get("daily_call_cap"),
        }
    searchad = repo.get_searchad_settings()
    if searchad:
        out["searchad"] = {
            "customer_id": dec(searchad["encrypted_customer_id"]),
            "api_key": dec(searchad["encrypted_api_key"]),
            "secret_key": dec(searchad["encrypted_secret_key"]),
        }
    # 키만 가져가는 PC에 기본 생성 모델이 없을 때 따를 값 (import_bundle 참고).
    out["default_generation_vendor"] = repo.get_app_settings().get("default_generation_vendor")
    return out


# --- 내보내기 ---------------------------------------------------------------

def _state_values(part: str) -> Dict[str, Any]:
    out = {}
    for key, owner in APP_STATE_PARTS.items():
        if owner == part:
            value = repo.get_app_state(key)
            if value is not None:
                out[key] = value
    return out


def summary_of_local() -> Dict[str, str]:
    """내보내기 화면에 보여 줄 '이 PC에 무엇이 있는지'."""
    kits = repo.list_brand_kits()
    company = repo.get_company_profile()
    vendors = [r["vendor"] for r in repo.list_llm_settings()]
    keys = []
    if vendors:
        keys.append("LLM " + ", ".join(vendors))
    if repo.get_naver_api_settings():
        keys.append("네이버 API HUB")
    if repo.get_searchad_settings():
        keys.append("검색광고")
    with get_conn() as conn:
        prices = conn.execute("select count(*) from model_prices").fetchone()[0]
    return {
        "brand_kits": f"{len(kits)}개 — " + ", ".join(k["name"] for k in kits),
        "company": f"{company.get('brand_name') or '(이름 없음)'} · 블로그 {company.get('naver_blog_id') or '-'}",
        "api_keys": ", ".join(keys) or "(저장된 키 없음)",
        "cost_settings": f"단가 {prices}개 · 환율 {repo.get_usd_krw():,.0f}원",
        "keyword_cache": f"{repo.keyword_cache_size():,}건",
        "title_history": f"{repo.title_history_count():,}건",
    }


def export_bundle(parts: List[str], password: Optional[str] = None) -> bytes:
    """고른 항목을 담은 .osmu 파일 내용(bytes)."""
    parts = [p for p in PARTS if p in set(parts)]
    if not parts:
        raise TransferError("내보낼 항목을 하나 이상 고르세요.")
    if "api_keys" in parts and (not password or len(password) < MIN_PASSWORD_LENGTH):
        raise TransferError(f"API 키를 내보내려면 {MIN_PASSWORD_LENGTH}자 이상의 비밀번호가 필요합니다.")

    contents: Dict[str, Any] = {}
    if "brand_kits" in parts:
        contents["brand_kits"] = [
            {
                **{k: kit.get(k) for k in repo.BRAND_KIT_FIELDS},
                "sort_order": kit.get("sort_order") or 0,
                "updated_at": kit.get("updated_at"),  # 미리 보기용 — 가져올 때는 받는 PC 시각
            }
            for kit in repo.list_brand_kits()
        ]
    if "company" in parts:
        contents["company"] = {
            "company_profile": repo.get_company_profile(),
            "app_settings": repo.get_app_settings(),
            "app_state": _state_values("company"),
        }
    if "cost_settings" in parts:
        contents["cost_settings"] = {
            "model_prices": [
                {k: p[k] for k in ("vendor", "model", "input_per_mtok", "output_per_mtok", "cached_input_per_mtok")}
                for p in repo.list_model_prices()
            ],
            "app_state": _state_values("cost_settings"),
        }
    with get_conn() as conn:
        if "keyword_cache" in parts:
            contents["keyword_cache"] = [
                dict(r) for r in conn.execute("select keyword, metric, value, fetched_at from keyword_cache")
            ]
        if "title_history" in parts:
            # campaign_id는 보낸 PC의 글 ID라 받는 PC에서는 뜻이 없어 뺀다.
            contents["title_history"] = [
                dict(r) for r in conn.execute("select title, created_at from title_history order by id")
            ]

    bundle: Dict[str, Any] = {
        "format": FORMAT, "version": VERSION,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "parts": parts, "contents": contents,
    }
    if "api_keys" in parts:
        bundle["secrets"] = _seal(_plain_secrets(), password)
    return json.dumps(bundle, ensure_ascii=False, indent=1).encode("utf-8")


def default_file_name() -> str:
    return f"OSMU_CJC_데이터_{datetime.now():%Y%m%d}.{FILE_EXTENSION}"


# --- 가져오기 ---------------------------------------------------------------

def read_bundle(raw: bytes) -> dict:
    """파일을 읽어 형식만 확인한다(가져오기 전 미리 보기용)."""
    try:
        bundle = json.loads((raw or b"").decode("utf-8"))
    except Exception as exc:  # noqa: BLE001
        raise TransferError("OSMU 데이터 파일이 아닙니다.") from exc
    if not isinstance(bundle, dict):
        raise TransferError("OSMU 데이터 파일이 아닙니다.")
    if bundle.get("format") in _OTHER_APP_FORMATS:
        raise TransferError("다른 회사용 OSMU 앱에서 만든 파일입니다. 씨제이씨 OSMU 앱에서 내보낸 파일만 가져올 수 있습니다.")
    if bundle.get("format") != FORMAT:
        raise TransferError("OSMU 데이터 파일이 아닙니다.")
    try:
        version = int(bundle.get("version") or 0)
    except (TypeError, ValueError):
        version = 0
    if version > VERSION:
        raise TransferError("더 새 버전의 앱에서 만든 파일입니다. 앱을 업데이트한 뒤 가져오세요.")
    if not isinstance(bundle.get("contents") or {}, dict):
        raise TransferError("파일이 손상되었습니다.")
    return bundle


def _clean_name(name: Any) -> str:
    return " ".join(str(name or "").split()) or DEFAULT_KIT_NAME


def preview_bundle(bundle: dict) -> Dict[str, str]:
    """가져오기 전에 항목마다 '이 PC에서 무엇이 바뀌는지'."""
    contents = bundle.get("contents") or {}
    out: Dict[str, str] = {}
    available = set(bundle.get("parts") or [])
    if "brand_kits" in available:
        local = {k["name"] for k in repo.list_brand_kits()}
        names = [_clean_name(k.get("name")) for k in contents.get("brand_kits") or []]
        changed = [n for n in names if n in local]
        added = [n for n in names if n not in local]
        bits = []
        if changed:
            bits.append("내용을 바꿈: " + ", ".join(changed))
        if added:
            bits.append("새로 만듦: " + ", ".join(added))
        out["brand_kits"] = " / ".join(bits) or "(킷 없음)"
    if "company" in available:
        prof = (contents.get("company") or {}).get("company_profile") or {}
        out["company"] = f"{prof.get('brand_name') or '-'} · 블로그 {prof.get('naver_blog_id') or '-'} (이 PC의 값을 바꿈)"
    if "api_keys" in available:
        out["api_keys"] = "비밀번호를 넣어야 내용을 볼 수 있습니다. 같은 벤더의 키는 바뀝니다."
    if "cost_settings" in available:
        prices = (contents.get("cost_settings") or {}).get("model_prices") or []
        out["cost_settings"] = f"단가 {len(prices)}개 (같은 모델의 단가는 바뀜)"
    if "keyword_cache" in available:
        out["keyword_cache"] = f"{len(contents.get('keyword_cache') or []):,}건 (이 PC에 더 최근 값이 있으면 유지)"
    if "title_history" in available:
        out["title_history"] = f"{len(contents.get('title_history') or []):,}건 (이미 있는 제목은 건너뜀)"
    return out


def backup_database() -> Optional[Path]:
    """가져오기 직전의 DB를 데이터 폴더의 backups/에 복사한다(최근 5개만 남김).
    설치 폴더가 아니라 데이터 폴더에 둔다 — CLAUDE.md '데이터 폴더' 참고."""
    if not DB_PATH.exists():
        return None
    folder = DATA_DIR / BACKUP_DIR_NAME
    folder.mkdir(parents=True, exist_ok=True)
    # 마이크로초까지 붙여 이름순 = 시간순이 되게 한다(아래 정리가 이름순으로 오래된 것을 지움).
    target = folder / f"osmu-before-import-{datetime.now():%Y%m%d-%H%M%S-%f}.db"
    src = sqlite3.connect(DB_PATH)
    dst = sqlite3.connect(target)
    try:
        src.backup(dst)  # WAL에 있는 내용까지 일관된 사본으로
    finally:
        dst.close()
        src.close()
    for old in sorted(folder.glob("osmu-before-import-*.db"))[:-_BACKUP_KEEP]:
        old.unlink(missing_ok=True)
    return target


def _encrypted_secrets(secrets: dict) -> dict:
    """받는 PC의 마스터 키로 다시 암호화. 트랜잭션을 열기 전에 한다 — 마스터 키를 처음
    만들 때 crypto_utils가 DB를 따로 읽기 때문이다."""
    enc = crypto_utils.encrypt_api_key
    out: dict = {"llm": [], "naver_api": None, "searchad": None}
    for item in secrets.get("llm") or []:
        if item.get("vendor") and item.get("api_key"):
            out["llm"].append({
                "vendor": item["vendor"], "model_name": item.get("model_name") or "",
                "encrypted_api_key": enc(item["api_key"]), "is_active": int(bool(item.get("is_active", True))),
            })
    n = secrets.get("naver_api")
    if n and n.get("client_id") and n.get("client_secret"):
        out["naver_api"] = (enc(n["client_id"]), enc(n["client_secret"]), int(n.get("daily_call_cap") or 500))
    s = secrets.get("searchad")
    if s and s.get("customer_id") and s.get("api_key") and s.get("secret_key"):
        out["searchad"] = (enc(s["customer_id"]), enc(s["api_key"]), enc(s["secret_key"]))
    return out


def _import_kits(conn, kits: List[dict]) -> str:
    active = {r["name"]: r["id"] for r in conn.execute("select id, name from brand_kit where is_archived = 0")}
    changed, added = [], []
    for kit in kits:
        if not isinstance(kit, dict):
            continue
        name = _clean_name(kit.get("name"))
        values = {k: kit[k] for k in repo.BRAND_KIT_FIELDS if k in kit and k != "name"}
        if isinstance(kit.get("sort_order"), int):
            values["sort_order"] = kit["sort_order"]
        encoded = repo._encode(values, repo._BRAND_KIT_JSON_COLS, repo._BRAND_KIT_BOOL_COLS)
        if name in active:
            if encoded:
                assignments = ", ".join(f"{k} = ?" for k in encoded)
                conn.execute(
                    f"update brand_kit set {assignments}, updated_at = datetime('now') where id = ?",
                    (*encoded.values(), active[name]),
                )
            changed.append(name)
        else:
            cols = ["name", *encoded.keys()]
            cur = conn.execute(
                f"insert into brand_kit ({', '.join(cols)}) values ({', '.join('?' * len(cols))})",
                (name, *encoded.values()),
            )
            active[name] = cur.lastrowid
            added.append(name)
    bits = []
    if changed:
        bits.append("바꿈 " + ", ".join(changed))
    if added:
        bits.append("새로 만듦 " + ", ".join(added))
    return "브랜드 킷: " + (" / ".join(bits) or "파일에 킷 없음")


def _update_single_row(conn, table: str, values: Dict[str, Any]) -> None:
    if not values:
        return
    assignments = ", ".join(f"{k} = ?" for k in values)
    conn.execute(f"insert or ignore into {table} (id) values (1)")
    conn.execute(f"update {table} set {assignments}, updated_at = datetime('now') where id = 1", tuple(values.values()))


def _set_state(conn, values: Dict[str, Any], part: str) -> None:
    for key, value in (values or {}).items():
        if APP_STATE_PARTS.get(key) != part:
            continue
        conn.execute(
            "insert into app_state (key, value) values (?, ?) "
            "on conflict(key) do update set value = excluded.value, updated_at = datetime('now')",
            (key, dumps(value)),
        )


def import_bundle(raw: bytes, parts: List[str], password: Optional[str] = None) -> Dict[str, str]:
    """고른 항목만 이 PC에 반영한다. 반환값은 항목별 결과 문구(+ "backup": 백업 파일 경로)."""
    bundle = read_bundle(raw)
    available = set(bundle.get("parts") or [])
    parts = [p for p in PARTS if p in set(parts) and p in available]
    if not parts:
        raise TransferError("가져올 항목을 하나 이상 고르세요.")
    contents = bundle.get("contents") or {}

    # 키부터 풀어 본다 — 비밀번호가 틀리면 아무것도 바꾸지 않고 멈춘다.
    secrets = enc = None
    if "api_keys" in parts:
        if not password:
            raise TransferError("API 키를 가져오려면 내보낼 때 정한 비밀번호를 입력하세요.")
        secrets = _open(bundle.get("secrets") or {}, password)
        enc = _encrypted_secrets(secrets)

    backup = backup_database()
    result: Dict[str, str] = {}
    with get_conn() as conn:
        conn.execute("begin immediate")

        if enc is not None:
            names = []
            for item in enc["llm"]:
                conn.execute(
                    """
                    insert into llm_settings (vendor, model_name, encrypted_api_key, is_active, updated_at)
                    values (?, ?, ?, ?, datetime('now'))
                    on conflict(vendor) do update set model_name = excluded.model_name,
                        encrypted_api_key = excluded.encrypted_api_key, is_active = excluded.is_active,
                        updated_at = datetime('now')
                    """,
                    (item["vendor"], item["model_name"], item["encrypted_api_key"], item["is_active"]),
                )
                names.append(item["vendor"])
            if enc["naver_api"]:
                conn.execute(
                    """
                    insert into naver_api_settings (id, encrypted_client_id, encrypted_client_secret, daily_call_cap)
                    values (1, ?, ?, ?)
                    on conflict(id) do update set encrypted_client_id = excluded.encrypted_client_id,
                        encrypted_client_secret = excluded.encrypted_client_secret,
                        daily_call_cap = excluded.daily_call_cap, updated_at = datetime('now')
                    """,
                    enc["naver_api"],
                )
                names.append("네이버 API HUB")
            if enc["searchad"]:
                conn.execute(
                    """
                    insert into searchad_settings (id, encrypted_customer_id, encrypted_api_key, encrypted_secret_key)
                    values (1, ?, ?, ?)
                    on conflict(id) do update set encrypted_customer_id = excluded.encrypted_customer_id,
                        encrypted_api_key = excluded.encrypted_api_key,
                        encrypted_secret_key = excluded.encrypted_secret_key, updated_at = datetime('now')
                    """,
                    enc["searchad"],
                )
                names.append("검색광고")
            result["api_keys"] = "API 키: " + (", ".join(names) or "파일에 키 없음")

        if "brand_kits" in parts:
            result["brand_kits"] = _import_kits(conn, contents.get("brand_kits") or [])

        keyed = {r["vendor"] for r in conn.execute("select vendor from llm_settings")}
        if "company" in parts:
            company = contents.get("company") or {}
            profile = company.get("company_profile") or {}
            _update_single_row(conn, "company_profile", repo._encode(
                {k: profile[k] for k in repo.COMPANY_FIELDS if k in profile},
                repo._COMPANY_JSON_COLS, repo._COMPANY_BOOL_COLS,
            ))
            app = {k: v for k, v in (company.get("app_settings") or {}).items() if k in repo.APP_SETTINGS_FIELDS}
            # 이 PC에 키가 없는 벤더로 모델 선택을 바꾸면 생성·사진 분석이 바로 실패하므로 그 값은 두고 간다.
            skipped = [k for k in ("default_generation_vendor", "vision_vendor") if app.get(k) and app[k] not in keyed]
            for k in skipped:
                app.pop(k)
            _update_single_row(conn, "app_settings", repo._encode(
                app, repo._APP_SETTINGS_JSON_COLS, repo._APP_SETTINGS_BOOL_COLS,
            ))
            _set_state(conn, company.get("app_state"), "company")
            note = " (이 PC에 키가 없는 모델 선택은 그대로 둠)" if skipped else ""
            result["company"] = f"회사 공통·앱 설정을 바꿨습니다{note}."

        if secrets is not None:
            # 키만 가져오고 이 PC에 '기본 생성 모델'이 아직 없으면, 보낸 PC의 선택(없으면 첫 벤더)을 쓴다.
            row = conn.execute("select default_generation_vendor from app_settings where id = 1").fetchone()
            if not (row and row[0]):
                sent = secrets.get("default_generation_vendor")
                vendors = [i["vendor"] for i in enc["llm"]]
                choice = sent if sent in vendors else (vendors[0] if vendors else None)
                if choice:
                    _update_single_row(conn, "app_settings", {"default_generation_vendor": choice})

        if "cost_settings" in parts:
            cost = contents.get("cost_settings") or {}
            count = 0
            for p in cost.get("model_prices") or []:
                try:
                    vendor, model = str(p["vendor"]).strip(), str(p["model"]).strip()
                    inp, out = float(p["input_per_mtok"]), float(p["output_per_mtok"])
                    cached = None if p.get("cached_input_per_mtok") is None else float(p["cached_input_per_mtok"])
                except (KeyError, TypeError, ValueError):
                    continue
                if not vendor or not model or min(inp, out, cached or 0) < 0:
                    continue
                conn.execute(
                    """
                    insert into model_prices (vendor, model, input_per_mtok, output_per_mtok, cached_input_per_mtok)
                    values (?, ?, ?, ?, ?)
                    on conflict (vendor, model) do update set input_per_mtok = excluded.input_per_mtok,
                        output_per_mtok = excluded.output_per_mtok,
                        cached_input_per_mtok = excluded.cached_input_per_mtok, updated_at = datetime('now')
                    """,
                    (vendor, model, inp, out, cached),
                )
                # 이 PC의 '단가 미등록' 기록도 받은 단가로 채운다 (⚙️ 설정에서 단가를 저장할 때와 같음).
                repo.backfill_unpriced_usage(conn, vendor, model)
                count += 1
            _set_state(conn, cost.get("app_state"), "cost_settings")
            result["cost_settings"] = f"AI 단가 {count}개와 환율·예산을 반영했습니다."

        if "keyword_cache" in parts:
            rows = [r for r in contents.get("keyword_cache") or []
                    if isinstance(r, dict) and r.get("keyword") and r.get("metric") and r.get("value") is not None]
            for r in rows:
                # 더 최근에 잰 값이 이 PC에 있으면 그대로 둔다.
                conn.execute(
                    """
                    insert into keyword_cache (keyword, metric, value, fetched_at) values (?, ?, ?, coalesce(?, datetime('now')))
                    on conflict(keyword, metric) do update set value = excluded.value, fetched_at = excluded.fetched_at
                    where excluded.fetched_at > keyword_cache.fetched_at
                    """,
                    (r["keyword"], r["metric"], str(r["value"]), r.get("fetched_at")),
                )
            result["keyword_cache"] = f"키워드 측정값 {len(rows):,}건을 반영했습니다."

        if "title_history" in parts:
            have = {r[0] for r in conn.execute("select title from title_history")}
            rows = sorted(
                (r for r in contents.get("title_history") or [] if isinstance(r, dict) and (r.get("title") or "").strip()),
                key=lambda r: r.get("created_at") or "",
            )
            added = 0
            for r in rows:
                title = r["title"].strip()
                if title in have:
                    continue
                conn.execute(
                    "insert into title_history (campaign_id, title, created_at) values (null, ?, coalesce(?, datetime('now')))",
                    (title, r.get("created_at")),
                )
                have.add(title)
                added += 1
            result["title_history"] = f"제목 이력 {added:,}건을 더했습니다."

    if backup:
        result["backup"] = str(backup)
    return result
