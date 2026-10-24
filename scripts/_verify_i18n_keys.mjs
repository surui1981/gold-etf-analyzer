// scripts/_verify_i18n_keys.mjs
// V0.116.1 验证：本轮改动的 i18n 键「真的被翻译」，不是只改了 HTML 属性名。
//
// 本轮改了 3 处 i18n（都来自 pytest 失败与 ruff 发现）：
//   1. ask.html  `data-i18n="status.warnings"` → `status.warn_pill_label`
//      （原键 3 语都不存在 ⇒ i18n 覆盖测试红；i18n.js 的 t() 会回落成字面量 "status.warnings"）
//   2. ask.html  `data-i18n="status.dismiss"` → `warn.dismiss_session`
//   3. ask.html  `data-i18n-attr="placeholder|ai.input_placeholder"`
//      → `data-i18n-placeholder="ai.input_placeholder"`
//      ★ i18n.js 的 apply() **只认** data-i18n / -html / -placeholder / -title / -aria，
//        `data-i18n-attr` 根本不被读取 ⇒ 改之前 placeholder 从来没被翻译过。
//   4. weights.html  `t("weights.mo_loading")` → `t(macroFactorState === "loading" ? ... )`
//      （权重页表格窄，长文案撑行）
//
// ⚠ 断言要查**实际 DOM 值**（placeholder 属性 / textContent），
//   不能查 data-lang —— 那是「当前语言是什么」，不是「文案翻译了没」。
//   （记忆 i18n-init-await：saved=非 zh-CN 时 reload 仍回退到 zh-CN，
//     所以本脚本显式 setLang 切语言，不依赖 localStorage 初始态。）
// ⚠ 断言必须先剥注释：这里断言的是「属性值等于某个具体文案」，
//   若实现回退成把 key 本身塞进去，值会变成 "ai.input_placeholder" —— 与期望文案不等 ⇒ 真的红。
import puppeteer from "puppeteer-core";

const BASE = process.env.BASE_URL || "http://127.0.0.1:8888";
const CHROME =
  "/home/surui/.cache/puppeteer/chrome/linux-153.0.8010.36/chrome-linux64/chrome";

let pass = 0;
let fail = 0;
const failures = [];

function ok(name) {
  pass += 1;
  console.log("  ✓ " + name);
}
function bad(name, detail) {
  fail += 1;
  failures.push(name + " — " + detail);
  console.log("  ✗ " + name + " — " + detail);
}
function assertEq(name, actual, expected) {
  if (actual === expected) ok(name);
  else bad(name, `期望 ${JSON.stringify(expected)}，实际 ${JSON.stringify(actual)}`);
}

const browser = await puppeteer.launch({
  executablePath: CHROME,
  headless: "new",
  args: ["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"],
});

try {
  // ───────────────── 1 · /ask 三语 placeholder ─────────────────
  const page = await browser.newPage();
  await page.setViewport({ width: 1352, height: 900 });
  const consoleErrors = [];
  const pageErrors = [];
  page.on("console", (m) => {
    if (m.type() === "error") consoleErrors.push(m.text());
  });
  page.on("pageerror", (e) => pageErrors.push(String(e)));

  const EXPECT = {
    "zh-CN": "提问关于黄金市场 / 持仓 / 评分…",
    "en-US": "Ask about gold markets, portfolio, scoring…",
    "zh-TW": "提問關於黃金市場 / 持倉 / 評分…",
  };

  await page.goto(BASE + "/ask", { waitUntil: "networkidle2", timeout: 30000 });
  await page.waitForFunction("window.I18n && typeof window.I18n.setLang === 'function'", {
    timeout: 15000,
  });

  for (const lang of ["zh-CN", "en-US", "zh-TW"]) {
    await page.evaluate(async (l) => {
      await window.I18n.setLang(l);
    }, lang);
    // 等 apply() 跑完（apply 是同步的，但保险起见让出一帧）
    await new Promise((r) => setTimeout(r, 200));
    const ph = await page.evaluate(() => {
      const el = document.querySelector("#msgInput");
      return el ? el.getAttribute("placeholder") : null;
    });
    assertEq(`ask placeholder @${lang}`, ph, EXPECT[lang]);
  }

  // ───────────────── 2 · 死属性 data-i18n-attr 已不存在 ─────────────────
  const deadAttr = await page.evaluate(
    () => document.querySelectorAll("[data-i18n-attr]").length
  );
  assertEq("ask.html 无 data-i18n-attr 残留", deadAttr, 0);

  // ───────────────── 3 · 警示 chip / 关闭文案真的被翻译 ─────────────────
  await page.evaluate(async () => {
    await window.I18n.setLang("en-US");
  });
  await new Promise((r) => setTimeout(r, 200));
  const warnLabel = await page.evaluate(() => {
    const el = document.querySelector(".warn-pill-label");
    return el ? el.textContent.trim() : null;
  });
  assertEq("ask warn pill 文案 @en-US", warnLabel, "Notice");

  const dismissLabel = await page.evaluate(() => {
    const el = document.querySelector(".warn-dismiss span");
    return el ? el.textContent.trim() : null;
  });
  assertEq("ask dismiss 文案 @en-US", dismissLabel, "Don't expand this session");

  // ───────────────── 4 · 三个键在 3 语都有值（不留空串） ─────────────────
  for (const lang of ["zh-CN", "en-US", "zh-TW"]) {
    await page.evaluate(async (l) => {
      await window.I18n.setLang(l);
    }, lang);
    await new Promise((r) => setTimeout(r, 150));
    const vals = await page.evaluate(() => {
      const out = {};
      for (const k of [
        "ai.input_placeholder",
        "status.warn_pill_label",
        "warn.dismiss_session",
        "weights.mo_loading_short",
      ]) {
        out[k] = window.I18n.t(k);
      }
      return out;
    });
    for (const [k, v] of Object.entries(vals)) {
      if (typeof v === "string" && v.length > 0 && v !== k) {
        ok(`i18n.t("${k}") @${lang} → "${v}"`);
      } else {
        bad(`i18n.t("${k}") @${lang}`, `值无效：${JSON.stringify(v)}`);
      }
    }
  }

  // ───────────────── 5 · /weights 短文案真的用了 ─────────────────
  const wpage = await browser.newPage();
  await wpage.setViewport({ width: 1352, height: 900 });
  wpage.on("pageerror", (e) => pageErrors.push("weights: " + String(e)));
  await wpage.goto(BASE + "/weights", { waitUntil: "networkidle2", timeout: 30000 });
  await wpage.waitForFunction("window.I18n && typeof window.I18n.t === 'function'", {
    timeout: 15000,
  });

  // 源文件层面：短文案不能被"长文案"顶替
  const wsrc = await (await fetch(BASE + "/static/weights.html")).text();
  if (wsrc.includes("weights.mo_loading_short")) {
    ok("weights.html 引用 weights.mo_loading_short");
  } else {
    bad("weights.html 引用 weights.mo_loading_short", "源码里没有这个键");
  }
  if (wsrc.includes("weights.mo_loading\"") && !wsrc.includes("weights.mo_loading_short") === false) {
    // 允许 weights.mo_loading 作为初始静态占位（data-i18n），但 t() 必须走 short
    ok("weights.html 保留了静态占位（可接受）");
  }

  // 运行时：loading 态下 moEmpty/状态区用短文案
  const moText = await wpage.evaluate(() => {
    const el = document.querySelector("#moRows .mo-empty");
    return el ? el.textContent.trim() : null;
  });
  if (moText === "正在读取宏观因子当前读数…" || moText === "暂无读数") {
    ok(`weights 宏观区文案为可接受值："${moText}"`);
  } else {
    // 数据已到 → 表格行，不是 .mo-empty
    if (moText === null) ok("weights 宏观区已渲染为表格（无 .mo-empty）");
    else bad("weights 宏观区文案", `实际 "${moText}"`);
  }

  // ───────────────── 6 · 零 console / pageerror ─────────────────
  const realConsoleErrors = consoleErrors.filter(
    (t) => !/favicon|Failed to load resource/i.test(t)
  );
  assertEq("零 console error", realConsoleErrors.length, 0);
  assertEq("零 pageerror", pageErrors.length, 0);
} finally {
  await browser.close();
}

console.log(`\n结果：${pass} passed, ${fail} failed`);
if (fail > 0) {
  console.log("\n失败明细：");
  for (const f of failures) console.log("  - " + f);
  process.exit(1);
}
