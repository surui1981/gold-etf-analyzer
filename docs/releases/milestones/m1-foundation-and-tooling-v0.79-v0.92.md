# M1 · 评估底座与工程化（V0.79 – V0.92）

> **发版区间**：V0.79.0 – V0.92.0（19 个版本）｜ **状态**：归档（历史里程碑）
> **本文件定位**：把该区间的 19 份 release notes 合并成一条**可读的演进脉络**。
> **逐版原始全文**在 git 历史里（tag 与原文件名同名）：`git show v0.92.0:docs/releases/v0.92.0.md`
>
> **延伸阅读**：[能力 × 版本对照表](../index.md) · [路线图 §1 历史里程碑](../../roadmap.md) · [开发指南](../../development.md) · [部署说明](../../deployment.md) · [变更日志](../../../CHANGELOG.md)

---

## 〇 一页结论

1. **「评估算法」从可调走到可解释、可回测**。V0.79.0 一步收口 Step G/E/F/H：宏观 5 因子阈值从硬编码改成近 252 日滚动 90/10 分位；技术面从「4 个高度相关维度加权」改成 3 组组内平均（趋势 0.50 / 超买 0.30 / 风险 0.20）；回测权重支持三层网格嵌套到 5 维子网格（243 组合）+ 异步接口。V0.86.0 把这套评分结果做成「拆解 + 对比 + tooltip」三件套，V0.92.0 把历史成绩单做成物化宽表 + 汇总页。

2. **多用户与 LAN 部署从「能登录」补到「能找回、能管人、能跨终端写」**。V0.80.0 把 `news_scores` / `analysis_records` / `push_subscriptions` 三张表按 user_id 隔离；V0.81.0 补齐找回密码 + 用户管理页；V0.80.1 → V0.81.1 → V0.82.0 三次迭代解决 prod 写端点 401（localStorage 按 origin 隔离，换机器就空），最终落地 HttpOnly cookie session（HMAC-SHA256，30 天 TTL）+ `AUTH_ENABLED=false` 单用户模式整体豁免。

3. **前端信息架构做了一次「减法」重构**。V0.83.0 主页改版 + 8 页面警示合并 + 共享 topnav 抽离（-16KB 重复 HTML）；V0.84.0 把时效与警示合并进单个 disclosure（省 ~80px）；V0.85.0 把时效迁到 /data-health.html 并收成 1 个健康 chip（主页首屏再省 290px）。这三版是同一件事的连续收敛：把「每页都重复披露」改成「一处披露 + 一处跳转」。

4. **门禁从「跑得起来」升级到「跑得对」**。V0.80.0 让本地第一次能跑全量回归（1101 例，8 分 28 秒）；V0.83.0 新增 `check_i18n_keys.py` 与 puppeteer 端到端脚本；V0.87.0 把 src/ 覆盖率从 84% 推到 87%；V0.88.0 引入 `scripts/check_routes.py` 真 HTTP 双向验证，并把三个低洼模块分别推到 100% / 98% / 90%。测试数从 1101 涨到 1362+，门禁从「静态扫描」走向「浏览器实跑 + 真实 HTTP」。

5. **「事后回看」这条产品线在本阶段成型**。V0.90.0 补决策时间线回放后端 API（顺带修掉 V0.79.0 遗留 6 个版本的 `SnapshotOut` 漏配 `macro_detail`）；V0.91.0 补 `/report` 复盘报告页（5 段，浏览器原生导出 PDF）+ 9 页跨页上下文保留；V0.92.0 补 `scoring_daily_wide` 物化宽表（26 列 + 3 索引）+ 5 个端点 + `/scoring` 双 Tab 汇总页，把「跨日跨月看成绩单」从 100-300ms 的多表 JOIN 变成宽表直查。

6. **留下的问题**：`macro_detail` 漏配说明「加列」不等于「暴露」；prod 401 路径至今没有自动化测试，只能手测；`app_settings` 混合表、专用审计日志、多角色 RBAC 全部顺延；「新增 i18n key 必须 3 语同步」直到 V0.91.0 才补上自动化断言；V0.92.0 明确把事件溯源表、冰山分层、跨用户对比划到 V0.93+。

---

## 一、版本一览

| 版本 | 主题 | 关键交付 |
|---|---|---|
| V0.79.0 | 阈值动态化 + 回测增强 | 宏观 5 因子改 252 日滚动 90/10 分位；技术面 3 组组内平均；回测权重三层嵌套 + 异步接口；样本阈值 10 / 5 分层 |
| V0.80.0 | 测试基础设施修复 + 数据隔离第 2 批 | engine 层配 WAL + busy_timeout，本地首次能跑全量回归（1101 例）；3 张用户表按 user_id 隔离 + ALL_USERS 哨兵 |
| V0.80.1 | prod 写端点自动附加 X-Admin-Token | auth.js 全局 fetch 打补丁自动附加 token 头，零后端改动（hotfix） |
| V0.81.0 | 找回密码 + 用户管理页 | password_reset_tokens 表 + 2 端点 + reset-password.html；admin/users 4 端点 + users.html（+75 用例） |
| V0.81.1 | admin token 缺失提示横幅 | 基座拦截 401 弹顶部黄色横幅 + 「去设置」按钮，每会话只弹一次（hotfix） |
| V0.82.0 | admin session cookie + 单用户模式豁免 | pm_admin_session HttpOnly cookie（HMAC-SHA256，30 天）+ admin-token 端点 + AUTH_ENABLED=false 整体豁免 |
| V0.83.0 | 主页 UI 改版 + 8 页面警示合并 + 静态门禁强化 | 双行顶 nav + warn-footer disclosure；8 页迁移；新增 check_i18n_keys.py 与 puppeteer_v083.mjs（1418 断言） |
| V0.83.2 | 共享 topnav 抽离 | 新增 static/topnav.js（111 行），8 页 nav 由 2000 字符缩到 25 字符，合计 -16KB |
| V0.83.3 | 限速中间件 /static/ bypass + 默认 600/min | /static/ 路径免计数；限速 120 → 600；补 fresh.load_failed_suffix 三语 |
| V0.83.4 | freshness 降级 UX 重设计 + sig() 关键 bug 修复 | 末次数据 + amber stale chip + 智能退避 60→120→300→600s；sig() 修 dict/array 不兼容 |
| V0.84.0 | 状态条方案 C · 数据时效 + 警示合并 1 行 | 单个 details#statusPanel 承载时效 + 警示 pill（省 ~80px）；warning.js 加 hashchange；i18n init() 补 await loadLang |
| V0.85.0 | 数据时效迁移到 /data-health.html + 主页版面优化 | 新增 static/health-summary.js；9 页 statusPanel 收成 1 个健康 chip；主页历史面板默认折叠省 290px |
| V0.86.0 | 决策可解释性增强（拆解 + 对比 + tooltip 三件套） | 新增 static/decision-explainer.js；42 个新 i18n key × 3 语 = 126 条 |
| V0.86.1 | 数据健康跳转 404 hotfix | main.py 补 /data-health 与 /data-health.html 双别名；chip href 升级到 /data-health；SW VERSION bump |
| V0.87.0 | 维护线：覆盖率扩充 + broken link 回归防护 | src/ 覆盖率 84% → 87%；central_bank_data.py 22% → 96%；main.py 37% → 79%；1237 passed |
| V0.88.0 | 维护线：HTTP 路由门禁 + 覆盖率 87→90% | scripts/check_routes.py 新建（真 HTTP 双向验证）；grams 100% / import_central_bank 98% / admin 90%；1297 passed |
| V0.90.0 | 决策时间线回放（后端 API） | GET /api/v1/trades/timeline + snapshots by-date / in-range；修 SnapshotOut 漏配 macro_detail |
| V0.91.0 | 复盘报告 PDF 一键导出 + 跨页上下文保留 | /report 5 段报告页 + print.css + nav-context.js（pm_ctx_v1_*）；顶栏第 12 个按钮；alias 11 → 12 |
| V0.92.0 | 历史打分数据汇总（物化宽表 + 汇总页） | scoring_daily_wide 26 列宽表 + 5 端点 + /scoring 双 Tab 页；alias 12 → 13；端点 28 → 33 |

---

## 二、逐版本记录

### V0.79.0 · 阈值动态化 + 回测增强

**发布信息**：2026-10-07 ｜ tag `v0.79.0`（annotated）｜ commit `f60e98c`（Step F-5 docs）+ 4 prior commits ｜ 13 个 commit（不含 docs 收口）、约 +1500 / -300 行 ｜ 与上一版本 V0.78.0（2026-10-05，`5ebffee`）间隔 2 天

**背景/问题**：V0.78.0 实测发现技术面 4 个维度（结构 / 动量 / 支撑 / 动能）都围绕「均线 + 价格动量」计算，内部高度相关，加权后实质变成「4 倍趋势 + 1 倍回撤」，回撤信号被稀释；宏观 5 因子的阈值是硬编码的，用 2008 年的阈值当 2026 年的标尺；总体样本阈值 20 对本地客户过高，难以达到可信度下界。

**修法**：

- Step G 回测权重嵌套扩展（3 commit）—— tech/macro/news 三层网格内每层都支持内部 5 维子网格（tech=0.5 时扫描结构 / 动量 / 支撑 / 动能 / 回撤各 3 个候选，共 243 组合）；新增 `POST /api/v1/backtest/run-async` 立即返回 202 + task_id + Location 头，`GET /api/v1/backtest/result/{task_id}` 状态机 pending → running → completed / failed；/backtest 页面加高级模式编辑器与异步进度条。
- Step E 动态化宏观阈值（4 commit）—— dxy / us10y / us30y / vix / cb_gold 改用近 252 日滚动 90/10 分位，`_friendly_score` 由硬编码阈值表改为动态 quantile；scheduler 每日 07:00 BJT 预热；`/market/gold/trend` 暴露 `macro_dynamic` 字段与 `[动态]` / `[静态]` 角标（trend.html 与 silver.html 双受益）。
- Step F 技术面 5 维度组内平均（5 commit）—— 趋势组（结构+动量）0.50 / 超买组（动能+支撑）0.30 / 风险组（回撤）0.20；`TrendService.combine_by_group()` 静态 helper；`TrendIndexOut.composed_by` 标识合成方式，`GoldTrendOut` / `SilverTrendOut` 顶层透传 `tech_composed_by`；回滚通道是 UI 切「单维度加权（历史）」或 `PUT /api/v1/settings/weights`。
- Step H 样本阈值分层（1 commit）—— `MIN_SAMPLES_OVERALL = 10` / `MIN_SAMPLES_BUCKET = 5`；`sample_warning` 由 bool 升级为可选字符串，服务端填提示文案（总样本 < 10 提示波动大，单桶 < 5 标「样本偏少」灰色 tag）。

**验证**：

- `check_docs_claims.py` 413 处声明全找到；`ruff check src tests` All checks passed。
- `check_static_js.py` 13 静态页 + 23 共享脚本；`check_cluster_render.mjs` 222 / 222 passed（含 A8 Step F i18n 与 UI 角标 35 条断言）。
- 相关 pytest 约 800+ 通过（trend 46 / settings 6 / sharpe_compare 7 / backtest 53 / ui_cluster_render 1 等）。
- Step F 合成数据实测（seed=42，100 样本）：单维度加权 avg_tech=49.40、hits=34/100；组内平均 avg_tech=49.49、hits=33/100；差 1/100，结论「方法可行」，默认保留 `group_combine=True`。完整数据见 `docs/parameter-evaluation/sharpe_compare_2026-10-07.md`。

**教训**：新增列 `daily_snapshots.tech_detail`（5 维度 JSON）与 `daily_snapshots.data_source` 历史 24 条无法回溯补（上游 K 线只覆盖其中 16-17 天，task #162 结论），嵌套权重回测只对未来快照生效；Step F 用的是合成数据，真实历史 Sharpe 对比要等 `tech_detail` 覆盖率达标后重跑；scheduler 预热只在开发环境验证过，生产需监控 `daily_macro_threshold_cache` 实际命中率。回测结论要有统计意义，至少得等自然累积 60 条完整快照。

**遗留**：tech_detail 历史覆盖率低（16/24 条历史快照无 5 维度分）；真实历史数据 Sharpe 对比未做；scheduler 预热未在生产监控。回滚通道逐 Step 备好（`git revert` + `alembic stamp`、关预热、UI 切回单维度加权、阈值改回 20/20）。

### V0.80.0 · 测试基础设施修复 + 数据隔离第 2 批

**发布信息**：2026-10-07 ｜ commit `c34709a` `16b6c2b`（测试基础设施）、`803258e`（数据隔离第 2 批）｜ 用例 1087 → 1101（+14）｜ 与上一版本 V0.79.0（2026-10-07，`fb9df90`）｜ 两个主题都是为后续工作清路而非新增功能

**背景/问题**：测试侧，`tests/test_api/test_async_backtest.py` 本地跑 1 passed / 10 errors 而 CI 是绿的 —— 时序不同掩盖了问题，导致本地无法完整回归、只能靠 CI。数据侧，第 1 批（2026-10-06）只做了 `positions` / `accounts`，`news_scores` / `analysis_records` / `push_subscriptions` 三张表当时连 `user_id` 列都没有。

**修法**：

- 测试侧把 WAL 下沉到 engine 层 —— `connect_args={"timeout": 30.0}`；`@event.listens_for(engine.sync_engine, "connect")` 在**每条新连接**上执行 `PRAGMA journal_mode=WAL` 与 `PRAGMA busy_timeout=30000`（启动时对单条连接执行一次不够，连接池会新建连接）；`:memory:` 库跳过 WAL；`tests/conftest.py` 在 `drop_all` 前 `await engine.dispose()`。
- 连带修 `.gitignore` —— 此前只有 `*.db-journal`，缺 `*.db-wal` / `*.db-shm`，而项目自 V0.73.0 起就开了 WAL，这两个文件一直在被生成却未被忽略，首次提交时被 `git add -A` 误带入。
- 三张表加 `user_id` 并让仓储按用户过滤 —— `NewsScoreRepository` 9 个方法全部加 `user_id` 参数 + `resolve_user_id`（`upsert` 的 `existing` 查找必须按 user_id 过滤，否则 A 用户提交会命中 B 用户同日同槽位的记录并覆盖）；`AnalysisRepository` 落库带归属 + `list_recent` 按用户过滤；`PushSubscriptionRepository` 查找键改为 (user_id, endpoint)，`archive` / `delete` 跨用户一律 False。
- 新增 `user_scope.ALL_USERS = 0` 显式哨兵（真实 id 从 1 起）—— `list_active` 的两个调用方是服务级操作（notify.py 告警广播、push.py 管理员验证推送），若靠「忘了传 ⇒ 不过滤」的默认行为实现全库查询，等于把越权藏在默认值里。

**验证**：

- 用例 1087 → 1101（+14）。测试修复连跑 3 遍全绿（11 passed / 23s / 23s / 23s），耗时从 63s 降到 23s 是决定性证据（不再有 5 秒超时等待重试）；本地全量回归 1101 例全绿（8 分 28 秒）。
- 迁移四步实测 upgrade → 幂等 upgrade → downgrade → upgrade，存量数据无损。
- 八道门禁全绿（ruff 206 files / static_js 13+23 / docs_claims 413 / cluster_render 222 / pwa / links / deps）。
- 新增 14 例在 `tests/test_services/test_user_isolation_batch2.py`，沿用第 1 批的 `acting_as` 上下文管理器，覆盖跨用户读不到、跨用户 upsert 不覆盖、跨用户撤销 False、区间查询与「沿用上次」隔离、analysis 落库与过滤、push 同端点两用户共存、`ALL_USERS` 全库、单用户模式回归。

**教训**：定位 `database is locked` 走了四轮才找到真根因，前三轮都是错解（清后台任务集合 → 仍锁；`cancel()` + `gather()` → `RuntimeError: Event loop is closed`；按 loop 归属过滤 + `loop_scope=session` → 仍锁），第 4 轮的「成功」是误判 —— 复跑立刻又失败，据此做的负向验证（移除 dispose 复现 10 errors）看似确认因果，其实是随机时序骗人。真根因是 engine 从未配置 SQLite 并发参数：WAL 只在 `main.py` 启动路径设置，测试根本不经过 `main.py`，`busy_timeout` 未设则 SQLite 默认立即抛锁错误而非等待重试；配套三环是 engine 模块级单例绑定第一个 event loop、pytest-asyncio 每测试新建 loop、上一用例遗留的 pooled 连接未 check-in。写在 engine 而非启动流程，是为了让测试与生产共用同一套语义。

**教训（续）**：加 `user_id` 时连带发现两个隐藏缺陷 —— `news_scores` 唯一键不含 user_id（两人根本无法共存，唯一键从 (score_date, slot) 改为 (user_id, score_date, slot)，且必须先删旧索引再建新的，否则旧键仍在生效、数据隔离形同虚设）；SQLite 的 alembic dialect 不支持 `ALTER` 约束（`NotImplementedError: No support for ALTER of constraints`，改用 CREATE UNIQUE INDEX），且重建表只复制数据、索引不会跟着走。

**遗留**：`app_settings` 混合表（用户权重与服务级推送密钥混存，须改复合主键 + 服务级键约定值，另起一轮）；`trade_records`；数据源稳定性（`etf` / `ny` 频繁降级 mock ⇒ `data_source='live'` 快照不足 ⇒ 回测 / 网格仍受限，属非代码问题）；V0.75.3 找回密码 + 用户管理页。

### V0.80.1 · prod 写端点自动附加 X-Admin-Token（hotfix）

**发布信息**：2026-10-08 ｜ commit `56c040e` ｜ 单文件单 commit、51+ / 17- ｜ 与上一版本 V0.80.0（2026-10-07，`b13c7fa`）间隔 1 天 ｜ 无 schema、无 i18n、无后端变动

**背景/问题**：prod 部署下用户在 `/static/news.html` 保存打分直接报 401 `admin token required`。根因是 V0.72.0 P3-b 上线的 `Depends(require_admin)` 守卫从未在客户端接上 —— 前端几十处裸 fetch 都没传 `X-Admin-Token` 头，dev 模式 `ADMIN_TOKEN` 未设所以从来没暴露。排查后确认涉及**所有写端点**：`PUT /api/v1/news-score`、`DELETE /api/v1/news-score/{slot}`、`POST /api/v1/portfolio/*`、`PUT /api/v1/settings/*`、`POST /api/v1/backtest/*`、`POST /api/v1/push/*`；症状只在 news-score 上暴露，是因为 news.html 的保存是 prod 用户每天都会点的写操作。

**修法**：

- 复用 V0.75.0 已有的 CSRF 自动注入模式 —— 在全站基座 `static/auth.js` 的 `patchedFetch()`（`static/auth.js:113-160`）里对同源写请求检查 `X-Admin-Token` 头，缺失时从 localStorage 的 `pm_admin_token` 读出并附加。
- 新增 `adminToken()` helper（`static/auth.js:76-83`）—— Safari 隐私模式 / cookie 禁用时视为未设。
- 设计取舍 —— 选 auth.js 而非 settings.js 是因为 auth.js 每页都加载，基座自治无反向依赖；不覆盖调用方显式传入的值；dev 模式读不到就不加头；三语 UI 不变（纯 fetch 打补丁，零可见 UI 变化）；服务端依赖、契约、数据库 schema 全不变。

**验证**：

- `node -c static/auth.js` syntax OK；`check_static_js.py` 13 页 + 23 脚本全过；`check_cluster_render.mjs` 222 / 222。
- 服务端 `require_admin` 路径逐条核对 —— `admin_token is None`（dev）→ return 不强制；token 存在且头缺失或不匹配 → 401。
- 浏览器手测（puppeteer 实跑）5 步 —— prod 配置启动 uvicorn（`APP_ENV=prod` + `.env.prod` 含 `ADMIN_TOKEN`）→ 设置页填 token 保存并确认 localStorage → news.html 保存打分不再 401 → Network 面板确认请求头含 token → 清除 localStorage 后回到 401（证明 token 来自 localStorage 而非写死）。

**教训**：CI 永远不会验这条 prod 路径 —— `tests/conftest.py` 走 `:memory:` SQLite 且 `ADMIN_TOKEN` env 不设，`require_admin` 直接 return，401 分支根本触发不了；puppeteer 手测是唯一能确认整条链路的手段。零后端改动的修法优先选「复用既有基座模式」，不引入新概念。

**遗留**：服务端 401 报错信息含糊（不区分「缺头」还是「不匹配」，排查时多绕一圈）；admin token 没统一管理（`app_settings` 混合表与 `.env.prod` 双源）；缺前端集成测试（没有「prod-mode 集成测试」覆盖 `require_admin` 真路径）。

### V0.81.0 · 找回密码 + 用户管理页（V0.75.3 收口）

**发布信息**：2026-10-09 ｜ tag `v0.81.0`（annotated）｜ 5 commit + 1 release commit、约 +2670 / -5 行 ｜ commit `c493b35`（找回密码底座）、`241bbfb`（找回密码端点）、`460af8c`（找回密码页面）、`1cc3362`（用户管理端点）、`ee0431f`（用户管理页面）｜ 与上一版本 V0.80.1（2026-10-08，`56c040e`）间隔 1 天

**背景/问题**：V0.75.0 上线注册登录后，唯一遗失密码的恢复路径是 owner 后台 SQL 直改 —— 本地单用户勉强能用，多用户场景下不可接受，用户找不回密码就直接流失。同时多用户场景下「owner 一个人管所有账号」成为必需：成员离职要停用账号并保留数据、邮箱失效要 owner 代重置、重复注册或违规账号要删除。

**修法**：

- 找回密码底座 —— 新增 `password_reset_tokens` 表（存哈希）与编排服务，迁移 `b4c6d8e2f0a1` 单步建表并加 user_id 索引。
- 找回密码端点 —— `POST /api/v1/auth/forgot-password`（输入邮箱 → 始终返回 200 的恒定响应）与 `POST /api/v1/auth/reset-password`（token + 新密码 → 一次性消费，重置成功撤销该用户所有会话）。
- 找回密码页面 —— `static/reset-password.html` 落地页 + 登录页入口。
- 用户管理端点 —— `GET /api/v1/admin/users`（分页 + 关键字）、`POST /api/v1/admin/users/{id}/reset-password`（owner 代重置，自动生成新密码返回）、`POST /api/v1/admin/users/{id}/set-active`（启停）、`DELETE /api/v1/admin/users/{id}`（删除）。
- 用户管理页面 —— `static/admin/users.html`（表格 + 操作列）+ 账号菜单「用户管理」入口（仅 owner 显示）。
- 邮件基础设施 —— 复用 `.env.prod` 已有的 `SMTP_HOST` / `SMTP_USER` / `SMTP_PASS` / `NOTIFY_FROM`，不引入新配置；dev 模式走 noop 实现，单元测试不依赖真实邮件服务；模板在 `src/app/services/password_reset.py:_render_email()` 内联生成 HTML + 纯文本双版本。

**验证**：

- 用例 1101 → 1176（+75，password_reset 36 + user_admin 30 + 集成 9）。
- `check_docs_claims.py` 413 处声明全找到；`ruff check src tests` All checks passed。
- `check_static_js.py` 15 静态页 + 23 共享脚本（新增 admin/users.html + reset-password.html）；`check_cluster_render.mjs` 222 / 222 passed；`check_pwa_assets.py` SHELL_ASSETS 28 条全可解析 + manifest 6 个目标全存在。
- `pytest tests/` 1176 passed / 0 failed。
- 测试覆盖 —— password_reset 36 例含哈希生成与校验、邮件限流触发、token 一次性消费（第二次 401）、过期路径、重置成功后撤销会话、用户不存在 vs 邮箱不存在的等价响应；user_admin 30 例含 owner / member 鉴权分流、防自锁、改密强度校验、软删与硬删、列表分页与关键字过滤、跨用户影响隔离。

**教训**：token 存 sha256 哈希不存原文，数据库泄露不等于 token 可用；`forgot-password` 即便邮箱不存在也走完整 token 生成 + sleep，防止用响应时间差探测账户是否存在；同一邮箱 60s 内最多 1 次、同一 IP 5min 最多 5 次；token 一次性消费由 DB 唯一约束 + `consumed_at` 双重保护，TTL 24h。owner 防自锁用 `require_owner` 依赖 + `is_self` 守卫双重保护；软删除默认（`is_active=False`，数据可恢复），物理删除需显式传 `?hard=true` 且保留审计日志；角色模型只有 owner / member 两类，schema 层 enum 限定；代重置的密码一次性返回、不持久化也不邮件发，owner 须线下传达。

**遗留**：代重置密码的传达通道（当前只能线下贴给用户，后续可考虑带一次性查看链接的临时邮件通道）；邮件模板单文件内联、未 i18n 化；多角色 RBAC（reader / editor / admin）留给 V0.83+；关键操作（改密 / 启停 / 删除）只入 telemetry 事件，没落专用审计表。

### V0.81.1 · admin token 缺失提示横幅（hotfix）

**发布信息**：2026-10-08 ｜ commit `2e9a7c1` ｜ `static/auth.js` +90 / -1 + 三语 i18n 各 2 键 + 版本号四处同步 ｜ 与上一版本 V0.81.0（2026-10-08，`8fff11a`）为同日第二个补丁版 ｜ 无 schema、无后端变动

**背景/问题**：局域网里其他主机打开页面，第一次保存打分直接 401 `admin token required`，页面只弹一句干巴巴的英文错误，用户不知道该去哪儿配。V0.80.1 的自动附加头依赖 localStorage 的 `pm_admin_token`，而 localStorage 按 origin 隔离（协议 + 主机 + 端口）—— 换一台机器（不同 origin）、首次访问、清过站点数据、隐私模式这四类场景下读到空值，不加头 ⇒ 401，且报错文案完全没有引导。

**修法**：

- 在基座里拦截而不是改几十处调用 —— `static/auth.js` 的 `patchedFetch()` 已经在包装所有 fetch，本版在这里**认错并引导**：响应 401 且 detail 为 `admin token required` 时调用 `showAdminTokenRequiredHint()`（`static/auth.js:125-160`）。
- 横幅实现 —— sessionStorage 标记 `pm_admin_token_hint_shown` 保证每会话只弹一次（否则重试 / 连续写操作会刷屏）；`injectAdminHintStyle()` 注入 `ADMIN_HINT_CSS`（`static/auth.js:92-113`），顶部 `position: fixed` + `z-index: 9999` 黄色告警条，带 slide-in 动画与移动端响应式；含图标 + 文案 + 「去设置」按钮 + 关闭按钮，不阻塞后续操作。
- 细节取舍 —— 判 detail 用 `resp.clone()` 读响应体，克隆后不影响调用方的 `resp.json()`；设置页 URL 自适应，`location.pathname` 含 `/gold/` 时跳 `/gold/static/settings.html`；新增 `admin_token.missing` / `admin_token.go_settings` 两键三语同步。

**验证**：

- `node -c static/auth.js` syntax OK；`check_static_js.py` 15 页 + 23 脚本全过；`check_cluster_render.mjs` 222 / 222；`check_docs_claims.py` 413 处声明全找到。
- `check_pwa_assets.py` 确认 `sw.js=v0.81.1` 与 `__version__=0.81.1` 一致；`check_links.py` 25 份文档 + 109 条内部链接；`ruff format --check` 213 files already formatted。
- 浏览器手测 5 步 —— prod 启动 → 清 localStorage → 出现顶部黄色横幅 + 「去设置」按钮（不是只有一行英文报错）→ 填 token 保存后回来写入成功且横幅不再出现 → 同一会话再触发 401 不重复弹。

**教训**：老浏览器装的 Service Worker 缓存名依赖 `sw.js` 的 VERSION，不换代就拿不到新的 auth.js，横幅永远不会出现 —— 版本号必须按 `src/app/__init__.py` 的清单四处同步（`__version__` / `pyproject.toml` / `uv.lock` / `static/sw.js`），sw.js 的 shell / runtime 缓存名随之换代。全局拦截优于逐页改：news / portfolio / weights 等几十处裸 fetch 完全不用动，逐个加 catch 会漏；用 sessionStorage 而非 localStorage 标记，是因为这个提示只该活在当前会话，换机器要重新提示一次。

**遗留**：prod 401 路径无自动化测试 —— 补一个 `ADMIN_TOKEN` 已设的 conftest 变体是根本解法；服务端 401 文案仍未细分「缺头」与「不匹配」（V0.80.1 遗留项原计划 V0.81.0 做，未落地）；`app_settings` 混合表双源问题仍在。

### V0.82.0 · admin session cookie + 单用户模式豁免（LAN 多终端）

**发布信息**：2026-10-09 ｜ commit `341934c` `2621cd1` `f46838b` `e0305fe` + `c9b8d04`（admin-token 端点）+ 版本号 5 处 ｜ 与上一版本 V0.81.1（2026-10-08，`2e9a7c1`）

**背景/问题**：LAN 部署（`192.168.0.204:8889/gold/`）下多个终端首次保存打分直接 401，即使按 V0.81.1 横幅提示去设置页配过 token，其他终端（不同浏览器 / 不同设备）打开仍是 401 —— localStorage 按 origin 隔离，配过不算。横幅本身也是被动响应（必须先踩 401 才知道要去设置），新用户根本不知道有这回事。理想体验应是：浏览器打开 URL 即可写，整个设备生命周期不需要任何手动配置。

**修法（双管齐下）**：

- Cookie session（端到端）—— 新增 `pm_admin_session` HttpOnly cookie，HMAC-SHA256 签名（密钥就是 `ADMIN_TOKEN` env），30 天 TTL；新增 `issue_admin_session_cookie_value()` / `verify_admin_session_cookie()` 两个纯函数；新增 `require_admin_session` 依赖，同时接受 `X-Admin-Token` header 或 cookie，任一通过即放行，同时保留 `require_admin` 旧语义供 CI / 脚本使用。
- 18 处端点迁双通道 —— `news` / `backtest` / `account` / `settings` / `push` / `position` 共 6 个端点文件里的 `Depends(require_admin)` 换成 `Depends(require_admin_session)`，否则 cookie 即使存在也走不通。
- 单用户模式豁免 —— `AUTH_ENABLED=false` 时 `get_admin_token()`（`src/app/dependencies.py:147`）返回 None，`require_admin` 与 `require_admin_session` 整体 skip，LAN 默认配置从此零摩擦。
- admin-token 端点 —— `POST /api/v1/admin-token`（校验 body.token 与 ADMIN_TOKEN env 匹配后下发 cookie）、`DELETE /api/v1/admin-token`（清 cookie）、`GET /api/v1/admin-token`（返回 has_session / ttl_seconds / auth_enabled）；settings.html 新增 Session Cookie 卡片，含「设置 Session」/「撤销 Session」按钮与状态行，单用户模式时按钮禁用 + 灰色提示。
- 附带 fix —— Auth/CsrfMiddleware 在 `__init__` 里缓存 settings，导致测试改 `auth_enabled` 时中间件看不见（csrf cookie 不下发 ⇒ write 端点 403 ⇒ 12 fail），移除缓存改为每请求重取 `get_settings()`。

**验证**：

- `pytest tests/` 全量回归 1198 passed / 0 failed。
- `test_admin_auth_v82.py` 13 例双通道与单用户豁免；`test_admin_token_endpoint.py` 13 例（POST / DELETE / GET + 单用户）；旧 `test_admin_auth.py` fixture 加 `AUTH_ENABLED=true` 后 5 例。
- `ruff check src tests` All checks passed；`check_static_js.py` 15 页 + 23 脚本；`check_cluster_render.mjs` 222 / 222。
- 端到端 curl —— GET 200（has_session false / ttl 2592000 / auth_enabled true）、错 token 401、正确 token 200 + Set-Cookie（HttpOnly + Max-Age + Path + SameSite=lax，另有 pm_csrf 联动）、带 cookie 200、DELETE 200 清空。
- 浏览器手测 settings 页 5 步状态流转，并确认 V0.81.1 横幅在清 cookie + 清 localStorage 后仍正常弹出。

**教训**：豁免要写在依赖层（`get_admin_token()` 返回 None）而不是每个端点写 if 判断，LAN 默认配置才真正零摩擦；`/api/v1/admin-token` 必须加入 `PUBLIC_API_PATHS`，否则未登录用户看不到 cookie 状态，形成「登不进来 → 看不到状态 → 永远登不进来」的死锁；错误响应统一 401 且不区分「缺」与「错」防枚举，比较用 `secrets.compare_digest`；GET 只返 has_session 布尔，不返回 cookie 值 / 签名 / 任何凭据细节。无状态 cookie 而非服务端 session 表，是因为 LAN 单机部署无 Redis，无状态 cookie 跨重启不失效、签名自带时间戳省一次 DB 读。

**遗留**：prod 401 路径仍无自动化测试；`/admin-token` 错误响应缺恒定延时（注释里已标，生产可加 0.5s sleep）；`AUTH_ENABLED=true` 切换器需同步 `docs/deployment.md`；Cookie 主动吊销未做（远程踢人须改服务端 session 表）。

### V0.83.0 · 主页 UI 改版 + 8 页面警示合并 + 静态门禁强化

**发布信息**：2026-10-10 ｜ commit `7729646` `37a5149` `ed4f886` `44b98c3` `3fdbb85` `ec77ee9` + 版本号 4 处 ｜ 与上一版本 V0.82.0（2026-10-09，`6525378`）

**背景/问题**：登陆主页信息密度高，时效分散在 3 处（每张 KPI 卡单独的 fsh-cell + hero 的 notice 重复），单行 nav 的 11 条链接在窄屏要么横向滚动要么 wrap 破版；投资警示沿用 V0.40 时代的「全屏显眼」设计，每页一段全屏宽度 warn-banner，5 条 bullet 占 200+ 像素，把研判主图挤到第二屏；help.js 数据来源 tab、各页 warn-banner 与 settings 帮助区三处重复几乎一样的免责文案，3 语各重复 3 次约 18 条冗余条目。

**修法（6 个 commit）**：

- 主页 redesign —— 双行顶 nav（`#1f2329` 渐变 + brand + 11 链接 + `#freshnessInline` 挂载点）；警示 disclosure 改 `<details id="warnFooter">` 替换旧 `<div class="warn-banner">`；移除与主图标题重复的 hero notice；新增 `static/warning.js` IIFE helper（sessionStorage `pm_warn_dismissed_session`）。
- 顶 nav i18n 修复 —— `i18n.js:115-127` 的 insertBefore 把 `data-i18n` 文本塞到第一个子节点前面，导致 emoji 图标与文本同时被覆写；改为把 text 节点下移到内层 span。
- a11y 兜底 —— warning.js 绑定 `aria-describedby="warnDismissHint"`；theme.css 补 `[data-theme="hc"]` 高对比 4 条覆盖（黄前景 + 黑背景，WCAG AAA ≥7:1）；summary 触控目标 `min-height: 44px`。
- freshness 优化 —— 状态签名 `lastSig` / `sig()` 跳过相同状态重渲染（避免每 60s 重复 announce）；离线缓存 chip 加 `fsh-cached-chip` class 幂等检查；help.js 合并重复警示文案并新增 `help.source_warn_prompt` 指向各页底部 disclosure 与 `#warn` 深链。
- 8 页面迁移 —— silver / portfolio / weights / trades / backtest / data-health / central_bank / review 全部套用 topnav + warn-footer + freshnessInline；并补齐 zh-TW 缺失的 9 条 i18n key（`central_bank.warn_b3_pre/strong/rest`、`central_bank.warn_b4_pre/strong/rest`、`backtest.warn_b1-b4_strong/rest`、`silver.warn_b5_strong/rest`）。
- 静态门禁强化 —— `check_cluster_render.mjs` 追加 V0.83 节 73 条断言；新增 `scripts/check_i18n_keys.py`（支持 key 回落链，V0.83 命名空间严格模式，exit 1 拦回归）与 `scripts/puppeteer_v083.mjs`（8 页 × 3 语 × 3 主题 = 72 组合实跑）。

**验证**：

- `check_static_js.py` 15 页面 + 24 共享脚本全通过；`check_cluster_render.mjs` 295 / 0（含 V0.83 节 73 条新断言）。
- `check_i18n_keys.py` V0.83 scope 0 missing / 59 in-scope；`--all` 全量报告 110 missing / 450 used（预存 gap 独立 ticket）。
- `puppeteer_v083.mjs` 1418 / 0（72 组合 × 约 20 断言，覆盖双行 nav、brand 文本、11 链接、当前页 active 匹配、`#freshnessInline` 的 aria-live=polite、warn-footer 真实渲染无 raw key、nav-warn-toggle 点击切换与 aria-expanded 同步、dismiss 写 sessionStorage、HC 主题对比度、跨页 4 页通用 5 条 bullet 文本一致、`#warn` 深链默认展开）。
- 端点 curl 确认 `/api/v1/market/freshness` 返回 3 个市场；浏览器人工补查 9 项（含 375px 窄屏不溢出、VoiceOver / NVDA 下顶 nav 元信息行不被频繁打断）。

**教训**：共享 topnav 刻意不抽文件 —— 纯静态 HTML 无 build 步骤，JS 注入 nav 会引入 FOUC 且破坏 view-source UX，留作独立 PR。portfolio.html 旧的整段合并键（`warn.b1-b5`）导致 zh-TW 缺 key、静默回退到 zh-CN 渲染，改成 `_strong` / `_rest` 配对键复用已有命名空间。central_bank 的 4 条领域特有警示与 data-health 的蓝色 accent（`#1d4ed8`）刻意保留品牌差异，只换容器不迁文案。`check_i18n_keys.py --all` 暴露的 110 个预存 gap 是门禁第一次把「静默回退到默认语言」变成可见输出。

**遗留**：110 个 i18n 预存 gap 单独 ticket 跟踪；8 页复制粘贴的 nav markup 后续会 drift，建议抽 `static/_topnav.js` 或 build-time 模板生成；drawer / palette / cluster 等组件是否也走 V0.83 模式待定（V0.83.0 仅完成页面级主体）。

### V0.83.2 · 共享 topnav 抽离

**发布信息**：2026-10-10 ｜ roadmap §4.1 M · P1 ｜ 范围：纯前端（HTML + 1 个新 JS + 3 个 gate 脚本）｜ 新增 1 个文件、修改 8 个页面与 3 个门禁脚本

**背景/问题**：V0.83.0 把 trend.html 的双行 nav 模板复制粘贴到 8 个页面，每页约 2000 字符的 nav markup（`<nav class="topnav">` + 11 个 `<a>` + brand + freshnessInline + warn-toggle），合计约 16KB 重复：每次新增或删除一个页面或链接要改 8 处；i18n `data-i18n` 属性散在 8 个 HTML，zh-TW 漏补的风险成倍上升；brand 文案与 emoji 微调要改 8 遍。

**修法**：

- 新增 `static/topnav.js`（111 行、约 4.2KB）作为 nav 的单一来源 —— 11 条 `NAV_LINKS` 配置（每条带 path / activeFor / ico / i18n / fb 中文兜底），4 个特殊 `BRAND_BY_PATH`（silver / backtest / data-health / settings）+ `DEFAULT_BRAND`（黄金主页）。
- 同步注入实现零 FOUC —— script 紧跟 `<div id="topnav-mount">` placeholder，无 defer / async，用 `outerHTML` 替换 placeholder，body 还没解析到 main 内容前完成。
- active 自动判定用 `l.activeFor.indexOf(location.pathname) >= 0`；i18n 走既有 `data-i18n` 协议由 i18n.js（defer）翻译。
- 8 个页面的 nav 块整块替换为 placeholder + script 引用，从 2000+ 字符降到 25 字符 / 页，合计 -16KB HTML 体积。

**验证**：

- `check_static_js.py` 15 页面 + 25 共享脚本（新增 topnav.js）全 OK；`check_cluster_render.mjs` 319 / 0。
- `check_i18n_keys.py` 0 missing / 58 in-scope；`--all` 0 missing / 459 in-scope；`node --check static/topnav.js` syntax OK。
- `puppeteer_v083.mjs` 1418 / 0（8 页 × 3 语 × 3 主题 + `#warn` 深链）。
- 兼容性 —— 渲染出的 DOM 与 V0.83.0 迁移后完全一致（puppeteer 实跑断言 11 链接、active、brand、topnav-meta、warn-toggle、freshnessInline 全部同形态）；标准 DOM API + ES5 var 语法，Chrome / Firefox / Safari 现代版全支持。
- i18n 增量为 0 —— nav 与 brand 的 key 在 V0.83.0 与 V0.83.1 已 3 语全覆盖。

**教训**：active 判定最初用 `l.path === activePath` 严格匹配，但用户点 `/portfolio` 链接后 FastAPI 会重定向到 `/static/portfolio.html`，`location.pathname` 对不上导致 active 丢失 —— 改为每条 link 显式列 `activeFor` 数组同时容纳两个形态，7 条有重定向的 link 都补齐。`check_i18n_keys.py` 必须补 JS 字面扫描正则，否则 topnav.js 里的 nav / brand key 完全不被门禁覆盖，删除或重命名仍能过 gate；补上之后这批 key 第一次被强制检查。`puppeteer_v083.mjs` 间隔从 2.5s 调到 3.5s —— dev server 5 req/s 限流下 2.5s 间隔会出现 19/72 偶发 429，多次重跑确认是限流而非逻辑问题。

**遗留**：roadmap §4.1 剩余改进项 K（多市场参数差异化，P3 长线），V0.84+ 评估。

### V0.83.3 · 限速中间件 /static/ bypass + 默认 600/min

**发布信息**：2026-10-10 ｜ 类型：Bugfix（用户报「主页数据时效加载失败」误报）｜ 非 §4.1 计划项，V0.83 收尾 ｜ 修改 11 个文件

**背景/问题**：用户报告「主页提示数据时效加载失败，什么问题」。根因不是 V0.83 的代码 bug —— `src/app/middleware/rate_limit.py:30-33` 的限速中间件对**所有路径**都计数，默认 `rate_limit_per_min = 120`（per-IP 60s 滑动窗口），与 docstring 第 11 行承诺的「不挂在 `/static/`」实现不一致；单次页面加载触发 HTML + 5 JS + 2 CSS + favicon + 1 API 约 10 请求，`freshness.js:241` 每 60s 再加 1，LAN 用户多标签页几分钟内必打满 120 触发 429。用户看到的「数据时效加载失败：HTTP 429」正是 429 传到前端后的渲染结果。附带一个 i18n 漏洞：`freshness.js:233` 引用 `fresh.load_failed_suffix` 但 3 语字典都没定义，走 DEFAULT_LANG 兜底并同时产生 `i18n_fallback_hit` telemetry 噪声。

**修法**：

- `/static/` 路径 bypass —— `dispatch()` 里判断 `request.url.path.startswith("/static/")` 直接放行；新增 `skip_static` 参数默认 True（与 docstring 承诺对齐）；`config.py:91` 新增 `rate_limit_skip_static: bool = True`，env `RATE_LIMIT_SKIP_STATIC=false` 可关闭（极端 DoS 场景）。
- 默认限速 120 → 600 —— bypass 后仅 `/api/*` 进入滑动窗口，600/min 给多标签页 + 轮询留足余量（约为当前用量的 10 倍）；写端点（POST / PUT / DELETE）的业务级限速不在这层，由各 endpoint 自管。
- 顺手补 i18n 漏洞 —— `fresh.load_failed_suffix` 三语各补 1 条，inline 兜底文本不再触发 telemetry 噪声。

**验证**：

- `tests/test_middleware/test_rate_limit.py` 新增 2 个断言后 8 passed in 2.47s —— `test_static_path_bypasses_limit`（30 次 `/static/ping` 全 200，同期 `/api/ping` 第 6 次 429，证明中间件没完全失效）与 `test_static_skip_can_be_disabled`（`skip_static=False` 时 `/static/ping` 也计入，第 3 次 429）。
- 部署验证 —— 30 次 `/static/` 突发 30/30 = 200（bypass 生效），30 次 `/api/` 突发 30/30 = 200（600/min 充足），429 路径 puppeteer 验证显示「数据时效加载失败：HTTP 429（不影响页面其他数据）」。
- `check_static_js.py` 15 页 + 25 脚本；`check_cluster_render.mjs` 319/0；`check_i18n_keys.py --all` 0/459。

**教训**：实现与自己的 docstring 不一致，等于承诺已经失效 —— 加 bypass 时应先让代码对齐已写下的契约，而不是反过来改契约。3 语 i18n 缺一个 key 不会让页面报错，但会让非默认语言静默回退到默认语言并持续产生 telemetry 噪声，这类「不报错」的缺口同样需要门禁。限速阈值必须与页面实际请求数一起算：单页约 10 请求 + 60s 轮询，120 的阈值在多标签页场景下天然会被打满。

**遗留**：freshness 遇 429 时的用户友好降级 UI（如改为「时效暂时不可用」而非错误样式）留 V0.84+ 评估；`nav-drawer.js:117` 的 insertBefore 报错独立 ticket 跟踪；写端点业务级限速（当前各 endpoint 自管，无统一配额）留 V0.84+ 评估。

### V0.83.4 · freshness 降级 UX 重设计 + sig() 关键 bug 修复

**发布信息**：2026-10-10 ｜ 类型：UX 重设计 + 关键 bugfix ｜ 非 §4.1 计划项，V0.83 收尾 ｜ 核心改动 `static/freshness.js` + 三语各 2 个新 key

**背景/问题**：用户报告「主页的数据时效 换一个显示方式，避免这样影响用户体验的设计存在」—— V0.83.3 修完限速后，错误态的 UX 仍然很差：「数据时效加载失败：HTTP 429」红框 + 错误样式占据顶 nav 整行，比「显示陈旧数据」更干扰用户。顺手还挖出一个用户没报但更严重的 bug：V0.83.0 引入的 `sig()` 对 `markets` 调 `.map()`，但 `/api/v1/market/freshness` 实际返回 `markets` 是按市场名 key 的 dict，`dict.map` 不存在 ⇒ TypeError，异常被 catch 吞掉 —— V0.83.0 到 V0.83.2 三个版本期间 freshness bar 一直处于「错误态 + 红色显示」状态，而 puppeteer 测试用假数据掩盖了它。

**修法（UX 重设计）**：

- 首次失败 —— 显示中性的「⏳ 数据加载中…」（`fresh-inline`）。
- 成功后再失败 —— 保留末次 chips（半透明 0.55）+ amber 色「⏳ 离线/缓存（数据可能过期）」chip 并加 `fsh-stale` class。
- 再次成功 —— 恢复正常 chips 并清 stale 状态（`lastSig = null` 强制 render 重写 DOM）。
- 关键不变量 —— 绝不显示红框 / `fsh-error` class / 「失败」字样；末次数据必须保留（用户能看见市场状态）；stale chip 用琥珀色而非红色，表明「数据可能过期」但不暗示「应用故障」。

**修法（智能退避）**：

- `BACKOFF_MS = [60000, 120000, 300000, 600000]` —— 0 次失败 60s、1 次 120s、2 次 300s、3 次以上封顶 600s，成功一次重置回 60s。
- 把 `setInterval` 换成自递归 `setTimeout` 才能动态调整间隔；429 限流时不再每 60s 反复打 API，最多 600s 才重试一次。

**修法（关键 bug）**：

- `sig()` 修复为与 `render()` 共用同一组 `order` 序列（ny / sge / etf），dict 与 array 都兼容。
- `fsh-cached-chip` 颜色从 `fsh-bad`（红）改为 `fsh-warn`（琥珀），与「加载失败」红框做语义区分。

**验证**：

- puppeteer 实跑 4 场景全 PASS —— 成功显示 chip、首次失败为中性「数据加载中…」无红框、成功→失败保留末次数据且 chip 半透明 + 追加 stale chip、失败→成功清 stale 状态。
- 静态门禁全绿 —— `node --check static/freshness.js` syntax OK；`check_i18n_keys.py --all` 0/459；`check_static_js.py` 15 + 25；`check_cluster_render.mjs` 319/0；`test_rate_limit.py` 8/8。
- 新增 `fresh.stale_chip` / `fresh.loading_first` 两 key × 3 语；旧 `fresh.load_failed` / `fresh.load_failed_suffix` 保留在字典（其他模块可能用），但 freshness.js 不再引用。

**教训**：puppeteer 的 mock 数据必须与真实 API schema 一致 —— 用假数据测渲染只会证明渲染函数本身没问题，掩盖了字段形态不匹配。降级态的设计要回答两个问题：末次数据还给不给看（要给），以及用什么颜色（用 amber 而不是红，红等于向用户宣告「应用坏了」）。退避把 `setInterval` 换成自递归 `setTimeout` 才谈得上「智能」，固定间隔只是把 429 打得更频繁。

**遗留**：失败时的 console.warn（方便 dev 调试）留 V0.84+ 评估；「离线/缓存」chip 可点击手动重试 UX 调研中；service worker 缓存策略与本版的协同（SW 仍在响应时浏览器层就会缓存响应，puppeteer 测试时遇过这个坑，生产不受影响）。

### V0.84.0 · 状态条方案 C · 数据时效 + 警示合并 1 行

**发布信息**：发布日期 — ｜ 范围：9 个 HTML 页面 + topnav.js / warning.js / i18n.js / theme.css / check_cluster_render.mjs + 版本号 3 处 ｜ 用户选定方案 C

**背景/问题**：用户原话「数据时效，投资警示，可以作到 1 行，并且进行合并显示给信息提供更好的显示版面」，并要求先给方案由用户决定方向。此前顶 nav 占两行（brand + 11 链接一行，时效 chips 与警示按钮一行），底部还有一个展开后约 80px 的警示 details，共 3 行。

**修法**：

- 采用用户选择的方案 C（单一 disclosure 统一处理，4 个方案中推荐且节省最多版面）—— 顶部只保留 1 行 brand + 11 链接，下面放一个 `<details id="statusPanel">`，summary 里同时放时效 chips 与「⚠️ 投资警示 N 条要点」pill，展开后是警示 bullets 与「本次会话不再展开」复选框，底部旧的 `<details id="warnFooter">` 删除，净省约 80px（首次访问看到 1 行而非 3 行）。
- `static/topnav.js` —— 删除 row 2 的 `.topnav-meta` 注入，只保留 1 行 brand + 11 链接。
- `static/warning.js` —— 监听 `#statusPanel`（不再是 `#warnFooter`）；按 `<ol>` 实际 li 数动态写 `[data-warn-count]`；新增 `hashchange` 监听，让同页 hash 跳转也响应 `#status` 深链。
- `static/i18n.js` —— 修 init() 漏 `await loadLang(saved)` 的 bug（saved 非 zh-CN 时 reload 仍显示中文）。
- `static/freshness.js` —— 未改动（挂载点 `#freshnessInline` 仍可用，只是不在 topnav-meta 而在 statusPanel summary 内）。
- 9 个 HTML 页面 —— 删 `.topnav-meta` CSS 与 `.warn-footer` CSS（替换为 `.status-panel` CSS），移除旧 `<details id="warnFooter">`，新增 `<details id="statusPanel">`；保留 4 页的蓝色 accent（silver / data-health 的 `#1d4ed8`）与 8 页的页面特定 i18n keys。
- 其他 —— `static/theme.css` 的 HC 高对比覆盖改名；`check_cluster_render.mjs` 的 V0.83 C4 段重写为 V0.84 段；版本号 v0.83.4 → v0.84.0。
- i18n —— 新增 2 个 key × 3 语 = 6 条（`status.warn_pill_label` 投资警示 / Notice / 投資警示；`status.warn_pill_unit` 条要点 / points / 條要點），不用 `{n}` 参数化。

**验证**：

- `check_static_js.py` 15 个静态页面内联脚本 + 25 个共享脚本全部通过；`check_cluster_render.mjs` 376 passed / 0 failed；`check_i18n_keys.py` 0 missing / 57 in-scope；`check_pwa_assets.py` PWA 资源门禁通过。
- `check_v084.mjs` 27 / 27 PASS（9 页 × 3 语）—— 校验 statusPanel 结构、freshnessInline mount、status-warn-pill、dismiss 复选框、折叠态、3 语 label 与 unit 正确、旧 markup 全部清除（warnFooter / warn-footer / topnav-meta / nav-warn-toggle）。
- `check_v084_interactive.mjs` 5 / 5 PASS —— 点击展开 + dismiss + reload 持久化 + `#status` 深链 + 截图。

**教训**：新 key 不做 `{n}` 参数化，拆成 label + count + unit 三段避免 i18n 参数复杂度。风险清单逐条对冲 —— dismiss 后同页 `#status` 跳转不响应靠 warning.js 加 hashchange 监听；折叠态 body 在部分浏览器不自动 hide 靠显式 `.status-panel:not([open]) > .status-body { display: none }` 解决；`[data-warn-count]` 不带 `data-i18n` 属性由 warning.js 单独控制，避免被 i18n.js apply 覆盖；警示标签用不带 emoji 的 `status.warn_pill_label`，⚠️ 由独立 span 控制以免双 emoji；news.html 用旧的 `.w-title` 模式不受影响，保留 `warn.title` / `warn.collapse_toggle` 两个 key。

**遗留**：共享 topnav.js 进一步抽离（仍保留外联引入 + 模板字符串拼接模式）留作未来 ticket；status panel 的 hover / focus 视觉强化（键盘 Tab 高亮、summary 焦点环）留 V0.85；真实 backtest 数据 Sharpe 对比留待 V0.79.0 Step F 二次复查；freshness 离线缓存 chip 显隐逻辑留 V0.85 评估。

### V0.85.0 · 数据时效迁移到 /data-health.html + 主页版面优化

**发布信息**：发布日期 — ｜ 范围：9 页 statusPanel summary 改造 + 新增 `static/health-summary.js` + trend.html 折叠改造 + 7 个 i18n key × 3 语 ｜ 用户选定方案 A（状态条瘦身 + 主页紧凑化）

**背景/问题**：用户原话「数据时效移动到数据健康页面，并对主页版面进行优化」。此前每页的 statusPanel summary 都铺开 3 个市场时效 chip（约 600px 宽），进入数据健康页还会被同样内容重复披露刷屏；主页「每日评估历史」面板把 4 张极值卡 + 260px 图表 + 区间按钮全铺在首屏。

**修法**：

- 新增 `static/health-summary.js`（约 282 行，自洽 IIFE，挂载点 `#healthSummary`）—— 数据源 `GET /api/v1/market/health`，每 60 秒自动刷新，失败时 60→120→300→600s 智能退避；6 数据源状态聚合为 live / stale / mock / unknown 4 类。
- 两种渲染模式 —— 8 个非 health 页用 chip 模式（一个链接，显示「5/7 实时 · 2 缓存 →」，`stopPropagation` 阻止冒泡到 summary）；data-health.html 用 panel 模式（4 个 mini-chip：数据源 / 实时 / 缓存 / 演示）。CSS 自注入，与 freshness.js 的暗底 chip 风格统一；失败降级保留末次数据 + 透明度 0.55（沿用 V0.83.4 的 stale 模式）；HC 高对比模式覆写黑底黄字。
- 9 页 statusPanel summary 同步改造 —— backtest 与 central_bank 原先缺 freshness.js（V0.84 历史 bug，`#freshnessInline` 一直空）本次补上 health-summary.js；data-health / portfolio / review / silver / trades / trend / weights 删除 freshness.js 改用 health-summary.js；CSS 选择器 `#freshnessInline` 同步改为 `#healthSummary`。
- 主页 history 面板默认折叠 —— 改为 `<details class="panel panel-collapse">`，从约 340px 收到约 50px，首屏省 290px（4 张极值卡 + 260px 图表 + 区间按钮全部进折叠体）；配套 `.panel-collapse` 4 条 CSS。

**验证**：

- `check_static_js.py` 15 个静态页面内联脚本 + 26 个共享脚本全部通过（新增 health-summary.js）。
- `check_cluster_render.mjs` 437 passed / 0 failed —— 新增 V0.85 节 63 条断言，旧 V0.84 节改写后净增 61。
- `check_i18n_keys.py` 0 missing / 57 in-scope。
- `check_v085.mjs` 51 passed / 0 failed —— 27 条渲染断言（9 页 × 3 语，校验 mount 点存在 + i18n title 正确 + live/total 数字渲染）+ 24 条 chip-click 交互断言（8 chip 页 × 3 语，验证点击不展开 statusPanel 即 stopPropagation 生效）。
- 新增 7 个 key × 3 语 = 21 条（hs.title / hs.sources / hs.live / hs.stale / hs.mock / hs.unknown / hs.loading）。

**教训**：chip 模式与 panel 模式分离是刻意的 —— 非 health 页只回答「数据新不新」，完整 6 数据源视图留给 /data-health.html 一处披露，避免每页重复刷屏。`<a>` 放在 `<summary>` 内点击会触发 disclosure 切换，必须 `stopPropagation` + href 跳转先发生；失败时 chip 显示「数据加载中…」而不是留空白，摘要区留白比显示中间态更糟。history 折叠不影响 DOM 初始化，用户主动展开后才看到极值卡。

**遗留**：trend.html 的 sge / cmp / kline 三个图区合并留 V0.86 评估；health-summary 接入 SW 离线缓存披露留 V0.86；chip 内置历史趋势 sparkline（显示过去 N 次 chip 颜色）留 V0.87；synthesis-card 接入数据源健康指示留 V0.86。

### V0.86.0 · 决策可解释性增强（拆解 + 对比 + tooltip 三件套）

**发布信息**：发布日期 — ｜ 范围：新增 `static/decision-explainer.js` + synthesis-card.js / portfolio.html / trend.html 三处集成 + 42 个 i18n key × 3 语 ｜ 用户从 4 个方案中选定方案 A

**背景/问题**：用户从 4 个方案中选了方案 A（决策可解释性增强），推迟方案 B（三市场对照可视化升级，V0.87 评估）、方案 C（多账本模板与复盘助手，V0.88 评估）、方案 D（移动端 PWA 体验优化，V0.89 评估）。此前的决策面板只有「决策行动 + 置信度 + 一句话总结 + 3 条 factor rows + 指数构成条形图」，用户看不到「为什么是这一档」和「跟现在持仓差多少」。

**修法**：

- 新增 `static/decision-explainer.js`（约 340 行，自洽 IIFE）提供 5 个能力 —— `breakdownRows(decision)` / `renderBreakdown()`（综合指数按权加权拆解 + 公式行）、`compareCard(decision)`（「按当前建议应加减」对比卡）、`tooltipFor(action, ctx)` / `renderTooltip()`（hover 决策行动的 3 行解释）、`dimensionBars(components)`（三维横向条形图）、`attachTooltip(anchorEl, action, decision)`（hover / focus 弹窗监听）。
- synthesis-card.js 集成 —— `.syn-action` 加 `de-action` class 与 `data-de-action`，`.syn-bars` 后插入对比卡与拆解，render 末尾自动重新挂 attachTooltip。
- portfolio.html 集成 —— 决策面板 `.badge` 加 `de-action` class，`position-rec` 后插入对比卡，`buildComposition` 后插入拆解，`loadDecision()` 末尾挂 attachTooltip。
- trend.html —— 加载 `decision-explainer.js`（synthesis-card.js 依赖它）。

**验证**：

- `check_static_js.py` 15 静态页 + 27 共享脚本全过（新增 decision-explainer.js）。
- `check_cluster_render.mjs` 437 passed / 0 failed（无回归）；`check_i18n_keys.py` 0 missing / 57 in-scope。
- `check_v086.mjs` 36 passed / 0 failed —— 2 页 × 3 语 × 6 断言，每组合验证 `.de-action` 存在 + compareCard + renderBreakdown 三行加公式 + attachTooltip + i18n 翻译 + hover 弹出 3 行 tooltip。
- 新增 42 个 key × 3 语 = 126 条（3 行动 × 3 行解释 = 27 行 + 15 个通用 key）。

**教训**：字段名拼错会静默渲染 undefined，用 hasOwn + 默认值保护，缺失行显示「— 未计入」；`trend_index.score` 为 null 时拆解会崩，用 typeof 判断守卫；i18n 字典缺 key 时用 `T(key, fallback)` 回退中文，绝不渲染 key 字面量；`position_ratio` 恒为 0 时对比卡显示「未录入本金」会让用户困惑，回退成「建议重仓建仓至 X%」这类描述性文案，不伪造金额；attachTooltip 每次重渲染都挂新 tip 元素、离开时隐藏，避免监听累积泄漏；tooltip 用 `position: absolute` + `z-index: 9999` 且 mouseenter 后才显示，避免遮挡下方内容。

**遗留**：方案 B / C / D 分别留给 V0.87 / V0.88 / V0.89 评估；decision-explainer 接入 SW 离线缓存、breakdown 行点击下钻到单维度详情、tooltip 显示共振信号明细，均留 V0.87 评估。

### V0.86.1 · 数据健康跳转 404 hotfix

**发布信息**：发布日期 — ｜ 范围：`src/app/main.py` 加双别名 + health-summary.js 与 8 个 HTML 的 chip href 升级 + sw.js SHELL_ASSETS 与 VERSION + 2 个门禁脚本断言同步

**背景/问题**：用户报告「现在通过内网测试主页发现数据健康的链接点击后出现 detail not found」。根因是 V0.85.0 引入的 chip 链接指向 `/data-health.html`，但 `src/app/main.py` 的根路径别名列表漏注册 `/data-health` 别名 —— 该路径既不是根路径别名（没有 `@app.get` 装饰），也不是 `StaticFiles` mount 的 `/static/` 前缀路径，FastAPI 默认返回 404。curl 现场：`/data-health.html` 返回 404，而 `/static/data-health.html` 返回 200（文件本身可访问）。

**修法**：

- 主修复 —— `main.py` 加 `/data-health` 与 `/data-health.html` 双别名，都是 307 重定向到 `/static/data-health.html`；后者为向后兼容 V0.85.0 的 chip 直链与外部书签。
- 升级（kebab-url 一致性）—— `health-summary.js` 与 8 个 HTML 的 chip href 从 `/data-health.html` 升级到 `/data-health`，与 `/portfolio`、`/central-bank`、`/trades` 等风格一致；偏离「直链静态文件」的设计，chip 现在走 FastAPI 别名（307），服务可控。
- SW 缓存 —— `sw.js` 的 SHELL_ASSETS 加 `/data-health`，VERSION bump 到 `v0.86.1`（缓存名从 `gold-shell-v0.86.0` 换代，触发浏览器重新安装 SW + 清缓存）。
- 测试同步 —— `check_cluster_render.mjs` 与 `check_v085.mjs` 的 chip href 断言从 `/data-health.html` 改为 `/data-health`。

**验证**：

- curl 端到端 —— `/data-health` 返回 307 且 Location 指向 `/static/data-health.html`，`/data-health.html` 返回 307，跟随重定向后 200。
- `check_static_js.py` 15 静态页 + 27 共享脚本全过；`check_cluster_render.mjs` 437 passed / 0 failed；`check_i18n_keys.py` 0 missing / 57 in-scope。
- `check_v085.mjs` 51 passed / 0 failed（chip href 断言同步后）；`check_v086.mjs` 36 passed / 0 failed（V0.86.0 决策可解释无回归）。

**教训**：新增静态页必须同步注册根路径别名 —— main.py 的别名列表是「白名单」，漏一个就 404；V0.85.0 引入 data-health.html 时没有「GET 返回 4xx」的断言，导致全部门禁通过但真实跳转 404，`check_pwa_assets.py` 只校验 SW SHELL_ASSETS，不验证 HTTP 200。chip href 走直链静态文件是「碰巧能用」—— 一旦 main.py 加了新路由优先匹配，static 直链就会失效（FastAPI 路由顺序）；升级到别名后跳 307 是显式可控的。测试必须涵盖 HTTP 状态 —— puppeteer 只验证 `document.body` 渲染，不验证 URL 跳转是否 200。

**遗留**：SW 缓存策略重构（cache-first → stale-while-revalidate）留 V0.87；所有静态页面 mount 到根路径（去掉 `/static/` 前缀）留 V0.88 评估，影响面大；根路径别名自动生成（扫描 static 目录自动注册）留 V0.88 评估 —— 即补 `scripts/check_routes.py` 做路由级 HTTP 门禁。

### V0.87.0 · 维护线：覆盖率扩充 + broken link 回归防护

**发布信息**：发布日期 — ｜ 依据 roadmap §11 V0.87+ Backlog 推荐组合 ｜ 零用户面变更、零功能变更，纯维护 ｜ 总测试数 1159 + 1 failed → 1237 passed（+77 例、1 失败修复）

**背景/问题**：本版聚焦测试基线扩充而非新增功能：src/ 覆盖率仅 84%（1388 miss），`central_bank_data.py` 仅 22%、`main.py` 仅 37%。同时 `docs/releases/v0.83.2.md` 的一处 inline code 把正则字面量写成了带**捕获组括号**的形式，被 `scripts/check_links.py` 的 LINK_RE 当成 markdown 链接（左方括号 + 紧跟的括号即构成链接语法），触发 `test_repo_docs_have_no_broken_links` 失败 —— 顺带说明本文件自身也曾因此被门禁报红。

**修法**：

- broken link 采用方案 A（文档侧最小侵入）—— 换成 fenced code block 并把捕获组改成非捕获组；不改基础设施是因为方案 B（改 `check_links.py` 先剥离 inline code）会引入跨测试回归风险，同时释放了一段对未来有指导价值的注释。
- 新建 `tests/test_repositories/test_central_bank_data.py`（50 用例、11 个 group）覆盖 `src/app/repositories/central_bank_data.py`（502 行 WGC chart 数据采集）的 dataclass、季度工具、进程内缓存与 TTL、chart series 解析、HTTP 取数、各国别 ISO 映射、聚合与 H1 编排、手工补丁加载、三源编排与全失败兜底 —— 所有 `_http_get` 通过 `monkeypatch` 注入不连真实网络，TTL 过期靠 monkeypatch 推进 `time.time` 25 小时验证，临时 JSON 用 `tmp_path` 写入。
- 新建 `tests/test_dependencies/test_main_app.py`（27 用例、6 个 group）覆盖 11 个别名的 307 重定向、StaticFiles mount、`/sw.js` 的 Service-Worker-Allowed 与 no-cache、openapi 与 docs、中间件栈与 lifespan 启动链路。

**验证**：

- `uv run python -m pytest -q`（忽略两个 fetcher 测试）1237 passed, 14 warnings in 880.79s（0:14:40）。
- 覆盖率 TOTAL 8477 stmts / 1088 miss / 87%（比 V0.86.1 的 84% 高 3pp，+300 行覆盖），其中 `central_bank_data.py` 96%（+74pp）、`main.py` 79%（+42pp）。
- 测试矩阵用 `@pytest.mark.parametrize` 一次断言 11 个别名，新增 alias 必须同时更新 `ROOT_ALIASES` 列表与测试断言；`test_app_version_matches_package` 锁定 `app.version == __version__`，防止 `__init__.py` 与 `pyproject.toml` 漂移。
- 已知噪音（不是测试失败）—— lifespan 退出时 `_warm_cache` 还在等 `_GatheringFuture`，会触发 `Task was destroyed but it is pending!` 与 `ValueError: I/O operation on closed file`，这是 V0.79.0 Step G 已记录的副作用，不在本次修复。

**教训**：覆盖率 baseline 必须每次升级前重跑 —— V0.86.1 误以为「前次跑过就行」，实际新增 main.py alias 后覆盖率会回退，本次基线是 V0.86.1 的真实 84%（不是 V0.85 的 87%），重新测量后才能识别低洼。写正则字面量是高风险：markdown 链接语法 = 左方括号 + 圆括号，一段带捕获组括号的正则会被 LINK_RE 当成链接，两处都要改 —— 放进 fenced code block（别用 inline code）且把捕获组改成非捕获组，只做一处仍会被匹配到。新增 alias 必须同步更新 3 处：main.py 的 `@app.get` + 测试断言 + roadmap §4 别名清单，任何一处遗漏都会产生「页面存在但 404」或「测试通过但路由不存在」的诡异状态。

**遗留**：决策可解释模式完成度（剩余历史决策可解释聚合）评估后单独排期 V0.88+；`check_routes.py` HTTP 门禁本版已由 TestClient 层覆盖路由 200/307 断言，HTTP curl gate 留 V0.88 增量；覆盖率继续向 90% 推进（`import_central_bank.py` 22%、`api/vend/endpoints/admin.py` 47% 等命令行工具与管理端点留 V0.88 评估）。

### V0.88.0 · 维护线：HTTP 路由门禁 + 覆盖率 87→90%

**发布信息**：发布日期 — ｜ roadmap §11 Backlog 候选 #1 + #3（候选 #2 决策可解释模式完成度拆到 V0.88.x）｜ 零用户面变更、零功能变更，纯维护 ｜ 总测试数 1237 → 1297 passed（+60 例），src/ 覆盖率 87% → 88%

**背景/问题**：核心问题是 V0.86.1 hotfix 暴露的那一类 —— V0.87.0 已用 FastAPI TestClient 覆盖 11 个 alias 的 307 重定向，但 TestClient 走 ASGI 内存通道，不验证「真实 HTTP 服务器 + curl GET → 落地页可达」。同时三个低洼模块长期拖累整体覆盖率：grams 56%、import_central_bank 22%、admin 47%。

**修法**：

- 新建 `scripts/check_routes.py`（约 290 行）—— `EXPECTED_ALIAS_PATHS` 列 11 条别名，`EXPECTED_STATUS` 覆盖 14 个端点（11 alias 期望 307，`/sw.js`、`/docs`、`/static/trend.html` 期望 200），提供 `discover_routes` / `check_routes` / `main` 三个 API，支持默认模式（起 in-process uvicorn + urllib 自测，无依赖）、`--base` 验证外部 server、`--list` dry-run 三种运行方式。
- 双向验证 —— `routes - expected.keys` 为漂移信号判 FAIL（防止新增 alias 忘记同步期望表）；`routes ∩ expected` 按期望表验证 status；`expected - routes` 按期望表独立抽样 StaticFiles 健康度（mount 不进路由反射）。
- 覆盖率补洼三处 —— `utils/grams.py` 56% → 100%（17 例，覆盖克数与整手份数互转、floor partial、类型矩阵与往返一致性，锁定 `LOT_SIZE == 100`）；`scripts/import_central_bank.py` 22% → 98%（13 例，mock 字符串路径注入 `build_full_dataset` 不连真实外网，dry-run 用 `AsyncMock` 验证不调用，空数据验证 `sys.exit(2)`）；`api/v1/endpoints/admin.py` 47% → 90%（19 例，用 `dependency_overrides` 注入 fake owner 绕开注册 + CSRF 鉴权栈，5 类已知错误码全 parametrize）。
- 新建 `tests/test_scripts_check_routes.py`（14 例）—— `TestExpectedStatusConsistency` 与 `test_main_app.ROOT_ALIASES` 互为漂移护栏，锁 EXPECTED_STATUS 总数为 14。

**验证**：

- 新增模块 63 passed in 20s；全套 1297 passed, 14 warnings in 504.45s（0:08:24）。
- 覆盖率 TOTAL 8477 / 1000 miss / 88%（三个目标模块本身达 100% / 98% / 90%，总体 +1pp 是新增 89 行 vs 减少 88 行 miss 的真实净增）。
- `python scripts/check_routes.py` 输出 `[OK] HTTP 路由门禁通过：12 条路由全部返回期望 status`（base 为自起的 59251 端口），exit 0。
- 反向验证 —— 注释掉 main.py 的 `/data-health` alias 后门禁报 `[FAIL] 发现 1 个路由问题：/data-health: 期望 status 307，实际 404` 并 exit 1。

**教训**：集成层门禁与单元层断言互为冗余 —— V0.86.1 hotfix 在 TestClient 层没问题但真实 curl 会 404，两层都不可少。常量同步必须用测试断言固化，EXPECTED_STATUS 与 ROOT_ALIASES 任一处漏更新都会让漏注册类回归漏检。双向验证比单向验证更稳 —— 单向（仅 routes ⊆ expected）漏掉「新增 alias 但未登记」的漂移信号，双向同时覆盖两个方向。覆盖率基线必须每次发版前重跑，增量覆盖率比绝对数字更能反映代码健康度。

**遗留**：决策可解释模式完成度留 V0.88.x 单独排期（用户决定拆分粒度）；`check_routes.py` 接入 SW 离线验证；覆盖率继续向 95% 推进留 V0.89 评估；三市场对比升级与多账户模板不在维护线范围。同期还发生一次发版遗漏 hotfix —— `static/sw.js` 的 `const VERSION` 仍为 `v0.86.1` 而 `__version__` 已是 `v0.88.0`，被 `tests/test_scripts_check_pwa_assets.py` 的两个用例当场捕获；4 处版本号同步点（`__version__` / `pyproject.toml` / `uv.lock` / `static/sw.js`）漏一处就会被这套门禁测试拦下，不依赖人脑记。

### V0.90.0 · 决策时间线回放（后端 API）

**发布信息**：发布日期 — ｜ 依据 V0.88.x backlog 候选 ｜ 后端 API（零前端 UI 变更，前端留给 V0.90.1）｜ 总测试数 1297 → 1323 passed（+26 例），src/ 覆盖率 88% → 89%

**背景/问题**：本版只交付决策时间线回放的后端 API，同时修掉一个 V0.79.0 留下的同类陷阱 —— Pydantic 的 `from_attributes=True` 按白名单丢弃未声明字段，`SnapshotOut` 漏配 `macro_detail`，导致前端拿到的快照响应永远没有宏观因子明细。V0.79.0 任务 #162 当期给 `tech_detail` 做了「列 + schema + 落库」三件套，`macro_detail` 做了前两件漏第三件，中间没有「同表所有 JSON 列 schema 暴露」的回归测试，一漏 6 个版本。当时没暴露是因为回测只直接读 DB、不经过 schema。

**修法**：

- schema 修复 —— `src/app/schemas/snapshot.py` 加 `macro_detail` 字段与 `field_validator` 反序列化：str JSON → dict（主流路径），dict 入参透传，None 透传（与 tech_detail 历史 NULL 同语义），损坏 JSON 或顶层非 dict 则 log warning 并置 None，不兜底为空字典。
- 仓储层 —— `SnapshotRepository.list_in_range(start, end)` 按日期升序返回（`start == end` → 1 行，`start > end` → 空 list，稀疏数据只返回已存在行，倒序插入输出仍升序）。
- 服务层 —— `DailySnapshotService.get_by_date` 与 `get_in_range` 两个薄包装，它们是 schema 边界，把 ORM 转成 `SnapshotOut` 并触发反序列化。
- 快照端点 —— `GET /api/v1/snapshots/by-date/{snapshot_date}`（当日无快照返 404 `snapshot_not_found`）与 `GET /api/v1/snapshots/in-range`（`start > end` 返 400 `invalid_date_range`，范围超 730 天返 400 `date_range_too_wide`）。
- timeline 服务与端点 —— 新增 `src/app/services/timeline.py` 的 `TimelineService.build`（聚合 TradeRecord 与 DailySnapshot 按日对齐，trade 当日优先、缺则回退最近前一日且上限 30 天防历史空洞误拿远古快照，空闲段跨度超 `compress_threshold_days` 折叠为一段）与 `src/app/schemas/timeline.py`（`TimelineOut` 与 `TimelineSegment`）；端点 `GET /api/v1/trades/timeline` 支持账本筛选、默认 90 天窗口、`compress_threshold_days` 默认 7（0 = 不折叠，最大 365）。

**验证**：

- 新增测试 56 passed —— `tests/test_schemas/test_snapshot.py` 14 例（新建目录，与 test_models / test_services 平级）、`tests/test_repositories/test_snapshot.py` 10 例、`test_snapshot_service.py::TestGetInRange` 6 例、`test_api/test_snapshot.py` 新增 10 例、`test_api/test_trades_timeline.py` 16 例；既有 6 例 V0.63.0 回归全过。
- 全套 1323 passed。
- curl 验证 `snapshots/by-date/2026-10-01` 的 `macro_detail.DXY.value` 为 104.5（此前该字段整个被丢弃 → undefined）；timeline 的 segments 类型序列为 idle / decision / idle。

**教训**：同类 schema 漏配要配对查找 —— 对策是未来加 JSON 列到任何 schema 时，写测试断言「同表所有 JSON 列 schema 都暴露」。薄包装是有意义的 —— 直接端点调仓储会绕过 schema 验证，所以「薄包装」也要有测试断言它返回的是 schema 而非 ORM。「同日多 trade」这类边界要单独立测试用例固化，不能指望组合 case 顺带覆盖；服务层每个分支都应对应至少 1 个测试用例。回退对齐的 30 天上限要写进代码注释，避免后续被误改成无上限而回退到远古快照，与决策点语义脱节。版本号同步在本版预防性完成，末步必跑 `pytest tests/test_scripts_check_pwa_assets.py`。

**遗留**：前端时间线 UI（review.html 横向时间轴 + 决策点钻石 + 状态卡片弹窗）、decision-explainer.js 适配 snapshot 数据契约、时间压缩交互、快照 URL 分享、移动端响应式，均列为 V0.90.1 候选。

### V0.91.0 · 复盘报告 PDF 一键导出 + 跨页上下文保留

**发布信息**：发布日期 — ｜ 承接 V0.74.0 路线图 M7「PDF 导出 ≤ 2 页」（挂 3 个月后落地）｜ 总测试数 1323 → 1352 passed（+29 例），src/ 覆盖率 89% 持平（后端端点零新增，纯前端 + 1 个路由 alias）

**背景/问题**：V0.90.0 的后端 timeline 与 snapshot 已就位，本版为「PDF 导出」补齐前端消费出口；同时业务页之间跳转时筛选状态全部丢失 —— 用户在 /news 看完打分跳 /review，日期、标的、账本都要重设。原先 11 个 nav 链接、11 条 alias、28 个静态资源，本版都各有增量。

**修法**：

- `static/print.css`（约 80 行）—— `@page A4` + 14mm 边距，强制 `print-color-adjust: exact` 避免深色主题下被浏览器「省墨」反转成白底白字；隐藏全站 chrome（topnav / status-panel / 时效条 / 警示 / 悬浮按钮 / canvas）；链接 URL 显式展开；表格 `border-collapse: collapse` + `page-break-inside: avoid`；`media="print"` 仅 print mode 加载，零运行时成本。
- `static/nav-context.js`（约 120 行）暴露 `window.PM_NavContext` —— 白名单 key（fStart / fEnd / fSide / fPosition / fKeyword / fSize / target / horizon / days / snapDays / klineDays / klineInterval / filterCountry / filterFrom / filterTo / compressThreshold）；`get(key)` 优先读 URL query 再回退 `pm_ctx_v1_<key>` localStorage；`write(key, value)` 写 LS 并派发 `nav-context-changed` CustomEvent；另有 `apply` / `bind` / `buildQuery` / `updateUrl` / `buildReportUrl`；不用 hash 存 context（review.html 的 `#status` 已被 warning.js 占用）。
- 顶栏导出按钮 —— `static/topnav.js` 新增 `buildExportButton()`（不进 NAV_LINKS，按钮不是链接），用 `document.addEventListener("click", ...)` 事件委托让 9 页共用一份；news.html 因用硬编码 nav 单独内联 `<button class="nav-btn-export">` + 自挂 click 委托。
- 报告页 —— 新增 `static/report.html`（约 200 行）与 `static/report.js`（约 250 行），5 段主体（持仓 / 时间线 / 消息面 / 收益曲线 / 央行购金），6 个端点用 `Promise.allSettled` 并行，任一失败只让该段显示「暂缺」而不整体失败；图表一律改 HTML 表格与文字摘要，不画 Chart.js canvas；`snapshot === null` 显式标「数据缺（节假日）」灰色，不兜底 50；central-bank 按 `tonnes_net` 降序取前 20；equity-curve 每 5 日采样加首尾。
- 9 页集成 —— 每页加 print.css 与 nav-context.js（约 45 行）；4 个筛选页（trades 6 controls / review 3 selects / central_bank 3 controls / backtest 2 selects）接 apply + bind；help.js 的 `VERSION` 从 `V0.73.0` 升到 `V0.91.0` 并新增一节指南；manifest.json 加第 3 条 shortcut；main.py 加 `/report` alias（不进 SHELL_ASSETS）。

**验证**：

- 新增测试 109 passed（`tests/test_scripts/` + `tests/test_dependencies/` + `tests/test_i18n/` 合计 65 + 44）—— `test_i18n_coverage.py` 5 例、`test_i18n_dict.py` 21 例、`test_i18n_apply.py` 18 例、`test_i18n_format.py` 21 例、`test_scripts_check_pwa_assets.py` 14 例（SHELL_ASSETS 29 条 / manifest 7 目标）、`test_scripts_check_routes.py` 22 例（12 alias + sw.js + docs + trend.html = 15 路由）、`test_main_app.py` 22 例全绿。
- 报告页路由返回 307，页面体积 6257 bytes；全套约 1352 passed。
- `check_pwa_assets.py` 报 sw.js VERSION = v0.91.0、SHELL_ASSETS 29 条、manifest shortcuts 3 条；`check_routes.py` 报 13 条路由全部期望 status；`check_static_js.py` 报 16 个静态页面内联脚本 + 29 个共享脚本全部通过；9 页 grep `nav-context.js` 与 `print.css` 全命中。
- 版本号 4 处同步完成，`uv lock` 验证 81 包、1ms 无 diff。

**教训**：sw.js VERSION 的 4 处同步一次做完、末步 PWA 资源门禁 + routes 门禁双绿 —— V0.88.0 的教训在本版生效。i18n 自动化门禁当场抓到 `status.summary_text` 漏声明，避免发版后用户切到 en-US / zh-TW 看到 raw key。nav-context 的命名空间版本化（`pm_ctx_v1_*`）借鉴 `pm_help_seen_version` 升级机制，未来字段增删可改 v2 强制重置，零迁移成本。原路线图写「≤ 2 页」，本版走「完整版 5 段 3-5 页」是有意的取舍 —— 给合伙人或家人看需要全维度，密度优先，精简版可作为后续开关。puppeteer mock 必须用真实 schema（参考 V0.83 的 sig() dict bug 教训）。顶栏 4 个组件在 ≤768px 时可能挤爆，方案是藏到汉堡抽屉，本次未做（实测 9 页 1080p 下未溢出）。

**遗留**：移动端 print 体验优化（iOS Safari / Android Chrome 打印对话框差异）；jsPDF / html2pdf 客户端生成（与 `window.print()` 二选一）；PWA 通知推送「复盘报告已生成」；报告页 SHELL_ASSETS 离线可用；report 模板多套主题；顶栏 4 组件响应式折叠；报告页自定义 from/to 范围（当前只暴露 7/30/90/180 预设，≤250 天自定义留后续）；zh-TW 翻译完整覆盖。

### V0.92.0 · 历史打分数据汇总（物化宽表 + 汇总页）

**发布信息**：发布日期 — ｜ 业务页 9 → 10，RESTful alias 12 → 13，端点 28 → 33，静态资源 31 → 33，物化表 0 → 1 ｜ 总测试数 1352 → 1362+ passed（+10 例）

**背景/问题**：V0.90.0 的 timeline 与 V0.91.0 的报告页把「事后回看」补齐后，下一个客户痛点是「跨日跨月跨 tag 看成绩单」。此前 6 个 history 端点各自 JOIN 4-6 张表，单次查询 100-300ms；而且没有汇总视图，查看历史成绩单只能靠 puppeteer 截图。

**修法（数据层）**：

- 新增 `scoring_daily_wide` 物化宽表（迁移 `i5d6e7f8a9b0`，约 80 行，26 列）—— 主键为 date + user_id + snapshot_id（FK 指向 daily_snapshots.id，NULL 表示未捕获）；列分为 4 指数（tech / macro / news / trend index + index_level）、价格参数（close / change_pct / direction / data_source）、消息面聚合（news_slot_count / news_basis_tags / news_backfilled_count）、共振信号（V0.78.0 Step C 当日重建）、复盘 outcomes（actual_change_pct 与 hit 的 t1 / t3 / t5 + outcome_pending_until）与元字段。
- 3 个索引 —— (user_id, date) 区间查询主路径、(date) 跨租户分析、(user_id, trend_index) 极值定位。
- 纪律 —— 所有数值列允许 NULL，绝不用 50 兜底；`news_basis_tags` 存 JSON 文本，应用层 `json.loads` 后过滤；`outcome_pending_until` 标 T+5 完成日期，NULL 表示未完成。
- 配套 —— `src/app/models/scoring_wide.py` 的 ORM + `src/app/repositories/scoring_wide.py`（约 120 行，提供 get_by_date / list_in_range / list_recent / list_dates，`upsert` 用 24 字段白名单）。

**修法（服务层）**：

- 新增 `src/app/services/scoring_wide.py`（约 250 行）做 ETL —— 3 源（daily_snapshots / news_scores / gold_price_daily）合并为一行；3 源都缺时返回 None 不写空行（写空行会被 by-month 聚合稀释）；news_scores 按当日所有 slot 聚合覆盖 snapshot 缓存值，basis_tags 用 `set()` 去重并倒序排（slot3 出现顺序优先）再过 `BASIS_TAGS` 白名单；`gold_price_daily` 取基准日 + T+1 / T+3 / T+5 判定命中，T+5 缺数据则 outcomes 留 NULL 并标 pending；rebuild 失败只 log warning 不抛异常、不回滚源表。
- 4 类聚合查询 —— `summary`（按 day / week / month 聚合，ISO week 格式 `2026-W42`）、`get_by_date`、`hit_stats`（按 horizon，含 5 个分值分箱 0-20/20-40/40-60/60-80/80-100）、`by_tag`（basis_tags JSON 解析 + 白名单过滤）；复用 V0.86.0 的 `ReviewStatsOut` schema 与 `MIN_SAMPLES_OVERALL=10` 阈值。

**修法（端点 / 写时 hook / 视图）**：

- 5 个端点 —— `/summary`、`/by-date/{date}`、`/hit-stats`、`/by-tag`、`/rebuild/{date}`；统一 `_validate_range` 门禁（start > end 或超 730 天返 400）。
- 写时 hook —— `capture_today()` 与 `save_today()` 末尾各追加一次 rebuild，失败隔离；另提供 `scripts/backfill_scoring_wide.py`（约 80 行）一次性历史回填，支持 `--dry-run` / `--from` / `--to`，默认从 2024-09-01（V0.66.0 上线日）起，需先跑 `alembic upgrade head`。
- DI cycle 处理 —— 用 lifespan 挂载的进程级单例（`set_scoring_wide_singleton` + `_wide_svc_singleton` + `_get_or_build_wide_svc` 兜底），不引入 Depends() 循环。
- 视图层 —— 新增 `/scoring` 双 Tab 页（日历视图默认 + 表格视图 4 段）；topnav 加第 13 个链接；33 个新 i18n key 三语同步；main.py 加 `/scoring` alias；`check_routes.py` 的 `EXPECTED_ALIAS_PATHS` 12 → 13。

**验证**：

- `tests/test_services/test_scoring_wide.py` 10 passed —— 覆盖 4 指数与 outcomes 全部命中、T+5 pending、3 源皆缺返回 None、basis_tags 跨 slot 去重、月度聚合、空区间、按日期 404、按 tag 统计。
- 全套 1362+ passed。
- curl 验证 —— summary 月度聚合返回 2 个桶、hit-stats 的 t5 命中率 0.56、by-tag 返回 12 个 tag、`/scoring` 返回 307。
- `check_routes.py` 报 13 alias + 4 新端点 + sw.js + docs + trend.html 共 17 路由；`check_pwa_assets.py` 报 SHELL_ASSETS 30 条、manifest shortcuts 4 条；`check_static_js.py` 报 17 个静态页面内联脚本 + 31 个共享脚本全部通过。
- 版本号 4 处同步完成，`uv lock` 验证 81 包、1ms 无 diff。

**教训**：V0.78.0 Step D 纪律沿用 —— 所有数值列允许 NULL，绝不用 50 或 0 兜底，测试显式断言 T+3 缺数据时为 None，缺数据不算 0 也不算 0%。V0.79.0 #162 教训升级为架构纪律 —— 宽表是「读优化副本」，源表是真值，写失败不回滚源表，下次 capture_today 幂等 rebuild 自动重算，CLI 工具兜底。V0.80.0 #159 隔离纪律自动应用 —— 仓储层所有 query 默认按当前 user_id 过滤，测试覆盖多用户场景。V0.83 的 sig() dict bug 教训生效 —— `news_basis_tags` 用 TEXT JSON 字符串存储，应用层 `json.loads` 后用 `in` 判定，不在 dict 上调用 `Array.map()`。V0.85 漏注册教训防回归 —— `check_routes.py` 的 alias 期望与两侧测试断言一次性同步。V0.86 决策可解释模式复用 —— 沿用 `ReviewStatsOut` schema 与 `MIN_SAMPLES_OVERALL=10` 阈值（by_tag 的 sample_size < 10 时降级标「样本不足」）。Forward reference DI cycle 用 lifespan 挂载的进程级单例解决。T+5 的 pending 语义用 `outcome_pending_until` 标到最后一个可用交易日，前端据此判断「该日还在等待中」，避免把 NULL 误展示成「失败」。

**遗留**：事件溯源 `scoring_events` 表（审计 / ML 训练数据准备）留 V0.93+；冰山分层（hot / cold + 月度 rollup）留 5 年体量后；chart 视图留 V0.93+（避免 print mode 空白）；DUCKDB 旁路明确不做（LAN 部署不引新依赖）；TimescaleDB 明确不做；移动端专属视图留 V0.95+；自动重新 ETL 失败告警依赖推送；跨用户对比留 V0.93+ 安全审计需求出现时。

---

## 三、这一阶段的通用教训

1. **「加一列」从来不是一件事**：落库 ≠ schema 暴露 ≠ 所有写入路径覆盖，三者要分别断言。V0.79.0 同期给 `daily_snapshots` 加了 `tech_detail` 与 `macro_detail`，前者三件套做完，后者漏了 schema 暴露（Pydantic `from_attributes=True` 按白名单丢弃未声明字段），一漏就是 6 个版本，到 V0.90.0 timeline 端到端走 schema 才暴露。V0.92.0 的 `upsert` 特意做成 24 字段白名单，并注明「V0.79.0 #162 教训：加列时必须同步 insert + update 路径」。

2. **新页面 = 根路径别名 + 门禁登记 + 静态资源，三处缺一即 404**：V0.85.0 引入 `data-health.html` 时漏注册 `/data-health` 别名，四道门禁全绿但真实点击 404，要到 V0.86.1 才修。修完之后的固化动作是：V0.87.0 把别名数量写成断言，V0.88.0 补 `scripts/check_routes.py` 做真 HTTP 双向验证（routes ∩ expected / routes − expected / expected − routes）。此后 V0.91.0 的 `/report` 与 V0.92.0 的 `/scoring` 都同步了 `EXPECTED_ALIAS_PATHS` 与两侧测试断言。

3. **CI 绿只证明「被测的那条路」是绿的**：prod 401 路径在 `tests/conftest.py` 里永远走 dev 分支（`ADMIN_TOKEN` 不设 ⇒ `require_admin` 直接 return），V0.80.1 与 V0.81.1 都只能 puppeteer 手测；V0.83.4 的 `sig()` 用了假数据，把 API 实际返回 dict 导致的 TypeError 掩盖了整整三个版本；V0.87.0 的 TestClient 层与 V0.88.0 的真 HTTP 层互为冗余，正说明单层不够。规律：mock 必须用真实 schema；每条用户真会走的路径都要有真实链路的验证。

4. **降级的第一原则是「不撒谎」**：缺数据不能用 50 / 0 兜底（V0.91.0 报告页把 `snapshot === null` 显式标成灰色「数据缺（节假日）」，V0.92.0 所有数值列允许 NULL 并用 `outcome_pending_until` 标 pending 期），也不能用红框假装应用坏了（V0.83.3 的 429 红框 → V0.83.4 改成保留末次数据 + 0.55 半透明 + amber「离线/缓存」chip + 60→120→300→600s 智能退避，V0.85.0 的 health-summary 直接沿用这套样式）。

5. **发版流程里的「4 处同步」要靠门禁而不是靠记性**：`__version__` / `pyproject.toml` / `uv.lock` / `static/sw.js` 的 VERSION。V0.88.0 漏改第 4 处，靠 `tests/test_scripts_check_pwa_assets.py` 当场抓出来；V0.81.1 也强调「不换代就拿不到新的 auth.js」；V0.90.0 起把「4 处同步 + pwa_assets 门禁」写进发版 checklist 第一项，V0.91.0 与 V0.92.0 都照做。

6. **一次修复往往要连带三处**：V0.80.0 给 `news_scores` 加 `user_id` 时连带发现唯一键不含 user_id（两人无法共存）、SQLite 不支持 ALTER 约束（改用 CREATE UNIQUE INDEX）、重建表不带索引（单列索引要补建）；V0.82.0 把 18 处 `Depends(require_admin)` 迁到双通道；V0.92.0 加两个写时 hook 时要处理 forward reference DI cycle（改用 lifespan 挂载的进程级单例）。规律：改一处之前先把「同一语义的全部落点」列出来。

**这条脉络的整体形状**：V0.79 – V0.82 处理「能不能用」（算法可调、多用户可用、LAN 可写），V0.83 – V0.86 处理「看得懂吗」（版面减法、状态条合并、时效集中披露、决策可解释），V0.87 – V0.92 处理「信得过吗」（门禁双向验证、覆盖率补洼、schema 漏配补课、事后回看的产品化）。三个阶段各留下一批明确的遗留项，且每一项都被写进了下一版的「不在本 PR」清单 —— 这条演进脉络之所以可读，靠的不是版本多，而是每次收口都把下一轮的债记下来。

---

*本文件由 V0.79.0 – V0.92.0 共 19 份 release notes 合并整理，逐版原始全文见 git 历史（tag 与原文件名同名）。*
