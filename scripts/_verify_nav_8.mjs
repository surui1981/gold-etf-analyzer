// scripts/_verify_nav_8.mjs
// V0.111.1 验证：数据健康降为「配置」子页后，顶 nav 回到 8 项 + 两处导航同序
//
// ⚠ 必须打 8888（主入口）。8889/gold/ 是备用入口且全站 /api/v1/* 404，
//   在那里跑只会得到与本改动无关的假失败。见记忆 lan-only-deployment。
import puppeteer from "puppeteer-core";

const BASE = process.env.BASE_URL || "http://127.0.0.1:8888";
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
const bad = [];
page.on("response", (r) => {
  if (r.status() >= 400 && !/favicon/.test(r.url())) bad.push(`${r.status()} ${r.url()}`);
});

// 顶 nav 项抽取（排除 brand —— 它也是 <a> 但不是场景项）
async function readTopnav() {
  return page.$$eval(".topnav a, .topnav-item", (els) =>
    els
      .filter((e) => !String(e.className).includes("brand"))
      .map((e) => ({
        href: e.getAttribute("href") || "",
        text: e.textContent.trim(),
        active: String(e.className).includes("active"),
      }))
  );
}

// ─── 1. 顶 nav 8 项 ───
console.log("【1】顶 nav 项数");
await page.goto(`${BASE}/home`, { waitUntil: "networkidle2" });
await page.waitForSelector(".topnav a", { timeout: 15000 });
const nav = await readTopnav();
ok("顶 nav 8 个场景项", nav.length === 8, `实际 ${nav.length}：${nav.map((n) => n.text).join(" / ")}`);

const labels = nav.map((n) => n.text);
ok("数据健康不再是顶项", !labels.some((t) => t.includes("数据健康")), labels.join(" / "));
ok("AI 智能分析仍是顶项", labels.some((t) => t.includes("AI 智能分析")));
ok("AI 排在最后一项", (labels[labels.length - 1] || "").includes("AI 智能分析"), labels[labels.length - 1]);

const EXPECTED = ["首页", "今日要闻", "决策", "持仓", "情报", "报告存档", "配置", "AI 智能分析"];
const got = nav.map((n) => {
  const e = EXPECTED.find((x) => n.text.includes(x));
  return e || `?(${n.text})`;
});
ok("顺序与预期一致", JSON.stringify(got) === JSON.stringify(EXPECTED), got.join(" → "));

// ─── 2. 配置的 subnav 含数据健康 ───
console.log("\n【2】配置子页");
await page.goto(`${BASE}/weights`, { waitUntil: "networkidle2" });
await page.waitForSelector(".topnav a", { timeout: 15000 });
const sub = await page.$$eval(".subnav a, .subnav-item, .subnav .tab", (els) =>
  els.map((e) => ({ href: e.getAttribute("href") || "", text: e.textContent.trim() }))
);
ok("配置渲染出 subnav", sub.length >= 3, `实际 ${sub.length}：${sub.map((s) => s.text).join(" / ")}`);
ok("subnav 含数据健康", sub.some((s) => s.text.includes("数据健康")), sub.map((s) => s.text).join(" / "));
ok("subnav 仍含权重配置 + 通知中心",
  sub.some((s) => s.text.includes("权重配置")) && sub.some((s) => s.text.includes("通知中心")));

const navOnWeights = await readTopnav();
const activeTop = navOnWeights.find((n) => n.active);
ok("在 /weights 时「配置」高亮", (activeTop?.text || "").includes("配置"), activeTop?.text);

// ─── 3. 数据健康页：高亮回归 + 仍是独立场景渲染 ───
console.log("\n【3】数据健康页");
await page.goto(`${BASE}/data-health`, { waitUntil: "networkidle2" });
await page.waitForSelector(".topnav a", { timeout: 15000 });
const navHealth = await readTopnav();
const activeHealth = navHealth.find((n) => n.active);
ok("数据健康页高亮「配置」（不再是独立顶项）", (activeHealth?.text || "").includes("配置"), activeHealth?.text);
const subOnHealth = await page.$$eval(".subnav a, .subnav-item, .subnav .tab", (els) =>
  els.map((e) => ({ text: e.textContent.trim(), active: String(e.className).includes("active") }))
);
const healthTab = subOnHealth.find((s) => s.text.includes("数据健康"));
ok("数据健康子页自身高亮", !!healthTab?.active, JSON.stringify(subOnHealth));
// 别名会 307 到静态页，必须真的落到 data-health 内容上
const hTitle = await page.evaluate(() => document.body.innerText.slice(0, 200));
ok("数据健康页内容正常（非 404）", !/404 Not Found/i.test(hTitle), hTitle.slice(0, 60));

// ─── 4. 首页 8 张板块 ───
console.log("\n【4】首页板块");
await page.goto(`${BASE}/home`, { waitUntil: "networkidle2" });
await page.waitForSelector(".home-scene", { timeout: 15000 });
const cards = await page.$$eval(".home-scene", (els) =>
  els.map((e) => ({
    href: e.getAttribute("href"),
    title: (e.querySelector(".scene-title") || {}).textContent || "",
    items: Array.from(e.querySelectorAll(".scene-links li")).map((li) => li.textContent.trim()),
  }))
);
// V0.111.1 定稿：首页 8 张板块。数据健康虽是「配置」的子页，但仍保留自己的首页卡
// （它有独立的摘要信息，是用户常回看的页面）—— 所以首页卡与顶 nav **不是**一一对应。
ok("首页 8 张场景卡", cards.length === 8, `实际 ${cards.length}：${cards.map((c) => c.title).join(" / ")}`);
ok("首页有数据健康卡", cards.some((c) => c.title.includes("数据健康")), cards.map((c) => c.title).join(" / "));
ok("AI 卡在最后", (cards[cards.length - 1]?.title || "").includes("AI 智能分析"), cards[cards.length - 1]?.title);
ok("无 undefined 泄漏", !cards.some((c) => c.title.includes("undefined")));

const cfg = cards.find((c) => (c.href || "").includes("weights"));
ok("配置卡列出 3 个子项（含数据健康）", cfg?.items.length === 3 && cfg.items.some((i) => i.includes("数据健康")), JSON.stringify(cfg?.items));

const hl = cards.find((c) => c.title.includes("数据健康"));
ok("数据健康卡指向 /data-health 别名", hl?.href === "/data-health", hl?.href);

// 首页卡顺序 = 顶 nav 去掉「首页」，再在「配置」后补回「数据健康」
const EXPECTED_CARDS = ["今日要闻", "决策", "持仓", "情报", "报告存档", "配置", "数据健康", "AI 智能分析"];
const gotCards = cards.map((c) => EXPECTED_CARDS.find((x) => c.title.includes(x)) || `?(${c.title})`);
ok("首页卡顺序与顶 nav 一致", JSON.stringify(gotCards) === JSON.stringify(EXPECTED_CARDS), gotCards.join(" → "));

// ─── 5. 三语 ───
console.log("\n【5】三语");
for (const [lang, expect] of [["en-US", "Data Health"], ["zh-TW", "數據健康"], ["zh-CN", "数据健康"]]) {
  await page.goto(`${BASE}/weights`, { waitUntil: "networkidle2" });
  await page.waitForSelector(".topnav a", { timeout: 15000 });
  await page.evaluate(async (l) => { await window.I18n.setLang(l); }, lang);
  await new Promise((r) => setTimeout(r, 500));
  const body = await page.evaluate(() => document.body.innerText);
  ok(`${lang} 「数据健康」子项已翻译`, body.includes(expect), `找不到「${expect}」`);
  ok(`${lang} 无 undefined 泄漏`, !body.includes("undefined"));
}
// 恢复中文，别把用户的浏览器留在测试语言上
await page.evaluate(async () => { await window.I18n.setLang("zh-CN"); });

// ─── 汇总 ───
console.log("\n【网络】");
const notFavicon = bad.filter((u) => !/favicon\.ico/.test(u));
ok("无 4xx/5xx", notFavicon.length === 0, JSON.stringify(notFavicon.slice(0, 5)));

await browser.close();
console.log(`\n${"=".repeat(56)}`);
console.log(`  结果：${pass} passed, ${fail} failed`);
console.log("=".repeat(56));
process.exit(fail === 0 ? 0 : 1);