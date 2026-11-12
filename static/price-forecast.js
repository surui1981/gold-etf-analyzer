/*!
 * static/price-forecast.js — V0.127.0 · 金价区间预测的前端共享逻辑
 *
 * 三个宿主共用同一份逻辑（**只写一份**，避免两页各抄一遍必然腐化）：
 *   ① static/price-forecast.html  独立页：结论卡 + 扇形图 + 形状对照 + 校准卡 + 方法说明
 *   ② static/trend.html            趋势页摘要卡：一句话结论 + 迷你扇形 + 详见链接
 *   ③ static/home.html             首页磁贴：当前区间一句话
 *
 * 宿主页只要放好挂载点，脚本就会自动接上：
 *   #pfConclusion  完整版结论区（独立页）
 *   #pfSummaryCard 摘要卡（趋势页）
 *   #fcTileRange   首页磁贴里的一行字（首页）
 *
 * ⚠ **口径纪律（页面上的数一律来自接口，前端不重算）**
 *   - 区间上下沿 / 中心 / **实测覆盖率** 全部取接口返回；
 *   - 前端只做格式化与渲染，**不自己算带宽**（否则页面与文档会各说各话）；
 *   - 取数失败 / 样本不足 ⇒ **明示**，**绝不画一条假带**（记忆
 *     fallback-layer-is-the-real-contract）。
 *
 * ⚠ **必须显示实测覆盖率，不是名义覆盖率**：名义 80% 的带子实测只有 79.2%
 *   （样本外）⇒ 只显示名义值等于让用户拿一个偏乐观的数当承诺。
 */
(function () {
  "use strict";

  const API = "/api/v1/forecast";
  const TARGET = "ny";
  const HORIZON = 20;
  const COVERAGES = [0.5, 0.8, 0.9, 0.98];
  const DEFAULT_COVERAGE = 0.8;

  /* 当前选中的覆盖率 —— **模块级**。
   * ⚠ 若放在 mountConclusion 的局部变量里，切语言会触发 mountConclusion() 重跑
   *   ⇒ 用户刚选的 90% 被悄悄重置回默认 80%（用户以为没生效）。
   * 同样，切换覆盖率后要重画校准表的「当前档」高亮 ⇒ 校准产物也得存在模块级。 */
  let currentCoverage = DEFAULT_COVERAGE;
  let lastCalib = null;

  /* ───────────────── i18n ───────────────── */

  // 字典命中优先；字典没命中时**不要**渲染 key 字面量 ⇒ 用代码里的 fb 兜底。
  // ⚠ 不能写成 `(I18n.t(key) || fb)`：I18n.t 找不到时返回的是 **key 本身**
  //   （真值）⇒ fb 永远用不上，页面会显示 "forecast.range_label"。
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

  /* ───────────────── 形状比值（从产物现算，不写死） ───────────────── */

  /**
   * 短端（k=fromK..toK）**类比形状 ÷ 正态锥** 的倍数区间。
   *
   * ⚠ 为什么不写死：形状是**离线校准**出来的产物（`assets/forecast/shape.json`），
   *   每次重算都可能给出不同的短端胖瘦（形状只对被校准的那个窗口成立）
   *   ⇒ 写死的文案必然随产物腐化。
   *   实测教训（V0.127.0 → V0.127.1）：文案写死成「1.2–1.4 倍」，
   *   而产物实测是 **1.32–1.43 倍** ⇒ 文档与页面同时说错。
   *
   * ⚠ 文案**不假设方向**：比值可能 > 1（更宽）也可能 < 1（更窄）
   *   ⇒ 句式用「相对正态锥为 {range} 倍（>1 表示更宽）」，不写死「更宽」。
   */
  function shortEndRatioRange(calib, fromK, toK) {
    const shape = calib && calib.shape;
    const cone = calib && calib.cone;
    if (!Array.isArray(shape) || !Array.isArray(cone)) return null;
    const lo = Math.max(1, fromK || 1);
    const hi = Math.min(toK || 5, shape.length, cone.length);
    let min = Infinity;
    let max = -Infinity;
    for (let k = lo; k <= hi; k++) {
      const c = Number(cone[k - 1]);
      const s = Number(shape[k - 1]);
      if (!isFinite(c) || !isFinite(s) || c <= 0) continue;
      const r = s / c;
      if (!isFinite(r)) continue;
      if (r < min) min = r;
      if (r > max) max = r;
    }
    if (!isFinite(min) || !isFinite(max)) return null;
    return { min: min, max: max, text: min.toFixed(2) + "–" + max.toFixed(2) };
  }

  /**
   * **跨窗口**的短端倍数（k=fromK..toK）—— 同一算法在另一个窗口上的
   * 「类比形状 ÷ 正态锥」。
   *
   * ⚠ 用途只有一个：把「形状不是恒定结构」这条**已知失效条件**的证据
   *   **现算**出来（页面上的「训练段 ≈0.98 倍 / 近 600 段 ≈1.27 倍」）。
   *   这两个数以前是写死的 ⇒ 产物重算后会静默变成假话（V0.127.1 教训）。
   *
   * ⚠ 窗口名必须与产物里的键一致（`shape_stability` 的键）：
   *   `recent_600`（近 600 段）/ `train`（训练段）。
   * ⚠ 找不到该窗口 / 数组长度对不上 ⇒ 返回 ``null`` ⇒ 页面降级为
   *   「不含具体数字的表述」，**不拿主窗口的数字冒充别的窗口**。
   */
  function windowRatioRange(calib, windowName, fromK, toK) {
    const stability = calib && calib.shape_stability;
    const cone = calib && calib.cone;
    if (!stability || typeof stability !== "object") return null;
    const blk = stability[windowName];
    if (!blk) return null;
    const shape = blk.shape;
    if (!Array.isArray(shape) || !Array.isArray(cone)) return null;
    const lo = Math.max(1, fromK || 1);
    const hi = Math.min(toK || 5, shape.length, cone.length);
    let min = Infinity;
    let max = -Infinity;
    for (let k = lo; k <= hi; k++) {
      const c = Number(cone[k - 1]);
      const s = Number(shape[k - 1]);
      if (!isFinite(c) || !isFinite(s) || c <= 0) continue;
      const r = s / c;
      if (!isFinite(r)) continue;
      if (r < min) min = r;
      if (r > max) max = r;
    }
    if (!isFinite(min) || !isFinite(max)) return null;
    const nDays = Number(blk.n_days) || 0;
    return {
      min: min,
      max: max,
      nDays: nDays,
      text: min.toFixed(2) + "–" + max.toFixed(2),
      // 供门禁/自检用：k=1 处的精确倍数
      k1: (function () {
        const c = Number(cone[0]);
        const s = Number(shape[0]);
        return isFinite(c) && isFinite(s) && c > 0 ? s / c : null;
      })(),
    };
  }

  /* ───────────────── 格式化 ───────────────── */

  function fmtNum(v, digits) {
    if (v == null || !isFinite(v)) return "—";
    return Number(v).toLocaleString("en-US", {
      minimumFractionDigits: digits || 0,
      maximumFractionDigits: digits || 0,
    });
  }
  function fmtPrice(v) { return fmtNum(v, 0); }
  function fmtPrice2(v) { return fmtNum(v, 2); }
  function fmtPct(v, digits) {
    if (v == null || !isFinite(v)) return "—";
    return (Number(v) * 100).toFixed(digits == null ? 1 : digits) + "%";
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

  function fetchForecast(opts) {
    const o = opts || {};
    const target = o.target || TARGET;
    const horizon = o.horizon || HORIZON;
    const coverage = o.coverage == null ? DEFAULT_COVERAGE : o.coverage;
    return fetchJson(
      API + "/price?target=" + encodeURIComponent(target) +
      "&horizon=" + encodeURIComponent(horizon) +
      "&coverage=" + encodeURIComponent(coverage)
    );
  }

  function fetchCalibration(target) {
    return fetchJson(API + "/calibration?target=" + encodeURIComponent(target || TARGET));
  }

  /* ───────────────── 结论文案（代码 → i18n 字典） ───────────────── */

  const METHOD_LABELS = {
    ewma_shape: { key: "forecast.method_ewma_shape", fb: "EWMA 定宽 + 类比定形" },
    ewma_widened: { key: "forecast.method_ewma_widened", fb: "EWMA 定宽（交叉校验后取更宽的一条）" },
    vol_only: { key: "forecast.method_vol_only", fb: "仅波动率模型（退化）" },
  };

  const CROSS_CHECK_LABELS = {
    analog_unusually_wide: {
      key: "forecast.cross_wide", fb: "类比带异常宽 → 已取更宽的一条",
    },
    analog_unusually_narrow: {
      key: "forecast.cross_narrow", fb: "类比带异常窄 → 仍用 EWMA（更宽）",
    },
    disagree: { key: "forecast.cross_disagree", fb: "两法口径不一致 → 已取更宽的一条" },
  };

  const SHAPE_SOURCE_LABELS = {
    analog: { key: "forecast.shape_source_analog", fb: "形状：历史类比" },
    cone: { key: "forecast.shape_source_cone", fb: "形状：√k 锥（退化）" },
  };

  const REASON_LABELS = {
    insufficient_analogs: {
      key: "forecast.reason_insufficient_analogs", fb: "相似历史日不足 → 退回纯波动率模型",
    },
    no_shape_artifact: {
      key: "forecast.reason_no_shape_artifact", fb: "形状产物缺失 → 退回 √k 锥",
    },
  };

  function labelOf(map, code, fallbackText) {
    if (!code) return fallbackText || "";
    const hit = map[code];
    if (!hit) return code;
    return T(hit.key, hit.fb);
  }

  /* ───────────────── 扇形图（趋势导航线） ───────────────── */

  /* 销毁挂在某个 canvas 上的既有 Chart 实例。
   *
   * ⚠ **为什么不能只靠调用方记住实例**：mountConclusion() 在切语言时会被重跑，
   *   它内部的 `fanChart` 局部变量是**新的 null** ⇒ 旧实例没人 destroy ⇒
   *   Chart.js 抛 "Canvas is already in use" ⇒ paint() 抛错 ⇒ 整个重渲染链断掉
   *   （实测：三语切换时扇形图 / 校准表 / 形状图全部停止更新）。
   * ⇒ 改成**从 canvas 上反查**既有实例再销毁，与调用方是否记得无关。 */
  function destroyChartOn(canvas) {
    if (!canvas || !window.Chart) return;
    try {
      if (typeof window.Chart.getChart === "function") {
        const inst = window.Chart.getChart(canvas);
        if (inst) inst.destroy();
      }
    } catch (e) { /* 销毁失败不该挡住重绘 */ }
  }

  function renderFanChart(canvas, data, opts) {
    if (!canvas || !window.Chart || !data || !Array.isArray(data.points) || !data.points.length) return null;
    const o = opts || {};
    const labels = data.points.map((p) => String(p.date || "").slice(5));
    const upper = data.points.map((p) => p.upper);
    const lower = data.points.map((p) => p.lower);
    const center = data.points.map(() => data.base_close);

    if (o.instance) { o.instance.destroy(); o.instance = null; }
    destroyChartOn(canvas);
    const chart = new window.Chart(canvas, {
      type: "line",
      data: {
        labels: labels,
        datasets: [
          {
            label: T("forecast.band_upper", "区间上沿"),
            data: upper,
            borderColor: "rgba(37,99,235,0.75)",
            borderWidth: 1.5,
            pointRadius: 0,
            tension: 0.25,
            fill: false,
            order: 2,
          },
          {
            label: T("forecast.band_lower", "区间下沿"),
            data: lower,
            borderColor: "rgba(37,99,235,0.75)",
            borderWidth: 1.5,
            pointRadius: 0,
            tension: 0.25,
            fill: "+1",
            backgroundColor: "rgba(37,99,235,0.12)",
            order: 3,
          },
          {
            label: T("forecast.center_line", "中心（当前收盘，无漂移）"),
            data: center,
            borderColor: "rgba(120,120,120,0.9)",
            borderWidth: 1.2,
            borderDash: [5, 4],
            pointRadius: 0,
            tension: 0,
            fill: false,
            order: 1,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        interaction: { mode: "index", intersect: false },
        scales: {
          y: {
            title: { display: true, text: T("forecast.unit", "美元/盎司") },
            ticks: { callback: (v) => fmtNum(v, 0) },
          },
          x: {
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
                return c.dataset.label + ": " + fmtPrice2(v);
              },
            },
          },
        },
      },
    });

    if (window.ChartA11y) {
      window.ChartA11y.wrapChart(canvas, {
        label: T("forecast.fan_a11y", "未来 N 个交易日金价区间扇形图（上下沿与中心线）"),
        table: {
          columns: [
            T("forecast.calib_col_k", "第 k 个交易日"),
            T("forecast.calib_col_date", "日期"),
            T("forecast.band_lower", "区间下沿"),
            T("forecast.band_upper", "区间上沿"),
          ],
          rows: data.points.map((p) => [p.k, p.date, fmtPrice2(p.lower), fmtPrice2(p.upper)]),
        },
      });
    }
    return chart;
  }

  /* ───────────────── 形状对照图（类比形状 vs √k 锥） ───────────────── */

  function renderShapeChart(canvas, shape, cone) {
    if (!canvas || !window.Chart) return null;
    const s = Array.isArray(shape) ? shape : [];
    const c = Array.isArray(cone) ? cone : [];
    const n = Math.max(s.length, c.length);
    if (!n) return null;
    const labels = [];
    for (let k = 1; k <= n; k++) labels.push(String(k));

    destroyChartOn(canvas);
    const chart = new window.Chart(canvas, {
      type: "line",
      data: {
        labels: labels,
        datasets: [
          {
            label: T("forecast.shape_analog", "类比形状（实测）"),
            data: s.length === n ? s : null,
            borderColor: "rgba(217,119,6,0.9)",
            backgroundColor: "rgba(217,119,6,0.12)",
            borderWidth: 2,
            pointRadius: 0,
            tension: 0.2,
            fill: false,
          },
          {
            label: T("forecast.shape_cone", "对数正态 √k 锥"),
            data: c.length === n ? c : null,
            borderColor: "rgba(120,120,120,0.9)",
            borderWidth: 1.5,
            borderDash: [5, 4],
            pointRadius: 0,
            tension: 0.2,
            fill: false,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        scales: {
          y: {
            min: 0,
            max: 1.05,
            title: { display: true, text: T("forecast.shape_y", "相对宽度（k=20 归一为 1.0）") },
            ticks: { callback: (v) => Number(v).toFixed(2) },
          },
          x: {
            title: { display: true, text: T("forecast.shape_x", "第 k 个交易日") },
            ticks: { maxRotation: 0, autoSkip: true, maxTicksLimit: 10 },
          },
        },
        plugins: {
          legend: { position: "top", labels: { boxWidth: 12, font: { size: 11 } } },
          tooltip: {
            callbacks: {
              label: (c) => c.parsed.y == null
                ? c.dataset.label + ": —"
                : c.dataset.label + ": " + Number(c.parsed.y).toFixed(3),
            },
          },
        },
      },
    });

    if (window.ChartA11y) {
      window.ChartA11y.wrapChart(canvas, {
        label: T("forecast.shape_a11y", "扇形形状对照图：类比形状与对数正态 √k 锥"),
        table: {
          columns: [
            T("forecast.calib_col_k", "第 k 个交易日"),
            T("forecast.shape_analog", "类比形状（实测）"),
            T("forecast.shape_cone", "对数正态 √k 锥"),
          ],
          rows: (function () {
            const rows = [];
            for (let i = 0; i < n; i++) {
              rows.push([
                i + 1,
                s.length ? Number(s[i]).toFixed(3) : "—",
                c.length ? Number(c[i]).toFixed(3) : "—",
              ]);
            }
            return rows;
          })(),
        },
      });
    }
    return chart;
  }

  /* ───────────────── 校准表 ───────────────── */

  function renderCalibrationTable(container, calib, coverage) {
    if (!container) return;
    if (!calib || !calib.available) {
      container.innerHTML = '<div class="pf-empty">' +
        escapeHtml(T("forecast.calib_missing", "未找到校准产物（该标的尚未做离线校准）")) +
        "</div>";
      return;
    }
    const covs = calib.coverages || {};
    const order = ["50", "80", "90", "98"];
    let html = '<div class="table-scroll" tabindex="0" role="region" aria-label="' +
      escapeHtml(T("forecast.calib_title", "覆盖率校准（walk-forward 实测）")) + '"><table><thead><tr>';
    html += "<th>" + escapeHtml(T("forecast.calib_col_cov", "名义覆盖率")) + "</th>";
    html += "<th>" + escapeHtml(T("forecast.calib_train", "训练段实测")) + "</th>";
    html += "<th>" + escapeHtml(T("forecast.calib_oos", "样本外实测")) + "</th>";
    html += "<th>" + escapeHtml(T("forecast.calib_recent", "近段实测")) + "</th>";
    html += "<th>" + escapeHtml(T("forecast.calib_n", "样本量（训练 / 样本外 / 近段）")) + "</th>";
    html += "</tr></thead><tbody>";
    order.forEach(function (key) {
      const e = covs[key];
      if (!e) return;
      const isCur = coverage != null && Math.abs(Number(e.nominal) - coverage) < 1e-9;
      const ns = [e.n_train, e.n_out_of_sample, e.n_recent]
        .map((v) => (v == null ? "—" : fmtNum(v, 0)))
        .join(" / ");
      html += '<tr' + (isCur ? ' class="pf-row-cur"' : "") + ">";
      html += "<td>" + escapeHtml(fmtPct(e.nominal, 0)) + "</td>";
      html += '<td class="num">' + escapeHtml(fmtPct(e.train)) + "</td>";
      html += '<td class="num">' + escapeHtml(fmtPct(e.out_of_sample)) + "</td>";
      html += '<td class="num">' + escapeHtml(fmtPct(e.recent)) + "</td>";
      html += '<td class="num">' + escapeHtml(ns) + "</td>";
      html += "</tr>";
    });
    html += "</tbody></table></div>";
    container.innerHTML = html;
  }

  /* ───────────────── 结论区（独立页 / 摘要卡共用） ───────────────── */

  function buildMetaChips(data) {
    const m = data.measured || {};
    const cc = data.cross_check || {};
    const bits = [];

    bits.push({
      cls: "pf-chip",
      text: T("forecast.center_label", "中心（当前收盘，无漂移）") + " " + fmtPrice2(data.base_close),
    });
    bits.push({
      cls: "pf-chip",
      text: T("forecast.nominal_label", "名义覆盖") + " " + fmtPct(data.coverage, 0),
    });
    // ⚠ 显示**实测**覆盖率（样本外优先），不是名义值 —— 名义 80% 实测只有 79.2%
    const meas = m.out_of_sample != null ? m.out_of_sample : m.recent;
    if (meas != null) {
      bits.push({
        cls: "pf-chip pf-chip-strong",
        text: T("forecast.measured_label", "实测覆盖（样本外）") + " " + fmtPct(meas),
      });
    }
    bits.push({
      cls: "pf-chip",
      text: T("forecast.basis_date", "基准日") + " " + (data.base_date || "—"),
    });
    bits.push({
      cls: "pf-chip",
      text: T("forecast.horizon_label", "期限") + " " + data.horizon + " " +
        T("forecast.trading_days", "个交易日"),
    });
    bits.push({
      cls: "pf-chip",
      text: T("forecast.sigma_label", "日波动率") + " " + fmtPct(data.sigma, 2) +
        " · " + T("forecast.sigma_annual", "年化") + " " + fmtPct(data.sigma_annual, 1),
    });
    if (cc.ratio != null) {
      bits.push({
        cls: "pf-chip",
        text: T("forecast.cross_ratio", "两法宽度比") + " " + Number(cc.ratio).toFixed(2),
      });
    }
    return bits;
  }

  function buildNoticeChips(data) {
    const chips = [];
    const cc = data.cross_check || {};
    chips.push({
      cls: "pf-chip pf-chip-method",
      text: labelOf(METHOD_LABELS, data.method, data.method || ""),
    });
    chips.push({
      cls: "pf-chip",
      text: labelOf(SHAPE_SOURCE_LABELS, data.shape_source, data.shape_source || ""),
    });
    if (cc.status) {
      chips.push({
        cls: "pf-chip pf-chip-warn",
        text: labelOf(CROSS_CHECK_LABELS, cc.status, cc.status),
      });
    } else {
      chips.push({
        cls: "pf-chip pf-chip-ok",
        text: T("forecast.cross_ok", "两法宽度一致"),
      });
    }
    if (data.reason) {
      chips.push({
        cls: "pf-chip pf-chip-warn",
        text: labelOf(REASON_LABELS, data.reason, data.reason),
      });
    }
    return chips;
  }

  function formatRangeText(data) {
    if (!data) return "—";
    return fmtPrice(data.lower) + " – " + fmtPrice(data.upper);
  }

  /* 一句话结论（首页磁贴 / 趋势页摘要卡共用） */
  function summarySentence(data) {
    if (!data) return "";
    const m = data.measured || {};
    const meas = m.out_of_sample != null ? m.out_of_sample : m.recent;
    let s = T("forecast.summary_sentence", "未来 {h} 个交易日金价大概率落在 {lo} – {hi} 美元/盎司")
      .replace("{h}", String(data.horizon))
      .replace("{lo}", fmtPrice(data.lower))
      .replace("{hi}", fmtPrice(data.upper));
    if (meas != null) {
      s += " " + T("forecast.summary_measured", "（名义 {nom}，实测 {meas}）")
        .replace("{nom}", fmtPct(data.coverage, 0))
        .replace("{meas}", fmtPct(meas));
    }
    return s;
  }

  /* ───────────────── 挂载：独立页 ───────────────── */

  async function mountConclusion() {
    const root = document.getElementById("pfConclusion");
    if (!root) return null;
    const rangeEl = document.getElementById("pfRange");
    const metaEl = document.getElementById("pfMeta");
    const chipsEl = document.getElementById("pfChips");
    const errEl = document.getElementById("pfError");
    const fanCanvas = document.getElementById("pfFanChart");
    const fanNote = document.getElementById("pfFanNote");

    let coverage = currentCoverage;
    let data = null;
    let fanChart = null;

    function showError(msg) {
      if (errEl) {
        errEl.hidden = false;
        errEl.textContent = T("forecast.load_failed", "⚠️ 取数失败：") + " " + msg;
      }
      if (rangeEl) rangeEl.textContent = "—";
    }

    function paint() {
      if (!data) return;
      if (errEl) errEl.hidden = true;
      if (rangeEl) rangeEl.textContent = formatRangeText(data);
      if (metaEl) {
        metaEl.innerHTML = buildMetaChips(data)
          .map((c) => '<span class="' + c.cls + '">' + escapeHtml(c.text) + "</span>")
          .join("");
      }
      if (chipsEl) {
        chipsEl.innerHTML = buildNoticeChips(data)
          .map((c) => '<span class="' + c.cls + '">' + escapeHtml(c.text) + "</span>")
          .join("");
      }
      if (fanChart) { fanChart.destroy(); fanChart = null; }
      fanChart = renderFanChart(fanCanvas, data, { instance: fanChart });
      if (fanNote) {
        fanNote.textContent = T("forecast.fan_note", "左端虚线 = 当前收盘价（中心线，恒为水平、无方向判断）；阴影为该覆盖率下的统计区间。");
      }
      // 覆盖率按钮高亮
      document.querySelectorAll("[data-cov]").forEach((b) => {
        const on = Math.abs(Number(b.getAttribute("data-cov")) - coverage) < 1e-9;
        b.classList.toggle("active", on);
        b.setAttribute("aria-pressed", on ? "true" : "false");
      });
      // 校准表的「当前档」高亮要跟着覆盖率走
      renderCalibrationTable(document.getElementById("pfCalibTable"), lastCalib, coverage);
    }

    async function load() {
      const res = await fetchForecast({ target: TARGET, horizon: HORIZON, coverage: coverage });
      if (!res.ok) {
        data = null;
        showError(res.error);
        return;
      }
      data = res.data;
      paint();
    }

    // ⚠ 监听只绑一次 —— mountConclusion() 在切语言时会被重跑，
    //   再绑一次就变成「点一下触发两次 load()」（功能上碰巧一样，但白白多打一次接口）。
    document.querySelectorAll("[data-cov]").forEach((b) => {
      if (b.dataset.pfBound === "1") return;
      b.dataset.pfBound = "1";
      b.addEventListener("click", async function () {
        const v = Number(b.getAttribute("data-cov"));
        if (!isFinite(v) || v === coverage) return;
        coverage = v;
        currentCoverage = v;
        await load();
      });
    });

    await load();

    // 校准卡 + 形状对照图（独立页才有这两个容器）
    const calibRes = await fetchCalibration(TARGET);
    const calib = calibRes.ok ? calibRes.data : null;
    lastCalib = calib;
    renderCalibrationTable(document.getElementById("pfCalibTable"), calib, coverage);
    const shapeCanvas = document.getElementById("pfShapeChart");
    if (shapeCanvas) {
      const shape = calib && calib.shape && calib.shape.length ? calib.shape : null;
      renderShapeChart(shapeCanvas, shape, (calib && calib.cone) || null);
      const note = document.getElementById("pfShapeNote");
      if (note) {
        // ⚠ 倍数**从产物现算**（V0.127.1）—— 写死的「1.2–1.4 倍」与产物实测（1.32–1.43）不符
        const ratio = shortEndRatioRange(calib, 1, 5);
        note.textContent = shape
          ? (ratio
              ? T(
                  "forecast.shape_note",
                  "类比形状在短期（1–5 交易日）相对正态锥为 {range} 倍（>1 表示更宽），到 10–20 日收敛。",
                  { range: ratio.text },
                )
              : T(
                  "forecast.shape_note_noratio",
                  "类比形状已加载（无法从产物算出相对正态锥的倍数），到 10–20 日收敛。",
                ))
          : T("forecast.shape_note_missing", "形状产物缺失 ⇒ 只画对数正态 √k 锥（退化基线）。");
      }
    }

    // ⚠ 「已知失效条件」第 4 条里的跨窗口倍数**现算**（V0.127.1）
    //   —— 以前写死「训练段 0.99 倍 / 近 600 段 1.27 倍」，
    //   产物重算后会静默变成假话（实测值已是 0.98 / 1.27）。
    //   找不到某个窗口 ⇒ 只写另一个；两个都没有 ⇒ 整段留空（句子的其余部分仍成立）。
    const failRatios = document.getElementById("pfFailShapeRatios");
    if (failRatios) {
      const train = windowRatioRange(calib, "train", 1, 5);
      const recent = windowRatioRange(calib, "recent_600", 1, 5);
      const one = function (w) {
        if (!w) return null;
        const r = w.k1 != null ? w.k1 : w.min;
        if (r == null || !isFinite(r)) return null;
        return {
          days: w.nDays || "—",
          ratio: r.toFixed(2),
        };
      };
      const tr = one(train);
      const rc = one(recent);
      // ⚠ 三个分支各用各的模板 —— 只缺一个窗口时不能共用双窗口模板，
      //   否则缺失的占位符会以字面量 "{recentDays}" 显示在页面上。
      if (tr && rc) {
        failRatios.textContent = T(
          "forecast.fail_shape_ratios",
          "（实测 k=1：训练段 {trainDays} 天 ≈{trainRatio} 倍；近 600 段 {recentDays} 天 ≈{recentRatio} 倍）",
          { trainDays: tr.days, trainRatio: tr.ratio, recentDays: rc.days, recentRatio: rc.ratio },
        );
      } else if (tr) {
        failRatios.textContent = T(
          "forecast.fail_shape_ratios_train",
          "（实测 k=1：训练段 {trainDays} 天 ≈{trainRatio} 倍）",
          { trainDays: tr.days, trainRatio: tr.ratio },
        );
      } else if (rc) {
        failRatios.textContent = T(
          "forecast.fail_shape_ratios_recent",
          "（实测 k=1：近 600 段 {recentDays} 天 ≈{recentRatio} 倍）",
          { recentDays: rc.days, recentRatio: rc.ratio },
        );
      } else {
        failRatios.textContent = "";
      }
    }

    return { reload: load };
  }

  /* ───────────────── 挂载：趋势页摘要卡 ───────────────── */

  async function mountSummaryCard() {
    const root = document.getElementById("pfSummaryCard");
    if (!root) return;
    const res = await fetchForecast({ target: TARGET, horizon: HORIZON, coverage: DEFAULT_COVERAGE });
    if (!res.ok) {
      root.innerHTML = '<div class="pf-empty">' +
        escapeHtml(T("forecast.load_failed", "⚠️ 取数失败：") + " " + res.error) + "</div>";
      return;
    }
    const data = res.data;
    const m = data.measured || {};
    const meas = m.out_of_sample != null ? m.out_of_sample : m.recent;
    // ⚠ 先销毁旧实例再换 innerHTML —— 否则旧 Chart 仍挂在被替换掉的 canvas 上（泄漏），
    //   而新 canvas 上再画一张时 Chart.js 的 canvas↔instance 映射会串。
    destroyChartOn(document.getElementById("pfSummaryChart"));
    root.innerHTML =
      '<div class="pf-sum-head">' +
        '<span class="pf-sum-title" data-i18n="forecast.summary_card_title">📐 未来 20 交易日金价区间导航线</span>' +
        '<a class="pf-sum-link" href="/price-forecast" data-i18n="forecast.summary_goto">详见区间预测页 →</a>' +
      '</div>' +
      '<div class="pf-sum-range"><span class="pf-sum-num">' +
        escapeHtml(formatRangeText(data)) +
      '</span> <span class="pf-sum-unit">' +
        escapeHtml(T("forecast.unit", "美元/盎司")) +
      '</span></div>' +
      '<div class="pf-sum-text">' +
        escapeHtml(summarySentence(data)) +
        " · " +
        escapeHtml(T("forecast.center_label", "中心（当前收盘，无漂移）") + " " + fmtPrice2(data.base_close)) +
        (meas != null
          ? " · " + escapeHtml(T("forecast.measured_label", "实测覆盖（样本外）") + " " + fmtPct(meas))
          : "") +
      "</div>" +
      '<div class="pf-chart-wrap pf-chart-sm"><canvas id="pfSummaryChart"></canvas></div>' +
      '<div class="pf-sum-chips">' +
        buildNoticeChips(data)
          .map((c) => '<span class="' + c.cls + '">' + escapeHtml(c.text) + "</span>")
          .join("") +
      "</div>";
    renderFanChart(document.getElementById("pfSummaryChart"), data, {});
  }

  /* ───────────────── 挂载：首页磁贴一行字 ───────────────── */

  async function mountTile() {
    const el = document.getElementById("fcTileRange");
    if (!el) return;
    const res = await fetchForecast({ target: TARGET, horizon: HORIZON, coverage: DEFAULT_COVERAGE });
    if (!res.ok) {
      el.textContent = T("forecast.tile_unavailable", "区间暂不可用（取数失败）");
      el.classList.add("is-warn");
      return;
    }
    const data = res.data;
    const m = data.measured || {};
    const meas = m.out_of_sample != null ? m.out_of_sample : m.recent;
    el.textContent = fmtPrice(data.lower) + " – " + fmtPrice(data.upper) +
      " " + T("forecast.unit", "美元/盎司") +
      (meas != null ? " · " + T("forecast.measured_label", "实测覆盖（样本外）") + " " + fmtPct(meas) : "");
  }

  /* ───────────────── 启动 ───────────────── */

  async function boot() {
    // ⚠ 等字典就绪再渲染 —— 否则首次打开非默认语言时，JS 拼的 DOM 会永久停在默认语言
    //   （记忆 i18n-init-await / i18n-imperative-render-race）。
    if (window.I18n && window.I18n.ready) {
      try { await window.I18n.ready; } catch (e) { /* 字典没就绪也继续 */ }
    }
    await mountConclusion();
    await mountSummaryCard();
    await mountTile();

    // 切语言后重渲染（JS 拼的 DOM 不在 i18n.apply 的扫描范围内）
    document.addEventListener("i18n:change", function () {
      mountConclusion();
      mountSummaryCard();
      mountTile();
    });
  }

  window.PM_PriceForecast = {
    TARGET: TARGET,
    HORIZON: HORIZON,
    COVERAGES: COVERAGES,
    DEFAULT_COVERAGE: DEFAULT_COVERAGE,
    fetchForecast: fetchForecast,
    fetchCalibration: fetchCalibration,
    renderFanChart: renderFanChart,
    renderShapeChart: renderShapeChart,
    renderCalibrationTable: renderCalibrationTable,
    summarySentence: summarySentence,
    formatRangeText: formatRangeText,
    mountConclusion: mountConclusion,
    mountSummaryCard: mountSummaryCard,
    mountTile: mountTile,
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
