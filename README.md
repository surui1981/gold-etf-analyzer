# Gold ETF Analyzer · 黄金ETF交易机会分析 API

基于 **FastAPI + Pydantic v2** 的分层架构 REST API 骨架，专注于黄金ETF交易机会分析。
延续 PM-Evaluator 的预期评估架构：以宏观因子（美元指数 / 美债收益率 / 实际利率 / 通胀预期 / 避险情绪）加权评分，输出**投资机会窗口**与**逐因子多空明细**（供前端红绿着色）。

## 快速开始

```bash
# 方式一：uv（首选）
uv sync --extra dev
uv run uvicorn app.main:app --reload --host 127.0.0.1 --port 8888

# 方式二：pip
python -m pip install -e ".[dev]"
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8888

# 方式三：Docker
docker compose up --build
```

启动后访问：

- Swagger 文档：http://127.0.0.1:8888/docs
- 健康检查：http://127.0.0.1:8888/api/v1/health

## 测试与代码质量

```bash
uv run pytest -v      # 运行测试
uv run ruff check src tests   # 静态检查
uv run ruff format src tests  # 格式化
```

## API 一览

| 方法 | 路径 | 说明 |
|------|------|------|
| GET  | `/api/v1/health` | 健康检查 |
| POST | `/api/v1/analysis/opportunity` | 提交宏观因子，返回机会评分与窗口 |
| GET  | `/api/v1/analysis/history?limit=20` | 历史分析记录（倒序） |
| GET  | `/api/v1/market/gold` | 黄金现货报价（当前 Mock） |

### 调用示例

```bash
curl -X POST http://127.0.0.1:8888/api/v1/analysis/opportunity \
  -H "Content-Type: application/json" \
  -d '{
    "factors": {
      "dxy": 96.0,
      "us10y_yield": 3.6,
      "real_rate": 1.4,
      "inflation_expectation": 3.0,
      "risk_off": 9
    },
    "gold_price_usd": 2350.5
  }'
```

响应关键字段：

```json
{
  "score": 94.5,
  "window": "strong",
  "signal": "bullish",
  "summary": "综合评分 94.5/100：宏观环境显著利多黄金，处于强机会窗口，可积极布局黄金ETF",
  "factors": [
    {
      "factor": "real_rate",
      "direction": "bullish",
      "weight": 0.35,
      "contribution": 35.0,
      "reason": "实际利率处于利多区间（友好度 100），构成黄金利多支撑"
    }
  ],
  "record_id": 1
}
```

## 架构分层

```
gold-etf-analyzer/
├── src/app/
│   ├── main.py              # 入口：装配路由、CORS、lifespan
│   ├── config.py            # pydantic-settings 配置（.env / 环境变量）
│   ├── dependencies.py      # 依赖注入容器（集中管理，便于测试替换）
│   ├── models/              # SQLAlchemy 2.0 ORM（analysis_records 表）
│   ├── schemas/             # Pydantic v2 请求/响应模型 + 枚举
│   ├── services/            # 业务层：评分引擎 + 编排服务
│   ├── repositories/        # 数据访问层：分析记录仓储 + 行情数据源抽象
│   ├── api/v1/              # 路由层：health / analysis / market
│   └── utils/               # 日志等通用工具
├── tests/                   # pytest：服务层单元测试 + API 集成测试
├── pyproject.toml           # 依赖与工具链配置（ruff / pytest）
├── Dockerfile / docker-compose.yml
├── Makefile / .env.example
└── README.md
```

依赖方向自上而下：`api → services → repositories → models`，`schemas` 为共享契约。
替换实现（如行情源、数据库、评分权重）不影响上层接口。

## 评分模型说明（rule-based，可调）

| 因子 | 权重 | 与黄金关系 | 友好度 100 分位 | 友好度 0 分位 |
|------|------|-----------|----------------|--------------|
| 实际利率 | 35% | 强负相关 | 1.5% | 2.5% |
| 美元指数 DXY | 30% | 负相关 | 95 | 105 |
| 美债10Y收益率 | 15% | 负相关 | 3.5% | 4.5% |
| 通胀预期 | 10% | 正相关 | 3.0% | 2.0% |
| 避险情绪 | 10% | 正相关 | 10 | 0 |

- **综合评分**：各因子友好度(0-100) × 权重 加权求和
- **投资窗口**：`≥70 strong` / `≥55 medium` / `≥40 weak` / `<40 standby`
- **方向信号**：`≥60 bullish` / `≤40 bearish` / 中间 neutral

权重与中枢集中在 `src/app/services/scoring.py` 的 `FACTOR_RULES`，可按经验直接调整；
后续可用历史行情回归或机器学习校准，接口不变。

## 待办 / 优化方向

- [ ] 接入真实行情源（替换 `MarketDataRepository` 的 Mock 实现）
- [ ] 用 Alembic 管理数据库迁移（当前为启动时 create_all）
- [ ] 评分参数支持运行时热更新（配置 API）
- [ ] 增加用户仓位管理（position）能力
- [ ] CI/CD（GitHub Actions）+ 监控告警
