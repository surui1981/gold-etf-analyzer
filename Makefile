# ===== 开发常用命令（uv 首选，亦可使用 pip 等价命令）=====
.PHONY: install dev run test lint format check-web clean

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

lint:
	uv run ruff check src tests

format:
	uv run ruff format src tests

clean:
	rm -rf .pytest_cache .ruff_cache .venv data
