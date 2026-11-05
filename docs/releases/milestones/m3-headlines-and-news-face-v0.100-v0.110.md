# M3 · 今日要闻与消息面（V0.100 – V0.110）

> **发版区间**：V0.100.0 – V0.110.0（14 个版本）｜ **状态**：归档（历史里程碑）
> **本文件定位**：把该区间的 14 份 release notes 合并成一条**可读的演进脉络**。
> **逐版原始全文**在 git 历史里（tag 与原文件名同名）：`git show v0.110.0:docs/releases/v0.110.0.md`

## 〇 一页结论

1. **消息面从「中性 50 兜底」改成「未打分 = pending」**（V0.100.0）。`NewsScoreOut.score` / `NewsIndexOut.score` 从 `float` 改为 `float | None`，删掉 `NEUTRAL_SCORE = 50.0` 常量；消息面未打分时综合指数走既有的「剔整面 + 归一化」路径并挂 pending chip，不再让 50 分的中性值按 `NEWS_WEIGHT=0.30` 稀释 15 分。
2. **今日要闻产品线在这一区间从「能看」走到「可用」**（V0.103.0 – V0.107.1）：新增 `/favorites` 永久收藏档案页（9 端点 + 16 字段快照表）、按日期分页（单日模式 + 日期导航）、5 类关键词分类筛选、顶 nav 提级为第 2 个顶级场景、调度 6h→4h、`news_feed_daily` 按天物化宽表 + 刷新 success toast。
3. **分类质量连续 4 版打补丁，且每次补丁都推翻了上一版的设计前提**。V0.107.1 弃入「其他」；V0.108.0 把 33 个站名写进内容词典；V0.109.0 修 `PE ⊂ Europe` 子串误匹配（576 条里 28 条误判）；V0.109.1 承认「站名压过内容」是设计失误，把架构改成「内容优先、站名兜底」且站名兜底只对垂直媒体开放。
4. **这条区间的主线其实是「数据是哪天的」**。V0.109.2 给白银三市场加 `data_as_of` + staleness 检测（akshare SGE 滞后 2 天却一直显示 ✅ 全绿）；V0.110.0 给宏观因子加手动校准（`dxy`/`vix` 长期用 2026-08-28 的常量，等于综合指数的 16% 建立在两个半月前的数字上），并把 `as_of` 设为必填 —— 理由原话就是「这正是 V0.109.2 白银页面踩过的坑」。
5. **改动静态资源必须 bump `sw.js VERSION` 这条纪律，是这一区间最贵的一课**（V0.100.1 → V0.100.2）。根因是 SW 按 cache name 清理，VERSION 不变则旧 cache 永远不会被清，浏览器持续回放 stale 的 `/home` 307 与旧 `/static/home.html`；从 V0.100.2 起改为「改 static 的第一个 commit 就 bump」，中期 bump（`v0.105.0 → v0.105.1`）再随发版统一 bump 成正式版本。
6. **留下了什么**：rule-based 分类器的精度上限（V0.105.0 自评 ~70-80%，V0.109.1 仍留「基金 → 老年基金会」「经济 → 村镇经济治理」两类通用词碰撞）；分类逻辑变更后历史数据不会自动重分类（V0.109.0 遗留 → V0.109.1 才补全量 sweep 脚本）；文档索引长期落后（`docs/releases/index.md` 停在 V0.100.2，13 份 release notes 无人索引），直到 V0.110.0 才补上门禁。

## 一、版本一览

| 版本 | 主题 | 关键交付 |
|---|---|---|
| V0.100.0 | 消息面未打分 → 综合指数 pending | `NewsScoreOut.score` / `NewsIndexOut.score` 改 `float \| None` + `pending_reason`；删 `NEUTRAL_SCORE`；trend.html + silver.js 加 `#idxPendingChip`；6 i18n key × 3 语 |
| V0.100.1 | home.html 今日要闻 SW 缓存击穿（hotfix） | 4 处版本同步 0.100.0→0.100.1；`sw.js` activate 阶段显式清 RUNTIME_CACHE 的 `/home` + `/static/home.html` |
| V0.100.2 | home.html 今日要闻 Top 5 → Top 20（hotfix） | `home.js` `limit=5→20` + `slice(0,5)→slice(0,20)`；`home.html` 骨架 3→5；首次在功能 commit 第 1 步就 bump SW VERSION |
| V0.103.0 | 我的收藏（今日要闻「收藏 / 永久存储 / 档案管理」） | `user_news_favorites` 表（16 字段 + 迁移 `n0a1b2c3d4`）+ ORM/Repository/Service + 9 REST 端点 + `/favorites` 页（3 语 47 个 `favorites.*` key）；ROOT_ALIASES 16→17 |
| V0.104.0 | headlines 按日期分页（单日模式 + 日期导航） | `GET /api/v1/news-feed/items` 加 `date` + `tz_offset_minutes`（与 `days` 互斥）；`NewsFeedListOut` 加 `current_date` / `has_older` / `has_newer`；仓储 `has_items_outside_day()` 2 个 EXISTS |
| V0.105.0 | headlines 分类筛选（5 类 + 多 switch） | `news_classifier.py` 关键词分类器（财经 / 科技 / 创投 / 商业 / 其他，财经优先）+ 3 路 backfill；`GET /api/v1/news-feed/categories`；`#categorySel` 工具栏第 5 控件 |
| V0.106.0 | 今日要闻顶 nav 提级 + scheduler 6h→4h 加密 | 今日要闻从「情报」子页提为顶级场景第 2 位；顶 nav 7→8 scene；`NEWS_FEED_INTERVAL_HOURS` 6→4（UTC 00/04/08/12/16/20） |
| V0.107.0 | 今日要闻按天聚合 + 刷新 UX 改进 | `news_feed_daily` 物化宽表（date-as-PK，仿 `scoring_daily_wide`）+ 合并迁移 `n1o2p3q4r5` 消除 alembic 双 head；2 个新端点；刷新 success toast + `PMToast`→`PM_Toast` typo 修（4 文件 11 处） |
| V0.107.1 | 今日要闻分类聚焦 + 弃入「其他」+ page_size=50 | 关键词字典财经 32→67 / 科技 33→49 / 创投 23→36 / 商业 22→32；fetcher 弃入「其他」+ service 二次 gate（`_ALLOWED_CATEGORIES`）；`_DEFAULT_PAGE_SIZE` 20→50 |
| V0.108.0 | 今日要闻站点黑白名单 + 财经二次加强 | `SITE_BLOCKLIST = {"新浪科技", "maomu.com"}`；33 个优质站名写入关键词词典；财经词典 67→100+ 词（大宗 / 监管 / 国际央行 / 银行险资 / 人物） |
| V0.109.0 | 分类词边界修复 + 发布词精度 | 长度 ≤3 的纯 ASCII 词改走词边界正则（37 词）；裸词「发布」改「发布会」+「发布公告」；576 条全量对拍量化误判 30/576（5.2%） |
| V0.109.1 | 分类架构改为「内容优先、站名兜底」 | 两段式分类（内容 title+summary 命中优先，站名 `_SITE_HINTS` 仅兜底）；通讯社（财联社 / 格隆汇 / 第一财经 等 6 家）从兜底表移除；`scripts/reclassify_v01090.py` 全量 sweep |
| V0.109.2 | 白银页面数据时效透明化（SGE akshare 数据滞后 2 天暴露） | `data_as_of: date \| None` 加到 4 个白银 quote schema；`_is_data_stale(last_date, max_lag_days=1)` 用 `trading_days_between`；前端滞后 chip + source-bar 尾部告警 |
| V0.110.0 | 宏观因子手动校准 + docs 整理 | `macro_factor_overrides` key + `MacroFactorOverride`（`as_of` 必填）；GET/PUT `/api/v1/settings/macro-overrides`；优先级链「用户覆盖 > 自动源 > STATIC_REF」；`check_links.py` 新增 `check_release_index()` 门禁 |

## 二、逐版本记录

### V0.100.0 · 消息面未打分 → 综合指数 pending

**背景/问题**：
- `TrendService._analyze_uncached`（trend.py:495-498）**默认** `news_score = 50.0`（中性兜底）；`aggregate_slots()`（news.py:79-93）当日无打分时返回 `NEUTRAL_SCORE=50.0`。
- 用户**未打分**的消息面会以「中性 50」自动参与综合指数，按 `NEWS_WEIGHT=0.30`（macro.py:79）稀释 15 分 —— **与用户「未完成消息面打分则不输出综合分」诉求直接矛盾**。
- `NewsIndexOut.score: float`（market.py:193-199）与 `NewsScoreOut.score: float`（schemas/news.py:82-106）schema 层不允许 None。
- 既有「剔整面 + 归一化」算法（trend.py:517-524）已实测覆盖「tech 整面缺失」场景，**news=None 可走同一分支** —— 不需新算法。

**修法**：5 个 commit（一个 PR 顺序）。
- C1 `cf63b7f` 数据层：`NewsScoreOut.score: float | None` + `direction: DirectionSignal | None`；`NewsIndexOut.score: float | None` + 新增 `pending_reason`；删 `NEUTRAL_SCORE` 常量；`aggregate_slots()` 未打分返回 `(None, "", False)`；`direction_of(None) → None`。
- C2 `112fdce` 服务层：`news_score` 默认 None；文案分支 `if set(dropped) == {"news"}` → 「消息面未打分，综合指数待定」；`NewsIndexOut` 构造补 `pending_reason`；logger 改 `_fmt_score(news_score)`；`snapshot.py:93` 快照表 NOT NULL 兜底 50.0 + `macro_detail` JSON 审计追溯。
- C3 `3fe4cef` + C4 `b7d52d5` 前端：trend.html:609-631 与 silver.js:374-407 在 `#idxBadge` 后插入 `#idxPendingChip`（className 复用 freshness.js `fsh-chip fsh-warn fsh-stale-chip`）+ `#idxNum.style.opacity = 0.55`；消息面区按 `news.scored` 分支（未打分显示「消息面指数 — · 今日未打分」+ 进度条 width=0%）；i18n +6 key × 3 语 = 18 条；**silver.html DOM 完全不变、不新增 CSS**。
- C5 `5c1eeef` 门禁：4 处版本同步 0.99.0 → 0.100.0；维护线顺手修 `ROOT_ALIASES` 13 → 15 与 `check_routes.py` 3 处硬断言 14/13/16 → 16/15/18。

**验证**：
- `check_pwa_assets.py`（SW v0.100.0 / SHELL_ASSETS 42 条）、`check_routes.py`（18 条路由）、`check_i18n_keys.py`（0 missing / 124 in-scope）、`check_static_js.py`（19 + 36）；pytest 5 个文件 = 78 OK（含 3 个新增 pending 用例）。 Puppeteer 探针（前置：清空今日 3 个 slot 打分）逐节点核对 `/trend` 与 `/silver`：`#idxPendingChip` 存在、`#idxNum` opacity=0.55、`#idxSummary` 含「消息面未打分；已剔除并按剩余面权重归一化」、`#idxMethod` 公式不变。
- 打分后验证：POST `/api/v1/news-score` 打 1 次 → 60s 缓存失效 → pending chip 消失、opacity=1.0；DELETE 撤销后回到 pending 状态。

**教训**：
- 「剔整面 + 归一化」算法（line 517-524）**保留不动**，旧的 `combined is None` 防御分支仍保留。
- 快照表 NOT NULL 列拒绝 news=None ⇒ 兜底 50.0 + `macro_detail` JSON 审计追溯（快照是历史记录，要求数值）。 `NewsScoreOut.scored: bool` 保持为**唯一真源**（前端 pending chip 触发依据）；`news_score = None` 让「不注入 service」与「注入但 scored=False」同形。
- 预存缺陷（i18n 覆盖、`test_ui_cluster_render` silver.html 缺 `async function loadTrend(` 标记等）按 V0.92.0 conftest 教训同等处理，不阻塞发版。

### V0.100.1 · home.html 今日要闻 SW 缓存击穿（hotfix）

**背景/问题**：
- 症状：用户报告「首页今日要闻没有正确显示新闻标题，不需要分值显示在栏目」；用户在 `192.168.0.204:8889/gold/home` 看到每个 `<li>` 渲染出 0-100 的分值 badge，标题文字未正确显示（`item.title` 命中 undefined 静默渲染）。
- 排查四步全绿：后端 `curl /api/v1/news-feed/items?days=2&limit=5` 返回完整 `[{external_id, title, url, site_name, publish_date, ...}]`；`/static/home.html` 里 `id="homeHeadlinesChip"` + `.home-news-title` 类齐全；本地 puppeteer 实跑 5 条新闻完整渲染，`hasAnyScoreField: false`。
- 第 4 步才找到根因：home.html / home.js 在 `bfeb39f`（V0.102 落地）已切到 readhub 端点，但 `static/sw.js` VERSION 仍是 `v0.100.0`。

**修法**：
- 4 处版本同步 0.100.0 → 0.100.1（`__init__.py:14` / `pyproject.toml:5` / `sw.js:17` / CHANGELOG 加 Fixed 1 项 hotfix 条目）。
- sw.js activate 阶段显式清 RUNTIME_CACHE 的 stale：`"/scoring", "/static/scoring.html", "/home", "/static/home.html"`（后两条 V0.100.1 新增），套 V0.92.0 `/scoring` 同模式。
- 原因：`/static/*` 走 cache-first；若 RUNTIME_CACHE 里有 stale `/home` 307 入口或旧 `/static/home.html`，SHELL_CACHE 里的新版永远没机会被命中。
- activate 的清理条件是 `k !== SHELL_CACHE && k !== RUNTIME_CACHE`，两常量分别是 `gold-shell-${VERSION}` / `gold-runtime-${VERSION}` —— VERSION 没变则旧 cache 名 == 新 cache 名，旧 cache **永远不会被清**。

**验证**：
- `check_routes.py` 17 条路由全 OK；`check_i18n_keys.py` 142 in-scope / 0 missing；`check_static_js.py` 20 静态页 + 37 共享脚本全过；`check_pwa_assets.py`（SW v0.100.1 / SHELL_ASSETS 45 条 / manifest 8 目标）；pytest 3 个文件 **67 passed, 0 failed**。
- Puppeteer 2 次连续访问：SW `hasController: true`、`scope: http://127.0.0.1:8888/`；渲染 `itemCount: 5`，5 条完整（时间 + 来源站 + 标题 + 链接），`chipText: "📰 20 条 · 24h +20"`，`hasAnyScoreField: false`。
- 波及范围核对：未触及 schema / model / repository、5 个 API 端点、3 语字典、`news_feed_loop` 调度器、22 个 V0.102 测试用例。

**教训**：
- 根因正是 `sw-version-sync-gate` 记忆条目的教训：发版 4 处版本同步清单必须同步 bump，否则浏览器 SW 缓存永远无法感知新版本。V0.102 落地 7 commit 时只 bump 了功能代码，「因为当时还不算 V0.102 正式发版」。
- 唯一风险：所有用户首次访问会触发 SW 重新 install（precache 45 条 shell 资源 + activate 清 4 条 stale entry），约 1-2s 闪一下 offline.html 兜底再回主页，可接受。
- 新增护栏建议（待 V0.101 收口）：`check_pwa_assets.py` 增一项检查 —— 对比最近 7 天改动的 `static/*.html` / `static/*.js` 清单与 sw.js 的 `git log --since=VERSION` 时间戳，若有静态资源在 VERSION 之后改动就报红。

### V0.100.2 · home.html 今日要闻 Top 5 → Top 20（hotfix）

**背景/问题**：
- 用户原话：「现在今日要闻再首页标题显示5条， 我们让它显示20条标题」。
- V0.102 落地后 home.html 底部 今日要闻 section 限 Top 5（V0.100.1 修复后即此状态），用户希望更密集的信息流。

**修法**：
- `static/home.js:7` 注释 `Top 5（V0.102 readhub 财经流）` → `Top 20（...）`；`:58` fetch `?days=2&limit=5` → `?days=2&limit=20`；`:112` slice `.slice(0, 5)` → `.slice(0, 20)`。
- `static/home.html` 骨架由 3 个 `<li class="home-news-skeleton">` 改为 5 个（视觉占位提升）。
- 4 处版本同步 0.100.1 → 0.100.2（`__init__.py:14` / `pyproject.toml:5` / `sw.js:17` / CHANGELOG 加 Fixed 2 项）。
- sw.js activate 阶段 `/home` + `/static/home.html` 加入 RUNTIME_CACHE 显式清理列表（与 V0.100.1 同模式），防止 307 旧入口回放。

**验证**：
- `check_pwa_assets.py` → SW v0.100.2 / SHELL_ASSETS 45 条 / manifest 8 目标全过。
- Puppeteer unregister 旧 SW + 硬刷新模拟新用户：`itemCount: 20`、`realItemCount: 20`；首 2 条为 techradar.com（18:00），末 2 条为央视新闻 / 快科技（15:55）；`chipText: "📰 20 条 · 24h +20"`。
- 20 条全部完整渲染（标题 + 时间 + 来源站 + 链接），无分值字段。

**教训**：
- 范围只动 1 个 section（home.html 底部 `.home-bottom` 内的 `.home-news-list`），不影响顶部 hero / 5 大场景卡 / AI 卡，不影响 `/headlines` 全功能页，不改任何 API 端点签名（`/api/v1/news-feed/*` 5 端点不变）。
- 这是 V0.100.1 沉淀的 `v01001-sw-bump-on-static-change` 教训的**首次兑现**，且是在功能 commit（不是正式发版）中直接应用。
- 三步做法：① 改 home.html + home.js 第 1 步就 bump sw.js VERSION（不是事后补）；② 同步 bump `__version__` + `pyproject.toml` + CHANGELOG（4 处同步清单一气呵成）；③ sw.js activate stale 清理同步更新。
- 结果：无 SW 缓存漂移、无需后续 hotfix 救火。

### V0.103.0 · 我的收藏（今日要闻「收藏 / 永久存储 / 档案管理」）

**背景/问题**：
- 用户原话：「我们好好梳理一下 今日要闻的存储逻辑，给有价值的新闻可以在应用中添加永久存储并设计一个页面，帮助用户掌握市场动态。写一个计划。」
- V0.102 落地的 `news_feed_items` 是「共享上下文」（migration `m9g0a1b2c3` 显式不挂 `user_id`），6h 抓取 / 无清理 / 字段外部所有；Explore 全仓 grep **0 命中** watchlist / favorite / bookmark / starred / pinned / user_note 业务实体 —— 项目里**没有任何「用户标记数据」的表或字段**。
- 已确认 2 个决策：① 单用户（共享）模式，与 `news-score` / `portfolio` / `decisions` 一致，AUTH_ENABLED=false 时零额外配置；② 独立表 + 快照字段（冗余 `title / summary / url / site_name / publish_date / source`，防 readhub 撤稿 / URL 失效时收藏断链）。

**修法**：7 个 commit / 7 件大项 / ~1680 行净新增。
- C1 `924bff6` 表 + 迁移 `n0a1b2c3d4`（down_revision=`m9g0a1b2c3`）：16 字段（11 快照 + 3 user_meta + 2 timestamp）；索引 `UNIQUE(news_external_id, news_source)`（重复 POST → 409）+ `(archived_at)` + `(importance, archived_at)` + `(site_name)` + `user_tags` LIKE 模式搜索。
- C2 `3c859eb` ORM（140 行）+ Repository（280 行 11 方法，含 `list_items` 5 维筛选 + 3 排序、`get_status` 6 维聚合）；C3 `c8b3344` Service（230 行 8 方法）+ 5 个 Pydantic schema（120 行），`add()` 先查 `news_feed_items` 回填快照。 C4 `292cd6a` 9 个 REST 端点（175 行）+ `Depends(require_user)`（单用户模式自动回退 `LEGACY_USER_ID=1`，防 401）；C5 `d4ce386` `/favorites` 页（favorites.html fork headlines.html 骨架 + favorites.js ~360 行）+ 47 个 `favorites.*` key × 3 语；`/headlines` 与 `/home` 每条加 `⭐ 收藏` 按钮。
- C6 `8497ba9` + C7：仓储 18 例 + API 22 例 + 4 门禁同步 + `ROOT_ALIASES` 16→17；4 处版本同步 0.100.2 → 0.103.0 + sw.js SHELL_ASSETS 加 `/favorites` 与 `/static/favorites.{html,js}`。

**验证**：
- 仓储 18 例：add / dedup（含不同 source 不冲突）/ update 3 字段任选 / delete 返回 bool / find_by_external / list_items 5 维筛选 + 3 排序 / list_sites / list_tags（distinct + 字母序）/ get_status 6 维聚合。
- API 22 例：GET `/items` 5 维筛选 + 排序 + 分页、GET `/items/{id}` 单条 + 404、GET `/sites` / `/tags` / `/stats` / `/exists`、POST 4 例（feed 回填 / 直传 / 409 / 422）、PATCH 3 例、DELETE 2 例（204 / 404）；autouse fixture 建 LEGACY_USER。
- 单用户回退端到端 1 例 `test_favorites_endpoint_works_in_single_user_mode`：验证 `auth_enabled=false` 下 `/api/v1/favorites/*` 走 `Depends(require_user)` 不 401。 4 门禁：`check_routes.py` EXPECTED_ALIAS_PATHS +1（`/favorites`）/ `check_pwa_assets.py` auto / `check_i18n_keys.py` V083_KEY_PREFIXES +1（`favorites.`）/ `check_static_js.py` auto-discover；维护线 src/ 覆盖率 ~90%+（V0.88.0 基线 90%），Repository 100%。

**教训**：
- 仓储 `update()` 用 Core UPDATE（`Model.__table__.update()` + `commit()`）**不会刷新 identity map** → 下次 `get(fav_id)` 返回陈旧对象 → 加 `expire_all()`（由 get_status 聚合测试暴露）。
- 单用户回退必须端到端测：`conftest._reset_db` 会 drop_all → 需 `autouse fixture` 显式建 LEGACY_USER（API 22 例全加 `_ensure_legacy_user` 兜底）。
- 依赖注入链路要包含 `feed_repo`：`UserNewsFavoriteService.__init__(fav_repo, feed_repo=None)`，`get_user_news_favorite_service` 同时注入两者，`add()` 才能从 `news_feed_items` 回填快照。
- 「拆 HTML+JS」模式（V0.99 沉淀）复用：favorites.html 12k + favorites.js 16k 拆出，`check_static_js.py` glob 自动发现，零额外配置；改 static 必须 bump SW VERSION（加 `["/favorites", "/static/favorites.html"]` 清理）。

### V0.104.0 · headlines 按日期分页（单日模式 + 日期导航）

**背景/问题**：
- 用户原话：「我们在 headlines 添加按照新闻日期的分页功能。这样方便用户查看新闻」。
- 现有 `/headlines` 只有「最近 N 天」窗口过滤（1/7/30 天）；想精准查看某一天（比如 3 天前）的所有新闻，唯一办法是把窗口拉大到 30 天，被迫看 30 天的列表才能找到目标日期。
- 已锁定 2 个决策：① 单日模式 + 日期导航（工具栏新增 ◀ / [日期选择器] / ▶ / 回到今日；与现有 1/7/30 天范围互斥）；② 浏览器本地时区 —— 用户看到「2026-10-19」= 他电脑上的当天 0:00-24:00。

**修法**：5 件大项 / 4 commit + 1 release。
- `GET /api/v1/news-feed/items` 新增 2 query param：`date`（`str | None`，YYYY-MM-DD）与 `tz_offset_minutes`（`int`，默认 0，带符号，东八区 = +480）；**与 `days` 互斥**，同时给 → 取 `date`，`days` 忽略。
- `NewsFeedListOut` 新增 3 字段：`current_date`（回显的 date，None = days 模式）/ `has_older` / `has_newer`；`total` 语义保持不变（`= len(items)`）。 仓储核心 SQL：`date` 分支用 `datetime.combine(date, time.min, tzinfo=tz)` 到 `day_end` 做 `publish_date >= day_start AND publish_date < day_end`；`days` 分支保留旧逻辑。另加 `has_items_outside_day()` 2 个 `LIMIT 1` EXISTS 存在性查询，不走 COUNT，走 `ix_news_feed_items_publish_date` 索引 < 5ms。
- 前端：`#dateNav` 默认 hidden；点日期控件 → 清空 `#rangeBtns` 的 active、API 改用 `date=`；点 range 按钮 → 隐藏 `#dateNav`、`#datePicker` 复位到今天、API 改用 `days=N`；`#btnPrevDay` / `#btnNextDay` 按 `has_older` / `has_newer` 置 disabled；`#btnToday` 仅在 `currentDate !== today` 时显示。i18n +3 key × 3 语。

**验证**：
- 仓储 4 例 date 模式 + 4 例 `has_items_outside_day`；API 6 例（date 模式 + tz offset + 422 + 互斥）+ 9 回归。
- Puppeteer `scripts/_verify_date_nav.mjs` 4 状态：初始 dateNav hidden + 7 天 active + 列表非空；选昨天 dateNav 显示 + ◀ 启用 + 回到今日显示；选今天 ▶ 禁用 + 回到今日隐藏；切回 7 天 dateNav hidden + 7 天恢复 active。
- 4 门禁全部自动覆盖（无新 alias）；验收清单逐条打勾：sw.js VERSION 同步 bump（activate 清 RUNTIME_CACHE 旧 `/headlines` 307）、3 语 i18n 同步、现有 days 模式 0 字段破坏、单日/范围模式互斥、翻页按钮 disabled 与 `has_older`/`has_newer` 一致。

**教训**：
- `date=None` 时 SQL 与上一版 **byte-identical** —— 现有 6 个 `data["total"] == len(items)` 断言全部保留，这是「0 字段破坏」的保障。
- 时区偏移符号约定 JS vs Python 易混 → `tzOffsetMinutes = -getTimezoneOffset()`，2 个测试用例固化。
- 刻意不做：「加载更早 N 天 append 模式」（已选单日模式）、日期范围 from-to、无限滚动、不改 `total` 字段语义、不改 `fmtBjtDate`、不改 `/scoring` / `/trades` / `/home` 等其他页。
- 已知边界接受现状：`has_older=true` 但 limit=100 时 ◀ 可能落 0 条（进阶 next_day/prev_day 字段下版本做）；`<input type="date">` 老 Safari 不一致（现状 scoring.html / trades.html 已用，无反馈）。

### V0.105.0 · headlines 分类筛选（5 类 + 多 switch）

**背景/问题**：
- 用户原话：「主要聚焦页面财经内容」。
- 用户在 `/headlines` 观察发现所有新闻都聚焦于财经 / 经济向（readhub 内部 API 6h 抓取窗口里 **80%+ 是财经**，挤掉了科技/创投/商业等其他类目）；当前无任何类目筛选，想看科技/创投类新闻时无能为力。
- 已锁定 3 个决策：① 5 类（财经 / 科技 / 创投 / 商业 / 其他，readhub 内部主题分类）；② 后端关键词分类器 rule-based —— readhub API 不带类目参数，必须自己分类；③ 顶部下拉筛选（不强制用 chip strip，灵活）。

**修法**：5 件大项 / 5 commit / 13 文件。
- 新建 `src/app/repositories/news_classifier.py`：`CATEGORIES = ("财经", "科技", "创投", "商业", "其他")` + 4 个关键词字典（顺序重要：财经优先），`classify(title, summary, site_name)` 按 `f"{title} {summary} {site_name}".lower()` 逐级命中。
- 3 路 backfill：Lazy（`service.refresh()` 走 `_normalize` 自动分类新条目，6h ≤ 20 条）/ Eager（`main.py` lifespan `_backfill_news_categories()`，64378 行 / 500 batch ≈ 130 批 × 50ms ≈ 6-10s，异步跑不阻塞 readiness）/ Upsert（`upsert_bulk` 的 set_ 含 `category=stmt.excluded.category`，O(1) per row）；`backfill_categories` 只处理 `category IS NULL` 行，幂等。
- API：`GET /api/v1/news-feed/items?category=科技` 新 query param + 新端点 `GET /api/v1/news-feed/categories`（distinct + 频次降序）；`NewsFeedItemOut` 加 `category: str | None`（未分类则 None），`NewsFeedListOut` **不变**（不破坏 V0.104 既有 3 字段契约）。 前端：`#categorySel` 作为工具栏第 5 控件（在 `#langSel` 之后 / `<span class="spacer">` 之前）；i18n 6 key × 3 语 = 18 项（`filter_category` + 5 个 `cat_*`）。

**验证**：
- 测试：分类器 9 例 + 仓储 10 + 7 + API 22 + 6 = 52 测试全过。
- 4 门禁：`check_routes.py` 无变化（无新 alias，`category` query param 不算 alias）/ `check_pwa_assets.py` **必跑**（VERSION bump v0.104.0→v0.105.0）/ `check_i18n_keys.py` 自动过（`headlines.` 前缀已白名单）/ `check_static_js.py` 自动过；`ROOT_ALIASES` 17 不变。
- Puppeteer `scripts/_verify_category_filter.mjs` 8 状态：初始 `categorySel="全部"` + 列表非空 + 下拉含 5 类 + 「全部」placeholder；选 5 类列表只剩该类；切回「全部」列表恢复；选「财经」+ date 2026-10-18 时 API 请求同时带 `category=财经&date=2026-10-18`。

**教训**：
- `on_conflict_do_update` 的 set_ 不加 category → 旧行永远 NULL —— 源文件把这条列为「**必须**」。
- 分类与时间**正交叠加**：切 category 不清 date/days/site/language，反之亦然；`has_older` / `has_newer` 不带 category 过滤（翻页语义不变，empty-state 接受「该日无此类新闻」）。
- 已知取舍：rule-based 分类器准确率 ~70-80%（上限），源文件写明「V0.106+ 引入 LLM 分类」；5 类索引选择率低（cardinality 5），SQLite 仍会选 B-tree 索引用于 LIMIT-bound query。
- 刻意不做：LLM 分类、卡片显示类目 badge（让分类纯粹是筛选轴，不污染卡片视觉）、改 `fmtBjtDate`、给 `has_items_outside_day` 加 category 过滤、扩展 5 类以外的类目、修 3 个 pre-existing stale 断言（V0.98 retrofit 范围）。

### V0.106.0 · 今日要闻顶 nav 提级 + scheduler 6h→4h 加密

**背景/问题**：
- 用户原话：「当前今日要闻页面连接 提升到 导航栏 首页之后 决策之前，并且更新策略也没有实现，修改成每四小更新一次财经新闻」。
- 问题 1：V0.102 起的「今日要闻」(`/headlines`) 藏在「情报」scene 下的 5 个子页之一（消息面评估 / 央行购金 / 白银追踪 / 今日要闻 / 我的收藏），用户想看新闻需要先点开「情报」再下钻，多 1 跳。
- 问题 2：V0.102 默认 6h 刷新一次（UTC 00/06/12/18 ≈ BJT 08/14/20/02），readhub 内部 API 1h ≈ 8-15 条新流，6h 抓一次覆盖率偏低。

**修法**：2 件大项 / 2 commit / 5 文件。
- 顶 nav 从 V0.98 的 7 scene 变 8 scene：🏠 首页 → 📢 今日要闻 → 📊 决策 → 💼 持仓 → 📰 情报 → ⚙️ 配置 → 🤖 AI → 🩺 数据健康。「今日要闻」从「情报」子页**提级**为顶级场景（独立顶项，无 sub-tabs）；「情报」scene 子页从 5 减到 4；顶 nav 总数 7 → 8，独立顶项 3 → 4；决策 scene 仍是 4 subpages。
- scheduler：`NEWS_FEED_INTERVAL_HOURS` 6 → 4；UTC 触发时刻 00/04/08/12/16/20（≈ BJT 08/12/16/20/00/04）；日抓取 4 → 6 次（+50%）；日新增覆盖率 ~32-60 条 → ~48-90 条。 触发小时动态化：`hours = tuple(range(0, 24, NEWS_FEED_INTERVAL_HOURS))`，将来改 3h / 2h 只需改 1 个常量，日志 `hours_label` 自动同步。
- C1 改 topnav + scheduler + sw.js 中间 bump v0.105.0 → v0.105.1 + 新增 `tests/test_services/test_scheduler_news_feed.py` 8 例；C2 4 处版本同步 v0.105.0 → v0.106.0 + CHANGELOG + release notes。

**验证**：
- 测试 60 全过（新增 scheduler 8 例 + 旧 52 例）。
- 4 门禁：`check_pwa_assets.py` **必跑**（VERSION bump v0.105.0→v0.106.0）/ `check_routes.py` 无变化（topnav 改动不影响路由表）/ `check_i18n_keys.py` 自动过（无新 key）/ `check_static_js.py` 自动过；`ROOT_ALIASES` 17 不变。
- Puppeteer 核对顶 nav 顺序，「今日要闻」高亮时无底部 sub-tabs，「情报」sub-tabs = 消息面评估 / 央行购金 / 白银追踪 / 我的收藏（4 个）。 运行时观察：服务启动后 30s 内首次抓取，之后每 4h 抓一次；`news_feed_loop` 日志显示 `every 4h (00/04/08/12/16/20 UTC)` 而非 `00/06/12/18`。

**教训**：
- 提级理由写成三条语义判断：① 顶级 scene = 高频入口 / 跨域场景，子页 = 同一主题下细分，今日要闻是独立主题（新闻流）；② 首页 + 决策 + 持仓是三大主操作，「实时新闻」放决策前符合「看新闻辅助决策」的心智模型；③ 用户原话明确要求「首页之后 决策之前」的位置。
- 子页减少的可达性风险用「从 2 跳到 1 跳」抵消 —— 顶 nav 第 2 位就是今日要闻，**可达性反而提升**。
- 刻意不做：合并「今日要闻」与「情报」scene（语义不同：情报 = 内部研究 + 收藏，今日要闻 = 外部新闻流）、加 favicon / PWA 快捷方式、scheduler 改 env 可配置（用户没要求，硬编码就够）。
- 风险与缓解：顶数 7→8 占更多水平空间（topnav 已有 `flex-wrap: wrap`，V0.98 设计时已预留 8+ 顶项空间）；抓取频率 +50% 的限流风险（实测 readhub 6h/4h/2h 无 429，fetch cache 5min 兜底）；凌晨触发（scheduler 异步执行，不影响可用性）；用户回退旧版（中间 bump v0.105.1 + 最终 bump v0.106.0）。

### V0.107.0 · 今日要闻按天聚合 + 刷新 UX 改进

**背景/问题**：
- 用户原话：「当前今日要闻 页面新闻 客户刷新后可以实现新闻更新么， 新闻的存储也需要按照天进行保存。制定计划开始实施」。
- 问题 1：`news_feed_items` 是单条粒度表（每条新闻 1 行），「/headlines 顶部 daily 摘要」每次都靠 `GROUP BY` 实时算（~30 天 × 1 次查询 ~5-20ms），**没有持久化的按日快照**。
- 问题 2：刷新按钮是 emoji-only 🔄，success 路径**无 toast**（fail 才弹），用户点击不知道触发了 readhub 调用；且 fav 收藏 toast 因 `PMToast` 拼错**静默 dead**（F12 看不到错）。 问题 3：alembic 双 head `n0a1b2c3d4`（V0.103 收藏）+ `n0o1p2q3r4`（V0.105 类目）从 V0.102 `m9g0a1b2c3` 分叉后**未合并**，`alembic heads` 一直返回 2 个 head。

**修法**：7 件大项 / 7 commit / 16 文件。
- C1 新建 `NewsFeedDaily` ORM（仿 `scoring_daily_wide` 的 date-as-PK 模式，15 列：`total_count` + 5 类目计数 + `unique_sites_count` + `en_count`/`zh_count` + `first/last_publish_at` + `last_refresh_at`），**不挂 user_id**（news 是 shared context，V0.80.0 #159 例外）；合并迁移 `n1o2p3q4r5` 用 `down_revision = (n0a1b2c3d4, n0o1p2q3r4)` tuple → alembic 自动合并 2 个 head，带 `_table_exists()` 幂等保护，**不**做 data backfill。
- C2 仓储 4 方法（`upsert_daily` / `get_daily` / `list_daily` / `backfill_daily`）：`upsert_daily` 用 BJT 边界 → 单条 SQL 聚合 → `INSERT ON CONFLICT(date) DO UPDATE`；**当日为空 → 返回 None（不创建空行）**。 C3 service 4 方法 + 2 端点：`GET /api/v1/news-feed/daily?date=YYYY-MM-DD`、`GET /api/v1/news-feed/daily/list?start=&end=`（start ≤ end，跨度 ≤ 90 天）；C4 scheduler refresh 后**始终**重建 BJT today + BJT yesterday 2 行（覆盖跨 BJT 午夜场景，self-healing，≈ 20ms），启动 lifespan 再 spawn_background 回填 30 天。
- C5/C6 前端：`/headlines` 顶 `#dailySummary` + `/home` 标题下方 `#homeDaily`（3 语各 +6 keys）；刷新 success 路径补 `PM_Toast.show(msg, n > 0 ? "success" : "info")`（3 语各 +3 keys）；顺手修 `window.PMToast` → `window.PM_Toast` typo（headlines.js 3 处 / home.js 4 处 / favorites.js 2 处 / 重复 fav handler 1 处，共 4 文件 11 处）。

**验证**：
- `python -m alembic upgrade n1o2p3q4r5` 后 `alembic heads` 应只有 `n1o2p3q4r5`。
- 测试：仓储 24 passed（+6）/ API 30 passed（+6）/ scheduler 8 passed；`check_i18n_keys.py` 0 missing / 185 in-scope（V0.106 = 179，+6）/ `check_static_js.py` 49 个 JS 全部通过 / `check_routes.py` 18 路由（+1 daily +1 daily/list，ROOT_ALIASES 17 不变）。
- 手动验证（2026-10-19 17:xx 实测）：`/daily?date=2026-10-19` → 27 条，finance 4 / tech 10 / biz 7 / other 6；`/daily/list?start=2026-10-15&end=2026-10-19` → 3 行；启动 lifespan 完成后 DB 里有 ~3-5 天 daily 行（历史无数据日跳过）。 Puppeteer：`scripts/_verify_daily_summary.mjs`（headlines 顶 + home chip 显示 daily）+ `scripts/_verify_refresh_toast.mjs`（点 🔄 → 看到 success toast）。

**教训**：
- daily 表是 BJT 日、items 表是 UTC —— 文档里加 BJT 标注，UI 也写「今日摘要（按 BJT 日）」，避免用户查 items 但 daily 显示不同。
- 刻意不做：page load 时 > 2h 自动刷新、daily 做成 incremental update（重算 30 天 = 30ms，复杂度不值）、给 daily 加 user_id、加 admin 守卫、daily 周报 / 月报聚合、跨语言 daily 聚合。
- `uv lock` 网络阻塞（PyPI 超时）→ 手动 bump uv.lock 4-place（pyproject.toml 无 dependency 变更）。
- 三者构成完整的「实时新闻流」能力栈：**4h 抓 → 按天聚 → 用户一键刷 → toast 反馈**。

### V0.107.1 · 今日要闻分类聚焦 + 弃入「其他」+ page_size=50

**背景/问题**：
- 用户原话：「今日要闻的摘要并没有实现统计，主要聚焦于财经方面的新闻，优化一下今日要闻的新闻抓取逻辑，聚焦 财经 科技 创投和商业」。
- 问题 1：V0.107.0 的 `news_classifier.py` 关键词字典偏薄 —— 财经 32 / 科技 33（含 1 处「英伟达」重复）/ 创投 23 / 商业 22，导致生产 ~26% 落入「其他」兜底。
- 问题 2：「其他」类目对用户**无意义**（不命中 4 类关键词的杂项新闻），但 V0.107 的 daily 摘要**展示了**「其他 pill + 计数」，UI 上看起来像正常数据，干扰用户「主要聚焦财经」的判断。 问题 3：readhub API max 100 条/页，V0.102 设 `page_size=20` + 6h 调度（V0.106 改 4h）覆盖太薄，4h 周期可能漏抓新分类条目。问题 4：`_TECH_KW` 末尾有重复「英伟达」（旧版 L44 bug）。

**修法**：4 commit / 12 文件。
- C1 关键词字典焦点化扩充（保持既有优先级 `财经 > 科技 > 创投 > 商业 > 其他`）：财经 32→67（行情 / 主体 / 宏观 / 人物 / 机构）、科技 33→49（硬件公司 / 前沿 / 节点）、创投 23→36（行为 / 身份 / 事件）、商业 22→32（扩张 / 渠道 / 经营）；`classify()` 函数签名与 CATEGORIES 5 类不变；修掉重复「英伟达」。
- C2 fetcher `fetcher._normalize()` L130-146 末尾拦截：分类为「其他」→ `logger.debug` + `return None`（不写入 DB）；`_DEFAULT_PAGE_SIZE` L62 由 20 → 50（readhub max 100；实测 P99 <2s）；User-Agent `gold-etf-analyzer/V0.102` → `V0.107.1`。 C2 service `service.refresh()` L96-126 二次 gate（defense-in-depth）：`_ALLOWED_CATEGORIES = ("财经", "科技", "创投", "商业")` 过滤 records；全被过滤时**软失败**返回 `{"ok": False, "upserted": 0, "error": "no valid items after category filter"}`（保留「保留末次」UX，参考 V0.84 状态条合并模式）。
- C4 4 处版本同步 v0.107.0 → v0.107.1（uv.lock 同样因网络阻塞手动 bump）；**不**改仓储 `upsert_bulk`（不加 SQL WHERE）/ **不**改 API 端点 / **不**改 schema / **不**改前端 5-cat pill 结构（兼容 V0.107.0 历史 297 行）。

**验证**：
- 测试 40 新增：分类器 10→30（4 类字典规模下限 finance≥60 / tech≥50 / vc≥35 / biz≥30 + tech 去重 + 12 新关键词命中 + 2 优先级回归）、fetcher 16→18（fetcher drop「其他」）、service 新建 3 例（混合 records → 只 4 类 upsert / 全「其他」→ 软失败 / 全 4 类 → 全部 upserted）、API 30→32（`/items?category=其他` → 空列表）。
- 40 PASSED + 1 pre-existing failure（`test_list_items_filter_days` 日期漂移：seed 10-17/18/19 而今天 10-20，与 V0.107.1 无关，按 MEMORY conftest-test-isolation 不阻塞发版）。
- 手动验证：`GET /daily?date=2026-10-19` 期望 `other_count == 0` 且 `finance_count > 0`（最高，因字典扩充）；`GET /items?category=其他&days=7` 期望 `total == 0`（新行不入 DB，legacy 297 行可能返部分「其他」属正常）。 Puppeteer `scripts/_verify_daily_summary.mjs` 验证「其他」pill = 0；期望摘要形如「财经 23 · 科技 42 · 创投 N · 商业 14 · 其他 0 · 共 79 条」。

**教训**：
- 关键词过度匹配（边界词「估值」「收购」同时命中 2 类）→ 优先级固定 `财经 > 科技 > 创投 > 商业`，由旧测试 `test_classify_finance_overrides_vc_when_both_hit` + 新测试 `test_classify_finance_overrides_vc_new_v01071` 双回归锁住。
- legacy 297 行「其他」历史数据**不删**（保留数据完整性）；`backfill_categories` 只处理 `category IS NULL`，**不**重写已有「其他」—— 设计正确，新 refresh 后当日 `other_count = 0`。
- service 测试的 patch 位置有坑：service 顶部是局部引用 → 必须 patch `app.services.news_feed.fetch_readhub_feed`。
- 刻意不做：改 `CATEGORIES` 5 类定义、「其他」pill 恒 0 + 灰化 CSS（推迟到 V0.108）、删 DB 历史「其他」行、加 `exclude_other` API 参数、加 `lastCursor` 分页（base64 逆向成本不值）、改 `/items` endpoint signature、升级 V0.108（用户确认 V0.107.1）。

### V0.108.0 · 今日要闻站点黑白名单 + 财经二次加强

**背景/问题**：
- 用户指令：「走方案B，然后再进行财经新闻加强。」readhub 是全站聚合流，30 天窗口出现 31 个来源，本次用**站点维度**做质量治理。
- 问题 1 聚合源的噪声：生产库 30 天窗口 200 条样本的站点分布实测 —— 新浪科技 26（抽样 6 条里 4 条是地方新闻 / 文艺活动）、格隆汇 / 财联社 / 华尔街见闻 / 第一财经 80（财经核心）、IT 之家 / 快科技 27（科技核心）、techradar.com / 9to5Mac 18（海外科技，有广告但主体有效）、澎湃新闻 3（**优质**，抽样 3 条全为量子网络 / 重大应用场景）、站长之家 3。新浪科技 26 条里只有 1 条（ETF）真正相关 —— **信噪比 26:1**，它本质上是新浪的**转载聚合入口**。
- 问题 2 优质源因摘要为空被误杀：readhub 上财经垂直源经常给空摘要，正文关键词命中不了 → V0.107.1 的 classify 判「其他」→ 被 fetcher 弃入；而**站名本身**才是最可靠的类目信号，但 V0.107.1 之前只有 8 个站名进了词典。

**修法**：方案 B（站点白名单）实际拆成**两条腿**，因为纯白名单会误杀 readhub 新增的优质源（31 个源里不少是新面孔）。
- 正向腿（`92bfd4c`）：33 个优质源的站名直接写进对应关键词元组，**零新增逻辑** —— 财经 +9（第一财经 / 金融界 / 同花顺财经 / 界面新闻 / 中国证券报 / 上海证券报 / 证券时报 / 经济观察报 / 每日经济新闻）、科技 +16（IT 之家 / IT之家 / 快科技 / C114 / 钛媒体 / 品玩 / 爱范儿 / 机器之心 / 雷峰网 / techradar / zdnet / 9to5Mac / theblockbeats / techflowpost / 蓝点网 / infoq）、创投 +7（36Kr / 创业邦 / 投资界 / 铅笔道 / IT桔子 / IT 桔子）。
- 负向腿（`35054ec`）：`SITE_BLOCKLIST = frozenset({"新浪科技", "maomu.com"})`；`_normalize` 在 `classify()` **之前**拦。收录纪律三条全满足才进黑名单，写进代码注释防止以后凭印象扩大：① 30 天窗口样本量 ≥ 10 条；② 抽样 ≥5 条里与 4 类无关的比例 ≥ 60%；③ 不是任何优质垂直媒体的转载源。
- 财经二次加强：词典 67 → 100+ 词，分 5 组 —— 大宗（白银 / 现货 / 商品期货 / 期权 / 套期保值 / 金价 / 银价 / 离岸人民币 / 外汇储备 / 跨境支付 …）、监管（证监会 / 银保监会 / 金融监管总局 / 国常会 / 中央经济工作会议 / 政治局会议 / 两会 …）、国际央行（欧央行 / ECB / 日银 / 日本央行 / BoJ / IMF / G7 / G20 / WTO / OPEC …）、银行险资、人物（潘功胜 / 周小川 / 易纲 / 拉加德 …）。
- 防御层：L1 fetcher._normalize（category ∈ 4 类 AND site_name ∉ SITE_BLOCKLIST）/ L2 service.refresh()（复用同一段 tuple 过滤，不新增分支）/ L3 news_feed_daily（不动）；L2 的存在意义是模拟「fetcher 的黑名单检查被漏改」，service 仍能拦住。

**验证**：
- 只读实测（真实 readhub，page_size=50，1250ms）：`20 raw → 13 normalized`，财经 8（61.5%）/ 科技 5（38.5%）/ 创投 0 / 商业 0 / 其他 0；V0.107.1 同口径是财经 52.9%，**财经占比 +8.6pp**。
- 单测：分类器 41 例 / fetcher 28 例 / service 5 例全绿；新增 25 例（白名单站点：财经 10 / 科技 11 / 创投 6；财经加强 5 组：大宗 / 监管 / 国际央行 / 银行 / 人物；黑名单：fetcher 5 + service 3）。
- 提交拆分 4 个：`35054ec`（fetcher 黑名单 + service gate 复用）/ `92bfd4c`（财经加强 + 白名单站名）/ `af472f6`（黑名单 8 例）/ 本次（4 处版本同步 v0.107.1 → v0.108.0 + CHANGELOG + release notes）。

**教训**：
- 刻意**不**拉黑的：初版名单里一度把澎湃新闻也列进黑名单，拉数据时**实测推翻了**（3 条全优质：136 项标志性重大应用场景清单 / 量子网络跨节点相位锁定 / 社会如何减震），已从名单撤除并**写成断言钉住**；techradar / 9to5Mac 同理保留。
- 留下 2 个已知问题不修（留 V0.109）：① `_BIZ_KW` 的「发布」过泛 —— 「俄罗斯称袭击乌克兰敖德萨地区四艘货船」被判**商业**（摘要里出现「发布」），修法方向是给 `_BIZ_KW` 加**负向黑名单**（战争 / 冲突 / 事故 / 灾害等）或把「发布」限定为「发布会 / 发布新品」；② `test_list_items_filter_days` 已失败 —— 硬编码 10-17 / 10-18 / 10-19 三个 seed 日期，今天是 10-20，`days=1` 的 cutoff 已把它们全排除，在干净 HEAD 上（`git stash` 验证）同样失败，属日期轮转导致的 pre-existing 失败。
- 刻意不做：引入 LLM 分类、改其他类目定义、把「其他」pill 灰化（推迟到 V0.108+ 留给真正需要时）。

### V0.109.0 · 分类词边界修复 + 发布词精度

**背景/问题**：
- 性质：数据质量 bugfix —— V0.108.0 引入的词典放大效应在生产数据上暴露。
- 缺陷 1 `PE` 命中 `Europe` / `OpenAI`：`PE`（市盈率）自 V0.105 起就在 `_FINANCE_KW`，而财经是**最高优先级**；分类器对英文只做子串匹配 `any(kw.lower() in text for kw in keywords)`，于是 `"pe" in "europe"` 为真、`"pe" in "openai"` 也为真 → 所有提到欧洲或 OpenAI 的新闻，无论主题是什么，都会落进财经。
- V0.108.0 把财经词典从 32 词扩到 100+ 词、把白名单站名写进词典，这套「站名/短词即信号」的设计**放大**了这个既有缺陷 —— 不是 V0.108.0 引入的 bug，但它在 V0.108.0 之后才被量化出来。
- 缺陷 2 中文裸词「发布」：中文没有词边界，`"发布" in text` 会命中一切含「发布」的文本 —— 这正是 V0.108.0 release notes 里记录的「已知问题 1」。

**修法**：
- 长度 ≤3 的纯 ASCII 词改走**词边界正则**，其余（长英文词 / 全部中文词）保持子串匹配：`_BOUNDARY_PATTERNS = {kw: re.compile(rf"(?<![a-z]){re.escape(kw.lower())}(?![a-z])") for kw in (...) if kw.isascii() and len(kw) <= 3}`，边界表共 **37 词**。
- 37 词清单：`PE ETH ETF BTC AI GPU CPU AMD IBM GPT 5G 6G 3nm 5nm 7nm AGI IPO VC FA GP LP BP CEO CFO COO CTO ECB BoJ IMF WTO GDP PMI QE G7 G20 M&A`；复合词显式补齐 `AIGC` / `AGI` / `GPU云` / `算力云`（否则 `AI` 因后接字母 G 被边界拒掉）。 中文侧裸词 `发布` → `发布会` + `发布公告`。
- 提交拆分 3 个：`21da095`（短 ASCII 词词边界 + 裸词「发布」改「发布会」）/ `28c732d`（词边界 6 例 + 发布词精度 3 例）/ 本次（4 处版本同步 v0.108.0 → v0.109.0 + CHANGELOG + release notes）。

**验证**：
- 生产 DB 576 条全量对拍（修复前朴素匹配 vs 修复后 classify）：`→ 财经 → 科技: 28`（全部是科技新闻被误判）、`财经 → 财经: 226`、`科技 → 科技: 174`、`商业 → 商业: 6`、`创投 → 创投: 4`、`→ 科技 → 其他: 1`、`→ 财经 → 其他: 1` —— **总变化 30/576（5.2%）**；触发词统计 `PE` 单独造成 28 条、`ETH+PE` 1 条、`PMI` 1 条。
- 新增 9 例（分类器 41 → 51）分两组：`TestWordBoundary` 6 例（含 `test_pe_no_longer_matches_europe` 核心回归、`test_pe_still_matches_standalone` 防修过头、`test_eth_no_longer_matches_ethiopia`、`test_openai_now_classifies_tech`）+ `TestPublishKeywordPrecision` 3 例；全量 `test_news_classifier` 51 / `test_readhub_fetcher` 28 / `test_news_feed` 24 / `test_news_feed_service` 5 = **108 passed**。
- 取舍表逐条验证：`2026PE` ✅ 命中 PE（数字不是字母边界，中文财经报道常见写法）、`科创50ETF` ✅ 命中 ETF（汉字不是 ASCII 字母边界）、`pe(ttm)` / `静态 pe` ✅ 命中、`OpenAI` / `Anthropic` ✅ 不受影响（长词不在边界表）、`Europe` / `European` / `shape` ❌ 不再误命中 PE、`Ethiopia` ❌ 不再误命中 ETH、`AIGC` ✅ 显式补词。

**教训**：
- 写测试时被实测纠正的两处 —— 是代码对、预期错：`classify("比特币突破", "", "")` 期望命中 `BTC`（纯中文文本本就不会字面出现 `BTC`），改用 `btc 突破新高`；`classify("OpenCode 2.0 正式发布", ...)` 期望科技（`OpenCode` 不在科技词典里，命中的是「发布」判商业，与缺陷 2 同源），改用 `Oppo 计划进军欧洲智能市场`。
- 中文侧移除裸词后，**失去唯一商业依据的恰好就是那 4 条噪声**，而生产数据里 7 条真正的「发布会」商业新闻全部保留 —— 修得干净，没有误伤。
- 遗留明确写下：历史数据未重分类 —— DB 里已有的 576 条仍带旧分类；`scripts/reclassify_v01071.py` 当前只扫 `category='其他'` 的行，**不覆盖**本次场景（被误判成财经的 28 条科技新闻），需要一个全量版，此项留 V0.109.1 或部署时一并处理。

### V0.109.1 · 分类架构改为「内容优先、站名兜底」

**背景/问题**：
- 性质：修正 V0.108.0 的设计失误。V0.108.0 把 33 个优质站名写进了内容关键词词典，而财经优先级最高 —— 于是**站名压过内容**；V0.108.0 那个「财经 226 条」的漂亮数字主要是假象。
- 实测证据：生产 DB 576 条全量对拍，一句话口径为 **160 条（27.8%）纯靠站名定类**；正文证据表列 6 个来源（格隆汇 35 / 财联社 26 / 第一财经 23 / 华尔街见闻 14 / techradar.com 18 / IT 之家 17），并写「合计 **182 条**纯站名定类」。内容样例：「印度东部踩踏致 17 人死亡」「伊拉克弹药仓库爆炸」「法国多地大规模抗议」因发稿站点是财联社 / 第一财经而混进财经流。
- 两条实测结论：① 通讯社那一档（约 100 条）全是与财经无关的国际新闻，**该丢**；② 科技垂直站那一档（约 60 条）是真科技新闻，**该留**。分界线不是「财经 vs 科技」，而是**垂直媒体 vs 综合通讯社**。

**修法**：
- 两段式分类：**内容优先**（`title + summary` 命中 4 类词典，优先级 `财经 > 科技 > 创投 > 商业`）→ **站名兜底**（内容一条都没命中时才查 `_SITE_HINTS`）→ **弃入**（都落空 → 「其他」，fetcher 不入库）。
- 站名兜底**只对垂直媒体开放**：财经垂直媒体（金十数据 / 同花顺财经 / 金融界 / 中国证券报 / 上海证券报 / 证券时报 / 每日经济新闻）✅、科技垂直站（techradar / 9to5Mac / IT 之家 / 快科技 / C114 / 钛媒体 / 品玩 / 爱范儿 / 机器之心 / 雷峰网 / 虎嗅 / 极客公园 / 量子位 / zdnet / theblockbeats / techflowpost / 蓝点网 / infoq / 36 氪）✅、创投垂直媒体（36Kr / 36氪 / 创业邦 / 投资界 / 铅笔道 / IT桔子）✅；综合通讯社（财联社 / 格隆汇 / 第一财经 / 界面新闻 / 经济观察报 / 华尔街见闻）❌。通讯社发纯市场内容时仍会被**内容词典**命中（不靠站名），只是内容无关时必须掉进「其他」。
- 兜底表**最长匹配优先**：readhub 的 `siteName` 常带后缀（`C114 通信网` / `IT之家`），子串包含即可命中，更长的站名压过更短的前缀；33 个站名移出内容词典，含 V0.105 起就在的 4 个（财联社 / 华尔街见闻 / 格隆汇 / 金十数据）；指数名（中证 / 上证 / 深证 / 创业板 / 科创板 / 沪指 / 深成指）**不是站名**，保留在 `_FINANCE_KW`。
- 历史 sweep：新增 `scripts/reclassify_v01090.py`，**默认 dry-run**，确认后才 `--apply` 写库（只改分类），`--drop-blocklisted` 连黑名单站点存量行（新浪科技 122 + maomu.com 2）一起清理；脚本会自动重建所有受影响日期的 `news_feed_daily`。与 `reclassify_v01071.py` 的区别：后者只扫 `category='其他'` 的行，本版扫**所有行**。

**验证**：
- 生产 DB 576 条全量：`科技 248 / 财经 58 / 商业 27 / 创投 5 → 入流 338 → 弃入「其他」114 → 黑名单站点（新浪科技 / maomu.com）不入流 124`。
- 国际财经保留：韩国财长谈半导体市场景气至少维持至明年 / 欧洲央行维持利率不变 拉加德发表讲话 / OPEC+ 宣布延长减产协议。国际战事灾难丢弃：印度东部踩踏事故致 17 人死亡 [财联社] / 伊拉克首都一弹药仓库发生爆炸 [财联社] / 法国多地发生大规模抗议 数百人被捕 [第一财经]。
- 新增 7 例（`TestContentFirstSiteFallback`），分类器 51 → 58，全量 **115 passed**；修正 2 例编码旧行为的断言：`test_classify_empty_title_uses_site_name`（V0.105 起，原用「华尔街见闻」，实测该站也发战事新闻）改为财经垂直站正向断言 + 3 家通讯社负向断言；`test_classify_whitelist_finance_site_v01080`（V0.108.0，原断言 10 个财经站全部兜底）改为「7 家财经垂直媒体兜底」。

**教训**：
- 另一条**推翻 V0.108.0 立论前提**的实测：V0.108.0 加白名单的理由是「readhub 上财经源经常给空摘要，站名即最可靠信号」，**但那 182 条里没有一条内容字段为空** —— 收益全部来自科技垂直站（英文评测天然没有中文关键词）这一半。
- 三处预期在写完后被实测纠正（代码是对的，测试预期写错了）：① `某芯片公司完成 B 轮融资` 实际判**科技** —— 科技 > 创投 是既定优先级，「芯片」先命中，补一条无「芯片」的 SaaS 版本才测得到创投；② `_SITE_HINTS` 漏加进 import → `NameError`；③ `韩国财长：半导体市场景气至少维持至明年` 标题单独看只命中「半导体」（科技），财经信号全在**摘要** —— 改用生产库真实摘要写成三元组。
- 已知精度问题（rule-based 上限，通用词碰撞需上下文消歧）：`基金` 命中「上海市**老年基金会**」→ 财经；`经济` 命中「村镇**经济**治理」→ 财经。`upsert_bulk` 遵循「已分类行不变更」纪律，所以只有新抓的条目用新逻辑 —— 这正是必须补 sweep 脚本的原因。

### V0.109.2 · 白银页面数据时效透明化（SGE akshare 数据滞后 2 天暴露）

**背景/问题**：
- 白银 SGE akshare 接口 `ak.spot_silver_benchmark_sge()` 在生产中常见滞后 2-3 个工作日；原 `/silver/sge-quote` 接口只用历史 K 线末根日期当 `updated_at`，前端看不出来 stale，用户连续刷新 cache（5 分钟过期）还是拿到同一日数据 → 误以为「缓存 2 天」。
- 实测 2026-10-20（周二）下午 20:22 BJT：`/silver/quote`（NY SI）last_date 10-20 / 距今 0 天 / sina_si 实时；`/silver/etf-quote`（562800）10-19 / 1 天 / eastmoney 挂 → 降级 sina sz161226 lof_proxy；`/silver/sge-quote`（Ag99.99）**10-18 / 2 天** / `ak.spot_silver_benchmark_sge()` 真源就是 10-18。
- 三个核心漏洞：① `get_silver_sge_quote()` 用历史 K 线最后一行当「最新报价」，但没把日期告诉前端，UI 只显示「13976 元/kg」数字，**用户看不见数据是哪天的**；② 没有任何 staleness 检测 —— akshare 数据如果 3 天前 / 1 周前，系统照样当 live 显示，「数据源健康条」一直显示 ✅ 全 green；③ `renderSourceBar()` 只统计 `data_sources` 里的 live/mock 计数（SGE 数据源 `sge_silver_history` 不在数据源统计里），问题源在 source-bar 完全不可见。
- **不是 cache TTL 问题**（默认 `QUOTE_CACHE_TTL=300` = 5 分钟是合理的）。

**修法**：
- `data_as_of` 字段：给 `SilverQuoteOut` 加 `data_as_of: date | None = Field(None, description="V0.109.2：数据真实所属交易日")`，同样加到 `SilverEtfQuoteOut` / `SilverGramQuoteOut` / `SilverSgeQuoteOut`。3 个效果：报价卡片下方显示「数据日期 2026-10-18」+ 滞后 chip；三市场报价统一携带语义位（不再混用 `updated_at`）；客户端向后兼容（`None` 默认，老 JS 不会报错）。
- 后端 staleness 检测：`_is_data_stale(last_date: date | None, *, max_lag_days: int = 1)` → `trading_days_between(last_date, date.today()) > max_lag_days`；Stale 数据走 `_mark(ok=False)`，source-bar 看到 `mock` 状态 → 用户从主条就知道有问题。
- 前端：`static/silver.js` 3 个卡片下方显示「数据日期 YYYY-MM-DD」+ 滞后 chip（形如「数据日期 2026-10-18 ⚠ 数据滞后 2 天」）；`renderSourceBar()` 健康条尾部追加「⚠️ 部分数据源时效滞后: SGE 上海银 Ag99.99 数据至 2026-10-18（滞后 2 天）」。复用 freshness.js 的 `fsh-chip fsh-warn fsh-stale-chip` 样式 + 与 idxPendingChip 同模式。
- 提交拆分 3 个：`7c5b505`（data_as_of 字段 + staleness 检测，4 后端文件 + 2 测试）/ `7841d2d`（silver.js 数据日期显示 + 滞后 chip）/ 本次（4 处版本同步 v0.109.1 → v0.109.2 + CHANGELOG + release notes）。

**验证**：
- 部署后用户打开 `http://192.168.0.204:8888/silver` 应看到：① NY SI 卡「数据日期 2026-10-20」（实时，无 chip）；② 562800 ETF 卡「数据日期 2026-10-19」（昨日，< 2 天，无 chip）；③ SGE Ag99.99 卡「数据日期 2026-10-18 ⚠ 数据滞后 2 天」；④ source-bar 尾部告警行。
- curl 验证：`curl -s "http://127.0.0.1:8888/api/v1/market/silver/sge-quote" | jq .` 期望 `{ ..., "data_as_of": "2026-10-18", "updated_at": "2026-10-18T00:00:00Z" }`。 测试增量 +10 全绿：`tests/test_utils/test_market_clock.py` +7 `trading_days_between` 用例（同日 / 周中 / 跨周末 / Sun→Mon / Sun→Tue / Sat→Sun / 逆序）；`tests/test_api/test_market.py` 3 个白银 quote 端点加 `data_as_of == today.isoformat()` 断言；`check_pwa_assets.py` ✅ 通过（SHELL_ASSETS 48 条全解析、sw VERSION v0.109.2 同步）。

**教训**：
- stale 阈值用**工作日**而非日历日：Sun(18)→Mon(19) = 1 trading day（跨周末挡路）→ **不**算 stale（正常）；Sun(18)→Tue(20) = 2 trading days → **算** stale（本次故障的真实状态）；工作日定义周一至周五 5×24h（不区分 A 股节假日，SGE 与 A 股同日休市，对齐即可）。
- 5 条设计取舍：不引入新数据源（akshare 滞后是上游问题，加代理源风险大收益小）、不调 cache TTL（300s 5min 合理，问题在 data-as-of 不透明）、阈值用工作日而前端 lag chip 用日历日（简化 UX，与后端略宽但展示够用户理解）、**stale 时仍走真数据路径**（不切 mock）—— 让用户看到真实价 + 滞告，假数据会误导决策。
- akshare 数据源恢复后（典型场景：下周一前 SGE 周末基准价补齐），下次刷新页面 chip 自动消失，无需代码改动。

### V0.110.0 · 宏观因子手动校准 + docs 整理

**背景/问题**：
- 宏观面 5 个因子里 `dxy` / `vix` **没有自动实时源**，用的是 `STATIC_REF` 里 **2026-08-28 的硬编码常量**（96.5 / 18.5）—— 相当于**综合趋势指数的 16% 建立在两个半月前的常量上**，而 UI 上完全看不出来。 权重账：`dxy` 0.25 + `vix` 0.15 = 宏观面内部 0.40；宏观面占综合指数 0.40；合计 **综合指数的 16%**。`us10y` / `us30y` 虽有美联储 H.15 自动源，但上游失败时静默回退到同样的过期常量，且只有一行 `logger.warning`。
- 用户实测又暴露一处降级缺陷：报告「保存失败：Not Found」—— **不是功能 bug，是部署滞后**（static 由 `StaticFiles` **直接读磁盘**、改完立即生效；Python 路由冻结在 uvicorn 进程内存里、必须重启），8888 上的 root 进程（PID 428807，**10 月 18 日**启动）跑着旧代码而 `curl /static/weights.html` 已是新版 → 页面有卡片、后端没端点，保存必然 404。

**修法**：
- 存储：复用既有 `app_settings` KV 表（`WeightService` 已注入 `SettingRepository`），但**新增独立 key** `macro_factor_overrides`，不与 `weight_config` 混存 —— 避免保存权重时把覆盖一起冲掉。`MacroFactorOverride` = `value: float` + **`as_of: date`（必填）** + `note: str | None`；`MacroFactorOverrideSet` 覆盖 dxy / us10y / us30y / vix / cb_gold。
- 优先级链：`_collect()` 从「静态常量 → 自动源」改成**用户手动覆盖 > 自动源（央行购金表 / 美联储 H.15）> STATIC_REF 内置常量**；覆盖的 `as_of` 原样写进 `MacroFactorOut.data_date`，`source` 标为「手动输入」—— **前端按来源决定是否显示滞后 chip**，服务端不做静默过期。
- 端点：GET `/api/v1/settings/macro-overrides`（公开，与 `/settings/weights` 同口径）+ PUT（`require_admin_session`）；整体替换语义 —— 传全 `null` 即清除全部覆盖。 UI：`/weights` 新增「宏观因子手动校准」卡片 5 行（因子 / 当前生效 / 手动值 / 数据日期 / 备注 / 清除）；「当前生效」列直接复用 `loadTrendForPreview()` 已拉取的 `gold/trend` 响应里的 `macro.factors[]` —— **不新增请求**；`source === "手动输入"` → 高亮 + chip；滞后 > 1 交易日 → 琥珀 chip；「清除全部覆盖」走**二次确认弹窗**（复用既有 `confirmDialog`）；i18n 22 key × 3 语。
- 保存即失效**两层**缓存：`clear_macro_cache()`（`MacroFactorService._CACHE`，600s）+ `TrendService.invalidate_cached_results()`（served_cache，600s，在上一层之上）。顺带修掉既有缺陷：`PUT /settings/weights` 原先一个缓存都不清，改完权重后首页最长 10 分钟仍显示旧指数；原 `invalidate_for_news` 改为转发别名（名字带 news 但现在两条写入路径都调它，不改名会说谎）。

**验证**：
- ① **`served_cache` 漏清 —— 功能等于没做（本版最严重的那个）**：只清前者时覆盖已落库、`GET /market/gold/trend` 仍返回 `dxy 96.5 · 2026-08-28` —— 页面提示「已保存」而数值纹丝不动，日志无异常。回归锁 `tests/test_api/test_settings.py` +2，两条都验证过**去掉修复即 FAIL**。
- ② **重渲染冲掉用户正在输入的值 —— 静默提交空值**：首屏 `loadOverrides()` 与 `loadTrendForPreview()` **并发在飞**，冷启动下后者要现拉 60 根 K 线（实测数秒），用户填的 dxy 被迟到的 `loadOverrides()` 冲掉，点击保存提交的就是全 null。修法：`snapshotUserEdits()` 捞出与 `overrideState` 不一致的字段 + `restoreUserEdits()` 写回。 ③ **备注输入框漏 class，整行折行**：`<input id="mo_${key}_n">` 少了 `class="mo-note"`，导致 `.mo-row .mo-note { width: 132px }` 整条 CSS 失效 → 「清除」按钮被挤到第二行，**5 行全是折的**。断言本身也踩坑：初版按 `getBoundingClientRect().top` 判折行，而 `.mo-row` 是 `align-items:center`、同行元素高度不同 → 把「1 行」误报成「4 行」，改判**垂直中心**后正确。另：冷启动「暂无读数」会被读成「因子丢了」→ 新增 `macroFactorState`（loading / ready / failed），加载期间显示中性「加载中…」。
- 降级修复：首屏 `loadOverrides()` 404 后被迟到的 `loadTrendForPreview()` 200 成功渲染**整个抹掉**（用户看到完全健康的表单直到提交才炸）→ `overrideApiMissing` 标志置位时只画琥珀说明块、**不画表单**、藏起表头与「保存 / 清除」按钮；`fetchOverrideApi()` 按 HTTP status 给可行动文案（404 / 403 / 422 / 5xx / 网络层），不再抛裸 status；i18n 8 key × 3 语。另 `.mo-ops` / `.mo-head` 的 `display:flex` 会盖掉 `[hidden]` 自带的 `display:none` —— 必须显式写 `.mo-ops[hidden] { display: none; }`，断言里因此专门加了 `getComputedStyle` 检查。
- 测试与门禁：`_verify_macro_override.mjs` = **15 passed / 0 failed**（新后端正常路径）；`_verify_mo_degraded.mjs` = **9 passed / 0 failed**（跑在**真实的旧后端** 8888 上，不 mock）。测试 +7（settings API）+7（macro service）+4（settings service）+3（links 门禁），回归 **157 passed**；`check_pwa_assets.py` ✅（SHELL_ASSETS 48 条全解析、VERSION v0.110.0 同步）。

**教训**：
- `as_of` **必填** —— 没有日期就算不出滞后，也无法向用户披露时效，这正是 V0.109.2 白银页面踩过的坑；可选字段会被前端「忘了传」。值和日期**都填才生效**（只填其一属半截数据，静默生效比不生效更危险，前端已处理成「视为清除」）。
- 覆盖**不设过期**（填了就一直生效）—— 服务端静默过期会造成「我明明填了却没生效」的困惑；改为前端显式提示滞后天数，把判断权交给用户（滞后透明度 > 自动失效）。 复用 `WeightService` 而非新建服务（`MacroFactorService` 已注入它，同一条 `SettingRepository` 链路，无需新增 DI）；新增独立 key 而非塞进 `weight_config`（保存权重时不应连带覆盖用户的因子校准）。
- 同发版 docs 整理：修掉 `check_links.py` 报出的 **12 条死链**；新增 `check_release_index()` 门禁 —— 死链门禁只看「**已写的链接能不能点开**」，看不见「**该写的链接根本没写**」，`docs/releases/index.md` 停在 V0.100.2 而 V0.103 ~ V0.109 共 9 份 release notes 无人索引且**没有任何门禁报红**，修完发现实际漏了 **13** 份，全部补登记，**刻意不设豁免名单**；另新建 `docs/README.md`、`roadmap.md` 补 9 个版本并重写 §2、`releases/index.md` 新增 §1.4.1 今日要闻逐版本登记。

## 三、这一阶段的通用教训

1. **改静态资源必须 bump `sw.js VERSION`，而且要在改的第一个 commit 就 bump。** SW 按 cache name 清理，VERSION 不变则旧 cache 永远不会被清 —— V0.100.1 为此发了一个 hotfix。此后全区间形成两段式 bump 惯例：功能 commit 中间 bump（`v0.105.0 → v0.105.1`、`v0.106.0` 同例），发版 commit 再统一 bump 成正式版本号（4 处同步：`__version__` / `pyproject.toml` / `sw.js VERSION` / `uv.lock`），并由 `check_pwa_assets.py` 强校验。

2. **词典是放大器：每次扩充都会把既有缺陷按比例放大。** `PE` 的子串误匹配早在 V0.105 就埋下，V0.108.0 把财经词典扩到 100+ 词后才被量化（576 条里 28 条误判）；站名入词典这个设计本身在 V0.109.1 被判定为失误并整段推翻。结论是「扩词典」不是低风险动作 —— 扩完必须拿生产数据全量对拍，不能只看新增测试是否通过。

3. **设计假设要用真实数据验证，且验证结果可以推翻设计本身。** V0.108.0 立论「readhub 财经源常给空摘要，站名即最可靠信号」，V0.109.1 实测发现那批站名定类的条目**没有一条内容字段为空** —— 收益全部来自另一类站点；澎湃新闻因为实测 3 条全优质而从黑名单撤除并写成断言钉住。反复出现的模式是「拉数据 → 推翻名单 → 写断言防回退」。

4. **防御要分层，且每层都要有单测。** V0.107.1 建立 fetcher gate + service gate 两层；V0.108.0 在两层上各加一条站点条件；V0.109.1 把分类逻辑从「一层拼串匹配」改成「内容优先 / 站名兜底 / 弃入」三段。L2 的意义被写明：模拟 L1 的检查被漏改，L2 仍能拦住。

5. **分类逻辑变更后，历史数据不会自动跟着变。** V0.109.0 明确留下这个坑（DB 里 576 条仍带旧分类，`reclassify_v01071.py` 只扫「其他」不覆盖误判成财经的科技新闻），V0.109.1 才补全量 sweep 脚本（默认 dry-run、`--apply` 才写库、并自动重建受影响日期的 `news_feed_daily`）。凡是「改了口径」的版本都要问一句：老数据怎么办。

6. **数据是哪天的，必须能被用户看见。** 这条从 V0.109.2 的 `data_as_of`（akshare SGE 滞后 2 天却一直显示健康条 ✅ 全绿）一路推到 V0.110.0 的 `as_of` 必填（`dxy`/`vix` 常量停在 2026-08-28，综合指数的 16% 建立在旧数上）。推论是：**没有日期就等于没有时效披露**，所以 `as_of` 不能做成可选字段。

7. **「保存成功」不等于「生效」，缓存要按层清。** V0.110.0 只清了 `MacroFactorService._CACHE` 时，覆盖已落库但 `served_cache` 回放旧响应，页面提示「已保存」而数值纹丝不动、日志无异常 —— 这是本区间最严重的一个 bug，且只有 puppeteer 实跑才暴露。顺带牵出 `PUT /settings/weights` 原先一个缓存都不清的既有缺陷。

8. **一次成功渲染可以把真实失败吃掉。** V0.110.0 部署滞后期，`loadOverrides()` 404 后被迟到的 `loadTrendForPreview()` 200 成功渲染整个抹掉，用户看到完全健康的表单直到提交才炸。修法是显式的降级状态位（`overrideApiMissing`）+ 按 HTTP status 给可行动文案，而不是把裸 status 抛给用户。

---

**相关文档**：[能力 × 版本对照表](../index.md)｜ [文档导航](../../README.md)｜ [架构说明](../../architecture.md)｜ [API 参考](../../api-reference.md)｜ [路线图](../../roadmap.md)｜ [CHANGELOG](../../../CHANGELOG.md)