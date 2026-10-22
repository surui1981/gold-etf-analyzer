// 诊断 7：分别注入 表格 / 代码块 / 长不换行文本，定位谁把对话列顶宽
import puppeteer from "puppeteer-core";
const CHROME = "/home/surui/.cache/puppeteer/chrome/linux-153.0.8010.36/chrome-linux64/chrome";
const BASE = "http://127.0.0.1:8888";

const CASES = {
  table: `| 周期 | 命中率 | 样本 | 最佳月 | 夏普 | 回撤 | 备注 |\n|---|---|---|---|---|---|---|\n| t0 | 62.3% | 128 | 2026-03 | 1.42 | -8.1% | 无 |\n| t1 | 58.7% | 128 | 2026-05 | 1.10 | -11.4% | 无 |`,
  pre: "```json\n" + JSON.stringify({ symbol: "XAU", price_usd: 4094.5, change_pct: -0.26, updated_at: "2026-10-22T07:00:00+08:00" }, null, 2) + "\n```",
  longurl: "见 https://www.example.com/a/very/long/path/that/has/no/spaces/at/all/segment1234567890 了解更多",
};

const browser = await puppeteer.launch({
  executablePath: CHROME, headless: "new",
  args: ["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"],
});
const page = await browser.newPage();
await page.setViewport({ width: 390, height: 844 });
await page.goto(`${BASE}/ask`, { waitUntil: "networkidle2" });

for (const [name, md] of Object.entries(CASES)) {
  const r = await page.evaluate(({ md }) => {
    document.getElementById("emptyState")?.remove();
    const stream = document.getElementById("messageStream");
    stream.innerHTML = "";
    const wrap = document.createElement("div");
    wrap.className = "message assistant";
    wrap.innerHTML = '<div class="avatar">🤖</div>';
    const b = document.createElement("div");
    b.className = "bubble";
    b.innerHTML = window.marked.parse(md, { gfm: true, breaks: true });
    wrap.appendChild(b);
    stream.appendChild(wrap);

    const main = document.querySelector(".ask-main");
    const t = b.querySelector("table"), pre = b.querySelector("pre");
    // 内容右缘是否超出可视区（= 被裁掉且无法滚动到）
    const clipped = [...b.querySelectorAll("table,pre,p,li,a")]
      .map((e) => ({ tag: e.tagName, right: Math.round(e.getBoundingClientRect().right) }))
      .filter((x) => x.right > 391);
    return {
      streamW: stream.clientWidth,
      mainW: main.clientWidth,
      docScrollW: document.documentElement.scrollWidth,
      docClientW: document.documentElement.clientWidth,
      clippedRight: clipped,
      tableW: t ? Math.round(t.getBoundingClientRect().width) : null,
      preW: pre ? Math.round(pre.getBoundingClientRect().width) : null,
    };
  }, { md });
  console.log(name.padEnd(8), JSON.stringify(r));
}
await browser.close();