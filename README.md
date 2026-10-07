# Gold Price Investment Assistant · 黄金价格投资辅助工具

> 面向**个人黄金投资者**的一站式数据参考平台：汇聚**纽约金 / 上海金 / 黄金ETF 三大市场**价格，融合**技术面 · 宏观面 · 消息面**给出 0-100 量化多空指数，搭配**个人持仓盈亏管理**、**ETF 买卖决策**与**每日评估快照本地历史**——全部数据留在你自己的机器上。

| | |
|---|---|
| **当前版本** | **V0.80.0**（2026-10-07）· 详见 [GitHub Releases](https://github.com/surui1981/gold-etf-analyzer/releases) |
| **测试基线** | **986 用例**（67 个测试模块）· 离线口径 **942 passed**（按文件名排除 2 个联网 fetcher 文件 44 用例）；全量含联网 fetcher = 986 collected |
| **页面** | 13 个静态页 · 67 个 REST 路径（76 个端点） |
| **语言** | 简体中文 / 繁體中文 / English（顶栏一键切换） |

> 📖 **使用文档**（按内容拆分为 5 文件，按需查阅）：
> [overview](docs/overview.md) · [getting-started](docs/getting-started.md) ·
> [architecture](docs/architecture.md) · [api-reference](docs/api-reference.md) ·
> [development](docs/development.md)
> · 完整索引见 [application-guide.md](docs/application-guide.md)
> 🧭 [docs/improvement-path.md](docs/improvement-path.md) · 易用性改善路径与版本规划
> 🎨 [docs/ux-roadmap.md](docs/ux-roadmap.md) · UX 与应用能力路线（V0.68.0 → V0.78.0）
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
- 📰 **消息面每日 3 次打分** — 越晚权重越高（1:2:3 加权），12 个依据标签 + 自由备注；**V0.76.0 起首页即可直接打分**（见下条）
- 🏦 **央行购金监控** — WGC 季度数据 2014Q1–2026Q2，52 季度 + 23 国家，Top 10 买家榜 + 完整明细
- 💼 **个人持仓闭环** — 多账本 / 开仓·加仓·减仓·清仓 / **克数模式** / 收益曲线 / 业绩分析
- 🧪 **参数回测校准** — 历史日线扫描权重网格 × 阈值带，输出夏普 + 最大回撤 + 5 区间校准
- 📜 **每日评估快照** — 参数 + 指数值每日 07:00 BJT 自动落库，指数历史曲线随时回看
- 📈 **共振信号卡** — 趋势页三色共振（宏观 × 技术 × 消息面），命中率高亮
- 🧭 **综合研判结论卡**（V0.75.1 新）— **首页置顶**：一行结论（观望/买入/加仓…）+ 三维分值条（带权重）+ **一致性判定**（同向/分歧）+ **建议仓位 vs 当前持仓** + 决策依据 + **数据质量提示**（静态参考值 / Mock 降级如实标注）；**黄金 ↔ 白银一键切换**
- 🌐 **三语切换** — 简体中文 / 繁體中文 / English，切换器在顶栏
- 🔒 **数据本地化** — 持仓、账本、消息面打分、推送订阅全部 SQLite 本地存，**不上云**
- 📲 **推送 + PWA + Web Push** — 4 类告警规则（指数跨档 / 单日波动 ≥X% / 自定义时段 / T+N 命中），4 渠道：浏览器 / Web Push / 邮件 / 微信
- 🧩 **仪表盘自定义** — 持仓页 7 张卡片拖拽排序 + 键盘替代（Space 抓取 / ↑↓ 移动）+ 布局本地持久化 + 一键恢复默认
- 🔑 **登录与账号体系**（V0.75.0 新）— 会话式登录（bcrypt cost=12 + HttpOnly/SameSite=Strict cookie + CSRF 双提交校验），**默认关闭**（单用户模式零影响），公网部署一键开启
- ✍️ **首页内嵌消息面打分器**（V0.76.0 新）— 把「客户评价」直接搬到趋势追踪页：3 槽位状态 + 有效分值 + 滑杆/快捷档位 + 研判依据 + 备注，**保存后即时刷新上方结论卡与消息面评估行**，全程不跳页；`/news` 仍保留为完整详情页（投行参考来源 + 历史记录）
- 🧩 **界面聚类分组**（V0.77.0 新）— 同类信息按语义聚成**带标题的组**，不再平铺让人自己归类：首页 8 张指标卡分「价格 / 涨跌 / 均线」、交易汇总分「成交规模 / 成本与收益」、数据健康按「黄金 / 白银」分组且状态与时效同卡、复盘三组横条并为 **Tab 分面**（←/→ 可键盘切换）
- 🎯 **口径一致性收口**（V0.78.0 新）— 解决「55 到底是看多还是中性」的口径分裂：把散落在 5 个模块的硬编码阈值集中为**四组语义互不相同的枚举**（`src/app/schemas/thresholds.py`）；决策档位由 4 档扩到 **9 档** 并补上缓冲档 `HOLD_CAUTIOUS`（消除「指数 60-70 且盈亏 -10% ~ +15% 时什么都不做」的**卡死区**）；共振信号把 `DIVERGENT` 从「只看方向相反」扩展为**三维幅度判定 + 子类型**（消息面 ↔ 技术面 / 宏观面此前整类漏判）；并**修掉两种「数据不足却显示中性 50」** —— 技术面 5 维度数据不足时 `score` 返回 `null`（前端灰色「— 未计入」并给出原因），综合指数按**有效维度**归一化，使 `None`（没算出来）与 `50.0`（算出来是中性）**不再同形**
- 🧷 **该记住的都记住了**（V0.77.2 新）— 修掉 4 处「悄无声息做错事」：`/news` 打分时**客户勾选的研判依据与复盘批注根本没进请求体**（页面有回填、后端也支持写库，唯独提交这步漏了 → 复盘「依据胜率」永远算不出，客户却会以为是自己没勾；两者后果其实不同：`basis` 在仓库层是**硬覆盖**、已存依据会被静默抹掉，`review_note` 走 `or` 语义不会被抹、属「填了等于没填」）；`/portfolio` 开仓价格框被**轮询反复清空**（原注释写「预填开仓价格」，实际两分支同值即恒清空，把初始化填好的 ETF 最新价抹掉，还可能让人按空价提交）；`/review` 空态指引**指路到不存在的功能**（「可在该页填写并指定日期」，而打分页并无日期控件）；`/weights`「恢复默认」**无确认、无错误处理**（一次误点即整体覆盖自定义权重并立刻改变综合指数与决策，失败还静默无反应）
- 🛡 **失败态不再伪装成正常**（V0.77.1 新）— 修复「取数挂了却显示一切正常」这一整类陷阱：数据健康页接口失败时四张概览卡从**全绿**改为**「—」未知态**并明说「不代表正常」；消息面有效分的静态默认 `50.0` 改为占位 `—`（50 恰是中性、又真占 30% 权重，最易被误读）；白银页失败后不再永久停在「数据加载中…」；回测校准曲线的「理论概率」正名为**完美校准基准线**并停止绘制恒为 0 的假「实际命中率」线；Service Worker 的只读 API 由 stale-while-revalidate 改为 **network-first**（价格类端点永不回退缓存，其余回退须在 30 分钟内且会在时效条上标注「来自离线缓存」）

## 12 个页面导览（另含 `login.html` 登录页 + `offline.html` PWA 离线兜底页，共 13 个静态页）

| 页面 | URL | 一句话功能 | 适用场景 |
|------|-----|-----------|---------|
| **趋势追踪** | `/static/trend.html` | **综合研判结论卡（置顶）** + **内嵌消息面打分器（V0.76.0，可直接打分）** + 综合指数 + 三大维度拆解 + K 线主图 + 宏观因子 | **打开就用**的主入口，看当日多空并录判断 |
| **持仓决策** | `/static/portfolio.html` | 当前持仓 + 实时盈亏 + 买卖决策（带理由） | 看现在该不该动 |
| **权重配置** | `/static/weights.html` | 调整技术 / 宏观 / 合成比权重 | 想自定义评分口径时 |
| **消息面评估** | `/static/news.html` | 每日 3 次打分（越晚权重越高）+ 投行参考来源 + 跨日历史记录 | 系统查阅依据与回看历史（打分已可在首页完成） |
| **研判复盘** | `/static/review.html` | 历史打分 vs 金价对齐，T+1/T+3/T+5 命中 + 校准曲线 | 看自己过去判断准不准 |
| **交易历史** | `/static/trades.html` | 多账本多条件筛选 + 已实现盈亏 + CSV 导出 | 回看成交明细 |
| **央行购金** | `/static/central_bank.html` | 全球央行季度净购金（吨）+ Top 榜 + 完整明细 | 看结构性买盘 |
| **白银行情** | `/static/silver.html` | 白银 ETF / NY 银趋势 + 共振信号（V0.71.0 新；共振卡 V0.75.1 起可用 `silver_etf` 口径） | 配套白银参考 |
| **参数回测** | `/static/backtest.html` | 权重网格 × 阈值带扫描 + 夏普 / 回撤 / 校准 | 校准参数有效性 |
| **数据健康** | `/static/data-health.html` | 各行情源实时性 / 覆盖率 / 降级状态一览（V0.73.0 N+16 新） | 排查取数异常 |
| **设置 / 通知** | `/static/settings.html` | 管理员 Token + 告警规则 + SMTP/Server酱 + PWA + Web Push | 配置推送 + 升级管理 |
| **登录 / 注册** | `/static/login.html`（或 `/login`） | 登录 / 注册双 Tab + 初始化管理员引导（V0.75.0 新） | 开启认证（`AUTH_ENABLED=true`）后进入 |

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

> 详见 [docs/api-reference.md §6 评分模型](docs/api-reference.md#6-核心模型)。

### 2️⃣ 个人持仓管理

- **多账本** — 默认账户 + 自定义账本（归档管理），全站顶栏账本切换器；持仓 / 收益曲线 / 业绩分析均按账本隔离
- **完整交易闭环** — 开仓 → 加仓 → 减仓 → 清仓，**实时盈亏** + **已实现盈亏** + **胜率 / 盈亏比 / 平均持仓天数**
- **双单位持仓** — 同时支持**份数**（ETF 标准 100 份一手）和**克数**（实物金 / 积存金口径），单位切换器在收益曲线右上角
- **收益曲线** — 流水回放重建，含**最大回撤**标注
- **决策可解释** — 「买 / 加 / 持有 / 减 / 卖」建议附理由明细（指数分位 / 持仓状态 / 阈值依据），不是黑盒

> 详见 [docs/api-reference.md §6 持仓与决策](docs/api-reference.md#6-核心模型)。

### 3️⃣ 央行购金监控

- **数据源**：WGC（世界黄金协会）Gold Demand Trends 季度报告
- **覆盖**：全球合计季度数据 **2014Q1–2026Q2（52 季度）** + 23 国家 / 季度明细 + UZB/IRN 手工补丁
- **页面元素**：4 个 KPI 卡（T12M / 本季合计 / 参与国数 / 数据截止季）+ Chart.js 堆叠柱状图 + **Top 10 买家榜** + 完整明细表（按国家 / 季度范围筛选）
- **cb_gold 因子联动** — `MacroFactorService` 自动从 `central_bank_purchases` 表汇总 T12M 注入宏观面评分；无数据时回退 STATIC_REF 硬编码
- **自动调度** — 每月 1 / 15 / 末日 07:30 BJT 自动从 WGC 拉取

> 详见 [docs/architecture.md §7 数据源](docs/architecture.md#7-数据源)。

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
- **多用户登录（V0.75.0）** — 会话式认证，**默认关闭**（`AUTH_ENABLED=false` = 单用户模式，行为与 V0.74.3 完全一致）。开启后除健康检查/登录注册/埋点外**全部 API 需登录**：
  - 密码 **bcrypt cost=12** 哈希，明文永不落库、不入日志；未知账号也跑一次同代价哈希以打平耗时（防账号枚举）
  - 会话 cookie `HttpOnly` + `SameSite=Strict`；**服务端 sessions 表**存储会话（登出 / 改密 / 禁用可**即时撤销**）
  - 写端点 **CSRF 双提交校验**（`X-CSRF-Token` 头 vs `pm_csrf` cookie，恒定时间比较；`sendBeacon` 埋点豁免）
  - 登录失败**账号 + IP 双维度节流**（默认 15 分钟内 5 次即锁定 15 分钟）
  - `APP_ENV=prod` + 开启认证时自动关闭 `/docs` `/redoc` `/openapi.json`（不暴露接口清单）
  - ⚠️ **本版为「认证骨架」**：登录后才可访问 API，但多个用户之间**尚未做数据隔离**（数据隔离属 V0.75.2）；单机自用建议保持 `AUTH_ENABLED=false`
- **管理员守卫** — `X-Admin-Token` 头（`secrets.compare_digest`），写端点全覆盖（无 `ADMIN_TOKEN` env 时 skip，dev 友好）
- **速率限制** — per-IP 60s sliding window 120 req/min（`app_env!=test` 自动禁用，避免测试 429 误伤）
- **Web Push** — VAPID EC P-256 密钥对持久化到本地，订阅表 endpoint unique + 退订硬删

---

## 技术栈

| 层 | 选型 |
|----|------|
| 后端 | Python 3.11+ · FastAPI · Pydantic v2 · SQLAlchemy · Alembic · bcrypt（V0.75.0 新） |
| 存储 | SQLite（默认）/ PostgreSQL 可换 · Redis 可选 |
| 数据源 | AKShare · WGC Gold Demand Trends · mock 降级 |
| 前端 | 纯静态 HTML + 内联 `<script>` + Chart.js · **无构建步骤** |
| 样式 | 原生 CSS 变量（4 主题：light / dark / auto / high-contrast） |
| 缓存 | 服务端 served cache（`quote_cache_ttl`）· SW 双 cache（gold-shell / gold-runtime） |
| 认证 | 服务端 sessions 表 + HttpOnly cookie + CSRF 双提交（V0.75.0）· 兼容开关 `AUTH_ENABLED` |
| 推送 | SMTP（aiosmtplib SSL/STARTTLS）+ Server酱（httpx）+ Web Push（pywebpush / VAPID） |
| 部署 | Docker 多阶段（镜像大小 1.2GB → 280MB **为设计目标、尚未实测**（V0.74.0 已首次真实构建成功并通过 smoke test，镜像体积仍未记录））+ docker-compose + Nginx + Certbot |
| 测试 | pytest 972 · ruff check / format · check_static_js.py（前端内联 JS 门禁）· check_docs_claims.py（文档声明门禁）· check_cluster_render.mjs（前端渲染行为门禁）· check_pwa_assets.py（PWA 资源门禁）· check_links.py（死链与锚点门禁）· check_deps.py（依赖声明门禁） |
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
python -m pytest -v                                      # 全量 972 用例；离线口径 928（按文件名排除 2 个联网 fetcher）
ruff check src tests                                     # lint
ruff format src tests                                    # format
python scripts/check_static_js.py                        # 前端内联 JS 门禁（语法 / 未定义调用 / DOM id）
python scripts/check_docs_claims.py                      # 文档声明门禁（表名 / localStorage key / 页面 / 端点存在性）
node scripts/check_cluster_render.mjs                    # 前端渲染行为门禁（抓取真实代码块在 Node 里执行后断言产出）
python scripts/check_pwa_assets.py                       # PWA 资源门禁（SW 缓存版本 / SHELL_ASSETS / manifest.json 目标）
python scripts/check_links.py                            # 死链门禁（文档内部链接与标题锚点）
python scripts/check_deps.py                             # 依赖声明门禁（src+tests 三方 import vs pyproject）
```

> ⚠️ **`-m "not network"` 在本仓是无效过滤** — `pyproject.toml` 未注册 `markers`、`tests/` 也无任何 `@pytest.mark.network`，该过滤**不排除任何用例**。真正的离线口径是**按文件名排除**：`--ignore=tests/test_services/test_irfcl_fetcher.py --ignore=tests/test_services/test_h15_fetcher.py`（44 用例）。

> ⚠️ **前端没有构建步骤** — JS 写错不会被任何编译期拦截，却会让整页脚本失效（按钮无响应、数据不加载），而后端测试依旧全绿。改完 `static/*.html` / `static/*.js` 后**务必**跑 `check_static_js.py`（等价于 `make check-web`）。

## 版本历程

> ⚠️ **本表的「日期」是提交日期，不是标签创建日期 —— 两者在历史上并不总是同一天。**
> 2026-10-03 做的全量标签审计（标签对象 SHA + 剥离提交 SHA 与远程逐一双向对账，39/39 全等）确认了两点限制，记录在此以免日后误用：
>
> 1. **11 个标签是事后批量补打**：v0.53.0–v0.60.0 共 8 个在 2026-09-12 一次性补齐，v0.67.0–v0.69.0 补于 09-19，v0.70.0–v0.73.0 补于 09-23。→ 这些版本的**真实发布时刻在 Git 中已不可考**，只有「提交时刻」可靠。**自 v0.74.0 起已规范**：每个标签都在对应提交后 1 分钟内创建。
> 2. **两个标签指向晚于「版本号首现」的提交**：`v0.74.0` 指向 `7c96d82`，而版本号首现于 `def5c5c`（中间隔 8 个提交）；`v0.75.1` 指向 `f6f0f6a`，属**有据可查的有意重发**（该提交信息即写明「修复 V0.75.0/V0.75.1 发布链路中断（重发 v0.75.1 标签）」）。→ 因此 `git checkout v0.74.0` 取到的是「V0.74.0 + 8 个后续修复」，**不是发布当刻的快照**。
>
> 两点都**不影响版本归属**：39 个标签内声明的版本号与标签名**全部相符**（`src/app/__init__.py` 的版本单源自 v0.74.0 起存在，仅影响「取到哪一刻的代码」）；v0.74.0 之前的 29 个标签因当时尚无版本单源，无法做这项比对。另：v0.51.0 / v0.51.1 / v0.64.0 / v0.65.0 / v0.66.0 为**轻量标签**（无 tag 对象、无 tagger 与说明），其余 34 个为标注标签 —— 保留现状，不做删改（重建会改变标签 SHA，收益低于风险）。

| 版本 | 日期 | 亮点 |
|------|------|------|
| **V0.78.2** | 2026-10-05 | **门禁可信度修复（补丁版）**：V0.78.1 刚立起三道门禁，本版修的是**门禁自身会不会被误读**。① **CI 门禁的 skip 面** —— GitHub Actions 的 step 默认条件是 `if: success()`，前序任一失败则其后**全部 skipped**，而 skipped 在界面上与「通过」仅一线之隔（本仓已有两次代价：docker job 曾因 `on.push` 未声明 `tags` 而**从未执行**却被读成「CI 全绿」，掩盖 20+ 版本的容器启动崩溃；V0.78.1 的三道新门禁位于 pytest 之后，pytest 一挂即被 skip）。现**八道门禁全部带** `if: always() && steps.install.outcome == 'success'` —— `always()` 保证每道门禁自己给出结论、不被别人的失败掩盖；但依赖必须装成功，否则会产生 8 个红 step 把唯一真实原因（`uv sync` 失败）淹没。② **PWA 门禁补常驻回归测试**（`tests/test_scripts_check_pwa_assets.py`，**14 例**）—— V0.78.1 时另两道新门禁各带 10 / 11 例，唯这一道的负向验证是**手工**做的、做完即不可复查；为此把该脚本的输入路径全部参数化（新增 `check_all()` / `Info` / `_rel()`），使其可对临时目录注入坏数据。③ **`SHELL_ASSETS` 的 307 条目确认「不可改」** —— V0.78.1 记下的「建议改写最终 URL」**是错的**：读 `sw.js` 的 fetch 分支才发现 HTML 页面走 network-first、离线兜底是 `caches.match(request)`，而 `request.url` 就是用户地址栏里的 `/portfolio`，缓存 key 必须与之一致；改成直连地址反而会让离线访问落到 `offline.html`。已写清理由并加回归锁（教训：**偏离直觉 ≠ 应该改**，记待办前先确认消费方怎么用它）。④ **ruff 0.16.6 → 0.16.10**（锁版范围内）+ **五个 GitHub Action 全部升到 Node 24** 运行时（checkout@v7 / upload-artifact@v7 / setup-uv@v7 / setup-buildx-action@v4 / build-push-action@v7），消除 Node 20 弃用提示；升级前逐个核对了目标版本的 breaking 与本项目用到的参数 —— 但**核对用的是精确标签（`v10.2.0`）、写进 workflow 的却是移动标签（`@v10`）**，而 `setup-uv` 作者只维护到 `v7` 的移动标签 ⇒ 首次推送即 `Set up job` 失败（失败发生在第一个 step 之前，日志里没有任何可诊断信息）。已改用 `@v7`（指向 v7.6.0，`using: node24`）并复跑通过。**刻意不做 `uv lock --upgrade`**：dry-run 显示 23 项变更含 `sqlalchemy 2.0.52 → 2.1.3`（跨大版本，且本仓有 `sqlalchemy 2.1.x` 致容器启动即崩的记录），属独立版本 + 容器验证的范畴。**接口零新增**；用例 972 → **986**（+14），模块 66 → **67** |
| **V0.78.1** | 2026-10-05 | **收口与门禁补齐（补丁版）**：把 V0.78.0 遗留的三个缺口收口，并把「同类缺陷换个地方再犯」变成机械可拦。① **SW 缓存版本脱钩（用户可见的静默缺陷）** —— `static/sw.js` 的 `const VERSION` 自 2026-09-21 起停在 `v0.77.1`，而 V0.77.2 与 V0.78.0 **都改过静态资源**：`/static/` 走 cache-first 且不后台更新 ⇒ sw.js 字节未变就不触发浏览器重装 SW；即便重装，`activate` 按 VERSION 清缓存也因名字没变而失效 ⇒ **已装 PWA 的用户长期「HTML 新 + JS 旧」错配**，比整站皆旧更难排查。现 VERSION 同步为 `v0.78.1`，并由新增门禁强制「SW 版本 == 应用版本」。② **PWA 快捷方式两条 404** —— `manifest.json` 的 `shortcuts` 指向 `/silver` 与 `/backtest`（实测 404，真实路径是 `/static/silver.html` 与 `/static/backtest.html`）。③ **共振缺维不再伪装中性** —— `compute_resonance` 原把缺失维度按 50 参与方向与幅度判定（实测 `macro=50, news=65`、技术面缺失时会标成 `tech_news`，而技术面根本没有数据），现只把**有效维度**纳入判定、任一维缺失的维度对直接跳过，新增响应字段 `missing_dimensions`，`_summarize` 对缺失维度输出「X 数据不足」而非「中性(50)」。④ **补 `starlette` 依赖声明** —— `src/` 直接 import 却未写进 `dependencies`（它是 fastapi 的强依赖故实际不会崩，属**隐患**，与偏差 #60 同类）。**护栏（本版重点）**：新增**三道机械门禁**并接入 CI，质量门禁由 5 道增至 **8 道** —— `check_pwa_assets.py`（SW 缓存版本 / `SHELL_ASSETS` 逐条可解析 / `manifest.json` 目标存在）、`check_links.py`（20 份文档的 109 条内部链接 + 锚点）、`check_deps.py`（`src/**` 三方 import 必须在 `dependencies`）；三道门禁的断言均先经**负向测试**验证会报错（修复前跑必然红）。**接口新增 1 个响应字段** `missing_dimensions`（非新端点）；用例 945 → **972**（+27 = check_links 10 + check_deps 11 + 共振缺维 6），模块 64 → **66** |
| **V0.78.0** | 2026-10-05 | **一致性收口：阈值口径统一 + 决策补全 + 兜底差异化**：把「55 到底是 UP 还是中性」这一整类口径冲突解决掉，四个 Step 一并交付。**Step A · 阈值常量集中**：新增 `src/app/schemas/thresholds.py`，四组 **IntEnum** —— `DirectionThreshold`（单维度 / 消息面 70/55/60/40/45/25）、`LevelThreshold`（等级 75/55/45/25）、`DecisionThreshold`（决策矩阵 75/65/55/50/40）、`OpportunityWindowThreshold`（投资窗口 70/55/40），替换 `macro.py` / `scoring.py` / `decision.py` / `news.py` / `resonance.py` 的裸字面量；新增 `tests/test_services/test_thresholds.py` **25 例**（含以 **AST 遍历** 机械保证服务层不再出现裸阈值字面量 —— 用 AST 而非 grep，因为 grep 会命中 docstring 与注释里的数字、也扛不住行号漂移）。**关键结论：「硬编码」不是一种语义、而是四种**：仓位档位可复用 `LevelThreshold`（与 `trend._to_level` 分界点完全一致），投资窗口语义独立须新增枚举，而指数着色 55/40 **有意保留**（40 故意不同于 `BEARISH`(45) 以更早示警，属产品语义决策）→ 路线图「校验：预期只剩 `thresholds.py` 一处定义」**未达成且不打算达成**，剩余字面量分属不同语义。**Step B · 决策档位补全**：`DecisionAction` 由 4 档扩到 **9 档**（`BUY_HEAVY`≥75 / `BUY`≥65 / `BUY_LIGHT`≥55 / `WAIT`<55；`ADD` / `HOLD` / **新增缓冲档 `HOLD_CAUTIOUS`≥40** / `REDUCE` / `SELL`），**StrEnum 保证 `DecisionAction.BUY == "BUY"` 仍成立 → 旧测试零修改**；消除「指数 60-70 × 盈亏 -10%~+15% 什么都不做」的**卡死区**；前端 9 档映射 + i18n 三语。**Step C · 共振反向识别**：`DIVERGENT` 由「只看方向相反」扩展为**三维幅度判定 + 子类型**（`tech_news` / `news_vs_macro` / …，取幅度最大的一对），补齐「消息面与另两面反向」这一整类漏判 —— 实测真实数据 `signal=divergent, subtype=tech_news, confidence=23.1`（`|3.8−50| = 46.2` 大于 tech-macro 的 `38.4`，正确选中最大幅度对，且 `46.2 × 0.5 = 23.1`），**改前该场景判 `neutral`**。**Step D · 兜底差异化（本版最重要）**：修掉**两种「假中性 50」** —— ① 技术面 5 维度数据不足时原先一律返回 `50` 且用字符串标注「数据不足」，与「真的算出来是中性」**同形**；② `_alignment_score` / `_support_score` 返回 `50, "均线数据不足"` 亦同形。现 5 维度 `score` 改 **`float \| None`**、门槛集中为 `DIM_MIN_BARS`（结构 40 / 动量 21 / 支撑 20 / 动能 15 / 回撕 10 根 K 线），数据不足返回 `None` + `reason`，前端灰色「— 未计入」 + 空进度条 + `data-insufficient="1"`；**维度级归一化**（`contribution = score × weight / Σ有效权重` ⇒ `Σcontribution` 恒等于上级指数）与**面级归一化**（某面不可用时**剔除该面**、按剩余面权重归一化，不再用 50 稀释）。顺带修 2 个既有缺陷：① **`_rsi` 守卫 `<= period` 允许 15 根收盘价，而循环最低读 `closes[-(period+2)]` ⇒ 恰好 15 根时 `IndexError` 冒泡（HTTP 500）**，改 `< period + 2` 并把该崩溃点写成断言；② W/M 视图的中性 50 披露文案原写在**从不进入响应**的 `tech_index.summary` 上（实测全部引用点：该字段只被读 `.score`）→ 等于**从未披露**，现新增 `tech_note` 写进对外可见的 `index.summary`。W/M 之所以保留 50 不改为 `None`：**「口径不适用」≠「数据不足」**，且要保跨周期可比性。另修 `static/silver.html` 字段名写错（`i.desc` → `i.detail`，原恒为空）与 `static/weights.html` 预览的面级归一化。**验证**：五道门禁全绿（format 187 files / 渲染 125 条 / 文档 408 处）；定向 `test_trend.py` **142 passed**；**零行为变更由「新旧实现差分」独立证明**（6 组序列 5 维度逐字段相同）；W/M 端到端 `index=46.9`、`components={tech:50.0, macro:42.2, news:50.0}` 与改前逐字段一致。**接口零新增**，用例 867 → **945**（+78 = Day 1 36 + Step C 7 + Step A 收口 25 + Step D 10），测试模块 63 → **64** |
| **V0.77.2** | 2026-10-03 | **数据不丢与交互安全（补丁版）**：V0.77.1 修的是「失败态被伪装成正常」，本版修的是下一层 —— **「操作明明点了保存，数据却悄悄丢了」与「操作没成功，界面却毫无反应」**。四条的共同特征是**页面看起来完全正常**（这正是它们能存活至今的原因），只在客户的复盘数据与决策依据上留下不可逆的空洞。① **`/news` 保存打分时 `basis` 与 `review_note` 从未提交** —— `save()` 的请求体只有 `{score, direction, notes, slot}`，而页面 L406-407 **明明有依据回填逻辑**（`selectedBasis` 从 `state` 读、`reviewNote` 回填）、后端 `services/news.py:233-234` 也**确实写库**（`basis=dump_basis(payload.basis)`），唯独「提交」这一步漏了两个字段 → 客户认真勾的 12 个研判依据**每次保存即被静默抹掉**（仓库层 `repositories/news.py::upsert` 的 UPDATE 分支 `existing.basis = basis` 是**硬覆盖**），而在本页填写的复盘批注则**从头到尾从未落库**（`review_note` 走 `review_note or existing.review_note` 空值保留旧值 → **不会被抹**，属「填了等于没填」；**两者后果不同，不可一并说成「都丢了」** —— 已由 2026-10-03 临时库实测确认：对同一槽位发窄请求体后 `basis` 归零、`review_note` 仍保留），复盘页「依据胜率」永远算不出，而客户会以为是自己没勾；现补上两字段（`basis` 用 `Array.from(selectedBasis)` —— **`selectedBasis` 是 `Set`，直接 `JSON.stringify` 会得到 `{}`**，这是修复时必须避开的陷阱）；② **`/portfolio` 开仓价格框被轮询反复清空** —— `renderDecision`（由 60 秒轮询反复调用）里原写 `document.getElementById("price").value = d.trend_index ? "" : "";`，**两个分支同值 = 恒清空**，注释却写「预填开仓价格」：它既没预填（`trend_index` 是指数取值、不是价格），还把 `fillPrice()` 在初始化时填好的 ETF 最新价抹掉，同时 `priceHint` 还写着「已自动填入，可修改」，前后自相矛盾、且可能让客户按空价提交；现改为「仅在价格框为空**且客户从未手动输入过**时才补一次预填」（新增 `priceTouched` 标记 + `input` 监听，程序化赋值不触发 `input` 故不会误置位）；③ **`/review` 空态指引断死** —— 提示「若想补录历史研判，可在该页填写并指定日期」，但 `/news` 的打分编辑器**并无日期控件**（补录能力属 V0.78.0 的 B3/B4），客户照做必然找不到入口；现改为可执行指引（去 `/news` 打分 → T+N 到期自动进本页验证 → 可点「📥 回填历史金价」补金价数据），并**如实说明「历史研判的补录入口尚未开放」**；④ **`/weights`「恢复默认」无二次确认、无错误处理** —— `resetAll()` 用一份内置常量整体覆盖客户自定义权重并立即保存，而原实现既无确认、也无 `try/catch`、`if (r.ok)` **无 `else`**：一次误点即不可逆地改写综合指数与决策，失败时页面毫无动静（客户会以为已恢复，实际权重没变）；现新增二次确认弹窗（自包含实现 + **Esc 可取消**）、`try/catch`、失败明确提示并带出后端原因、成功后以后端返回为准重渲染。**门禁**：`check_cluster_render.mjs` 由 **102 → 125 条**断言，新增第 9 节「数据不丢与交互安全」—— 四条全是「静默错误」，正常路径与人工点页面都看不出来，故**真实执行源码片段**并配反向断言：B1 真实跑 `save()` 并捕获它实际发出的请求体（断言 `basis` 为数组且内容正确、未选时为空数组、原有字段未被破坏）、B2 真实跑轮询那段价格逻辑（空且未编辑 → 补预填；已编辑或已有值 → 一律不动）、C2 真实执行确认弹窗（取消→false / 确定→true / Esc→false）与 `resetAll()`（**取消时一个请求都不发**、确认时提交的确实是默认值且三组各自归一、500 时提示失败并告知「权重未被改动」）。**接口零新增、用例数不变 867**。另修复一处门禁自身的可用性问题：`check_static_js.py` 的箭头函数形参正则 `\(([^)]*)\)\s*=>` 在 `new Promise((resolve) => {` 这类**带括号单参 + 外层调用括号**的组合下会贪婪跨括号、把 `(resolve` 当作形参名而漏收 `resolve`，导致误报「疑似调用了未定义的函数」（按既有页面的无括号写法 `resolve =>` 即可规避）；门禁第 9 节同时确立一条写法约定：**断言「旧写法已消失」时不可对全文 `includes`**，因为修复处的注释会有意保留旧代码作历史说明 —— 改用行首锚定正则区分注释行与真实代码行 |
| **V0.77.1** | 2026-10-02 | **信任修复：失败态不再伪装成正常（补丁版）**：V0.77.0 的客户交互易用性评估给出 55/100，结论是「功能覆盖完整，但**信任层**有结构性短板」—— 多数地方做对了（降级会明示、mock 有警示、空态有引导），却在关键路径上给出**与事实不符的正向信号**。本版修 5 类：① **数据健康页接口失败时 4 张概览卡全绿** —— `load()` 在 catch 里静默兜底成 `{sources:{}}`，于是 `total=0`、`live=0`，而判定式 `live === total` 在 `0 === 0` 时**成立** → 「实时 (live)」判 ok；`stale`/`mock` 因「> 0 才告警」也不成立 → 同样判 ok，而真实情况是一个数据源都没取到；现改为「接口失败」或「成功但零数据源」一律走 **「—」未知态**（新增 `.vl.unknown` 灰，视觉上明确区别于「已确认正常」），并把「哪个接口失败 + 这意味着什么 + 怎么办」写进提示条，提示条自身也从页面底部（紧贴 footer）移到概览区、与它解释的卡片同屏；② **消息面有效分的静态默认 `50.0`** —— `renderAll()` 开头 `if (!d) return`，接口失败时静态值永远留在页面上，而 50 恰是「中性」、又真占综合指数 30% 权重，客户会把它当「今天消息面中性」的结论来用；现改为占位 `—`，新增 `fmtScore()`（缺值一律「—」，真实的 0 仍显示 0.0）与 `renderLoadFailure()`（占位 + 禁用保存 + 明说「不代表今日中性 50」）；③ **白银页失败后永久停在「数据加载中…（首次约 10-30 秒）」** —— 加载条的隐藏只写在 `renderMain`（成功分支）里，失败路径永远走不到；现改由 `finally` 收起（成功/失败都走到），并把错误从页面下方的图表区提到首屏可见的 `#alertBar`，同时去掉「请确认服务已启动（127.0.0.1:8888）」这类对投资客户不可执行、又把部署细节暴露给无关人的文案，原始异常只进 console 供排查；④ **回测校准曲线**：「理论概率」正名为**完美校准基准线**（取值就是每桶分数中值 10/30/50/70/90，不由任何模型算出）并新增图下说明；**停止绘制「实际命中率」假线** —— 复核发现 `_bucket_data` 在后端**从未存在过**（`services/backtest.py:44` 定义了 `_CALIBRATION_BUCKETS` 五桶常量、注释写「与 review._calibration 共享形状」，但全仓无任何调用点，`BacktestResultOut` 也无分桶字段），该曲线自 V0.71.0 起一直是恒为 0 的假线，客户读到的是「模型命中率 0%」；现缺数据时整条曲线不入图（**缺数据 ≠ 命中率 0%**）、桶内无样本留 `null` 断线，前端按「后端补上字段即自动生效」写好；⑤ **Service Worker 的只读 API 由 stale-while-revalidate 改为 network-first** —— 原策略先返回缓存、后台再更新缓存，而缓存**没有 TTL**，于是**在线**也可能拿到上次会话的响应（`review` / `news` / `weights` / `backtest` 这几页只拉一次数据、不会自我校正）；现网络优先，仅网络失败时回退且须满足两道闸：**价格类端点（`/market/gold*`、`/market/silver*`）永不回退**（过期价格比无数据更危险，宁可让页面明示取数失败）、其余回退须在 **30 分钟**内（超期即从缓存删除并抛错让页面走错误态）；回退时注入 `X-SW-Cached-At`（真实缓存时点）由时效条披露「本页数据来自离线缓存（时点）」；顺带**不再把 4xx/5xx 写入缓存**（原先会把失败响应回放成「正常」）。**门禁**：`check_cluster_render.mjs` 从 33 条断言扩到 **102 条**，新增第 7 节「失败态渲染」与第 8 节「接线与 SW 缓存护栏」—— 本包五条改的全是失败路径，正常请求走不到、人工点页面看不出来，因此直接构造「接口挂掉」的输入执行各页**真实的失败分支**（`load()` 用桩 fetch 端到端跑通、断言失败标记确实传到了渲染层；`sw.js` 的 `serveStaleApi` / `cacheApiResponse` 用桩 caches + 真实 `Response` 真实执行：价格端点拒绝回退、新鲜缓存可回退且带出缓存时点、超期缓存被拒并清除、5xx 不入缓存），并保留「6 源全 live 时仍恢复正常判定」的反向断言以防把正常态一起改坏。用例数不变（**867**），i18n 三语各 +7 键（`health.err_failed` / `health.src_health` / `health.src_freshness` / `health.list_sep` / `health.err_meaning` / `health.err_advice` + `fresh.offline_cached`），并给 zh-TW 补上原先缺失的 `backtest.calibration_chart_title`（该键另两语已有，本版改了文案） |
| **V0.77.0** | 2026-10-01 | **界面聚类分组（同类项归簇）**：全站 13 页审计出 23 处「同类项平铺 / 同一数据多出口」—— 属于同一语义类别的信息项平铺在一个容器里、没有分组标题，用户得一条条读完再自己归类；更严重的是同一份数据在多处渲染，字段互补却要人肉横向对照。本版新增**全站统一的聚类样式基元**（`theme.css` 的 `.pmc-cluster` / `.pmc-tabs` / `.pmc-group` / `.pmc-grid-title` / `.pmc-count`，只用主题变量故 light / dark / hc 自动适配，前缀 `pmc-` 避开页面私有类名），落地 5 处改造：① **首页 `#cards` 8 张 KPI 磁贴 → 3 组**（价格 / 涨跌 / 均线），`#sgeCards` 6 张 → 2 组；② **`/trades` 6 张 KPI → 2 簇**（成交规模 / 成本与收益）、9 个筛选字段 → 2 组（查询条件 / 输出动作，靠虚线分隔，不再需要 3 处手工对齐的空白 label）；③ **`/data-health` 同一批 6 个数据源从「6 张状态卡 + 6 行时效表」两处渲染合并为一处**，按 `SOURCE_LABELS` 的天然分组聚成**黄金 / 白银**两组、状态与时效同卡展示，并去掉暴露内部键名的「键: etf」技术噪音（`renderFreshnessTable` 整体移除）；④ **`/review` 三组同构横条**（按研判方向 / 按判定窗口 / 按分值档位 —— 同由 `barRow()` 渲染、同取一份 `stats`，却散在两张卡里）**并为 1 个「统计分面」簇 + Tab**，Tab 支持 ←/→ 键盘切换，独立「分值校准」卡并入第三个 tab。**同批修复 3 处既有缺陷**：首页 4 张快照卡用 `class="val"` 而样式表只有 `.card .value` → 数值**一直没有任何字号字重样式**；`/news` 历史表**表头 7 列 vs 数据 8 列错位**（「备注」表头实际对着依据列、末列无表头，空态 `colspan=7` 与错误态 `8` 自相矛盾）；央行页顶栏**缺「研判复盘」链接**（其余 10 页都有）且堆叠图图例只显示 ISO 代码（`UZB`）、与表格中文国名对不上。**新增第 4 道门禁** `scripts/check_cluster_render.mjs`：从各页源码提取**真实的聚类代码块**、用最小 DOM 桩在 Node 里**真实执行**并断言产出的 HTML 结构（簇数量 / 簇标题 / 卡片数 / 分组顺序，共 33 条断言），补上「静态门禁全绿 ≠ 渲染正确」的盲区（`check_static_js.py` 只查语法 / 未定义调用 / DOM id）—— 开发期就踩过一次「只提取到函数定义却没调用它、`innerHTML` 为空却看着通过」。用例 866 → **867** |
| **V0.76.0** | 2026-09-30 | **首页内嵌消息面打分器（客户评价上首页）**：消息面占综合评估指数 30%，但 V0.75.1 收敛「今日操作清单」后，首页只剩 `#newsFactor` **一行只读**展示 —— 想记一次判断必须整页跳到 `/news`。本版把打分能力**内联到趋势追踪页**（`static/news-score-widget.js`，IIFE + `window.PM_NewsScore`，自注入 CSS 适配 4 主题）：① **3 槽位状态一览**（分值 / 权重 / 方向 / 提交时刻 / 备注 / 补录标记）；② **当日有效分值** + 后端返回的**加权算式原样展示**（`(1×45 + 2×70) ÷ 3 = 61.7`，**前端不重算**，口径与 `/news`、复盘页同源）；③ **编辑器**：滑杆 + 快捷档位 + 「沿用上次」+ 方向判定 + 研判备注 + 12 个研判依据标签（取 `/api/v1/review/meta`）+ 复盘批注；④ **保存后即时刷新**上方「综合研判结论卡」与「消息面评估」行（组件派发 `news-score-changed`，首页监听后重算），全程不跳页。**`/news` 保留为完整详情页**（投行参考来源 + 历史记录），首页为其轻量通道。**刻意不轮询**：打分器含可拖拽滑杆与文本框，定时重渲染会打断输入（滑杆跳回、光标丢失），故只在提交后自渲染。i18n 三语各 +64 个 `nsw.*` 键并新增 2 条门禁（脚本引用键三语齐全 + 三语键集合严格一致）；`sw.js` VERSION → `v0.76.0` 并把新脚本纳入 `SHELL_ASSETS`。用例 864 → **866**（+2 = i18n `nsw.*` 门禁 2） |
| **V0.75.1** | 2026-09-29 | **首页综合研判结论卡（面向「一眼决策」）**：首页此前把判断原料（综合指数 / 三维分值 / 共振类别 / 决策建议 / 建议仓位 / 理由明细）**平铺在 6 个面板里**，用户要自己扫一遍再心算「到底该不该动」。本版把原料**收敛成一张置顶结论卡**：① **一行结论**（观望 / 买入 / 加仓 / 持有 / 减仓 / 卖出 + 综合指数 + 等级 + 置信度）；② **三维分值条**（技术 30% / 宏观 40% / 消息面 30%，带权重与 ↑↓→ 方向）；③ **一致性判定**（三维同向看多/看空、弱同向、**技术 vs 宏观分歧**、中性 —— 口径**复用后端 `compute_resonance()`**，阈值 55/45 与置信度折扣同源，前端**不重算**）；④ **建议仓位 vs 当前持仓**对照；⑤ 决策依据（逐条方向着色）；⑥ **数据质量提示**（宏观静态参考值项数、行情源 Mock 降级如实标注）→ 便于用户自己折可信度。**黄金 ↔ 白银一键切换**（localStorage 记忆）。为支持白银口径，`GET /api/v1/resonance/signal` 新增 `target` 参数（`ny/etf/gram/silver_etf/silver_ny/silver_gram`，默认 `etf`，非法值 422）——此前白银页共振卡**写死 `etf`、一直显示黄金的三维分值**。同步收敛首页重复面板（删除 `#resonanceCard` 与「今日操作清单」两块，能力并入结论卡）、修复 `PM_Resonance.mount()` **未导出却被 `silver.html` 调用**（该页共振卡实际从未挂载成功）。测试 845 → **864** 用例（离线 820） |
| **V0.75.0** | 2026-09-29 | **认证骨架（多用户登录第一步）**：新增 `users` / `sessions` 两张表（迁移 `d5f81a3c9b47`）+ 6 个认证端点（status / register / login / logout / me / change-password）+ `static/login.html` 登录注册页 + 12 个页面顶栏账号菜单（含改密弹窗）。**密码 bcrypt cost=12**（未知账号也跑一次同代价哈希，防账号枚举）；**服务端 sessions 表**存储会话，登出 / 改密 / 禁用**即时撤销**；cookie `HttpOnly` + `SameSite=Strict`；写端点 **CSRF 双提交校验**（中间件自动下发 `pm_csrf`，`auth.js` 给全局 `fetch` 打补丁自动回填 `X-CSRF-Token`，故既有 11 个页面的几十处写请求**一行未改**）；登录失败**账号 + IP 双维度节流**。**默认 `AUTH_ENABLED=false` 为单用户模式**：Auth / Csrf 两个中间件完全透传（不读 cookie、不查库、不下发 cookie），既有 728 用例零破坏。业务数据隔离（`user_id` 透传）留给 V0.75.2 |
| **V0.74.3** | 2026-09-29 | **趋势页克价图去重（面板合并）**：对照面板的 `#cmpGramChart`（上海金 Au99.99 · 元/克）与页面上方「上海金 Au99.99（元/克）· 国内金价对照」面板的 `#sgeChart` 是**同一标的、同一 60 交易日窗口** → 同一根曲线画两遍，读者误以为是两个不同品种。改为**图形只画一次**：克价走势统一由上方面板承载（含 MA20/MA40），对照面板只保留 `黄金ETF 518880 · 元/份` 单图 + `#cmpTable`/`#cmpCards` 的 **ETF vs 克价指标对照表**（对比信息不丢，只是不再重复绘图）。同步调整 `trend.cmp_title` 文案（zh-CN / en-US，zh-TW 走简中 fallback）、移除 `.cmp-charts` 双列栅格、单图高度 220 → 260px 与上方面板对齐。**同批依赖本地化**：5 个页面（trend / portfolio / silver / backtest / central_bank）的 Chart.js 由 `cdn.jsdelivr.net` 改为随应用分发 —— `static/vendor/chart.umd.min.js`（4.4.3）+ 纳入 Service Worker 预缓存清单，消除「公网不可达 / 离线时**所有图表静默空白**」的隐患（此前 `SHELL_ASSETS` 里根本没有它，PWA 宣称的离线能力对图表无效） |
| **V0.74.2** | 2026-09-29 | **对照面板改为真实价格 + 2 处轮询期缺陷修复**：① 趋势页「ETF vs 克价 对照」原来是**归一化双线图**（`起点=100`，Y 轴裸数字 96/100/104 极易被误读成价格或评分）→ 改为**两张并列的真实价格图**：左 `黄金ETF华安 518880 · 元/份`、右 `上海金 Au99.99 · 元/克`，各带 `起价 → 现价 涨跌%` 标题行；接口 `points` 新增 `etf_price` / `gram_price`（归一化字段 `etf` / `gram` 保留，向后兼容）。② `#badge` 曾用 `outerHTML` 整体重建（新节点**不带 id**）→ 页面每 60 秒自动刷新，**第二次即抛 `Cannot set properties of null`、主图面板整块消失**；改为就地更新。③ 对照图 / 上海金图未 `destroy()` 即 `new Chart()` 复用画布 → `Canvas is already in use`（每个轮询周期必现）；改为重建前先 `destroy()` 并置 `null`。附带修复 i18n BOM 测试里的**永真断言**（`b"\ufeff"` 是非法转义、实为 6 字节字面量，断言永远通过） |
| **V0.74.1** | 2026-09-29 | **前端功能缺陷修复**（3 处此前被前端门禁「全绿」掩盖、用户直接碰壁的问题）：① `ChartA11y.wrapChart` 是 a11y 包装器（只打 aria 属性、**不创建实例且无返回**），却被 5 处调用方当图表工厂用 → 实例恒 `undefined` → 白银页/回测页画布**永久空白**（已改为 `new Chart()` 创建 + 单独补 a11y）；② `backtest-chart.js` 的加载位置晚于调用点（内联脚本解析期即调 `PM_Backtest.mount()`）→ TypeError 中断整段脚本 → 回测按钮/自动回测/参数监听**全未绑定**（已把该脚本移到内联脚本之前）；③ Service Worker 预缓存含 3 条服务端不存在的 URL（实测 404）→ `cache.addAll` 原子失败 → 离线缓存**全空**（已改为真实路径，20 条 URL 全部 200） |
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

---

## 功能拓展路径（V0.78.0 → V0.79.0）

> 标注规则：**✅ 已落地**（代码 + 测试齐备）/ **🟡 部分落地**（主体验收项已合，子项有遗留）/ **📋 规划中**（路线已定，待排期）。本节与 [docs/ux-roadmap.md](docs/ux-roadmap.md)（范围 **V0.68.0 → V0.78.0**）同步维护，**冲突时以路线图为准**；**V0.76.1 为 README 展望，尚未纳入路线图**。

### V0.74.0 · 仪表盘自定义 + 通知偏好（**🟡 部分落地**，N+11~N+18）

| 子项 | 状态 | 落地位置 |
|------|------|----------|
| **告警规则 CRUD** · discriminated union 重构（`VolatilityRule` / `CrossingRule` / `WindowRule` / `TPlusNRule`，discriminator `RuleKind = Literal["volatility","crossing","window","t_plus_n"]`）+ UI 模态 + i18n 三语 | ✅ 已落地 | `src/app/schemas/alert.py` · `src/app/services/alert.py` · `/static/settings.html` |
| **portfolio 仪表盘自定义** · 7 张卡片拖拽排序（纯原生 HTML5 drag/drop + Space/↑↓ 键盘替代）+ 布局持久化到 `localStorage.pm_dashboard_layout` + 一键恢复默认 | ✅ 已落地 | `static/portfolio.html` · `static/dashboard.js` |
| **数据健康独立页** · 各行情源实时性 / 覆盖率 / 降级状态一览 + trend 页三清理 + 全站 nav 接入 | ✅ 已落地（**V0.73.0 N+16**，非本版产出） | `/static/data-health.html` |
| **CI 门禁 + 版本号单源化** · ruff lint 0 / format 174 files / `src/app/__init__.py` 作版本号唯一真源（根治 V0.63/V0.65/V0.73/V0.74 连续四次漏改） | ✅ 已落地 | `.github/workflows/ci.yml` · `src/app/__init__.py` |
| **打印友好 CSS + 一键 PDF 导出**（路线图 V0.74.0 子项 ③） | ⏳ **未落地** | 仅 `portfolio.html` 有 `@media print` 隐藏拖拽控制条；无 `window.print()` 入口、无 `pdf_export_click` 埋点 → 路线图 M7 验收项「PDF 导出 ≤ 2 页」**尚未满足** |

### V0.75.0 · 多用户登录 + 数据隔离（**🟡 部分落地** —— 认证骨架已上岸，数据隔离待续）

已按「认证骨架 → 数据隔离 → 找回密码」三步递进拆分（对应 `0.75.0 / 0.75.2 / 0.75.3`，中间 `0.75.1` 让位给首页综合研判结论卡），本次交付第一步：

| 子项 | 状态 | 落地位置 |
|------|------|----------|
| **认证体系** · bcrypt cost=12（未知账号跑同代价伪哈希防枚举）+ 服务端 `sessions` 表 + cookie `HttpOnly`/`SameSite=Strict`/`Secure`(可配) + CSRF 双提交 + 登录失败账号/IP 双维度节流 + `AUTH_ENABLED` 兼容开关（默认 `false`，单用户模式零回归） | ✅ 已落地 | `src/app/services/auth.py` · `src/app/middleware/auth.py` · `src/app/models/user.py` |
| **登录入口** · `/static/login.html`（登录/注册双 Tab + 初始化管理员引导 + 三语错误码映射）+ 12 个页面顶栏账号菜单（改密 / 登出，`window.PM_AUTH`） | ✅ 已落地 | `static/login.html` · `static/auth.js` |
| **API 面** · `GET /api/v1/auth/status`（匿名可访问）· `POST /api/v1/auth/register` · `POST /api/v1/auth/login` · `POST /api/v1/auth/logout` · `GET /api/v1/auth/me` · `POST /api/v1/auth/change-password` | ✅ 已落地 | `src/app/api/v1/endpoints/auth.py` |
| **数据隔离**（`user_id` 透传业务表 + 越权审计） | 📋 **规划中（V0.75.2）** | ⚠️ 本版仅「登录后才能用」，**用户之间尚未隔离数据**；`accounts.user_id` 字段 V0.62.0 起已预留（恒为 1） |
| **找回密码**（邮件 token，30 分钟过期） | 📋 **规划中（V0.75.3）** | 依赖 V0.72.0 SMTP；本版改密需已知当前密码 |
| **审计日志** | 🟡 部分落地 | 登录成功/失败已入 `telemetry_events`（`login_success` / `login_fail`）；独立的 `audit_log` 表（含跨用户访问尝试）随 V0.75.2 数据隔离一起做 —— 没有隔离就没有「越权」，此时建表只会收空数据 |

> ⚠️ **开启认证前请注意**：`AUTH_ENABLED=true` 会让**除健康检查 / 登录注册登出 / 埋点外的全部 API 都要求登录**。单机自用（只有自己访问 `127.0.0.1`）建议保持 `false`；仅在**对公网 / 局域网开放**时才需要打开。

### V0.75.1 · 首页综合研判结论卡（**✅ 已落地**）

> 起因：首页已有全部判断原料，但**散在 6 个面板**（评估摘要 / 共振卡 / 今日操作清单 / 每日评估历史 / 趋势维度 / ETF 对照），用户要自己横着扫一遍再心算结论 —— 缺的不是数据，是**收敛**。

| 子项 | 状态 | 落地位置 |
|------|------|----------|
| **置顶结论卡** · 一行结论 + 三维分值条（权重可见）+ 一致性判定 + 建议仓位 vs 当前持仓 + 决策依据 + 数据质量提示 | ✅ 已落地 | `static/synthesis-card.js` · `static/trend.html` `#synthesisCard` |
| **黄金 ↔ 白银切换** · 切换即换整套取数口径（trend target / decision target / resonance target 三接口同步），选择记忆在 `localStorage.pm_synthesis_asset` | ✅ 已落地 | `static/synthesis-card.js` |
| **`/api/v1/resonance/signal` 支持 `target`** · `ny` / `etf` / `gram` / `silver_etf` / `silver_ny` / `silver_gram`，默认 `etf`（与 V0.70.0 行为一致），非法值 422 | ✅ 已落地 | `src/app/api/v1/endpoints/resonance.py` · `src/app/services/resonance.py` |
| **一致性口径同源** · 5 类（强同向看多/看空、弱同向、分歧、中性）不在前端重算，一律取后端 `compute_resonance()`（阈值 55/45、`confidence = avg × (1 - stdev/55)`）→ 后端调阈值不会出现两处口径打架 | ✅ 已落地 | 复用 `src/app/services/resonance.py` |
| **首页去重收敛** · 删除 `#resonanceCard` 与「今日操作清单」两块重复面板（能力并入结论卡），「共振详情」模态与「历史 + STRONG_UP 胜率」下钻保留 | ✅ 已落地 | `static/trend.html` |
| **如实标注可信度** · `position_ratio` 后端恒为 0（账户本金未知）→ **不臆造「当前仓位 X%」**，只显示「空仓 / 持有 N 份 · 浮盈浮亏」；宏观静态参考值项数、行情源 Mock 降级逐条列出 | ✅ 已落地 | `static/synthesis-card.js` `qualityNotes()` |

### V0.78.0 · 一致性收口（**✅ 已落地**）

> 主题：**把所有「55 是 UP 还是中性」的口径冲突解决掉**，让方向判定在多个模块里口径一致。四个 Step 分四批提交：Day 1（A/B）→ C → A 收口 → D。

| 子项 | 状态 | 落地位置 |
|------|------|----------|
| **A · 阈值常量集中** · 四组语义互不相同的 IntEnum（方向 / 等级 / 决策矩阵 / 投资窗口），替换 5 个模块的裸字面量；`test_thresholds.py` 25 例（含 AST 断言服务层无裸阈值） | ✅ 已落地 | `src/app/schemas/thresholds.py` · `tests/test_services/test_thresholds.py` |
| **B · 决策档位 4 → 9 档** · 新增缓冲档 `HOLD_CAUTIOUS`(≥40)，消除「指数 60-70 × 盈亏 -10%~+15% 什么都不做」的卡死区；`StrEnum` 保证 `== "BUY"` 旧比较仍成立 | ✅ 已落地 | `src/app/schemas/decision.py` · `src/app/services/decision.py` · `static/portfolio.html` |
| **C · 共振反向识别扩展** · `DIVERGENT` 从「只看方向相反」扩为**三维幅度判定 + `subtype`**，补齐「消息面 vs 另两面」整类漏判（改前判 `neutral`） | ✅ 已落地 | `src/app/services/resonance.py` · `src/app/schemas/resonance.py` |
| **D · 兜底差异化** · 5 维度 `score` 改 `float \| None`（数据不足返回 `None` + `reason`，**不再伪装中性 50**）；门槛集中 `DIM_MIN_BARS`；维度级与**面级**归一化；W/M 保留 50 但补披露 | ✅ 已落地 | `src/app/services/trend.py` · `src/app/schemas/market.py` · `static/trend.html` · `static/silver.html` · `static/synthesis-card.js` · `static/weights.html` |
| **D 附带修复** · `_rsi` 守卫少算一根 → 恰好 15 根收盘价时 `IndexError` 冒泡（HTTP 500）；W/M 中性披露写在从不进入响应的 `tech_index.summary` 上（等于从未披露）；`silver.html` 字段名 `i.desc` → `i.detail`（原恒为空） | ✅ 已落地 | `src/app/services/trend.py` · `static/silver.html` |
| **API 契约文档同步** · `docs/api-reference.md` §6.2 / §6.3 补「数据不足不再伪装中性 50」契约（门槛表 / `reason` / 归一化 / 页面表现 / W-M 说明）与面级剔除归一化 + 共振下游耦合提示 | ✅ 已落地 | `docs/api-reference.md` |

> 本版**接口零新增**（仍 67 路径 / 76 端点）；用例 867 → **945**（+78），测试模块 63 → **64**；**无 DB 迁移**。
> W/M（周/月 K）视图**保留**中性 50 计入（「口径不适用」≠「数据不足」），但已在 `index.summary` 中**显式披露**。

### V0.77.2 · 数据不丢与交互安全（**✅ 已落地**）

| 子项 | 状态 | 落地位置 |
|------|------|----------|
| **B1 · 打分保存丢依据** · `basis` / `review_note` 未进请求体 → 复盘「依据胜率」永远为空，客户会以为是自己没勾 | ✅ 已落地 | `static/news.html` `save()` |
| **B2 · 轮询清空已填价格** · 两分支同值即恒清空，抹掉初始化预填的 ETF 最新价，可能让人按空价提交 | ✅ 已落地 | `static/portfolio.html` `renderDecision` + `priceTouched` |
| **B5 · 复盘空态指引断死** · 指向 `/news` 的「指定日期」能力，而该页并无日期控件 | ✅ 已落地 | `static/review.html` 空态文案 |
| **C2 · 权重恢复默认无确认无错误处理** · 一次误点即不可逆覆盖，失败还静默无反应 | ✅ 已落地 | `static/weights.html` `confirmDialog` + `resetAll` |
| **渲染门禁第 9 节** · 四条「静默错误」的真实执行断言（102 → **125 条**） | ✅ 已落地 | `scripts/check_cluster_render.mjs` |

> 本版为**纯前端补丁**：接口零新增、用例数不变（**867**）、无 DB 迁移。

### V0.77.1 · 信任修复：失败态不再伪装成正常（**✅ 已落地**）

> 起因：V0.77.0 的客户交互易用性评估给出 **55 / 100**，结论是「功能覆盖很完整，但**信任层**有结构性短板」—— 多数地方做对了（降级会明示、mock 有警示、时效条透明、空态有引导），却在关键路径上给出**与事实不符的正向信号**。对投资决策工具，这比功能缺失危险得多：客户一旦发现屏幕上某个数字与事实不符，整套决策依据都会失去可信度。本版只修「取数失败 / 缺数据时界面给出错误正向信号」这一整类问题，**接口零新增、用例数不变**。

| 子项 | 状态 | 落地位置 |
|------|------|----------|
| **数据健康页失败不再判「全绿」** · 接口失败或零数据源时四张概览卡走「—」未知态（新增 `.vl.unknown`），并给出「哪个接口失败 + 这意味着什么 + 怎么办」；提示条从页面底部（紧贴 footer）移到概览区、与它解释的卡片同屏 | ✅ 已落地 | `static/data-health.html` `renderOverall` / `failureText` |
| **消息面默认分改占位** · 静态 `50.0` → `—`；新增 `fmtScore`（缺值一律「—」，真实的 0 仍为 0.0）与 `renderLoadFailure`（占位 + 禁用保存 + 明说「不代表今日中性 50」） | ✅ 已落地 | `static/news.html` |
| **白银页失败态** · 加载条改由 `finally` 收起（原先只在成功分支隐藏 → 失败后永久停在「加载中」）；错误提到首屏 `#alertBar`，并去掉「请确认服务已启动（127.0.0.1:8888）」文案 | ✅ 已落地 | `static/silver.html` |
| **校准曲线正名 + 停止画假线** · 「理论概率」→「完美校准基准线」+ 图下说明；`_bucket_data` 经复核**后端从未实现**（`services/backtest.py:44` 的 `_CALIBRATION_BUCKETS` 常量无任何调用点），故停止绘制恒为 0 的「实际命中率」线（缺数据 ≠ 命中率 0%） | ✅ 已落地 | `static/backtest-chart.js` · `static/backtest.html` |
| **SW 只读 API 改 network-first** · 网络优先（在线必新）；价格类端点永不回退缓存，其余回退限 30 分钟内，回退时注入 `X-SW-Cached-At` 由时效条披露「来自离线缓存」；4xx/5xx 不再写入缓存 | ✅ 已落地 | `static/sw.js` · `static/freshness.js` |
| **失败态纳入渲染门禁** · 第 7 / 8 节新增 69 条断言（33 → 102）：构造「接口挂掉」的输入执行各页真实失败分支、桩 fetch 跑通 `load()` 接线、桩 caches 真实执行 SW 缓存护栏；含反向断言保证正常态未被一起改坏 | ✅ 已落地 | `scripts/check_cluster_render.mjs` |

### V0.77.0 · 界面聚类分组（**✅ 已落地**）

- **同类项归簇** · 新增全站聚类样式基元（`theme.css` 的 `.pmc-cluster` / `.pmc-tabs` / `.pmc-group` / `.pmc-grid-title` / `.pmc-count`），只用主题变量故 light / dark / hc 自动适配
- **首页 15 张指标卡归位** · `#cards` 8 张 → 3 组（价格 / 涨跌 / 均线）、`#sgeCards` 6 张 → 2 组、4 张快照卡修回 `.value` 样式
- **交易汇总归簇** · 6 张 KPI → 2 簇（成交规模 / 成本与收益）；9 个筛选字段 → 2 组（查询条件 / 输出动作），不再需要 3 处手工对齐的空白 label
- **数据健康去重** · 同一批 6 个数据源原先渲染两遍（6 张状态卡 + 6 行时效表），现**合并为一处**、按黄金 / 白银分组、状态与时效同卡；去掉暴露内部键名的「键: etf」技术噪音
- **复盘分面化** · 三组同构横条（按方向 / 按窗口 / 按分值档位）并为一个 **Tab 分面**，支持 ←/→ 键盘切换
- **新增第 4 道门禁** · `scripts/check_cluster_render.mjs` —— 提取真实聚类代码块、Node 真实执行、断言产出结构，补上「静态门禁全绿 ≠ 渲染正确」的盲区（V0.77.0 起 33 条；**V0.77.1 扩至 102 条**，新增第 7 / 8 节：失败态渲染 + 接线与 SW 缓存护栏；**V0.77.2 扩至 125 条**，新增第 9 节：数据不丢与交互安全 —— B1 真实跑 `save()` 抓请求体、B2 真实跑轮询价格逻辑、C2 真实执行确认弹窗与 `resetAll`）

### V0.76.0 · 首页内嵌消息面打分器（**✅ 已落地**）

> 起因：消息面占综合评估指数 **30%**，是三维里唯一**由用户自己产出**的维度。但 V0.75.1 收敛「今日操作清单」后，首页只剩 `#newsFactor` **一行只读**展示（其注释还写着"仅保留真正需要用户动作的 ② 消息面打分"，入口却没补上）—— 想记一次判断必须整页跳到 `/news`。**首页是每日必看的落地页，为打一次分而整页跳转，是本页最大的易用性缺口。**

| 子项 | 状态 | 落地位置 |
|------|------|----------|
| **3 槽位状态一览** · 每槽显示分值 / 权重（1:2:3）/ 方向 / 提交时刻 / 备注 / 补录标记，并可直接对某槽「修改」「撤销」 | ✅ 已落地 | `static/news-score-widget.js` · `static/trend.html` `#newsScoreCard` |
| **当日有效分值 + 算式原样展示** · 直接显示后端返回的 `formula`（如 `(1×45 + 2×70) ÷ 3 = 61.7`），**前端不重算加权**，与 `/news`、复盘页同源（`services.news.aggregate_slots`） | ✅ 已落地 | 同上（`GET/PUT/DELETE /api/v1/news-score`） |
| **内嵌编辑器** · 滑杆（0-100）+ 快捷档位（看空 30 / 中性 50 / 看多 70）+「沿用上次」+ 实时方向判定 + 研判备注 + 12 个研判依据标签（取 `/api/v1/review/meta`）+ 复盘批注 | ✅ 已落地 | 同上 |
| **保存后即时刷新** · 组件派发 `news-score-changed`，首页监听后重算评估口径；同时直接刷新置顶「综合研判结论卡」，**全程不跳页** | ✅ 已落地 | `static/news-score-widget.js` `afterWrite()` · `static/trend.html` |
| **`/news` 保留为完整详情页** · 投行参考来源链接 + 跨日历史记录仍在该页；首页为其轻量通道，两处共用同一接口与口径 | ✅ 已落地 | `static/news.html`（本版**未改动**） |
| **刻意不轮询** · 打分器含可拖拽滑杆与文本框，定时重渲染会打断输入（滑杆跳回、光标丢失）→ 只在提交后自渲染；只读的 `#newsFactor` 仍由首页既有 60s 轮询保持新鲜 | ✅ 已落地（设计取舍） | `static/news-score-widget.js` |

### V0.76.1 · 数据导入 / 导出闭环（**📋 规划中**）

| 子项 | 预期产出 |
|------|----------|
| **券商对账单 CSV 导入** | 字段映射向导（成交日期 / 标的代码 / 方向 / 数量 / 价额 / 手续费）；dry-run 预览 + 二次确认；映射模板可保存复用 |
| **月度报告 PDF 导出** | 需**先补 V0.74.0 未落地的打印样式**（当前仅 `portfolio.html` 有 `@media print` 隐藏拖拽控制条，无 `window.print()` 入口、无 `pdf_export_click` 埋点）；封面 + 收益曲线 + 业绩归因 + 命中校准 + 关键事件流（自动生成，非手写） |
| **Excel 多 sheet 导出** | 交易明细 / 持仓快照 / 评估历史 / 央行购金 4 张 sheet，列冻结 + 自适应列宽 |
| **备份恢复 GUI** | 当前是 `backup-cron` + 手动 scp；V0.76 提供一键导出 sqlite + 上传恢复（保留 `.env` 模板） |

### V0.78.0 · 多标的扩展 + AI 解读（**📋 规划中**）

> 版本位说明：本规划项原先误标为 **V0.77.0**，与已落地的「界面聚类分组」撞号（V0.77.0/V0.77.1 均为前端质量修复，不承载新能力），现更正为 **V0.78.0**。

| 子项 | 预期产出 |
|------|----------|
| **铂金 / 钯金 / 原油 ETF** | 沿用白银先例（`static/silver.html` + `silver_yahoo` provider）：新增 `static/platinum.html` / `static/palladium.html` / `static/oil.html`；宏观因子权重可按标的独立配置（黄金重 DXY，原油重 OPEC + 库存） |
| **跨品种共振** | 在趋势页头部增加「黄金 × 白银 × 铂金 × 原油」四标联动卡：当 ≥3 标的同向时点亮强信号，便于判断贵金属周期阶段 |
| **AI 消息面解读**（可选） | 用户提交新闻 URL / 摘要 → 调用 LLM（OpenAI-compatible，含本地 Ollama）生成 0-100 分 + 依据标签 + 风险点；与现有 `news_scores` 槽位并列存储，人工可覆盖 |
| **本地 LLM 优先** | 默认走 `OLLAMA_BASE_URL`（无外网依赖），回退 `OPENAI_API_KEY`；隐私口径与项目「数据本地化」原则一致 |

### 横向可持续主题（持续滚动）

- **i18n 完成度** — zh-TW 当前 **70.7%**（597/845；V0.75.0 新增 39 个 `login.*`、V0.75.1 新增 42 个 `syn.*`、V0.76.0 新增 64 个 `nsw.*`，**均三语齐备**），目标 100%
- **测试规模与回归** — 当前 **867 收集 / 823 离线**（排除 2 个联网 fetcher 文件共 44 用例），新功能 PR 必须带测试（守住「离线回归 0 失败」红线）。⚠️ 这是**测试规模**而非覆盖率：项目当前**无任何覆盖率工具**（`pyproject.toml` 无 pytest-cov、CI 无 `--cov`），真实行覆盖率不可知 —— 建基线属 P1 事项
- **无障碍** — 拖拽 / 模态 / 账号菜单已提供键盘与 ARIA（`aria-haspopup` / `aria-expanded` / `role="menu"` / Esc 关闭）；但仓库中**无任何 axe-core 文件/测试**，所谓「0 critical」无自动化守卫，纳入 CI 属 P2 事项
- **数据守门** — `trace_id` 全链路追踪 + schema 校验新增 / 行情源扩展时同步加上

---

## 文档

- 📖 **使用文档**（按内容拆分为 5 文件）：
  - [docs/overview.md](docs/overview.md) — 项目概述 / 功能清单
  - [docs/getting-started.md](docs/getting-started.md) — 快速开始 / 配置说明
  - [docs/architecture.md](docs/architecture.md) — 技术架构 / 数据源
  - [docs/api-reference.md](docs/api-reference.md) — API 参考 / 核心模型
  - [docs/development.md](docs/development.md) — 测试 / 版本历史 / 改进计划 / 备注
  · 完整索引见 [docs/application-guide.md](docs/application-guide.md)
- 🧭 [docs/improvement-path.md](docs/improvement-path.md) — 易用性改善路径（P0-P3 改善方案）
- 🎨 [docs/ux-roadmap.md](docs/ux-roadmap.md) — UX 路线（**V0.68.0 → V0.76.0**：仪表盘自定义 / 通知偏好 / 首页综合研判结论卡 / 首页内嵌消息面打分器 / 多用户登录 + 数据隔离）
- ✅ [docs/feature-alignment.md](docs/feature-alignment.md) — README ↔ 代码 ↔ 文档三方对账报告
- 🚀 [docs/deployment.md](docs/deployment.md) — 公开部署 runbook（HTTPS + Nginx + Docker）

## 许可

个人研究项目，无对外许可证。所有数据源版权归原机构（AKShare / WGC）所有。
