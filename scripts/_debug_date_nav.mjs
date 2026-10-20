// Minimal V0.104 verification: only verify change event → loadAll → date mode
import puppeteer from "puppeteer-core";

const browser = await puppeteer.launch({
  executablePath: "/home/surui/.cache/puppeteer/chrome/linux-153.0.8010.36/chrome-linux64/chrome",
  headless: "new",
  args: ["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"],
});
const page = await browser.newPage();
await page.setViewport({ width: 1400, height: 800 });
await page.setCacheEnabled(false);

// Block favorites calls (which flood rate limit on init)
await page.setRequestInterception(true);
page.on("request", (req) => {
  if (req.url().includes("/favorites/exists/")) {
    req.respond({ status: 200, contentType: "application/json", body: "{}" });
  } else {
    req.continue();
  }
});

const calls = [];
page.on("request", (req) => {
  if (req.url().includes("/api/v1/news-feed/items") && !req.url().includes("/favorites")) {
    calls.push(req.url());
  }
});
page.on("response", async (resp) => {
  if (resp.url().includes("/api/v1/news-feed/items") && !resp.url().includes("/favorites")) {
    let body = null;
    try { body = await resp.json(); } catch (e) { body = "PARSE_ERR"; }
    console.log("RESP", resp.status(), resp.url().slice(-80), "→", JSON.stringify({total: body.total, current_date: body.current_date, has_older: body.has_older, has_newer: body.has_newer, items_len: body.items?.length}));
  }
});

await page.goto("http://127.0.0.1:8888/headlines", { waitUntil: "networkidle0", timeout: 15000 });
await new Promise(r => setTimeout(r, 2500));
console.log("初始 calls:", calls.length);

console.log("\n=== 选 2026-10-18（昨天）===");
await page.evaluate(() => {
  const dp = document.getElementById("datePicker");
  dp.focus();
  const desc = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value");
  desc.set.call(dp, "2026-10-18");
  dp.dispatchEvent(new Event("input", { bubbles: true }));
  dp.dispatchEvent(new Event("change", { bubbles: true }));
});
await new Promise(r => setTimeout(r, 3000));
const s1 = await page.evaluate(() => ({
  dateValue: document.getElementById("datePicker").value,
  prevDisabled: document.getElementById("btnPrevDay").disabled,
  nextDisabled: document.getElementById("btnNextDay").disabled,
  todayHidden: document.getElementById("btnToday").hidden,
  listCount: document.querySelectorAll(".news-card").length,
  activeRange: document.querySelector(".range-btns button.active")?.textContent.trim() || null,
}));
console.log("state:", JSON.stringify(s1));

console.log("\n=== 选 2026-10-19（今天，应 has_newer=False）===");
await page.evaluate(() => {
  const dp = document.getElementById("datePicker");
  const desc = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value");
  desc.set.call(dp, "2026-10-19");
  dp.dispatchEvent(new Event("change", { bubbles: true }));
});
await new Promise(r => setTimeout(r, 3000));
const s2 = await page.evaluate(() => ({
  dateValue: document.getElementById("datePicker").value,
  prevDisabled: document.getElementById("btnPrevDay").disabled,
  nextDisabled: document.getElementById("btnNextDay").disabled,
  todayHidden: document.getElementById("btnToday").hidden,
  listCount: document.querySelectorAll(".news-card").length,
}));
console.log("state:", JSON.stringify(s2));

console.log("\n=== 点 7 天按钮（应退出单日模式）===");
await page.evaluate(() => {
  const btn = document.querySelector('.range-btns button[data-days="7"]');
  btn.click();
});
await new Promise(r => setTimeout(r, 3000));
const s3 = await page.evaluate(() => ({
  dateNavHidden: document.getElementById("dateNav").hidden,
  activeRange: document.querySelector(".range-btns button.active")?.textContent.trim(),
  listCount: document.querySelectorAll(".news-card").length,
}));
console.log("state:", JSON.stringify(s3));

await page.screenshot({ path: "/tmp/date_nav_final.png" });
console.log("\ntotal calls:", calls.length);
await browser.close();
