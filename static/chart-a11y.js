/* =========================================================================
 * chart-a11y.js — V0.69.0 Chart.js 画布可访问性封装
 *
 * 设计目标：让屏幕阅读器能读懂图表语义（每个 canvas 都被打上 role="img" + aria-label），
 *   并为 sighted / keyboard 用户附加一份可展开的 <details><table> 数据 fallback。
 *
 * 合约：
 *   window.ChartA11y.wrapChart(canvas, opts)
 *     opts = { label: string, summaryId?: string, table?: { columns: string[], rows: any[][] } }
 *
 *   window.ChartA11y.patchTrendChartInjection()
 *     trend.html:626 动态注入 trendChart 时同步打 a11y 标记 + table fallback
 *
 *   window.ChartA11y.describeBy(canvas, tableId)
 *     central_bank.html: _cbChart → 已存在的 #detailBody 表，aria-describedby 指向它
 *
 *   window.ChartA11y.insertTableFallback(canvas, columns, rows)
 *     在 canvas 后插入 <details><summary>数据表</summary><table>...</table></details>
 * ========================================================================= */
(function () {
  "use strict";

  function wrapChart(canvas, opts) {
    if (!canvas || canvas.getAttribute("role") === "img") return;
    opts = opts || {};
    var label = opts.label || "图表";
    if (opts.summaryId) {
      var sum = document.getElementById(opts.summaryId);
      if (sum) label += "：" + (sum.textContent || "").replace(/\s+/g, " ").trim();
    }
    canvas.setAttribute("role", "img");
    canvas.setAttribute("aria-label", label);
    canvas.setAttribute("tabindex", "0");
    if (opts.table) insertTableFallback(canvas, opts.table.columns, opts.table.rows);
  }

  function describeBy(canvas, tableId) {
    if (!canvas || !tableId) return;
    if (canvas.getAttribute("aria-describedby") === tableId) return;
    canvas.setAttribute("role", "img");
    canvas.setAttribute("aria-describedby", tableId);
    canvas.setAttribute("tabindex", "0");
    var t = document.getElementById(tableId);
    if (t) {
      // V0.69.0：传进来的 id 也可能是 tbody；fallback 到最近祖先 table 的 caption
      var capHost = t.tagName === "TABLE" ? t : (t.closest("table") || t);
      var head = (capHost.querySelector("caption") || {}).textContent || "";
      if (head) canvas.setAttribute("aria-label", head.trim());
    }
  }

  function insertTableFallback(canvas, columns, rows) {
    if (!canvas || !columns || !rows) return;
    if (canvas.nextElementSibling && canvas.nextElementSibling.classList.contains("pm-chart-fallback")) return;
    var details = document.createElement("details");
    details.className = "pm-chart-fallback";
    var summary = document.createElement("summary");
    summary.textContent = "数据表（辅助技术可读）";
    details.appendChild(summary);
    var table = document.createElement("table");
    table.style.fontSize = "12px";
    table.style.marginTop = "6px";
    var thead = document.createElement("thead");
    var trH = document.createElement("tr");
    columns.forEach(function (c) {
      var th = document.createElement("th");
      th.textContent = c;
      trH.appendChild(th);
    });
    thead.appendChild(trH);
    table.appendChild(thead);
    var tbody = document.createElement("tbody");
    rows.forEach(function (r) {
      var tr = document.createElement("tr");
      r.forEach(function (cell) {
        var td = document.createElement("td");
        td.textContent = cell == null ? "—" : String(cell);
        tr.appendChild(td);
      });
      tbody.appendChild(tr);
    });
    table.appendChild(tbody);
    details.appendChild(table);
    canvas.parentNode.insertBefore(details, canvas.nextSibling);
  }

  // 用安全版替换前面的（避免双重写入）
  function patchTrendChartInjection() {
    var chartArea = document.getElementById("chartArea");
    if (!chartArea || !window.MutationObserver) return;
    var observer = new MutationObserver(function () {
      var c = document.getElementById("trendChart");
      if (c && c.getAttribute("role") !== "img") {
        wrapChart(c, {
          label: "近 60 天纽约金趋势指数图（实际收盘 + 移动均线 5/20/40 日）",
          summaryId: "summary"
        });
      }
    });
    observer.observe(chartArea, { childList: true, subtree: false });
  }

  window.ChartA11y = {
    wrapChart: wrapChart,
    patchTrendChartInjection: patchTrendChartInjection,
    describeBy: describeBy,
    insertTableFallback: insertTableFallback
  };
})();