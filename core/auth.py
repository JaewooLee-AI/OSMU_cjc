"""Lightweight password gate for the internal admin engine.

The Streamlit backend is never exposed to end-users (only marketers/ops
with the shared admin password), so a single ADMIN_PASSWORD env var is
sufficient here rather than full Supabase Auth/JWT plumbing.
"""
import os

import streamlit as st


def require_login() -> None:
    if st.session_state.get("osmu_authenticated"):
        return

    expected = os.environ.get("ADMIN_PASSWORD")
    if not expected:
        # No password configured (e.g. local dev) -> skip the gate.
        st.session_state["osmu_authenticated"] = True
        return

    st.markdown("<div class='osmu-brand'>OSMU Admin Engine</div>", unsafe_allow_html=True)
    with st.form("osmu_login"):
        password = st.text_input("관리자 비밀번호", type="password")
        submitted = st.form_submit_button("로그인")
    if submitted:
        if password == expected:
            st.session_state["osmu_authenticated"] = True
            st.rerun()
        else:
            st.error("비밀번호가 올바르지 않습니다.")
    st.stop()
