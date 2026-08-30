# ===== 开发常用命令（uv 首选，亦可使用 pip 等价命令）=====
.PHONY: install dev run test lint format clean

install:
	uv sync --extra dev

dev:
	uv run uvicorn app.main:app --reload --host 127.0.0.1 --port 8888

run:
	uv run uvicorn app.main:app --host 127.0.0.1 --port 8888

test:
	uv run pytest -v

lint:
	uv run ruff check src tests

format:
	uv run ruff format src tests

clean:
	rm -rf .pytest_cache .ruff_cache .venv data
