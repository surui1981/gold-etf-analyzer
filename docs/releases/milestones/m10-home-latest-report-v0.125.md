# M10 · 首页研报入口（V0.125）

> **一句话**：**首页加一条「今日市场研究报告」入口 —— 只显示最新上传的那一份**，
> 点标题直达报告本体（不是一份列表）。
>
> **发版区间**：V0.125.0 ｜ **状态**：活跃（最新里程碑）
> **本文件定位**：把「首页直达研报」这条产品线的**口径决策**与**顺带修掉的真缺陷**写成一条可复核的脉络。
> **逐版原始全文**在 git 历史里：`git show v0.125.0:CHANGELOG.md`
> **注意**：本里程碑覆盖到当前版本，**应用当前正在用的版本号以 [../../version-status.md](../../version-status.md) 为准**。

## 〇 一页结论

| 问 | 答 | 依据 |
|---|---|---|
| 首页上有什么？ | 一条独立的 `.home-report` 条带：标题「今日市场研究报告」+ 日期 chip +「全部报告 →」 | §四 |
| 显示几份？ | **一份** —— 最新上传的那份 | §二 |
| 「最新」是哪个口径？ | **最新上传**（`created_at` 倒序），**不是**报告自身日期最新 | §二·2 |
| 首页那份和存档列表第一行是同一份吗？ | **是**（同一套排序常量，有测试锁住这个不变式） | §二·2、§三·3 |
| 一份都没上传过怎么办？ | `200 {"item": null}` —— 显示「还没有上传过报告」，**不是** 404 | §三·2 |
| 接口挂了怎么办？ | 显示「报告加载失败」并压暗 —— **绝不把故障说成空库** | §四·3 |
| 报告本体怎么打开？ | **新标签页**（`target="_blank" rel="noopener noreferrer"`）—— 不能 iframe | §四·2 |
| 顺带修掉了什么？ | i18n 门禁的**盲区**（小写 `t()` 形式从未被扫）+ 一个真缺失键 `ai.streaming` | §五 |

---

## 一、版本一览

| 版本 | 主题 | 关键交付 |
|---|---|---|
| **V0.125.0** | 首页「今日市场研究报告」入口 | 新端点 `GET /api/v1/reports/latest`（只返回最新上传的一份）· 首页新增 `.home-report` 条带（标题/日期 chip/分类/大小/上传时间/摘要/「查看报告 →」）· 3 语 i18n（`home.report_*` 7 键）· **6 条新测试**（含「首页那份 == 存档列表第一行」不变式）· 顺带把 i18n 门禁的**扫描盲区**补上（in-scope 501 → **582**）并修掉真缺失键 `ai.streaming` |

---

## 二、需求与口径

### 2.1 需求原文

> 「我们在首页提供一个今日市场研究报告的连接提供查看研究报告的功能，
> **只显示最新的得到的上传报告**。」

拆成三个可执行的决定：

| 决定 | 内容 | 为什么 |
|---|---|---|
| **放在哪** | 首页一条**独立**的 `<section class="home-report">`，**不插进 `.home-scenes` 网格** | `.home-scenes` 那 8 张是 260px 的纯链接磁贴，且 **4 个门禁脚本硬编码「场景卡 = 8 张」**（`_verify_nav_8` / `_verify_home_metals` / `_verify_home_verdict` / `_verify_report_archive`）⇒ 插进去要连带改 4 处断言；独立条带零改动 |
| **显示几份** | **一份**（最新上传的那份），**不给列表** | 用户要的是「刚拿到的那份」，不是一份目录；列表已有 `/report-archive` |
| **「最新」怎么定** | **最新上传**（`created_at` 倒序 + `id` 兜底） | 见 §二·2 |

### 2.2 「最新」= 最新**上传**，不是报告自身日期最新 —— 这条必须钉死

报告存档里 **补录旧报告是常态**：今天拿到一份上周的报告，填 `report_date = 上周一` 再上传。

| 候选口径 | 后果 | 判定 |
|---|---|---|
| `report_date` 倒序（报告自身日期最新） | 补录一份旧报告会把**刚上传的那份挤到第二行** ⇒ 首页显示的既不是用户刚拿到的、也不是存档列表第一行 | ❌ |
| `created_at` 倒序（最新上传） | 首页那份 **== 存档列表第一行** ⇒ 用户点进去和从存档页点进去看到的是同一份 | ✅ **采用** |

⚠ 这条不是「选一个顺眼的」—— 它被**一条测试**钉住（§三·3）：

```python
# tests/test_api/test_reports.py::test_latest_matches_list_first_item
assert latest["id"] == listing["items"][0]["id"]
```

排序口径**只在仓储层写一份**（`desc(created_at), desc(id)`，列表与 latest 共用同一对 `order_by`），
不在 service 层再抄一遍。

⚠ 另一条边界：**多用户隔离**。`get_latest` 带 `user_id` 过滤 ⇒ A 用户看不到 B 用户的报告
（单用户模式下 `resolve_user_id` 回退 `LEGACY_USER(id=1)` ⇒ 行为不变）。

---

## 三、后端：`GET /api/v1/reports/latest`

### 3.1 三个新件

| 层 | 文件 | 内容 |
|---|---|---|
| 仓储 | `src/app/repositories/reports.py` | `get_latest(user_id=...)` —— 与 `list_items` **同一套排序** |
| schema | `src/app/schemas/reports.py` | `ReportLatestOut{item: ReportOut \| None}` |
| 服务 | `src/app/services/reports.py` | `latest()` —— 空库返回 `item=None`，**不抛 404** |
| 端点 | `src/app/api/v1/endpoints/reports.py` | `GET /api/v1/reports/latest` |

### 3.2 为什么空库返回 `200 {"item": null}` 而不是 404

首页要能区分两种**完全不同**的状态：

| 状态 | 含义 | 首页显示 |
|---|---|---|
| `item: null` | **还没上传过**（正常状态） | 「还没有上传过报告 —— 去「报告存档」上传一份。」 |
| 请求 rejected / 返回体没有 `item` 字段 | **接口挂了**（降级态） | 「报告加载失败」+ 整块压暗（amber 描边） |

⇒ 用 404 的话这两种在 `Promise.allSettled` 里长得一样，前端只能一律显示「加载失败」
—— **把故障说成空库**（memory `fallback-masks-missing-data` 那条纪律的同一个坑）。

前端因此用 `hasOwnProperty(payload, 'item')` 判定「接口有没有回话」，
**不是**判 `payload` 是否为空 —— `allSettled` 里 `fulfilled + null` 与 `rejected` 必须分得开。

### 3.3 ⚠ 路由声明顺序（FastAPI 按声明顺序匹配）

新端点注册在 `/{report_id}` **之前**：

```python
@router.get("/latest", ...)     # ← 必须在前
...
@router.get("/{report_id}", ...)  # ← 否则 "latest" 被当成 report_id → 422（不是 404）
```

这不是新坑 —— `/categories`、`/stats` 当初就踩过同一个（memory `scoring-hit-filter` 那类
「静默 422」）。**新增字面量子路径时记得插在 `/{report_id}` 上方**，
并有一条测试 `test_latest_route_not_swallowed_by_report_id` 守着。

### 3.4 测试（`tests/test_api/test_reports.py`，**43 passed**）

| 测试 | 守住什么 |
|---|---|
| `test_latest_route_not_swallowed_by_report_id` | 路由顺序（200 而不是 422） |
| `test_latest_empty_is_null_item_not_404` | 空库契约（`{"item": null}`） |
| `test_latest_returns_last_uploaded` | 返回的是刚上传那份 + `view_url` 指向 `/content` |
| `test_latest_uses_upload_time_not_report_date` | **上传时间 ≠ 报告日期**（补录旧报告仍是最新） |
| `test_latest_matches_list_first_item` | 首页那份 == 存档列表第一行 |
| `test_latest_excludes_other_users_report` | 多用户隔离 |

---

## 四、前端：首页 `.home-report` 条带

### 4.1 结构

```
<section class="home-report" id="homeReport">
  <div class="home-report-head">
    <h3 data-i18n="home.report_title">今日市场研究报告</h3>
    <span class="home-report-chip" id="homeReportChip">2026-11-09</span>   ← 报告自身日期
    <a href="/report-archive" data-i18n="home.report_all">全部报告 →</a>
  </div>
  <div class="home-report-body" id="homeReportBody"></div>   ← 标题 / 分类·大小·上传于 / 摘要 / 查看报告 →
</section>
```

⚠ **body 初始为空**（HTML 里不预渲染「暂无报告」）——
「没有报告」这句话**必须来自接口**，不能是猜的。JS 没跑成时宁可空着。

### 4.2 报告本体只能**新标签页**打开

`GET /api/v1/reports/{id}/content` 的响应强制带：

```
Content-Security-Policy: sandbox allow-scripts allow-popups; connect-src 'none'; ...
X-Content-Type-Options: nosniff
Content-Disposition: inline
Cache-Control: no-store
```

`sandbox` 不带 `allow-same-origin` ⇒ 文档进入 **opaque origin** ⇒
**不能 iframe**、**不能 fetch 完塞 innerHTML**（那样会继承主站 origin）⇒ 只能
`<a target="_blank" rel="noopener noreferrer">`。
（`rel="noopener"` 还挡住新标签页反向操纵 `window.opener`。）

### 4.3 降级 UX：失败 ≠ 空

| 情形 | 判定依据 | 显示 |
|---|---|---|
| 接口失败 / 返回体没有 `item` | `allSettled` rejected 或 `!hasOwnProperty(payload,'item')` | 「报告加载失败」+ `.is-empty`（压暗 + amber 描边，与贵金属卡的降级态同款） |
| 接口正常但 `item === null` | `hasOwnProperty` 为真且 `item` 为空 | 「还没有上传过报告 —— 去「报告存档」上传一份。」 |
| 正常 | — | 标题（链接）/ 分类 · 大小 · 上传于 / 摘要 / 「查看报告 →」 |

### 4.4 ⚠ 一个真 bug：`created_at` 是 UTC，前端当本地时间解析 ⇒ **差 8 小时**

后端 `created_at` 来自 SQLite 的 `CURRENT_TIMESTAMP` —— 它是 **UTC**
（实测：sqlite 的 `CURRENT_TIMESTAMP` 与 `date -u` 逐秒相同），
而 SQLAlchemy 读回来是**无时区**的 naive datetime ⇒ Pydantic 序列化成
`"2026-11-08T22:15:34"`（**不带 Z**）。

`new Date("2026-11-08T22:15:34")` 按 ES2015 规范当作**本地时间**解析
⇒ 在 CST（UTC+8）机器上显示值比真实时刻**早 8 小时**。

实测（报告 id=20）：真实上传时刻 = BJT 11-09 06:15；不补 `'Z'` 会显示成 11-08 22:15。

⇒ 首页用了一个**显式的 UTC 解析器**：

```js
const parseUtc = (s) => {
  const str = String(s);
  const hasTz = /(?:Z|[+-]\d{2}:?\d{2})$/i.test(str);
  const d = new Date(hasTz ? str : str + 'Z');
  return isNaN(d.getTime()) ? null : d;
};
```

⚠ **已知遗留**：`static/report-archive.js::fmtBjt` 仍然按本地时间解析 ⇒
存档页的「上传于」**比真实时刻早 8 小时**。本轮**没有顺手改**它
（改它要连带重验存档页的既有门禁断言）⇒ 记为待办，见 §六。

### 4.5 i18n

3 语各加 7 个键（`home.report_*`）：标题 / 全部报告 / 查看报告 / 暂无报告 / 加载失败 / 上传于 {dt} / 未填日期。

⚠ `home.report_uploaded` 用了 `{dt}` 占位符 ⇒ 走 `window.I18n.t(key, params)` 的参数替换
（**不是** `window.PM_I18N` —— 后者不存在，memory `i18n-global-is-window-i18n`）。

JS 拼出来的部分（标题 / meta / CTA）**不带 `data-i18n`** ⇒ 切语言时必须整体重绘
⇒ 已挂进 `i18n:change` 监听（与 `renderMetals()` / `renderVerdict()` 并列）。

---

## 五、顺带修掉的一个**真缺陷**：i18n 门禁的扫描盲区

### 5.1 盲区在哪

`scripts/check_i18n_keys.py` 此前扫 3 种 JS 取 key 的写法：

| 形式 | 例子 | 此前是否被扫 |
|---|---|---|
| `i18n: "key"` | topnav.js 的 `SCENES` | ✅ |
| `I18n.t('key')` | headlines.js / command-palette.js | ✅（V0.112.0 补） |
| `tr('key', fb)` | decision-explainer.js / command-palette.js | ✅（V0.112.0 补） |
| `T('key', fb)` | synthesis-card.js / news-score-widget.js / scoring.js | ✅（V0.120.0 补） |
| **`t('key', fb)`（小写）** | **home.js / ask.js / auth.js / favorites.js / report-archive.js** | ❌ **从未被扫** |

本项目里 **5 个文件**各自定义了**同名小写包装器** `t(key, fallback)`
（字典没命中就回退代码里的中文常量）⇒ 这 5 个文件用到的 key **完全不在门禁视野内** ——
漏了 zh-TW / en-US 不会报错，运行时只是**悄悄显示中文**。

### 5.2 补上之后量到了什么

以 HEAD 的 `static/` 与本轮改后的 `static/` **对拍**（同一条正则，唯一差别是加不加小写 `t(`）：

| 指标 | 改前 | 改后 |
|---|---|---|
| 被引用的 key 总数 | 906 | **1011**（+105） |
| 落在严格清单里的 in-scope 数 | 501 | **582**（+81） |
| 这 81 个里的**真缺失** | — | **1 个**：`ai.streaming`（ask.js:829，三语都缺） |

⇒ `ai.streaming` 是**真缺陷**：`ask.js` 调 `t('ai.streaming', '调用中…')`，
字典没这一条 ⇒ **en-US / zh-TW 一直在显示中文兜底串**。本轮补齐（3 语）。

⚠ 数字是**实测**的，不是估的：改前那一列是把 `git archive HEAD static` 解到临时目录、
用同一套正则跑出来的（memory `doc-numbers-must-be-rerun-verified`）。

### 5.3 为什么这一轮值得顺手做

新加的 `home.report_*` 7 个键正是用**小写 `t()`** 取的（home.js 的既有约定）——
如果门禁仍看不见这个形式，这 7 个键**从落地那一刻起就没有 3 语保护**。
⇒ 先把门禁的洞补上，再让新键进去。

---

## 六、顺带修好的一个**既有坏门禁**：`_verify_nav_8.mjs` 间歇性挂死

### 6.1 现象

跑首页相关门禁时，`scripts/_verify_nav_8.mjs` 反复**挂死**在某个 `page.goto` 上：

```
【4】首页板块
Warning: Detected unsettled top-level await at .../_verify_nav_8.mjs:116
await page.goto(`${BASE}/home`, { waitUntil: "networkidle2" });
```

### 6.2 定位（**这一节的初版结论是错的，已订正**）

> ⚠ **订正说明**：初版把根因写成「Service Worker 接管后请求不发 `loadingFinished`」。
> 抓 CDP 原始事件后发现**两处都不对**：① SW 在 LAN 入口上**根本不参与**（见下）；
> ② 真正的缺失事件不是 `loadingFinished`，而是 `Page.lifecycleEvent`。
> **一个错误标签会让后来人照着错的方向查** ⇒ 这里保留订正过程，不只留结论。

**真正的根因（CDP 原始事件实测）**：

`/static/*.html` 的响应头只有 `etag` + `last-modified`，**没有 `Cache-Control`**
⇒ Chrome 套用「启发式缓存」⇒ **同一浏览器上下文里再次访问同一页面时，
主文档直接从磁盘缓存命中**（实测 `Network.responseReceived` 带 `fromDiskCache=true`）
⇒ 此时 Chrome **不再发 `Page.lifecycleEvent`**
⇒ puppeteer 的 `waitUntil`（`domcontentloaded` / `load` / `networkidle0` /
`networkidle2` **全都**）永远等不到那个事件 ⇒ **`page.goto` 无限期挂死**。

挂起时的现场（很能说明问题）：页面其实**早已加载完** ——
`document.readyState === "complete"`、标题正确、`Page.frameNavigated` 已发、
所有子资源都 `loadingFinished` 了 —— **只有 puppeteer 在等一个不会来的事件**。

实测复现率（脚本抓 CDP 事件，5 次连续导航）：

| 组合 | 结果 |
|---|---|
| 缓存开 + `domcontentloaded` | 6 次挂 **4** 次 |
| 缓存开 + `networkidle2` | 4 次挂 **2** 次 |
| **缓存关** + `domcontentloaded` | **8 次全过** |

⚠ **SW 为什么不是根因**：LAN 入口 `http://192.168.0.204:8888` **不是安全上下文**
⇒ `navigator.serviceWorker` 是 `undefined` ⇒ **SW API 在 LAN 上根本不可用**，
更谈不上「SW 接管」。（`setBypassServiceWorker(true)` 保留是为了 localhost，
那里 SW 可用 —— 但它在 LAN 上是空操作，别把它当答案。）

⚠ **为什么早先会误判成 SW**：初版只看了 puppeteer 的**现象**
（「在飞请求一直不减」），没抓 CDP **原始事件** ⇒ 只能猜。
**教训：门禁挂死要抓底层事件，不要靠现象反推**。

### 6.3 ⚠ 关键判定：**与本版改动无关**

把 `static/home.html` + `static/home.js` 临时换回 **HEAD 版本**、重启服务后，
**同一个门禁照样挂死**（只是挂在另一处 goto：第 146 行而不是第 116 行）⇒
**既有缺陷，不是 V0.125.0 引入的回归**。

⚠ 这类判定必须做 A/B（换回旧文件实测），
否则很容易把「自己刚改的东西」当成罪魁祸首，或者反过来
（memory `stub-hides-replaced-caller` 的同一类教训：**桩/旧件藏住真缺陷**）。

### 6.4 修法

**① 关掉浏览器缓存（关键那条）** —— 这也是**本项目既有惯例**：
`_verify_money_flow.mjs`（9 处）、`_verify_category_filter.mjs`、
`_verify_date_nav.mjs`、`_verify_upload_dialog.mjs`、`_verify_multi_source.mjs`
**早就写了 `setCacheEnabled(false)`**；**缺这一行的门禁，就是会挂的那些**。

```js
await page.setCacheEnabled(false);   // 主文档不再走磁盘缓存 ⇒ lifecycle 事件正常发
await page.setBypassServiceWorker(true);
```

**② 等 DOM，不等网络**（memory `gate-reads-unready-page`）：

```js
// 旧：await page.goto(url, { waitUntil: "networkidle2" });
await page.goto(url, { waitUntil: "domcontentloaded" });
await page.waitForSelector(".topnav a", { timeout: 15000 });            // 顶栏（JS 渲染）
await page.waitForSelector(".subnav a, .subnav-item, .subnav .tab", { timeout: 15000 }); // 子页签（JS 挂载）
```

`.home-scene`（8 张场景卡）是**静态 HTML** ⇒ `domcontentloaded` 后即可见。
`.subnav` 是 JS 挂载进 `#subnav-mount` 的 ⇒ 必须显式等。

修好后连跑 **4 次 = 27 passed / 0 failed**（原先是「挂死」）。

### 6.5 ⚠ 同一个缺陷的**系统性**排查

这不是「一个门禁的个别毛病」，而是**凡是多次 `page.goto` 的门禁都中招**。
本轮处理范围（**只动本版要跑、且本轮验证过的 5 个**）：

| 门禁 | goto 次数 | 本轮处置 |
|---|---|---|
| `_verify_nav_8.mjs` | 5 | ✅ 已加 `setCacheEnabled(false)` + 改 `domcontentloaded` |
| `_verify_home_report.mjs`（本版新增） | 1(+4 reload) | ✅ 已加 |
| `_verify_home_metals.mjs` | 1(+1 reload) | ✅ 已加 |
| `_verify_home_verdict.mjs` | 1(+1 reload) | ✅ 已加 |
| `_verify_report_archive.mjs` | 1(+1 reload) | ✅ 已加 |

**其余 ~20 个浏览器门禁没在本轮扫**：改一行很便宜，但**没逐个验证过的批量改动
比不改更危险**（memory `gate-that-crashes-is-not-a-gate`：崩的门禁不是门禁）⇒
已在 [docs/roadmap.md](../../roadmap.md) §五 登记为**带清单的待办**，下一轮批量做。
⚠ 排查脚本（抓 CDP 原始事件）留在 `scripts/_diag_nav8_cdp.mjs`——
**它是排障工具，不进门禁**（沿用本项目 `_diag_*.mjs` 的既有惯例），
但留着能让后来人 30 秒复现根因。

### 6.6 第二个不稳定源：门禁被**限流**打成假红（比 6.2 那个更阴险）

连跑 5 个首页门禁时，`_verify_home_report` / `_verify_home_verdict` 间歇性报
「en-US CTA 文案 → 实际 ""」「chip → 实际 "—"」——**跟被测功能毫无关系**。

| 事实 | 实测值 |
|---|---|
| 服务端限速 | 按 IP 做 **60s 滑动窗口**，`RATE_LIMIT_PER_MIN=600`（`.env.prod` 实测） |
| 一次 `/home` 加载的 API 请求 | **32 个**，其中 **20 个是 `/api/v1/favorites/exists/{external_id}`**（实测脚本 `scripts/_diag_home_req_count.mjs`） |
| 一个首页门禁跑一次 | **224 个请求**（140 个是 favorites） |
| 后果 | 连续跑 4 次就把桶打满 ⇒ **429**（实测：4 次连跑挂了 1 次） |

⚠ **为什么假红长得像真 bug**：429 打中 `/api/v1/reports/latest` ⇒ 首页 `getJSON`
返回 null ⇒ 条带走进**降级态** ⇒ CTA 消失、chip 变「—」⇒ 断言以为「功能坏了」；
**而门禁的错误过滤原先把 *所有* `/reports/latest` 错误一并排掉**
（`!/reports\/latest/`）⇒ **429 连日志都没留下**。

⇒ 修法三条：
1. **打桩掉 favorites**（它与这些门禁要测的东西无关）⇒ 一次门禁从 **224 个请求降到 84 个**；
2. 每个门禁配一个**独立限流桶**（`X-Forwarded-For` 假 IP，`198.51.100.1` ~ `.5`）
   —— 服务端**只对限流**信任 XFF（认证默认不看：`trust_proxy_headers=False`，
   实测 `.env.prod` 未设该项；即便开启，XFF 也只用于「审计展示 + 登录节流」，
   **不做安全判定**）；
3. **收窄门禁的错误过滤**：打桩阶段的错误单独收进 `mockErrs`，
   并**新增一条断言「打桩期间不许出现 429」** ⇒ 以后限流假红会**自己喊出来**。

⚠ **首页那 20 个请求本身是个真问题**（用户刷新几次就可能撞 429）——
批量 favorites 查询端点属**应用层**改动（可能要加端点 + 改前端 + 加测试），
**另立一轮**，本轮只登记（[docs/roadmap.md](../../roadmap.md) §五）不做。
⚠ 由此推论：**任何加载 `/home` 的门禁都要么打桩 favorites、要么自带限流桶**，
否则连跑几次就会假红 ⇒ 新增此类门禁时**先抄这 5 个里的一个**。

---

## 七、已知遗留（不在本轮范围）

| # | 事项 | 为什么没在本轮做 |
|---|---|---|
| 1 | `static/report-archive.js::fmtBjt` 的 **UTC 8 小时偏差** | 改它要连带重验存档页既有的门禁断言（`_verify_report_archive.mjs`）⇒ 单独立一轮更稳 |
| 2 | 首页条带**无「重新加载」按钮** | 首页其余模块也都是「打开即取」的同一口径；真需要时靠刷新页面 |
| 3 | `docs/api-reference.md` 的报告端点**此前整段缺失** | 本轮已补（§5 表 + 9 个端点） |

---

## 八、门禁与验证

| 类别 | 结果 |
|---|---|
| `scripts/check_version_sync.py` | 9 passed（4 处版本号 + CHANGELOG 降序 + 里程碑登记 + 基线未过期） |
| `scripts/check_i18n_keys.py` | **0 missing / 582 in-scope**（含本轮新增的 7 个 `home.report_*`） |
| `scripts/check_pwa_assets.py` | SW `v0.125.0` == 应用版本，54 条 SHELL_ASSETS 全部可解析 |
| `scripts/check_static_js.py` | 22 页 + 39 个共享脚本语法通过 |
| `scripts/check_docs_claims.py` | 149 处端点引用全部可在 `app.openapi()` 找到对应实体 |
| `tests/test_api/test_reports.py` | **43 passed**（6 条新增） |
| `scripts/_verify_home_report.mjs`（**新建**） | **49 passed / 0 failed**（真值 / 空态 / 故障态 / 反向验证 / 三语 / **打桩期间不许出现 429**） |
| `scripts/_verify_home_metals.mjs` | 39 passed（**含「场景卡仍为 8 张」断言**） |
| `scripts/_verify_home_verdict.mjs` | 55 passed |
| `scripts/_verify_report_archive.mjs` | 43 passed |
| `scripts/_verify_nav_8.mjs` | 修好后 **27 passed / 0 failed**（原先挂死，§六） |

### 8.0 稳定性复测（§六 / §6.6 修完之后）

**5 个首页门禁 × 连续 4 次 = 20 次全绿**（这是本轮「不稳定」问题的验收判据——
**一次绿不算数**，必须是连跑不翻）：

| 门禁 | run1 | run2 | run3 | run4 |
|---|---|---|---|---|
| `_verify_nav_8` | 27/0 | 27/0 | 27/0 | 27/0 |
| `_verify_home_report` | 49/0 | 49/0 | 49/0 | 49/0 |
| `_verify_home_metals` | 39/0 | 39/0 | 39/0 | 39/0 |
| `_verify_home_verdict` | 55/0 | 55/0 | 55/0 | 55/0 |
| `_verify_report_archive` | 43/0 | 43/0 | 43/0 | 43/0 |

⚠ **修之前的对照组**：同一串命令下 `_verify_home_report` 4 次里挂了 1 次、
`_verify_home_verdict` 4 次里挂了 2 次 ⇒ **修后 20/20 绿**才是有效证据。

### 8.1 线上实测（192.168.0.204:8888）

```
GET /openapi.json            → info.version = 0.125.0
GET /api/v1/reports/latest   → {"item": {"id": 21, "report_date": "2026-11-10", …}}
GET /api/v1/reports?limit=3  → 第一行同样是 id=21   ⇒「首页那份 == 存档列表第一行」在线上成立
```

⚠ **`id` 会每天变**（实测：每日 **BJT 06:15** 自动上传一份，UTC `22:15` ⇒ `id` 逐日递增）——
所以「id=21」只是**发版当天**的读数，**不变式本身**（首页那份 == 列表第一行）
由 `tests/test_api/test_reports.py::test_latest_matches_list_first_item` 与
`_verify_home_report.mjs` 钉住，不依赖某一个具体 id。

---

## 九、与既有里程碑的关系

| 里程碑 | 版本 | 关系 |
|---|---|---|
| [M4 · 报告存档与移动端](m4-archive-mobile-news-failover-v0.111-v0.115.md) | V0.111–V0.115 | **本版的前身**：报告存档页、上传、列表、CSP sandbox 隔离都出自那里；本版只是给它加了一条首页入口 |
| [M9 · 宏观面证据复算](m9-macro-face-evidence-v0.124.md) | V0.124 | 上一版；与本版无技术耦合 |
| **M10 · 首页研报入口（本文件）** | **V0.125** | **最新里程碑** |
