// scripts/_verify_nav_8.mjs
// V0.111.1 验证：数据健康降为「配置」子页后，顶 nav 回到 8 项 + 两处导航同序
//
// ⚠ 必须打 8888（主入口）。8889/gold/ 是备用入口且全站 /api/v1/* 404，
//   在那里跑只会得到与本改动无关的假失败。见记忆 lan-only-deployment。
//
// ⚠⚠ V0.125.0 hotfix：**goto 必须禁用浏览器缓存**（`setCacheEnabled(false)`）
//   —— 根因（抓 CDP 原始事件实测定位，**不是** SW）：
//   `/static/*.html` 的响应头只有 `etag` + `last-modified`、**没有 `Cache-Control`**
//   ⇒ Chrome 套用「启发式缓存」⇒ **同一浏览器上下文里再次访问同一页面时，
//     主文档直接从磁盘缓存命中**
//     （实测 `Network.responseReceived` 带 `fromDiskCache=true`）
//   ⇒ 此时 Chrome **不再发 `Page.lifecycleEvent`**
//   ⇒ puppeteer 的 `waitUntil`（`domcontentloaded` / `load` / `networkidle0` /
//     `networkidle2` **全都**）永远等不到那个事件 ⇒ `page.goto` 无限期挂死。
//   实测（脚本 `scripts/_diag_nav8_cdp.mjs` 抓 CDP 事件）：
//     缓存开 + domcontentloaded → 6 次里挂 4 次；缓存开 + networkidle2 → 4 次里挂 2 次；
//     缓存关 → 8 次全过。挂起时页面其实**早已加载完**
//     （`document.readyState === "complete"`、标题正确、`framenavigated` 已发）。
//   ⇒ 修法三条一起上：
//     ① `setCacheEnabled(false)`（**关键**：本项目既有惯例 —— `_verify_money_flow.mjs`
//        等 5 个门禁早就这么写了；缺它的门禁就是会挂的那些）；
//     ② `waitUntil: "domcontentloaded"` + 每个断言点各自 `waitForSelector`
//        （等 DOM，不等网络 —— 见记忆 gate-reads-unready-page）；
//     ③ `setBypassServiceWorker(true)`：LAN 入口（192.168.0.204:8888）**不是安全
//        上下文** ⇒ `navigator.serviceWorker` 为 undefined ⇒ SW 在 LAN 上根本不参与
//        （实测）；保留它是为了 localhost（那里 SW 可用）。
//   ⚠ 与本版改动**无关**：把 static/home.html + home.js 换回 HEAD 版本、
//     重启服务后同一个门禁照样挂死。
//   ⚠ SW 自身的行为由 `scripts/_verify_sw_update.mjs` 单独覆盖，不靠本门禁。
import puppeteer from "puppeteer-core";
import { readFileSync } from "node:fs";

const BASE = process.env.BASE_URL || "http://127.0.0.1:8888";
const CHROME =
  "/home/surui/.cache/puppeteer/chrome/linux-153.0.8010.36/chrome-linux64/chrome";

let pass = 0;
let fail = 0;
function ok(name, cond, extra = "") {
  if (cond) { pass++; console.log(`  ✓ ${name}`); }
  else { fail++; console.log(`  ✗ ${name} ${extra}`); }
}

const browser = await puppeteer.launch({
  executablePath: CHROME,
  headless: "new",
  args: ["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"],
});
const page = await browser.newPage();
// ⚠ 必须禁用浏览器缓存 —— 见文件头「V0.125.0 hotfix」的根因说明：
//   主文档命中磁盘缓存时 Chrome 不发 `Page.lifecycleEvent` ⇒ goto 永远不 settle。
await page.setCacheEnabled(false);
// ⚠ 给门禁**独立的限流桶**（V0.125.0）：服务端按 IP 做 60s 滑动窗口限速
//   （`rate_limit_per_min = 600`），而**首页一次加载会打 ~20 个
//   `/api/v1/favorites/exists/*`** ⇒ 多个首页门禁连着跑就把真实 IP 的额度耗光
//   ⇒ 429 ⇒ 跟被测功能无关的断言（i18n 文案）跟着挂。
//   ⇒ 门禁改用 RFC 5737 文档保留网段的假 IP ⇒ 每个门禁一个**独立桶**，互不干扰。
//   ⚠ 服务端**只对限流**信任 `X-Forwarded-For`：认证默认不看（`trust_proxy_headers=False`，
//     实测 .env.prod 未设该项）；即便开启，XFF 也只用于「审计展示 + 登录节流」，
//     **不做安全判定**（见 middleware/auth.py:124 client_ip 的 docstring）。
await page.setExtraHTTPHeaders({ "X-Forwarded-For": "198.51.100.1" });
// ── 门禁豁免：把首页那 20 个 /api/v1/favorites/exists 请求打桩掉 ──
//   它与本门禁要测的东西无关，却占掉一次 /home 加载 **32 个 API 请求里的 20 个**
//   （实测脚本 scripts/_diag_home_req_count.mjs）⇒ 多个首页门禁连着跑就把服务端
//   `RATE_LIMIT_PER_MIN=600` 的额度吃光 ⇒ **429** ⇒ 跟被测功能无关的断言
//   （i18n 文案 / chip）跟着挂 —— 实测本门禁连跑 4 次就挂过 1 次。
//   ⇒ 打桩成「未收藏」（真实端点在未收藏时返回 200 + body `null`）。
//   ⚠ **豁免失效的条件**：若哪天有门禁要断言**收藏态**，必须先撤掉这条打桩。
await page.setRequestInterception(true);
page.on("request", async (req) => {
  if (req.url().includes("/api/v1/favorites/exists/")) {
    return req.respond({ status: 200, contentType: "application/json", body: "null" });
  }
  return req.continue();
});
await page.setBypassServiceWorker(true);
const bad = [];
page.on("response", (r) => {
  if (r.status() >= 400 && !/favicon/.test(r.url())) bad.push(`${r.status()} ${r.url()}`);
});

// 顶 nav 项抽取（排除 brand —— 它也是 <a> 但不是场景项）
async function readTopnav() {
  return page.$$eval(".topnav a, .topnav-item", (els) =>
    els
      .filter((e) => !String(e.className).includes("brand"))
      .map((e) => ({
        href: e.getAttribute("href") || "",
        text: e.textContent.trim(),
        active: String(e.className).includes("active"),
      }))
  );
}

// ─── 1. 顶 nav 8 项 ───
console.log("【1】顶 nav 项数");
await page.goto(`${BASE}/home`, { waitUntil: "domcontentloaded" });
await page.waitForSelector(".topnav a", { timeout: 15000 });
const nav = await readTopnav();
ok("顶 nav 8 个场景项", nav.length === 8, `实际 ${nav.length}：${nav.map((n) => n.text).join(" / ")}`);

const labels = nav.map((n) => n.text);
ok("数据健康不再是顶项", !labels.some((t) => t.includes("数据健康")), labels.join(" / "));

// ⚠ V0.120.4：这几条断言原先**按中文文案**认人（"AI 智能分析"），
//   而顶栏的标签真正的来源是 i18n 字典（nav.ask = "智能分析"），
//   topnav.js 里那个 "AI 智能分析" 只是**兜底 fb**。
//   V0.120.4 修完 home.js 的 i18n 取值 bug 之后，顶栏终于真的走了字典 ——
//   zh-CN 显示 "智能分析"（字典值）而不是 "AI 智能分析"（fb）。
//   ⇒ 旧断言等于**把 bug 当成了期望**：它要求的正是「顶栏别翻译」。
//   而且旧行为本身是自相矛盾的：实测 zh-CN 显示 fb「AI 智能分析」、
//   en-US 显示字典值「Ask AI」—— 同一处顶栏两种语言两种文案。
// ⇒ 改成按 **href** 认人（稳定契约），文案另与**字典值**比对
//   （这样「顶栏回退到 fb」这种回归仍能被抓到）。
const EXPECTED_HREFS = ["/home", "/headlines", "/scoring", "/portfolio", "/news", "/report-archive", "/weights", "/ask"];
const gotHrefs = nav.map((n) => {
  const h = (n.href || "").replace(BASE, "").replace(/\/$/, "") || (n.href || "");
  return h;
});
ok("AI 智能分析仍是顶项", gotHrefs.some((h) => h.includes("/ask")), gotHrefs.join(" → "));
ok("AI 排在最后一项", (gotHrefs[gotHrefs.length - 1] || "").includes("/ask"), gotHrefs[gotHrefs.length - 1]);
ok("顺序与预期一致（按 href）", JSON.stringify(gotHrefs) === JSON.stringify(EXPECTED_HREFS),
  gotHrefs.join(" → "));

// 顶栏文案必须来自字典，而不是 topnav.js 的 fb
const dictSrc = readFileSync(new URL("../static/i18n/zh-CN.js", import.meta.url), "utf8");
const dictAsk = (dictSrc.match(/"nav\.ask"\s*:\s*"([^"]+)"/) || [])[1] || "";
const aiLabel = (nav.find((n) => (n.href || "").includes("/ask")) || {}).text || "";
ok("AI 顶项文案 = 字典值（不是 fb 兜底）",
  !!dictAsk && aiLabel.includes(dictAsk),
  `实际 "${aiLabel}" 字典 "${dictAsk}"`);

// ─── 2. 配置的 subnav 含数据健康 ───
console.log("\n【2】配置子页");
await page.goto(`${BASE}/weights`, { waitUntil: "domcontentloaded" });
await page.waitForSelector(".topnav a", { timeout: 15000 });
await page.waitForSelector(".subnav a, .subnav-item, .subnav .tab", { timeout: 15000 });
const sub = await page.$$eval(".subnav a, .subnav-item, .subnav .tab", (els) =>
  els.map((e) => ({ href: e.getAttribute("href") || "", text: e.textContent.trim() }))
);
ok("配置渲染出 subnav", sub.length >= 3, `实际 ${sub.length}：${sub.map((s) => s.text).join(" / ")}`);
ok("subnav 含数据健康", sub.some((s) => s.text.includes("数据健康")), sub.map((s) => s.text).join(" / "));
ok("subnav 仍含权重配置 + 通知中心",
  sub.some((s) => s.text.includes("权重配置")) && sub.some((s) => s.text.includes("通知中心")));

const navOnWeights = await readTopnav();
const activeTop = navOnWeights.find((n) => n.active);
ok("在 /weights 时「配置」高亮", (activeTop?.text || "").includes("配置"), activeTop?.text);

// ─── 3. 数据健康页：高亮回归 + 仍是独立场景渲染 ───
console.log("\n【3】数据健康页");
await page.goto(`${BASE}/data-health`, { waitUntil: "domcontentloaded" });
await page.waitForSelector(".topnav a", { timeout: 15000 });
await page.waitForSelector(".subnav a, .subnav-item, .subnav .tab", { timeout: 15000 });
const navHealth = await readTopnav();
const activeHealth = navHealth.find((n) => n.active);
ok("数据健康页高亮「配置」（不再是独立顶项）", (activeHealth?.text || "").includes("配置"), activeHealth?.text);
const subOnHealth = await page.$$eval(".subnav a, .subnav-item, .subnav .tab", (els) =>
  els.map((e) => ({ text: e.textContent.trim(), active: String(e.className).includes("active") }))
);
const healthTab = subOnHealth.find((s) => s.text.includes("数据健康"));
ok("数据健康子页自身高亮", !!healthTab?.active, JSON.stringify(subOnHealth));
// 别名会 307 到静态页，必须真的落到 data-health 内容上
const hTitle = await page.evaluate(() => document.body.innerText.slice(0, 200));
ok("数据健康页内容正常（非 404）", !/404 Not Found/i.test(hTitle), hTitle.slice(0, 60));

// ─── 4. 首页 9 张板块 ───
console.log("\n【4】首页板块");
await page.goto(`${BASE}/home`, { waitUntil: "domcontentloaded" });
await page.waitForSelector(".home-scene", { timeout: 15000 });
const cards = await page.$$eval(".home-scene", (els) =>
  els.map((e) => ({
    href: e.getAttribute("href"),
    title: (e.querySelector(".scene-title") || {}).textContent || "",
    items: Array.from(e.querySelectorAll(".scene-links li")).map((li) => li.textContent.trim()),
  }))
);
// V0.111.1 定稿：首页 8 张板块。数据健康虽是「配置」的子页，但仍保留自己的首页卡
// （它有独立的摘要信息，是用户常回看的页面）—— 所以首页卡与顶 nav **不是**一一对应。
// V0.127.0：新增「金价区间」卡（未来 20 交易日扇形区间）⇒ 8 → 9 张。
ok("首页 9 张场景卡", cards.length === 9, `实际 ${cards.length}：${cards.map((c) => c.title).join(" / ")}`);
ok("首页有数据健康卡", cards.some((c) => c.title.includes("数据健康")), cards.map((c) => c.title).join(" / "));
ok("AI 卡在最后", (cards[cards.length - 1]?.title || "").includes("AI 智能分析"), cards[cards.length - 1]?.title);
ok("无 undefined 泄漏", !cards.some((c) => c.title.includes("undefined")));

const cfg = cards.find((c) => (c.href || "").includes("weights"));
ok("配置卡列出 3 个子项（含数据健康）", cfg?.items.length === 3 && cfg.items.some((i) => i.includes("数据健康")), JSON.stringify(cfg?.items));

const hl = cards.find((c) => c.title.includes("数据健康"));
ok("数据健康卡指向 /data-health 别名", hl?.href === "/data-health", hl?.href);

// V0.127.0：新增「金价区间」卡 ⇒ 断言它在，且指向 /price-forecast
const fc = cards.find((c) => (c.href || "").includes("price-forecast"));
ok("首页有金价区间卡", !!fc, cards.map((c) => c.title).join(" / "));
ok("金价区间卡指向 /price-forecast", fc?.href === "/price-forecast", fc?.href);
ok("金价区间卡列出 3 个子项", fc?.items.length === 3, JSON.stringify(fc?.items));

// 首页卡顺序 = 顶 nav 去掉「首页」，再在「配置」后补回「数据健康」
const EXPECTED_CARDS = ["今日要闻", "决策", "金价区间", "持仓", "情报", "报告存档", "配置", "数据健康", "AI 智能分析"];
const gotCards = cards.map((c) => EXPECTED_CARDS.find((x) => c.title.includes(x)) || `?(${c.title})`);
ok("首页卡顺序与顶 nav 一致", JSON.stringify(gotCards) === JSON.stringify(EXPECTED_CARDS), gotCards.join(" → "));

// ─── 5. 三语 ───
console.log("\n【5】三语");
for (const [lang, expect] of [["en-US", "Data Health"], ["zh-TW", "數據健康"], ["zh-CN", "数据健康"]]) {
  await page.goto(`${BASE}/weights`, { waitUntil: "domcontentloaded" });
  await page.waitForSelector(".topnav a", { timeout: 15000 });
  await page.evaluate(async (l) => { await window.I18n.setLang(l); }, lang);
  await new Promise((r) => setTimeout(r, 500));
  const body = await page.evaluate(() => document.body.innerText);
  ok(`${lang} 「数据健康」子项已翻译`, body.includes(expect), `找不到「${expect}」`);
  ok(`${lang} 无 undefined 泄漏`, !body.includes("undefined"));
}
// 恢复中文，别把用户的浏览器留在测试语言上
await page.evaluate(async () => { await window.I18n.setLang("zh-CN"); });

// ─── 汇总 ───
console.log("\n【网络】");
const notFavicon = bad.filter((u) => !/favicon\.ico/.test(u));
ok("无 4xx/5xx", notFavicon.length === 0, JSON.stringify(notFavicon.slice(0, 5)));

await browser.close();
console.log(`\n${"=".repeat(56)}`);
console.log(`  结果：${pass} passed, ${fail} failed`);
console.log("=".repeat(56));
process.exit(fail === 0 ? 0 : 1);