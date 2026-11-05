# M4 · 报告存档 · 移动端 · 新闻容灾（V0.111 – V0.115）

> **发版区间**：V0.111.0 – V0.115.0（6 个版本）｜ **状态**：归档（历史里程碑）
> **本文件定位**：把该区间的 6 份 release notes 合并成一条**可读的演进脉络**。
> **逐版原始全文**在 git 历史里（tag 与原文件名同名）：`git show v0.115.0:docs/releases/v0.115.0.md`

## 〇 一页结论

1. **产品面第一次有了「我的文档」入口**。V0.111.0 落地报告存档：上传 HTML、填元数据、
   搜索筛选、新标签页查看。关键设计是**新标签页打开 + 响应级 CSP** —— 靠 `sandbox`
   （不带 `allow-same-origin`）把上传文档关进 opaque origin，`connect-src 'none'` 封死
   全部接口调用，**渲染保真度分毫不动**。这在认证关闭的生产环境里尤其重要：一份裸发的
   同源 HTML 里的 JS 本来能直接调全部 `/api/v1/*` 写端点。

2. **移动端第一次被「量」过**。V0.113.0 在 390px 真实视口下逐页实测，量出三类
   **全都不报错**的缺陷：横向溢出（`/scoring` **221px**、`/report` 175px、`/silver`
   123px、`/central_bank` 71px）、聚焦被 sticky 顶栏遮挡 **17 处**、触摸目标 < 44px
   （`/headlines` 单页 **115 个**）。修完 18/18 页三项归零，并把三个基元钉进门禁。

3. **新闻源从单点变成链式 failover**。V0.114.0 把 readhub 单源改成 wallstcn ★ → jin10
   → eastmoney → readhub 四源链式，首个足量即止；同一版还挖出「收藏从头到尾**没有任何
   反馈**」的**三层**缺陷，以及金十 20 位 id 撑爆 int64 的类型事故。

4. **两个 hotfix 都源于「先被撞见的那个现象」**。V0.114.1 修全站 favicon 404（21 页
   全不声明 `rel="icon"`）；V0.114.2 修「点上传并存档没有文件对话框」—— 后者初判是
   Firefox 特有问题，实跑 Chrome 后被推翻：根因是**通用 bug**。

5. **数据源是实测出来的，不是推断的**。V0.115.0 为首页贵金属区从零建黄金库存线，两个
   候选源被实测否掉（一个**没有任何库存字段**，一个最新统计停在 2025-01-15、陈旧
   21 个月且口径不对），宁可不做也不「凑一个看起来像库存的数」。

6. **这一阶段的共同敌人是「静默失效」**。搜索转义错误（零命中）、44px 规则被折成后代
   组合器、收藏点了没反应、两个 hero chip 一直显示 `金价 --` / `时效 --`、1y 变化率恒为
   `None`、`external_id` 被 `parseInt` 静默舍入 —— 全都不抛异常，全都要靠实跑 + 反向
   验证才抓得到。**这一阶段真正沉淀下来的，是「撤销改动必须变红」这条验收标准。**

---

## 一、版本一览

| 版本 | 主题 | 关键交付 |
|---|---|---|
| V0.111.0 | 报告存档（HTML 上传 + 元数据登记表 + 新标签页查看） | 新页 `static/report-archive.html` / `.js` + `reports` 真表 + 8 个 `/reports` 端点 + 响应级 CSP sandbox + 37 条测试 |
| V0.113.0 | 移动端可用性（表格滚动容器 + 44px 触摸目标 + 聚焦不被顶栏遮挡） | `.table-scroll` 基元覆盖 11 张表 + 44px 触摸目标规则 + `scroll-padding-top` 实测高度 + `_verify_mobile.mjs` 33 断言 |
| V0.114.0 | 新闻多源容灾 | 4 源链式 failover + `external_id` 改 `String(32)` + 收藏链路打通 `source` + `toast.js` 补 `show()` 派发器 |
| V0.114.1 | 修全站 favicon 404 | 21 页补 `rel="icon"` + 根作用域 `/favicon.ico` 路由 + `check_pwa_assets` 从 3 项扩到 4 项 |
| V0.114.2 | 修「点上传并存档没有文件对话框」 | file input 改透明覆盖层 + `:focus-within` 焦点环 + `_verify_upload_dialog.mjs` 10 条断言 |
| V0.115.0 | 首页「贵金属走势」区（金价 / 库存 / 央行购金） | `gold_inventory_daily` 表 + `GET /api/v1/market/gold/inventory` + 每日 08:10 BJT 刷新 + 首页 3 卡 + `home.metals_*` 24 键 × 3 语 |

> 版本跨度 V0.111.0 → V0.115.0 共 6 个版本；区间内另有 V0.111.1（仅 4 处版本同步 +
> CHANGELOG，**无 release notes**），故不在本文逐版记录内。

---

## 二、逐版本记录

### V0.111.0 · 报告存档（HTML 上传 + 元数据登记表 + 新标签页查看）

**背景/问题**：应用里一直没有「我自己的文档」入口（`/report` 是**复盘报告**，由持仓/交易数据自动生成，另一回事）。用户原话：「我们首页添加一个报告上传的板块，用户可以上传 html 格式的报告，并提供客户查看显示，然后建立存单方便用户查看。」「存单」经确认为**元数据登记表**（可搜索筛选的字段集合），不是书签。4 个产品决策：存单=元数据登记表；报告一律新标签页打开；「提供客户查看显示」的边界=**就在应用里看**（不做免登录分享链接、不做导出给他人）；导航=独立顶级场景放在「情报」之后 ⇒ 顶 nav 8→9 项、首页卡 7→8 张。

**修法**：新建真表 `reports`（**不**复用 `app_settings` KV —— 它无 `user_id`、`key` 是 `String(64)` 主键、整值替换，做不了列表），落盘 `data/reports/`（在 systemd unit 的 `ReadWritePaths` 白名单内，`ProtectHome=read-only`）；迁移 `p2q3r4s5t6_reports.py`，`down_revision = "n1o2p3q4r5"`，抄 `_table_exists()` 幂等守卫 —— 明确**不跑 `alembic autogenerate`**（`models/__init__.py` 漏了 `news_feed` 和 `user_news_favorite`）。端点 8 个（`prefix="/reports"`），分层照抄 `user_news_favorite` 五件套；新页 `static/report-archive.html` / `.js` 照抄 `static/favorites.html` 结构。**安全**：生产 `.env.prod` **没有 `AUTH_ENABLED`** ⇒ `user_id` 恒为 `LEGACY_USER_ID=1` ⇒ 裸发同源 HTML 里的 JS 能直接调全部 `/api/v1/*` 写端点 ⇒ 响应级 CSP：`sandbox`（**不带** `allow-same-origin`）关进 opaque origin，`connect-src 'none'` 等 5 条封死外联，**刻意不给 `default-src`**（否则连带禁掉外部 CSS / 字体 / 图片，把报告渲染打残）。3 条硬规矩：上传物**绝不落 `static/`**；落盘用 `uuid4().hex`，**原始文件名只当展示元数据**；nginx 补 `client_max_body_size`（默认 1MB，超限直接 413，应用连日志都看不到）。

**验证**：37 条新测试 `tests/test_api/test_reports.py`（上传 4 道校验正反向、列表 5 维筛选、`/content` CSP 头逐条断言、跨用户 404）；两个必须的 fixture（`_seed_legacy` 避免每个写端点都 401、`_tmp_reports_dir` 避免写进真实 `data/reports/`）；puppeteer `scripts/_verify_report_archive.mjs` 在报告页里断言 `localStorage` 访问抛 `SecurityError`（opaque origin 的直接证据 —— 光看 CSP 响应头不算验证）；门禁 7 道全绿。

**教训**：顺手修的两个既有缺陷都是「静默」类。① `scripts/check_routes.py` 门禁会以 **134（SIGABRT）** 假失败收场 —— `_start_in_process_server` 成功路径从不置 `server.should_exit`，daemon uvicorn 线程在解释器收尾时撞 stdout 锁。② `_escape_like` 把 `%` 转义成 `\%` 却**每个 `.like()` 都没传 `escape=`** ⇒ 搜 `100%` 一条都搜不到 —— **少传 `escape=` 比不转义更糟**（不转义是全命中、结果脏；错误转义是零命中、用户以为搜索坏了）。此外别名必须**同 commit 同步两处**（`test_main_app.py:114` 硬断言 `len(ROOT_ALIASES) == 17`，`check_routes.py` 有镜像的 `EXPECTED_ALIAS_PATHS`）。

---

### V0.113.0 · 移动端可用性（表格滚动容器 + 44px 触摸目标 + 聚焦不被顶栏遮挡）

**背景/问题**：本项目第一次**在 390px 真实视口下逐页实测**。此前所有「响应式」都是桌面浏览器缩窄窗口看出来的，从没量过触控手指够不够得着、表格滑不滑得动、Tab 会不会把焦点送到顶栏底下。量完是三类缺陷，而且**全都不报错**：横向溢出 4 页表格（`/scoring` **221px**、`/report` 175px、`/silver` 123px、`/central_bank` 71px）+ 6 页因引导提示框硬编码宽度多出 11px；聚焦被 sticky 顶栏遮挡 **17 处**；触摸目标 < 44px（`/headlines` 单页 **115 个**，其余页零星 1–30 个）。这三类都不会抛异常、不会被 `check_static_js` 抓到。

**修法**：① `.table-scroll` 基元（`overflow-x: auto` + `-webkit-overflow-scrolling: touch` + `overscroll-behavior-x: contain` + `max-width: 100%`），覆盖 11 张表（`scoring.js` 3 / `report.js` 5 / `silver.js` 1 / `silver.html` 1 / `central_bank.html` 1），每处带无障碍三件套 `tabindex="0"` + `role="region"` + `aria-label`（**全是属性，没有对应的 CSS**），`aria-label` 复用表上方小节标题已有的 i18n key，本轮**新增 0 个 i18n key**；落地前那版带 `min-width: max-content` 的草案被删掉了 —— 验证时发现**含长文本的表格在桌面端也被拖出滚动条**。② 44px 触摸目标，触发条件 `@media (max-width: 640px), (pointer: coarse)` 取「或」。③ 聚焦遮挡用 `scroll-padding-top`，高度**实测**（`getBoundingClientRect().height`）而非硬编码，挂在 `resize` + `ResizeObserver` + `document.fonts.ready` + `i18n:change` 上。

**验证**：新增 `scripts/_verify_mobile.mjs`（33 断言，18 页 × 390px 实跑）→ **33 passed / 0 failed**；`check_cluster_render.mjs` **+28 条断言**（**461 passed / 0 failed**）；反向验证 9 个注入缺陷 9 条各自变红（选择器折行 / 漏 `:not([type=color])` / 整条 44px 规则消失 / `table-scroll` 被补上 `min-width` / `responsive.css` 退回 40px / 面板去掉 `visibility` / 去掉 `ResizeObserver` / `report.js` 少包一张 / 某处漏 `tabindex`）；回归 `_verify_cmd_palette` 30 · `_verify_nav_8` 26 · `_verify_report_archive` 43 全绿。门禁 7 道全绿；`check_routes` 本轮**故意没跑** —— 它会拉起进程内 app，其 lifespan 会执行 `alembic upgrade`，而本机指向的是生产库。

**教训**：本轮最大的坑是**换行 = 后代组合器**。规则写完后输入框仍停在 27–35px，`min-height: 44px` 就在文件里、`el.matches(selector) === true`、`matchMedia(...).matches === true` —— 全绿，**就是没生效**：CSSOM dump 显示解析后的 `selectorText` 里 `[type="radio"]` 后面多了一个空格，换行 + 缩进被解析成「input 里的 input」，永不命中。**CSS 不报错，DevTools 里也不显形。** 所以门禁里那条核心断言查的不是「文件里有没有 `min-height: 44px`」（那样查不出死规则），而是「选择器里有没有非逗号处的换行」。另有 3 个顺手修的既存缺陷：两页漏引 i18n 字典文件（`/report` 21 处 + `/reset-password` 11 处 ⇒ 整页渲染成 key 字面量，根因是 `i18n.js:46` 的 `syncLoadDefault()` 只读 `window.PM_I18N_ZH_CN`）、`/report` 每访问一次吃一个 favicon 404（它单独引了 `/static/favicon.svg`，而 `static/` 下从来没有这个文件）、引导提示框硬编码 320px 宽度（`help.css` 窄屏下改成 `width: calc(100vw - 24px)` ⇒ 390px 视口下 = 366px，右侧伸出视口）。另一条可复用经验：**注释里的「代码样文字」不能当代码** —— 第一版断言写的是「`.pm-cmd` 规则里有 `visibility: hidden`」，反向验证时把真正的声明删掉门禁依然全绿，因为规则上方那段 ⚠ 注释里就写着 `visibility:hidden` 字样，正则把注释当成了声明 ⇒ 改成**只扫字符串字面量**。

---

### V0.114.0 · 新闻多源容灾

**背景/问题**：用户给出三个新闻源，要求「互为冗余，单点挂了还有输出」。实测确认三源全通，但现状是**只有 readhub 一个源**，而这轮实测中 readhub **直接超时了一次** —— 单点无冗余不是理论风险，是已经发生过的事。

**修法**：4 源链式 failover，顺序 wallstcn ★ → jin10 → eastmoney → readhub（readhub 降为末位兜底），**首个足量即止**（`len(items) >= MIN_ITEMS(=10)` 即返回，不做四源合并），`url` 改可空、无链接时卡片不可点（不合成假链接）。新 `src/app/repositories/news_sources_fetcher.py`，3 个源各一个 `_normalize_*`，输出与 `readhub_fetcher._normalize` **完全一致的 dict 形状**（含 `source`），共用 `classify()` + 弃入「其他」+ 共享 `SITE_BLOCKLIST`；**`readhub_fetcher` 一行不动**（28 个现有测试依赖它），只作为注册表末位参与。多源后 `external_id` 不再全局唯一，`headlines.js` / `home.js` / `favorites.js` 三处改成按 `data-source` 定位与提交。**实测数据（本机，非文档推断）**：华尔街见闻 `api-one.wallstcn.com` 200 / 0.28s / raw 30 / classify 后 20（科技 11 财经 9）/ title **22/30 为空**（快讯只有 `content_text`）/ url ✅；金十 `flash-api.jin10.com` 200 / 0.39s / 21 / 20（科技 14 财经 6，0 其他）/ title 0/21 / url ❌；东财 `np-listapi.eastmoney.com` 200 / 0.33s / 30 / 23（科技 10 财经 12 创投 1）/ title 30/30 / url ❌；readhub 200 / 20 / title 有 / url ✅。华尔街见闻与 readhub 标题**仅 2 条重合** ⇒ readhub 是真正的第 4 个独立源，不是冗余重复。

**验证**：端到端 failover 真重启 uvicorn，5 种场景 —— 基线 `source=wallstcn upserted=21`；A wallstcn 不可达 → jin10 16；B wallstcn + jin10 不可达 → eastmoney 16；C 三个新源全挂 → readhub 14；D 四源全挂 → HTTP **200**、`ok=False`、error 列出全部 4 源，`/items` 仍供末次数据（返回 200 是**刻意**的，V0.84：绝不 500，绝不在用户可见路径上显示红框）。puppeteer 1352×900 实跑 **23 条断言全绿**（4 源卡片都渲染 / 无链接条目标题**不是 `<a>`**，实测 68 张有 `<a>`、32 张是 `span.no-url` / fav 按钮带 `data-source` 且 `external_id` **全程字符串** / 点收藏后**真的弹出 toast** / 3 语无 i18n key 字面量泄漏）。门禁全绿，`check_cluster_render.mjs` **461 passed / 0 failed**；pytest 相关 8 个文件 **195 passed / 1 failed**。

**教训**：金十 `id` 是 **20 位数字串**（`20261022052115590800`），超出 JS `Number.MAX_SAFE_INTEGER` **2249 倍**，也超出 SQLite INTEGER（int64）⇒ 列类型必须 `String(32)`；计划里原本写 BigInteger，**实测推翻**（`OverflowError: Python int too large to convert to SQLite INTEGER`），改 `String(32)` 后又发现直接构造 ORM 传 int 仍溢出（绑定发生在 Python 侧，早于 SQLite 的 affinity），因此加 `models/base.py::SourceId` TypeDecorator，`process_bind_param` **永远**以文本绑定；前端先前用 `parseInt` 会把 `20261022055128917800` 静默舍入到 `…7000`，收藏落到不存在的行。另一条：**收藏从头到尾没有任何反馈**是三层叠加 —— ① `toast.js` 只导出 `info/success/warn/err`，**从未导出 `show`**，而全站 **14 处**在调 `PM_Toast.show(...)`（自 V0.98 C3 起）；② `headlines.js` / `home.js` 的 guard 只查 `window.PM_Toast`（对象在）⇒ 抛 TypeError，`favorites.js` / `report-archive.js` guard 查到 `.show` 为 falsy ⇒ 静默不弹；③ `headlines.js` **模块作用域没有 `t()`**，却裸调 `t("favorites.toast_archived", ...)` ⇒ `ReferenceError`，且抛在 **catch 块内**无人接管。三层的用户可见后果完全一样：点了收藏，POST 成功了，屏幕毫无反应。另记：① 第一版 failover 验证是**无效的** —— `sed` 改文件不影响已在跑的 uvicorn，5 个场景全返回 `wallstcn`；改成每场景重启服务才拿到真结果。② 本轮先把 favicon 404 豁免掉（理由「与多源无关、纯装饰」），后单开一轮修复 —— **豁免清单会自我腐化**。

---

### V0.114.1 · 修全站 favicon 404

**背景/问题**：V0.114.0 的 puppeteer 实跑里，`/favicon.ico` 的 404 一直躺在「豁免清单」里。当时的判断是「全站性既存项、纯装饰、不在本轮范围」，于是豁免掉了。但豁免存在过本身就是它坏了的证据 —— 一旦豁免留在脚本里，下次真出问题时它会自动被一起豁免掉。根因：`StaticFiles` 只挂在 `/static/` 下 ⇒ `/favicon.ico` 无路由；21 个页面**全部**没有 `<link rel="icon">` ⇒ 浏览器只能去根路径找；20 个页面引了 `rel="manifest"`，但 **manifest 的 icons 不做标签页 favicon**（那是 PWA 安装图标）⇒ 引了 manifest 也照样 404。

**修法**：① 21 个页面补 `<link rel="icon" href="/static/icon-192.png" type="image/png">`，统一插在 `<link rel="manifest" href="/static/manifest.json">` 之后（20 页），`static/offline.html` 无 manifest 行（SW 离线兜底页刻意保持最小 head），在 `<meta name="theme-color">` 后单列一行并注明原因；`type="image/png"` **如实写** —— 媒体类型要与实际字节一致，撒谎会让部分浏览器拒绝解析。② `src/app/main.py` 新增根作用域 `/favicon.ico` 路由，理由与既有的 `/sw.js` 完全相同；兜的是仍会打这个路径的情况（旧书签、收藏夹、PWA 安装前的首屏，以及不解析 link 标签的客户端如 curl / 抓取器）。③ `scripts/check_pwa_assets.py` 从 3 项检查扩到 4 项（每页必须有 `rel="icon"`、href 必须指向真实文件、`.png` 必须带 `type="image/png"`）。④ `check_routes.py` 登记 `/favicon.ico` → 200（路由数 19 → 20）。⑤ `scripts/_verify_multi_source.mjs` **删掉豁免**并把 `page.on("response")` 里的 4xx 也计入断言，新增 5 条 favicon 断言。

**验证**：puppeteer 23 → **28 passed / 0 failed，零豁免**（此前 2 条被豁免）；`curl /favicon.ico` → `HTTP 200`、`content-type: image/png`、`content-length: 413`；21/21 页有 `rel="icon"`；`check_pwa_assets` 新增项**三条反向测试各自变红**（删 `rel=icon` → `缺少 <link rel="icon">`；href 指向 `icon-404.png` → `指向 /static/icon-404.png，但该文件不存在`；去掉 `type` → `指向 .png 却没写 type="image/png"`）；4xx 检测机制本身也反向验过（请求拦截器人为造一个 404，断言如实变红）；`check_routes` 19 → **20 条路由全部通过**；`tests/test_dependencies/test_main_app.py` **37 passed**；`check_static_js` · `check_i18n_keys`（0 missing / 240）· `check_links`（65 份 / 273 链接）· `check_docs_claims`（343）· `check_pwa_assets` 全绿。

**教训**：**豁免清单会自我腐化。** 一个「已知无害所以豁免」的 404，一旦留在验证脚本里，下一次真的出现同类 4xx 时它会跟着一起被跳过 —— 门禁从此对这一类问题失明，而且没人会注意到。豁免要么**限时修掉**，要么写进注释说明**为什么**无害、以及**什么条件下**必须重新启用；本轮之前那条只有一句「与本轮无关」，没有失效条件，所以它实际是在永久放行。另有一条**诚实记录反向验证结果**的做法值得保留：试过「删掉某页的 rel=icon，看新门禁会不会红」—— **会红**（门禁有效）；但试过「删掉某页的 rel=icon，看浏览器还会不会 404」—— **不会**，因为根路由兜住了。② 是真正止血的那层，① 是声明式加固，两条都留着是有意的分层，不是冗余。

---

### V0.114.2 · 修「点上传并存档没有文件对话框」

**背景/问题**：用户报「点击报告上传，浏览器中没有文件上传的对话框」，用的是 Firefox。初判是 Firefox 特有问题，**实跑 Chrome 后被推翻**：`点 .drop 后 filechooser 触发: 否`、`fileInput 计算样式: display=none offsetParent=null`。根因是**通用 bug**，Firefox 只是先被撞见的那个 —— 三处叠起来：① `report-archive.html:151` 的 `.upload-card .drop input[type="file"] { display: none; }` ⇒ 用户点不到它；② `report-archive.js:426` **只有** dragenter/dragover/dragleave/drop 监听器，**没有 click** ⇒ 提示文案承诺的「点击选择」没有任何实现；③ 于是**唯一可用的路径是把文件拖进来**，而提示文案完全没提这点。所以这不是「某个浏览器拦了对话框」，而是**根本没有对话框可弹**。

**修法**：把 `display: none` 换成铺满 `.drop` 的**透明覆盖层**（`position: absolute; inset: 0; width/height: 100%; opacity: 0; cursor: pointer; z-index: 2`），并给 `.drop:focus-within` 加 `outline: 2px solid var(--accent)` 焦点环。真实点击落在**原生 file input** 上 ⇒ 浏览器自己的默认行为就是弹对话框，**没有 JS 参与**，也就没有「用户手势」「是否在事件回调里」这类浏览器差异。拖拽不受影响 —— drag 事件从覆盖层**冒泡**到 `.drop`，原有监听器照旧命中。

**验证**：新增 `scripts/_verify_upload_dialog.mjs`，**10 条断言** → 修复后 **10 passed / 0 failed**；反向验证把 CSS 退回 `display: none` 后 **6 条变红**，含决定性的那条 `[FAIL] drop 区中心命中的是 fileInput :: {"tag":"SPAN"}` 与 `[FAIL] fileInput 有实际尺寸（能接到点击） :: 0×0`。门禁全绿，`check_cluster_render.mjs` **461 passed / 0 failed**。

**教训**：判据选错了 —— 第一版用 `page.on("filechooser")` 当「对话框真的弹了」的判据，跑出来是红的；但基线测试证明**这个 headless Chrome 连裸 `<input type="file">` 的真实点击都不发 `filechooser`**（`A. JS 调 input.click() → 未触发` / `B. 真实点击 input → 未触发`）。那条断言测的是 puppeteer 的能力，不是被测代码 —— **比没有断言更坏**（假绿）。换成真正的判据：**`document.elementFromPoint(drop 区中心)` 是不是那个 fileInput** —— 浏览器对**已渲染**的 file input 的默认行为就是弹对话框，落点对了对话框就会弹，路径上没有 JS；修复前这里命中的是无处理器的 `<SPAN>`。另一条：为什么**不**用「`display:none` + JS 调 `input.click()`」—— Chrome **放行**、Firefox **拒绝**（元素未渲染 unrendered 时不允许唤起文件选择器）；不加注释的话这条路会在 Chrome 上测得「通过」，上线后只在 Firefox 静默失效。同理用 `opacity: 0` 而不是 `visibility: hidden`：后者在部分浏览器里会让控件**不可聚焦**，键盘用户彻底够不着。

**⚠ 遗留**：**未在 Firefox 实跑验证** —— `npx puppeteer browsers install firefox` 因网络受限下不来；修复走的是「点击原生 file input」，这是各浏览器的默认行为，理论上不存在差异，但仍请在 Firefox 里确认一次再收工。**明确不做**：❌ 不改 `accept="text/html"`；❌ 不加 `<label for="fileInput">` 方案（比现在的覆盖层多一层间接，且 label 的点击转发在 `display:none` 的 input 上各浏览器行为又不一致）；❌ 不动拖拽上传的任何逻辑（实测未受影响）。

---

### V0.115.0 · 首页「贵金属走势」区（金价 / 库存 / 央行购金）

**背景/问题**：用户：「我们在主页页面内容缺少贵金属走势的页面，包括 金价变化、黄金库存变化、央行购金变化，卡片放在今日要闻前面。」摸底结果是三条线里两条现成、一条要从零建。金价变化 ✅ 端点齐全（`/market/gold` XAU 4094.5 -0.26%、`/gold/etf-quote`、`/gold/gram-quote`、`/gold/trend?days=60&target=ny`）；央行购金变化 ✅ `central_bank_purchases` 146 行 / 2014Q1–2026Q2 / 25 国，`WGC_AGGR` 全球合计行**每季都有**，正好直接当 sparkline；黄金库存变化 ❌ **完全不存在** —— 无模型 / 无 fetcher / 无表 / 无端点。

**修法**：新建 `src/app/models/gold_inventory.py` → `GoldInventoryDaily` / 表 `gold_inventory_daily`（`inv_date` Date unique、`tonnes` Float、`ounces` Float|None、`source` String(32)），迁移 `s1t2u3v4w5x`，`down_revision = "q3r4s5t6u7"`，**必须带 `_table_exists()` 幂等守卫**（`main._migrate_db()` 在 alembic 失败时会回退 `Base.metadata.create_all`，两条路径都跑过时第二次启动会炸）。`repositories/gold_inventory_data.py` 的 `fetch_comex_inventory()` 走**子进程隔离**（照抄 `market_providers._sina_etf_via_subprocess` —— akshare 内嵌 V8（py_mini_racer）崩起来能把整个 uvicorn 带走），进程内 TTL 24h，**失败不回退 mock**。`services/gold_inventory.py` 按**日历日**回看算 1w/1m/3m/1y 变化率 —— 不是按行索引，库存是**交易日频**，索引回看会错位。端点 `GET /api/v1/market/gold/inventory?days=90` + 每日 **08:10 BJT** 自动刷新（与 07:00 快照、4h 新闻错开），env `GOLD_INVENTORY_AUTO_REFRESH` 开关；**bootstrap：表空或最新行超 24h 才抓**，避免每次重启都全量回填。源选定 `ak.futures_comex_inventory`：**1234 行**、2021-10-25→2026-10-20、最新 **727.96 吨**、近 1 年 **-41.65%**。静态侧插在 `.home-scenes`（8 张板块卡）与 `.home-bottom`（今日要闻）之间的独立整行 section ⇒ `.home-scene` 卡数**仍是 8**，顶 nav `SCENES` 不动，既有门禁断言零影响；`home.js` 的 `Promise.allSettled` 5 项 → 9 项，新增 3 个渲染块 + `drawSpark` 迷你折线，三语新增 24 个 `home.metals_*` 键。

**教训**：两个真 bug 都是「静默为空」型。① **1y 变化率恒为 `None`** —— `snapshot()` 用 `date.today() - 365d` 当查询起点，但**最新观测日（2026-10-20）比今天（2026-10-22）落后 2 天**，「一年前」那一点就落在查询窗口外了 ⇒ 1m / 3m 看着正常、**只有 1y 静默为空**，不细看根本发现不了。修法：回看起点锚在**最新观测日**而不是今天，已补回归测试。② `IntegrityError: NOT NULL constraint failed: gold_inventory_daily.source` —— SQLAlchemy Core 的 `insert()` **绕过 ORM 的 Python 侧 `default`**，只认 `server_default`；迁移里写了 `server_default="COMEX"` 而模型没写 ⇒ **schema 漂移**。两处都补齐（模型加 `server_default`，repo 里再兜一层 `"source": r.source or "COMEX"`）。**顺带修掉的两个既有静默失效**：`home.js` 读的两个字段**后端根本不返回** —— 金价 chip 读 `gold.value.price` 而后端返回 `price_usd` ⇒ 一直显示 `金价 --`；时效 chip 读 `fresh.value.overall_status` 而后端只有 `degraded: bool` ⇒ 一直显示 `时效 --`。

**验证**：**34 条 puppeteer 断言全绿**（`scripts/_verify_home_metals.mjs`，视口 1352×900）；反向验证 4 处 —— 把 section 挪到今日要闻之后 → 顺序断言红；`drawSpark` 打桩 → 3 条走势线断言红；把 hero 字段名改回旧错名 → 复现 `金价 --`；zh-TW 库存卡标题退回简体 → 3 语断言红。端到端：迁移应用 → 回填 1234 行 → **重跑仍 1234 行（幂等）**；端点 4 个基线全部有值。门禁增项：`check_i18n_keys.py` 的 `V083_KEY_PREFIXES` 新增 `"home."` —— in-scope 从 240 → **307**，**0 missing**（整个 `home.*` namespace 3 语零缺口；此前首页文案完全不在严格清单里，漏同步只会静默回落）。

**明确不做**：❌ 不给顶 nav 加「贵金属」场景（会让 `SCENES` 8→9，连带 4 处硬编码断言）；❌ 不用 ETF 份额冒充「库存」；❌ 库存取数失败不 mock（**假数据比空卡更坏**）；❌ 不顺手修 README:50「52 季度 + 23 国家」（库内实为 50 + 25）—— 另开。数据源是**实测出来的，不是推断的**（akshare 1.19.1），被否掉的两个库存候选是：`spot_quotations_sge` 只有 `品种/时间/现价/更新时间`，**没有任何库存字段**；`fund_etf_scale_sse` 是单截面，最新统计日期停在 **2025-01-15（陈旧 21 个月）**，且 ETF 份额本就**不是库存口径** ⇒ 二者都不用「凑一个看起来像库存的数」来糊（V0.77.1：假数据比空卡更坏）。

---

## 三、这一阶段的通用教训

1. **静默失效是本阶段的头号敌人，它只在实跑与反向验证面前现形。**
   V0.111.0 的搜索转义错误（零命中）、V0.113.0 的 44px 规则被折成后代组合器、
   V0.114.0 的收藏没反馈（POST 成功但屏幕毫无反应）、V0.115.0 的两个 hero chip 一直显示
   `金价 --` / `时效 --` 与 1y 变化率恒为 `None` —— 全都不抛异常、全都不进 CI。
   这四类缺陷只能靠**实跑 + 反向验证**抓到，所以「撤销改动必须变红」才是门禁的验收
   标准，而不是看退出码。

2. **豁免清单会自我腐化；注释里的字面量会被门禁当真代码。**
   V0.114.0 把 favicon 404 豁免掉，V0.114.1 就得单开一轮把它修掉 —— 豁免要么限时修掉，
   要么写清**为什么无害**与**什么条件下必须重新启用**。同一阶段反向出现的还有「注释里的
   『代码样文字』不能当代码」：V0.113.0 的门禁把 ⚠ 注释里的 `visibility:hidden` 当成了
   声明；V0.114.0 的 `check_i18n_keys` 把注释里的 `tr("headlines.source_" + key, ...)`
   当成真调用，凭空造出 3 个「缺失 key」。

3. **断言的判据必须是「被测代码的行为」，不是「工具的能力」。**
   V0.114.2 用 `page.on("filechooser")` 当判据，测的其实是 headless Chrome 连裸 file input
   都不发这个事件 —— **比没有断言更坏**（假绿）；换成 `document.elementFromPoint()` 看命中
   谁。同源的反例还有 V0.114.0 的「只断言请求发出去了」：服务端 4xx 时前端同样会发请求，
   必须补真实响应码断言（顺手发现 POST 返回 **201** 不是 200）。V0.113.0 也做过同样的
   纠偏：第一版断言查「文件里有没有 `min-height: 44px`」，改成查「选择器有没有被折成后代
   组合器」。

4. **凭实测选型、凭实测否掉候选；假数据比空卡更坏。**
   V0.114.0 的四源顺序、url 可空与金十 20 位 id 的 `String(32)` 全部来自实测表；
   V0.115.0 的黄金库存线宁可从零建，也不用「陈旧 21 个月且口径不对」的 ETF 份额去凑一个
   看起来像库存的数；V0.114.0 也明确**不做**跨源内容去重（实测重叠仅 2 条，收益低于误杀
   风险）。同一原则在 V0.111.0 出现过：上传物的原始文件名只当展示元数据，绝不参与路径拼接。

5. **门禁与硬编码断言必须同 commit 同步两处，否则 CI 即红。**
   V0.111.0 加别名要同时改 `tests/test_dependencies/test_main_app.py:114` 的
   `len(ROOT_ALIASES) == 17` 与 `scripts/check_routes.py` 的镜像 `EXPECTED_ALIAS_PATHS`；
   V0.115.0 决定不新增顶 nav 场景，正是为了不碰那 4 处硬编码断言。门禁本身也是债 ——
   V0.114.1 不得不把 `check_pwa_assets` 从 3 项扩到 4 项、把 `check_routes` 路由数
   19 → 20。

6. **「我以为是浏览器问题」先跑一遍另一个浏览器；不确定就写进遗留。**
   V0.114.2 的 Firefox 报障被实跑 Chrome 推翻（通用 bug），同一版又记录了
   `display:none` + `input.click()` 在 Chrome 放行、Firefox 拒绝的差异 —— 不加注释的话这条路
   会在 Chrome 上测得「通过」，上线后只在 Firefox 静默失效。V0.114.1 留下一条**未在目标
   浏览器实跑**的诚实记录；V0.114.2 同样诚实写下「未在 Firefox 实跑验证，请再确认一次
   再收工」；V0.114.0 则把行情侧 outage（`push2.eastmoney.com` 与 `push2his.eastmoney.com`
   本机均 HTTP 000、`akshare fund_etf_hist_em` 抛 `ConnectionError`，意味着
   `AkshareGoldHistoryProvider` 的主黄金 ETF 历史源正在静默失败、每次 518880 历史抓取都
   退化到内嵌 V8 引擎的 sina 子进程）明确列为**待用户决定**的独立故障，而不是顺手混进
   本轮 diff。

---

### 延伸阅读

- 逐版本能力对照：[docs/releases/index.md](../index.md)
- 版本历史与当前焦点：[CHANGELOG.md](../../../CHANGELOG.md) · [docs/roadmap.md](../../roadmap.md)
- 产品能力全景：[docs/overview.md](../../overview.md) · [docs/architecture.md](../../architecture.md)
