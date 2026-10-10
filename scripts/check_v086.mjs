#!/usr/bin/env node
// V0.86.0 决策可解释性 · 拆解 + 对比 + hover tooltip 验证
// 断言：
//   1) portfolio.html：#decisionArea 含 .de-action badge + .de-compare 卡 + .de-breakdown 拆解
//   2) trend.html：#synthesisCard 含 .de-action + .de-compare + .de-breakdown
//   3) i18n 翻译正确（zh-CN "综合指数拆解" / zh-TW "綜合指數拆解" / en-US "Index Breakdown"）
//   4) hover .de-action 后弹出 .de-tip tooltip（且文本非空）
import puppeteer from "puppeteer-core";
import { mkdirSync } from "node:fs";

const BASE = "http://127.0.0.1:8888";
const CHROME = "/home/surui/.cache/puppeteer/chrome/linux-153.0.8010.36/chrome-linux64/chrome";

const PAGES = [
  { name: "portfolio", url: "/static/portfolio.html" },
  { name: "trend",     url: "/static/trend.html" },
];

const LANGS = ["zh-CN", "zh-TW", "en-US"];

const I18N_EXPECT = {
  "zh-CN": { breakdown: "综合指数拆解", compare: "按当前建议仓位" },
  "zh-TW": { breakdown: "綜合指數拆解", compare: "按當前建議倉位" },
  "en-US": { breakdown: "Index Breakdown", compare: "Per Current Recommendation" },
};

mkdirSync("/tmp/v086-verify", { recursive: true });

const browser = await puppeteer.launch({
  executablePath: CHROME,
  headless: "new",
  args: ["--no-sandbox", "--disable-setuid-sandbox"],
});

let pass = 0, fail = 0;
const fails = [];

async function checkOne(pageCfg, lang) {
  const page = await browser.newPage();
  await page.evaluateOnNewDocument((l) => { try { localStorage.setItem("pm_lang", l); } catch(e){} }, lang);
  const url = `${BASE}${pageCfg.url}`;
  let result;
  try {
    await page.goto(url, { waitUntil: "domcontentloaded", timeout: 30000 });
    // 等待 decision API + explainer 渲染完成
    await new Promise(r => setTimeout(r, 4000));

    result = await page.evaluate((pageName) => {
      const out = { ok: true, errors: [], bodyLang: document.body.getAttribute("data-lang") };
      // 1) de-action badge 存在
      const actionEl = document.querySelector(pageName === "portfolio" ? "#decisionArea .de-action" : "#synthesisCard .de-action");
      if (!actionEl) {
        out.errors.push(`missing .de-action in ${pageName}`);
        return out;
      }
      out.actionText = actionEl.textContent.trim();
      out.actionDataKey = actionEl.getAttribute("data-de-action");

      // 2) compare 卡存在
      const compareEl = document.querySelector(pageName === "portfolio" ? "#decisionArea .de-compare" : "#synthesisCard .de-compare");
      if (!compareEl) out.errors.push(`missing .de-compare in ${pageName}`);
      else out.compareText = compareEl.textContent.replace(/\s+/g, " ").trim().slice(0, 80);

      // 3) breakdown 拆解区存在
      const bdEl = document.querySelector(pageName === "portfolio" ? "#decisionArea .de-breakdown" : "#synthesisCard .de-breakdown");
      if (!bdEl) out.errors.push(`missing .de-breakdown in ${pageName}`);
      else {
        out.breakdownRows = bdEl.querySelectorAll(".de-row").length;
        out.hasFormula = !!bdEl.querySelector(".de-formula");
      }

      // 4) PM_DecisionExplainer 存在
      out.hasExplainer = !!window.PM_DecisionExplainer;

      return out;
    }, pageCfg.name);

    if (result.errors.length) {
      for (const e of result.errors) fails.push(`[${pageCfg.name}/${lang}] ${e}`);
      fail += result.errors.length;
      console.log(`✗ ${pageCfg.name}/${lang}: ${result.errors.length} error(s)`);
      result.errors.forEach(e => console.log(`    - ${e}`));
    } else {
      pass += 3;
      console.log(`✓ ${pageCfg.name}/${lang}: action="${result.actionText}" data="${result.actionDataKey}" rows=${result.breakdownRows} formula=${result.hasFormula}`);
    }

    // 5) i18n 翻译断言（直接比对 compare/breakdown 标题）
    const expected = I18N_EXPECT[lang];
    const i18nCheck = await page.evaluate((expected) => {
      const bd = document.querySelector(".de-bd-head");
      const cmp = document.querySelector(".de-cmp-k");
      return {
        bdText: bd ? bd.textContent.trim() : null,
        cmpText: cmp ? cmp.textContent.trim() : null
      };
    });
    if (i18nCheck.bdText && !i18nCheck.bdText.includes(expected.breakdown)) {
      fails.push(`[${pageCfg.name}/${lang}] breakdown title "${i18nCheck.bdText}" missing "${expected.breakdown}"`);
      fail++;
      console.log(`  ✗ i18n breakdown: "${i18nCheck.bdText}"`);
    } else if (i18nCheck.bdText) {
      pass++;
      console.log(`  ✓ i18n breakdown: "${i18nCheck.bdText}"`);
    }
    if (i18nCheck.cmpText && !i18nCheck.cmpText.includes(expected.compare)) {
      fails.push(`[${pageCfg.name}/${lang}] compare title "${i18nCheck.cmpText}" missing "${expected.compare}"`);
      fail++;
      console.log(`  ✗ i18n compare: "${i18nCheck.cmpText}"`);
    } else if (i18nCheck.cmpText) {
      pass++;
      console.log(`  ✓ i18n compare: "${i18nCheck.cmpText}"`);
    }

    // 6) hover .de-action 后弹出 tooltip
    const actionHandle = await page.$(pageCfg.name === "portfolio" ? "#decisionArea .de-action" : "#synthesisCard .de-action");
    if (actionHandle) {
      const box = await actionHandle.boundingBox();
      if (box) {
        await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
        await new Promise(r => setTimeout(r, 800));
        const tipInfo = await page.evaluate(() => {
          const tips = document.querySelectorAll(".de-tip");
          if (!tips.length) return { found: false };
          const tip = tips[tips.length - 1];
          const visible = tip.style.display !== "none" && getComputedStyle(tip).display !== "none";
          return {
            found: true,
            visible: visible,
            text: tip.textContent.replace(/\s+/g, " ").trim().slice(0, 100),
            rowCount: tip.querySelectorAll(".de-tip-row").length
          };
        });
        if (tipInfo.found && tipInfo.visible && tipInfo.rowCount > 0) {
          pass++;
          console.log(`  ✓ tooltip: ${tipInfo.rowCount} rows "${tipInfo.text.slice(0, 50)}..."`);
        } else {
          fails.push(`[${pageCfg.name}/${lang}] tooltip not visible: found=${tipInfo.found} visible=${tipInfo.visible} rows=${tipInfo.rowCount || 0}`);
          fail++;
          console.log(`  ✗ tooltip: found=${tipInfo.found} visible=${tipInfo.visible} rows=${tipInfo.rowCount || 0}`);
        }
        await page.screenshot({ path: `/tmp/v086-verify/${pageCfg.name}-${lang}-hover.png`, fullPage: false });
      }
    }
  } catch (e) {
    fails.push(`[${pageCfg.name}/${lang}] exception: ${e.message}`);
    fail++;
    console.log(`✗ ${pageCfg.name}/${lang}: exception ${e.message}`);
  } finally {
    await page.close();
  }
}

for (const p of PAGES) {
  for (const l of LANGS) {
    await checkOne(p, l);
  }
}

await browser.close();

console.log(`\n结果：${pass} passed / ${fail} failed`);
if (fail) {
  console.log("Failures:");
  fails.forEach(f => console.log(`  ${f}`));
  process.exit(1);
}