# Gold Price Investment Assistant · 黄金价格投资辅助工具

> 面向**个人黄金投资者**的一站式数据参考平台：汇聚**纽约金 / 上海金 / 黄金ETF 三大市场**价格，融合**技术面 · 宏观面 · 消息面**给出 0-100 量化多空指数，搭配**个人持仓盈亏管理**、**ETF 买卖决策**与**每日评估快照本地历史**——全部数据留在你自己的机器上。

| | |
|---|---|
| **当前版本** | **V0.74.0**（2026-09-26）· 详见 [GitHub Releases](https://github.com/surui1981/gold-etf-analyzer/releases) |
| **测试基线** | 728 用例 / 684 通过 / 0 失败（pytest 离线回归，排除 2 个联网 fetcher 文件 44 用例） |
| **页面** | 12 个静态页 · 61 个 REST 路径（70 个端点） |
| **语言** | 简体中文 / 繁體中文 / English（顶栏一键切换） |

> 📖 [docs/application-guide.md](docs/application-guide.md) · 架构 / API / 核心模型
> 🧭 [docs/improvement-path.md](docs/improvement-path.md) · 易用性改善路径与版本规划
> 🎨 [docs/ux-roadmap.md](docs/ux-roadmap.md) · UX 与应用能力路线（V0.74.0 → V0.75.0）
> ✅ [docs/feature-alignment.md](docs/feature-alignment.md) · README ↔ 代码 ↔ 文档三方对账
> 🚀 [docs/deployment.md](docs/deployment.md) · 公开部署 runbook（Nginx + HTTPS + Docker）

---

## 产品定位

本工具是为**个人黄金投资者**（尤其做**中短期 ETF 波段**）做的数据参考平台。你看到的核心问题是：单一行情 App 只给报价，没有「综合多空」判断；自己拉一堆宏观数据又太散。我们把这三件事缝成一个产品：

1. **量化多空** — 把技术面、宏观面、消息面三维度按权重加权成一个 0-100 的「综合趋势指数」，看一眼就知道现在偏多还是偏空。
2. **持仓闭环** — 你的开仓 / 加减仓 / 清仓都进系统，**实时盈亏、胜率、最大回撤、收益曲线**自动算。
3. **决策可解释** — 系统给出「买 / 加 / 持有 / 减 / 卖」建议时，每一条都附**理由明细**（指数分位、持仓状态、阈值依据），而不是黑盒。

延续 PM-Evaluator 架构思路：各因子按经验赋权、输出**红绿着色**的机会窗口与多空信号；**消息面由你基于主流财经网站的投行展望自行打分**，避免「被算法替你判断」。

## 一图速览

- 📊 **三大市场一屏对比** — 纽约金（COMEX）/ 上海金（Au99.99）/ 黄金 ETF（518880），实时报价 + 趋势曲线 + 价差对照
- 🎯 **综合趋势评估指数** — 技术 30% × 宏观 40% × 消息面 30% 加权，0-100 量化多空，等级红绿着色
- 🔬 **5 维技术 + 5 因子宏观** — 结构 / 动量 / 支撑 / 动能 / 回撤 + 美元 / 美债10Y·30Y / VIX / 央行购金，**权重可调**
- 📰 **消息面每日 3 次打分** — 越晚权重越高（1:2:3 加权），12 个依据标签 + 自由备注
- 🏦 **央行购金监控** — WGC 季度数据 2014Q1–2026Q2，52 季度 + 23 国家，Top 10 买家榜 + 完整明细
- 💼 **个人持仓闭环** — 多账本 / 开仓·加仓·减仓·清仓 / **克数模式** / 收益曲线 / 业绩分析
- 🧪 **参数回测校准** — 历史日线扫描权重网格 × 阈值带，输出夏普 + 最大回撤 + 5 区间校准
- 📜 **每日评估快照** — 参数 + 指数值每日 07:00 BJT 自动落库，指数历史曲线随时回看
- 📈 **共振信号卡** — 趋势页头部三色共振（宏观 × 技术 × 消息面），命中率高亮
- 🌐 **三语切换** — 简体中文 / 繁體中文 / English，切换器在顶栏
- 🔒 **数据本地化** — 持仓、账本、消息面打分、推送订阅全部 SQLite 本地存，**不上云**
- 📲 **推送 + PWA + Web Push** — 4 类告警规则（指数跨档 / 单日波动 ≥X% / 自定义时段 / T+N 命中），4 渠道：浏览器 / Web Push / 邮件 / 微信
- 🧩 **仪表盘自定义** — 持仓页 7 张卡片拖拽排序 + 键盘替代（Space 抓取 / ↑↓ 移动）+ 布局本地持久化 + 一键恢复默认

## 11 个页面导览（另含 `offline.html` PWA 离线兜底页，共 12 个静态页）

| 页面 | URL | 一句话功能 | 适用场景 |
|------|-----|-----------|---------|
| **趋势追踪** | `/static/trend.html` | 综合指数 + 三大维度拆解 + K 线主图 + 宏观因子 + 共振信号卡 | **打开就用**的主入口，看当日多空 |
| **持仓决策** | `/static/portfolio.html` | 当前持仓 + 实时盈亏 + 买卖决策（带理由） | 看现在该不该动 |
| **权重配置** | `/static/weights.html` | 调整技术 / 宏观 / 合成比权重 | 想自定义评分口径时 |
| **消息面评估** | `/static/news.html` | 每日 3 次打分（越晚权重越高）+ 依据标签 | 看新闻后录入当日研判 |
| **研判复盘** | `/static/review.html` | 历史打分 vs 金价对齐，T+1/T+3/T+5 命中 + 校准曲线 | 看自己过去判断准不准 |
| **交易历史** | `/static/trades.html` | 多账本多条件筛选 + 已实现盈亏 + CSV 导出 | 回看成交明细 |
| **央行购金** | `/static/central-bank.html` | 全球央行季度净购金（吨）+ Top 榜 + 完整明细 | 看结构性买盘 |
| **白银行情** | `/static/silver.html` | 白银 ETF / NY 银趋势 + 共振信号（V0.71.0 新） | 配套白银参考 |
| **参数回测** | `/static/backtest.html` | 权重网格 × 阈值带扫描 + 夏普 / 回撤 / 校准 | 校准参数有效性 |
| **数据健康** | `/static/data-health.html` | 各行情源实时性 / 覆盖率 / 降级状态一览（V0.73.0 N+16 新） | 排查取数异常 |
| **设置 / 通知** | `/static/settings.html` | 管理员 Token + 告警规则 + SMTP/Server酱 + PWA + Web Push | 配置推送 + 升级管理 |

---

## 三大核心能力

### 1️⃣ 综合趋势评估指数

**公式**：`综合指数 = 技术面 × 30% + 宏观面 × 40% + 消息面 × 30%`（权重可在 `/weights` 页面调整）

**技术面**（5 维度，权重可调）：结构 30% · 动量 20% · 支撑 20% · 动能（RSI）15% · 回撤 15%

**宏观面**（5 因子）：

| 因子 | 权重 | 与黄金 | 100 分位 | 0 分位 |
|------|------|-------|---------|--------|
| 美元指数 DXY | 25% | 负相关 | 95 | 105 |
| 美债 10Y | 20% | 负相关 | 3.5% | 4.5% |
| 美债 30Y | 15% | 负相关 | 4.0% | 5.0% |
| VIX 恐慌指数 | 15% | 正相关 | 25 | 12 |
| 央行购金（吨/年） | 25% | 正相关 | 1200 | 500 |

**消息面**：由你在 `/news` 页面自行打分（0-100：>55 看多，<45 看空，50 中性），**每日 3 次槽位**，1:2:3 加权合成，越晚权重越高。

**等级阈值**：`≥75 强势上升` / `≥55 上升` / `≥45 震荡` / `≥25 下降` / `<25 弱势下降`（趋势页红绿着色）

> 详见 [docs/application-guide.md §4 评分模型](docs/application-guide.md)。

### 2️⃣ 个人持仓管理

- **多账本** — 默认账户 + 自定义账本（归档管理），全站顶栏账本切换器；持仓 / 收益曲线 / 业绩分析均按账本隔离
- **完整交易闭环** — 开仓 → 加仓 → 减仓 → 清仓，**实时盈亏** + **已实现盈亏** + **胜率 / 盈亏比 / 平均持仓天数**
- **双单位持仓** — 同时支持**份数**（ETF 标准 100 份一手）和**克数**（实物金 / 积存金口径），单位切换器在收益曲线右上角
- **收益曲线** — 流水回放重建，含**最大回撤**标注
- **决策可解释** — 「买 / 加 / 持有 / 减 / 卖」建议附理由明细（指数分位 / 持仓状态 / 阈值依据），不是黑盒

> 详见 [docs/application-guide.md §5 持仓与决策](docs/application-guide.md)。

### 3️⃣ 央行购金监控

- **数据源**：WGC（世界黄金协会）Gold Demand Trends 季度报告
- **覆盖**：全球合计季度数据 **2014Q1–2026Q2（52 季度）** + 23 国家 / 季度明细 + UZB/IRN 手工补丁
- **页面元素**：4 个 KPI 卡（T12M / 本季合计 / 参与国数 / 数据截止季）+ Chart.js 堆叠柱状图 + **Top 10 买家榜** + 完整明细表（按国家 / 季度范围筛选）
- **cb_gold 因子联动** — `MacroFactorService` 自动从 `central_bank_purchases` 表汇总 T12M 注入宏观面评分；无数据时回退 STATIC_REF 硬编码
- **自动调度** — 每月 1 / 15 / 末日 07:30 BJT 自动从 WGC 拉取

> 详见 [docs/application-guide.md §6 央行购金](docs/application-guide.md)。

---

## 数据 & 时效

- **数据源**：**AKShare**（新浪 ETF / 东方财富备选 / SGE 上海金 / 英为财情纽约金 / 中债美债收益率）+ **WGC Gold Demand Trends**（央行购金季度统计，HTML chart JS 自动抓取）+ **Yahoo Finance**（白银 `562800.SS` / `SI=F`，**V0.73.0 新**）
- **失败降级**：采集失败自动降级为内置 Mock / 静态参考值；AKShare 调用全局串行（py_mini_racer 兼容）；**Yahoo Silver 失败自动降级 mock，HTTP 200 不掉链**（V0.73.0 N+12）
- **行情源 provider 可切换** — `.env` 配置 `MARKET_PROVIDER=akshare|mock|eastmoney_only|sina_only|silver_yahoo`，测试 / 离线演示直接走 mock 不触网；白银可选 `silver_yahoo` 拉真实报价
- **时效透明** — 顶栏 freshness 角标显示数据**采集时点 + 缓存状态 + 时段**（交易 / 非交易）+ 4 个时点（09:30 / 11:30 / 14:00 / 15:30 BJT）预热 + 趋势页 60s 轮询 + 切回前台自动刷新
- **多时间框架** — K 线主图支持 60D / 52W / 24M 三档（服务端抽 730 天日 K 后聚合）

## 多语言

- **3 语言**：简体中文（默认）/ 繁體中文 / English
- **切换位置**：顶栏 `<select class="lang-sel">`
- **持久化**：`localStorage.pm_lang`，刷新保留
- **覆盖率**：zh-CN 699 key · en-US 700 key · **zh-TW 451 key（64.5%，阈值 60%）**
- **格式化**：`Intl.NumberFormat` / `Intl.DateTimeFormat` locale-aware（货币、日期、相对时间）

## 隐私 & 安全

- **数据本地化** — SQLite 文件存本机，**不上传任何持仓/打分/账本数据**
- **管理员守卫** — `X-Admin-Token` 头（`secrets.compare_digest`），写端点全覆盖（无 `ADMIN_TOKEN` env 时 skip，dev 友好）
- **速率限制** — per-IP 60s sliding window 120 req/min（`app_env!=test` 自动禁用，避免测试 429 误伤）
- **Web Push** — VAPID EC P-256 密钥对持久化到本地，订阅表 endpoint unique + 退订硬删

---

## 技术栈

| 层 | 选型 |
|----|------|
| 后端 | Python 3.11+ · FastAPI · Pydantic v2 · SQLAlchemy · Alembic |
| 存储 | SQLite（默认）/ PostgreSQL 可换 · Redis 可选 |
| 数据源 | AKShare · WGC Gold Demand Trends · mock 降级 |
| 前端 | 纯静态 HTML + 内联 `<script>` + Chart.js · **无构建步骤** |
| 样式 | 原生 CSS 变量（4 主题：light / dark / auto / high-contrast） |
| 缓存 | 服务端 served cache（`quote_cache_ttl`）· SW 双 cache（gold-shell / gold-runtime） |
| 推送 | SMTP（aiosmtplib SSL/STARTTLS）+ Server酱（httpx）+ Web Push（pywebpush / VAPID） |
| 部署 | Docker 多阶段（1.2GB → 280MB）+ docker-compose + Nginx + Certbot |
| 测试 | pytest 728 · ruff · check_static_js.py（前端内联 JS 门禁） |
| CI | GitHub Actions · Python 3.11/3.12 matrix · uv 缓存 |

## 快速开始

### 方式一：Docker（推荐）

```bash
docker compose up --build
# 访问 http://127.0.0.1:8888
```

### 方式二：本地 pip

```bash
python -m pip install -e ".[dev]"
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8888
```

### 访问入口

- 主页：[http://127.0.0.1:8888/](http://127.0.0.1:8888/)
- Swagger：[http://127.0.0.1:8888/docs](http://127.0.0.1:8888/docs)
- 健康检查：[http://127.0.0.1:8888/api/v1/health](http://127.0.0.1:8888/api/v1/health)

### 公开部署（HTTPS + Nginx + 域名）

详见 [docs/deployment.md](docs/deployment.md)：多阶段 Dockerfile + docker-compose.prod.yml（app / nginx / certbot / backup-cron 5 服务）+ TLS 1.2/1.3 + HSTS + 自动续签。

## 测试

```bash
python -m pytest -v                                      # 728 用例（离线回归 684 passed）
ruff check src tests                                     # lint
ruff format src tests                                    # format
python scripts/check_static_js.py                        # 前端内联 JS 门禁（语法 / 未定义调用 / DOM id）
```

> ⚠️ **前端没有构建步骤** — JS 写错不会被任何编译期拦截，却会让整页脚本失效（按钮无响应、数据不加载），而后端测试依旧全绿。改完 `static/*.html` / `static/*.js` 后**务必**跑 `check_static_js.py`（等价于 `make check-web`）。

## 版本历程

| 版本 | 日期 | 亮点 |
|------|------|------|
| **V0.74.0** | 2026-09-26 | 仪表盘自定义（7 卡片拖拽排序 + 键盘替代 + localStorage 布局持久化 + 恢复默认）+ 告警规则 CRUD（discriminated union 重构 + UI 模态）+ Web Push 订阅闭环 + i18n 三语补齐；本次一并修复 CI 门禁（ruff lint / format 长期未通过）与版本号单源化 |
| **V0.73.0** | 2026-09-22 | i18n 三语（zh-CN 626 + zh-TW 391 + en-US 627 key）+ locale 格式化 + 后端国家名解耦 + **Yahoo Silver provider + 自动降级 mock** + i18n.apply() inline 子节点保留修复（目标分 91.0 → 91.5） |
| V0.72.0 | 2026-09 | 推送 + PWA + Web Push + 公开部署（90.5 → 91.0） |
| V0.71.0 | 2026-08 | 白银 + 参数回测全链路（90 → 90.5） |
| V0.70.0 | 2026-08 | 共振信号 + 克数持仓（89 → 90） |
| V0.69.0 | 2026-07 | 4 主题 + 无障碍扩面（axe-core 0 critical） |
| V0.68.0 | 2026-07 | 导航折叠 + 全局搜索（⌘K）+ 客户端埋点底座 |
| V0.67.0 | 2026-06 | CI/CD + trace_id 全链路 + 价格校验 |
| V0.66.0 | 2026-06 | 研判复盘与准确率校准（T+1/T+3/T+5 + 分值分箱） |
| V0.65.0 | 2026-05 | 消息面每日 3 次打分（1:2:3 加权，槽位修复） |
| V0.64.0 | 2026-05 | 多时间框架（60D / 52W / 24M） |
| V0.63.0 | 2026-04 | 评估指数历史曲线升级（4 条线 + 极值卡） |
| V0.62.0 | 2026-04 | 单用户多账本 + 交易历史查询页 |
| V0.61.0 | 2026-03 | 交易闭环 + 业绩分析（胜率 / 盈亏比 / 最大回撤） |
| V0.60.0 | 2026-03 | 行情实时性增强（cache TTL + 4 点预热 + 60s 轮询） |
| V0.50.0 | 2026-01 | Alembic 迁移 + 每日快照定时任务（看门狗 06/16 点） |

完整 release notes 见 [GitHub Releases](https://github.com/surui1981/gold-etf-analyzer/releases)。

## 文档

- 📖 [docs/application-guide.md](docs/application-guide.md) — 完整使用文档（架构 / API 参考 / 核心模型 / 改进计划）
- 🧭 [docs/improvement-path.md](docs/improvement-path.md) — 易用性改善路径（P0-P3 改善方案）
- 🎨 [docs/ux-roadmap.md](docs/ux-roadmap.md) — UX 路线（V0.74.0 → V0.75.0：导航 / 主题 / a11y / i18n / 自定义 / 多用户）
- ✅ [docs/feature-alignment.md](docs/feature-alignment.md) — README ↔ 代码 ↔ 文档三方对账报告
- 🚀 [docs/deployment.md](docs/deployment.md) — 公开部署 runbook（HTTPS + Nginx + Docker）

## 许可

个人研究项目，无对外许可证。所有数据源版权归原机构（AKShare / WGC）所有。