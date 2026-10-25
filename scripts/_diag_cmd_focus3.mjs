// 复刻 _verify_mobile.mjs 的【慢过渡】断言块，逐毫秒记录 visibility / focus 变化。
// 目的：查清「门禁回退实现后仍报绿」到底是因为
//   (a) 浏览器拿到的是旧文件、还是
//   (b) visibility 翻转的时刻与 transition-duration 无关（我的判据设计错了）。
// 用法：node scripts/_diag_cmd_focus4.mjs   （读当前 static/command-palette.js）
import puppeteer from "puppeteer-core";

const BASE = process.env.BASE_URL || "http://127.0.0.1:8888";
const CHROME =
  "/home/surui/.cache/puppeteer/chrome/linux-153.0.8010.36/chrome-linux64/chrome";
const SLOW_MS = Number(process.env.SLOW_MS || 1500);

const browser = await puppeteer.launch({
  executablePath: CHROME,
  headless: "new",
  args: ["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"],
});
const page = await browser.newPage();
await page.setViewport({ width: 390, height: 844 });

async function goto(url, wait = 900) {
  try {
    await page.goto(url, { waitUntil: "networkidle2", timeout: 20000 });
  } catch (e) {
    await page.goto(url, { waitUntil: "domcontentloaded", timeout: 20000 });
  }
  await new Promise((r) => setTimeout(r, wait));
}

await goto(`${BASE}/static/home.html`);
await page.waitForSelector(".nav-btn-cmd");

// ① 浏览器到底拿到的是哪个版本的文件？
const served = await page.evaluate(async () => {
  const t = await (await fetch("/static/command-palette.js?probe=1")).text();
  return {
    hasFocusWhenVisible: t.includes("focusWhenVisible"),
    hasSetTimeout30: /setTimeout\(function \(\) \{[\s\S]{0,200}?\}, 30\)/.test(t),
    len: t.length,
  };
});
console.log("浏览器拿到的文件：", served);

// ⚠ transition-duration 改不了「visibility 什么时候翻成 visible」——
// visibility 是离散插值：过渡开始后**第一帧**（progress>0）就翻，
// 加长 duration 只影响 opacity 淡入，不影响可见时刻（实测 t=29ms 就翻）。
// 要把「可见时刻」推后，必须用 **transition-delay**：延迟期间属性保持起始值（hidden）。
const CSS = process.env.CSS_OVERRIDE ||
  `.pm-cmd { transition: opacity .14s ease, transform .14s ease, visibility 0s ease ${SLOW_MS}ms !important; }`;
await page.addStyleTag({ content: CSS });

const res = await page.evaluate(async () => {
  const pal = document.querySelector(".pm-cmd");
  const input = document.querySelector(".pm-cmd-input");
  const t0 = performance.now();
  const samples = [];
  let prevVis = null;
  let focusedAt = null;
  let prevFocus = null;
  window.PM_CmdPalette.open();
  for (let i = 0; i < 220; i++) {
    await new Promise((r) => setTimeout(r, 5));
    const t = Math.round(performance.now() - t0);
    const vis = getComputedStyle(pal).visibility;
    const focused = document.activeElement === input;
    if (vis !== prevVis || focused !== prevFocus) {
      samples.push({
        t,
        vis,
        op: getComputedStyle(pal).opacity.slice(0, 5),
        focused,
        active: document.activeElement
          ? document.activeElement.className || document.activeElement.tagName
          : null,
      });
      prevVis = vis;
      prevFocus = focused;
    }
    if (focused && focusedAt === null) focusedAt = t;
    if (t > 900) break;
  }
  return { focusedAt, samples, dur: getComputedStyle(pal).transitionDuration };
});

console.log("transition-duration =", res.dur);
console.log("focusedAt(ms) =", res.focusedAt);
console.table(res.samples);
await browser.close();
