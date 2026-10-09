// V0.83 C4 · 端到端 puppeteer 验证
// 8 页面 × 3 语 × 3 主题 = 72 组合 · 含 #warn 深链 / HC 模式对比度 / 跨页一致性
// 参考 MEMORY `frontend-undefined-rendering.md` —— 模板字符串 `${x.prop}` 字段名不一致会
// 静默渲染 undefined；本脚本用真实 Chromium 跑出实际 DOM 后再断言
//
// 依赖：puppeteer-core + 系统 Chromium
//   cd /tmp && npm init -y && npm install puppeteer-core
//   node /path/to/scripts/puppeteer_v083.mjs
import puppeteer from "puppeteer-core";
import fs from "node:fs";
import path from "node:path";

const PAGES = [
  { path: "/static/silver.html",        activeNav: "白银追踪",    expectBullets: 5, genericBullet: false },
  { path: "/static/portfolio.html",     activeNav: "持仓与决策", expectBullets: 5, genericBullet: true },
  { path: "/static/weights.html",       activeNav: "权重配置",   expectBullets: 5, genericBullet: true },
  { path: "/static/trades.html",        activeNav: "交易历史",   expectBullets: 5, genericBullet: true },
  { path: "/static/backtest.html",      activeNav: "参数回测",   expectBullets: 5, genericBullet: false },
  { path: "/static/data-health.html",   activeNav: "数据健康",   expectBullets: 3, genericBullet: false },
  { path: "/static/central_bank.html",  activeNav: "央行购金统计", expectBullets: 4, genericBullet: false },
  { path: "/static/review.html",        activeNav: "研判复盘",   expectBullets: 5, genericBullet: true },
];

const LANGS = ["zh-CN", "zh-TW", "en-US"];
const THEMES = ["light", "dark", "hc"];

let pass = 0, fail = 0;
const results = [];
function assert(name, cond, detail = "") {
  if (cond) { pass++; results.push(`  [OK]   ${name}`); }
  else { fail++; results.push(`  [FAIL] ${name}${detail ? "  ::  " + detail : ""}`); }
}

const browser = await puppeteer.launch({
  executablePath: "/home/surui/.cache/puppeteer/chrome/linux-153.0.8010.36/chrome-linux64/chrome",
  args: ["--no-sandbox", "--disable-setuid-sandbox"],
  headless: "new",
});

// 跨页通用 5 条 bullet 文本快照（zh-CN 下采集）
const bulletSnapshot = {};

for (const page of PAGES) {
  for (const lang of LANGS) {
    for (const theme of THEMES) {
      const tab = `[${page.path} | ${lang} | ${theme}]`;
      await new Promise((r) => setTimeout(r, 3500)); // 限流保护（dev server 5 req/s）
      const p = await browser.newPage();

      // 屏蔽 21s 限流的 API + 后端图表
      await p.setRequestInterception(true);
      p.on("request", (req) => {
        const u = req.url();
        if (u.includes("/api/v1/market/freshness") || u.includes("/api/v1/backtest/")) {
          return req.respond({ status: 200, contentType: "application/json", body: '{"markets":[],"degraded":true}' });
        }
        req.continue();
      });

      await p.evaluateOnNewDocument(({ lang, theme }) => {
        try { localStorage.setItem("pm_lang", lang); localStorage.setItem("pm_theme_mode", theme); } catch (e) {}
      }, { lang, theme });

      try {
        // 429 retry
        let pageOk = false, lastErr;
        for (let attempt = 0; attempt < 4; attempt++) {
          try {
            const resp = await p.goto("http://127.0.0.1:8888" + page.path, { waitUntil: "domcontentloaded", timeout: 15000 });
            if (resp && resp.status() === 429) {
              lastErr = new Error("HTTP 429");
              await new Promise((r) => setTimeout(r, 4000));
              continue;
            }
            if (resp && resp.status() >= 500) {
              lastErr = new Error("HTTP " + resp.status());
              await new Promise((r) => setTimeout(r, 3000));
              continue;
            }
            pageOk = true;
            break;
          } catch (e) {
            lastErr = e;
            await new Promise((r) => setTimeout(r, 3000));
          }
        }
        if (!pageOk) throw lastErr || new Error("page failed");
        await new Promise((r) => setTimeout(r, 600));

        // A. 顶 nav 双行
        const nav = await p.evaluate(() => {
          const n = document.querySelector("nav.topnav");
          if (!n) return null;
          const brand = n.querySelector(".brand");
          const links = n.querySelectorAll(".topnav-row .links > a");
          const active = n.querySelector(".topnav-row .links > a.active");
          return {
            brandText: brand?.textContent.trim() || "",
            linkCount: links.length,
            activeText: active?.textContent.trim() || "",
            topnavMeta: !!n.querySelector(".topnav-meta"),
          };
        });
        assert(`${tab} topnav 存在`, !!nav);
        assert(`${tab} 含 .topnav-meta`, nav?.topnavMeta);
        assert(`${tab} brand 文本非空`, (nav?.brandText?.length || 0) > 0, `actual="${nav?.brandText}"`);
        assert(`${tab} 11 链接`, nav?.linkCount === 11, `actual=${nav?.linkCount}`);
        assert(`${tab} 当前页 active 匹配`, nav?.activeText.includes(page.activeNav), `expected "${page.activeNav}" got "${nav?.activeText}"`);

        // B. #freshnessInline 挂载点
        const fresh = await p.evaluate(() => {
          const el = document.getElementById("freshnessInline");
          return el ? { ariaLive: el.getAttribute("aria-live"), exists: true } : { exists: false };
        });
        assert(`${tab} #freshnessInline 存在`, fresh.exists);
        assert(`${tab} #freshnessInline aria-live=polite`, fresh.ariaLive === "polite", `actual=${fresh.ariaLive}`);

        // C. warn-footer details
        const warn = await p.evaluate(() => {
          const d = document.getElementById("warnFooter");
          if (!d) return null;
          const lis = d.querySelectorAll("li");
          const summary = d.querySelector("summary");
          const dismissCb = d.querySelector("[data-warn-dismiss]");
          const hint = d.querySelector("#warnDismissHint");
          return {
            isDetails: d.tagName === "DETAILS",
            liCount: lis.length,
            summaryText: summary?.textContent.trim() || "",
            dismissExists: !!dismissCb,
            dismissAria: dismissCb?.getAttribute("aria-describedby"),
            hintExists: !!hint,
            liTexts: Array.from(lis).map((li) => li.textContent.trim()),
          };
        });
        assert(`${tab} <details id="warnFooter"> 存在`, !!warn);
        assert(`${tab} warn-footer 是 <details> 元素`, warn?.isDetails);
        assert(`${tab} warn-footer ${page.expectBullets} 条 bullet`,
               warn?.liCount === page.expectBullets, `actual=${warn?.liCount}`);
        assert(`${tab} dismiss checkbox 存在`, warn?.dismissExists);
        assert(`${tab} dismiss aria-describedby=warnDismissHint`,
               warn?.dismissAria === "warnDismissHint", `actual=${warn?.dismissAria}`);
        assert(`${tab} warnDismissHint 存在`, warn?.hintExists);
        // bullet 真实渲染：无 raw key、无空
        const hasRawKey = warn?.liTexts.some((t) => /\{\{[^}]+\}\}|^\s*(warn|backtest|silver|central_bank|health)\./.test(t));
        assert(`${tab} bullet 文本已渲染（无 raw key）`, !hasRawKey && (warn?.liTexts.every((t) => (t?.length || 0) > 5)),
               `texts=${JSON.stringify(warn?.liTexts)}`);

        // D. nav-warn-toggle 行为
        const toggleBehavior = await p.evaluate(() => {
          const t = document.querySelector("[data-warn-toggle]");
          const d = document.getElementById("warnFooter");
          if (!t || !d) return null;
          const startOpen = d.hasAttribute("open");
          const startAria = t.getAttribute("aria-expanded");
          t.click();
          const afterOpen = d.hasAttribute("open");
          const afterAria = t.getAttribute("aria-expanded");
          t.click(); // 复位
          const finalOpen = d.hasAttribute("open");
          const finalAria = t.getAttribute("aria-expanded");
          return { startOpen, startAria, afterOpen, afterAria, finalOpen, finalAria, controls: t.getAttribute("aria-controls") };
        });
        assert(`${tab} nav-warn-toggle 存在`, !!toggleBehavior);
        assert(`${tab} nav-warn-toggle aria-controls=warnFooter`,
               toggleBehavior?.controls === "warnFooter", `actual=${toggleBehavior?.controls}`);
        assert(`${tab} nav-warn-toggle 点击切换 details[open]`,
               toggleBehavior && toggleBehavior.startOpen !== toggleBehavior.afterOpen,
               `start=${toggleBehavior?.startOpen} after=${toggleBehavior?.afterOpen}`);
        assert(`${tab} nav-warn-toggle 同步 aria-expanded`,
               toggleBehavior?.startAria !== toggleBehavior?.afterAria,
               `start=${toggleBehavior?.startAria} after=${toggleBehavior?.afterAria}`);

        // E. dismiss checkbox → sessionStorage + 同会话内 reload 保持折叠
        const dismissTest = await p.evaluate(() => {
          return new Promise((resolve) => {
            const cb = document.querySelector("[data-warn-dismiss]");
            if (!cb) return resolve({ error: "no checkbox" });
            cb.click();
            setTimeout(() => {
              const session = sessionStorage.getItem("pm_warn_dismissed_session");
              cb.click(); // 复位
              resolve({ session, hasSession: session === "1" });
            }, 100);
          });
        });
        assert(`${tab} dismiss 写入 sessionStorage=1`, dismissTest?.hasSession,
               `session=${dismissTest?.session}`);

        // F. HC 模式对比度（仅 hc 主题断言）
        if (theme === "hc") {
          const hcStyle = await p.evaluate(() => {
            const s = document.querySelector(".warn-footer > summary");
            if (!s) return null;
            const cs = getComputedStyle(s);
            return { color: cs.color, bg: getComputedStyle(document.querySelector(".warn-footer")).backgroundColor };
          });
          // HC 主题：summary 前景色 = #ffff00 = rgb(255,255,0)，背景 = #000000 = rgb(0,0,0)
          assert(`${tab} HC 模式 summary 颜色 = rgb(255,255,0)`,
                 hcStyle?.color === "rgb(255, 255, 0)", `actual=${hcStyle?.color}`);
          assert(`${tab} HC 模式 warn-footer 背景 = rgb(0,0,0)`,
                 hcStyle?.bg === "rgb(0, 0, 0)", `actual=${hcStyle?.bg}`);
        }

        // G. 跨页通用 bullet 文本快照（仅 zh-CN + light 主题采一次）
        if (lang === "zh-CN" && theme === "light" && page.genericBullet) {
          bulletSnapshot[page.path] = warn?.liTexts;
        }
      } catch (e) {
        fail++;
        results.push(`  [FAIL] ${tab} :: exception ${e.message}`);
      } finally {
        await p.close();
      }
    }
  }
}

// H. 跨页通用 5 条 bullet 文本完全一致（zh-CN）
{
  const tab = "[cross-page consistency]";
  const paths = Object.keys(bulletSnapshot);
  if (paths.length === 4) {
    const ref = bulletSnapshot[paths[0]];
    const allMatch = ref && paths.every((p) => {
      const b = bulletSnapshot[p];
      return b && b.length === ref.length && b.every((t, i) => t === ref[i]);
    });
    assert(`${tab} 4 页通用 5 条 bullet 文本 zh-CN 完全一致`, allMatch,
           `pages=${paths.length}`);
  } else {
    assert(`${tab} 跨页快照数 = 4`, paths.length === 4, `actual=${paths.length}`);
  }
}

// I. #warn 深链：打开 silver.html#warn → details 打开
{
  const tab = "[#warn deep-link]";
  await new Promise((r) => setTimeout(r, 3000));
  const p = await browser.newPage();
  try {
    await p.goto("http://127.0.0.1:8888/static/silver.html#warn", { waitUntil: "domcontentloaded", timeout: 15000 });
    await new Promise((r) => setTimeout(r, 600));
    const isOpen = await p.evaluate(() => {
      const d = document.getElementById("warnFooter");
      // warning.js 处理 hash: 检测 location.hash === "#warn" → 设置 open
      return d?.hasAttribute("open") || false;
    });
    assert(`${tab} silver.html#warn → details[open] = true`, isOpen, `actual=${isOpen}`);
  } catch (e) {
    fail++;
    results.push(`  [FAIL] ${tab} :: ${e.message}`);
  } finally {
    await p.close();
  }
}

await browser.close();
console.log(results.join("\n"));
console.log(`\n结果：${pass} passed / ${fail} failed`);
process.exit(fail > 0 ? 1 : 0);
