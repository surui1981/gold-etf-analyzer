# 功能对账报告 · README ↔ 代码 ↔ 文档

> 生成日期：2026-09-16 ｜ 适用版本：**V0.67.0**
> 目的：定期核对 README 功能清单、实际代码实现、文档声明三方的落地状态，标记 ✅ 已落实 / ⚠️ 半成品 / 📋 待办，避免文档漂移。

---

## 一、README 功能清单 vs 代码实际（截至 V0.66.0）

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
| **行情源 provider 可切换** | `MARKET_PROVIDER=.env` 配置（akshare / mock / eastmoney_only / sina_only） | ✅（V0.59.0） |
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

**测试数对账**：`pytest --collect-only -q` = **454 用例 / 38 个测试模块**。纵向演变：V0.64.0 = 397 → **V0.65.0 = 410**（新增 `test_api/test_news_api.py` 7 例 + 重写 `test_news_service.py` 5 → 11 例，净 +13）→ **V0.66.0 = 432**（新增 `test_services/test_review_service.py` 13 例 + `test_api/test_review_api.py` 9 例，净 +22）→ **V0.67.0 = 454**（新增 `test_middleware/test_trace_id.py` 8 例 + `test_services/test_price_calendar_validation.py` 12 例 + `test_utils/test_logger_trace_id.py` 2 例，净 +22）。

**V0.67.0 回归实测**：① 离线 `python -m pytest -q --ignore=tests/test_services/test_irfcl_fetcher.py --ignore=tests/test_services/test_h15_fetcher.py`（排除 2 个联网 fetcher 文件共 **44** 用例）= **410 passed / 0 failed**（2m32s）；② `ruff check src tests` = **All checks passed**；③ `ruff format --check src tests` = **128 files already formatted**；④ `python scripts/check_static_js.py` = **7 静态页 + 3 共享脚本全部通过**（语法 / 引用 / DOM id）。

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

---

## 五、后续待办（按优先级）

| 优先级 | 事项 | 估时 | 备注 |
|---|---|---|---|
| 🟢 已闭环 | 规划 P1 #3 CI/CD（GitHub Actions） | ✅ V0.67.0 | `.github/workflows/ci.yml` 已落地：pytest + ruff + JS 门禁 + Python 3.11/3.12 matrix + uv 缓存 + concurrency 取消旧 PR；P1 三项（CI/CD / 权重配置页 / 多时间框架）已全部闭环 |
| 🟡 中 | P3 #15 邮件/微信推送（需外部 SMTP/Server酱密钥） | 1d | V0.56.0 仅前端侧 |
| 🟡 中 | UX 6.9 Service Worker 离线缓存 | 0.5d | 离线缓存 trend.html + 最近一次行情 |
| 🟢 低 | UX 6.5 剩余项（主题切换 / 标的与区间记忆） | 1d | **多账本与账本记忆 V0.62.0 已落地**；剩余为主题与展示偏好记忆 |
| 🟢 低 | UX 6.7 剩余项（权重参数回测） | 1-2d | 收益曲线 V0.61.0 + 指数曲线 V0.63.0 + 周/月线 V0.64.0 均已落地；**仅剩权重参数回测**，依赖回测引擎（P3 #13） |
| 🟡 中 | 复盘统计样本积累（V0.66.0 能力已就绪） | 持续 | 金价回填受行情源限制最深约 60 个交易日（2026-06-25 起）；统计页在样本 <20 天前标注「仅供参考」；补录样本按设计**不计入**命中率 |
| 🟢 已闭环 | **工程路线 §三·五 + UX 路线双视图** | ✅ 2026-09-18 | 新增 [`docs/ux-roadmap.md`](ux-roadmap.md) —— 面向应用能力 + 用户体验的下一阶段路线（V0.68.0 → V0.75.0，8 版本）；与 [`improvement-path.md §三·五`](improvement-path.md) 工程路线（CI / 可观测 / 部署）形成「应用 vs 工程」双视图；重叠版本（V0.68.0 / V0.69.0 / V0.71.0 / V0.72.0）在两文档 cross-link；仅 UX 视角独有的 4 版（V0.70.0 共振卡片 / V0.73.0 i18n / V0.74.0 仪表盘自定义 / V0.75.0 多用户登录）填补 §三·五 空白 |

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
