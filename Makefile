# ===== 开发常用命令（uv 首选，亦可使用 pip 等价命令）=====
.PHONY: install dev run test lint format check-web check-docs clean

install:
	uv sync --extra dev

dev:
	uv run uvicorn app.main:app --reload --host 127.0.0.1 --port 8888

run:
	uv run uvicorn app.main:app --host 127.0.0.1 --port 8888

test:
	uv run pytest -v

# 静态页面内联 JS 质量门禁（语法 / 未定义调用 / DOM id 一致性）
# 本项目前端无构建步骤，写错的 JS 不会被任何编译期拦截，改完页面务必跑一次
check-web:
	uv run python scripts/check_static_js.py

# 文档声明可校验门禁（数据表名 / localStorage key / 静态页 / API 端点 的存在性断言）
# 背景：文档曾出现「凭空捏造的数据表名」与「写错的 localStorage key」，
# 纯靠人工对账（docs/feature-alignment.md）拦不住，故升级为机制门禁
check-docs:
	uv run python scripts/check_docs_claims.py

lint:
	uv run ruff check src tests

format:
	uv run ruff format src tests

clean:
	rm -rf .pytest_cache .ruff_cache .venv data
