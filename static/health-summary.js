/* 全站数据健康摘要 chip / panel（V0.85.0）
 *
 * 把分散在各页 statusPanel summary 里的「3 市场时效」chip 换成「6 数据源健康摘要」，
 * 数据时效完整披露集中到 /data-health（V0.85.0 起，与项目 kebab-url 约定一致：
 * /portfolio /central-bank /trades 等都不带 .html 后缀）。
 *
 * 挂载点（按页面二选一）：
 *   - #healthSummary（非 health 8 页）：渲染 <a href="/data-health"> 紧凑 chip
 *     → 显示「5/6 实时 ·1 缓存 →」，点击跳 /data-health（FastAPI 重定向到
 *     /static/data-health.html；详见 src/app/main.py::data_health_page）
 *   - #healthSummary（data-health.html）：渲染 4 个 mini-chip（数据源 / 实时 / 缓存 / 演示）
 *     → 一行展示整体健康度，summary 展开 body 后仍是 6 张市场卡详情
 *
 * 数据源：GET /api/v1/market/health（每 60 秒自动刷新；失败时 60→120→300→600s 退避）
 *
 * V0.85.0 设计要点：
 *   - 与 freshness.js 同模式（自洽模块 + CSS 自注入 + 智能退避 + i18n 安全降级）
 *   - 非 health 页 chip 是 <a>，stopPropagation 阻止冒泡到 <summary> 触发 disclosure 切换
 *   - 失败降级：保留末次摘要 + 透明度 0.55（与 freshness 的 fsh-stale 一致）
 */
(function () {
  var REFRESH_MS = 60000;
  var FETCH_TIMEOUT_MS = 30000;
  // V0.85.0 沿用 freshness.js 的智能退避（连续失败时延长轮询）
  var BACKOFF_MS = [60000, 120000, 300000, 600000];
  var _consecutiveFails = 0;
  var _lastGoodData = null;
  var _timer = null;

  // 6 数据源 status → 归类（与 data-health.html STATUS_LABELS 对齐）
  var AGG = {
    live:    { agg: "live",    color: "ok",   dot: "●" },
    realtime:{ agg: "live",    color: "ok",   dot: "●" },
    delayed: { agg: "live",    color: "ok",   dot: "●" },
    t1:      { agg: "stale",   color: "warn", dot: "◐" },
    lagged:  { agg: "stale",   color: "warn", dot: "▲" },
    cached:  { agg: "stale",   color: "warn", dot: "▲" },
    stale:   { agg: "stale",   color: "warn", dot: "▲" },
    mock:    { agg: "mock",    color: "bad",  dot: "✖" },
    unknown: { agg: "unknown", color: "dim",  dot: "○" }
  };

  // CSS 自注入（暗底 statusPanel summary 上使用）
  var CSS = [
    /* 非 health 页 chip link：紧凑、跳转 */
    "#healthSummary.hs-chip-link { display:inline-flex; align-items:center; gap:6px;",
    "  padding:3px 11px; border-radius:999px; font-size:11.5px; text-decoration:none;",
    "  background:rgba(126,226,163,.10); color:#7ee2a3;",
    "  border:1px solid rgba(126,226,163,.30); transition:background .15s, color .15s;",
    "  white-space:nowrap; flex-shrink:0; }",
    "#healthSummary.hs-chip-link:hover { background:rgba(126,226,163,.20); }",
    "#healthSummary.hs-chip-link:focus { outline:1px solid #f5d97a; outline-offset:2px; }",
    "#healthSummary .hs-title { font-weight:600; }",
    "#healthSummary .hs-dot { font-size:14px; line-height:1; }",
    "#healthSummary .hs-txt { font-variant-numeric: tabular-nums; }",
    "#healthSummary .hs-arrow { font-size:13px; opacity:.7; margin-left:2px; }",
    "#healthSummary.hs-warn { background:rgba(255,185,138,.10); color:#ffb98a;",
    "  border-color:rgba(255,185,138,.30); }",
    "#healthSummary.hs-warn:hover { background:rgba(255,185,138,.20); }",
    "#healthSummary.hs-bad { background:rgba(255,155,155,.10); color:#ff9b9b;",
    "  border-color:rgba(255,155,155,.30); }",
    "#healthSummary.hs-bad:hover { background:rgba(255,155,155,.20); }",
    "#healthSummary.hs-dim { background:rgba(154,163,173,.10); color:#9aa3ad;",
    "  border-color:rgba(154,163,173,.30); }",
    "#healthSummary.hs-dim:hover { background:rgba(154,163,173,.20); }",
    /* 失败降级透明度 */
    "#healthSummary.hs-stale { opacity:.55; }",
    /* data-health.html 4-chip panel */
    "#healthSummary.hs-panel { display:inline-flex; gap:14px; align-items:center;",
    "  flex-wrap:wrap; }",
    "#healthSummary.hs-panel .hs-mini { display:inline-flex; flex-direction:column;",
    "  align-items:center; min-width:46px; padding:0 4px; }",
    "#healthSummary.hs-panel .hs-num { font-size:18px; font-weight:700; line-height:1.1;",
    "  font-variant-numeric: tabular-nums; }",
    "#healthSummary.hs-panel .hs-lbl { font-size:10.5px; opacity:.65; margin-top:2px;",
    "  letter-spacing:.3px; }",
    "#healthSummary.hs-panel .hs-total .hs-num { color:#d6d9dd; }",
    "#healthSummary.hs-panel .hs-live .hs-num { color:#7ee2a3; }",
    "#healthSummary.hs-panel .hs-stale .hs-num { color:#ffb98a; }",
    "#healthSummary.hs-panel .hs-mock .hs-num { color:#ff9b9b; }",
    "#healthSummary.hs-panel .hs-unknown .hs-num { color:#9aa3ad; }",
    /* 高对比模式（[data-theme=hc]）：覆盖 chip/panel 配色为 黑底黄字 */
    "[data-theme=\"hc\"] #healthSummary.hs-chip-link { background:#000000; color:#ffff00;",
    "  border-color:#ffff00; }",
    "[data-theme=\"hc\"] #healthSummary.hs-warn,",
    "[data-theme=\"hc\"] #healthSummary.hs-bad,",
    "[data-theme=\"hc\"] #healthSummary.hs-dim { background:#000000; color:#ffff00;",
    "  border-color:#ffff00; }",
    "[data-theme=\"hc\"] #healthSummary.hs-panel .hs-num { color:#ffff00; }",
    "[data-theme=\"hc\"] #healthSummary.hs-panel .hs-lbl { color:#ffffff; }"
  ].join("\n");

  function _t(key, fallback) {
    try {
      if (window.I18n && typeof window.I18n.t === "function") {
        var v = window.I18n.t(key);
        if (v && v !== key) return v;
      }
    } catch (e) {}
    return fallback;
  }

  function ensureStyle() {
    if (document.getElementById("healthSummaryStyle")) return;
    var s = document.createElement("style");
    s.id = "healthSummaryStyle";
    s.textContent = CSS;
    document.head.appendChild(s);
  }

  // 聚合 6 数据源状态
  function summarize(d) {
    var sources = (d && d.sources) || {};
    var keys = Object.keys(sources);
    var total = keys.length;
    var live = 0, stale = 0, mock = 0, unknown = 0;
    keys.forEach(function (k) {
      var meta = AGG[sources[k]] || AGG.unknown;
      if (meta.agg === "live") live++;
      else if (meta.agg === "stale") stale++;
      else if (meta.agg === "mock") mock++;
      else unknown++;
    });
    var degraded = mock > 0 || stale > 0;
    var color = "hs-dim";
    if (mock > 0) color = "hs-bad";
    else if (stale > 0) color = "hs-warn";
    else if (live === total && total > 0) color = "hs-ok";
    else if (live === 0 && unknown === total) color = "hs-dim";
    else color = "hs-ok";
    return {
      total: total, live: live, stale: stale, mock: mock, unknown: unknown,
      degraded: degraded, color: color, ok: total > 0 && live === total
    };
  }

  // 非 health 页 chip link 渲染
  function renderChip(s) {
    var dot = (s.color === "hs-ok") ? "●" :
              (s.color === "hs-warn") ? "▲" :
              (s.color === "hs-bad") ? "✖" : "○";
    var colorCls = s.color; // hs-ok / hs-warn / hs-bad / hs-dim
    var inner;
    if (s.total === 0) {
      // 首次加载失败 / 接口空
      inner =
        '<span class="hs-title" data-i18n="hs.title">' + _t("hs.title", "📊 数据健康") + '</span>' +
        '<span class="hs-dot hs-dim">○</span>' +
        '<span class="hs-txt" data-i18n="hs.loading">' + _t("hs.loading", "数据加载中…") + '</span>';
      colorCls = "hs-dim";
    } else {
      var liveLabel = _t("hs.live", "实时");
      var staleLabel = _t("hs.stale", "缓存");
      var liveChip = s.live + "/" + s.total + " " + liveLabel;
      var staleChip = s.stale > 0 ? " · " + s.stale + " " + staleLabel : "";
      inner =
        '<span class="hs-title" data-i18n="hs.title">' + _t("hs.title", "📊 数据健康") + '</span>' +
        '<span class="hs-dot">' + dot + '</span>' +
        '<span class="hs-txt">' + liveChip + staleChip + '</span>' +
        '<span class="hs-arrow" aria-hidden="true">→</span>';
    }
    var staleCls = s.total === 0 ? "" : "";
    return '<a id="healthSummary" class="hs-chip-link ' + colorCls + staleCls + '"' +
           ' href="/data-health" aria-label="' + _t("hs.title", "📊 数据健康") + '">' +
           inner + '</a>';
  }

  // data-health.html 4-chip panel 渲染
  function renderPanel(s) {
    var minis = [
      { cls: "hs-total", num: s.total, lbl: _t("hs.sources", "数据源") },
      { cls: "hs-live", num: s.live, lbl: _t("hs.live", "实时") },
      { cls: "hs-stale", num: s.stale, lbl: _t("hs.stale", "缓存") },
      { cls: "hs-mock", num: s.mock, lbl: _t("hs.mock", "演示") }
    ];
    if (s.unknown > 0) {
      minis.push({ cls: "hs-unknown", num: s.unknown, lbl: _t("hs.unknown", "未知") });
    }
    var inner = minis.map(function (m) {
      return '<span class="hs-mini ' + m.cls + '">' +
               '<span class="hs-num">' + m.num + '</span>' +
               '<span class="hs-lbl" data-i18n="' + (m.cls === "hs-total" ? "hs.sources" :
                  m.cls === "hs-live" ? "hs.live" :
                  m.cls === "hs-stale" ? "hs.stale" :
                  m.cls === "hs-mock" ? "hs.mock" : "hs.unknown") + '">' + m.lbl + '</span>' +
             '</span>';
    }).join("");
    return '<span id="healthSummary" class="hs-panel" aria-live="polite" aria-atomic="false">' + inner + '</span>';
  }

  function render() {
    var mount = document.getElementById("healthSummary");
    // mount 可能是旧 <a> 或旧 <span>，或刚被外链重写 —— 用类名判断模式
    if (!mount) return;
    var s = summarize(_lastGoodData);
    var isChipMode = mount.tagName === "A" ||
      mount.classList.contains("hs-chip-link") ||
      mount.getAttribute("href") === "/data-health";
    if (isChipMode) {
      // 写入新的 <a>（替换旧节点以保证 stopPropagation 监听生效）
      var tmp = document.createElement("div");
      tmp.innerHTML = renderChip(s);
      var newChip = tmp.firstChild;
      mount.parentNode.replaceChild(newChip, mount);
      newChip.addEventListener("click", function (e) { e.stopPropagation(); });
    } else {
      // panel 模式：data-health.html 的 4-chip
      mount.outerHTML = renderPanel(s);
    }
  }

  function fetchJSON(url) {
    var ctl = typeof AbortController !== "undefined" ? new AbortController() : null;
    var timer = ctl ? setTimeout(function () { ctl.abort(); }, FETCH_TIMEOUT_MS) : null;
    return fetch(url, ctl ? { signal: ctl.signal } : undefined).then(function (r) {
      if (timer) clearTimeout(timer);
      if (!r.ok) throw new Error("HTTP " + r.status);
      return r.json();
    });
  }

  function load() {
    var mount = document.getElementById("healthSummary");
    if (!mount) return Promise.resolve();
    var base = (location.port === "8888" || location.port === "8889") ? "" : "http://127.0.0.1:8888";
    return fetchJSON(base + "/api/v1/market/health")
      .then(function (d) {
        _consecutiveFails = 0;
        _lastGoodData = d;
        render();
      })
      .catch(function () {
        // 静默降级（不红框）—— 与 V0.83 freshness.js 一致
        _consecutiveFails++;
        render();
      });
  }

  function schedule() {
    if (_timer) clearTimeout(_timer);
    var idx = Math.min(_consecutiveFails, BACKOFF_MS.length - 1);
    var wait = BACKOFF_MS[idx];
    _timer = setTimeout(function () { load().finally(schedule); }, wait);
  }

  function boot() {
    ensureStyle();
    // 首次渲染（即使失败也能展示 chip/panel 外壳）
    render();
    load().finally(schedule);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }

  window.HealthSummary = { load: load, VERSION: "0.85.0" };
})();