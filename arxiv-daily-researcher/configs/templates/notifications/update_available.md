# 更新通知模板 — 通用 Markdown
#
# 可用变量（使用 {变量名} 引用）：
#   {local_version}    — 当前版本号
#   {remote_version}   — 最新版本号
#   {release_url}      — GitHub Release 页面链接
#   {release_notes}    — 更新日志摘要

## ArXiv Daily Researcher

**🔄 新版本可用**

> 当前版本: `{local_version}`
> 最新版本: `{remote_version}`

**更新方式**
> Docker: `docker compose pull && docker compose up -d`
> 本地: `git pull`

{release_notes}

[查看发布页面]({release_url})
