/*!
 * static/topnav.js — V0.91.0 · 共享顶 nav 同步注入（roadmap §4.1 M）
 *
 * 设计动机：8 页面原本各复制粘贴 25 行 nav markup（trend.html 主页 + silver /
 * portfolio / weights / trades / backtest / data-health / central_bank / review），
 * drift 风险 + 维护成本。每次新增页面都得记得复制 11 个链接 + brand。
 *
 * 设计取舍：
 * 1. **同步注入（非 defer）**：script 放在 placeholder div 紧后、无 defer/async，
 *    浏览器阻塞解析、加载、执行 → 用 `outerHTML` 替换 placeholder，此时 body
 *    还没渲染到 main 内容 → **无 FOUC**。如果用 defer，必须等 DOMContentLoaded
 *    后才注入，会出现几十毫秒的「无 nav」闪烁。
 * 2. **`outerHTML` 替换（不是 `document.write`）**：document.write 在 service
 *    worker / 部分 PWA 场景会被忽略；outerHTML 是标准 DOM API、跨场景稳定。
 * 3. **active 自动判定**：基于 `location.pathname` 与每条 link.path 严格匹配；
 *    redirect 路径（如 `/` → `/static/trend.html`）单独处理。brand 同理——
 *    4 个特殊 brand（silver / backtest / data-health / settings）按 pathname
 *    选 `brand.*` 命名空间，其他统一 `brand.gold`。
 * 4. **i18n 走原 `data-i18n` 协议**：注入的 nav 元素带 `data-i18n="nav.trend"`
 *    等属性，i18n.js（defer）按既有流程翻译；fb 默认文本（zh-CN）兜底显示，
 *    用户切到 zh-TW / en-US 后 i18n.js 替换。
 * 5. **V0.84.0：顶 nav 收为 1 行**（brand + 11 links）。原 row 2 的时效条 +
 *    警示按钮下沉到 `<details id="statusPanel">` —— 数据时效在 summary 内
 *    持续可见，警示以「⚠️ N 条要点」pill 形式同行右对齐；点开看警示全文。
 *    这样释放 ~36px 顶 nav 高度 + 删底部 warnFooter，腾出版面给 main。
 * 6. **V0.91.0：导出复盘报告按钮（📄）**：复用品牌行右侧的"顶栏"位置（D3 决策），
 *    9 页统一可见。**不进 NAV_LINKS**（按钮不是链接，单独模板）。
 *    点击 → 拼 `/report?days=&account_id=&...` URL → 新标签打开。
 *    URL 拼装优先调用 `PM_NavContext.buildReportUrl`（nav-context.js 加载后可用），
 *    否则用内联保底（防御：单页加载顺序变动时仍可工作）。
 *
 * 加载方式：紧跟 `<div id="topnav-mount"></div>` 之后，例如：
 *   <div class="wrap">
 *     <div id="topnav-mount"></div>
 *     <script src="/static/topnav.js"></script>
 *     <details id="statusPanel" class="status-panel">...</details>
 *     <section>... 页面主体 ...</section>
 *   </div>
 *
 * 兼容性：所有现代浏览器（Chrome 1+ / Firefox 1+ / Safari 1+）；
 * 旧 IE 不支持（项目早就不支持 IE）。
 */

(function () {
  "use strict";

  // 11 个链接 + 各自 i18n key + emoji + zh-CN 兜底文本
  // 顺序 = 显示顺序（不可调）
  // `activeFor` 列出路徑在哪些 pathname 下應點亮（解決 `/portfolio` → `/static/portfolio.html`
  // redirect 後 location.pathname 變 `/static/portfolio.html` 但 link.path 仍是 `/portfolio`）
  var NAV_LINKS = [
    { path: "/static/trend.html",       activeFor: ["/static/trend.html", "/", ""], ico: "📈", i18n: "nav.trend",        fb: "趋势追踪" },
    { path: "/portfolio",               activeFor: ["/portfolio", "/static/portfolio.html"], ico: "💼", i18n: "nav.portfolio",    fb: "持仓与决策" },
    { path: "/trades",                  activeFor: ["/trades", "/static/trades.html"], ico: "📜", i18n: "nav.trades",       fb: "交易历史" },
    { path: "/weights",                 activeFor: ["/weights", "/static/weights.html"], ico: "⚖️", i18n: "nav.weights",      fb: "权重配置" },
    { path: "/news",                    activeFor: ["/news", "/static/news.html"], ico: "📰", i18n: "nav.news",         fb: "消息面评估" },
    { path: "/review",                  activeFor: ["/review", "/static/review.html"], ico: "🔍", i18n: "nav.review",       fb: "研判复盘" },
    { path: "/central-bank",            activeFor: ["/central-bank", "/static/central_bank.html"], ico: "🏛️", i18n: "nav.central_bank", fb: "央行购金统计" },
    { path: "/static/silver.html",      activeFor: ["/static/silver.html"], ico: "🪙", i18n: "nav.silver",       fb: "白银追踪" },
    { path: "/static/backtest.html",    activeFor: ["/static/backtest.html"], ico: "🧪", i18n: "nav.backtest",     fb: "参数回测" },
    { path: "/scoring",                 activeFor: ["/scoring", "/static/scoring.html"], ico: "📊", i18n: "nav.scoring",     fb: "打分汇总" },
    { path: "/ask",                     activeFor: ["/ask", "/static/ask.html"], ico: "🤖", i18n: "nav.ask",            fb: "智能分析" },
    { path: "/static/data-health.html", activeFor: ["/static/data-health.html"], ico: "🩺", i18n: "nav.health",       fb: "数据健康" },
    { path: "/static/settings.html",    activeFor: ["/static/settings.html"], ico: "🔔", i18n: "nav.settings",     fb: "通知中心" },
  ];

  // 特殊 brand 按 pathname 选命名空间（4 页专属 brand）
  // 路径含 redirect 后形式（如 `/portfolio` → `/static/portfolio.html`），
  // 两个形态都登记，保证 `location.pathname` 是哪个都匹配上
  var BRAND_BY_PATH = {
    "/static/silver.html":      { i18n: "brand.silver",   fb: "白银价格投资辅助工具" },
    "/static/backtest.html":    { i18n: "brand.backtest", fb: "参数回测" },
    "/static/data-health.html": { i18n: "brand.health",   fb: "数据健康" },
    "/static/settings.html":    { i18n: "brand.gold",     fb: "通知中心 · 黄金 ETF" },
  };
  var DEFAULT_BRAND = { i18n: "brand.gold", fb: "黄金价格投资辅助工具" };

  // 计算当前页面的 active 路径与 brand
  var path = location.pathname;
  var brand = BRAND_BY_PATH[path] || DEFAULT_BRAND;

  // 构造 nav markup（与 V0.83 commit 4 迁移后的 8 页完全一致，puppeteer 门禁无改动）
  function escAttr(s) { return String(s).replace(/&/g, "&amp;").replace(/"/g, "&quot;"); }
  function buildNav() {
    var brandHTML =
      '<a href="/static/trend.html" class="brand" data-i18n="' + escAttr(brand.i18n) + '">' +
        '<span class="brand-dot" aria-hidden="true"></span>' + brand.fb +
      '</a>';
    var linksHTML = NAV_LINKS.map(function (l) {
      var active = l.activeFor.indexOf(path) >= 0 ? ' class="active"' : "";
      return '<a href="' + escAttr(l.path) + '"' + active + '>' +
        '<span class="nav-ico" aria-hidden="true">' + l.ico + '</span>' +
        '<span data-i18n="' + escAttr(l.i18n) + '">' + l.fb + '</span>' +
      '</a>';
    }).join("\n        ");
    var exportHTML = buildExportButton();
    return '<!-- V0.91.0 · 共享 topnav（topnav.js 同步注入，1 行 brand+links+export） -->\n' +
      '<nav class="topnav" aria-label="主导航">\n' +
      '  <div class="topnav-row">\n' +
      '    ' + brandHTML + '\n' +
      '    <div class="links">\n' +
      '      ' + linksHTML + '\n' +
      '    </div>\n' +
      '    ' + exportHTML + '\n' +
      '  </div>\n' +
      '</nav>';
  }

  // 导出复盘报告按钮（V0.91.0）—— 不进 NAV_LINKS（按钮不是链接，单独模板）。
  // 文案靠 i18n nav.export；icon 用 📄；走 brand 行右侧（CSS .nav-btn-export 定位）。
  // 走 data-i18n 协议，fb 默认 zh-CN 由 i18n.js 切语种后覆盖。
  function buildExportButton() {
    return '<button type="button" class="nav-btn-export" ' +
      'aria-label="Export report" ' +
      'data-action="open-report">' +
      '<span class="nav-ico" aria-hidden="true">📄</span>' +
      '<span data-i18n="nav.export">导出复盘报告</span>' +
    '</button>';
  }

  // 打开报告页 —— 优先走 PM_NavContext.buildReportUrl；fallback 内联保底。
  // 触发时机：用户点击 .nav-btn-export；事件委托到 document，避免对每个按钮单独绑。
  function openReport() {
    var url = null;
    if (window.PM_NavContext && typeof window.PM_NavContext.buildReportUrl === "function") {
      var days = window.PM_NavContext.get("days") || "30";
      url = window.PM_NavContext.buildReportUrl({ days: days });
    } else {
      // Fallback：nav-context.js 未加载（或加载顺序异常）时内联拼装
      var daysFallback = "30";
      try {
        var lsDays = localStorage.getItem("pm_ctx_v1_days");
        if (lsDays && /^\d+$/.test(lsDays)) daysFallback = lsDays;
      } catch (e) { /* 隐私模式 */ }
      var parts = ["days=" + encodeURIComponent(daysFallback)];
      try {
        var acc = localStorage.getItem("gold_account_id");
        if (acc && acc !== "all") parts.push("account_id=" + encodeURIComponent(acc));
      } catch (e) { /* ignore */ }
      url = "/report?" + parts.join("&");
    }
    if (url) window.open(url, "_blank", "noopener");
  }

  // 替换 placeholder div。必须同步：当前 script 紧跟 placeholder，浏览器在
  // 执行此 JS 时已解析到 placeholder 但未解析后续 main 内容 → outerHTML 替换
  // 不会引入 FOUC。
  var mount = document.getElementById("topnav-mount");
  if (mount) {
    mount.outerHTML = buildNav();
  } else {
    // 防御：找不到 placeholder 时回退到 body 头部插入（不完美但优于无 nav）
    console.warn("[topnav] #topnav-mount not found, fallback to body prepend");
    document.body.insertAdjacentHTML("afterbegin", buildNav());
  }

  // 事件委托：导出按钮 click。document 级委托一次，复用 9 页所有 nav 按钮实例。
  document.addEventListener("click", function (e) {
    var target = e.target;
    // closest 找到按钮本体（点击 icon / text 都能命中）
    var btn = target.closest && target.closest(".nav-btn-export[data-action='open-report']");
    if (!btn) return;
    e.preventDefault();
    openReport();
  });
})();
