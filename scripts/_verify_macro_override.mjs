// scripts/_verify_macro_override.mjs
// V0.110.0 验证：/weights 页「宏观因子手动校准」卡片渲染
// - 期望：5 行（dxy/us10y/us30y/vix/cb_gold）全部渲染出当前生效值
// - 期望：每行 3 个输入框（number / date / text）+ 1 个清除按钮
// - 期望：i18n key 无 undefined 泄漏到 textContent
// - 期望：填值 → 保存 → 卡片行刷新且 source 变「手动输入」+ 滞后 chip
//
// 已知踩坑（见记忆 frontend-undefined-rendering）：模板字符串 `${x.prop}` 字段名
// 不一致会静默渲染 undefined。所以这里查 textContent，不是查 data-lang 属性。
import puppeteer from "puppeteer-core";

const BASE = process.env.BASE_URL || "http://127.0.0.1:8888";
const KEYS = ["dxy", "us10y", "us30y", "vix", "cb_gold"];

const browser = await puppeteer.launch({
  executablePath:
    "/home/surui/.cache/puppeteer/chrome/linux-153.0.8010.36/chrome-linux64/chrome",
  headless: "new",
  args: ["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"],
});

// 基线归零：上一次运行可能留下覆盖，导致 waitForFunction 条件被"旧数据"满足
// 而瞬间通过，断言读到的是保存前的状态。先清空再开跑。
const resetStatus = await fetch(`${BASE}/api/v1/settings/macro-overrides`, {
  method: "PUT",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ dxy: null, us10y: null, us30y: null, vix: null, cb_gold: null }),
}).then((r) => r.status);
if (resetStatus !== 200) {
  console.log(`[FATAL] 基线归零失败 HTTP ${resetStatus} —— 跳过验证`);
  await browser.close();
  process.exit(1);
}

const page = await browser.newPage();
await page.setViewport({ width: 1400, height: 1100 });

const consoleErrors = [];
page.on("pageerror", (e) => consoleErrors.push("pageerror: " + e.message));
page.on("console", (m) => {
  // favicon.ico 在本地开发服务器（未走生产静态挂载）上恒 404，与本版无关。
  // 注意 404 的 URL 在 m.location().url 里，不在 m.text() 里 —— 早期版本按
  // text() 过滤没生效，这里按 URL 判。
  const url = (m.location() && m.location().url) || "";
  if (m.type() === "error" && !url.includes("favicon")) {
    consoleErrors.push("console: " + m.text() + " @ " + url);
  }
});

const ok = [];
const bad = [];
const check = (cond, label) => (cond ? ok : bad).push(label);

await page.goto(BASE + "/static/weights.html", { waitUntil: "networkidle2" });

// 冷启动时 gold/trend 要现拉 60 根 K 线（实测数秒），等「当前生效」列脱离
// 「加载中」再断言 —— 否则会把"还没加载完"误判成"没读到值"。
const loading0 = await page.$$eval("#moRows .cur", (els) =>
  els.map((e) => e.textContent.trim()),
);
check(
  loading0.every((x) => x === "加载中…" || x.includes("·")),
  `首屏显示「加载中…」而非「暂无读数」：${JSON.stringify(loading0)}`,
);
await page.waitForFunction(
  () => {
    const cells = document.querySelectorAll("#moRows .cur");
    return cells.length === 5 && [...cells].every((e) => !e.textContent.includes("加载中"));
  },
  { timeout: 60000 },
);
check(true, "「当前生效」列在 60s 内完成加载");

// 1. 卡片存在
const cardExists = await page.$("#macroOverrideCard");
check(!!cardExists, "宏观因子手动校准卡片存在");

// 2. 5 行全部渲染
const rows = await page.$$eval("#moRows .mo-row", (els) =>
  els.map((el) => ({
    inputs: el.querySelectorAll("input").length,
    buttons: el.querySelectorAll("button").length,
    cur: el.querySelector(".cur")?.textContent?.trim() || "",
  })),
);
check(rows.length === 5, `渲染 5 行（实际 ${rows.length}）`);
check(
  rows.every((r) => r.inputs === 3),
  `每行 3 个输入框（实际 ${rows.map((r) => r.inputs).join("/")}）`,
);
check(
  rows.every((r) => r.buttons === 1),
  `每行 1 个清除按钮（实际 ${rows.map((r) => r.buttons).join("/")}）`,
);

// 3. 「当前生效」列有值（不应是 undefined / 暂无读数）
const curTexts = rows.map((r) => r.cur);
check(
  curTexts.every((t) => t && !t.includes("undefined") && !t.includes("暂无读数")),
  `当前生效列全部有值：${JSON.stringify(curTexts)}`,
);

// 3b. 每行必须单行排布。曾经踩到：备注输入框漏了 class="mo-note"，
// 宽度约束（.mo-row .mo-note）整条失效，退回浏览器默认宽度，
// 累加宽度超过卡片后「清除」按钮被挤到第二行 —— 5 行全是这样。
// ⚠ 判断折行要看**垂直中心**而不是 top：.mo-row 是 align-items:center，
// 同行元素高度不同 → top 本就各不相同，早期版本据此误判成"5 行都折了"。
const layout = await page.$$eval("#moRows .mo-row", (els) =>
  els.map((el) => {
    const cys = [...el.children].map((c) => {
      const r = c.getBoundingClientRect();
      return r.top + r.height / 2;
    });
    const min = Math.min(...cys);
    return {
      lines: new Set(cys.map((c) => Math.round(c / 8))).size,
      w: Math.round(el.getBoundingClientRect().width),
      min: Math.round(min),
    };
  }),
);
check(
  layout.every((l) => l.lines === 1),
  `每行单行排布（实测折行数 ${layout.map((l) => l.lines).join("/")}，卡片宽 ${layout[0].w}px）`,
);

// 4. 全文无 undefined 泄漏
const bodyText = await page.$eval("body", (el) => el.innerText);
check(!bodyText.includes("undefined"), "页面无 undefined 泄漏");

// 5. 录入并保存 → 行刷新 + source 变「手动输入」
await page.evaluate(() => {
  document.getElementById("mo_dxy").value = "97.42";
  document.getElementById("mo_dxy_d").value = "2026-10-21";
  document.getElementById("mo_dxy_n").value = "puppeteer verify";
});
await page.click('#macroOverrideCard button.btn-save');
// 保存会失效 served_cache → 下一次 gold/trend 是全量重算（要现拉 K 线，
// docs/api-reference.md 记录过 DNS 故障环境下 23.26s），所以等条件而不是等固定时长。
// 先等保存提示落定，再等"当前生效"列刷新 —— 两步都不能用固定 sleep。
await page
  .waitForFunction(
    () => {
      const m = document.getElementById("moMsg");
      return m && /已保存|保存失败/.test(m.textContent);
    },
    { timeout: 60000 },
  )
  .catch(() => {});
await page
  .waitForFunction(
    () => {
      const c = document.querySelector("#moRows .cur");
      return c && c.textContent.includes("97.42");
    },
    { timeout: 90000 },
  )
  .catch(() => {});

const afterSave = await page.evaluate(() => ({
  msg: document.getElementById("moMsg")?.textContent?.trim() || "",
  dxyCur: document.querySelector("#moRows .mo-row .cur")?.textContent?.trim() || "",
  isManual: !!document.querySelector("#moRows .mo-row.is-manual"),
  chip: document.querySelector("#moRows .mo-row .mo-chip")?.textContent?.trim() || "",
  chipWarn: !!document.querySelector("#moRows .mo-row .mo-chip-warn"),
}));
check(afterSave.msg.includes("已保存"), `保存成功提示：${afterSave.msg}`);
check(afterSave.dxyCur.includes("97.42"), `当前生效列显示手动值：${afterSave.dxyCur}`);
check(afterSave.isManual, "该行标记 is-manual 高亮");
check(afterSave.chip.includes("手动输入"), `显示「手动输入」来源 chip：${afterSave.chip}`);

// 6. 清理：清除全部覆盖（走二次确认弹窗）
await page.evaluate(() => {
  for (const k of ["dxy", "us10y", "us30y", "vix", "cb_gold"]) {
    document.getElementById("mo_" + k).value = "";
    document.getElementById("mo_" + k + "_d").value = "";
    document.getElementById("mo_" + k + "_n").value = "";
  }
});
const cleared = await page.evaluate(async () => {
  const r = await fetch("/api/v1/settings/macro-overrides", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      dxy: null, us10y: null, us30y: null, vix: null, cb_gold: null,
    }),
  });
  return r.status;
});
check(cleared === 200, `清除覆盖 API 返回 ${cleared}`);

await page.screenshot({ path: "/tmp/v01100_weights.png", fullPage: true });

check(consoleErrors.length === 0, `无 JS 报错：${JSON.stringify(consoleErrors.slice(0, 3))}`);

await browser.close();

console.log("\n=== V0.110.0 宏观因子手动校准 · /weights 验证 ===");
ok.forEach((l) => console.log("  [OK  ] " + l));
bad.forEach((l) => console.log("  [FAIL] " + l));
console.log(`\n结果：${ok.length} passed, ${bad.length} failed`);
process.exit(bad.length ? 1 : 0);