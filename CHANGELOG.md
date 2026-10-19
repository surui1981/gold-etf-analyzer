# Changelog

> 黄金 ETF 投资辅助 · 完整发版历史
>
> 详细 release notes 见 [docs/releases/](docs/releases/) 系列
>
> 能力 × 版本对照（"哪个能力在哪个版本落地"）见 [docs/releases/index.md](docs/releases/index.md)

本项目遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/) 与 [Conventional Commits](https://www.conventionalcommits.org/zh-hans/) 规范。

---

## [Unreleased]

### Added

- 📰 **今日要闻**（readhub 财经新闻流） —— 6 commit

  - 🗄️ `news_feed_items` 表 + alembic 迁移（V0.102 m9g0a1b2c3，down_revision=l8f9a0b1c2 ai_chat）；单表 + 5 索引（site_name / language / publish_date / fetched_at + 唯一 external_id）；`external_id` 整型 UNIQUE → dedup 主键
  - 🏗️ ORM 模型 `NewsFeedItem` + `NewsFeedRepository`（4 维查询：days / site_name / language / limit；批量 upsert 走 `sqlite_insert().on_conflict_do_update(index_elements=['external_id'])`）
  - 🌐 `readhub` fetcher（httpx async + 30s timeout + 1 次重试，5min 进程内 cache 避免 scheduler 与手动 refresh 撞车；`_normalize` 缺关键字段自动 drop；`NewsFeedService.refresh()` 失败仅日志 + `ok=False`，不抛异常走 V0.84 保留末次 UX）
  - 🔌 5 REST 端点：`GET /api/v1/news-feed/{items,sites,languages,status}` + `POST /refresh`（admin 守卫，单用户模式自动豁免）
  - ⏰ 6h 调度器（`news_feed_loop` 启动 30s 立即抓 + 00/06/12/18 UTC 4 触发点 ≈ 08/14/20/02 BJT；`NEWS_FEED_AUTO_REFRESH` env 开关，默认启用）
  - 🖥️ `/headlines` 静态页（headlines.html + headlines.js，silver 模式拆分；3 chip 顶栏：last_refresh + total + 24h；工具栏 时间/来源/语种 下拉；BJT 日分组卡片；新 tab 跳原文）+ 3 语 i18n 21 keys + topnav 接入「情报」第 4 子页
  - 🧪 22 测试 + 4 门禁同步（`check_routes` 16→17 alias，`check_pwa_assets` SHELL_ASSETS +3 条，`check_i18n_keys` V083_KEY_PREFIXES + `headlines.`，`test_main_app` ROOT_ALIASES 15→16）

- ⭐ **我的收藏**（今日要闻「收藏 / 永久存储 / 档案管理」）—— 7 commit / V0.103 正式发版

  - 🗄️ `user_news_favorites` 表 + alembic 迁移（V0.103 n0a1b2c3d4，down_revision=m9g0a1b2c3 V0.102）；单表 + 16 字段（11 快照 + 3 user_meta + 2 timestamp）；`UNIQUE(news_external_id, news_source)` dedup 主键 + 3 索引（archived_at 倒序 / (importance, archived_at) 复合 / site_name）
  - 🏗️ ORM `UserNewsFavorite` + `UserNewsFavoriteRepository`（CRUD + 6 维 list：days / site_name / tag LIKE 模式 / importance_min / sort=recent|importance|publish + 分页；3 聚合：list_sites / list_tags 字母序 / get_status 6 维）
  - 🛠️ `UserNewsFavoriteService` 编排（_normalize_tags 去重 + 字母序；add 时优先从 `news_feed_items` 回填快照保证与 readhub 一致，外部 URL 收藏走客户端直传；`DuplicateFavoriteError` → 409）+ 5 Pydantic schema（ItemOut 16 字段 / CreateIn 12 字段 / UpdateIn 3 字段 / ListOut / StatusOut 6 维）
  - 🔌 9 REST 端点：`GET /api/v1/favorites/{items,items/{id},sites,tags,stats,exists/{ext}}` + `POST /items` + `PATCH /items/{id}` + `DELETE /items/{id}`（POST/PATCH/DELETE 走 `Depends(require_user)`，单用户模式自动回退 LEGACY_USER，V0.97.0 hotfix 防 401）
  - 🖥️ `/favorites` 档案管理页（fork headlines.html；toolbar：时间 4 段 / 来源 / 标签 / 重要度 / 排序；4 status chip：总数 / ★3 / 7d / 来源站；主列表：卡片含重要度徽章 + tag chip + inline 笔记 + 重要度升降 + 取消收藏；280px stats 侧栏：5 卡（重要度 / 标签 / 来源 / 月度 / KPI））+ 3 语 i18n 47 keys + topnav intel 第 5 子页
  - 🔗 `/headlines` 与 `/home` 每条新闻加 `⭐ 收藏` 按钮（POST → toast；409 = 幂等；初次渲染 GET /exists/{ext} 并发检查）
  - 🧪 仓储 18 例 + API 22 例 + 单用户回退端到端 1 例（`test_favorites_endpoint_works_in_single_user_mode`）+ 4 门禁同步（`check_routes` 17→18 alias，`check_pwa_assets` SHELL_ASSETS +3 条，`check_i18n_keys` V083_KEY_PREFIXES + `favorites.`，`test_main_app` ROOT_ALIASES 16→17）

### Fixed

- 🔧 **V0.100.1 hotfix · home.html 今日要闻不显示新闻标题** —— 旧 SW 缓存里 home.html 仍是 news-score 版（含 score 字段），用户报告「没显示新闻标题 / 不要分值」

  - 根因：`static/sw.js` VERSION 卡在 `v0.100.0`，但 home.html / home.js 已在 bfeb39f 改 readhub 流；activate 阶段按 cache name `gold-shell-v0.100.0` / `gold-runtime-v0.100.0` 不清旧 cache，浏览器持续回放 stale 入口（cache-first 命中 `RUNTIME_CACHE` 旧 `/home` 307 + 旧 `/static/home.html`）
  - 修复：`__version__` / `pyproject.toml` / `sw.js VERSION` 同步 bump `v0.100.1`（4 处版本同步门禁，参照 V0.100.0 release notes 第 105-111 行清单）；activate 阶段新增 `/home` + `/static/home.html` 的 `RUNTIME_CACHE` stale 清理（套 V0.92.0 `/scoring` 同模式）；新增 `pwa_assets` 门禁必跑
- 🔧 **V0.100.2 hotfix · home.html 今日要闻 Top 5 → Top 20** —— 用户要求首页显示更多新闻

  - 改动：`static/home.js` `limit=5` → `limit=20`、`slice(0, 5)` → `slice(0, 20)`；`static/home.html` 3 骨架 → 5 骨架（视觉占位）
  - 4 处版本同步 bump 到 `v0.100.2`（按 V0.100.1 沉淀的「改 static 必须 bump」教训，参见 memory `v01001-sw-bump-on-static-change`）

---

## [V0.100.0] · 2026-10-18

`消息面未打分 → 综合指数 pending` — 5 件大项 / 5 个 commit

### Added

- ⏳ 综合指数 pending chip（trend.html + silver.html）—— 消息面未打分时数字降级透明度 0.55 + 「▲ 消息面 pending」chip（复用 freshness.js fsh-warn 样式） — **C3 + C4 ✅**
- 🏷️ NewsIndexOut.pending_reason 字段（中文「今日尚未打分（消息面不参与综合指数）」） — **C1 ✅**
- 🌐 i18n +6 trend.* key × 3 语 = 18 条翻译（pending_chip / pending_tooltip / news_unscored_label / news_unscored_chip / news_pending_hint / combined_pending_news） — **C3 ✅**

### Changed

- 🔄 NewsScoreOut.score / direction：`float` → `float | None`（未打分时 None，替代中性 50 兜底） — **C1 ✅**
- 🔄 NewsIndexOut.score：`float` → `float | None` + 新增 pending_reason — **C1 ✅**
- ♻️ aggregate_slots()：records=[] 返回 `(None, "", False)`（替代 NEUTRAL_SCORE 兜底） — **C1 ✅**
- 📊 综合指数文案分支：`if set(dropped) == {"news"}` → 「消息面未打分，综合指数待定」pending 表述；多面被剔时沿用通用「不可用」 — **C2 ✅**
- 🛠️ snapshot.py news=None 兜底 50.0（DB NOT NULL；配合 macro_detail JSON 保持审计追溯） — **C2 ✅**

### Fixed

- 🐛 后端综合指数不再被「未打分消息面」以中性 50 稀释（剔整面归一化后 macro 自动按 0.4/0.7=57.1% 加权） — **C2 ✅**
- 🐛 test_main_app.ROOT_ALIASES 13 → 15 同步（V0.97.0 /ask + V0.98 /home 后预存漂移） — **C5 ✅**
- 🐛 check_routes / check_routes_test 3 处硬断言同步（14/13/16 → 16/15/18） — **C5 ✅**

### Discipline

- 「剔整面 + 归一化」算法（trend.py:517-524）**保留不动**（V0.78.0 Step D 实测覆盖）
- 既有 `combined is None` 防御分支仍保留（unreachable 兜底）
- `#idxMethod` 运算方法描述**不变**（×30% + ×40% + ×30% 公式维持口径；pending 仅 chip + summary 披露）

[详情](docs/releases/v0.100.0.md)

---

## [V0.99.0] · 2026-10-18

`白银数据修复 + SGE 上海银跟踪 + 页面重构` — 6 件大项 / 6 个 commit

### Added

- 🥈 SGE 上海银基准价 2 端点（`/silver/sge-quote` + `/silver/sge-trend`，CNY/kg） — **C3 ✅**
- 📊 白银页 3-market 视角：ETF（562800）+ NY SI + SGE Ag99.99，5 张卡渲染 — **C5 ✅**
- 📐 多市场升贴水表（以 SGE 为锚；ETF × 1000 / NY × 31.1035 × 7.1 / SGE 0%） — **C5 ✅**
- 🔀 主图市场选择器（3 market-btn：ETF / NY / SGE） + SGE-only 收盘价曲线 — **C5 ✅**
- 🌐 SGE 端点 schema：SilverSgeQuoteOut / SilverSgeTrendOut / SilverSgeTrendMetrics — **C3 ✅**
- 🔄 AkshareSgeSilverHistoryProvider（ak.spot_silver_benchmark_sge，1700+ 行历史） — **C2 ✅**
- 🏷️ SilverQuote.data_source_note 字段：eastmoney 失败时显示「LOF 代理」备注 — **C1 ✅**

### Changed

- ♻️ silver.html 655 行 → silver.html 332 行 + silver.js 445 行（IIFE 包装 + 7 模块函数 + DOMContentLoaded 入口） — **C4 ✅**
- 📊 562800 ETF 历史 K 线：em→sina sz161226（白银基金 LOF）双源降级，与 518880 黄金 ETF 对齐 — **C1 ✅**
- 🎨 headline 标题改 3-market（headline_title_3market） — **C5 ✅**
- 🏷️ sw.js SHELL_ASSETS 加 `/static/silver.js` — **C4 ✅**
- 🌐 i18n +12 silver.* keys × 3 langs = 36 条翻译 — **C5 ✅**

### Fixed

- 🐛 562800 ETF 历史 K 线静默走 mock（eastmoney `RemoteDisconnected`）→ em+sina 双源 — **C1 ✅**
- 🐛 silver.js TDZ bug（`techComposeBadge` 在使用之后才声明） — **C4 修**
- 🐛 renderMain 漏传 market 参数导致切 SGE 抛 `ReferenceError: market is not defined` — **C5 修**
- 🐛 SGE klines 无 ma5/ma20/ma40 字段 → hasMA 守卫只画 1 条收盘价 — **C5 修**

[详情](docs/releases/v0.99.0.md)

---

`体验重塑 + 结构清偿` — 7 件大项 / 11 个 commit

### Added

- 🏠 场景化首页（/home）— 5 大场景卡（决策 / 持仓 / 情报 / 配置 / AI） — **C4 ✅**
- ⚡ /ask SSE 流式响应（`/api/v1/ai/conversations/{id}/messages/stream`） — **C5 ✅**
- 🔗 URL 状态化（6 页）+ 跨页链接器 + 跨 tab 同步 — **C6 ✅**
- 📦 全局 toast 系统（`window.PM_Toast`）+ 断网检测 — **C3 ✅**
- 📥 PWA 安装体验完善（`appinstalled` 监听 + iOS 引导 + 7 天 TTL + manifest 完善） — **C3 ✅**
- 🧭 双层导航 7 顶场景 + 4 子场景 sub-tabs（首页/决策/持仓/情报/配置/AI/健康） — **C7 ✅**
- 📚 CHANGELOG.md + docs/releases 索引 — **C1 ✅**

### Changed

- ♻️ `ai_chat.py` 428 行 → 4 文件拆分（service / prompts / serializers / proxy_fallbacks） — **C2 ✅**
- 🏠 主页布局对齐 `.wrap` + `.hero` 标准模式（commit `94adce4`）
- 🏠 topnav 「🏠 首页」tab 加在最前

### Dependencies

- `+ sse-starlette ^2.0.0`（SSE 流式依赖） — **C5 ✅**

### Fixed

- 🐛 home 新闻加载失败（端点 URL 修正 `/api/v1/news-score/history`） — **C4 hotfix `83a0025`**
- 🐛 home topnav mount 缺失（占位符 → `<div id="topnav-mount">`） — **C4 hotfix `83a0025`**
- 🐛 home topnav CSS 缺失（字体/链接与其他业务页对齐） — **C4 hotfix `7434cda`**
- 🐛 nav-drawer.js:117 `insertBefore` 抛 NotFoundError（pre-existing，`.links` 是 `.topnav-row` 子节点） — **C7 顺手修**

[详情](docs/releases/v0.98.0.md)

---

---

## [V0.97.2 hotfix] · 2026-10-17

`miniMax 代理 2013 三级降级兜底` — tool_result inline 重试 + fresh-only 兜底

- **3 级降级链路**：L1 内联 tool_result 转纯文本 + tools=None 重试；L2 同时把上一条 assistant 的 tool_use 块也转纯文本（在 L1 内完成）；L3 只发用户原问题不传历史
- `_inline_tool_results_as_text()` 增强：除 user 消息的 tool_result blocks，还把前一条 assistant 消息的 tool_use blocks 转为 `[Called name with {input}]` 纯文本，彻底平铺对话
- `send_message()` LLMError 兜底重写为 3 级链：「失败 → L1 inlined tools=None → 仍 2013 → L3 fresh-only → 仍失败才抛」
- 新增测试 `test_tool_result_fallback_l1_also_2013_falls_to_l3_fresh_only`（mock 4 次 LLM 调用）
- 不 bump 版本号，按 `sw-version-sync-gate` 不需要 SW 缓存重建

[详情](docs/releases/v0.97.2-hotfix.md)

---

## [V0.97.2] · 2026-10-17

`/ask 页面布局修复（视口感知 + welcome 卡片）` — 纯前端 CSS + HTML + JS

- 视口感知 flex 三层链布局：`body` → `.wrap` → `.ask-layout(grid)`，所有层级 `min-height: 0` 让 `.message-stream` 可滚动
- 2 栏默认 / 3 栏按需：`grid-template-columns: 240px minmax(0, 1fr)` 默认，`.has-tools` 时切到 `240px minmax(0, 1fr) 280px`
- Welcome 卡片（5 个示例 chip：市场概览 / 持仓 / 命中率 / 风险 / 资金流）替换旧 `empty_state` 文案
- 输入栏微优化：textarea `title="Enter 发送 · Shift+Enter 换行"`、`max-height: 120px`、字数提示 `N / 8000`（>2000 显示，>8000 变红）
- i18n `ai.*` 新增 12 keys × 3 语（empty_title / empty_desc / example_market / _q 等）
- 4 处版本同步：pyproject / `__init__.py` / `sw.js` / `docs/releases/v0.97.2.md`
- 设计纪律：不引依赖、不动后端、不动 DB schema、SHELL_ASSETS 35 条不变

[详情](docs/releases/v0.97.2.md)

---

## [V0.97.1] · 2026-10-XX

`AI 智能分析页 UI hotfix` — 工具调用展示 + 数据来源可验证

- Tool name 中文化 + emoji 标签（`TOOL_LABELS` 字典）：`get_market_overview` → 📈 市场概览 等 5 项
- Tool 输入摘要（`summarizeInput`）：按 tool 白名单抽取关键参数（日期范围 / N / 未知 tool 截断 100 字符）
- Tool 结果摘要（`summarizeResult`）：按 tool 白名单抽取核心数据（1-2 行可读，未知 tool 截断 200 字符）
- 聊天流调整：assistant tool_use 消息不再 spinner 永久，显示「🔧 📈 市场概览」chip；tool 结果用折叠 `<details>` 默收
- 最终 assistant 末尾追加「📊 基于 N 个工具调用 · 右侧查看详情」chip（虚线边框）
- 右侧 trace 面板重做：工具名 + 角色 chip（`→ 调用` / `← 结果`）+ 参数摘要 + 结果摘要 + 折叠原始 JSON
- 4 处版本同步：pyproject / `__init__.py` / sw.js（v0.97.1 + SHELL_ASSETS 加 ask.js）/ docs
- 门禁：check_pwa_assets 33→35 SHELL_ASSETS / check_routes 14→15 alias（/ask）

[详情](docs/releases/v0.97.1.md)

---

## [V0.97.0] · 2026-10-XX

`AI 智能分析页 (/ask)` — 多轮对话 + 5 个只读 tool

- **数据层**：2 张新表（`ai_conversations` / `ai_messages`）+ alembic 迁移 `l8f9a0b1c2` + 4 索引；2 个仓储（`AIConversationRepository` 6 方法 + `AIMessageRepository` 6 方法）
- **服务层**：`ClaudeClient` httpx 直调 Anthropic Messages API（重试退避 2.0/5.0/15.0 + 仅 429/5xx）+ `ToolDispatcher` 5 个只读 tool（get_market_overview / get_scoring_summary / get_user_portfolio / get_warning_summary / get_etf_recent_flows）
- **`AIChatService`**：多轮 tool_use 循环（硬上限 3 轮，命中 end_turn 即停）+ 8000 字符 prompt injection 防护 + LLM 异常时 `msg.delete(user_msg.id)` 失败回滚
- **6 端点**：`GET /health` / `POST /conversations` / `GET /conversations` / `GET /conversations/{id}` / `PATCH/DELETE /conversations/{id}` / `POST /conversations/{id}/messages`
- **`PerUserRateLimitMiddleware`**：per-user 60s 滑动窗口（默认 30 req/min）+ 每日 token 配额（默认 100k/天）
- **前端 3 pane chat UI**：左 240px 对话列表 + 中 flex 消息流 + 右 280px tool trace；marked v12 markdown 解析 + 自写 XSS 清洗
- **i18n**：新增 `ai.*` 36 keys + `nav.ask` × 3 语（zh-CN / en-US / zh-TW）
- **测试**：22 例（service 5 + LLM 6 + endpoint 11）；4 处版本同步清单 + check_pwa_assets / check_routes 门禁

[详情](docs/releases/v0.97.0.md)

---

## [V0.96.0] · 2026-09-XX

`scoring「命中分析」Tab` + 4 horizon 柱状图 + 3 mini card

- 新端点 `GET /api/v1/scoring/hit-stats-all`（不改动 `scoring_daily_wide` 宽表）—— 1 次 fetch 拿 4 horizon (t0/t1/t3/t5) by_month + 3 mini card
- 新 schema：`ScoringHitStatsAllOut`（顶层）+ `ScoringHitStatsAllHorizon`（by_month）+ `ScoringHitStatsAllMiniCard`（30d / mom / best）
- 新 mini card helper `_compute_mini_card()`：最近 30 ready 日 vs 上 30 ready 日 + 最佳 horizon（多 horizon 同分取字典序最小）
- 第 3 Tab「命中分析」panel：canvas#hitChart（Chart.js bar type，4 dataset 4 色叠加）+ 3 mini card（最近 30 天 / 同比上月 / 最佳 horizon）
- 4 色 chart palette：t0=amber / t1=blue / t3=violet / t5=green（避开 V0.92.1 红绿）
- 排序：x 轴按月份降序（V0.95.1 降序约定 · 最近→远期自上而下）
- i18n 新增 9 keys × 3 语（tab_hit / hit_chart_title / hit_mini_30d 等）
- 4 处版本同步：pyproject / `__init__.py` / sw.js（v0.96.0）/ docs
- 旧 `GET /hit-stats?horizon=tN` 单 horizon 端点保留向后兼容

[详情](docs/releases/v0.96.0.md)

---

## [V0.95.1] · 2026-09-XX

`scoring 4 指数时序桶排序降序` — 最近→远期自上而下

- `summary()` 桶迭代 `sorted(...)` → `sorted(..., reverse=True)`（line 282）
- `hit_stats().by_month` 桶迭代同上（line 392）
- **多视图一致性**：日历视图（renderCalendar 早就是 `.reverse()` 倒序 line 328），主表与日历排序方向统一
- **period 字符串设计**：day=`YYYY-MM-DD` / week=`YYYY-Wxx` / month=`YYYY-MM` 都是字典序 == 时间序，`reverse=True` 即可无需自定义 comparator
- puppeteer 视觉确认：4 指数时序表自上而下从 2026-10-14 排到 2026-09-07
- 门禁：check_routes.py 14 OK / check_pwa_assets v0.92.0 OK / check_static_js 17+30 OK
- commit `2e956d3`
- **注**：本版未发版本号（V0.92.0 维护线无 sw.js VERSION 改动需求）

[详情](docs/releases/v0.95.1.md)

---

## [V0.94.0] · 2026-09-XX

`scoring 预测评估卡` — 顶部 verdict card（方向 + 置信度 + 4 horizon 状态）

- 顶部 verdict card：方向（看多 / 看空 / 中性）+ 置信度（high / medium / low）+ 4 horizon（t0/t1/t3/t5）ready/pending/missing
- 一句话 summary（首段自然语言结论）
- 跟随 toDate 联动（顶部日期 picker 变化时 verdict card 重渲染）
- 与 V0.96.0 第 3 Tab「命中分析」功能不重叠（verdict 是当日决策摘要 + tab 是时序走势）
- i18n 新增 verdict 相关 keys × 3 语
- 门禁：check_routes / check_pwa_assets / check_i18n_keys 全过

[详情](docs/releases/v0.94.0.md)

---

## [V0.93.0] · 2026-09-XX

`scoring T+0 outcome` — 当日 close vs 上一交易日 close

- 基准：当日 close vs 上一交易日 close（`gold_price_daily.latest_before(target, date)` 自动处理节假日/周末）
- DB 字段：`scoring_daily_wide.actual_change_pct_t0 FLOAT` / `hit_t0 BOOLEAN`（nullable，老行 NULL=pending）
- migration `j6d7e8f9a0b1` 仅 `add_column`，老行 `hit_t0=NULL` = pending；历史回填用 `backfill_scoring_wide`
- horizon 枚举扩为 `^(t0|t1|t3|t5)$`（endpoint Query pattern + service ValueError 校验）
- `hit_col` dict 加 `0: "hit_t0"`，UI 列全显（顺序：t0 / t1 / t3 / t5，默认仍 t1）
- **纪律**：T+0 含打分时刻已发生的盘内信息，**不**用于评估「预测能力」，仅作快速 sanity check
- `ScoringWideRepository.upsert` 字段白名单加 `actual_change_pct_t0` / `hit_t0`（V0.79.0 #162 教训）

[详情](docs/releases/v0.93.0.md)

---

## [V0.92.1] · 2026-08-XX

`scoring 命中筛选` — 行级 filter（全部 / 是 / 否）+ 「是」用红色

- API 契约 `GET /api/v1/scoring/summary` 新增 `hit`（all / yes / no，默认 all）+ `horizon`（默认 t1）
- 服务端按 `hit_t{horizon}` 在**行级**过滤后再分桶（pending 行被 `yes`/`no` 排除；`all` 保留）
- 默认值改动：`groupBy=month` → `groupBy=day`，`horizon=t5` → `horizon=t1`
- 「是」色 = **红色 `#dc2626`**（用户语义覆盖：常规红=坏，这里红=命中；以后 scoring 页「是」都用此色）
- 「否」色 = 绿色 `#16a34a`（语义化）
- 「待定」色 = `var(--muted)` 灰（pending：等待 T+1/T+3/T+5 就绪）
- `ScoringSummaryBucket` 新增 `hit: bool | None` 字段 —— 仅 `group_by=day` 且桶内恰 1 行时承载
- i18n 新增 8 keys × 3 语（hit_filter / hit_filter_all/yes/no / hit_col / hit_col_yes/no/pending）

[详情](docs/releases/v0.92.1.md)

---

## [V0.92.0] · 2026-08-XX

`维护线 + 多项修复` — scoring 物化宽表 + 汇总页 + 多项 hotfix

- **`scoring_daily_wide` 物化宽表**（migration `i5d6e7f8a9b0`）：1 行/日，4 指数 + 消息面聚合 + 复盘 outcomes + basis_tags JSON，26 列 + 3 索引，写时 hook ETL
- **5 端点**：`/summary`（按 day/week/month 聚合）/ `/by-date/{date}` / `/hit-stats`（按 horizon + by_direction + by_month + calibration）/ `/by-tag`（basis_tag 维度）/ `/rebuild/{date}`（手动重算）
- **`/scoring` 汇总页** —— 双 Tab：日历视图（每日 4 指数热力图）+ 表格视图（4 指数时间序列 + basis_tag 频次 + 命中率）
- **`backfill_scoring_wide.py` CLI** —— 一次性历史回填（默认从 V0.66.0 上线日 2024-09-01 起）
- 跨日历史查询路径性能：6 个 history 端点 JOIN 4-6 表（100-300ms/次）→ 宽表 O(天数) 直查（<10ms/次）
- 业务页 9 → 10（+ /scoring），RESTful alias 12 → 13
- 端点 28 → 33（+ 5 端点），维护线覆盖率 90%+

[详情](docs/releases/v0.92.0.md)

---

[Unreleased]: https://example.com/compare/v0.99.0...HEAD
[V0.99.0]: docs/releases/v0.99.0.md
[V0.98.0]: docs/releases/v0.98.0.md
[V0.97.2 hotfix]: docs/releases/v0.97.2-hotfix.md
[V0.97.2]: docs/releases/v0.97.2.md
[V0.97.1]: docs/releases/v0.97.1.md
[V0.97.0]: docs/releases/v0.97.0.md
[V0.96.0]: docs/releases/v0.96.0.md
[V0.95.1]: docs/releases/v0.95.1.md
[V0.94.0]: docs/releases/v0.94.0.md
[V0.93.0]: docs/releases/v0.93.0.md
[V0.92.1]: docs/releases/v0.92.1.md
[V0.92.0]: docs/releases/v0.92.0.md
