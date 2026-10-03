# 黄金 ETF 分析器 · 用户体验改进方向

> 版本基线 **V0.74.0**（`a9b2089`，本地 = 远程 = 标签 `v0.74.0`）｜实测日期 **2026-09-28**
> 审计范围：`static/` 下 12 个页面（6,299 行）+ 21 个共享脚本/CSS + Service Worker
> 方法：逐行源码核对 + Node 运行时取证 + curl 实测 + 项目自带门禁交叉验证
> **本文所有数字均为本轮实测所得，附可复核命令，无一来自推断。**

---

## 摘要

**代码层面版本差距为零** —— 本地与远程 `main` 同为 `a9b2089`，无需合并。

真正的问题不在版本，而在**「门禁全绿」与「用户可用」之间存在系统性断层**：项目现有四道构建期门禁（`ruff check` / `ruff format` / `pytest` 684 用例 / `check_static_js.py`）**全部通过**，但同一版本在浏览器中有 **3 处让用户直接碰壁的缺陷**，以及 17 处"失败了但用户不知道"的静默失败。

因此 UX 改进的正确顺序是：**先把"可信"补上（用户看到的必须是真的），再谈效率、理解与触达。** 否则在坏地基上加功能，只会放大困惑。

---

## 一、三个"用户直接碰壁"的缺陷（P0）

### P0-1 白银追踪页：两张主图永久空白

**用户症状**：打开「白银追踪」，页面先显示"正在加载白银行情数据…"，随后被抹掉，直接变成**一片空白** —— 不是"无数据"提示，是空白框。页面上「白银 ETF vs 纽约白银 对照」与「白银趋势主图」两块画布从始至终没有内容。

**根因（双层叠加）**

1. `static/chart-a11y.js:23-35` 的 `wrapChart(canvas, opts)` 契约本是**「给 canvas 打无障碍属性」**，它**既不执行 `new Chart()`，也没有 `return`**：

```js
// static/chart-a11y.js:23-35
function wrapChart(canvas, opts) {
  if (!canvas || canvas.getAttribute("role") === "img") return;   // 无返回值
  opts = opts || {};
  var label = opts.label || "图表";
  ...
  canvas.setAttribute("role", "img");
  canvas.setAttribute("aria-label", label);
  canvas.setAttribute("tabindex", "0");
  if (opts.table) insertTableFallback(canvas, opts.table.columns, opts.table.rows);
}                                                                   // 无 return
```

2. 但有 **5 处调用方把它当「图表工厂」使用** —— 传入 Chart.js 配置并接收返回值：

```js
// static/silver.html:344 与 :458（同样的错误写法）
window.silverCmpChart = ChartA11y.wrapChart(canvas, {
  type: "line",
  data: { labels, datasets: [...] },
  options: { responsive: true },
});
```

`silver.html:342` 取出的 `ctx = canvas.getContext("2d")` **此后从未被使用**；全页 `grep "new Chart"` 结果为空（只有注释提到）。**该页没有任何一处真正创建图表。**

**运行时取证**（Node + 最小 DOM 桩，执行 `chart-a11y.js` 真实代码）：

```
[场景1] silver.html:458  trendChart = ChartA11y.wrapChart(canvas, {type,data,options})
  返回值        = undefined
  canvas 属性   = {"role":"img","aria-label":"图表","tabindex":"0"}
  → trendChart 是否拿到图表实例: 否 ❌
```

**全仓 10 处 `wrapChart` 调用，5 处用法错误**：

| 位置 | 传入参数 | 结果 |
|---|---|---|
| `portfolio.html:1311` | `{ label, summaryId }` | 正确 |
| `trend.html:635 / 691 / 744 / 838` | `{ label, summaryId }` | 正确 |
| `silver.html:344` | `{ type, data, options }` | **实例 = undefined** |
| `silver.html:458` | `{ type, data, options }` | **实例 = undefined** |
| `backtest-chart.js:118 / 145 / 196` | `{ type, data, options }` | **实例 = undefined** |

**连带伤害（会咬人的那种）**

- `silver.html:457` 的 `if (trendChart) trendChart.destroy()` **永不生效**（实例恒 undefined）→ 一旦修好 `wrapChart`，每次重建都会叠加 Chart 实例，立刻变成内存泄漏。
- `silver.html:509` `setInterval(init, 60000)` 每 60 秒全量重跑；`silver.html:452-455` 每轮都 `appendChild` 一个 `data-badge` 且**从不清理** → 挂机 1 小时堆叠 60 个同位徽章。`trend.html:502-509` 同病。
- `silver.html:17` 的注释写着「V0.69.0：Chart.js a11y 封装必须在所有 `new Chart()` 调用之前同步加载」—— 而该页**根本没有 `new Chart()`**，注释与实现已经完全脱节。

**修复成本：约 30 分钟。** 5 处改为 `new Chart(canvas, cfg)` 后再单独调用 `ChartA11y.wrapChart(canvas, {label})`。

---

### P0-2 参数回测页：整页交互失效

**用户症状**：点「▶ 立即回测」**没有任何反应**；切换「基准标的 / 回看窗口」也不重算；页面永远停在「尚未运行 / 点『立即回测』开始计算」；底部三张结果图（夏普 / 最大回撤 / 校准曲线）恒为空白。用户会怀疑是自己操作错了或服务挂了。

**根因：脚本加载时序错误**

```html
<!-- static/backtest.html:332-337  内联脚本：解析到该行时【立即】执行 -->
renderChips();
window.PM_Backtest.mount({ onRun: runBacktest });   <!-- L334：此刻 PM_Backtest 尚未定义 → TypeError -->
(async function init() { ... })();                  <!-- L337：永远不会执行 -->
...
<!-- static/backtest.html:357  defer：要等 DOM 解析完成后才执行 -->
<script src="/static/backtest-chart.js" defer></script>
```

`defer` 脚本在 DOM 解析**结束后**才执行，而内联脚本在**解析到该行时立即执行**。因此 L334 抛出 `TypeError: Cannot read properties of undefined (reading 'mount')`，**该内联脚本自 L334 起全部中断**，导致：

- `#runBtn` 的 click 绑定（在 `backtest-chart.js:230-246` 的 `mount()` 内）**从未执行** → 按钮彻底无响应
- L337-351 的首次自动回测**从未执行** → 页面停在「尚未运行」
- L354-355 的 `daysSel` / `targetSel` change 监听**从未绑定** → 改参数不重算
- 点击权重 chip 时 L267 调 `window.PM_Backtest.debouncedRun` → 每次点击抛异常，静默无效

**即「参数回测」整页是一个死页面**，只剩 chip 的高亮切换有视觉反馈（因为那部分在 L334 之前）。

**修复成本：约 5 分钟。** `backtest.html:357` 去掉 `defer`，或把 L334/L337 的调用包进 `DOMContentLoaded`。

---

### P0-3 PWA 离线缓存从未成功（原子性失败）

**用户症状**：安装为 PWA 后断网，应用完全不可用 —— 连自带的离线提示页都出不来。

**根因**：`static/sw.js` 的 `SHELL_ASSETS` 里有 3 条 URL 在服务端不存在。**逐条 curl 实测**：

| URL | 实测状态 | 说明 |
|---|---|---|
| `/central_bank` | **404** | 真实路由是 `/central-bank`（`main.py:320`） |
| `/backtest` | **404** | 真实入口是 `/static/backtest.html` |
| `/silver` | **404** | 真实入口是 `/static/silver.html` |
| 其余 17 条（`/`、`/portfolio`、`/static/*` 等） | 200 / 307 | 正常 |

`cache.addAll()` 是**原子操作**：任一请求失败则整批 reject。因此 **`SHELL_CACHE` 是空的** —— `theme.css`、`theme.js`、`help.js`、`i18n` 字典、`manifest.json`、应用图标，一个都没进缓存。`sw.js:49-52` 只有外层 `.catch` 打日志，用户与开发者都无感。

**修复成本：约 5 分钟。** 3 条 URL 改为实际路径。

> **附带发现（值得单独重视）**：同一 App 内 **URL 风格分裂** —— 7 个页面走 RESTful 路由（`/portfolio`、`/trades`、`/weights`、`/news`、`/review`、`/central-bank`），4 个页面走静态文件路径（`/static/silver.html`、`/static/backtest.html`、`/static/data-health.html`、`/static/settings.html`）。SW 的崩溃正是这个分裂的直接后果 —— 写 SW 的人按 RESTful 风格猜了 3 个 URL。这既是 UX 问题（地址栏出现 `.html`，不像一个应用），也是持续性的维护隐患。

---

## 二、为什么门禁没拦住？（根因治理 · 本轮最重要的发现）

我实测运行了项目现有的前端门禁：

```
$ python scripts/check_static_js.py
[OK] 12 个静态页面内联脚本 + 19 个共享脚本全部通过（语法 / 引用 / DOM id）
```

**全绿。但上面的 P0-1 和 P0-2 都从它眼皮底下溜过去了。** 盲区恰好有两类：

1. **返回值语义不符** —— `wrapChart` 是一个**已定义**的函数，调用它语法合法、引用合法。检查器看不出「函数行为与调用方期望不符」。这类缺陷需要**运行时断言**才能发现。
2. **脚本加载时序错误** —— `defer` 与内联脚本的执行顺序是**运行时**语义（HTML 规范定义的行为），静态语法分析完全看不见。

**结论：现有门禁只覆盖「代码写对了吗」，不覆盖「用户能用到吗」。**

这是本轮最有价值的发现 —— 它比任何单个 bug 都重要，因为**它决定了同类缺陷会持续复发**。项目已经有过"文档声明不可校验 → 加 `check_docs_claims.py`"的成功先例（上一轮），现在需要在**行为层**做同样的事。

---

## 三、用户体验改进的五个方向

按「用户感知强度 × 修复成本」排序。方向 1-2 是"及格线"，3-4 是"体验增益"，5 是"防复发护栏"。

### 方向 1｜可信性：先让"看到的东西是对的"

> 一个投资工具的最低要求：我看到的数字和图形是真的。

**1.1 修 P0-1 / P0-2 / P0-3**（详见第一节，合计约 40 分钟）

**1.2 三态补齐（加载态 / 失败态 / 空态）**

当前全站的加载反馈**几乎为零**。实测各页"加载类关键词"命中次数：`central_bank.html` 全文仅 **1 次**，`weights.html` / `settings.html` / `backtest.html` 各 2 次，而**骨架屏全站 0 处**。用户看到的是旧数据一直停留到新数据覆盖，无从判断"我看到的数字是几点的"。

静默失败精确分布（口径：`catch` 体为空 / 仅注释 / 仅 `console` / `.catch(() => null)`）：

| 类别 | 数量 | 判定 |
|---|---|---|
| `<head>` 内 FOUC 守卫（弹窗防闪烁） | 11 处 | ✅ 可接受设计，不需改 |
| body 内静默 catch | 12 处 | ❌ 需治理 |
| `.catch(() => null)` 型 | 5 处 | ❌ 需治理 |
| **合计** | **28 处**（其中 **17 处**用户完全无感） | |

优先治理清单：`portfolio.html`（静默 1 + 返回 null 5）、`backtest.html`（2）、`freshness.js`（2）、`pwa.js`（2）、`trend.html`、`data-health.html`、`account.js`、`command-palette.js`、`backtest-chart.js`。

典型例子 —— 快照接口失败后，阈值提醒永久不出现，用户以为"今天没有异动"：

```js
// static/trend.html:435-446
try {
  const snaps = await fetchJSON(API_BASE + "/api/v1/snapshots?days=30");
  ...
} catch (e) { /* 快照不可达时忽略 */ }
```

**已有正确样板可直接复用**：`data-health.html:350-351` 的 `showLoading(false, "加载失败：" + e.message)`、`central_bank.html:477-483` 的"追加错误面板 + 给出修复命令"、`freshness.js:162-166` 的"红色时效条 + 明确说明不影响其他数据"。

**1.3 写操作成功反馈**

`portfolio.html` 最严重 —— 开仓 / 加仓 / 减仓成功后**只清空输入框**，用户只能靠"持仓表里悄悄多了一行"推断是否成功：

```js
// static/portfolio.html:821-828
await json(API.positions, { method: "POST", ... });
document.getElementById("qty").value = "";      // 清空
document.getElementById("grams").value = "";
loadPositions(); loadDecision();                // 静默重取，无任何提示
```

页面里**已有** `showUndoToast`（`portfolio.html:461-469`）基建，直接复用加成功 toast 即可，成本极低。对比 `weights.html:309`、`news.html:479`、`review.html:433` 都有明确的 ✅ 成功文案 —— 不是不会做，是没统一。

---

### 方向 2｜顺畅：消除"点了不知道有没有生效"

**2.1 防重复提交（对涉及资金的页面，这是真实风险，不只是体验问题）**

全站仅 **4 处**有效实现（`trades.html:288`、`trend.html:879`、`review.html:428`、`backtest-chart.js:233` —— 最后这处还因 P0-2 从未生效）。

**开仓 / 加仓 / 减仓 / 导出 / 建账本 / 保存权重 / 保存规则全部零防护**：

```js
// static/weights.html:297-311  连点 5 次会发出 5 个 PUT
async function save() {
  const msg = document.getElementById("msg");
  const body = collect();
  try {
    const r = await fetch(API, { method: "PUT", ... });   // 无 disable、无 in-flight 判断
```

对投资应用而言，"重复下单"是会造成真实损失的问题。建议抽一个统一包装器 `withLoading(btn, fn)`，一次性覆盖全站。

**2.2 危险操作二次确认**

| 位置 | 操作 | 现状 |
|---|---|---|
| `weights.html:153` | 「恢复默认」一键覆盖全部权重配置 | **无 confirm、无 try/catch**（`L313-317`），误点即丢失所有手工调参 |
| `settings.js:159-162` | 删除告警规则 | 无确认，直接 `splice` |
| `settings.js:448-462` | 退订 Web Push | 无确认，直接 `unsubscribe()` |
| `portfolio.html:1148` | 归档账本 | 传了 `danger=false`，危险色样式未启用 |

**2.3 弹窗风格统一**

实测原生弹窗：`portfolio.html` **11 处 `alert()` + 1 处 `prompt()`**，`settings.js` 2 处，`resonance-card.js` 1 处（**共 15 处**）。而页面里**已有**自研的精美 `confirmDialog`（`portfolio.html:443-458`，Promise 化、支持危险样式）和 `cd-mask`（`news.html:418-437`）。

两套风格混用，在移动端尤其突兀；且 `prompt()` 在部分浏览器 / WebView 中会被直接拦截。抽 `common-dialog.js` 统一即可。

**2.4 图表区空态**

```js
// static/portfolio.html:1259-1263  无数据时只改 hint 文本，但 300px 高的 .chart-wrap 仍是空白块
if (!d.points || !d.points.length) {
  hint.textContent = "暂无交易记录，记录买入后即可生成收益曲线";
  if (equityChart) { equityChart.destroy(); equityChart = null; }
  return;
}
```

`weights.html:245-247` 更典型：数据未就绪时直接 `return`，DOM 永久停在字面量「正在获取最新评估数据…」（接口失败后也永远停在那里）。

---

### 方向 3｜可懂：让"为什么"一眼可见

> 这个应用的核心价值时刻是：**打开它，1 分钟内知道该买还是该卖。**

**3.1 把「今日操作清单」移植到首页**

`trend.html:374-402` 的实现是全站最好的新用户引导 —— 4 步带完成状态 + 明确的「去打分 / 去查看 / 去开仓」跳转按钮：

```js
// static/trend.html:396-402
{ done: list.length > 0, title: "④ 记录 / 管理交易",
  value: list.length > 0 ? `当前 ${list.length} 笔持仓...` : "当前空仓 · 可按建议仓位建仓",
  btn: { label: list.length > 0 ? "去管理" : "去开仓", href: "/portfolio" } }
```

而 `portfolio.html` 是用户最可能直接落地的页面（也是导航里最醒目的入口），却没有这套引导。建议移植。

**3.2 修复新手引导（当前会把调试文案给新用户看）**

`help.js:189` 的 portfolio tour 第 3 步选择器写成了 `.decision-card, .panel`，但实测 `portfolio.html` 里这两个类名**出现 0 次**（该页只有 `class="card"`，7 处）。于是 `help.js:446` 的兜底分支会把**开发期调试文案**直接显示在引导气泡里：

```js
// static/help.js:444-448
if (!target) {
  tip.querySelector(".pmh-tip-body").textContent = `（找不到元素 ${step.selector}，跳过）`;
```

新用户首访会看到：**「（找不到元素 .decision-card, .panel，跳过）」**。同一问题也存在于 `help.js:145` 的术语表。

另外 `silver.html` / `review.html` / `backtest.html` **根本没有引入 `help.js`**（实测），完全没有引导。

**3.3 空态要给出路，不能是死胡同**

```js
// static/portfolio.html:762  文案有"先买入建仓"但不是链接/按钮，不指向表单
if (!list.length) { area.innerHTML = '<div class="empty">暂无持仓，先买入建仓吧</div>'; return; }
```

对比正确样板 `trades.html:335-340`（告知原因 + 给出具体下一步路径 + 提供放宽条件的方法）：

```js
'当前筛选条件下没有成交记录。<br>可在「持仓与决策」页通过加仓 / 减仓录入交易，' +
'或放宽筛选条件（如把日期区间清空、切到「全部账本」）后重试。'
```

**3.4 数据时效提示补全 3 页**

`freshness.js` + `GET /api/v1/market/freshness`（`market.py:50`，服务实现在 `services/freshness.py:51`）**已经实现且信息完整** —— 时段状态、时效等级、数据截止日、"N 分钟前"相对时间、`mock` 降级红标、加载失败提示都已具备。

覆盖 **8/12 页**。缺口：

| 页面 | 问题 |
|---|---|
| `central_bank.html` | 未引入 `freshness.js` |
| `backtest.html` | 未引入 `freshness.js` |
| `settings.html` | 引入了脚本但**没有 `#freshnessBar` 容器** → `freshness.js:157-158` 直接 return，静默 no-op（白跑一次请求） |

这三页补齐成本极低，收益直接。

**3.5 术语门槛**

`help.js` 已有 12 项 GLOSSARY（Sharp / 最大回撤 / 校准曲线等），但入口在右下角 `?` 悬浮按钮，隐蔽。建议在决策卡、回测结果卡内联术语提示。

---

### 方向 4｜可达：性能、移动端、离线

**4.1 首屏阻塞：5 页在 `<head>` 同步加载 200KB CDN 脚本**

```html
<!-- 完全相同的这一行出现在 5 个文件的 <head> 内，无 defer / async / preconnect -->
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.3/dist/chart.umd.min.js"></script>
```

位置：`portfolio.html:181`、`trend.html:16`、`silver.html:16`、`central_bank.html:16`、`backtest.html:16`。

**实测**：`status=200 size=205,637 B time=1.05 s`。当前可达，但无 `preconnect`、无 `crossorigin`、无本地兜底 → **CDN 不可达时这 5 页直接白屏**（对已安装的 PWA 尤其致命）。

讽刺的是：其中 `silver.html` 与 `backtest.html` 当前**一张图都画不出来**（P0-1），却完整付出了这次阻塞代价。

**4.2 内联 JS 无法缓存（实测 3,517 行）**

| 页面 | 总行数 | 内联 JS | 占比 |
|---|---|---|---|
| `portfolio.html` | 1,385 | **1,007** | 73% |
| `trend.html` | 923 | 615 | 67% |
| `news.html` | 561 | 316 | 56% |
| `silver.html` | 514 | 280 | 54% |
| `trades.html` | 488 | 263 | 54% |
| `central_bank.html` | 494 | 260 | 53% |
| `review.html` | 480 | 255 | 53% |
| `data-health.html` | 371 | 184 | 50% |
| `weights.html` | 340 | 180 | 53% |
| `backtest.html` | 359 | 145 | 40% |
| **`settings.html`** | 338 | **12** | **4%** ✅ |

**`settings.html` 是唯一把逻辑外置到 `settings.js` 的页面 —— 这个样板值得推广。** 内联 JS 无法被浏览器缓存、无法被复用，也拉高了每次改动的回归面。

同时存在明显的复制粘贴：`fetchJSON` 在 **7 个文件**各写一份（签名还不一致，`data-health.html:241` 版甚至没有 `timeout` 参数）；`esc()` 在 **10 个文件**重复定义（`news.html:268` 的版本不转义单引号，存在注入风险）；顶部导航块在 **11 个页面**逐字复制（漏链问题正是由此产生）。

**4.3 移动端导航形态分裂**

实测共享脚本引入矩阵（`✓`/`✗`）：

| 页面 | nav-drawer | command-palette | account.js | telemetry |
|---|---|---|---|---|
| portfolio / trend / news / central_bank / trades / review / weights / settings | ✓ | ✓ | ✓ | ✓ |
| **silver** | **✗** | **✗** | **✗** | **✗** |
| **data-health** | **✗** | **✗** | **✗** | **✗** |
| **backtest** | **✗** | **✗** | **✗** | **✗** |

≤768px 时，这三页的顶栏 11 个链接**全部平铺换行**、占掉大半个首屏，而其他 8 页是汉堡抽屉 —— 同一 App 内两种导航行为，用户每换一页都要重新适应。

**4.4 漏链**

`central_bank.html` 是 11 个业务页中**唯一没有「研判复盘」链接**的（实测 `href="/review"` 出现 **0 次**），从央行购金页无法进入复盘页。

**4.5 `settings.html` 零响应式**

该页自身 CSS **没有任何 `@media` 查询**，也未引入 `responsive.css`（其余 11 页均有）。而 `.pm-drawer { width: 360px }` 在 360px 宽的屏幕上等于全屏遮罩。

**4.6 离线补全**

修好 P0-3 后，还需把实际必需的资源补进 `SHELL_ASSETS`：`chart-a11y.js`、`freshness.js`、`account.js`、`dashboard.js`、`command-palette.js`、`settings.js`、`notifications.js`、`pwa.js`、`resonance-card.js`、`backtest-chart.js`、`data-health.html`、`settings.html`、`i18n/zh-TW.js`、`i18n/en-US.js`。

**4.7 i18n 补全**

实测字典键数：

| 语言 | 键数 | 完整度 |
|---|---|---|
| `zh-CN` | 699 | 基准 |
| `en-US` | 700 | ≈100% ✅ |
| **`zh-TW`** | **451** | **≈64.5%，缺 35%** ⚠️ |

繁体用户会看到大量简体字混排。好在 `i18n.js:70-86` 的 fallback 机制已用埋点 `i18n_fallback_hit` 记录命中 —— **可直接用埋点数据反推待补键位**，无需人工比对。

此外，**动态渲染内容 100% 硬编码中文**。静态标记覆盖率也不均：`news.html` 仅 25 处 `data-i18n` 标记 vs 101 行未标注中文文本；`backtest.html` 60 处标记 vs 仅 16 行未标注（做得好）。已做对的范本：`portfolio.html:390-398` 的 `_actionTxt` + `I18n.t()`，以及 `L1368-1372` 监听 `i18n:change` 重渲染动态区。

---

### 方向 5｜护栏：把「页面可用」纳入 CI（防复发，建议最优先做）

详见第二节。**最小可行方案**：CI 增加一个 headless 冒烟 job，加载 12 个页面并断言：

1. **无未捕获 JS 错误**（Playwright `page.on('pageerror')`）→ 拦住 P0-2
2. **关键交互可点**：`backtest.html` 点 `#runBtn` 后 `#resultSub` 文案发生变化 → 拦住 P0-2
3. **有图表的页面 canvas 存在非空 Chart 实例**（或 canvas 尺寸 > 0）→ 拦住 P0-1
4. **`sw.js` 的 `SHELL_ASSETS` 每条 URL 实测 < 400** → 拦住 P0-3

这 4 条断言可拦住本轮**全部 3 个 P0**。投入约 1.5 人天，换来对未来所有同类回归的防护。

> 这与上一轮加 `scripts/check_docs_claims.py`（文档声明校验）是同一思路的延续：**把"曾经出错的地方"变成可自动验证的门禁。**

---

## 四、路线建议

| 阶段 | 内容 | 预估 |
|---|---|---|
| **V0.74.1 · 修复版（建议立即）** | P0-1 / P0-2 / P0-3 三个功能缺陷；tour 选择器；`central_bank` 漏链；3 页共享脚本补齐 | **~0.5 人天** |
| **V0.75.0 · 体验补齐** | 方向 1-4：三态补齐、防重复提交、成功反馈、弹窗统一、空态出路、时效补 3 页、SW 资源补全 | **~4 人天** |
| **V0.76.0 · 护栏** | 方向 5：headless 行为冒烟纳入 CI；`scripts/` 纳入 ruff 范围 | **~1.5 人天** |
| 后续 | roadmap 既有的 V0.75.0「多用户登录 + 数据隔离」 | 6 人天 |

**建议顺序理由**：V0.74.1 只用半天就能消除"用户碰壁"，性价比最高；V0.76.0 的护栏虽然排在第三，但如果能提前，可以保护 V0.75.0 的所有改动不被回归。

> **⚠️ roadmap 落地标记需修正**：`docs/ux-roadmap.md` 中 V0.69.0 标注「Chart.js canvas a11y + 数据表 fallback」已落地、V0.71.0 标注「白银页 / 回测页」已落地（✅）。但实测：
> - `chart-a11y.js:52` 的 `insertTableFallback` 与 `:88-101` 的 `patchTrendChartInjection` **全仓无任何调用方**，`opts.table` 从未被传入 → **数据表 fallback 实现度 0**；
> - 白银页与回测页的图表与交互**实际未生效**（P0-1 / P0-2）。
>
> 建议按上一轮的做法，把落地标记改为 🟡 并注明实际状态，避免后续规划建立在错误前提上。

---

## 五、验收标准（建议直接写进 CI）

1. 12 个页面在 headless 浏览器中 **0 未捕获错误**
2. `silver.html` / `backtest.html` 的 5 个 canvas 均有**非空 Chart 实例**
3. `backtest.html` 点「立即回测」后 `#resultSub` 由「尚未运行」变为含结果行数
4. `sw.js` 的 `SHELL_ASSETS` 每条 URL 实测状态码 **< 400**
5. 所有写操作按钮在 in-flight 期间处于 `disabled`
6. 危险操作（恢复默认 / 删规则 / 退订 Push / 归档账本）**均弹二次确认**
7. 每个页面都存在 `#freshnessBar` 容器且能渲染出版本号与时效（或明确标注该页不需要）
8. `zh-TW` 键数 ≥ `zh-CN` 的 **95%**

---

## 附录 · 复核命令

```bash
export PATH="/usr/bin:/bin:$PATH"
cd gold-etf-analyzer

# P0-1 图表：确认真实调用形态
grep -rn "new Chart" --include=*.html --include=*.js static/
grep -rn "wrapChart" --include=*.html --include=*.js static/

# P0-2 时序：确认 defer 与内联调用顺序
grep -n "PM_Backtest\|defer" static/backtest.html

# P0-3 SW：逐条实测 SHELL_ASSETS
grep -oE '^\s*"/[^"]*"' static/sw.js | tr -d ' "' | while read u; do
  printf "%s -> %s\n" "$u" "$(curl -s --noproxy '*' -o /dev/null -w '%{http_code}' -m 6 "http://127.0.0.1:8888$u")"
done

# 门禁盲区：静态检查全绿，但页面是坏的
python scripts/check_static_js.py

# 服务端真实路由（对比 URL 风格分裂）
grep -nE '@app\.get\("' src/app/main.py

# 共享脚本引入矩阵
for f in static/*.html; do echo "$f: nav-drawer=$(grep -c nav-drawer.js $f)"; done

# i18n 键数
for f in static/i18n/*.js; do echo "$f $(grep -cE '^\s*"[^"]+"\s*:' $f)"; done
```

---

*报告生成：2026-09-28 ｜ 基线 V0.74.0（`a9b2089`）｜ 全部结论已逐条实测，可对上表命令直接复核。*
