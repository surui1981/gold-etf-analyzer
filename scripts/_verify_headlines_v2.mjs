import puppeteer from "puppeteer-core";

const browser = await puppeteer.launch({
  executablePath: "/home/surui/.cache/puppeteer/chrome/linux-153.0.8010.36/chrome-linux64/chrome",
  headless: "new",
  args: ["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"],
});
const page = await browser.newPage();
await page.setViewport({ width: 1400, height: 900 });
await page.setCacheEnabled(false);
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
      console.log("API", r.status(), r.url().slice(-100), "→", JSON.stringify({total: b.total, items_len: (b.items || []).length}));
    } catch (e) {}
  }
});

await page.goto("http://127.0.0.1:8890/headlines", { waitUntil: "networkidle0", timeout: 15000 });
await new Promise(r => setTimeout(r, 3000));

const s1 = await page.evaluate(() => {
  const list = document.getElementById("newsList");
  return {
    newsListExists: !!list,
    newsListChildren: list?.children.length || 0,
    newsListInnerHTMLLen: list?.innerHTML?.length || 0,
    newsListFirst200: list?.innerHTML?.slice(0, 300) || "",
    emptyState: list?.querySelector(".empty-state")?.textContent || null,
  };
});
console.log("[1] /headlines 初始:", JSON.stringify(s1, null, 2));

// 选 2026-10-19（今天）
await page.evaluate(() => {
  const dp = document.getElementById("datePicker");
  const desc = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value");
  desc.set.call(dp, "2026-10-19");
  dp.dispatchEvent(new Event("change", { bubbles: true }));
});
await new Promise(r => setTimeout(r, 3000));
const s2 = await page.evaluate(() => {
  const list = document.getElementById("newsList");
  return {
    newsListChildren: list?.children.length || 0,
    emptyState: list?.querySelector(".empty-state")?.textContent || null,
    firstItemText: list?.querySelector(".news-item, .news-card, [data-ext]")?.textContent?.slice(0, 60) || null,
  };
});
console.log("[2] 选 2026-10-19:", JSON.stringify(s2, null, 2));

await page.screenshot({ path: "/tmp/headlines_today_v2.png" });
await browser.close();
