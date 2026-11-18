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
 *     插入 <details><summary>数据表</summary><table>...</table></details>。
 *     ⚠ V0.127.2：落点**不一定是 canvas 后面** —— 若图表容器是固定高度的，
 *       <details> 会溢出容器（收起压住下方文字 / 展开浮在页面上方），
 *       此时自动挪到**容器之后**。详见 insertTableFallback 内的说明。
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

  /* ── V0.127.2：fallback 的**落点** ──────────────────────────────────────
   * 老做法：<details> 插在 canvas 后面（canvas.parentNode 里）。
   * ⚠ 那等于把它塞进**图表容器**，而图表容器几乎都是**固定高度**的盒子：
   *     .pf-chart-wrap{height:380px} / .chart-wrap{height:300px} / 内联 height:320px …
   *   容器的高度是给 canvas 留的，后面的 <details> 只能**溢出容器**：
   *     · 收起时：summary 压住容器下方第一行文字（实测把图表说明压没了）；
   *     · 展开时：整张数据表浮在页面上方，把图表/说明/下一张表全糊住
   *       （/price-forecast 实测截图：扇形图、形状图、校准表全被盖住）。
   *   ⇒ 规则改成：**实测溢出容器 ⇒ 挪到容器之后**（同一父级里）⇒ 回到正常文档流，
   *     展开时把下方内容**推下去**，而不是盖住它。
   *   ⚠ 挪动后 <details> 不再是 canvas 的兄弟节点 ⇒ 幂等判据必须换成 id 标记
   *     （老判据「nextElementSibling 是 fallback」会漏判 ⇒ 重复插入）。
   * -------------------------------------------------------------------- */
  var fallbackSeq = 0;

  function overflowsHost(el, host) {
    if (!el || !host || !host.getBoundingClientRect) return false;
    var hb = host.getBoundingClientRect();
    var eb = el.getBoundingClientRect();
    if (!hb.height || !eb.height) return false;
    return eb.bottom > hb.bottom + 1 || eb.right > hb.right + 1;
  }

  function placeFallback(details, host) {
    if (!details || !host) return;
    if (details.parentNode !== host) return; // 已经在容器外了 —— 不用再动
    if (!overflowsHost(details, host)) return; // 没溢出 ⇒ 留在容器里（老行为不变）
    if (!host.parentNode) return;
    host.parentNode.insertBefore(details, host.nextSibling);
  }

  function insertTableFallback(canvas, columns, rows) {
    if (!canvas || !columns || !rows) return;
    // 幂等：同一个 canvas 只挂一张表。
    // ⚠ 不能只看「canvas.nextElementSibling 是 fallback」—— V0.127.2 起
    //   fallback 会被挪到**图表容器之后**，那时它不再是 canvas 的兄弟节点。
    var prevId = canvas.getAttribute("data-pm-a11y-table");
    if (prevId && document.getElementById(prevId)) return;
    // 同源旧表（canvas 被重建、但旧表还留在页面里）⇒ 先清掉，避免两份
    // ⚠ 只在 canvas **有 id** 时才清 —— 否则多个无 id 的 canvas 会互删对方的表
    var cid = canvas.id || "";
    if (cid) {
      var olds = document.querySelectorAll("details.pm-chart-fallback[data-pm-a11y-for]");
      for (var i = 0; i < olds.length; i++) {
        if (olds[i].getAttribute("data-pm-a11y-for") === cid && olds[i].parentNode) {
          olds[i].parentNode.removeChild(olds[i]);
          break;
        }
      }
    }
    var details = document.createElement("details");
    details.className = "pm-chart-fallback";
    details.setAttribute("data-pm-a11y-for", cid);
    fallbackSeq += 1;
    details.id =
      "pm-a11y-table-" + (cid ? cid.replace(/[^\w-]+/g, "-") : "chart") + "-" + fallbackSeq;
    canvas.setAttribute("data-pm-a11y-table", details.id);
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
    var host = canvas.parentNode;
    if (!host) return;
    host.insertBefore(details, canvas.nextSibling);
    placeFallback(details, host);
    // ⚠ Chart.js 的初次 resize 可能是异步的 —— 下一帧再核一次，
    //   否则「插入那一刻 canvas 还没量到尺寸」会漏判，details 就留在固定高度容器里。
    if (typeof requestAnimationFrame === "function") {
      requestAnimationFrame(function () {
        placeFallback(details, host);
      });
    }
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