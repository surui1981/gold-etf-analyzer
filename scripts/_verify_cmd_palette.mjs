// scripts/_verify_cmd_palette.mjs
// V0.112.0 验证：⌘K 命令面板（可见入口 / 自动派生清单 / 桌面+手机 / 三语）
//
// 覆盖：
//  1. 18 个有顶栏的页都挂了 command-palette.js，且顶栏都有「⌘ 搜索」按钮
//  2. 点按钮能打开面板（此前**全站 0 个可见入口**，手机端等于没有）
//  3. 清单是**自动派生**的：含 V0.68 硬编码清单里没有的 4 条
//     （今日要闻 / 报告存档 / 数据健康 / AI），且场景分组与 SCENES 顺序一致
//  4. 每个导航命令的 href 实测可达（200/307）—— 清单里的死链是照样能显示的
//  5. 手机视口 390px 下按钮可见可点、面板能开、行高够触摸目标 ← 「手机上打不开」的修复证据
//  6. 桌面 Ctrl+K 仍可用（老用户的手感不能因为加了按钮就丢）
//  7. 三语切换查 textContent（不是 data-lang —— 见记忆 i18n-init-await）
//
// ⚠ 必须打 8888（主入口）。8889/gold/ 是备用入口且全站 /api/v1/* 404，
//   在那里跑只会得到与本改动无关的假失败。见记忆 lan-only-deployment。
// ⚠ 必须 setViewport(1352×900)。puppeteer 默认 800×600，顶 nav 在窄宽下会折行、
//   撑高后的 sticky 层盖住下方元素，page.click() 会点不中。见记忆
//   puppeteer-viewport-sticky-nav。
import puppeteer from "puppeteer-core";

const BASE = process.env.BASE_URL || "http://127.0.0.1:8888";
const CHROME =
  "/home/surui/.cache/puppeteer/chrome/linux-153.0.8010.36/chrome-linux64/chrome";

// 18 个挂 topnav-mount 的页（与 check_cluster_render 的页面清单同源口径）
const PAGES = [
  "home", "headlines", "scoring", "trend", "backtest", "review",
  "portfolio", "trades", "news", "central_bank", "silver", "favorites",
  "report-archive", "report", "weights", "settings", "data-health", "ask",
];

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
await page.setViewport({ width: 1352, height: 900 });

const pageErrors = [];
page.on("pageerror", (e) => pageErrors.push(e.message));
page.on("console", (m) => {
  if (m.type() === "error" && !/Failed to load resource|favicon/i.test(m.text()))
    pageErrors.push(m.text());
});

// ─── 1/2. 逐页：脚本挂载 + 按钮存在 + 点得开 ───
console.log("【1】18 页逐页：挂载 + 可见入口 + 可打开");
let openedAll = 0;
for (const name of PAGES) {
  await page.goto(`${BASE}/static/${name}.html`, { waitUntil: "networkidle2" });
  const hasBtn = await page.waitForSelector(".nav-btn-cmd", { timeout: 15000 })
    .then(() => true)
    .catch(() => false);
  if (!hasBtn) { ok(`${name} 顶栏有搜索按钮`, false, "没找到 .nav-btn-cmd"); continue; }

  // 用 evaluate 触发而不是 page.click()：顶栏是 sticky，窄宽下会遮挡，
  // 但这里点的是**顶栏自己的按钮**，即便被遮挡事件也该派发到它 —— 用 click
  // 反而会引入与本断言无关的视口耦合。
  const opened = await page.evaluate(async () => {
    document.querySelector(".nav-btn-cmd").click();
    await new Promise((r) => setTimeout(r, 250));
    return document.body.classList.contains("pm-cmd-open");
  });
  if (opened) openedAll++;
  else ok(`${name} 点按钮能打开面板`, false);

  const n = await page.$$eval(".pm-cmd-item", (e) => e.length);
  if (n < 10) ok(`${name} 清单条目数`, false, `只有 ${n} 条`);
  await page.evaluate(() => window.PM_CmdPalette.close());
}
ok("18 页全部能点开面板", openedAll === PAGES.length, `${openedAll}/${PAGES.length}`);
console.log(`  （${PAGES.length} 页逐页检查完毕）`);

// ─── 3. 清单是派生的，不是 V0.68 那份硬编码 ───
console.log("\n【2】清单内容（自动派生）");
await page.goto(`${BASE}/static/home.html`, { waitUntil: "networkidle2" });
await page.waitForSelector(".nav-btn-cmd");
await page.evaluate(async () => {
  document.querySelector(".nav-btn-cmd").click();
  await new Promise((r) => setTimeout(r, 250));
});

const secs = await page.$$eval(".pm-cmd-sec", (e) => e.map((x) => x.textContent.trim()));
const items = await page.$$eval(".pm-cmd-item", (e) =>
  e.map((x) => ({
    label: x.querySelector(".pm-cmd-label").textContent.trim(),
    hint: x.querySelector(".pm-cmd-hint").textContent.trim(),
  }))
);

// 18 而不是 19：帮助命令是**按需出现**的 —— help.js 只挂在 10 个页上
//（ask/central_bank/news/data-health/portfolio/settings/scoring/trades/weights/trend），
// home.html 没有它，所以少一条。有 help.js 的页上应是 19（见下方 trend.html 那段）。
ok("清单共 18 条（17 导航 + 刷新；本页无 help.js）", items.length === 18, `实际 ${items.length}`);
ok("按场景分组", secs.length === 9, `实际 ${secs.length} 组：${secs.join(" / ")}`);

// 这 4 条是 V0.68 硬编码清单里**没有**的，正是「两代导航都没跟上」的实证
for (const must of ["今日要闻", "报告存档", "数据健康", "智能分析"]) {
  ok(`含「${must}」（V0.68 清单里没有）`, items.some((i) => i.label.includes(must)));
}
ok("含首页", items.some((i) => i.label.includes("首页")));

// 去重：8 场景 + 13 子页 = 21 个 path，但 4 个场景 path 与某子页重合 → 17 条
const hints = items.map((i) => i.hint).filter((h) => h.startsWith("/"));
ok("17 个导航 URL 且无重复", hints.length === 17 && new Set(hints).size === 17,
   `${hints.length} 条 / ${new Set(hints).size} 个唯一`);

// 分组顺序应与 SCENES 顺序一致（首页/今日要闻/决策/持仓/情报/报告存档/配置/AI）
const EXPECT_SECS = ["首页", "今日要闻", "决策", "持仓", "情报", "报告存档", "配置", "智能分析", "动作"];
ok("分组顺序与 SCENES 一致", JSON.stringify(secs) === JSON.stringify(EXPECT_SECS), secs.join(" → "));

// ─── 4. 死链检查 ───
console.log("\n【3】导航命令 href 实测可达");
const dead = [];
for (const h of [...new Set(hints)]) {
  const r = await fetch(`${BASE}${h}`, { redirect: "manual" });
  if (!(r.status >= 200 && r.status < 400)) dead.push(`${r.status} ${h}`);
}
ok("全部导航 URL 可达（200/307）", dead.length === 0, JSON.stringify(dead));

// ─── 3b. 动作命令不是死的 ───
console.log("\n【4】动作命令真的接了线");
const actLabels = items.slice(-1).map((i) => i.label);
ok("动作组含刷新", actLabels.some((l) => l.includes("刷新")), JSON.stringify(actLabels));

// help.js 页上才有帮助命令（按需出现，见上面 18/19 条的说明）
await page.goto(`${BASE}/static/trend.html`, { waitUntil: "networkidle2" });
await page.waitForSelector(".nav-btn-cmd");
const trendItems = await page.evaluate(async () => {
  document.querySelector(".nav-btn-cmd").click();
  await new Promise((r) => setTimeout(r, 250));
  const n = document.querySelectorAll(".pm-cmd-item").length;
  const last = document.querySelectorAll(".pm-cmd-item");
  const lastLabel = last[last.length - 1].textContent;
  window.PM_CmdPalette.close();
  return { n, lastLabel };
});
ok("有 help.js 的页是 19 条", trendItems.n === 19, `实际 ${trendItems.n}`);
ok("动作组含帮助（trend 有 help.js）", trendItems.lastLabel.includes("引导"), trendItems.lastLabel);

// 帮助命令 → 功能导览弹窗真的打开（V0.68 调的是不存在的 PM_Help.show()）
const helpWorks = await page.evaluate(async () => {
  document.querySelector(".nav-btn-cmd").click();
  await new Promise((r) => setTimeout(r, 250));
  const its = document.querySelectorAll(".pm-cmd-item");
  its[its.length - 1].click();               // 最后一条 = 帮助
  await new Promise((r) => setTimeout(r, 400));
  const m = document.getElementById("pmHelpModal");
  return m ? !m.hidden : null;
});
ok("帮助命令打开功能导览弹窗", helpWorks === true, String(helpWorks));

// ─── 6. 桌面 Ctrl+K ───
console.log("\n【5】桌面 Ctrl+K 快捷键");
await page.goto(`${BASE}/static/home.html`, { waitUntil: "networkidle2" });
await page.waitForSelector(".nav-btn-cmd");
await page.keyboard.down("Control");
await page.keyboard.press("KeyK");
await page.keyboard.up("Control");
await new Promise((r) => setTimeout(r, 250));
ok("Ctrl+K 打开面板", await page.evaluate(() => document.body.classList.contains("pm-cmd-open")));
await page.keyboard.press("Escape");
await new Promise((r) => setTimeout(r, 250));
ok("Esc 关闭面板", await page.evaluate(() => !document.body.classList.contains("pm-cmd-open")));

// ─── 5. 手机视口 ───
console.log("\n【6】手机视口 390px");
await page.setViewport({ width: 390, height: 844, isMobile: true, hasTouch: true });
await page.goto(`${BASE}/static/headlines.html`, { waitUntil: "networkidle2" });
await page.waitForSelector(".nav-btn-cmd");

const btnBox = await page.$eval(".nav-btn-cmd", (e) => {
  const r = e.getBoundingClientRect();
  const cs = getComputedStyle(e);
  return { w: r.width, h: r.height, display: cs.display, visible: r.width > 0 && r.height > 0 };
});
ok("手机上按钮可见", btnBox.visible && btnBox.display !== "none", JSON.stringify(btnBox));
ok("按钮触摸高度 ≥ 44px", btnBox.h >= 44, `${Math.round(btnBox.h)}px`);

const mOpen = await page.evaluate(async () => {
  document.querySelector(".nav-btn-cmd").click();
  await new Promise((r) => setTimeout(r, 300));
  return document.body.classList.contains("pm-cmd-open");
});
ok("手机上能打开面板（V0.112.0 的核心修复）", mOpen === true);

const rowH = await page.$$eval(".pm-cmd-item", (e) =>
  Math.min(...e.map((x) => x.getBoundingClientRect().height))
);
ok("清单行高 ≥ 44px 触摸目标", rowH >= 44, `${Math.round(rowH)}px`);

const footText = await page.$eval(".pm-cmd-foot", (e) => e.textContent.trim());
ok("底部提示是触屏文案（不含 ⌘K / ↑↓ / Esc）",
   !/⌘K|Ctrl K|↑↓|Esc/.test(footText) && footText.length > 0, footText);

// 横向不溢出
const overflow = await page.evaluate(() =>
  document.documentElement.scrollWidth - document.documentElement.clientWidth
);
ok("手机上无横向溢出", overflow <= 1, `溢出 ${overflow}px`);

await page.setViewport({ width: 1352, height: 900 });

// ─── 7. 三语 ───
console.log("\n【7】三语");
for (const [lang, expect] of [["en-US", "Search"], ["zh-TW", "搜尋"], ["zh-CN", "搜索"]]) {
  await page.goto(`${BASE}/static/home.html`, { waitUntil: "networkidle2" });
  await page.waitForSelector(".nav-btn-cmd");
  // ⚠ 用 I18n.setLang() 公开 API（key 是 pm_lang，不是 i18n_lang），且必须 await
  await page.evaluate(async (l) => { await window.I18n.setLang(l); }, lang);
  await new Promise((r) => setTimeout(r, 600));
  // ⚠ 查 textContent，不是 data-lang 属性 —— data-lang 只是标记，不代表真翻过了
  const btn = await page.$eval(".nav-btn-cmd", (e) => e.textContent.trim());
  ok(`${lang} 顶栏按钮已翻译`, btn.includes(expect), `实际「${btn}」`);
  ok(`${lang} 无 undefined 泄漏`, !btn.includes("undefined"));
}
await page.evaluate(async () => { await window.I18n.setLang("zh-CN"); });

// ─── 汇总 ───
console.log("\n【JS 运行时错误】");
// ⚠ 既存缺陷（**不是** V0.112.0 引入，最后改动见 V0.82 e0305fe）：
//   static/settings.js 三处裸调 apiJson(...)，但该函数在 auth.js 里是局部 function，
//   只以 PM_AUTH.apiJson 暴露 ⇒ ReferenceError。settings.js 用经典 script 加载、
//   auth.js 用 defer，加载顺序还不同，修起来不能想当然，故本轮不动，单列出来。
//   这里显式过滤而不是静默忽略 —— 免得哪天它消失了没人发现。
const KNOWN = /apiJson is not defined/;
const knownErrors = pageErrors.filter((e) => KNOWN.test(e));
const realErrors = pageErrors.filter((e) => !KNOWN.test(e));
if (knownErrors.length) {
  console.log(`  ⚠ 已知既存缺陷（settings.js 裸调 apiJson，V0.82 起）：${knownErrors.length} 次`);
}
ok("无其它 pageerror / console.error", realErrors.length === 0, JSON.stringify(realErrors.slice(0, 5)));

await browser.close();
console.log(`\n${"=".repeat(56)}`);
console.log(`  结果：${pass} passed, ${fail} failed`);
console.log("=".repeat(56));
process.exit(fail === 0 ? 0 : 1);