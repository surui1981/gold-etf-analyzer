# 黄金ETF交易机会分析 API —— 生产镜像
FROM python:3.12-slim

# 避免 .pyc 与缓冲，规范容器行为
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# 先装依赖（利用 Docker 层缓存，依赖变更才重建此层）
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir .

# 非 root 运行，最小权限原则
RUN useradd --create-home appuser
USER appuser

EXPOSE 8888

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8888"]
