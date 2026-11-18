/*!
 * static/crisis-fit.js — V0.128.0 · 经济危机金价拟合曲线的前端逻辑
 *
 * ⚠⚠⚠ **这不是预测**：这是「历史形态参照 + 情景假设」。
 *   算法把历史危机周期的**等权平均模板**套到当前周期上再外推，
 *   它**有方向**（与 V0.127.0 的金价区间扇形图「刻意不预测涨跌」相反）
 *   ⇒ 页面上必须常驻说明，且**不得**出现「目标价 / 预计金价 / 看多看空」。
 *
 * 两个宿主共用同一份逻辑：
 *   ① static/crisis-fit.html  独立页：结论卡 + 拟合图 + 模板图 + 边界与口径
 *   ② static/home.html         首页磁贴：形态拟合一行字（#cfTileRange）
 *
 * ⚠ **口径纪律**（页面上的数一律来自接口，前端不重算）：
 *   - 终点隐含价 / drift=0 对照 / 单周期终点区间 / 锚点敏感度 / 模板支撑轮数
 *     **全部**取接口返回；
 *   - 前端只做格式化与渲染 —— 自己算一遍就等于页面与文档各说各话；
 *   - 取数失败 / 产物缺失 ⇒ **明示「待数据」**，**绝不画一条假曲线**
 *     （记忆 fallback-layer-is-the-real-contract）。
 *
 * ⚠ **drift 是假设不是结论**：结论卡上永远同时显示 drift=0 的终点，
 *   让「这条曲线里有多少是假设撑起来的」一眼可见。
 */
(function () {
  "use strict";

  const API = "/api/v1/forecast";
  const TARGET = "ny";
  const HORIZON = 30;

  /* ───────────────── i18n / 格式化 ───────────────── */

  // 字典命中优先；没命中时**不要**渲染 key 字面量 ⇒ 用代码里的 fb 兜底。
  // ⚠ 不能写成 `(I18n.t(key) || fb)`：I18n.t 找不到时返回的是 **key 本身**（真值）
  //   ⇒ fb 永远用不上，页面会显示 "crisis.endpoint_label"。
  function T(key, fallback, params) {
    if (window.I18n && typeof window.I18n.t === "function") {
      const v = window.I18n.t(key, params);
      if (v && v !== key) return v;
    }
    return fallback != null ? fallback : key;
  }

  function escapeHtml(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    })[c]);
  }

  function fmtNum(v, digits) {
    if (v == null || !isFinite(v)) return "—";
    return Number(v).toLocaleString("en-US", {
      minimumFractionDigits: digits,
      maximumFractionDigits: digits,
    });
  }

  function fmtPrice(v) {
    return fmtNum(v, 0);
  }

  function fmtPct(v, digits) {
    if (v == null || !isFinite(v)) return "—";
    return (Number(v) >= 0 ? "+" : "") + Number(v).toFixed(digits == null ? 1 : digits) + "%";
  }

  /* ───────────────── 取数 ───────────────── */

  async function fetchJson(url) {
    let r;
    try {
      r = await fetch(url, { credentials: "same-origin", headers: { accept: "application/json" } });
    } catch (e) {
      return { ok: false, status: 0, error: String((e && e.message) || e) };
    }
    let body = null;
    try { body = await r.json(); } catch (e) { body = null; }
    if (!r.ok) {
      return {
        ok: false,
        status: r.status,
        error: (body && (body.detail || body.message)) || ("HTTP " + r.status),
      };
    }
    return { ok: true, status: r.status, data: body };
  }

  /* ───────────────── 图表 ───────────────── */

  /** 反查并销毁旧实例（Chart.js 不会自动销毁 ⇒ 重渲染会 "Canvas already in use"）。 */
  function destroyChartOn(canvas) {
    if (!canvas) return;
    try {
      if (window.Chart && typeof window.Chart.getChart === "function") {
        const inst = window.Chart.getChart(canvas);
        if (inst) inst.destroy();
      }
    } catch (e) {
      /* 忽略：销毁失败不该阻断渲染 */
    }
  }

  /** 相对「锚点月」的月份标签（t=0 是锚点月）。 */
  function monthLabels(anchorMonth, horizon) {
    const out = [];
    if (!anchorMonth) return out;
    const parts = String(anchorMonth).split("-");
    const total = Number(parts[0]) * 12 + (Number(parts[1]) - 1);
    for (let t = 0; t <= horizon; t++) {
      const v = total + t;
      out.push(String(Math.floor(v / 12)) + "-" + String((v % 12) + 1).padStart(2, "0"));
    }
    return out;
  }

  /**
   * 拟合图：拟合曲线 + 模板×缩放（形状对照）+ 单周期终点散点 + 当前点。
   * ⚠ 模板覆盖到 t=template_max_t 之后是**平台外推**（没有历史信息）⇒ 图上要标出来。
   */
  function renderFitChart(canvas, data) {
    if (!canvas || !window.Chart) return null;
    destroyChartOn(canvas);

    const horizon = Number(data.horizon_months) || HORIZON;
    const curve = Array.isArray(data.curve) ? data.curve : [];
    const t0 = Number(data.t0) || 0;
    // ⚠ x 轴 = **距锚点月的月数 t**。拟合线只存在于 t ≥ t0（当前点之后），
    //   所以轴上要覆盖 0 … (t0 + horizon) ⇒ 用 horizon 会少画 t0 个月（实测错位）。
    const lastT = t0 + horizon;
    const labels = monthLabels(data.anchor_month, lastT);
    const maxT = data.template_max_t != null ? Number(data.template_max_t) : null;

    // 缩放因子：当前归一 ÷ 模板在 t0 处的值（接口已算好 scale 的效果 ⇒ 这里只用形状）
    const template = Array.isArray(data.template) ? data.template : [];
    const templateByT = {};
    template.forEach((row) => { templateByT[Number(row[0])] = Number(row[1]); });
    const curNorm = Number(data.cur_norm);
    const tplAtT0 = templateByT[t0];
    const scale = tplAtT0 && isFinite(tplAtT0) && tplAtT0 !== 0 ? curNorm / tplAtT0 : null;

    const fitData = new Array(lastT + 1).fill(null);
    curve.forEach((pt) => {
      const t = Number(pt.t);
      if (t >= 0 && t <= lastT) fitData[t] = Number(pt.price);
    });

    // 模板×缩放（不含漂移）⇒ 看得出「漂移假设加了多少」
    const shapeData = new Array(lastT + 1).fill(null);
    if (scale != null) {
      for (let t = 0; t <= lastT; t++) {
        const v = templateByT[t];
        if (v != null && isFinite(v)) shapeData[t] = Number(data.anchor_avg) * v * scale / 100;
      }
    }

    // 单周期终点（离散区间）
    // ⚠ x 轴是 **category 轴**（labels 是月份字符串）⇒ 散点的 x 必须给**标签字符串**；
    //   给数字会被当成「找不到的标签」⇒ 全部落到索引 0（实测全挤在左边）。
    const ends = Array.isArray(data.cycle_ends) ? data.cycle_ends : [];
    const endPoints = ends.map((e) => ({
      x: labels[lastT],
      y: Number(e.price),
      name: e.name,
    }));

    const datasets = [
      {
        label: T("crisis.shape_label", "模板×缩放（不含漂移假设）"),
        data: shapeData,
        borderColor: "rgba(120,120,120,0.9)",
        borderWidth: 1.5,
        borderDash: [5, 4],
        pointRadius: 0,
        tension: 0.2,
        fill: false,
      },
      {
        label: T("crisis.fit_label", "形态拟合曲线（历史形态参照）"),
        data: fitData,
        borderColor: "rgba(217,119,6,0.95)",
        backgroundColor: "rgba(217,119,6,0.12)",
        borderWidth: 2.4,
        pointRadius: 0,
        tension: 0.2,
        fill: false,
      },
    ];

    if (endPoints.length) {
      datasets.push({
        label: T("crisis.cycle_ends_label", "各轮周期各自外推到终点"),
        data: endPoints,
        type: "scatter",
        backgroundColor: "rgba(37,99,235,0.75)",
        pointRadius: 5,
        pointStyle: "rectRot",
      });
    }

    const chart = new window.Chart(canvas, {
      type: "line",
      data: { labels: labels, datasets: datasets },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        interaction: { mode: "nearest", intersect: false },
        scales: {
          y: {
            title: { display: true, text: T("crisis.unit", "美元/盎司") },
            ticks: { callback: (v) => fmtPrice(v) },
          },
          x: {
            title: { display: true, text: T("crisis.x_title", "距锚点月的月数（t）") },
            ticks: { maxRotation: 0, autoSkip: true, maxTicksLimit: 10 },
          },
        },
        plugins: {
          legend: { position: "top", labels: { boxWidth: 12, font: { size: 11 } } },
          tooltip: {
            callbacks: {
              label: (c) => {
                const v = c.parsed.y;
                if (v == null) return c.dataset.label + ": —";
                return c.dataset.label + ": " + fmtPrice(v);
              },
            },
          },
        },
      },
    });

    if (window.ChartA11y) {
      window.ChartA11y.wrapChart(canvas, {
        label: T("crisis.fit_a11y", "经济危机金价拟合曲线（历史形态参照，非预测）"),
        table: {
          columns: [
            T("crisis.col_month", "月份"),
            T("crisis.col_fit", "拟合隐含价"),
            T("crisis.col_shape", "模板×缩放"),
          ],
          rows: labels.map((m, i) => [
            m,
            fitData[i] == null ? "—" : fmtPrice(fitData[i]),
            shapeData[i] == null ? "—" : fmtPrice(shapeData[i]),
          ]),
        },
      });
    }

    // ⚠ 模板覆盖边界：超过 max_t 的部分是**平台外推**（没有历史信息）⇒ 明示
    const note = document.getElementById("cfFitNote");
    if (note) {
      if (maxT != null && maxT < horizon) {
        note.textContent = T(
          "crisis.template_clamped",
          "模板只覆盖到 t={maxT}（{n} 轮周期支撑）；t={maxT} 之后是**平台外推** —— 那里没有历史信息，曲线形状由插值器的端点夹取决定。",
          { maxT: maxT, n: (data.template_counts || []).length ? data.template_counts[maxT] : "—" },
        );
      } else {
        note.textContent = T(
          "crisis.template_covered",
          "模板覆盖到 t={maxT}，整条外推区间都在历史形态的信息范围内。",
          { maxT: maxT == null ? "—" : maxT },
        );
      }
    }
    return chart;
  }

  /** 模板图：等权均值 + 每轮周期的原始归一路径（均值的原料）。 */
  function renderTemplateChart(canvas, data) {
    if (!canvas || !window.Chart) return null;
    destroyChartOn(canvas);

    const template = Array.isArray(data.template) ? data.template : [];
    const counts = Array.isArray(data.template_counts) ? data.template_counts : [];
    const paths = Array.isArray(data.cycle_paths) ? data.cycle_paths : [];
    if (!template.length) return null;

    const maxT = template.length - 1;
    const labels = [];
    for (let t = 0; t <= maxT; t++) labels.push(String(t));

    const datasets = paths.map((p, i) => ({
      label: p.name || "cycle" + i,
      data: (p.points || []).map((pt) => Number(pt[1])),
      borderColor: "rgba(120,120,120,0.45)",
      borderWidth: 1,
      pointRadius: 0,
      tension: 0.2,
      fill: false,
    }));
    datasets.push({
      label: T("crisis.template_label", "等权平均模板（形态参照本体）"),
      data: template.map((row) => Number(row[1])),
      borderColor: "rgba(217,119,6,0.95)",
      backgroundColor: "rgba(217,119,6,0.12)",
      borderWidth: 2.6,
      pointRadius: 0,
      tension: 0.2,
      fill: false,
    });

    const chart = new window.Chart(canvas, {
      type: "line",
      data: { labels: labels, datasets: datasets },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        interaction: { mode: "index", intersect: false },
        scales: {
          y: {
            title: { display: true, text: T("crisis.template_y", "相对高点（高点=100）") },
            ticks: { callback: (v) => Number(v).toFixed(0) },
          },
          x: {
            title: { display: true, text: T("crisis.template_x", "距各轮高点月数（t）") },
            ticks: { maxRotation: 0, autoSkip: true, maxTicksLimit: 12 },
          },
        },
        plugins: {
          legend: { position: "top", labels: { boxWidth: 12, font: { size: 11 } } },
          tooltip: {
            callbacks: {
              label: (c) => {
                const v = c.parsed.y;
                if (v == null) return c.dataset.label + ": —";
                return c.dataset.label + ": " + Number(v).toFixed(1);
              },
            },
          },
        },
      },
    });

    if (window.ChartA11y) {
      window.ChartA11y.wrapChart(canvas, {
        label: T("crisis.template_a11y", "历史危机周期的等权平均模板与各轮原始路径"),
        table: {
          columns: [
            T("crisis.col_t", "t（距高点月数）"),
            T("crisis.col_template", "等权平均模板"),
            T("crisis.col_support", "支撑轮数"),
          ],
          rows: labels.map((l, i) => [
            l,
            Number(template[i][1]).toFixed(1),
            counts[i] == null ? "—" : String(counts[i]),
          ]),
        },
      });
    }

    // 支撑轮数随 t 变少 ⇒ 明示（尾部证据薄）
    const note = document.getElementById("cfTemplateNote");
    if (note) {
      const minCount = counts.length ? Math.min.apply(null, counts) : null;
      const maxCount = counts.length ? Math.max.apply(null, counts) : null;
      note.textContent = T(
        "crisis.template_support",
        "模板每个 t 由 {min}–{max} 轮周期平均而来（轮数越少 ⇒ 证据越薄；t 越大轮数通常越少）。拟合只取 **{from} 之后**的周期，更早的在下一张图作参照。",
        {
          min: minCount == null ? "—" : minCount,
          max: maxCount == null ? "—" : maxCount,
          from: (data.fit_window && data.fit_window.start) || "—",
        },
      );
    }
    return chart;
  }

  /**
   * 参照集图表：**拟合窗口之前**的更早周期（用户 2026-11-18 拍板：
   * 「拟合只用 2000 年以后，更早的周期放到别的图表显示」）。
   * ⚠ 这些周期**不进模板**（不进等权平均）⇒ 图注要写明，
   *    否则用户会以为模板里也含了它们。
   */
  function renderReferenceChart(canvas, data) {
    if (!canvas || !window.Chart) return null;
    destroyChartOn(canvas);

    const paths = Array.isArray(data.reference_paths) ? data.reference_paths : [];
    if (!paths.length) {
      const note = document.getElementById("cfRefNote");
      if (note) note.textContent = T("crisis.ref_missing", "没有更早的参照周期。");
      return null;
    }

    let maxT = 0;
    paths.forEach((p) => {
      (p.points || []).forEach((pt) => { maxT = Math.max(maxT, Number(pt[0])); });
    });
    const labels = [];
    for (let t = 0; t <= maxT; t++) labels.push(String(t));

    const datasets = paths.map((p, i) => ({
      label: p.name || "cycle" + i,
      data: (p.points || []).map((pt) => Number(pt[1])),
      borderColor: "rgba(120,120,120,0.55)",
      borderWidth: 1.2,
      pointRadius: 0,
      tension: 0.2,
      fill: false,
    }));

    const chart = new window.Chart(canvas, {
      type: "line",
      data: { labels: labels, datasets: datasets },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        interaction: { mode: "nearest", intersect: false },
        scales: {
          y: {
            title: { display: true, text: T("crisis.template_y", "相对高点（高点=100）") },
            ticks: { callback: (v) => Number(v).toFixed(0) },
          },
          x: {
            title: { display: true, text: T("crisis.template_x", "距各轮高点月数（t）") },
            ticks: { maxRotation: 0, autoSkip: true, maxTicksLimit: 12 },
          },
        },
        plugins: {
          legend: { position: "top", labels: { boxWidth: 12, font: { size: 11 } } },
          tooltip: {
            callbacks: {
              label: (c) => {
                const v = c.parsed.y;
                if (v == null) return c.dataset.label + ": —";
                return c.dataset.label + ": " + Number(v).toFixed(1);
              },
            },
          },
        },
      },
    });

    if (window.ChartA11y) {
      window.ChartA11y.wrapChart(canvas, {
        label: T("crisis.ref_a11y", "更早的危机周期（参照用，不参与拟合）"),
        table: {
          columns: [
            T("crisis.col_t", "t（距高点月数）"),
            T("crisis.col_ref", "参照周期归一值"),
          ],
          rows: (function () {
            const rows = [];
            for (let t = 0; t <= maxT; t++) {
              rows.push([
                String(t),
                paths
                  .map((p) => {
                    const hit = (p.points || []).find((pt) => Number(pt[0]) === t);
                    return hit ? Number(hit[1]).toFixed(1) : "—";
                  })
                  .join(" / "),
              ]);
            }
            return rows;
          })(),
        },
      });
    }

    const note = document.getElementById("cfRefNote");
    if (note) {
      note.textContent = T(
        "crisis.ref_note",
        "这 {n} 轮是**拟合窗口之前**的更早周期（{from} 起）—— **只作参照，不参与等权平均**（模板只用拟合窗口内的那几轮）。看它们的形状，是为了对照「现代形态和当年的形态差多少」。",
        { n: paths.length, from: (data.reference_window && data.reference_window.start) || "—" },
      );
    }
    return chart;
  }

  /* ───────────────── 结论区 ───────────────── */

  function chip(cls, text) {
    return '<span class="' + cls + '">' + escapeHtml(text) + "</span>";
  }

  async function mountConclusion() {
    const box = document.getElementById("cfConclusion");
    if (!box) return;
    const errEl = document.getElementById("cfError");
    const rangeEl = document.getElementById("cfRange");
    const metaEl = document.getElementById("cfMeta");
    const chipsEl = document.getElementById("cfChips");
    const endsEl = document.getElementById("cfCycleEnds");
    const sensEl = document.getElementById("cfSensitivity");
    const provEl = document.getElementById("cfProvenance");

    const res = await fetchJson(
      API + "/crisis-fit?target=" + TARGET + "&horizon=" + HORIZON + "&drift=0.003",
    );
    if (!res.ok) {
      if (errEl) {
        errEl.hidden = false;
        errEl.textContent = T("crisis.load_error", "取数失败：{err}", { err: res.error });
      }
      return;
    }
    const data = res.data || {};
    if (errEl) errEl.hidden = true;

    // ⚠ 产物缺失 ⇒ 明示「待数据」，**不画假曲线**
    if (!data.available) {
      if (rangeEl) rangeEl.textContent = T("crisis.pending", "待数据");
      if (metaEl) {
        metaEl.innerHTML =
          '<span class="cf-pending-hint">' +
          escapeHtml(
            T(
              "crisis.pending_hint",
              "历史危机周期的月度序列产物尚未入库 ⇒ 本页**不画曲线**（画一条编出来的线比没有更糟）。",
            ),
          ) +
          "</span>";
      }
      if (chipsEl) chipsEl.innerHTML = "";
      if (endsEl) endsEl.innerHTML = "";
      if (sensEl) sensEl.innerHTML = "";
      if (provEl) provEl.innerHTML = "";
      return;
    }

    const endpoint = data.endpoint || {};
    const drift0 = data.endpoint_drift0 || {};

    if (rangeEl) {
      rangeEl.textContent = fmtPrice(endpoint.price) + " " + T("crisis.unit", "美元/盎司");
    }

    // ★ drift 是假设 ⇒ 常驻 drift=0 对照
    if (metaEl) {
      let html =
        '<span class="cf-drift0">' +
        escapeHtml(
          T(
            "crisis.drift0_line",
            "drift=0（不做漂移假设）时：{price}",
            { price: fmtPrice(drift0.price) },
          ),
        ) +
        "</span>";
      if (data.gain_pct != null) {
        html +=
          '<span class="cf-gain">' +
          escapeHtml(
            T("crisis.gain_line", "相对当前：{pct}", { pct: fmtPct(data.gain_pct, 1) }),
          ) +
          "</span>";
      }
      metaEl.innerHTML = html;
    }

    // chips
    if (chipsEl) {
      const bits = [];
      bits.push(chip("cf-chip", T("crisis.chip_anchor", "锚点月") + " " + (data.anchor_month || "—")));
      if (data.peak_date) {
        bits.push(
          chip("cf-chip", T("crisis.chip_peak", "锚点对应日线峰值") + " " + data.peak_date + " " + fmtPrice(data.peak_price)),
        );
      }
      bits.push(chip("cf-chip", T("crisis.chip_cur", "当前归一") + " " + (data.cur_norm == null ? "—" : Number(data.cur_norm).toFixed(1))));
      bits.push(chip("cf-chip", T("crisis.chip_t0", "距锚点") + " " + (data.t0 == null ? "—" : data.t0) + " " + T("crisis.months", "个月")));
      bits.push(chip("cf-chip", T("crisis.chip_drift", "drift 假设") + " " + fmtPct((data.drift || 0) * 100, 1) + "/月"));
      if (data.template_max_t != null) {
        bits.push(chip("cf-chip", T("crisis.chip_template", "模板覆盖") + " t=0…" + data.template_max_t));
      }
      chipsEl.innerHTML = bits.join("");
    }

    // 单周期终点区间（离散度）
    if (endsEl) {
      const ends = Array.isArray(data.cycle_ends) ? data.cycle_ends : [];
      if (ends.length) {
        const prices = ends.map((e) => Number(e.price)).filter((v) => isFinite(v));
        const lo = Math.min.apply(null, prices);
        const hi = Math.max.apply(null, prices);
        let html =
          '<div class="cf-ends-head">' +
          escapeHtml(
            T(
              "crisis.ends_head",
              "各轮周期各自外推到 T+{h} 个月的终点（这是**离散区间**，不是置信区间）",
              { h: data.horizon_months },
            ),
          ) +
          "</div>";
        html +=
          '<div class="cf-ends-range">' +
          escapeHtml(
            T("crisis.ends_range", "区间 {lo} – {hi}（{n} 轮周期）", {
              lo: fmtPrice(lo),
              hi: fmtPrice(hi),
              n: ends.length,
            }),
          ) +
          "</div>";
        html += '<ul class="cf-ends-list">';
        ends.forEach((e) => {
          html +=
            "<li><span>" +
            escapeHtml(e.name) +
            '</span><span class="num">' +
            escapeHtml(fmtPrice(e.price)) +
            "</span></li>";
        });
        html += "</ul>";
        endsEl.innerHTML = html;
      } else {
        endsEl.innerHTML = "";
      }
    }

    // ⚠ 外推终点的支撑轮数（薄了必须说）—— 拟合收窄到 2000 年以后后，
    //   3 轮里有 2 轮很短（11 / 18 个月）⇒ t≥18 之后只剩 1 轮撑着。
    const supEl = document.getElementById("cfSupport");
    if (supEl) {
      const sup = data.support_at_horizon;
      if (sup == null) {
        supEl.className = "cf-sup";
        supEl.textContent = "";
      } else if (sup <= 1) {
        supEl.className = "cf-sup cf-sup-warn";
        supEl.textContent = T(
          "crisis.support_thin",
          "⚠ 外推终点只由 **{n} 轮**周期支撑（拟合窗口收窄到 2000 年以后，其中两轮很快就收复了）⇒ 长程外推几乎等于「那一轮怎么走」，不是「几轮的平均」。",
          { n: sup },
        );
      } else {
        supEl.className = "cf-sup";
        supEl.textContent = T(
          "crisis.support_ok",
          "外推终点由 {n} 轮周期支撑（模板每个 t 的支撑轮数见图注）。",
          { n: sup },
        );
      }
    }

    // 锚点敏感性（证据门 E5）
    if (sensEl) {
      const s = data.sensitivity;
      if (s && s.spread_pct != null) {
        const wide = Number(s.spread_pct) >= 10;
        sensEl.className = wide ? "cf-sens cf-sens-warn" : "cf-sens";
        sensEl.innerHTML =
          "<b>" +
          escapeHtml(T("crisis.sens_title", "锚点敏感性")) +
          "</b> " +
          escapeHtml(
            T(
              "crisis.sens_text",
              "锚点月 ±1 个月时，终点隐含价在 {lo} – {hi} 之间（相对波动 {pct}）。",
              { lo: fmtPrice(s.low), hi: fmtPrice(s.high), pct: fmtPct(s.spread_pct, 1) },
            ),
          ) +
          (wide
            ? ' <span class="cf-sens-flag">' +
              escapeHtml(T("crisis.sens_wide", "⇒ 锚点选哪个月，结论差很多 —— 别把这条线当锚点。")) +
              "</span>"
            : "");
      } else {
        sensEl.className = "cf-sens";
        sensEl.innerHTML =
          "<b>" +
          escapeHtml(T("crisis.sens_title", "锚点敏感性")) +
          "</b> " +
          escapeHtml(T("crisis.sens_none", "锚点相邻月份没有足够数据 ⇒ 无法给出敏感性（不编数字）。"));
      }
    }

    // provenance（周期数据来源）
    if (provEl) {
      const p = data.provenance || {};
      const warn = Array.isArray(data.warnings) ? data.warnings : [];
      let html = "";
      if (p.source) {
        html +=
          "<li>" +
          escapeHtml(T("crisis.prov_source", "周期数据来源") + "：" + p.source) +
          "</li>";
      }
      if (p.coverage) {
        html += "<li>" + escapeHtml(T("crisis.prov_coverage", "覆盖区间") + "：" + p.coverage) + "</li>";
      }
      if (p.method) {
        html += "<li>" + escapeHtml(T("crisis.prov_method", "口径") + "：" + p.method) + "</li>";
      }
      if (warn.length) {
        html +=
          '<li class="cf-warn">' +
          escapeHtml(T("crisis.prov_warnings", "已剔除 {n} 轮不合规周期：{list}", {
            n: warn.length,
            list: warn.join("；"),
          })) +
          "</li>";
      }
      provEl.innerHTML = html;
    }

    // 图表
    renderFitChart(document.getElementById("cfFitChart"), data);
    renderTemplateChart(document.getElementById("cfTemplateChart"), data);
    renderReferenceChart(document.getElementById("cfRefChart"), data);
  }

  /* ───────────────── 首页磁贴 ───────────────── */

  async function mountTile() {
    const el = document.getElementById("cfTileRange");
    if (!el) return;
    const res = await fetchJson(
      API + "/crisis-fit?target=" + TARGET + "&horizon=" + HORIZON + "&drift=0.003",
    );
    if (!res.ok) {
      el.textContent = T("crisis.tile_unavailable", "形态拟合暂不可用（取数失败）");
      el.classList.add("is-warn");
      return;
    }
    const data = res.data || {};
    if (!data.available) {
      // ⚠ 没有产物 ⇒ 明说「待数据」，**不回退**显示别的口径的数（那是另一个功能）
      el.textContent = T("crisis.tile_pending", "形态拟合：待周期数据入库");
      el.classList.add("is-warn");
      return;
    }
    const ends = Array.isArray(data.cycle_ends) ? data.cycle_ends : [];
    const prices = ends.map((e) => Number(e.price)).filter((v) => isFinite(v));
    const lo = prices.length ? Math.min.apply(null, prices) : null;
    const hi = prices.length ? Math.max.apply(null, prices) : null;
    el.textContent =
      T("crisis.tile_line", "形态拟合 T+{h} 月：{p}", { h: data.horizon_months, p: fmtPrice((data.endpoint || {}).price) }) +
      (lo != null
        ? " · " + T("crisis.tile_range", "各轮 {lo}–{hi}", { lo: fmtPrice(lo), hi: fmtPrice(hi) })
        : "");
  }

  /* ───────────────── 启动 ───────────────── */

  async function boot() {
    if (window.I18n && window.I18n.ready) {
      try { await window.I18n.ready; } catch (e) { /* 字典失败也要渲染（用兜底文案） */ }
    }
    await mountConclusion();
    await mountTile();

    // ⚠ i18n.js 广播的是 **document 上的 "i18n:change" 自定义事件**
    //   （不是 window.I18n.on —— 那个 API 不存在 ⇒ 静默不订阅 ⇒ 切语言不重渲染）。
    document.addEventListener("i18n:change", function () {
      mountConclusion();
    });
  }

  window.PMCrisisFit = { mountConclusion: mountConclusion, mountTile: mountTile };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
