// 诊断 8：打开真实对话，截「今天金价怎么样？」这类含表格/标题的回复原图
import puppeteer from "puppeteer-core";
const CHROME = "/home/surui/.cache/puppeteer/chrome/linux-153.0.8010.36/chrome-linux64/chrome";
const BASE = "http://127.0.0.1:8888";

const browser = await puppeteer.launch({
  executablePath: CHROME, headless: "new",
  args: ["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"],
});
const page = await browser.newPage();
await page.setViewport({ width: 1352, height: 900 });
const errs = [];
page.on("pageerror", (e) => errs.push("pageerror " + e));
page.on("console", (m) => { if (m.type() === "error") errs.push("console " + m.text()); });
await page.goto(`${BASE}/ask`, { waitUntil: "networkidle2" });

// 点开第 2 个会话（"📈 今天金价怎么样？"）
const clicked = await page.evaluate(() => {
  const items = [...document.querySelectorAll("#convList .conv-item")];
  if (!items.length) return { ok: false, n: 0 };
  items[0].click();
  return { ok: true, n: items.length, title: items[1].textContent.slice(0, 30) };
});
await new Promise((r) => setTimeout(r, 2500));

const info = await page.evaluate(() => {
  const asst = [...document.querySelectorAll("#messageStream .message.assistant")];
  // 挑内容最长的那条（更可能含表格/标题）
  let last = asst[0], best = -1;
  for (const a of asst) { const L = (a.textContent||"").length; if (L > best) { best = L; last = a; } }
  if (!last) return { n: asst.length };
  const outer = last.querySelector(".bubble");
  const inner = outer?.querySelector(".bubble");
  const cs = outer ? getComputedStyle(outer) : null;
  return {
    assistantCount: asst.length,
    nestedBubble: !!inner,
    outerPad: cs ? cs.padding : null,
    outerBorder: cs ? cs.border : null,
    hasH2: !!last.querySelector("h2, h3"),
    hasTable: !!last.querySelector("table"),
    hasPre: !!last.querySelector("pre"),
    text: (last.textContent || "").replace(/\s+/g, " ").slice(0, 120),
  };
});
console.log("clicked:", JSON.stringify(clicked));
console.log("info   :", JSON.stringify(info, null, 2));
console.log("errors :", errs.slice(0, 5));

const el = await page.$("#messageStream .message.assistant:last-child");
if (el) { await el.screenshot({ path: "/tmp/ask_real_before.png" }); console.log("shot -> /tmp/ask_real_before.png"); }
await browser.close();