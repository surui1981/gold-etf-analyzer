# Changelog

> 黄金 ETF 投资辅助 · 完整发版历史
>
> 详细 release notes 见 [docs/releases/](docs/releases/) 系列

## [V0.108.0] · 2026-10-20

`今日要闻站点黑白名单 + 财经二次加强` — 站点维度质量治理 + 财经词 67→100+

- 🔻 **fetcher 站点黑名单**（用户方案 B 负向腿）`SITE_BLOCKLIST`
  - 只收 2 个源：`新浪科技`（30 天 26 条里约 4 条地方新闻/文艺活动，ETF 有效内容仅 1 条）、`maomu.com`（加密 spam）
  - 收录纪律（写进代码注释防凭印象扩大）：样本量 ≥10 + 无关比例 ≥60% + 非优质源转载
  - `_normalize` 在 `classify()` **之前**拦 —— 聚合源即使单条能分类（ETF 题材）也不进 4 类流
  - 刻意**不**拉黑 `澎湃新闻`（实测 3 条全优质，初版误列已撤）/ `techradar` / `9to5Mac`
- 🔺 **白名单站点名写入关键词词典**（方案 B 正向腿，复用 classify 通路零新增逻辑）
  - 财经 +9 / 科技 +16 / 创投 +7 = 33 个优质源站名
  - 价值：readhub 财经源常给空摘要，站名即最可靠的类目信号，不再被误判「其他」
  - `IT 之家`/`IT之家`、`IT桔子`/`IT 桔子` 两种空格写法都收
- 📈 **财经二次加强 67 → 100+ 词**（对齐黄金 ETF 分析器的品种与政策变量）
  - 大宗：白银 现货 期权 套期保值 原油 铁矿石 螺纹钢 焦炭 铜价 金价 银价 离岸人民币 人民币中间价 外汇储备 跨境支付 结售汇
  - 监管：证监会 银保监会 金融监管总局 国资委 财政部 发改委 国常会 政治局会议 两会
  - 国际央行：欧央行 ECB 日银 BoJ 英国央行 IMF 世界银行 G7 G20 WTO OPEC
  - 银行险资：六大行 兴业 汇丰 渣打 平安 保监会 险资
  - 人物：潘功胜 周小川 易纲 郭树清 拉加德
- 🛡️ **service gate 复用**：`refresh()` 的既有 tuple 过滤加 `site_name ∉ SITE_BLOCKLIST`，与 category gate 共用一段逻辑不新增分支
- ✅ **测试 +25 例**：分类器 41 / fetcher 28 / service 5 全绿
  - 去重用例当场抓到本次引入的「金十数据」重复（V0.105 已在原 32 词里），已删
  - 修 1 例 V0.107.1 用例站名冲突（「创业邦」进白名单后抢走商业关键词用例的分类，改用中性站名「企业内参」）
- 📊 **只读实测**：真实 readhub 20 raw → 13 normalized，财经占比 52.9% → **61.5%**（+8.6pp），耗时 1250ms
- ⚠️ **已知问题（留 V0.109）**：`_BIZ_KW` 的「发布」过泛，会把战事新闻判成商业（关键词精度问题，非站点问题）；`test_list_items_filter_days` 的日期轮转失败经 `git stash` 验证为 pre-existing

## [V0.107.0] · 2026-10-19

`今日要闻 按天聚合 + 刷新 UX 改进` — news_feed_daily 物化宽表 + alembic 双 head 合并 + 刷新 toast

- 🆕 **news_feed_daily 物化宽表**（migration `n1o2p3q4r5`，双 head 合并 + 新表合一）
  - 1 日 1 行（date 主键，仿 scoring_daily_wide · date-as-PK · 无 user_id）
  - 5 类目计数：finance / tech / vc / biz / other
  - unique_sites_count / en_count / zh_count
  - first_publish_at / last_publish_at（UTC，nullable 当日空）
  - last_refresh_at（最近一次 refresh 重建本行时间，UTC）
  - 共 15 列
- 🆕 **2 端点**：
  - `GET /api/v1/news-feed/daily?date=YYYY-MM-DD` —— 单日聚合，无则 null
  - `GET /api/v1/news-feed/daily/list?start=&end=` —— [start, end] 闭区间 + 倒序，最多 90 天
- 🆕 **仓储 4 方法**：`upsert_daily` / `get_daily` / `list_daily` / `backfill_daily`
  - BJT 边界：`datetime.combine(target_date, time.min, tzinfo=BJT)` → SQLAlchemy 自动转 UTC
  - 单条 SQL 聚合 5 类目 + 独立站点 + 中英文 + 首末时间（9 列单行 GROUP BY）
  - 当日为空 → 不创建空行（保留「DB 反映实际数据」原则）
- 🆕 **scheduler 集成**：refresh 末尾**始终**重建 BJT today + BJT yesterday 2 行（self-healing 跨午夜场景）
- 🆕 **启动 lifespan backfill**：`_backfill_news_feed_daily(30 天)` spawn_background（仿 _backfill_news_categories 模式）
- 🆕 **前端 daily 摘要**：
  - `/headlines` 顶 daily-summary 横条（5 类目 pill + 总数 pill，仿 status-row 风格）
  - `/home` 标题下方 daily 一行（同类目 5 + total）
  - `Promise.all +1 daily 端点`，O(1) 行替代实时 GROUP BY
- 🆕 **刷新 UX 改进**：
  - 刷新 success 路径加 toast（之前仅 fail 弹）
    - upserted > 0 → 「刷新成功，新增 N 条」（success 绿）
    - upserted = 0 → 「已是最新，0 条新增」（info 蓝）
  - 刷新按钮 tooltip 改写：「从 readhub 立即拉取最新」
- 🐛 **PMToast → PM_Toast typo 修**（4 文件 11 处，fav toast 之前**静默 dead**）
  - `static/headlines.js` 3 处
  - `static/home.js` 4 处
  - `static/favorites.js` 2 处
  - `static/home.js` 1 处（重复 fav handler）
  - **影响**：fav 收藏成功 / 失败 toast 之前从不见到 —— 因 PMToast 拼错 → undefined.show() TypeError → 静默吞
- 🔧 **alembic 双 head 合并**：`n0a1b2c3d4 (V0.103 收藏) + n0o1p2q3r4 (V0.105 类目) → n1o2p3q4r5 (V0.107 daily)`
  - `down_revision = (n0a1b2c3d4, n0o1p2q3r4)` tuple 自动合并
  - 之后是单一 head（V0.108+ 不再有多 head 状态）
- 🔧 **i18n stale 修**（V0.106 漏改）：`headlines.subtitle` 「每 6 小时」→「每 4 小时」3 语统一
- 端点 17 → 18（+2 daily，-0 移除），仓储 16 → 20 测试
- 静态 JS 49 个全部通过（check_static_js.py）

[详情](docs/releases/v0.107.0.md)

>
> 能力 × 版本对照（"哪个能力在哪个版本落地"）见 [docs/releases/index.md](docs/releases/index.md)

本项目遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/) 与 [Conventional Commits](https://www.conventionalcommits.org/zh-hans/) 规范。

---

## [Unreleased]

---

## [V0.107.1] · 2026-10-20

`今日要闻分类聚焦（财经 32→60+ / 科技 33→50+ / 创投 23→35+ / 商业 22→30+）+ fetcher 弃入「其他」+ page_size 50 + service 二次 gate` — 4 commit hotfix

### Added

- ✨ **关键词字典焦点化扩充**（`src/app/repositories/news_classifier.py`）
  - **财经** 32 → 67：新增「行情」（牛市 / K线 / 黄金ETF / PE）、「主体」（比特币 / ETH / 离岸 / 外汇 / 储备）、「宏观」（衰退 / 通缩 / 缩表）、「人物」（鲍威尔 / 耶伦 / 巴菲特 / 芒格）、「机构」（贝莱德 / 桥水 / 高盛 / 中金 / 中信 / 瑞银 / 摩根士丹利）— 用户原话「主要聚焦于财经方面的新闻」重点扩充
  - **科技** 33 → 49：删「英伟达」duplicate（修旧版 L44 bug）+ 硬件公司（比亚迪 / 特斯拉 / SpaceX / 台积电 / 中芯国际 / 宁德时代 / 三星 / 英特尔 / AMD / 高通 / 联发科 / Meta / 亚马逊 / Oracle / IBM）+ 前沿（机器人 / 无人机 / 储能 / 自动驾驶 / 脑机接口 / 可穿戴）+ 节点（3nm / 5nm / 7nm / 5 纳米 / 7 纳米）
  - **创投** 23 → 36：行为（风投 / 退出 / 并购 / M&A / FA / 财顾 / 路演 / BP / 商业计划书）+ 身份（创始人 / 联创 / 合伙人 / GP / LP）+ 事件（增发 / 配股 / 可转债 / 债转股 / 借壳 / 回购 / 对赌）
  - **商业** 22 → 32：扩张（出海 / 跨境 / 国际化 / 海外）+ 渠道（电商 / 直播带货 / 抖音 / 微信 / 品牌）+ 经营（份额 / 用户 / 流量 / 增长 / 净利润 / 扭亏 / 亏损 / 增亏 / 渗透率）
  - 优先级保留 `财经 > 科技 > 创投 > 商业 > 其他` 不变

### Changed

- 🔧 **fetcher 弃入「其他」**（`src/app/repositories/readhub_fetcher.py` L130-146）
  - `_normalize()` 末尾加 `if category == "其他": return None` —— 不写入 DB，落 `logger.debug`
- 🔧 **page_size 20 → 50**（同上 L62）
  - readhub max 100，实测 50 P99 <2s，4h 周期足够覆盖
  - fetcher 文档 + User-Agent V0.102 → V0.107.1 同步
- 🔧 **service 二次 gate**（`src/app/services/news_feed.py` L96-126）
  - `refresh()` 在 fetcher 返回 records 后再 `tuple(...)` filter `category in (财经/科技/创投/商业)`
  - 全被弃入 → 软失败 `ok=False + error='no valid items after category filter'`，保留「保留末次」 UX（参考 V0.84 状态条合并模式）
  - 落入条目打印 `logger.info dropped N`

### Fixed

- 🐛 **`_TECH_KW` 重复「英伟达」bug**（V0.105 旧版 L44 末尾）—— 字典去重

### Discipline

- **测试覆盖**：3 测试文件 + 1 新增文件（test_news_classifier 10→30 / test_readhub_fetcher 16→18 / test_news_feed_service 新建 3 / test_news_feed API +2 / 仓储 test_news_feed 24 不变）；40 测试 PASSED（1 pre-existing failure `test_list_items_filter_days` 由 seed 日期漂移导致，与 V0.107.1 无关，不阻塞发版）
- **维护线覆盖率**：本次仅修改 backend + tests，UI / API schema 不变；`check_pwa_assets.py` sw.js VERSION bump 必跑门禁已通过
- **不在 5 类 list 中间移除「其他」常量**（CATEGORIES 5 类保持兼容；新写入 daily `other_count = 0`）

### Why hotfix 不开 docs 单条

V0.107.1 是 V0.107.0 release 后的数据质量 hotfix（关键词字典 + fetcher 弃入「其他」），无新功能模块；纳入 V0.107 综合 release notes 统一记录，并在 `docs/releases/v0.107.1.md` 留独立 summary。

---

---

## [V0.106.2] · 2026-10-19

`16 静态文件去掉 8888 硬编码（API_BASE 全改同源相对 URL）` — 1 commit hotfix

### Fixed

- 🐛 **/headlines 选日期新闻「加载失败 · Failed to fetch」** —— 16 个静态文件硬编码了 `location.port === "8888" ? "" : "http://127.0.0.1:8888"`，导致 V0.106.1 验证用的 8890 uvicorn 时 JS 全部指向 8888 → **CORS 拦截**（8890 origin fetch 8888 origin），fetch 直接 rejected

  - 表现 1：home 底部 5 条新闻列表为空（home.js fetch 失败被 Promise.allSettled 吞掉）
  - 表现 2：/headlines 选日期显示「⚠️ 加载失败 · Failed to fetch」
  - 表现 3：所有 9 个数据子页（central_bank / weights / trend / news / backtest / review / data-health / silver / favorites）的 API 请求都走错实例

### Changed

- 🔧 **API_BASE 同源统一**（整合 16 个文件的重复 pattern）

  | 文件 | 旧 | 新 |
  |---|---|---|
  | static/headlines.js | `port==="8888"?"":"http://127.0.0.1:8888"` | `""` |
  | static/silver.js | 同 | `""` |
  | static/freshness.js | 同 | `""` |
  | static/resonance-card.js | 同（×2）| `""` |
  | static/synthesis-card.js | 同 | `""` |
  | static/health-summary.js | `port==="8888"‖"8889"?"":"..."` | `""` |
  | static/news-score-widget.js | `ABS_BASE='http://127.0.0.1:8888'` | `""` + 删除 ABS_BASE 概念 |
  | static/favorites.js | 同 | `""` |
  | static/weights.html | 同 | `""` |
  | static/central_bank.html | 同（×2）| `""` |
  | static/trend.html | 同 | `""` |
  | static/news.html | `protocol检测?"":"..."` | `""` |
  | static/backtest.html | 同 | `""` |
  | static/data-health.html | `port==="8888"‖"8889"?"":"..."` | `""` |
  | static/review.html | `protocol检测?"":"..."` | `""` |

- 🗑️ **删除冗余的 ABS_BASE 概念**（news-score-widget.js 独有）
- 📝 **3 处错误提示文案**改用 `location.origin`（central_bank / trend / trades）—— 用户能看到自己实际访问的 origin，不再被强制看到 8888

### Discipline

- 📐 4 处版本同步：__version__ 0.106.1→0.106.2 / pyproject.toml 同 / sw.js v0.106.1→v0.106.2 / uv.lock 同步
- 🧪 4 门禁：pwa_assets ✓ / i18n_keys ✓（0 missing / 179 in-scope）/ static_js ✓ / routes ✓（18 路由 OK）
- 🐛 **Puppeteer 验证**：fix 后 /headlines 初始 2 day group + 选 2026-10-19 显示 36Kr 00:59 文章（fix 前是 empty-state warn）

### Why hotfix 不开 docs

V0.106.2 是 V0.106.1 release 当天的 CORS 拦截修复，非新功能。`docs/releases/` 暂不新增条目，纳入 V0.107 综合 release notes 统一记录。

---

## [V0.106.1] · 2026-10-19

`home 场景卡同步 topnav 8 scene（hotfix · 不发 docs）` — 1 commit

### Changed

- 🏠 **home.html 场景卡 5 → 7 张**（与顶 nav 8 scene 对齐：topnav 8 个 scene 去掉「home」自身）

  - 📢 新增 `scene-headlines` 今日要闻卡（顶 nav 顺序第 2 位）
  - 🩺 新增 `scene-health` 数据健康卡（顶 nav 顺序第 8 位）
  - 📐 重排顺序：今日要闻 → 决策 → 持仓 → 情报 → 配置 → 数据健康 → AI（AI 全宽）
  - 🧹 整合 3 张旧卡的 sub-items 与顶 nav subpages：
    - 决策：3 项 → 4 项（+研判复盘；今日评分→打分汇总）
    - 持仓：3 项 → 2 项（-复盘报告：复盘已归入决策 subpage）
    - 情报：4 项错位 → 4 项对齐（消息面评估 / 央行购金 / 白银追踪 / 我的收藏）
  - 📝 desc 文案同步：决策「趋势 · 打分 · 回测 · 复盘」、持仓「决策 · 流水」、情报「新闻 · 央行 · 白银 · 收藏」

### Discipline

- 📐 **改 static 立即 bump SW**（V0.100.1 教训）：`__version__` 0.106.0 → 0.106.1 + sw.js VERSION v0.106.0 → v0.106.1 + 4 处版本同步
- 🌐 3 语 i18n 同步：zh-CN / en-US / zh-TW 增 11 key + 改 6 key
- 🧪 4 门禁：pwa_assets ✓ / i18n_keys ✓（0 missing / 179 in-scope）/ static_js ✓ / routes ✓（18 路由 OK）

### Why hotfix 不开 docs

V0.106.1 是 V0.106.0 release 当天的 home 页面布局补全（顶 nav 8 scene → home 卡片同步），非新功能。`docs/releases/` 暂不新增条目，纳入 V0.107 综合 release notes 统一记录。

---

## [V0.106.0] · 2026-10-19

`今日要闻顶 nav 提级 + scheduler 6h→4h 加密` — 2 commit

### Added

- 📢 **「今日要闻」提级为顶 nav 第 2 位** —— 用户原话「当前今日要闻页面连接 提升到 导航栏 首页之后 决策之前」

  - 🖥️ `static/topnav.js` `SCENES` 数组 7 → 8 顶 scene
  - 🆕 新增 `key:"headlines"` 顶级场景：`/headlines` 入口、`ico:"📢"`、无 sub-tabs（独立页）
  - 📐 顶 nav 顺序：首页(🏠) → 今日要闻(📢) → 决策(📊) → 持仓(💼) → 情报(📰) → 配置(⚙️) → AI(🤖) → 数据健康(🩺)
  - 🗑️ 「情报」scene 子页 5 → 4（移除今日要闻）：消息面评估 / 央行购金 / 白银追踪 / 我的收藏
  - 📐 独立顶项 3 → 4（首页 / 今日要闻 / AI / 健康）
  - 📝 注释同步更新（V0.98 7-scene 描述 → V0.106 8-scene 描述）

### Changed

- ⏰ **今日要闻 scheduler 6h → 4h 加密** —— 用户原话「更新策略也没有实现，修改成每四小更新一次财经新闻」

  - 🔧 `src/app/services/scheduler.py` `NEWS_FEED_INTERVAL_HOURS` 6 → 4
  - 📐 触发时刻（UTC）：00/06/12/18 (4点/日) → 00/04/08/12/16/20 (6点/日)
  - 📐 触发时刻（BJT ≈）：08/14/20/02 → 08/12/16/20/00/04
  - ♻️ `next_news_feed_run_utc()` 改用 `tuple(range(0, 24, NEWS_FEED_INTERVAL_HOURS))` 自动算小时列表（日志 hours_label 同步动态生成）
  - ♻️ `news_feed_loop()` 日志格式从硬编码 `00/06/12/18` 改为 `hours_label` 动态（将来改间隔只需改 1 个常量）

### Discipline

- 📐 **4 处版本同步**（V0.100.1 教训）：`__version__` / `pyproject.toml` / `sw.js VERSION` 同步 bump `v0.106.0`；`uv.lock` 同步 lockfile
- 📐 **改 static 立即 bump SW**（V0.100.1）：C1 bump `v0.105.0 → v0.105.1`（topnav.js 改动），C2 release bump `v0.105.1 → v0.106.0`
- 🧪 8 个新 scheduler 单测（4h 节奏 6 触发点全覆盖 + 跨日 + 默认 now_utc）

---

## [V0.105.0] · 2026-10-19

---

## [V0.105.0] · 2026-10-19

`headlines 分类筛选（5 类 + 多 switch）` — 5 commit

### Added

- 🏷️ **headlines 类目筛选** —— 用户原话「主要聚焦页面财经内容」（"主要 聚焦页面财经内容"）

  - 🗄️ `news_feed_items` 表加 `category` 列（V0.105 n0o1p2q3r4，down_revision=m9g0a1b2c3 V0.102）；`String(16) NULL` + 单列索引（5 类 cardinality 仍走 B-tree）
  - 🤖 关键词分类器 `app/repositories/news_classifier.py`（rule-based 5 类：财经/科技/创投/商业/其他；优先级 财经 > 科技 > 创投 > 商业 > 其他；准确率 ~70-80% 是 rule-based 上限，V0.106+ 再升级 LLM）
  - 🛠️ `NewsFeedRepository`：`upsert_bulk` set_ 加 `category=stmt.excluded.category`（关键：防历史行永远 NULL）+ `list_items` 加 `category` filter（与 date/days/site_name/language **正交叠加**）+ 新增 `list_categories()`（distinct + 频次降序）+ `backfill_categories(batch_size=500)` 启动时一次性补齐 ~64378 行
  - 🌐 `readhub_fetcher._normalize()` 入库即调 `classify()` 填入 category；新条目不会留 NULL
  - ⏰ `main.py` lifespan `_backfill_news_categories()`（`spawn_background` 异步，6-10s 完成；启动过渡期少数 NULL 不阻塞）
  - 🔌 `GET /api/v1/news-feed/items` 新增 `category` query param（max_length=16）；新端点 `GET /api/v1/news-feed/categories`（DB distinct + 频次降序）
  - 🏷️ `NewsFeedItemOut` schema 加 `category: str | None` 字段（V0.78.0 NULL 纪律：未分类则 None）
  - 🖥️ `headlines.html` 工具栏新增 `<select id="categorySel">`（5 控件后，第 5 位）
  - 🖥️ `headlines.js` `currentCategory` state + `renderCategoryOptions()`（合并「DB 频次降序 + 固定 5 类兜底」并去重，5 类一定可选；i18n key `headlines.cat_{finance|tech|vc|business|other}`）+ bindToolbar change handler
  - 🌐 i18n +6 keys × 3 语 = 18 条翻译：`headlines.filter_category` / `cat_finance` / `cat_tech` / `cat_vc` / `cat_business` / `cat_other`
  - 🧪 分类器 9 例 + 仓储 7 例（filter / 联 site / 联 date / 联 days / distinct / backfill / 幂等 / upsert 更新）+ API 6 例（filter / 422 / 联 date / 联 days / /categories / 字段回归）+ puppeteer 8 状态验收（`scripts/_verify_category_filter.mjs`）

### Discipline

- 📐 **4 处版本同步**（V0.100.1 教训）：`__version__` / `pyproject.toml` / `sw.js VERSION` 同步 bump `v0.105.0`；`uv.lock` 同步 lockfile
- 📐 **改 static 立即 bump SW**（V0.100.1）：C4 bump `v0.104.0 → v0.104.1`（中间版本），C5 release bump `v0.104.1 → v0.105.0`（最终版本）
- 📐 **5 commit 顺序**：feat(repo) → feat(api) → test → feat(static) → chore(release)（沿用 V0.100/V0.103/V0.104 模式）
- 📐 **正交叠加**：`category` 与 V0.104 `date` / V0.102 `days` / V0.102 `site_name` / V0.102 `language` 完全正交，切换 category 不清其他 state
- 📐 **卡片不显类目 badge**（设计取舍）：让分类纯粹是筛选轴，不污染卡片视觉；用户没要求就不加

---

## [V0.104.0] · 2026-10-19

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
- 🔧 **V0.103.1 hotfix · 5 个情报子页 subnav 显示不一致** —— 用户报告「情报下面的五个超链接展示形式和其他页面不一致」

  - 根因：5 个 intel 子页（消息面评估 / 央行购金 / 白银追踪 / 今日要闻 / 我的收藏）渲染同一段 `<nav class="subnav">`（topnav.js 统一生成），但容器 + 样式不一致：news/central_bank/silver 3 老页有内联 `.subnav` CSS + mount INSIDE `.wrap`（900/1040/960px），headlines/favorites 2 新页无内联 CSS + mount OUTSIDE `.wrap`（裸链接铺满 body 宽）
  - 修复：3 commit
    - C1 `b55b035 refactor(theme)`：`.subnav` 18 行从 news.html:112-131 抽到 `static/theme.css`，5 子页共用
    - C2 `6379f42 refactor(static)`：news/central_bank/silver 3 老页 `<div id="topnav-mount">` + `<div id="subnav-mount">` 一起从 `<main>` 内的 `<div class="wrap">` 移到 `<main>` 之前（OUTSIDE 任何宽度限制，与 headlines/favorites 对齐），同时删 3 处 byte-identical 内联 CSS 块
    - C3 验证：puppeteer 5 子页截图比对（`scripts/_verify_subnav_5sub.mjs`），5 个 subnav 统一为 1352px 全宽 + `rgb(255,255,255)` bg + `10px` radius + 5 tabs + 当前页 active 高亮
  - 4 处版本同步 bump 到 `v0.103.1`（`__version__` / `pyproject.toml` / `sw.js VERSION` / `CHANGELOG.md`）—— 改 static HTML 必须 bump SW VERSION 是 V0.100.1 沉淀教训

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

---

## [V0.104.0] · 2026-10-19

`headlines 按日期分页（单日模式 + 日期导航）` — 4 commit / 1 hotfix

### Added

- 📅 **headlines 单日模式 + 日期导航** —— 用户原话「我们在 headlines 添加按照新闻日期的分页功能」
  - 🔌 `GET /api/v1/news-feed/items` 新增 2 个 query param：`date`（YYYY-MM-DD）+ `tz_offset_minutes`（带符号，BJT = +480）；与现有 `days` 互斥
  - 🏷️ `NewsFeedListOut` 新增 3 字段：`current_date`（回显的 date）/ `has_older`（前一天是否有新闻）/ `has_newer`（后一天是否有新闻）
  - 🗄️ `NewsFeedRepository.list_items` 新增 `date` + `tz_offset_minutes` 参数；新增 `has_items_outside_day()` 2 个 EXISTS 查询（无 COUNT，走索引）
  - 🖥️ `headlines.html` 工具栏新增 `#dateNav`：◀ / `<input type="date">` / ▶ / 回到今日（4 控件 + 13 行 CSS）
  - 🖥️ `headlines.js` `enterDateMode()` + `refreshDateNav()`：currentDate state + 单日/范围模式互斥 + 翻页按钮 disabled
  - 🌐 i18n +3 keys × 3 语 = 9 条翻译：`headlines.btn_today` / `.btn_prev_day_title` / `.btn_next_day_title`
  - 🧪 仓储 4 例 + API 6 例 + puppeteer 4 状态验收（`scripts/_verify_date_nav.mjs`）

### Fixed

- 🐛 `refreshDateNav()` 同步 `btnToday.hidden`（修复 loadAll 失败时回到今日按钮状态不重置的 UX bug）— **C4 修**

### Discipline

- `total` 字段语义保留 `len(items)`，不升级为「匹配总数」；与现有 6 个测试一致
- 现有 `days` 模式 SQL 与 V0.103 byte-identical（`date=None` 时不进入 date 分支），0 字段破坏
- 时区偏移符号约定：JS `getTimezoneOffset()` 返回 WEST，反转后东八区 = +480；2 个测试用例固化
- 改 static HTML/JS → bump SW VERSION v0.103.2 → v0.104.0（按 V0.100.1 沉淀教训）

[详情](docs/releases/v0.104.0.md)

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
