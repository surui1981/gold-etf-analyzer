// Verify what the user actually sees on 8888 - exact same path
import puppeteer from "puppeteer-core";

const browser = await puppeteer.launch({
  executablePath: "/home/surui/.cache/puppeteer/chrome/linux-153.0.8010.36/chrome-linux64/chrome",
  headless: "new",
  args: ["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"],
});
const page = await browser.newPage();
await page.setCacheEnabled(false);
await page.setViewport({ width: 1400, height: 900 });

// Capture all API + JS errors
const apiCalls = [];
page.on("request", (req) => {
  if (req.url().includes("/api/v1/news-feed/")) {
    apiCalls.push({ method: req.method(), url: req.url().replace("http://192.168.0.204:8888", "") });
  }
});
page.on("response", async (resp) => {
  if (resp.url().includes("/api/v1/news-feed/")) {
    const idx = apiCalls.findIndex((c) => !c.status && c.url === resp.url().replace("http://192.168.0.204:8888", ""));
    if (idx >= 0) {
      apiCalls[idx].status = resp.status();
      try { apiCalls[idx].body = await resp.json(); } catch (e) { apiCalls[idx].body = "(non-JSON)"; }
    }
  }
});
page.on("console", (msg) => {
  if (msg.type() === "error" || msg.type() === "warn") {
    console.log(`[BROWSER ${msg.type().toUpperCase()}]`, msg.text().slice(0, 200));
  }
});
page.on("pageerror", (err) => {
  console.log(`[PAGE ERROR] ${err.message.slice(0, 200)}`);
});

// Simulate user's actual flow: visit /headlines, then refresh
console.log("=== Visit 1: fresh load ===");
await page.goto("http://192.168.0.204:8888/headlines", { waitUntil: "networkidle0", timeout: 20000 });
await new Promise((r) => setTimeout(r, 3000));

const v1 = await page.evaluate(() => {
  const cards = Array.from(document.querySelectorAll(".news-card"));
  const dates = cards.map(c => c.querySelector(".news-date, time, .meta, .news-meta")?.textContent?.trim()).filter(Boolean);
  return {
    cardCount: cards.length,
    firstFewDates: dates.slice(0, 5),
    dailyHidden: document.getElementById("dailySummary")?.hidden,
    dailyTotal: document.getElementById("dailyTotal")?.textContent,
    activeRangeBtn: document.querySelector(".range-btns button.active")?.textContent?.trim(),
    currentDate: document.getElementById("datePicker")?.value || null,
    refreshBtnTitle: document.getElementById("refreshBtn")?.title,
  };
});
console.log("State:", JSON.stringify(v1, null, 2));
console.log("API calls:", JSON.stringify(apiCalls, null, 2));

console.log("\n=== Visit 2: hard refresh (Ctrl+Shift+R) ===");
await page.reload({ waitUntil: "networkidle0" });
await new Promise((r) => setTimeout(r, 3000));

const v2 = await page.evaluate(() => {
  const cards = Array.from(document.querySelectorAll(".news-card"));
  return {
    cardCount: cards.length,
    firstCardDate: cards[0]?.querySelector(".news-date, time, .meta, .news-meta")?.textContent?.trim() || "NONE",
  };
});
console.log("State:", JSON.stringify(v2, null, 2));

await page.screenshot({ path: "/tmp/diag_user_8888.png" });
await browser.close();
