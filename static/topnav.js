/*!
 * static/topnav.js — V0.98 C7 · 双层导航（顶场景 + 底 sub-tabs）
 *
 * 设计动机（V0.98 C7）：
 * 之前顶 nav 14 个链接平铺 1 行，wrap 后排版乱、首屏占用高、用户找不到
 * 所属「场景」。改为：
 *   - 顶 nav 8 个**场景入口**（首页 + 今日要闻 + 决策 + 持仓 + 情报 + 配置 + AI + 健康）
 *   - 底 nav **sub-tabs**：当前场景下子页快捷切换（决策 4 / 持仓 2 / 情报 3 / 配置 2）
 *   - 3 个独立顶项（首页 / 今日要闻 / AI / 健康）无 sub-tabs
 *   - active 判定：当前 pathname → 找所属 scene → 顶高亮 + 底高亮子页
 *   - 报告导出按钮（V0.91.0）保留在顶 nav 右侧
 *
 * 重要变更（V0.106 · 今日要闻提升到顶 nav）：
 *   - 「今日要闻」从「情报」子页（5 个之一）提升为顶级场景，排第 2 位（首页之后 / 决策之前）
 *   - 「情报」子页剩 4 个：消息面评估 / 央行购金 / 白银追踪 / 我的收藏
 *   - 用户原话「当前今日要闻页面连接 提升到 导航栏 首页之后 决策之前」：
 *     1) 让用户首屏即可达要闻（不必点开情报再下钻）
 *     2) 与「首页 / 决策 / 持仓」三大主操作并列，符合 V0.98 双层导航语义
 *
 * 设计取舍（与 V0.91.0 沿用）：
 * 1. **同步注入（非 defer）**：避免 FOUC。script 紧跟 placeholder。
 * 2. **`outerHTML` 替换（不是 `document.write`）**：service worker 友好。
 * 3. **active 自动判定**：基于 `location.pathname`。
 * 4. **i18n 走 data-i18n 协议**：defer 的 i18n.js 翻译；fb 兜底 zh-CN。
 * 5. **双 mount 同步注入**：
 *    - `<div id="topnav-mount">` → 顶 nav
 *    - `<div id="subnav-mount">` → 底 sub-tabs（紧跟 topnav-mount）
 *    - 找不到 subnav-mount 时仅渲染顶 nav（首页 / 今日要闻 / AI / 健康 4 页无 subnav）
 *
 * 加载方式：
 *   <div id="topnav-mount"></div>
 *   <div id="subnav-mount"></div>     ← 可选（无 subnav 的页不挂）
 *   <script src="/static/topnav.js"></script>
 */

(function () {
  "use strict";

  // ────────────── 8 个顶 nav 场景（顺序 = 显示顺序）──────────────
  // 每个 scene 是一个「顶级分类」：含子页 sub-tabs + 自己的入口 URL
  //  - key: scene 唯一标识
  //  - path: 顶 nav 点击时跳的 URL（场景默认页）
  //  - ico / i18n / fb: 顶 nav 显示
  //  - subpages: 子页数组（activeFor 按 pathname 匹配）
  // 顶项无 subpages 的（首页 / 今日要闻 / AI / 健康）：path 是入口，subnav-mount 不渲染
  var SCENES = [
    {
      key: "home", path: "/home", activeFor: ["/home", "/static/home.html"],
      ico: "🏠", i18n: "nav.home", fb: "首页",
    },
    {
      key: "headlines", path: "/headlines",
      activeFor: ["/headlines", "/static/headlines.html"],
      ico: "📢", i18n: "nav.headlines", fb: "今日要闻",
    },
    {
      key: "decision", path: "/scoring",
      activeFor: ["/scoring", "/static/scoring.html"],
      ico: "📊", i18n: "nav.scene_decision", fb: "决策",
      subpages: [
        { path: "/static/trend.html", ico: "📈", i18n: "nav.trend",     fb: "趋势追踪",     activeFor: ["/static/trend.html", "/", ""] },
        { path: "/scoring",            ico: "🎯", i18n: "nav.scoring",   fb: "打分汇总",     activeFor: ["/scoring", "/static/scoring.html"] },
        { path: "/static/backtest.html", ico: "🧪", i18n: "nav.backtest", fb: "参数回测",     activeFor: ["/static/backtest.html"] },
        { path: "/review",             ico: "🔍", i18n: "nav.review",    fb: "研判复盘",     activeFor: ["/review", "/static/review.html"] },
      ],
    },
    {
      key: "portfolio", path: "/portfolio",
      activeFor: ["/portfolio", "/static/portfolio.html"],
      ico: "💼", i18n: "nav.scene_portfolio", fb: "持仓",
      subpages: [
        { path: "/portfolio", ico: "💼", i18n: "nav.portfolio", fb: "持仓与决策", activeFor: ["/portfolio", "/static/portfolio.html"] },
        { path: "/trades",    ico: "📜", i18n: "nav.trades",    fb: "交易历史",   activeFor: ["/trades", "/static/trades.html"] },
      ],
    },
    {
      key: "intel", path: "/news",
      activeFor: ["/news", "/static/news.html"],
      ico: "📰", i18n: "nav.scene_intel", fb: "情报",
      subpages: [
        { path: "/news",                    ico: "📰", i18n: "nav.news",         fb: "消息面评估", activeFor: ["/news", "/static/news.html"] },
        { path: "/central-bank",            ico: "🏛️", i18n: "nav.central_bank", fb: "央行购金",   activeFor: ["/central-bank", "/static/central_bank.html"] },
        { path: "/static/silver.html",      ico: "🪙", i18n: "nav.silver",       fb: "白银追踪",   activeFor: ["/static/silver.html"] },
        { path: "/favorites",               ico: "⭐", i18n: "nav.favorites",    fb: "我的收藏",   activeFor: ["/favorites", "/static/favorites.html"] },
      ],
    },
    {
      key: "config", path: "/weights",
      activeFor: ["/weights", "/static/weights.html"],
      ico: "⚙️", i18n: "nav.scene_config", fb: "配置",
      subpages: [
        { path: "/weights",              ico: "⚖️", i18n: "nav.weights",  fb: "权重配置", activeFor: ["/weights", "/static/weights.html"] },
        { path: "/static/settings.html", ico: "🔔", i18n: "nav.settings", fb: "通知中心", activeFor: ["/static/settings.html"] },
      ],
    },
    {
      key: "ai", path: "/ask",
      activeFor: ["/ask", "/static/ask.html"],
      ico: "🤖", i18n: "nav.ask", fb: "AI 智能分析",
    },
    {
      key: "health", path: "/static/data-health.html",
      activeFor: ["/static/data-health.html"],
      ico: "🩺", i18n: "nav.health", fb: "数据健康",
    },
  ];

  // 兼容旧 topnav 字段：把每个 scene 摊平出可被 report/旧逻辑使用的 path/activeFor
  // （用于 brand 判定和 export 按钮不变）
  var BRAND_BY_PATH = {
    "/static/silver.html":      { i18n: "brand.silver",   fb: "白银价格投资辅助工具" },
    "/static/backtest.html":    { i18n: "brand.backtest", fb: "参数回测" },
    "/static/data-health.html": { i18n: "brand.health",   fb: "数据健康" },
    "/static/settings.html":    { i18n: "brand.gold",     fb: "通知中心 · 黄金 ETF" },
    "/static/headlines.html":   { i18n: "brand.headlines", fb: "今日要闻 · 黄金 ETF" },
    "/static/favorites.html":   { i18n: "brand.favorites", fb: "我的收藏 · 黄金 ETF" },
  };
  var DEFAULT_BRAND = { i18n: "brand.gold", fb: "黄金价格投资辅助工具" };

  // ────────────── 计算当前 active ──────────────

  var path = location.pathname;

  var brand = BRAND_BY_PATH[path] || DEFAULT_BRAND;

  // 找当前页所属 scene
  function findCurrentScene() {
    for (var i = 0; i < SCENES.length; i++) {
      var s = SCENES[i];
      if (s.activeFor && s.activeFor.indexOf(path) >= 0) return s;
      if (s.subpages) {
        for (var j = 0; j < s.subpages.length; j++) {
          if (s.subpages[j].activeFor && s.subpages[j].activeFor.indexOf(path) >= 0) return s;
        }
      }
    }
    return null;
  }
  var currentScene = findCurrentScene();

  // ────────────── HTML helpers ──────────────

  function escAttr(s) { return String(s).replace(/&/g, "&amp;").replace(/"/g, "&quot;"); }

  // ────────────── 顶 nav 渲染 ──────────────

  function buildTopNav() {
    var brandHTML =
      '<a href="/static/trend.html" class="brand" data-i18n="' + escAttr(brand.i18n) + '">' +
        '<span class="brand-dot" aria-hidden="true"></span>' + brand.fb +
      '</a>';
    var linksHTML = SCENES.map(function (s) {
      // active 判定：当前 scene 等于此 scene（含子页 active 的情况）
      var active = (currentScene && currentScene.key === s.key) ? ' class="active"' : "";
      return '<a href="' + escAttr(s.path) + '"' + active + ' data-scene="' + s.key + '">' +
        '<span class="nav-ico" aria-hidden="true">' + s.ico + '</span>' +
        '<span data-i18n="' + escAttr(s.i18n) + '">' + s.fb + '</span>' +
      '</a>';
    }).join("\n        ");
    var exportHTML = buildExportButton();
    return '<!-- V0.98 C7 · 双层导航顶 row：7 个场景入口 + brand + 导出按钮 -->\n' +
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

  // ────────────── 底 subnav 渲染 ──────────────

  function buildSubnav() {
    // 当前 scene 无 subpages（首页 / AI / 健康）→ 不渲染
    if (!currentScene || !currentScene.subpages || currentScene.subpages.length === 0) {
      return "";
    }
    var tabsHTML = currentScene.subpages.map(function (sp) {
      var active = (sp.activeFor && sp.activeFor.indexOf(path) >= 0) ? ' class="active"' : "";
      return '<a href="' + escAttr(sp.path) + '"' + active + ' data-subtab="' + escAttr(sp.i18n) + '">' +
        '<span class="sub-ico" aria-hidden="true">' + sp.ico + '</span>' +
        '<span data-i18n="' + escAttr(sp.i18n) + '">' + sp.fb + '</span>' +
      '</a>';
    }).join("\n        ");
    return '<!-- V0.98 C7 · 双层导航底 row：' + currentScene.fb + ' 场景子页 tabs -->\n' +
      '<nav class="subnav" aria-label="' + currentScene.fb + ' 子导航">\n' +
      '  <div class="subnav-row">\n' +
      '    <span class="subnav-label" data-i18n="' + escAttr(currentScene.i18n) + '">' + currentScene.fb + '</span>\n' +
      '    <div class="subnav-tabs">\n' +
      '      ' + tabsHTML + '\n' +
      '    </div>\n' +
      '  </div>\n' +
      '</nav>';
  }

  // ────────────── 导出复盘报告按钮（V0.91.0，沿用）──────────────

  function buildExportButton() {
    return '<button type="button" class="nav-btn-export" ' +
      'aria-label="Export report" ' +
      'data-action="open-report">' +
      '<span class="nav-ico" aria-hidden="true">📄</span>' +
      '<span data-i18n="nav.export">导出复盘报告</span>' +
    '</button>';
  }

  function openReport() {
    var url = null;
    if (window.PM_NavContext && typeof window.PM_NavContext.buildReportUrl === "function") {
      var days = window.PM_NavContext.get("days") || "30";
      url = window.PM_NavContext.buildReportUrl({ days: days });
    } else {
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

  // ────────────── 双 mount 注入 ──────────────

  // 顶 nav
  var topMount = document.getElementById("topnav-mount");
  if (topMount) {
    topMount.outerHTML = buildTopNav();
  } else {
    console.warn("[topnav] #topnav-mount not found, fallback to body prepend");
    document.body.insertAdjacentHTML("afterbegin", buildTopNav());
  }

  // 底 subnav（可选 —— 无 subnav 的页面不挂 mount）
  var subMount = document.getElementById("subnav-mount");
  if (subMount) {
    var subnavHTML = buildSubnav();
    if (subnavHTML) {
      subMount.outerHTML = subnavHTML;
    } else {
      // 当前页无 sub-tabs（首页 / AI / 健康）→ 隐藏空 mount 占位
      subMount.outerHTML = "";
    }
  }

  // ────────────── 事件委托：导出按钮 ──────────────

  document.addEventListener("click", function (e) {
    var target = e.target;
    var btn = target.closest && target.closest(".nav-btn-export[data-action='open-report']");
    if (!btn) return;
    e.preventDefault();
    openReport();
  });
})();
