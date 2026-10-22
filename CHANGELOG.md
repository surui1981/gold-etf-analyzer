# Changelog

> 黄金 ETF 投资辅助 · 完整发版历史
>
> 详细 release notes 见 [docs/releases/](docs/releases/) 系列

## [V0.115.0] · 2026-10-22

`首页贵金属走势区（金价 / 黄金库存 / 央行购金）` — feature · 详见 [v0.115.0.md](docs/releases/v0.115.0.md)

> 用户：「我们在主页页面内容缺少贵金属走势的页面，包括 金价变化、黄金库存变化、央行购金变化，
> 卡片放在今日要闻前面。」

- 🥇 首页新增**贵金属走势区**（`.home-scenes` 8 张板块卡与今日要闻之间的独立整行 section），
  三张卡：**金价变化**（XAU + 518880 + Au99.99 + 60 日走势线）/ **黄金库存变化** /
  **央行购金变化**（WGC 全球合计季度 + 较上季吨数增减）
  - ⇒ `.home-scene` 卡数**仍是 8**，顶 nav `SCENES` 不动，既有门禁断言零影响
- 📦 **COMEX 黄金库存从零建**：模型 + 迁移 `s1t2u3v4w5x` + 子进程隔离 fetcher
  （akshare 内嵌 V8 会崩 uvicorn）+ repo + service + `GET /market/gold/inventory`
  + 每日 08:10 BJT 调度 + CLI。实测 **1234 行 / 2021-10 起 / 最新 727.96 吨 / 近 1 年 -41.65%**
- 🔎 数据源是**实测选出来的**：否掉 `spot_quotations_sge`（无库存字段）与
  `fund_etf_scale_sse`（单截面且陈旧 21 个月、且不是库存口径）
- 🐛 **1y 变化率恒为 `None`** —— `snapshot()` 用 `date.today()` 当回看起点，
  但最新观测日落后今天 2 天，「一年前」那点落到窗口外。1m/3m 正常、**只有 1y 静默为空**
- 🐛 **`IntegrityError: NOT NULL ... source`** —— Core `insert()` **绕过 ORM 的 Python 侧
  `default`**（只认 `server_default`），迁移写了而模型没写 = schema 漂移
- 🐛 **2 处既有静默失效**（顺带）：hero 两个 chip 读的字段后端根本不返回
  （`price` vs `price_usd`、`overall_status` vs 只有 `degraded`）
  ⇒ 金价 / 时效 chip 从上线起一直停在 `金价 --` / `时效 --`
- ✅ 门禁：`_verify_home_metals.mjs` 34 条断言 + **反向验证 4 处**（挪位置 / 打桩
  `drawSpark` / 改回错字段名 / zh-TW 退简体，逐条确认变红）
- ✅ `check_i18n_keys.py` 新增 `"home."` 前缀 —— in-scope 240 → **307**，**0 missing**
  （此前首页文案根本不在严格清单里，漏同步只会静默回落）

---

## [V0.114.2] · 2026-10-22

`修点上传没有文件对话框` — hotfix · 1 处 CSS · 详见 [v0.114.2.md](docs/releases/v0.114.2.md)

> 用户报「点击报告上传，浏览器中没有文件上传的对话框」并附「我用的是 Firefox」。
> **Firefox 是对的线索，但不是原因** —— Chrome 实跑同样不弹。

- 🐛 上传区file input 是 `display: none`，而 `.drop` 上**只挂了 drag 事件、没有
  click 处理器** ⇒ 提示文案承诺的「点击选择」根本没有实现，唯一能用的路径是把
  文件**拖进来**，而文案完全没提。**所有浏览器都一样坏**
- 🔧 修法：把 `display: none` 换成**铺满 `.drop` 的透明覆盖层**（`opacity:0` +
  `position:absolute` + `z-index:2`）。真实点击落在**原生 file input** 上 ⇒
  浏览器默认行为就是弹对话框，**点击路径上不经过任何 JS**
  - ⚠️ **不用**「`display:none` + JS 调 `input.click()`」：Chrome 放行、Firefox
    拒绝（元素未渲染不允许唤起文件选择器）—— 不加注释就会在 Chrome 测得通过、
    上线后只在 Firefox 静默失效
  - ⚠️ 用 `opacity:0` 而非 `visibility:hidden`：后者会让控件在部分浏览器里
    **不可聚焦**，键盘用户彻底够不着（V0.113.0 口径）。配 `:focus-within`
    给 `.drop` 一圈可见焦点环
  - ♿ 拖拽不受影响：drag 事件从覆盖层冒泡到 `.drop`，原有监听器照旧命中
- 🧪 新增 `scripts/_verify_upload_dialog.mjs`（10 断言），**反向验证 6 条变红**，
  含决定性的一条：退回 `display:none` 后 `elementFromPoint` 命中的是无处理器的
  `<SPAN>`
- ⚠️ **判据选错的教训**：第一版用 `page.on("filechooser")` 当判据，结果是红的。
  基线测试证明**这个 headless Chrome 连裸 `<input type=file>` 真实点击都不发
  `filechooser`** —— 那条断言测的是 puppeteer 的能力，**比没有断言更坏（假绿）**。
  换成 `elementFromPoint(落点)` 才是真判据
- ⚠️ **未在 Firefox 实跑验证**：`puppeteer browsers install firefox` 因网络受限
  下不下来，请在 Firefox 里确认一次再收工

## [V0.114.1] · 2026-10-22

`修全站 favicon 404` — hotfix · 无新资源 · 详见 [v0.114.1.md](docs/releases/v0.114.1.md)

> V0.114.0 的 puppeteer 实跑里，`/favicon.ico` 的 404 一直躺在「豁免清单」里，
> 当时的判断是「全站性既存项、纯装饰、不在本轮范围」。**豁免存在过本身就是它坏了
> 的证据** —— 留着它，下次真出同类 4xx 会跟着一起被跳过，门禁从此对这一类失明。

- 🖼️ **根因**：浏览器约定 favicon 在**站点根** `/favicon.ico`，而 `StaticFiles` 只挂
  `/static/`；21 个页面**全部**没声明 `rel="icon"`。20 页虽引了 `rel="manifest"`，
  但 **manifest 的 icons 是 PWA 安装图标，不做标签页 favicon** ⇒ 照样 404
- 🔧 两层修法（分层不是冗余）：
  - **根作用域 `/favicon.ico` 路由**（真正止血的那层）—— 理由与既有 `/sw.js` 完全
    相同。兜旧书签 / 收藏夹 / PWA 安装前首屏 / 不解析 link 的客户端
  - **21 页补 `<link rel="icon">`**（声明式加固）—— 省一次根路径往返，路由若被
    nginx 改写仍有效。`static/icon-192.png` 早就在仓库里，**不新增任何资源**
  - ⚠️ 返回 192px PNG 而非真多尺寸 `.ico`；`content_type` 如实写 `image/png`，
    **不撒谎**（撒谎会让部分浏览器拒绝解析）
- 🧱 门禁：`check_pwa_assets` 从 3 项扩到 **4 项**（每页 rel=icon 存在 + href 指向
  真实文件 + `.png` 须带 type）；`check_routes` 登记 `/favicon.ico` → 200，
  路由数 **19 → 20**
- 🧪 三条反向测试**各自变红**：删标签 / href 指不存在 / 去掉 type。4xx 检测机制本身
  也反向验过（请求拦截器人为造 404，断言如实变红）
- 🎯 验证脚本 **删掉**豁免：puppeteer **23 → 28 passed / 0 failed，零豁免**

## [V0.114.0] · 2026-10-22

`新闻多源容灾` — 4 源链式 failover + 修「收藏无反馈」三层缺陷 · 详见 [v0.114.0.md](docs/releases/v0.114.0.md)

> 今日要闻原本**只有 readhub 一个源**，而这轮实测中 readhub 直接超时了一次 ——
> 单点无冗余不是理论风险，是已经发生过的事。

- 🔁 **4 源链式 failover**（wallstcn ★ → jin10 → eastmoney → readhub 兜底），首个足量即止
  - ✅ 端到端真重启 uvicorn 验 5 种场景：基线 `wallstcn/21` → A 挂 `jin10/16` →
    B 挂 `eastmoney/16` → C 挂 `readhub/14` → **D 四源全挂返回 HTTP 200**
    + `ok=False` + error 列全 4 源，`/items` 仍供末次数据（V0.84：绝不 500）
  - 🧱 `external_id` Integer → **String(32)**。计划里写的是 BigInteger，**实测推翻**：
    SQLite 的 INTEGER 是 int64（≈9.22e18），金十 id ≈2.02e19 ⇒ `OverflowError`。
    再加 `models/base.py::SourceId` TypeDecorator，因为绑定发生在 Python 侧、
    早于 SQLite affinity
  - 🔑 `UNIQUE(external_id)` → `UNIQUE(source, external_id)`：多源后 id **不再全局唯一**，
    同一个数字可能同时是华尔街见闻的 `3182985` 和金十的某条
  - 🌐 实测**金十 / 东财 0/20 条有 url** ⇒ url 改可空，无链接时标题渲染成
    `span.no-url` **不可点纯文本**（不合成 `href="#"`，V0.77.1）
  - ⚠️ 东财成功码是**字符串** `"1"`，`code != 1` 会把成功当失败（踩过）

- 🔔 **修「收藏从头到尾没有任何反馈」（三层，全是既存）**
  - ① `toast.js` 从未导出 `show`，而全站 **14 处**在调 `PM_Toast.show(...)`
  - ② `headlines.js` / `home.js` 只 guard `window.PM_Toast` ⇒ TypeError；
    `favorites.js` / `report-archive.js` guard 到 `.show` 为 falsy ⇒ 静默不弹
  - ③ `headlines.js` **模块作用域没有 `t()`**，却裸调 `t("favorites.toast_archived", ...)`
    ⇒ `ReferenceError`，且抛在 **catch 块内**无人接管 ⇒ 未处理拒绝
  - 三层用户可见后果**完全一样**：点了收藏，POST 成功，屏幕毫无反应
  - 🩹 修法：`toast.js` 补 `show(msg, type)` 派发器（一次修好 14 处，含 `error`→`err`
    别名 + 未知值退回 info 绝不抛错）；`headlines.js` 两处改 `tr()`
  - ⚠️ `headlines.js` **故意**不叫 `t()`：本页 `fmtBjtDate()` 内部有 `const t = new Date(iso)`，
    同名会把翻译函数整个遮蔽

- 🧪 **57 个新测试**（`test_news_sources_fetcher.py`）＋ 6 个多源入库测试 ＋ 5 个收藏服务测试
  · 相关 8 个文件 **195 passed / 1 failed**
  - 🕵️ 那 1 个失败是**既存**（已 `git stash` 在未改动的 main 上复现）：
    `test_list_items_filter_days` 的种子数据写死 2026-10-19，今天 10-22 ⇒ `days=1` 全被过滤。
    修它要连带改 4 个测试语义（tz-offset 用例期望 id 从 1002 翻成 1001），会让发版 diff
    混进无关改动，单独一轮处理
  - 🖥️ puppeteer **23 条断言全绿**：4 源渲染 / 无 `href="#"` 假链接 / fav POST 带
    `news_source` / 金十 20 位 id 全程字符串（点 `20261022055128917800` → POST 原样透传，
    先前 `parseInt` 会静默舍入到 …7000）/ 点收藏真的弹出 toast / 3 语无 key 泄漏
  - 🪞 验证脚本自身也修了两次：① 只能绿一次不算门禁（第二轮点同一张卡必然 409 幂等
    分支）⇒ 点击前经 API 删上一轮收藏；② 只断言「请求发出去了」不够（服务端 4xx 时前端
    同样发请求）⇒ 补真实响应码，顺手发现 POST 返回 **201** 不是 200

- 🔢 版本号 4 处同步 0.114.0（`__init__.py` / `pyproject.toml` / `uv.lock` / `sw.js`）

## [V0.113.0] · 2026-10-22

`移动端可用性` — UI + 门禁 · 无后端改动 · 详见 [v0.113.0.md](docs/releases/v0.113.0.md)

> 本项目第一次**在 390px 真实视口下逐页实测**。此前所有「响应式」都是桌面浏览器
> 缩窄窗口看出来的，没量过触控手指够不够得着。三类缺陷，而且**全都不报错**。

- 📱 **横向溢出 18/18 页归零**（此前 4 页表格溢出：`/scoring` **221px**、
  `/report` 175px、`/silver` 123px、`/central_bank` 71px；另 6 页因引导提示框硬编码
  宽度各多 11px）
  - 🧱 `.table-scroll`（`overflow-x:auto` + `overscroll-behavior-x:contain`）
    基元进 `theme.css`，**11 张宽表**套用：`scoring.js` 3 / `report.js` 5 /
    `silver.js` 1 / `silver.html` 1 / `central_bank.html` 1
  - ♿ 每处带 `tabindex="0"` + `role="region"` + `aria-label`（WCAG 2.1.1
    键盘可滚动）。**CSS 做不到，只能写在标记里**
  - 🌍 `aria-label` **复用小节标题已有的 i18n key**，静态页用 `data-i18n-aria`
    跟着语言翻 ⇒ **本轮新增 0 个 i18n key**
  - ⚠️ 基元**刻意不加** `min-width: max-content`：落地前写过带它的草案，验证时
    发现含长文本的表格在**桌面端**也被拖出滚动条才删掉

- 👆 **44px 触摸目标（WCAG 2.5.5 / Apple HIG 44pt），18/18 页归零**
  （此前 `/headlines` 单页 115 个，其余页零星 1–30 个）
  - 📐 `@media (max-width: 640px), (pointer: coarse)` 取**或** —— 平板横屏不窄
    但一定触摸，手机竖屏很窄但可能接鼠标，只认一个都会漏
  - 🚫 **刻意不放大**正文段落流里的文字链（`/headlines` 有 23 个，撑到 44px 会把
    排版撕碎）与 checkbox/radio 方块本体（触摸区域是包它的 `<label>`）
  - ⚠️ **`responsive.css` 的 40px 会压回 44px** —— 它在各页内联 `<style>` **之后**
    加载、同特异性胜出。光改 `theme.css` 的话全站 20 个按钮仍卡在 40px

- ⌨️ **聚焦被 sticky 顶栏遮挡 17 处 → 0**
  - 🐛 **17 处里 16 处是同一个 bug**：关闭的命令面板只有 `opacity:0`，而
    **`opacity:0` 的元素仍在 tab 序列里**（WCAG 2.4.3 / 2.4.7）。键盘用户进页面
    第一个 Tab 到的就是这个看不见的搜索框，且正好落在顶栏底下 ⇒ 看着像「点不动」。
    18 页里 16 页中招。**只影响键盘用户，鼠标用户完全无感** ⇒ 一直没人发现
  - 💡 关闭态改 `visibility: hidden`（参与 transition，淡出结束后才真正移出 tab
    序列），打开态 `visible`
  - 🎯 `scroll-padding-top`（浏览器滚动对齐预留）跟随顶栏**实测**高度，挂
    `resize` + `ResizeObserver` + `document.fonts.ready` + `i18n:change`

- 🐛 **顺手修 3 个既存缺陷**（验证时撞见的，都属 V0.77.1「静默展示错误内容」）
  - **`/report` + `/reset-password` 漏引 i18n 字典文件 ⇒ 整页渲染成 key 字面量**
    （21 + 11 处）。根因 `i18n.js:46`：非默认语言会动态插 `<script>` 取字典，
    **唯独默认语言 zh-CN 走 `syncLoadDefault()`**，只读 `window.PM_I18N_ZH_CN`，
    不自己去取 ⇒ **漏引没有任何机制会报错**
  - **`/report` 每访问一次吃一个 favicon 404**（单独引 `favicon.svg`，而该文件
    从来不存在；全站仅此一页引，图标已由 manifest.json 承担）
  - **`help.js` 提示框硬编码 320px 宽度** —— 窄屏媒体查询已改成
    `calc(100vw - 24px)`，拿桌面的 320 钳位 ⇒ 6 页各多 11px 横向溢出

- 🚪 **门禁 7 道全绿**，`check_cluster_render` **461 passed / 0 failed**（+28 断言）
  - 🎯 三个新基元都是**静默失效**型（写坏了不报错、DevTools 不显形），必须钉住：
    `.table-scroll` 4 条 / 44px 规则 7 条 / `responsive.css` 同步 2 条 /
    命令面板 `visibility` 2 条 / `topnav` `scroll-padding-top` 2 条 /
    11 张表源码契约 11 条
  - ⚠️ **本轮踩到的最大的坑**：44px 规则为了排版折成两行，换行 + 缩进被 CSS
    解析成**后代组合器**（匹配「input 里的 input」）⇒ 输入框实测停在 27–35px，
    而 `min-height: 44px` 就在文件里、`.matches()` 全绿 —— **就是没生效**。
    所以门禁那条核心断言查的不是「文件里有没有 `min-height: 44px`」（查不出死
    规则），而是「**选择器有没有被折成后代组合器**」
  - ⚠️ **门禁自己也踩了同一个坑**：第一版扫 `.pm-cmd` 规则里的 `visibility: hidden`，
    反向验证时**把真声明删掉门禁依然全绿** —— 因为该规则上方解释「为什么需要它」的
    ⚠ 注释里就写着 `visibility:hidden` 字样。改成**只扫字符串字面量**。这与
    `check_static_js` 里的「注释里的 `<script>` 字面量让正则吞掉真脚本」同类：
    **注释里的「代码样文字」不能当代码**
  - ✅ `check_i18n_keys` 新增字典文件加载检查（20 页）
  - ✅ `check_static_js` 在 `node --check` 前**先剥 HTML 注释**（注释里的
    `<script>` 字面量会让非贪婪 `.*?</script>` 吞到下一个真 `</script>`，
    报出的语法错误指向真实代码之外的行）
  - 🧪 **反向验证 9 个注入缺陷，9 条各自变红**。只看退出码会把崩溃当通过，所以
    每条都要求红在**指定那条**断言上；其中 1 条第一版红在别处（同块里
    `input[type=range]` 也带 44px，把「块内存在 44px 规则」顶住了）⇒ 断言改成
    判「input 规则**确实**带 44px（选择器与声明同属一条规则）」

- ✅ **新增 `scripts/_verify_mobile.mjs`（33 断言，18 页 × 390px 实跑）：全绿**
  逐页横向溢出 + 触摸目标 + 聚焦遮挡（合并在一次 `page.evaluate` 里）· 滚动容器
  真能滚 / `tabindex` / `role` / 无障碍名**不是 i18n key 字面量** · 11 张表源码契约 ·
  三语下 `aria-label` 跟着翻 · 关闭面板不可聚焦**且打开时仍然可见可聚焦**（别把功能
  改没了）· `scroll-padding-top == 顶栏实测高度`
- ✅ **回归全绿**：`_verify_cmd_palette` 30 · `_verify_nav_8` 26 ·
  `_verify_report_archive` 43（本轮动了 `topnav.js` / `command-palette.js` /
  `theme.css` / `responsive.css`，回归面不算小）
- 🔢 版本号 4 处同步 0.113.0（`__init__.py` / `pyproject.toml` / `uv.lock` / `sw.js`）

## [V0.112.0] · 2026-10-21

`命令面板修好` — UI + 门禁修复 · 无后端改动

- ⌘ **修好 ⌘K 命令面板**（V0.68.0 建的设施，此前一直半残）
  - 🐛 **全站没有任何可见入口**：`open()` 只由 Ctrl+K 触发 ⇒ **手机上 100% 打不开**
  - 🐛 **菜单停在两代导航之前**：硬编码的 7 条平铺导航，V0.98 双层导航、V0.111
    收敛到 8 场景后都没跟上 —— 今日要闻 / 报告存档 / 打分汇总 / 参数回测 / 白银 /
    收藏 / 数据健康 / AI 全部缺席
  - 💡 **根因不是忘了改，是没法改**：`SCENES` 只活在 `topnav.js` 的 IIFE 里不导出，
    面板拿不到导航结构只能自己抄一份，抄的那份自然腐化。现导出
    `window.PM_Topnav.SCENES`，面板在 `open()` 时**惰性派生**清单（8 场景 + 子页
    去重后 17 个导航目标 + 2 个动作 = 19 条）—— 加减导航项面板自动跟随，
    结构上不可能再腐化。惰性读取同时解开了与两个 defer 脚本的执行顺序耦合
  - 🚪 **顶栏新增「⌘ 搜索」按钮**（18 个有顶栏的页全有）：手机上唯一能打开面板的
    入口。走 `data-action` + document 委托，与导出按钮同一模式
  - 📱 **9 个页补挂 `command-palette.js`**（此前只挂 9/18）：`ask` / `backtest` /
    `data-health` / `favorites` / `headlines` / `home` / `report-archive` / `report` /
    `silver`。`login` / `offline` / `reset-password` 无顶栏，不补
  - 🧹 **删掉 / 修好 5 条「按下去什么都不发生」的死命令**（V0.77.1「失败态不伪装」同理）
    - 切换时间区间 ×3：派发 `pm-range-change`，全站 **0 个监听方**
    - 主题切换：派发 `pm-theme-change`，同样 0 个；且 `#pmThemeBtn` 本就常驻可见
    - 帮助：V0.68 调的是 `PM_Help.show()`，而 `help.js` 导出的是 `{ showModal,
      showTour, ... }` —— **从来没有 `show()`**。改调 `showModal()`
  - 🎨 **清单按场景分组**、组头不可点；过滤匹配 标题 / URL / 所属场景名；
    标签走 `I18n.t()`（只用 `fb` 会在 en-US 下显示中文，与顶栏对不上像 bug）
  - 📱 **触屏适配**（`pointer: coarse`）：行高提到 44px 触摸目标、面板上移、
    底部提示换成触屏文案；补深色主题样式
  - 🔁 `i18n:change` 时若面板开着则重建，换语言不用关掉重开

- 🎨 **顺带修顶栏按钮样式**：`nav-btn-cmd` / `nav-btn-export` 都是 `<button>`，
  各页内联的 `.topnav a {...}` 规则套不上，`nav-btn-export` 一直以浏览器默认浅灰
  外观落在深色顶栏上。样式补在 `theme.css`（而非散进 18 个内联块）。窄屏下
  `min-height: 44px`、文字标签隐藏只留图标

- 🔒 **修 `escHtml`**：V0.68 写成 `{ '&': '&', '<': '<', '>': '>', '"': '"' }` ——
  前四个映射到自身是 no-op，含 `<` 或 `&` 的标签会原样进 `innerHTML`

- 🚪 **修 `check_cluster_render.mjs` —— 这道门从 V0.99 起就一次都没真正跑过**
  - V0.99 C4 把 `silver.html` 655 行拆成 `silver.html` 332 + `silver.js` 445，
    A2 块要的 3 个函数全在 `silver.js`，门禁仍读 `silver.html` ⇒ `sliceBetween`
    找不到起始标记直接抛异常
  - 新增 `sliceFn()`（按大括号配对截取）。`sliceBetween` 的 `"\n}"` 结束标记
    **只在函数顶格写时成立**，函数一旦缩进（在 IIFE 内）就会一路吞到文件里下一个
    顶格 `}` —— 既可能让 `new Function()` 崩，也可能让 `includes()` 断言**假绿**
    （A2「加载条改由 finally 收起」原本就是这么通过的）
  - A7/A8 的 `sh` 改为 `silver.html + silver.js` 拼接：这些断言里既有查 JS 的
    也有查 CSS 色值的（`#e8f7ee` 还在 html 的 `<style>` 里），拼接的语义就是原意
    「白银这个页包含 X」，下次再拆文件不会又坏一遍
  - 「含 11 条 NAV_LINKS」断言自 V0.98 起一直失配（actual 21）。改为在循环外
    单跑的新块，断言 8 场景 + 21 导航目标 + `PM_Topnav` 导出 + 面板按钮接线
    —— 原断言读 `topnav.js` 却在 9 页循环里，跑 9 遍、失败刷 9 行
  - **结果：433 passed / 0 failed**（修之前是「启动即崩」，无从谈起通过率）

- 🚦 **补 `check_i18n_keys.py` 的扫描缺口**（加 `"cmd."` 到严格清单的前提）
  - 此前 JS 侧只扫 `i18n: "key"` 一种形态，漏掉两大类：`I18n.t('key')`
    （`headlines.js` 11 处）与 `tr('key', 'fallback')`
    —— 后者是本项目**既有约定**（V0.86 `decision-explainer.js` 首用），
    约 15 个 `decision.explain_*` + 本次的 12 个 `cmd.*` 全在门外
  - 补完后 in-scope **211 → 232**，且 **0 missing** ⇒ 这 21 个键三语本来就齐，
    纯粹是门禁看不见。已负向验证：删 zh-TW 的 `cmd.help` / `headlines.empty`
    均 `exit=1`
  - ⚠️ 这是**既存缺口**，不是本次引入 —— `headlines.*` 与 `decision.explain_*`
    在此之前一直不受门禁保护

- 🌐 **i18n**：`nav.cmd_palette` ×3 + `cmd.*` 12 键 ×3 语

## [V0.111.1] · 2026-10-21

`导航收敛` — hotfix · 无后端改动

- 🧭 **数据健康由顶级场景降为「配置」的第 3 个子页，顶 nav 9→8 项**
  （用户诉求：「把 AI 分析也和其他门类做成一样的部署，正好 8 个入口，结构也工整」）
  - 💡 **理由**：数据健康是运维诊断页，不是内容门类。降级后剩下 8 项全是真门类
  - 🏠 **首页仍是 8 张板块**：数据健康**只降 nav 层级、保留自己的首页卡**（它有
    独立摘要信息，是用户常回看的页面）。所以首页卡数（8）与顶 nav 场景数（8）
    相等却**不是一一对应** —— 数据健康有卡、但 nav 里归在「配置」下
  - 🐛 **顺带修两处导航不一致**：`topnav.js` 的 SCENES 与 `home.html` 的场景卡
    **原本顺序不同**（AI 与数据健康在两处是反的）。现在两处同序，AI 两边都排末位
  - 🩺 **数据健康页补挂 `#subnav-mount`**：它原先是独立顶级场景，不渲染二级导航
    行；降级后若不补，进本页顶 nav 只高亮「配置」却看不到自己在这组子页里的位置
    —— 与其余 13 个子页不一致。`.subnav` 样式由 `theme.css` 提供（该页已引），
    无需内联复制
  - 🌐 **i18n ×3**：配置卡补第 3 个 chip（`home.scene_config_3` = 数据健康）、
    描述补「健康」

- 🐛 **修 `_verify_report_archive.mjs` 两个自己的 bug**（不是应用错）
  - `page.click()` 在 puppeteer **默认 800×600** 视口下点不到上传按钮：顶 nav 在
    窄宽下折行撑高，其 sticky 层（z-index 100）正好盖住按钮，点击被派发给顶栏的
    `pmThemeBtn`，脚本表现为「点了没反应 / 上传超时」。1280×720 / 1352×900 实测
    正常 ⇒ 显式 `setViewport(1352×900)`
  - 首页卡数断言 8 → 7（V0.111.1 的改动本身）

## [V0.111.0] · 2026-10-21

`报告存档` — 功能 + 文档

- 📁 **首页新增「报告存档」场景：上传 HTML 报告 + 元数据登记表检索**
  （用户诉求：「首页添加一个报告上传的板块，用户可以上传 html 格式的报告，
  并提供客户查看显示，然后建立存单方便用户查看」；「存单」= 元数据登记表）
  - 🗄️ **存储**：新表 `reports`（user_id / title / stored_name / original_name /
    size_bytes / report_date / category / tags / summary），手写迁移
    `p2q3r4s5t6`。**不复用** `app_settings` KV —— 它无 `user_id`、整值替换、
    内存 TTL 缓存，结构上做不了列表
  - 🌐 **端点**：`/api/v1/reports/*` 8 个（upload / 列表 / 单条 / PATCH /
    DELETE / content / categories / stats）。⚠ `/categories` 与 `/stats`
    必须注册在 `/{report_id}` **之前** —— FastAPI 按声明顺序匹配，否则会被
    当成 `report_id` 报 422（各有一条测试锁住）
  - 🛡️ **上传校验 4 道**：扩展名 / ≤20MB / 去 BOM 后首字节必须是 `<` /
    **分块读累计**（不把伪装成 `.html` 的 500MB 整个读进内存）。入库失败回收孤儿文件
  - 🔒 **报告与主站同源 ⇒ 响应级 CSP sandbox**：
    `sandbox allow-scripts allow-popups; connect-src 'none'; form-action 'none'`
    。当前生产 `.env.prod` 没有 `AUTH_ENABLED` ⇒ 认证关闭、无 cookie、
    `user_id` 恒为 1，连 `ADMIN_TOKEN` 校验都被跳过 —— 所以真实风险不是
    「偷 session」，而是**报告里的 JS 能以你的身份调全部 `/api/v1/*` 写端点**。
    `sandbox` 不带 `allow-same-origin` ⇒ 文档进 **opaque origin**（读不到
    localStorage、够不到父页面）；`connect-src 'none'` 封死
    fetch/XHR/sendBeacon/WebSocket。**刻意不给 `default-src`** —— 那会连带禁掉
    外部 CSS/字体/图片把渲染打残
  - 🗂️ **落盘规矩**：绝不落 `static/`（SW `cache-first` + 限流豁免区，进去就
    永久回放）；用 `uuid4().hex`，原始文件名只作展示元数据、绝不参与路径拼接；
    落 `data/reports/`（systemd `ReadWritePaths` 白名单内，换别处生产会
    `Read-only file system` 而测试照过）
  - 🎨 **UI**：`/report-archive` 新页（工具条搜索/分类/标签 + 卡片列表 +
    侧栏统计 + 拖拽上传卡），卡片内联「编辑登记表」折叠区
  - 🧭 **导航**：独立顶级场景放在「情报」之后 → 顶 nav 8→9 项，首页卡 7→8 张；
    `main.py` 加 `/report-archive` 307 别名
  - 🌐 i18n 51 键 × 3 语（`reports.*` 49 + `nav.archive` + `brand.archive`）；
    `check_i18n_keys.py` 的 `V083_KEY_PREFIXES` 加 `reports.`（13→14 类）
- 🐛 **测试当场逮住一个真 bug：`_escape_like` 转义了但没接上**
  `repositories/reports.py` 把 `%` 转义成 `\%`，但每个 `.like()` 都没传
  SQLAlchemy 的 `escape=`。SQLite 默认不把反斜杠当转义符 ⇒ 搜 `100%` 一条都
  搜不到。**少传 `escape=` 比不转义更糟**：不转义是全命中（结果脏），错误
  转义是零命中（用户以为搜索坏了）。已全部补 `escape="\\"` 并写进 docstring
- 🐛 **修 `scripts/check_routes.py` 门禁假失败（SIGABRT 134）**
  `_start_in_process_server` 返回 thread 但**成功路径从不置 `should_exit`**，
  daemon uvicorn 线程在解释器收尾时仍写 stdout →
  `Fatal Python error: _enter_buffered_busy ... at interpreter shutdown`。
  多一条路由就改变时序（本改动下 4 次炸 1 次，基线 5 次不炸纯属运气）。
  改为返回 server 句柄 + `try/finally` 优雅停机，修后连跑 6 次 exit=0
- ✅ 37 条新测试 `tests/test_api/test_reports.py`；7 个 commit（C1 后端地基 →
  C2 服务层 → C3 端点 → C4 前端 → C5 导航/别名/门禁修复 → C6 sw.js → C7 发版）

## [V0.110.0] · 2026-10-21

`宏观因子手动校准 + docs 整理` — 功能 + 文档

- 🎯 **核心评估参数可由用户手动更新**（用户诉求：「有些核心评估参数更新不及时」）
  - 根因：`dxy` / `vix` **无自动实时源**，用 `STATIC_REF` 里 **2026-08-28** 的硬编码常量
    （96.5 / 18.5）。两者在宏观面内部合计权重 0.40，宏观面占综合指数 0.40
    → **综合指数的 16% 建立在两个半月前的常量上**，UI 上完全看不出来
  - ✏️ **存储**：`app_settings` 新增独立 key `macro_factor_overrides`
    （5 因子 × 值 / 数据日期 / 备注）；复用 `WeightService` 已有的 `SettingRepository`
  - 🔁 **优先级链**：用户手动覆盖 > 自动源（央行购金表 / 美联储 H.15）> 内置常量
  - 🌐 **端点**：`GET/PUT /api/v1/settings/macro-overrides`（PUT 需 admin session）
  - 🎨 **UI**：`/weights` 页新增「宏观因子手动校准」卡片 —— 5 行同屏显示
    「当前生效值 + 数据日期 + 来源标记」，复用已有的 `gold/trend` 响应不新增请求；
    滞后 > 1 交易日显示琥珀 chip；「清除全部覆盖」走二次确认弹窗
  - 🕐 **保存即失效两层缓存**：`MacroFactorService._CACHE`（10min）+ `served_cache`
    （10min，在前者之上）。只清前者时 `/market/gold/trend` 会从 served_cache 回放
    覆盖前的响应 —— 提示"已保存"而数值纹丝不动
  - 🌐 i18n 23 key × 3 语（zh-CN / en-US / zh-TW）
- 🐛 **验证期实跑修掉 4 个缺陷**（`scripts/_verify_macro_override.mjs` 15 项断言暴露）
  - **`served_cache` 漏清 —— 功能等于没做**：上面那条的实测形态。顺带修掉
    `PUT /settings/weights` 的**既有缺陷**（原先一个缓存都不清，改完权重后首页
    最长 10 分钟仍显示旧指数）。新增 `TrendService.invalidate_cached_results()`，
    `invalidate_for_news` 改为转发别名并说明三条调用路径；两条回归锁均验证过
    「去掉修复即 FAIL」
  - **`renderOverrides()` 冲掉用户正在输入的值**：整块 innerHTML 替换 + 首屏
    `loadOverrides()` 与 `loadTrendForPreview()` 并发（冷启动数秒）→ 静默提交全 null，
    表现为"我明明填了却没生效"且一次覆盖被全清。改为重渲染前 `snapshotUserEdits()`
    快照、渲染后写回
  - **备注输入框漏 `class="mo-note"`**：`.mo-row .mo-note` 整条 CSS 失效，
    字段退回默认宽度 → 「清除」按钮被挤到第二行，5 行全折
  - **冷启动显示「暂无读数」**：会被读成"因子丢了"；新增 `macroFactorState`
    （loading/ready/failed），加载期间显示中性「加载中…」
  - 🧹 重命名 `TrendService.invalidate_for_news` → `invalidate_cached_results`
    （名字带 news，但两条写入路径都调它，不改名会说谎；原名保留为转发别名）
- 🐛 **用户实测 hotfix —— 「保存失败：Not Found」**（部署滞后，非功能 bug）
  - 根因：`static/*.html` 由 `StaticFiles` **直接读磁盘**（改完即生效），而 Python
    路由**冻结在进程内存**（必须重启）。`8888` 的 root 进程 10月18日 启动、
    跑着旧代码，页面却已是新版 —— 页面有卡片、后端无端点，保存必然 404
  - **降级本身才是 bug**：首屏 `loadOverrides()` 404 画出的「加载失败」，被紧随其后
    成功的 `loadTrendForPreview() → renderOverrides()` **整个抹掉**，换成 5 行看起来
    完全正常的表单 —— 真实失败被一次后续的成功渲染吃掉了
  - 修：`overrideApiMissing` 置位后只画琥珀色说明块、不画表单、藏起表头与
    保存/清除按钮；`fetchOverrideApi()` 按 status 给可行动文案（404/403/422/5xx/网络），
    不再把裸 `Not Found` 抛给用户；i18n 8 key × 3 语
  - `.mo-ops` / `.mo-head` 的 `display:flex` 会盖掉 `[hidden]`，必须显式写
    `[hidden] { display:none }`；断言里加 `getComputedStyle` 检查防骗
  - 验证：`_verify_mo_degraded.mjs` 9 passed（跑在**真实旧后端** 8888 上，不 mock）
- 📚 **docs 整理**
  - 🐛 **死链门禁当时是红的**（12 条失效链接）：2 条指向已删除的 `application-guide.md`、
    3 条指向仓库外的 `.claude/.../memory/*.md`、1 条相对路径写错、
    5 条 `v0.87.0.md` 里带捕获组的 regex 被 `LINK_RE` 当成链接 —— 全部修掉
  - 🚦 **新增门禁**：`check_links.py` 增加 release notes 索引完整性检查
    （目录里有 `v*.md`、索引里没入口 ⇒ 报红）。此前 `releases/index.md` 停在
    V0.100.2，9 份 release notes 无人索引且无任何门禁报红；实际漏登记 **13** 份，已全部补齐
  - 🆕 **新建 `docs/README.md`**：按「我要做什么」导航 + 目录结构与三条边界 +
    文档门禁矩阵 + 三条踩过的坑；README 顶部补入口
  - 📈 **`roadmap.md` 补 9 个版本**：§1 里程碑表在 V0.100.0 后断了 V0.102–V0.109.2；
    §2 从「V0.101 迁移收口 in progress」（早已完成）改写为
    V0.110.0 已落 + V0.111.0 阈值可覆盖 + K 项多市场独立校准
  - 🏷️ 3 份规划文档补 `状态：` 抬头（`roadmap.md` / `improvement-path.md` / `ux-roadmap.md`）
  - 📑 `releases/index.md` 新增 §1.4.1「今日要闻」逐版本登记表
- ✅ **测试**：+21（API 7 / 宏观服务 7 / 设置服务 4 / 门禁 3）；相关回归 **157 passed**；
  UI 实跑 `_verify_macro_override.mjs` **15 passed / 0 failed**

---

## [V0.109.2] · 2026-10-20

`白银页面数据时效透明化（SGE akshare 数据滞后 2 天暴露）` — 接口透明化 hotfix

- 🐛 **白银 `/silver/sge-quote` 数据「缓存 2 天」伪象根因**
  - `ak.spot_silver_benchmark_sge()` 在生产常见滞后 2-3 个工作日
    （实测 2026-10-20 周二时接口最新数据停在 10-18 周日）
  - 原仓储 `get_silver_sge_quote()` 用历史 K 线末根日期当 `updated_at` + 没告诉前端
    → 用户反复刷新拿同一日数据 → 误以为「缓存 2 天」
  - cache TTL 不是问题（默认 300s = 5min 是合理的）
- ✅ **加 `data_as_of` 字段**到 4 个白银 quote schema（Silver/Etf/Gram/Sge）
  - 字段语义 = 数据真实所属交易日
  - 与 `updated_at` 分离，前端可独立判断 staleness
  - 向后兼容（`None` 默认，老客户端不报错）
- 🔍 **后端 staleness 检测**：`trading_days_between(last_date, today) > 1` → `_mark(ok=False)`
  - 阈值 1 工作日的直觉：Sun→Mon（跨周末挡路）不算 stale；Sun→Tue 算 stale
  - stale 时 source-bar 把 `sge_silver` 标 mock
- 🎨 **前端数据日期显示 + 滞后 chip**：3 个白银卡片下方显示「数据日期 YYYY-MM-DD」
  - 跨日 > 1 日历天时显示琥珀色「⚠ 数据滞后 N 天」chip
  - 复用 `fsh-chip fsh-warn fsh-stale-chip` 样式（freshness.js 已有）
  - `renderSourceBar()` 增强：尾部追加「⚠ 时效滞后: 〈源〉数据至 〈date〉（滞后 N 天）」
- 🛠️ **`utils.market_clock.trading_days_between()`** 简化版工作日数（周一至周五 5×24h）
- 🚫 **不引入新数据源**：akshare 滞后是上游问题；加代理源风险大、收益小
- ✅ **stale 时仍走真数据路径**（不切 mock）：让用户看到真实价 + 滞告提示；假数据会误导

测试增量：+10 全绿（market_clock trading_days_between 7 例 + market API data_as_of 3 例）

## [V0.109.1] · 2026-10-20

`分类架构改为「内容优先、站名兜底」` — 修正 V0.108.0「站名压过内容」的设计失误

- 🐛 **站名压过内容（V0.108.0 设计失误）**
  - V0.108.0 把 33 个优质站名写进内容关键词词典，站名与标题摘要同池、且财经优先级最高 → 站名成了最高优先级信号
  - 实测生产 DB 576 条：**160 条（27.8%）纯靠站名定类**，样例全是与财经无关的通讯社国际新闻
    - `印度东部踩踏致 17 人死亡` → 财经（财联社）
    - `伊拉克首都一弹药仓库发生爆炸` → 财经（财联社）
    - `法国多地大规模抗议 数百人被捕` → 财经（第一财经）
    - `胡塞武装发言人：沙特战斗机对萨那发动袭击` → 财经（格隆汇）
  - 即 V0.108.0 那个「财经 226 条」的漂亮数字主要是假象
- 🔍 **另一条实测推翻 V0.108.0 立论前提**：那 182 条纯站名定类的条目里**没有一条内容字段为空** —— 「白名单为了救空摘要好新闻」在生产数据上不成立，收益全来自科技垂直站
- ✅ **改为两段式**：内容优先（title+summary，财经>科技>创投>商业）→ 站名兜底 → 落「其他」弃入
- 🎯 **站名兜底只对垂直媒体开放**，分界是「垂直媒体 vs 综合通讯社」而非「财经 vs 科技」
  - 兜底：财经垂直（金十数据/同花顺/金融界/证券报/证券时报/每经）+ 科技垂直（techradar/9to5Mac/IT 之家/快科技 等 17 站）+ 创投垂直（36Kr/创业邦/投资界 等）
  - 排除：财联社/格隆汇/第一财经/界面新闻/经济观察报/华尔街见闻 —— 实测它们 14-35 条内容未命中条目里大量是战事灾难；发纯市场内容时仍会被内容词典命中
  - 最长匹配优先（`C114 通信网` / `IT之家` 带后缀）
- 🗑️ **33 个站名移出内容词典**（含 V0.105 起的财联社/华尔街见闻/格隆汇/金十数据）；指数名 `中证/上证/深证/创业板/科创板/沪指/深成指` 不是站名，保留
- 📊 **实测新分布**：科技 248 / 财经 58 / 商业 27 / 创投 5，入流 338，弃入 114，另 124 条黑名单站点不入流
  - 国际**财经**保留：韩国财长谈半导体景气 / 欧央行利率决议 / OPEC+ 减产
  - 国际**战事灾难**丢弃：印度踩踏 / 伊拉克爆炸 / 法国抗议 / 胡塞武装
- ✅ **测试 +7 例**（分类器 51 → 58），全量 115 passed
  - 修正 2 例编码了旧行为的断言（`test_classify_empty_title_uses_site_name` 原用华尔街见闻、`test_classify_whitelist_finance_site_v01080` 原断言 10 站全兜底）
- 🛠️ **新增 `scripts/reclassify_v01090.py`**：全量 sweep，**默认 dry-run**，`--apply` 才写库，`--drop-blocklisted` 连带清理新浪科技 122 + maomu.com 2 条存量；自动重建受影响日期的 `news_feed_daily`
  - 与 `reclassify_v01071.py` 区别：后者只扫 `category='其他'` 的行，修不了「被误判成财经的 28 条科技新闻」
- ⚠️ **已知精度问题**：`基金` 命中「老年基金会」、`经济` 命中村镇治理 —— rule-based 上限，需上下文消歧

## [V0.109.0] · 2026-10-20

`分类词边界修复 + 发布词精度` — PE ⊂ Europe 子串误匹配 + 中文裸词「发布」过泛

- 🐛 **`PE` 命中 `Europe` / `OpenAI`（财经优先级最高，误判代价最大）**
  - `"pe" in "europe"` 为真 → 所有提到欧洲 / OpenAI 的新闻都被判成财经
  - 实测生产 DB 576 条：**28 条科技新闻被误判成财经**（4.9%），含 Oppo / Claude / OpenCode / AWS / iPhone / Sony / Windows / 谷歌开源
  - 修法：长度 ≤3 的纯 ASCII 词（37 个）改走词边界正则 `(?<![a-z])KW(?![a-z])`，长英文词与全部中文词仍走子串
  - 边界定义「字母才算邻居」保证正常用法不受影响：`2026PE`、`科创50ETF`、`pe(ttm)` 照常命中
  - 复合词显式补齐 `AIGC` / `AGI` / `GPU云`（否则 `AIGC` 里的 `AI` 会被边界拒掉）
  - 同类一并修：`ETH ⊂ Ethiopia`、`GP ⊂ GPT`、`AI ⊂ Retail/Chain/Mail`
- 🐛 **中文裸词「发布」过泛**（V0.108.0 release notes 记录的已知问题 1）
  - 会把「警方发布彩叶观赏季安全提示」「中央档案馆集中开放」「俄乌战事通报」判成商业
  - 裸词换成 `发布会` + `发布公告`；实测移除裸词后失去唯一商业依据的恰好就是那 4 条噪声，7 条真发布会新闻全部保留
- 📊 **全量对拍**：生产 DB 576 条，30 条分类变化（5.2%）：财经→科技 28 / 科技→其他 1 / 财经→其他 1，**无一条改错方向**
- ✅ **测试 +9 例**（分类器 41 → 51），全量 108 passed
  - 含双向回归：`test_pe_no_longer_matches_europe`（核心）+ `test_pe_still_matches_standalone`（防修过头）
- ⚠️ **遗留**：历史 576 条仍带旧分类，`scripts/reclassify_v01071.py` 只扫「其他」行、不覆盖本次场景，需全量 sweep（留 V0.109.1）

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
