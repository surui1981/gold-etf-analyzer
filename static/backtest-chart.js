/*!
 * backtest-chart.js —— 回测结果 3 张 Chart.js 图（V0.71.0 P3-a）
 *
 * 用法（在 backtest.html 末尾，必须在调用 mount() 的脚本【之前】同步加载）：
 *   <script src="/static/backtest-chart.js"></script>
 *   <script>window.PM_Backtest.mount({ onRun: runBacktest });</script>
 *
 * 注意：本脚本【不可加 defer】。defer 会在 DOM 解析完成后才执行，而调用方是在内联
 *   脚本的解析期就调用 window.PM_Backtest.mount() → 此刻 PM_Backtest 尚未定义，
 *   抛 TypeError 并中断整段内联脚本（按钮监听 / 首次回测 / 控件监听全部失绑）。
 *   脚本位于 </body> 之前，同步加载时 DOM 已就绪，无需等待。
 *
 * 提供：
 *   PM_Backtest.mount(opts) 初始化绑定 3 张 canvas + 控件
 *   PM_Backtest.render(result) 渲染 API 返回的 BacktestResultOut
 *   PM_Backtest.debounced_run(fn, ms) 500ms 节流（前端 debounce + 后端 5 分钟）
 *
 * 设计：
 * - 自注入 CSS（与 resonance-card.js:37-64 同模式）
 * - 销毁旧 chart 实例再 new Chart()（仿 portfolio.html drawEquityChart 内存管理）
 * - 先 new Chart(ctx, cfg) 创建实例，再调 ChartA11y.wrapChart(canvas, { label })
 *   补无障碍属性 —— wrapChart 只负责打 aria 属性，本身【不创建图表、也不返回实例】
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
      // V0.79.0 Step G Commit 3：高级模式面板 + 异步进度条 CSS
      ".adv-panel { background:var(--card); border:1px dashed var(--border); border-radius:10px; padding:14px 16px; margin:12px 0; font-size:12px; }",
      ".adv-panel > summary { cursor:pointer; font-size:13px; font-weight:600; color:var(--accent); list-style:none; padding:4px 0; }",
      ".adv-panel > summary::-webkit-details-marker { display:none; }",
      ".adv-panel > summary::before { content:'▸ '; font-size:11px; }",
      ".adv-panel[open] > summary::before { content:'▾ '; }",
      ".adv-panel .adv-enable-row { display:flex; gap:18px; flex-wrap:wrap; margin:10px 0 6px; font-size:12px; color:var(--muted); }",
      ".adv-panel .adv-enable-row label { display:flex; align-items:center; gap:6px; cursor:pointer; }",
      ".adv-panel .adv-enable-row input[type=\"checkbox\"] { accent-color:var(--accent); }",
      ".grp-grid { display:grid; grid-template-columns:repeat(5, 1fr); gap:8px; margin:8px 0; }",
      ".grp-grid .grp-cell { display:flex; flex-direction:column; gap:3px; background:var(--bg); border:1px solid var(--border); border-radius:8px; padding:8px 10px; }",
      ".grp-grid .grp-label { font-size:11px; color:var(--muted); font-weight:600; }",
      ".grp-grid input[type=\"number\"] { border:1px solid var(--border); border-radius:6px; padding:3px 6px; background:var(--card); color:var(--text); font-size:13px; font-weight:600; text-align:right; width:100%; }",
      ".grp-grid input[type=\"number\"]:focus { outline:1px solid var(--accent); }",
      ".adv-hint { font-size:12px; margin:6px 0; padding:4px 10px; border-radius:6px; }",
      ".adv-hint.ok { background:#e6f4ea; color:var(--down); }",
      ".adv-hint.bad { background:#ffe9e9; color:var(--up); }",
      ".run-btn-async { background:transparent; color:var(--accent); border:1px solid var(--accent); padding:6px 14px; border-radius:8px; font-weight:600; font-size:13px; cursor:pointer; margin-left:8px; }",
      ".run-btn-async:disabled { opacity:0.5; cursor:not-allowed; }",
      ".progress-bar { position:relative; height:18px; background:var(--bg); border:1px solid var(--border); border-radius:10px; overflow:hidden; margin:6px 0; }",
      ".progress-bar .progress-fill { height:100%; width:0%; background:var(--accent); transition:width 0.4s ease; }",
      ".progress-bar .progress-fill.bad { background:var(--up); }",
      ".progress-bar .progress-msg { position:absolute; inset:0; display:flex; align-items:center; justify-content:center; font-size:11px; color:var(--text); font-weight:600; mix-blend-mode:difference; }",
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
      // V0.79.0：usable=False 时指标是填充值，卡片必须**在标题里就说清**，
      // 否则「最佳 Sharpe 0.00」配上绿色 up 样式会被当成「策略表现差」而非
      // 「根本没算出来」—— 这正是原缺陷的伤害路径。
      var notMeasured = (s.usable === false || cov.usable === false);
      var suffix = notMeasured ? "（填充值）" : "";
      var upCls = notMeasured ? "" : " up";
      sumEl.innerHTML = [
        '<div class="card"><div class="label">总组合数</div><div class="value">' + (s.total_rows || 0) + '</div><div class="extra">tech × macro × news × bullish × bearish</div></div>',
        '<div class="card"><div class="label">最佳 Sharpe' + suffix + '</div><div class="value' + upCls + '">' + (s.best_sharpe || 0).toFixed(2) + '</div><div class="extra">' + (notMeasured ? "缺少价格数据，未计算" : "越高越好") + '</div></div>',
        '<div class="card"><div class="label">最小最大回撤' + suffix + '</div><div class="value">' + (s.best_max_drawdown || 0).toFixed(2) + '%</div><div class="extra">' + (notMeasured ? "缺少价格数据，未计算" : "越低越好") + '</div></div>',
        '<div class="card"><div class="label">平均命中率' + suffix + '</div><div class="value">' + (((s.avg_win_rate || 0) * 100).toFixed(1)) + '%</div><div class="extra">' + (notMeasured ? "中性行在零收益下全部命中，非真实命中率" : "阈值带命中率") + '</div></div>',
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
      sharpeChart = new Chart(sCanvas.getContext("2d"), {
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
      ChartA11y.wrapChart(sCanvas, { label: "各组参数的年化 Sharpe 柱状图（共 " + result.rows.length + " 组，绿正红负）" });
    }

    // 最大回撤图
    var dCanvas = document.getElementById("drawdownChart");
    if (dCanvas && result.rows && result.rows.length) {
      var labels2 = result.rows.map(function (r, i) { return "#" + (i + 1); });
      drawdownChart = new Chart(dCanvas.getContext("2d"), {
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
      ChartA11y.wrapChart(dCanvas, { label: "各组参数的最大回撤折线图（越低越好，共 " + result.rows.length + " 组）" });
    }

    // 校准曲线：5 桶（0-20/20-40/40-60/60-80/80-100），按 daily_snapshots.tech_index 等分桶
    // 取首组参数 (tech_w + macro_w + news_w) 的 score 序列 → 5 桶实际命中率
    var cCanvas = document.getElementById("calibrationChart");
    if (cCanvas) {
      var buckets = ["0-20", "20-40", "40-60", "60-80", "80-100"];
      // V0.77.1 A5：这条线是「完美校准」的参照，取值就是每桶的分数中值，不由任何模型算出。
      // 原先注释与图例都只写「理论概率」，客户会把它当成模型输出的概率来评估可靠性。
      var baseline = [10, 30, 50, 70, 90];
      var first = (result.rows || [])[0];
      var bucketData = result._bucket_data;
      var hasBuckets = !!(first && bucketData && bucketData.scores && bucketData.scores.length);
      var actual = [0, 0, 0, 0, 0];
      var total = [0, 0, 0, 0, 0];
      if (hasBuckets) {
        for (var i = 0; i < bucketData.scores.length; i++) {
          var sc = bucketData.scores[i];
          var idx = Math.min(4, Math.floor(sc / 20));
          total[idx]++;
          if (bucketData.hits[i]) actual[idx]++;
        }
        for (var k = 0; k < 5; k++) {
          // 桶内无样本时留 null（折线断开）而不是 0 —— 0% 是一个结论，「无样本」不是
          actual[k] = total[k] ? Math.round(actual[k] / total[k] * 100) : null;
        }
      }

      // V0.77.1 A5：没有分桶数据时【整条】实际命中率曲线都不加进图表。
      // 原实现把 actual 全置 0 后照样画 —— 一条贴在 0 上的实线，客户读到的结论是
      // 「模型的命中率是 0」，而事实是「这次没返回分桶数据」。缺数据 ≠ 命中率 0%。
      //
      // ⚠ 实测（V0.77.1 复核）：`_bucket_data` 在后端【从未存在过】——
      //   `src/app/services/backtest.py:44` 定义了 _CALIBRATION_BUCKETS 五桶常量
      //   （注释写「与 review._calibration 共享形状」）但全仓无任何调用点，
      //   `BacktestResultOut` 也没有分桶字段。也就是说这条「实际命中率」自 V0.71.0 起
      //   一直是恒为 0 的假线，不是「偶尔缺数据」。本改动因此会让图上只剩基准线 ——
      //   这是有意为之：缺失要看得见，假线比缺线更危险。
      //   前端判断已按「后端补上字段即自动生效」写好，补后端分桶输出是后续独立事项。
      var datasets = [
        { label: "完美校准基准线 %", data: baseline, borderColor: "#946300", borderDash: [5, 5], pointRadius: 4, tension: 0 },
      ];
      if (hasBuckets) {
        datasets.push(
          { label: "实际命中率 %", data: actual, borderColor: "#1d4ed8", backgroundColor: "rgba(29,78,216,0.1)", pointRadius: 5, tension: 0, fill: false },
        );
      }

      calibrationChart = new Chart(cCanvas.getContext("2d"), {
        type: "line",
        data: { labels: buckets, datasets: datasets },
        options: {
          responsive: true,
          plugins: { legend: { position: "top" } },
          scales: {
            y: { min: 0, max: 100, title: { display: true, text: "命中率 %" } },
          },
        },
      });
      var calLabel = hasBuckets
        ? "阈值带命中率校准曲线（完美校准基准线 vs 实际命中率，5 个分数桶）"
        : "阈值带校准基准线（5 个分数桶）；回测接口未提供分桶命中率数据，无法绘制实际命中率曲线";
      ChartA11y.wrapChart(cCanvas, { label: calLabel });
      // wrapChart 对已标记过的画布会早退，重跑回测时 label 不会刷新 —— 这里强制覆盖语义
      cCanvas.setAttribute("aria-label", calLabel);

      // V0.77.1 A5：把两条线的含义写在图下（原图只有图例，没有一句解释）
      var calNote = document.getElementById("calibrationNote");
      if (calNote) {
        calNote.textContent = hasBuckets
          ? "金色虚线是「完美校准基准线」—— 5 个桶的分数中值（10 / 30 / 50 / 70 / 90），是理想参照，并非模型算出的概率；蓝色实线才是实际命中率。两线越贴合，说明分值越有区分度。"
          : "金色虚线是「完美校准基准线」—— 5 个桶的分数中值（10 / 30 / 50 / 70 / 90），是理想参照，并非模型算出的概率。本图当前没有「实际命中率」曲线：回测接口未提供分桶命中率数据 —— 缺数据不等于命中率为 0%。";
        calNote.style.display = "block";
      }
    }

    // 警告：结果不可用 / 样本不足
    // V0.79.0：此前条件写死 `available_days < 20`，于是「快照充足但价格日历为空」
    // 这类**静默假结果**（Sharpe 恒 0、命中率虚高）完全不告警 —— 而它恰恰是
    // 最需要告警的一类：数字看着正常，实际不是回测结论。
    // 故改为：usable=False 走「结果不可用」红色警示（说明根因），
    // 否则才按样本天数提示「仅供参考」。
    var warnEl = document.getElementById("btWarn");
    if (warnEl) {
      if (cov.usable === false) {
        warnEl.innerHTML = '<div class="source-bar source-warn">⚠️ <strong>回测结果不可用</strong>：'
          + (cov.note || "缺少判定对错所需的价格数据")
          + '<br>下列 Sharpe / 命中率是<b>填充值而非实测值</b>，请勿据此判断策略优劣。'
          + '需先在「复盘」页执行价格回填（该页会把收盘价写入价格日历），再重跑回测。</div>';
        warnEl.style.display = "block";
      } else if (cov.sample_warning && (cov.available_days || 0) < 20) {
        warnEl.innerHTML = '<div class="source-bar source-warn">⚠️ 样本仅 ' + cov.available_days + ' 天（&lt;20），回测结果仅供参考</div>';
        warnEl.style.display = "block";
      } else {
        warnEl.innerHTML = "";
        warnEl.style.display = "none";
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