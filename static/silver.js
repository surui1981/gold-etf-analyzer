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

  // V0.106.2 整合：去掉 8888 硬编码（同源）
  const API_BASE = "";

  // 状态：避免在 3 个 render 函数间共享
  let trendChart = null;
  let lastTrend = null;
  let currentKlineInterval = "D";

  const INTERVAL_SUB = {
    D: "日 K · 60 个交易日",
    W: "周 K · 聚合至 ISO 周界（52 周 ≈ 1 交易年）",
    M: "月 K · 聚合至年月界（24 月 ≈ 2 交易年）",
  };

  // V0.99 C5：主图市场选择器（默认 ETF，与 V0.98 行为一致；点 SGE 走 /silver/sge-trend）
  let currentMarket = "etf";
  const MARKET_SUB = {
    etf: "白银 ETF（562800）· 元/份",
    ny: "纽约白银（COMEX SI）· 美元/盎司",
    sge: "SGE 上海银 Ag99.99 · 元/千克",
  };
  const MARKET_ENDPOINT = {
    etf: (days, interval) => `/api/v1/market/silver/trend?days=${days}&interval=${interval}`,
    ny: (days) => `/api/v1/market/silver/ny-trend?days=${days}`,
    sge: (days) => `/api/v1/market/silver/sge-trend?days=${days}`,
  };
  const MARKET_TREND_FIELD = {
    etf: "points", // SilverTrendOut.points
    ny: "points", // SilverNyTrendOut 同形态
    sge: "klines", // SilverSgeTrendOut 用 klines 字段
  };
  const MARKET_TREND_CLOSE = {
    etf: (p) => p.close,
    ny: (p) => p.close,
    sge: (k) => k.close,
  };
  const MARKET_NAME = {
    etf: "白银 ETF 562800",
    ny: "纽约白银 SI",
    sge: "SGE Ag99.99",
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

  async function loadTrend(days = 60, interval = "D", market = currentMarket) {
    currentKlineInterval = interval;
    currentMarket = market;
    const subEl = document.getElementById("trendSub");
    // V0.99 C5：主图副标题 = 市场标签 + 区间标签（市场切换时刷新）
    const subMarket = MARKET_SUB[market] || "";
    const subInterval = INTERVAL_SUB[interval] || INTERVAL_SUB.D;
    if (subEl) subEl.textContent = subMarket + " · " + subInterval;
    try {
      const endpoint = MARKET_ENDPOINT[market] || MARKET_ENDPOINT.etf;
      const data = await fetchJSON(API_BASE + endpoint(days, interval));
      lastTrend = data;
      renderSourceBar(data);
      renderMain(data, market);
      loadAlerts();
    } catch (e) {
      showTrendError(e);
    } finally {
      hideLoadBar();
    }
  }

  // V0.109.2：根据 data_as_of 与今日差几个工作日，超 1 个 = 「数据滞后」
  // 工作日简化：date 对象差的天数（容忍周末 1-2 天，走后端 tradng_days_between 不准但显示够用）
  function _lagTradingDaysFromString(dataAsOfStr) {
    if (!dataAsOfStr) return 0;
    const asOf = new Date(dataAsOfStr + "T00:00:00");
    if (isNaN(asOf.getTime())) return 0;
    const today = new Date();
    today.setHours(0, 0, 0, 0);
    // 简化版：直接换算日历天数 → 周末休市的「真实滞后」只会偏高 1-2 天（用户理解无碍）
    return Math.max(0, Math.round((today - asOf) / 86400000));
  }

  async function loadCards() {
    try {
      const [etf, ny, sge] = await Promise.all([
        fetchJSON(API_BASE + "/api/v1/market/silver/etf-quote"),
        fetchJSON(API_BASE + "/api/v1/market/silver/quote"),
        fetchJSON(API_BASE + "/api/v1/market/silver/sge-quote"),
      ]);
      // V0.109.2：data_as_of → 滞后 chip（仅跨日 > 1 天时显示）
      const etfLag = _lagTradingDaysFromString(etf.data_as_of);
      const nyLag = _lagTradingDaysFromString(ny.data_as_of);
      const sgeLag = _lagTradingDaysFromString(sge.data_as_of);
      function lagChipHtml(lag) {
        return lag > 1
          ? ` <span class="fsh-chip fsh-warn fsh-stale-chip" style="font-size:10px" title="上游数据源滞后">⚠ 数据滞后 ${lag} 天</span>`
          : "";
      }
      function asOfLabel(dataAsOf) {
        if (!dataAsOf) return "数据日期未知";
        return "数据日期 " + dataAsOf;
      }
      const items = [
        {
          label: "白银 ETF 562800",
          value: etf.price.toFixed(3) + " 元/份",
          extra: (etf.change_pct >= 0 ? "+" : "") + etf.change_pct.toFixed(2) + "%",
          color: etf.change_pct >= 0 ? "up" : "down",
          // V0.99：LOF 代理源时给前端一个可见提示（eastmoney 失败后回退 sina sz161226）
          sourceNote: etf.data_source_note === "lof_proxy" ? "（LOF 代理）" : "",
          // V0.109.2：数据日期 + 滞后 chip
          asOf: asOfLabel(etf.data_as_of),
          lagChip: lagChipHtml(etfLag),
        },
        {
          label: "纽约白银 SI",
          value: ny.price_usd.toFixed(2) + " 美元/盎司",
          extra: (ny.change_pct >= 0 ? "+" : "") + ny.change_pct.toFixed(2) + "%",
          color: ny.change_pct >= 0 ? "up" : "down",
          sourceNote: "",
          asOf: asOfLabel(ny.data_as_of),
          lagChip: lagChipHtml(nyLag),
        },
        {
          label: "SGE 上海银 Ag99.99",
          value: sge.price_cny_per_kg.toFixed(2) + " 元/千克",
          extra: (sge.change_pct >= 0 ? "+" : "") + sge.change_pct.toFixed(2) + "%",
          color: sge.change_pct >= 0 ? "up" : "down",
          sourceNote: "",
          asOf: asOfLabel(sge.data_as_of),
          lagChip: lagChipHtml(sgeLag),
        },
        {
          label: "数据源",
          value: etf.unit || "场内",
          extra: "ETF + NY + SGE 三市场同步",
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
        <div class="extra">${i.extra}${i.sourceNote ? " " + i.sourceNote : ""}</div>
        ${i.asOf ? `<div class="as-of" style="font-size:11px;color:var(--muted);margin-top:2px">${i.asOf}${i.lagChip || ""}</div>` : ""}
      </div>`
        )
        .join("");

      // 顺手把 3-market 报价存到状态机，给升贴水表 + 趋势选择器复用
      window._silverQuotes = { etf, ny, sge };

      // V0.99 C5：渲染 3-market 升贴水表（以 SGE 为锚）
      renderPremiumTable(etf, ny, sge);

      // V0.109.2：loadCards 在 loadTrend 之后跑，_silverQuotes 已就绪，
      // 重新跑一次 source-bar 渲染，让「数据滞后」尾部标能拿到 quote 真实数据日期
      if (typeof lastTrend === "object" && lastTrend) {
        renderSourceBar(lastTrend);
      }
    } catch (e) {
      document.getElementById("cards").innerHTML =
        '<div class="card"><div class="label">报价</div><div class="value">加载失败</div><div class="extra">' +
        e.message +
        "</div></div>";
    }
  }

  /**
   * V0.99 C5 · 3-market 升贴水表（以 SGE 现货基准价为锚）
   *
   * 折算口径：
   *   - 562800 ETF：1 份 ≈ 1000 g 白银现货 → 元/份 × 1000 = 元/千克
   *   - NY SI：USD/oz → 1 oz = 31.1035 g → × 31.1035 × 7.1 = 元/千克（7.1 = CNY/USD 固定参考）
   *   - SGE Ag99.99：CNY/kg 现货基准
   *
   * 升贴水 = (折算价 - SGE) / SGE × 100%
   * SGE 列 = 0%（锚定）
   */
  function renderPremiumTable(etf, ny, sge) {
    const el = document.getElementById("premiumTable");
    if (!el) return;
    // 容错：任一报价缺失就降级
    if (!etf || !ny || !sge) {
      el.innerHTML = '<div style="padding:8px;color:var(--muted);font-size:12px">报价未就绪，暂无法计算升贴水</div>';
      return;
    }
    const ETF_G_PER_SHARE = 1000.0;
    const OZ_TO_G = 31.1035;
    const CNY_PER_USD = 7.1; // V0.99 固定参考汇率
    const etfPerKg = etf.price * ETF_G_PER_SHARE;
    const nyPerKg = ny.price_usd * OZ_TO_G * CNY_PER_USD;
    const sgePerKg = sge.price_cny_per_kg;
    const premEtf = ((etfPerKg - sgePerKg) / sgePerKg) * 100;
    const premNy = ((nyPerKg - sgePerKg) / sgePerKg) * 100;
    const premSge = 0.0;
    const fmt = (n) => (n >= 0 ? "+" : "") + n.toFixed(2) + "%";
    const col = (n) => (n > 0.5 ? "up" : n < -0.5 ? "down" : "");
    el.innerHTML = `
      <!-- V0.113.0 · 表格横向滚动容器；aria-label 复用上方小节标题的 i18n key
           （silver.premium_table_title），不新造 key -->
      <div class="table-scroll" tabindex="0" role="region"
           aria-label="${(window.I18n ? I18n.t('silver.premium_table_title') : null) || '多市场升贴水表（以 SGE 为锚）'}">
      <table style="width:100%;border-collapse:collapse;font-size:13px">
        <thead>
          <tr style="background:var(--card)">
            <th style="padding:8px;text-align:left">指标</th>
            <th style="padding:8px;text-align:right">562800 ETF</th>
            <th style="padding:8px;text-align:right">NY SI 折算</th>
            <th style="padding:8px;text-align:right;background:#e8f7ee">SGE Ag99.99</th>
          </tr>
        </thead>
        <tbody>
          <tr><td style="padding:6px">折算口径</td>
              <td style="padding:6px;text-align:right">元/份 × 1000</td>
              <td style="padding:6px;text-align:right">USD/oz × 31.1035 × 7.1</td>
              <td style="padding:6px;text-align:right;background:#f5fbfa">现货基准</td></tr>
          <tr><td style="padding:6px">最新价</td>
              <td style="padding:6px;text-align:right">${etfPerKg.toFixed(0)}</td>
              <td style="padding:6px;text-align:right">${nyPerKg.toFixed(0)}</td>
              <td style="padding:6px;text-align:right;background:#f5fbfa;font-weight:600">${sgePerKg.toFixed(0)}</td></tr>
          <tr><td style="padding:6px">升贴水（以 SGE 为锚）</td>
              <td style="padding:6px;text-align:right" class="${col(premEtf)}">${fmt(premEtf)}</td>
              <td style="padding:6px;text-align:right" class="${col(premNy)}">${fmt(premNy)}</td>
              <td style="padding:6px;text-align:right;background:#f5fbfa;font-weight:600">${fmt(premSge)}</td></tr>
        </tbody>
      </table>
      </div>
      <div style="font-size:11px;color:var(--muted);margin-top:8px;line-height:1.5">
        📐 升贴水 = (折算价 - SGE 基准) / SGE 基准 × 100%。SGE 列为锚定（0%）。
        汇率 CNY/USD = 7.1（固定参考，实时汇率请参考专门汇率工具）。
      </div>
    `;
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
    // V0.109.2：补「数据滞后」尾部标 + 改用 warn 时包含具体源
    const quotes = window._silverQuotes || {};
    const SOURCE_LABEL_LOCAL = {
      silver_etf: "白银 ETF 562800",
      silver_ny: "纽约白银 SI",
      sge_silver: "SGE 上海银 Ag99.99",
    };
    const staleLines = [];
    ["silver_etf", "silver_ny", "sge_silver"].forEach((k) => {
      const q = quotes[
        k === "silver_etf" ? "etf" : k === "silver_ny" ? "ny" : "sge"
      ];
      if (q && q.data_as_of) {
        const lag = _lagTradingDaysFromString(q.data_as_of);
        if (lag > 1) {
          staleLines.push(`${SOURCE_LABEL_LOCAL[k]} 数据至 ${q.data_as_of}（滞后 ${lag} 天）`);
        }
      }
    });
    const staleSuffix = staleLines.length ? ` · ⚠ 时效滞后: ${staleLines.join(" / ")}` : "";
    if (mock === 0 && !staleLines.length) {
      bar.className = "source-bar source-ok";
      bar.textContent = `✅ 全部数据源实时（${live} 个源：白银 ETF 562800 + COMEX SI 期货 + 黄金宏观因子）`;
    } else if (mock > 0 && live > 0) {
      bar.className = "source-bar source-warn";
      bar.textContent = `⚠️ 部分数据源降级为演示数据（${mock} mock / ${live} live）：${Object.entries(ds)
        .filter(([, v]) => v === "mock")
        .map(([k]) => k)
        .join(" / ")}${staleSuffix}`;
    } else if (staleLines.length) {
      bar.className = "source-bar source-warn";
      bar.textContent = `⚠️ 部分数据源时效滞后：${staleLines.join(" / ")}`;
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

  function renderMain(data, market = currentMarket) {
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

    // V0.100：消息面未打分 → 综合指数显示「pending」chip + 数字透明度降级
    // 复用 freshness.js 的 fsh-chip fsh-warn 样式（琥珀色 + ▲ 三角）
    const newsForPending = data.news || {};
    const newsPendingSilver = newsForPending.scored === false;
    const existingPendingSilver = document.getElementById("idxPendingChip");
    if (existingPendingSilver) existingPendingSilver.remove();
    if (newsPendingSilver && data.index?.score != null) {
      const chip = document.createElement("span");
      chip.id = "idxPendingChip";
      chip.className = "fsh-chip fsh-warn fsh-stale-chip";
      chip.title =
        window.I18n && typeof window.I18n.t === "function"
          ? window.I18n.t(
              "trend.pending_tooltip",
              "消息面尚未打分，综合指数按技术+宏观归一计算（暂未含消息面权重）",
            )
          : "消息面尚未打分，综合指数按技术+宏观归一计算（暂未含消息面权重）";
      chip.textContent =
        "▲ " +
        (window.I18n && typeof window.I18n.t === "function"
          ? window.I18n.t("trend.pending_chip", "消息面 pending")
          : "消息面 pending");
      badge.insertAdjacentElement("afterend", chip);
      numEl.style.opacity = "0.55";  // V0.83 fsh-stale 同模式视觉降级
    } else {
      numEl.style.opacity = "1";
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
    // V0.118.0：角标文案从后端 dynamic_factors 逐因子明细派生，不再硬编码因子个数
    // V0.119.0：可滚动因子清单由后端 rolling_factors 给出（低频因子走 hardcode），
    // 前端不再维护「排除 cb_gold」这种硬编码清单（会腐化）。
    const macroFactorsArr = macro.factors || [];
    const macroRollingTotal = Array.isArray(macro.rolling_factors)
      ? macro.rolling_factors.length
      // 兜底：只有老后端（V0.118.x，没这个字段）才会走到这里 —— 那时后端本来只有
      // cb_gold 一个不滚动因子，所以排除 cb_gold 恰好是对的。新后端一定给
      // rolling_factors，这条分支不会被执行。
      : macroFactorsArr.filter((f) => f.key !== "cb_gold").length;
    const macroDynamicCount = (macro.dynamic_factors || []).length;
    const macroBadgeHint = macroDynamic
      ? `${macroRollingTotal} 个可滚动因子全部使用近 252 日滚动 90/10 分位`
      : macroDynamicCount > 0
      ? `${macroDynamicCount}/${macroRollingTotal} 个因子使用近 252 日滚动 90/10 分位，其余样本不足回退 hardcode`
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
    // V0.100：未打分时显式「— · 今日未打分」（替代旧「未打分 · 按 50 中性」表述）
    const newsInfoEl = document.getElementById("newsInfo");
    if (news.scored) {
      newsInfoEl.textContent = news.score != null ? `综合 ${news.score.toFixed(1)} / 100` : "";
    } else {
      newsInfoEl.textContent =
        window.I18n && typeof window.I18n.t === "function"
          ? window.I18n.t("trend.news_unscored_label", "消息面指数 — · 今日未打分")
          : "消息面指数 — · 今日未打分";
    }
    const newsFactorEl = document.getElementById("newsFactor");
    if (news.summary) {
      newsFactorEl.innerHTML = news.summary;
    } else if (news.scored) {
      newsFactorEl.innerHTML = `已打分 ${news.score}`;
    } else {
      // V0.100：未打分时显式 chip + 提示文案
      const unscoredChipText =
        window.I18n && typeof window.I18n.t === "function"
          ? window.I18n.t("trend.news_unscored_chip", "未打分 · pending")
          : "未打分 · pending";
      const pendingHintText =
        window.I18n && typeof window.I18n.t === "function"
          ? window.I18n.t(
              "trend.news_pending_hint",
              "消息面未打分不参与综合指数（30% 权重剔除）。去下方「今日消息面打分」完成评价",
            )
          : "消息面未打分不参与综合指数（30% 权重剔除）。去下方「今日消息面打分」完成评价";
      newsFactorEl.innerHTML = `<div class="macro-row">
      <span class="nm">消息面打分</span>
      <span class="val" style="color:var(--muted)">—</span>
      <span class="bar"><i style="width:0%;background:var(--muted)"></i></span>
      <span class="dt"><span class="fsh-chip fsh-warn fsh-stale-chip" style="font-size:10px">${unscoredChipText}</span></span>
    </div>
    <div class="desc" style="font-size:11px;color:var(--muted);margin-top:2px">
      💬 ${pendingHintText}
    </div>`;
    }

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

    // 主图（V0.99 C5：3-market 自适应 — ETF/NY 用 data.points，SGE 用 data.klines）
    const fieldName = MARKET_TREND_FIELD[market] || "points";
    const points = data[fieldName] || [];
    const labelOf = (p) => p.date;
    const closeOf = MARKET_TREND_CLOSE[market] || ((p) => p.close);
    // V0.99：SGE klines 没有 ma5/ma20/ma40 字段（端点不返回均线），用 undefined 占位
    const hasMA = market === "etf" || market === "ny";
    const ma5Of = (p) => p.ma5;
    const ma20Of = (p) => p.ma20;
    const ma40Of = (p) => p.ma40;

    const labels = points.map(labelOf);
    const closes = points.map(closeOf);
    const ma5 = hasMA ? points.map(ma5Of) : points.map(() => null);
    const ma20 = hasMA ? points.map(ma20Of) : points.map(() => null);
    const ma40 = hasMA ? points.map(ma40Of) : points.map(() => null);

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
    const marketName = MARKET_NAME[market] || data.name || "白银";
    const datasets = [
      { label: marketName, data: closes, borderColor: "#1d4ed8", backgroundColor: "rgba(29,78,216,0.1)", tension: 0.2, fill: false, pointRadius: 0 },
    ];
    if (hasMA) {
      datasets.push({ label: "MA5", data: ma5, borderColor: "#f59f00", borderDash: [4, 4], tension: 0, fill: false, pointRadius: 0 });
      datasets.push({ label: "MA20", data: ma20, borderColor: "#946300", borderDash: [4, 4], tension: 0, fill: false, pointRadius: 0 });
      datasets.push({ label: "MA40", data: ma40, borderColor: "#c92a2a", borderDash: [4, 4], tension: 0, fill: false, pointRadius: 0 });
    }
    trendChart = new Chart(ctx, {
      type: "line",
      data: { labels, datasets },
      options: {
        responsive: true,
        plugins: { legend: { position: "top" } },
        scales: { y: { beginAtZero: false } },
      },
    });
    ChartA11y.wrapChart(canvas, {
      label: marketName + " 趋势主图（收盘价" + (hasMA ? " + MA5/MA20/MA40，" : "，") + "近 " + labels.length + " 个交易日）",
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
      const days = parseInt(btn.dataset.days, 10);
      const interval = btn.dataset.interval;
      // V0.99 C5：SGE/NY 不接 interval 参数（端点不带 interval），按 days 即可
      if (currentMarket === "sge" || currentMarket === "ny") {
        loadTrend(days, "D", currentMarket);
      } else {
        loadTrend(days, interval, currentMarket);
      }
    });
  }

  function bindMarketSelector() {
    const wrap = document.getElementById("marketSelector");
    if (!wrap) return;
    wrap.addEventListener("click", (e) => {
      const btn = e.target.closest(".market-btn");
      if (!btn) return;
      const newMarket = btn.dataset.market;
      if (!newMarket || newMarket === currentMarket) return;
      document.querySelectorAll("#marketSelector .market-btn").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      // 切换市场时取当前 range-btn 的 days（默认 60D）
      const activeRange = document.querySelector("#klineRangeBtns .range-btn.active");
      const days = activeRange ? parseInt(activeRange.dataset.days, 10) : 60;
      const interval = activeRange ? activeRange.dataset.interval : "D";
      loadTrend(days, interval, newMarket);
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
    // V0.99 C5：默认 60D · ETF；market 切换后由 market-btn 状态决定 currentMarket
    await loadTrend(60, "D", currentMarket);
    await loadCards();
    await loadCompare();
  }

  function onReady() {
    bindRangeButtons();
    bindMarketSelector();
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
