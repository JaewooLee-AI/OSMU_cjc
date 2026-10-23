"""pytest 공통 설정 — 실제 data/ 폴더를 절대 건드리지 않도록 임시 데이터 폴더를 씁니다.

core.db는 import할 때 OSMU_DATA_DIR을 읽으므로, core를 import하기 전에 환경 변수를 넣습니다.
시험마다 DB 파일을 지우고 다시 만들어(`fresh_db`) 서로 영향을 주지 않게 합니다.
LLM은 부르지 않습니다 — 실제 호출 시험은 tests/live_gemini_check.py(수동 실행)에 있습니다.
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

_TMP = Path(tempfile.mkdtemp(prefix="osmu_test_"))
os.environ["OSMU_DATA_DIR"] = str(_TMP)
os.environ.setdefault("ENCRYPTION_MASTER_KEY_BASE64", "")

import pytest  # noqa: E402

from core import db  # noqa: E402

assert str(db.DATA_DIR) == str(_TMP), "시험이 실제 데이터 폴더를 쓰려고 합니다"


@pytest.fixture(autouse=True)
def fresh_db():
    for suffix in ("", "-wal", "-shm"):
        path = Path(str(db.DB_PATH) + suffix)
        if path.exists():
            path.unlink()
    db._initialized = False
    db.init_db()
    yield
