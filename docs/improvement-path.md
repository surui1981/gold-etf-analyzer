# 改进路径 · 易用性提升路线图

> 项目：`gold-etf-analyzer`（黄金价格投资辅助工具）
> 当前版本：**V0.66.0** ｜ 制定日期：2026-08-31 ｜ 状态：**P0-P2 已全部落地 + P1 #5 行情源配置化（V0.59.0）+ P1 #6 单用户多账本与交易历史查询页（V0.62.0，P1 仅剩 #3 CI/CD）+ V0.60.0 行情实时性增强 + V0.61.0 交易闭环与业绩分析（ETF 报价口径修正 + 加仓/减仓内联面板 + 收益曲线 + 获利分析总结）+ V0.62.1 收益回放口径修复（行情未覆盖的成交归入最后可得交易日）+ V0.63.0 评估指数历史曲线升级（P2 #14 起步，4 条线 + 区间切换 + 极值卡 + 稀疏 UX）+ V0.64.0 多时间框架（周/月线趋势，P2 #9，60D / 52W / 24M 三档区间 + ISO 周界 / 年月聚合 + MA 重算）+ V0.65.0 消息面每日 3 次打分（1:2:3 加权，修复同日静默覆盖）+ **V0.66.0 研判复盘与准确率校准（金价日历 + T+1/3/5 对比 + 命中率·校准曲线·标签胜率）**；6.1 数据时效透明 + 6.2 响应式适配 + 6.3 决策可解释性 + 6.4 操作防错与撤销 + 6.6 主动提醒 + 6.7 业绩可视化（收益曲线 V0.61.0 + 指数曲线 V0.63.0 + 周月线 V0.64.0）+ 6.8 新手引导与帮助体系（V0.58.0）+ 6.10 央行购金数据化与自动化（V0.57.0）+ 6.11 研判复盘与准确率校准（V0.66.0，非原路线图项） 已落地**（6.5 主题/偏好记忆、6.9 离线体验 待规划；6.7 权重参数回测 待规划） ｜ 文档更新：2026-09-16（V0.65.0 + V0.66.0 落地 + 全量文档对账）
> 目标：从「能用」走向「好用、可信、随时可用」
> 投资指引基准：**纽约金（COMEX GC）**——连续交易、夜盘覆盖国内休市时段，对国内金价具领先指示意义；ETF / 上海金作国内对照与交易标的

---

## 一、现状评估

### 1.1 当前已具备的能力（V0.51 基线 + 迭代至 V0.66.0，UX P0-P3 专项 9 项已全部落地）

| 模块 | 能力 |
|------|------|
| 评估体系 | **三面评估**：技术面 30% + 宏观面 40% + 消息面 30%（以纽约金为指引基准）；消息面**每日 3 次打分按 1:2:3 加权**合成当日有效分值（V0.65.0） |
| 页面 | 趋势追踪 / 持仓与决策 / 权重配置 / 消息面评估 / 研判复盘 / 世界央行购金 / 交易历史（统一顶部导航 + 账本切换器 + 帮助与时效条） |
| 数据 | 三市场（纽约金 COMEX / 上海金 Au99.99 / 黄金ETF 518880）、宏观 5 因子、每日快照、**金价日历 `gold_price_daily`**（V0.66.0，客观价格可回填可长期积累） |
| 决策 | 买入 / 加仓 / 持有 / 减仓 / 卖出 + **仓位推荐**（评估指数 → 仓位 80/60/40/20/10%） |
| **复盘与校准** | **研判复盘（V0.66.0）**：按日期归档研判（分值/方向/依据标签/备注）→ 对齐金价给出 **T+1 / T+3 / T+5** 涨跌与命中判定 → 统计总命中率 / 方向分组 / 窗口分组 / **分值分箱校准曲线** / **依据标签胜率**；样本不足自动标注，补录数据默认排除防前视偏差 |
| **可视化** | **评估指数历史曲线**（V0.63.0：综合 / 技术 / 宏观 / 消息面 4 条线 + 7D/30D/90D 区间切换 + 极值卡 + 稀疏 UX）+ **多时间框架 K 线主图**（V0.64.0：60D / 52W / 24M 三档区间切换 + ISO 周界 / 年月聚合 + MA 在聚合序列上重算）+ 收益曲线 + 获利分析 + 价格曲线 + 宏观因子 |
| 工程 | **432 测试**（37 个测试模块）、本机常驻（看门狗自愈 + `install_startup.ps1` 开机自启）、Alembic 正式迁移、央行购金月度自动调度、前端内联 JS 门禁（`make check-web`） |

### 1.2 易用性自评

| 维度 | 评分 | 说明 |
|------|------|------|
| 功能完整度 | ★★★★★ | 三面评估 + 决策 + 持仓闭环成型，指引基准切换为纽约金 |
| **稳定性** | ★★★★★ | 看门狗自愈 + 开机自启，无需人工重启 |
| **可信度** | ★★★★★ | 数据源三态标识（实时/缓存/演示）+ 健康度 + 备源兜底 |
| **响应速度** | ★★★★☆ | 缓存命中首屏 < 5s，进度反馈完整 |
| 操作效率 | ★★★★☆ | 今日操作清单串联每日流程 + 持仓录入简化 |
| 决策支持 | ★★★★★ | 仓位推荐 + 理由明细 + 权重实时预览 + 阈值提醒 |

> **结论**：P0-P2 易用性专项已全部落地，当前聚焦 **投资指引基准（纽约金）** 的展示与决策贯通。
>
> **关于"P0/P1/P2/P3"编号的语义说明**（避免与 §二 §三 路线图混淆）：
> - **§一 1.1 / §二**：指**易用性专项**编号（P0 体验杀手 / P1 每日高频 / P2 决策增强 / P3 细节打磨），共 9 项已全部落地。
> - **§三 实施路线 + application-guide 第 11 章**：指**总改进计划**编号（P1 工程化收口 / P2 分析深度 / P3 产品化），与 UX 编号独立；UX 6.1-6.10 在 §六 UX Roadmap。
> - 两者侧重点不同：UX 编号针对**用户感知**（页面是否好用），总计划编号针对**系统能力**（回测 / 多品种 / CI/CD 等）。

---

## 二、痛点诊断与改善方案（UX 易用性专项 P0-P3）

### P0 · 体验杀手（决定"能不能用、敢不敢信"）✅ 已全部落地

#### 1. 服务周期性卡死

- **现状**：服务进程监听 8888 但停止响应（uvicorn 事件循环阻塞），需人工发现并重启，今日已发生 6-7 次。
- **影响**：随时打不开，是所有体验问题中最致命的一项。
- **方案**：
  - 进程内看门狗：定时自检 `/api/v1/health`，连续失败自动重启进程；
  - 外部守护（兜底）：Windows 计划任务每 5 分钟巡检，健康检查失败则拉起；
  - 请求级超时：所有 akshare 调用统一超时，超时快速失败而非挂起阻塞事件循环。
- **验收标准**：连续 7 天无需人工重启，可用性 ≥ 99%。

#### 2. 数据源降级静默（可信度缺陷）

- **现状**：数据源（新浪 / 东财 / SGE / 英为财情 / 中债）失败时自动回退 Mock，页面**无任何提示**。
- **影响**：⚠️ 用户可能依据 Mock 假数据做投资决策——对投资类应用是致命问题。
- **方案**：
  - 接口返回 `data_source`（`live` / `mock`）与 `data_date`；
  - 页面顶部统一显示数据源状态条：绿色「实时数据」/ 橙色「部分降级」/ 红色「降级演示数据」；
  - Mock 数据在图表与指标上以虚线或角标区分。
- **验收标准**：任意数据源失败时，用户 100% 可见降级状态，无"静默假数据"。

#### 3. 首屏加载无反馈

- **现状**：页面加载并发 4 个数据接口，akshare 全局锁串行 + 首次 import 开销，首屏 20-30 秒，期间页面空白。
- **影响**：用户误判为"没数据"（已实际发生）。
- **方案**：
  - 数据源 TTL 缓存（行情 / 宏观 / 快照），避免同一源重复拉取；
  - 分区块骨架屏 + 加载进度提示（各区块独立 loading 文案）；
  - 服务启动预热：启动时预取一次核心行情，缩短首次请求耗时。
- **验收标准**：缓存命中时首屏 < 5 秒；未命中时显示明确进度而非空白。

---

### P1 · 每日高频（决定"每天用起来顺不顺手"）✅ 已全部落地

#### 4. 今日操作清单引导

- **现状**：每日流程（看指数 → 打消息面分 → 看决策 → 记录交易）分散在 4 个页面，无串联。
- **方案**：趋势页顶部增加「今日操作清单」卡片，按步骤高亮待办（消息面未打分 / 未记录交易等），每步可一键跳转。
- **验收标准**：新用户无需说明即可完成每日完整流程。

#### 5. 消息面打分提醒与继承

- **现状**：消息面打分需用户记忆主动完成，未打分则按中性 50 参与计算（占 30% 权重）。
- **方案**：
  - 未打分时在导航与清单中高亮提醒；
  - 提供「沿用昨日」按钮与快捷档位（看多 70 / 中性 50 / 看空 30）；
  - 打分记录历史可回看（已有 `news_scores` 表，需页面展示）。
- **验收标准**：每日打分操作 ≤ 10 秒完成。

#### 6. 持仓录入简化

- **现状**：需手动查询当前价、手算份数后填写。
- **方案**：
  - 按金额反算份数（输入"买入 1 万元"自动换算）；
  - 价格字段默认预填当前市价；
  - 快捷比例按钮（1/4 仓 / 1/2 仓 / 全仓）。
- **验收标准**：录入一笔交易 ≤ 3 次点击。

---

### P2 · 决策增强（决定"判断够不够及时"）✅ 已全部落地

#### 7. 权重实时预览与预设

- **方案**：权重页拖动滑块即时预览「调整后综合指数」，并提供预设（保守 / 均衡 / 激进）一键套用。
- **验收标准**：调权重时实时可见指数变化，无需保存后跳转查看。

#### 8. 阈值提醒

- **方案**：指数跨越档位（如 上升→强势上升）、价格异动 > 2%、持仓盈亏 ±10% → 页面醒目提示。
- **验收标准**：重要变化不遗漏，中短期操作可及时响应。

#### 9. 每日快照自动捕获

- **方案**：每日收盘后定时执行 `POST /api/v1/snapshots/capture`（计划任务或服务内定时器），历史曲线自动积累。
- **验收标准**：无需人工干预，30 天后自动形成完整指数时间序列。

---

### P3 · 细节打磨（决定"用起来安不安心"）✅ 已全部落地（V0.52–V0.55）

| 项 | 方案 |
|------|------|
| 响应式适配 | 窄屏 / 平板下表格与图表自适应，导航折叠 |
| 交易撤销 | 误录交易支持撤销（软删除 + 撤销按钮） |
| 数据时效标识 | 显示 T-1 / 更新时间 / 非交易日提示，避免误判数据新鲜度 |

---

## 三、实施路线（版本规划，含总改进计划 P1 #5 / P1 #6 / P2 #14）

| 版本 | 内容 | 主题 | 状态 |
|------|------|------|------|
| **V0.50** | P0 全部 + P1 全部 + P2 之快照自动捕获（看门狗/数据源标识/首屏/清单/打分提醒/持仓简化/缓存持久化/并发/WAL/备份/归档/Alembic/配置缓存） | 稳定可信·高效省心 | ✅ 已发布 |
| **V0.51** | **投资指引基准切换为纽约金（COMEX）**：趋势指数/决策/快照以纽约金为基准，前端主面板改显纽约金 + 上海金国内对照，`/gold/trend` 支持 target 参数 | 指引基准统一 | ✅ |
| **V0.51.1** | **启动健壮性修复**：移除 Alembic 前冗余 create_all，消除 SQLite 双写锁导致启动 hang；新增 WAL checkpoint + 迁移 30s 超时兜底；启动后后台预热行情缓存（首屏直接命中，避免空白等待）；前端 fetch 增加 40s 超时与失败可见态 | 启动/加载可靠性 | ✅ |
| **V0.57.0** | **6.10 央行购金数据化与自动化**：新增 `/central-bank` 页面（4 KPI + Chart.js 堆叠柱 + Top 10 + 按国家/季度范围筛选明细表）+ 3 个 endpoint；数据源切到 WGC HTML chart JS（绕开 XLSX 403），覆盖 2014Q1–2026Q2 + H1 2026 按国家 + UZB/IRN 手工补丁；cb_gold 宏观因子从表自动汇总 T12M；**月度自动调度** 每月 1/15/末日 07:30 BJT 自动从 WGC 拉取；216 测试通过 | 央行购金数据化 + 自动化 | ✅ |
| **V0.58.0** | **6.8 新手引导与帮助体系**：新增 `static/help.js` + `static/help.css` 自包含脚本，右下角悬浮 `?` 按钮唤起 3 tab modal（操作指南 5 步流程 / 术语速查 30+ 条按 7 大类分组 / 数据来源 + 投资警示）；首次访问 5 个页面自动弹 2-4 步 tour 浮层（高亮 + 蒙层 + 步骤切换），`localStorage.pm_help_seen_version` 升级时强制重看；15 项关键术语 inline `?` 图标自动注入（综合指数 / MA5/20/40 / RSI(14) / T12M / Au99.99 / COMEX / 518880 / 仓位推荐 等）；响应式：modal 在 <768px 改为底部抽屉；63 项新测试覆盖 glossary / tour / HTML 注入 / XSS 转义 / 数据源标注；279 测试通过 | 新手引导 + 帮助体系 | ✅ |
| **V0.59.0** | **P1 #5 行情源配置化**：`repositories/market_data.py` 重构为 Provider 抽象入口，新增 `repositories/market_providers.py` 工厂模块；3 个窄接口（GoldHistoryProvider / GoldLiveQuoteProvider / TreasuryYieldProvider）+ `MarketProviderBundle` 三件套 + `build_provider_bundle(settings)` 工厂；4 个内置 provider：**akshare**（默认：东财 ETF + 新浪 ETF 备 + 英为财情外盘 + gold-api 实时 + H.15 美债）/ **mock**（确定性序列、零依赖、零网络）/ **eastmoney_only**（仅东财，省去新浪子进程开销）/ **sina_only**（仅新浪，适用东财 403 场景）；`.env` 配置 `MARKET_PROVIDER=akshare\|mock\|eastmoney_only\|sina_only`，启动时一次性读取；`XAU_FALLBACK_CHAIN=goldapi,sina,etf_history` 与 `QUOTE_CACHE_TTL=300` 也可配；旧 `MarketDataRepository(provider=...)` 签名保留向后兼容；24 项新测试（工厂解析 4 provider 名 + 大小写 + 未知名抛错 + 空回退默认 + Mock 数据正确性 + bundle 注入 + XAU chain + cache_ttl=0 禁用）；303 测试通过（279 → 303） | 行情源配置化 | ✅ |
| **V0.66.0**（当前） | **6.11 研判复盘与准确率校准（新增项）**：① 新增 `gold_price_daily` 金价日历表（`target` + `price_date` 唯一，存 `close`/`change_pct`/`source`），**只存客观价格、与 `daily_snapshots` 解耦**，可回填可长期积累；② `news_scores` 增 `basis`（JSON 依据标签）/ `review_note`（事后批注）/ `backfilled`（补录标记）；③ `ReviewService`：`backfill(days)` 从 `/gold/ny-trend` 幂等回填 / `journal(days)` 按**交易日**对齐（基准 = 研判日或之前最近交易日收盘，T+N 取第 N 个后继，自动跳过周末休市）/ `stats(days)` 输出总命中率 + 方向分组 + 窗口分组 + **分值分箱校准曲线** + **依据标签胜率**（补录日期整日排除防前视偏差，样本 <20 标注「仅供参考」）/ `hint_for_score()` 打分页即时提示；④ 命中口径：看多须涨、看空须跌、看平 `\|涨跌\| ≤ 0.3%`；⑤ 6 个 review 接口 + `/review` 页面（统计面板 + 按日期倒序研判日志卡片）+ 5 页导航入口；⑥ `news.html` 增 12 个依据标签多选 + 复盘批注 + 打分时历史校准提示；⑦ 迁移 `a3d9e1f7b2c4`；路由 32 → 40；新增 22 用例（服务 13 + API 9），用例 410 → 432 | 研判复盘·准确率校准 | ✅ |
| **V0.65.0** | **消息面每日 3 次打分（1:2:3 加权）+ 修复同日静默覆盖**：① 原缺陷——`news_scores.score_date` 唯一约束 + upsert 保存，同日第二次打分**静默覆盖**第一次且页面仍提示「已保存」；② 增 `slot`(1-3) / `scored_at`，改 `(score_date, slot)` 复合唯一；③ 当日有效分值按**越晚权重越高** `Σ(i × scoreᵢ) / Σi` 合成；三次用尽后留空 slot 提交返回 400（不再静默覆盖），显式 slot 可覆盖修正；④ 新增 `DELETE /news-score/{slot}` 撤销（剩余次数重新归一）与 `GET /news-score/history`；⑤ 前端 `news.html` 重做（三槽位卡片 + 加权算式 + 剩余次数 + 历史表 + 撤销确认）；⑥ 迁移 `f2a7b4c9d1e3` 放开旧唯一索引、存量行归入 `slot=1`；新增 13 用例（API 7 + 重写服务 5→11），用例 397 → 410 | 消息面 3 次打分 | ✅ |
| **V0.64.0** | **多时间框架（周/月线趋势，P2 #9）**：趋势页 K 线主图加 3 档区间按钮（60D / 52W / 24M）—— ① 后端抽 730 天日 K 后按 ISO 周界聚合到 ~52 根周 K / 按年月聚合到 ~24 根月 K（`aggregate_klines(daily, interval)` 核心函数）；② MA 在聚合后序列上重算（周线 MA5≈1 交易月、MA20≈季线、MA40≈半年线）；③ W/M 模式技术面 5 维度旁路（指标对日 K 敏感），宏观与消息面仍正常合成综合指数；④ `/gold/trend?interval=W\|M` + `days` 上限 250 → 750；⑤ 缓存 key 扩展为 (target, interval, date) 三维独立（避免 W/M 结果被 D 请求误命中）；⑥ 趋势页 `trendChart.destroy()` 内存管理（仿 V0.63.0 snapChart 模式）；⑦ 60s 轮询只刷日 K，避免每分钟重画周/月主图；⑧ 摘要自适应（"近 1 年" / "近 2 年"）。新增 14 个测试（服务 4 + API 4 + 工具 6）；397 用例通过（383 → 397），离线回归 **365 passed / 0 failed**（130s） | 多时间框架 | ✅ |
| **V0.63.0** | **评估指数历史曲线升级（P2 #14 起步）**：趋势追踪页『每日评估历史』面板前端增强，后端零改动。① **第 4 条曲线**：新增 `news_index` 消息面线（紫色虚线），综合指数的 4 个构成维度（综合 / 技术 / 宏观 / 消息面）一目了然；② **区间切换**：`7D / 30D / 90D` 三档按钮（参考 portfolio 收益曲线 `EQUITY_RANGES` 模式），调用 `/api/v1/snapshots?days=N` 重新渲染；③ **4 个极值卡**：最新（带档位）/ 区间最高（附日期）/ 区间最低（附日期）/ 日变（↑↓→ 红绿色），用现有 `.cards` 网格替代单行 summary；④ **稀疏数据 3 档 UX**：< 3 天「样本不足，趋势尚不显著」+ 隐藏极值卡；< 7 天「仅 N 天数据」；≥ 7 天默认（pointRadius 缩小到 2）；⑤ **chart.destroy 内存管理**：`snapChart` 模块级变量 + 渲染前 `snapChart?.destroy()`，区间切换不堆积 Chart 实例；⑥ **空数据兜底**：`< canvas >` 占位 + 子标题改为「暂无快照数据（每日 07:00 BJT 自动捕获）」，旧 chart 销毁。新增 6 个测试（API 4 + 服务 2）；383 用例通过（377 → 383） | 指数曲线可视化 | ✅ |
| **V0.62.1** | **收益回放口径修复（验证阶段发现）**：修复 `PortfolioAnalyticsService._replay()` **静默丢单** —— 成交日晚于价格序列最后一个交易日时（**行情源 T-1 滞后 / 盘中录入 / 周末节假日录入**都会触发），`bisect_left` 返回 `len(price_dates)`，原逻辑 `if idx < len(price_dates)` 直接跳过该笔交易，导致同一响应内 **`sell_count` 与 `closed_trades` 自相矛盾**（`sell_count=2` 却 `closed_trades=0`、胜率 0%），「累计投入本金」显示 **0.00 元**、已实现盈亏归零，与持仓页实时持仓完全冲突。现改为把行情未覆盖的成交**归入最后一个可得交易日**，累计投入 / 已实现盈亏 / 胜率 / 盈亏比恢复正确（收益曲线同步受益）。新增 2 项回归测试并断言 `sell_count == closed_trades`；377 用例收集（375 → 377） | 业绩口径可信 | ✅ |
| **V0.62.0** | **单用户多账本 + 交易历史查询页（P1 #6，P1 收官）**：① **多账本**——新增 `accounts` 表 + `positions.account_id`（迁移 `b8e14c7a2f36` 幂等 seed 默认账本 id=1，既有持仓与流水全部归入），`/api/v1/accounts` 六端点（清单 / 新建 / 改名 / 设默认 / 归档 / 恢复），默认账本自愈（`list` / `create` 均先 `ensure_default`，防新账本抢占 id=1）、重名校验、默认账本不可归档、仍有未平仓持仓不可归档；② **交易历史查询页** `/trades`——`GET /api/v1/trades`（方向 / 持仓 / 品种 / 关键字 / 日期区间 / 分页 + 6 项汇总 KPI）与 `/trades/export` CSV 导出（BOM + 附件头）；③ **均价法逐笔回放**——按时间升序回放算每笔卖出的「已实现盈亏」与「成交后份额」，并采用**双次取数**（scope 供回放 / display 供展示），使按方向或日期筛选不丢失买入上下文；④ **全链路账本隔离**——持仓 / 收益曲线 / 获利分析 / 购买决策均贯通 `?account_id=`，`account_id=None` 表示「全部账本」合并视图，写操作统一落 `targetAccountId()`（合并视图下落到默认账本），避免「看着合并视图下单，持仓却不知归属」；⑤ 前端 `static/account.js` 全站账本切换器（localStorage 记忆 + `account-changed` 事件）+ `/trades` 新页面 + portfolio 账本管理卡片；41 项新测试（账本服务 20 / 交易历史 12 / 账本 API 8 / 决策账本透传 1）；375 测试通过（334 → 375） | 多账本·可追溯 | ✅ |
| **V0.61.0** | **交易闭环与业绩分析**：① **修复 ETF 报价口径错配**——新增 `get_gold_etf_quote()` + `GET /market/gold/etf-quote`（元/份），持仓估值 / 开仓预填 / 清仓价全部改用 ETF 价（此前误用 XAU/USD 国际金价，收益率虚高数万个百分点）；② **加仓/减仓内联交易面板**——金额↔份数双向换算、快捷比例（1/4·1/2·3/4·全部）、摊薄成本与已实现盈亏实时预览，替代原生 `prompt()`，并新增 `GET /positions/{id}/trades` 流水查询；③ **收益曲线**（`GET /api/v1/portfolio/equity-curve`）——由交易流水 + ETF 历史价回放重建每日持有份数/成本/市值/累计收益率，附最大回撤；④ **获利分析总结评估**（`GET /api/v1/portfolio/performance`）——已实现 / 浮动盈亏、平仓笔数与胜率、盈亏比、最佳/最差平仓、平均持仓天数 + 面向客户的中文总结；⑤ **手续费口径统一**——回放成本不再计入手续费（与 `PositionService.add_trade` 摊薄成本同口径），手续费只体现在「累计投入本金」，修正同一页面收益曲线与获利分析出现两个收益率（-4.29% vs -4.25%）的信任问题；并新增 `scripts/check_static_js.py` 前端内联 JS 门禁（语法 / 未定义调用 / DOM id 一致性，`make check-web`）——本项目前端无构建步骤，JS 写错不会被任何编译期拦截却会让整页脚本失效 | 业绩看得见 | ✅ |
| **V0.60.0** | **行情实时性增强（D + B）**：① `services/cache.py` value 由 `GoldTrendOut` → `(GoldTrendOut, set_at)` 元组；`get_served` 新增 keyword-only `max_age_seconds`，超期返回 None（默认 600s，可由 `.env` 配 `SERVED_CACHE_TTL_SECONDS`），旧调用方不传 → 行为完全不变；② `repositories/market_data.py` 6 个接口（`get_gold_history` / `get_gold_gram_history` / `get_us_gold_history` / `get_gold_quote` / `get_gold_gram_quote` / `get_us_gold_quote`）启用 `quote_cache_ttl=300` 进程级 cache（V0.59.0 之前是死代码），cache hit 时**不调** `_mark` 保留 `_fetched_at` → `source_status()` 按 `_fetched_at + cache_ttl` 派生 `"stale"` 状态；③ `services/scheduler.py` `daily_capture_loop` 内部串联日内分钟表 `next_intraday_run_utc`（默认 09:30 / 11:30 / 14:00 / 15:30 BJT，可由 `.env` 配 `INTRADAY_REFRESH_HOURS`，`INTRADAY_REFRESH_ENABLED=false` 关闭），取 `min(next_daily, next_intraday)` 最近点触发（`intraday_warm_once` 仅刷新 served cache 不落库）；④ 前端 `trend.html` `setInterval(refreshTrendQuotes, 60_000)` + `visibilitychange` 切回前台自动刷新 + 右上角手动 🔄 按钮（带旋转动画），`portfolio.html` 60s → 30s + `visibilitychange` + 同步 `FreshnessBar.load()`；⑤ `tests/conftest.py` `_reset_db` fixture 同时清空 `_CACHE`（行情 cache）保证跨测试隔离；13 项新测试（5 cache hit/expire/disabled/key-isolation/stale + 4 served TTL + 2 intraday 时间计算 + 1 silent-on-failure + 1 writes-served-cache）；316 测试通过（303 → 316） | 行情实时性 | ✅ |
| **V0.56.0** | **6.6 主动提醒（前端侧）**：持仓决策页新增「提醒开关」（localStorage 记忆），开启后每 60s 轮询评估指数与纽约金；指数档位切换（如中性↔偏多）或金价波动≥2% 触发浏览器通知 + 页面顶部提醒条；决策区新增「今日简报」一句话摘要。邮件/微信推送因需外部服务与密钥，本期未做 | 主动触达 | ✅ |
| **V0.55.0** | **6.4 操作闭环防错与撤销**：开仓/加仓/减仓/清仓统一二次确认弹窗（带操作摘要，防误点）+ 前端范围校验；持仓「删除」改为软删除（`deleted_at` 字段，启动幂等迁移补齐），支持 8 秒内置「撤销」恢复；新增 `GET /api/v1/positions/export` 导出持仓+流水 CSV（对账/备份）；修复前端 API_BASE 指向已死 8888 端口的同源问题 | 操作不翻车 | ✅ |
| **V0.54.0** | **6.3 决策可解释性增强**：决策理由结构化（利多/利空中性三向 `reason_items`），前端以红绿对照条呈现；指数构成（技术/宏观/消息）堆叠条可视化；保留 `reasons` 向后兼容 | 决策看得懂 | ✅ |
| **V0.53.0** | **6.2 响应式与移动端适配**：新增共享 `static/responsive.css`（768/480/360 三档断点）并在四页注入，窄屏下顶栏换行、面板与导航纵向堆叠、固定宽列收窄、表单输入满宽、持仓表格容器内横向滚动、按钮触控放大 | 多端可用 | ✅ |
| **V0.52.0** | 6.1 数据时效透明：全局时效条 + 三市场时段判定 + 降级持续角标；启动期 Alembic 子进程化消除死锁 | 数据可信 / 启动可靠 | ✅ 已发布 |

---

## 四、验收度量

| 指标 | 目标 | 当前（V0.66.0） |
|------|------|------|
| 服务可用性（7 天） | ≥ 99%（无需人工重启） | ✅ 看门狗自愈 + 开机自启 |
| 首屏加载（缓存命中） | < 5 秒 | ✅ 缓存持久化 + 后台预热，冷启动 ~1.6s |
| 数据源状态可见性 | 100% | ✅ 三态标识 + 健康度 + 备源兜底 |
| 每日完整操作流程耗时 | ≤ 3 分钟 | ✅ 今日操作清单串联 |
| 每日打分操作耗时 | ≤ 10 秒 | ✅ 每日 3 次机会（1:2:3 加权）+ 快捷档位 + 逐次可改可撤 |
| 投资指引基准 | 纽约金（连续/领先） | ✅ V0.51 已切换 |
| 交易可追溯性 | 逐笔成交可查、可按账本隔离 | ✅ V0.62.0 交易历史页 + 多账本（均价法回放已实现盈亏） |
| 业绩可见性 | 收益率 / 回撤 / 胜率可读 | ✅ V0.61.0 收益曲线 + 获利分析总结 |
| **指数曲线回看** | 综合 / 技术 / 宏观 / 消息面 4 条线 + 区间切换 + 稀疏 UX | ✅ V0.63.0 已落地（4 条线 + 7D/30D/90D + 极值卡） |
| **多时间框架 K 线主图** | 60D / 52W / 24M 三档区间切换 + ISO 周界 / 年月聚合 + MA 重算 | ✅ **V0.64.0 已落地**（趋势页 K 线主图加 3 档按钮 + 服务端 ISO 周界 / 年月聚合 + MA 在聚合序列上重算 + W/M 模式技术面旁路 + `days` 上限 250 → 750） |
| **消息面打分准确率可校准** | 按日期归档研判 + 次日/3 日/5 日金价对比 + 命中率与分箱校准 | ✅ **V0.66.0 已落地**（`gold_price_daily` 金价日历 + `/review` 按日期归档 + T+1/3/5 判定 + 命中率/校准曲线/标签胜率；补录样本默认排除） |
| 回归测试 | 全绿 | ✅ **432 用例 / 37 个测试模块**（离线 **388 passed / 0 failed**，27m05s；全量含联网 fetcher **431 passed / 1 skipped / 0 failed**） |

---

## 五、部署状态与运行时质量（V0.64.0）

> 截至 2026-09-13，三个部署路径（Windows 本机 / Linux 开发机 / Docker 容器）均可直接跑通；服务以 8888 端口监听 SQLite。本节回答"现在怎么部署 / 跑得怎么样 / 出问题怎么办"。

### 5.1 三种部署方式

| 场景 | 命令 | 入口文件 | 备注 |
|------|------|---------|------|
| **Windows 本机常驻（推荐，主用）** | 双击 `start_server.bat` | 自动探测 `C:\Users\DFCFF\.workbuddy\binaries\python\…\python.exe` → 缺失依赖自动 `pip install -e ".[dev]"` → `uvicorn app.main:app --host 127.0.0.1 --port 8888` | 6 秒后自动打开浏览器；端口被占时**一键自愈**（自动 `taskkill` 残留进程后再启动） |
| **开机自启 + 看门狗** | 右键 `install_startup.ps1` → PowerShell 运行 | 写入 `$APPDATA\Microsoft\Windows\Start Menu\Programs\Startup\GoldPriceAssistant.bat`（登录后自动启动 `watchdog.py --interval 30 --threshold 2`）；管理员权限下额外注册 3 个 Windows 计划任务（`GoldPriceAssistant` 服务 / `GoldPriceAssistantWatchdog` 看门狗 / `GoldPriceAssistantSnapshot` 每日 06:00 + 16:00 采集快照） | 看门狗职责：拉起服务 + 30s 健康巡检（连续 2 次失败拉起新进程）+ 触发快照采集 |
| **Linux / macOS 开发** | `make dev` 或 `make run` | `Makefile`：`uv sync --extra dev` → `uv run uvicorn app.main:app`（`--reload` 仅 `make dev`） | 推荐 uv（pip 等价命令兼容） |
| **Docker 容器** | `docker compose up --build` | `Dockerfile` + `docker-compose.yml`：端口 8888 映射、`./data:/app/data` 卷持久化 SQLite、`APP_ENV=prod`、策略 `restart: unless-stopped` | 容器内 SQLite 在宿主机可见，方便备份 |

### 5.2 启动期健壮性（lifespan 钩子，5 步顺序）

`src/app/main.py::lifespan` 按顺序执行：

1. **WAL checkpoint（TRUNCATE）** —— `asyncio.to_thread(sqlite3.PRAGMA wal_checkpoint)` 清理上次异常退出遗留的 `-wal/-shm`，防止新连接卡在恢复/锁等待。**异常强杀（如 -9）不阻断启动**。
2. **Alembic 升级到 head** —— 以**子进程**方式跑 `alembic upgrade head`（`subprocess.run(..., timeout=60)`），与应用异步引擎完全隔离，避免双写者争 SQLite 写锁导致永久等待；超 60s OS 级 kill 子进程并回退 `Base.metadata.create_all`。
3. **`ensure_sqlite_columns` + `ensure_sqlite_optimizations`** —— 运行时幂等补齐历史库缺失的新增列（V0.62.0 `positions.account_id` / V0.55.0 `deleted_at` 等）+ WAL/索引优化。
4. **默认账本保障（`_ensure_default_account`）** —— V0.62.0 引入。`accounts` 表为空时显式 seed id=1「默认账户」，使历史持仓在账本视图中可见，避免「无归属」孤儿数据。
5. **后台预热 + 调度器启动** —— 异步后台 `asyncio.create_task(_warm_cache())` 拉取 ny/etf/gram 三市场 60 天 K 线 + 预生成当日 served cache（首屏秒级命中）；同时启动 `daily_capture_loop`（07:00 BJT 落快照 + 日内 4 时点 09:30/11:30/14:00/15:30 BJT 预热 served cache）+ `monthly_central_bank_loop`（每月 1/15/末日 07:30 BJT 拉 WGC）。

### 5.3 运行时质量（实测，V0.64.0）

| 指标 | 实测值 | 度量方法 |
|------|------|---------|
| **冷启动耗时（pip 安装后首次启动）** | ~30-40s | uvicorn 启动 + alembic 子进程 + 三市场 60 天 K 线预热 + served cache 生成 |
| **冷启动首屏响应** | < 5s | served cache 预热命中 + Chart.js CDN |
| **缓存命中首屏** | < 5s（典型 1.6s） | `quote_cache_ttl=300` + `served_cache_ttl_seconds=600` 双层命中 |
| **离线全量回归** | **388 passed / 0 failed**（432 用例收集，排除 2 个联网 fetcher 文件 44 用例；本机实测 27m05s，耗时主要在行情源网络超时重试） | `python -m pytest -q --ignore=tests/test_services/test_irfcl_fetcher.py --ignore=tests/test_services/test_h15_fetcher.py` |
| **全量回归（含联网 fetcher）** | **431 passed / 1 skipped / 0 failed**（432 collected，19m59s；跳过项为 fetcher 依赖 gitignore 数据文件的既有 skipif 守卫） | `python -m pytest -q` |
| **JS 门禁** | 10 个脚本全 OK（7 静态页 + 3 共享） | `python scripts/check_static_js.py` / `make check-web` |
| **ruff 检查** | 0 错误 | `ruff check src tests` |
| **行情源灵活度** | 4 选 1（akshare / mock / eastmoney_only / sina_only） | `.env` `MARKET_PROVIDER` |
| **依赖** | 仅 `fastapi + uvicorn + sqlalchemy + aiosqlite + akshare + pydantic-settings + ruff + pytest` | `pyproject.toml` `[project.optional-dependencies]` |

> **ruff 基线说明（V0.63.0 起）**：`[tool.ruff.lint]` 的 `select` 使用**规则组前缀**（`E/F/I/UP/B/SIM/RUF`），因此**必须配合版本锁定**——ruff 小版本会在组内新增规则，门禁会毫无征兆地从 0 条变成数千条（0.16.5 曾一次报出 3749 条，其中 3494 条为中文全角标点的 `RUF001/002/003` 误报）。现锁 `ruff>=0.16,<0.17`，并显式 ignore：中文全角标点（`RUF001/002/003`）、`B008`（FastAPI `Depends(...)` 默认参数）、`BLE001`（行情源失败降级需捕获宽泛异常）、`UP017`（`timezone.utc`）。**升级 ruff 前请先重跑 `ruff check src tests` 并复核 ignore 列表。**

### 5.4 自愈能力

- **进程内看门狗**：`watchdog.py --interval 30 --threshold 2` 每 30s 巡检 `/api/v1/health`，连续 2 次失败自动拉起新进程。
- **进程外兜底**：Windows 计划任务每 30s 巡检（看门狗自身也可能挂）。
- **数据源降级**：`MARKET_PROVIDER=akshare` 任意子源失败 → 自动 fallback chain（goldapi → sina → etf_history）→ 兜底内置 Mock；`source_status()` 实时标记 `live / mock / stale`，前端 `freshness.js` 60s 同步。
- **启动卡死自愈**：`start_server.bat` 检测到端口被残留进程占用 → `taskkill /F /PID` 后自动重启。
- **首屏加载**：6 个 `Promise.allSettled` 并发拉取，互不阻塞；任一失败仅记日志不影响其他。

### 5.5 已知部署边界（写在 README 里供首次部署参考）

| 项 | 限制 | 解决方式 |
|---|---|---|
| 监听地址 | 默认 `127.0.0.1`（仅本机） | 反向代理 / 防火墙转发；或将 `uvicorn --host 0.0.0.0`（`install_startup.ps1` 计划任务已是 `0.0.0.0`） |
| 公网鉴权 | 无（设计为单用户本机） | 待 P3 #16 公开部署；当前**仅可信网络环境运行** |
| SQLite 并发写 | 单写者；高并发下偶发 `database is locked` | 已开启 WAL + 应用内串行写队列；不建议多进程部署 |
| AKShare 子进程开销 | 首次 import ~3-5s | 后台预热已覆盖；冷启动 < 5s |
| 数据备份 | SQLite 单文件 | `data/gold_etf.db` 拷走即全量（持仓 / 流水 / 快照 / 央行购金 / 账本全在）；`/positions/export` + `/trades/export` 提供 CSV 对账 |
| 卸载 | `install_startup.ps1` 启动文件夹版：`Remove-Item "$env:APPDATA\Microsoft\Windows\Start Menu\Programs\Startup\GoldPriceAssistant.bat"`；计划任务版：`Unregister-ScheduledTask -TaskName "GoldPriceAssistant" -Confirm:$false`（×3） |

---

## 六、用户体验改进方向（UX Roadmap）

> 基于 V0.53.0 现状，围绕「数据可信、看得懂、用得顺、记得住、主动提醒」五个体验目标梳理可落地方向。
> 优先级：🔴 高（影响信任/可用性）｜ 🟡 中（显著提效）｜ 🟢 低（锦上添花）。与既有 P1/P2/P3 路线衔接。

### 6.1 数据时效与语境透明（🔴 高 · 消除"误判数据新鲜度"）✅ 已落地（V0.52.0）
- 全局显示**数据时效标记**：实时 / 延时 / T-1，附最后更新时间戳；
- **交易时段提示**：纽约金（几乎全天 + 夜盘）与国内市场的盘前/盘中/休市状态，避免把盘后静态价当实时；
- 降级数据（stale / mock）在图表与数字上持续角标，绝不静默。

> 实现要点（V0.52.0）：新增 `utils/market_clock.py`（纽约金 CME Globex / 上海金 SGE / ETF 三时段判定 + 时效分级）、`services/freshness.py`（FreshnessService）、API `GET /api/v1/market/freshness`；趋势接口 `GET /api/v1/market/gold/trend` 内嵌 `freshness` 字段；前端 `static/freshness.js` 全站时效条（60s 刷新），趋势页主面板/上海金面板加 stale/mock 持续角标。

### 6.2 响应式与移动端适配（🟡 中）✅ 已落地（V0.53.0）
- 新增共享 `static/responsive.css`（768/480/360 三档媒体查询断点），四页 `</style>` 之后引入，媒体查询覆盖内联基准样式；
- 窄屏/平板下：顶栏链接可换行、追踪指数面板与导航网格纵向堆叠、宏因子/权重固定宽列收窄、表单与输入框满宽纵向排列、持仓表格在 `#posArea` 内横向滚动（不再撑破页面）、按钮最小高度放大（触控友好）、时效条超小屏字号微调；
- 关键指标（评估指数 / 建议仓位 / 今日操作清单）在窄屏首屏优先置顶，一屏可读；
- 注：「顶部导航折叠为抽屉菜单」为更高阶优化，本次未做（当前链接已可换行容纳，暂够用）。

### 6.3 决策可解释性增强（🟡 中 · 降低理解成本）✅ 已落地（V0.54.0）
- 决策理由做成**利多/利空因子对照条**（红绿着色），替代纯文字罗列；
- 当前仓位 vs 建议仓位**可视化进度条**，加仓/减仓幅度直观；
- 指数构成（技术/宏观/消息）以堆叠条呈现，权重调整即时反映。

> 实现要点（V0.54.0）：`schemas/position.py` 新增 `ReasonItem(text, direction)`，`DecisionOut` 增加 `reason_items`（保留 `reasons` 向后兼容）；`services/decision.py` 的 `_build_reason_items` 为每条理由标注 `bullish`/`bearish`/`neutral`（参数面按指数方向、交易面按盈亏、决策依据按行动、仓位建议标中性）；前端 `portfolio.html` 用 `buildFactors()` 渲染红绿对照条（`.bullish` 红 / `.bearish` 绿 / `.neutral` 灰，含「利多/利空/中性」标签），并用 `buildComposition()` 以堆叠条展示技术/宏观/消息三面对应分值与方向着色。

### 6.4 操作闭环防错与撤销（🟡 中）✅ 已落地（V0.55.0）
- 交易录入**校验 + 确认弹窗**（价格/数量范围、手续费提示），防误点；
- 误录交易**软删除 + 撤销按钮**；
- 数据**本地导出**（持仓/快照 CSV），便于对账与备份。

> 实现要点（V0.55.0）：前端开仓/加仓/减仓/清仓统一走 `confirmDialog()` 二次确认弹窗（展示数量/成交价/手续费/预估金额摘要，减仓/清仓/删除标红危险态）；`validateTrade()` 做范围校验（数量/价格/手续费上限，错误前端即时提示）；持仓列表新增「删」按钮 → `DELETE /api/v1/positions/{id}` 软删除（`models/position.py` 加 `deleted_at`，`utils/db_migrate.py` 的 `COLUMN_MIGRATIONS` 启动幂等补齐该列），删除后 `#toast` 提示条提供 8 秒「撤销」→ `POST /{id}/restore`；`GET /api/v1/positions/export` 返回 UTF-8 BOM 的持仓+交易流水 CSV 供下载；前端 `API_BASE` 改为同源（修复此前写死指向已死 8888 端口导致接口全失败的问题）。

### 6.5 个性化与上下文记忆（🟢 低）🟡 部分落地（V0.62.0）
- 记住上次标的/区间、默认展示纽约金 or ETF、亮/暗主题切换（**待做**）；
- ✅ **V0.62.0 已落地「多账本隔离 + 上下文记忆」**：`accounts` 表 + `positions.account_id` 实现**单用户多账本**（默认账本 / 新建 / 改名 / 设默认 / 归档 / 恢复），前端 `static/account.js` 在 6 个页面注入统一**账本切换器**并用 `localStorage.gold_account_id` **记住当前账本**，切换后各页自动重取数据；「全部账本」为合并视图（`account_id=None`）。多用户 `user_id` 仍为单用户预留，未做登录隔离。

### 6.6 主动提醒与推送（🟡 中 · 从"被动查看"到"主动触达"）✅ 已落地（V0.56.0，前端侧）
- 评估指数/价格跨越阈值时，除页面提示外增加**浏览器通知**，可选**邮件 / 微信推送**；
- **盘前/盘后一句话简报**（自动生成，含三市场对照与今日操作清单）。

> 实现要点（V0.56.0，纯前端）：持仓决策页新增「🔔 提醒」开关（`localStorage` 记忆 `pm_alert_on`，默认关）；开启时若浏览器支持则请求 `Notification` 授权。页面每 60s 轮询 `decision` + `gold` 行情（`startAlertPolling`），`checkAlerts()` 比较评估指数档位（`bandOf(score)`：强烈偏空/偏空/中性/偏多/强烈偏多）与纽约金价格：档位切换或金价波动 ≥2% 时，触发浏览器 `Notification` + 顶部 `alertBar` 提示条（6s 自动消失）；`renderBriefing()` 在决策区下方常驻展示「今日简报」一句话（指数/档位/建议动作/建议仓位/纽约金现价涨跌）。邮件/微信推送因依赖外部服务与密钥，本期未实现，标注于路线表。

### 6.7 多时间框架与回测可视化（🟢 低 · 增强"指引可信"）🟡 部分落地（V0.61.0 + V0.63.0 + V0.64.0）
- ✅ **V0.64.0 已落地「K 线主图多时间框架」**：趋势页 K 线主图加 60D / 52W / 24M 三档区间按钮（仿 V0.63.0 snapRangeBtns 模式）；服务端抽 730 天日 K → ISO 周界聚合到 ~52 根周 K / 年月聚合到 ~24 根月 K；MA 在聚合后序列上重算（周线 MA5 ≈ 1 交易月、MA20 ≈ 季线、MA40 ≈ 半年线）；W/M 模式技术面 5 维度旁路（指标对日 K 敏感），宏观与消息面仍正常合成综合指数；`/gold/trend?interval=W|M` + `days` 上限 250 → 750；缓存 key 扩展为 (target, interval, date) 三维独立；`trendChart.destroy()` 内存管理（仿 V0.63.0 snapChart 模式）；60s 轮询只刷日 K，避免每分钟重画周/月主图；摘要自适应（"近 1 年" / "近 2 年"）。P2 #9 多时间框架（周/月线趋势）由 ⚠️ 未做 升 ✅ V0.64.0；
- 评估指数**历史曲线回看** ✅ **V0.63.0 已落地**：综合 / 技术 / 宏观 / **消息面** 4 条线 + 7D / 30D / 90D 区间切换 + 4 个极值卡（最新 / 区间最高 / 区间最低 / 日变）+ 稀疏数据 3 档 UX；
- 用历史数据**回测权重有效性**，给用户"过去准不准"的参照（待做，依赖回测引擎 P3 #13）；
- ✅ **V0.61.0 已落地「交易业绩可视化」**：账户**收益曲线**（累计收益率 + 持仓市值双轴，30/90/180/365 天区间可切换，含最大回撤）+ **获利分析总结评估**（已实现 / 浮动盈亏、平仓笔数与胜率、盈亏比、最佳/最差平仓、平均持仓天数 + 面向客户的中文复盘总结）。曲线由 `trade_records` 回放重建，历史交易即刻可见，无需等每日快照长期积累。

### 6.8 新手引导与帮助体系（🟢 低）✅ 已落地（V0.58.0）
- 首次使用**高亮引导（tour）**；各指标 **tooltip** 解释与术语表；
- 投资警示常驻，决策页附"本工具为研究参考，不构成投资建议"。

**V0.58.0 实现要点**：
- 新增 `static/help.js`（~480 行，自包含 IIFE 挂在 `window.PM_Help`）+ `static/help.css`（暗色主题，移动端 <768px modal 改为底部抽屉）；
- **3 tab modal**：操作指南（每日 5 步流程 + 4 页面链接）/ 术语速查（30+ 术语按 7 类分组：评估指数/指标均线/宏观因子/品种代码/交易动作/系统状态/时段）/ 数据来源（5 类数据源 + 投资警示 + 交易时段 + 采集容错）；
- **首访 tour 浮层**：5 个页面分别配 2-4 步（首步统一指向 `.topnav`），蒙层 + 高亮框 + 步骤切换；`localStorage.pm_help_tour_<page>` per-page 记忆 + `pm_help_seen_version` 升级时强制重看；
- **15 项 inline tooltip**：综合指数 / 技术面 / 宏观面 / 消息面 / MA5/20/40 / RSI(14) / T12M / cb_gold / DXY / 美债10Y·30Y / VIX / Au99.99 / COMEX / SGE / 518880 / 仓位推荐，覆盖 5 个页面关键位置；
- 5 个 HTML 页面各 +2 行：`<link href="/static/help.css">`（在 responsive.css 之后）+ `<script src="/static/help.js" defer></script>`（在 freshness.js 之后或 `</body>` 前）；
- 命名空间：`pm_help_*`（与既有 `pm_alert_on` 风格一致）；
- 63 项新测试（`tests/test_help/test_glossary.py` + `test_modal.py`），其中 `test_modal.py` 通过 Node 子进程沙箱执行抽取的 JS 函数，验证 escapeHtml 转义与 XSS 防护；
- 不在范围：亮/暗主题切换（属 UX 6.5 个性化）、多语言、视频教程 —— 留作后续 V0.59+。

### 6.9 加载与离线体验（🟡 中）
- 区块**骨架屏**升级（已有进度条），部分接口失败时**降级展示**而非整页错误；
- **Service Worker 离线缓存**常用页面与最近一次数据，断网仍可看历史。

### 6.10 央行购金数据化与自动化（🟡 中 · 从「硬编码 STATIC_REF」到「自动数据化」）✅ 已落地（V0.57.0）
- 趋势页宏观因子卡的 `cb_gold`（国际央行购金量）原为 STATIC_REF 硬编码（1019 吨/年 T12M），数据来源仅一行注释；现**从 `central_bank_purchases` 表自动汇总 T12M**，表无数据时回退 STATIC_REF；
- 新增 `/central-bank` 页面（4 KPI 卡 + Chart.js 堆叠柱状图 + Top 10 榜 + 按国家/季度范围筛选明细表），用于人工研判；
- 数据源由 IMF IRFCL（不可达）切到 **WGC Gold Demand Trends HTML chart JS**（`fsapi.gold.org/api/v12/charts/js/...`，绕开 XLSX 403 反爬），覆盖全球合计 2014Q1–2026Q2（52 季度）+ H1 2026 按国家（19 买家 + 4 卖家）+ UZB/IRN 手工补丁；
- **月度自动调度**：每月 1/15/末日 07:30 BJT 由 `services/scheduler.py` 自动从 WGC 拉取（`calendar.monthrange()` 动态月末），通过 `CENTRAL_BANK_AUTO_REFRESH` 环境变量开关；
- 三层测试：fetcher（32 项 `_parse_chart_series` / `_iso_for_country` / `_find_country_chart` / 端到端 mock）+ scheduler（26 项 BJT 时区算术 + 月末动态 + 环境变量开关 + 异常容错）+ 集成（service + API）。

> 实现要点（V0.57.0）：新增 `models/central_bank.py`（`CentralBankPurchase` 表 + `(country_iso, quarter)` 唯一约束）+ Alembic 迁移 `c1b3a1d27e9f_central_bank_purchases.py`；`repositories/central_bank_data.py` 重写为 WGC HTML chart JS fetcher（`_fetch_chart_js` / `_parse_chart_series` / `_find_country_chart` / `_iso_for_country` / `load_manual_overrides`）；`services/central_bank.py` 提供 `summary()` / `top_buyers(year, limit)` / `list_purchases(from_q, to_q, country)`；`MacroFactorService` 注入 `CentralBankService` 让 `cb_gold` 从表自动汇总；`scripts/import_central_bank.py` CLI + `scheduler.monthly_central_bank_loop()` 后台协程共用 `run_import()` 入口。

### 6.11 研判复盘与准确率校准（🟡 中 · 从「打个分」到「打得准」）✅ 已落地（V0.66.0）

> **非原路线图项** —— 由「消息展望出现重复打分」的排查延伸出的新能力：把「判断」与「结果」放到同一张对照表上，让打分准确率**可度量、可改进**。

- **问题**：打分只有自由文本备注，既无法回看「当时依据什么判断」，也没有把「判断」与「之后金价实际怎么走」对齐 —— **准确率无从改进**；
- **按日期归档**：每日卡片对齐一行数据 —— 当日加权分值 / 方向 / 依据标签 / 备注 → 基准日收盘 → **T+1 / T+3 / T+5** 收盘与涨跌幅 → 命中或偏离；
- **判定口径**：基准价取研判日（或之前最近交易日）收盘；窗口一律按**交易日**对齐（自动跳过周末与休市）；看多须涨、看空须跌、看平 `|涨跌| ≤ 0.3%`；
- **校准统计**：总命中率、按方向分组、按窗口分组、**分值分箱校准曲线**（"打 70 分时实际上涨概率是多少"）、**依据标签胜率**（哪类依据最可靠）；样本 < 20 时明确标注「仅供参考」；
- **闭环反馈**：打分页滑竿旁实时显示「您在 60-80 档打过 N 次，上涨概率 X%、命中率 Y%」—— 高估自己会被直接指出；
- **前视偏差防护**：允许按指定日期**补录**历史研判以快速攒样本，但记录打 `backfilled` 标记，**统计整日排除**，补录样本单独展示。

**V0.66.0 实现要点**：新增 `models/review.py`（`GoldPriceDaily` 表，`target` + `price_date` 唯一）+ `repositories/review.py`（`list_range` / `get_on` / `latest_before` / `upsert_many` —— **在合并后的时间序列上重算涨跌幅**，重复回填不抹平已有值）+ `services/review.py`（`backfill` / `journal` / `stats` / `hint_for_score`）；`news_scores` 增 `basis` / `review_note` / `backfilled` 三列（迁移 `a3d9e1f7b2c4`，运行时 `db_migrate` 兜底）；`NewsScoreService` 抽出公共 `aggregate_slots`，使复盘与打分页口径同源；新增 `static/review.html`（统计面板 + 研判日志）并在 5 个既有页面加导航入口；`news.html` 增 12 个依据标签多选与打分时校准提示。

**建议落地顺序**：6.1（信任）→ 6.2 / 6.3（看懂用顺）→ 6.6（主动触达）→ 6.10（数据化）→ 6.4 / 6.5 / 6.7 / 6.8 / 6.9 → 6.11（复盘校准，V0.66.0 已落地）。

---

## 七、附：与既有文档的关系

- 架构 / API / 核心模型 / 改进计划总表：见 [application-guide.md](application-guide.md) 第 11 章
- 快速开始与功能清单：见 [README.md](../README.md)
- 本文档聚焦**易用性**维度的改善路径，与技术改进计划（数据源扩展、回测、CI/CD 等）互补。
