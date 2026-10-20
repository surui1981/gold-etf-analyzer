// Diagnose user's reported issue: browser shows 10-18 instead of 10-19 news
import puppeteer from "puppeteer-core";

const browser = await puppeteer.launch({
  executablePath: "/home/surui/.cache/puppeteer/chrome/linux-153.0.8010.36/chrome-linux64/chrome",
  headless: "new",
  args: ["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"],
});
const page = await browser.newPage();
await page.setViewport({ width: 1400, height: 900 });

// Capture all API calls and responses
const apiCalls = [];
page.on("request", (req) => {
  if (req.url().includes("/api/v1/news-feed/")) {
    apiCalls.push({ method: req.method(), url: req.url().slice(-120), at: Date.now() });
  }
});
page.on("response", async (resp) => {
  if (resp.url().includes("/api/v1/news-feed/")) {
    const idx = apiCalls.findIndex((c) => !c.status && c.url === resp.url().slice(-120));
    if (idx >= 0) {
      apiCalls[idx].status = resp.status();
      try { apiCalls[idx].body = await resp.json(); } catch (e) { apiCalls[idx].body = "(non-JSON)"; }
    }
  }
});

await page.setCacheEnabled(false);
await page.goto("http://192.168.0.204:8889/gold/headlines", { waitUntil: "networkidle0", timeout: 20000 });
await new Promise((r) => setTimeout(r, 3000));

const state = await page.evaluate(() => {
  const cards = Array.from(document.querySelectorAll(".news-card"));
  return {
    swVersion: navigator.serviceWorker?.controller?.scriptURL || "no SW controller",
    currentDate: document.getElementById("datePicker")?.value || null,
    activeRangeBtn: document.querySelector(".range-btns button.active")?.textContent?.trim() || null,
    dailySummaryHidden: document.getElementById("dailySummary")?.hidden,
    dailyTotal: document.getElementById("dailyTotal")?.textContent || null,
    dailyFinance: document.getElementById("dailyFinance")?.textContent || null,
    listCount: cards.length,
    firstCardDate: cards[0]?.querySelector(".news-date, time, .meta")?.textContent?.trim() || null,
    firstCardTitle: cards[0]?.querySelector(".news-title, h3, h4")?.textContent?.trim()?.slice(0, 60) || null,
  };
});

console.log("=== state ===");
console.log(JSON.stringify(state, null, 2));
console.log("\n=== api calls ===");
for (const c of apiCalls) {
  console.log(`${c.status || "PEND"} ${c.url} ${c.body ? "→" : ""} ${c.body && typeof c.body === "object" ? JSON.stringify(c.body).slice(0, 100) : ""}`);
}

await page.screenshot({ path: "/tmp/diag_headlines.png" });
await browser.close();
