# 功能对账报告 · README ↔ 代码 ↔ 文档

> 生成日期：2026-09-18 ｜ 最近更新：2026-09-29 ｜ 适用版本：**V0.74.2**
> 目的：定期核对 README 功能清单、实际代码实现、文档声明三方的落地状态，标记 ✅ 已落实 / ⚠️ 半成品 / 📋 待办，避免文档漂移。

---

## 一、README 功能清单 vs 代码实际（截至 V0.74.2）

| README 声明 | 代码位置 | 状态 |
|---|---|---|
| 三市场行情（NY/上海金/ETF） | `market.py` `/gold/trend` + `target=ny/etf/gram` | ✅ |
| 综合趋势指数（5 维技术 + 5 因子宏观 + 消息 30%） | `services/trend.py` + `macro.py` | ✅ |
| 宏观参考因子（5 因子含 cb_gold） | `services/macro.py` + 中央银行注入 | ✅ |
| 权重配置 `/weights` | `static/weights.html` + `settings.py` | ✅ |
| **央行购金统计 `/central-bank`** | `static/central_bank.html` + 3 endpoints | ✅（V0.57.0） |
| 个人交易跟踪（含软删除/撤销/CSV 导出） | `position.py` 9 个 endpoint | ✅ |
| 购买决策（含仓位推荐 + 决策可解释性） | `decision.py` `/etf` | ✅ |
| 每日快照 | `snapshot.py` + 自动补当日 | ✅ |
| **自动调度** | `scheduler.py` 每日 07:00 + 央行月 1/15/末 07:30 | ✅（V0.57.0） |
| 可视化 5 页 | trend/portfolio/weights/news/central-bank | ✅ |
| 消息面评估页 `/news` | `static/news.html` + `news.py` | ✅ |
| 数据时效透明（freshness.js 三态） | `static/freshness.js` + `/market/freshness` | ✅（V0.52.0） |
| 主动提醒（前端通知 + 简报） | `static/portfolio.html` 6.6 节 | ✅（V0.56.0） |
| **新手引导与帮助体系** | `static/help.js` + `static/help.css` + 5 HTML 各 +2 行 | ✅（V0.58.0） |
| **行情源 provider 可切换** | `MARKET_PROVIDER=.env` 配置（akshare / mock / eastmoney_only / sina_only / silver_yahoo） | ✅（V0.59.0，V0.73.0 N+12 扩展 silver_yahoo） |
| **行情实时性增强** | served cache 日内 TTL + 行情 cache 启用 + 日内 4 点预热 + 前端 60s 轮询 + visibilitychange | ✅（V0.60.0） |
| **ETF 报价口径修正** | `get_gold_etf_quote()` + `GET /market/gold/etf-quote`（元/份）；PositionService 改用 ETF 价 | ✅（V0.61.0） |
| **加仓 / 减仓内联面板** | `portfolio.html` 交易面板（金额↔份数、快捷比例、盈亏预览）+ `GET /positions/{id}/trades` | ✅（V0.61.0） |
| **收益曲线** | `GET /api/v1/portfolio/equity-curve` + `PortfolioAnalyticsService.equity_curve` | ✅（V0.61.0） |
| **获利分析总结评估** | `GET /api/v1/portfolio/performance` + `PortfolioAnalyticsService.performance` | ✅（V0.61.0） |
| **收益口径一致性** | 回放成本不含手续费（对齐 `add_trade` 摊薄成本），fee 并入 `total_invested`；两面板收益率一致（回归测试 2 例守护） | ✅（V0.61.0） |
| **前端内联 JS 门禁** | `scripts/check_static_js.py` / `make check-web`：语法 + 未定义调用 + DOM id 一致性 | ✅（V0.61.0） |
| **评估指数历史曲线升级** | 趋势页 `loadSnapshots(days)` 重构：综合 / 技术 / 宏观 / **消息面（新增）** 4 条线 + `7D / 30D / 90D` 区间切换按钮 + 4 个极值卡（最新 / 区间最高 / 区间最低 / 日变）+ 稀疏数据 3 档 UX + `snapChart.destroy()` 内存管理 | ✅（V0.63.0） |
| **多时间框架（周/月线）** | 趋势页 K 线主图加 3 档区间按钮（60D / 52W / 24M）：服务端抽 730 天日 K → 按 ISO 周界聚合到 ~52 根周 K / 按年月聚合到 ~24 根月 K；MA 在聚合后序列上重算；W/M 模式技术面 5 维度旁路（指标对日 K 敏感）；`/api/v1/market/gold/trend?interval=W\|M` + `days` 上限 250 → 750；缓存 key 扩展为 (target, interval, date) 三维独立 | ✅（V0.64.0） |
| **消息面每日 3 次打分** | `models/news.py` `slot`(1-3) / `scored_at` + `(score_date, slot)` 复合唯一；`services/news.py` 自动占位 + `Σ(i×scoreᵢ)/Σi` 加权 + 用尽拦截（400）+ 显式覆盖修正；`DELETE /news-score/{slot}` + `GET /news-score/history`；`static/news.html` 三槽位卡片 + 加权算式面板 | ✅（V0.65.0） |
| **研判复盘与准确率校准** | `models/review.py`（`gold_price_daily`）+ `repositories/review.py`（`upsert_many` 合并后重算涨跌幅 + V0.67.0 schema 校验）+ `services/review.py`（`backfill` / `journal` / `stats` / `hint_for_score`）+ 6 个 review 接口 + `static/review.html`；`news_scores.basis` / `review_note` / `backfilled` | ✅（V0.66.0） |
| **框架基础补齐（CI/CD + trace_id + 价格校验）** | `app/middleware/trace.py` `TraceIdMiddleware`（纯 ASGI，X-Request-ID 入站沿用 / UUIDv4 自动生成 / 响应头回写 / contextvars 注入）+ `utils/logger.py` 自动附加 trace_id；`repositories/review.py` `upsert_many` schema 校验（`close > 0` 含 NaN 检测 / `source` 白名单 / 单日涨跌幅 ±50% 跳过）；`.github/workflows/ci.yml` Python 3.11/3.12 matrix + uv 缓存 + concurrency | ✅（V0.67.0） |
| **导航折叠 + 全局搜索 + 客户端埋点底座** | 后端 `models/telemetry.py` `TelemetryEvent`（append-only + `(event_type, created_at)` 复合索引）+ `repositories/telemetry.py` + `services/telemetry.py`（白名单 10 类事件 + page `/` 开头校验 + payload ≤50 字段）+ `api/v1/endpoints/telemetry.py`（`POST /ingest` + `GET /stats?days=N`，trace_id 透传）+ 迁移 `b7c5d9e3f1a2`；前端 `static/telemetry.js`（sendBeacon 批量 + visibilitychange / pagehide / error 兜底 + localStorage 会话）+ `static/nav-drawer.js`（自注入 CSS + 汉堡按钮 + 抽屉 + 遮罩，≤768px 自动折叠）+ `static/command-palette.js`（⌘K 唤起 + 13 命令 + ↑↓/Enter/Esc + pm-range-change / pm-theme-change CustomEvent）；7 页统一注入 | ✅（V0.68.0） |

**测试数对账（2026-09-26 实测）**：`pytest --collect-only -q` = **728 用例 / 59 个测试模块**，`find tests -name "test_*.py"` = **59 文件**。纵向演变（有文档记载的节点）：V0.64.0 = 397 → **V0.65.0 = 410**（新增 `test_api/test_news_api.py` 7 例 + 重写 `test_news_service.py` 5 → 11 例，净 +13）→ **V0.66.0 = 432**（`test_review_service.py` 13 + `test_review_api.py` 9，净 +22）→ **V0.67.0 = 454**（`test_trace_id.py` 8 + `test_price_calendar_validation.py` 12 + `test_logger_trace_id.py` 2，净 +22）→ **V0.68.0 = 468**（`test_telemetry_service.py` 9 + `test_telemetry_api.py` 5，净 +14）→ **V0.69.0 = 485** → **V0.70.0 = 510**（共振 11 + 共振 API 3 + 克数 10 + 克数 API 4 + gram-quote 1）→ **V0.71.0 = 557**（白银 20 + 回测 27）→ **V0.73.0 = 664**（i18n / push / PWA 等）→ **684**（V0.73.0 N+8~N+15：i18n 三语 + `test_i18n_apply.py` + push service + 白银 provider + 仓储单例）→ **728**（V0.74.0：N+17 仪表盘布局 10 + N+18 告警规则 `test_alert_service` 12→30（+18）/ `test_settings` +5 / `test_alert_rules_ui` 11）。

**V0.74.0 回归实测（2026-09-26）**：① `python -m pytest -q --ignore=tests/test_services/test_irfcl_fetcher.py --ignore=tests/test_services/test_h15_fetcher.py`（排除 2 个联网 fetcher 文件共 44 用例）= **684 passed / 0 failed（221.54s）**；全量口径 = **727 passed / 1 skipped / 0 failed**（728 collected）；② `ruff check src tests` = **All checks passed**（`ruff>=0.16,<0.17` 锁版，lock = 0.16.6）；③ `ruff format --check src tests` = **174 files already formatted**；④ `python scripts/check_static_js.py` = **12 静态页 + 19 共享脚本全部通过**（语法 / 引用 / DOM id，含新增 `dashboard.js` 与 `data-health.html`）；⑤ `uv lock --check` = **Resolved 80 packages**（lock 与 pyproject 一致，CI `uv sync --frozen` 不会因 lock 过期失败）。

**V0.74.2 回归实测（2026-09-29）**：① 全量回归 = **727 passed / 1 skipped / 0 failed**（728 collected，3894.85s —— ⚠️ 本机环境较慢，约 5s/用例，较 V0.74.0 那次的 221.54s 慢约 18 倍，**属环境问题而非回归**）。**口径澄清**：本次命令写的是 `pytest -q -m "not network"`，但实测 `pyproject.toml` **既未在 `markers` 中注册 `network`**、`tests/` 下**也无任何 `@pytest.mark.network`**（`grep` 全仓 0 命中）→ 该 `-m` 过滤**未排除任何用例**，跑的就是全集 728；真正排除联网 fetcher 的是**文件名**口径 `--ignore=tests/test_services/test_irfcl_fetcher.py --ignore=tests/test_services/test_h15_fetcher.py`（44 用例 → 684）。**建议**：要么注册并使用 `network` marker，要么把文档里的 `-m "not network"` 全部改成 `--ignore=` 口径，避免下次误以为「已跳过联网用例」；② `pytest tests/test_i18n -q` = **58 passed**，且全量输出中的 `SyntaxWarning: invalid escape sequence '\u'` **归零**（见 §四 #49）；③ `python scripts/check_static_js.py` = **12 静态页 + 19 共享脚本全部通过**；④ `python scripts/check_docs_claims.py` = **287 处声明全部命中**（表名 42 / localStorage key 23 / 页面 43 / 端点 179）。**前端行为验证（新增手段）**：headless Chrome `--virtual-time-budget=75000` 快进跨过一次 60 秒轮询周期后截图 → 趋势页主图与两张对照价格图均完好、0 未捕获错误（见 §四 #48，方法另立技能 `headless-chrome-screenshot`）。

---

## 二、application-guide.md 第 11 章改进计划对账

### P1 · 工程化收口

| # | 事项 | 文档状态 | 实际 | 一致性 |
|---|------|------|------|------|
| 1 | V0.50 发布 | ✅ | ✅ | ✅ |
| 2 | 权重配置页 | ✅ | ✅ | ✅ |
| 3 | **CI/CD** | ✅ V0.67.0 | ✅ `.github/workflows/ci.yml`（Python 3.11/3.12 matrix + uv 缓存 + concurrency 取消旧 PR + `fail-fast: false` + pytest + ruff + JS 门禁） | ✅ |
| 4 | Alembic 迁移 | ✅ | ✅ + 央行购金表 c1b3a1d27e9f | ✅ |
| 5 | **行情源配置化** | ✅ V0.59.0 | ✅ MARKET_PROVIDER=.env 4 选 1 + 工厂 + bundle 注入 | ✅ |
| 5′ | （application-guide P1 表 #5 长期停留 📋） | ✅ | ✅ 实际 V0.59.0 已落地，**V0.62.0 已修正该陈旧状态** | ✅ 已修正 |
| 6 | **多账户 + 交易历史查询页** | ✅ V0.62.0 | ✅ 单用户多账本（`accounts` + `positions.account_id`，历史持仓归入默认账户）+ `/accounts` 6 端点 + `/trades` 查询/导出 + `static/account.js` 全站切换器 + `/trades` 页面 | ✅ |

> **验证阶段发现并修复（V0.62.1）**：端到端验证 V0.62.0 改进项时，发现 `PortfolioAnalyticsService._replay()` 在**成交日晚于价格序列最后一个交易日**时（行情源 T-1 滞后 / 盘中录入 / 周末录入均会触发）用 `if idx < len(price_dates)` 把该笔交易**静默丢弃**，导致同一响应内 `sell_count` 与 `closed_trades` 自相矛盾、「累计投入本金」显示 **0.00 元**、胜率为 0%，与持仓页实时持仓冲突。已改为归入最后一个可得交易日，并补 2 项回归测试（含 `sell_count == closed_trades` 自洽断言）。
>
> 验证方法与结论见 §六「对账方法」补充的端到端验证清单。

### P2 · 分析深度

| # | 事项 | 文档状态 | 实际 | 一致性 |
|---|------|------|------|------|
| 7 | **宏观×技术共振**（双维度信号/背离） | 📋 | ❌ 仅有宏观因子表，无共振/背离判定 | ⚠️ 未做 |
| 8 | **克数持仓跟踪** | 📋 | ❌ 持仓只按 ETF 份数 | ⚠️ 未做 |
| 9 | **多时间框架（周/月线）** | ✅ V0.64.0 | ✅ V0.64.0 已落地——趋势页 K 线主图加 60D / 52W / 24M 三档区间按钮；服务端抽 730 天日 K → ISO 周界聚合 ~52 根周 K / 年月聚合 ~24 根月 K；MA 在聚合后序列上重算；W/M 模式技术面 5 维度旁路；`/gold/trend?interval=W\|M` + `days` 上限 250 → 750；缓存 key 扩展为 (target, interval, date) | ✅ |
| 10 | **指数参数校准（回测）** | 📋 | ❌ 无回测引擎 | ⚠️ 未做 |
| 11 | **多品种（白银）** | 📋 | ❌ | ⚠️ 未做 |

### P3 · 产品化

| # | 事项 | 文档状态 | 实际 | 一致性 |
|---|------|------|------|------|
| 12 | **仓位建议（账户本金）** | 📋 | ⚠️ 部分实现（80/60/40/20/10%），无账户本金估算 | ⚠️ 半成品 |
| 13 | **模拟交易 + 回测引擎** | 📋 | ❌ | ⚠️ 未做 |
| 14 | **指数时间序列可视化** | ✅ V0.63.0 | ✅ V0.63.0 已落地——评估指数曲线（综合 / 技术 / 宏观 / 消息面 4 条线 + 7D/30D/90D 区间切换 + 4 个极值卡 + 稀疏数据 3 档 UX + chart.destroy 内存管理）；账户收益曲线 V0.61.0 已加 | ✅ |
| 15 | **监控告警** | 📋 | ⚠️ 浏览器通知已做，邮件/微信未做 | ⚠️ 半成品 |
| 16 | **公开部署** | 📋 | ❌ 当前 `127.0.0.1:8888` 仅本机 | ⚠️ 未做 |

---

## 三、improvement-path.md UX Roadmap 对账

| 编号 | 主题 | 文档 | 实际 | 一致性 |
|---|---|---|---|---|
| 6.1 | 数据时效透明 | ✅ V0.52.0 | ✅ | ✅ |
| 6.2 | 响应式与移动端 | ✅ V0.53.0 | ✅ | ✅ |
| 6.3 | 决策可解释性 | ✅ V0.54.0 | ✅ | ✅ |
| 6.4 | 操作防错与撤销 | ✅ V0.55.0 | ✅ | ✅ |
| **6.5** | **个性化与上下文记忆** | 🟡 部分（V0.62.0） | ⚠️ V0.62.0 已落地**多账本 + 全站账本切换器 + `localStorage` 账本记忆**；**主题切换与标的/区间记忆仍未做** | ⚠️ 部分 |
| 6.6 | 主动提醒与推送 | ✅ V0.56.0 | ✅ 浏览器通知（邮件/微信仍欠） | ⚠️ 部分 |
| **6.7** | **多时间框架 + 回测可视化** | 🟡 部分（V0.64.0） | ⚠️ **V0.61.0 收益曲线 + 获利分析总结** + **V0.64.0 周/月线趋势已落地**（趋势页 K 线主图 60D / 52W / 24M 切换）；权重参数回测未做 | ⚠️ 部分 |
| **6.8** | **新手引导与帮助** | ✅ V0.58.0 | ✅ help.js + help.css + 5 HTML 注入 | ✅ |
| **6.9** | **加载与离线体验** | 🟡 中 | ⚠️ 有进度条 + V0.60.0 加 60s 轮询 + visibilitychange，**仍无 Service Worker 离线缓存** | ⚠️ 部分 |
| **6.10** | **央行购金数据化与自动化** | ✅ V0.57.0 | ✅ | ✅ |
| **消息面 3 次打分** | （非路线图项，由缺陷排查延伸） | ✅ V0.65.0 | ✅ 槽位模型 + 1:2:3 加权 + 撤销 + 历史 | ✅ |
| **6.11** | **研判复盘与准确率校准** | ✅ V0.66.0（新增项） | ✅ `/review` 页 + 6 个接口 + 金价日历 + 命中率/校准曲线/标签胜率 | ✅ |
| **6.12** | **框架基础补齐（CI/CD + trace_id + 价格校验）** | ✅ V0.67.0（新增项） | ✅ `.github/workflows/ci.yml` + `app/middleware/trace.py` + `repositories/review.py` schema 校验 + 22 个新测试 | ✅ |
| **6.13** | **导航折叠 + 全局搜索 + 客户端埋点底座** | ✅ V0.68.0（新增项） | ✅ `nav-drawer.js`（≤768px 汉堡抽屉，自注入不改 HTML）+ `command-palette.js`（⌘K / Ctrl+K，13 命令：7 页导航 + 刷新 + 时间区间 1D/5D/1M + 主题切换预埋 + 帮助重看）+ `telemetry.js`（sendBeacon 批量 + visibilitychange / pagehide / error 兜底 + localStorage 会话）+ `telemetry_events` 表（append-only，复合索引 `(event_type, created_at)`）+ 2 个 telemetry 接口 + 7 页统一注入 + 14 个新测试 | ✅ |

---

## 四、文档自身不一致（V0.57.0 → V0.63.0 同步已完成）

| # | 原问题 | 修复 |
|---|---|---|
| 1 | `application-guide.md` 头部版本号 V0.53.0 → V0.57.0 → … → V0.60.0 | ✅ 已升 V0.62.1 |
| 2 | `application-guide.md` 第 10 章缺 V0.54–V0.59 六条 + 表格列错位 | ✅ 已补齐，统一 5 列格式 |
| 3 | `improvement-path.md` 头部版本号 V0.56.0 → … → V0.60.0 | ✅ 已升 V0.62.1 |
| 4 | `improvement-path.md` 实施路线表缺 V0.57.0/V0.58.0/V0.59.0/V0.60.0 行 + 6.10/6.8/P1#5 | ✅ 已补，V0.62.1 亦已补 |
| 5 | 三文档测试数不一致（67/214/216/279/303 残留 → 316） | ✅ 统一 377（离线 333 passed） |
| 6 | `application-guide.md` 第 2 章功能清单缺央行购金/调度/新手引导/行情源 | ✅ 已补 4 行 |
| 7 | `application-guide.md` 第 5 章 API 表缺 `/news-score`、`/snapshots`、`/central-bank/*` | ✅ 已补全 28 endpoints |
| 8 | `application-guide.md` 第 7 章数据源"央行购金"硬编码描述 | ✅ 改为 WGC 自动汇总 |
| 9 | `application-guide.md` 第 12 章数据来源仅 AKShare | ✅ + WGC + 行情源 provider 说明 |
| 10 | V0.58.0：help.js 内 V0.57.0 央行购金标注 | ✅ renderSourceTab 含 WGC + V0.57.0 |
| 11 | **P1 表 #5「行情源配置化」长期停留 📋**（实际 V0.59.0 已落地） | ✅ V0.62.0 已修正为 ✅ |
| 12 | `improvement-path.md` 实施路线表缺 V0.61.0 / V0.62.0 行，且 V0.61.0 仍标「（当前）」 | ✅ 2026-09-13 补 V0.62.0 行并摘掉「（当前）」 |
| 13 | `improvement-path.md` §四 验收度量表头停在「当前（V0.60.0）」 | ✅ 2026-09-13 升 V0.62.0 并补 3 项度量（交易可追溯 / 业绩可见 / 回归全绿） |
| 14 | `application-guide.md` §5 API 表缺 V0.61.0/V0.62.0 新增端点（`/trades` 页、`etf-quote`、`equity-curve`、`performance`） | ✅ 2026-09-13 补 4 行，并给 positions/decision 行补 `account_id` 参数说明 |
| 15 | `application-guide.md` §11 状态补遗注「截至 V0.57.0」（实际已到 V0.62.0） | ✅ 2026-09-13 重写为 V0.62.0 口径，补 P2/P3/UX 未做项清单 |
| 16 | P3 #14「指数时间序列可视化」停留在 ⚠️ 半成品（评估指数自身曲线仍无），实际 V0.63.0 已落地 | ✅ 2026-09-13 升 ✅ V0.63.0 |
| 17 | V0.63.0 新增 6 个测试（API 4 + 服务 2），三文档测试数声明需同步 377 → 383 | ✅ 2026-09-13 同步 README / application-guide / improvement-path / feature-alignment 四文档 |
| 18 | **代码版本号未随 V0.63.0 更新**：`pyproject.toml` 与 `src/app/main.py` 停在 `0.62.1`，`/openapi.json` 亦返回 0.62.1，而四份文档已全部声明 V0.63.0（feat 提交只改了前端与测试） | ✅ 2026-09-15 升至 `0.63.0` 并重启服务校验 |
| 19 | **`ruff` 门禁失真**：`select` 使用规则组前缀（`RUF`/`UP`/`B`）+ 依赖范围过宽（`ruff>=0.8,<1.0`），实际装入 0.16.5 后一次报出 **3749 条**（其中 3494 条为中文全角标点的 RUF001/002/003 误报），文档 §5.3 声称的「ruff 0 错误」不成立 | ✅ 2026-09-15 锁定 `ruff>=0.16,<0.17`；显式 ignore 中文标点、`B008`（FastAPI Depends）、`BLE001`（降级捕获）、`UP017`；自动修复 81 条 + 人工修 14 条 → **All checks passed** |
| 20 | **`test_market_providers.py` 用例被截断并覆盖**（F811）：`test_market_data_repository_backward_compat_provider_kwarg` 被 `_StubHistory` 类定义从中间截断，函数体只剩 docstring，其后又出现同名函数将其覆盖 → 该「旧签名向后兼容」断言等价于从未执行 | ✅ 2026-09-15 合并为单一完整用例（保留 stub 类 + 恢复断言 + 补 docstring） |
| 21 | `application-guide.md` §11 状态补遗仍写「评估指数自身曲线仍无（#14 半成品）」，与 feature-alignment 的「✅ V0.63.0」自相矛盾 | ✅ 2026-09-15 改为「#14 评估指数历史曲线 → ✅（V0.63.0）」 |
| 22 | 代码内 **14 处静态检查问题**（未使用变量/导入、`zip` 无 `strict`、`try-except-pass`、`asyncio.create_task` 未持引用等） | ✅ 2026-09-15 全部修复：`main.py` 后台任务改由强引用集合托管（防 GC 回收）等 |
| 23 | **离线回归命令引用了不存在的文件**：`improvement-path.md` §5.3 写 `--ignore=tests/test_services/test_wgc_fetcher.py`，而仓库中该文件名为 `test_h15_fetcher.py` → 该 `--ignore` 静默失效（pytest 对不存在的 ignore 不报错），**照抄命令实得 351 而非文档声称的 337** | ✅ 2026-09-15 命令修正为 `--ignore=…test_irfcl_fetcher.py --ignore=…test_h15_fetcher.py`（并在 §5.3 / README / application-guide 同步可复现写法） |
| 24 | **离线回归计数算术错误**：V0.62.1 为 377 用例 / 离线 333（差 44）；V0.63.0 新增 6 → 383，离线应为 **339**，文档却写 **337**；同一处又把 fetcher 用例数写成 **46**（实测 irfcl 32 + h15 12 = **44**） | ✅ 2026-09-15 全仓统一为 **383 收集 / 离线 339 passed / fetcher 44 用例**（README + 三文档） |
| 25 | **`test_irfcl_fetcher.py` 依赖 gitignore 的数据文件**：`test_load_manual_overrides_returns_uZB_and_irn` 读 `data/central_bank_manual_overrides.json`（`data/` 在 `.gitignore` 内），新克隆必然 failed | ✅ 2026-09-15 补 `skipif` 守卫（`cb_data._OVERRIDES_PATH` 不存在即跳过）→ 该文件 **31 passed / 1 skipped** |
| 26 | V0.64.0 多时间框架落地：服务端 ISO 周界 / 年月聚合 + MA 重算 + 技术面旁路 + 三档区间按钮；测试数 383 → 397（+14：服务 4 + API 4 + 工具 6）；P2 #9 由 ⚠️ 未做 升 ✅ V0.64.0；UX 6.7 进一步落地（周/月线部分） | ✅ 2026-09-16 同步 README / application-guide / improvement-path / feature-alignment 四文档（**原编号误标为「18」，本次修正为 26**） |
| 27 | **V0.65.0 / V0.66.0 落地后文档整体滞后**：README 与三份 docs 版本号仍停在 V0.64.0，功能清单 / API 表 / 版本历史 / 路线图 / 测试数（397）全部未同步；`improvement-path.md` 缺 V0.65.0 / V0.66.0 路线行，`application-guide.md` 缺两版版本历史 | ✅ 2026-09-16 四文档同步至 V0.66.0：README 功能清单 +2 行、API 表 +7 行、架构树更新；application-guide 功能清单 +2 行、API 表 +9 行、版本历史 +2 行、数据源 +1 行、测试数 397 → 432；improvement-path 新增 §6.11 + 两版路线行 + 验收度量更新；feature-alignment 对账表 +2 行 |
| 28 | **上游版本号曾不一致**（V0.63.0 遗留）：`pyproject.toml` 与 `src/app/main.py` 曾停 0.62.1 / 0.63.0，`/openapi.json` 与文档声明不符 | ✅ V0.65.0 已一并修正，现两处均为 **0.66.0**，线上 `/openapi.json` 实测返回 `0.66.0` |
| 29 | **V0.68.0 / V0.69.0 落地后 docs 部分滞后**：UX 路线 V0.70.0 仍写「计划」但 P2 #7 / #8 后端 + UX 已落地；`improvement-path.md` P2-b V0.70.0 行仍是 📋 待做；测试数仍 485 而非 510；`application-guide.md` §6 缺 `positions.grams_held`、§9 缺 3 个端点（resonance × 3、gram-quote），端点总数 40 而非 43 | ✅ 2026-09-19 V0.70.0 同步：improvement-path P2 #7 / #8 翻牌 ✅ + 测试 485 → 510；ux-roadmap V0.70.0 段落改「✅ 已落地」+ 增 3 端点 + 端点数 40→43；application-guide §6 增 grams_held 列、§9 API 表 +4 行（resonance signal/history/strength-up + market gram-quote）+ §11 版本历史 +1 行；README 版本号 → 0.70.0 + 测试数 510 + 功能清单 +2 行 |
| 30 | **版本号三处漂移**（V0.73.0 N+15 时）：`pyproject.toml` = `0.72.0`、`src/app/main.py` = `0.67.0`、`uv.lock` = `0.72.0`，而 README 与四份 docs 已声明 **V0.73.0**，`/openapi.json` 实测返回 `0.67.0`。根因：版本号在两处手工维护，V0.63 / V0.65 / V0.73 已连续三次漏改 | ✅ 2026-09-26 **单源化**：`src/app/__init__.py` 新增 `__version__ = "0.73.0"` 作运行时唯一真源，`main.py` 改 `version=__version__`，`pyproject.toml` + `uv.lock` 同步 `0.73.0`（`uv lock --check` 通过）；重启后 `/openapi.json` = **0.73.0 / 61 paths** |
| 31 | **CI 连续失败 8 次**（`566063b`~`0b4c87d` 全部 failure）：根因 **`ruff lint` 7 个错误** —— `dependencies.py` 未使用 `Settings` 导入（F401）、`test_dependencies/test_market_data_repository_singleton.py` 可变类属性（RUF012）、`test_resonance_api.py` 未用局部量（F841）、`test_i18n_dict.py` F401 + F841、`test_push_service.py` 盲断言 `Exception`（B017 ×2） | ✅ 2026-09-26 全部修复（含删除死代码 `FakeRepo` 类、`pytest.raises(Exception)` 改 `ValidationError`、`_load_dict` 补顶层赋值校验）→ `ruff check src tests` = **All checks passed** |
| 32 | **`ruff format --check` 从未通过**：仓库从未执行过 `ruff format`，**35 个文件**待重排（纯排版：折行 / 引号归一 / 幂等空行）；该步在 CI 中排在 lint 之后，被 lint 失败长期掩盖，从未真正执行过 | ✅ 2026-09-26 `ruff format src tests` → `35 files reformatted`；`--check` = **171 files already formatted**。改动仅限 `src/` + `tests/`（测试只读 `static/*.js`/`*.html` 文本，不读 `.py` 源码，故无副作用） |
| 33 | **`test_i18n_apply.py`（V0.73.0 N+11 新增）在 Windows 上必然全红**：把含反斜杠的路径直接插进 Node `-e` 的 JS 字符串（`loadDict('C:\...\static/i18n/zh-CN.js')`），`\U` / `\2` / `\g` 被当成 JS 转义序列吞掉 → **5 failed + 1 error**；Linux / CI 路径本身是正斜杠，故不暴露（同类问题此前已修 `test_i18n_api.py` / `test_i18n_format.py`） | ✅ 2026-09-26 改用 `json.dumps(str(STATIC))` 生成 JS 安全字面量（与另两个文件统一）；顺带修 `\s` 无效转义（Python 3.12+ SyntaxWarning，未来版本将升级为 SyntaxError） |
| 34 | **`test_market_providers.py` 4 个用例失败**（V0.73.0 N+15 起）：① `MockSilverHistoryProvider` 的 NY base 已由 31.5 上调到 **64.0**，两处断言仍写 `28~36` / `25~50`；② `test_build_provider_bundle_all_modes_have_silver_live` 对未加 `@runtime_checkable` 的 `SilverLiveQuoteProvider` 做 `isinstance` → **TypeError**（任何环境必失败）；③ `test_silver_fallback_chain_sina_first_via_settings` 补丁打在外部临时 bundle 上，而仓储在 `__init__` 内自建 bundle → **真的联网取数**（实测 64.789 vs 期望 64.5） | ✅ 2026-09-26 ① 价位断言改 **55~75** 区间并补 docstring（避免 base 微调脆断）；② 改结构化校验 `callable(getattr(..., "get_silver_spot", None))`；③ 改打 `repo._bundle.silver_live` 补丁；④ `test_yahoo_silver_falls_back_on_network_error` 改为与 `MockSilverHistoryProvider` 输出**逐根比对**，不再硬编码价位 |
| 35 | **文档版本头与测试数滞后**：`application-guide.md` 头部 V0.68.0（正文却已有 V0.73.0 版本历史行）、`improvement-path.md` 头部 V0.67.0、`feature-alignment.md` 头部 V0.68.0；测试数三份文档分别写 557 / 537 / 468，README 写 664，**实测 684**；`application-guide.md` §9 还写「9 静态页 + 10 共享脚本」（实测 **11 页 + 18 脚本**） | ✅ 2026-09-26 **已闭环**：四份文档 + README 头部版本 / 日期 / 测试数已全部对齐；V0.74.0 后再次刷新为 **728 收集 / 684 离线 passed / 12 静态页 + 19 共享脚本 / 61 REST 路径（70 端点）**。**遗留**：`application-guide.md` §6 数据模型表与 `improvement-path.md` 版本路线表尚未逐版回填 V0.69.0~V0.74.0 条目 —— 见 §五 待办 |
| 36 | **版本号在 V0.74.0 两个提交（N+17 `0f74be0` / N+18 `cb94da5`）中再次漏改**：`pyproject.toml` + `uv.lock` 仍停在 `0.72.0`，`main.py` 仍停在 `0.67.0`（单源化前的残留），而提交信息与 ux-roadmap 已声称 **V0.74.0** | ✅ 2026-09-26 单源化生效后统一升到 **0.74.0**：`src/app/__init__.py` `__version__` + `pyproject.toml` + `uv.lock`（`uv lock --check` 通过）；实测 `app.openapi()` = **0.74.0 / 61 paths**。⚠️ 注意：单源化只消除了「同一版本号写在多处」的漂移，**发版仍须人工在 `__init__.py` 升版** |
| 37 | **V0.74.0 两个远程提交自身未过门禁**（CI 持续红的直接来源）：`git rebase` 到 `cb94da5` 后新基底暴露出 **11 个 ruff 错误**（RUF100 冗余 `noqa: PLC0415` ×3、UP037 类型注解多余引号 ×4、UP007 `Optional` → `\|`、RUF022 `__all__` 未排序、F401 未用导入 ×1，以及 `services/alert.py` 的 SIM103）+ **7 个文件未格式化**（`ruff format --check` 失败）—— 即 N+17 / N+18 是在 lint 长期失败的 CI 上合入的，红灯被连续失败掩盖 | ✅ 2026-09-26 `ruff --fix`（10 项自动）+ 手修 `_is_four_level_crossing` 的 `if prev == curr: return False; return True` → `return prev != curr`（语义等价）+ `ruff format src tests`（7 文件）→ `ruff check` = **All checks passed**、`--check` = **174 files already formatted** |
| 38 | **`test_layout_persistence.py`（V0.74.0 N+17 新增）在 Windows 上 4 例必然失败**：4 处 `subprocess.run(["node", "-e", runner], env={"DASHBOARD_JS_PATH": ..., "PATH": "/usr/bin:/bin"})` 传了**只有 PATH 的极简环境** → Windows 上 node 初始化加密随机源需要 `SystemRoot`，缺省直接 `Assertion failed: ncrypto::CSPRNG(nullptr, 0)` 崩溃（**rc=134**），`test_load_layout_roundtrip` / `corrupt_json_fallback` / `missing_key_backfilled` / `dedup` 全红；Linux / CI 不受影响（同文件另外 6 例不走 node 子进程，故显示「4 failed, 6 passed」）。实测：不传 `env=` → rc=0；传极简 `env` → rc=134 | ✅ 2026-09-26 新增模块级 `node_env()`：继承 `os.environ` 再叠加 `DASHBOARD_JS_PATH`，4 处调用点统一改为 `env = node_env()`；修复后 `tests/test_dashboard/` = **23 passed**。注：仓库内其余 node 子进程测试（`test_i18n/*` / `test_help/test_modal.py`）本就没传 `env`，故无需改动 |
| 39 | **README「功能拓展路径（V0.74.0 → V0.77.0）」章节（`4685118` 新增）含 10 处文档 vs 代码硬伤**：① `localStorage.pm_dash_layout`（实际 `pm_dashboard_layout`，`static/dashboard.js:25`）② 告警规则 4 个类名错 2 个（`ThresholdRule` / `BandCrossRule` → 实际 `VolatilityRule` / `CrossingRule`，`schemas/alert.py:81/88`）③ 数据健康页误归 V0.74.0（实为 **V0.73.0 N+16**）④ V0.75.0 规划要给 `alert_rules` 加 `user_id`，而它**不是表**（是 `app_settings` 的 JSON key，`services/settings.py:185`）⑤⑥ `portfolios` / `snapshot_overrides` 两张表**凭空捏造**（真实账本表是 `accounts`，全仓 `models/` 无此二表）⑦ 链接把 ux-roadmap 范围写成「V0.74.0 → V0.77.0」，而该文档自身是 **V0.68.0 → V0.75.0** 且无 V0.76/77 章节 → 与其「冲突时以路线图为准」自相矛盾 ⑧ V0.74.0 整版标 ✅ 已落地，与路线图 **🟡 部分落地** 冲突（子项 ③ 打印 CSS + PDF 导出未做），且 V0.76.0 声明的「复用 V0.74.0 打印 CSS」**前提不存在** ⑨「测试覆盖率」小节实为测试规模（仓库**无任何覆盖率工具**）⑩「axe-core 0 critical 守住」但仓库**无任何 axe 文件** | ✅ 2026-09-27 10 处全部修正（另修 `ux-roadmap.md` 头部「适用版本 V0.67.0」陈旧 → V0.74.0）；V0.74.0 表补「打印 CSS + PDF 未落地」行、新增 `🟡 部分落地` 标注档、明确 V0.76/77 为 README 展望不在路线图内。**根因**：本文件的对账是**人工事后补记**，写规划时未做存在性校验 → 建议 `scripts/check_docs_claims.py` 升级为机制门禁（§五 待办） |
| 40 | **`docker multi-stage build` job 不可达（「假绿灯」级缺陷）**：`ci.yml` 的 `on.push` 只声明 `branches: [main]`、**未声明 `tags`**（GitHub 语义：只写 `branches` 时 tag 推送不触发 CI），而该 job 的 `if: startsWith(github.ref, 'refs/tags/v')` 要求 tag ref → 该 job **从未执行过一次**。实证：全仓 **27 个 run 的 `head_branch` 全为 `main`**，该 job 结论**恒为 `skipped`**；V0.72.0 声称的「tag 触发镜像构建 + dry-run 启动验证」一次未跑。排查陷阱：`/commits/<sha>/check-runs` 会连带返回该 commit 在 **main** 上的 run（含 skipped 的 docker job），极易误判为「tag 已触发」——必须核对 run 的 `head_branch` / `event` | ✅ 2026-09-28 **已闭环（首次真实镜像验证成功）**：PAT 更换为含 `workflow` scope 后，`on.push.tags: ['v*']` 与文档门禁步骤随合并提交 `d8f135c` 进入 `main`（分支 `ci/enable-tag-trigger` 亦已推送）。随后打 `v0.74.0` 触发**首次 tag 触发型 CI** —— 实证：推送 tag 后出现 `head_branch=v0.74.0` 的 run（此前全仓 27 个 run 的 `head_branch` 全为 `main`、该 job 恒为 `skipped`），`docker multi-stage build` 从此真实执行。**首轮即暴露 3 处镜像缺陷**（见 #43 / #44），修复后第三轮全绿：`Build (runtime stage)` + `Smoke test` 双 success，容器 **6s 内健康**（`GET /api/v1/health` → 200）。⚠️ 排查陷阱依然有效：`/commits/<sha>/check-runs` 会连带返回该 commit 在 `main` 上的 run（含 skipped 的 docker job），判断是否 tag 触发**必须核对 run 的 `head_branch` / `event`** |
| 41 | **「未验证即声称」类硬伤**（#40 的连带影响面）：① `application-guide.md` 的 P1#3 行把「tag 触发自动构建」标为 **✅ V0.67.0** —— 而该 job 从未执行过（见 #40）；② 「镜像 1.2GB → 280MB」在 **5 处**被当作既成事实陈述（`README.md` 技术栈表、`application-guide.md` 公开部署行、`improvement-path.md` 实施路线表 + P3 #16 验收列、`ux-roadmap.md` V0.72.0 落地注记），但镜像**从未构建过一次**，该数字不可能来自实测，实为 Dockerfile 的设计目标 | ✅ 2026-09-28 已修 4 处「现状陈述」类：`application-guide.md` P1#3（✅ → 🟡 并注明从未生效）、`README.md` 技术栈表、`application-guide.md` 公开部署行、`improvement-path.md` 实施路线表 —— 统一加注「**为设计目标、尚未实测**（CI 镜像构建从未执行）」。另 2 处（`improvement-path.md` P3 #16 验收列 / `ux-roadmap.md` V0.72.0 注记）属**当初规划的目标值**，性质不同，保留原文并在此登记 |
| 42 | **本类硬伤无任何自动化守卫**：文档里的表名 / 文件路径 / 端点 / `localStorage` key / 类名，全部靠人工对账（本文件就是人工事后补记的），故 #39（凭空造表名）、#41（未验证即声称）能长期存活 | ✅ 2026-09-28 新增 `scripts/check_docs_claims.py` 并接入 `make check-docs`：扫描 `README.md` + `docs/*.md` 中的**数据表名 / `localStorage` key / `/static/*.html` 页面 / `/api/v1/*` 端点**做**存在性断言**（表名比对 `models/*.py` 的 `__tablename__`、key 比对 `static/*.js`、页面比对文件系统、端点比对 `app.openapi()['paths']`），查不到即以 `文件:行号` 报错并非零退出；规划项登记于脚本内 `ALLOW`，对账报告 `feature-alignment.md` 整体跳过（它天然引用错误值）。**首跑即抓出 3 处真硬伤**（`central-bank.html` → `central_bank.html`、`pm_theme` → `pm_theme_mode` ×2、`/api/v1/push/unsubscribe` → `subscribe`），均已修正；**负向测试**：临时注入 4 类假声明 → 4 类全部命中、退出码 1，删除后恢复全绿（证明不是「假绿灯」）。✅ **CI 已接入并跑绿**：`Documentation claims gate` 步骤随 `d8f135c` 进入 `main`，py3.11 / py3.12 双矩阵连续三轮 success（每轮校验 287 处文档声明引用） |

---

| 43 | **Docker 镜像的 3 处缺陷（首次真实构建才暴露）**：① **构建直接失败** —— builder 仅 `COPY pyproject.toml README.md` 便执行 `pip install . --target=/install`，而项目是 src-layout（`[tool.setuptools.packages.find] where = ["src"]`），构建后端报 `error in 'egg_base' option: 'src' does not exist or is not a directory`；② **容器内 `PROJECT_ROOT` 错位** —— `config.py` 与 `main.py` 均以 `Path(__file__).resolve().parents[2]` 推导项目根，若 `app` 从 `/install/app` 载入则 `parents[2]` 会解析为 `/`，`static/`、`data/`、`alembic.ini`、`migrations/` 全部指向根目录下不存在的路径（非 root 的 `appuser` 亦无法写 `/`）；③ **运行时缺 `httpx`** —— `services/notify.py` 第 17 行是模块级无保护导入，但 `httpx` 仅声明在 dev extra，生产镜像不含它 → `ImportError`（`market_providers.py` 的导入有 `try/except` 兜底，故只有 notify 是硬失败点） | ✅ 2026-09-28 修复（`8c6f8b2`）：① builder 改为只装依赖（`uv export` 导出清单后 `pip -r`），业务代码由 runtime 以 `/app/src` 提供 —— 既修好构建，又保住「业务代码变更不触发依赖重装」的缓存设计；② `src` 落至 `/app/src` + `PYTHONPATH=/app/src:/install`（业务源码优先），**已用两种目录布局对照实证**（`<root>/app` 正确 / `<root>/install/app` 上推一层）；③ `httpx` 提升为运行时依赖并重跑 `uv lock`。**验证**：第二轮构建 `Build (runtime stage)` = success |
| 44 | **镜像依赖与 `uv.lock` 完全脱钩（容器启动即崩的根因）**：原 Dockerfile 由裸 `pip install` 现场解析版本，实测容器装到 `sqlalchemy 2.1.1`（锁内 `2.0.52`，**次版本跃迁**）、`starlette 1.7.0`（锁 `1.6.0`）、`pandas 3.0.6`（锁 `3.0.5`）、`akshare 1.18.97`（锁 `1.18.94`）、`uvicorn 0.54.0`（锁 `0.52.4`）、`alembic 1.20.0`（锁 `1.19.2`）—— 即镜像内跑的是一套**从未被 CI 测试过**的依赖组合。项目有锁、CI 用 `uv sync --frozen`，唯独镜像绕过了锁。症状：容器启动后立刻退出（`Smoke test` 失败，且因 #45 拿不到日志） | ✅ 2026-09-28 修复（`7c96d82`）：改用 `uv export --frozen --no-dev --no-emit-project --no-hashes` 从 `uv.lock` 导出精确版本再安装，与 CI 的 `uv sync --frozen` 同一口径，确保「CI 测试通过的依赖集」＝「镜像内的依赖集」。**验证**：第三轮构建装到的正是锁内版本（`sqlalchemy-2.0.52` / `starlette-1.6.0` / `pandas-3.0.5` / `akshare-1.18.94`），容器 6s 内健康 |
| 45 | **smoke test 无诊断能力 + 仓库缺 `.dockerignore`**：① 原 smoke test 用 `docker run --rm -d`，容器启动即退出会被连带删除，`docker logs gold-smoke` 只报 `No such container` → **失败时零信息**（初版失败即因此无从定位，只能靠推断）；固定 `sleep 15` 亦无重试、无「提前退出即停」探测。② 仓库无 `.dockerignore`，整个仓库（含本地 `data/gold_etf.db` 与 `server_v*.log`）都被当作构建上下文上传（实测上下文 2.01MB） | ✅ 2026-09-28 修复（`7c96d82`）：① 去掉 `--rm`、`sleep 15` → 轮询至多 120s、容器提前退出即停止等待、无论成败都打印 `docker ps -a` 与容器日志；② 新增 `.dockerignore`（排除清单式，避免误排除 `src` / `static` / `migrations` / `alembic.ini` 等构建必需文件）。**验证**：第三轮 smoke test 输出 `healthcheck OK（第 3 次探测，约 6s）` 并完整打印容器日志 |
| 46 | **前端 3 处功能缺陷全部逃过「门禁全绿」（用户直接碰壁级）**：① **图表实例恒 `undefined`** —— `chart-a11y.js` 的 `ChartA11y.wrapChart` 契约是「给 canvas 打无障碍属性」（只设 aria，**既不 `new Chart()` 也无 `return`**），但 5 处调用方把它当**图表工厂**用并接收返回值（`silver.html` 的对比图与趋势主图、`backtest-chart.js` 的 sharpe / drawdown / calibration）→ 实例恒为 `undefined`，**画布永久空白**；连带 `destroyCharts()` 与 `if (trendChart) trendChart.destroy()` 因拿到 `undefined` 而**长期空转**（内存释放逻辑从未生效）。② **脚本加载时序** —— `backtest.html` 的内联脚本在**解析期**即调用 `window.PM_Backtest.mount()`，而定义它的 `backtest-chart.js` 加载位置在其后 → `TypeError` 中断整段内联脚本，**回测按钮 / 首次自动回测 / 参数变更监听全部从未绑定**（整页交互死掉）。③ **SW 预缓存 3 条 404** —— `sw.js` 的 `SHELL_ASSETS` 含 `/central_bank`、`/backtest`、`/silver`，逐条 curl 实测**均为 404**（真实路径是 `/central-bank`、`/static/backtest.html`、`/static/silver.html`）；`cache.addAll` 是**原子操作**，任一失败整批回滚 → **`SHELL_CACHE` 完全为空**，离线能力等于零（连主题 / i18n 字典 / 离线页都没进缓存）。**共同点：三者全部通过 `check_static_js.py` 的「12 页 + 19 脚本全绿」判定** —— 该门禁只验语法 / 引用 / DOM id，验不了**函数返回值语义**与**脚本加载时序**（见 #47） | ✅ 2026-09-29 修复（V0.74.1）：① 改为 `new Chart(ctx, cfg)` 创建实例后**单独**调 `wrapChart(canvas, {label})` 补 a11y —— 全仓 `new Chart` 实际调用由 6 处增至 **11 处**；② 把 `backtest-chart.js` 的 `<script>` **移到内联脚本之前**（该 IIFE 顶层只做变量声明与函数定义、不查 DOM，而 `mount()` 依赖的 `#runBtn` / `#paramsPanel` 均在更早位置解析完毕）—— ⚠️ 首版仅去掉 `defer` 是**无效**修法：加载位置本就在调用点之后，与 `defer` 无关，靠「模拟 HTML 解析器执行顺序」的验证才抓回来；③ SW 三条 URL 改真实路径，**20 条 URL 全部 200**。**四条独立验证**：`check_static_js.py` 全绿无回归；Node + 最小 DOM 桩执行**真实**代码 → 3 张图实例真实创建、`aria-label` 齐全、二次 `render` 累计创建 6 次证明释放逻辑生效、旧写法残留 **0**；模拟解析器顺序 → 定义（第 6 个）早于调用（第 7 个）；服务端 curl → 页面 200 |
| 47 | **前端「用户可用性」无任何自动化守卫**（#46 的根因面）：`check_static_js.py` 的设计目标是语法 / 引用 / DOM id 校验，故 #46 的三类缺陷 —— **函数返回值语义**、**脚本加载时序**、**SW 预缓存 URL 的有效性** —— **在原理上就不在它的检查范围**：它报「12 页 + 19 脚本全绿」时，用户仍可能点不动按钮、看不到图、离线打不开。另：`sw.js` 的 `SHELL_ASSETS` 是**手工维护的 URL 清单**，无任何断言保证它与服务端真实路由一致（那 3 条 404 正是靠人工失误长期潜伏）；根因之一是**同仓 URL 风格分裂** —— 7 页走 `/portfolio` 这类 RESTful 路由，4 页走 `/static/*.html`，两套并存使手工清单极易写错 | 📋 2026-09-29 登记（**本轮未修**，按「只修 3 个 P0」的范围约定）：建议补 **headless 行为冒烟**（0 未捕获错误 + 关键交互可点 + 图表 canvas 有非空实例）并把 `SHELL_ASSETS` 纳入存在性断言 → 见 §五 待办 |
| 48 | **趋势页 2 处「只在 60 秒轮询后才暴露」的缺陷**（与 #46 同源：静态门禁不验运行时行为）：① **`#badge` 元素丢 id** —— `static/trend.html` 的 `render()` 用 `document.getElementById("badge").outerHTML = '<span class="badge" …>'` 整体替换节点，而新节点**不带 `id`**；页面每 60 秒自动刷新一次，**第二次调用即取到 `null`** → 抛 `Cannot set properties of null (setting 'outerHTML')`，主图面板被 `数据加载失败：…` 整块替换（首屏正常，**静置 1 分钟后才崩**）。② **画布复用未销毁** —— 对照图 / 上海金图直接 `new Chart(canvas, cfg)`，原 `ChartA11y.wrapChart` 只打 aria 属性、**不持有实例**（#46 的残留面），第二次进入即抛 `Canvas is already in use. Chart with ID '0' must be destroyed before the canvas with ID 'compareChart' can be reused` → 图例变「加载失败」。**两者均通过 `check_static_js.py` 全绿**（它查 DOM id 一致性，但查不到「节点被替换后 id 丢失」与「实例未销毁」） | ✅ 2026-09-29 修复（V0.74.2）：① 改为**就地更新**（`badge2` 保留原 `<span id="badge">`、只改 `className` / `style.background` / `textContent`），不再用 `outerHTML` 重建节点；② `loadCompare` / `loadSge` 各持模块级实例变量，重建前**先 `destroy()` 并置 `null`**。**验证方法**（另立技能 `headless-chrome-screenshot`）：headless Chrome `--virtual-time-budget=75000` 快进跨过一次轮询周期后截图 → 两张价格图与主图均完好、控制台无未捕获错误；修复前同法必现上述两处报错 |
| 49 | **`test_no_bom_in_files` 的第二条断言形同虚设（永真）**：`tests/test_i18n/test_i18n_dict.py:78` 写 `assert not text.startswith(b"\ufeff")` —— **bytes 字面量不支持 `\u` 转义**，`b"\ufeff"` 实际得到的是字面量「反斜杠 + u + f + e + f + f」共 6 个字节，任何文件都不会以它开头，故该断言**永远通过**；且 UTF-16 BOM 的字节形态本是 `FF FE`（LE）/ `FE FF`（BE），与 `\ufeff` 无关。Python 仅以 `SyntaxWarning: invalid escape sequence '\u'` 提示，在 727 条用例的输出里几乎不可见（本轮全量回归 `1 warning` 即此条） | ✅ 2026-09-29 修复（V0.74.2）：改为 `assert not text.startswith((b"\xff\xfe", b"\xfe\xff"))` 并加注释说明「bytes 字面量不支持 `\u` 转义」这一坑点。`pytest tests/test_i18n -q` = **58 passed**，`SyntaxWarning` 消失（全量回归的 `1 warning` 归零） |

## 五、后续待办（按优先级）

| 优先级 | 事项 | 估时 | 备注 |
|---|---|---|---|
| 🟡 中 | **补 headless 行为冒烟门禁**（防 #46 同类回归） | 1.5d | #46 的 3 个缺陷全部逃过静态门禁，根因见 #47：门禁只验「代码写对了吗」，不验「用户能用到吗」。需覆盖：① 页面 0 未捕获错误；② 关键交互可点（回测「立即回测」按钮、仪表盘拖拽）；③ 图表 canvas 有**非空**实例（而非只看元素存在）。**若不做，V0.75.0 的三态补齐 / 批量表单改动会以同样方式反复退化** |
| 🟢 已闭环 | 规划 P1 #3 CI/CD（GitHub Actions） | ✅ V0.67.0 | `.github/workflows/ci.yml` 已落地：pytest + ruff + JS 门禁 + Python 3.11/3.12 matrix + uv 缓存 + concurrency 取消旧 PR；P1 三项（CI/CD / 权重配置页 / 多时间框架）已全部闭环 |
| 🟡 中 | P3 #15 邮件/微信推送（需外部 SMTP/Server酱密钥） | 1d | V0.56.0 仅前端侧 |
| 🟡 中 | UX 6.9 Service Worker 离线缓存 | 0.5d | 离线缓存 trend.html + 最近一次行情 |
| 🟢 低 | UX 6.5 剩余项（主题切换 / 标的与区间记忆） | 1d | **多账本与账本记忆 V0.62.0 已落地**；剩余为主题与展示偏好记忆 |
| 🟢 低 | UX 6.7 剩余项（权重参数回测） | 1-2d | 收益曲线 V0.61.0 + 指数曲线 V0.63.0 + 周/月线 V0.64.0 均已落地；**仅剩权重参数回测**，依赖回测引擎（P3 #13） |
| 🟡 中 | 复盘统计样本积累（V0.66.0 能力已就绪） | 持续 | 金价回填受行情源限制最深约 60 个交易日（2026-06-25 起）；统计页在样本 <20 天前标注「仅供参考」；补录样本按设计**不计入**命中率 |
| 🟢 已闭环 | **工程路线 §三·五 + UX 路线双视图** | ✅ 2026-09-18 | 新增 [`docs/ux-roadmap.md`](ux-roadmap.md) —— 面向应用能力 + 用户体验的下一阶段路线（V0.68.0 → V0.75.0，8 版本）；与 [`improvement-path.md §三·五`](improvement-path.md) 工程路线（CI / 可观测 / 部署）形成「应用 vs 工程」双视图；重叠版本（V0.68.0 / V0.69.0 / V0.71.0 / V0.72.0）在两文档 cross-link；仅 UX 视角独有的 4 版（V0.70.0 共振卡片 / V0.73.0 i18n / V0.74.0 仪表盘自定义 / V0.75.0 多用户登录）填补 §三·五 空白 |
| 🟢 已闭环 | **UX 路线 V0.68.0 启动版（导航 + 搜索 + 埋点）落地** | ✅ 2026-09-18 | V0.68.0 实际交付 UX 路线第一版（而非原 §三·五 计划的 Prometheus + SW + 一致性 + 性能基准）—— 决策原因已在 `improvement-path.md §三·五 V0.68.0` 顶部标注；原计划项顺延到 V0.68.1 微版本或 V0.69.0 合并；UX 6.13 由 📋 升 ✅ |

---

## 六、对账方法

每发版一次（新 V0.X.0 推送 GitHub 后），跑一次本对账：

```bash
# 1. 跑全量测试，确认实际用例数
python -m pytest --collect-only -q 2>&1 | tail -1

# 2. 扫 README 与 docs 声明的测试数
grep -rn "测试\|用例" README.md docs/*.md | grep -E "测试|用例"

# 3. 扫版本号一致性
grep -rnE "V0\.\d+\.\d+" README.md docs/*.md

# 4. 检查功能清单 vs 实际 endpoint（用 openapi.json 自动对账，比人工翻 endpoint 目录更准）
python - <<'PY'
import json, re, urllib.request
d = json.load(urllib.request.urlopen("http://127.0.0.1:8888/openapi.json"))
api = {re.sub(r"\{[^}]+\}", "{}", p) for p in d["paths"]}
doc = open("docs/application-guide.md", encoding="utf-8").read()
sec = doc[doc.index("## 5. API 参考"):doc.index("### 5.1")]
docp = {re.sub(r"\{[^}]+\}", "{}", p) for p in re.findall(r"`(/[A-Za-z0-9_\-{}/\.]*)`", sec)}
print("openapi 有、文档缺：", sorted(api - docp) or "无")
PY

# 5. 前端门禁
python scripts/check_static_js.py
```

### 端到端验证清单（V0.62.1 起纳入）

文档与接口对账只能证明「声明一致」，证明不了「行为正确」。涉及资金口径的改动，
必须再跑一次**写路径端到端验证**——用临时实例 + 独立临时库，不触碰正式数据：

```bash
# 起临时实例（mock 行情源，零网络；独立库避免污染 data/gold_etf.db）
DATABASE_URL="sqlite+aiosqlite:///./data/verify_tmp.db" \
MARKET_PROVIDER=mock \
python -m uvicorn app.main:app --host 127.0.0.1 --port 8899
```

覆盖要点（V0.62.1 实测 47 项断言全绿）：

| # | 场景 | 期望 |
|---|------|------|
| 1 | 空库启动 | 自动创建 id=1「默认账户」，不报错 |
| 2 | 新建 / 重名 / 改名冲突 | 201 / 400 / 400 |
| 3 | 均价法回放（买 1000@10 + 买 1000@9 + 卖 500@11，费 3） | 已实现盈亏 = **747**，成交后份额 = **1500** |
| 4 | **成交日晚于行情序列末日** | 不得丢弃；本金 / 已实现盈亏 / 胜率仍正确 |
| 5 | 带 `side=sell` 筛选 | 回放上下文保留，盈亏不为空（双次取数回归） |
| 6 | 账本隔离 | A 账本交易不出现在默认账本；不传 `account_id` = 合并视图 |
| 7 | 口径自洽 | `sell_count == closed_trades`（V0.62.1 起纳入断言） |
| 8 | CSV 导出 | BOM + 表头 + N 行成交 + `# 汇总` 块 |
| 9 | 归档约束 | 默认账本不可归档；有未平仓持仓不可归档；清仓后可归档可恢复 |
| 10 | 参数校验 | 非法 `side` / `start>end` → 422；账本不存在 → 404 |

> 真实数据（`data/gold_etf.db`）只做**只读**冒烟，写路径一律走临时库。
