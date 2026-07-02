# 更新通知模板 — Telegram HTML
#
# Telegram 使用 HTML 标签：<b> <code> <a> <blockquote>

<b>ArXiv Daily Researcher</b>
<b>🔄 新版本可用</b>

当前版本: <code>{local_version}</code>
最新版本: <code>{remote_version}</code>

<b>更新方式</b>
<blockquote>Docker: docker compose pull && docker compose up -d
本地: git pull</blockquote>

{release_notes}

<a href="{release_url}">查看发布页面</a>
