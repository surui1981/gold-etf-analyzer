# V0.72.0 P3-b：黄金 ETF 投资辅助 — 多阶段生产镜像
# ────────────────────────────────────────────────────────────────
# 镜像大小：~280 MB（runtime）vs 单阶段 ~1.2 GB（builder）
# 安全：runtime 无 gcc、curl 仅用于 healthcheck、非 root 运行
# 缓存：pyproject 单独一层 → 业务代码变更不重装依赖

# Stage 1 · builder：装依赖到 /install（target dir 隔离 site-packages）
FROM python:3.12-slim AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends gcc \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build

# 先拷贝 pyproject（依赖清单），装包到 /install
COPY pyproject.toml README.md ./
RUN pip install --no-cache-dir . --target=/install

# Stage 2 · runtime：slim 基础 + 拷贝 /install + 非 root + HEALTHCHECK
FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/install \
    PATH=/install/bin:$PATH

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --shell /bin/bash appuser

WORKDIR /app

# 拷贝 /install（依赖）+ src + 静态 + alembic 配置
COPY --from=builder /install /install
COPY --chown=appuser:appuser src /app/src
COPY --chown=appuser:appuser static /app/static
COPY --chown=appuser:appuser alembic.ini /app/alembic.ini
COPY --chown=appuser:appuser migrations /app/migrations

# data 目录：SQLite 数据库落点（named volume 挂到这里）
RUN mkdir -p /app/data && chown -R appuser:appuser /app/data

USER appuser

EXPOSE 8888

# 健康检查：curl /api/v1/health（main.py 端点，30s 间隔，5s 超时）
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
    CMD curl -fsS http://localhost:8888/api/v1/health || exit 1

CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8888"]
