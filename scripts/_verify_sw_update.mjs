import puppeteer from "puppeteer-core";
const browser = await puppeteer.launch({
  executablePath: "/home/surui/.cache/puppeteer/chrome/linux-153.0.8010.36/chrome-linux64/chrome",
  headless: "new",
  args: ["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"],
});
const page = await browser.newPage();
await page.setViewport({ width: 1280, height: 900 });

// 1st visit: install new SW v0.100.1
await page.goto("http://127.0.0.1:8888/home", { waitUntil: "networkidle2", timeout: 30000 });
await new Promise(r => setTimeout(r, 4000));

// Wait for SW controller
await page.evaluate(async () => {
  if (!navigator.serviceWorker.controller) {
    await new Promise(r => navigator.serviceWorker.addEventListener("controllerchange", r, { once: true }));
  }
});

// Verify SW version
const swInfo = await page.evaluate(async () => {
  const reg = await navigator.serviceWorker.getRegistration();
  return {
    hasController: !!navigator.serviceWorker.controller,
    scope: reg?.scope,
    scriptURL: reg?.active?.scriptURL,
  };
});
console.log("SW state after 1st load:", JSON.stringify(swInfo, null, 2));

// 2nd visit: SW v0.100.1 should intercept, but home.html is network-first → gets fresh
await page.reload({ waitUntil: "networkidle2" });
await new Promise(r => setTimeout(r, 4000));

// Force navigate again to make sure cache-first home.js is the new version
await page.goto("http://127.0.0.1:8888/home", { waitUntil: "networkidle2" });
await new Promise(r => setTimeout(r, 4000));

const result = await page.evaluate(() => {
  const list = document.getElementById("homeNewsList");
  const chip = document.getElementById("homeHeadlinesChip");
  const items = Array.from(list?.querySelectorAll("li") || []).map(li => ({
    time: li.querySelector(".home-news-date")?.textContent?.trim() || "",
    site: li.querySelector(".home-news-site")?.textContent?.trim() || "",
    title: (li.querySelector(".home-news-title")?.textContent || "").trim().slice(0, 40),
    hasScore: !!li.querySelector(".home-news-score, [class*='score']"),
  }));
  return {
    itemCount: items.length,
    sample: items.slice(0, 3),
    chipText: chip?.textContent?.trim() || "",
    hasAnyScoreField: items.some(i => i.hasScore),
  };
});
console.log("=== 渲染结果 ===");
console.log(JSON.stringify(result, null, 2));
await page.screenshot({ path: "/tmp/home_after_sw_update.png", fullPage: false });
await browser.close();
