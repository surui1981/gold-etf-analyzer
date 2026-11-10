// 临时测量：一次 /home 加载打多少个 API 请求（诊断限流假红用）
import puppeteer from "puppeteer-core";

const BASE = process.env.BASE_URL || "http://192.168.0.204:8888";
const CHROME =
  "/home/surui/.cache/puppeteer/chrome/linux-153.0.8010.36/chrome-linux64/chrome";

const browser = await puppeteer.launch({
  executablePath: CHROME,
  headless: "new",
  args: ["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"],
});
const page = await browser.newPage();
await page.setCacheEnabled(false);
await page.setExtraHTTPHeaders({ "X-Forwarded-For": "203.0.113.99" });

let api = 0;
const byPrefix = {};
page.on("request", (r) => {
  const u = r.url();
  if (u.includes("/api/")) {
    api++;
    const p = u.replace(BASE, "").split("?")[0].replace(/\/\d+/g, "/:id");
    byPrefix[p] = (byPrefix[p] || 0) + 1;
  }
});

for (let i = 1; i <= 5; i++) {
  const before = api;
  await page.goto(`${BASE}/home`, { waitUntil: "networkidle2" });
  await new Promise((r) => setTimeout(r, 1500));
  console.log(`load ${i}: +${api - before} 个 API 请求（累计 ${api}）`);
}
console.log("\n按路径：");
for (const [k, v] of Object.entries(byPrefix).sort((a, b) => b[1] - a[1])) {
  console.log(`  ${String(v).padStart(4)} × ${k}`);
}
await browser.close();
