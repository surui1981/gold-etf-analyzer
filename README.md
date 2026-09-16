# Gold Price Investment Assistant · 黄金价格投资辅助工具

面向**个人黄金投资者**的一站式数据参考平台（**中短期 ETF 波段操作**）：汇聚 **纽约金（COMEX）、上海金（Au99.99）、黄金ETF（518880）** 三大市场价格，提供**综合趋势评估指数**（技术面 30% × 宏观面 40% × 消息面 30% 加权，0-100 量化多空）、个人持仓跟踪与盈亏管理、参数面 × 交易面驱动的 **ETF 购买决策**、以及**每日评估快照**本地历史数据。

延续 PM-Evaluator 的预期评估架构：各因子/维度按典型经验赋权加权评分，输出机会窗口与多空信号（红绿着色，面向客户展示）。**消息面由客户基于主流财经网站的投行黄金走势展望研判打分**（独立评估页），汇入每日评估。

> 📖 完整说明文档（架构 / API 参考 / 核心模型 / 改进计划）：[docs/application-guide.md](docs/application-guide.md)
> 🧭 易用性改善路径（现状评估 + P0-P3 改善方案与版本规划）：[docs/improvement-path.md](docs/improvement-path.md)
> ✅ README ↔ 代码 ↔ 文档三方对账报告（已落实 / 待完善）：[docs/feature-alignment.md](docs/feature-alignment.md)

## 快速开始

### 方式一：本机常驻（推荐）

```bash
# 手动启动（双击运行，窗口保持即可常驻，6 秒后自动打开浏览器）
start_server.bat

# 开机自启（Windows 计划任务，登录时后台启动 + server.log 日志）
# 右键 install_startup.ps1 -> 使用 PowerShell 运行（仅需执行一次）
# 卸载：Unregister-ScheduledTask -TaskName "GoldPriceAssistant" -Confirm:$false
```

### 方式二：命令行 / Docker

```bash
# pip
python -m pip install -e ".[dev]"
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8888

# Docker
docker compose up --build
```

访问：主页 `http://127.0.0.1:8888/` ｜ Swagger `http://127.0.0.1:8888/docs` ｜ 健康 `http://127.0.0.1:8888/api/v1/health`

## 功能清单

| 模块 | 能力 |
|------|------|
| 三市场行情 | 纽约金 / 上海金 / 黄金ETF 实时价格与趋势曲线 |
| 综合趋势指数 | 技术面（5 维度）× 宏观面（5 因子）加权合成 0-100 指数 |
| 宏观参考因子 | 美元指数 / 美债10Y·30Y / VIX / 央行购金，随参数动态变化 |
| 权重配置 | `/weights` 页面调整技术/宏观/合成比权重，指数实时重算 |
| 央行购金统计 | `/central-bank` 世界各国央行季度净购金（吨）数据，按国家/季度筛选，Chart.js 堆叠柱状图 + Top 榜 + 明细表 |
| 个人交易跟踪 | 开仓/加仓/减仓/清仓、实时盈亏（SQLite 持久化） |
| 购买决策 | 趋势指数 × 持仓状态 → 买入/加仓/持有/减仓/卖出 + 理由明细 |
| 每日快照 | 每日参数+评估值本地存储（`daily_snapshots`），指数历史序列 |
| 自动调度 | 每日 07:00 BJT 捕获快照 + 央行购金每月 1/15/末日 07:30 BJT 自动从 WGC 拉取数据 |
| 可视化 | 趋势页（指数/曲线/对照/宏观因子/历史）、央行页（KPI/堆叠柱/Top 榜/明细表）、持仓页、权重页、消息面页、交易历史页、研判复盘页 |
| **新手引导与帮助体系** | 右下角悬浮 `?` 按钮唤起 3 tab modal（操作指南 5 步流程 / 术语速查 30+ 条按 7 类分组 / 数据来源 + 投资警示）；首访 5 页面自动弹 2-4 步 tour 浮层；15 项关键术语 inline `?` 图标自动注入；移动端 modal 改底部抽屉 |
| **评估指数历史曲线升级** | 趋势追踪页『每日评估历史』面板升级：综合 / 技术 / 宏观 / **消息面（新增）** 4 条线；7D / 30D / 90D 区间切换按钮；4 个极值卡（最新 / 区间最高 / 区间最低 / 日变，带 ↑↓→ 着色）；稀疏数据 3 档 UX（< 3 天提示样本不足 / < 7 天提示天数 / ≥ 7 天默认）；Chart.js 实例化前 destroy 旧实例防内存泄漏（区间切换安全） |
| **行情源 provider 可切换** | `.env` 配置 `MARKET_PROVIDER=akshare\|mock\|eastmoney_only\|sina_only`，4 选 1；XAU fallback chain 与缓存 TTL 也可配；测试 / 离线演示可直接走 mock 不触网 |
| **行情实时性增强** | served cache 日内 TTL（默认 10 分钟，`.env` 可配）+ 6 个行情接口启用进程级 cache（`quote_cache_ttl` 真生效）+ 日内 4 个时点（09:30/11:30/14:00/15:30 BJT）自动预热；趋势页 60s 轮询 + 切回前台自动刷新 + 手动 🔄 按钮；持仓页 30s 轮询；freshness 角标自动派生"缓存过期"分支 |
| **多时间框架（周/月线）** | 趋势追踪页 K 线主图加 3 档区间按钮（60D / 52W / 24M）：服务端抽 730 天日 K → 按 ISO 周界聚合到 ~52 根周 K / 按年月聚合到 ~24 根月 K；MA 在聚合后序列上重算；W/M 模式技术面 5 维度旁路（指标对日 K 敏感）；`/api/v1/market/gold/trend?interval=W\|M` + `days` 上限 250 → 750；缓存 key 扩展为 (target, interval, date) 三维独立 |
| **消息面每日 3 次打分** | `/news` 页面：每日 3 次打分机会（按序号第 1/2/3 次，各自记录实际提交时刻），当日有效分值按「越晚权重越高」**1:2:3 加权**合成（`Σ(i×scoreᵢ)/Σi`）；三次用尽后留空提交返回 400 提示指定槽位（**不再静默覆盖**）；每次打分可单独修改或撤销；研判依据 12 个预置标签多选 + 自由备注 |
| **研判复盘与准确率校准** | `/review` 页面：按日期归档每日研判（分值 / 方向 / 依据标签 / 备注）并与金价对齐，给出 **T+1 / T+3 / T+5** 三个交易日的涨跌与命中判定；统计面板含总命中率、按方向分组、按窗口分组、**分值分箱校准曲线**、**依据标签胜率**；支持历史补录（标记 `backfilled`，统计默认排除以防前视偏差）；打分页实时提示该分值区间的历史胜率 |

## API 一览

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/` / `/portfolio` / `/weights` / `/news` / `/central-bank` / `/trades` / `/review` | 趋势追踪 / 持仓决策 / 权重配置 / 消息面评估 / 央行购金 / 交易历史 / 研判复盘 页面 |
| GET | `/api/v1/health` | 健康检查 |
| POST | `/api/v1/analysis/opportunity` | 宏观因子 → 机会评分与窗口 |
| GET | `/api/v1/analysis/history` | 历史分析记录 |
| GET | `/api/v1/market/gold` | 黄金ETF最新报价 |
| GET | `/api/v1/market/gold/trend` | 趋势追踪 + 综合指数 + 宏观因子明细 |
| GET | `/api/v1/market/gold/ny-trend` | 纽约金 60 天曲线（美元/盎司） |
| GET | `/api/v1/market/gold/compare` | ETF vs 上海金 对照 |
| POST | `/api/v1/positions` | 开仓 |
| GET | `/api/v1/positions` | 持仓列表（实时盈亏） |
| POST | `/api/v1/positions/{id}/trades` | 加仓/减仓 |
| POST | `/api/v1/positions/{id}/close` | 清仓 |
| GET | `/api/v1/decision/etf` | 购买决策 |
| GET/PUT | `/api/v1/settings/weights` | 权重配置读取/保存 |
| GET/PUT | `/api/v1/news-score` | 消息面打分（客户评估；支持 `basis` 依据标签 / `review_note` 复盘批注 / `score_date` 补录） |
| DELETE | `/api/v1/news-score/{slot}` | 撤销当日某一次打分（释放该槽位） |
| GET | `/api/v1/news-score/history` | 历史打分记录（跨日回看） |
| GET | `/api/v1/review/meta` | 复盘配置元信息（基准标的 / 窗口 / 12 个依据标签 / 价格日历覆盖） |
| GET | `/api/v1/review/journal` | 研判日志（按日期倒序，含基准收盘 → T+1/3/5 收盘、涨跌幅、命中判定） |
| GET | `/api/v1/review/stats` | 复盘统计（命中率 / 方向分组 / 窗口分组 / 分值分箱校准 / 依据标签胜率） |
| GET | `/api/v1/review/hint` | 打分页校准提示（指定分值区间的历史胜率） |
| GET | `/api/v1/review/horizons` | 可用判定窗口（T+1 / T+3 / T+5） |
| POST | `/api/v1/review/backfill` | 回填历史金价日历（幂等，来自 `/gold/ny-trend`） |
| GET | `/api/v1/central-bank/summary` | 央行购金摘要（T12M 总量 / 参与国数 / 最新季度） |
| GET | `/api/v1/central-bank/top-buyers` | 某年度 Top N 买家 |
| GET | `/api/v1/central-bank/purchases` | 央行购金明细（按国家 / 季度范围筛选） |
| POST | `/api/v1/snapshots/capture` | 捕获当日快照 |
| GET | `/api/v1/snapshots` | 每日评估历史（自动补当日） |

> 数据源：**AKShare**（新浪 ETF / 东方财富备选 / SGE 上海金 / 英为财情纽约金 / 中债美债收益率）+ **WGC Gold Demand Trends**（央行购金月度统计，HTML chart JS 自动抓取），
> 采集失败自动降级内置 Mock / 静态参考值；akshare 调用全局串行（py_mini_racer 兼容）。

## 央行购金数据

独立的 `/central-bank` 页面（`static/central_bank.html`）展示世界各国央行近年来的黄金净购金（吨）：

- **数据源**：WGC（世界黄金协会）Gold Demand Trends 季度报告 HTML chart JS（`fsapi.gold.org/api/v12/charts/js/...`），绕开 XLSX 直链 403 反爬
- **覆盖**：全球合计季度数据 2014Q1–2026Q2（52 季度）+ H1 2026 按国家（19 买家 + 4 卖家）+ UZB/IRN 手工补丁（26 季度）
- **页面元素**：4 个 KPI 卡（T12M / 本季合计 / 参与国数 / 数据截止季） + Chart.js 堆叠柱状图（季度 × 国家） + Top 10 排行榜 + 完整明细表（按国家 / 季度范围筛选）
- **cb_gold 因子联动**：`MacroFactorService` 注入 `CentralBankService`，从 `central_bank_purchases` 表自动汇总 T12M；表无数据时回退 STATIC_REF 硬编码
- **手动刷新**：
  ```bash
  python -m app.scripts.import_central_bank             # 全量落库
  python -m app.scripts.import_central_bank --dry-run    # 预览
  ```
- **自动调度**：每月 1 / 15 / 末日 07:30 BJT 自动从 WGC 拉取；通过 `CENTRAL_BANK_AUTO_REFRESH` 环境变量控制（`0` / `false` / `no` / `off` 关闭）

## 综合趋势评估指数

```
综合指数 = 技术面评分 × 30% + 宏观参考评分 × 40% + 消息面评分 × 30%（可在 /weights 调整）
```

**技术面（5 维度）**：结构 30% / 动量 20% / 支撑 20% / 动能(RSI) 15% / 回撤 15%

**消息面（客户评估）**：消息面评估页（API `/news-score`）基于主流财经网站（金十/新浪/东财/英为财情/汇通/华尔街见闻）的**投行黄金走势展望**研判打分（0-100：>55 看多、<45 看空、50 中性），保存后立即汇入综合指数与每日快照。

> **每日 3 次打分（V0.65.0）**：按序号第 1/2/3 次占用槽位（不绑定具体时段，各自记录实际提交时刻），当日有效分值 = `Σ(i × scoreᵢ) / Σ(i)`（**越晚权重越高**，1:2:3）。打满 3 次后留空 slot 提交会返回明确报错而**不再静默覆盖**；点卡片「修改」可指定槽位覆盖，或「撤销」释放槽位（剩余次数按权重重新归一）。每次打分可挂 **12 个预置依据标签**（美元指数 / 美债收益率 / 实际利率 / 通胀预期 / 美联储政策 / 央行购金 / 地缘风险 / 避险情绪 / ETF 资金流 / 人民币汇率 / 技术面 / 投行观点）+ 自由备注。

> **研判复盘（V0.66.0）**：`/review` 页面按日期归档研判（分值 / 方向 / 依据 / 备注），对齐金价日历给出 **T+1 / T+3 / T+5** 三个交易日的涨跌与命中判定（看多须涨、看空须跌、看平容差 ±0.3%），并汇总总命中率、**分值分箱校准曲线**与**依据标签胜率**，用于回看「判断准不准、哪类依据更可靠」。金价日历 `gold_price_daily` 独立于快照表，只存客观价格，可长期积累与回填。

**宏观参考（5 因子）**：

| 因子 | 权重 | 与黄金关系 | 100 分位 | 0 分位 |
|------|------|-----------|----------|--------|
| 美元指数 | 25% | 负相关 | 95 | 105 |
| 美债10Y | 20% | 负相关 | 3.5% | 4.5% |
| 美债30Y | 15% | 负相关 | 4.0% | 5.0% |
| VIX | 15% | 正相关（避险） | 25 | 12 |
| 央行购金 | 25% | 正相关（结构性） | 1200吨/年 | 500吨/年 |

等级：`≥75 强势上升` / `≥55 上升` / `≥45 震荡` / `≥25 下降` / `<25 弱势下降`。
权重集中在 `services/macro.py` / `services/trend.py`，可在 `/weights` 页面调整。

## 架构分层

```
gold-etf-analyzer/
├── src/app/
│   ├── main.py              # 入口：路由装配、CORS、lifespan、静态页、调度器启动
│   ├── config.py            # pydantic-settings 配置
│   ├── dependencies.py      # 依赖注入容器
│   ├── models/              # ORM：analysis / position / snapshot / settings / central_bank / account / news / review
│   ├── schemas/             # Pydantic v2 请求/响应 + 枚举
│   ├── services/            # scoring / trend / macro / decision / position / account / trades / compare / freshness / news / review / snapshot / settings / central_bank / cache / scheduler
│   ├── repositories/        # analysis / market_data(AKShare) / market_providers / position / account / snapshot / settings / news / review(价格日历) / central_bank / central_bank_data (WGC fetcher)
│   ├── api/v1/              # health / analysis / market / position / account / trades / decision / settings / snapshot / news / review / central_bank
│   └── utils/               # logger / market_clock / db_migrate（启动幂等补列）
├── static/                  # trend.html / portfolio.html / trades.html / weights.html / news.html / central_bank.html / review.html
│                            #   + account.js（账本切换器）/ freshness.js / help.js / responsive.css
├── data/
│   └── central_bank_manual_overrides.json   # UZB/IRN 手工补丁
├── tests/                   # pytest（432 个用例，含 fetcher / scheduler / 集成 / help / providers / cache / intraday / 业绩分析 / 多账本 / 指数曲线 / 多时间框架 / 消息面槽位 / 研判复盘）
├── start_server.bat         # 本机常驻：手动启动（自动开浏览器）
├── install_startup.ps1      # 本机常驻：注册开机自启计划任务
├── Dockerfile / docker-compose.yml
└── README.md
```

## 测试与代码质量

```bash
python -m pytest -v          # 432 用例（离线回归 388 passed，排除 2 个联网 fetcher 文件 44 用例）：服务层 + API 集成 + scheduler + help + providers + cache + intraday + 业绩分析 + 多账本 + 指数曲线 + 多时间框架 + 消息面槽位 + 研判复盘
python scripts/check_static_js.py   # 静态页内联 JS 门禁（语法 / 未定义调用 / DOM id）——改完前端必跑
ruff check src tests
ruff format src tests
```

> 前端为「纯静态 HTML + 内联 `<script>`」，**没有构建步骤**：JS 写错不会被任何编译期拦截，却会让整页脚本失效（按钮无响应、数据不加载），而后端测试依旧全绿。因此改动 `static/*.html` 后请务必执行上面的 `check_static_js.py`（等价于 `make check-web`）。

## 待办 / 优化方向

- [ ] 宏观×技术共振深化：决策引擎纳入宏观机会评分（消息面权重生效）
- [ ] 克数持仓跟踪：实物金/积存金按克持仓，与 ETF 并列盈亏
- [ ] CI/CD（GitHub Actions 自动 pytest + ruff，tag 触发构建）
- [x] **研判复盘与准确率校准（V0.66.0）**：新增 `gold_price_daily` 金价日历（客观价格，独立于快照表，可回填）+ `news_scores.basis/review_note/backfilled`；`/review` 页面按日期归档研判并与金价对齐，给出 **T+1 / T+3 / T+5** 三窗口涨跌与命中判定（看多须涨、看空须跌、看平 ±0.3%）；统计面板含总命中率 / 方向分组 / 窗口分组 / **分值分箱校准曲线** / **依据标签胜率**；补录标记 `backfilled` 且统计默认排除（避免前视偏差）；打分页实时显示该分值区间历史胜率；新增 6 个 review 接口 + `/review` 路由（路由 32 → 40 条），新增 24 个测试（服务 16 + API 8）
- [x] **消息面每日 3 次打分（V0.65.0）**：`news_scores` 增 `slot`(1-3) / `scored_at` 并改 `(score_date, slot)` 复合唯一；当日有效分值按 **1:2:3 加权**（越晚权重越高）合成；三次用尽后留空提交返回 400（**修复同日第二次打分被静默覆盖**的原缺陷）；`DELETE /news-score/{slot}` 撤销 + `GET /news-score/history`；前端三槽位卡片 + 加权算式面板 + 剩余次数提示
- [x] 每日快照定时任务（V0.50 看门狗 06:00/16:00 自动捕获）✅
- [x] Alembic 数据库迁移（替代启动时 create_all，V0.50 已落地）
- [x] 世界央行购金统计页（`/central-bank`，WGC 自动抓取 + 手工补丁，月度调度）
- [x] 新手引导与帮助体系（`?` 按钮 + 3 tab modal + 首访 tour + 15 项 inline tooltip，5 页面统一注入）
- [x] 行情源 provider 可切换（`.env` 配置 `MARKET_PROVIDER=akshare|mock|eastmoney_only|sina_only`，测试 / 离线演示直接走 mock）
- [x] 行情实时性增强（V0.60.0：served cache 日内 TTL + 行情 cache 启用 + 日内 4 点预热 + 趋势页 60s 轮询 + visibilitychange + 持仓页 30s）
- [x] **评估指数历史曲线升级（V0.63.0）**：综合 / 技术 / 宏观 / 消息面 4 条线 + 7D/30D/90D 区间切换 + 极值卡（最新/区间最高/区间最低/日变）+ 稀疏数据 3 档 UX + chart.destroy 内存管理
- [x] **多时间框架（V0.64.0，P2 #9）**：趋势追踪页 K 线主图加 3 档区间按钮（60D / 52W / 24M）—— 服务端抽 730 天日 K 后按 ISO 周界聚合到 ~52 根周 K / 按年月聚合到 ~24 根月 K；MA 在聚合后序列上重算；W/M 模式技术面 5 维度旁路（指标对日 K 敏感）；`/gold/trend?interval=W|M` + `days` 上限 250 → 750；缓存 key 扩展为 (target, interval, date) 三维独立；新增 14 个测试用例（服务 4 + API 4 + 工具 6）
- [x] **单用户多账本 + 交易历史查询页（V0.62.0，P1 #6）**：`accounts` 表 + `positions.account_id`（迁移把历史持仓归入 id=1「默认账户」）；`/api/v1/accounts` 账本增改归档（默认账本不可归档、有未平仓持仓不可归档）；`/api/v1/trades` 多条件筛选（账本/方向/日期/持仓/关键字）+ 均价法回放给出每笔卖出的**已实现盈亏**与**成交后份额** + CSV 导出；全站账本切换器（`account.js`，localStorage 记忆，支持「全部账本」合并视图）；持仓 / 收益曲线 / 获利分析 / 决策均按账本隔离
- [x] **收益回放口径修复（V0.62.1）**：修复「成交日晚于行情序列最后一个交易日」时交易被静默丢弃的问题 —— 此前会导出 `sell_count=2` 却 `closed_trades=0`、累计投入本金显示 **0.00 元** 的自相矛盾（行情源 T-1 滞后或周末录入成交时必现）；现改为归入最后一个可得交易日，本金 / 已实现盈亏 / 胜率统计恢复正确
- [x] 交易闭环与业绩分析（V0.61.0：**ETF 报价口径修正**（`/market/gold/etf-quote`，元/份）+ 加仓/减仓内联面板（金额换算 / 快捷比例 / 摊薄成本与已实现盈亏预览）+ 收益曲线（流水回放重建，含最大回撤）+ 获利分析总结（胜率 / 盈亏比 / 平均持仓天数））
- [ ] 指数参数回测校准：用历史数据回测权重与阈值有效性（消息面打分校准已由 V0.66.0 研判复盘覆盖）
- [ ] 监控告警：数据源失败告警、价格异动提醒（浏览器通知已做，邮件 / 微信待做）
- [ ] 公开部署：域名 + HTTPS（内部 → 公开发布）

> 完整三阶段改进计划见 [docs/application-guide.md](docs/application-guide.md) 第 11 章。
> 易用性专项改善路径（P0 稳定性/可信度优先）见 [docs/improvement-path.md](docs/improvement-path.md)。
> 用户体验（UX）专项改进方向（数据时效透明 / 响应式 / 决策可解释性 / 主动提醒 / 加载与离线体验等）见 [docs/improvement-path.md](docs/improvement-path.md) 第六章。
