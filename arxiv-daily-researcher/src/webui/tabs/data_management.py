"""数据管理 Tab — 配置导出 + WebDAV 同步"""

import io
import zipfile
import logging
from datetime import time as dt_time
import streamlit as st
from pathlib import Path

from webui.i18n import t

logger = logging.getLogger(__name__)

# 路径常量
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
DEFAULT_CONFIG_PATH = _PROJECT_ROOT / "configs" / "config.json"
DEFAULT_ENV_PATH = _PROJECT_ROOT / ".env"


def render(env_values: dict, config_values: dict):
    """渲染数据管理 Tab。"""
    flat = config_values

    # ==================== 配置导出 ====================
    st.markdown(
        f'<p class="section-title">📦 {t("dm_export_title")}</p>',
        unsafe_allow_html=True,
    )
    st.markdown(
        f'<p class="hint-text">{t("dm_export_hint")}</p>',
        unsafe_allow_html=True,
    )

    col_exp1, col_exp2 = st.columns(2)
    with col_exp1:
        zip_data = _build_export_zip()
        if zip_data:
            st.download_button(
                label=t("dm_export_btn"),
                data=zip_data,
                file_name="arxiv_researcher_config.zip",
                mime="application/zip",
                use_container_width=True,
            )
        else:
            st.warning(t("dm_export_no_files"))

    with col_exp2:
        st.caption(t("dm_export_contents"))

    st.divider()

    # ==================== WebDAV 同步 ====================
    st.markdown(
        f'<p class="section-title">☁️ {t("dm_webdav_title")}</p>',
        unsafe_allow_html=True,
    )
    st.markdown(
        f'<p class="hint-text">{t("dm_webdav_hint")}</p>',
        unsafe_allow_html=True,
    )

    # 全局开关
    st.toggle(
        t("dm_webdav_enable"),
        value=flat.get("webdav_enabled", False),
        key="webdav_enabled",
    )

    # WebDAV 连接凭据（直接在面板配置，类似 API tab）
    st.text_input(
        t("dm_webdav_url_label"),
        value=env_values.get("WEBDAV_URL", ""),
        key="webdav_url",
        placeholder="https://dav.jianguoyun.com/dav/",
    )

    col_u, col_p = st.columns(2)
    with col_u:
        st.text_input(
            t("dm_webdav_username_label"),
            value=env_values.get("WEBDAV_USERNAME", ""),
            key="webdav_username",
        )
    with col_p:
        st.text_input(
            t("dm_webdav_password_label"),
            value=env_values.get("WEBDAV_PASSWORD", ""),
            type="password",
            key="webdav_password",
        )

    # 操作按钮（紧跟凭据后面）
    col_a, col_b, col_c = st.columns(3)
    with col_a:
        if st.button(t("dm_webdav_test_btn"), use_container_width=True):
            _do_test_connection()
    with col_b:
        if st.button(t("dm_webdav_upload_btn"), use_container_width=True):
            _do_sync("upload")
    with col_c:
        if st.button(t("dm_webdav_download_btn"), use_container_width=True):
            _do_sync("download")

    st.divider()

    # 远程路径 & 同步设置
    st.markdown(
        f'<p class="section-title">⚙️ {t("dm_webdav_sync_settings")}</p>',
        unsafe_allow_html=True,
    )

    st.text_input(
        t("dm_webdav_remote_path"),
        value=flat.get("webdav_remote_path", "/arxiv-daily-researcher/"),
        key="webdav_remote_path",
        help=t("dm_webdav_remote_path_help"),
    )

    # 同步模式
    mode_options = ["manual", "scheduled", "after_report"]
    mode_labels = [
        t("dm_webdav_mode_manual"),
        t("dm_webdav_mode_scheduled"),
        t("dm_webdav_mode_after_report"),
    ]
    current_mode = flat.get("webdav_sync_mode", "after_report")
    current_idx = mode_options.index(current_mode) if current_mode in mode_options else 2

    selected_label = st.selectbox(
        t("dm_webdav_sync_mode"),
        options=mode_labels,
        index=current_idx,
        key="webdav_sync_mode_label",
    )
    _mode_idx = mode_labels.index(selected_label)
    st.session_state["webdav_sync_mode"] = mode_options[_mode_idx]

    # 定时同步 — 时间选择器（小时:分钟）
    if st.session_state.get("webdav_sync_mode") == "scheduled":
        # Parse existing cron or default to 23:00
        cron_str = flat.get("webdav_cron_schedule", "0 23 * * *")
        try:
            parts = cron_str.split()
            default_hour = int(parts[1]) if len(parts) > 1 else 23
            default_minute = int(parts[0]) if len(parts) > 0 else 0
        except (ValueError, IndexError):
            default_hour, default_minute = 23, 0

        sync_time = st.time_input(
            t("dm_webdav_sync_time"),
            value=dt_time(default_hour, default_minute),
            key="webdav_sync_time",
            help=t("dm_webdav_sync_time_help"),
        )
        # Store as cron expression for backend compatibility
        st.session_state["webdav_cron_schedule"] = f"{sync_time.minute} {sync_time.hour} * * *"

    st.divider()

    # 同步范围
    st.markdown(
        f'<p class="section-title">📂 {t("dm_webdav_scope_title")}</p>',
        unsafe_allow_html=True,
    )

    col1, col2 = st.columns(2)
    with col1:
        st.toggle(
            t("dm_webdav_sync_configs_label"),
            value=flat.get("webdav_sync_configs", True),
            key="webdav_sync_configs",
        )
        st.toggle(
            t("dm_webdav_sync_history_label"),
            value=flat.get("webdav_sync_history", True),
            key="webdav_sync_history",
        )
    with col2:
        st.toggle(
            t("dm_webdav_sync_keywords_label"),
            value=flat.get("webdav_sync_keywords", True),
            key="webdav_sync_keywords",
        )
        st.toggle(
            t("dm_webdav_sync_reports_label"),
            value=flat.get("webdav_sync_reports", False),
            key="webdav_sync_reports",
        )


def collect(env_values: dict, _config_values: dict) -> tuple:
    """收集数据管理 Tab 的配置值。返回 (env_updates, config_updates)。"""
    env_updates = {
        "WEBDAV_URL": st.session_state.get("webdav_url", ""),
        "WEBDAV_USERNAME": st.session_state.get("webdav_username", ""),
        "WEBDAV_PASSWORD": st.session_state.get("webdav_password", ""),
    }

    config_updates = {
        "webdav_enabled": st.session_state.get("webdav_enabled", False),
        "webdav_remote_path": st.session_state.get(
            "webdav_remote_path", "/arxiv-daily-researcher/"
        ),
        "webdav_sync_mode": st.session_state.get("webdav_sync_mode", "after_report"),
        "webdav_cron_schedule": st.session_state.get("webdav_cron_schedule", "0 23 * * *"),
        "webdav_sync_configs": st.session_state.get("webdav_sync_configs", True),
        "webdav_sync_history": st.session_state.get("webdav_sync_history", True),
        "webdav_sync_keywords": st.session_state.get("webdav_sync_keywords", True),
        "webdav_sync_reports": st.session_state.get("webdav_sync_reports", False),
    }

    return env_updates, config_updates


# ==================== 内部辅助函数 ====================


def _build_export_zip() -> bytes | None:
    """构建包含 config.json 和 .env 的 zip 压缩包。"""
    files_to_zip = []

    # Check multiple possible paths (local vs Docker mount)
    for config_path in [DEFAULT_CONFIG_PATH, Path("/app/configs/config.json")]:
        if config_path.exists():
            files_to_zip.append(("config.json", config_path))
            break

    for env_path in [DEFAULT_ENV_PATH, Path("/app/.env")]:
        if env_path.exists():
            files_to_zip.append((".env", env_path))
            break

    if not files_to_zip:
        return None

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for arcname, filepath in files_to_zip:
            zf.write(filepath, arcname)
    return buf.getvalue()


def _do_test_connection():
    """测试 WebDAV 连接。"""
    try:
        from utils.webdav_sync import WebDAVSync

        # Use current form values directly so users can test before clicking Save.
        url = (st.session_state.get("webdav_url") or "").strip()
        username = (st.session_state.get("webdav_username") or "").strip()
        password = st.session_state.get("webdav_password") or ""
        remote_path = (
            st.session_state.get("webdav_remote_path") or "/arxiv-daily-researcher/"
        ).strip()

        if not url or not username:
            st.error(t("dm_webdav_not_configured"))
            return

        client = WebDAVSync(
            url=url,
            username=username,
            password=password,
            remote_path=remote_path,
        )

        if client.test_connection():
            st.success(t("dm_webdav_test_ok"))
        else:
            st.error(t("dm_webdav_test_fail"))
    except ImportError:
        st.error(t("dm_webdav_missing_lib"))
    except Exception as e:
        st.error(f"{t('dm_webdav_test_fail')}: {e}")


def _do_sync(direction: str):
    """执行 WebDAV 同步。"""
    try:
        from utils.webdav_sync import WebDAVSync

        # Use current form values directly so users can sync immediately.
        url = (st.session_state.get("webdav_url") or "").strip()
        username = (st.session_state.get("webdav_username") or "").strip()
        password = st.session_state.get("webdav_password") or ""
        remote_path = (
            st.session_state.get("webdav_remote_path") or "/arxiv-daily-researcher/"
        ).strip()

        if not url or not username:
            st.error(t("dm_webdav_not_configured"))
            return

        client = WebDAVSync(
            url=url,
            username=username,
            password=password,
            remote_path=remote_path,
        )

        include_reports = st.session_state.get("webdav_sync_reports", False)
        with st.spinner(t("dm_webdav_syncing")):
            result = client.sync_all(direction=direction, include_reports=include_reports)

        if result["success"] == result["total"]:
            st.success(
                f"{t('dm_webdav_sync_done')} "
                f"{result['success']}/{result['total']} — "
                f"{result['elapsed_seconds']}s"
            )
        else:
            st.warning(
                f"{t('dm_webdav_sync_partial')} "
                f"{result['success']}/{result['total']} — "
                f"{result['elapsed_seconds']}s"
            )
            for path, ok in result["results"].items():
                if not ok:
                    st.caption(f"❌ {path}")
    except ImportError:
        st.error(t("dm_webdav_missing_lib"))
    except Exception as e:
        st.error(f"{t('dm_webdav_sync_error')}: {e}")
