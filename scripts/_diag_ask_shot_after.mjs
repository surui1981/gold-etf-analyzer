// 终检：往真实页面灌一条「典型 AI markdown 回复」，过 renderAssistantMsg 真路径，截 1352 / 390 两张图
import puppeteer from "puppeteer-core";
const CHROME = "/home/surui/.cache/puppeteer/chrome/linux-153.0.8010.36/chrome-linux64/chrome";
const BASE = "http://127.0.0.1:8888";

const MD = `AI 一句话结论：**金价短线承压，中期未破位**，建议持有观望。

## 数据支撑

| 口径 | 最新 | 日变动 | 近 5 日 |
|------|------|--------|--------|
| COMEX XAU | 4094.5 | -0.26% | +0.8% |
| SHFE Au99.99 | 728.4 | +0.12% | +1.4% |
| 518880 ETF | 2.913 | -0.31% | +0.5% |

## 关键观察

1. ETF 连续 3 日净流入，合计 \`+2.1 亿元\`
2. COMEX 库存近 1 年 \`-41.65%\`，供给端仍是主要支撑
3. 央行购金 2026Q2 全球合计 **184 吨**，环比 +6 吨

原始数据片段：

\`\`\`json
{"symbol": "XAU", "price_usd": 4094.5, "change_pct": -0.26,
 "cometx_inventory_t": 727.96, "inventory_yoy_pct": -41.65}
\`\`\`

## 建议

分批建仓，单次不超过计划仓位的 1/3。

参考：[伦敦金走势](https://www.example.com/gold/price-trend?period=1y&ref=chat-long-path-segment-1234567890)`;

const browser = await puppeteer.launch({
  executablePath: CHROME, headless: "new",
  args: ["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"],
});
const errs = [];

for (const [tag, vp] of [["desktop", { width: 1352, height: 900 }], ["mobile", { width: 390, height: 844 }]]) {
  const page = await browser.newPage();
  page.on("pageerror", (e) => errs.push(`[${tag}] pageerror ` + e));
  page.on("console", (m) => { if (m.type() === "error") errs.push(`[${tag}] console ` + m.text()); });
  await page.setViewport(vp);
  await page.goto(`${BASE}/ask`, { waitUntil: "networkidle2" });

  // 关掉 PWA 安装横幅，否则它盖住整个下半屏（截图实测）
  await page.evaluate(() => {
    document.querySelectorAll("#installPrompt, .install-prompt, [id*=install i], [class*=install i]")
      .forEach((n) => n.remove());
  });

  // 走真路径：直接调页面里的 renderMarkdown + enhanceBubble（与 renderAssistantMsg 同一套）
  const r = await page.evaluate((md) => {
    document.getElementById("emptyState")?.remove();
    const stream = document.getElementById("messageStream");
    stream.innerHTML = "";
    const msg = document.createElement("div");
    msg.className = "message assistant";
    const wrap = document.createElement("div");
    wrap.className = "bubble-wrap";
    const b = document.createElement("div");
    b.className = "bubble";
    b.innerHTML = window.__askTest.renderMarkdown(md);
    wrap.appendChild(b);
    msg.appendChild(wrap);
    stream.appendChild(msg);
    window.__askTest.enhanceBubble(b, true);
    const vw = document.documentElement.clientWidth;
    const bb = b.getBoundingClientRect();
    const h2 = b.querySelector("h2"), hr = b.querySelector("hr");
    return {
      vw,
      docScrollW: document.documentElement.scrollWidth,
      bubbleW: Math.round(bb.width), bubbleRight: Math.round(bb.right),
      tableScroll: !!b.querySelector(".table-scroll"),
      copyBtn: !!b.querySelector(".copy-code-btn"),
      linkTarget: b.querySelector("a")?.getAttribute("target"),
      linkRel: b.querySelector("a")?.getAttribute("rel"),
      h2MarginTop: h2 ? getComputedStyle(h2).marginTop : null,
      hrMargin: hr ? getComputedStyle(hr).marginTop : null,
      nested: !!b.querySelector(".bubble"),
    };
  }, MD);

  console.log(`\n【${tag} ${vp.width}×${vp.height}】`);
  console.log(JSON.stringify(r, null, 2));

  // ⚠ 元素截图在移动端会错乱（clip 超出视口 ⇒ 文本叠在一起，见第一次 mobile 截图）。
  //    改成滚到消息顶部再截整个视口。
  await page.evaluate(() => {
    // 移动端侧栏（会话列表）会把消息流挤成一小条；截图前先收起来，
    // 再把 .message-stream（自己的滚动容器）滚到底。
    if (innerWidth < 700) document.querySelector(".ask-sidebar")?.remove();
    const stream = document.getElementById("messageStream");
    // 滚到代码块（看复制按钮工具条行），滚不到再退到底部
    const cb = document.querySelector(".code-block");
    if (cb && stream) stream.scrollTop = cb.offsetTop - 8;
    else if (stream) stream.scrollTop = stream.scrollHeight;
    window.scrollTo(0, 0);
  });
  await new Promise((r) => setTimeout(r, 200));
  await page.screenshot({ path: `/tmp/ask_after_${tag}.png` });
  console.log(`shot -> /tmp/ask_after_${tag}.png`);
  await page.close();
}
console.log("\nerrors:", errs.length ? errs : "(none)");
await browser.close();