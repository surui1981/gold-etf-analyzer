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

await browser.close();
console.log(`\n${"=".repeat(56)}`);
console.log(`  结果：${pass} passed, ${fail} failed`);
console.log("=".repeat(56));
process.exit(fail === 0 ? 0 : 1);
