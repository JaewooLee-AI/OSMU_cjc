"""요청 1(대시보드·게시 기록)과 요청 3(비용 환산)의 데이터 계층 시험."""
from __future__ import annotations

from datetime import datetime

import pytest

from ai_workers.naver_paste_worker import extract_post_url
from core import repo


def _campaign(**fields):
    c = repo.insert_campaign(source_type="manual", status="awaiting_media", memo="메모")
    if fields:
        repo.update_campaign(c["id"], **fields)
    return repo.get_campaign(c["id"])


# --- 요청 1 ---------------------------------------------------------------

def test_mark_published_records_time_and_url():
    c = _campaign(status="ready_to_publish")
    repo.mark_published(c["id"], " blog.naver.com/cjc/223000000001 ")
    got = repo.get_campaign(c["id"])
    assert got["status"] == "published"
    assert got["published_url"] == "https://blog.naver.com/cjc/223000000001"
    assert datetime.strptime(got["published_at"], "%Y-%m-%d %H:%M:%S")


def test_mark_published_without_url_keeps_previous_url():
    c = _campaign(status="ready_to_publish", published_url="https://blog.naver.com/cjc/1234567")
    repo.mark_published(c["id"], "")
    assert repo.get_campaign(c["id"])["published_url"] == "https://blog.naver.com/cjc/1234567"


def test_set_published_url_validates():
    c = _campaign(status="published")
    assert repo.set_published_url(c["id"], "그냥 글자") is False
    assert repo.set_published_url(c["id"], "https://blog.naver.com/cjc/22") is True
    assert repo.set_published_url(c["id"], "") is True
    assert repo.get_campaign(c["id"])["published_url"] is None


@pytest.mark.parametrize("url,expected", [
    ("https://blog.naver.com/cjc01/223456789012", "https://blog.naver.com/cjc01/223456789012"),
    ("https://m.blog.naver.com/cjc01/223456789012?x=1", "https://blog.naver.com/cjc01/223456789012"),
    ("https://blog.naver.com/PostView.naver?blogId=cjc01&logNo=223456789012", "https://blog.naver.com/cjc01/223456789012"),
    ("https://blog.naver.com/cjc01?Redirect=Write", None),
    ("https://blog.naver.com/PostWriteForm.naver?blogId=cjc01", None),
    ("https://blog.naver.com/someoneelse/223456789012", None),
    ("https://blog.naver.com/cjc012/223456789012", None),
])
def test_extract_post_url(url, expected):
    assert extract_post_url(url, "cjc01") == expected


def test_delete_campaign_unlinks_topic():
    tid = repo.add_topic("가발 세척법")
    c = repo.topic_to_campaign(tid)
    assert repo.get_topic(tid)["campaign_id"] == c["id"]
    repo.delete_campaign(c["id"])
    assert repo.get_topic(tid)["campaign_id"] is None


def test_reset_unlinks_topics():
    tid = repo.add_topic("가발 보관법")
    repo.topic_to_campaign(tid)
    repo.reset_generated_content()
    assert repo.get_topic(tid)["campaign_id"] is None


# --- 요청 3 ---------------------------------------------------------------

def test_unpriced_calls_are_not_zero():
    repo.log_usage("text", vendor="google", model="gemini-x", est_input_tokens=1000, est_output_tokens=500)
    total = repo.cost_all_time()
    assert total["unpriced_calls"] == 1
    assert total["cost_usd"] == 0
    assert repo.recent_usage(1)[0]["cost_usd"] is None


def test_cost_computed_at_call_time_and_not_rewritten():
    repo.save_model_price("google", "gemini-x", 1.0, 4.0)
    repo.log_usage("text", vendor="google", model="gemini-x", est_input_tokens=1_000_000, est_output_tokens=500_000)
    assert repo.recent_usage(1)[0]["cost_usd"] == pytest.approx(1.0 + 2.0)
    repo.save_model_price("google", "gemini-x", 10.0, 40.0)  # 단가 인상
    assert repo.recent_usage(1)[0]["cost_usd"] == pytest.approx(3.0)  # 과거 금액은 그대로
    repo.log_usage("text", vendor="google", model="gemini-x", est_input_tokens=1_000_000)
    assert repo.recent_usage(1)[0]["cost_usd"] == pytest.approx(10.0)


def test_first_price_backfills_only_unpriced_rows():
    repo.log_usage("text", vendor="openai", model="m", est_input_tokens=2_000_000, est_output_tokens=0)
    repo.log_usage("text", vendor="openai", model="other", est_input_tokens=1_000_000)
    filled = repo.save_model_price("openai", "m", 0.5, 2.0)
    assert filled == 1
    by = {(r["vendor"], r["model"]): r for r in repo.cost_by_model()}
    assert by[("openai", "m")]["cost_usd"] == pytest.approx(1.0)
    assert by[("openai", "other")]["unpriced_calls"] == 1


def test_cached_input_rate():
    repo.save_model_price("anthropic", "c", 3.0, 15.0, 0.3)
    repo.log_usage("text", vendor="anthropic", model="c", est_input_tokens=1_000_000,
                   cached_input_tokens=800_000, est_output_tokens=0)
    # 20만 일반 × $3 + 80만 캐시 × $0.3 = 0.6 + 0.24
    assert repo.recent_usage(1)[0]["cost_usd"] == pytest.approx(0.84)
    repo.save_model_price("anthropic", "d", 3.0, 15.0)  # 캐시 단가 없음 → 일반 단가
    repo.log_usage("text", vendor="anthropic", model="d", est_input_tokens=1_000_000, cached_input_tokens=800_000)
    assert repo.recent_usage(1)[0]["cost_usd"] == pytest.approx(3.0)


def test_saved_tokens_priced_at_input_rate():
    repo.save_model_price("google", "v", 2.0, 8.0)
    repo.log_usage("vision-saving", vendor="google", model="v", est_saved_tokens=500_000)
    assert repo.cost_all_time()["saved_cost_usd"] == pytest.approx(1.0)


def test_usage_scope_attributes_campaign():
    c = _campaign()
    start = repo.last_usage_id()
    repo.save_model_price("google", "g", 1.0, 1.0)
    with repo.usage_scope(c["id"]):
        repo.log_usage("text", vendor="google", model="g", est_input_tokens=1_000_000)
    repo.log_usage("text", vendor="google", model="g", est_input_tokens=1_000_000)  # 범위 밖
    assert repo.cost_for_campaign(c["id"], since_id=start)["cost_usd"] == pytest.approx(1.0)
    assert repo.cost_for_campaign(c["id"])["calls"] == 1


def test_usage_scope_crosses_thread_pool_via_submit():
    from concurrent.futures import ThreadPoolExecutor
    from ai_workers.content_writer import _submit
    c = _campaign()
    with repo.usage_scope(c["id"]):
        with ThreadPoolExecutor(max_workers=1) as pool:
            _submit(pool, lambda: repo.log_usage("text", vendor="google", model="g", est_input_tokens=10)).result()
    assert repo.cost_for_campaign(c["id"])["calls"] == 1


def test_exchange_rate_and_budget_levels():
    assert repo.get_usd_krw() == repo.DEFAULT_USD_KRW
    repo.set_usd_krw(1000)
    repo.save_model_price("google", "g", 1.0, 0.0)
    repo.log_usage("text", vendor="google", model="g", est_input_tokens=1_000_000)  # $1 = 1,000원
    assert repo.cost_this_month()["cost_krw"] == pytest.approx(1000)
    assert repo.budget_status()["level"] is None and repo.budget_message() is None
    repo.set_monthly_budget_krw(1400)  # 71%
    assert repo.budget_status()["level"] == 70
    repo.set_monthly_budget_krw(1100)  # 91%
    assert repo.budget_status()["level"] == 90
    repo.set_monthly_budget_krw(900)
    assert repo.budget_status()["level"] == 100
    assert "넘었습니다" in repo.budget_message()
    repo.set_monthly_budget_krw(None)
    assert repo.budget_status()["level"] is None
    with pytest.raises(ValueError):
        repo.set_usd_krw(0)


def test_today_month_and_average_per_post():
    repo.save_model_price("google", "g", 1.0, 0.0)
    repo.log_usage("text", vendor="google", model="g", est_input_tokens=1_000_000)
    assert repo.cost_today()["calls"] == 1
    _campaign(status="draft")
    _campaign(status="published")
    _campaign(status="awaiting_media")
    assert repo.generated_post_count() == 2


def test_usage_models_lists_seen_and_registered():
    repo.upsert_llm_setting("google", "gemini-reg", "enc")
    repo.log_usage("text", vendor="openai", model="gpt-seen", est_input_tokens=1)
    names = {(m["vendor"], m["model"]) for m in repo.usage_models()}
    assert {("google", "gemini-reg"), ("openai", "gpt-seen")} <= names
