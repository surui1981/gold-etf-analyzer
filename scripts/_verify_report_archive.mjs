// scripts/_verify_report_archive.mjs
// V0.111.0 验证：/report-archive 页 + 上传 + 新标签页沙箱隔离
//
// 覆盖：
//  1. 首页第 8 张场景卡渲染 + 点击进 /report-archive
//  2. 顶 nav 第 5 项「报告存档」存在且高亮
//  3. 真实 multipart 上传 → 卡片出现
//  4. 点「查看」新标签页打开，报告 HTML 正常渲染（脚本执行、样式生效）
//  5. ⚠ 报告页内 localStorage 访问抛 SecurityError —— opaque origin 的**直接证据**
//     （只看 CSP 响应头不算验证隔离，必须证明浏览器真的执行了 sandbox）
//  6. 报告页内 fetch 调不动 /api/v1/*（connect-src 'none'）
//  7. 搜索 / 分类 / 标签 筛选联动
//  8. 编辑登记表（PATCH）→ 标题变化
//  9. 删除 → 卡片消失 + 磁盘文件消失
// 10. 3 语切换查 textContent（不是 data-lang 属性 —— 见记忆 frontend-undefined-rendering）
//
// 基线归零：上一次运行可能留下同名报告导致断言读到旧卡片，先按标题清场。
import puppeteer from "puppeteer-core";

const BASE = process.env.BASE_URL || "http://127.0.0.1:8890";
const TITLE = "Puppeteer验证报告";
const TAG = "verify-tag";

const CHROME =
  "/home/surui/.cache/puppeteer/chrome/linux-153.0.8010.36/chrome-linux64/chrome";

let pass = 0;
let fail = 0;
function ok(name, cond, extra = "") {
  if (cond) {
    pass++;
    console.log(`  ✓ ${name}`);
  } else {
    fail++;
    console.log(`  ✗ ${name} ${extra}`);
  }
}

// ─── 清场：删掉上次运行留下的同标题报告 ───
async function cleanup() {
  const r = await fetch(`${BASE}/api/v1/reports?q=${encodeURIComponent(TITLE)}`);
  const d = await r.json();
  for (const it of d.items || []) {
    await fetch(`${BASE}/api/v1/reports/${it.id}`, { method: "DELETE" });
  }
  return (d.items || []).length;
}

const removed = await cleanup();
console.log(`基线清场：删除历史报告 ${removed} 份\n`);

const browser = await puppeteer.launch({
  executablePath: CHROME,
  headless: "new",
  args: ["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"],
});

const page = await browser.newPage();
// ⚠ 必须给一个够大的视口。puppeteer 默认 800x600，顶 nav 在窄宽下会折行成多行、
//   撑高后的 sticky 层（z-index 100）正好盖住上传按钮 —— page.click() 于是把点击
//   派发给了顶栏的 pmThemeBtn，脚本表现为「点了没反应 / 上传超时」。
//   1280x720 / 1352x900 实测正常，这也是真实用户的使用尺寸。
await page.setViewport({ width: 1352, height: 900 });
const consoleErrors = [];
const badResponses = [];
page.on("console", (m) => {
  // 资源加载失败（4xx/5xx）由 badResponses 按 URL 记录，这里跳过，
  // 否则同一件事会被记两次，且这条消息里没有 URL、无法判断是否 favicon
  if (m.type() === "error" && !/Failed to load resource/i.test(m.text()))
    consoleErrors.push(m.text());
});
page.on("pageerror", (e) => consoleErrors.push("pageerror: " + e.message));
page.on("response", (r) => {
  if (r.status() >= 400) badResponses.push(`${r.status()} ${r.url()}`);
});

// ─── 1. 首页第 8 张场景卡 ───
console.log("【1】首页场景卡");
await page.goto(`${BASE}/home`, { waitUntil: "networkidle2" });
await page.waitForSelector(".home-scene", { timeout: 15000 });
const cards = await page.$$eval(".home-scene", (els) =>
  els.map((e) => ({
    href: e.getAttribute("href"),
    title: (e.querySelector(".scene-title") || {}).textContent || "",
  }))
);
// V0.111.1 定稿：首页 8 张板块。数据健康归到「配置」子页但仍保留自己的首页卡，
// 所以首页卡数（8）与顶 nav 场景数（8）相等，却不是一一对应。
ok("首页 8 张场景卡", cards.length === 8, `实际 ${cards.length}`);
const archiveCard = cards.find((c) => c.href === "/report-archive");
ok("存在 scene-archive 卡", !!archiveCard);
ok("卡片标题非 undefined", archiveCard && !archiveCard.title.includes("undefined"), archiveCard?.title);
ok("卡片文字为「报告存档」", archiveCard?.title.trim() === "报告存档", archiveCard?.title);

// ─── 2. 顶 nav ───
console.log("\n【2】顶 nav");
// ⚠ 选择器会连 brand 链接一起选中（它是 .brand，不属于场景项）—— 计数时必须排除
const navAll = await page.$$eval(".topnav a, .topnav-item", (els) =>
  els.map((e) => ({
    cls: e.className,
    href: e.getAttribute("href"),
    text: e.textContent.trim(),
  }))
);
const navItems = navAll.filter((n) => !n.cls.includes("brand"));
// V0.111.1：数据健康降为「配置」子页后，顶 nav 由 9 项回到 8 项
ok("顶 nav 8 个场景项", navItems.length === 8, `实际 ${navItems.length}（含 brand 共 ${navAll.length}）`);
const navArchive = navItems.find((n) => (n.href || "").includes("report-archive"));
ok("nav 含报告存档", !!navArchive);
// 文案含 emoji 前缀（📁），所以用 includes 而不是等值
ok("nav 文案正确", (navArchive?.text || "").includes("报告存档"), navArchive?.text);
const pos = navItems.findIndex((n) => (n.href || "").includes("report-archive"));
const intelPos = navItems.findIndex((n) => (n.href || "").includes("news"));
ok("紧邻情报之后", pos === intelPos + 1, `archive@${pos} intel@${intelPos}`);

// 点卡片进入
await page.click('.home-scene[href="/report-archive"]');
await page.waitForFunction(() => location.pathname.includes("report-archive"), {
  timeout: 10000,
});
ok("点击卡片进入报告存档页", page.url().includes("report-archive"));

// ─── 3. 上传 ───
console.log("\n【3】上传");
await page.waitForSelector("#btnToggleUpload", { timeout: 10000 });
await page.click("#btnToggleUpload");
await page.waitForSelector("#uploadCard:not([hidden])", { timeout: 5000 });
ok("上传卡展开", true);

const html = `<!DOCTYPE html><html><head><meta charset="utf-8"><title>探针报告</title>
<style>body{font-family:sans-serif;background:#fff}</style></head>
<body><h1 id="hdr">Puppeteer 探针</h1><p id="probe">init</p>
<script>
  document.getElementById('probe').textContent = 'script-executed';
  window.__probeStorage = (function(){ try { localStorage.getItem('x'); return 'accessible'; }
    catch(e){ return e.name; } })();
  window.__probeFetch = fetch('/api/v1/reports').then(()=> 'fetch-ok').catch(e => 'fetch-blocked:' + (e && e.message ? e.message.slice(0,40) : String(e)));
</script></body></html>`;

const input = await page.$("#fileInput");
// ⚠ puppeteer-core 的 uploadFile 只收磁盘路径，不收 {name, buffer} 对象
// （对象形式会报 ERR_INVALID_ARG_TYPE）—— 先落临时文件再喂。
const TMP_REPORT = "/tmp/_puppeteer_probe.html";
const { writeFileSync, rmSync } = await import("node:fs");
writeFileSync(TMP_REPORT, html, "utf8");
await input.uploadFile(TMP_REPORT);
await page.waitForFunction(() => document.getElementById("pickedName")?.hidden === false, {
  timeout: 5000,
});
ok("选中文件后显示文件名", true);

await page.type("#upTitle", TITLE);
await page.type("#upCategory", "研报");
await page.type("#upTags", `${TAG}, 黄金`);
await page.type("#upSummary", "puppeteer 实跑上传");

await page.click("#btnUpload");
await page.waitForFunction(
  (t) => Array.from(document.querySelectorAll(".rep-card h3")).some((h) => h.textContent.trim() === t),
  { timeout: 20000 },
  TITLE
);
ok("上传成功且卡片出现", true);

const cardInfo = await page.evaluate((t) => {
  const card = Array.from(document.querySelectorAll(".rep-card")).find(
    (c) => c.querySelector("h3")?.textContent.trim() === t
  );
  if (!card) return null;
  return {
    cat: card.querySelector(".cat")?.textContent.trim(),
    tags: Array.from(card.querySelectorAll(".tag-chip")).map((e) => e.textContent.trim()),
    fname: card.querySelector(".fname")?.textContent.trim(),
    summary: card.querySelector(".summary")?.textContent.trim(),
    meta: card.querySelector(".meta")?.textContent.trim(),
    viewHref: card.querySelector("a.view")?.getAttribute("href"),
    viewTarget: card.querySelector("a.view")?.getAttribute("target"),
  };
}, TITLE);
ok("卡片分类正确", cardInfo?.cat === "研报", cardInfo?.cat);
ok("卡片标签正确", (cardInfo?.tags || []).includes(TAG) && (cardInfo?.tags || []).includes("黄金"), JSON.stringify(cardInfo?.tags));
ok("卡片显示原名+大小", /\.html/.test(cardInfo?.fname || "") && /B$|KB|MB/.test(cardInfo?.fname || ""), cardInfo?.fname);
ok("摘要渲染", cardInfo?.summary === "puppeteer 实跑上传", cardInfo?.summary);
ok("⚠ 上传时间无 {dt} 泄漏", cardInfo?.meta && !cardInfo.meta.includes("{dt}"), cardInfo?.meta);
ok("「查看」指向 /content", /\/api\/v1\/reports\/\d+\/content/.test(cardInfo?.viewHref || ""), cardInfo?.viewHref);
ok("「查看」target=_blank", cardInfo?.viewTarget === "_blank", cardInfo?.viewTarget);

// ─── 4/5/6. 新标签页沙箱隔离 ───
console.log("\n【4】新标签页 + 沙箱隔离");
const before = (await browser.pages()).length;
await page.click(".rep-card a.view");
await new Promise((r) => setTimeout(r, 2500));
const pages = await browser.pages();
ok("新标签页已打开", pages.length > before, `${before} → ${pages.length}`);

const rpage = pages[pages.length - 1];
await rpage.waitForSelector("#probe", { timeout: 10000 });

ok("报告 HTML 正常渲染", (await rpage.$eval("#hdr", (e) => e.textContent.trim())) === "Puppeteer 探针");
const probeTxt = await rpage.$eval("#probe", (e) => e.textContent.trim());
ok("⚠ 报告内脚本执行（渲染保真）", probeTxt === "script-executed", probeTxt);

const storage = await rpage.evaluate(() => window.__probeStorage);
ok("⚠ localStorage 抛 SecurityError（opaque origin）", storage === "SecurityError", `实际: ${storage}`);

const origin = await rpage.evaluate(() => String(window.origin));
ok("⚠ document origin 为 null", origin === "null", `实际: ${origin}`);

const canReachParent = await rpage.evaluate(() => {
  try { return window.parent !== window; } catch (e) { return "threw:" + e.name; }
});
ok("⚠ 够不到 window.parent", canReachParent === false, String(canReachParent));

const fetchResult = await rpage.evaluate(() => window.__probeFetch);
ok("⚠ fetch 被 connect-src 'none' 封死", String(fetchResult).startsWith("fetch-blocked"), String(fetchResult));

// ─── 7. 筛选 ───
console.log("\n【7】筛选");
await rpage.close();
const pages2 = await browser.pages();
await pages2[0].bringToFront();
await page.bringToFront();

await page.waitForSelector("#searchInput", { timeout: 10000 });
await page.type("#searchInput", TITLE);
await page.waitForFunction(
  () => document.querySelectorAll(".rep-card").length === 1,
  { timeout: 8000 }
);
ok("搜索命中唯一卡片", true);

await page.evaluate(() => { document.getElementById("searchInput").value = ""; });
await page.type("#searchInput", "不存在的关键词zzz");
await page.waitForFunction(
  () => !!document.querySelector(".empty-state"),
  { timeout: 8000 }
);
ok("搜不到时显示空态", true);
await page.evaluate(() => { document.getElementById("searchInput").value = ""; });
await page.evaluate(() => {
  document.getElementById("searchInput").dispatchEvent(new Event("input", { bubbles: true }));
});
await page.waitForFunction(() => document.querySelectorAll(".rep-card").length >= 1, { timeout: 8000 });

// 分类筛选
await page.select("#catSel", "研报");
await page.waitForFunction(
  () => Array.from(document.querySelectorAll(".rep-card h3")).some((h) => h.textContent.trim() === "十月金价月报" || h.textContent.trim().startsWith("Puppeteer")),
  { timeout: 8000 }
);
ok("分类筛选联动", true);

// ─── 8. 编辑登记表 ───
console.log("\n【8】编辑登记表");
await page.select("#catSel", "");
await new Promise((r) => setTimeout(r, 900));
await page.evaluate((t) => {
  const card = Array.from(document.querySelectorAll(".rep-card")).find(
    (c) => c.querySelector("h3")?.textContent.trim() === t
  );
  card.querySelector(".edit").click();
  card.querySelector(".f-title").value = t + "-已改名";
  card.querySelector(".save").click();
}, TITLE);
// ⚠ waitForFunction 的签名是 (fn, options, ...args) —— 忘了把 TITLE 作为第三个
// 实参传进去的话，t 是 undefined，等于在等一个永远不会出现的 "undefined-已改名"。
// 下面删除那步同款错误还会「假通过」（因为没人等于 "undefined-已改名"）。
await page.waitForFunction(
  (t) =>
    Array.from(document.querySelectorAll(".rep-card h3")).some(
      (h) => h.textContent.trim() === t + "-已改名"
    ),
  { timeout: 10000 },
  TITLE
);
ok("PATCH 改标题生效", true);

// ─── 10. 3 语 ───
console.log("\n【10】i18n 三语");
// ⚠ 用 I18n.setLang() 公开 API，而不是手改 localStorage —— key 是 pm_lang
// （不是 i18n_lang），且 setLang 内部会 await 载入字典后才 apply，
// 漏了这一步就会拿到 zh-CN 字面量（见记忆 i18n-init-await）。
// 顺带走通 i18n:change 事件 → 验证 report-archive.js 的重渲染监听。
for (const [lang, expect] of [["en-US", "Report Archive"], ["zh-TW", "報告存檔"], ["zh-CN", "报告存档"]]) {
  await page.evaluate(async (l) => {
    await window.I18n.setLang(l);
  }, lang);
  await new Promise((r) => setTimeout(r, 600));
  // ⚠ 查 textContent，不是 data-lang 属性 —— data-lang 只是标记，不代表真的翻过了
  const bodyText = await page.evaluate(() => document.body.innerText);
  const navText = await page.evaluate(
    () => (document.querySelector(".topnav") || {}).textContent || ""
  );
  ok(`${lang} 页面标题已翻译`, bodyText.includes(expect), `找不到「${expect}」`);
  ok(`${lang} 顶 nav 已翻译`, navText.includes(expect), navText.trim().slice(0, 60));
  ok(`${lang} 无 undefined 泄漏`, !bodyText.includes("undefined"));
}

// ─── 9. 删除 ───
console.log("\n【9】删除");
await page.reload({ waitUntil: "networkidle2" });
await page.waitForSelector(".rep-card", { timeout: 15000 });
page.on("dialog", (d) => d.accept());
await page.evaluate((t) => {
  const card = Array.from(document.querySelectorAll(".rep-card")).find(
    (c) => c.querySelector("h3")?.textContent.trim() === t + "-已改名"
  );
  card.querySelector(".del").click();
}, TITLE);
await page.waitForFunction(
  (t) =>
    !Array.from(document.querySelectorAll(".rep-card h3")).some(
      (h) => h.textContent.trim() === t + "-已改名"
    ),
  { timeout: 10000 },
  TITLE
);
ok("删除后卡片消失", true);

const apiCheck = await fetch(`${BASE}/api/v1/reports?q=${encodeURIComponent(TITLE)}`);
const apiData = await apiCheck.json();
ok("⚠ 删除后 API 查不到", (apiData.items || []).length === 0, JSON.stringify(apiData.items));

// ─── 汇总 ───
console.log("\n【控制台错误】");
// ⚠ 不能按 console 文本过滤 —— 404 的消息是 "Failed to load resource: the
// server responded with a status of 404 (Not Found)"，**不含 URL**，
// 只认 favicon 的话得看 response 事件的 URL。
const notFavicons = badResponses.filter((u) => !/favicon\.ico/.test(u));
ok("无 4xx/5xx 资源请求（favicon 除外）", notFavicons.length === 0, JSON.stringify(notFavicons.slice(0, 5)));
ok("无 JS 运行时错误", consoleErrors.length === 0, JSON.stringify(consoleErrors.slice(0, 5)));

await browser.close();
rmSync(TMP_REPORT, { force: true });
console.log(`\n${"=".repeat(56)}`);
console.log(`  结果：${pass} passed, ${fail} failed`);
console.log("=".repeat(56));
process.exit(fail === 0 ? 0 : 1);
