import puppeteer from "puppeteer-core";

const browser = await puppeteer.launch({
  executablePath: "/home/surui/.cache/puppeteer/chrome/linux-153.0.8010.36/chrome-linux64/chrome",
  headless: "new",
  args: ["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"],
});
const page = await browser.newPage();
await page.setViewport({ width: 1400, height: 900 });

// 拦截 console + 网络错误
page.on("console", (msg) => console.log(`[console.${msg.type()}]`, msg.text().slice(0, 200)));
page.on("pageerror", (err) => console.log(`[pageerror]`, err.message));
page.on("requestfailed", (req) => console.log(`[requestfailed]`, req.url(), req.failure()?.errorText));
page.on("response", async (r) => {
  if (r.url().includes("/api/v1/news-feed/")) {
    console.log(`[response]`, r.status(), r.url().slice(-100));
  }
});

await page.goto("http://127.0.0.1:8890/headlines", { waitUntil: "networkidle0", timeout: 15000 });
await new Promise(r => setTimeout(r, 2000));

// 试直接 fetch 验证浏览器能否到 API
const testResult = await page.evaluate(async () => {
  try {
    const r = await fetch("/api/v1/news-feed/items?days=2&limit=5");
    return { ok: r.ok, status: r.status, sample: (await r.json())?.items?.length };
  } catch (e) {
    return { error: e.message, stack: e.stack?.slice(0, 300) };
  }
});
console.log("直接 fetch 测试:", JSON.stringify(testResult));

await browser.close();
