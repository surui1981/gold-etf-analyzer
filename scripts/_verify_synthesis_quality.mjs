// scripts/_verify_synthesis_quality.mjs
// V0.118.1 验证：综合卡「数据质量」提示必须能区分**两种**降级。
//
// 背景：宏观因子新增「末次落库」兜底层（tier=lkg）之后，降级有了两档：
//   lkg   = 上游源当时不可用，用上次成功落库的真实读数顶替（真值，但旧）
//   static= 内置常量兜底（根本不是市场读数）
// 二者都必须出现在数据质量提示里 —— 只报 static 会让「用了旧真值」这种
// 降级对用户不可见，恰好违背本卡「不夸大可信度」的目的。
//
// 判据用后端给的 tier 字段（不是匹配中文 source 前缀）。
//
// ⚠ 必须 setBypassServiceWorker(true)：SW 接管页面后 mock 会静默失效
//    （第二次导航拿真实数据，断言看着绿其实没测到）。
// ⚠ mock 必须用**真实 schema**（从线上抓的原响应改字段），
//    凭想象编的 payload 会让断言假绿/假红。
import puppeteer from "puppeteer-core";
import { readFileSync } from "node:fs";

const BASE = process.env.BASE_URL || "http://192.168.0.204:8888";
const TREND_MOCK = process.env.TREND_MOCK || "/tmp/trend_gold.json";

const browser = await puppeteer.launch({
  executablePath:
    "/home/surui/.cache/puppeteer/chrome/linux-153.0.8010.36/chrome-linux64/chrome",
  headless: "new",
  args: ["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"],
});

const page = await browser.newPage();
await page.setViewport({ width: 1352, height: 900 });
await page.setBypassServiceWorker(true);

const ok = [];
const bad = [];
const check = (cond, label) => (cond ? ok : bad).push(label);

// ── 构造 mock：把 dxy 降级成 lkg、vix 降级成 static，其余保持 live ──
const trend = JSON.parse(readFileSync(TREND_MOCK, "utf8"));
const byKey = Object.fromEntries(trend.macro.factors.map((f) => [f.key, f]));
if (!byKey.dxy || !byKey.vix) {
  console.log("[FATAL] mock 里没有 dxy / vix 因子 —— schema 变了，先更新本脚本");
  await browser.close();
  process.exit(1);
}
byKey.dxy.tier = "lkg";
byKey.dxy.source = "末次落库·Yahoo DX-Y.NYB";
byKey.dxy.data_date = "2026-10-23";
byKey.vix.tier = "static";
byKey.vix.source = "静态参考值";
byKey.vix.data_date = "2026-08-28";
const mockBody = JSON.stringify(trend);

let mocked = 0;
await page.setRequestInterception(true);
page.on("request", (req) => {
  const url = req.url();
  if (url.includes("/api/v1/market/gold/trend")) {
    mocked++;
    req.respond({
      status: 200,
      contentType: "application/json; charset=utf-8",
      body: mockBody,
    });
    return;
  }
  req.continue();
});

const errs = [];
page.on("pageerror", (e) => errs.push("pageerror: " + e.message));
page.on("console", (m) => {
  const url = (m.location() && m.location().url) || "";
  if (m.type() === "error" && !url.includes("favicon")) {
    errs.push("console: " + m.text() + " @ " + url);
  }
});

await page.goto(BASE + "/static/trend.html", { waitUntil: "networkidle2" });

// 等质量提示区落定（两条 note 都要在）
let notes = [];
try {
  await page.waitForFunction(
    () => {
      const el = document.querySelector(".syn-qual");
      return !!el && el.textContent.trim().length > 0;
    },
    { timeout: 60000 },
  );
  notes = await page.evaluate(() => {
    const el = document.querySelector(".syn-qual");
    return el ? el.textContent.trim() : "";
  });
} catch (e) {
  check(false, `质量提示区在 60s 内出现：${e.message}`);
}

check(mocked > 0, `mock 命中了 trend 请求（拦截 ${mocked} 次）`);
check(notes.includes("降级读数"), `提示里有「降级读数」（lkg）：${JSON.stringify(notes.slice(0, 200))}`);
check(notes.includes("美元指数"), "lkg 提示点名了降级因子（美元指数）");
check(notes.includes("静态参考值"), `提示里有「静态参考值」（static）：${JSON.stringify(notes.slice(0, 200))}`);
check(notes.includes("VIX") || notes.includes("恐慌"), "static 提示点名了降级因子（VIX）");
check(!notes.includes("undefined"), "质量提示里无 undefined 泄漏");
check(errs.length === 0, `无 JS 报错：${JSON.stringify(errs.slice(0, 3))}`);

await page.screenshot({ path: "/tmp/v01181_synthesis_quality.png", fullPage: false });
await browser.close();

console.log("\n=== V0.118.1 综合卡数据质量提示（lkg / static 两档降级） ===");
ok.forEach((l) => console.log("  [OK  ] " + l));
bad.forEach((l) => console.log("  [FAIL] " + l));
console.log(`\n结果：${ok.length} passed, ${bad.length} failed`);
process.exit(bad.length ? 1 : 0);
