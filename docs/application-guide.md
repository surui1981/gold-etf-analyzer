# 黄金价格投资辅助工具 · 说明文档

> 项目名：`gold-etf-analyzer` ｜ 当前版本：**V0.64.0**
> 命题：面向个人黄金投资者（中短期 ETF 波段），三市场对照（纽约金/上海金/黄金ETF）+ 综合趋势评估指数（技术/宏观/消息面）+ 持仓跟踪 + ETF购买决策 + 世界央行购金统计
> 技术栈：FastAPI + Pydantic v2 + SQLAlchemy 2.0 (async) + AKShare + WGC Gold Demand Trends (HTML chart JS)
> 仓库：https://github.com/surui1981/gold-etf-analyzer

---

## 1. 项目概述

面向**贵金属（黄金）投资窗口研究**的 REST API 应用，延续 PM-Evaluator 的预期评估架构：

- **宏观维度**：对美元指数、美债收益率、实际利率、通胀预期、避险情绪等宏观因子按典型经验赋权评分，输出**投资机会窗口**与**多空信号**；
- **技术维度**：基于 AKShare 采集黄金 ETF（518880 华安黄金ETF）真实行情，提供 **2 个月趋势追踪**，并合成**市场趋势评估追踪指数**（0-100）；
- **展示维度**：浏览器趋势页面（K线/折线 + 均线 + 参数维度 + 指数仪表盘），**红涨绿跌**着色，面向客户直观呈现决策明细。

---

## 2. 功能清单（现状）

| 模块 | 能力 | 状态 |
|------|------|------|
| 宏观机会分析 | `POST /api/v1/analysis/opportunity` 宏观因子加权评分 → 机会窗口 | ✅ |
| 分析历史 | `GET /api/v1/analysis/history` SQLite 持久化查询 | ✅ |
| 实时报价 | `GET /api/v1/market/gold` AKShare 真实报价（失败降级 Mock） | ✅ |
| 趋势追踪 | `GET /api/v1/market/gold/trend?days=60&interval=D` 价格序列 + MA5/20/40 + 方向（**默认纽约金 COMEX 为投资指引基准**；`target=ny/etf/gram` 可切换；`interval=D/W/M` 支持日/周/月多时间框架，W/M 模式由 730 天日 K 聚合） | ✅ |
| 纽约金曲线 | `GET /api/v1/market/gold/ny-trend?days=60&interval=D` COMEX 黄金期货 60 天曲线（等价于 `/gold/trend?target=ny`） | ✅ |
| 趋势评估指数 | 5 维度加权合成 0-100 指数（结构/动量/支撑/动能/回撤） | ✅ |
| 宏观参考因子 | 美元指数/美债10Y·30Y/VIX/央行购金 → 宏观参考指数，与技术面合成综合指数 | ✅ |
| 权重配置 | `GET/PUT /settings/weights` + `/weights` 页面：技术面/宏观面/合成比三组权重可调 | ✅ |
| 消息面评估 | `GET/PUT /api/v1/news-score` + `/news` 页面：客户基于投行展望给消息面打分（沿用昨日 / 快捷档位） | ✅ |
| 每日快照 | `POST/GET /snapshots`：每日参数+评估值本地持久化（daily_snapshots 表），指数历史序列 | ✅ |
| 个人交易跟踪 | `POST/GET /api/v1/positions` 开仓/持仓/加仓/减仓/清仓，实时盈亏 + **软删除/撤销 + CSV 导出** | ✅ |
| 购买决策引擎 | `GET /api/v1/decision/etf` 参数面×交易面 → 买入/加仓/持有/减仓/卖出 + **仓位推荐 + 决策可解释性红绿对照** | ✅ |
| ETF vs 克价对照 | `GET /api/v1/market/gold/compare` 518880 vs 上海金Au99.99 归一化对照 | ✅ |
| **央行购金统计** | `GET /api/v1/central-bank/{summary,top-buyers,purchases}` + `/central-bank` 页面：WGC GDT 季度净购金（吨）按国家/季度筛选，Chart.js 堆叠柱 + Top 10 + 明细表 | ✅ V0.57.0 |
| **自动调度** | 每日 07:00 BJT 捕获快照 + **央行购金月度 1/15/末日 07:30 BJT 自动从 WGC 拉取**（`CENTRAL_BANK_AUTO_REFRESH` 环境变量开关） | ✅ V0.57.0 |
| 数据时效透明 | `GET /api/v1/market/freshness` + 全站 `freshness.js` 时效条：三市场时段判定 + live/stale/mock 三态 + 60s 自动刷新 | ✅ V0.52.0 |
| 主动提醒（前端侧） | `/portfolio` 页面 60s 轮询评估指数/纽约金，档位切换/金价波动 ≥2% 触发浏览器通知 + 提醒条 + 今日简报 | ✅ V0.56.0 |
| **新手引导与帮助体系** | 右下角悬浮 `?` 按钮唤起 3 tab modal（操作指南 5 步流程 / 术语速查 30+ 条按 7 类分组 / 数据来源 + 投资警示）；首访 5 页面自动弹 2-4 步 tour 浮层；15 项关键术语 inline `?` 图标自动注入；移动端 modal 改底部抽屉；`localStorage.pm_help_*` 命名空间 | ✅ V0.58.0 |
| **行情源 provider 可切换** | `.env` 配置 `MARKET_PROVIDER=akshare\|mock\|eastmoney_only\|sina_only`，4 选 1；`market_providers.py` 工厂解析 bundle 注入；XAU fallback chain 与缓存 TTL 也可配；旧 `provider=` 签名保留向后兼容 | ✅ V0.59.0 |
| **行情实时性增强** | served cache 日内 TTL（默认 600s，`.env` 配 `SERVED_CACHE_TTL_SECONDS`）+ 6 个行情接口启用 `quote_cache_ttl` 真生效 + 日内 4 点（09:30/11:30/14:00/15:30 BJT）自动预热 served cache；趋势页 60s 轮询 + visibilitychange + 手动 🔄 按钮；持仓页 30s 轮询；freshness 角标按 `_fetched_at + cache_ttl` 派生 "stale" | ✅ V0.60.0 |
| **单用户多账本 + 交易历史查询页** | ① **多账本**：`accounts` 表 + `positions.account_id`（迁移把历史持仓归入 id=1「默认账户」），`/api/v1/accounts` 支持新建 / 重命名 / 备注 / 排序 / 设为默认 / 归档 / 恢复；默认账本不可归档、仍有未平仓持仓不可归档；② **账本隔离**：持仓、交易流水、收益曲线、获利分析、购买决策全部支持 `?account_id=`，前端右上角切换器（`static/account.js`）支持「全部账本」合并视图并记忆选择；③ **交易历史查询页** `/trades`：按账本 / 方向 / 日期区间 / 持仓 / 关键字筛选 + 分页，每笔卖出附**已实现盈亏**与**成交后份额**（均价法逐笔回放，回放始终取完整买入上下文），汇总覆盖全部匹配行，可导出 CSV | ✅ V0.62.0 |
| **交易闭环与业绩分析** | ① **ETF 报价口径修正**：新增 `GET /api/v1/market/gold/etf-quote`（518880，元/份；字段为 `price` + `currency`/`unit`，**不再用易混淆的 `price_usd`**），持仓估值 / 开仓预填 / 清仓价统一改用 ETF 价（此前误用 XAU/USD 国际金价导致收益率虚高）；② **加仓 / 减仓内联交易面板**：金额↔份数双向换算、快捷比例（1/4·1/2·3/4·全部）、摊薄成本与已实现盈亏实时预览，替代原生 `prompt()`；新增 `GET /positions/{id}/trades` 流水查询；③ **收益曲线** `GET /api/v1/portfolio/equity-curve?days=90`：交易流水 + ETF 历史价**回放重建**每日持有份数 / 成本 / 市值 / 累计收益率 + 最大回撤，30/90/180/365 天可切；④ **获利分析总结评估** `GET /api/v1/portfolio/performance`：已实现 / 浮动盈亏、平仓笔数与胜率、盈亏比、最佳 / 最差平仓、平均持仓天数 + 面向客户的中文复盘总结 | ✅ V0.61.0 |
| 可视化页面 | 趋势页 `/static/trend.html`（含对照区块）+ 持仓决策页 `/static/portfolio.html` + 权重页 `/weights` + 消息面页 `/news` + **央行购金页 `/central-bank`** | ✅ |
| **评估指数历史曲线升级** | 趋势页『每日评估历史』面板升级：① **4 条曲线**（综合 / 技术 / 宏观 / **消息面-新增·虚线**）替代原有 3 条；② **7D / 30D / 90D 区间切换按钮**（参考 portfolio 收益曲线 `EQUITY_RANGES` 模式）；③ **4 个极值卡**——最新（带档位）/ 区间最高 / 区间最低 / 日变（↑↓→ 红绿色），改用 `.cards` 网格；④ **稀疏数据 3 档 UX**——< 3 天「样本不足」、< 7 天「仅 N 天」、≥ 7 天默认；⑤ **chart.destroy 内存管理**——`snapChart` 模块级变量 + 渲染前 `snapChart?.destroy()`，区间切换无内存泄漏。后端零改动（`/api/v1/snapshots` 已支持 1-365 days + `news_index` 字段），纯前端增强 | ✅ V0.63.0 |
| **多时间框架（周/月线）** | 趋势页 K 线主图加 3 档区间按钮（60D / 52W / 24M）：服务端抽 730 天日 K → 按 ISO 周界聚合到 ~52 根周 K / 按年月聚合到 ~24 根月 K；MA 在聚合后序列上重算；W/M 模式技术面 5 维度旁路（指标对日 K 敏感）；`/api/v1/market/gold/trend?interval=W\|M` + `days` 上限 250 → 750；缓存 key 扩展为 (target, interval, date) 三维独立 | ✅ V0.64.0 |
| 健康检查 | `GET /api/v1/health` | ✅ |

---

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
├── models/              # SQLAlchemy 2.0 ORM（analysis / position / snapshot / settings / central_bank / account）
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
│   ├── news.py          # 消息面评分（沿用昨日 / 快捷档位）
│   ├── snapshot.py      # 每日评估快照服务
│   ├── settings.py      # 权重配置持久化
│   ├── central_bank.py  # 央行购金业务编排（T12M / Top / 范围筛选）
│   ├── cache.py         # served cache（首屏直接命中）
│   └── scheduler.py     # 每日 07:00 BJT 快照 + 央行月度 1/15/末日 07:30 BJT 自动拉取
├── repositories/
│   ├── market_data.py   # AKShare 数据源（ETF 新浪主/东财备 + SGE 克价 + 纽约金英为财情 + Mock 兜底）
│   ├── analysis.py      # 分析记录仓储
│   ├── position.py      # 持仓/流水仓储（账本过滤 + 多条件流水查询 + 分账本统计）
│   ├── account.py       # 账本仓储（默认账本自愈 / 重名校验 / 归档）
│   ├── snapshot.py      # 快照仓储
│   ├── settings.py      # 权重配置仓储
│   ├── central_bank.py  # 央行购金 DB CRUD（按国家/季度查询 + upsert）
│   ├── central_bank_data.py  # WGC HTML chart JS fetcher（季度合计 + H1 按国家）
│   └── db.py            # async 引擎与会话工厂
├── api/v1/endpoints/    # health / analysis / market / position / account / trades / decision / settings / snapshot / news / central_bank
├── scripts/             # CLI 工具（import_central_bank: WGC 数据全量导入）
└── utils/               # logger / market_clock / db_migrate（启动幂等补列）
static/                  # trend.html / portfolio.html / trades.html / weights.html / news.html / central_bank.html
                         #   + account.js（账本切换器）/ freshness.js / help.js / responsive.css
tests/                   # pytest（397 用例，含 fetcher / scheduler / 服务 / API / help / providers / cache / intraday / 业绩分析 / 多账本 / 多时间框架）
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

## 4. 快速开始

```bash
# 1) 安装依赖（uv 或 pip）
python -m pip install -e ".[dev]"

# 2) 启动服务（默认 127.0.0.1:8888）
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8888

# 3) 浏览器访问
#    趋势页：  http://127.0.0.1:8888/
#    API 文档：http://127.0.0.1:8888/docs
```

**测试与代码质量**

```bash
python -m pytest -v          # 397 用例（离线回归 365 passed，排除 2 个联网 fetcher 文件）：服务层 + API 集成 + scheduler / cache / intraday / help / providers / 业绩分析 / 多账本 / 多时间框架
ruff check src tests          # 静态检查
ruff format src tests         # 格式化
```

**Docker 部署**

```bash
docker compose up --build     # 同样映射 127.0.0.1:8888
```

---

## 5. API 参考

| 方法 | 路径 | 说明 | 关键参数 |
|------|------|------|----------|
| GET | `/` | 趋势追踪页 | - |
| GET | `/portfolio` | 个人交易跟踪与购买决策页 | - |
| GET | `/weights` | 评估权重配置页 | - |
| GET | `/news` | 消息面评估页 | - |
| GET | `/central-bank` | **世界央行购金统计页** | - |
| GET | `/trades` | **交易历史查询页** | - |
| GET | `/api/v1/health` | 健康检查 | - |
| GET | `/api/v1/market/health` | 数据源健康度统计 | - |
| GET | `/api/v1/market/freshness` | 三市场数据时效与交易时段 | - |
| POST | `/api/v1/analysis/opportunity` | 宏观机会评分 | body: `factors{dxy, us10y_yield, real_rate, inflation_expectation, risk_off}` |
| GET | `/api/v1/analysis/history` | 历史分析记录 | `limit`(1-100) |
| GET | `/api/v1/market/gold` | 黄金ETF最新报价 | - |
| GET | `/api/v1/market/gold/trend` | 趋势追踪 + 评估指数（**默认纽约金 COMEX 为投资指引基准**） | `days`(20-750)、`target`(ny/etf/gram，默认 ny)、`interval`(D/W/M，默认 D) |
| GET | `/api/v1/market/gold/ny-trend` | 纽约金 60 天趋势曲线（美元/盎司，等价于 `/gold/trend?target=ny`） | `days`(20-750)、`interval`(D/W/M，默认 D) |
| GET | `/api/v1/market/gold/compare` | ETF vs 黄金克价对照（归一化） | `days`(20-250) |
| GET | `/api/v1/market/gold/etf-quote` | **黄金ETF报价（元/份，估值与交易专用口径）** | - |
| POST | `/api/v1/positions` | 开仓买入 | body: `{symbol, quantity, price, fee}`；query: `account_id`（缺省=默认账本） |
| GET | `/api/v1/positions` | 持仓列表（实时盈亏） | `include_closed`、`account_id`（缺省=全部账本） |
| GET | `/api/v1/positions/export` | 持仓 + 流水 CSV 导出 | `account_id` |
| POST | `/api/v1/positions/{id}/trades` | 加仓/减仓 | body: `{side, quantity, price}` |
| POST | `/api/v1/positions/{id}/close` | 按市价清仓 | - |
| DELETE | `/api/v1/positions/{id}` | 软删除持仓（可撤销） | - |
| POST | `/api/v1/positions/{id}/restore` | 撤销软删除 | - |
| GET | `/api/v1/positions/{id}/trades` | 某持仓成交流水（倒序） | - |
| GET | `/api/v1/portfolio/equity-curve` | **账户收益曲线（流水+历史价回放，含最大回撤）** | `days`(20-250)、`account_id` |
| GET | `/api/v1/portfolio/performance` | **获利分析总结（已实现/浮动盈亏、胜率、盈亏比 + 中文总结）** | `account_id` |
| GET | `/api/v1/accounts` | 账本清单（含持仓/流水统计） | query: `include_archived` |
| POST | `/api/v1/accounts` | 新建账本 | body: `{name, note, is_default}` |
| PATCH | `/api/v1/accounts/{id}` | 改名 / 备注 / 排序 / 设为默认 | body: `{name?, note?, sort_order?, is_default?}` |
| POST | `/api/v1/accounts/{id}/archive` | 归档账本（数据保留） | - |
| POST | `/api/v1/accounts/{id}/restore` | 恢复已归档账本 | - |
| GET | `/api/v1/trades` | 交易历史查询（分页 + 汇总） | query: `account_id/side/position_id/symbol/keyword/start/end/page/page_size` |
| GET | `/api/v1/trades/export` | 交易历史 CSV 导出（含汇总） | 同上（无分页） |
| GET | `/api/v1/decision/etf` | 购买决策（趋势指数×持仓 + 仓位推荐 + 红绿理由） | `days`(20-250)、`account_id` |
| GET/PUT | `/api/v1/settings/weights` | 权重配置读取/保存 | body: `{tech, macro, news}` 等 |
| GET/PUT | `/api/v1/news-score` | 消息面打分（客户评估） | body: `{score, note}` |
| POST | `/api/v1/snapshots/capture` | 捕获当日评估快照 | - |
| GET | `/api/v1/snapshots` | 历史评估快照（自动补当日） | `limit` |
| GET | `/api/v1/central-bank/summary` | **央行购金摘要（T12M 总量 / 参与国数 / 最新季度）** | - |
| GET | `/api/v1/central-bank/top-buyers` | **某年度 Top N 买家** | `year`(2020-2030)、`limit`(1-20) |
| GET | `/api/v1/central-bank/purchases` | **央行购金明细（按国家 / 季度范围筛选）** | `from_q`、`to_q`、`country` |

### 5.1 机会分析示例

```jsonc
// POST /api/v1/analysis/opportunity
{
  "factors": {
    "dxy": 96.0, "us10y_yield": 3.6, "real_rate": 1.4,
    "inflation_expectation": 3.0, "risk_off": 9
  },
  "gold_price_usd": 2350.5
}
// 响应：score 94.5 / window "strong" / signal "bullish"
//       factors[] 每项含 direction（bullish/bearish/neutral）供红绿着色
```

### 5.2 趋势追踪示例

```jsonc
// GET /api/v1/market/gold/trend?days=60&interval=D  （默认 target=ny：纽约金 COMEX；target=etf/gram 返回对应市场；interval=D/W/M 支持多时间框架）
{
  "symbol": "GC", "name": "纽约金COMEX", "unit": "美元/盎司", "days": 60,
  "points": [/* 60 个 {date, close, ma5, ma20, ma40} */],
  "metrics": { /* start/end/change_pct/high/low/ma20/ma40/direction/summary */ },
  "indicators": [ /* 5 个维度 {name, value, score, direction, weight, contribution, detail} */ ],
  "index": { "score": 95.0, "level": "strong_up", "direction": "bullish", "summary": "..." }
}
```

---

## 6. 核心模型

### 6.1 宏观机会评分模型（PM-Evaluator 架构）

| 因子 | 权重 | 与黄金关系 | 友好度100分位 | 友好度0分位 |
|------|------|-----------|--------------|------------|
| 实际利率 | 35% | 强负相关 | 1.5% | 2.5% |
| 美元指数 DXY | 30% | 负相关 | 95 | 105 |
| 美债10Y收益率 | 15% | 负相关 | 3.5% | 4.5% |
| 通胀预期 | 10% | 正相关 | 3.0% | 2.0% |
| 避险情绪 | 10% | 正相关 | 10 | 0 |

- 综合评分 = Σ(因子友好度 × 权重)
- 窗口：`≥70 strong` / `≥55 medium` / `≥40 weak` / `<40 standby`
- 配置位置：`services/scoring.py::FACTOR_RULES`

### 6.2 市场趋势评估追踪指数

| 维度 | 权重 | 评分依据 |
|------|------|----------|
| 结构 | 30% | 均线排列（MA5/20/40 多空）+ MA20 斜率 |
| 动量 | 20% | 近 20 日涨跌幅 |
| 支撑 | 20% | 收盘价相对 MA20/MA40 乖离 |
| 动能 | 15% | RSI(14) |
| 回撤 | 15% | 距区间高点回撤 |

- 指数 = Σ(维度评分 × 权重)，0-100
- 等级：`≥75 强势上升` / `≥55 上升` / `≥45 震荡` / `≥25 下降` / `<25 弱势下降`
- 配置位置：`services/trend.py::TREND_WEIGHTS`

### 6.3 宏观参考指数（综合趋势指数 = 技术面 × 30% + 宏观面 × 40% + 消息面 × 30%）

| 因子 | 权重 | 与黄金关系 | 友好度100分位 | 友好度0分位 |
|------|------|-----------|--------------|------------|
| 美元指数 DXY | 25% | 负相关 | 95 | 105 |
| 美债10Y收益率 | 20% | 负相关 | 3.5% | 4.5% |
| 美债30Y收益率 | 15% | 负相关 | 4.0% | 5.0% |
| VIX恐慌指数 | 15% | 正相关（避险） | 25 | 12 |
| 国际央行购金量 | 25% | 正相关（结构性） | 1200吨/年 | 500吨/年 |

- 宏观参考指数 = Σ(因子友好度 × 权重)，0-100；**随宏观参数动态变化**（美债实时采集 `bond_zh_us_rate`，美元指数/VIX 静态参考值，央行购金为年度数据）
- 综合趋势指数 = 技术面 × 30% + 宏观面 × 40% + 消息面 × 30%（`services/macro.py::TECH_WEIGHT/MACRO_WEIGHT/NEWS_WEIGHT`，用户可在 `/weights` 调整）

---

## 7. 数据源

| 标的 / 层级 | 说明 |
|------|------|
| 纽约金（COMEX GC，指引基准） | 主源 AKShare `futures_foreign_hist`（英为财情）｜ 备选 `futures_global_hist_em`（东方财富 GC00Y）｜ 美元/盎司 |
| 上海金（SGE Au99.99） | AKShare `spot_hist_sge`（上海黄金交易所）｜ 元/克，作国内对照 |
| 黄金 ETF（518880） | 主源 AKShare `fund_etf_hist_sina`（新浪）｜ 备选 `fund_etf_hist_em`（东方财富）｜ 元 |
| 宏观 5 因子 | 美元指数 / 美债 10Y·30Y（实时采集 `bond_zh_us_rate`）/ VIX |
| **央行购金（V0.57.0 升级）** | **WGC Gold Demand Trends HTML chart JS（`fsapi.gold.org/api/v12/charts/js/...`）**——绕开 XLSX 403 反爬；季度合计 2014Q1–2026Q2 + H1 2026 按国家 + UZB/IRN 手工补丁；月度 1/15/末日 07:30 BJT 自动从 WGC 拉取并 upsert 到 `central_bank_purchases` 表；cb_gold 宏观因子从表汇总 T12M，无数据时回退 STATIC_REF（1019 吨/年） |
| 兜底 | 数据源三态：实时 `live` / 磁盘缓存 `stale` / 演示 `mock`（页面顶部状态条 + 健康度可见） |

> 采集策略：AKShare 为同步阻塞库，经 `asyncio.to_thread` 放入线程池；按源分锁（`etf`/`sge`/`ny`）并发采集避免 V8 全局锁崩溃；统一 30s 超时快速失败而非挂起；内存 + 独立 SQLite 双写缓存（TTL 300s，冷启动 ~1.6s）。WGC fetcher 走异步 HTTP（`httpx.AsyncClient`），同样 30s 超时。

---

## 8. 配置说明（.env）

```ini
APP_NAME=gold-etf-analyzer
APP_ENV=dev            # dev/prod/test
DEBUG=true             # 开发期打印 SQL
DATABASE_URL=sqlite+aiosqlite:///./data/gold_etf.db
CORS_ORIGINS=*         # 逗号分隔，* 表示全部放行（仅开发）
```

> `.env` 不入库（.gitignore）；`data/`、`*.db` 同样排除。

---

## 9. 测试

216 + 63 + 24 + 13 + 18 + 43 + 20 = 397 个用例（`pytest --collect-only -q`，34 个文件）覆盖：

- **服务层**：宏观评分引擎（权重归一/多空映射/逐因子方向，含 cb_gold 注入中央银行服务）、趋势服务（均线/方向/指数合成/数据不足异常）、消息面、快照、决策、设置、央行购金（T12M / Top / 范围筛选）、**业绩分析（交易流水回放 / 收益曲线 / 平仓统计 / 空仓与除零边界）**
- **API 层**：机会分析（评分/历史/参数校验 422）、行情（报价/趋势 `target` 三市场/维度校验/健康度/时效/**ETF 报价口径**）、决策、持仓（开仓/加减仓/清仓/软删除/撤销/导出/**流水查询**）、**业绩（收益曲线区间校验 / 获利分析）**、快照、消息面、央行购金（3 个 endpoint）、健康检查
- **数据层**：WGC fetcher（`_parse_chart_series` / `_iso_for_country` / `_find_country_chart` / `load_manual_overrides` / 端到端 mock 32 项）、市场时段判定、SQLite 启动幂等补列
- **调度层**：央行购金月度调度时间计算（月末动态 28/29/30/31 天 / 年切换 / 环境变量开关 13 项 / 循环节流）
- 主体用例通过 `FakeRepo` 注入假数据源，**离线可跑**：V0.64.0 实测 `python -m pytest -q --ignore=tests/test_services/test_irfcl_fetcher.py --ignore=tests/test_services/test_h15_fetcher.py`（排除 2 个联网 fetcher 文件 44 用例）**365 passed / 0 failed**
- **例外（既有问题，非本版本引入）**：`tests/test_services/{test_irfcl_fetcher,test_h15_fetcher}.py` 共 44 用例，实测 **43 passed / 1 skipped**——跳过项 `test_load_manual_overrides_returns_uZB_and_irn` 依赖本地数据文件 `data/central_bank_manual_overrides.json`（位于 `.gitignore` 内，新克隆不携带）；已加 `skipif` 守卫（文件缺失即跳过，不再误报 failed）
- **前端**：`python scripts/check_static_js.py`（或 `make check-web`）对 **6 个静态页面**的内联 JS + **3 个共享脚本**（`account.js` / `freshness.js` / `help.js`）做语法 / 未定义调用 / DOM id 一致性校验——前端无构建步骤，这道门禁用于拦下「JS 写错导致整页脚本失效」的问题

---

## 10. 版本历史

| 版本 | 内容 | 主题 | 状态 |
|------|------|------|------|
| **V0.10**（已发布 v0.10.0） | FastAPI 分层骨架、宏观机会评分、SQLite 持久化、Mock 行情、12 测试 | 骨架 | ✅ |
| **V0.11**（已发布 v0.11.0） | AKShare 数据源、2 个月趋势追踪、趋势评估指数、可视化页面、**个人交易跟踪（持仓/盈亏）、购买决策引擎、ETF vs 克价对照、纽约金 60 天曲线、指数置顶+运算方法展示**、41 测试 | 三市场 + 交易闭环 | ✅ |
| **V0.20**（已发布 v0.20.0） | **三面评估体系**（技术 30%/宏观 40%/消息面 30%）、**消息面评估页**（客户投行展望打分化）、**权重配置页**（持久化）、**每日评估快照**（daily_snapshots 本地历史）、宏观参考因子（美元/美债/VIX/央行购金）、**仓位推荐**（评估指数→建议仓位）、数据源 30s 超时兜底、统一顶部导航、投资警示五条、本机常驻（start_server.bat 一键自愈 + install_startup.ps1）、56 测试 | 三面评估 + 易用 | ✅ |
| **V0.50**（已发布 v0.50.0） | **易用性**：今日操作清单引导、消息面打分提醒/快捷档位/沿用上次、持仓录入简化（金额↔份数/快捷比例）、纽约金昨日与 5 日涨跌；**稳定性**：服务看门狗自愈 + 开机自启（启动文件夹）；**可信度**：数据源三态标识（实时/缓存/演示）+ 健康度统计 + 备源与 stale 兜底；**性能**：行情缓存持久化（冷启动 1.6s）、分源并发采集（-39%）、SQLite WAL + 索引；**数据保障**：快照定时采集（06:00/16:00）、数据库自动备份（保留 7 份）、超期快照归档；**工程**：Alembic 正式迁移、配置内存缓存、66 测试 | 稳定可信·高效省心 | ✅ |
| **V0.51** | **投资指引基准切换为纽约金（COMEX GC）**：趋势追踪指数、购买决策、每日快照均以纽约金为基准（连续交易、夜盘覆盖国内休市，对国内金价具领先指示意义）；ETF/上海金作为国内对照与交易标的。前端主趋势面板改显纽约金（美元/盎司），新增上海金 Au99.99（元/克）国内对照面板，`/gold/trend` 支持 `target` 参数（ny/etf/gram），67 测试 | 指引基准统一 | ✅ |
| **V0.51.1** | **启动健壮性修复**：移除 Alembic 前的冗余 `create_all`，消除 SQLite 双引擎争写锁导致启动 hang；新增 WAL checkpoint（防异常退出遗留锁）+ 迁移 30s 超时兜底；启动后后台预热行情缓存使首屏直接命中；前端 `fetch` 增加 40s 超时与失败可见态，避免页面静默空白 | 启动/加载可靠性 | ✅ |
| **V0.52.0** | **数据时效透明（UX Roadmap 6.1）**：新增 `utils/market_clock.py`（纽约金 CME Globex / 上海金 SGE / ETF 三时段判定 + 时效分级）、`services/freshness.py`（FreshnessService）与 API `GET /api/v1/market/freshness`；趋势接口 `GET /api/v1/market/gold/trend` 内嵌 `freshness` 字段；前端 `static/freshness.js` 全站时效条（60s 刷新），降级持续角标；启动期 Alembic 子进程化消除死锁 | 数据可信 / 启动可靠 | ✅ |
| **V0.53.0** | **响应式与移动端适配（UX Roadmap 6.2）**：新增共享 `static/responsive.css`（768/480/360 三档媒体查询断点）并在趋势/持仓/权重/消息四页注入，使窄屏下顶栏换行、追踪面板与导航网格纵向堆叠、固定宽列收窄、表单输入满宽、持仓表格容器内横向滚动、按钮触控放大、时效条超小屏微调，关键指标首屏置顶；6.1 数据时效透明能力同步收敛进响应式体系 | 多端可用 | ✅ |
| **V0.54.0** | **决策可解释性增强（UX Roadmap 6.3）**：`schemas/position.py` 新增 `ReasonItem(text, direction)`，`DecisionOut` 增加 `reason_items`（保留 `reasons` 向后兼容）；`services/decision.py` 为每条理由标注 `bullish`/`bearish`/`neutral`（参数面按指数方向、交易面按盈亏、决策依据按行动、仓位建议标中性）；前端 `portfolio.html` 渲染红绿对照条（`.bullish` 红 / `.bearish` 绿 / `.neutral` 灰，含「利多/利空/中性」标签）+ 指数构成（技术/宏观/消息）堆叠条可视化 | 决策看得懂 | ✅ |
| **V0.55.0** | **操作闭环防错与撤销（UX Roadmap 6.4）**：开仓/加仓/减仓/清仓统一 `confirmDialog()` 二次确认弹窗（数量/价格/手续费/预估金额摘要，危险态标红）；`validateTrade()` 前端范围校验；持仓软删除（`models/position.py` 加 `deleted_at`，`utils/db_migrate.py` 启动幂等补齐）+ `DELETE /positions/{id}` + 8 秒内「撤销」→ `POST /{id}/restore`；新增 `GET /api/v1/positions/export` 导出持仓+流水 CSV（UTF-8 BOM）；前端 `API_BASE` 改同源，修复此前写死指向已死 8888 端口导致接口全失败的问题 | 操作不翻车 | ✅ |
| **V0.56.0** | **主动提醒与推送（UX Roadmap 6.6，前端侧）**：持仓决策页新增「🔔 提醒」开关（`localStorage` 记忆 `pm_alert_on`，默认关）；开启时请求 `Notification` 授权；每 60s 轮询 `decision` + `gold`，`checkAlerts()` 比较评估指数档位与纽约金价格：档位切换或金价波动 ≥2% 时，触发浏览器通知 + 顶部 `alertBar`（6s 自动消失）；`renderBriefing()` 在决策区下方常驻「今日简报」一句话摘要。邮件/微信推送因需外部服务与密钥，本期未做 | 主动触达 | ✅ |
| **V0.57.0** | **世界央行购金统计独立页面 + 月度自动调度**：新增 `/central-bank` 页面（4 KPI 卡 + Chart.js 堆叠柱状图 + Top 10 + 按国家/季度范围筛选明细表）+ `GET /api/v1/central-bank/{summary,top-buyers,purchases}` 三个 endpoint。数据源由 IMF IRFCL（不可达）切到 **WGC Gold Demand Trends HTML chart JS**（`fsapi.gold.org/api/v12/charts/js/...`，绕开 XLSX 403 反爬），覆盖全球合计 2014Q1–2026Q2（52 季度）+ H1 2026 按国家（19 买家 + 4 卖家）+ UZB/IRN 手工补丁。`cb_gold` 宏观因子从表自动汇总 T12M（无数据回退 STATIC_REF）。**月度自动调度**：每月 1/15/末日 07:30 BJT 由 `services/scheduler.py` 自动从 WGC 拉取（`calendar.monthrange()` 动态月末，`CENTRAL_BANK_AUTO_REFRESH` 环境变量开关）。三层测试覆盖（fetcher 32 + scheduler 26 + 集成），216 测试通过；顺手修复 `ensure_sqlite_columns` 跳过不存在表（部分老库启动不再崩溃） | 央行购金数据化 + 自动化 | ✅ |
| **V0.58.0** | **新手引导与帮助体系（UX Roadmap 6.8）**：新增 `static/help.js`（~480 行，自包含 IIFE，挂在 `window.PM_Help`）+ `static/help.css`（暗色主题 + 移动端 <768px modal 改为底部抽屉）。右下角悬浮 `?` 按钮唤起 3 tab modal（**操作指南**每日 5 步流程 / **术语速查**30+ 术语按 7 大类分组：评估指数/指标均线/宏观因子/品种代码/交易动作/系统状态/时段 / **数据来源**5 类数据源 + 投资警示 + 交易时段 + 采集容错）。首次访问 5 个页面自动弹 2-4 步 **tour 浮层**（蒙层 + 高亮 + 步骤切换），`localStorage.pm_help_seen_version` 升级时强制重看。15 项关键术语 inline `?` 图标自动注入（综合指数/MA5·MA20·MA40/RSI(14)/T12M/Au99.99/COMEX/518880/仓位推荐 等）。5 个 HTML 页面各 +2 行注入。63 项新测试（`tests/test_help/test_glossary.py` + `test_modal.py`，后者通过 Node 子进程沙箱执行 JS 验证 escapeHtml 与 XSS 防护）。279 测试全通过 | 新手引导 + 帮助体系 | ✅ |
| **V0.59.0** | **行情源 provider 配置化（P1 #5）**：`repositories/market_data.py` 重构为 Provider 抽象入口，新增 `repositories/market_providers.py` 工厂模块。3 个窄接口（GoldHistoryProvider / GoldLiveQuoteProvider / TreasuryYieldProvider）+ `MarketProviderBundle` 三件套 + `build_provider_bundle(settings)` 工厂；4 个内置 provider：**akshare**（默认：东财 ETF 主 + 新浪 ETF 备 + 英为财情外盘 + gold-api 实时 + H.15 美债，全部免费零 KEY）/ **mock**（确定性序列，纯内存、零依赖、零网络）/ **eastmoney_only**（仅东财，省去新浪子进程开销）/ **sina_only**（仅新浪，适用东财 403 场景）。`.env` 配置 `MARKET_PROVIDER=akshare\|mock\|eastmoney_only\|sina_only`，启动时一次性读取；`XAU_FALLBACK_CHAIN=goldapi,sina,etf_history` 与 `QUOTE_CACHE_TTL=300` 也可配；旧 `MarketDataRepository(provider=...)` 签名保留向后兼容（旧测试零改动）。24 项新测试覆盖：工厂解析（4 provider 名 + 大小写 + 未知名抛错 + 空回退默认）+ Mock provider 数据正确性 + bundle 注入 + XAU chain 解析 + cache_ttl=0 禁用 + 5 mock 取数集成。303 测试全通过（279 → 303） | 行情源配置化 | ✅ |
| **V0.60.0** | **行情实时性增强（D + B）**：① 后端死代码启用：`repositories/market_data.py` 6 个接口（`get_gold_history` / `get_gold_gram_history` / `get_us_gold_history` / `get_gold_quote` / `get_gold_gram_quote` / `get_us_gold_quote`）启用 `quote_cache_ttl=300` 进程级 cache（V0.59.0 之前是死代码），cache hit 时**不调** `_mark` 保留 `_fetched_at`；② served cache 日内 TTL：`services/cache.py` value 由 `GoldTrendOut` → `(GoldTrendOut, set_at)` 元组；`get_served` 新增 keyword-only `max_age_seconds`（默认 600s，可由 `.env` 配 `SERVED_CACHE_TTL_SECONDS`），超期返回 None 强制重算，旧调用方不传 → 行为完全不变；③ `source_status()` 按 `_fetched_at + cache_ttl` 派生 `"stale"` 状态（不改 `_mark`），前端 freshness 角标"缓存过期"分支自然点亮；④ 日内多次预热：`services/scheduler.py` `daily_capture_loop` 内部串联 `next_intraday_run_utc`（默认 09:30 / 11:30 / 14:00 / 15:30 BJT，可由 `.env` 配 `INTRADAY_REFRESH_HOURS`，`INTRADAY_REFRESH_ENABLED=false` 关闭），取 `min(next_daily, next_intraday)` 最近点触发（`intraday_warm_once` 仅刷新 served cache 不落库）；⑤ 前端轮询：`trend.html` `setInterval(refreshTrendQuotes, 60_000)` + `visibilitychange` 切回前台自动刷新 + 右上角手动 🔄 按钮（带旋转动画）；`portfolio.html` 60s → 30s + `visibilitychange` + 同步 `FreshnessBar.load()`；⑥ `tests/conftest.py` `_reset_db` fixture 同时清空 `_CACHE`（行情 cache）保证跨测试隔离；13 项新测试覆盖（5 cache hit/expire/disabled/key-isolation/stale-promotion/mock-keep + 4 served TTL set/max_age/zero-disable/old-signature + 2 intraday 时间计算/异常静默 + 1 writes-served-cache + 1 stale 派生 + 1 mock 保持）；316 测试全通过（303 → 316） | 行情实时性 | ✅ |
| **V0.61.0** | **交易闭环与业绩分析**：① P0 修复 **ETF 报价口径错配**——新增 `MarketDataRepository.get_gold_etf_quote()`（518880 元/份，与收益曲线同源）与 `GET /market/gold/etf-quote`（返回 `price` + `currency`/`unit`），`PositionService._current_price()` 改用它（此前误用 XAU/USD 4349.7 美元/盎司当作 9 元/份，持仓收益率虚高至 46670%）；② **加仓 / 减仓内联交易面板**（金额↔份数、快捷比例、一键取现价、摊薄成本与已实现盈亏预览，替代 `prompt()`）+ `GET /positions/{id}/trades`；③ **收益曲线** `GET /portfolio/equity-curve?days=7..730`——交易流水 + ETF 历史价回放重建（不新增表，`bisect` 把非交易日成交顺延），含最大回撤 / 区间最高最低；④ **获利分析** `GET /portfolio/performance`——胜率 / 盈亏比 / 最佳最差平仓 / 平均持仓天数 + 中文复盘；⑤ **手续费口径统一**（回放成本不含 fee，与 `add_trade` 摊薄成本一致），修正同页两个收益率（-4.29% vs -4.25%）；⑥ 新增 `scripts/check_static_js.py` 前端内联 JS 门禁（`make check-web`）；334 测试通过（316 → 334） | 交易闭环与业绩分析 | ✅ |
| **V0.64.0**（当前） | **多时间框架（周/月线趋势，P2 #9）**：趋势页 K 线主图加 3 档区间按钮（60D / 52W / 24M）—— ① 后端抽 730 天日 K 后按 ISO 周界聚合到 ~52 根周 K / 按年月聚合到 ~24 根月 K；② MA 在聚合后序列上重算（周线 MA5≈1 交易月、MA20≈季线、MA40≈半年线）；③ W/M 模式技术面 5 维度旁路（指标对日 K 敏感），宏观与消息面仍正常合成综合指数；⑤ `/gold/trend?interval=W\|M` + `days` 上限 250 → 750；⑥ 缓存 key 扩展为 (target, interval, date) 三维独立（避免 W/M 结果被 D 请求误命中）；⑦ 趋势页 `trendChart.destroy()` 内存管理（仿 V0.63.0 snapChart 模式）；⑧ 60s 轮询只刷日 K，避免每分钟重画周/月。新增 14 个测试（服务 4 个：默认 D / W 聚合 + 技术面旁路 / M 聚合 + MA 重算 / 非法 interval 回退；API 4 个：W 52 点 / M 24 点 / interval=X 422 / days 上限 750；工具 6 个：日 K identity / 周聚合 ISO 周界 / 月聚合跨年 / 单点桶 / volume 求和 / 空输入兜底）；397 用例通过（383 → 397），离线回归 **365 passed / 0 failed**（排除 2 个联网 fetcher 文件 32 用例） | 多时间框架 | ✅ |
| **V0.63.0** | **评估指数历史曲线升级（P2 #14 起步）**：趋势页『每日评估历史』面板前端增强，**后端零改动**——① **第 4 条曲线**：新增 `news_index` 消息面线（紫色虚线），4 条线反映完整综合指数构成（综合 / 技术 / 宏观 / 消息面）；② **区间切换**：`7D / 30D / 90D` 三档按钮（参考 portfolio 收益曲线 `EQUITY_RANGES` 模式），调用 `/api/v1/snapshots?days=N` 重新渲染；③ **4 个极值卡**：最新（带档位）/ 区间最高（附日期）/ 区间最低（附日期）/ 日变（↑↓→ 红绿色），用现有 `.cards` 网格；④ **稀疏数据 3 档 UX**：< 3 天「样本不足，趋势尚不显著」+ 隐藏极值卡；< 7 天「仅 N 天数据」；≥ 7 天默认；⑤ **chart.destroy 内存管理**：`snapChart` 模块级变量 + 渲染前 `snapChart?.destroy()` 防内存泄漏；⑥ **空数据兜底**：`!s.snapshots.length` 时 destroy 旧 chart + 隐藏极值卡 + 子标题改为「暂无快照数据（每日 07:00 BJT 自动捕获）」。新增 6 个测试（API 4 个：days=1/365/校验 + news_index 字段存在；服务 2 个：news_index 字段存在 + 无重复日期）；383 用例通过（377 → 383），离线回归 **339 passed / 0 failed**（排除 2 个联网 fetcher 文件 44 用例） | 指数曲线可视化 | ✅ |
| **V0.62.1** | **收益回放口径修复（验证阶段发现）**：修复 `PortfolioAnalyticsService._replay()` 的**静默丢单** —— 成交日晚于价格序列最后一个交易日时（**行情源 T-1 滞后、盘中录入、周末/节假日录入**均会触发），`bisect.bisect_left` 返回 `len(price_dates)`，原逻辑 `if idx < len(price_dates)` 直接跳过该笔交易。后果是同一响应内口径自相矛盾：**`sell_count=2` 却 `closed_trades=0`、胜率 0%**，「累计投入本金」显示 **0.00 元**、已实现盈亏归零，与持仓页看到的实时持仓完全冲突。现改为把行情未覆盖的成交**归入最后一个可得交易日**（`idx > last_idx → last_idx`），累计投入 / 已实现盈亏 / 胜率 / 盈亏比恢复正确，收益曲线同步受益。新增 2 项回归测试（`test_equity_curve_trade_after_last_price_date_kept`、`test_performance_trade_after_last_price_date_not_zero`，后者显式断言 `sell_count == closed_trades` 自洽）；377 用例收集（375 → 377） | 业绩口径可信 | ✅ |
| **V0.62.0** | **单用户多账本 + 交易历史查询页（P1 #6，P1 收官）**：① `accounts` 表（`models/account.py`）+ `positions.account_id`（迁移 `b8e14c7a2f36`，幂等 seed id=1「默认账户」并把历史持仓归入该账本，`db_migrate.py` 同步补列兜底，lifespan `_ensure_default_account()` 自愈）；② `AccountRepository` / `AccountService`（默认账本保障、重名校验、**默认账本不可归档**、**仍有未平仓持仓不可归档**、归档后 `resolve()` 仍可访问以便查询历史）；③ `/api/v1/accounts` 六个端点（list / create / get / patch / archive / restore，list 内嵌持仓与流水统计）；④ `/api/v1/trades` + `/api/v1/trades/export`：按账本 / 方向 / 日期区间 / 持仓 / 关键字筛选 + 分页，**均价法逐笔回放**给出每笔卖出的「已实现盈亏」与「成交后份额」，汇总覆盖全部匹配行；⑤ **回放取完整 scope**（side / 日期过滤只作用于展示）——否则按「卖出」筛选时会丢失买入上下文导致盈亏全部算不出（已加回归测试）；⑥ 账本上下文贯通 `positions` / `portfolio` / `decision`（`?account_id=`，`static/account.js` 全站切换器 + localStorage 记忆 + 「全部账本」合并视图，写操作落 `targetAccountId()`）；⑦ 新增 `/trades` 页面（筛选 / 汇总 KPI / 明细 / 分页 / CSV）与 `portfolio.html` 账本管理面板；⑧ `check_static_js.py` 增强（覆盖 `static/*.js` 语法 + 识别共享脚本注入的 DOM id）；375 用例收集（334 → 375，含决策 `account_id` 透传回归）；离线回归实测 **331 passed / 0 failed**（29m45s，排除 2 个联网 fetcher 文件 44 用例） | 多账本与交易历史（P1 收官） | ✅ |

---

## 11. 下一阶段改进计划

> 状态图例：✅ 已完成 ｜ ⏳ 进行中 ｜ 📋 待办
>
> 易用性专项改善路径（V0.20 现状评估 + P0-P3 方案与版本规划）：[improvement-path.md](improvement-path.md)
> 用户体验（UX）专项改进方向（数据时效/响应式/可解释性/主动提醒等）：见 [improvement-path.md](improvement-path.md) 第六章。

### P1 · 近期（1-2 周）—— 工程化收口

| # | 事项 | 状态 | 价值 |
|---|------|------|------|
| 1 | 发布 **V0.50**（commit + `v0.50.0` 标签推送 GitHub） | ✅ | 固化易用性/稳定性/可信度/性能/数据保障/工程全链路优化 |
| 2 | **权重配置页** `/weights.html`：趋势 5 维度权重 + 决策「技术面 vs 消息面」合成权重可调（持久化 app_settings） | ✅ | 用户可定制评估逻辑 |
| 3 | **CI/CD**：GitHub Actions 自动跑 pytest + ruff，tag 触发自动构建 | 📋 | 质量门禁 |
| 4 | **Alembic 数据库迁移**（替代启动时 create_all） | ✅ | V0.50 已落地（async 模板 + baseline；启动编程式 `upgrade head`，失败回退 `create_all`） |
| 5 | 行情源**配置化**（.env 切换 sina/em/investing/mock） | ✅ | **V0.59.0 已落地**（`.env` 配 `MARKET_PROVIDER=akshare\|mock\|eastmoney_only\|sina_only` + `market_providers.py` 工厂 + bundle 注入）；文档此处曾长期停留 📋，已修正 |
| 6 | 交易面**多账户**（user_id 已预留）与交易历史查询页 | ✅ | **V0.62.0 已落地**：单用户多账本（`accounts` 表 + `positions.account_id`）+ `/api/v1/accounts` 增改归档 + `/api/v1/trades` 多条件查询与 CSV 导出 + 全站账本切换器 |

### P2 · 中期（1-2 月）—— 分析深度

| # | 事项 | 状态 | 价值 |
|---|------|------|------|
| 7 | **宏观 × 技术共振**：宏观机会评分叠加趋势页，双维度信号（共振/背离），消息面权重生效 | 📋 | 核心差异化能力 |
| 8 | **克数持仓跟踪**：实物金/积存金按克持仓，与 ETF 持仓并列盈亏对照 | 📋 | 「买克数」完整闭环 |
| 9 | **多时间框架**：周线/月线趋势与指数 | 📋 | 中期趋势判断 |
| 10 | **指数参数校准**：用历史数据回测权重与阈值 | 📋 | 模型可信度 |
| 11 | 多品种扩展：白银 ETF / 现货 | 📋 | 贵金属全景 |

### P3 · 长期（2-3 月）—— 产品化

| # | 事项 | 状态 | 价值 |
|---|------|------|------|
| 12 | **仓位建议**：结合账户本金估算仓位占比（position_ratio） | 📋 | 投资闭环 |
| 13 | **模拟交易 + 回测引擎** | 📋 | 策略验证 |
| 14 | **指数时间序列**：追踪指数历史曲线，观察趋势演化 | 📋 | 可视化增强 |
| 15 | **监控告警**：数据源失败告警、价格异动提醒 | 📋 | 运维保障 |
| 16 | **公开部署**：域名 + HTTPS（遵循分阶段发布：内部 → 公开发布） | 📋 | 对外服务 |

> 已在 V0.11 完成：AKShare 三市场数据源（ETF 新浪/东财、上海金 SGE、纽约金英为财情）、趋势追踪 + 评估指数、交易面（持仓/流水/盈亏）、购买决策引擎、ETF vs 克价对照、纽约金 60 天曲线、指数置顶与运算方法展示、网站命题更新、akshare 并发稳定性修复（全局串行锁）、41 测试。
>
> 状态补遗（截至 V0.64.0）：
> - P1 #1（V0.50 发布）→ ✅；#2 权重配置页 → ✅；#4 Alembic → ✅；#5 行情源配置化 → ✅（V0.59.0）；#6 多账户 + 交易历史查询页 → ✅（V0.62.0）；**#3 CI/CD 仍 📋（P1 唯一未完成项）**
> - P2 #7 宏观×技术共振 / #8 克数持仓 / #10 参数回测校准 / #11 多品种 → 均 📋 未做；**#9 多时间框架（周/月线趋势）→ ✅ V0.64.0**
> - P3 #12 仓位推荐（80/60/40/20/10%）已实现但**未结合账户本金**（#12 半成品）；#13 模拟交易与回测引擎 → ❌ 未做；#14 评估指数自身曲线（V0.63.0 综合/技术/宏观/消息面 4 条线 + 区间切换 + 极值卡）+ 账户收益曲线（V0.61.0）已落地，#14 ✅；#15 浏览器通知已做（V0.56.0 6.6）但**邮件/微信推送未做**（#15 半成品）；#16 公开部署 → ❌ 未做（当前 `127.0.0.1:8888` 仅本机）
> - UX 6.5 个性化与上下文记忆 → ❌ 未做（多账本 V0.62.0 已部分覆盖「标的/账本记忆」语义）；6.7 多时间框架 → 🟡 部分（V0.61.0 收益曲线 + V0.64.0 K 线主图多时间框架已落地，权重回测未做）；6.9 加载与离线 → 🟡 部分（进度条 + 轮询已做，Service Worker 离线缓存未做）

---

## 12. 备注

- 本应用输出为**研究参考**，不构成投资建议。
- 权重与阈值为典型经验值（rule-based），随数据积累逐步用回测校准。
- 数据来源：AKShare（东方财富 / 新浪财经 / 上海黄金交易所 / 英为财情 / 中债收益率）+ WGC Gold Demand Trends（央行购金月度统计，HTML chart JS 自动抓取），第三方接口可能变化，已做降级容错。
