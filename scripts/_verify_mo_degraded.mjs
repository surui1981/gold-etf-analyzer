// scripts/_verify_mo_degraded.mjs
// V0.110.0 hotfix 验证：后端**未部署**该端点时（GET/PUT → 404）的降级表现。
//
// 复现的是用户实际遇到的形态：8888 上的 root 进程跑着旧代码，而 static/*.html
// 由 StaticFiles 直接读磁盘 —— 页面是新的、后端是旧的。断言：
//   1. 卡片显示「未部署」说明，而不是 5 行可填表单
//   2. loadTrendForPreview() 成功后不会再把上面的失败提示抹掉
//   3. 保存 / 清除按钮被藏起来（点了也只会再撞一次 404）
//   4. 无 undefined 泄漏、无 JS 报错
//
// 依赖 BASE_URL 指向**旧后端**（默认 8888）。若是新后端则本脚本无意义。
import puppeteer from "puppeteer-core";

const BASE = process.env.BASE_URL || "http://127.0.0.1:8888";
const browser = await puppeteer.launch({
  executablePath: "/home/surui/.cache/puppeteer/chrome/linux-153.0.8010.36/chrome-linux64/chrome",
  headless: "new", args: ["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"],
});
const page = await browser.newPage();
await page.setViewport({ width: 1400, height: 1000 });
const errs = [];
page.on("pageerror", (e) => errs.push("pageerror: " + e.message));
page.on("console", (m) => {
  const url = (m.location() && m.location().url) || "";
  // 本场景里 macro-overrides 的 404 是**预期结果**（端点不存在），不是 JS 报错
  if (m.type() === "error" && !url.includes("favicon") && !url.includes("macro-overrides")) {
    errs.push("console: " + m.text() + " @ " + url);
  }
});

const ok = [], bad = [];
const check = (c, l) => (c ? ok : bad).push(l);

const probe = await fetch(`${BASE}/api/v1/settings/macro-overrides`).catch(() => null);
if (!probe || probe.status !== 404) {
  console.log(`[SKIP] ${BASE} 的 macro-overrides 返回 ${probe ? probe.status : "连接失败"}，不是 404 —— 该后端已部署本功能`);
  await browser.close();
  process.exit(0);
}
check(true, `前置确认：${BASE} 后端对该端点返回 404（模拟"页面新、后端旧"）`);

await page.goto(`${BASE}/static/weights.html`, { waitUntil: "networkidle2" });
// 等 gold/trend 那条并发请求落地 —— 正是它曾把失败提示抹掉
await new Promise((r) => setTimeout(r, 6000));

const s = await page.evaluate(() => ({
  missing: !!document.querySelector("#moRows .mo-missing"),
  rows: document.querySelectorAll("#moRows .mo-row").length,
  text: (document.getElementById("moRows").textContent || "").trim().slice(0, 80),
  opsHidden: document.querySelector("#macroOverrideCard .mo-ops")?.hidden ?? null,
  opsVisible: (() => {
    const o = document.querySelector("#macroOverrideCard .mo-ops");
    return o ? getComputedStyle(o).display !== "none" : null;
  })(),
  headVisible: (() => {
    const h = document.querySelector("#macroOverrideCard .mo-head");
    return h ? getComputedStyle(h).display !== "none" : null;
  })(),
}));

check(s.missing, `显示「后端未部署」说明块（文本：${s.text}…）`);
check(s.rows === 0, `不渲染可填表单（实际 .mo-row ${s.rows} 个）`);
check(s.opsHidden === true, "保存/清除按钮已 hidden");
check(s.opsVisible === false, `按钮实际不可见（computed display 检查，防 [hidden] 被 display:flex 盖掉）`);
// 表头下面是说明块、没有数据行，留着表头只会让人以为还能填
check(s.headVisible === false, "表头已隐藏（说明块下方无数据行）");
check(!/undefined/.test(s.text), "无 undefined 泄漏");

// 切语言后说明块要跟着变（i18n:change → renderOverrides → 仍保持未部署态）
await page.evaluate(() => window.I18n.setLang("en-US"));
await new Promise((r) => setTimeout(r, 2000));
const en = await page.evaluate(() => ({
  missing: !!document.querySelector("#moRows .mo-missing"),
  text: (document.getElementById("moRows").textContent || "").trim().slice(0, 60),
}));
check(en.missing && /backend/i.test(en.text), `切到 en-US 后仍保持未部署态：${en.text}…`);

check(errs.length === 0, `无 JS 报错：${JSON.stringify(errs.slice(0, 3))}`);
await page.screenshot({ path: "/tmp/mo_degraded.png", fullPage: false });
await browser.close();

console.log("\n=== V0.110.0 hotfix · 后端未部署时的降级验证 ===");
ok.forEach((l) => console.log("  [OK  ] " + l));
bad.forEach((l) => console.log("  [FAIL] " + l));
console.log(`\n结果：${ok.length} passed, ${bad.length} failed`);
process.exit(bad.length ? 1 : 0);
