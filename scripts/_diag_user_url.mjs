// Test both user paths and compare
import puppeteer from "puppeteer-core";

const PATHS = [
  { name: "LAN nginx 8889", url: "http://192.168.0.204:8889/gold/headlines" },
  { name: "LAN direct 8888", url: "http://192.168.0.204:8888/headlines" },
  { name: "Localhost nginx 8889", url: "http://127.0.0.1:8889/gold/headlines" },
  { name: "Localhost direct 8888", url: "http://127.0.0.1:8888/headlines" },
];

const browser = await puppeteer.launch({
  executablePath: "/home/surui/.cache/puppeteer/chrome/linux-153.0.8010.36/chrome-linux64/chrome",
  headless: "new",
  args: ["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"],
});

for (const p of PATHS) {
  const page = await browser.newPage();
  await page.setCacheEnabled(false);
  const apiCalls = [];
  page.on("response", async (resp) => {
    if (resp.url().includes("/api/v1/news-feed/items") && !resp.url().includes("favorites")) {
      try {
        const body = await resp.json();
        apiCalls.push({ status: resp.status(), total: body.total, firstPub: body.items?.[0]?.publish_date });
      } catch (e) { apiCalls.push({ status: resp.status(), err: "(non-JSON)" }); }
    }
  });
  try {
    await page.goto(p.url, { waitUntil: "networkidle0", timeout: 10000 });
    await new Promise((r) => setTimeout(r, 2500));
    const listCount = await page.evaluate(() => document.querySelectorAll(".news-card").length);
    const firstDate = await page.evaluate(() => {
      const c = document.querySelector(".news-card time, .news-card .news-date, .news-card .meta");
      return c ? c.textContent.trim().slice(0, 30) : null;
    });
    const daily = await page.evaluate(() => ({
      hidden: document.getElementById("dailySummary")?.hidden,
      total: document.getElementById("dailyTotal")?.textContent,
    }));
    console.log(`\n[${p.name}] ${p.url}`);
    console.log(`  list cards: ${listCount}, first date: ${firstDate || "NONE"}`);
    console.log(`  daily: hidden=${daily.hidden}, total=${daily.total}`);
    console.log(`  /items calls: ${JSON.stringify(apiCalls)}`);
  } catch (e) {
    console.log(`[${p.name}] ERROR: ${e.message}`);
  }
  await page.close();
}
await browser.close();
