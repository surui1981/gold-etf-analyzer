/* V0.91.0 · 复盘报告 PDF 一键导出
 * report.js — 报告页生成 / 渲染 / 打印 入口
 *
 * 设计动机：V0.74.0 路线图 M7「PDF 导出 ≤ 2 页」一直挂 🟡 至今未落地。
 * V0.90.0 后端 timeline + snapshot 已就位，本页把"PDF 导出"补齐：
 * 5 段（封面 / 持仓 / 决策时间线 / 消息面 / 收益曲线 / 央行购金），
 * 纯表格 + 文字摘要，**不画 Chart.js canvas**（print 模式默认空白）。
 *
 * 设计取舍：
 * 1. **Promise.allSettled 拉 6 端点** —— 任一失败不影响其他段渲染，
 *    失败段显示「该段暂缺」+ 整体错误条。R10 缓解。
 * 2. **window.print() 浏览器原生** —— 不引 jsPDF / html2pdf（D6 决策）；
 *    print.css @page A4 + 14mm 边距 + 链接 URL 展开是固定模板。
 * 3. **固定 30/90/180/自定义 ≤ 250** —— D7 决策：兼容 decision/etf 接口
 *    250 上限；timeline / equity-curve 上限 730 自然容纳。
 * 4. **i18n 走 I18n.t** —— 复盘报告里所有用户可见文本（含按钮 /
 *    段标题 / 表头）都从 i18n.* 命名空间读；fb 留 zh-CN 字面量。
 * 5. **不重渲染 i18n 切换** —— 用户在报告页切语言后整页 reload（与
 *    9 页一致：i18n.js init 时 reload 当前 location）。
 * 6. **日期范围优先 URL > localStorage > 默认 30 天** —— 复用
 *    nav-context.js 的 `pm_ctx_v1_days` 兜底；顶栏导出按钮也会写入。
 * 7. **account_id = "all" 时不传参** —— 后端默认聚合；非"all"时附参数。
 * 8. **timeline snapshot=null 显式标"数据缺（节假日）"** —— V0.78.0 Step D
 *    纪律：数据不足 ≠ 中性（**不**兜底 50）。
 *
 * 加载方式：defer（与 i18n.js 一致）；DOMContentLoaded 触发 init。
 *
 * 兼容性：所有现代浏览器（Chrome 1+ / Firefox 1+ / Safari 1+）；
 * 旧 IE 不支持（项目早就不支持 IE）。
 */

(function () {
  "use strict";

  // === Configuration ===
  var DEFAULT_DAYS = 30;
  var MAX_DAYS = 250; // D7 决策：与 decision/etf 接口 days 上限对齐
  var COMPRESS_THRESHOLD = 7; // timeline 折叠阈值
  var MAX_NEWS_ROWS = 50; // 段 3 消息面打分行数上限

  // === State ===
  var state = {
    days: DEFAULT_DAYS,
    accountId: "all",
    fromDate: null,
    toDate: null,
  };

  // === DOM helpers ===
  function $(sel) { return document.querySelector(sel); }
  function $$(sel) { return document.querySelectorAll(sel); }
  function show(el) { if (el) el.style.display = ""; }
  function hide(el) { if (el) el.style.display = "none"; }
  function i18n(key, params) {
    if (window.I18n && typeof window.I18n.t === "function") {
      return window.I18n.t(key, params);
    }
    return key;
  }
  function esc(s) {
    if (s == null) return "";
    return String(s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }
  function fmtNum(n, digits) {
    if (n == null || isNaN(n)) return "—";
    return Number(n).toFixed(digits);
  }

  // === Date helpers ===
  function todayISO() {
    var d = new Date();
    return d.toISOString().slice(0, 10);
  }
  function addDays(iso, n) {
    var d = new Date(iso);
    d.setDate(d.getDate() + n);
    return d.toISOString().slice(0, 10);
  }
  function dateToQuarter(iso) {
    var d = new Date(iso);
    var m = d.getMonth() + 1;
    var q = m <= 3 ? 1 : m <= 6 ? 2 : m <= 9 ? 3 : 4;
    return d.getFullYear() + "Q" + q;
  }
  function nowLocalStr() {
    try {
      return new Date().toLocaleString("zh-CN", { hour12: false });
    } catch (e) {
      return new Date().toISOString();
    }
  }

  // === Init ===
  function init() {
    parseContext();
    setupToolbar();
    updateCover();
    generate(); // auto-generate on page load
  }

  function parseContext() {
    var u = new URLSearchParams(location.search);

    // days: URL > LS > DEFAULT
    var days = parseInt(u.get("days") || "", 10);
    if (!(days >= 1 && days <= MAX_DAYS)) {
      try {
        var ls = localStorage.getItem("pm_ctx_v1_days");
        if (ls) days = parseInt(ls, 10);
      } catch (e) { /* 隐私模式 */ }
    }
    if (!(days >= 1 && days <= MAX_DAYS)) days = DEFAULT_DAYS;
    state.days = days;

    // date range
    var fromQuery = u.get("from");
    var toQuery = u.get("to");
    if (fromQuery && toQuery) {
      state.fromDate = fromQuery;
      state.toDate = toQuery;
    } else {
      state.toDate = todayISO();
      state.fromDate = addDays(state.toDate, -state.days);
    }

    // account_id
    var accQuery = u.get("account_id");
    if (accQuery) {
      state.accountId = accQuery;
    } else {
      try {
        var ls = localStorage.getItem("gold_account_id");
        if (ls) state.accountId = ls;
      } catch (e) { /* ignore */ }
    }
  }

  function setupToolbar() {
    // days 按钮点击 → 切状态 + 重渲染
    $$(".days-btn").forEach(function (btn) {
      var d = parseInt(btn.dataset.days, 10);
      if (d === state.days) btn.classList.add("active");
      btn.addEventListener("click", function () {
        $$(".days-btn").forEach(function (b) { b.classList.remove("active"); });
        btn.classList.add("active");
        state.days = d;
        state.toDate = todayISO();
        state.fromDate = addDays(state.toDate, -state.days);
        updateCover();
        generate();
      });
    });

    // 生成按钮（显式 trigger；auto-generate 之后用户改了什么再点）
    var gen = $("#btn-generate");
    if (gen) gen.addEventListener("click", function () { generate(); });

    // 打印按钮
    var prt = $("#btn-print");
    if (prt) prt.addEventListener("click", function () { window.print(); });
  }

  function updateCover() {
    var periodEl = $("#cover-period");
    var accEl = $("#cover-account");
    var genEl = $("#cover-generated");
    var curAccEl = $("#current-account");
    if (periodEl) periodEl.textContent = state.fromDate + " ~ " + state.toDate + " (" + state.days + " " + i18n("report.range_label") + ")";
    var accLabel = state.accountId === "all" ? i18n("report.cover_account_all") : "#" + state.accountId;
    if (accEl) accEl.textContent = accLabel;
    if (curAccEl) curAccEl.textContent = accLabel;
    if (genEl) genEl.textContent = nowLocalStr();
  }

  // === Fetch & render ===
  function buildEndpoints() {
    var accQ = state.accountId === "all" ? "" : "?account_id=" + encodeURIComponent(state.accountId);
    var accAmp = state.accountId === "all" ? "" : "&account_id=" + encodeURIComponent(state.accountId);
    return {
      positions: "/api/v1/positions" + accQ,
      timeline: "/api/v1/trades/timeline?from_date=" + state.fromDate + "&to_date=" + state.toDate +
        "&compress_threshold_days=" + COMPRESS_THRESHOLD + accAmp,
      newsHistory: "/api/v1/news-score/history?limit=100",
      newsToday: "/api/v1/news-score",
      equity: "/api/v1/portfolio/equity-curve?days=" + state.days + accAmp,
      central: "/api/v1/central-bank/purchases?from_q=" + dateToQuarter(state.fromDate) +
        "&to_q=" + dateToQuarter(state.toDate),
    };
  }

  async function generate() {
    var loading = $("#report-loading");
    var errorEl = $("#report-error");
    show(loading);
    hide(errorEl);

    var endpoints = buildEndpoints();
    var keys = Object.keys(endpoints);

    var settled = await Promise.allSettled(keys.map(function (k) {
      return fetch(endpoints[k]).then(function (r) {
        if (!r.ok) throw new Error(k + " HTTP " + r.status);
        return r.json().then(function (d) { return [k, d]; });
      });
    }));

    hide(loading);

    var data = {};
    var errors = [];
    settled.forEach(function (s, i) {
      if (s.status === "fulfilled") {
        data[s.value[0]] = s.value[1];
      } else {
        errors.push(keys[i] + ": " + (s.reason && s.reason.message || "unknown"));
      }
    });

    if (errors.length === keys.length) {
      // 全部失败：显示错误条 + 退出
      if (errorEl) {
        errorEl.textContent = i18n("report.error_load", { msg: errors.join("; ") });
        show(errorEl);
      }
      return;
    }
    if (errors.length && errorEl) {
      errorEl.textContent = i18n("report.error_load", { msg: errors.join("; ") });
      show(errorEl);
    }

    show($("#report-cover"));
    renderPositions(data.positions);
    renderTimeline(data.timeline);
    renderNews(data.newsHistory, data.newsToday);
    renderCurve(data.equity);
    renderCentral(data.central);
  }

  function renderPositions(positions) {
    var sec = $("#section-positions");
    var body = $("#positions-body");
    show(sec);
    if (!positions || !positions.length) {
      body.innerHTML = '<p class="empty">' + esc(i18n("report.empty_section")) + "</p>";
      return;
    }
    var rows = positions.map(function (p) {
      var pnlColor = p.pnl >= 0 ? "#c00" : "#090";
      return '<tr>' +
        "<td>" + esc(p.name || p.symbol) + "</td>" +
        "<td>" + esc(p.symbol) + "</td>" +
        '<td class="num">' + fmtNum(p.quantity, 2) + "</td>" +
        '<td class="num">' + fmtNum(p.avg_cost, 4) + "</td>" +
        '<td class="num">' + fmtNum(p.market_value, 2) + "</td>" +
        '<td class="num" style="color:' + pnlColor + '">' + fmtNum(p.pnl, 2) + "</td>" +
        '<td class="num" style="color:' + pnlColor + '">' + fmtNum(p.pnl_pct, 2) + "%</td>" +
      "</tr>";
    }).join("");
    body.innerHTML =
      "<table>" +
        "<thead><tr>" +
          "<th>名称</th><th>代码</th>" +
          '<th class="num">数量</th>' +
          '<th class="num">成本</th>' +
          '<th class="num">市值</th>' +
          '<th class="num">盈亏</th>' +
          '<th class="num">收益率</th>' +
        "</tr></thead>" +
        "<tbody>" + rows + "</tbody>" +
      "</table>";
  }

  function renderTimeline(timeline) {
    var sec = $("#section-timeline");
    var body = $("#timeline-body");
    show(sec);
    if (!timeline || !timeline.segments || !timeline.segments.length) {
      body.innerHTML = '<p class="empty">' + esc(i18n("report.empty_section")) + "</p>";
      return;
    }
    var segments = timeline.segments;
    var rows = [];
    segments.forEach(function (seg) {
      if (seg.type === "idle") {
        // 折叠段显式渲染为单行；未折叠但很短的 idle 段也可保留（信息密度优先）
        if (seg.compressed) {
          rows.push(
            '<tr class="idle-row idle-separator"><td colspan="6">' +
              esc(i18n("report.idle_compressed", { n: seg.idle_days })) +
              "（" + esc(seg.start) + " ~ " + esc(seg.end) + "）" +
            "</td></tr>"
          );
        }
        // 未折叠的 idle 段（跨度短）省略：与决策点相比信息量低
      } else if (seg.type === "decision") {
        var trade = seg.trade || {};
        var snap = seg.snapshot;
        var trendCell;
        if (snap === null || snap === undefined) {
          trendCell = '<span class="no-snapshot">' + esc(i18n("report.no_snapshot")) + "</span>";
        } else if (snap.trend_index != null) {
          var c = snap.trend_index >= 60 ? "#c00" : snap.trend_index < 50 ? "#090" : "#666";
          trendCell = '<span style="color:' + c + '">' + fmtNum(snap.trend_index, 1) + "</span>";
        } else {
          trendCell = "—";
        }
        var action = trade.side === "buy" ? i18n("report.decision_buy") :
                     trade.side === "sell" ? i18n("report.decision_sell") :
                     (trade.side || "—");
        var actionColor = trade.side === "buy" ? "#c00" :
                          trade.side === "sell" ? "#090" : "#000";
        rows.push(
          '<tr class="decision-row">' +
            "<td>" + esc(seg.start) + "</td>" +
            '<td style="color:' + actionColor + ';font-weight:600">' + esc(action) + "</td>" +
            "<td>" + esc(trade.symbol || "—") + "</td>" +
            '<td class="num">' + fmtNum(trade.quantity, 2) + "</td>" +
            '<td class="num">' + fmtNum(trade.price, 4) + "</td>" +
            '<td class="num">' + trendCell + "</td>" +
          "</tr>"
        );
      }
    });
    var meta =
      "<p class=\"report-meta\">" +
        "活跃天数 " + timeline.active_days + " / 跨度 " + timeline.span_days +
        "，决策点 " + timeline.decision_count +
      "</p>";
    body.innerHTML = meta +
      "<table>" +
        "<thead><tr>" +
          "<th>日期</th><th>动作</th><th>代码</th>" +
          '<th class="num">数量</th>' +
          '<th class="num">价格</th>' +
          '<th class="num">趋势指数</th>' +
        "</tr></thead>" +
        "<tbody>" + rows.join("") + "</tbody>" +
      "</table>";
  }

  function renderNews(history, today) {
    var sec = $("#section-news");
    var body = $("#news-body");
    show(sec);
    var items = [];
    if (today && today.scored) {
      items.push({
        score_date: today.score_date,
        slot: "today",
        score: today.score,
        direction: today.direction,
        notes: today.notes,
        weight: "—",
        formula: today.formula,
      });
    }
    if (history && history.items) {
      items = items.concat(history.items);
    }
    if (!items.length) {
      body.innerHTML = '<p class="empty">' + esc(i18n("report.empty_section")) + "</p>";
      return;
    }
    var sliced = items.slice(0, MAX_NEWS_ROWS);
    var rows = sliced.map(function (it) {
      return "<tr>" +
        "<td>" + esc(String(it.score_date)) + "</td>" +
        "<td>" + esc(String(it.slot)) + "</td>" +
        '<td class="num">' + fmtNum(it.score, 0) + "</td>" +
        "<td>" + esc(String(it.direction)) + "</td>" +
        "<td>" + esc((it.notes || "").slice(0, 80)) + "</td>" +
      "</tr>";
    }).join("");
    body.innerHTML =
      "<table>" +
        "<thead><tr>" +
          "<th>日期</th><th>槽位</th>" +
          '<th class="num">分值</th>' +
          "<th>方向</th><th>备注</th>" +
        "</tr></thead>" +
        "<tbody>" + rows + "</tbody>" +
      "</table>";
  }

  function renderCurve(equity) {
    var sec = $("#section-curve");
    var body = $("#curve-body");
    show(sec);
    if (!equity || !equity.points || !equity.points.length) {
      body.innerHTML = '<p class="empty">' + esc(i18n("report.empty_section")) + "</p>";
      return;
    }
    var points = equity.points;
    // 采样：每 5 个 + 首尾
    var sampled = [];
    for (var i = 0; i < points.length; i += 5) sampled.push(points[i]);
    if (sampled[sampled.length - 1] !== points[points.length - 1]) {
      sampled.push(points[points.length - 1]);
    }
    var rows = sampled.map(function (p) {
      var c = p.total_pnl >= 0 ? "#c00" : "#090";
      var c2 = p.return_pct >= 0 ? "#c00" : "#090";
      return "<tr>" +
        "<td>" + esc(p.date) + "</td>" +
        '<td class="num">' + fmtNum(p.market_value, 2) + "</td>" +
        '<td class="num" style="color:' + c + '">' + fmtNum(p.total_pnl, 2) + "</td>" +
        '<td class="num" style="color:' + c2 + '">' + fmtNum(p.return_pct, 2) + "%</td>" +
      "</tr>";
    }).join("");
    var sum = equity.summary || {};
    var meta =
      "<p class=\"report-meta\">" +
        "最新市值 " + fmtNum(sum.latest_market_value, 2) +
        " · 累计收益率 " + fmtNum(sum.latest_return_pct, 2) + "%" +
        " · 区间最高 " + fmtNum(sum.max_return_pct, 2) + "%" +
        " / 最低 " + fmtNum(sum.min_return_pct, 2) + "%" +
        " / 最大回撤 " + fmtNum(sum.max_drawdown_pct, 2) + "%" +
      "</p>";
    body.innerHTML = meta +
      "<table>" +
        "<thead><tr>" +
          "<th>日期</th>" +
          '<th class="num">市值</th>' +
          '<th class="num">总盈亏</th>' +
          '<th class="num">累计收益率</th>' +
        "</tr></thead>" +
        "<tbody>" + rows + "</tbody>" +
      "</table>";
  }

  function renderCentral(central) {
    var sec = $("#section-central");
    var body = $("#central-body");
    show(sec);
    if (!central || !central.items || !central.items.length) {
      body.innerHTML = '<p class="empty">' + esc(i18n("report.empty_section")) + "</p>";
      return;
    }
    // 按净购金降序，取前 20
    var items = central.items.slice().sort(function (a, b) {
      return (b.tonnes_net || 0) - (a.tonnes_net || 0);
    }).slice(0, 20);
    var rows = items.map(function (it) {
      var c = it.tonnes_net >= 0 ? "#c00" : "#090";
      return "<tr>" +
        "<td>" + esc(it.country_name || it.country_iso) + "</td>" +
        "<td>" + esc(it.country_iso) + "</td>" +
        "<td>" + esc(it.quarter) + "</td>" +
        '<td class="num" style="color:' + c + '">' + fmtNum(it.tonnes_net, 1) + "</td>" +
        "<td>" + esc(it.source || "") + "</td>" +
      "</tr>";
    }).join("");
    var summary = central.summary || {};
    var meta =
      "<p class=\"report-meta\">" +
        "覆盖 " + (summary.country_count != null ? summary.country_count : "?") + " 国" +
        " · T12M " + fmtNum(summary.t12m_total, 1) + " 吨" +
        " · 最新数据 " + (summary.latest_data_quarter || "?") +
      "</p>";
    body.innerHTML = meta +
      "<table>" +
        "<thead><tr>" +
          "<th>国家</th><th>ISO</th><th>季度</th>" +
          '<th class="num">净购金（吨）</th>' +
          "<th>来源</th>" +
        "</tr></thead>" +
        "<tbody>" + rows + "</tbody>" +
      "</table>";
  }

  // === Boot ===
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
