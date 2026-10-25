// scripts/_verify_macro_factors.mjs
// V0.118.0 验证：/weights 页「宏观面权重」8 因子 + /backtest 页宏观网格用因子 key
//
// 覆盖的三件事（V0.118.0 之前没有门禁管）：
// 1. 宏观面分组渲染出 **8 个**滑块（5 → 8 因子），且合计 = 100%
// 2. 「恢复默认」把 8 个滑块设成新方案默认值（dxy 15 / us2y 6 / us10y 8 /
//    us30y 6 / curve 10 / real10y 20 / vix 10 / cb_gold 25）
// 3. /backtest 页宏观网格的 input 用**因子 key**（data-key="dxy"）而不是中文显示名
//    —— 中文名与快照 macro_detail 的键对不上会让「启用宏观内部权重」跑出 0 行
//
// ⚠️ 行数断言写死 8：因子数变了不改这里，脚本会静默通过（少渲染的行不会报）。
import puppeteer from "puppeteer-core";

const BASE = process.env.BASE_URL || "http://127.0.0.1:8888";
const KEYS = ["dxy", "us2y", "us10y", "us30y", "curve_10y2y", "real10y", "vix", "cb_gold"];
const EXPECTED_ROWS = KEYS.length;
// V0.118.0 的默认权重（百分比），与后端 MacroWeightConfig 默认值一致
const DEFAULTS = {
  dxy: 15,
  us2y: 6,
  us10y: 8,
  us30y: 6,
  curve_10y2y: 10,
  real10y: 20,
  vix: 10,
  cb_gold: 25,
};
// 回测页宏观网格仍是 5 个（新增 3 因子从 V0.118.0 起才落快照，历史快照没有）
const BACKTEST_MACRO_KEYS = ["dxy", "us10y", "us30y", "vix", "cb_gold"];

const browser = await puppeteer.launch({
  executablePath:
    "/home/surui/.cache/puppeteer/chrome/linux-153.0.8010.36/chrome-linux64/chrome",
  headless: "new",
  args: ["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"],
});

const page = await browser.newPage();
// V0.113.0 记忆：默认 800×600 下顶 nav 会盖住按钮，page.click 静默失效
await page.setViewport({ width: 1352, height: 900 });

const consoleErrors = [];
page.on("pageerror", (e) => consoleErrors.push("pageerror: " + e.message));
page.on("console", (m) => {
  const url = (m.location() && m.location().url) || "";
  if (m.type() === "error" && !url.includes("favicon")) {
    consoleErrors.push("console: " + m.text() + " @ " + url);
  }
});

const ok = [];
const bad = [];
const check = (cond, label) => (cond ? ok : bad).push(label);

/* 等条件的统一入口。
 *
 * ⚠ 为什么不能直接 `waitForFunction(...).catch(() => {})`：
 * 谓词在**页面里**执行，一旦引用了 Node 侧变量就抛 ReferenceError，
 * 而 puppeteer **把异常吞掉、只报超时** —— 看起来像「条件没满足」，
 * 实际是谓词本身写错了。吞掉异常会让这类写错的门禁**永远绿**。
 * ⇒ 这里统一 try/catch 并把失败原因记成一条 FAIL（带页面当时的状态）。 */
async function waitFor(label, fn, opts, ...args) {
  try {
    await page.waitForFunction(fn, opts, ...args);
    check(true, label);
    return true;
  } catch (e) {
    const dump = await page
      .evaluate(() => ({
        sliders: [...document.querySelectorAll("#macroRows .w-row input")].map((i) => i.id + "=" + i.value),
        sum: document.getElementById("macroSum")?.textContent?.trim() || "",
      }))
      .catch(() => null);
    check(false, `${label} —— ${e.message}；页面当时：${JSON.stringify(dump)}`);
    return false;
  }
}

await page.goto(BASE + "/static/weights.html", { waitUntil: "networkidle2" });
// 等权重从 API 载入（滑块由 state 渲染，state 为空时会是 0%）
await waitFor(
  "权重从 API 载入（m_dxy > 0）",
  () => {
    const el = document.getElementById("m_dxy");
    return el && Number(el.value) > 0;
  },
  { timeout: 30000 },
);

// 1. 宏观面 8 个滑块
const sliders = await page.$$eval("#macroRows .w-row", (els) =>
  els.map((el) => ({
    id: el.querySelector("input[type=range]")?.id || "",
    value: Number(el.querySelector("input[type=range]")?.value || 0),
    label: el.querySelector(".nm")?.textContent?.trim() || "",
    pct: el.querySelector(".pct")?.textContent?.trim() || "",
  })),
);
check(sliders.length === EXPECTED_ROWS, `宏观面渲染 ${EXPECTED_ROWS} 个滑块（实际 ${sliders.length}）`);
for (const k of KEYS) {
  const hit = sliders.find((s) => s.id === "m_" + k);
  check(!!hit, `滑块 m_${k} 存在`);
  if (hit) {
    check(hit.pct === hit.value + "%", `m_${k} 百分比标签与滑块一致：${hit.pct}`);
    check(hit.label.length > 0, `m_${k} 有中文标签：${hit.label}`);
  }
}

// 2. 合计 = 100%
const macroSum = await page.$eval("#macroSum", (el) => ({
  text: el.textContent.trim(),
  cls: el.className,
}));
check(macroSum.text === "100%", `宏观面合计显示 100%（实际 ${macroSum.text}）`);
check(macroSum.cls === "sum-ok", `合计标记为 sum-ok（实际 ${macroSum.cls}）`);

// 3. 标题文案含「8」
const heading = await page.$eval("#macroRows", () => {
  const h = document.querySelector("h2[data-i18n='weights.macro_title']");
  return h ? h.textContent.trim() : "";
});
check(heading.includes("8"), `宏观面标题含因子数 8：${heading}`);

// 4. 「恢复默认」→ 8 个默认值
//    注意：resetAll() 会弹二次确认框，脚本要自己点「确定恢复」
//    ⚠️ resetAll() 内部是**真的 PUT 保存**（会覆盖线上用户的自定义权重），
//    所以脚本先备份当前权重、跑完再原样写回去。
const beforeWeights = await page.evaluate(async () => {
  const r = await fetch("/api/v1/settings/weights");
  return r.ok ? await r.json() : null;
});
check(!!beforeWeights, "备份当前权重（供恢复默认测试后回写）");
await page.evaluate(() => {
  // 先把滑块改成非默认值，确保「恢复默认」真的生效而不是没变化
  for (const k of ["dxy", "us2y", "us10y", "us30y", "curve_10y2y", "real10y", "vix", "cb_gold"]) {
    const el = document.getElementById("m_" + k);
    if (el) el.value = 1;
  }
  if (typeof update === "function") update();
});
const btnReset = await page.$$eval("button.btn-reset", (els) =>
  els.findIndex((e) => (e.textContent || "").includes("恢复默认")),
);
check(btnReset >= 0, "找到「恢复默认」按钮");
if (btnReset >= 0) {
  const handles = await page.$$("button.btn-reset");
  await handles[btnReset].click();
  // 确认框是动态创建的 .cd-mask > .cd-box > .cd-ops（不是 .modal）
  await waitFor(
    "弹出二次确认框（.cd-box 确定恢复）",
    () => {
      const b = document.querySelector(".cd-box button.btn-save[data-act='yes']");
      return !!b;
    },
    { timeout: 10000 },
  );
  const confirmed = await page.$(".cd-box button.btn-save[data-act='yes']");
  if (confirmed) await confirmed.click();
  // 等滑块真的变成默认值（resetAll 内部要 PUT 一次再重渲染）
  await waitFor(
    "恢复默认后滑块变成默认值",
    (exp) =>
      Object.keys(exp).every(
        (k) => Number(document.getElementById("m_" + k)?.value) === exp[k],
      ),
    { timeout: 20000 },
    DEFAULTS,
  );
}
const afterReset = await page.$$eval("#macroRows .w-row", (els) =>
  Object.fromEntries(
    els.map((el) => [
      el.querySelector("input[type=range]")?.id || "",
      Number(el.querySelector("input[type=range]")?.value || 0),
    ]),
  ),
);
for (const k of KEYS) {
  check(
    afterReset["m_" + k] === DEFAULTS[k],
    `恢复默认后 m_${k} = ${DEFAULTS[k]}%（实际 ${afterReset["m_" + k]}%）`,
  );
}

// 4b. 把线上权重原样写回去（恢复默认测试是有副作用的真实保存）
if (beforeWeights) {
  const restored = await page.evaluate(async (w) => {
    const r = await fetch("/api/v1/settings/weights", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(w),
    });
    return { status: r.status, body: await r.json().catch(() => null) };
  }, beforeWeights);
  check(restored.status === 200, `回写原权重成功（${restored.status}）`);
  const nowSum = KEYS.reduce((s, k) => s + (restored.body?.macro?.[k] || 0), 0);
  check(Math.abs(nowSum - 1) < 1e-6, `回写后宏观权重合计 = 1（实际 ${nowSum}）`);
}

// 5. GET /api/v1/settings/weights 返回 8 个宏观 key
const weightsApi = await page.evaluate(async () => {
  const r = await fetch("/api/v1/settings/weights");
  return { status: r.status, body: await r.json() };
});
check(weightsApi.status === 200, `GET /settings/weights 返回 ${weightsApi.status}`);
const macroKeys = Object.keys(weightsApi.body?.macro || {});
check(
  macroKeys.length === EXPECTED_ROWS && KEYS.every((k) => macroKeys.includes(k)),
  `API 返回 ${EXPECTED_ROWS} 个宏观 key：${macroKeys.join("/")}`,
);
const apiSum = KEYS.reduce((s, k) => s + (weightsApi.body?.macro?.[k] || 0), 0);
check(Math.abs(apiSum - 1) < 1e-6, `API 宏观权重合计 = 1（实际 ${apiSum}）`);

// 6. 页面无 undefined 泄漏
const bodyText = await page.$eval("body", (el) => el.innerText);
check(!bodyText.includes("undefined"), "权重页无 undefined 泄漏");

await page.screenshot({ path: "/tmp/v01180_weights.png", fullPage: true });

// 7. 回测页宏观网格用因子 key
await page.goto(BASE + "/static/backtest.html", { waitUntil: "networkidle2" });
await waitFor(
  "回测页宏观网格渲染出（#macroGrid input[data-key]）",
  () => {
    const el = document.querySelector("#macroGrid input[data-key]");
    return !!el;
  },
  { timeout: 30000 },
);
const grid = await page.$$eval("#macroGrid input[data-key]", (els) =>
  els.map((e) => ({ key: e.getAttribute("data-key"), value: e.value })),
);
check(grid.length === BACKTEST_MACRO_KEYS.length, `回测宏观网格 ${BACKTEST_MACRO_KEYS.length} 个输入（实际 ${grid.length}）`);
for (const k of BACKTEST_MACRO_KEYS) {
  check(
    grid.some((g) => g.key === k),
    `回测宏观网格含因子 key「${k}」`,
  );
}
// 回归锁：中文显示名**不能**出现在 data-key 里
// （V0.118.0 之前就是用中文名当 key → 快照 macro_detail 对不上 → 回测永远 0 行）
const chineseKey = grid.find((g) => /[一-鿿]/.test(g.key || ""));
check(!chineseKey, `回测网格 data-key 不含中文（发现 ${chineseKey?.key}）`);

await page.screenshot({ path: "/tmp/v01180_backtest.png", fullPage: true });

check(consoleErrors.length === 0, `无 JS 报错：${JSON.stringify(consoleErrors.slice(0, 3))}`);

await browser.close();

console.log("\n=== V0.118.0 宏观面 8 因子 · /weights + /backtest 验证 ===");
ok.forEach((l) => console.log("  [OK  ] " + l));
bad.forEach((l) => console.log("  [FAIL] " + l));
console.log(`\n结果：${ok.length} passed, ${bad.length} failed`);
if (bad.length) process.exit(1);
