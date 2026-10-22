// 诊断 3：证明 sanitizeHtml 的正则绕过 + 表格无独立滚动容器
import puppeteer from "puppeteer-core";
const CHROME = "/home/surui/.cache/puppeteer/chrome/linux-153.0.8010.36/chrome-linux64/chrome";
const BASE = "http://127.0.0.1:8888";

const browser = await puppeteer.launch({
  executablePath: CHROME, headless: "new",
  args: ["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"],
});
const page = await browser.newPage();
await page.setViewport({ width: 1352, height: 900 });
await page.goto(`${BASE}/ask`, { waitUntil: "networkidle2" });

// ── A. XSS：正则清洗器能不能挡住无引号的事件属性 ──
const XSS = await page.evaluate(() => {
  // 复刻 ask.js:64-73 的 sanitizeHtml（原样，不改）
  function sanitizeHtml(html) {
    if (!html) return '';
    return String(html)
      .replace(/<script[\s\S]*?<\/script>/gi, '')
      .replace(/<iframe[\s\S]*?<\/iframe>/gi, '')
      .replace(/<object[\s\S]*?<\/object>/gi, '')
      .replace(/<embed[\s\S]*?<\/embed>/gi, '')
      .replace(/\s(onc(?:lick|load|error|mouseover|focus|blur|change|submit)\s*=\s*["'][^"']*["'])/gi, '')
      .replace(/(href|src)\s*=\s*["']\s*javascript:[^"']*["']/gi, '$1="#"');
  }
  const payloads = {
    "img-onerror-noquote": '<img src=x onerror=window.__pwned=1>',
    "img-onerror-quoted":  '<img src=x onerror="window.__pwned=1">',
    "svg-onload":          '<svg onload=window.__pwned=1>',
    "a-javascript-noquote": '<a href=javascript:window.__pwned=1>x</a>',
    "body-onload":         '<body onload=window.__pwned=1>',
  };
  const out = {};
  for (const [k, v] of Object.entries(payloads)) {
    const cleaned = sanitizeHtml(v);
    // 关键：清洗后是否仍含 on*= 或 javascript:
    out[k] = {
      survived: cleaned.includes("onerror") || cleaned.includes("onload")
                || /javascript:/i.test(cleaned),
      cleaned,
    };
  }
  return out;
});
console.log("【A】sanitizeHtml 正则清洗结果（survived=true = 危险属性仍存活）");
console.log(JSON.stringify(XSS, null, 2));

// ── B. 真把 payload 灌进页面，看是否真的执行 ──
const pwned = await page.evaluate((html) => {
  const wrap = document.createElement("div");
  wrap.className = "message assistant";
  const b = document.createElement("div");
  b.className = "bubble";
  function sanitizeHtml(h) {
    return String(h || '')
      .replace(/<script[\s\S]*?<\/script>/gi, '')
      .replace(/<iframe[\s\S]*?<\/iframe>/gi, '')
      .replace(/\s(onc(?:lick|load|error|mouseover|focus|blur|change|submit)\s*=\s*["'][^"']*["'])/gi, '')
      .replace(/(href|src)\s*=\s*["']\s*javascript:[^"']*["']/gi, '$1="#"');
  }
  // 走和 ask.js renderMarkdown 完全一样的路径
  b.innerHTML = sanitizeHtml(window.marked.parse(html, { breaks: true, gfm: true, mangle: false, headerIds: false }));
  document.getElementById("messageStream").appendChild(wrap);
  wrap.appendChild(b);
  return { injectedHtml: b.innerHTML, pwned: window.__pwned === 1 };
}, '<img src=x onerror=window.__pwned=1>\n\n<img src=y onerror="window.__pwned=1">');
console.log("\n【B】真实页面执行结果");
console.log(JSON.stringify(pwned, null, 2));

// ── C. 宽表格：列多 + 长内容，窄列里会不会顶破布局 ──
const tbl = await page.evaluate(() => {
  const wrap = document.querySelectorAll("#messageStream .message.assistant");
  const host = wrap[wrap.length - 1];
  const b = host.querySelector(".bubble");
  b.querySelectorAll("table").forEach(t => t.remove());
  // 模拟 AI 给的宽表：7 列 + 长中文
  const md = "| 工具 | 用途 | 什么时候会用 | 覆盖范围 | 频率 | 口径 | 备注 |\n|---|---|---|---|---|---|---|\n"
    + "| **市场行情** | NY 金（COMEX 美元/盎司）、上海金（元/克）、沪金 ETF 518880（元/份）、白银收盘价 + 综合趋势指数（技术 30% + 宏观 40% + 消息面 30%） | \"现在金价多少\"、\"市场整体怎么走\" | NY/SGE/ETF/AG | 60s | 收盘价 | 无 |";
  const t = document.createElement("div");
  t.innerHTML = window.marked.parse(md, { gfm: true });
  b.appendChild(t);
  const table = b.querySelector("table");
  const r = table.getBoundingClientRect();
  const br = b.getBoundingClientRect();
  return {
    tableRectW: Math.round(r.width),
    tableScrollW: table.scrollWidth,
    bubbleClientW: b.clientWidth,
    bubbleScrollW: b.scrollWidth,
    tableOverflowsBubble: table.scrollWidth > b.clientWidth + 1,
    extendsPastBubbleRight: Math.round(r.right) > Math.round(br.right) + 1,
    ownScrollContainer: (() => {
      const p = table.parentElement;
      const s = getComputedStyle(p);
      return p === b ? "(none — 直接挂在 bubble 下，无滚动容器)" : s.overflowX;
    })(),
  };
});
console.log("\n【C】宽表格在 1352px 三栏布局里的实际表现（对话列本身很窄）");
console.log(JSON.stringify(tbl, null, 2));

await browser.close();