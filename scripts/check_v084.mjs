#!/usr/bin/env node
// V0.84.0 状态条方案 C 验证：9 页 × 3 语 = 27 组合
// 断言：statusPanel 存在 + summary 1 行 + 计数 pill + 时效 mount + dismiss 行为
import puppeteer from "puppeteer-core";
import { mkdirSync, writeFileSync } from "node:fs";

const BASE = "http://127.0.0.1:8888";
const CHROME = "/home/surui/.cache/puppeteer/chrome/linux-153.0.8010.36/chrome-linux64/chrome";

const PAGES = [
  { name: "trend",       url: "/static/trend.html",       expectedCount: 5 },
  { name: "silver",      url: "/static/silver.html",      expectedCount: 5 },
  { name: "portfolio",   url: "/static/portfolio.html",   expectedCount: 5 },
  { name: "weights",     url: "/static/weights.html",     expectedCount: 5 },
  { name: "trades",      url: "/static/trades.html",      expectedCount: 5 },
  { name: "backtest",    url: "/static/backtest.html",    expectedCount: 5 },
  { name: "data-health", url: "/static/data-health.html", expectedCount: 3 },
  { name: "central_bank",url: "/static/central_bank.html",expectedCount: 4 },
  { name: "review",      url: "/static/review.html",      expectedCount: 5 },
];

const LANGS = ["zh-CN", "zh-TW", "en-US"];

mkdirSync("/tmp/v084-verify", { recursive: true });

const browser = await puppeteer.launch({
  executablePath: CHROME,
  headless: "new",
  args: ["--no-sandbox", "--disable-setuid-sandbox"],
});

let pass = 0, fail = 0;
const fails = [];

async function checkOne(pageCfg, lang) {
  const page = await browser.newPage();
  // 关键：必须在文档加载前 setItem，i18n.js init() 读 localStorage
  await page.evaluateOnNewDocument((l) => { try { localStorage.setItem("pm_lang", l); } catch(e){} }, lang);
  const url = `${BASE}${pageCfg.url}`;
  try {
    await page.goto(url, { waitUntil: "domcontentloaded", timeout: 30000 });
    // 等待 i18n.js + warning.js 跑完
    await new Promise(r => setTimeout(r, 1000));

    const result = await page.evaluate((expectedCount) => {
      const out = { ok: true, errors: [], bodyLang: document.body.getAttribute("data-lang") };

      // Debug: check if i18n keys exist
      const labelEl = document.querySelector("[data-i18n='status.warn_pill_label']");
      if (labelEl) {
        out.labelText = labelEl.textContent;
        out.labelKey = labelEl.getAttribute("data-i18n");
      }
      const unitEl = document.querySelector("[data-i18n='status.warn_pill_unit']");
      if (unitEl) {
        out.unitText = unitEl.textContent;
      }
      // Check if I18n global is available
      out.hasI18n = !!(window.I18n);
      if (window.I18n) {
        out.i18nLang = window.I18n.lang;
        out.i18nT = window.I18n.t("status.warn_pill_label");
        out.i18nTUnit = window.I18n.t("status.warn_pill_unit");
      }

      // 1) statusPanel 存在
      const panel = document.getElementById("statusPanel");
      if (!panel) { out.ok = false; out.errors.push("statusPanel 缺失"); return out; }

      // 2) warnFooter 不应再存在
      const oldFooter = document.getElementById("warnFooter");
      if (oldFooter) { out.ok = false; out.errors.push("warnFooter 仍残留"); }

      // 3) topnav-meta 不应存在（class 选择器为空）
      const oldMeta = document.querySelector(".topnav .topnav-meta");
      if (oldMeta) { out.ok = false; out.errors.push("topnav-meta 仍残留"); }

      // 4) summary 包含 #freshnessInline
      const fresh = panel.querySelector("#freshnessInline");
      if (!fresh) { out.ok = false; out.errors.push("summary 内 #freshnessInline 缺失"); }

      // 5) summary 包含 status-warn-pill + data-warn-count
      const pill = panel.querySelector(".status-warn-pill");
      if (!pill) { out.ok = false; out.errors.push(".status-warn-pill 缺失"); }
      const countEl = panel.querySelector("[data-warn-count]");
      if (!countEl) { out.ok = false; out.errors.push("[data-warn-count] 缺失"); }
      else {
        const n = parseInt(countEl.textContent.trim(), 10);
        if (n !== expectedCount) { out.ok = false; out.errors.push(`count=${n} 期望 ${expectedCount}`); }
      }

      // 6) body 包含 warn-list + 5 li + dismiss
      const list = panel.querySelector(".warn-list");
      if (!list) { out.ok = false; out.errors.push(".warn-list 缺失"); }
      else {
        const li = list.querySelectorAll("li").length;
        if (li !== expectedCount) { out.ok = false; out.errors.push(`li=${li} 期望 ${expectedCount}`); }
      }
      const dismiss = panel.querySelector("[data-warn-dismiss]");
      if (!dismiss) { out.ok = false; out.errors.push("[data-warn-dismiss] 缺失"); }

      // 7) aria-describedby 已绑定
      if (dismiss && dismiss.getAttribute("aria-describedby") !== "warnDismissHint") {
        out.ok = false; out.errors.push("aria-describedby 未绑");
      }

      // 8) 默认折叠态（无 open attr）
      if (panel.hasAttribute("open")) {
        out.ok = false; out.errors.push("默认应折叠但带 open attr");
      }

      // 9) topnav 1 行（无 .topnav-row 之外的 .topnav 子元素）
      const navRows = document.querySelectorAll(".topnav .topnav-row");
      if (navRows.length !== 1) { out.ok = false; out.errors.push(`topnav 1 行校验失败 rows=${navRows.length}`); }

      // 10) 抓 pill 显示文本（i18n 后）
      if (pill) {
        out.pillText = pill.textContent.replace(/\s+/g, " ").trim();
      }
      if (countEl) {
        out.countText = countEl.textContent.trim();
      }
      return out;
    }, pageCfg.expectedCount);

    if (!result.ok) {
      fail++;
      fails.push({ page: pageCfg.name, lang, errors: result.errors });
      console.log(`✗ ${pageCfg.name} [${lang}] (data-lang=${result.bodyLang}): ${result.errors.join("; ")}`);
    } else {
      pass++;
      console.log(`✓ ${pageCfg.name} [${lang}] (data-lang=${result.bodyLang}) label="${result.labelText}" unit="${result.unitText}" i18nLang=${result.i18nLang} i18n.t(label)="${result.i18nT}" i18n.t(unit)="${result.i18nTUnit}"`);
    }

    // 截图
    const shotPath = `/tmp/v084-verify/${pageCfg.name}_${lang}.png`;
    await page.screenshot({ path: shotPath, fullPage: false });
  } catch (e) {
    fail++;
    fails.push({ page: pageCfg.name, lang, errors: ["EXCEPTION: " + e.message] });
    console.log(`✗ ${pageCfg.name} [${lang}]: EXCEPTION ${e.message}`);
  } finally {
    await page.close();
  }
}

console.log("V0.84.0 状态条方案 C 验证（9 页 × 3 语）\n");
for (const page of PAGES) {
  for (const lang of LANGS) {
    await checkOne(page, lang);
  }
}

await browser.close();

console.log(`\n========================================`);
console.log(`PASS: ${pass} / ${pass + fail}`);
if (fail > 0) {
  console.log(`FAIL: ${fail}`);
  console.log(JSON.stringify(fails, null, 2));
  process.exit(1);
}
console.log("All checks green.");
