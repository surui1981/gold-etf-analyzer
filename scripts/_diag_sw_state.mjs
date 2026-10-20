// Diagnose SW state and what the browser actually loads
import puppeteer from "puppeteer-core";

const browser = await puppeteer.launch({
  executablePath: "/home/surui/.cache/puppeteer/chrome/linux-153.0.8010.36/chrome-linux64/chrome",
  headless: "new",
  args: ["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"],
});
const page = await browser.newPage();
await page.setViewport({ width: 1400, height: 900 });
// NOTE: cache ENABLED this time - simulate user's actual browser
await page.setCacheEnabled(true);

await page.goto("http://192.168.0.204:8888/headlines", { waitUntil: "networkidle0", timeout: 20000 });
await new Promise((r) => setTimeout(r, 3000));

const swInfo = await page.evaluate(async () => {
  const regs = await navigator.serviceWorker.getRegistrations();
  const cacheNames = await caches.keys();
  const cacheContents = {};
  for (const name of cacheNames) {
    const cache = await caches.open(name);
    const keys = await cache.keys();
    cacheContents[name] = keys.map((k) => k.url);
  }
  return {
    registrations: regs.map((r) => ({
      scope: r.scope,
      active: r.active?.scriptURL,
      scriptUrl: r.active?.scriptURL,
      state: r.active?.state,
    })),
    cacheNames,
    cacheContents,
  };
});
console.log("=== Service Worker State ===");
console.log(JSON.stringify(swInfo, null, 2));

const headlineState = await page.evaluate(() => {
  const cards = Array.from(document.querySelectorAll(".news-card"));
  return {
    cardCount: cards.length,
    dailyTotal: document.getElementById("dailyTotal")?.textContent,
    dailyHidden: document.getElementById("dailySummary")?.hidden,
    activeRangeBtn: document.querySelector(".range-btns button.active")?.textContent?.trim(),
    refreshBtn: document.getElementById("refreshBtn")?.title,
  };
});
console.log("\n=== Page state ===");
console.log(JSON.stringify(headlineState, null, 2));

await browser.close();
