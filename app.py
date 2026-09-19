"""씨제이씨협동조합 OSMU 워크벤치 — entry point.

Folds OSMU_admin (Streamlit engine + Supabase + polling worker) and OSMU_web
(Next.js editor + channel simulators) into one Streamlit process backed by a
local SQLite file. The three-tier split existed to work around Vercel's
10-second serverless timeout; with one process there is no timeout to work
around, so the queue, the service-role keys, the Realtime subscriptions and
the TTL cleanup cron all disappear along with it.
"""
from __future__ import annotations

import streamlit as st
from dotenv import load_dotenv

from core import repo
from core.auth import require_login
from core.brand_seed import seed_if_empty
from core.db import init_db
from core.theme import inject_theme, render_sidebar_brand

load_dotenv()

st.set_page_config(
    page_title="씨제이씨협동조합 OSMU 워크벤치",
    page_icon="🧵",
    layout="wide",
    initial_sidebar_state="expanded",
)

init_db()
seeded = seed_if_empty()

inject_theme()
require_login()

brand_kit = repo.get_brand_kit()
render_sidebar_brand(brand_kit)

if seeded:
    st.sidebar.success("회사 자료 기반 Brand Kit을 초기 세팅했습니다.")

# NOTE: these live in views/, not pages/. Streamlit auto-discovers a directory
# literally named `pages/` next to the entrypoint and builds its own navigation
# from it — which raced st.navigation on a cold deep link (opening
# http://…/report directly in a fresh server showed the auto-discovered,
# untranslated sidebar instead of this one). Renaming the directory removes the
# ambiguity entirely; st.navigation is then the only source of routing.
pages = [
    st.Page("views/01_dashboard.py", title="대시보드", icon="📊", default=True),
    st.Page("views/02_workbench.py", title="워크벤치", icon="✍️"),
    st.Page("views/03_news_curation.py", title="뉴스 큐레이션", icon="📰"),
    st.Page("views/04_brand_kit.py", title="브랜드 킷", icon="🧵"),
    st.Page("views/05_naver_publish.py", title="네이버 게시", icon="🚀"),
    st.Page("views/06_settings.py", title="설정 · 토큰", icon="⚙️"),
    st.Page("views/07_report.py", title="구축 보고서", icon="📋"),
]

st.navigation(pages).run()
