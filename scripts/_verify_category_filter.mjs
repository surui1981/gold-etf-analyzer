// scripts/_verify_category_filter.mjs
// V0.105 C4 验证：headlines 类目筛选（5 类 + 多 switch）
// 7 状态：默认 / 财经 / 科技 / 创投 / 商业 / 其他 / 切回全部 / +date 联动
// 关键：拦截 /favorites/exists/* 避免 100 卡片 init 把 rate limit 打满（V0.83.2 实测）
import puppeteer from "puppeteer-core";

const browser = await puppeteer.launch({
  executablePath: "/home/surui/.cache/puppeteer/chrome/linux-153.0.8010.36/chrome-linux64/chrome",
  headless: "new",
  args: ["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"],
});
const page = await browser.newPage();
await page.setViewport({ width: 1400, height: 800 });
await page.setCacheEnabled(false);
// ⚠ 绕过 Service Worker（V0.118.0 修）：static/sw.js 会在第 1 次导航后
//   skipWaiting + clients.claim() 接管页面，而 **SW 自己的 fetch() 不走
//   puppeteer 的页面级请求拦截** ⇒ 拦截会在页面加载中途静默失效
//   （mock 不再生效 ⇒ 门禁要么假红、要么假绿）。绕过 SW 后拦截全程有效。
await page.setBypassServiceWorker(true);

await page.setRequestInterception(true);
page.on("request", (req) => {
  if (req.url().includes("/favorites/exists/")) {
    req.respond({ status: 200, contentType: "application/json", body: "{}" });
  } else {
    req.continue();
  }
});

const apiCalls = [];
page.on("request", (req) => {
  if (req.url().includes("/api/v1/news-feed/items") && !req.url().includes("/favorites")) {
    apiCalls.push(req.url());
  }
});

async function selectCategory(val) {
  await page.evaluate((v) => {
    const sel = document.getElementById("categorySel");
    if (!sel) return;
    // ⚠ V0.118.0 修：原型要按**元素实际类型**取，不能用 `A || B` 兜底。
    //   `HTMLInputElement.prototype` 永远有 "value" 描述符 ⇒ 兜底分支永远走不到
    //   ⇒ 用 **input** 的 setter 去写 <select> ⇒ 浏览器抛
    //   `TypeError: Illegal invocation` ⇒ 门禁启动即崩（V0.105.0 把
    //   #categorySel 从 input 改成 select 之后就一直崩）。
    const proto =
      sel instanceof HTMLSelectElement ? HTMLSelectElement.prototype : HTMLInputElement.prototype;
    const desc = Object.getOwnPropertyDescriptor(proto, "value");
    desc.set.call(sel, v);
    sel.dispatchEvent(new Event("change", { bubbles: true }));
  }, val);
  await new Promise((r) => setTimeout(r, 2500));
}

async function readState() {
  return page.evaluate(() => ({
    categorySel: document.getElementById("categorySel")?.value,
    categoryOptions: Array.from(document.getElementById("categorySel")?.options || []).map((o) => o.value),
    listCount: document.querySelectorAll(".news-card").length,
    activeRange: document.querySelector(".range-btns button.active")?.textContent.trim() || null,
  }));
}

await page.goto("http://127.0.0.1:8888/headlines", { waitUntil: "networkidle0", timeout: 15000 });
await new Promise((r) => setTimeout(r, 3500));

// 1) 初始：默认 7 天 + 全部
const s1 = await readState();
console.log(`\n[1] 初始:`, JSON.stringify(s1));

// 2) 选「财经」
await selectCategory("财经");
const s2 = await readState();
console.log(`[2] 选财经:`, JSON.stringify(s2));

// 3) 选「科技」
await selectCategory("科技");
const s3 = await readState();
console.log(`[3] 选科技:`, JSON.stringify(s3));

// 4) 选「创投」
await selectCategory("创投");
const s4 = await readState();
console.log(`[4] 选创投:`, JSON.stringify(s4));

// 5) 选「商业」
await selectCategory("商业");
const s5 = await readState();
console.log(`[5] 选商业:`, JSON.stringify(s5));

// 6) 选「其他」
await selectCategory("其他");
const s6 = await readState();
console.log(`[6] 选其他:`, JSON.stringify(s6));

// 7) 切回「全部」
await selectCategory("");
const s7 = await readState();
console.log(`[7] 切回全部:`, JSON.stringify(s7));

// 8) 选「财经」+ date 2026-10-18：正交叠加
await selectCategory("财经");
await page.evaluate(() => {
  const dp = document.getElementById("datePicker");
  const desc = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value");
  desc.set.call(dp, "2026-10-18");
  dp.dispatchEvent(new Event("change", { bubbles: true }));
});
await new Promise((r) => setTimeout(r, 2500));
const s8 = await readState();
console.log(`[8] 财经 + date 2026-10-18:`, JSON.stringify(s8));

// 9) 截图
await page.screenshot({ path: "/tmp/category_filter_8states.png" });
await browser.close();

// 验收断言
const pass = (cond, msg) => console.log(`  ${cond ? "✅" : "❌"} ${msg}`);
console.log("\n=== 验收 ===");

pass(s1.categorySel === "", "[1] categorySel 默认空（全部）");
pass(s1.listCount > 0, "[1] 列表非空");
pass(s1.categoryOptions.includes("财经"), "[1] categorySel 含「财经」option");
pass(s1.categoryOptions.includes("科技"), "[1] categorySel 含「科技」option");
pass(s1.categoryOptions.includes("创投"), "[1] categorySel 含「创投」option");
pass(s1.categoryOptions.includes("商业"), "[1] categorySel 含「商业」option");
pass(s1.categoryOptions.includes("其他"), "[1] categorySel 含「其他」option");

pass(s2.categorySel === "财经", "[2] categorySel = 财经");
pass(s2.listCount > 0, "[2] 列表非空（财经至少 1 条）");

pass(s3.categorySel === "科技", "[3] categorySel = 科技");
pass(s4.categorySel === "创投", "[4] categorySel = 创投");
pass(s5.categorySel === "商业", "[5] categorySel = 商业");
pass(s6.categorySel === "其他", "[6] categorySel = 其他");
pass(s7.categorySel === "", "[7] categorySel 切回空（全部）");

// API 验证：8 次请求都带 category 或 date 参数
const lastCall = apiCalls[apiCalls.length - 1];
pass(
  lastCall.includes("category=") && lastCall.includes("date="),
  `[8] API 联动: ${lastCall.slice(-100)}`
);
