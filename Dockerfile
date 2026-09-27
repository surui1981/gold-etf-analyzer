# 黄金 ETF 投资辅助 — 多阶段生产镜像
# ────────────────────────────────────────────────────────────────
# 镜像大小：~280 MB（runtime）为早期设计目标值，尚未实测（首次真实构建于 V0.74.0 打通）
# 安全：runtime 无 gcc、curl 仅用于 healthcheck、非 root 运行
#
# 相对初版的三处修正（首次真实构建暴露，此前 docker job 因 CI 触发条件缺 tags 而恒为 skipped）：
#   1. src-layout 构建失败 —— 原 `COPY pyproject.toml README.md ./` + `pip install .` 缺 src/，
#      构建后端报 "error in 'egg_base' option: 'src' does not exist or is not a directory"。
#      现改为：builder 只装「依赖」（不装项目本体），业务代码由 runtime 直接以 /app/src 提供。
#      这样既修好构建，又保住「业务代码变更不触发依赖重装」的缓存设计。
#   2. 容器内 PROJECT_ROOT 错位 —— config.py / main.py 均以 Path(__file__).resolve().parents[2]
#      推导项目根。若 app 从 /install/app 载入，parents[2] 会算成 "/"，导致 static/、data/、
#      alembic.ini、migrations/ 全部指向根目录下的不存在路径。故必须让 app 从 /app/src/app 载入。
#   3. runtime 依赖缺失 —— httpx 曾是 dev extra，但 services/notify.py 模块级导入它，
#      生产镜像会因 ImportError 启动失败；已提升为 pyproject 的运行时依赖。
#
# ⚠️ 改动本文件后必须实际构建一次验证（不可只跑静态检查）：
#    docker build --target runtime -t gold-etf-analyzer:local . \
#      && docker run --rm -d -p 8889:8888 gold-etf-analyzer:local \
#      && curl -fsS http://localhost:8889/api/v1/health

# Stage 1 · builder：仅装运行时依赖到 /install（target dir 隔离 site-packages）
FROM python:3.12-slim AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends gcc \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build

# 只拷贝依赖清单：业务代码变更不会使这一层失效
COPY pyproject.toml ./

# 从 pyproject 抽出 [project].dependencies 后安装。
# 不执行 `pip install .` —— src-layout 下该命令需要 src/ 在场，而把 src 拷进来会让
# 依赖层随每次业务代码改动失效；项目本体由 runtime 以 /app/src 形式提供即可
# （代码不读取已安装包的元数据，故无需安装本包）。
RUN python -c "import pathlib, tomllib; d = tomllib.loads(pathlib.Path('pyproject.toml').read_text(encoding='utf-8')); open('/tmp/requirements.txt', 'w').write(chr(10).join(d['project']['dependencies']))" \
    && echo '--- 待安装的运行时依赖 ---' \
    && cat /tmp/requirements.txt \
    && pip install --no-cache-dir --target=/install -r /tmp/requirements.txt

# Stage 2 · runtime：slim 基础 + 拷贝 /install + 非 root + HEALTHCHECK
FROM python:3.12-slim AS runtime

# PYTHONPATH 以 /app/src 优先：确保 app 从业务源码载入（PROJECT_ROOT 才能解析为 /app），
# 依赖目录 /install 仅提供第三方包。
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src:/install \
    PATH=/install/bin:$PATH

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --shell /bin/bash appuser

WORKDIR /app

# 拷贝 /install（依赖）+ src + 静态 + alembic 配置
# src 落到 /app/src（而非 /app/app）：config.py 的 parents[2] 由此解析为 /app
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
