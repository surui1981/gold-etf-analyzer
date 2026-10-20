import puppeteer from "puppeteer-core";
const browser = await puppeteer.launch({
  executablePath: "/home/surui/.cache/puppeteer/chrome/linux-153.0.8010.36/chrome-linux64/chrome",
  headless: "new",
  args: ["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"],
});
const page = await browser.newPage();
await page.setViewport({ width: 1280, height: 2000 });

const errors = [];
page.on("pageerror", err => errors.push("PAGEERROR: " + err.message));
page.on("console", msg => { if (msg.type() === "error") errors.push("CONSOLE: " + msg.text()); });

// 模拟「新用户首次访问」：unregister 旧 SW + 清 cache
await page.goto("http://127.0.0.1:8888/home", { waitUntil: "networkidle2", timeout: 30000 });
await page.evaluate(async () => {
  const regs = await navigator.serviceWorker.getRegistrations();
  for (const r of regs) await r.unregister();
  const keys = await caches.keys();
  await Promise.all(keys.map(k => caches.delete(k)));
});
await new Promise(r => setTimeout(r, 1000));

// 第 2 次访问：新 SW v0.100.2 install + precache
await page.reload({ waitUntil: "networkidle2", timeout: 30000 });
await new Promise(r => setTimeout(r, 4000));

// 第 3 次访问：SW 已激活，cache 命中
await page.reload({ waitUntil: "networkidle2" });
await new Promise(r => setTimeout(r, 4000));

const result = await page.evaluate(() => {
  const list = document.getElementById("homeNewsList");
  const chip = document.getElementById("homeHeadlinesChip");
  const items = Array.from(list?.querySelectorAll("li") || []).map(li => ({
    time: li.querySelector(".home-news-date")?.textContent?.trim() || "",
    site: li.querySelector(".home-news-site")?.textContent?.trim() || "",
    title: (li.querySelector(".home-news-title")?.textContent || "").trim().slice(0, 50),
    isSkeleton: li.classList.contains("home-news-skeleton"),
    isError: li.classList.contains("home-news-error"),
  }));
  return {
    itemCount: items.length,
    realItemCount: items.filter(i => !i.isSkeleton && !i.isError).length,
    first2: items.slice(0, 2),
    last2: items.slice(-2),
    chipText: chip?.textContent?.trim() || "",
  };
});
console.log("errors:", errors);
console.log("result:", JSON.stringify(result, null, 2));

const section = await page.$(".home-bottom");
const box = await section.boundingBox();
await page.screenshot({ path: "/tmp/home_top20.png", clip: box });
await browser.close();
