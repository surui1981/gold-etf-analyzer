// 诊断 2：真实 .message.assistant 容器内量 markdown 渲染效果
import puppeteer from "puppeteer-core";
const CHROME = "/home/surui/.cache/puppeteer/chrome/linux-153.0.8010.36/chrome-linux64/chrome";
const BASE = "http://127.0.0.1:8888";

const MD = `## 当前模型

**claude-sonnet-4-5**（MiniMax M2.1 版本）

## 我能做什么

| 工具 | 用途 | 什么时候会用 |
|---|---|---|
| **市场行情** | NY 金（COMEX 美元/盎司）、上海金（元/克）、沪金 ETF 518880（元/份）、白银收盘价 + 综合趋势指数 | "现在金价多少"、"市场整体怎么走" |
| **评分汇总** | t0/t1/t3/t5 四个预测周期的命中率 + 月度聚合 | "近期命中率怎么样" |

- 列表项一
- 列表项二

> 引用行

\`\`\`
const x = 1;
\`\`\`

---

结尾正文。`;

const browser = await puppeteer.launch({
  executablePath: CHROME, headless: "new",
  args: ["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"],
});

async function run(width, height) {
  const page = await browser.newPage();
  await page.setViewport({ width, height });
  const errs = [];
  page.on("pageerror", (e) => errs.push("pageerror: " + e));
  await page.goto(`${BASE}/ask`, { waitUntil: "networkidle2" });

  const out = await page.evaluate((md) => {
    const wrap = document.createElement("div");
    wrap.className = "message assistant";
    wrap.innerHTML = '<div class="avatar">🤖</div>';
    const bubble = document.createElement("div");
    bubble.className = "bubble";
    bubble.innerHTML = window.marked
      ? window.marked.parse(md, { breaks: true, gfm: true, mangle: false, headerIds: false })
      : "NO_MARKED";
    wrap.appendChild(bubble);
    document.getElementById("messageStream").appendChild(wrap);

    const cs = (el) => {
      if (!el) return null;
      const s = getComputedStyle(el);
      return { fs: s.fontSize, lh: s.lineHeight, mt: s.marginTop, mb: s.marginBottom, ovx: s.overflowX };
    };
    const table = bubble.querySelector("table");
    const scrollAncestor = (el) => {
      let n = el?.parentElement;
      while (n && n !== document.body) {
        const s = getComputedStyle(n);
        if (s.overflowX === "auto" || s.overflowX === "scroll") return n.className || n.tagName;
        n = n.parentElement;
      }
      return null;
    };
    return {
      markedParse: typeof window.marked?.parse,
      bubbleFontSize: cs(bubble)?.fs,
      h2: { ...cs(bubble.querySelector("h2")), text: bubble.querySelector("h2")?.textContent },
      h3: cs(bubble.querySelector("h3")),
      hr: cs(bubble.querySelector("hr")),
      pre: cs(bubble.querySelector("pre")),
      table: { ...cs(table), scrollW: table?.scrollWidth, clientW: table?.clientWidth,
               rectW: Math.round(table?.getBoundingClientRect().width || 0),
               scrollAncestor: scrollAncestor(table) },
      bubbleOverflow: bubble.scrollWidth > bubble.clientWidth + 1
        ? { scrollW: bubble.scrollWidth, clientW: bubble.clientWidth } : null,
      copyBtnOnPre: !!bubble.querySelector("pre button, .copy-btn"),
      linkTarget: bubble.querySelector("a")?.getAttribute("target") ?? null,
    };
  }, MD);

  await page.close();
  return { viewport: `${width}x${height}`, errs, ...out };
}

for (const [w, h] of [[1352, 900], [390, 844]]) {
  const r = await run(w, h);
  console.log("=" .repeat(60));
  console.log(JSON.stringify(r, null, 2));
}
await browser.close();