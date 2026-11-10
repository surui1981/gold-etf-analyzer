// scripts/_verify_home_report.mjs
// V0.125.0 验证：首页「今日市场研究报告」条带（只显示最新上传的那一份）
//
// ⚠ 必须打 8888（主入口）。8889/gold/ 是备用入口且全站 /api/v1/* 404，
//   在那里跑只会得到与本改动无关的假失败。见记忆 lan-only-deployment。
// ⚠ 视口必须 1352×900：默认 800×600 下顶 nav 会盖住按钮，page.click 静默失效。
//   见记忆 puppeteer-viewport-sticky-nav。
// ⚠ 打桩前必须 setBypassServiceWorker(true) —— SW 接管页面后 request 拦截
//   静默失效，第二次导航拿的是真数据（见记忆
//   puppeteer-sw-silently-bypasses-interception）。
// ⚠ 断言一律打在 textContent 上，不打 data-lang 属性（属性切了不代表字典已
//   apply 到 DOM，见记忆 i18n-init-await）。
import puppeteer from "puppeteer-core";

const BASE = process.env.BASE_URL || "http://127.0.0.1:8888";
const CHROME =
  "/home/surui/.cache/puppeteer/chrome/linux-153.0.8010.36/chrome-linux64/chrome";

let pass = 0;
let fail = 0;
function ok(name, cond, extra = "") {
  if (cond) { pass++; console.log(`  ✓ ${name}`); }
  else { fail++; console.log(`  ✗ ${name}${extra ? " → " + extra : ""}`); }
}

const browser = await puppeteer.launch({
  executablePath: CHROME,
  headless: "new",
  args: ["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"],
});
const page = await browser.newPage();
await page.setViewport({ width: 1352, height: 900 });
// ⚠ 必须禁用浏览器缓存（V0.125.0 定位的挂死根因）：
//   `/static/*.html` 无 `Cache-Control` ⇒ Chrome 启发式缓存 ⇒ 主文档从磁盘缓存
//   命中时**不发 `Page.lifecycleEvent`** ⇒ `waitUntil` 永不 settle ⇒ goto 挂死。
await page.setCacheEnabled(false);
// ⚠ 给门禁**独立的限流桶**（V0.125.0）：服务端按 IP 做 60s 滑动窗口限速
//   （`rate_limit_per_min = 600`），而**首页一次加载会打 ~20 个
//   `/api/v1/favorites/exists/*`** ⇒ 多个首页门禁连着跑就把真实 IP 的额度耗光
//   ⇒ 429 ⇒ 跟被测功能无关的断言（i18n 文案）跟着挂。
//   ⇒ 门禁改用 RFC 5737 文档保留网段的假 IP ⇒ 每个门禁一个**独立桶**，互不干扰。
//   ⚠ 服务端**只对限流**信任 `X-Forwarded-For`：认证默认不看（`trust_proxy_headers=False`，
//     实测 .env.prod 未设该项）；即便开启，XFF 也只用于「审计展示 + 登录节流」，
//     **不做安全判定**（见 middleware/auth.py:124 client_ip 的 docstring）。
await page.setExtraHTTPHeaders({ "X-Forwarded-For": "198.51.100.2" });
// ⚠ SW 会绕过 puppeteer 的 request 拦截 ⇒ 打桩必须先绕过 SW。
await page.setBypassServiceWorker(true);

// ── 门禁豁免：把首页那 20 个 /api/v1/favorites/exists 请求打桩掉 ──
//   它与本门禁要测的东西无关，却占掉一次 /home 加载 **32 个 API 请求里的 20 个**
//   （实测脚本 scripts/_diag_home_req_count.mjs）⇒ 多个首页门禁连着跑就把服务端
//   `RATE_LIMIT_PER_MIN=600` 的额度吃光 ⇒ **429** ⇒ 跟被测功能无关的断言
//   （i18n 文案 / chip）跟着挂 —— 实测本门禁连跑 4 次就挂过 1 次。
//   ⇒ 打桩成「未收藏」（真实端点在未收藏时返回 200 + body `null`）。
//   ⚠ **豁免失效的条件**：若哪天有门禁要断言**收藏态**，必须先撤掉这条打桩。
//   ⚠ 另一个打桩（/reports/latest 的空态 / 故障态）用同一个 handler + 一个可切换
//   的开关实现 —— puppeteer 的多个 request 监听器会**重复 resolve 同一个请求**，
//   必须合成一个 handler。
let mockLatest = null; // null = 放行真实响应；否则 {status, body} 表示打桩
await page.setRequestInterception(true);
page.on("request", async (req) => {
  const u = req.url();
  if (u.includes("/api/v1/favorites/exists/")) {
    return req.respond({ status: 200, contentType: "application/json", body: "null" });
  }
  if (mockLatest && u.endsWith("/api/v1/reports/latest")) {
    return req.respond({
      status: mockLatest.status,
      contentType: "application/json",
      body: mockLatest.body,
    });
  }
  return req.continue();
});

// 三处错误来源分别收集 —— console 和 response 会把同一个 4xx 重复报一遍。
// ⚠ console 那条要带上 location().url —— 浏览器对「Failed to load resource」
//   只给一句没有 URL 的话，过滤时认不出是不是本脚本自己打桩的那个 500。
// ⚠ 打桩阶段（mockPhase = true）的错误单独收进 mockErrs ——
//   自打桩的 500 是**预期内**的，不该混进最终断言；但打桩期间的
//   **429 限流**必须被抓出来（那不是预期，是额度被吃光了）。
const errs = new Set();
const mockErrs = new Set();
let mockPhase = false;
page.on("pageerror", (e) => (mockPhase ? mockErrs : errs).add(`pageerror: ${String(e)}`));
page.on("console", (m) => {
  if (m.type() !== "error") return;
  const loc = m.location?.()?.url || "";
  (mockPhase ? mockErrs : errs).add(`console: ${m.text()}${loc ? ` @ ${loc}` : ""}`);
});
page.on("response", (r) => {
  if (r.status() >= 400) (mockPhase ? mockErrs : errs).add(`HTTP ${r.status()} ${r.url()}`);
});

// ─── 0. 先把真实 API 的返回值抓下来（断言要用它当基准，不能用页面自己的值）───
console.log("【0】基准：真实 /api/v1/reports/latest");
const apiRes = await fetch(`${BASE}/api/v1/reports/latest`);
ok("端点返回 200", apiRes.status === 200, `实际 ${apiRes.status}`);
const apiJson = await apiRes.json();
ok("返回体含 item 字段（空库也是 item=null，不是 404）",
  Object.prototype.hasOwnProperty.call(apiJson, "item"),
  JSON.stringify(apiJson).slice(0, 120));
const item = apiJson.item;
ok("线上库里确实有一份报告（否则本脚本的「有值」断言无意义）",
  !!item, "item=null —— 请先在 /report-archive 上传一份");
if (!item) {
  await browser.close();
  console.log(`\n结果：${pass} passed, ${fail} failed`);
  process.exit(1);
}
// ⚠ 复算「上传于」：后端 created_at 是 **UTC 但不带 Z**（SQLite CURRENT_TIMESTAMP），
//   必须补 'Z' 再按本地时区渲染，否则比真实时刻早 8 小时。
const parsedUtc = new Date(item.created_at + "Z");
const p2 = (n) => String(n).padStart(2, "0");
const expectDt =
  `${parsedUtc.getFullYear()}-${p2(parsedUtc.getMonth() + 1)}-${p2(parsedUtc.getDate())} ` +
  `${p2(parsedUtc.getHours())}:${p2(parsedUtc.getMinutes())}`;
const expectSize =
  item.size_bytes < 1024 ? `${item.size_bytes} B`
  : item.size_bytes < 1048576 ? `${(item.size_bytes / 1024).toFixed(1)} KB`
  : `${(item.size_bytes / 1024 / 1024).toFixed(1)} MB`;
// ⚠ 这条断言的**鉴别力自检**：朴素解析（不补 'Z'，按本地时间）必须与期望值**不同**
//   —— 否则「上传于」那条断言就是恒真的假绿（换任何时刻都过）。
const naive = new Date(item.created_at);
const naiveDt =
  `${naive.getFullYear()}-${p2(naive.getMonth() + 1)}-${p2(naive.getDate())} ` +
  `${p2(naive.getHours())}:${p2(naive.getMinutes())}`;
ok("鉴别力自检：朴素解析 ≠ UTC 换算值（否则该断言恒真）",
  naiveDt !== expectDt, `朴素 "${naiveDt}" / 期望 "${expectDt}"`);

// ─── 1. 条带存在 + 位置 + 场景卡数量没动 ───
console.log("【1】条带存在、位置、场景卡数量");
await page.goto(`${BASE}/home`, { waitUntil: "networkidle2" });
await page.waitForFunction(
  () => !!document.querySelector("#homeReportBody .home-report-item"),
  { timeout: 30000 }
).catch(() => {});
const layout = await page.evaluate(() => {
  const sec = document.getElementById("homeReport");
  const scenes = document.querySelector(".home-scenes");
  const metal = document.querySelector(".home-metals");
  const bottom = document.querySelector(".home-bottom");
  return {
    hasSection: !!sec,
    // ⚠ 条带必须**不在** .home-scenes 里 —— 那是 8 张 260px 磁贴的网格，
    //   且 4 个门禁脚本硬编码「场景卡 = 8 张」。
    insideScenes: !!(sec && scenes && scenes.contains(sec)),
    scenesCount: document.querySelectorAll(".home-scene").length,
    // 条带应在 .home-scenes 之后、.home-metals 之前
    // ⚠ compareDocumentPosition 的位义：a.compareDocumentPosition(b) 描述的是 **b 相对 a** 的位置。
    //   DOCUMENT_POSITION_FOLLOWING(4) = b 在 a 之后；PRECEDING(2) = b 在 a 之前。
    afterScenes: !!(sec && scenes && (sec.compareDocumentPosition(scenes) & 2)),
    beforeMetals: !!(sec && metal && (sec.compareDocumentPosition(metal) & 4)),
    hasBottom: !!bottom,
    title: document.getElementById("homeReportTitle")?.textContent.trim() || "",
    allLink: document.querySelector('.home-report-actions a[href="/report-archive"]')?.textContent.trim() || "",
  };
});
ok("存在 #homeReport 条带", layout.hasSection);
ok("条带不在 .home-scenes 网格里（保住 4 个门禁的「8 张场景卡」断言）",
  !layout.insideScenes);
ok("场景卡仍是 8 张", layout.scenesCount === 8, `实际 ${layout.scenesCount}`);
ok("条带排在 .home-scenes 之后", layout.afterScenes);
ok("条带排在 .home-metals 之前", layout.beforeMetals);
ok("标题渲染为「今日市场研究报告」", layout.title === "今日市场研究报告", `实际 "${layout.title}"`);
ok("「全部报告 →」指向 /report-archive", layout.allLink === "全部报告 →", `实际 "${layout.allLink}"`);

// ─── 2. 条带内容 == 真实 API ───
console.log("【2】条带内容与真实 API 逐项一致");
const dom = await page.evaluate(() => {
  const body = document.getElementById("homeReportBody");
  const link = body?.querySelector(".home-report-title");
  const cta = body?.querySelector(".home-report-cta");
  return {
    chip: document.getElementById("homeReportChip")?.textContent.trim() || "",
    titleText: link?.textContent.trim() || "",
    href: link?.getAttribute("href") || "",
    target: link?.getAttribute("target") || "",
    rel: link?.getAttribute("rel") || "",
    meta: body?.querySelector(".home-report-meta")?.textContent.trim() || "",
    cat: body?.querySelector(".home-report-meta .cat")?.textContent.trim() || "",
    sum: body?.querySelector(".home-report-sum")?.textContent.trim() || "",
    ctaText: cta?.textContent.trim() || "",
    ctaHref: cta?.getAttribute("href") || "",
    empty: !!body?.querySelector(".home-report-empty"),
  };
});
ok("日期 chip == 报告自身日期（不是上传日）",
  dom.chip === String(item.report_date).slice(0, 10), `实际 "${dom.chip}"`);
ok("标题文本 == 报告标题", dom.titleText === item.title,
  `实际 "${dom.titleText}" vs "${item.title}"`);
ok("标题链接指向报告本体端点",
  dom.href === `/api/v1/reports/${item.id}/content` && dom.href === item.view_url,
  `实际 "${dom.href}"`);
ok("报告本体只能**新标签页**打开（/content 带 CSP sandbox ⇒ 不能 iframe）",
  dom.target === "_blank", `实际 target="${dom.target}"`);
ok("链接带 rel=noopener noreferrer",
  dom.rel.includes("noopener") && dom.rel.includes("noreferrer"), `实际 rel="${dom.rel}"`);
ok("meta 含分类", dom.cat === item.category, `实际 "${dom.cat}"`);
ok("meta 含文件大小", dom.meta.includes(expectSize), `实际 "${dom.meta}" 期望含 "${expectSize}"`);
ok("meta 含「上传于」且时间按 UTC 正确换算（不是本地直读的 8 小时偏差）",
  dom.meta.includes(expectDt), `实际 "${dom.meta}" 期望含 "${expectDt}"`);
ok("摘要已渲染", dom.sum === item.summary, `实际 "${dom.sum.slice(0, 40)}"`);
ok("CTA 文案为「查看报告 →」", dom.ctaText === "查看报告 →", `实际 "${dom.ctaText}"`);
ok("CTA 与标题指向同一处", dom.ctaHref === dom.href, `实际 "${dom.ctaHref}"`);
ok("有值时**不**显示空态文案", !dom.empty);

// ─── 3. 空态（打桩 {item:null}）──
console.log("【3】空态：一份都没上传过");
mockPhase = true;
mockLatest = { status: 200, body: JSON.stringify({ item: null }) };
await page.reload({ waitUntil: "networkidle2" });
await page.waitForFunction(
  () => !!document.querySelector("#homeReportBody .home-report-empty"),
  { timeout: 30000 }
).catch(() => {});
const emptyState = await page.evaluate(() => ({
  text: document.querySelector("#homeReportBody .home-report-empty")?.textContent.trim() || "",
  chip: document.getElementById("homeReportChip")?.textContent.trim() || "",
  isEmptyClass: document.getElementById("homeReport")?.className.includes("is-empty") || false,
  hasItem: !!document.querySelector("#homeReportBody .home-report-item"),
}));
ok("空态文案是「还没有上传过报告 —— 去「报告存档」上传一份。」",
  emptyState.text === "还没有上传过报告 —— 去「报告存档」上传一份。", `实际 "${emptyState.text}"`);
ok("空态时 chip 显示「—」", emptyState.chip === "—", `实际 "${emptyState.chip}"`);
ok("空态**不**走降级样式（空库是正常状态，不是故障）", !emptyState.isEmptyClass);
ok("空态时没有渲染出条目", !emptyState.hasItem);

// ─── 4. 故障态（打桩 500）──
console.log("【4】故障态：端点挂了");
mockLatest = { status: 500, body: "{}" };
await page.reload({ waitUntil: "networkidle2" });
await page.waitForFunction(
  () => !!document.querySelector("#homeReportBody .home-report-empty"),
  { timeout: 30000 }
).catch(() => {});
const failState = await page.evaluate(() => ({
  text: document.querySelector("#homeReportBody .home-report-empty")?.textContent.trim() || "",
  chip: document.getElementById("homeReportChip")?.textContent.trim() || "",
  isEmptyClass: document.getElementById("homeReport")?.className.includes("is-empty") || false,
}));
ok("故障态文案是「报告加载失败」", failState.text === "报告加载失败", `实际 "${failState.text}"`);
ok("故障态**不**说「暂无报告」（绝不把故障说成空库）",
  !failState.text.includes("还没有上传过"));
ok("故障态走降级样式（.is-empty）", failState.isEmptyClass);
ok("故障态 chip 显示「—」", failState.chip === "—", `实际 "${failState.chip}"`);

// ─── 4.5 反向验证：撤掉打桩 ⇒ 故障文案必须消失、真值必须回来 ───
console.log("【4.5】反向验证：撤掉打桩");
// ⚠ 只把 **/reports/latest 的打桩**撤掉（放行真实响应），**不**关掉整个
//   request interception —— favorites 的打桩要留着（见上面的豁免说明），
//   否则这一阶段的 20 个 favorites 请求会重新打到服务端、吃掉限流额度。
mockLatest = null;
mockPhase = false;
await page.reload({ waitUntil: "networkidle2" });
await page.waitForFunction(
  () => !!document.querySelector("#homeReportBody .home-report-item"),
  { timeout: 30000 }
).catch(() => {});
const restored = await page.evaluate(() => ({
  hasItem: !!document.querySelector("#homeReportBody .home-report-item"),
  failText: document.body.innerText.includes("报告加载失败"),
  emptyText: document.body.innerText.includes("还没有上传过报告"),
  chip: document.getElementById("homeReportChip")?.textContent.trim() || "",
}));
ok("撤掉打桩后条目回来了", restored.hasItem);
ok("撤掉打桩后「报告加载失败」消失", !restored.failText);
ok("撤掉打桩后也不出现「还没有上传过报告」", !restored.emptyText);
ok("撤掉打桩后 chip 恢复为报告日期",
  restored.chip === String(item.report_date).slice(0, 10), `实际 "${restored.chip}"`);

// ─── 5. 三语 ───
console.log("【5】三语渲染");
const LANGS = [
  ["zh-CN", "今日市场研究报告", "查看报告 →", "全部报告 →"],
  ["zh-TW", "今日市場研究報告", "查看報告 →", "全部報告 →"],
  ["en-US", "Today's Market Research Report", "View report →", "All reports →"],
];
for (const [lang, title, cta, all] of LANGS) {
  // ⚠ 两个键名都踩过坑：localStorage 键是 **pm_lang**，全局是 **window.I18n**。
  await page.evaluate(async (l) => {
    localStorage.setItem("pm_lang", l);
    if (window.I18n?.setLang) await window.I18n.setLang(l);
  }, lang);
  await page.reload({ waitUntil: "networkidle2" });
  await page.waitForFunction(
    () => !!document.querySelector("#homeReportBody .home-report-item"),
    { timeout: 30000 }
  ).catch(() => {});
  const got = await page.evaluate(() => ({
    title: document.getElementById("homeReportTitle")?.textContent.trim() || "",
    cta: document.querySelector("#homeReportBody .home-report-cta")?.textContent.trim() || "",
    all: document.querySelector(".home-report-actions a")?.textContent.trim() || "",
    chip: document.getElementById("homeReportChip")?.textContent.trim() || "",
  }));
  ok(`${lang} 条带标题`, got.title === title, `实际 "${got.title}"`);
  ok(`${lang} CTA 文案`, got.cta === cta, `实际 "${got.cta}"`);
  ok(`${lang} 「全部报告」文案`, got.all === all, `实际 "${got.all}"`);
  ok(`${lang} chip 仍是报告日期（不是键字面量）`,
    got.chip === String(item.report_date).slice(0, 10), `实际 "${got.chip}"`);
}

// ─── 6. 错误收口 ───
console.log("【6】错误收口");
const errList = [...errs].filter((e) => !/favicon/i.test(e));
ok("无 console / pageerror / HTTP>=400（打桩阶段的错误已单独收进 mockErrs）",
  errList.length === 0, errList.slice(0, 5).join(" | "));
// ⚠ 打桩阶段唯一**不该**出现的是 429（限流）—— 自打桩的 500 是预期内的。
const mock429 = [...mockErrs].filter((e) => /429/.test(e));
ok("打桩期间没有 429（限流额度够用）", mock429.length === 0, mock429.slice(0, 3).join(" | "));

await browser.close();
console.log(`\n结果：${pass} passed, ${fail} failed`);
process.exit(fail === 0 ? 0 : 1);
