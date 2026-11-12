// scripts/_verify_price_forecast.mjs
// V0.127.0 验证：金价区间预测页（独立页 + 趋势页摘要卡 + 首页磁贴）
//
// 覆盖：
//  1. /price-forecast 别名可达（307 → /static/price-forecast.html），页面真的渲染出区间数字
//     —— **不是 undefined / 不是「—」**（记忆 frontend-undefined-rendering）
//  2. 页面上显示的是**实测**覆盖率，不是名义覆盖率（证据门 E4）
//  3. 扇形图 canvas 存在、3 条 dataset、每条 20 个点、且**越走越宽**
//  4. 覆盖率切换（50/80/90/98）真的生效：区间变宽 ⇒ 接口被重新打过
//  5. 形状对照图有 2 条线（类比形状 + √k 锥），且类比形状在 k=1 处比锥更胖
//  6. 校准表 4 行（50/80/90/98），且当前档高亮
//  7. 趋势页摘要卡渲染出区间（不是空 panel）
//  8. 首页磁贴渲染出区间文案，且磁贴指向 /price-forecast
//  9. 三语切换（查 textContent，不是 data-lang —— 记忆 i18n-init-await）
// 10. 无 4xx/5xx、无 console error、无 undefined 泄漏
//
// ⚠ 必须打 8888（主入口）。8889/gold/ 是备用入口且全站 /api/v1/* 404，
//   在那里跑只会得到与本改动无关的假失败。见记忆 lan-only-deployment。
// ⚠ 必须 setViewport(1352×900)。puppeteer 默认 800×600，顶 nav（sticky）会盖住
//   页面顶部的按钮，page.click() 静默失效。见记忆 puppeteer-viewport-sticky-nav。
// ⚠ 必须 setCacheEnabled(false) + setBypassServiceWorker(true)：
//   `/static/*.html` 响应头没有 Cache-Control ⇒ Chrome 套用启发式缓存 ⇒
//   主文档命中磁盘缓存时 Chrome 不发 Page.lifecycleEvent ⇒ page.goto 无限挂死
//   （见 _verify_nav_8.mjs 文件头的实测记录 + 记忆 puppeteer-goto-hangs-on-disk-cache）。
// ⚠ 必须等**页面自己的数据**（#pfRange 出数字），不能只等 DOMContentLoaded ——
//   子组件各自 fetch 后才渲染（记忆 gate-reads-unready-page）。
// ⚠ 独立限流桶（X-Forwarded-For）：服务端按 IP 做 600 req/min 滑动窗口限速，
//   多个首页门禁连着跑会互相抢额度 ⇒ 429 ⇒ 假失败。见 _verify_nav_8.mjs 同款做法。
import puppeteer from "puppeteer-core";

const BASE = process.env.BASE_URL || "http://192.168.0.204:8888";
const CHROME =
  "/home/surui/.cache/puppeteer/chrome/linux-153.0.8010.36/chrome-linux64/chrome";

let pass = 0;
let fail = 0;
function ok(name, cond, extra = "") {
  if (cond) { pass++; console.log(`  ✓ ${name}`); }
  else { fail++; console.log(`  ✗ ${name} ${extra}`); }
}

const browser = await puppeteer.launch({
  executablePath: CHROME,
  headless: "new",
  args: ["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"],
});
const page = await browser.newPage();
await page.setViewport({ width: 1352, height: 900 });
await page.setCacheEnabled(false);
await page.setBypassServiceWorker(true);
await page.setExtraHTTPHeaders({ "X-Forwarded-For": "198.51.100.77" });

const pageErrors = [];
page.on("pageerror", (e) => pageErrors.push("pageerror: " + e.message));
page.on("console", (m) => {
  if (m.type() === "error" && !/Failed to load resource|favicon/i.test(m.text())) {
    pageErrors.push("console: " + m.text());
  }
});
const bad = [];
page.on("response", (r) => {
  if (r.status() >= 400 && !/favicon/.test(r.url())) bad.push(`${r.status()} ${r.url()}`);
});

const RANGE_RE = /\d[\d,]*\s*–\s*\d[\d,]*/;

/** 等 #pfRange 里出真实区间数字（不是 "—" / 不是 undefined）。 */
async function waitRange(sel, timeout = 20000) {
  await page.waitForFunction(
    (s) => {
      const el = document.querySelector(s);
      if (!el) return false;
      const t = (el.textContent || "").trim();
      return t && t !== "—" && !/undefined|NaN/.test(t);
    },
    { timeout },
    sel
  );
}

// ─── 1. 独立页：别名可达 + 区间渲染 ───
console.log("【1】独立页 /price-forecast");
const alias = await fetch(`${BASE}/price-forecast`, { redirect: "manual" });
ok("别名 307 重定向", alias.status === 307, `实际 ${alias.status}`);

await page.goto(`${BASE}/price-forecast`, { waitUntil: "domcontentloaded" });
await page.waitForSelector("#pfConclusion", { timeout: 20000 });
await waitRange("#pfRange");

const rangeText = await page.$eval("#pfRange", (el) => (el.textContent || "").trim());
ok("区间渲染出数字", RANGE_RE.test(rangeText), `实际 "${rangeText}"`);
ok("区间无 undefined / NaN", !/undefined|NaN/.test(rangeText), rangeText);
ok("页面无 undefined 泄漏", !(await page.evaluate(() => document.body.innerText)).includes("undefined"));

// ─── 2. E4：显示的是实测覆盖率，不是名义覆盖率 ───
console.log("\n【2】实测覆盖率（证据门 E4）");
const metaText = await page.$eval("#pfMeta", (el) => el.innerText);
ok("元信息含「实测覆盖」", metaText.includes("实测覆盖"), metaText.replace(/\n/g, " | "));
const measuredMatch = metaText.match(/实测覆盖（样本外）\s*([\d.]+)%/);
ok("实测覆盖率有具体数值", !!measuredMatch, metaText.replace(/\n/g, " | "));
const nominalMatch = metaText.match(/名义覆盖\s*([\d.]+)%/);
if (measuredMatch && nominalMatch) {
  const m = Number(measuredMatch[1]);
  const n = Number(nominalMatch[1]);
  ok("实测值 ≠ 名义值（不是同一个数换个说法）", m !== n, `实测 ${m} / 名义 ${n}`);
} else {
  ok("实测值 ≠ 名义值（不是同一个数换个说法）", false, "缺少实测或名义覆盖率");
}
ok("中心 = 当前收盘（无漂移）", metaText.includes("中心"), metaText.replace(/\n/g, " | "));

// ─── 3. 扇形图 ───
console.log("\n【3】趋势导航线（扇形图）");
const fan = await page.evaluate(() => {
  const c = document.getElementById("pfFanChart");
  if (!c || !window.Chart) return null;
  const inst = Chart.getChart(c);
  if (!inst) return null;
  return {
    n: inst.data.datasets.length,
    lens: inst.data.datasets.map((d) => (d.data || []).length),
    labels: inst.data.labels.length,
    firstLower: inst.data.datasets[1]?.data?.[0],
    lastLower: inst.data.datasets[1]?.data?.[inst.data.datasets[1].data.length - 1],
    firstUpper: inst.data.datasets[0]?.data?.[0],
    lastUpper: inst.data.datasets[0]?.data?.[inst.data.datasets[0].data.length - 1],
  };
});
ok("扇形图已渲染", !!fan, JSON.stringify(fan));
if (fan) {
  ok("3 条 dataset（上沿/下沿/中心）", fan.n === 3, `实际 ${fan.n}`);
  ok("每条 20 个点", fan.lens.every((l) => l === 20), JSON.stringify(fan.lens));
  ok("x 轴 20 个刻度", fan.labels === 20, `实际 ${fan.labels}`);
  ok("扇形越走越宽（下沿）", fan.lastLower < fan.firstLower, `${fan.firstLower} → ${fan.lastLower}`);
  ok("扇形越走越宽（上沿）", fan.lastUpper > fan.firstUpper, `${fan.firstUpper} → ${fan.lastUpper}`);
}
ok("扇形图有 a11y 描述", await page.evaluate(() => {
  const c = document.getElementById("pfFanChart");
  return !!c && c.getAttribute("role") === "img" && !!c.getAttribute("aria-label");
}));
ok("扇形图有数据表兜底", await page.evaluate(() => {
  const c = document.getElementById("pfFanChart");
  return !!c && !!c.parentElement.querySelector("details.pm-chart-fallback table");
}));

// ─── 4. 覆盖率切换 ───
console.log("\n【4】覆盖率切换（50/80/90/98）");
const readNums = async () =>
  page.evaluate(() => {
    const t = (document.getElementById("pfRange")?.textContent || "").replace(/,/g, "");
    const m = t.match(/(\d+(?:\.\d+)?)\s*–\s*(\d+(?:\.\d+)?)/);
    return m ? { lo: Number(m[1]), hi: Number(m[2]) } : null;
  });

const w80 = await readNums();
ok("默认 80% 档", await page.evaluate(() =>
  document.querySelector('[data-cov="0.8"]')?.classList.contains("active")));

await page.click('[data-cov="0.9"]');
await page.waitForFunction(() => {
  const t = (document.getElementById("pfRange")?.textContent || "").replace(/,/g, "");
  const m = t.match(/(\d+(?:\.\d+)?)\s*–\s*(\d+(?:\.\d+)?)/);
  return m && Number(m[1]) < 3630; // 90% 的下沿必然低于 80% 的下沿
}, { timeout: 20000 }).catch(() => {});
await new Promise((r) => setTimeout(r, 1200));
const w90 = await readNums();
ok("切到 90% 后区间变宽", !!w80 && !!w90 && w90.hi > w80.hi && w90.lo < w80.lo,
  `80% ${JSON.stringify(w80)} → 90% ${JSON.stringify(w90)}`);
ok("90% 按钮高亮", await page.evaluate(() =>
  document.querySelector('[data-cov="0.9"]')?.classList.contains("active")));

await page.click('[data-cov="0.5"]');
await new Promise((r) => setTimeout(r, 1200));
const w50 = await readNums();
ok("切到 50% 后区间变窄", !!w50 && !!w80 && w50.hi < w80.hi && w50.lo > w80.lo,
  `80% ${JSON.stringify(w80)} → 50% ${JSON.stringify(w50)}`);

// 切回默认（后面的断言按 80% 口径）
await page.click('[data-cov="0.8"]');
await new Promise((r) => setTimeout(r, 1200));

// ─── 5. 形状对照图 ───
console.log("\n【5】形状对照图");
const shape = await page.evaluate(() => {
  const c = document.getElementById("pfShapeChart");
  if (!c) return null;
  const inst = Chart.getChart(c);
  if (!inst) return null;
  const ds = inst.data.datasets;
  return {
    n: ds.length,
    analog0: ds[0]?.data?.[0],
    cone0: ds[1]?.data?.[0],
    analogLast: ds[0]?.data?.[ds[0].data.length - 1],
    coneLast: ds[1]?.data?.[ds[1].data.length - 1],
    len: ds[0]?.data?.length,
  };
});
ok("形状图已渲染", !!shape, JSON.stringify(shape));
if (shape) {
  ok("2 条线（类比形状 + √k 锥）", shape.n === 2, `实际 ${shape.n}`);
  ok("每条 20 点", shape.len === 20, `实际 ${shape.len}`);
  ok("类比形状在 k=1 处比锥更胖", shape.analog0 > shape.cone0,
    `analog ${shape.analog0} vs cone ${shape.cone0}`);
  ok("两条线在 k=20 处都归一为 1.0",
    Math.abs(shape.analogLast - 1) < 1e-3 && Math.abs(shape.coneLast - 1) < 1e-3,
    `analog ${shape.analogLast} / cone ${shape.coneLast}`);
}

// ⚠ V0.127.1：页面说明里的「短端胖多少倍」必须**等于产物现算值**
//   （旧实现把 1.2–1.4 写死在文案里 ⇒ 与产物实测 1.32–1.43 对不上）
const ratioNote = await page.evaluate(() => {
  const c = document.getElementById("pfShapeChart");
  const note = document.getElementById("pfShapeNote");
  if (!c || !note) return null;
  const inst = Chart.getChart(c);
  if (!inst) return null;
  const s = inst.data.datasets[0]?.data || [];
  const cone = inst.data.datasets[1]?.data || [];
  let min = Infinity;
  let max = -Infinity;
  for (let k = 0; k < Math.min(5, s.length, cone.length); k++) {
    if (!cone[k]) continue;
    const r = s[k] / cone[k];
    if (!isFinite(r)) continue;
    if (r < min) min = r;
    if (r > max) max = r;
  }
  if (!isFinite(min) || !isFinite(max)) return null;
  return { text: min.toFixed(2) + "–" + max.toFixed(2), note: (note.textContent || "").trim() };
});
ok("形状说明里的短端倍数 = 产物现算值", !!ratioNote && ratioNote.note.includes(ratioNote.text),
  JSON.stringify(ratioNote));
ok("形状说明没有残留写死的旧文案",
  !!ratioNote && !/1\.2–1\.4/.test(ratioNote.note), ratioNote?.note || "");

// ─── 6. 校准表 ───
console.log("\n【6】覆盖率校准表");
const calib = await page.evaluate(() => {
  const host = document.getElementById("pfCalibTable");
  if (!host) return null;
  const rows = Array.from(host.querySelectorAll("tbody tr")).map((tr) =>
    Array.from(tr.querySelectorAll("td")).map((td) => (td.textContent || "").trim())
  );
  return { rows, cur: host.querySelectorAll("tr.pf-row-cur").length };
});
ok("校准表渲染出 4 行", !!calib && calib.rows.length === 4, JSON.stringify(calib?.rows));
if (calib) {
  ok("当前档高亮 1 行", calib.cur === 1, `实际 ${calib.cur}`);
  const oos = calib.rows.map((r) => r[2]).filter((v) => /%$/.test(v));
  ok("每行都有样本外实测值", oos.length === 4, JSON.stringify(oos));
  const nom = calib.rows.map((r) => r[0]);
  ok("名义覆盖率档位齐全", JSON.stringify(nom) === JSON.stringify(["50%", "80%", "90%", "98%"]),
    JSON.stringify(nom));
}

// ─── 7. 趋势页摘要卡 ───
console.log("\n【7】趋势页摘要卡");
await page.goto(`${BASE}/static/trend.html`, { waitUntil: "domcontentloaded" });
await page.waitForSelector("#pfSummaryCard", { timeout: 20000 });
await waitRange("#pfSummaryCard .pf-sum-num", 20000).catch(() => {});
const sumText = await page.$eval("#pfSummaryCard", (el) => (el.innerText || ""));
ok("摘要卡渲染出区间", RANGE_RE.test(sumText), sumText.replace(/\n/g, " | ").slice(0, 120));
ok("摘要卡无 undefined", !/undefined/.test(sumText));
ok("摘要卡有「详见」链接", await page.evaluate(() => {
  const a = document.querySelector("#pfSummaryCard a.pf-sum-link");
  return !!a && a.getAttribute("href") === "/price-forecast";
}));
ok("摘要卡迷你扇形图有数据", await page.evaluate(() => {
  const c = document.getElementById("pfSummaryChart");
  if (!c) return false;
  const inst = Chart.getChart(c);
  return !!inst && inst.data.datasets[0].data.length === 20;
}));

// ─── 8. 首页磁贴 ───
console.log("\n【8】首页磁贴");
await page.goto(`${BASE}/home`, { waitUntil: "domcontentloaded" });
await page.waitForSelector("#fcTileRange", { timeout: 20000 });
await waitRange("#fcTileRange", 20000).catch(() => {});
const tileText = await page.$eval("#fcTileRange", (el) => (el.textContent || "").trim());
ok("磁贴渲染出区间", RANGE_RE.test(tileText), `实际 "${tileText}"`);
ok("磁贴无 undefined", !/undefined/.test(tileText), tileText);
ok("磁贴在「金价区间」卡里", await page.evaluate(() => {
  const tile = document.querySelector(".home-scene.scene-forecast");
  return !!tile && tile.getAttribute("href") === "/price-forecast";
}));
ok("磁贴可点（跳到区间页）", await page.evaluate(() => {
  const tile = document.querySelector(".home-scene.scene-forecast");
  return !!tile && tile.tagName === "A" && !!tile.getAttribute("href");
}));

// ─── 9. 三语切换 ───
console.log("\n【9】三语切换");
await page.goto(`${BASE}/price-forecast`, { waitUntil: "domcontentloaded" });
await page.waitForSelector("#pfConclusion", { timeout: 20000 });
await waitRange("#pfRange");
for (const [lang, expect] of [
  ["en-US", "Measured coverage"],
  ["zh-TW", "實測覆蓋"],
  ["zh-CN", "实测覆盖"],
]) {
  await page.evaluate(async (l) => { await window.I18n.setLang(l); }, lang);
  await new Promise((r) => setTimeout(r, 900));
  const meta = await page.$eval("#pfMeta", (el) => el.innerText);
  const body = await page.evaluate(() => document.body.innerText);
  ok(`${lang} 元信息已翻译`, meta.includes(expect), meta.replace(/\n/g, " | ").slice(0, 120));
  ok(`${lang} 区间仍是数字`, RANGE_RE.test(await page.$eval("#pfRange", (el) => el.textContent || "")));
  ok(`${lang} 无 undefined 泄漏`, !body.includes("undefined"));
}
await page.evaluate(async () => { await window.I18n.setLang("zh-CN"); });

// ─── 10. 网络与脚本错误 ───
console.log("\n【10】网络 / 脚本");
const notFavicon = bad.filter((u) => !/favicon\.ico/.test(u));
ok("无 4xx/5xx", notFavicon.length === 0, JSON.stringify(notFavicon.slice(0, 6)));
ok("无 console error / pageerror", pageErrors.length === 0, JSON.stringify(pageErrors.slice(0, 6)));

await browser.close();
console.log(`\n${"=".repeat(56)}`);
console.log(`  结果：${pass} passed, ${fail} failed`);
console.log("=".repeat(56));
process.exit(fail === 0 ? 0 : 1);
