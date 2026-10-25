// Diagnose the command palette focus race:
//   open() → setTimeout(30ms) → input.focus()
//   but .pm-cmd has `transition: opacity .14s, transform .14s, visibility .14s`
// Hypothesis: at t=30ms the panel may still be visibility:hidden → focus() is a no-op.
import puppeteer from "puppeteer-core";

const BASE = process.env.BASE_URL || "http://192.168.0.204:8888";
const browser = await puppeteer.launch({
  executablePath: "/home/surui/.cache/puppeteer/chrome/linux-153.0.8010.36/chrome-linux64/chrome",
  headless: "new",
  args: ["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"],
});
const page = await browser.newPage();
await page.setViewport({ width: 1352, height: 900 });
await page.goto(BASE + "/static/home.html", { waitUntil: "networkidle2", timeout: 30000 });
await page.waitForSelector(".nav-btn-cmd");

// 第 1 次 open：DOM 还不存在（新建 ⇒ 无过渡）→ 应当正常聚焦
const first = await page.evaluate(async () => {
  const t0 = performance.now();
  window.PM_CmdPalette.open();
  const samples = [];
  for (const t of [0, 10, 20, 30, 40, 60, 90, 120, 160, 220]) {
    while (performance.now() - t0 < t) await new Promise((r) => setTimeout(r, 2));
    const pal = document.querySelector(".pm-cmd");
    const input = document.querySelector(".pm-cmd-input");
    samples.push({
      t,
      vis: getComputedStyle(pal).visibility,
      opacity: getComputedStyle(pal).opacity,
      focused: document.activeElement === input,
      active: document.activeElement ? document.activeElement.className || document.activeElement.tagName : null,
    });
  }
  return samples;
});
console.log("=== 第 1 次 open（新建 DOM，无过渡）===");
console.table(first);

await page.evaluate(() => window.PM_CmdPalette.close());
await new Promise((r) => setTimeout(r, 400));

// 第 2 次 open：DOM 已存在（重新显示 ⇒ 走 visibility 过渡）→ 假设会丢焦点
const second = await page.evaluate(async () => {
  const t0 = performance.now();
  window.PM_CmdPalette.open();
  const samples = [];
  for (const t of [0, 10, 20, 30, 40, 60, 90, 120, 160, 220]) {
    while (performance.now() - t0 < t) await new Promise((r) => setTimeout(r, 2));
    const pal = document.querySelector(".pm-cmd");
    const input = document.querySelector(".pm-cmd-input");
    samples.push({
      t,
      vis: getComputedStyle(pal).visibility,
      opacity: getComputedStyle(pal).opacity,
      focused: document.activeElement === input,
      active: document.activeElement ? document.activeElement.className || document.activeElement.tagName : null,
    });
  }
  return samples;
});
console.log("=== 第 2 次 open（复用 DOM ⇒ visibility 过渡）===");
console.table(second);

await browser.close();
