// scripts/_diag_decision_nav.mjs
// 诊断：全站所有文案含「决策」的链接/按钮，实测点下去落在哪个页面。
//
// 目的：用户反馈「点击决策看到的页面是趋势追踪」——
// 先找出「决策」这个文案到底出现在哪些入口、每个入口的 href 是什么，
// 再实测点击后的最终 URL，不要靠读代码猜。
import puppeteer from "puppeteer-core";

const BASE = process.env.BASE_URL || "http://127.0.0.1:8888";
const CHROME =
  "/home/surui/.cache/puppeteer/chrome/linux-153.0.8010.36/chrome-linux64/chrome";

const PAGES = [
  "home", "trend", "scoring", "portfolio", "news", "headlines",
  "weights", "settings", "backtest", "review", "favorites", "trades",
  "silver", "central-bank", "report-archive", "data-health", "ask",
];

const browser = await puppeteer.launch({
  executablePath: CHROME,
  headless: "new",
  args: ["--no-sandbox", "--disable-dev-shm-usage"],
});

const page = await browser.newPage();
await page.setViewport({ width: 1352, height: 900 });

for (const p of PAGES) {
  await page.goto(`${BASE}/static/${p}.html`, { waitUntil: "networkidle2" });
  const found = await page.evaluate(() => {
    const out = [];
    document.querySelectorAll("a, button").forEach((el) => {
      const t = (el.innerText || el.textContent || "").replace(/\s+/g, " ").trim();
      if (!t || !t.includes("决策")) return;
      // 只取最内层元素，避免外层容器重复计数
      if (el.querySelector("a, button")) return;
      const r = el.getBoundingClientRect();
      out.push({
        tag: el.tagName.toLowerCase(),
        cls: el.className || "",
        text: t.slice(0, 40),
        href: el.getAttribute("href") || "",
        scene: el.getAttribute("data-scene") || "",
        subtab: el.getAttribute("data-subtab") || "",
        visible: r.width > 0 && r.height > 0,
      });
    });
    return out;
  });
  if (found.length) {
    console.log(`\n──── /static/${p}.html`);
    for (const f of found) {
      console.log(
        `  <${f.tag} class="${f.cls}"${f.scene ? ` data-scene="${f.scene}"` : ""}` +
          `${f.subtab ? ` data-subtab="${f.subtab}"` : ""}> "${f.text}"` +
          `  href="${f.href}"  visible=${f.visible}`
      );
    }
  }
}

// 实测点击：首页顶栏「决策」
await page.goto(`${BASE}/static/home.html`, { waitUntil: "networkidle2" });
const topLink = await page.evaluate(() => {
  const a = document.querySelector('.topnav a[data-scene="decision"]');
  return a ? { href: a.getAttribute("href"), text: a.innerText.replace(/\s+/g, " ").trim() } : null;
});
console.log(`\n=== 顶栏「决策」链接 ===\n  ${JSON.stringify(topLink)}`);
if (topLink) {
  await Promise.all([
    page.waitForNavigation({ waitUntil: "networkidle2" }),
    page.click('.topnav a[data-scene="decision"]'),
  ]);
  console.log(`  点击后 URL = ${page.url()}`);
  const title = await page.evaluate(() => ({
    h1: (document.querySelector("h1") || {}).innerText || "",
    scene: (document.querySelector(".subnav-label") || {}).innerText || "",
    subnavActive: (document.querySelector(".subnav-tabs a.active") || {}).innerText || "",
  }));
  console.log(`  落页 h1="${title.h1.replace(/\s+/g, " ").trim()}"  subnav="${title.scene}"  高亮 tab="${title.subnavActive.replace(/\s+/g, " ").trim()}"`);
}

// 实测点击：首页场景卡「决策」
await page.goto(`${BASE}/static/home.html`, { waitUntil: "networkidle2" });
const card = await page.evaluate(() => {
  const a = document.querySelector(".home-scene.scene-decision");
  return a ? { href: a.getAttribute("href"), text: a.innerText.replace(/\s+/g, " ").trim().slice(0, 60) } : null;
});
console.log(`\n=== 首页场景卡「决策」 ===\n  ${JSON.stringify(card)}`);
if (card) {
  await Promise.all([
    page.waitForNavigation({ waitUntil: "networkidle2" }),
    page.click(".home-scene.scene-decision"),
  ]);
  console.log(`  点击后 URL = ${page.url()}`);
}

await browser.close();
