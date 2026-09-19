/*!
 * backtest-chart.js —— 回测结果 3 张 Chart.js 图（V0.71.0 P3-a）
 *
 * 用法（在 backtest.html 末尾）：
 *   <script src="/static/backtest-chart.js" defer></script>
 *   <script>window.PM_Backtest.mount({ onRun: runBacktest });</script>
 *
 * 提供：
 *   PM_Backtest.mount(opts) 初始化绑定 3 张 canvas + 控件
 *   PM_Backtest.render(result) 渲染 API 返回的 BacktestResultOut
 *   PM_Backtest.debounced_run(fn, ms) 500ms 节流（前端 debounce + 后端 5 分钟）
 *
 * 设计：
 * - 自注入 CSS（与 resonance-card.js:37-64 同模式）
 * - 销毁旧 chart 实例再 new Chart()（仿 portfolio.html drawEquityChart 内存管理）
 * - ChartA11y.wrapChart 包裹（无障碍读屏）
 * - 命中 5 分钟节流：响应头 X-Backtest-Cached=true 时显示「已用缓存」角标
 */
(function () {
  "use strict";

  /* ───── 自注入 CSS ───── */
  function injectCSS() {
    if (document.getElementById("pm-backtest-css")) return;
    var s = document.createElement("style");
    s.id = "pm-backtest-css";
    s.textContent = [
      "#cachedBadge { position:absolute; top:8px; right:14px; z-index:5; font-size:11px; font-weight:700;",
      "  padding:4px 12px; border-radius:999px; background:#fff8e6; color:#946300; border:1px solid #ffd8a8;",
      "  display:none; }",
      "#cachedBadge.on { display:inline-block; }",
      ".bt-result-row { display:flex; justify-content:space-between; padding:8px 0; border-bottom:1px dashed var(--border); font-size:13px; }",
      ".bt-result-row:last-child { border-bottom:none; }",
      ".bt-result-row .nm { color:var(--muted); }",
      ".bt-result-row .vl { font-weight:600; }",
      ".bt-summary { display:grid; grid-template-columns:repeat(auto-fit, minmax(140px, 1fr)); gap:12px; margin-bottom:16px; }",
      ".bt-summary .card { background:var(--card); border:1px solid var(--border); border-radius:10px; padding:12px 14px; }",
      ".bt-summary .card .label { font-size:12px; color:var(--muted); margin-bottom:6px; }",
      ".bt-summary .card .value { font-size:20px; font-weight:600; }",
      ".bt-summary .card .extra { font-size:12px; color:var(--muted); margin-top:4px; }",
      ".bt-debounce { color:var(--muted); font-size:11px; margin-left:8px; }",
    ].join("\n");
    document.head.appendChild(s);
  }

  /* ───── chart 实例管理 ───── */
  var sharpeChart = null;
  var drawdownChart = null;
  var calibrationChart = null;
  var lastResult = null;

  function destroyCharts() {
    if (sharpeChart) { sharpeChart.destroy(); sharpeChart = null; }
    if (drawdownChart) { drawdownChart.destroy(); drawdownChart = null; }
    if (calibrationChart) { calibrationChart.destroy(); calibrationChart = null; }
  }

  /* ───── 渲染 ───── */
  function render(result) {
    if (!result) return;
    lastResult = result;

    // 节流缓存角标
    var badge = document.getElementById("cachedBadge");
    if (badge) {
      if (result.cached) {
        badge.textContent = "⏱ 已用 5 分钟内缓存（" + (result.cached_age_seconds || 0) + "s 前）";
        badge.classList.add("on");
      } else {
        badge.classList.remove("on");
      }
    }

    destroyCharts();

    // summary
    var s = result.summary || {};
    var cov = result.coverage || {};
    var sumEl = document.getElementById("btSummary");
    if (sumEl) {
      sumEl.innerHTML = [
        '<div class="card"><div class="label">总组合数</div><div class="value">' + (s.total_rows || 0) + '</div><div class="extra">tech × macro × news × bullish × bearish</div></div>',
        '<div class="card"><div class="label">最佳 Sharpe</div><div class="value up">' + (s.best_sharpe || 0).toFixed(2) + '</div><div class="extra">越高越好</div></div>',
        '<div class="card"><div class="label">最小最大回撤</div><div class="value">' + (s.best_max_drawdown || 0).toFixed(2) + '%</div><div class="extra">越低越好</div></div>',
        '<div class="card"><div class="label">平均命中率</div><div class="value">' + (((s.avg_win_rate || 0) * 100).toFixed(1)) + '%</div><div class="extra">阈值带命中率</div></div>',
        '<div class="card"><div class="label">覆盖期样本</div><div class="value">' + (cov.available_days || 0) + '</div><div class="extra">' + (cov.start_date || "-") + " ~ " + (cov.end_date || "-") + '</div></div>',
      ].join("");
    }

    // 命中详情表
    var tableEl = document.getElementById("btTable");
    if (tableEl && result.rows) {
      var html = '<tr style="background:var(--card)"><th style="padding:6px;text-align:right">tech</th><th style="padding:6px;text-align:right">macro</th><th style="padding:6px;text-align:right">news</th><th style="padding:6px;text-align:right">BULL</th><th style="padding:6px;text-align:right">BEAR</th><th style="padding:6px;text-align:right">Sharpe</th><th style="padding:6px;text-align:right">最大回撤%</th><th style="padding:6px;text-align:right">胜率</th><th style="padding:6px;text-align:right">样本</th></tr>';
      var rows = result.rows.slice().sort(function (a, b) { return (b.sharpe || 0) - (a.sharpe || 0); }).slice(0, 30);
      rows.forEach(function (r) {
        html += '<tr style="border-bottom:1px dashed var(--border)">'
          + '<td style="padding:4px;text-align:right">' + r.tech_w.toFixed(2) + '</td>'
          + '<td style="padding:4px;text-align:right">' + r.macro_w.toFixed(2) + '</td>'
          + '<td style="padding:4px;text-align:right">' + r.news_w.toFixed(2) + '</td>'
          + '<td style="padding:4px;text-align:right">' + r.bullish_threshold.toFixed(0) + '</td>'
          + '<td style="padding:4px;text-align:right">' + r.bearish_threshold.toFixed(0) + '</td>'
          + '<td style="padding:4px;text-align:right;font-weight:600;color:' + (r.sharpe >= 0 ? "var(--up)" : "var(--down)") + '">' + r.sharpe.toFixed(2) + '</td>'
          + '<td style="padding:4px;text-align:right">' + r.max_drawdown_pct.toFixed(2) + '</td>'
          + '<td style="padding:4px;text-align:right">' + (r.win_rate * 100).toFixed(1) + '%</td>'
          + '<td style="padding:4px;text-align:right">' + r.samples + '</td>'
          + '</tr>';
      });
      if (result.rows.length > 30) {
        html += '<tr><td colspan="9" style="padding:8px;text-align:center;color:var(--muted);font-size:11px">仅展示前 30 行（按 Sharpe 降序）</td></tr>';
      }
      tableEl.innerHTML = html;
    }

    // Sharpe 图：每行 (tech_w + macro_w + news_w) 作为 x 轴（取组合 hash 简化），y 轴 Sharpe
    var sCanvas = document.getElementById("sharpeChart");
    if (sCanvas && result.rows && result.rows.length) {
      var labels = result.rows.map(function (r, i) { return "#" + (i + 1); });
      sharpeChart = ChartA11y.wrapChart(sCanvas, {
        type: "bar",
        data: {
          labels: labels,
          datasets: [{
            label: "Sharpe",
            data: result.rows.map(function (r) { return r.sharpe; }),
            backgroundColor: result.rows.map(function (r) { return r.sharpe >= 0 ? "rgba(26,127,55,0.65)" : "rgba(201,42,42,0.65)"; }),
            borderColor: result.rows.map(function (r) { return r.sharpe >= 0 ? "#1a7f37" : "#c92a2a"; }),
            borderWidth: 1,
          }],
        },
        options: {
          responsive: true,
          plugins: { legend: { display: false }, tooltip: { callbacks: { title: function (ctx) { return "组合 " + ctx[0].label; } } } },
          scales: {
            x: { display: false },
            y: { beginAtZero: true, title: { display: true, text: "Sharpe（年化）" } },
          },
        },
      });
    }

    // 最大回撤图
    var dCanvas = document.getElementById("drawdownChart");
    if (dCanvas && result.rows && result.rows.length) {
      var labels2 = result.rows.map(function (r, i) { return "#" + (i + 1); });
      drawdownChart = ChartA11y.wrapChart(dCanvas, {
        type: "line",
        data: {
          labels: labels2,
          datasets: [{
            label: "最大回撤 %",
            data: result.rows.map(function (r) { return r.max_drawdown_pct; }),
            borderColor: "#c92a2a",
            backgroundColor: "rgba(201,42,42,0.1)",
            tension: 0.2,
            fill: true,
            pointRadius: 0,
          }],
        },
        options: {
          responsive: true,
          plugins: { legend: { display: false } },
          scales: {
            x: { display: false },
            y: { beginAtZero: true, title: { display: true, text: "最大回撤 %" } },
          },
        },
      });
    }

    // 校准曲线：5 桶（0-20/20-40/40-60/60-80/80-100），按 daily_snapshots.tech_index 等分桶
    // 取首组参数 (tech_w + macro_w + news_w) 的 score 序列 → 5 桶实际命中率
    var cCanvas = document.getElementById("calibrationChart");
    if (cCanvas) {
      var buckets = ["0-20", "20-40", "40-60", "60-80", "80-100"];
      var ideal = [10, 30, 50, 70, 90];  // 理论概率
      // 实际：基于首组 score 序列 + 命中 → 分桶统计
      var first = (result.rows || [])[0];
      var actual = [0, 0, 0, 0, 0].map(function () { return 0; });
      var total = [0, 0, 0, 0, 0];
      if (first && result._bucket_data) {
        var bucketData = result._bucket_data;  // {scores: [], hits: []}
        for (var i = 0; i < bucketData.scores.length; i++) {
          var sc = bucketData.scores[i];
          var idx = Math.min(4, Math.floor(sc / 20));
          total[idx]++;
          if (bucketData.hits[i]) actual[idx]++;
        }
        for (var k = 0; k < 5; k++) {
          actual[k] = total[k] ? Math.round(actual[k] / total[k] * 100) : 0;
        }
      } else {
        // 没有 _bucket_data：用 first.win_rate 兜底（不展示 actual，全为 0）
        actual = [0, 0, 0, 0, 0];
      }

      calibrationChart = ChartA11y.wrapChart(cCanvas, {
        type: "line",
        data: {
          labels: buckets,
          datasets: [
            { label: "理论概率 %", data: ideal, borderColor: "#946300", borderDash: [5, 5], pointRadius: 4, tension: 0 },
            { label: "实际命中率 %", data: actual, borderColor: "#1d4ed8", backgroundColor: "rgba(29,78,216,0.1)", pointRadius: 5, tension: 0, fill: false },
          ],
        },
        options: {
          responsive: true,
          plugins: { legend: { position: "top" } },
          scales: {
            y: { min: 0, max: 100, title: { display: true, text: "命中率 %" } },
          },
        },
      });
    }

    // 警告：样本不足
    if (cov.sample_warning && (cov.available_days || 0) < 20) {
      var warn = document.getElementById("btWarn");
      if (warn) {
        warn.innerHTML = '<div class="source-bar source-warn">⚠️ 样本仅 ' + cov.available_days + ' 天（&lt;20），回测结果仅供参考</div>';
      }
    }
  }

  /* ───── 控件绑定 ───── */
  function mount(opts) {
    injectCSS();
    opts = opts || {};
    var onRun = opts.onRun || function () {};

    var runBtn = document.getElementById("runBtn");
    if (runBtn) {
      runBtn.addEventListener("click", function () {
        runBtn.disabled = true;
        runBtn.textContent = "计算中…";
        Promise.resolve(onRun())
          .catch(function (e) {
            console.error("backtest run failed", e);
            var errEl = document.getElementById("btWarn");
            if (errEl) errEl.innerHTML = '<div class="source-bar source-bad">❌ 回测失败：' + (e.message || "未知错误") + '</div>';
          })
          .then(function () {
            runBtn.disabled = false;
            runBtn.textContent = "▶ 立即回测";
          });
      });
    }

    // 任意控件变更 → 标记"参数已变"（不自动 run，等用户点）
    var inputs = document.querySelectorAll("#paramsPanel input, #paramsPanel select");
    inputs.forEach(function (el) {
      el.addEventListener("change", function () {
        try { window.TL && window.TL.track && window.TL.track("backtest_param_change", { field: el.id || el.name }); } catch (_) {}
      });
    });
  }

  /* ───── 500ms 节流（前端 debounce） ───── */
  var debounceTimer = null;
  function debouncedRun(fn, ms) {
    ms = ms || 500;
    if (debounceTimer) clearTimeout(debounceTimer);
    debounceTimer = setTimeout(function () { debounceTimer = null; fn(); }, ms);
  }

  /* ───── 暴露 API ───── */
  window.PM_Backtest = {
    mount: mount,
    render: render,
    debouncedRun: debouncedRun,
    destroyCharts: destroyCharts,
    getLastResult: function () { return lastResult; },
  };
})();