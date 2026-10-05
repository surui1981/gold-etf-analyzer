# 技术架构与数据源

> 本指南已拆分为 5 部分，本文件包含 **技术架构（§3）+ 数据源（§7）**。
> 其他部分：[overview](overview.md) · [getting-started](getting-started.md) ·
> [api-reference](api-reference.md) · [development](development.md)
>
> 完整索引见 [application-guide.md](application-guide.md)。

## 3. 技术架构

### 3.1 分层结构

```
api/v1（路由） → services（业务） → repositories（数据访问） → models（ORM）
                        ↕
                     schemas（Pydantic v2 共享契约）
```

依赖方向自上而下，替换任一实现（行情源 / 数据库 / 评分权重）不影响上层接口。

### 3.2 目录说明

```
src/app/
├── main.py              # 入口：路由装配、CORS、lifespan、静态文件、调度器启动
├── config.py            # pydantic-settings 配置（.env / 环境变量）
├── dependencies.py      # 依赖注入容器（测试可整体替换）
├── models/              # SQLAlchemy 2.0 ORM（analysis / position / snapshot / settings / central_bank / account / news / review / push / user）
├── schemas/             # Pydantic v2 请求/响应模型 + 枚举
├── services/
│   ├── scoring.py       # 宏观机会评分引擎（FACTOR_RULES）
│   ├── trend.py         # 趋势分析 + 追踪指数（TREND_WEIGHTS）
│   ├── macro.py         # 宏观参考因子评分（5 因子；cb_gold 注入中央银行服务）
│   ├── decision.py      # 购买决策引擎（趋势×持仓规则矩阵 + reason_items）
│   ├── position.py      # 交易面：开仓/加减仓/清仓/盈亏/软删除/CSV 导出（按账本过滤）
│   ├── account.py       # 账本：默认账本保障 / 增改 / 归档恢复 / 统计（P1 #6）
│   ├── trades.py        # 交易历史：多条件筛选 + 均价法回放 + 汇总 + CSV 导出（P1 #6）
│   ├── compare.py       # ETF vs 克价对照
│   ├── freshness.py     # 数据时效与三市场时段判定
│   ├── news.py          # 消息面评分（每日 3 槽位 + 1:2:3 加权合成 + 依据标签）
│   ├── review.py        # 研判复盘（金价回填 / 按日对齐 T+1·3·5 / 命中率·校准·标签胜率）
│   ├── snapshot.py      # 每日评估快照服务
│   ├── settings.py      # 权重配置持久化
│   ├── central_bank.py  # 央行购金业务编排（T12M / Top / 范围筛选）
│   ├── cache.py         # served cache（首屏直接命中）
│   ├── auth.py          # 认证：bcrypt 口令 / 密码策略 / 登录限流 / 会话签发校验撤销（V0.75.0）
│   └── scheduler.py     # 每日 07:00 BJT 快照 + 央行月度 1/15/末日 07:30 BJT 自动拉取
├── repositories/
│   ├── market_data.py   # AKShare 数据源（ETF 新浪主/东财备 + SGE 克价 + 纽约金英为财情 + Mock 兜底）
│   ├── analysis.py      # 分析记录仓储
│   ├── position.py      # 持仓/流水仓储（账本过滤 + 多条件流水查询 + 分账本统计）
│   ├── account.py       # 账本仓储（默认账本自愈 / 重名校验 / 归档）
│   ├── snapshot.py      # 快照仓储
│   ├── settings.py      # 权重配置仓储
│   ├── news.py          # 消息面打分仓储（(score_date, slot) 复合唯一 + 区间查询）
│   ├── review.py        # 金价日历仓储（upsert 合并后重算涨跌幅 / 取 T 之后第一个交易日）
│   ├── central_bank.py  # 央行购金 DB CRUD（按国家/季度查询 + upsert）
│   ├── central_bank_data.py  # WGC HTML chart JS fetcher（季度合计 + H1 按国家）
│   ├── user.py          # 用户与会话仓储（邮箱唯一约束 / 会话撤销 / 过期清理，V0.75.0）
│   └── db.py            # async 引擎与会话工厂
├── api/v1/endpoints/    # health / analysis / market / position / portfolio / account / trades / decision / settings / snapshot / news / review / central_bank / telemetry / resonance / backtest / push / **auth（V0.75.0）**
├── middleware/          # trace（X-Request-ID）/ rate_limit（per-IP 限速）/ admin_auth（X-Admin-Token）/ **auth + csrf（V0.75.0）**
├── scripts/             # CLI 工具（import_central_bank: WGC 数据全量导入）
└── utils/               # logger / market_clock / db_migrate（启动幂等补列）
static/                  # trend.html / portfolio.html / trades.html / weights.html / news.html / central_bank.html / review.html / silver.html / backtest.html / data-health.html / settings.html / offline.html / **login.html（V0.75.0）**
                         #   + account.js / freshness.js / help.js / **auth.js（V0.75.0）** / **synthesis-card.js（V0.75.1）** / **news-score-widget.js（V0.76.0）** / resonance-card.js / responsive.css
tests/                   # pytest（867 用例 / 63 个测试模块，含 fetcher / scheduler / 服务 / API / help / providers / cache / intraday / 业绩分析 / 多账本 / 多时间框架 / 消息面槽位 / 研判复盘 / 共振信号 / 克数持仓 / 白银 / 回测 / i18n / 埋点 / push / 仪表盘布局 / **认证（V0.75.0：服务 54 + API 32 + 中间件 28）**）
```

### 3.3 数据流

```
浏览器页面 ──fetch──▶ FastAPI ──▶ TrendService/ScoringService ──▶ MarketDataRepository
                                                                    │
                                           AKShare(新浪/东财) ◀────┘
                                                                    │ 失败降级
                                                              Mock 数据
```

---

## 7. 数据源

| 标的 / 层级 | 说明 |
|------|------|
| 纽约金（COMEX GC，指引基准） | 主源 AKShare `futures_foreign_hist`（英为财情）｜ 备选 `futures_global_hist_em`（东方财富 GC00Y）｜ 美元/盎司 |
| 上海金（SGE Au99.99） | AKShare `spot_hist_sge`（上海黄金交易所）｜ 元/克，作国内对照 |
| 黄金 ETF（518880） | 主源 AKShare `fund_etf_hist_sina`（新浪）｜ 备选 `fund_etf_hist_em`（东方财富）｜ 元 |
| 宏观 5 因子 | 美元指数 / 美债 10Y·30Y（实时采集 `bond_zh_us_rate`）/ VIX |
| **央行购金（V0.57.0 升级）** | **WGC Gold Demand Trends HTML chart JS（`fsapi.gold.org/api/v12/charts/js/...`）**——绕开 XLSX 403 反爬；季度合计 2014Q1–2026Q2 + H1 2026 按国家 + UZB/IRN 手工补丁；月度 1/15/末日 07:30 BJT 自动从 WGC 拉取并 upsert 到 `central_bank_purchases` 表；cb_gold 宏观因子从表汇总 T12M，无数据时回退 STATIC_REF（1019 吨/年） |
| **金价日历（V0.66.0 新增）** | `gold_price_daily` 表：按 `target`(ny/etf/gram) + `price_date` 唯一，存 `close` / `change_pct` / `source`。**只存客观价格、与 `daily_snapshots` 解耦**，故可回填、可长期积累；由 `POST /api/v1/review/backfill` 从 `/gold/ny-trend` 批量写入（upsert 时在合并后的时间序列上重算涨跌幅，重复回填不抹平已有值）。当前行情源提供约 60 个交易日历史（实测回填 2026-06-25 ~ 09-16） |
| 兜底 | 数据源三态：实时 `live` / 磁盘缓存 `stale` / 演示 `mock`（页面顶部状态条 + 健康度可见） |

> 采集策略：AKShare 为同步阻塞库，经 `asyncio.to_thread` 放入线程池；按源分锁（`etf`/`sge`/`ny`）并发采集避免 V8 全局锁崩溃；统一 30s 超时快速失败而非挂起；内存 + 独立 SQLite 双写缓存（TTL 300s，冷启动 ~1.6s）。WGC fetcher 走异步 HTTP（`httpx.AsyncClient`），同样 30s 超时。

---