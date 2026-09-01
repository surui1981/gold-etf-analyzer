# 黄金价格投资辅助工具 · 说明文档

> 项目名：`gold-etf-analyzer` ｜ 当前版本：**V0.51**
> 命题：面向个人黄金投资者（中短期 ETF 波段），三市场对照（纽约金/上海金/黄金ETF）+ 综合趋势评估指数（技术/宏观/消息面）+ 持仓跟踪 + ETF购买决策
> 技术栈：FastAPI + Pydantic v2 + SQLAlchemy 2.0 (async) + AKShare
> 仓库：https://github.com/surui1981/gold-etf-analyzer（Private）

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
| 趋势追踪 | `GET /api/v1/market/gold/trend?days=60` 价格序列 + MA5/20/40 + 方向 | ✅ |
| 纽约金曲线 | `GET /api/v1/market/gold/ny-trend?days=60` COMEX 黄金期货 60 天曲线 | ✅ |
| 趋势评估指数 | 5 维度加权合成 0-100 指数（结构/动量/支撑/动能/回撤） | ✅ |
| 宏观参考因子 | 美元指数/美债10Y·30Y/VIX/央行购金 → 宏观参考指数，与技术面合成综合指数 | ✅ |
| 权重配置 | `GET/PUT /settings/weights` + `/weights` 页面：技术面/宏观面/合成比三组权重可调 | ✅ |
| 每日快照 | `POST/GET /snapshots`：每日参数+评估值本地持久化（daily_snapshots 表），指数历史序列 | ✅ |
| 个人交易跟踪 | `POST/GET /api/v1/positions` 开仓/持仓/加仓/减仓/清仓，实时盈亏 | ✅ |
| 购买决策引擎 | `GET /api/v1/decision/etf` 参数面×交易面 → 买入/加仓/持有/减仓/卖出 | ✅ |
| ETF vs 克价对照 | `GET /api/v1/market/gold/compare` 518880 vs 上海金Au99.99 归一化对照 | ✅ |
| 可视化页面 | 趋势页 `/static/trend.html`（含对照区块）+ 持仓决策页 `/static/portfolio.html` | ✅ |
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
├── main.py              # 入口：路由装配、CORS、lifespan、静态文件
├── config.py            # pydantic-settings 配置（.env / 环境变量）
├── dependencies.py      # 依赖注入容器（测试可整体替换）
├── models/              # SQLAlchemy 2.0 ORM（analysis_records）
├── schemas/             # Pydantic v2 请求/响应模型 + 枚举
├── services/
│   ├── scoring.py       # 宏观机会评分引擎（FACTOR_RULES）
│   ├── trend.py         # 趋势分析 + 追踪指数（TREND_WEIGHTS）
│   ├── decision.py      # 购买决策引擎（趋势×持仓规则矩阵）
│   ├── position.py      # 交易面：开仓/加减仓/清仓/盈亏
│   ├── compare.py       # ETF vs 克价对照
│   └── analysis.py      # 机会分析编排（评分 + 落库）
├── repositories/
│   ├── market_data.py   # AKShare 数据源（ETF 新浪主/东财备 + SGE 克价 + Mock 兜底）
│   ├── analysis.py      # 分析记录仓储
│   ├── position.py      # 持仓/流水仓储
│   └── db.py            # async 引擎与会话工厂
├── api/v1/endpoints/    # health / analysis / market / position / decision
└── utils/logger.py      # 统一日志
static/                  # trend.html（趋势+对照） / portfolio.html（持仓决策）
tests/                   # pytest（39 用例）
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
python -m pytest -v          # 21 个用例
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
| GET | `/api/v1/health` | 健康检查 | - |
| POST | `/api/v1/analysis/opportunity` | 宏观机会评分 | body: `factors{dxy, us10y_yield, real_rate, inflation_expectation, risk_off}` |
| GET | `/api/v1/analysis/history` | 历史分析记录 | `limit`(1-100) |
| GET | `/api/v1/market/gold` | 黄金ETF最新报价 | - |
| GET | `/api/v1/market/gold/trend` | 趋势追踪 + 评估指数 | `days`(20-250) |
| GET | `/api/v1/market/gold/ny-trend` | 纽约金 60 天趋势曲线（美元/盎司） | `days`(20-250) |
| GET | `/api/v1/market/gold/compare` | ETF vs 黄金克价对照（归一化） | `days`(20-250) |
| POST | `/api/v1/positions` | 开仓买入 | body: `{symbol, quantity, price, fee}` |
| GET | `/api/v1/positions` | 持仓列表（实时盈亏） | - |
| POST | `/api/v1/positions/{id}/trades` | 加仓/减仓 | body: `{side, quantity, price}` |
| POST | `/api/v1/positions/{id}/close` | 按市价清仓 | - |
| GET | `/api/v1/decision/etf` | 购买决策（趋势指数×持仓） | `days`(20-250) |

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
// GET /api/v1/market/gold/trend?days=60
{
  "symbol": "518880", "name": "黄金ETF华安", "days": 60,
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

### 6.3 宏观参考指数（综合趋势指数 = 技术面 × 60% + 宏观面 × 40%）

| 因子 | 权重 | 与黄金关系 | 友好度100分位 | 友好度0分位 |
|------|------|-----------|--------------|------------|
| 美元指数 DXY | 25% | 负相关 | 95 | 105 |
| 美债10Y收益率 | 20% | 负相关 | 3.5% | 4.5% |
| 美债30Y收益率 | 15% | 负相关 | 4.0% | 5.0% |
| VIX恐慌指数 | 15% | 正相关（避险） | 25 | 12 |
| 国际央行购金量 | 25% | 正相关（结构性） | 1200吨/年 | 500吨/年 |

- 宏观参考指数 = Σ(因子友好度 × 权重)，0-100；**随宏观参数动态变化**（美债实时采集 `bond_zh_us_rate`，美元指数/VIX 静态参考值，央行购金为年度数据）
- 综合趋势指数 = 技术面 × 60% + 宏观参考 × 40%（`services/macro.py::TECH_WEIGHT/MACRO_WEIGHT`）

---

## 7. 数据源

| 层级 | 说明 |
|------|------|
| 主源 | AKShare `fund_etf_hist_sina`（新浪，多数网络可达，含本沙箱） |
| 备选 | AKShare `fund_etf_hist_em`（东方财富，部分网络被代理拦截） |
| 兜底 | 内置 Mock 确定性序列（离线演示，保证应用可用） |

> 说明：AKShare 为同步阻塞库，代码中通过 `asyncio.to_thread` 放入线程池，避免阻塞事件循环。

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

21 个用例覆盖：

- **服务层**：宏观评分引擎（权重归一/多空映射/逐因子方向）、趋势服务（均线/方向/指数合成/数据不足异常）
- **API 层**：机会分析（评分/历史/参数校验 422）、行情（报价/趋势/维度校验）、健康检查
- 测试通过 `FakeRepo` 注入假数据源，**不依赖网络**

---

## 10. 版本历史

| 版本 | 内容 |
|------|------|
| **V0.10**（已发布 v0.10.0） | FastAPI 分层骨架、宏观机会评分、SQLite 持久化、Mock 行情、12 测试 |
| **V0.11**（已发布 v0.11.0） | AKShare 数据源、2 个月趋势追踪、趋势评估指数、可视化页面、**个人交易跟踪（持仓/盈亏）、购买决策引擎、ETF vs 克价对照、纽约金 60 天曲线、指数置顶+运算方法展示**、41 测试 |
| **V0.20**（已发布 v0.20.0） | **三面评估体系**（技术 30%/宏观 40%/消息面 30%）、**消息面评估页**（客户投行展望打分化）、**权重配置页**（持久化）、**每日评估快照**（daily_snapshots 本地历史）、宏观参考因子（美元/美债/VIX/央行购金）、**仓位推荐**（评估指数→建议仓位）、数据源 30s 超时兜底、统一顶部导航、投资警示五条、本机常驻（start_server.bat 一键自愈 + install_startup.ps1）、56 测试 |
| **V0.50**（已发布 v0.50.0） | **易用性**：今日操作清单引导、消息面打分提醒/快捷档位/沿用上次、持仓录入简化（金额↔份数/快捷比例）、纽约金昨日与 5 日涨跌；**稳定性**：服务看门狗自愈 + 开机自启（启动文件夹）；**可信度**：数据源三态标识（实时/缓存/演示）+ 健康度统计 + 备源与 stale 兜底；**性能**：行情缓存持久化（冷启动 1.6s）、分源并发采集（-39%）、SQLite WAL + 索引；**数据保障**：快照定时采集（06:00/16:00）、数据库自动备份（保留 7 份）、超期快照归档；**工程**：Alembic 正式迁移、配置内存缓存、66 测试 |
| **V0.51**（当前） | **投资指引基准切换为纽约金（COMEX GC）**：趋势追踪指数、购买决策、每日快照均以纽约金为基准（连续交易、夜盘覆盖国内休市，对国内金价具领先指示意义）；ETF/上海金作为国内对照与交易标的。前端主趋势面板改显纽约金（美元/盎司），新增上海金 Au99.99（元/克）国内对照面板，`/gold/trend` 支持 `target` 参数（ny/etf/gram），67 测试 |

---

## 11. 下一阶段改进计划

> 状态图例：✅ 已完成 ｜ ⏳ 进行中 ｜ 📋 待办
>
> 易用性专项改善路径（V0.20 现状评估 + P0-P3 方案与版本规划）：[improvement-path.md](improvement-path.md)

### P1 · 近期（1-2 周）—— 工程化收口

| # | 事项 | 状态 | 价值 |
|---|------|------|------|
| 1 | 发布 **V0.50**（commit + `v0.50.0` 标签推送 GitHub） | ✅ | 固化易用性/稳定性/可信度/性能/数据保障/工程全链路优化 |
| 2 | **权重配置页** `/weights.html`：趋势 5 维度权重 + 决策「技术面 vs 消息面」合成权重可调（持久化 app_settings） | ✅ | 用户可定制评估逻辑 |
| 3 | **CI/CD**：GitHub Actions 自动跑 pytest + ruff，tag 触发自动构建 | 📋 | 质量门禁 |
| 4 | **Alembic 数据库迁移**（替代启动时 create_all） | 📋 | 结构可演进 |
| 5 | 行情源**配置化**（.env 切换 sina/em/investing/mock） | 📋 | 环境适配 |
| 6 | 交易面**多账户**（user_id 已预留）与交易历史查询页 | 📋 | 个人化增强 |

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

---

## 12. 备注

- 本应用输出为**研究参考**，不构成投资建议。
- 权重与阈值为典型经验值（rule-based），随数据积累逐步用回测校准。
- 数据来源：AKShare（东方财富 / 新浪财经），第三方接口可能变化，已做降级容错。
