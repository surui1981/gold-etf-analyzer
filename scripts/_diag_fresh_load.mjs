// Diagnose what the browser ACTUALLY serves to the user
import puppeteer from "puppeteer-core";

const browser = await puppeteer.launch({
  executablePath: "/home/surui/.cache/puppeteer/chrome/linux-153.0.8010.36/chrome-linux64/chrome",
  headless: "new",
  args: ["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"],
});
const page = await browser.newPage();
await page.setViewport({ width: 1400, height: 900 });
await page.setCacheEnabled(true);

// Intercept responses to see what's served from network vs cache
const resources = [];
page.on("response", async (resp) => {
  if (resp.url().includes("/api/v1/news-feed/items") && !resp.url().includes("favorites")) {
    const fromCache = resp.fromCache?.() || resp.fromServiceWorker;
    let body = null;
    try { body = await resp.json(); } catch (e) {}
    resources.push({
      url: resp.url().replace("http://192.168.0.204:8888", ""),
      status: resp.status(),
      fromSW: resp.fromServiceWorker?.() || false,
      fromCache: resp.fromCache?.() || false,
      firstPub: body?.items?.[0]?.publish_date,
      total: body?.total,
    });
  }
});

console.log("=== Load #1 (warm) ===");
await page.goto("http://192.168.0.204:8888/headlines", { waitUntil: "networkidle0", timeout: 20000 });
await new Promise((r) => setTimeout(r, 3000));

const v1 = await page.evaluate(() => {
  const cards = Array.from(document.querySelectorAll(".news-card"));
  // Look for the date text in each card
  const sampleCards = cards.slice(0, 5).map(c => {
    return c.textContent.match(/\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}/)?.[0] || c.textContent.slice(0, 100);
  });
  return {
    cardCount: cards.length,
    sampleDates: sampleCards,
    dailyTotal: document.getElementById("dailyTotal")?.textContent,
  };
});
console.log("Page state:", JSON.stringify(v1, null, 2));
console.log("API calls:", JSON.stringify(resources, null, 2));

console.log("\n=== Force refresh (no cache) ===");
const client = await page.target().createCDPSession();
await client.send("Network.setCacheDisabled", { cacheDisabled: true });
resources.length = 0;
await page.reload({ waitUntil: "networkidle0" });
await new Promise((r) => setTimeout(r, 3000));

const v2 = await page.evaluate(() => {
  const cards = Array.from(document.querySelectorAll(".news-card"));
  return {
    cardCount: cards.length,
    sampleDates: cards.slice(0, 3).map(c => c.textContent.match(/\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}/)?.[0] || "?"),
    dailyTotal: document.getElementById("dailyTotal")?.textContent,
  };
});
console.log("Page state (no cache):", JSON.stringify(v2, null, 2));
console.log("API calls:", JSON.stringify(resources, null, 2));

await browser.close();
