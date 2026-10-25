// scripts/_diag_palette_decision.mjs
// 诊断：命令面板里输入「决策」，看列出什么、默认选中哪条、按回车落到哪个页面。
import puppeteer from "puppeteer-core";

const BASE = process.env.BASE_URL || "http://127.0.0.1:8888";
const CHROME =
  "/home/surui/.cache/puppeteer/chrome/linux-153.0.8010.36/chrome-linux64/chrome";

const browser = await puppeteer.launch({
  executablePath: CHROME,
  headless: "new",
  args: ["--no-sandbox", "--disable-dev-shm-usage"],
});
const page = await browser.newPage();
await page.setViewport({ width: 1352, height: 900 });
await page.goto(`${BASE}/static/home.html`, { waitUntil: "networkidle2" });

await page.evaluate(() => window.PM_CmdPalette.open());
await new Promise((r) => setTimeout(r, 600));
await page.type(".pm-cmd-input", "决策");
await new Promise((r) => setTimeout(r, 400));

const list = await page.evaluate(() => {
  const items = [...document.querySelectorAll(".pm-cmd-list li, .pm-cmd-item, [role=option]")].map(
    (el) => ({
      text: (el.innerText || "").replace(/\s+/g, " ").trim(),
      active: el.className.includes("active") || el.getAttribute("aria-selected") === "true",
    })
  );
  return { items, count: items.length };
});
console.log("=== 输入「决策」后列出的条目 ===");
list.items.forEach((it, i) => console.log(`  ${i}. ${it.active ? "▶选中" : "      "} ${it.text}`));

// 面板里选中的项是第几条？回车落到哪？
const before = page.url();
await page.keyboard.press("Enter");
await new Promise((r) => setTimeout(r, 1200));
console.log(`\n  回车前 URL = ${before}`);
console.log(`  回车后 URL = ${page.url()}`);

await browser.close();
