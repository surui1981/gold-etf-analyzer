"""app 包：黄金ETF交易机会分析 API。"""

# 应用版本号（运行时唯一真源）。
# `main.py` 的 FastAPI(version=...) 与 `/openapi.json` 均读取此值。
# 发版时需同步四处：
#   ① 此处
#   ② pyproject.toml 的 version
#   ③ uv.lock（跑 `uv lock`）
#   ④ static/sw.js 的 `const VERSION`（SW 缓存名的组成部分）。
#      ⚠ 不同步它，已安装 PWA 的浏览器会一直复用旧缓存里的 /static/ 资源
#      （cache-first + sw.js 字节未变 ⇒ 不重装 SW ⇒ 不清缓存），
#      表现为「HTML 新 + JS 旧」错配。由 scripts/check_pwa_assets.py 强制校验。
#      ⚠ 注意与 static/dashboard.js 的同名 VERSION 区分 —— 那是布局 schema 锚，不可动。
__version__ = "0.83.2"
