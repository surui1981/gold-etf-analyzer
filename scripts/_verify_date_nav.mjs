// scripts/_verify_date_nav.mjs
// V0.104 C4 验证：headlines 单日模式 + 日期导航
// 4 状态：默认 7天 / 选昨天 / 选今天 / 切回 7天
// 关键：拦截 /favorites/exists/* 避免 init 100 卡片并发把 rate limit 打满（V0.83.2 实测）
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

// 拦截 /favorites/exists/*（避免 100 卡片并发打满 rate limit）
await page.setRequestInterception(true);
page.on("request", (req) => {
  if (req.url().includes("/favorites/exists/")) {
    req.respond({ status: 200, contentType: "application/json", body: "{}" });
  } else {
    req.continue();
  }
});

function pad(n) { return String(n).padStart(2, "0"); }
function isoLocal(d) {
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}
const today = new Date();
const yesterday = new Date(today); yesterday.setDate(today.getDate() - 1);
const todayStr = isoLocal(today);
const yestStr = isoLocal(yesterday);

async function setDate(v) {
  await page.evaluate((val) => {
    const dp = document.getElementById("datePicker");
    const desc = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value");
    desc.set.call(dp, val);
    dp.dispatchEvent(new Event("change", { bubbles: true }));
  }, v);
  await new Promise(r => setTimeout(r, 2500));
}

async function readState() {
  return page.evaluate(() => ({
    dateNavHidden: document.getElementById("dateNav").hidden,
    activeRange: document.querySelector(".range-btns button.active")?.textContent.trim() || null,
    dateValue: document.getElementById("datePicker").value,
    prevDisabled: document.getElementById("btnPrevDay").disabled,
    nextDisabled: document.getElementById("btnNextDay").disabled,
    todayHidden: document.getElementById("btnToday").hidden,
    listCount: document.querySelectorAll(".news-card").length,
  }));
}

await page.goto("http://127.0.0.1:8888/headlines", { waitUntil: "networkidle0", timeout: 15000 });
await new Promise(r => setTimeout(r, 3000));

// 1) 初始：dateNav hidden, 7天 active
const s1 = await readState();
console.log(`\n[1] 初始（默认 7 天）:`, JSON.stringify(s1));

// 2) 选昨天
await setDate(yestStr);
const s2 = await readState();
console.log(`[2] 选昨天 (${yestStr}):`, JSON.stringify(s2));

// 3) 选今天（应触发 has_newer=False，▶ 禁用 + 回到今日隐藏）
await setDate(todayStr);
const s3 = await readState();
console.log(`[3] 选今天 (${todayStr}):`, JSON.stringify(s3));

// 4) 点 7 天按钮（应退出单日模式）
await page.evaluate(() => {
  document.querySelector('.range-btns button[data-days="7"]').click();
});
await new Promise(r => setTimeout(r, 2500));
const s4 = await readState();
console.log(`[4] 切回 7 天:`, JSON.stringify(s4));

// 5) 截图
await page.screenshot({ path: "/tmp/date_nav_4states.png" });
await browser.close();

// 验收断言
const pass = (cond, msg) => console.log(`  ${cond ? "✅" : "❌"} ${msg}`);
console.log("\n=== 验收 ===");
pass(s1.dateNavHidden === true, "[1] dateNav hidden");
pass(s1.activeRange === "7 天", "[1] rangeBtns 7 天 active");
pass(s1.listCount > 0, "[1] 列表非空");

pass(s2.dateNavHidden === false, "[2] dateNav 显示");
pass(s2.activeRange === null, "[2] rangeBtns 无 active");
pass(s2.dateValue === yestStr, "[2] datePicker = 昨天");
pass(s2.prevDisabled === false, "[2] ◀ 启用（有更早）");
pass(s2.todayHidden === false, "[2] 回到今日显示");

pass(s3.dateValue === todayStr, "[3] datePicker = 今天");
pass(s3.nextDisabled === true, "[3] ▶ 禁用（无更新）");
pass(s3.todayHidden === true, "[3] 回到今日隐藏");

pass(s4.dateNavHidden === true, "[4] dateNav hidden");
pass(s4.activeRange === "7 天", "[4] rangeBtns 7 天恢复 active");
