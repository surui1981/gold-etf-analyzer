# UX & 应用能力路线（V0.68.0 → V0.75.0）

> 适用版本：**V0.67.0** → V0.75.0 ｜ 制定日期：2026-09-18 ｜ 视角：应用能力 + 用户体验
>
> **工程路线**（CI / 可观测 / 部署）见 [docs/improvement-path.md §三·五](./improvement-path.md#三五下一阶段路线-v0670--v0720--工程化补齐--业务深度--产品化)；
> **已落地 UX**（6.1 时效 / 6.2 响应式 / 6.3 决策可解释 / 6.4 操作防错 / 6.6 主动提醒 / 6.8 帮助 / 6.10 央行购金 / 6.11 研判复盘 / 6.12 框架基础）见 [docs/improvement-path.md §六](./improvement-path.md)。
>
> 本文档与 §三·五 形成 **「应用 vs 工程」双视图**：重叠版本（V0.68.0 / V0.69.0 / V0.71.0 / V0.72.0）在两文档里互相 cross-link，避免双线维护失同步。

---

## 〇 North-star metric

| 指标 | 当前（V0.67.0） | 目标（V0.75.0） |
|---|---|---|
| **端到端首次操作耗时**（打第一条分 → 看到综合指数） | ≤ 3 分钟 | **≤ 1 分钟** |
| **每日回访率**（连续 7 天 ≥ 1 次访问） | 无埋点基线 | ≥ 60% |
| **持久化命中率**（localStorage / settings 覆盖用户行为） | 50%（账本已 100%，其余 0） | ≥ 90% |
| **每日操作总时长** | ≤ 90 秒 | ≤ 60 秒 |

**支撑手段**：V0.68.0 起的 `telemetry_events` 表记录所有关键点击，4 个指标均从埋点 SQL 实时聚合。

---

## 一 8 版本总览表

| 版本 | 主题 | 主要交付 | 用户价值 | 风险 | 人天 |
|---|---|---|---|---|---|
| **V0.68.0** | 导航折叠 + 全局搜索 + 客户端埋点底座 | ① 汉堡抽屉式顶栏（≤768px 自动折叠）<br>② `Cmd/Ctrl+K` 全局命令面板<br>③ `telemetry.js` + `telemetry_events` 表（5 类事件） | 移动端首屏 ≤ 1 跳可达任意功能；高级用户操作提速 50%；功能使用可量化 | 🟡 中（汉堡菜单影响 7 页布局） | 3.5 |
| **V0.69.0** | 主题切换 + 无障碍扩面 | ① 4 主题（light / dark / auto / **high-contrast**）<br>② Chart.js canvas 加 `role="img"` + 数据表 fallback<br>③ 全站 axe-core 0 critical + 键盘 Tab 序修复 | 暗光环境舒适；色盲/低视力可访问；WCAG 2.1 AA 通过 | 🟡 中（Chart.js a11y 需手工包） | 4 |
| **V0.70.0** | 共振卡片 + 克数持仓 UX | ① 趋势页顶部"宏观×技术×消息面"三色共振信号卡<br>② `/portfolio` 克数持仓并列展示<br>③ 双口径收益曲线（按份 / 按克） | 中期反转可视化；实物金闭环 | 🟢 低（复用 §三·五 V0.70.0 后端） | 4 |
| **V0.71.0** | 多品种 UI + 回测可视化 | ① `/silver.html`（白银 K 线 / 评估 / 决策）<br>② `/backtest.html`（权重 / 阈值 / 阈值穿越回测 + 命中率/夏普曲线） | 贵金属全景；参数可信度闭环 | 🟡 中（回测计算可能慢，需节流） | 5 |
| **V0.72.0** | 推送渠道 + PWA 安装 | ① 邮件（SMTP）+ 微信（Server酱 webhook）<br>② `manifest.json` + 安装横幅 + 通知中心抽屉<br>③ 浏览器通知升级为 Web Push（VAPID + SW push） | 离线 / 后台也能收到；iOS / Android 可装桌面 | 🟡 中（Web Push 需 VAPID 密钥） | 4 |
| **V0.73.0** | i18n 框架 + 英文版 | ① `data-i18n` 属性 + `i18n.js` + 简繁英三语字典<br>② 顶栏语言切换器（zh-CN / en-US / zh-TW）<br>③ 货币 / 日期 / 百分比自动 locale 化 | 海外华人 + 港台 + 英文用户可用 | 🟢 低（已有 `toLocaleString("zh-CN")` 基础） | 4 |
| **V0.74.0** | 仪表盘自定义 + 通知偏好 | ① 卡片拖拽排序（纯原生）<br>② 提醒规则面板（≥X% 波动 / 指数跨档 / T+N 命中 / 自定义时段）<br>③ 打印友好 CSS + 一键 PDF 导出 | 个性化首页；通知降噪；月度报告 | 🟡 中（拖拽需无障碍实现） | 5 |
| **V0.75.0** | 多用户登录 + 数据隔离 | ① bcrypt 密码 + session cookie（HttpOnly + SameSite=Strict）+ CSRF token<br>② `user_id` 透传到所有业务表；`AUTH_ENABLED` 兼容开关<br>③ `/login` + `/register` + 找回密码（邮件 token） | 家庭 / 合伙多用户独立数据 | 🔴 高（数据迁移 + 安全审计） | 6 |

**合计**：~35.5 人天（约 7-8 周全职开发）。

---

## 二 各版本设计要点

### V0.68.0 · 导航折叠 + 全局搜索 + 客户端埋点底座

- **目标**：移动端首屏 ≤ 1 跳可达任意功能；操作可量化。
- **关键能力**：
  1. 顶栏在 ≤768px 自动折叠为汉堡菜单，桌面端 ≥769px 保留横排
  2. `Cmd/Ctrl+K` 唤起命令面板（输入即搜：标的 / 页面 / 时间区间 / 常用打分档位）
  3. 前端埋点底座（`telemetry.js`）：5 类事件（`page_view` / `action_click` / `range_change` / `theme_change` / `error_caught`）+ `sendBeacon` 批量上报 + `telemetry_events` 本地表
- **复用模式**：`static/account.js:20-220` IIFE + 自注入 CSS + `window.PM_Acc` 命名空间 → 抽屉 / 命令面板 / 埋点均沿用此模式；`static/help.js:21` `tourPrefix` + `localStorage.pm_help_seen_version` 升级重看机制
- **依赖**：§三·五 V0.68.0 已规划 SW（用于离线兜底）；本文档不重复
- **验证**：DevTools 模拟 360 / 480 / 768 / 1024 四档；埋点表 24h 内有数据；`Cmd+K` 在 5 页都生效
- **自身可观测性**：搜索成功率（`palette_query` → `palette_open` 比）、汉堡菜单触发率
- **人天**：3.5

### V0.69.0 · 主题切换 + 无障碍扩面

- **目标**：暗光环境舒适；WCAG 2.1 AA 通过。
- **关键能力**：
  1. 4 主题（light / dark / auto / **high-contrast**），CSS 变量统一切换
  2. Chart.js canvas 加 `role="img"` + `aria-label` + 数据表 fallback（点击展开）
  3. 全站 axe-core 0 critical + 键盘 Tab 序修复 + skip-to-content 链接
- **复用模式**：`static/help.css` 暗色主题 CSS 变量体系（V0.58.0 已有）→ 抽到 `static/themes.css` 全局；`static/freshness.js:9-156` 三态时效条（**主题切换不得破坏降级角标**）
- **依赖**：§三·五 V0.69.0 已规划主题基础（3 主题）；本文档扩面到 high-contrast + Chart.js a11y
- **验证**：axe-core 0 critical；high-contrast 在 lighthouse 对比度 100%；`prefers-reduced-motion` 友好
- **自身可观测性**：主题切换率（`theme_change` 事件分布）、dark 用户回访率
- **人天**：4

### V0.70.0 · 共振卡片 + 克数持仓 UX ✅ 已落地（V0.70.0）

- **目标**：把"判断准不准"做成日常可视化；实物金闭环。
- **关键能力**：
  1. 趋势页顶部"宏观×技术×消息面"三色共振信号卡（4 类信号：共振上行 / 共振下行 / 背离 / 中性）— `static/resonance-card.js` + 趋势页头部 `<section id="resonanceCard">`，点击弹窗显示 components 表 + STRONG_UP 命中率
  2. `/portfolio` 克数持仓并列展示（实物 / 积存金按克）— `positions.grams_held` 字段 + 持仓表 `<th>克数</th>` + 开/加/减仓均支持 `grams` 字段（与 `quantity` XOR 校验）
  3. 双口径收益曲线（按份 / 按克），切换不丢上下文 — `<button id="btnEquityUnit">单位：份</button>` + `drawEquityChart()` 在克数模式下右侧 Y 轴显示「g」
- **复用模式**：§六 6.4 `validateTrade` / `confirmDialog`（克数交易二次确认）；`static/trend.html:224-226` range-btn + `chart.destroy()` 模式；`static/portfolio.html` 既有 `confirmDialog` 复用
- **依赖**：§三·五 V0.70.0 后端 `services/resonance.py` + `positions.grams_held` 已合并
- **后端新增**（V0.70.0 P2 #7/#8）：
  - `GET /api/v1/resonance/signal` — 当日 4 类信号 + confidence 0-100
  - `GET /api/v1/resonance/history?days=N` — 历史回放（默认 30）
  - `GET /api/v1/resonance/strength-up?days=90&horizon=1` — STRONG_UP 命中率统计（样本 < 20 时 `sample_warning=true`）
  - `GET /api/v1/market/gold/gram-quote` — Au99.99 元/克实时报价
- **端点数**：40 → 43（+3）
- **测试增量**：+25 → 510 用例（共振 service 11 + API 3 + position service 10 + API 4 = +28；端到端含 `gold_gram_quote` 共振 API 共 +25）
- **验证**：共振卡片信号与回盘历史命中率 ≥ 70%（MVP 弹窗用 alert 显示；待 V0.71+ 接 sparkline）；克数交易平均操作 ≤ 30 秒（XOR 校验 + `gramsFromQty` 实时预览）
- **自身可观测性**：共振信号卡点击渗透率（`resonance_card_click`）；克数交易占比（`grams_trade_open`）；克/份切换（`equity_curve_switch_unit`）
- **人天**：4

### V0.71.0 · 多品种 UI + 回测可视化

- **目标**：贵金属全景；参数可信度闭环。
- **关键能力**：
  1. `/silver.html`（白银 K 线 / 评估 / 决策三模块，复用 7 页骨架）
  2. `/backtest.html`（权重 / 阈值 / 阈值穿越回测配置 + 命中率 / 夏普曲线）
- **复用模式**：现有 7 页骨架（`portfolio.html` / `trend.html` 等），参数面 80% 复用；§六 6.7 回测可视化原则（已记录但未实现）
- **依赖**：§三·五 V0.71.0 已规划白银后端 + 回测引擎；本文档专注前端
- **验证**：白银页 K 线 / 决策 / 评估 三模块齐；回测页可配置 ≥ 3 维度参数并即时计算
- **自身可观测性**：白银用户占比；回测使用深度（每次会话参数调整次数）
- **人天**：5

### V0.72.0 · 推送渠道 + PWA 安装

- **目标**：离线 / 后台也能收到；移动端可装桌面。
- **关键能力**：
  1. 邮件（SMTP）+ 微信（Server酱 webhook），用户配置中心
  2. `manifest.json` + 安装横幅（iOS Safari + Android Chrome）+ 通知中心抽屉
  3. 浏览器通知升级为 Web Push（需 VAPID 密钥 + SW push handler）
- **复用模式**：`src/app/middleware/trace.py` V0.67.0 纯 ASGI 中间件模式 → 新增 `PushSubscription` 仓储；`static/account.js` 配置中心 UI 模式
- **依赖**：§三·五 V0.72.0 已规划 SMTP / Server酱；本文档聚焦 Web Push + PWA 安装
- **验证**：iOS Safari 添加到主屏 → 启动为 standalone；邮件 / 微信收到测试告警
- **自身可观测性**：PWA 安装转化率（`pwa_install_prompted` → `pwa_installed` 漏斗）；邮件 / 微信 / Web Push 三渠道点击率
- **人天**：4

### V0.73.0 · i18n 框架 + 英文版

- **目标**：海外华人 / 港台 / 英文用户可用。
- **关键能力**：
  1. `data-i18n` 属性 + `i18n.js` + 简繁英三语字典（zh-CN / zh-TW / en-US）
  2. 顶栏语言切换器（持久化到 `localStorage.pm_lang`）
  3. 货币 / 日期 / 百分比自动 locale 化（基于 `Intl.NumberFormat` / `Intl.DateTimeFormat`）
- **复用模式**：`static/trades.html:215, 219` 现有 `toLocaleString("zh-CN")` 模式 → 全局 `format(num, locale)`；`static/account.js` 切换器 UI
- **依赖**：无（纯前端）
- **验证**：英文版 7 页无残留中文；语言切换 ≤ 200ms；货币日期按 locale 渲染
- **自身可观测性**：英文用户占比；语言切换频率
- **人天**：4

### V0.74.0 · 仪表盘自定义 + 通知偏好

- **目标**：个性化首页；通知降噪；月度报告。
- **关键能力**：
  1. 卡片拖拽排序（纯原生 `dragstart / dragover / drop`，无需 react-dnd）
  2. 提醒规则面板（≥X% 波动 / 指数跨档 / T+N 命中 / 自定义时段）
  3. 打印友好 CSS + 一键 PDF 导出（`window.print()` + `@media print`）
- **复用模式**：`static/help.js:21` `localStorage.pm_help_seen_version` 升级重看机制 → 新 `localStorage.pm_dashboard_layout` 持久化布局；§六 6.4 操作防错（拖拽须配合撤销 toast）
- **依赖**：无（纯前端 + `news_scores` 提醒规则扩展）
- **验证**：布局持久化跨刷新；通知规则触发准确率 ≥ 95%；PDF 导出 ≤ 2 页
- **自身可观测性**：自定义渗透率（默认 vs 自定义布局比）；提醒规则使用深度
- **人天**：5

### V0.75.0 · 多用户登录 + 数据隔离

- **目标**：家庭 / 合伙多用户独立数据。
- **关键能力**：
  1. bcrypt 密码（cost=12）+ session cookie（HttpOnly + SameSite=Strict + Secure）+ CSRF token
  2. `user_id` 透传到 `accounts` / `positions` / `trades` / `news_scores` / `snapshots` / `gold_price_daily`；`AUTH_ENABLED` 环境变量兼容开关（单用户模式默认 `false`）
  3. `/login` + `/register` + 找回密码（邮件 token，依赖 V0.72.0 SMTP）
- **复用模式**：`src/app/middleware/trace.py` 纯 ASGI 中间件（V0.67.0）→ 新增 `AuthMiddleware`（在 trace 之前注册）；§三·五 V0.67.0 `set_trace_id` / `reset_trace_id` 手动管理 → 新 `set_user_id` / `reset_user_id`；§六 6.4 操作防错模式（注册 / 找回密码二次确认）
- **依赖**：V0.72.0 SMTP（找回密码）；Alembic 迁移（加 `user_id` 列 + 索引 + 复合主键调整）
- **验证**：单用户模式（`AUTH_ENABLED=false`）行为 100% 兼容 V0.74.0；多用户模式 A 用户看不到 B 用户数据；密码 bcrypt cost=12
- **自身可观测性**：登录成功率；多用户模式下数据隔离零越权事件（审计日志）
- **人天**：6

---

## 三 与工程路线 §三·五 的关系

### 3.1 重叠版本双视角对照

| 版本 | §三·五 工程视角 | 本文档 UX 视角 | 协同点 |
|---|---|---|---|
| V0.68.0 | Prometheus / 跨源一致性 / 性能基准 | 导航折叠 + 全局搜索 + 埋点底座 | 埋点事件入 Prometheus 一起出 dashboard |
| V0.69.0 | 主题切换（3 主题 light/dark/auto）+ 全站 a11y + backfill 60→365 天 | 4 主题（含 high-contrast）+ Chart.js canvas a11y + axe-core 0 critical | backfill 扩窗支撑长期数据可视化 |
| V0.71.0 | 白银后端 + 回测引擎 | `/silver.html` + `/backtest.html` | UI 与算法同步发布；回测结果埋点观测 |
| V0.72.0 | 邮件 / 微信 + 公开部署 | Web Push + PWA 安装 + 通知中心抽屉 | 推送渠道合并测试；部署阶段 PWA 必须 ready |

### 3.2 仅本文档独有

- **V0.70.0** —— §三·五 已规划克数后端 + 共振算法，但**前端可视化是 UX 视角独占**（共振信号卡 + 双口径收益曲线）
- **V0.73.0** —— §三·五 完全未覆盖；i18n 是纯前端能力
- **V0.74.0** —— §三·五 完全未覆盖；仪表盘自定义 + 通知偏好是 UX 维度
- **V0.75.0** —— §三·五 完全未覆盖；多用户登录涉及数据迁移 + 安全审计，超出 §三·五 工程债范围

### 3.3 不在本文档的 7 项

| 项 | 理由 |
|---|---|
| 回测引擎深度优化（多目标 / 蒙特卡洛） | 留给 V0.76+；V0.71.0 只做基础回测 UI |
| 白银完整交易闭环（多账本 / 收益曲线 / 复盘） | V0.71.0 只做行情 + 评估 + 决策三件套 |
| 移动原生 App（iOS / Android） | Web PWA（V0.72.0）足够；原生需 React Native 等新栈 |
| 新 CDN / 构建工具（Vite / Webpack） | 保持"纯静态 + 内联 JS"原则；首屏可缓存 |
| ML 预测 / 神经网络 | 留 V0.76+；当前 7 页决策够用 |
| 社交分享 / 评论 / 多用户互动 | 单机部署无后端支撑；留 V0.76+ |
| 对外 API（OAuth / 第三方接入） | 多用户（V0.75.0）后才考虑 |

---

## 四 不变项（Invariants）

| # | 不变项 |
|---|---|
| 1 | **7 页 + 40 端点 + 454 测试基线不破坏**（V0.75.0 时变 8 页 + 多用户 5 端点 + ~530 测试） |
| 2 | **数据表只读扩展**（`gold_price_daily` / `daily_snapshots` / `news_scores` / `accounts` / `positions` / `trades` —— 只加列，不改主键） |
| 3 | **现有 JS 资产不重写只扩展**（`account.js` / `help.js` / `freshness.js` / `responsive.css` 命名空间稳定；新增资产通过 `window.PM_xxx` IIFE 自注入） |
| 4 | **`pm_help_seen_version` 升级强制重看行为保留**（V0.58.0 帮助体系不变） |
| 5 | **Chart.js 4.4.3 + 单 CDN 不变 + 无新框架 / 构建工具**（保持"纯静态 + 内联 JS"原则） |
| 6 | **`freshness.js` 三态时效条静默语义保留**（主题切换不得破坏降级角标的颜色与可读性） |
| 7 | **`gold_account_id` localStorage 键名不变**（与 V0.62.0 起向后兼容；多账本记忆不被破坏） |
| 8 | **telemetry 数据本地落库、不外发**（单机部署隐私；埋点只在 `telemetry_events` 表，`sendBeacon` 走同源） |

---

## 五 里程碑 M1-M8

| 里程碑 | 版本 | 验收口号 |
|---|---|---|
| **M1** | V0.68.0 | "首屏 ≤ 1 跳达标，埋点有数据" |
| **M2** | V0.69.0 | "暗色主题全站 OK + axe-core 0 critical" |
| **M3** | V0.70.0 | "共振卡片信号与历史命中率 ≥ 70% + 克数闭环" |
| **M4** | V0.71.0 | "白银 / 回测可独立跑（≥ 3 维参数）" |
| **M5** | V0.72.0 | "PWA 可装 + 三渠道推送全通" |
| **M6** | V0.73.0 | "英文版完整可用，切换 ≤ 200ms" |
| **M7** | V0.74.0 | "首页可个性化，PDF 导出 ≤ 2 页" |
| **M8** | V0.75.0 | "多用户独立数据，零越权事件" |

---

## 六 Cross-doc references

- **已落地 UX**（6.1 ~ 6.12）→ [docs/improvement-path.md §六](./improvement-path.md)
- **工程路线**（V0.68.0 → V0.72.0）→ [docs/improvement-path.md §三·五](./improvement-path.md)
- **应用能力 + 架构说明**（功能清单 + API 表 + 数据源）→ [docs/application-guide.md](./application-guide.md)
- **文档对账**（代码 vs 文档 vs README）→ [docs/feature-alignment.md](./feature-alignment.md)
- **项目主页**（版本 + 测试数 + 功能清单）→ [README.md](../README.md)

---

## 附录 A · 工时估算汇总

| 版本 | 人天 | 累计 |
|---|---|---|
| V0.68.0 | 3.5 | 3.5 |
| V0.69.0 | 4 | 7.5 |
| V0.70.0 | 4 | 11.5 |
| V0.71.0 | 5 | 16.5 |
| V0.72.0 | 4 | 20.5 |
| V0.73.0 | 4 | 24.5 |
| V0.74.0 | 5 | 29.5 |
| V0.75.0 | 6 | 35.5 |

**合计**：~35.5 人天（约 7-8 周全职开发）。

---

## 附录 B · 每个版本的验证清单

实施每个版本时必跑：

1. **本地手测**：`MARKET_PROVIDER=mock` 启动新端口（8899）实例，按版本"验证"段逐项检查
2. **JS 门禁**：`python scripts/check_static_js.py`（每个新 JS 文件都要过）
3. **测试**：
   - 服务层 ≥ 5 个新测试（参数计算 / schema 校验 / 边界）
   - 前端 ≥ 2 个 Playwright 测试（拖拽 / 命令面板 / 主题切换 / 命令面板）
4. **埋点**：版本上线后 24h 检查 `telemetry_events` 表有该版本对应事件
5. **文档三方同步**：每个版本结束时 README + application-guide + feature-alignment + 本文档 同步更新

---

## 附录 C · 每版本「自身可观测性」总表

| 版本 | 埋点事件 | 派生指标 |
|---|---|---|
| V0.68.0 | `palette_open` / `palette_query` / `nav_drawer_open` / `telemetry_page_view` | 搜索成功率 / 汉堡菜单触发率 / 7 日回访率 |
| V0.69.0 | `theme_change` / `a11y_skip_link_click` | 主题切换率 / dark 用户占比 / 对比度合规率 |
| V0.70.0 | `resonance_card_click` / `grams_trade_open` / `equity_curve_switch_unit` | 共振卡渗透率 / 克数交易占比 |
| V0.71.0 | `silver_page_view` / `backtest_run` / `backtest_param_change` | 白银用户占比 / 回测使用深度 |
| V0.72.0 | `pwa_install_prompted` / `pwa_installed` / `push_channel_click` | PWA 安装转化率 / 三渠道点击率 |
| V0.73.0 | `lang_change` / `i18n_fallback_hit` | 英文用户占比 / 翻译覆盖率 |
| V0.74.0 | `dashboard_drag_end` / `notification_rule_save` / `pdf_export_click` | 自定义渗透率 / 提醒规则使用深度 |
| V0.75.0 | `login_success` / `login_fail` / `authz_violation` | 登录成功率 / 越权事件计数（应恒为 0） |