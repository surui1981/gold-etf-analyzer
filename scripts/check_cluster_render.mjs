/**
 * 聚类改造行为验证（V0.77.0）—— scripts/check_cluster_render.mjs
 *
 * 为什么需要它：`check_static_js.py` 只做「语法 / 未定义调用 / DOM id」三类静态检查，
 * 查不出「渲染出来的 HTML 结构对不对」；而聚类改造改的正是渲染逻辑 —— 比如把 8 张卡
 * 分成 3 组、把 6 个数据源从两处渲染合并到一处。这类改动语法完全正确、DOM id 一个不差，
 * 静态门禁全绿，却可能让分组根本不出现（本次开发中就出现过提取到函数定义却没调用、
 * 结果 innerHTML 为空的假绿）。
 *
 * 做法：从各页源码里**提取真实的聚类代码块**，用最小 DOM 桩 + mock 数据在 Node 里
 * 真实执行，再断言产出的 HTML 结构（簇数量 / 簇标题 / 卡片数 / 分组顺序）。
 *
 * 用法：node scripts/check_cluster_render.mjs   （exit 0 = 通过）
 */
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const STATIC_DIR = join(dirname(fileURLToPath(import.meta.url)), "..", "static");

let pass = 0;
let fail = 0;
const ok = (name, cond, detail) => {
  if (cond) {
    pass++;
    console.log("  [OK]   " + name);
  } else {
    fail++;
    console.log("  [FAIL] " + name + (detail ? "  :: " + detail : ""));
  }
};

function read(name) {
  return readFileSync(join(STATIC_DIR, name), "utf8");
}
function sliceBetween(src, startMark, endMark) {
  const i = src.indexOf(startMark);
  if (i < 0) throw new Error("未找到起始标记：" + startMark);
  const j = src.indexOf(endMark, i);
  if (j < 0) throw new Error("未找到结束标记：" + endMark);
  return src.slice(i, j + endMark.length);
}
/** 最小 DOM 桩：只支持按 id 取元素 + innerHTML 存储（足够验证「渲染出了什么」） */
function makeDoc() {
  const store = {};
  return {
    getElementById(id) {
      if (!store[id]) store[id] = { id, innerHTML: "", textContent: "" };
      return store[id];
    },
    querySelector(sel) {
      return this.getElementById(String(sel).replace(/^#/, "").split(/\s/)[0]);
    },
  };
}
const countOf = (html, re) => (html.match(re) || []).length;

console.log("=".repeat(70));
console.log("V0.77.0 聚类改造 · 渲染行为验证");
console.log("=".repeat(70));

// ── 1. trend.html：#cards 8 张 KPI 卡 → 3 组（价格 / 涨跌 / 均线） ──
{
  console.log("\n[1] trend.html  #cards —— 8 张卡应聚成 3 组");
  const src = read("trend.html");
  const code = sliceBetween(src, "const cardGroups = [", ').join("");');
  const m = {
    end_price: 2650.5,
    high: 2700,
    low: 2600,
    change_pct_1d: 1.2,
    change_pct_5d: -0.5,
    change_pct: 2.1,
    ma20: 2640,
    ma40: 2620,
  };
  const fn = new Function(
    "m",
    "unit",
    "isUp",
    "document",
    code + "\nreturn document.getElementById('cards').innerHTML;"
  );
  const html = fn(m, "美元/盎司", true, makeDoc());
  const titles = [...html.matchAll(/pmc-grid-title">([^<]+)</g)].map((x) => x[1]);
  ok("聚成 3 组", titles.length === 3, "实际 " + JSON.stringify(titles));
  ok("组名为 价格/涨跌/均线", titles.join(",") === "价格,涨跌,均线", titles.join(","));
  ok("8 张卡一张不少", countOf(html, /class="card"/g) === 8, String(countOf(html, /class="card"/g)));
  ok("最新价 在 MA20 之前（顺序合理）", html.indexOf("最新价") < html.indexOf("MA20"));
  ok("数值类样式为 .value", countOf(html, /class="value/g) === 8, String(countOf(html, /class="value/g)));
}

// ── 2. trend.html：#sgeCards 6 张卡 → 2 组 ──
{
  console.log("\n[2] trend.html  #sgeCards —— 6 张卡应聚成 2 组");
  const src = read("trend.html");
  const code = sliceBetween(
    src,
    'document.getElementById("sgeCards").innerHTML = [',
    '    ).join("");'
  );
  const m = { end_price: 612.34, high: 620, low: 600, change_pct: 1.5 };
  const pct = (v) => (v == null ? "—" : Number(v).toFixed(2) + "%");
  const cls = (v) => (v >= 0 ? "up" : "down");
  const fn = new Function(
    "m",
    "pct",
    "cls",
    "d1",
    "d5",
    "isUp",
    "document",
    code + "\nreturn document.getElementById('sgeCards').innerHTML;"
  );
  const html = fn(m, pct, cls, 0.4, -0.2, true, makeDoc());
  const titles = [...html.matchAll(/pmc-grid-title">([^<]+)</g)].map((x) => x[1]);
  ok("聚成 2 组", titles.length === 2, "实际 " + JSON.stringify(titles));
  ok("组名为 价格/涨跌", titles.join(",") === "价格,涨跌", titles.join(","));
  ok("6 张卡一张不少", countOf(html, /class="card"/g) === 6, String(countOf(html, /class="card"/g)));
}

// ── 3. trades.html：renderSummary 6 张 KPI → 2 簇 ──
{
  console.log("\n[3] trades.html  renderSummary —— 6 张 KPI 应聚成 2 簇");
  const src = read("trades.html");
  const code = sliceBetween(src, "function renderSummary(s) {", "\n  }");
  const doc = makeDoc();
  const fn = new Function(
    "s",
    "signCls",
    "fmtMoney",
    "signText",
    "esc",
    "$",
    code + "\nrenderSummary(s);\nreturn $('kpiArea').innerHTML;"
  );
  const s = {
    count: 12,
    buy_count: 7,
    sell_count: 5,
    buy_amount: 100000,
    sell_amount: 80000,
    net_amount: 20000,
    total_fee: 35.5,
    realized_pnl: 5555.5,
  };
  const html = fn(
    s,
    () => "",
    (v) => String(v),
    (v) => String(v),
    (x) => String(x),
    (id) => doc.getElementById(id)
  );
  ok("聚成 2 簇", countOf(html, /class="pmc-cluster"/g) === 2, String(countOf(html, /class="pmc-cluster"/g)));
  ok("簇标题为 成交规模 / 成本与收益", html.includes("成交规模") && html.includes("成本与收益"));
  ok("6 张 KPI 一张不少", countOf(html, /class="kpi"/g) === 6, String(countOf(html, /class="kpi"/g)));
  ok("计数徽标 4 项 / 2 项", html.includes(">4 项<") && html.includes(">2 项<"));
}

// ── 4. data-health.html：6 个数据源 → 2 组（黄金/白银），状态与时效同卡 ──
{
  console.log("\n[4] data-health.html  renderSourceGroups —— 6 源应聚成 2 组、含时效摘要");
  const src = read("data-health.html");
  const code = sliceBetween(src, "  var SOURCE_GROUPS = [", "\n  }");
  const doc = makeDoc();
  const SOURCE_LABELS = {
    etf: "黄金 ETF（华安 518880）",
    sge: "上海金（SGE Au99.99）",
    ny: "纽约金（COMEX GC）",
    silver_etf: "白银 ETF（易方达 562800）",
    silver_gram: "白银克重（上海银）",
    silver_ny: "纽约白银（COMEX SI）",
  };
  const STATUS_LABELS = {
    live: { txt: "实时", cls: "live", badge: "badge-live" },
    mock: { txt: "演示", cls: "mock", badge: "badge-mock" },
    unknown: { txt: "未知", cls: "unknown", badge: "badge-unknown" },
  };
  const safeText = (v) => String(v == null ? "" : v);
  const fmtAge = (v) => (v == null ? "—" : v + " 分钟");
  const _t = (k, fallback) => fallback;
  const fn = new Function(
    "document",
    "healthData",
    "freshData",
    "SOURCE_LABELS",
    "STATUS_LABELS",
    "safeText",
    "fmtAge",
    "_t",
    code +
      "\nrenderSourceGroups(healthData, freshData);" +
      "\nreturn document.getElementById('sourceGroups').innerHTML;"
  );
  const health = { sources: { etf: "live", sge: "live", ny: "mock", silver_etf: "live", silver_gram: "live", silver_ny: "live" } };
  const mk = (date, age, sess) => ({
    status: "live",
    data_date: date,
    age_minutes: age,
    session: { state_label: sess },
    freshness_label: "实时",
  });
  const fresh = {
    markets: {
      etf: mk("2026-09-30", 12, "盘中"),
      sge: mk("2026-09-30", 45, "盘后"),
      ny: mk("2026-09-30", 600, "盘后"),
      silver_etf: mk("2026-09-30", 12, "盘中"),
      silver_gram: mk("2026-09-30", 45, "盘后"),
      silver_ny: mk("2026-09-30", 600, "盘后"),
    },
  };
  const html = fn(doc, health, fresh, SOURCE_LABELS, STATUS_LABELS, safeText, fmtAge, _t);
  const heads = [...html.matchAll(/pmc-cluster-head">([^<]+)</g)].map((x) => x[1]);
  ok("聚成 2 组", heads.length === 2, "实际 " + JSON.stringify(heads));
  ok("组名为 黄金/白银", heads.join(",") === "黄金,白银", heads.join(","));
  ok("6 个数据源各出现一次", countOf(html, /class="market-card/g) === 6, String(countOf(html, /class="market-card/g)));
  ok("每张卡都带时效摘要（截止/分钟）", countOf(html, /截止 2026-09-30/g) === 6, String(countOf(html, /截止 2026-09-30/g)));
  ok("不再暴露内部键名（旧「键: etf」已去除）", !html.includes("键:"));
  ok("两组各 3 个源（计数徽标）", countOf(html, /pmc-count">3</g) === 2);
}

// ── 5. review.html：静态结构断言（Tab 分面） ──
{
  console.log("\n[5] review.html  统计分面 Tab —— 静态结构");
  const src = read("review.html");
  ok("3 个 tab", countOf(src, /class="pmc-tab"/g) === 3, String(countOf(src, /class="pmc-tab"/g)));
  ok("3 个 tabpanel", countOf(src, /class="pmc-tabpanel"/g) === 3, String(countOf(src, /class="pmc-tabpanel"/g)));
  ok("两个非默认面板初始 hidden", countOf(src, /class="pmc-tabpanel"[^>]*hidden>/g) === 2, String(countOf(src, /class="pmc-tabpanel"[^>]*hidden>/g)));
  ok("切面容器 #dirBars/#hzBars/#calBars 仍在", src.includes('id="dirBars"') && src.includes('id="hzBars"') && src.includes('id="calBars"'));
  ok("已安装 Tab 切换逻辑", src.includes("initFacetTabs") && src.includes("initFacetTabs();"));
  ok("旧的 #statGrid 两列 grid 已移除", !src.includes("id=\"statGrid\""));
  ok("分值校准独立卡已并入 panelCal", src.includes('id="calInsight"') && src.includes('aria-labelledby="tabCal"'));
}

// ── 6. 三处既有缺陷修复 ──
{
  console.log("\n[6] 既有缺陷修复验证");
  const t = read("trend.html");
  ok("trend 快照卡已改 .value（4 处）", countOf(t, /<div class="value" id="snap(Latest|Max|Min|Delta)"/g) === 4, String(countOf(t, /<div class="value" id="snap(Latest|Max|Min|Delta)"/g)));
  ok("trend 不再有 .val 的错用（.macro-row .val 的两处保留）", countOf(t, /<span class="val"/g) === 2, String(countOf(t, /<span class="val"/g)));

  const n = read("news.html");
  const thead = n.slice(n.indexOf("<thead>"), n.indexOf("</thead>"));
  ok("news 历史表表头 8 列", countOf(thead, /<th>/g) === 8, String(countOf(thead, /<th>/g)));
  ok("news 空态 colspan 8", n.includes('colspan="8" style="color:var(--muted)">暂无打分记录'));
  ok("news 表头已含「依据」列", thead.includes("<th>依据</th>"));

  const c = read("central_bank.html");
  ok("央行页 topnav 已补「研判复盘」", c.includes('href="/review" data-i18n="nav.review"'));
  ok("央行页 topnav 共 11 条", countOf(c.slice(c.indexOf('<nav class="topnav">'), c.indexOf("</nav>")), /<a href=/g) === 11, String(countOf(c.slice(c.indexOf('<nav class="topnav">'), c.indexOf("</nav>")), /<a href=/g)));
  ok("图例改走 I18n.t('country.'+iso)", c.includes('I18n.t("country." + iso)') && c.includes("countryLabel"));
}

console.log("\n" + "=".repeat(70));
console.log(`结果：${pass} passed / ${fail} failed`);
console.log("=".repeat(70));
process.exit(fail === 0 ? 0 : 1);
