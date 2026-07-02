"""
自动更新检查模块

从 GitHub 仓库检查是否有新版本，并自动拉取最新代码。
Docker 环境下通过 GitHub API 检查版本并通过通知系统报告。
"""

import os
import subprocess
import sys
from pathlib import Path

REPO_URL = "https://github.com/yzr278892/arxiv-daily-researcher"
GITHUB_API_LATEST = "https://api.github.com/repos/yzr278892/arxiv-daily-researcher/releases/latest"
VERSION_FILE = Path(__file__).resolve().parent.parent.parent / "VERSION"
TEMPLATES_DIR = Path(__file__).resolve().parent.parent.parent / "configs" / "templates"


def _get_local_version() -> str:
    """读取本地 VERSION 文件，不存在返回 'unknown'。"""
    try:
        if VERSION_FILE.exists():
            return VERSION_FILE.read_text(encoding="utf-8").strip()
    except Exception:
        pass
    return "unknown"


def _load_template(name: str, subdir: str = "notifications") -> str | None:
    """从 configs/templates 加载通知模板文件。"""
    path = TEMPLATES_DIR / subdir / name
    if path.exists():
        try:
            content = path.read_text(encoding="utf-8")
            # 跳过模板文件的注释头（以 # 或 <!-- 开头的行）
            lines = content.splitlines()
            body_lines = []
            in_header = True
            for line in lines:
                stripped = line.strip()
                if in_header and (stripped.startswith("#") and not stripped.startswith("##")):
                    continue
                if in_header and stripped.startswith("<!--"):
                    # Skip HTML comment blocks
                    continue
                if in_header and stripped.startswith("-->"):
                    continue
                in_header = False
                body_lines.append(line)
            return "\n".join(body_lines).strip()
        except Exception:
            return None
    return None


def _inject_proxy_env(logger=None):
    """
    从 config.py 的代理配置注入 http_proxy/https_proxy 环境变量，
    供 git 和 requests 使用。
    """
    try:
        from config import settings
        if not getattr(settings, "PROXY_UPDATE_CHECK", False):
            return
        proxy_url = getattr(settings, "PROXY_URL", "")
        if proxy_url:
            os.environ["http_proxy"] = proxy_url
            os.environ["https_proxy"] = proxy_url
            if logger:
                logger.info(f"[更新检查] 已注入代理: {proxy_url}")
    except Exception:
        pass


def check_and_update(logger=None) -> bool:
    """
    检查 GitHub 仓库是否有更新，如有则自动拉取。

    返回:
        bool: True 表示已更新或已是最新，False 表示检查失败
    """

    def log(msg, level="info"):
        if logger:
            getattr(logger, level)(msg)
        else:
            print(msg)

    project_root = Path(__file__).resolve().parent.parent.parent
    git_dir = project_root / ".git"

    # 注入代理环境变量
    _inject_proxy_env(logger)

    if not git_dir.exists():
        log("未检测到 .git 目录（Docker/CI 环境），通过 GitHub API 检查版本", "info")
        return _check_version_via_api(logger)

    try:
        # 获取当前分支
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=project_root,
            capture_output=True,
            text=True,
            timeout=10,
        )
        branch = result.stdout.strip() or "main"

        # 获取远程更新信息
        log("正在检查更新...")
        fetch_result = subprocess.run(
            ["git", "fetch", "origin", branch],
            cwd=project_root,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if fetch_result.returncode != 0:
            log(f"获取远程更新失败: {fetch_result.stderr.strip()}", "warning")
            return False

        # 比较本地和远程的提交
        result = subprocess.run(
            ["git", "rev-list", f"HEAD..origin/{branch}", "--count"],
            cwd=project_root,
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            log(f"比较提交失败: {result.stderr.strip()}", "warning")
            return False
        behind_count = int(result.stdout.strip())

        if behind_count == 0:
            log("当前已是最新版本")
            return True

        log(f"发现 {behind_count} 个新提交，正在更新...")

        # 检查是否有未提交的修改
        status_result = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=project_root,
            capture_output=True,
            text=True,
            timeout=10,
        )
        has_changes = bool(status_result.stdout.strip())

        if has_changes:
            log("检测到本地修改，暂存中...")
            subprocess.run(
                ["git", "stash", "push", "-m", "auto-update-stash"],
                cwd=project_root,
                capture_output=True,
                text=True,
                timeout=10,
            )

        # 拉取最新代码
        pull_result = subprocess.run(
            ["git", "pull", "origin", branch],
            cwd=project_root,
            capture_output=True,
            text=True,
            timeout=60,
        )

        if pull_result.returncode != 0:
            log(f"拉取更新失败: {pull_result.stderr.strip()}", "warning")
            if has_changes:
                subprocess.run(
                    ["git", "stash", "pop"],
                    cwd=project_root,
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
            return False

        if has_changes:
            pop_result = subprocess.run(
                ["git", "stash", "pop"],
                cwd=project_root,
                capture_output=True,
                text=True,
                timeout=10,
            )
            if pop_result.returncode != 0:
                log("恢复本地修改时出现冲突，请手动解决", "warning")

        log(f"更新完成！已拉取 {behind_count} 个新提交")
        return True

    except subprocess.TimeoutExpired:
        log("更新检查超时，跳过", "warning")
        return False
    except Exception as e:
        log(f"更新检查异常: {e}", "warning")
        return False


def _check_version_via_api(logger=None) -> bool:
    """
    通过 GitHub API 检查最新版本，如果有新版本则通过通知系统发送更新提醒。
    适用于 Docker 等无 .git 目录的环境。
    """
    import requests as req

    def log(msg, level="info"):
        if logger:
            getattr(logger, level)(msg)
        else:
            print(msg)

    local_version = _get_local_version()
    if local_version == "unknown":
        log("未找到 VERSION 文件，跳过版本检查", "info")
        return True

    try:
        resp = req.get(GITHUB_API_LATEST, timeout=15)
        if resp.status_code == 404:
            log("未找到发布版本，跳过", "info")
            return True
        resp.raise_for_status()
        data = resp.json()
        remote_version = data.get("tag_name", "").lstrip("v")
        release_url = data.get("html_url", REPO_URL)
        release_body = data.get("body", "")[:500]

        if not remote_version:
            log("无法获取远程版本号", "warning")
            return True

        if remote_version == local_version:
            log(f"当前版本 {local_version} 已是最新")
            return True

        log(f"发现新版本: {remote_version}（当前: {local_version}）")
        _send_update_notification(local_version, remote_version, release_url, release_body, logger)
        return True

    except Exception as e:
        log(f"GitHub API 版本检查失败: {e}", "warning")
        return False


def _send_update_notification(
    local_version: str,
    remote_version: str,
    release_url: str,
    release_notes: str,
    logger=None,
):
    """通过已配置的通知渠道发送更新提醒，使用外部模板文件。"""
    try:
        from config import settings

        if not settings.ENABLE_NOTIFICATIONS:
            return

        from notifications.notifier import NotifierAgent

        agent = NotifierAgent()
        if not agent.notifiers:
            return

        subject = f"ArXiv Daily Researcher - 新版本 {remote_version} 可用"
        template_vars = {
            "local_version": local_version,
            "remote_version": remote_version,
            "release_url": release_url,
            "release_notes": release_notes if release_notes else "无更新日志",
        }

        for notifier in agent.notifiers:
            try:
                platform = agent._platform_for_notifier(notifier)
                body = _format_update_body(platform, template_vars)

                from notifications.notifier import EmailNotifier

                if isinstance(notifier, EmailNotifier):
                    html_body = _format_update_html(template_vars)
                    notifier.send(subject, body, html_body=html_body)
                else:
                    notifier.send(subject, body)
            except Exception as e:
                if logger:
                    logger.warning(f"更新通知发送失败: {e}")

    except Exception as e:
        if logger:
            logger.warning(f"更新通知初始化失败: {e}")


def _format_update_body(platform: str, vars: dict) -> str:
    """根据平台加载对应的更新通知模板。"""
    # 按平台选择模板文件
    template_map = {
        "telegram": "update_available_telegram.md",
        "wechat_work": "update_available_wechat.md",
    }
    template_name = template_map.get(platform, "update_available.md")
    template = _load_template(template_name)

    if template:
        try:
            return template.format(**vars)
        except KeyError:
            pass

    # 回退到硬编码格式
    return (
        f"## ArXiv Daily Researcher\n\n"
        f"**🔄 新版本可用**\n\n"
        f"> 当前版本: `{vars['local_version']}`\n"
        f"> 最新版本: `{vars['remote_version']}`\n\n"
        f"[查看发布页面]({vars['release_url']})"
    )


def _format_update_html(vars: dict) -> str:
    """加载 Email HTML 更新通知模板。"""
    import html as html_mod

    template = _load_template("update_available.html", subdir="email")
    if template:
        try:
            safe_vars = {k: html_mod.escape(str(v)) for k, v in vars.items()}
            # release_url 不需要 HTML escape（用于 href 属性）
            safe_vars["release_url"] = vars["release_url"]
            return template.format(**safe_vars)
        except KeyError:
            pass

    # 回退到基础 HTML
    return (
        f"<h2>ArXiv Daily Researcher</h2>"
        f"<p><b>🔄 新版本可用</b></p>"
        f"<p>当前版本: <code>{html_mod.escape(vars['local_version'])}</code></p>"
        f"<p>最新版本: <code>{html_mod.escape(vars['remote_version'])}</code></p>"
        f'<p><a href="{html_mod.escape(vars["release_url"])}">查看发布页面</a></p>'
    )
