// 诊断 4：把 DB 里的真实 AI 回复灌进 ask.html，截图 + 量标题/分隔线/表格间距
import puppeteer from "puppeteer-core";
const CHROME = "/home/surui/.cache/puppeteer/chrome/linux-153.0.8010.36/chrome-linux64/chrome";
const BASE = "http://127.0.0.1:8888";

const MD = `## 当前模型

**claude-sonnet-4-5**（MiniMax M2.1 版本）

## 我能做什么

我是**黄金 ETF 投资分析助手**，在本应用内可调用 5 个只读数据工具：

| 工具 | 用途 | 什么时候会用 |
|---|---|---|
| **市场行情** | NY 金、上海金、ETF 518880 + 综合趋势指数 | "现在金价多少" |
| **评分汇总** | t0/t1/t3/t5 命中率 + 月度聚合 | "近期命中率怎么样" |

## 我的工作方式

1. **中文回复**，你用其他语言我也跟随
2. 涉及数据必调工具，不凭印象回答
3. **结构化输出**：一句话结论 → 数据支撑 → 建议

> 引用行

---

有具体问题吗？比如想看**现在金价**、**持仓盈盈**。`;

const browser = await puppeteer.launch({
  executablePath: CHROME, headless: "new",
  args: ["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"],
});
const page = await browser.newPage();
await page.setViewport({ width: 1352, height: 900 });
await page.goto(`${BASE}/ask`, { waitUntil: "networkidle2" });

const m = await page.evaluate((md) => {
  document.getElementById("emptyState")?.remove();
  const wrap = document.createElement("div");
  wrap.className = "message assistant";
  wrap.innerHTML = '<div class="avatar">🤖</div>';
  const b = document.createElement("div");
  b.className = "bubble";
  function sanitizeHtml(html) {
    return String(html || '')
      .replace(/<script[\s\S]*?<\/script>/gi, '')
      .replace(/<iframe[\s\S]*?<\/iframe>/gi, '')
      .replace(/\s(onc(?:lick|load|error|mouseover|focus|blur|change|submit)\s*=\s*["'][^"']*["'])/gi, '')
      .replace(/(href|src)\s*=\s*["']\s*javascript:[^"']*["']/gi, '$1="#"');
  }
  b.innerHTML = sanitizeHtml(window.marked.parse(md, { breaks: true, gfm: true, mangle: false, headerIds: false }));
  wrap.appendChild(b);
  document.getElementById("messageStream").appendChild(wrap);
  b.scrollIntoView();

  const box = (sel) => {
    const e = b.querySelector(sel);
    if (!e) return null;
    const s = getComputedStyle(e);
    const r = e.getBoundingClientRect();
    return { text: (e.textContent || "").slice(0, 18), fs: s.fontSize, mt: s.marginTop, mb: s.marginBottom,
             fw: s.fontWeight, top: Math.round(r.top), bottom: Math.round(r.bottom), h: Math.round(r.height) };
  };
  const kids = [...b.children].map((e) => ({
    tag: e.tagName, text: (e.textContent || "").replace(/\s+/g, " ").slice(0, 20),
    mt: getComputedStyle(e).marginTop, mb: getComputedStyle(e).marginBottom,
    top: Math.round(e.getBoundingClientRect().top),
  }));
  return { h2: box("h2"), pAfterH2: box("h2 + p"), hr: box("hr"), table: box("table"), kids };
}, MD);

console.log(JSON.stringify(m, null, 2));
const el = await page.$("#messageStream .message.assistant:last-child");
await el.screenshot({ path: "/tmp/ask_bubble_before.png" });
console.log("screenshot -> /tmp/ask_bubble_before.png");
await browser.close();