# 交付总览：gold-etf-analyzer 项目骨架

## 完成内容

基于 **FastAPI + Pydantic v2 + SQLAlchemy 2.0 (async)** 搭建了黄金ETF交易机会分析 REST API 项目骨架，采用标准分层架构（api / services / repositories / models / schemas），并延续 PM-Evaluator 的预期评估架构（宏观因子加权评分 → 投资机会窗口）。

**位置**：`C:\Users\DFCFF\WorkBuddy\2026-08-30-07-53-17\gold-etf-analyzer\`

## 关键决策

1. **评分模型（rule-based，可调）**：实际利率 35% + 美元指数 30% + 美债10Y收益率 15% + 通胀预期 10% + 避险情绪 10%，各因子线性映射为 0-100 黄金友好度后加权；窗口分级 strong(≥70) / medium(≥55) / weak(≥40) / standby(<40)。权重集中在 `services/scoring.py::FACTOR_RULES`。
2. **逐因子多空明细**：响应 `factors[]` 携带 `direction`（bullish/bearish/neutral）与 `reason`，供前端按红绿着色区分利多/利空，与 PM-Evaluator 客户展示需求对齐。
3. **行情源抽象**：`MarketDataRepository` 为 Mock 实现，保持 `get_gold_quote` 签名不变即可无缝切换真实行情源（如腾讯自选股）。
4. **数据库**：SQLite（aiosqlite async），启动时 `create_all`（骨架期），后续可换 Alembic 迁移。
5. **端口**：默认 `127.0.0.1:8888`（贴合本地浏览器访问习惯），Docker 同样映射 8888。

## 验证结果

- ✅ `pytest`：**12/12 全部通过**（服务层评分引擎 + API 集成 + 参数校验）
- ✅ 真实启动实测：`/api/v1/health`、`POST /analysis/opportunity`（利多环境 → 94.5 分 strong/bullish）、`GET /analysis/history`（记录持久化）均正常

## 接口一览

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/v1/health` | 健康检查 |
| POST | `/api/v1/analysis/opportunity` | 宏观因子 → 机会评分/窗口/因子明细 |
| GET | `/api/v1/analysis/history?limit=N` | 历史分析记录（倒序） |
| GET | `/api/v1/market/gold` | 黄金报价（Mock） |

## 后续建议

- 接入真实行情源、Alembic 迁移、评分参数热更新 API、用户仓位管理（position）
- 前端可直接消费 `factors[].direction` 做红绿着色展示
- 运行：`uvicorn app.main:app --reload --host 127.0.0.1 --port 8888`，文档见 `http://127.0.0.1:8888/docs`

## GitHub 发布（V0.10）

- 远程仓库：**https://github.com/surui1981/gold-etf-analyzer**（Private）
- 本地 commit `3f28a13`（main，41 文件）+ annotated tag **`v0.10.0`** 均已推送并验证
- 凭据已持久化（`~/.git-credentials` + store），后续版本推送直接 `git push` 即可
- 迭代约定：版本号对齐 `vX.Y.Z` 标签（如 v0.10.0）

## 功能迭代（V0.11 待发布）

- **AKShare 数据源**：新浪主源/东财备选/Mock 兜底三级降级；`asyncio.to_thread` 避免阻塞
- **2 个月趋势追踪**：`GET /market/gold/trend?days=60`（价格序列 + MA5/20/40 + 方向）
- **市场趋势评估追踪指数**：5 维度加权（结构30/动量20/支撑20/动能15/回撤15）→ 0-100 指数与等级
- **可视化页面** `/static/trend.html`：折线+均线、指标卡、指数仪表盘、参数维度条（红涨绿跌）
- 测试 21/21 通过；服务运行于 127.0.0.1:8888
- 完整文档：`gold-etf-analyzer/docs/application-guide.md`（含 P1/P2/P3 改进计划）
