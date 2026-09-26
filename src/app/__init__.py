"""app 包：黄金ETF交易机会分析 API。"""

# 应用版本号（运行时唯一真源）。
# `main.py` 的 FastAPI(version=...) 与 `/openapi.json` 均读取此值。
# 发版时需同步三处：此处 + pyproject.toml 的 version + uv.lock（跑 `uv lock`）。
__version__ = "0.74.0"
