// scripts/_verify_central_bank_aggregate.mjs
// V0.121.4 验证：央行购金页「全球合计行」不得与各国明细重复计数。
//
// 背景：旧口径把「WGC 全球合计行」和「各国明细行」一起求和
//   （2026Q2：336.7 = 合计 288.9 + 各国 47.8）⇒ 数字虚高。
// 本门禁断言的是**结构性事实**（卡片值 == API 的合计口径，而不是全表求和），
// 不写死吨数 ⇒ WGC 以后修订数据时门禁不会假红。
//
// ⚠ 必须打 8888（主入口）。8889/gold/ 是备用入口且全站 /api/v1/* 404。见记忆 lan-only-deployment。
// ⚠ 视口必须 1352×900：默认 800×600 下顶 nav 会盖住按钮。见记忆 puppeteer-viewport-sticky-nav。
// ⚠ 必须 setBypassServiceWorker(true)：SW 接管页面后 mock 静默失效。见记忆 puppeteer-sw-silently-bypasses-interception。
import puppeteer from "puppeteer-core";

const BASE = process.env.BASE_URL || "http://192.168.0.204:8888";
const CHROME =
  "/home/surui/.cache/puppeteer/chrome/linux-153.0.8010.36/chrome-linux64/chrome";

let pass = 0;
let fail = 0;
function ok(name, cond, extra = "") {
  if (cond) { pass++; console.log(`  ✓ ${name}`); }
  else { fail++; console.log(`  ✗ ${name}${extra ? " → " + extra : ""}`); }
}

const browser = await puppeteer.launch({
  executablePath: CHROME,
  headless: "new",
  args: ["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"],
});
const page = await browser.newPage();
await page.setViewport({ width: 1352, height: 900 });
await page.setBypassServiceWorker(true);

const errs = new Set();
page.on("pageerror", (e) => errs.add(`pageerror: ${String(e)}`));
page.on("console", (m) => { if (m.type() === "error") errs.add(`console: ${m.text()}`); });
page.on("response", (r) => {
  if (r.status() >= 400) errs.add(`HTTP ${r.status()} ${r.url()}`);
});

// ─── 1. 页面渲染 ───
console.log("【1】央行购金页渲染");
await page.goto(`${BASE}/central-bank`, { waitUntil: "networkidle2" });
await page.waitForFunction(
  () => {
    const v = document.getElementById("kpiCurrent")?.textContent || "";
    const t = document.getElementById("topBody")?.textContent || "";
    return /\d/.test(v) && t.length > 0 && !/暂无数据/.test(t);
  },
  { timeout: 30000 },
).catch(() => {});
ok("KPI 与 Top 表格已渲染",
  /\d/.test((await page.$eval("#kpiCurrent", (e) => e.textContent).catch(() => "")) || ""));

// ─── 2. KPI 口径 = 合计口径，不是全表求和 ───
console.log("【2】KPI 取合计口径（不是「合计 + 各国」）");
const cmp = await page.evaluate(async () => {
  // 用页面自己那份 API 响应（fullData）；取不到就同源再取一次同样的端点。
  const data = (typeof fullData !== "undefined" && fullData)
    ? fullData
    : await (await fetch("/api/v1/central-bank/purchases")).json();
  const items = data.items || [];
  const curQ = data.summary?.current_quarter;
  const naiveSum = items
    .filter((i) => i.quarter === curQ)
    .reduce((s, i) => s + Number(i.tonnes_net || 0), 0);
  const aggRows = items.filter((i) => i.country_iso === "WGC_AGGR");
  const curAgg = aggRows.find((i) => i.quarter === curQ);
  return {
    curQ,
    summaryCurrent: Number(data.summary?.current_quarter_total),
    summaryT12m: Number(data.summary?.t12m_total),
    countryCount: Number(data.summary?.country_count),
    naiveSum: Math.round(naiveSum * 10) / 10,
    aggExists: !!curAgg,
    aggValue: curAgg ? Number(curAgg.tonnes_net) : null,
    aggCount: aggRows.length,
    // 「既有合计行、又有各国明细行」的季度 —— 这才是重复计数的风险点。
    // （2026Q3 没有各国明细：Q3 报告只发区域图 ⇒ 当季全表求和 == 合计行，
    //   那里看不出重复；2026Q2 才是旧口径 336.7 = 288.9 + 47.8 的现场。）
    overcount: (() => {
      const qs = [...new Set(items.map((i) => i.quarter))].sort();
      for (const q of qs) {
        const a = items.find((i) => i.country_iso === "WGC_AGGR" && i.quarter === q);
        const countries = items.filter((i) => i.country_iso !== "WGC_AGGR" && i.quarter === q);
        if (!a || countries.length === 0) continue;
        const csum = countries.reduce((s, i) => s + Number(i.tonnes_net || 0), 0);
        if (Math.abs(csum) > 0.05) {
          return {
            quarter: q,
            agg: Number(a.tonnes_net),
            countrySum: Math.round(csum * 10) / 10,
            naive: Math.round((Number(a.tonnes_net) + csum) * 10) / 10,
          };
        }
      }
      return null;
    })(),
    // T12M 窗口（2025Q4–2026Q3）**有**各国明细 ⇒ 这里的「合计 + 明细」是活的重复计数。
    t12m: (() => {
      const w = data.summary?.t12m_window || "";
      const m = w.match(/^(\d{4}Q\d)–(\d{4}Q\d)$/);
      if (!m) return null;
      const inWin = (i) => i.quarter >= m[1] && i.quarter <= m[2];
      const aggRows = items.filter((i) => i.country_iso === "WGC_AGGR" && inWin(i));
      const cRows = items.filter((i) => i.country_iso !== "WGC_AGGR" && inWin(i));
      const aggSum = aggRows.reduce((s, i) => s + Number(i.tonnes_net || 0), 0);
      const cSum = cRows.reduce((s, i) => s + Number(i.tonnes_net || 0), 0);
      return {
        window: w,
        aggSum: Math.round(aggSum * 10) / 10,
        countrySum: Math.round(cSum * 10) / 10,
        naive: Math.round((aggSum + cSum) * 10) / 10,
      };
    })(),
    distinctCountries: new Set(items.map((i) => i.country_iso)).size,
    kpiCurrentText: document.getElementById("kpiCurrent")?.textContent.trim() || "",
    kpiCountriesText: document.getElementById("kpiCountries")?.textContent.trim() || "",
    kpiCurrentLabel: document.getElementById("kpiCurrentLabel")?.textContent.trim() || "",
    kpiT12mText: document.getElementById("kpiT12m")?.textContent.trim() || "",
  };
});
ok("数据里有全球合计行", cmp.aggExists, `quarter=${cmp.curQ}`);
ok("全球合计行不止一条（季度序列）", cmp.aggCount >= 4, `实际 ${cmp.aggCount}`);
ok("KPI 当前季度 == 合计行的值",
  Math.abs(cmp.summaryCurrent - cmp.aggValue) < 0.05,
  `summary=${cmp.summaryCurrent} agg=${cmp.aggValue}`);
ok("存在「既有合计行又有各国明细」的季度（重复计数的风险现场）",
  cmp.overcount !== null,
  cmp.overcount ? "" : "数据里没有这种季度 ⇒ 本门禁的重复计数断言会空转");
if (cmp.overcount) {
  ok("⚠️ 该季度若全表求和就会虚高（合计 + 明细）",
    Math.abs(cmp.overcount.naive - cmp.overcount.agg) > 0.05,
    JSON.stringify(cmp.overcount));
}
ok("T12M 窗口能解析出来", cmp.t12m !== null, JSON.stringify(cmp.t12m));
if (cmp.t12m) {
  ok("⚠️ T12M 窗口内全表求和确实会虚高（重复计数的活现场）",
    Math.abs(cmp.t12m.naive - cmp.t12m.aggSum) > 0.05,
    JSON.stringify(cmp.t12m));
  ok("KPI T12M == 窗口内合计行之和（不是合计 + 各国）",
    Math.abs(cmp.summaryT12m - cmp.t12m.aggSum) < 0.05,
    `kpi=${cmp.summaryT12m} aggSum=${cmp.t12m.aggSum}`);
}
ok("KPI 国家数 == 合计行以外的国家数",
  cmp.countryCount === cmp.distinctCountries - 1,
  `country_count=${cmp.countryCount} distinct=${cmp.distinctCountries}`);
ok("KPI 数字与 API 一致",
  cmp.kpiCurrentText.includes(String(cmp.summaryCurrent).replace(/\.0$/, "").split(".")[0]),
  `kpi="${cmp.kpiCurrentText}" summary=${cmp.summaryCurrent}`);
ok("KPI 国家数与 API 一致",
  cmp.kpiCountriesText === String(cmp.countryCount),
  `kpi="${cmp.kpiCountriesText}" summary=${cmp.countryCount}`);

// ─── 3. 合计行不进排名 / 不进堆叠图 ───
console.log("【3】合计行不进 Top 排名与堆叠图");
const dom = await page.evaluate(() => ({
  topIsos: [...document.querySelectorAll("#topBody tr td:nth-child(3)")]
    .map((e) => e.textContent.trim()),
  legend: (document.getElementById("chartLegend")?.textContent || "").trim(),
  detailHasAggr: /WGC_AGGR/.test(document.getElementById("detailBody")?.textContent || ""),
  detailAggrBadge: [...document.querySelectorAll("#detailBody tr")]
    .map((tr) => tr.textContent)
    .filter((t) => /WGC_AGGR/.test(t))
    .map((t) => (t.match(/WGC 合计|WGC 手工|WGC 报告/) || [""])[0]),
}));
ok("Top 10 排名里没有全球合计行",
  !dom.topIsos.includes("WGC_AGGR"), JSON.stringify(dom.topIsos));
ok("Top 10 排名里没有「全球合计」字样", !/全球合计/.test(dom.legend + dom.topIsos.join(",")));
ok("堆叠图图例里没有全球合计", !/全球合计|WGC_AGGR/.test(dom.legend), dom.legend);
ok("明细表里合计行仍可见（数据没被藏起来）", dom.detailHasAggr);
ok("合计行的来源标记是「WGC 合计」",
  dom.detailAggrBadge.length > 0 && dom.detailAggrBadge.every((b) => b === "WGC 合计"),
  JSON.stringify(dom.detailAggrBadge));

// ─── 4. 无前端错误 ───
console.log("【4】错误收口");
const errList = [...errs].filter((e) => !/favicon/i.test(e));
ok("无 console / pageerror / HTTP>=400", errList.length === 0, errList.slice(0, 5).join(" | "));

await browser.close();
console.log(`\n结果：${pass} passed, ${fail} failed`);
process.exit(fail === 0 ? 0 : 1);
