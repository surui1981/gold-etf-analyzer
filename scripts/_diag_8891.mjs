// Verify V0.107 features work end-to-end on new uvicorn 8891
import puppeteer from "puppeteer-core";

const browser = await puppeteer.launch({
  executablePath: "/home/surui/.cache/puppeteer/chrome/linux-153.0.8010.36/chrome-linux64/chrome",
  headless: "new",
  args: ["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"],
});
const page = await browser.newPage();
await page.setCacheEnabled(false);
await page.setViewport({ width: 1400, height: 900 });

await page.goto("http://192.168.0.204:8891/headlines", { waitUntil: "networkidle0", timeout: 20000 });
await new Promise((r) => setTimeout(r, 3000));

const state = await page.evaluate(() => {
  const cards = Array.from(document.querySelectorAll(".news-card"));
  return {
    cardCount: cards.length,
    firstDates: cards.slice(0, 3).map(c => c.textContent.match(/\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}/)?.[0] || "?"),
    dailyHidden: document.getElementById("dailySummary")?.hidden,
    dailyTotal: document.getElementById("dailyTotal")?.textContent,
    dailyFinance: document.getElementById("dailyFinance")?.textContent,
    dailyTech: document.getElementById("dailyTech")?.textContent,
    dailyBiz: document.getElementById("dailyBiz")?.textContent,
    dailyOther: document.getElementById("dailyOther")?.textContent,
    refreshBtn: document.getElementById("refreshBtn")?.title,
  };
});
console.log(JSON.stringify(state, null, 2));
await page.screenshot({ path: "/tmp/v0107_8891_verify.png" });
await browser.close();
