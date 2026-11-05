# M2 · AI 与多市场（V0.96 – V0.99）

> **发版区间**：V0.96.0 – V0.99.0（7 个版本）｜ **状态**：归档（历史里程碑）
> **本文件定位**：把该区间的 7 份 release notes 合并成一条**可读的演进脉络**。
> **逐版原始全文**在 git 历史里（tag 与原文件名同名）：`git show v0.99.0:docs/releases/v0.99.0.md`

## 〇 一页结论

1. **这一阶段的主线是「让数字可被追问」**。V0.96.0 先把 scoring 的命中率从「一段文字」变成 4 horizon 时序图 + 3 mini card；紧接着 V0.97.0 落地 `/ask` 智能分析页（多轮对话 + 5 个只读 tool），让用户可以用自然语言追问「为什么这样、下一步该怎么做」。两版合起来把项目从「只展示预计算指标」推到「能解释、能追问」。
2. **AI 功能不是一次做成的，是被真实用户反馈打磨出来的**。V0.97.0 发版后连出 3 个补丁：V0.97.1（工具调用展示：spinner 永久显示、原始 JSON 直接糊在聊天流里）、V0.97.2（页面布局：1280×720 视口下输入框只剩 22px 宽、被折到视口外 156px）、V0.97.2 hotfix（miniMax 代理报 2013 tool id not found，1 级降级不够，升级为 3 级）。三版都**不动后端契约**或**只动后端一个文件**。
3. **代理兼容性是这阶段最深的坑**。根因是 miniMax 代理不跨 round 追踪 `tool_use_id`（OpenAI 风格 stateless），却对外暴露 Anthropic 兼容 API。最终解法是三级降级：L1 把 `tool_result` / `tool_use` 块整条平铺成纯文本并 `tools=None` 重试，L3 只发用户原问题、丢掉全部历史。
4. **V0.98 是一次「体验重塑 + 结构清偿」**：7 件大项 11 个 commit，把 14-link 单层导航改成 7 场景 + 4 子场景，`/ask` 从 1-10 秒黑屏改成 SSE 逐字流式，6 个带 filter 的页改成 URL 状态化，同时把 428 行 4 职责的 `ai_chat.py` 拆成 4 个文件并新建 `CHANGELOG.md`。
5. **V0.99 把项目带出黄金**。修掉 562800 白银 ETF「当前价是真的、历史 K 线是 Mock」的半真半假问题（东方财富源长期 `RemoteDisconnected`），补上新浪备援（sz161226 白银基金 LOF），并新增 SGE 上海银 `Ag99.99` 基准价跟踪，白银页从 2 market 升级为 3 market 并同步重构为 `silver.html` + `silver.js`。
6. **留下的东西**：这一阶段的门禁基线是「4 处版本同步 + check_pwa_assets 必跑」，i18n 一律 3 语同改，SW `SHELL_ASSETS` 必须随新静态文件同步。V0.99 明确把 SHFE 沪银期货、实时汇率、白银回测、金银相关性推给 V0.99.x / V1.0。

## 一、版本一览

| 版本 | 主题 | 关键交付 |
|---|---|---|
| V0.96.0 | scoring 第 3 Tab「命中分析」 | `/api/v1/scoring/hit-stats-all` 一次取 4 horizon + Chart.js 4 dataset 柱状图 + 3 mini card + i18n 9 keys × 3 语 |
| V0.97.0 | AI 智能分析页 `/ask` | 2 张新表 + `ClaudeClient` httpx 直调 + 5 个只读 tool + `AIChatService` 多轮编排 + 6 端点 + 3 pane chat UI + 22 例测试 |
| V0.97.1 | `/ask` 工具调用展示调整 | `TOOL_LABELS` 中文化 + `summarizeInput` / `summarizeResult` + 折叠原始 JSON + 「基于 N 个工具调用」chip |
| V0.97.2 | `/ask` 页面布局修复 | flex 三层链 + `min-height: 0` + 2 栏默认 / 3 栏按需 + welcome 卡片与 5 个示例 chip + i18n 12 keys × 3 语 |
| V0.97.2 hotfix | miniMax 代理 2013 三级降级 | L1 平铺 tool_use / tool_result 块为纯文本重试 + L3 fresh-only 只发原问题 + 新增 1 例降级测试 |
| V0.98 | 体验重塑 + 结构清偿 | `CHANGELOG.md` + `ai_chat` 拆 4 文件 + 全局 toast / 断网 / PWA + 场景化首页 `/home` + SSE 流式 + URL 状态化 6 页 + 双层导航 7+4 |
| V0.99 | 白银数据修复 + SGE 上海银 + 页面重构 | 562800 em+sina 双源降级 + `AkshareSgeSilverHistoryProvider` + `/silver/sge-quote` 与 `/silver/sge-trend` 2 端点 + 3-market 卡片与升贴水表 + silver.html 655→332 行拆分 |

## 二、逐版本记录

### V0.96.0 · scoring「命中分析」Tab + 4 horizon 柱状图 + 3 mini card

**背景/问题**：scoring 页从 V0.92.0 落地以来一直只有 2 个 Tab（汇总 / 日历）。「命中率」段落是「汇总」Tab 内 line 290-296 的一段文字，用户看不到时序走势，只能看单 horizon 单一数字。本版是 roadmap §12.1 候选 A 的完整交付。

**修法**：5 段交付。

1. **数据层**（不改动 `scoring_daily_wide` 宽表）：新 schema `ScoringHitStatsAllOut` + `ScoringHitStatsAllHorizon` + `ScoringHitStatsAllMiniCard`；新 service 方法 `ScoringWideService.hit_stats_all_horizons()` 复用 `hit_stats()` 内部 by_month 聚合循环，1 次 `list_in_range` + 4 horizon 各聚合；新 mini card helper `_compute_mini_card()`（最近 30 ready 日 vs 上 30 ready 日 + 最佳 horizon，多 horizon 同分取字典序最小）；新端点 `GET /api/v1/scoring/hit-stats-all?from=&to=`；旧 `GET /hit-stats?horizon=tN` 保留向后兼容。
2. **视图层**：`scoring.html` 加第 3 个 `role="tab"` button（`data-tab="hit"`）与 `<div class="tab-panel" id="panel-hit">`，含 canvas#hitChart（Chart.js bar 图）、3 mini card、`aria-label` 与 `<details>` 数据表 fallback。
3. **渲染层**：`scoring.js` 的 `loadHitData(p)` / `renderHitChart(data)`（Chart.js bar type，4 dataset 4 色叠加，销毁旧实例）/ `renderHitCards(data)` / `switchTab(tab)`（切到 hit Tab 时按当前日期范围加载 1 次）。
4. **i18n**：9 keys × 3 语（`tab_hit` / `hit_chart_title` / `hit_chart_desc` / `hit_mini_30d` / `hit_mini_mom` / `hit_mini_best` 及其 desc）。
5. **维护线**：4 处版本同步 + `check_pwa_assets.py` 必跑。

4 色 chart palette：t0 = amber `#fbbf24`（早期反馈）、t1 = blue `#3b82f6`（主流窗口）、t3 = violet `#8b5cf6`（中期验证）、t5 = green `#10b981`（长线稳定），避开 V0.92.1 命中列的红 / 绿。

**验证**：后端 `pytest tests/test_services/test_scoring_wide.py` 15 passed in 5.11s（无回归）；端点手验 `curl 'http://127.0.0.1:8888/api/v1/scoring/hit-stats-all?from=2026-09-01&to=2026-10-14'` 返回 `by_horizon` 4 项与 `mini_card`；puppeteer 实跑 `/scoring` 10 项全 ✓（3 Tab、panel.active、canvas role=img、3 mini card、bar type + 4 dataset、x 轴降序、a11y fallback、zh-CN / en-US / zh-TW 文案）。门禁：`check_routes.py` 14/14（13→14 alias）、`check_pwa_assets.py` v0.96.0 OK、`check_static_js.py` 17 + 30 全过、`check_i18n_keys.py` 0 missing / 0 fallback、pytest 15/15。

**教训**：本版把历次版本的设计纪律全部继承下来，逐条对照如下：

- **V0.78.0 Step D**：所有数值列允许 NULL（绝不 50 / 0 兜底）——`mini_card.last_30d[h]` 与 `last_30d_mom[h]` 不足 30 ready 日时为 None，前端显示「—」；`mini_card.best_horizon` 全 None 时为 None。
- **V0.79.0 #162**：本版不改宽表（只读现有 4 字段），无白名单风险。
- **V0.80.0 #159**：所有 query 默认 user_id 过滤（`list_in_range` 复用）。
- **V0.86.1 教训**：URL 跳转必须 curl 验证 200/307 —— check_routes 同步 13→14 alias。
- **V0.92.0 物化宽表模式**：复用 `scoring_daily_wide` 不加列；V0.92.1 命中筛选保留，本版**新端点**与旧端点并行不冲突。
- **V0.93.0 T+0 模式**：4 horizon (t0/t1/t3/t5) 全部支持，hit_col dict 复用。
- **V0.94.0 verdict card 保留**：本版是「Tab 3 全局可视化」，与 verdict card（Tab 1 顶部）功能不重叠；V0.95.0 NY 金列本版不动。
- **V0.95.1 降序约定**：chart x 轴按月份降序（最近→远期），与主表 / 日历一致。
- **V0.83.0 sig() dict bug**：本次 mock 用真实 schema；**V0.83.4 freshness 降级**：沿用 am / chip 风格。

**commit 切分**：`a32f56d`（feat(api) GET /api/v1/scoring/hit-stats-all · 4 horizon 聚合 + mini card 摘要 —— schema + service + endpoint + 5 例测试）与 `933fb45`（feat(scoring) 第 3 Tab「命中分析」+ 4 horizon 柱状图 + 3 mini card —— HTML + JS + CSS + i18n 9 keys × 3 语），按 C1-C2-C3 顺序：后端 API → 前端可视化 → 版本号 + 发版。

**不在本版（候选延后）**：候选 B「胜率随 horizon 退化曲线」、候选 C「跨市场对照扩展」、候选 D「数据自动刷新」、候选 E「错误降级 UX 重构」、候选 F「移动端 PWA 体验优化」、候选 G「快捷键」均为 V0.97+ 候选；候选 H「K 项 · 多市场独立校准」为 V0.98+ 必做。

### V0.97.0 · AI 智能分析页（多轮对话 + 5 个只读 tool）

**背景/问题**：9 个业务页（trend / portfolio / news / review / central-bank / silver / backtest / scoring / data-health）只能展示预计算的指标。用户看到「最近 30 天 T+1 命中率 40.7%」是数字，「为什么这样、下一步该怎么做」需要自然语言解读，且任何地方都不能让用户问「现在适合加仓吗？」「为什么今天评分变低了？」。本版是 roadmap §12 候选 I 的完整交付。

**修法**：5 段交付。

1. **数据层**：`migrations/versions/l8f9a0b1c2_ai_chat.py` 建 `ai_conversations`（id 36 字符 uuid + user_id FK + title + model + message_count + 2 token 累计 + is_archived + 3 timestamp）与 `ai_messages`（id uuid + conversation_id FK CASCADE + user_id + role + content + tool_name / input / call_id + 2 token + latency_ms + error_code）2 张表 + 4 索引；`src/app/models/ai_chat.py` 用 SQLAlchemy 2.0 `Mapped[]` 声明，常量 `DEFAULT_MODEL="claude-sonnet-4-5"` / `TITLE_MAX_CHARS=24`；`src/app/repositories/ai_chat.py` 的 `AIConversationRepository` 6 方法与 `AIMessageRepository` 6 方法。
2. **后端服务层**：`src/app/services/llm/claude.py` 的 `ClaudeClient` httpx 直调（ENDPOINT `https://api.anthropic.com/v1/messages`，ANTHROPIC_VERSION `2023-06-01`，重试退避 (2.0, 5.0, 15.0) 仅 429/5xx，`ClaudeResponse` dataclass + `LLMError` / `LLMRetryable` 异常分层）；`src/app/services/llm/tools.py` 的 `ToolDispatcher` + 5 个只读 tool（`get_market_overview` / `get_scoring_summary` / `get_user_portfolio` / `get_warning_summary` / `get_etf_recent_flows`），单 tool 失败返 `is_error=True` 的 ToolResult 而不抛异常到 LLM，单 tool 结果 4000 字符截断；`src/app/services/ai_chat.py` 的 `AIChatService` 编排（多轮 tool_use 循环硬上限 3 轮、命中 end_turn 即停；首条 user 消息自动派生 title，24 字符 + … 截断；prompt injection 防护 8000 字符截断 + 移除 `<system>` / `<assistant>` / `IGNORE_PREVIOUS_INSTRUCTIONS` 等危险 token；LLM 异常时 `msg.delete(user_msg.id)` 回滚避免脏历史）；`src/app/middleware/per_user_rate_limit.py` 的 `PerUserRateLimitMiddleware`（per-user 60s 滑动窗口，默认 30 req/min + 每日 token 配额默认 100k/天，只作用于 `/api/v1/ai/*`，in-memory 状态）；`src/app/api/v1/endpoints/ai.py` 6 端点（health / 建对话 / 列表 / 详情 / 改名归档 / 发消息）。
3. **前端**：`static/ask.html` 3 pane 布局（左 240px 对话列表、中 flex 消息流、右 280px tool trace）+ `static/ask.js` + vendored `static/marked.min.js`（marked v12.0.2，35KB）+ `static/topnav.js` 加 `/ask` + `static/manifest.json` 加 PWA shortcut + `static/sw.js` 的 `SHELL_ASSETS` 加 `/ask` + `/static/ask.html` + `marked.min.js`；i18n 新增 `ai.*` 36 keys + `nav.ask` × 3 语。
4. **配置 + 维护线**：`src/app/config.py` 9 项 LLM 设置（`llm_api_key` env only / `llm_model` = "claude-sonnet-4-5" / `llm_max_tokens` = 2048 / `llm_timeout_seconds` = 30.0 / `llm_per_user_per_minute` = 30 / `llm_daily_token_quota` = 100_000 / `llm_max_tool_rounds` = 3 / `llm_tool_result_max_chars` = 4000 / `llm_user_message_max_chars` = 8000）+ 4 处版本同步 + 门禁同步（`check_routes.py` 的 `EXPECTED_ALIAS_PATHS` 加 `/ask`，14→15；`check_i18n_keys.py` 的 `V083_KEY_PREFIXES` 加 `"ai."`）。
5. **测试**：22 例（service 5 + LLM 6 + endpoint 11），含端到端 mock LLM 的 `test_send_message_pure_text` 与 `test_send_message_with_tool_use`（1 user → 1 asst(tool_use) + 1 tool + 1 asst(text)）。

**验证**：`pytest` 22 passed；`check_routes.py` 15 条路由全过；`check_pwa_assets.py` SW 版本一致（v0.97.0）、SHELL_ASSETS 33 条、manifest 8 个目标；`check_static_js.py` 18 个静态页内联脚本 + 32 个共享脚本；`check_i18n_keys.py` 74 in-scope keys 全覆盖；puppeteer 3 语验证（`/tmp/check_ask.mjs`）3 语 hero 与「+ 新对话」文案全对。

**教训**：安全基线 —— `LLM_API_KEY` env only；server 端 `_sanitize_user_text()` 截断 8000 chars；PII 最小化（system prompt 只传 model 名 + 业务规则，不传 IP / cookie / session_id）；XSS 防护（marked v12 解析后 strip script / iframe / object / embed + on* 事件属性 + javascript: URI）；rate limit + token quota 双护栏（per-user 30 req/min + 每日 100k tokens）。工程纪律 —— V0.80.0 #159 所有 query 强制 user_id 过滤、越权访问表现「查不到」（404）；V0.92.0 教训新加 static/*.html 必须同步 SW（cache-first + RUNTIME_CACHE 旧 307 优先）；所有资源 vendored（marked.min.js），无 CDN 依赖，保持 LAN-only 部署。

**5 个只读 tool 与其数据来源**（永不暴露 mutation endpoint）：

| tool | 数据来源 |
|---|---|
| `get_market_overview` | `TrendService.analyze()`（NY 金 / 综合指数） |
| `get_scoring_summary` | `ScoringWideService.hit_stats_all_horizons()`（4 horizon by_month） |
| `get_user_portfolio` | `PositionService.equity_curve()` + `performance()`（90 日权益 + 业绩） |
| `get_warning_summary` | `FreshnessService.snapshot()`（数据源 stale 状态） |
| `get_etf_recent_flows` | `MarketDataRepository.get_gold_history(days=1-90)`（沪金 ETF K 线） |

**commit 列表**：`e1147cc` C1 feat(db) ai_conversations + ai_messages 表 + alembic 迁移 + ORM 仓储；`d519f46` C2a feat(ai) Claude LLM client + 5 tool schema + ToolDispatcher；`e5c492c` C2b feat(ai) 6 端点 + PerUserRateLimit + send_message 多轮；`2108d66` C3 feat(ai) /ask 智能分析页 + 3 pane chat + marked.js + i18n 36 keys × 3 语；本 commit 为 C4 chore(release) V0.97.0 版本号 + 发版说明。

**部署**：① 配置 `LLM_API_KEY` env（**必填**，未配置时 `/ask` 显「未启用」cover）；② `git pull` + `alembic upgrade head`（应用 `l8f9a0b1c2` 迁移）；③ 重启服务加载新 C2b/C3 代码；④ topnav 点「🤖 智能分析」或 PWA shortcut 进入。

**不在本版（候选延后 V0.98+）**：流式响应（SSE / WebSocket）、多模型切换（Opus / Haiku）、图片 / 文件附件、对话导出（PDF / MD）为 V0.98 候选；每日 / 每周自动报告走 `ai_chat` 后台任务；Web search tool 为 V0.99 候选；代码解释器 tool 风险大延后；跨用户共享对话团队版才需要；多副本 Redis 状态（当前 in-memory 限速 / 配额）。

### V0.97.1 · /ask 工具调用展示调整（UI hotfix）

**背景/问题**：V0.97.0 部署后用户实测反馈 4 条：

1. 工具调用完成后还在显示 spinner —— assistant 消息因 `content` 为空 + `tool_name` 命中分支，永久展示「正在调用工具: get_market_overview...」文案；
2. tool 结果在聊天流里直接显示原始 JSON —— 1KB+ 的 JSON 字符串塞在消息流里，既不友好也暴露内部结构；
3. 右侧 trace 面板用英文 tool 名 + 原始 JSON —— `get_market_overview` 是开发者术语；
4. 缺少「模型答案是否基于实时数据」的验证提示 —— 用户无法判断「这个数字是我编的还是查的」。

**修法**：5 项交付，纯前端展示层。

1. `TOOL_LABELS` 字典中文化 + emoji 标签：`get_market_overview` → 📈 市场概览、`get_scoring_summary` → 🎯 评分汇总、`get_user_portfolio` → 💼 持仓查询、`get_warning_summary` → ⚠️ 警示、`get_etf_recent_flows` → 💸 ETF 资金流。
2. `summarizeInput` 按 tool 白名单抽取关键参数（如 `get_scoring_summary` → "2026-10-01 → 2026-10-14"，`get_etf_recent_flows` → "近 30 天"，未知 tool → 原 JSON 截断 100 字符）。
3. `summarizeResult` 按 tool 白名单抽取核心数据 1-2 行可读（如 `get_scoring_summary` → "近 30d T+0/T+1/T+3/T+5: 35.7% / 40.7% / 40.0% / 39.1% · 最佳: t1"，未知 tool → 原 JSON 截断 200 字符）。
4. 聊天流展示调整：assistant tool_use 消息由 spinner 改为「🔧 📈 市场概览」chip；tool 消息由直接渲染 `<pre>` 改为折叠 `<details>` 默认收起（展开看原始 JSON，限 280 字符 max-height + 滚动）；最终 assistant 末尾追加「📊 基于 N 个工具调用 · 右侧查看详情」chip。
5. 右侧 trace 面板重做：中文 label + 角色 chip（`→ 调用` / `← 结果`）+ 参数摘要 + 结果摘要 + 折叠「原始 JSON」（展开看 ≤800 字符原始数据）。

**验证**：`check_pwa_assets.py` SW 版本一致（v0.97.1）、SHELL_ASSETS 35 条、manifest 8 个目标；`check_static_js.py` 18 个静态页 + 33 个共享脚本（ask.js +1）；`check_routes.py` 15 条路由（含 /ask alias）；`pytest tests/ -q` 现有全过（无新后端逻辑）。

**教训**：**不修改任何后端逻辑 / API 契约** —— 纯前端展示层；**数据可追溯** —— 每个 assistant 答案下方都标注「基于 N 个工具调用」，右侧 trace 面板可逐条验证数据来源；**不破坏 XSS 防护** —— marked 渲染仍走 `sanitizeHtml` 清洗；**不破坏 i18n** —— i18n key 复用未新增（`ai.calling_tool` 旧 spinner 文案删除后无引用，保留 key 不影响）；**响应式保留** —— 手机端 `< 1000px` 隐藏 trace 面板规则不变。

**关键文件**：

| 文件 | 改动 |
|---|---|
| `static/ask.js` | +130 行：`TOOL_LABELS` / `summarizeInput` / `summarizeResult` / `renderToolMsgInStream`；`renderAssistantMsg` / `renderToolTraceItem` / `renderMessages` 调整 |
| `static/ask.html` | +45 行 CSS：`.tool-chip` / `.tool-result-stream` / `.data-source-chip` / `.role-chip` / `.raw-details` |
| `static/sw.js` | `VERSION` → `v0.97.1` + SHELL_ASSETS 加 `/static/ask.js` |
| `pyproject.toml` | version 0.97.0 → 0.97.1 |
| `src/app/__init__.py` | `__version__` 0.97.0 → 0.97.1 |

**部署**：LAN 部署需浏览器 hard-refresh 一次（Ctrl+Shift+R）拉新 SHELL_CACHE；已安装 PWA 由 SW 检测到 `v0.97.0` → `v0.97.1` 变更后自动 activate 重建缓存；后端无变更，uvicorn 无需重启。

**不在本版**：工具流式展示（V0.98+ SSE 候选）、Tool 耗时详情（当前只显示总 latency_ms）、用户对工具结果的反馈（upvote / downvote，长期候选）、工具调用 reasoning（让模型解释「为什么调这个 tool」，V0.98 候选）。

### V0.97.2 · /ask 页面布局修复（视口感知 + welcome 卡片）

**背景/问题**：V0.97.1 部署后用户实测反馈：「智能分析的页面布局，我看不到填写内容的对话框，页面布局也需要优化」。puppeteer 探针定位 3 个叠加缺陷：

| 视口 | 旧 msgInput.y | 视口底 | 旧 msgInput.w | 状态 |
|---|---|---|---|---|
| 1280×720 | 876 | 720 | 22px | fold 下 156px |
| 1366×768 | 876 | 768 | 22px | fold 下 108px |
| 1440×900 | 876 | 900 | 22px | fold 上 24px（勉强） |

根因 3 条：① `.ask-layout { min-height: 540px }` 写死，与 topnav+hero 叠加后固定超出视口；② `.input-bar` 在 `.ask-main`（flex 列）里没声明 `flex-shrink: 0` + 显式宽度，塌缩到 `textarea 22 + gap 8 + send 62 = 92px`（所有视口 `msgInput.w = 22px`）；③ 3 栏 grid `240px 1fr 280px` 里右侧 `.ask-tools` 初始 `[hidden]` 但仍占第 3 列 280px 空白。

**修法**：4 项交付。

1. **视口感知 flex 三层链布局**：`body` → `min-height: 100dvh`（带 `100vh` 兜底给老 Safari < 15.4）；`.wrap` → `flex: 1 1 auto` + `min-height: 0`；`.ask-layout` → `flex: 1 1 auto` + `grid` + `min-height: 0`；`.message-stream` → `flex: 1 1 auto` + `min-height: 0` + `overflow-y: auto`；`.input-bar` → `flex-shrink: 0` + `width: 100%`。
2. **2 栏默认 / 3 栏按需**：默认 `grid-template-columns: 240px minmax(0, 1fr)`（用 `minmax(0, 1fr)` 防 textarea min-content 撑爆列），当 `askLayout.classList.contains('has-tools')` 时切为 `240px minmax(0, 1fr) 280px`；JS 加 `setToolsVisible()` 同步 `toolTraceEl.hidden` 与 class；移动端 `<1000px` 仍走 1 栏。
3. **Welcome 卡片 + 5 个示例 chip**：`.empty-stream` 由单行文案改为带 `💬` 图标 + 标题 + 描述 + 5 个 chip（📈 今天金价怎么样？/ 💼 我的持仓表现如何？/ 🎯 最近 T+1 命中率走势？/ ⚠️ 当前有什么风险信号？/ 💸 最近 ETF 资金流向？）；`renderEmptyStream()` 不再 `innerHTML` 整片擦写以保留 `#emptyState` 节点、chip 事件不丢失；点击 chip 填入 textarea + focus + auto-resize + char-count 同步，不自动开新对话；`i18n:change` 触发 `renderExamplePrompts()`。
4. **输入栏微优化**：textarea + send-btn 加 `title="Enter 发送 · Shift+Enter 换行"`；`max-height` 140px → 120px；新增字数提示 `N / 8000`，> 8000 字变红。

**验证**：`node /tmp/snap_ask.mjs` 3 视口探针全过（1280×720 / 1366×768 / 1440×900 的 `msgInput.y+height ≤ 视口`，`input.width = 656`）；`check_pwa_assets.py` SW v0.97.2、SHELL_ASSETS 35 条；`check_static_js.py` 18+34；`check_i18n_keys.py` ai.* 命名空间 30 keys × 3 语全覆盖；`check_routes.py` 15 条路由不变；`pytest tests/ -q` 现有全过（无后端改动）。

**教训**：**不引依赖、不引新构建步骤** —— 纯 HTML + CSS + JS；**不动后端 / API / DB** —— 纯前端重构；**保留所有 i18n 既有 key**（18 个 key × 3 语 + ask.js 运行时 `t()` 用 ~20 个 key），12 个新 key 走 `ai.example_*` / `ai.empty_*` 命名空间；**SHELL_ASSETS 35 条不动** —— ask.html / ask.js 已在 precache 列表，VERSION bump 后 `gold-shell-v0.97.2` 与旧版完全分离，SW activate 自动清掉 `gold-shell-v0.97.1`。布局层面沉淀：`min-height: 0` 是允许 `.message-stream` 滚动的关键，漏任一层滚动就失效；`width: 100%` 显式 stretch 是治 22px 塌缩 bug 的兜底；`minmax(0, 1fr)` 用来防 textarea min-content 撑爆列。

**关键文件**：

| 文件 | 改动 |
|---|---|
| `static/ask.html` | CSS 重构（flex 三层链 + min-height:0 + width:100%）；HTML 改 `empty-state` 为 welcome 卡片 + 5 chip + `charCount` |
| `static/ask.js` | `setToolsVisible()` 替换 3 处 `toolTraceEl.hidden`；`renderEmptyStream` 保留 `#emptyState` 节点；`renderExamplePrompts` + `bindExampleChips`；`updateCharCount`；i18n:change 加 chip re-render |
| `static/i18n/{zh-CN,zh-TW,en-US}.js` | +12 keys × 3 语：empty_title / empty_desc / example_market / _q / example_portfolio / _q / example_scoring / _q / example_warning / _q / example_flows / _q |
| `static/sw.js` | `VERSION` → `v0.97.2` |
| `pyproject.toml` | version 0.97.1 → 0.97.2 |
| `src/app/__init__.py` | `__version__` 0.97.1 → 0.97.2 |
| `uv.lock` | 跑 `uv lock` 同步 |

**不在本版（候选延后 V0.98+）**：流式响应（SSE）、工具调用 reasoning、输入历史（上 / 下方向键调出最近 N 条输入）、完整 mobile drawer（左 / 右栏抽屉化）、dark mode 下 welcome 卡片配色微调；`#statusPanel` 在 /ask 的可见性策略本版保守保留（ask.js / health-summary.js / warning.js 都没人 strip `statusPanel.hidden`），留待 V0.98 单独调研；拖拽上传图片 / 附件延到 V0.99。

### V0.97.2 hotfix · miniMax 代理 2013 三级降级兜底

**背景/问题**：V0.97.2（/ask 布局修复）发版后，用户实测仍偶发 `tool result's tool id(call-...) not found (2013)`。根因是 miniMax 代理不跨 round 追踪 `tool_use_id`（OpenAI 风格 stateless），但暴露 Anthropic 兼容 API。V0.97.0 hotfix 只做了 1 级降级（内联 tool_result 重试），对「内联后仍 2013」场景无解。

**修法**：升级为 3 级降级链。

- 旧链路（V0.97.0）：Round 1 tool_use → tool_result 拼回 → Round 2 报 2013 → L1 `_inline_tool_results_as_text(messages)` 重试 1 次（tools=None）→ 失败 → 抛 `LLMError`（前端 503）。
- 新链路：L1 `_inline_tool_results_as_text()` 重试（tools=None），**并把上一条 assistant 的 tool_use 块也转纯文本**（彻底平铺 = 整条对话无 tool_use / tool_result 块，代理无歧义）→ 仍 2013 → L3 `messages=[{"role": "user", "content": user_msg.content}]` + tools=None，丢历史只问原问题 → 仍失败才抛 `LLMError`。
- `send_message()` 的 LLMError 兜底重写为 3 级链；L2 在注释中保留，逻辑并入 L1（检测 L1 仍 2013 时直接进入 L3）。

**验证**：新增 `tests/test_api/test_ai_chat_endpoints.py::test_tool_result_fallback_l1_also_2013_falls_to_l3_fresh_only` —— mock 4 次 LLM 调用（tool_use → 2013 → 2013（inlined 重试也挂）→ 文本成功（fresh-only）），验证 L3 调用时 `tools is None` 且 messages 长度 == 1（只有 user 原问题），用户拿到 200 OK（不是 503），且最终 assistant 消息含「无工具数据」兜底文案。

**教训**：**不 bump 版本** —— 纯后端 ai_chat.py + test，static/sw.js / ask.html / ask.js 没动，按 `sw-version-sync-gate` 不需要 VERSION bump；**不增新 API / DB schema** —— 失败兜底 + 内部重试；**不动 i18n** —— 用户可见错误文案没改。降级链本身沉淀出一条口径：L1 增强 = 顺带把 assistant tool_use 块也转纯文本（原来只转 user tool_result），所以本版其实只有 L1 + L3 真实降级，但代码注释按 3 级链路标注便于排障；实测 L1 已能覆盖绝大多数 miniMax 误报，L3 是「保底不返 5xx」的最后一道。新增测试用 in-memory mock，不依赖 DB schema，因而绕开了 `conftest-test-isolation` 教训里提到的 conftest drop_all 偶发 no such table 问题。

### V0.98 · 体验重塑 + 结构清偿（7 件大项 / 11 个 commit）

**背景/问题**：V0.97.x 收尾后盘点 3 类体验 + 3 类结构债。

体验：17 个业务页 13 个 topnav tab + 14 个 root alias，导航负担重；`/ask` 1-10 秒黑屏等回，缺流式；6 个有 filter 的页靠 LS 存状态，URL 不持久化 → 复制链接 / 跨页跳丢上下文；无全局 toast 系统（dashboard / ask / pwa 3 处孤例）。

结构：`ai_chat.py` 428 行 1 文件，吃掉「多轮编排 + miniMax 2013 3 级降级 + 历史窗口 + 配额扣减」4 个职责；无 `CHANGELOG.md`，发版历史散在各 release note，不可索引。

用户已确认的 4 个关键决策：首页 = 5 大场景卡（决策 / 持仓 / 情报 / 配置 / AI）；流式 = SSE（`sse-starlette` + `EventSource`）；URL 状态化 = 6 个有 filter 的页全做；PWA + toast = 全套。

**修法**：7 件大项 / 11 个 commit。

- **C1 · CHANGELOG.md 索引**（`a8a50be`）：新增 `CHANGELOG.md`，Keep a Changelog + Conventional Commits 双格式；`docs/releases/` 顶部建索引表。
- **C2 · ai_chat.py 拆分**（`a8a50be`）：428 行 1 文件按职责拆成 4 个文件（`service.py` / `prompts.py` / `serializers.py` / `proxy_fallbacks.py`），每个 60-150 行；`__init__.py` 重新导出 `AIChatService` 保持外部 import 路径不变；13 个既有 test 零回归。
- **C3 · 全局 toast + 断网检测 + PWA 安装体验**（`d2fd513`）：新 `static/toast.js` + `static/toast.css`，暴露 `window.PM_Toast` 的 info / success / warn / err / dismiss / clear，4 种类型、自动消失默认 4s、最多同时 3 个（超 3 挤掉最老）、支持 action button + undo；新 `static/net-status.js` 监听 `online` / `offline` 事件并每 30s 主动 `fetch('/api/v1/health', { cache: 'no-store' })` 探活，失败弹 `PM_Toast.err('网络异常', { duration: 0 })` + 顶部固定 banner，恢复时 banner 消失 + `PM_Toast.success('网络已恢复')`；PWA 侧加 `appinstalled` 监听、install banner 文案改写、dismiss 频率控制（7 天内不再弹）、manifest 加 `description` + `screenshots`，并抽出 `static/pwa.css`。
- **C4 · 场景化首页**（`8fc552a` + 3 个后置修复 commit `83a0025` / `94adce4` / `7434cda`）：新页 `/home`（未登录跳 `/login`，`/` 仍 redirect 到 `/static/trend.html` 保持向后兼容），新文件 `static/home.html` + `static/home.js`（约 100 行，fetch 6 个轻 endpoint 拉概览），布局为 hero + 5 大场景卡（📊 决策 / 💼 持仓 / 📰 情报 / ⚙️ 配置 / 🤖 AI 助手独立大卡）+ 底部今日要闻 Top 3 + 末次数据刷新时间 + AI 配额 chip，i18n +30 keys × 3 语，`static/topnav.js` 的 `NAV_LINKS` 最前插「🏠 首页」。
- **C5 · /ask SSE 流式响应**（`89ed23f` + `13652e6`）：新依赖 `sse-starlette ^2.0.0`（唯一新 dep）；`claude.py` 加 `ask_stream()`（`httpx.AsyncClient.stream` 逐行读 Anthropic SSE，yield `TextDelta` / `ToolUseStart` / `MessageStop` / `Ping` / `Error` 的 `StreamEvent` dataclass）；`ai_chat/service.py` 加 `send_message_stream()` 并**保留 `send_message()` 不变**；新端点 `POST /api/v1/ai/conversations/{conv_id}/messages/stream`（旧 `POST /messages` 保留，V0.97.0 contract 不破坏）；前端 `ask.js` 重写 `sendMessage()` 用 `response.body.getReader()` + `TextDecoder` 逐行解析 SSE，`appendDelta` 追加到 `textContent` 防 XSS，3 个 tool chip 渲染函数，断线自动重连 1 次（带 user 原始消息）。
- **C6 · URL 状态化 + 跨页链接器**（`668a11b`）：复用并扩展已有 `nav-context.js`，加 `bindToFilters(selectors, onChange, { debounce: 200, writeUrl: true })` / `crossLink(keys, hrefTemplate)` / `setContext(key, val)`（经 `storage` 事件多 tab 同步），启动时从 URL 反向应用；6 页接入 —— scoring（`days, from, to, account_id, group_by, horizon, hit`）、backtest（`target, horizon, days, equity_days, slippage`）、review（`target, horizon, days, account_id, tag_filter`）、trades（6 keys 完整）、portfolio（`account_id, sort, period`）、news（`category, sort`）。
- **C7 · 双层导航 7 顶场景 + 4 子场景 sub-tabs**（`f2cae44`）：`static/topnav.js` 从 14 个 `NAV_LINKS` 重构为 7 个 SCENES（首页 / 决策 / 持仓 / 情报 / 配置 / AI / 健康），每个 SCENE 配 `activeFor[]` 路径匹配 + `subpages[]` 子 tab，`buildSubnav()` 在 `#subnav-mount` 注入子导航，11 个业务页加 `<div id="subnav-mount"></div>` + 子导航 CSS，i18n 增 4 场景 key × 3 语；顺手修 pre-existing bug —— nav-drawer.js:117 `insertBefore` 抛 `NotFoundError`（根因是 `.links` 是 `.topnav-row` 子节点而非 `.topnav` 直接子节点，改插 `linksEl.parentNode`）。

**验证**：门禁 —— `check_pwa_assets.py` SW 版本一致（v0.98.0）、SHELL_ASSETS 41 条、manifest 8 个目标；`check_routes.py` 16 条路由；`check_i18n_keys.py` 0 missing / 84 in-scope；`check_static_js.py` 19 个静态页 + 35 个共享脚本，外加 nav-context 单元测试「结果：21 passed, 0 failed」。puppeteer 探针 `/tmp/check_v098_nav.mjs` —— 7/7 页面顶 nav 7 链接 + subnav 渲染（trend / scoring / backtest / review / portfolio / trades / news / central_bank / silver / weights / settings / ask / data-health / home）、4 场景（决策 / 持仓 / 情报 / 配置）subnav tabs 全对齐、3 语 + icon + active 状态正确。

**教训**（源文件「风险与教训」表）：R1 `sse-starlette` 与现有 uvicorn 兼容 → 装后立刻探活，老 `send_message` 同步路径保留（前端可降级）；R2 miniMax 代理对 SSE 不友好 → stream endpoint 内部移植 3 级降级；R3 30 个新 i18n key × 3 语翻译遗漏 → `check_i18n_keys.py` 强校验门禁；R4 URL 状态化与既有 LS 状态冲突 → `nav-context.js:get()` URL 优先，老用户无感；R5 PWA install banner 沉默 → LS TTL 7 天 + 关键价值（推送通知）放 banner 标题。T1 nav-drawer.js:117 pre-existing NotFoundError → C7 顺手修；T2 topnav 13-link + 14 alias 导航负担 → 7 顶 + 4 子场景分组；T3 ai_chat.py 428 行 4 职责 → C2 拆 4 文件；T4 无 CHANGELOG → C1 Keep a Changelog 格式。

**不在本版（候选延后 V0.99+）**：filter-bar Web Component（抽 `<filter-bar schema="...">` 统一所有 filter）、完整 mobile drawer、WebSocket 实时通知（行情 / 警示 / AI 全部实时）、AI 工具 reasoning 解释（让模型解释「为什么调这个 tool」）为 V0.99 候选；AI Markdown 渲染器升级（marked → markdown-it，表格 + 代码高亮）与首页 dark mode 微调（5 卡配色 + 渐变背景）为 V0.98.x；AI 多模态（拖拽上传截图（金价图）让 AI 解读）与 scoring T+N 命中期货市场（接入实时期货 API）推到 V1.0。

### V0.99 · 白银数据修复 + SGE 上海银跟踪 + 页面重构

**背景/问题**：用户原话：「现在白银的数据还是演示数据 而且还没有上海银价跟踪」+「寻找方案并添加白银跟踪的页面，完善功能」。

`static/silver.html` 展示 562800 + NY SI 双市场白银数据，但 562800 的数据源（东方财富 `ak.fund_etf_hist_em`）一直 `RemoteDisconnected` 失败，仓储层标记为 mock 后走 `_mock_silver_etf_history(days)` 返回「确定性 Mock 序列（base 2.45 元/份）」。前端 freshness 角标不会误标 live，但用户看到的「562800 当前价 = 1.744」实际是**真实 ETF 价**而**历史 K 线是 Mock 序列** —— 这是更危险的「数据部分真部分假」。对比黄金 ETF 518880 走 `ak.fund_etf_hist_em` + sina 备援（market_providers.py:240-294），silver 562800 只有 em 一条路。

另外 `static/silver.html` 655 行单文件、JS 全内联，违反 home / dashboard / ask 等其他页的 html+js 拆分模式。

用户已确认的 2 个关键决策：「上海银」= 只加 SGE 上海银基准价（CNY/kg 现货），不加 SHFE 沪银期货；白银页改造 = 全页重构。

**修法**：6 个 commit / 6 件大项。

- **C1 · 562800 历史 K 线修 em+sina 双源降级**（`fb2db4f`）：`AkshareSilverHistoryProvider._fetch_etf_silver`（market_providers.py:845-877）镜像 `AkshareGoldHistoryProvider._fetch_inner`（market_providers.py:240-294）的 em→sina 降级链。调研发现 `sh562800` 在新浪是「稀有金属ETF嘉实」（错！），正确白银基金是 `sz161226`（白银基金 LOF）—— 两者是不同基金但同标的白银、价格强相关。仓储层加 `_last_was_lof_proxy` 标志 → `SilverQuote.data_source_note = "lof_proxy"` → 前端展示「数据来源：白银基金 LOF（新浪代理）」。
- **C2 · SGE 上海银基准价 Provider**（`fb2db4f`）：新 `AkshareSgeSilverHistoryProvider`，端点 `ak.spot_silver_benchmark_sge()`（1700+ 行历史、零 V8 / 零 KEY），字段映射取「晚盘价」作当日 close；`MarketProviderBundle.sge_silver_history` 字段注入；`PROVIDER_REGISTRY` 4 个 entry 全部加 sge provider。
- **C3 · SGE 2 端点 + 仓储层 + price_source target**（`2bf0bb6`）：新端点 `GET /silver/sge-quote`（`SilverSgeQuoteOut`，CNY/kg，最新价 + 涨跌）与 `GET /silver/sge-trend`（`SilverSgeTrendOut`，K 线 + MA20/MA40 + direction）；新 schema `SilverSgeQuoteOut` / `SilverSgeTrendPoint` / `SilverSgeTrendOut` / `SilverSgeTrendMetrics`；仓储层 `get_silver_sge_quote()` / `get_silver_sge_history()` 并在 `_is_silver_data_real()` 加 `sge_silver` key 识别；`price_source.py` 的 `silver_sge → ('sge_silver',)` 保证 silver_sge target 走白名单入库。
- **C4 · silver.html 655 行 → silver.html 332 行 + silver.js 445 行**（`86c8b3d`）：删约 323 行内联 JS，改为 `<script src="silver.js" defer>`；silver.js 用 IIFE 包装 + DOMContentLoaded 入口，含 7 个模块函数 + 状态机（trendChart / lastTrend / currentKlineInterval / currentMarket）；`static/sw.js` 的 SHELL_ASSETS 加 `/static/silver.js`。重构发现原内联 JS 有 TDZ bug —— `techComposeBadge` 在使用之后才声明（line 513 引用、line 534 定义），原代码偶然能跑（var 提升 + 全局），拆到 silver.js 后 IIFE 严格模式 + const → `ReferenceError: Cannot access 'techComposeBadge' before initialization`，修法是把声明移到 idxMethod 赋值之前。
- **C5 · 3-market cards + 升贴水表 + 主图市场选择器**（`3c56db0`）：白银页从「2 market 视角」升级为「3 market 视角」= ETF（562800 元/份）+ NY SI（USD/oz）+ SGE Ag99.99（CNY/kg）。silver.js 加 `currentMarket` 状态机 + 5 个 lookup 表（MARKET_SUB / MARKET_ENDPOINT / MARKET_TREND_FIELD / MARKET_TREND_CLOSE / MARKET_NAME），`loadCards()` 改 3-market Promise.all，`loadTrend(days, interval, market)` 与 `renderMain(data, market)` 加 market 参数，新增 `renderPremiumTable(etf, ny, sge)`（以 SGE 为锚算 3-market 升贴水）与 `bindMarketSelector()`；silver.html 改 headline 标题、新增「多市场升贴水表」section、主图加 `marketSelector` div（ETF / NY SI / SGE Ag99.99）与 `.market-btn` CSS（青色 active 区分）；i18n 12 keys × 3 langs = 36 条翻译。
- **C6 · 发版**：`src/app/__init__.py` + `pyproject.toml` + `static/sw.js` 4 处版本同步（0.98.0 → 0.99.0）+ `CHANGELOG.md` 加节 + release notes。

升贴水公式：562800 ETF × 1000 = 元/千克；NY SI × 31.1035 × 7.1 = 元/千克（oz→g + CNY/USD 固定）；SGE 为 CNY/kg 现货基准，锚定 0%。

**验证**：门禁 —— `check_pwa_assets.py` SW v0.99.0、SHELL_ASSETS 42 条（+ silver.js）；`check_routes.py` 18 条路由全 OK（+2 silver sge）；`check_i18n_keys.py` 0 missing / 120 in-scope（+12 silver.* × 3 语）；`check_static_js.py` 20 + 36 全过（+ silver.js 抽出）；`pytest tests/test_api/test_market.py -q` 17 passed。puppeteer 探针 `/tmp/check_silver.mjs` 7 项全过 —— 5 张卡渲染（ETF + NY + SGE + 数据源 + 评估指数）、SGE 卡显示 13620 元/千克（与 `ak.spot_silver_benchmark_sge()` 实测值一致）、升贴水表 3 行且 SGE 列 0%（锚定）、market selector 切换（点击「SGE Ag99.99」→ 主图重拉 `/silver/sge-trend`）、1 张趋势主图 + 3 个 range-btn + 3 个 market-btn、silver.html 内联 script 数 = 0、topnav 7 链接 + subnav 3 链接。端到端手测 6 项全勾：562800 历史 K 线有真实数据（不再是 base 2.45 的 Mock 序列）、SGE 卡 13620 元/千克、market-btn 切换主图为 SGE、升贴水表 SGE 列「0%」「+0.00%」、3 语切换所有新增 i18n key 都翻译、uvicorn log 不再出现 `silver ETF history failed ... RemoteDisconnected` 警告。

**教训**（源文件「风险与缓解」表）：R1 `ak.spot_silver_benchmark_sge` 早盘 / 晚盘口径混淆 → 取「晚盘价」作 close、早盘作 open、high/low 取 max/min；R2 `ak.fund_etf_hist_sina` 是否真存在 / V8 风险 → 用 sz161226（白银基金 LOF）做代理；R3 silver.html 拆 .js 后内联 CSS 与 .js 顺序错乱 → 严格按 home.html / dashboard.html / ask.html 模式（CSS 在 `<head>`、`<script src="silver.js" defer>` 在 `</body>` 前）；R4 market selector 切换后 chart 状态泄漏 → `if (trendChart) trendChart.destroy()` 放在 renderMain 头部；R5 升贴水表硬编码汇率 7.1 → 表头加注「CNY/USD = 7.1 固定参考汇率，实时汇率请参考专门汇率工具」；R6 SGE 端点无 ma5/ma20/ma40 字段 → hasMA 守卫，SGE 只画 1 条收盘价。T1 V0.92.0 教训 `scoring-page-css-block-tech-debt` → silver.html 保留 CSS 内联块在 head，V0.99 不动；T2 V0.92.0 教训 `sw-cache-static-html-bust` → 新增 silver.js 必走 SHELL_ASSETS，VERSION 升 v0.99.0 强制 SW 重建缓存；T3 V0.83 教训 `frontend-undefined-rendering` → 3-market card 字段名要 hasOwn 保护；T4 V0.83 教训 `i18n-init-await` → 12 新 key × 3 语同步改齐，不留单语；T5 拆 silver.js 的 TDZ 教训 → techComposeBadge 声明必须先于使用；`renderMain` 必须显式收 market 参数（C5 修的正是 C4 漏传 market 导致的 `ReferenceError: market is not defined`）。

**关键文件**：

| 文件 | 改动 |
|---|---|
| `src/app/repositories/market_providers.py` | `_fetch_etf_silver` 加 sina 备援；新增 `AkshareSgeSilverHistoryProvider` + Mock；`MarketProviderBundle` + `PROVIDER_REGISTRY` 注入 sge_silver_history |
| `src/app/repositories/market_data.py` | 加 `get_silver_sge_quote/history`；`SilverQuote.data_source_note`；`_is_silver_data_real` 加 sge_silver key |
| `src/app/services/price_source.py` | `_TARGET_TO_MARKET_KEY` 加 silver_sge |
| `src/app/api/v1/endpoints/market.py` | 加 2 端点（sge-quote / sge-trend） |
| `src/app/schemas/market.py` | 加 4 schema（SilverSgeQuoteOut / SilverSgeTrendPoint / SilverSgeTrendOut / SilverSgeTrendMetrics） |
| `static/silver.html` | 删内联 JS → `<script src="silver.js" defer>`；3-market 标题；新增「升贴水表」section；主图加 market-btn；CSS 内联保留 |
| `static/silver.js` | 新文件（445 行）—— 7 模块函数 + 3-market 状态机 + 升贴水表 render |
| `static/i18n/{zh-CN,en-US,zh-TW}.js` | +12 silver.* keys × 3 语 = 36 条翻译 |
| `static/sw.js` | SHELL_ASSETS + `/static/silver.js` + VERSION v0.99.0 |
| `src/app/__init__.py` | `__version__ = "0.99.0"` |
| `pyproject.toml` | `version = "0.99.0"` |

**不在本版（候选延后 V0.99.x / V1.0+）**：SHFE 沪银期货（用户暂不做，预留接口路径 `/silver/shfe-*`）、实时汇率接入（升贴水表 7.1 硬编码升级为调 `/api/v1/fx/usd-cny`）、白银 ETF 升贴水 K 线（562800 vs SGE 升贴水时序图）、白银回测（类似 gold 的 backtest，支持 silver_sge target）、白银克价 = SGE 折算（改 silver_gram 口径为 SGE / 1000 而非 silver_etf × 1000）、完整 mobile drawer 为 V0.99.x；silver 与 gold 跨市场相关性（金/银价比 + 金银相关系数）为 V1.0。

## 三、这一阶段的通用教训

1. **「数字看得见」不等于「数字说得清」，也不等于「数字追得上」。** V0.96.0 把命中率从文字变成 4 horizon 时序图 + 3 mini card，V0.97.0 把它变成可以追问的自然语言；但 V0.99 才暴露出更深一层的问题 —— 562800 的「当前价是真的、K 线是 Mock」，freshness 角标不误标 live 却掩盖了半真半假。**可见 ≠ 可信 ≠ 可溯源**，三件事要分开验收。

2. **纯前端补丁与后端补丁可以并行演进，但都要有可验证的护栏。** V0.97.1 与 V0.97.2 两版都声明「不动后端 / API / DB」，用 puppeteer 探针和门禁脚本兜底；V0.97.2 hotfix 则相反，「不 bump 版本」——因为它只动 `ai_chat.py` + 一个测试，`static/sw.js` / `ask.html` / `ask.js` 没动。**动没动前端，决定了要不要 bump SW 版本**，这条口径在这一阶段被反复使用。

3. **对外兼容的接口不等于对外兼容的语义。** miniMax 代理暴露 Anthropic 兼容 API，却不跨 round 追踪 `tool_use_id`（OpenAI 风格 stateless），于是 2013 只在真实多轮 tool_use 时才炸。解法不是让代理改，而是把整条对话平铺成纯文本（L1）直至只发原问题（L3）——**降级要覆盖「代理对历史有更深问题」的情形，而不只是「某个块格式不认」**。

4. **裁剪布局和降级链路是同一类工作。** V0.97.2 的 22px 输入框宽度来自 flex 链缺 `flex-shrink: 0` / 缺 `min-height: 0`，V0.97.2 hotfix 的 L1/L3 来自对话历史里残留的 tool_use 块。两处都指向同一条纪律：**链路里的每一层都可能成为失败点，必须显式定义「砍掉哪一层还能继续」。**

5. **拆分文件会暴露旧代码里被容错掩盖的缺陷。** silver.html 从 655 行拆成 silver.html + silver.js 时，原内联 JS 因 var 提升 + 全局作用域「偶然能跑」的 TDZ bug 在 IIFE 严格模式下变成 `ReferenceError`；同一次拆分还漏传 `market` 参数，切到 SGE 直接 `ReferenceError: market is not defined`。**重构的价值不只是变短，而是让隐藏的时序与作用域错误显形。**

6. **这一阶段建立了贯穿后续版本的交付节拍。** 4 处版本同步（`pyproject.toml` / `src/app/__init__.py` / `static/sw.js` / release note）+ `check_pwa_assets.py` 必跑；i18n 一律 N keys × 3 语同改（V0.96.0 的 9 keys、V0.97.2 的 12 keys、V0.99.0 的 12 keys）；新增 `static/*.js` 必同步 SW 的 `SHELL_ASSETS`（silver.js / ask.js / home.js 同模式）；改 static/*.html 后必须 bump `sw.js` 的 `VERSION`，否则 cache-first + RUNTIME_CACHE 的旧 307 会继续回放旧版。

---

**相关文档**：项目总览见 [docs/overview.md](../../overview.md)，演进脉络索引见 [docs/releases/index.md](../index.md)，完整发版历史见 [CHANGELOG.md](../../../CHANGELOG.md)。
