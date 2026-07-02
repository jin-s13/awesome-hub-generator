"""Network Proxy settings tab for the Streamlit config panel."""

import streamlit as st
from webui.i18n import t


def render(_env_values: dict, config_values: dict):
    """Render the Network Proxy tab."""
    flat = config_values

    # ---- Global Enable ----
    st.markdown(
        f'<p class="section-title">🌐 {t("proxy_title")}</p>',
        unsafe_allow_html=True,
    )

    st.toggle(
        t("proxy_enable_label"),
        value=flat.get("proxy_enabled", False),
        key="proxy_enabled",
    )

    # ---- Proxy URL ----
    st.text_input(
        t("proxy_url_label"),
        value=flat.get("proxy_url", ""),
        key="proxy_url",
        placeholder="http://127.0.0.1:7890",
        help=t("proxy_url_help"),
    )

    # ---- No Proxy (textarea, one per line) ----
    no_proxy_val = flat.get("proxy_no_proxy", "localhost,127.0.0.1")
    # Convert comma-separated to newline-separated for display
    if "," in no_proxy_val and "\n" not in no_proxy_val:
        no_proxy_val = no_proxy_val.replace(",", "\n")
    st.text_area(
        t("proxy_no_proxy_label"),
        value=no_proxy_val,
        key="proxy_no_proxy",
        help=t("proxy_no_proxy_help"),
        height=100,
        placeholder="localhost\n127.0.0.1\n192.168.1.0/24",
    )

    st.divider()

    # ---- Per-service toggles ----
    st.markdown(
        f'<p class="section-title">🎯 {t("proxy_scope_title")}</p>',
        unsafe_allow_html=True,
    )
    st.markdown(
        f'<p class="hint-text">{t("proxy_scope_hint")}</p>',
        unsafe_allow_html=True,
    )

    col1, col2 = st.columns(2)
    with col1:
        st.toggle(
            t("proxy_arxiv_label"),
            value=flat.get("proxy_arxiv", True),
            key="proxy_arxiv",
            help=t("proxy_arxiv_help"),
        )
        st.toggle(
            t("proxy_openalex_label"),
            value=flat.get("proxy_openalex", False),
            key="proxy_openalex",
            help=t("proxy_openalex_help"),
        )
        st.toggle(
            t("proxy_semantic_scholar_label"),
            value=flat.get("proxy_semantic_scholar", False),
            key="proxy_semantic_scholar",
            help=t("proxy_semantic_scholar_help"),
        )

    with col2:
        st.toggle(
            t("proxy_llm_api_label"),
            value=flat.get("proxy_llm_api", False),
            key="proxy_llm_api",
            help=t("proxy_llm_api_help"),
        )
        st.toggle(
            t("proxy_notifications_label"),
            value=flat.get("proxy_notifications", False),
            key="proxy_notifications",
            help=t("proxy_notifications_help"),
        )
        st.toggle(
            t("proxy_update_check_label"),
            value=flat.get("proxy_update_check", False),
            key="proxy_update_check",
            help=t("proxy_update_check_help"),
        )


def collect(_env_values: dict, _config_values: dict) -> dict:
    """从 session_state 收集当前值，返回 config 更新字典。"""
    # Convert newline-separated no_proxy back to comma-separated for storage
    raw_no_proxy = st.session_state.get("proxy_no_proxy", "localhost,127.0.0.1")
    no_proxy = ",".join(
        line.strip() for line in raw_no_proxy.splitlines() if line.strip()
    )

    return {
        "proxy_enabled": st.session_state.get("proxy_enabled", False),
        "proxy_url": st.session_state.get("proxy_url", ""),
        "proxy_no_proxy": no_proxy,
        "proxy_arxiv": st.session_state.get("proxy_arxiv", True),
        "proxy_openalex": st.session_state.get("proxy_openalex", False),
        "proxy_semantic_scholar": st.session_state.get("proxy_semantic_scholar", False),
        "proxy_llm_api": st.session_state.get("proxy_llm_api", False),
        "proxy_notifications": st.session_state.get("proxy_notifications", False),
        "proxy_update_check": st.session_state.get("proxy_update_check", False),
    }
