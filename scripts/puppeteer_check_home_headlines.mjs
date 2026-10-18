// V0.102 烟测：home.html 今日要闻 section 切到 readhub 财经流
import puppeteer from "puppeteer-core";

const browser = await puppeteer.launch({
  executablePath: "/home/surui/.cache/puppeteer/chrome/linux-153.0.8010.36/chrome-linux64/chrome",
  headless: "new",
  args: ["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"],
});
const page = await browser.newPage();

const errors = [];
page.on("pageerror", (err) => errors.push("PAGEERROR: " + err.message));
page.on("console", (msg) => { if (msg.type() === "error") errors.push("CONSOLE: " + msg.text()); });

await page.setViewport({ width: 1280, height: 900 });
await page.goto("http://127.0.0.1:8888/home", { waitUntil: "networkidle2", timeout: 30000 });
// 等 readhub 端点拉完（首次 ~3s + 渲染）
await new Promise(r => setTimeout(r, 6000));

const data = await page.evaluate(() => {
  const list = document.getElementById("homeNewsList");
  const chip = document.getElementById("homeHeadlinesChip");
  const more = document.querySelector(".home-news-more");
  const items = Array.from(list?.querySelectorAll("li") || []).map((li) => ({
    time: li.querySelector(".home-news-date")?.textContent?.trim() || "",
    site: li.querySelector(".home-news-site")?.textContent?.trim() || "",
    title: (li.querySelector(".home-news-title")?.textContent || "").trim().slice(0, 50),
    href: li.querySelector(".home-news-title")?.getAttribute("href") || "",
    target: li.querySelector(".home-news-title")?.getAttribute("target") || "",
    isSkeleton: li.classList.contains("home-news-skeleton"),
    isError: li.classList.contains("home-news-error"),
  }));
  return {
    itemCount: items.length,
    realItemCount: items.filter(i => !i.isSkeleton && !i.isError).length,
    sample: items.slice(0, 3),
    chipText: chip?.textContent?.trim() || "",
    chipIsLoading: chip?.classList.contains("is-loading") || false,
    chipIsWarn: chip?.classList.contains("is-warn") || false,
    moreHref: more?.getAttribute("href") || "",
    moreText: more?.textContent?.trim() || "",
  };
});

console.log(JSON.stringify({ errors, ...data }, null, 2));
await browser.close();
