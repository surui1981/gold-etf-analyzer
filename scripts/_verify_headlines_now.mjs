// V0.106 verification: headlines + date selection
import puppeteer from "puppeteer-core";

const browser = await puppeteer.launch({
  executablePath: "/home/surui/.cache/puppeteer/chrome/linux-153.0.8010.36/chrome-linux64/chrome",
  headless: "new",
  args: ["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"],
});
const page = await browser.newPage();
await page.setViewport({ width: 1400, height: 900 });
await page.setCacheEnabled(false);
// block favorites (avoid 100-card rate limit on init)
await page.setRequestInterception(true);
page.on("request", (req) => {
  if (req.url().includes("/favorites/exists/")) {
    req.respond({ status: 200, contentType: "application/json", body: "{}" });
  } else req.continue();
});
page.on("response", async (r) => {
  if (r.url().includes("/api/v1/news-feed/items")) {
    try {
      const b = await r.json();
      console.log("API", r.status(), r.url().slice(-80), "→", JSON.stringify({total: b.total, items_len: (b.items || []).length, first: (b.items||[])[0]?.title?.slice(0, 40)}));
    } catch (e) {}
  }
});

// 1. 打开 /headlines
await page.goto("http://127.0.0.1:8890/headlines", { waitUntil: "networkidle0", timeout: 15000 });
await new Promise(r => setTimeout(r, 2500));
const s1 = await page.evaluate(() => ({
  listCount: document.querySelectorAll(".news-card").length,
  listEmpty: document.getElementById("listEmpty")?.hidden,
  activeRange: document.querySelector(".range-btns button.active")?.textContent.trim(),
  dateValue: document.getElementById("datePicker")?.value,
}));
console.log("[1] /headlines 初始:", JSON.stringify(s1));

// 2. 选昨天 2026-10-18
await page.evaluate(() => {
  const dp = document.getElementById("datePicker");
  const desc = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value");
  desc.set.call(dp, "2026-10-18");
  dp.dispatchEvent(new Event("change", { bubbles: true }));
});
await new Promise(r => setTimeout(r, 3000));
const s2 = await page.evaluate(() => ({
  listCount: document.querySelectorAll(".news-card").length,
  listEmpty: document.getElementById("listEmpty")?.hidden,
  dateValue: document.getElementById("datePicker")?.value,
}));
console.log("[2] 选 2026-10-18:", JSON.stringify(s2));

// 3. 选今天 2026-10-19
await page.evaluate(() => {
  const dp = document.getElementById("datePicker");
  const desc = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value");
  desc.set.call(dp, "2026-10-19");
  dp.dispatchEvent(new Event("change", { bubbles: true }));
});
await new Promise(r => setTimeout(r, 3000));
const s3 = await page.evaluate(() => ({
  listCount: document.querySelectorAll(".news-card").length,
  listEmpty: document.getElementById("listEmpty")?.hidden,
  dateValue: document.getElementById("datePicker")?.value,
}));
console.log("[3] 选 2026-10-19:", JSON.stringify(s3));

await page.screenshot({ path: "/tmp/headlines_today.png" });
await browser.close();
