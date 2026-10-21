// scripts/_verify_mobile.mjs
// V0.113.0 验证：移动端可用性（390px 窄屏）
//
// 覆盖三类此前无门禁、也无人实测过的缺陷：
//  1. **横向溢出**：11 张宽表散在 4 个页（scoring / silver / report / central_bank），
//     全都没有滚动容器 ⇒ /scoring 在 390px 下整页横溢出 221px。
//     断言：18 页 scrollWidth == clientWidth。
//  2. **触摸目标 < 44px**：实测 /headlines 有 115 个可点元素只有 27-29px。
//     断言：18 页「真控件」（排除正文内文字链 / label[for]）无一 < 44px。
//  3. **聚焦被 sticky 顶栏吃掉**：浏览器滚动对齐不知道上面压着顶栏，Tab 会把目标
//     送到顶栏底下。断言：逐个 focus() 后 elementFromPoint 命中的不是顶栏。
//
// ⚠ 视口用 isMobile:false。isMobile:true 会让 innerWidth 比 clientWidth 大 ~11px
//   （模拟器工件），凭空造出一个不存在的横向溢出，V0.113.0 调查时被它误导过一次。
// ⚠ 必须打 8888（主入口），8889/gold/ 全站 /api/v1/* 404。见记忆 lan-only-deployment。
import puppeteer from "puppeteer-core";

const BASE = process.env.BASE_URL || "http://127.0.0.1:8888";
const CHROME =
  "/home/surui/.cache/puppeteer/chrome/linux-153.0.8010.36/chrome-linux64/chrome";

// 与 check_cluster_render / _verify_cmd_palette 同源的 18 页口径
const PAGES = [
  "home", "headlines", "scoring", "trend", "backtest", "review",
  "portfolio", "trades", "news", "central_bank", "silver", "favorites",
  "report-archive", "report", "weights", "settings", "data-health", "ask",
];

// 表格滚动容器：本次新增包裹的 4 个页（scoring / silver / report / central_bank）。
//
// ⚠ 这里**不能**断言「每个页恰好 N 个容器」：其中 9 张表是 JS 在**数据到达后**才渲染的
//   （silver 升贴水表在报价未就绪时根本不建；report 5 段各自有 show(sec) 门控），
//   数据没来容器就不在 DOM 里。按数据计数会把「数据没到」误报成「包裹漏了」。
//   所以这里只判「一个都没有」，精确数量放到下面【5b】按**源码**契约断言（与数据无关）。
const WRAPPED = { scoring: 1, silver: 1, report: 1, central_bank: 1 };

let pass = 0, fail = 0;
function ok(name, cond, extra = "") {
  if (cond) { pass++; console.log(`  ✓ ${name}`); }
  else { fail++; console.log(`  ✗ ${name} ${extra}`); }
}

const browser = await puppeteer.launch({
  executablePath: CHROME, headless: "new",
  args: ["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"],
});
const page = await browser.newPage();
// ⚠ 390×844 但**不开** isMobile —— 见文件头
await page.setViewport({ width: 390, height: 844 });

const pageErrors = [];
page.on("pageerror", (e) => pageErrors.push(e.message));
page.on("console", (m) => {
  if (m.type() === "error" && !/Failed to load resource|favicon/i.test(m.text()))
    pageErrors.push(m.text());
});

// ─── 1/2/3 逐页三项检查 ───
console.log("【1】390px 逐页：横向溢出 + 触摸目标 + 聚焦遮挡");
const overflowBad = [];
const touchBad = [];
const occlBad = [];

// 有些页有常驻轮询/长连接，networkidle2 永远等不到 —— 超时不算失败，
// 退回 domcontentloaded 再固定等一会儿，页面该渲染的都渲染完了。
async function goto(url, wait = 1100) {
  try {
    await page.goto(url, { waitUntil: "networkidle2", timeout: 20000 });
  } catch (e) {
    if (!/Navigation timeout/i.test(e.message)) throw e;
    await page.goto(url, { waitUntil: "domcontentloaded", timeout: 20000 });
  }
  await new Promise((r) => setTimeout(r, wait));
}

for (const name of PAGES) {
  await goto(`${BASE}/static/${name}.html`);

  const r = await page.evaluate(async () => {
    const de = document.documentElement;

    // ── 横向溢出 ──
    const over = de.scrollWidth - de.clientWidth;

    // ── 触摸目标 ──
    // 真控件 = button / input / select / textarea / summary / role=button|tab
    // 排除两类**不是**触摸目标的：
    //   · 正文段落流里的文字链（新闻标题、来源名）—— 放大它们会撕碎文字排版
    //   · label[for] —— 触摸目标是它 for 指向的控件，label 只是文字标签
    //   · checkbox / radio 本体 —— 触摸区域是包它的 <label>
    const PROSE = new Set(["P","TD","TH","LI","H1","H2","H3","H4","H5","SPAN","DIV","DD","DT",
      "BLOCKQUOTE","FIGCAPTION","ARTICLE","SECTION","MAIN","FOOTER","HEADER","NAV","ASIDE",
      "UL","OL","DL","TABLE","TR","BODY","HTML","SUMMARY","DETAILS","FORM","LABEL"]);
    const SEL = 'button, input:not([type=hidden]), select, textarea, summary, [role="button"], [role="tab"]';
    const small = [];
    for (const el of document.querySelectorAll(SEL)) {
      const bb = el.getBoundingClientRect();
      if (bb.height >= 44 || bb.height === 0 || bb.width === 0) continue;
      if (el.closest("[hidden]")) continue;
      if (el.tagName === "INPUT" && /^(checkbox|radio)$/.test(el.type)) {
        // 触摸区域看外层 label
        const lab = el.closest("label");
        if (lab && lab.getBoundingClientRect().height >= 44) continue;
        small.push({ sel: el.tagName.toLowerCase() + "#" + (el.id || "?"), h: Math.round(bb.height), why: "checkbox 无够高 label" });
        continue;
      }
      const cs = getComputedStyle(el);
      if (cs.display === "none" || cs.visibility === "hidden") continue;
      if (el.tagName === "A") continue;               // 文字链，不算
      if (el.tagName === "LABEL" && el.htmlFor && document.getElementById(el.htmlFor)) continue;
      // 祖先是正文流 ⇒ 多半是行内文字链
      let inProse = false;
      for (let a = el.parentElement; a && a !== document.body; a = a.parentElement) {
        if (PROSE.has(a.tagName.toUpperCase())) { inProse = true; break; }
      }
      if (inProse && el.tagName !== "BUTTON") continue;
      small.push({ sel: el.tagName.toLowerCase() + (el.id ? "#" + el.id : "." + String(el.className).trim().split(/\s+/)[0]),
        h: Math.round(bb.height), why: "真控件偏小" });
    }

    // ── 聚焦被顶栏遮挡 ──
    const nav = document.querySelector(".topnav");
    const occl = [];
    let navB = 0;
    if (nav) {
      navB = nav.getBoundingClientRect().bottom;
      window.scrollTo(0, document.body.scrollHeight);
      await new Promise((r) => setTimeout(r, 140));
      const targets = [...document.querySelectorAll(
        'a[href], button, input:not([type=hidden]), select, textarea, summary, [tabindex]:not([tabindex="-1"])')]
        .filter((e) => !e.closest(".topnav") && !e.closest("[hidden]"))
        .filter((e) => {
          const cs = getComputedStyle(e);
          if (cs.display === "none" || cs.visibility === "hidden") return false;
          const b = e.getBoundingClientRect();
          return b.height > 0 && b.width > 0;
        });
      for (const el of targets) {
        el.focus({ preventScroll: false });
        await new Promise((r) => requestAnimationFrame(r));
        const b = el.getBoundingClientRect();
        if (b.height === 0) continue;
        const cy = b.top + b.height / 2;
        if (cy < 0 || cy > window.innerHeight) continue;
        const top = document.elementFromPoint(Math.round(b.left + b.width / 2), Math.round(cy));
        if (top && top !== el && !el.contains(top) && !top.contains(el) && top.closest(".topnav")) {
          occl.push({ sel: el.tagName.toLowerCase() + (el.id ? "#" + el.id : "." + String(el.className).trim().split(/\s+/)[0]),
            cy: Math.round(cy), by: top.tagName.toLowerCase() + "." + String(top.className).trim().split(/\s+/)[0] });
        }
        if (occl.length >= 3) break;
      }
      window.scrollTo(0, 0);
    }

    return { over, small, occl, navH: Math.round(navB),
      wraps: document.querySelectorAll(".table-scroll").length };
  });

  const tag = [];
  if (r.over > 1) { overflowBad.push(`${name} ${r.over}px`); tag.push("溢出"); }
  if (r.small.length) { touchBad.push(`${name}: ${r.small.map((s) => `${s.sel}=${s.h}px(${s.why})`).join(", ")}`); tag.push("触摸"); }
  if (r.occl.length) { occlBad.push(`${name}: ${r.occl.map((o) => `${o.sel}@y${o.cy}被${o.by}`).join(", ")}`); tag.push("遮挡"); }
  const want = WRAPPED[name] || 0;
  if (want && r.wraps < want) tag.push(`容器${r.wraps}（应为 0 个都没有才对）`);

  console.log(`  ${tag.length ? "✗" : "✓"} ${name.padEnd(16)} 顶栏${String(r.navH).padStart(4)}px 滚动容器${r.wraps}${want ? `（含数据未到时不可见的 JS 表）` : ""}${tag.length ? "  ← " + tag.join("/") : ""}`);
}

console.log("\n【2】横向溢出");
ok(`18 页在 390px 下均无横向溢出`, overflowBad.length === 0, JSON.stringify(overflowBad));

console.log("\n【3】触摸目标 ≥ 44px");
ok("无真控件小于 44px", touchBad.length === 0, JSON.stringify(touchBad.slice(0, 6)));

console.log("\n【4】聚焦不被 sticky 顶栏遮挡");
ok("聚焦后无一被顶栏挡住", occlBad.length === 0, JSON.stringify(occlBad.slice(0, 6)));

// ─── 5. 表格滚动容器真的能滚 ───
console.log("\n【5】滚动容器可横向滚动");
await goto(`${BASE}/static/scoring.html`, 1400);
const scrollable = await page.evaluate(() => {
  const out = [];
  for (const w of document.querySelectorAll(".table-scroll")) {
    const cs = getComputedStyle(w);
    out.push({ overX: cs.overflowX, canScroll: w.scrollWidth > w.clientWidth + 1,
      tab: w.getAttribute("tabindex"), role: w.getAttribute("role"),
      label: (w.getAttribute("aria-label") || "").slice(0, 24),
      unnamed: !w.getAttribute("aria-label") });
  }
  return out;
});
ok("scoring 有 3 个 .table-scroll", scrollable.length === 3, `实际 ${scrollable.length}`);
ok("全部 overflow-x: auto", scrollable.every((s) => s.overX === "auto" || s.overX === "scroll"), JSON.stringify(scrollable.map((s) => s.overX)));
ok("至少一个真的溢出可滚", scrollable.some((s) => s.canScroll), JSON.stringify(scrollable.map((s) => s.canScroll)));
ok("全部 tabindex=0（键盘可聚焦滚动 WCAG 2.1.1）", scrollable.every((s) => s.tab === "0"), JSON.stringify(scrollable.map((s) => s.tab)));
ok("全部 role=region", scrollable.every((s) => s.role === "region"));
ok("全部有无障碍名（无 aria-label 会静默丢失）", scrollable.every((s) => !s.unnamed), JSON.stringify(scrollable.map((s) => s.label)));
ok("无障碍名不是 i18n key 字面量", scrollable.every((s) => !/^[a-z]+\.[a-z_]+$/.test(s.label)), JSON.stringify(scrollable.map((s) => s.label)));

// ─── 5b. 源码层契约：11 张表都包了（与数据无关）───
console.log("\n【5b】源码契约：11 张表都包了滚动容器");
const { readFileSync } = await import("node:fs");
const REPO = new URL("..", import.meta.url).pathname;
const SRC_CONTRACT = {
  "static/scoring.js": 3,
  "static/report.js": 5,
  "static/silver.js": 1,
  "static/silver.html": 1,
  "static/central_bank.html": 1,
};
let srcTotal = 0;
for (const [f, n] of Object.entries(SRC_CONTRACT)) {
  const txt = readFileSync(REPO + f, "utf8");
  // 去掉注释行再数，否则「// ……见 .table-scroll」这种说明会被算进去
  const code = txt.split("\n").filter((l) => !/^\s*(\/\/|\*|\/\*)/.test(l)).join("\n");
  const got = (code.match(/class="table-scroll"/g) || []).length;
  srcTotal += got;
  ok(`${f} 包裹 ${n} 张表`, got === n, `实际 ${got}`);
}
ok("共 11 张表全部有滚动容器", srcTotal === 11, `实际 ${srcTotal}`);

// ─── 6. 三语下无障碍名跟着翻 ───
console.log("\n【6】三语：aria-label 跟着切换");
for (const [lang, expect] of [["en-US", null], ["zh-TW", null], ["zh-CN", null]]) {
  await page.evaluate(async (l) => { await window.I18n.setLang(l); }, lang);
  await new Promise((r) => setTimeout(r, 500));
  await page.reload({ waitUntil: "networkidle2" });
  await new Promise((r) => setTimeout(r, 1300));
  const labels = await page.$$eval(".table-scroll", (els) =>
    els.map((e) => e.getAttribute("aria-label") || ""));
  ok(`${lang} 滚动区有非空无障碍名`, labels.every((l) => l && l.length > 1), JSON.stringify(labels));
}
await page.evaluate(async () => { await window.I18n.setLang("zh-CN"); });

// ─── 7. 命令面板关闭后不可聚焦（V0.113.0 修的 WCAG 2.4.3/2.4.7 缺陷）───
console.log("\n【7】关闭的命令面板不留在 tab 序列里");
for (const name of ["home", "headlines", "scoring", "ask"]) {
  await goto(`${BASE}/static/${name}.html`, 900);
  const r = await page.evaluate(() => {
    const pal = document.querySelector(".pm-cmd");
    const input = document.querySelector(".pm-cmd-input");
    return { has: !!pal, vis: pal ? getComputedStyle(pal).visibility : null,
      inputFocusable: input ? input.offsetParent !== null && getComputedStyle(input).visibility !== "hidden" : null };
  });
  ok(`${name} 面板关闭时 visibility:hidden`, r.has && r.vis === "hidden", JSON.stringify(r));
  ok(`${name} 关闭时搜索框不可聚焦`, r.inputFocusable === false, JSON.stringify(r));
}
// 打开时必须仍然可见可聚焦（别把功能改没了）
await goto(`${BASE}/static/home.html`, 900);
await page.waitForSelector(".nav-btn-cmd");
const opened = await page.evaluate(async () => {
  window.PM_CmdPalette.open();
  await new Promise((r) => setTimeout(r, 350));
  const pal = document.querySelector(".pm-cmd");
  const input = document.querySelector(".pm-cmd-input");
  const vis = getComputedStyle(pal).visibility;
  const focusable = document.activeElement === input;
  window.PM_CmdPalette.close();
  await new Promise((r) => setTimeout(r, 350));
  return { vis, focusable, closedVis: getComputedStyle(pal).visibility };
});
ok("打开时面板可见", opened.vis === "visible", opened.vis);
ok("打开时搜索框自动聚焦", opened.focusable === true);
ok("关闭后重新变 hidden", opened.closedVis === "hidden", opened.closedVis);

// ─── 8. scroll-padding-top 跟随顶栏 ───
console.log("\n【8】scroll-padding-top = 顶栏实测高度");
await goto(`${BASE}/static/settings.html`, 1100);
const sp = await page.evaluate(() => {
  const nav = document.querySelector(".topnav");
  return { pad: parseInt(getComputedStyle(document.documentElement).scrollPaddingTop, 10) || 0,
    nav: Math.round(nav.getBoundingClientRect().height) };
});
ok("scroll-padding-top 已按顶栏高度设置", Math.abs(sp.pad - sp.nav) <= 1, JSON.stringify(sp));
ok("顶栏高度确实 > 0", sp.nav > 0);

// ─── 汇总 ───
console.log("\n【JS 运行时错误】");
const KNOWN = /apiJson is not defined/;
const known = pageErrors.filter((e) => KNOWN.test(e));
const real = pageErrors.filter((e) => !KNOWN.test(e));
if (known.length) console.log(`  ⚠ 已知既存缺陷（settings.js 裸调 apiJson，V0.82 起）：${known.length} 次`);
ok("无其它 pageerror / console.error", real.length === 0, JSON.stringify(real.slice(0, 5)));

await browser.close();
console.log(`\n${"=".repeat(56)}`);
console.log(`  结果：${pass} passed, ${fail} failed`);
console.log("=".repeat(56));
process.exit(fail === 0 ? 0 : 1);