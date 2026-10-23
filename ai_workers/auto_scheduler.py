"""예약 시각 자동 작성 (요청 2 — 📅 캘린더).

워크벤치에서 '자동 작성 예약'을 켜 둔 글을, 예약 시각이 지나면 run_pipeline으로 초안까지
만듭니다. 이 앱은 서버 없이 PC에서 도는 데스크톱 앱이라 **앱이 켜져 있는 동안만** 돕니다:
flet_app/main.py가 시작할 때 백그라운드 스레드로 띄우고 1분마다 확인합니다. 앱이 꺼져 있던
동안 지난 예약은 다음에 켤 때 첫 확인에서 처리합니다.

- 발행은 하지 않습니다. 결과는 '초안 완료'로 남고, 검수 결과를 사람이 보고 게시합니다.
- 한 번 시도한 예약은 성공·실패와 관계없이 지웁니다 — 실패한 글을 1분마다 다시 돌려 API 비용이
  계속 나가지 않게. 실패 이유는 publish_error에 남아 대시보드 '실패한 작업'에 보입니다.
- 한 번에 한 글씩 차례로 만듭니다(동시에 여러 글을 돌리면 벤더가 503으로 거절하기 쉬움).
"""
from __future__ import annotations

import threading
from datetime import datetime
from typing import Callable, List, Optional

from core import repo

CHECK_INTERVAL_SECONDS = 60

_lock = threading.Lock()
_stop = threading.Event()
_thread: Optional[threading.Thread] = None


def run_due(
    now: Optional[datetime] = None,
    generate: Optional[Callable[[str], object]] = None,
    on_done: Optional[Callable[[dict, Optional[str]], None]] = None,
) -> List[dict]:
    """예약 시각이 지난 글을 차례로 생성합니다. 시도한 글마다 {id, title, ok, error}를 돌려줍니다.

    `generate`는 시험용으로 바꿔 끼울 수 있습니다(기본: content_writer.run_pipeline).
    `on_done(campaign, error)`는 글 하나가 끝날 때마다 불립니다(화면 알림용).
    """
    if generate is None:
        from ai_workers.content_writer import run_pipeline

        def generate(campaign_id: str):
            return run_pipeline(campaign_id)

    results: List[dict] = []
    if not _lock.acquire(blocking=False):
        return results  # 이전 확인이 아직 생성 중
    try:
        for campaign in repo.due_auto_generation(now):
            cid = campaign["id"]
            stamp = campaign.get("auto_generate_at")
            # 먼저 지웁니다 — 생성 도중 앱이 꺼져도 다음 실행에서 같은 글을 다시 돌리지 않게.
            repo.update_campaign(cid, auto_generate_at=None)
            error: Optional[str] = None
            if not ((campaign.get("memo") or "").strip() or campaign.get("source_url")):
                error = f"자동 작성 예약({stamp})을 실행하지 못했습니다 — 메모나 뉴스 기사가 없어 쓸 재료가 없습니다."
                repo.update_campaign(cid, status="failed", publish_error=error)
            else:
                try:
                    generate(cid)
                    fresh = repo.get_campaign(cid) or {}
                    report = dict(fresh.get("guardrail_report") or {})
                    report["auto_generated"] = {"scheduled": stamp, "ran_at": datetime.now().strftime("%Y-%m-%d %H:%M")}
                    repo.update_campaign(cid, guardrail_report=report)
                except repo.CampaignBusyError as exc:
                    error = str(exc)
                except Exception as exc:  # noqa: BLE001 — run_pipeline이 이미 failed로 기록함
                    error = f"자동 작성 예약({stamp}) 실패: {exc}"
                    repo.update_campaign(cid, publish_error=error)
            result = {"id": cid, "title": campaign.get("title") or (campaign.get("memo") or "")[:30],
                      "ok": error is None, "error": error}
            results.append(result)
            if on_done:
                try:
                    on_done(repo.get_campaign(cid) or campaign, error)
                except Exception:  # noqa: BLE001 — 알림 실패가 다음 글을 막으면 안 됨
                    pass
    finally:
        _lock.release()
    return results


def start(on_done: Optional[Callable[[dict, Optional[str]], None]] = None) -> None:
    """앱 시작 시 한 번 부릅니다. 이미 돌고 있으면 아무것도 하지 않습니다."""
    global _thread
    if _thread and _thread.is_alive():
        return
    _stop.clear()

    def _loop() -> None:
        while not _stop.is_set():
            try:
                run_due(on_done=on_done)
            except Exception as exc:  # noqa: BLE001 — 확인 루프는 죽지 않게
                print(f"[auto_scheduler] 확인 중 오류: {exc}")
            _stop.wait(CHECK_INTERVAL_SECONDS)

    _thread = threading.Thread(target=_loop, name="auto-scheduler", daemon=True)
    _thread.start()


def stop() -> None:
    _stop.set()
