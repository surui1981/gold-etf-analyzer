// scripts/_verify_home_metals.mjs
// V0.115.0 验证：首页「贵金属走势」三卡（金价 / 黄金库存 / 央行购金）
//
// ⚠ 必须打 8888（主入口）。8889/gold/ 是备用入口且全站 /api/v1/* 404，
//   在那里跑只会得到与本改动无关的假失败。见记忆 lan-only-deployment。
// ⚠ 视口必须 1352×900：默认 800×600 下顶 nav 会盖住按钮，page.click 静默失效。
//   见记忆 puppeteer-viewport-sticky-nav。
import puppeteer from "puppeteer-core";

const BASE = process.env.BASE_URL || "http://127.0.0.1:8888";
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

// 三处错误来源分别收集 —— console 和 response 会把同一个 4xx 重复报一遍，
// 去重后打印，避免刷屏时看不出有几处真问题。见记忆 exemption-lists-rot-silently。
const errs = new Set();
page.on("pageerror", (e) => errs.add(`pageerror: ${String(e)}`));
page.on("console", (m) => { if (m.type() === "error") errs.add(`console: ${m.text()}`); });
page.on("response", (r) => {
  if (r.status() >= 400) errs.add(`HTTP ${r.status()} ${r.url()}`);
});

// ─── 1. 区块存在 + 位置在今日要闻之前 ───
console.log("【1】区块存在与位置");
await page.goto(`${BASE}/home`, { waitUntil: "networkidle2" });
// 等真实值而不是固定 sleep：金价/库存/央行三条线各一次 fetch，冷启动时序不稳定。
// 判据用 .metal-value 拿到数字，而不是等 li —— 那是骨架屏。
await page.waitForFunction(
  () => {
    const vals = [...document.querySelectorAll(".metal-card .metal-value")];
    return vals.length === 3 && vals.every((v) => /[\d]/.test(v.textContent));
  },
  { timeout: 30000 }
).catch(() => {});
ok("存在 .home-metals 区块", (await page.$(".home-metals")) !== null);

const order = await page.evaluate(() => {
  const metals = document.querySelector(".home-metals");
  const bottom = document.querySelector(".home-bottom");
  const newsCard = document.querySelector(".home-scene.scene-headlines");
  if (!metals || !bottom) return null;
  // DOCUMENT_POSITION_FOLLOWING === 4：metals 在 bottom 之前
  const beforeNewsList = !!(metals.compareDocumentPosition(bottom) & 4);
  // 板块卡 grid 里那张「今日要闻」磁贴仍在最前（本次没有动它）
  const firstScene = document.querySelector(".home-scene");
  return {
    beforeNewsList,
    gridFirstIsHeadlines: firstScene ? firstScene.className.includes("scene-headlines") : false,
    scenesCount: document.querySelectorAll(".home-scene").length,
    hasNewsList: !!document.getElementById("homeNewsList"),
  };
});
ok("取到 DOM 顺序信息", order !== null);
ok("贵金属区在底部今日要闻（.home-bottom）之前", !!order?.beforeNewsList);
ok("今日要闻新闻列表仍在", !!order?.hasNewsList);
ok("板块卡仍为 8 张（未动 grid）", order?.scenesCount === 8, `实际 ${order?.scenesCount}`);
ok("grid 首张仍是今日要闻磁贴", !!order?.gridFirstIsHeadlines);

// ─── 2. 三张卡都有真实数值 ───
console.log("【2】三张卡的真实数值（不是占位符）");
const cards = await page.evaluate(() => {
  return [...document.querySelectorAll(".metal-card")].map((c) => ({
    id: c.id,
    title: c.querySelector(".metal-title")?.textContent.trim() || "",
    value: c.querySelector(".metal-value")?.textContent.trim() || "",
    chg: c.querySelector(".metal-chg")?.textContent.trim() || "",
    badge: c.querySelector(".metal-badge")?.textContent.trim() || "",
    note: c.querySelector(".metal-note")?.textContent.trim() || "",
    empty: c.className.includes("is-empty"),
    sparkPaths: c.querySelectorAll("svg.metal-spark path").length,
    sparkD: c.querySelector("svg.metal-spark path")?.getAttribute("d") || "",
    subs: [...c.querySelectorAll(".metal-sub b")].map((b) => b.textContent.trim()),
  }));
});
ok("正好 3 张卡", cards.length === 3, `实际 ${cards.length}`);
for (const c of cards) {
  ok(`${c.id} 未走降级态`, !c.empty);
  // 央行卡主值是有符号的吨数（+288.9 / -12.4），正则必须放开 "+"
  ok(`${c.id} 主值是数字（不是 —/--）`, /^[+-]?\d/.test(c.value), `实际 "${c.value}"`);
  ok(`${c.id} 副标题已渲染`, c.badge.length > 0, `实际 "${c.badge}"`);
  ok(`${c.id} 走势线已画（path 有真实 d）`,
    c.sparkPaths >= 1 && /M-?[\d.]/.test(c.sparkD) && !c.sparkD.includes("NaN"),
    `paths=${c.sparkPaths} d="${c.sparkD.slice(0, 40)}"`);
}
ok("金价卡两条副行都有值",
  cards[0].subs.length === 2 && cards[0].subs.every((s) => /[\d]/.test(s)),
  JSON.stringify(cards[0].subs));
ok("库存卡 3 条副行都有值",
  cards[1].subs.length === 3 && cards[1].subs.every((s) => /[\d]/.test(s)),
  JSON.stringify(cards[1].subs));
ok("央行购金卡 2 条副行都有值",
  cards[2].subs.length === 2 && cards[2].subs.every((s) => /[\d]/.test(s)),
  JSON.stringify(cards[2].subs));
ok("库存卡标注了数据截止日（源是日频，不能当实时值看）",
  /数据截止|\d{4}-\d{2}-\d{2}/.test(cards[1].note), `实际 "${cards[1].note}"`);
ok("央行卡标注了数据截止季度",
  /2026Q|2025Q|数据截止/.test(cards[2].note + cards[2].badge),
  `note="${cards[2].note}" badge="${cards[2].badge}"`);

// ─── 3. hero 两个 chip 的字段名回归 ───
console.log("【3】hero 金价 / 时效 chip（V0.115.0 修的静默失效）");
const hero = await page.evaluate(() => ({
  gold: document.getElementById("homeGoldPrice")?.textContent.trim() || "",
  fresh: document.getElementById("homeFreshness")?.textContent.trim() || "",
}));
// 原先读 gold.value.price / fresh.value.overall_status —— 后端两个键都不返回，
// 两个 chip 从上线起一直停在「金价 --」/「时效 --」。
ok("hero 金价 chip 显示真实价格", /\d+\.\d+/.test(hero.gold), `实际 "${hero.gold}"`);
ok("hero 时效 chip 显示真实状态", /实时|降级/.test(hero.fresh), `实际 "${hero.fresh}"`);

// ─── 4. 总状态 chip ───
console.log("【4】区块状态 chip");
const chip = await page.evaluate(() =>
  document.getElementById("homeMetalsChip")?.textContent.trim() || "");
ok("状态 chip 显示 3/3（无卡片降级）", chip === "3/3", `实际 "${chip}"`);

// ─── 5. 三语 ───
console.log("【5】三语渲染");
const LANGS = [
  ["zh-CN", "贵金属走势", "金价变化", "黄金库存变化", "央行购金变化"],
  ["zh-TW", "貴金屬走勢", "金價變化", "黃金庫存變化", "央行購金變化"],
  ["en-US", "Precious Metals", "Gold Price", "Gold Inventory", "Central Bank Buying"],
];
for (const [lang, title, p, inv, cb] of LANGS) {
  // ⚠ 两个键名都踩过坑：localStorage 键是 **pm_lang**（i18n.js:26），
  //   全局是 **window.I18n**（i18n.js:238）不是 PM_I18N。写错任何一个都只是
  //   静默 no-op，页面照常回落 zh-CN，看起来像"切换功能坏了"。
  await page.evaluate(async (l) => {
    localStorage.setItem("pm_lang", l);
    if (window.I18n?.setLang) await window.I18n.setLang(l);
  }, lang);
  await page.reload({ waitUntil: "networkidle2" });
  await page.waitForFunction(
    () => {
      const vals = [...document.querySelectorAll(".metal-card .metal-value")];
      return vals.length === 3 && vals.every((v) => /[\d]/.test(v.textContent));
    },
    { timeout: 30000 }
  ).catch(() => {});
  // ⚠ 断言一律打在 textContent 上，不打 data-lang 属性：属性切了不代表
  //   字典已 apply 到 DOM（i18n-init-await 那轮踩过这个坑）。
const got = await page.evaluate(() => ({
    section: document.querySelector(".home-metals h3")?.textContent.trim() || "",
    titles: [...document.querySelectorAll(".metal-title")].map((e) => e.textContent.trim()),
  }));
  ok(`${lang} 区块标题`, got.section === title, `实际 "${got.section}"`);
  ok(`${lang} 三张卡标题`, JSON.stringify(got.titles) === JSON.stringify([p, inv, cb]),
    JSON.stringify(got.titles));
}

// ─── 6. 无前端错误 ───
console.log("【6】错误收口");
const errList = [...errs].filter((e) => !/favicon/i.test(e));
ok("无 console / pageerror / HTTP>=400", errList.length === 0, errList.slice(0, 5).join(" | "));

await browser.close();
console.log(`\n结果：${pass} passed, ${fail} failed`);
process.exit(fail === 0 ? 0 : 1);