// V0.99 C4 · silver.html 内联 JS 抽出
// 入口：DOMContentLoaded → init() → 拉取 3 套数据 + 渲染
// 模块边界：
//   - init()           总编排
//   - loadTrend()      主图（K 线 + 趋势评估指数 + 指标 + 摘要）
//   - loadCards()      实时报价卡（ETF + NY；C5 扩为 3 market）
//   - loadCompare()    对照（ETF vs NY 涨跌幅 + 表格 + 归一化曲线）
//   - renderMain()     主图绘制
//   - renderCompareChart() 对照曲线绘制
//   - renderSourceBar() 数据源健康条
//   - loadAlerts()     强信号横幅
//   - bindRangeButtons() / bindRefresh() 交互
//   - 共振卡 / 健康摘要 chip 挂载（保留 V0.85.0 模式）

(function () {
  "use strict";

  const API_BASE = location.port === "8888" ? "" : "http://127.0.0.1:8888";

  // 状态：避免在 3 个 render 函数间共享
  let trendChart = null;
  let lastTrend = null;
  let currentKlineInterval = "D";

  const INTERVAL_SUB = {
    D: "日 K · 60 个交易日",
    W: "周 K · 聚合至 ISO 周界（52 周 ≈ 1 交易年）",
    M: "月 K · 聚合至年月界（24 月 ≈ 2 交易年）",
  };

  async function fetchJSON(url, timeoutMs = 40000) {
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), timeoutMs);
    try {
      const resp = await fetch(url, { signal: ctrl.signal });
      if (!resp.ok) throw new Error("HTTP " + resp.status);
      return await resp.json();
    } finally {
      clearTimeout(timer);
    }
  }

  /* V0.77.1 A2：取数失败要说清楚，并放在首屏看得见的地方。 */
  function hideLoadBar() {
    const bar = document.getElementById("loadBar");
    if (bar) bar.style.display = "none";
  }

  function showTrendError(e) {
    hideLoadBar();
    const advice =
      "白银价格数据加载失败。可能是数据源暂时不可用或网络中断 —— " +
      "本页其余模块不受影响，请稍后点右上角 🔄 重试。";
    const alertBar = document.getElementById("alertBar");
    if (alertBar) alertBar.innerHTML = '<div class="source-bar source-bad">⚠️ ' + advice + "</div>";
    const area = document.getElementById("chartArea");
    if (area) area.innerHTML = '<div class="error">趋势图暂不可用，重试后自动恢复。</div>';
    if (window.console && console.warn) console.warn("silver trend load failed:", e);
  }

  async function loadTrend(days = 60, interval = "D") {
    currentKlineInterval = interval;
    document.getElementById("trendSub").textContent = INTERVAL_SUB[interval] || INTERVAL_SUB.D;
    try {
      const data = await fetchJSON(
        API_BASE + `/api/v1/market/silver/trend?days=${days}&interval=${interval}`
      );
      lastTrend = data;
      renderSourceBar(data);
      renderMain(data);
      loadAlerts();
    } catch (e) {
      showTrendError(e);
    } finally {
      hideLoadBar();
    }
  }

  async function loadCards() {
    try {
      const [etf, ny] = await Promise.all([
        fetchJSON(API_BASE + "/api/v1/market/silver/etf-quote"),
        fetchJSON(API_BASE + "/api/v1/market/silver/quote"),
      ]);
      const items = [
        {
          label: "白银 ETF 562800",
          value: etf.price.toFixed(3) + " 元/份",
          extra: (etf.change_pct >= 0 ? "+" : "") + etf.change_pct.toFixed(2) + "%",
          color: etf.change_pct >= 0 ? "up" : "down",
        },
        {
          label: "纽约白银 SI",
          value: ny.price_usd.toFixed(2) + " 美元/盎司",
          extra: (ny.change_pct >= 0 ? "+" : "") + ny.change_pct.toFixed(2) + "%",
          color: ny.change_pct >= 0 ? "up" : "down",
        },
        {
          label: "数据源",
          value: etf.unit || "场内",
          extra: "ETF+NY 同步",
        },
        {
          label: "评估指数",
          value: (lastTrend?.index?.score?.toFixed(1) ?? "--") + " / 100",
          extra: lastTrend?.index?.level ?? "--",
        },
      ];
      document.getElementById("cards").innerHTML = items
        .map(
          (i) => `
      <div class="card">
        <div class="label">${i.label}</div>
        <div class="value ${i.color || ""}">${i.value}</div>
        <div class="extra">${i.extra}</div>
      </div>`
        )
        .join("");
    } catch (e) {
      document.getElementById("cards").innerHTML =
        '<div class="card"><div class="label">报价</div><div class="value">加载失败</div><div class="extra">' +
        e.message +
        "</div></div>";
    }
  }

  async function loadCompare() {
    try {
      const data = await fetchJSON(API_BASE + "/api/v1/market/silver/compare?days=60");
      document.getElementById("cmpSub").textContent =
        `近 ${data.days} 日 · 领先 ${data.lead_gap?.toFixed(2) ?? "--"} 百分点`;
      const cards = [
        {
          label: "白银 ETF",
          value: data.silver_etf?.change_pct?.toFixed(2) + "%",
          color: (data.silver_etf?.change_pct ?? 0) >= 0 ? "up" : "down",
        },
        {
          label: "纽约白银",
          value: data.silver_ny?.change_pct?.toFixed(2) + "%",
          color: (data.silver_ny?.change_pct ?? 0) >= 0 ? "up" : "down",
        },
        {
          label: "领先者",
          value: data.leader === "tie" ? "持平" : data.leader === "silver_etf" ? "白银 ETF" : "纽约白银",
        },
        { label: "差距", value: (data.lead_gap >= 0 ? "+" : "") + data.lead_gap?.toFixed(2) + " pp" },
      ];
      document.getElementById("cmpCards").innerHTML = cards
        .map(
          (c) => `
      <div class="card"><div class="label">${c.label}</div><div class="value ${c.color || ""}">${c.value}</div></div>`
        )
        .join("");
      document.getElementById("cmpTable").innerHTML = `
      <tr style="background:var(--card)"><th style="padding:8px;text-align:left">指标</th><th style="padding:8px;text-align:right">白银 ETF</th><th style="padding:8px;text-align:right">纽约白银</th></tr>
      <tr><td style="padding:6px">起始价</td><td style="padding:6px;text-align:right">${data.silver_etf?.start_price?.toFixed(3)}</td><td style="padding:6px;text-align:right">${data.silver_ny?.start_price?.toFixed(2)}</td></tr>
      <tr><td style="padding:6px">最新价</td><td style="padding:6px;text-align:right">${data.silver_etf?.end_price?.toFixed(3)}</td><td style="padding:6px;text-align:right">${data.silver_ny?.end_price?.toFixed(2)}</td></tr>
      <tr><td style="padding:6px">区间最高</td><td style="padding:6px;text-align:right">${data.silver_etf?.high?.toFixed(3)}</td><td style="padding:6px;text-align:right">${data.silver_ny?.high?.toFixed(2)}</td></tr>
      <tr><td style="padding:6px">区间最低</td><td style="padding:6px;text-align:right">${data.silver_etf?.low?.toFixed(3)}</td><td style="padding:6px;text-align:right">${data.silver_ny?.low?.toFixed(2)}</td></tr>
    `;
      renderCompareChart(data);
      document.getElementById("cmpSummary").textContent = data.summary || "";
    } catch (e) {
      document.getElementById("cmpCards").innerHTML =
        '<div class="card"><div class="label">对照</div><div class="value">加载失败</div><div class="extra">' +
        e.message +
        "</div></div>";
    }
  }

  function renderCompareChart(data) {
    const canvas = document.getElementById("compareChart");
    if (!canvas || !data.points) return;
    const labels = data.points.map((p) => p.date);
    const ctx = canvas.getContext("2d");
    if (window.silverCmpChart) {
      window.silverCmpChart.destroy();
      window.silverCmpChart = null;
    }
    window.silverCmpChart = new Chart(ctx, {
      type: "line",
      data: {
        labels,
        datasets: [
          {
            label: "白银 ETF（归一化）",
            data: data.points.map((p) => p.silver_etf),
            borderColor: "#1d4ed8",
            backgroundColor: "rgba(29,78,216,0.1)",
            tension: 0.25,
          },
          {
            label: "纽约白银（归一化）",
            data: data.points.map((p) => p.silver_ny),
            borderColor: "#0e7490",
            backgroundColor: "rgba(14,116,144,0.1)",
            tension: 0.25,
          },
        ],
      },
      options: { responsive: true, plugins: { legend: { position: "top" } }, scales: { y: { beginAtZero: false } } },
    });
    ChartA11y.wrapChart(canvas, {
      label: "白银 ETF 与纽约白银归一化对照（近 " + labels.length + " 个交易日）",
    });
  }

  function renderSourceBar(data) {
    const bar = document.getElementById("sourceBar");
    const ds = data.data_sources || {};
    const live = Object.values(ds).filter((v) => v === "live").length;
    const mock = Object.values(ds).filter((v) => v === "mock").length;
    if (mock === 0) {
      bar.className = "source-bar source-ok";
      bar.textContent = `✅ 全部数据源实时（${live} 个源：白银 ETF 562800 + COMEX SI 期货 + 黄金宏观因子）`;
    } else if (live > 0) {
      bar.className = "source-bar source-warn";
      bar.textContent = `⚠️ 部分数据源降级为演示数据（${mock} mock / ${live} live）：${Object.entries(ds)
        .filter(([, v]) => v === "mock")
        .map(([k]) => k)
        .join(" / ")}`;
    } else {
      bar.className = "source-bar source-bad";
      bar.textContent = `❌ 全部数据源降级为演示数据，请检查网络`;
    }
    bar.style.display = "block";
  }

  function loadAlerts() {
    const el = document.getElementById("alertBar");
    if (!lastTrend) return;
    const lvl = lastTrend.index?.level || "";
    const score = lastTrend.index?.score ?? 0;
    let html = "";
    if (lvl === "strong_up")
      html = `<div class="source-bar source-ok">⚡ 白银指数 ${score.toFixed(1)} 强势上升 · 关注参数共振</div>`;
    else if (lvl === "strong_down")
      html = `<div class="source-bar source-bad">⚡ 白银指数 ${score.toFixed(1)} 弱势下降 · 警惕下行风险</div>`;
    el.innerHTML = html;
  }

  function renderMain(data) {
    const lvl = data.index?.level || "—";
    const numEl = document.getElementById("idxNum");
    numEl.textContent = data.index?.score?.toFixed(1) ?? "--";
    numEl.className = "num " + (data.index?.score >= 60 ? "up" : data.index?.score <= 40 ? "down" : "");

    const badge = document.getElementById("idxBadge");
    const lvlMap = { strong_up: "强势上升", up: "上升", sideways: "震荡整理", down: "下降", strong_down: "弱势下降" };
    const colorMap = { strong_up: "#1a7f37", up: "#1a7f37", sideways: "#946300", down: "#c92a2a", strong_down: "#c92a2a" };
    if (lvl && lvlMap[lvl]) {
      badge.textContent = lvlMap[lvl];
      badge.style.background = colorMap[lvl] || "#888";
      badge.style.display = "inline-block";
    } else {
      badge.style.display = "none";
    }

    document.getElementById("idxSummary").innerHTML = data.index?.summary || "";
    document.getElementById("snapTime").textContent = "快照于 " + (data.served_at || "").slice(0, 16).replace("T", " ");

    // V0.79.0 Step E：动态/静态阈值角标（先算）
    const macro = data.macro || {};
    const macroDynamic = macro.macro_dynamic === true;
    const macroBadgeBg = macroDynamic ? "#e8f7ee" : "#e9ecef";
    const macroBadgeColor = macroDynamic ? "var(--up)" : "var(--muted)";
    const macroBadgeText =
      window.I18n && typeof window.I18n.t === "function"
        ? window.I18n.t(macroDynamic ? "trend.macro_dynamic_badge" : "trend.macro_static_badge")
        : macroDynamic
        ? "[动态]"
        : "[静态]";
    const macroBadgeHint = macroDynamic
      ? "5 因子中 ≥4 使用近 252 日滚动 90/10 分位"
      : "数据不足，阈值回退 hardcode 默认";
    const macroBadge = `<span class="src" style="margin-left:6px;padding:1px 6px;border-radius:8px;background:${macroBadgeBg};color:${macroBadgeColor};font-size:10px;font-weight:500" title="${macroBadgeHint}">${macroBadgeText}</span>`;

    // V0.79.0 Step F：技术面合成方式角标（再算，idxMethod 用到）
    const techComposed = data.tech_composed_by === "weighted" ? "weighted" : "grouped";
    const techBadgeBg = techComposed === "grouped" ? "#e8f7ee" : "#fff4e5";
    const techBadgeColor = techComposed === "grouped" ? "var(--up)" : "var(--muted)";
    const techBadgeText =
      window.I18n && typeof window.I18n.t === "function"
        ? window.I18n.t(techComposed === "grouped" ? "trend.tech_grouped_badge" : "trend.tech_weighted_badge")
        : techComposed === "grouped"
        ? "[组内平均]"
        : "[单维度加权]";
    const techComposeBadge = `<span class="src" style="margin-left:6px;padding:1px 6px;border-radius:8px;background:${techBadgeBg};color:${techBadgeColor};font-size:10px;font-weight:500">${techBadgeText}</span>`;

    document.getElementById("idxMethod").innerHTML = (data.index?.method || "") + techComposeBadge;
    document.getElementById("macroInfo").innerHTML = macro.score != null ? `综合 ${macro.score?.toFixed(1)} / 100${macroBadge}` : "";
    const macroFactorsEl = document.getElementById("macroFactors");
    macroFactorsEl.innerHTML = (macro.factors || [])
      .map(
        (f) => `
    <div class="macro-row">
      <span class="nm">${f.name}</span>
      <span class="val">${f.value?.toFixed ? f.value.toFixed(2) : f.value} ${f.unit || ""}</span>
      <span class="bar"><i style="width:${Math.max(0, Math.min(100, f.score || 0))}%; background:${(f.score || 0) >= 55 ? "var(--up)" : (f.score || 0) <= 45 ? "var(--down)" : "#946300"}"></i></span>
      <span class="dt">${f.score?.toFixed(0) ?? "--"}</span>
    </div>
  `
      )
      .join("");

    const news = data.news || {};
    document.getElementById("newsInfo").textContent = news.score != null ? `综合 ${news.score?.toFixed(1)} / 100` : "";
    document.getElementById("newsFactor").innerHTML = news.summary || (news.scored ? `已打分 ${news.score}` : "未打分 · 按 50 中性");

    document.getElementById("indicators").innerHTML = (data.indicators || [])
      .map((i) => {
        const miss = i.score == null;
        const col = miss ? "var(--muted)" : i.score >= 55 ? "var(--up)" : i.score <= 45 ? "var(--down)" : "#946300";
        const sub = miss ? (i.reason || "数据不足") + "（其余维度已按有效权重归一化）" : i.detail || "";
        return `
    <div class="ind-row"${miss ? ' data-insufficient="1" style="opacity:.75"' : ""}>
      <div class="ind-head">
        <span class="nm">${i.name}</span>
        <span class="vl">${i.value ?? "—"}</span>
        <span class="sc" style="color:${col}">${miss ? "—" : i.score.toFixed(0)}</span>
      </div>
      <div class="ind-sub">${sub}</div>
      <div class="bar"><i style="width:${miss ? 0 : Math.max(0, Math.min(100, i.score))}%; background:${col}"></i></div>
    </div>
  `;
      })
      .join("");

    document.getElementById(
      "subtitle"
    ).textContent = `区间 ${data.metrics?.start_date} ~ ${data.metrics?.end_date}（${data.metrics?.trading_days ?? "—"} 个交易日）`;

    document.getElementById("loadBar").style.display = "none";

    // 主图
    const labels = data.points.map((p) => p.date);
    const closes = data.points.map((p) => p.close);
    const ma5 = data.points.map((p) => p.ma5);
    const ma20 = data.points.map((p) => p.ma20);
    const ma40 = data.points.map((p) => p.ma40);

    const area = document.getElementById("chartArea");
    area.innerHTML = '<canvas id="trendCanvas"></canvas>';
    const canvas = document.getElementById("trendCanvas");
    const ctx = canvas.getContext("2d");

    const badge2 = document.createElement("div");
    badge2.className =
      "data-badge db-" + (data.freshness?.level === "live" ? "ok" : data.freshness?.level === "stale" ? "warn" : "dim");
    badge2.textContent = data.freshness?.label || data.freshness?.level || "live";
    area.appendChild(badge2);

    if (trendChart) {
      trendChart.destroy();
      trendChart = null;
    }
    trendChart = new Chart(ctx, {
      type: "line",
      data: {
        labels,
        datasets: [
          { label: data.name || "白银", data: closes, borderColor: "#1d4ed8", backgroundColor: "rgba(29,78,216,0.1)", tension: 0.2, fill: false, pointRadius: 0 },
          { label: "MA5", data: ma5, borderColor: "#f59f00", borderDash: [4, 4], tension: 0, fill: false, pointRadius: 0 },
          { label: "MA20", data: ma20, borderColor: "#946300", borderDash: [4, 4], tension: 0, fill: false, pointRadius: 0 },
          { label: "MA40", data: ma40, borderColor: "#c92a2a", borderDash: [4, 4], tension: 0, fill: false, pointRadius: 0 },
        ],
      },
      options: {
        responsive: true,
        plugins: { legend: { position: "top" } },
        scales: { y: { beginAtZero: false } },
      },
    });
    ChartA11y.wrapChart(canvas, {
      label: "白银趋势主图（收盘价 + MA5/MA20/MA40，近 " + labels.length + " 个交易日）",
    });

    document.getElementById("summary").innerHTML = data.metrics?.summary || "";
  }

  function bindRangeButtons() {
    const wrap = document.getElementById("klineRangeBtns");
    if (!wrap) return;
    wrap.addEventListener("click", (e) => {
      const btn = e.target.closest(".range-btn");
      if (!btn) return;
      document.querySelectorAll("#klineRangeBtns .range-btn").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      loadTrend(parseInt(btn.dataset.days, 10), btn.dataset.interval);
    });
  }

  function bindRefresh() {
    const btn = document.getElementById("refreshBtn");
    if (!btn) return;
    btn.addEventListener("click", async (e) => {
      const t = e.currentTarget;
      t.classList.add("refreshing");
      await init();
      setTimeout(() => t.classList.remove("refreshing"), 600);
    });
  }

  function mountResonanceCard() {
    // V0.75.1 起需显式传 target —— 该端点原先写死 etf，导致白银页
    // 的共振卡一直显示的是黄金三维分值
    if (window.PM_Resonance) {
      window.PM_Resonance.mount("resonanceCard", { target: "silver_etf" });
      return;
    }
    const s = document.createElement("script");
    s.src = "/static/resonance-card.js";
    s.onload = () =>
      window.PM_Resonance && window.PM_Resonance.mount("resonanceCard", { target: "silver_etf" });
    document.head.appendChild(s);
  }

  function mountHealthSummary() {
    if (document.querySelector('script[src="/static/health-summary.js"]')) return;
    const s = document.createElement("script");
    s.src = "/static/health-summary.js";
    document.head.appendChild(s);
  }

  async function init() {
    await loadTrend(60, "D");
    await loadCards();
    await loadCompare();
  }

  function onReady() {
    bindRangeButtons();
    bindRefresh();
    mountResonanceCard();
    mountHealthSummary();
    // 自动 60 秒刷新
    setInterval(init, 60000);
    init();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", onReady);
  } else {
    onReady();
  }
})();
