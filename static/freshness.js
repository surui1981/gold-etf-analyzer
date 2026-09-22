/* 全站数据时效条（UX 6.1：数据时效与语境透明）
 *
 * 在每个页面顶部展示各市场的「交易时段 + 数据时效 + 数据截止日 + 采集时间」，
 * 并在数据源降级（演示/缓存）时给出持续可见的警示角标，绝不静默。
 *
 * 用法：页面中加入 <div id="freshnessBar"></div> 并引入本脚本即可。
 * 数据源：GET /api/v1/market/freshness（每 60 秒自动刷新）
 *
 * V0.73.0 N+9：所有用户可见字符串走 I18n.t() + I18n.fmt.relative()
 */
(function () {
  var REFRESH_MS = 60000;
  var FETCH_TIMEOUT_MS = 30000;

  var LEVEL_META = {
    realtime: { cls: "fsh-ok", dot: "●" },
    delayed: { cls: "fsh-delay", dot: "◐" },
    t1: { cls: "fsh-delay", dot: "◐" },
    lagged: { cls: "fsh-warn", dot: "▲" },
    cached: { cls: "fsh-warn", dot: "▲" },
    mock: { cls: "fsh-bad", dot: "✖" },
    unknown: { cls: "fsh-dim", dot: "○" }
  };

  var CSS = [
    ".fresh-bar { display:flex; align-items:center; flex-wrap:wrap; gap:7px 12px;",
    "  background:var(--card,#fff); border:1px solid var(--border,#e5e7eb); border-radius:10px;",
    "  padding:8px 14px; margin-bottom:12px; font-size:12px; line-height:1.8; }",
    ".fresh-bar .fsh-title { font-weight:700; color:var(--muted,#6b7280); }",
    ".fresh-bar .fsh-chip { display:inline-flex; align-items:center; gap:5px; white-space:nowrap;",
    "  padding:2px 10px; border-radius:20px; border:1px solid transparent; }",
    ".fresh-bar .fsh-name { font-weight:600; }",
    ".fresh-bar .fsh-sep { opacity:.45; }",
    ".fresh-bar .fsh-meta { color:var(--muted,#6b7280); font-size:11.5px; }",
    ".fsh-ok { background:#e8f7ee; color:#1a7f37; border-color:#b7e4c7; }",
    ".fsh-delay { background:#fff8e6; color:#9a6700; border-color:#ffe0a3; }",
    ".fsh-warn { background:#fff1e6; color:#b35309; border-color:#ffd8a8; }",
    ".fsh-bad { background:#ffe9e9; color:#c92a2a; border-color:#ffc9c9; }",
    /* V0.69.0 WCAG AA: dim 角标 fg 与 muted 对齐，bg 同时提亮以保证 4.5:1 */
    ".fsh-dim { background:#e9ecef; color:var(--muted,#5b6470); border-color:#ced4da; }",
    ".fsh-alert { font-weight:700; }",
    ".fresh-bar.fsh-error { background:#ffe9e9; color:#c92a2a; border-color:#ffc9c9; }"
  ].join("\n");

  // V0.73.0 N+9: i18n helpers — 安全降级到原始字符串（i18n.js 尚未加载时）
  function _t(key, fallback) {
    try {
      if (window.I18n && typeof window.I18n.t === "function") {
        var v = window.I18n.t(key);
        // 字典缺失时 I18n.t 返回 key 字面量；保留 fallback
        if (v && v !== key) return v;
      }
    } catch (e) {}
    return fallback;
  }

  function ensureStyle() {
    if (document.getElementById("freshnessStyle")) return;
    var s = document.createElement("style");
    s.id = "freshnessStyle";
    s.textContent = CSS;
    document.head.appendChild(s);
  }

  function shortName(name) {
    return String(name || "").split("（")[0];
  }

  // V0.73.0 N+9: fmtAge 走 I18n.fmt.relative()（locale 化时间相对格式）
  function fmtAge(min) {
    if (min == null || min < 0) return "";
    var secs = Math.round(min * 60);
    if (window.I18n && typeof window.I18n.fmt.relative === "function") {
      try {
        return window.I18n.fmt.relative(secs);
      } catch (e) {}
    }
    // 降级（i18n.js 尚未加载）
    if (secs < 60) return _t("time.just_now", "刚刚");
    if (secs < 3600) return Math.round(secs / 60) + " " + _t("time.minutes_ago_unit", "分钟前").replace("{n} ", "");
    if (secs < 86400) return Math.floor(secs / 3600) + " " + _t("time.hours_ago_unit", "小时前").replace("{n} ", "");
    return Math.floor(secs / 86400) + " " + _t("time.days_ago_unit", "天前").replace("{n} ", "");
  }

  function chip(m) {
    var meta = LEVEL_META[m.freshness] || LEVEL_META.unknown;
    var tip = [
      m.name,
      _t("fresh.tip_session", "时段：") + m.session.state_label,
      _t("fresh.tip_windows", "交易时间：") + (m.session.windows || []).join(_t("fresh.sep", "；")),
      _t("fresh.tip_next", "下一时点：") + m.session.next_event,
      m.data_date ? _t("fresh.tip_data_date", "数据截止：") + m.data_date : "",
      m.note || ""
    ].filter(Boolean).join("\n");
    var parts = [
      '<span class="fsh-chip ' + meta.cls + '" title="' + tip.replace(/"/g, "") + '">',
      "<span>" + meta.dot + "</span>",
      '<span class="fsh-name">' + shortName(m.name) + "</span>",
      '<span class="fsh-sep">·</span>',
      "<span>" + m.session.state_label + "</span>",
      '<span class="fsh-sep">·</span>',
      "<span>" + m.freshness_label + "</span>"
    ];
    if (m.data_date) parts.push('<span class="fsh-meta">截止 ' + m.data_date.slice(5) + "</span>");
    var age = fmtAge(m.age_minutes);
    if (age) parts.push('<span class="fsh-meta">' + age + "</span>");
    parts.push("</span>");
    return parts.join("");
  }

  function render(d) {
    var bar = document.getElementById("freshnessBar");
    if (!bar) return;
    var order = ["ny", "sge", "etf"];
    var markets = order.map(function (k) { return d.markets && d.markets[k]; }).filter(Boolean);

    var t = new Date(d.server_time);
    var timeStr = window.I18n && typeof window.I18n.fmt.time === "function"
      ? window.I18n.fmt.time(t)
      : (String(t.getHours()).padStart(2, "0") + ":" + String(t.getMinutes()).padStart(2, "0"));

    bar.className = "fresh-bar";
    bar.innerHTML =
      '<span class="fsh-title">' + _t("fresh.title", "🕒 数据时效") + '</span>' +
      markets.map(chip).join("") +
      '<span class="fsh-meta">' + _t("fresh.local_time_suffix", "本地时间") + " " + timeStr +
      _t("fresh.refresh_hint", "（每 60 秒自动刷新）").replace("{secs}", "60") + "</span>";

    // 降级绝不静默：缓存 / 演示数据追加持续警示
    if (d.degraded) {
      var mock = markets.filter(function (m) { return m.status === "mock"; }).map(function (m) { return shortName(m.name); });
      var cached = markets.filter(function (m) { return m.status === "stale"; }).map(function (m) { return shortName(m.name); });
      var parts = [];
      if (mock.length) parts.push(mock.join("、") + " " + _t("fresh.alert_mock", "为<b>演示数据（非真实行情）</b>"));
      if (cached.length) parts.push(cached.join("、") + " " + _t("fresh.alert_cached", "为<b>缓存数据（可能过期）</b>"));
      if (parts.length) {
        bar.insertAdjacentHTML(
          "beforeend",
          '<span class="fsh-chip fsh-bad fsh-alert">' + _t("fresh.alert_icon", "⚠") + " " +
          parts.join(_t("fresh.sep", "；")) + _t("fresh.alert_suffix", "，请勿据此决策") + "</span>"
        );
      }
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
    var bar = document.getElementById("freshnessBar");
    if (!bar) return Promise.resolve();
    var base = location.port === "8888" ? "" : "http://127.0.0.1:8888";
    return fetchJSON(base + "/api/v1/market/freshness")
      .then(render)
      .catch(function (e) {
        bar.className = "fresh-bar fsh-error";
        bar.textContent = _t("fresh.load_failed", "数据时效加载失败：") + e.message +
          _t("fresh.load_failed_suffix", "（不影响页面其他数据）");
      });
  }

  function boot() {
    ensureStyle();
    load();
    setInterval(load, REFRESH_MS);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }

  window.FreshnessBar = { load: load };
})();