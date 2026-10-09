/**
 * 前端渲染行为验证（V0.77.0 聚类分组 + V0.77.1 信任修复）—— scripts/check_cluster_render.mjs
 *
 * 为什么需要它：`check_static_js.py` 只做「语法 / 未定义调用 / DOM id」三类静态检查，
 * 查不出「渲染出来的 HTML 结构对不对」；而这两版改的正是渲染逻辑 —— 比如把 8 张卡
 * 分成 3 组、把 6 个数据源从两处渲染合并到一处。这类改动语法完全正确、DOM id 一个不差，
 * 静态门禁全绿，却可能让分组根本不出现（本次开发中就出现过提取到函数定义却没调用、
 * 结果 innerHTML 为空的假绿）。
 *
 * V0.77.1 追加：失败态渲染验证。信任修复包（A 包）五条改的全是【失败路径】——
 *   正常请求永远走不到那些分支，人工点页面看不出来，改错了就是「失败被显示成正常」
 *   这类后果最重的错误。因此这里直接构造「接口挂掉」的输入，执行各页真实的失败分支
 *   （renderOverall / showTrendError / renderLoadFailure / serveStaleApi 的价格护栏），
 *   断言其产出的可见结果。sw.js 的价格类正则也在这里被真实执行后逐路径验证。
 *
 * 做法：从各页源码里**提取真实的代码块**，用最小 DOM 桩 + mock 数据在 Node 里
 * 真实执行，再断言产出的 HTML 结构（簇数量 / 簇标题 / 卡片数 / 分组顺序）与失败态结果。
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
/** 最小 DOM 桩：支持按 id 取元素 + innerHTML / textContent / style / classList / disabled
 *  （足够验证「渲染出了什么」；style 与 classList 供 V0.77.1 的失败态与接线断言使用） */
function makeDoc() {
  const store = {};
  return {
    getElementById(id) {
      if (!store[id]) {
        store[id] = {
          id,
          innerHTML: "",
          textContent: "",
          style: {},
          disabled: false,
          classList: { add() {}, remove() {}, contains: () => false },
          addEventListener() {},
        };
      }
      return store[id];
    },
    querySelector(sel) {
      return this.getElementById(String(sel).replace(/^#/, "").split(/\s/)[0]);
    },
  };
}
const countOf = (html, re) => (html.match(re) || []).length;

console.log("=".repeat(70));
console.log("V0.77.0 聚类分组 + V0.77.1 信任修复 + V0.77.2 数据不丢 · 前端渲染行为验证");
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
  // V0.83 C3：topnav 链接文本迁到内层 <span>，旧版「属性上直接带 data-i18n」检查改查 V0.83 模板
  ok("央行页 topnav 已补「研判复盘」", /href="\/review"[^>]*>\s*<span class="nav-ico"[^>]*>[^<]*<\/span>\s*<span data-i18n="nav\.review">/m.test(c));
  // V0.83 C3：topnav 含 brand + 11 链接 = 12 个 <a href=>
  ok("央行页 topnav 共 12 个 a (brand + 11 链接)", countOf(c.slice(c.indexOf('class="topnav"'), c.indexOf("</nav>")), /<a href=/g) === 12, String(countOf(c.slice(c.indexOf('class="topnav"'), c.indexOf("</nav>")), /<a href=/g)));
  ok("图例改走 I18n.t('country.'+iso)", c.includes('I18n.t("country." + iso)') && c.includes("countryLabel"));
}

// ── 7. V0.77.1 A 包「信任修复」：失败态渲染 ──
// 这一包五条改的全是【失败路径】—— 正常请求永远走不到那些分支，靠人工点页面看不出来，
// 而这恰恰是最需要验证的部分（改错了就是「失败被显示成正常」这类后果最重的错误）。
// 因此这里直接构造「接口挂掉」的输入，执行各页真实的失败分支，断言它产出的可见结果。
{
  console.log("\n[7] V0.77.1 A 包 — 失败态渲染（正常路径测不出）");

  // ── A1 data-health：接口全挂时不得判「4 张全绿」 ──
  {
    const src = read("data-health.html");
    const code =
      sliceBetween(src, "  function overallCard(label, value, klass) {", "\n  }") +
      "\n" +
      sliceBetween(src, "  function renderOverall(healthData, ok) {", "\n  }");
    const _t = (k, fallback) => fallback;
    const safeText = (v) => String(v == null ? "" : v);
    const run = (health, okv) => {
      const fn = new Function(
        "document", "healthData", "ok", "_t", "safeText",
        code +
          "\nrenderOverall(healthData, ok);" +
          "\nreturn document.getElementById('overallCards').innerHTML;"
      );
      return fn(makeDoc(), health, okv, _t, safeText);
    };
    const green = (html) => (html.match(/vl ok/g) || []).length;
    const dash = (html) => (html.match(/>—</g) || []).length;

    // 场景 1：健康度接口失败。原实现 catch 兜底成 {sources:{}}，于是 total=0、live=0，
    // 而 live === total 在 0 === 0 时成立 → 4 张卡全判 ok（绿）。
    const hFail = run({ sources: {} }, false);
    ok("A1 接口失败 → 4 张卡全为「—」占位", dash(hFail) === 4, "实际 " + dash(hFail));
    ok("A1 接口失败 → 不再出现任何绿色 ok 判定", green(hFail) === 0, "实际 " + green(hFail));
    ok("A1 接口失败 → 走 unknown 态", (hFail.match(/vl unknown/g) || []).length === 4);

    // 场景 2：接口成功但一个数据源都没返回 —— 同样不能说「正常」
    const hEmpty = run({ sources: {} }, true);
    ok("A1 成功但零数据源 → 仍走未知态", green(hEmpty) === 0 && dash(hEmpty) === 4);

    // 场景 3：真实正常数据 —— 保证修复没把正常态一起改坏
    const hOk = run(
      { sources: { ny: "live", sge: "live", etf: "live", silver_ny: "live", silver_etf: "live", silver_gram: "live" } },
      true
    );
    ok("A1 6 源全 live → 恢复正常判定（live/stale/mock 三卡为绿）", green(hOk) === 3 && dash(hOk) === 0,
      "green=" + green(hOk) + " dash=" + dash(hOk));

    // 失败说明文案：要说清「哪个接口 + 这意味着什么 + 怎么办」
    const ft = new Function("_t", sliceBetween(src, "  function failureText(arr) {", "\n  }") + "\nreturn failureText;")(
      (k, f) => f
    );
    const bothFail = ft([{ ok: false }, { ok: false }]);
    ok("A1 两接口都失败 → 文案含「取数失败」", bothFail.includes("取数失败"));
    ok("A1 文案明说「— 不代表正常」", bothFail.includes("不代表正常"));
    ok("A1 文案给出可执行引导", bothFail.includes("🔄"));
    const oneFail = ft([{ ok: true }, { ok: false }]);
    ok("A1 只有时效失败 → 只点名失败的那个", oneFail.includes("数据时效") && !oneFail.includes("数据源健康度"));
    const noneFail = ft([{ ok: true }, { ok: true }]);
    ok("A1 全部成功 → 不产生失败提示", noneFail === "", JSON.stringify(noneFail));
  }

  // ── A2 silver：失败时加载条必须收起 + 错误提到首屏 + 不暴露本机地址 ──
  {
    const src = read("silver.html");
    const lt = sliceBetween(src, "async function loadTrend(", "\n}");
    ok("A2 加载条改由 finally 收起（失败路径也走到）", lt.includes("finally {") && lt.includes("hideLoadBar();"));
    ok("A2 失败分支接入 showTrendError", lt.includes("showTrendError(e);"));

    const code =
      sliceBetween(src, "function hideLoadBar() {", "\n}") +
      "\n" +
      sliceBetween(src, "function showTrendError(e) {", "\n}");
    const doc = makeDoc();
    // 用参数遮蔽全局 console，否则被测代码的 console.warn 会把堆栈打进门禁输出
    new Function("document", "window", "console", code + "\nshowTrendError(new Error('Failed to fetch'));")(
      doc,
      { console: { warn() {} } },
      { warn() {} }
    );
    ok("A2 失败后加载条被收起", doc.getElementById("loadBar").style.display === "none");
    ok("A2 错误提到首屏可见位（#alertBar）", doc.getElementById("alertBar").innerHTML.includes("加载失败"));
    ok("A2 首屏提示不含本机地址与端口", !doc.getElementById("alertBar").innerHTML.includes("127.0.0.1"));
    ok("A2 图表区不再渲染原始异常文本", !doc.getElementById("chartArea").innerHTML.includes("Failed to fetch"));
  }

  // ── A3 news：缺值占位 + 失败显式标注 ──
  {
    const src = read("news.html");
    ok("A3 静态默认分不再是 50.0", src.includes('id="effScore">—<') && !src.includes('id="effScore">50.0<'));
    ok("A3 静态口径文案不再是「按中性 50 参与评估」", src.includes("正在读取当日打分状态…"));

    const fs = new Function("v", sliceBetween(src, "function fmtScore(v) {", "\n}") + "\nreturn fmtScore(v);");
    ok("A3 fmtScore(null) → 「—」", fs(null) === "—", String(fs(null)));
    ok("A3 fmtScore(undefined) → 「—」", fs(undefined) === "—", String(fs(undefined)));
    ok("A3 fmtScore(0) → 0.0（真实的 0 不被吞掉）", fs(0) === "0.0", String(fs(0)));
    ok("A3 fmtScore(52.34) → 52.3", fs(52.34) === "52.3", String(fs(52.34)));

    const doc = makeDoc();
    new Function(
      "document", "esc",
      sliceBetween(src, "function renderLoadFailure(msg) {", "\n}") + "\nrenderLoadFailure('HTTP 500');"
    )(doc, (s) => String(s == null ? "" : s));
    ok("A3 失败后有效分显示「—」", doc.getElementById("effScore").textContent === "—");
    ok("A3 失败后保存按钮被禁用", doc.getElementById("btnSave").disabled === true);
    ok("A3 失败后明说「不代表今日中性 50」", doc.getElementById("scoreAlert").innerHTML.includes("不代表「今日中性 50」"));
    ok("A3 失败后公式位说明「未知」", doc.getElementById("effFormula").textContent.includes("未知"));
  }

  // ── A4 sw.js：只读 API 改 network-first + 价格类禁缓存 + 缓存时点披露 ──
  {
    const sw = read("sw.js");
    ok("A4 已弃用 stale-while-revalidate 回放", !sw.includes("return cached || fetchPromise"));
    ok("A4 API 分支改为 network-first", /fetch\(request\)\s*\n?\s*\.then\(\(response\) => \{[\s\S]{0,140}cacheApiResponse/.test(sw));
    ok("A4 只缓存成功响应（4xx/5xx 不入缓存）", /if \(!response\.ok\) return;/.test(sw));
    ok("A4 有离线回退的新鲜度上限常量", /const MAX_API_STALE_MS = \d+ \* 60 \* 1000;/.test(sw));
    ok("A4 回退时注入 X-SW-Cached-At", sw.includes('headers.set("X-SW-Cached-At"'));

    // 真实执行价格类正则：价格端点禁止回退，状态端点允许
    const re = new Function("return " + sw.match(/const PRICE_API_RE = (\/.*?\/);/)[1])();
    ok("A4 黄金价格端点禁止缓存回退", re.test("/api/v1/market/gold/trend") && re.test("/api/v1/market/gold/etf-quote"));
    ok("A4 白银价格端点禁止缓存回退", re.test("/api/v1/market/silver/trend") && re.test("/api/v1/market/silver/ny-trend"));
    ok("A4 状态端点仍可短时回退（health / freshness）", !re.test("/api/v1/market/health") && !re.test("/api/v1/market/freshness"));
    ok("A4 非行情端点不受价格规则影响", !re.test("/api/v1/news-score/history") && !re.test("/api/v1/review/meta"));

    const fresh = read("freshness.js");
    ok("A4 时效条读取缓存时点响应头", fresh.includes('r.headers.get("X-SW-Cached-At")'));
    ok("A4 时效条披露「离线缓存」", fresh.includes("fresh.offline_cached"));
    ok("A4 sw.js 版本常量已随版本升位", /const VERSION = "v0\.\d+\.\d+";/.test(sw));
  }

  // ── A5 backtest：基准线正名 + 缺数据不画 0 曲线 ──
  {
    const bt = read("backtest-chart.js");
    ok("A5 图例/数据不再称其为「理论概率」", !bt.includes('"理论概率 %"'));
    ok("A5 图例已正名为「完美校准基准线」", bt.includes("完美校准基准线 %"));
    ok("A5 缺分桶数据时整条曲线不入图（不再画 0 线）", bt.includes("if (hasBuckets) {") && bt.includes("datasets.push("));
    ok("A5 桶内无样本留 null 而非 0", bt.includes(": null;"));
    ok("A5 图下给出曲线含义说明", bt.includes("并非模型算出的概率"));
    ok("A5 明说缺数据不等于 0%", bt.includes("缺数据不等于命中率为 0%"));

    const bth = read("backtest.html");
    ok("A5 页面标题同步正名", bth.includes("实际命中率 vs 完美校准基准线"));
    ok("A5 新增图下说明容器", bth.includes('id="calibrationNote"'));

    for (const [loc, file] of [["zh-CN", "i18n/zh-CN.js"], ["zh-TW", "i18n/zh-TW.js"], ["en-US", "i18n/en-US.js"]]) {
      const dict = read(file);
      const line = dict.split("\n").find((l) => l.includes('"backtest.calibration_chart_title"')) || "";
      ok("A5 " + loc + " 标题已正名（zh-TW 不再是缺键）",
        line.includes("基准线") || line.includes("基準線") || line.includes("calibrated baseline"), line.slice(0, 90));
    }
  }

  // ── A6 backtest：高级面板 + 异步进度（V0.79.0 Step G Commit 3） ──
  {
    console.log("\n[A6] backtest 高级面板 + 异步进度（V0.79.0 Step G Commit 3）");
    const bth = read("backtest.html");

    // 6.1 HTML id 齐备（11 个 id）
    for (const id of ["advPanel", "trendOn", "macroOn", "asyncOn", "runBtnAsync",
                       "asyncProgress", "asyncFill", "asyncMsg", "trendGrid",
                       "macroGrid", "advHint"]) {
      ok(`A6 backtest.html 含 id="${id}"`, bth.includes(`id="${id}"`));
    }

    // 6.2 inline JS 函数定义存在
    ok("A6 定义 runBacktestAsync 函数", bth.includes("async function runBacktestAsync"));
    ok("A6 定义 pollBacktask 函数",    bth.includes("async function pollBacktask"));
    ok("A6 定义 validateSum 函数",     bth.includes("function validateSum"));
    ok("A6 定义 renderTrendGrid/renderMacroGrid",
       bth.includes("renderTrendGrid") && bth.includes("renderMacroGrid"));

    // 6.3 中文键字面（必填，后端 schema 期望）
    ok("A6 trend_weights 中文键「结构」字面出现", bth.includes('"结构"'));
    ok("A6 macro_weights 中文键「美元」字面出现", bth.includes('"美元"'));
    ok("A6 trend_weights / macro_weights 字段名都在 inline JS",
       bth.includes("trend_weights") && bth.includes("macro_weights"));

    // 6.4 异步切换判定
    ok("A6 同步/异步切换阈值 200 写明", bth.includes("> 200"));
    ok("A6 提交到 /api/v1/backtest/run-async", bth.includes("/api/v1/backtest/run-async"));
    ok("A6 轮询读 poll_url 字段（202 响应）", bth.includes("poll_url"));

    // 6.5 三语 i18n 7 个新 key 齐备
    const newKeys = ["backtest.advanced_title", "backtest.trend_5",
      "backtest.macro_5", "backtest.async_run", "backtest.sum_hint_ok",
      "backtest.sum_hint_bad", "backtest.async_progress"];
    for (const [loc, file] of [["zh-CN", "i18n/zh-CN.js"],
                               ["zh-TW", "i18n/zh-TW.js"],
                               ["en-US", "i18n/en-US.js"]]) {
      const dict = read(file);
      for (const k of newKeys) {
        ok(`A6 ${loc} 含 ${k}`, dict.includes(`"${k}"`));
      }
    }

    // 6.6 CSS 注入路径（必须 backtest-chart.js，不能在 backtest.html <style>）
    const btjs = read("backtest-chart.js");
    ok("A6 .adv-panel 在 backtest-chart.js injectCSS",
       btjs.includes(".adv-panel"));
    ok("A6 .progress-bar 在 backtest-chart.js",
       btjs.includes(".progress-bar"));
    ok("A6 .grp-grid 在 backtest-chart.js",
       btjs.includes(".grp-grid"));

    // 6.7 中文键 vs weights.html 英文键防呆
    ok("A6 backtest.html 不含 weights.html 风格的英文键（structure/momentum）",
       !/data-key="(structure|momentum|support|drawdown)"/.test(bth));
  }

  // ── A7 trend/silver 宏观阈值角标（V0.79.0 Step E Commit 4） ──
  {
    console.log("\n[A7] trend/silver 宏观阈值角标（V0.79.0 Step E Commit 4）");
    const bth = read("trend.html");
    const sh = read("silver.html");

    // 7.1 trend.html 角标代码：动态/静态 badge + I18n.t + hint
    ok("A7 trend.html 含 macroDynamic 变量定义", bth.includes("macroDynamic"));
    ok("A7 trend.html 含 macroBadgeText 变量",
       bth.includes("macroBadgeText"));
    ok("A7 trend.html 通过 window.I18n.t 取翻译",
       bth.includes("window.I18n.t"));
    ok("A7 trend.html fallback [动态]/[静态] 字面",
       bth.includes('"[动态]"') && bth.includes('"[静态]"'));
    ok("A7 trend.html 含动态阈值 hint 文案",
       bth.includes("5 因子中 ≥4"));
    ok("A7 trend.html macroInfo 改用 innerHTML（容下 badge）",
       bth.includes("getElementById(\"macroInfo\").innerHTML"));

    // 7.2 silver.html 同步加角标（commit 4 一改两受益）
    ok("A7 silver.html 含 macroDynamic 变量定义", sh.includes("macroDynamic"));
    ok("A7 silver.html 通过 window.I18n.t 取翻译",
       sh.includes("window.I18n.t"));
    ok("A7 silver.html 含动态阈值 hint 文案",
       sh.includes("5 因子中 ≥4"));
    ok("A7 silver.html 与 trend.html 角标逻辑一致（macroBadgeText 同步）",
       sh.includes("macroBadgeText"));

    // 7.3 配色（沿用 srcBadge 的 #e7f5ff/#e9ecef 风格，新增 #e8f7ee 表示 dynamic）
    ok("A7 trend.html 含动态色 #e8f7ee", bth.includes("#e8f7ee"));
    ok("A7 trend.html 含静态色 #e9ecef", bth.includes("#e9ecef"));
    ok("A7 silver.html 含动态色 #e8f7ee", sh.includes("#e8f7ee"));

    // 7.4 i18n 三语 2 key × 3 语 = 6 条存在性
    const zhCN = read("i18n/zh-CN.js");
    const enUS = read("i18n/en-US.js");
    const zhTW = read("i18n/zh-TW.js");
    ok("A7 zh-CN 含 macro_dynamic_badge（动态阈值）",
       zhCN.includes('"trend.macro_dynamic_badge": "动态阈值"'));
    ok("A7 zh-CN 含 macro_static_badge（静态阈值）",
       zhCN.includes('"trend.macro_static_badge": "静态阈值"'));
    ok("A7 en-US 含 macro_dynamic_badge（Dynamic）",
       enUS.includes('"trend.macro_dynamic_badge": "Dynamic"'));
    ok("A7 en-US 含 macro_static_badge（Static）",
       enUS.includes('"trend.macro_static_badge": "Static"'));
    ok("A7 zh-TW 含 macro_dynamic_badge（動態閾值）",
       zhTW.includes('"trend.macro_dynamic_badge": "動態閾值"'));
    ok("A7 zh-TW 含 macro_static_badge（靜態閾值）",
       zhTW.includes('"trend.macro_static_badge": "靜態閾值"'));
  }

  // ── A8 V0.79.0 Step F · 技术面合成方式角标 + 权重配置 4 卡片 ──
  {
    console.log("\n[A8] V0.79.0 Step F · 技术面合成方式角标 + 权重配置页");
    const bth = read("trend.html");
    const sh = read("silver.html");
    const wh = read("weights.html");
    const zhCN = read("i18n/zh-CN.js");
    const enUS = read("i18n/en-US.js");
    const zhTW = read("i18n/zh-TW.js");

    // 8.1 trend.html 技术面合成方式角标（与 macro badge 同模式）
    ok("A8 trend.html 含 techComposed 变量定义", bth.includes("techComposed"));
    ok("A8 trend.html 含 techBadgeText 变量", bth.includes("techBadgeText"));
    ok("A8 trend.html 通过 window.I18n.t 取翻译",
       bth.includes("trend.tech_grouped_badge") && bth.includes("trend.tech_weighted_badge"));
    ok("A8 trend.html fallback [组内平均]/[单维度加权] 字面",
       bth.includes('"[组内平均]"') && bth.includes('"[单维度加权]"'));
    ok("A8 trend.html 含组内平均 hint 文案",
       bth.includes("5 维度按组内先平均再加权"));
    ok("A8 trend.html 含 techComposeBadge 拼到 idxMethod",
       bth.includes("techComposeBadge +"));

    // 8.2 silver.html 同步技术面角标
    ok("A8 silver.html 含 techComposed 变量定义", sh.includes("techComposed"));
    ok("A8 silver.html 含 techComposeBadge 拼到 idxMethod",
       sh.includes("+ techComposeBadge"));
    ok("A8 silver.html 通过 window.I18n.t 取翻译",
       sh.includes("trend.tech_grouped_badge"));

    // 8.3 weights.html 第 4 卡片：组内平均 vs 单维度加权
    ok("A8 weights.html 含 gcOn radio (group_combine=true)",
       wh.includes('id="gcOn"'));
    ok("A8 weights.html 含 gcOff radio (group_combine=false)",
       wh.includes('id="gcOff"'));
    ok("A8 weights.html 默认勾选 gcOn（推荐）",
       /id="gcOn"\s+checked/.test(wh));
    ok("A8 weights.html collect() 含 group_combine",
       wh.includes("group_combine,"));
    ok("A8 weights.html render() 含 radio 状态设置",
       wh.includes("gcOn\").checked = gc"));
    ok("A8 weights.html resetAll body 含 group_combine: true",
       wh.includes("group_combine: true"));

    // 8.4 i18n 三语 7 key × 3 语 = 21 条存在性
    ok("A8 zh-CN 含 tech_grouped_badge", zhCN.includes('"trend.tech_grouped_badge": "[组内平均]"'));
    ok("A8 zh-CN 含 tech_weighted_badge", zhCN.includes('"trend.tech_weighted_badge": "[单维度加权]"'));
    ok("A8 zh-CN 含 tech_compose_title", zhCN.includes("weights.tech_compose_title"));
    ok("A8 zh-CN 含 group_combine_on", zhCN.includes("weights.group_combine_on"));
    ok("A8 zh-CN 含 group_combine_off", zhCN.includes("weights.group_combine_off"));
    ok("A8 zh-CN 含 group_combine_on_hint", zhCN.includes("weights.group_combine_on_hint"));
    ok("A8 zh-CN 含 group_combine_off_hint", zhCN.includes("weights.group_combine_off_hint"));

    ok("A8 en-US 含 tech_grouped_badge", enUS.includes('"trend.tech_grouped_badge": "[Grouped]"'));
    ok("A8 en-US 含 tech_weighted_badge", enUS.includes('"trend.tech_weighted_badge": "[Weighted]"'));
    ok("A8 en-US 含 tech_compose_title", enUS.includes("weights.tech_compose_title"));
    ok("A8 en-US 含 group_combine_on", enUS.includes("weights.group_combine_on"));
    ok("A8 en-US 含 group_combine_off", enUS.includes("weights.group_combine_off"));

    ok("A8 zh-TW 含 tech_grouped_badge", zhTW.includes('"trend.tech_grouped_badge": "[組內平均]"'));
    ok("A8 zh-TW 含 tech_weighted_badge", zhTW.includes('"trend.tech_weighted_badge": "[單維度加權]"'));
    ok("A8 zh-TW 含 tech_compose_title", zhTW.includes("weights.tech_compose_title"));
    ok("A8 zh-TW 含 group_combine_on", zhTW.includes("weights.group_combine_on"));
    ok("A8 zh-TW 含 group_combine_off_hint", zhTW.includes("weights.group_combine_off_hint"));
  }
}

// ── 8. V0.77.1 接线与 SW 护栏：桩 fetch / 桩 caches 全链路真实执行 ──
// 第 7 节验证的是「渲染函数拿到失败输入后产出什么」，但还差一环：`load()` 到底有没有
// 把失败标记传下去（第 7 节测不出「接线断了」）。这里用桩 fetch 真正跑一遍 load()，
// 再用桩 caches + 真实 Response 跑一遍 SW 的缓存护栏 —— 都是真实执行，不是静态断言。
const pending = [];
{
  console.log("\n[8] V0.77.1 接线与 SW 缓存护栏（异步执行，结果在末尾统一汇总）");

  // ── A1 接线：data-health 的 load() 全链路（桩 fetch）──
  {
    const src = read("data-health.html");
    const code =
      sliceBetween(src, "  function fetchJSON(url) {", "\n  }") + "\n" +
      sliceBetween(src, "  function overallCard(label, value, klass) {", "\n  }") + "\n" +
      sliceBetween(src, "  function renderOverall(healthData, ok) {", "\n  }") + "\n" +
      sliceBetween(src, "  function failureText(arr) {", "\n  }") + "\n" +
      sliceBetween(src, "  var SOURCE_GROUPS = [", "\n  ];") + "\n" +
      sliceBetween(src, "  function renderSourceGroups(healthData, freshData) {", "\n  }") + "\n" +
      sliceBetween(src, "  function renderNote(healthData) {", "\n  }") + "\n" +
      sliceBetween(src, "  function showLoading(loading, errMsg) {", "\n  }") + "\n" +
      sliceBetween(src, "  function load() {", "\n  }");

    const _t = (k, f) => f;
    const fmtAge = (v) => (v == null ? "—" : v + " 分钟");
    const safeText = (v) => String(v == null ? "" : v);
    const SOURCE_LABELS = {
      etf: "黄金 ETF（华安 518880）", sge: "上海金（SGE Au99.99）", ny: "纽约金（COMEX GC）",
      silver_etf: "白银 ETF（易方达 562800）", silver_gram: "白银克重（上海银）", silver_ny: "纽约白银（COMEX SI）",
    };
    const STATUS_LABELS = {
      live: { txt: "实时", cls: "live", badge: "badge-live" },
      unknown: { txt: "未知", cls: "unknown", badge: "badge-unknown" },
    };
    const HEALTH_OK = {
      sources: { ny: "live", sge: "live", etf: "live", silver_ny: "live", silver_etf: "live", silver_gram: "live" },
      note: "进程内累计",
    };
    const FRESH_OK = {
      markets: {
        ny: { status: "live", data_date: "2026-10-02", age_minutes: 600, session: { state_label: "盘后" }, freshness_label: "实时" },
        sge: { status: "live", data_date: "2026-10-02", age_minutes: 45, session: { state_label: "盘后" }, freshness_label: "实时" },
        etf: { status: "live", data_date: "2026-10-02", age_minutes: 12, session: { state_label: "盘中" }, freshness_label: "实时" },
      },
    };

    /** 跑一遍真实 load()，返回 doc 与「本轮 errorHint 文本」。
     *  注意：load() 自身不 return 那句 Promise 链（真实代码就是这样），
     *  所以不能 await 它的返回值 —— 必须让出事件循环，等 microtask 链跑完再断言。
     *  第一版这里写成 `await fn(...)`，断言全在渲染前执行 —— 其中「全部正常 → 无失败提示」
     *  因此还假通过了一次（空的错误文本当然「没有失败提示」）。 */
    const runLoad = async (healthFails, freshFails) => {
      const fetchStub = (url) => {
        const fails = url.includes("/market/health") ? healthFails : freshFails;
        if (fails) return Promise.reject(new Error("HTTP 500"));
        const data = url.includes("/market/health") ? HEALTH_OK : FRESH_OK;
        return Promise.resolve({ ok: true, status: 200, json: async () => data });
      };
      const doc = makeDoc();
      const fn = new Function(
        "document", "fetch", "API_BASE", "_t", "fmtAge", "safeText", "SOURCE_LABELS", "STATUS_LABELS",
        code + "\nreturn load();"
      );
      fn(doc, fetchStub, "", _t, fmtAge, safeText, SOURCE_LABELS, STATUS_LABELS);
      await new Promise((r) => setTimeout(r, 20));
      return doc;
    };

    pending.push(
      (async () => {
        // S1：两个接口都挂 —— 原先会渲染成 4 张全绿卡
        const d1 = await runLoad(true, true);
        const cards = d1.getElementById("overallCards").innerHTML;
        const errEl = d1.getElementById("errorHint");
        ok("A1接线 两接口全挂 → 概览卡全为「—」", (cards.match(/>—</g) || []).length === 4);
        ok("A1接线 两接口全挂 → 无任何绿色 ok 判定", (cards.match(/vl ok/g) || []).length === 0);
        ok("A1接线 两接口全挂 → 失败被传到了提示条", errEl.textContent.includes("取数失败") && errEl.style.display === "block",
          JSON.stringify(errEl.textContent.slice(0, 60)));
        ok("A1接线 失败提示含「不代表正常」", errEl.textContent.includes("不代表正常"));
        ok("A1接线 失败时收起加载提示", d1.getElementById("loadingHint").style.display === "none");

        // S2：只有时效接口挂 —— 概览可用，提示只点名时效
        const d2 = await runLoad(false, true);
        const cards2 = d2.getElementById("overallCards").innerHTML;
        const err2 = d2.getElementById("errorHint").textContent;
        ok("A1接线 仅时效失败 → 概览仍正常（6 源 live）", (cards2.match(/vl ok/g) || []).length === 3);
        ok("A1接线 仅时效失败 → 只点名时效", err2.includes("数据时效") && !err2.includes("数据源健康度"), JSON.stringify(err2.slice(0, 60)));

        // S3：都正常 —— 不得产生任何失败提示（防止把正常态改坏）
        const d3 = await runLoad(false, false);
        ok("A1接线 全部正常 → 无失败提示", d3.getElementById("errorHint").textContent === "",
          JSON.stringify(d3.getElementById("errorHint").textContent.slice(0, 60)));
        ok("A1接线 全部正常 → 概览为 6 源正常判定", (d3.getElementById("overallCards").innerHTML.match(/vl ok/g) || []).length === 3);
      })()
    );
  }

  // ── A4 行为：serveStaleApi / cacheApiResponse 真实执行（桩 caches + 真 Response）──
  {
    const sw = read("sw.js");
    const code =
      // RUNTIME_CACHE 定义在 sw.js 更前面，切片带不上，这里补一个同名常量
      'const RUNTIME_CACHE = "gold-runtime-test";\n' +
      sliceBetween(sw, "const PRICE_API_RE = ", 'const STORED_AT_HEADER = "X-SW-Stored-At";') + "\n" +
      sliceBetween(sw, "function cacheApiResponse(request, response) {", "\n}") + "\n" +
      sliceBetween(sw, "async function serveStaleApi(request) {", "\n}");

    const mkCaches = (resp, tracker) => ({
      open: async () => ({
        put: async (r, res) => { tracker.put = res; },
        delete: async () => { tracker.deleted = true; },
      }),
      match: async () => resp,
    });
    const build = (caches) =>
      new Function("caches", "console", code + "\nreturn { serveStaleApi, cacheApiResponse };")(caches, { warn() {} });
    const cachedJson = (storedAtIso) =>
      new Response('{"ok":true}', {
        status: 200,
        headers: { "Content-Type": "application/json", "X-SW-Stored-At": storedAtIso },
      });
    const minsAgo = (n) => new Date(Date.now() - n * 60 * 1000).toISOString();
    const rejects = async (p) => {
      try { await p; return false; } catch { return true; }
    };

    pending.push(
      (async () => {
        // 1) 价格端点：即使有「刚刚」的缓存也绝不回退
        const apiPrice = build(mkCaches(cachedJson(minsAgo(1)), {}));
        ok("A4行为 价格端点即使有新鲜缓存也拒绝回退",
          await rejects(apiPrice.serveStaleApi({ url: "http://x/api/v1/market/gold/trend" })));
        ok("A4行为 白银价格端点同样拒绝回退",
          await rejects(apiPrice.serveStaleApi({ url: "http://x/api/v1/market/silver/ny-trend" })));

        // 2) 非价格端点 + 新鲜缓存 → 回退成功，且带出真实缓存时点
        const apiFresh = build(mkCaches(cachedJson(minsAgo(5)), {}));
        const r2 = await apiFresh.serveStaleApi({ url: "http://x/api/v1/market/freshness" });
        ok("A4行为 新鲜缓存可回退（离线仍可用）", r2.status === 200);
        ok("A4行为 回退响应带上 X-SW-Cached-At", !!r2.headers.get("X-SW-Cached-At"),
          String(r2.headers.get("X-SW-Cached-At")));
        ok("A4行为 回退响应正文可用（JSON 未被破坏）", (await r2.json()).ok === true);

        // 3) 超期缓存（> 30 分钟）→ 抛错并清除，页面走错误态而不是显示旧值
        const trk = {};
        const apiOld = build(mkCaches(cachedJson(minsAgo(40)), trk));
        ok("A4行为 超期缓存拒绝回退（不拿旧快照冒充当前值）",
          await rejects(apiOld.serveStaleApi({ url: "http://x/api/v1/market/freshness" })));
        ok("A4行为 超期缓存被清除", trk.deleted === true);

        // 4) 无缓存 → 抛错（页面报错，而不是静默空白）
        const apiNone = build(mkCaches(undefined, {}));
        ok("A4行为 无缓存可回退时抛错", await rejects(apiNone.serveStaleApi({ url: "http://x/api/v1/news-score" })));

        // 5) 缓存写入：4xx/5xx 不入缓存（原先会把失败响应回放成「正常」）
        const tOk = {};
        build(mkCaches(undefined, tOk)).cacheApiResponse(
          { url: "http://x/api/v1/news-score" },
          new Response('{"ok":true}', { status: 200, headers: { "Content-Type": "application/json" } })
        );
        await new Promise((r) => setTimeout(r, 30));
        ok("A4行为 成功响应写入缓存", !!tOk.put);
        ok("A4行为 写入时打上 X-SW-Stored-At（自记时点，不依赖上游 Date）",
          !!tOk.put && !!tOk.put.headers.get("X-SW-Stored-At"));

        const tBad = {};
        build(mkCaches(undefined, tBad)).cacheApiResponse(
          { url: "http://x/api/v1/news-score" },
          new Response('{"detail":"boom"}', { status: 500, headers: { "Content-Type": "application/json" } })
        );
        await new Promise((r) => setTimeout(r, 30));
        ok("A4行为 5xx 响应不写入缓存", !tBad.put);
      })()
    );
  }
}

await Promise.all(pending);

// ── 9. V0.77.2 四条「静默错误」修复：真实执行 + 反向断言 ──
// 这四条都不是「界面报错」，而是「悄无声息地做错事」：丢依据、清输入、指错路、误覆盖。
// 正常路径下页面看起来完全正常（这正是它们能存活至今的原因），所以必须构造输入、
// 真实执行源码片段，断言「实际发生的后果」—— 而不是断言「代码里有某句话」。
{
  console.log("\n[9] V0.77.2 数据不丢与交互安全（B1 / B2 / B5 / C2）");

  // ── B1：/news 保存时 basis 与 review_note 是否真的进了请求体 ──
  {
    const src = read("news.html");
    const code = sliceBetween(src, "async function save() {", "\n}");

    /** 真实跑一遍 save()，返回它实际发出去的请求体。 */
    const runSave = async (basisArr, reviewNote) => {
      const doc = makeDoc();
      doc.getElementById("score").value = "78";
      doc.getElementById("notes").value = "高盛上调目标价";
      doc.getElementById("reviewNote").value = reviewNote;
      let captured = null;
      const fetchStub = (url, init) => {
        captured = JSON.parse(init.body);
        return Promise.resolve({ ok: true, status: 200, json: async () => ({ score: 61.7, next_slot: 2 }) });
      };
      const fn = new Function(
        "document", "fetch", "API", "selectedBasis", "dirOf",
        "state", "forceReload", "editSlot", "renderAll", "loadHistory",
        code + "\nreturn save();"
      );
      await fn(doc, fetchStub, "/api/v1/news-score", new Set(basisArr), () => "bullish",
        {}, false, 1, () => {}, () => {});
      return captured;
    };

    const c1 = await runSave(["美元指数", "央行购金"], "事后回看：低估了美元反弹");
    ok("B1 保存请求体带上 basis（原先被静默丢弃）",
      Array.isArray(c1.basis) && c1.basis.length === 2 && c1.basis[0] === "美元指数",
      JSON.stringify(c1.basis));
    ok("B1 保存请求体带上 review_note",
      c1.review_note === "事后回看：低估了美元反弹", JSON.stringify(c1.review_note));
    ok("B1 原有字段未被破坏（score / direction / notes / slot）",
      c1.score === 78 && c1.direction === "bullish" && c1.notes === "高盛上调目标价" && c1.slot === 1,
      JSON.stringify({ score: c1.score, direction: c1.direction, notes: c1.notes, slot: c1.slot }));

    const c2 = await runSave([], "");
    ok("B1 未选依据时提交空数组（避开 Set 被序列化成 {} 的陷阱）",
      Array.isArray(c2.basis) && c2.basis.length === 0, JSON.stringify(c2.basis));
    ok("B1 旧的窄 payload 写法已消失",
      !src.includes('{ score: v, direction: dirOf(v), notes: document.getElementById("notes").value, slot: editSlot }'));
  }

  // ── B2：轮询不再抹掉客户填写的成交价 ──
  {
    const src = read("portfolio.html");
    const code = sliceBetween(
      src,
      'const priceEl = document.getElementById("price");',
      "if (priceEl && !priceEl.value && !priceTouched) fillPrice();"
    );

    /** 真实执行 renderDecision 里那段价格逻辑（轮询每次都会走到）。 */
    const runTick = (value, touched) => {
      const doc = makeDoc();
      doc.getElementById("price").value = value;
      let calls = 0;
      const fn = new Function("document", "priceTouched", "fillPrice", code);
      fn(doc, touched, () => { calls++; });
      return { calls, value: doc.getElementById("price").value };
    };

    ok("B2 价格框为空且未编辑过 → 仍会补预填（没把预填功能一起改坏）", runTick("", false).calls === 1);
    ok("B2 客户已手动输入过 → 轮询不再清空/覆盖", runTick("", true).calls === 0);
    const filled = runTick("7.123", false);
    ok("B2 价格框已有值 → 一律不动", filled.calls === 0 && filled.value === "7.123");
    // 注意：这条不能对全文做 includes —— 修复处的注释里有意保留了旧写法作为历史说明，
    // 全文搜索会把注释本身判成「旧写法仍在」。用行首锚定区分注释行与真实代码行。
    ok("B2 旧的恒清空写法已消失（只看真实代码行）",
      !/^[ \t]*document\.getElementById\("price"\)\.value\s*=\s*d\.trend_index/m.test(src));
    ok("B2 已接线 input 监听以记录人工编辑",
      src.includes('addEventListener("input"') && src.includes("priceTouched = true"));
  }

  // ── B5：复盘页空态不再指路到不存在的能力 ──
  {
    const src = read("review.html");
    const i = src.indexOf("暂无研判记录。");
    const line = src.slice(i, src.indexOf("</div>`;", i) + 8);
    ok("B5 断死指引（「可在该页填写并指定日期」）已移除", !line.includes("指定日期"));
    ok("B5 保留真实存在的路径 /news", line.includes('href="/news"'));
    ok("B5 明确交代补录入口尚未开放（不再承诺不存在的功能）", line.includes("补录入口尚未开放"));
    ok("B5 给出的替代动作确有对应按钮",
      line.includes("回填历史金价") && src.includes('id="btnBackfill"'));
  }

  // ── C2-a：确认弹窗本体真实执行（weights.html 此前无任何确认机制）──
  {
    const src = read("weights.html");
    const code = sliceBetween(src, "function confirmDialog(text) {", "\n}");
    const runDialog = () => {
      const created = [];
      let keydown = null;
      const doc = {
        createElement() {
          const el = {
            className: "", innerHTML: "", _h: {},
            querySelector: () => ({ textContent: "" }),
            addEventListener(t, fn) { this._h[t] = fn; },
            getAttribute: () => null,
          };
          created.push(el);
          return el;
        },
        body: { appendChild() {}, removeChild() {} },
        addEventListener(t, fn) { if (t === "keydown") keydown = fn; },
        removeEventListener() {},
      };
      const p = new Function("document", code + "\nreturn confirmDialog('测试文案');")(doc);
      return { mask: created[0], p, getKeydown: () => keydown };
    };
    const clickWith = (mask, act) =>
      mask._h.click({ target: { getAttribute: (n) => (n === "data-act" ? act : null) } });

    const a = runDialog();
    clickWith(a.mask, "no");
    ok("C2 确认弹窗：点「取消」→ false", (await a.p) === false);

    const b = runDialog();
    clickWith(b.mask, "yes");
    ok("C2 确认弹窗：点「确定」→ true", (await b.p) === true);

    const c = runDialog();
    const kd = c.getKeydown();
    if (kd) kd({ key: "Escape" });
    ok("C2 确认弹窗：按 Esc → false（键盘可安全取消）", !!kd && (await c.p) === false);
  }

  // ── C2-b：resetAll 真实执行 —— 取消不发请求、失败必有提示 ──
  {
    const src = read("weights.html");
    const code = sliceBetween(src, "async function resetAll() {", "\n}");
    const runReset = async (confirmed, response) => {
      const doc = makeDoc();
      let fetched = null, fetchCount = 0, rendered = 0;
      const fetchStub = (url, init) => {
        fetchCount++;
        fetched = JSON.parse(init.body);
        return Promise.resolve(response);
      };
      const fn = new Function(
        "document", "fetch", "API", "confirmDialog", "state", "render",
        code + "\nreturn resetAll();"
      );
      await fn(doc, fetchStub, "/api/v1/settings/weights", async () => confirmed, {},
        () => { rendered++; });
      return { doc, fetched, fetchCount, rendered };
    };

    const r1 = await runReset(false, { ok: true, status: 200, json: async () => null });
    ok("C2 取消确认时 → 一个保存请求都不发（原先会直接覆盖）", r1.fetchCount === 0);

    const r2 = await runReset(true, { ok: true, status: 200, json: async () => null });
    ok("C2 确认后 → 提交的确实是内置默认权重",
      r2.fetchCount === 1 && r2.fetched.trend.structure === 0.3 && r2.fetched.combine.news === 0.3);
    const sums = [r2.fetched.trend, r2.fetched.macro, r2.fetched.combine]
      .map((o) => Object.values(o).reduce((x, y) => x + y, 0));
    ok("C2 默认值三组各自归一（各组和 = 1）", sums.every((s) => Math.abs(s - 1) < 1e-9), JSON.stringify(sums));
    ok("C2 成功后 → 提示成功并重渲染",
      r2.doc.getElementById("msg").textContent.includes("已恢复默认") && r2.rendered === 1);

    const r3 = await runReset(true, { ok: false, status: 500, json: async () => ({ detail: "内部错误" }) });
    const m3 = r3.doc.getElementById("msg");
    ok("C2 失败 → 明确报错（原先 if (r.ok) 无 else，静默无反应）",
      m3.className.includes("err") && m3.textContent.includes("失败"), JSON.stringify(m3.textContent));
    ok("C2 失败 → 告知权重未被改动并带出后端原因",
      m3.textContent.includes("未被改动") && m3.textContent.includes("内部错误"), JSON.stringify(m3.textContent));
  }
}

console.log("\n" + "=".repeat(70));
console.log(`结果：${pass} passed / ${fail} failed`);
console.log("=".repeat(70));
process.exit(fail === 0 ? 0 : 1);
