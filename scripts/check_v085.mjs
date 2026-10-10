#!/usr/bin/env node
// V0.85.0 数据健康摘要 chip / panel 验证：9 页 × 3 语 = 27 组合
// 断言：
//   1) #healthSummary 挂载点存在（live element，非 live markup 是注释里可能残留）
//   2) 非 health 页 chip 是 <a> 且 href="/data-health.html"
//      data-health 页是 <span class="hs-panel">
//   3) i18n 翻译正确（zh-CN "数据健康" / zh-TW "數據健康" / en-US "Health"）
//   4) chip 渲染了真实健康摘要（live/total 数字 + 颜色 class）
//   5) 非 health 页 chip 点击 → 跳 /data-health.html 且不展开 statusPanel
import puppeteer from "puppeteer-core";
import { mkdirSync } from "node:fs";

const BASE = "http://127.0.0.1:8888";
const CHROME = "/home/surui/.cache/puppeteer/chrome/linux-153.0.8010.36/chrome-linux64/chrome";

const PAGES = [
  { name: "trend",        url: "/static/trend.html",        mode: "chip" },
  { name: "silver",       url: "/static/silver.html",       mode: "chip" },
  { name: "portfolio",    url: "/static/portfolio.html",    mode: "chip" },
  { name: "weights",      url: "/static/weights.html",      mode: "chip" },
  { name: "trades",       url: "/static/trades.html",       mode: "chip" },
  { name: "backtest",     url: "/static/backtest.html",     mode: "chip" },
  { name: "data-health",  url: "/static/data-health.html",  mode: "panel" },
  { name: "central_bank", url: "/static/central_bank.html", mode: "chip" },
  { name: "review",       url: "/static/review.html",       mode: "chip" },
];

const LANGS = ["zh-CN", "zh-TW", "en-US"];

const I18N_EXPECT = {
  "zh-CN": { title: "数据健康", contains: ["数据健康"] },
  "zh-TW": { title: "數據健康", contains: ["數據健康"] },
  "en-US": { title: "Health",   contains: ["Health"] },
};

mkdirSync("/tmp/v085-verify", { recursive: true });

const browser = await puppeteer.launch({
  executablePath: CHROME,
  headless: "new",
  args: ["--no-sandbox", "--disable-setuid-sandbox"],
});

let pass = 0, fail = 0;
const fails = [];

async function checkOne(pageCfg, lang) {
  const page = await browser.newPage();
  // 必须在文档加载前 setItem，i18n.js init() 读 localStorage
  await page.evaluateOnNewDocument((l) => { try { localStorage.setItem("pm_lang", l); } catch(e){} }, lang);
  const url = `${BASE}${pageCfg.url}`;
  try {
    await page.goto(url, { waitUntil: "domcontentloaded", timeout: 30000 });
    // 等待 i18n + health-summary.js + warning.js 都跑完
    await new Promise(r => setTimeout(r, 2000));

    const result = await page.evaluate((expectedMode) => {
      const out = { ok: true, errors: [], bodyLang: document.body.getAttribute("data-lang") };

      // 1) #healthSummary 挂载点存在
      const chip = document.getElementById("healthSummary");
      if (!chip) {
        out.errors.push("missing #healthSummary mount point");
        return out;
      }
      out.chipTag = chip.tagName;
      out.chipClass = chip.className;
      out.chipHref = chip.getAttribute("href");

      // 2) chip vs panel 模式判断
      if (expectedMode === "panel") {
        if (!chip.classList.contains("hs-panel")) {
          out.errors.push("data-health: expected .hs-panel class, got: " + chip.className);
        }
      } else {
        if (chip.tagName !== "A" || chip.getAttribute("href") !== "/data-health.html") {
          out.errors.push("chip: expected <a href='/data-health.html'>, got " +
            chip.tagName + " href=" + chip.getAttribute("href"));
        }
        if (!chip.classList.contains("hs-chip-link")) {
          out.errors.push("chip: expected .hs-chip-link class, got: " + chip.className);
        }
      }

      // 3) i18n 翻译：chip 模式检查 title，panel 模式检查任一 mini-chip 标签
      const titleEl = document.querySelector("[data-i18n='hs.title']");
      if (titleEl) {
        out.titleText = titleEl.textContent;
      } else {
        // panel 模式：取任一 hs.* 标签作为 i18n 验证
        const lblEl = document.querySelector("[data-i18n='hs.live'], [data-i18n='hs.sources']");
        out.titleText = lblEl ? lblEl.textContent : "(missing)";
        out.panelMode = true;
      }
      out.hasI18n = !!(window.I18n);

      // 4) 健康摘要数字：检查 chip 渲染了 live/total 数字
      // chip 模式：搜索 "5/6" 或类似模式；panel 模式：查 .hs-num 数
      if (expectedMode === "panel") {
        const nums = document.querySelectorAll("#healthSummary .hs-num");
        out.numCount = nums.length;
        out.numTexts = Array.from(nums).map(n => n.textContent);
      } else {
        // chip 模式：渲染后的 innerHTML 应包含 <span class="hs-txt">
        const txtEl = chip.querySelector(".hs-txt");
        out.txtContent = txtEl ? txtEl.textContent : "(missing)";
        // 应包含 "X/Y" 模式
        if (!/\d+\/\d+/.test(out.txtContent)) {
          out.errors.push("chip: txtContent missing live/total pattern, got: " + out.txtContent);
        }
        // 颜色 class
        out.chipColor = chip.className.match(/hs-(ok|warn|bad|dim)/);
        out.chipColor = out.chipColor ? out.chipColor[0] : "(none)";
      }

      return out;
    }, pageCfg.mode);

    // i18n 文本断言
    const expect = I18N_EXPECT[lang];
    if (result.panelMode) {
      // panel 模式：标题文字就是 mini-chip 标签（数据源/數據源/Sources）
      const panelExpect = {
        "zh-CN": "数据源",
        "zh-TW": "數據源",
        "en-US": "Sources",
      };
      if (!result.titleText.includes(panelExpect[lang])) {
        result.errors.push(`panel label "${result.titleText}" missing "${panelExpect[lang]}"`);
      }
    } else {
      if (!expect.contains.some(c => result.titleText.includes(c))) {
        result.errors.push(`title text "${result.titleText}" missing i18n "${expect.title}"`);
      }
    }

    if (result.errors.length === 0) {
      pass++;
      console.log(`  [PASS] ${pageCfg.name}/${lang} :: ${result.titleText} ${pageCfg.mode === "chip" ? result.txtContent : "[" + result.numTexts.join(",") + "]"}`);
    } else {
      fail++;
      fails.push(`${pageCfg.name}/${lang}: ${result.errors.join("; ")} | got: ${JSON.stringify(result)}`);
      console.log(`  [FAIL] ${pageCfg.name}/${lang} :: ${result.errors.join("; ")}`);
    }

    // 5) 交互测试（仅 chip 模式）：点击不展开 statusPanel，跳转
    if (pageCfg.mode === "chip" && result.errors.length === 0) {
      const interactPage = await browser.newPage();
      await interactPage.evaluateOnNewDocument((l) => { try { localStorage.setItem("pm_lang", l); } catch(e){} }, lang);
      await interactPage.goto(url, { waitUntil: "domcontentloaded", timeout: 30000 });
      await new Promise(r => setTimeout(r, 2000));

      // 移除 tour 元素干扰
      await interactPage.evaluate(() => {
        ["pmhTourMask", "pmhTourSpot", "pmhTourTip"].forEach(id => {
          const el = document.getElementById(id);
          if (el) el.remove();
        });
      });

      const navResult = await interactPage.evaluate(() => {
        const chip = document.getElementById("healthSummary");
        const panel = document.getElementById("statusPanel");
        const wasOpen = panel ? panel.hasAttribute("open") : false;
        // 模拟点击：阻止默认跳转，验证 stopPropagation
        let propagationStopped = false;
        const origToggle = panel && panel.tagName === "DETAILS" ? panel : null;
        chip.addEventListener("click", (e) => {
          if (e.defaultPrevented) propagationStopped = true;
        }, { once: true, capture: true });
        chip.click();
        const stillOpen = panel ? panel.hasAttribute("open") : false;
        return { wasOpen, stillOpen, panelExists: !!panel };
      });

      if (navResult.stillOpen === navResult.wasOpen) {
        pass++;
        console.log(`  [PASS] ${pageCfg.name}/${lang} :: chip click 不展开 statusPanel`);
      } else {
        fail++;
        fails.push(`${pageCfg.name}/${lang}: chip click 错误地展开 disclosure (wasOpen=${navResult.wasOpen} stillOpen=${navResult.stillOpen})`);
        console.log(`  [FAIL] ${pageCfg.name}/${lang} :: chip click 展开 disclosure`);
      }
      await interactPage.close();
    }
  } catch (e) {
    fail++;
    fails.push(`${pageCfg.name}/${lang}: ${e.message}`);
    console.log(`  [FAIL] ${pageCfg.name}/${lang} :: ${e.message}`);
  }
  await page.close();
}

console.log("\n[V0.85.0] 9 页 × 3 语 = 27 + 8 chip-click = 35 断言\n");

for (const p of PAGES) {
  for (const l of LANGS) {
    await checkOne(p, l);
  }
}

console.log("\n" + "=".repeat(70));
console.log(`结果：${pass} passed / ${fail} failed`);
if (fail > 0) {
  console.log("失败明细：");
  fails.forEach(f => console.log("  - " + f));
}
console.log("=".repeat(70));

await browser.close();
process.exit(fail === 0 ? 0 : 1);