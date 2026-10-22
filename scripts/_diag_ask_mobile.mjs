// 诊断 5：390px 下宽表格 / 长代码块会不会顶破对话列
import puppeteer from "puppeteer-core";
const CHROME = "/home/surui/.cache/puppeteer/chrome/linux-153.0.8010.36/chrome-linux64/chrome";
const BASE = "http://127.0.0.1:8888";

const MD = `| 周期 | 命中率 | 样本 | 最佳月 | 夏普 | 回撤 |\n|---|---|---|---|---|---|\n| t0 | 62.3% | 128 | 2026-03 | 1.42 | -8.1% |\n| t1 | 58.7% | 128 | 2026-05 | 1.10 | -11.4% |\n\n\`\`\`json\n{"symbol":"XAU","price_usd":4094.5,"change_pct":-0.26,"updated_at":"2026-10-22T07:00:00Z"}\n\`\`\``;

const browser = await puppeteer.launch({
  executablePath: CHROME, headless: "new",
  args: ["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"],
});

for (const [w, h] of [[390, 844], [768, 900], [1352, 900]]) {
  const page = await browser.newPage();
  await page.setViewport({ width: w, height: h });
  await page.goto(`${BASE}/ask`, { waitUntil: "networkidle2" });
  const r = await page.evaluate((md) => {
    document.getElementById("emptyState")?.remove();
    const wrap = document.createElement("div");
    wrap.className = "message assistant";
    wrap.innerHTML = '<div class="avatar">🤖</div>';
    const b = document.createElement("div");
    b.className = "bubble";
    b.innerHTML = window.marked.parse(md, { gfm: true, breaks: true });
    wrap.appendChild(b);
    document.getElementById("messageStream").appendChild(wrap);

    const table = b.querySelector("table");
    const pre = b.querySelector("pre");
    const stream = document.getElementById("messageStream");
    const host = document.querySelector(".ask-main") || stream;
    return {
      viewport: innerWidth,
      streamClientW: stream.clientWidth,
      streamScrollW: stream.scrollWidth,
      streamOverflowsX: stream.scrollWidth > stream.clientWidth + 1,
      hostClientW: host.clientWidth,
      hostScrollW: host.scrollWidth,
      hostOverflowsX: host.scrollWidth > host.clientWidth + 1,
      tableScrollW: table?.scrollWidth,
      tableOverflowsHost: table ? table.scrollWidth > host.clientWidth + 1 : null,
      tableOwnScroll: table ? getComputedStyle(table.parentElement).overflowX : null,
      preScrollW: pre?.scrollWidth,
      preClientW: pre?.clientWidth,
      preOwnScroll: pre ? getComputedStyle(pre).overflowX : null,
      docOverflowsX: document.documentElement.scrollWidth > document.documentElement.clientWidth + 1,
      docScrollW: document.documentElement.scrollWidth,
      docClientW: document.documentElement.clientWidth,
    };
  }, MD);
  console.log(JSON.stringify(r));
  await page.close();
}
await browser.close();