"""요청 2(캘린더·주제·반복 규칙·자동 작성 예약) 시험."""
from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest

from ai_workers import auto_scheduler
from core import repo
from flet_app.views.calendar_view import month_weeks, week_of


def _campaign(**fields):
    c = repo.insert_campaign(source_type="manual", status="awaiting_media", memo="가발 세척법")
    if fields:
        repo.update_campaign(c["id"], **fields)
    return repo.get_campaign(c["id"])


def test_schedule_validation():
    c = _campaign()
    saved = repo.set_campaign_schedule(c["id"], "2026-11-03", " 관리 시리즈 ", "2026-11-02 14:30")
    assert saved == {"scheduled_date": "2026-11-03", "series_name": "관리 시리즈", "auto_generate_at": "2026-11-02 14:30"}
    saved = repo.set_campaign_schedule(c["id"], "11월 3일", "", "2026-11-02")
    assert saved["scheduled_date"] is None
    assert saved["auto_generate_at"] == "2026-11-02 09:00"  # 날짜만 → 오전 9시
    assert repo.set_campaign_schedule(c["id"], "2026-02-30")["scheduled_date"] is None


def test_scheduled_range_kit_filter_and_overdue():
    kit2 = repo.create_brand_kit("두피")
    a = _campaign(scheduled_date="2026-10-05")
    b = _campaign(scheduled_date="2026-10-20", brand_kit_id=kit2)
    _campaign(scheduled_date="2026-11-20")
    got = repo.scheduled_campaigns("2026-10-01", "2026-10-31")
    assert [c["id"] for c in got] == [a["id"], b["id"]]
    assert [c["id"] for c in repo.scheduled_campaigns("2026-10-01", "2026-10-31", kit2)] == [b["id"]]
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    late = _campaign(scheduled_date=yesterday)
    done = _campaign(scheduled_date=yesterday, status="published")
    assert repo.is_overdue(late) and not repo.is_overdue(done)
    assert repo.overdue_count() >= 1


def test_unscheduled_lists_only_unpublished_without_date():
    a = _campaign()
    _campaign(scheduled_date="2026-10-05")
    _campaign(status="published")
    assert [c["id"] for c in repo.unscheduled_campaigns()] == [a["id"]]


def test_topic_to_campaign_carries_fields_and_is_idempotent():
    kit2 = repo.create_brand_kit("창업")
    tid = repo.add_topic("가맹 안내", memo="5기 모집", brand_kit_id=kit2, content_mode="seo",
                         planned_date="2026-11-10", series_name="창업 시리즈")
    c = repo.topic_to_campaign(tid)
    assert c["memo"] == "가맹 안내\n5기 모집"
    assert c["brand_kit_id"] == kit2 and c["content_mode"] == "seo"
    assert c["scheduled_date"] == "2026-11-10" and c["series_name"] == "창업 시리즈"
    assert repo.topic_to_campaign(tid)["id"] == c["id"]
    assert repo.list_topics(include_linked=False) == []


def test_add_topic_needs_title_or_memo():
    with pytest.raises(ValueError):
        repo.add_topic("  ", memo=" ")


def test_rules_make_four_weeks_once():
    rid = repo.add_rule(1, title="화요 팁", content_mode="balanced")
    start = date(2026, 10, 23)  # 금요일
    assert repo.rule_dates(1, start) == ["2026-10-27", "2026-11-03", "2026-11-10", "2026-11-17"]
    assert repo.apply_rules(start) == 4
    assert repo.apply_rules(start) == 0  # 두 번 불러도 겹치지 않음
    slots = repo.list_topics()
    assert {t["planned_date"] for t in slots} == set(repo.rule_dates(1, start))
    assert all(t["title"] == "화요 팁" and t["rule_id"] == rid for t in slots)
    # 하나를 글로 만든 뒤 규칙을 지우면, 글로 만든 자리는 남고 나머지는 지워짐
    repo.topic_to_campaign(slots[0]["id"])
    assert repo.delete_rule(rid) == 3
    left = repo.list_topics()
    assert len(left) == 1 and left[0]["rule_id"] is None


def test_rule_on_today_includes_today():
    today = date(2026, 10, 27)  # 화요일
    assert repo.rule_dates(1, today)[0] == "2026-10-27"


def test_month_and_week_grid():
    weeks = month_weeks(2026, 10)
    assert weeks[0][0] == date(2026, 9, 28) and weeks[0][0].weekday() == 0
    assert weeks[-1][-1] >= date(2026, 10, 31)
    assert week_of(date(2026, 10, 23)) == [date(2026, 10, 19) + timedelta(days=i) for i in range(7)]


def test_move_campaign_and_topic_dates():
    c = _campaign(scheduled_date="2026-10-05")
    repo.move_campaign_date(c["id"], "2026-10-06")
    assert repo.get_campaign(c["id"])["scheduled_date"] == "2026-10-06"
    tid = repo.add_topic("주제")
    repo.update_topic(tid, planned_date="2026-10-07")
    assert repo.get_topic(tid)["planned_date"] == "2026-10-07"


# --- 자동 작성 예약 -------------------------------------------------------------

def test_due_auto_generation_filters():
    now = datetime(2026, 10, 23, 10, 0)
    due = _campaign(auto_generate_at="2026-10-23 09:59")
    _campaign(auto_generate_at="2026-10-23 10:01")  # 아직
    _campaign(auto_generate_at="2026-10-23 09:00", content="이미 초안", status="draft")
    _campaign(auto_generate_at="2026-10-23 09:00", status="processing")
    assert [c["id"] for c in repo.due_auto_generation(now)] == [due["id"]]


def test_run_due_generates_and_clears_schedule():
    now = datetime(2026, 10, 23, 10, 0)
    c = _campaign(auto_generate_at="2026-10-23 09:00")
    called = []

    def fake_generate(cid):
        called.append(cid)
        repo.update_campaign(cid, status="draft", content="본문", guardrail_report={"score": 90})

    notes = []
    results = auto_scheduler.run_due(now, generate=fake_generate, on_done=lambda camp, err: notes.append(err))
    assert called == [c["id"]] and results[0]["ok"] and notes == [None]
    got = repo.get_campaign(c["id"])
    assert got["auto_generate_at"] is None and got["status"] == "draft"
    assert got["guardrail_report"]["auto_generated"]["scheduled"] == "2026-10-23 09:00"
    assert auto_scheduler.run_due(now, generate=fake_generate) == []  # 다시 돌지 않음


def test_run_due_without_memo_fails_visibly_once():
    now = datetime(2026, 10, 23, 10, 0)
    c = repo.insert_campaign(source_type="manual", status="awaiting_media")
    repo.update_campaign(c["id"], auto_generate_at="2026-10-23 09:00")
    results = auto_scheduler.run_due(now, generate=lambda cid: pytest.fail("재료 없이 생성하면 안 됨"))
    assert results[0]["ok"] is False
    got = repo.get_campaign(c["id"])
    assert got["status"] == "failed" and "메모" in got["publish_error"] and got["auto_generate_at"] is None


def test_run_due_generation_error_is_recorded_not_retried():
    now = datetime(2026, 10, 23, 10, 0)
    c = _campaign(auto_generate_at="2026-10-23 09:00")

    def boom(cid):
        repo.update_campaign(cid, status="failed", publish_error="503")
        raise RuntimeError("503 UNAVAILABLE")

    results = auto_scheduler.run_due(now, generate=boom)
    assert results[0]["ok"] is False and "503" in results[0]["error"]
    assert repo.get_campaign(c["id"])["auto_generate_at"] is None
    assert repo.due_auto_generation(now) == []
