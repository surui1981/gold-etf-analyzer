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
  // V0.77.1 A4：本次 freshness 响应是否来自 SW 的离线缓存（非空即来自缓存，值为缓存时点）
  var swCachedAt = null;
  // V0.83.4：智能退避（连续失败时延长轮询间隔），重置条件 = 任意成功
  // 序列：60s → 120s → 300s → 600s（封顶 10min）
  var BACKOFF_MS = [60000, 120000, 300000, 600000];
  var _consecutiveFails = 0;
  var _lastGoodData = null;     // 上一次成功的响应（用于错误时降级渲染）
  var _lastGoodSig = null;      // 上次成功 sig（避免重复重渲染）
  var _timer = null;            // 持有当前 setTimeout 句柄（便于退避时重排）

  var LEVEL_META = {
    realtime: { cls: "fsh-ok", dot: "●" },
    delayed: { cls: "fsh-delay", dot: "◐" },
    t1: { cls: "fsh-delay", dot: "◐" },
    lagged: { cls: "fsh-warn", dot: "▲" },
    cached: { cls: "fsh-warn", dot: "▲" },
    mock: { cls: "fsh-bad", dot: "✖" },
    unknown: { cls: "fsh-dim", dot: "○" }
  };

  // V0.83 C2 · a11y 优化：状态签名 —— 相同状态跳过 DOM 重写，避免每 60 秒重复 announce
  // aria-live="polite" 在 innerHTML 每次重写时都会触发屏幕阅读器；相同状态时静默
  // V0.83.4 修：API 实际返回 markets 为 dict（按市场名 key），不是 array
  // 原 .map() 在 dict 上必然 TypeError，被 .catch 吞后整个 render() 静默失败
  // —— V0.83.0 起生产环境的 freshness 一直显示 stale 就是这个原因。
  // 现在 sig() 与 render() 共用同一组 order 序列，dict/array 兼容
  var lastSig = null;
  function sig(d) {
    if (!d) return "-";
    var order = ["ny", "sge", "etf"];
    var list = (d.markets && !Array.isArray(d.markets))
      ? order.map(function (k) { return d.markets[k]; }).filter(Boolean)
      : (d.markets || []);
    return (d.degraded ? "D" : "-") +
      list.map(function (m) {
        return (m && m.name ? m.name : "") + "|" +
               (m && m.freshness ? m.freshness : "?") + "|" +
               (m && m.status ? m.status : "ok");
      }).join(";");
  }

  // V0.83.4：错误状态下的降级渲染
  // - 有 _lastGoodData：在末次数据后追加「⏳ 离线/缓存」chip，不重写整个 bar
  //   （保留用户已看到的 chip 信息 + 静默标记「已过期」）
  // - 无 _lastGoodData（首次失败）：显示中性「⏳ 数据加载中…」（不红、不报错）
  function renderStale() {
    var bar = document.getElementById("freshnessBar") || document.getElementById("freshnessInline");
    if (!bar) return;
    // 去掉可能的 fsh-error class（V0.83.3 之前的红色样式）
    bar.className = bar.id === "freshnessInline" ? "fresh-inline" : "fresh-bar";

    if (_lastGoodData) {
      // 重渲染末次数据（stale 视觉：chip 半透明）
      bar.classList.add("fsh-stale");
      // 幂等：仅在「⏳ 离线/缓存」chip 不存在时追加
      if (!bar.querySelector(".fsh-stale-chip")) {
        bar.insertAdjacentHTML(
          "beforeend",
          '<span class="fsh-chip fsh-warn fsh-stale-chip">' +
            _t("fresh.stale_chip", "⏳ 离线/缓存（数据可能过期）") +
          "</span>"
        );
      }
    } else {
      // 首次失败：中性提示，不显示错误
      bar.innerHTML =
        '<span class="fsh-title fsh-loading-text">' +
          _t("fresh.loading_first", "⏳ 数据加载中…") +
        "</span>";
    }
  }

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
    ".fresh-bar.fsh-error { background:#ffe9e9; color:#c92a2a; border-color:#ffc9c9; }",
    /* V0.83：topnav 内嵌版 —— 暗底上要重写 chip 配色 + 收紧容器尺寸 */
    ".fresh-inline { display:flex; align-items:center; flex-wrap:wrap; gap:6px 10px;",
    "  font-size:11.5px; line-height:1.6; width:100%; }",
    ".fresh-inline .fsh-title { font-weight:600; color:#f5d97a; letter-spacing:.5px; }",
    ".fresh-inline .fsh-chip { display:inline-flex; align-items:center; gap:5px; white-space:nowrap;",
    "  padding:1px 9px; border-radius:20px; border:1px solid rgba(255,255,255,.12);",
    "  background:rgba(255,255,255,.06); color:#d6d9dd; }",
    ".fresh-inline .fsh-name { font-weight:600; color:#f5d97a; }",
    ".fresh-inline .fsh-sep { opacity:.35; }",
    ".fresh-inline .fsh-meta { color:#9aa3ad; font-size:11px; }",
    /* 暗底上的 5 档语义色：用半透明 + 高对比文字 */
    ".fresh-inline .fsh-ok { background:rgba(26,127,55,.18); color:#7ee2a3; border-color:rgba(126,226,163,.35); }",
    ".fresh-inline .fsh-delay { background:rgba(154,103,0,.20); color:#ffd58a; border-color:rgba(255,213,138,.35); }",
    ".fresh-inline .fsh-warn { background:rgba(179,83,9,.20); color:#ffb98a; border-color:rgba(255,185,138,.35); }",
    ".fresh-inline .fsh-bad { background:rgba(201,42,42,.22); color:#ff9b9b; border-color:rgba(255,155,155,.40); }",
    ".fresh-inline .fsh-dim { background:rgba(255,255,255,.04); color:#9aa3ad; border-color:rgba(255,255,255,.10); }",
    ".fresh-inline .fsh-alert { font-weight:700; }",
    ".fresh-inline.fsh-error { background:rgba(201,42,42,.18); color:#ff9b9b; border:1px solid rgba(255,155,155,.35); padding:4px 10px; border-radius:8px; }",
    /* V0.83.4：stale / 加载中 视觉（不红、不报错，仅降级提示） */
    ".fresh-bar.fsh-stale .fsh-chip, .fresh-inline.fsh-stale .fsh-chip { opacity:.55; }",
    ".fsh-loading-text { color:var(--muted,#6b7280); font-size:12px; padding:4px 0; }",
    ".fresh-inline .fsh-loading-text { color:#9aa3ad; }"
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
    var bar = document.getElementById("freshnessBar") || document.getElementById("freshnessInline");
    if (!bar) return;
    var order = ["ny", "sge", "etf"];
    var markets = order.map(function (k) { return d.markets && d.markets[k]; }).filter(Boolean);

    var t = new Date(d.server_time);
    var timeStr = window.I18n && typeof window.I18n.fmt.time === "function"
      ? window.I18n.fmt.time(t)
      : (String(t.getHours()).padStart(2, "0") + ":" + String(t.getMinutes()).padStart(2, "0"));

    // V0.83 C2 · 状态签名：相同状态跳过 innerHTML 重写（aria-live 静默）
    // 仍然允许挂载新增的离线缓存 chip（如果本轮新出现 swCachedAt）
    var s = sig(d);
    if (s === lastSig) {
      // 幂等挂载：仅当 chip 不存在时才追加
      if (swCachedAt && !bar.querySelector(".fsh-cached-chip")) {
        bar.insertAdjacentHTML(
          "beforeend",
          '<span class="fsh-chip fsh-bad fsh-alert fsh-cached-chip">' +
          _t("fresh.offline_cached", "⚠ 本页数据来自离线缓存（{at}），可能已过期")
            .replace("{at}", fmtCachedAt(swCachedAt)) +
          "</span>"
        );
      }
      return;
    }
    lastSig = s;

    bar.className = bar.id === "freshnessInline" ? "fresh-inline" : "fresh-bar";
    bar.innerHTML =
      '<span class="fsh-title">' + _t("fresh.title", "🕒 数据时效") + '</span>' +
      markets.map(chip).join("") +
      '<span class="fsh-meta">' + _t("fresh.local_time_suffix", "本地时间") + " " + timeStr +
      _t("fresh.refresh_hint", "（每 60 秒自动刷新）").replace("{secs}", "60") + "</span>";

    // V0.77.1 A4：离线缓存披露。置于降级警示之前 —— 它解释的是「这份时效本身从哪来」。
    // V0.83.4：fsh-bad (红) → fsh-warn (琥珀)，与「数据加载失败」红框做语义区分
    if (swCachedAt) {
      bar.insertAdjacentHTML(
        "beforeend",
        '<span class="fsh-chip fsh-warn fsh-cached-chip">' +
        _t("fresh.offline_cached", "⚠ 本页数据来自离线缓存（{at}），可能已过期")
          .replace("{at}", fmtCachedAt(swCachedAt)) +
        "</span>"
      );
    }

    // 降级绝不静默：缓存 / 演示数据追加持续警示
    if (d.degraded) {      var mock = markets.filter(function (m) { return m.status === "mock"; }).map(function (m) { return shortName(m.name); });
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
      // V0.77.1 A4：SW 网络失败回退缓存时会带 X-SW-Cached-At（真实缓存时点）。
      // 时效条是十二个页面共用的披露位，正好由它把「这份时效来自离线缓存」说出来 ——
      // 否则客户会把缓存里的旧时效当成当前时效。无此头时置空，避免上一轮的值残留。
      swCachedAt = r.headers.get("X-SW-Cached-At") || null;
      if (!r.ok) throw new Error("HTTP " + r.status);
      return r.json();
    });
  }

  function fmtCachedAt(iso) {
    var d = new Date(iso);
    if (isNaN(d.getTime())) return String(iso);
    var p = function (n) { return String(n).padStart(2, "0"); };
    return p(d.getMonth() + 1) + "-" + p(d.getDate()) + " " + p(d.getHours()) + ":" + p(d.getMinutes());
  }

  function load() {
    var bar = document.getElementById("freshnessBar") || document.getElementById("freshnessInline");
    if (!bar) return Promise.resolve();
    var base = location.port === "8888" ? "" : "http://127.0.0.1:8888";
    return fetchJSON(base + "/api/v1/market/freshness")
      .then(function (d) {
        // V0.83.4：成功 → 清理 stale 状态（即便 sig 相同也得清，否则 render 短路会留下旧 chip）
        // + 记下末次数据 + 重置退避计数
        _consecutiveFails = 0;
        bar.classList.remove("fsh-stale");
        _lastGoodData = d;
        _lastGoodSig = sig(d);
        // 强制重置 lastSig（render 内部）确保本次一定重写 DOM
        lastSig = null;
        render(d);
      })
      .catch(function (e) {
        // V0.83.4：失败 → 静默降级（不显示红框），不 console.error（已在 telemetry 可见）
        _consecutiveFails++;
        renderStale();
      });
  }

  // V0.83.4：智能退避调度 —— 替换 setInterval，改用 setTimeout 自递归
  // 成功重置为 60s；失败按 BACKOFF_MS 数组递增（封顶 600s / 10min）
  function schedule() {
    if (_timer) clearTimeout(_timer);
    var idx = Math.min(_consecutiveFails, BACKOFF_MS.length - 1);
    var wait = BACKOFF_MS[idx];
    _timer = setTimeout(function () {
      load().finally(schedule);
    }, wait);
  }

  function boot() {
    ensureStyle();
    load().finally(schedule);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }

  window.FreshnessBar = { load: load };
})();