"""Notifications Configuration tab for the Streamlit config panel."""

import streamlit as st
from webui.i18n import t


def render(env_values: dict, config_values: dict):
    """Render the Notifications configuration tab."""

    flat = config_values

    # ---- Global Toggle ----
    st.markdown(
        f'<p class="hint-text">{t("notif_settings_hint")}</p>',
        unsafe_allow_html=True,
    )

    st.toggle(
        t("enable_notifications"),
        value=flat.get("notifications_enabled", False),
        key="notifications_enabled",
    )

    col1, col2, col3 = st.columns(3)
    with col1:
        st.toggle(
            t("notify_success"), value=flat.get("notify_on_success", True), key="notify_on_success"
        )
    with col2:
        st.toggle(
            t("notify_failure"), value=flat.get("notify_on_failure", True), key="notify_on_failure"
        )
    with col3:
        st.number_input(
            t("top_n_label"),
            min_value=1,
            max_value=50,
            value=flat.get("notification_top_n", 5),
            key="notification_top_n",
        )

    st.toggle(
        t("attach_reports"),
        value=flat.get("notify_attach_reports", False),
        key="notify_attach_reports",
    )

    st.divider()

    # ---- Email ----
    with st.expander(t("email_expander"), expanded=flat.get("notify_email_enabled", False)):
        st.toggle(
            t("enable_email"),
            value=flat.get("notify_email_enabled", False),
            key="notify_email_enabled",
        )

        col4, col5, col6 = st.columns(3)
        with col4:
            st.text_input(
                t("smtp_host_label"),
                value=env_values.get("SMTP_HOST", ""),
                key="smtp_host",
                placeholder="smtp.gmail.com",
            )
        with col5:
            st.text_input(
                t("smtp_port_label"), value=env_values.get("SMTP_PORT", "587"), key="smtp_port"
            )
        with col6:
            st.toggle(
                t("use_tls_label"),
                value=env_values.get("SMTP_USE_TLS", "true").lower() == "true",
                key="smtp_use_tls",
            )

        col7, col8 = st.columns(2)
        with col7:
            st.text_input(
                t("smtp_user_label"), value=env_values.get("SMTP_USER", ""), key="smtp_user"
            )
        with col8:
            st.text_input(
                t("smtp_password_label"),
                value=env_values.get("SMTP_PASSWORD", ""),
                type="password",
                key="smtp_password",
            )

        col9, col10 = st.columns(2)
        with col9:
            st.text_input(
                t("from_address_label"), value=env_values.get("SMTP_FROM", ""), key="smtp_from"
            )
        with col10:
            st.text_input(
                t("to_addresses_label"), value=env_values.get("SMTP_TO", ""), key="smtp_to"
            )

        if st.button(t("test_email_btn"), key="test_smtp"):
            with st.spinner(t("testing_smtp")):
                from utils.config_io import validate_smtp_connection

                ok, msg = validate_smtp_connection(
                    st.session_state.get("smtp_host", ""),
                    int(st.session_state.get("smtp_port", "587")),
                    st.session_state.get("smtp_user", ""),
                    st.session_state.get("smtp_password", ""),
                    st.session_state.get("smtp_use_tls", True),
                )
            if ok:
                st.success(msg)
            else:
                st.error(msg)

    # ---- WeChat Work ----
    with st.expander(t("wechat_expander"), expanded=flat.get("notify_wechat_enabled", False)):
        st.toggle(
            t("enable_wechat"),
            value=flat.get("notify_wechat_enabled", False),
            key="notify_wechat_enabled",
        )
        st.text_input(
            t("webhook_url_label"),
            value=env_values.get("WECHAT_WEBHOOK_URL", ""),
            type="password",
            key="wechat_webhook_url",
        )

    # ---- DingTalk ----
    with st.expander(t("dingtalk_expander"), expanded=flat.get("notify_dingtalk_enabled", False)):
        st.toggle(
            t("enable_dingtalk"),
            value=flat.get("notify_dingtalk_enabled", False),
            key="notify_dingtalk_enabled",
        )
        st.text_input(
            t("webhook_url_label"),
            value=env_values.get("DINGTALK_WEBHOOK_URL", ""),
            type="password",
            key="dingtalk_webhook_url",
        )
        st.text_input(
            t("secret_optional_label"),
            value=env_values.get("DINGTALK_SECRET", ""),
            type="password",
            key="dingtalk_secret",
        )

    # ---- Telegram ----
    with st.expander(t("telegram_expander"), expanded=flat.get("notify_telegram_enabled", False)):
        st.toggle(
            t("enable_telegram"),
            value=flat.get("notify_telegram_enabled", False),
            key="notify_telegram_enabled",
        )
        col11, col12 = st.columns(2)
        with col11:
            st.text_input(
                t("bot_token_label"),
                value=env_values.get("TELEGRAM_BOT_TOKEN", ""),
                type="password",
                key="telegram_bot_token",
            )
        with col12:
            st.text_input(
                t("chat_id_label"),
                value=env_values.get("TELEGRAM_CHAT_ID", ""),
                key="telegram_chat_id",
            )

    # ---- Slack ----
    with st.expander(t("slack_expander"), expanded=flat.get("notify_slack_enabled", False)):
        st.toggle(
            t("enable_slack"),
            value=flat.get("notify_slack_enabled", False),
            key="notify_slack_enabled",
        )
        st.text_input(
            t("webhook_url_label"),
            value=env_values.get("SLACK_WEBHOOK_URL", ""),
            type="password",
            key="slack_webhook_url",
        )

    # ---- Generic Webhook ----
    with st.expander(
        t("generic_webhook_expander"), expanded=flat.get("notify_generic_webhook_enabled", False)
    ):
        st.toggle(
            t("enable_generic_webhook"),
            value=flat.get("notify_generic_webhook_enabled", False),
            key="notify_generic_webhook_enabled",
        )
        st.text_input(
            t("webhook_url_label"),
            value=env_values.get("GENERIC_WEBHOOK_URL", ""),
            type="password",
            key="generic_webhook_url",
        )


def collect(env_values: dict, _config_values: dict) -> tuple:
    """Collect values. Returns (env_updates, config_updates)."""
    env_updates = {
        "SMTP_HOST": st.session_state.get("smtp_host", ""),
        "SMTP_PORT": st.session_state.get("smtp_port", "587"),
        "SMTP_USER": st.session_state.get("smtp_user", ""),
        "SMTP_PASSWORD": st.session_state.get("smtp_password", ""),
        "SMTP_FROM": st.session_state.get("smtp_from", ""),
        "SMTP_TO": st.session_state.get("smtp_to", ""),
        "SMTP_USE_TLS": "true" if st.session_state.get("smtp_use_tls", True) else "false",
        "WECHAT_WEBHOOK_URL": st.session_state.get("wechat_webhook_url", ""),
        "DINGTALK_WEBHOOK_URL": st.session_state.get("dingtalk_webhook_url", ""),
        "DINGTALK_SECRET": st.session_state.get("dingtalk_secret", ""),
        "TELEGRAM_BOT_TOKEN": st.session_state.get("telegram_bot_token", ""),
        "TELEGRAM_CHAT_ID": st.session_state.get("telegram_chat_id", ""),
        "SLACK_WEBHOOK_URL": st.session_state.get("slack_webhook_url", ""),
        "GENERIC_WEBHOOK_URL": st.session_state.get("generic_webhook_url", ""),
    }

    config_updates = {
        "notifications_enabled": st.session_state.get("notifications_enabled", False),
        "notify_on_success": st.session_state.get("notify_on_success", True),
        "notify_on_failure": st.session_state.get("notify_on_failure", True),
        "notify_attach_reports": st.session_state.get("notify_attach_reports", False),
        "notification_top_n": st.session_state.get("notification_top_n", 5),
        "notify_email_enabled": st.session_state.get("notify_email_enabled", False),
        "notify_wechat_enabled": st.session_state.get("notify_wechat_enabled", False),
        "notify_dingtalk_enabled": st.session_state.get("notify_dingtalk_enabled", False),
        "notify_telegram_enabled": st.session_state.get("notify_telegram_enabled", False),
        "notify_slack_enabled": st.session_state.get("notify_slack_enabled", False),
        "notify_generic_webhook_enabled": st.session_state.get(
            "notify_generic_webhook_enabled", False
        ),
    }

    return env_updates, config_updates
