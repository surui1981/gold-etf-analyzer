// scripts/_verify_scoring_robust.mjs
// V0.116.4 验证：scoring「命中分析」Tab 在**接口兜底/异常**时不能整块崩掉
//
// 缺陷（真实复现，不是推演）：
//   static/scoring.js 的 fetchJson 在任何失败（429 限流 / 网络抖动 / 500）时
//   返回通用空壳 `{ rows: [], buckets: [], tags: [] }` —— 这个壳**没有**
//   sample_size / by_direction。而 renderHitStats 的守卫写的是
//   `data.sample_size === 0` ⇒ 兜底场景下 undefined !== 0 ⇒ 守卫不生效
//   ⇒ 落进 `for (const d of data.by_direction)` ⇒ `undefined is not iterable`
//   ⇒ TypeError ⇒ **整个「命中分析」Tab 渲染不出来**。
//
// 本门禁用**真实请求拦截**造出这两种响应，不靠「等它恰好撞上限流」：
//   A. 兜底空壳（缺 sample_size / by_direction）⇒ 必须显示空态、零 JS 错误
//   B. 正常 payload（有 by_direction）⇒ 必须正常渲染出方向卡（防「修成永远空态」）
//
// ⚠ 必须打 8888（主入口）。见记忆 lan-only-deployment。
// ⚠ 必须 setViewport(1352×900)。见记忆 puppeteer-viewport-sticky-nav。
import puppeteer from "puppeteer-core";

const BASE = process.env.BASE_URL || "http://127.0.0.1:8888";
const CHROME =
  "/home/surui/.cache/puppeteer/chrome/linux-153.0.8010.36/chrome-linux64/chrome";

let pass = 0;
let fail = 0;
function ok(name, cond, detail = "") {
  if (cond) {
    pass++;
    console.log(`  ✓ ${name}`);
  } else {
    fail++;
    console.log(`  ✗ ${name}${detail ? "  " + detail : ""}`);
  }
}

const browser = await puppeteer.launch({
  executablePath: CHROME,
  headless: "new",
  args: ["--no-sandbox", "--disable-dev-shm-usage"],
});
const page = await browser.newPage();
await page.setViewport({ width: 1352, height: 900 });
// ⚠ 必须绕过 Service Worker（V0.118.0 修）：static/sw.js 的 API 分支是
//   network-first，但 **SW 自己的 fetch() 不走 puppeteer 的页面级请求拦截**
//   （Fetch 域只挂在 page target 上）。而 sw.js 有 skipWaiting + clients.claim()，
//   所以**第 1 次导航后 SW 就会接管页面** —— 于是：
//     场景 A（第 1 次导航）→ 拦截生效 → 拿到兜底空壳 ✓（但这也取决于 SW 尚未激活，是竞态）
//     场景 B（第 2 次导航）→ 请求由 SW 转发，拦截**静默失效** ⇒ 页面拿到真实接口数据
//        ⇒ desc 变成 "sample=27"（真实值）而不是 mock 的 "sample=12"
//        ⇒ 门禁稳定报红，看起来像「scoring 渲染坏了」，实际是门禁自己的 mock 失效了。
//   绕过 SW 后两次导航都直接走网络 ⇒ 拦截稳定生效 ⇒ 门禁可重入。
await page.setBypassServiceWorker(true);
// ⚠ 独立限流桶（X-Forwarded-For）：服务端按 IP 做 600 req/min 滑动窗口限速，
//   多个门禁连着跑会互相抢额度 ⇒ 429 ⇒ 假失败。见记忆 browser-gate-429-rate-limit。
await page.setExtraHTTPHeaders({ "X-Forwarded-For": "198.51.100.78" });

const pageErrors = [];
page.on("pageerror", (e) => pageErrors.push(String(e && e.message ? e.message : e)));

// ─── A. 接口返回「兜底空壳」⇒ 不能崩 ───
console.log("\n【A】hit-stats 返回兜底空壳（缺 sample_size / by_direction）");
await page.setRequestInterception(true);
page.on("request", (req) => {
  const url = req.url();
  if (url.includes("/api/v1/scoring/hit-stats?")) {
    // fetchJson 的错误兜底返回的就是这个形状（scoring.js:318）
    req.respond({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ rows: [], buckets: [], tags: [] }),
    });
    return;
  }
  req.continue();
});

await page.goto(`${BASE}/static/scoring.html`, { waitUntil: "networkidle2" });
await page.waitForSelector('[data-tab="hit"]');
await page.click('[data-tab="hit"]');
await new Promise((r) => setTimeout(r, 900));

const shellCase = await page.evaluate(() => {
  const desc = document.getElementById("hitDesc");
  const stats = document.getElementById("hitStats");
  return {
    desc: desc ? desc.textContent.trim() : null,
    statsHTML: stats ? stats.innerHTML.trim() : null,
    // 「没有数据」时不该出现 undefined 字面量
    hasUndefined: /undefined|NaN/.test((desc ? desc.textContent : "") + (stats ? stats.innerHTML : "")),
  };
});
ok("兜底场景零 pageerror（不能再抛 undefined is not iterable）",
   pageErrors.filter((e) => /by_direction|not iterable/.test(e)).length === 0,
   JSON.stringify(pageErrors.slice(0, 3)));
ok("兜底场景显示空态文案", !!shellCase.desc && shellCase.desc.length > 0, JSON.stringify(shellCase.desc));
ok("兜底场景没有 undefined / NaN 泄漏", !shellCase.hasUndefined, JSON.stringify(shellCase).slice(0, 160));
ok("兜底场景不渲染方向卡（本来就没数据）",
   !/stat-grid/.test(shellCase.statsHTML || ""), (shellCase.statsHTML || "").slice(0, 80));

// ─── B. 正常 payload ⇒ 必须真的渲染（防「修成永远空态」）───
console.log("\n【B】hit-stats 返回正常 payload ⇒ 仍要渲染出方向卡");
page.removeAllListeners("request");
await page.setRequestInterception(true);
page.on("request", (req) => {
  const url = req.url();
  if (url.includes("/api/v1/scoring/hit-stats?")) {
    req.respond({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        sample_size: 12,
        overall_hit_rate: 0.5833,
        by_direction: [
          { direction: "up", hit_count: 5, total: 8, hit_rate: 0.625 },
          { direction: "down", hit_count: 2, total: 4, hit_rate: 0.5 },
        ],
        calibration: [],
      }),
    });
    return;
  }
  req.continue();
});

pageErrors.length = 0;
await page.goto(`${BASE}/static/scoring.html`, { waitUntil: "networkidle2" });
await page.waitForSelector('[data-tab="hit"]');
await page.click('[data-tab="hit"]');
await new Promise((r) => setTimeout(r, 900));

const normalCase = await page.evaluate(() => {
  const desc = document.getElementById("hitDesc");
  const stats = document.getElementById("hitStats");
  return {
    desc: desc ? desc.textContent.trim() : "",
    hasGrid: /stat-grid/.test(stats ? stats.innerHTML : ""),
    hasUp: /up/.test(stats ? stats.innerHTML : ""),
    hasDown: /down/.test(stats ? stats.innerHTML : ""),
  };
});
ok("正常 payload 零 pageerror", pageErrors.length === 0, JSON.stringify(pageErrors.slice(0, 3)));
ok("正常 payload 渲染出方向卡（没被修成永远空态）", normalCase.hasGrid, JSON.stringify(normalCase).slice(0, 160));
ok("正常 payload 两个方向都在", normalCase.hasUp && normalCase.hasDown, JSON.stringify(normalCase).slice(0, 160));
ok("正常 payload 描述行带 sample 与命中率", /sample=12/.test(normalCase.desc), normalCase.desc);

// ─── C. 真实数据 ⇒ a11y 数据表兜底不能「浮在页面上方」（V0.127.2）───
// ⚠ A/B 两个场景都 mock 了 hit-stats（没有 buckets）⇒ 命中分析图**不渲染**，
//   也就没有 a11y 兜底表 ⇒ 这里必须放行**真实接口**（关掉拦截）才测得到。
console.log("\n【C】命中分析图的 a11y 数据表落点（不溢出固定高度容器）");
page.removeAllListeners("request");
await page.setRequestInterception(false);
await page.goto(`${BASE}/static/scoring.html`, { waitUntil: "networkidle2" });
await page.waitForSelector('[data-tab="hit"]');
await page.click('[data-tab="hit"]');
await page.waitForFunction(
  () => !!document.querySelector('details.pm-chart-fallback[data-pm-a11y-for="hitChart"]'),
  { timeout: 25000 },
).catch(() => {});
const a11yCase = await page.evaluate(() => {
  const d = document.querySelector('details.pm-chart-fallback[data-pm-a11y-for="hitChart"]');
  if (!d) return { has: false };
  const host = d.parentElement;
  const hb = host.getBoundingClientRect();
  const db = d.getBoundingClientRect();
  d.open = true;
  const r = d.getBoundingClientRect();
  const covered = [];
  document.querySelectorAll("canvas, table, h2, .desc, .hit-mini, .hit-mini-grid, .stat-grid").forEach((t) => {
    if (d.contains(t)) return;
    const tr = t.getBoundingClientRect();
    if (!tr.width || !tr.height) return;
    const ix = Math.min(r.right, tr.right) - Math.max(r.left, tr.left);
    const iy = Math.min(r.bottom, tr.bottom) - Math.max(r.top, tr.top);
    if (ix > 2 && iy > 2) {
      covered.push({ el: t.id || t.className || t.tagName, ix: +ix.toFixed(1), iy: +iy.toFixed(1) });
    }
  });
  return {
    has: true,
    over: db.bottom > hb.bottom + 1 || db.right > hb.right + 1,
    hostBottom: +hb.bottom.toFixed(1),
    dBottom: +db.bottom.toFixed(1),
    covered,
  };
});
ok("命中分析图有 a11y 数据表兜底", a11yCase.has === true, JSON.stringify(a11yCase).slice(0, 200));
ok("命中分析的 a11y 数据表没有溢出图表容器", a11yCase.has === true && a11yCase.over !== true,
  JSON.stringify(a11yCase).slice(0, 200));
ok("命中分析的 a11y 数据表展开后不遮挡下方内容",
  a11yCase.has === true && (a11yCase.covered || []).length === 0,
  JSON.stringify(a11yCase.covered || []).slice(0, 200));

// ─── C. 金价列必须有真实数值（V0.128.4 修的故障）───
// ⚠ 2026-11-24 用户报「scoring 页面的金价数据没有同步更新」。
//   根因：``gold_price_daily`` 没有调度器刷新 ⇒ 停在 11-11 ⇒
//   ``scoring_daily_wide.gold_ny_close`` 为 NULL ⇒ 该列整列「—」。
//   ⇒ 断言「最近几行（交易日）必须有金价数值」—— 只查**前几行**，
//   因为周末/源缺口（实测 11-21 源里没有） legitimately 是「—」。
console.log("\n【D】金价列必须有真实数值");
await page.goto(`${BASE}/static/scoring.html`, { waitUntil: "networkidle2", timeout: 60000 });
await page.waitForSelector("table tbody tr", { timeout: 20000 });
await new Promise((r) => setTimeout(r, 2500));
const goldCol = await page.evaluate(() => {
  const ths = Array.from(document.querySelectorAll("table thead th"));
  const idx = ths.findIndex((th) => (th.textContent || "").includes("NY金"));
  if (idx < 0) return { noCol: true };
  const rows = Array.from(document.querySelectorAll("table tbody tr")).slice(0, 6);
  const vals = rows.map((tr) => {
    const tds = tr.querySelectorAll("td");
    return {
      date: (tds[0]?.textContent || "").trim(),
      gold: (tds[idx]?.textContent || "").trim(),
    };
  });
  return { idx, vals };
});
ok("表格有「NY金美元/盎司收盘」列", !goldCol.noCol, JSON.stringify(goldCol).slice(0, 200));
const withPrice = (goldCol.vals || []).filter((v) => v.gold && v.gold !== "—");
ok("最近几行有真实金价数值（不是整列「—」）", withPrice.length >= 3,
  JSON.stringify(goldCol.vals));
ok("金价数值是合理的美元/盎司量级",
  withPrice.every((v) => {
    const n = Number(String(v.gold).replace(/,/g, ""));
    return isFinite(n) && n > 500 && n < 20000;
  }),
  JSON.stringify(withPrice));

await browser.close();
console.log(`\n${"=".repeat(56)}`);
console.log(`  结果：${pass} passed, ${fail} failed`);
console.log("=".repeat(56));
process.exit(fail === 0 ? 0 : 1);
