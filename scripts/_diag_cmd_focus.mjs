// Diagnose: how long does the command palette take to focus its search box?
// Why: _verify_mobile.mjs 的「打开时搜索框自动聚焦」偶发红 —— 固定 350ms 等待是否够？
import puppeteer from "puppeteer-core";

const BASE = process.env.BASE_URL || "http://192.168.0.204:8888";
const browser = await puppeteer.launch({
  executablePath: "/home/surui/.cache/puppeteer/chrome/linux-153.0.8010.36/chrome-linux64/chrome",
  headless: "new",
  args: ["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"],
});
const page = await browser.newPage();
await page.setViewport({ width: 1352, height: 900 });
const errs = [];
page.on("pageerror", (e) => errs.push("pageerror: " + e.message));
page.on("console", (m) => {
  if (m.type() === "error") errs.push("console: " + m.text());
});

await page.goto(BASE + "/static/home.html", { waitUntil: "networkidle2", timeout: 30000 });
await page.waitForSelector(".nav-btn-cmd");

const res = await page.evaluate(async () => {
  const out = [];
  for (let i = 0; i < 12; i++) {
    const input = document.querySelector(".pm-cmd-input");
    const t0 = performance.now();
    window.PM_CmdPalette.open();
    let focusedAt = null;
    for (let t = 0; t < 300; t += 5) {
      if (document.activeElement === input) {
        focusedAt = Math.round(performance.now() - t0);
        break;
      }
      await new Promise((r) => setTimeout(r, 5));
    }
    out.push({
      i,
      focusedAt,
      active: document.activeElement
        ? document.activeElement.className || document.activeElement.tagName
        : null,
    });
    window.PM_CmdPalette.close();
    await new Promise((r) => setTimeout(r, 250));
  }
  return out;
});

console.log(JSON.stringify(res));
console.log("errors:", errs.length ? errs : "none");
await browser.close();
