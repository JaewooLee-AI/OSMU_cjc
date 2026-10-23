"""각 화면이 예외 없이 만들어지는지(컨트롤 트리 생성) 확인합니다.

실제 창은 띄우지 않습니다. 화면의 build()는 페이지 객체를 이벤트 처리기에서만 쓰므로,
여기서는 아무 일도 하지 않는 가짜 페이지를 넘깁니다. 클릭 동작은 로컬에서 앱으로 확인합니다.
"""
from __future__ import annotations

from datetime import date, timedelta

import flet as ft
import pytest

from core import repo
from core.brand_seed import seed_if_empty
from flet_app.state import AppState


class _FakeServices:
    def register_service(self, service):
        pass


class FakePage:
    _services = _FakeServices()
    _naver_publish_poll_generation = 0

    def __getattr__(self, name):
        return lambda *a, **k: None


def _walk(control, seen=None):
    """컨트롤 트리를 끝까지 돌아 속성 접근 오류를 드러냅니다."""
    seen = seen if seen is not None else set()
    if control is None or id(control) in seen:
        return 0
    seen.add(id(control))
    n = 1
    for attr in ("content", "controls", "tabs", "rows", "cells", "spans", "title", "actions"):
        child = getattr(control, attr, None)
        if isinstance(child, list):
            for c in child:
                if isinstance(c, ft.BaseControl):
                    n += _walk(c, seen)
        elif isinstance(child, ft.BaseControl):
            n += _walk(child, seen)
    return n


@pytest.fixture(autouse=True)
def page_context():
    """복사 버튼(ft.CopyToClipboard)은 만들 때 현재 페이지를 찾으므로 가짜 페이지를 넣어 둡니다."""
    from flet.controls import context as flet_context
    token = flet_context._context_page.set(FakePage())
    yield
    flet_context._context_page.reset(token)


@pytest.fixture
def populated():
    seed_if_empty()
    a = repo.insert_campaign(source_type="manual", status="awaiting_media", memo="가발 세척")
    b = repo.insert_campaign(source_type="manual", status="awaiting_media", memo="가발 보관")
    repo.update_campaign(b["id"], status="draft", title="보관법", content="첫 문단입니다.\n둘째 문단입니다.",
                         guardrail_report={"compliance_pass": True, "score": 95,
                                           "cost": {"calls": 3, "cost_krw": 12.3, "cost_usd": 0.0088,
                                                    "unpriced_calls": 0, "input_tokens": 1, "output_tokens": 1}})
    c = repo.insert_campaign(source_type="manual", status="awaiting_media", memo="게시됨")
    repo.mark_published(c["id"], "https://blog.naver.com/cjc/223000000009")
    repo.save_model_price("google", "gemini-3.8-flash", 0.3, 2.5)
    repo.log_usage("text", vendor="google", model="gemini-3.8-flash", est_input_tokens=1000, est_output_tokens=300)
    repo.log_usage("text", vendor="anthropic", model="claude-x", est_input_tokens=1000)
    repo.set_monthly_budget_krw(1)
    return {"a": a, "b": b, "c": c}


def test_dashboard_builds(populated):
    from flet_app.views import dashboard_view
    assert _walk(dashboard_view.build(FakePage(), AppState())) > 20


def test_settings_builds(populated):
    from flet_app.views import settings_view
    assert _walk(settings_view.build(FakePage(), AppState())) > 50


def test_naver_publish_builds(populated):
    from flet_app.views import naver_publish_view
    assert _walk(naver_publish_view.build(FakePage(), AppState())) > 10


@pytest.mark.parametrize("which", ["a", "b", "c"])
def test_workbench_builds_each_campaign(populated, which):
    from flet_app.views import workbench_view
    state = AppState(pending_workbench_campaign_id=populated[which]["id"])
    assert _walk(workbench_view.build(FakePage(), state)) > 20


def test_calendar_builds_month_and_week(populated):
    from flet_app.views import calendar_view
    repo.move_campaign_date(populated["a"]["id"], date.today().isoformat())
    repo.move_campaign_date(populated["b"]["id"], (date.today() - timedelta(days=3)).isoformat())
    repo.add_topic("주제 1", planned_date=date.today().isoformat())
    repo.add_topic("날짜 미정 주제")
    repo.add_rule(2, title="수요 팁")
    repo.apply_rules()
    root = calendar_view.build(FakePage(), AppState())
    assert _walk(root) > 100


def test_formatted_post_renders_in_workbench_simulator_and_publish(populated):
    from ai_workers import formatting
    from tests.test_v2_formatting import DRAFT
    from flet_app.views import naver_publish_view, workbench_view
    import flet_app.simulators as sim

    plain, items = formatting.extract(DRAFT)
    fmt = formatting.finalize(plain, items, "rich", "info")
    cid = populated["b"]["id"]
    repo.update_campaign(cid, content=plain, content_format=fmt, status="ready_to_publish")
    campaign = repo.get_campaign(cid)
    for mobile in (False, True):
        assert _walk(sim.render("naver", campaign, is_mobile=mobile, brand_kit=repo.get_campaign_brand_kit(campaign))) > 30
    assert _walk(workbench_view.build(FakePage(), AppState(pending_workbench_campaign_id=cid))) > 60
    assert _walk(naver_publish_view.build(FakePage(), AppState())) > 20


def test_brand_kit_view_builds_with_design_fields(populated):
    from flet_app.views import brand_kit_view
    assert _walk(brand_kit_view.build(FakePage(), AppState())) > 50
