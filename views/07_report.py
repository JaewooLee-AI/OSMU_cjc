"""📋 구축 보고서 — HANDOFF.md를 앱 안에서 그대로 보여줍니다.

편집기 폰트 설정이 깨져 한글이 제대로 안 보이는 상황에서도 보고 내용을 읽을 수 있어야 해서,
파일 사본이 아니라 **같은 파일을 브라우저에서 렌더링**합니다. 브라우저는 IDE와 폰트 스택이
별개라, 편집기 쪽 한글 표시가 깨져도 여기서는 정상적으로 보입니다.

내용을 고칠 때는 이 파일이 아니라 HANDOFF.md를 고치세요. 여기서는 읽기만 합니다.
"""
from __future__ import annotations

from pathlib import Path

import streamlit as st

HANDOFF_PATH = Path(__file__).resolve().parent.parent / "HANDOFF.md"

st.title("구축 보고서")

if not HANDOFF_PATH.exists():
    st.error(f"보고서 파일을 찾을 수 없습니다: {HANDOFF_PATH}")
    st.stop()

report = HANDOFF_PATH.read_text(encoding="utf-8")

st.info(
    "편집기에서 한글이 깨져 보이면 이 페이지에서 읽으세요. "
    "브라우저는 IDE와 폰트 스택이 달라 영향을 받지 않습니다.",
    icon="🈳",
)

col1, col2 = st.columns([1, 3])
with col1:
    st.download_button(
        "⬇️ 보고서 내려받기",
        data=report,
        file_name="더스티치_OSMU_구축보고.md",
        mime="text/markdown",
        width="stretch",
    )
with col2:
    st.caption(f"원본 파일: `{HANDOFF_PATH}`")

st.divider()

# 제목 줄(`# ...`)은 위의 st.title과 중복되므로 걷어내고 본문만 렌더링합니다.
body = report.split("\n", 1)[1] if report.startswith("# ") else report
st.markdown(body)

st.divider()
with st.expander("📄 원문(Markdown) 그대로 보기"):
    st.code(report, language="markdown")
