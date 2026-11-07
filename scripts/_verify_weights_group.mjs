// scripts/_verify_weights_group.mjs
// V0.121.2（P0-7）线上实测门禁：组内平均模式下的权重页必须**说真话**
//
//   P0-7 真缺陷：`group_combine=true`（默认）时技术面指数 = Σ(组权重 × 组内均值)，
//   **5 个维度滑块完全不参与计算** —— 但页面照常可拖、照常显示「保存成功」
//   ⇒ 用户以为调参生效了，实际对技术面指数**零影响**（装饰性参数）。
//
//   本门禁断言：
//     ① 组内平均模式下 5 个维度滑块**确实是 disabled**（不是「看起来灰」而是真 disabled）
//     ② 有一行**说明文案**解释为什么灰（只 disabled 不解释 = 用户一头雾水）
//     ③ 3 个**组权重**滑块存在、可编辑、合计 100%（那才是真正生效的那套）
//     ④ 切到「单维度加权」⇒ 5 个滑块解锁、组权重编辑器隐藏
//     ⑤ 页面不出现 i18n key 字面量 / 未替换的 `{sum}` 占位符
//
// ⚠ 必须打 192.168.0.204:8888（主入口）。见记忆 lan-only-deployment。
// ⚠ 必须 setViewport(1352×900)。见记忆 puppeteer-viewport-sticky-nav。
// ⚠ 必须 setBypassServiceWorker(true)。见记忆 puppeteer-sw-silently-bypasses-interception。
// ⚠ 幂等：只读页面 + 只切 radio（不点保存），不改任何服务端状态。
import puppeteer from "puppeteer-core";

const BASE = process.env.BASE_URL || "http://192.168.0.204:8888";
const CHROME =
  "/home/surui/.cache/puppeteer/chrome/linux-153.0.8010.36/chrome-linux64/chrome";

let pass = 0;
let fail = 0;
function ok(name, cond, detail = "") {
  if (cond) {
    pass++;
    console.log(`  ✓ ${name}`);
  } else {
    fail++;
    console.log(`  ✗ ${name}${detail ? "  " + detail : ""}`);
  }
}

const browser = await puppeteer.launch({
  executablePath: CHROME,
  headless: "new",
  args: ["--no-sandbox", "--disable-dev-shm-usage"],
});
const page = await browser.newPage();
await page.setViewport({ width: 1352, height: 900 });
await page.setBypassServiceWorker(true);

const jsErrors = [];
page.on("pageerror", (e) => jsErrors.push(String(e)));
page.on("console", (m) => {
  if (m.type() === "error") jsErrors.push(m.text());
});

console.log("\n[P0-7] /weights 组权重");
await page.goto(`${BASE}/weights`, { waitUntil: "networkidle2", timeout: 90000 });
// ⚠ 等滑块行真的画出来再断言（子组件各自 fetch 后才渲染 ⇒ 等 DOM 不等网络）
await page
  .waitForFunction(() => !!document.getElementById("t_structure"), { timeout: 30000 })
  .catch(() => {});
await new Promise((r) => setTimeout(r, 1200));

const state = await page.evaluate(() => {
  const TREND = ["structure", "momentum", "support", "momentum_rsi", "drawdown"];
  const GROUP = ["trend", "overbought", "risk"];
  const sliders = (prefix, keys) =>
    keys.map((k) => {
      const el = document.getElementById(prefix + k);
      return el
        ? { id: prefix + k, disabled: !!el.disabled, value: el.value }
        : { id: prefix + k, missing: true };
    });
  const note = document.getElementById("trendModeNote");
  const block = document.getElementById("groupWeightBlock");
  const sum = document.getElementById("groupSum");
  return {
    gcOn: !!document.getElementById("gcOn")?.checked,
    trend: sliders("t_", TREND),
    group: sliders("g_", GROUP),
    noteHidden: note ? !!note.hidden : null,
    noteText: note ? (note.textContent || "").trim() : "",
    blockHidden: block ? !!block.hidden : null,
    groupSumText: sum ? (sum.textContent || "").trim() : "",
    bodyText: document.body.innerText,
  };
});
console.log(`  组内平均 = ${state.gcOn}`);
console.log(`  5 维度滑块: ${JSON.stringify(state.trend)}`);
console.log(`  3 组权重滑块: ${JSON.stringify(state.group)}`);
console.log(`  #groupSum = ${JSON.stringify(state.groupSumText)}`);

ok("组内平均模式已开启（默认档）", state.gcOn === true);
ok(
  "5 个维度滑块**确实 disabled**（不参与计算就别让用户拖）",
  state.trend.length === 5 && state.trend.every((s) => s.disabled === true),
  JSON.stringify(state.trend),
);
ok("有说明文案解释为什么置灰", state.noteHidden === false && state.noteText.length > 10,
   `hidden=${state.noteHidden} text=${JSON.stringify(state.noteText.slice(0, 60))}`);
ok("3 个组权重滑块存在且**可编辑**",
   state.group.length === 3 && state.group.every((s) => !s.missing && s.disabled === false),
   JSON.stringify(state.group));
const gSum = state.group.reduce((a, s) => a + (parseInt(s.value, 10) || 0), 0);
ok("3 个组权重合计 = 100%", gSum === 100, `sum=${gSum}`);
ok("组权重合计行显示 100%（不是未替换的 {sum} 占位符）",
   state.groupSumText === "100%", `groupSum=${JSON.stringify(state.groupSumText)}`);
ok("组权重编辑器可见", state.blockHidden === false, `hidden=${state.blockHidden}`);

// ── 切到「单维度加权」⇒ 5 个滑块解锁、组权重编辑器隐藏 ──
await page.evaluate(() => {
  const off = document.getElementById("gcOff");
  off.checked = true;
  off.dispatchEvent(new Event("change", { bubbles: true }));
});
await new Promise((r) => setTimeout(r, 500));
const after = await page.evaluate(() => {
  const TREND = ["structure", "momentum", "support", "momentum_rsi", "drawdown"];
  return {
    gcOff: !!document.getElementById("gcOff")?.checked,
    trend: TREND.map((k) => {
      const el = document.getElementById("t_" + k);
      return { id: "t_" + k, disabled: !!el.disabled };
    }),
    blockHidden: !!document.getElementById("groupWeightBlock")?.hidden,
  };
});
ok("切到「单维度加权」后 radio 状态正确", after.gcOff === true);
ok("单维度加权模式下 5 个滑块解锁",
   after.trend.every((s) => s.disabled === false), JSON.stringify(after.trend));
ok("单维度加权模式下组权重编辑器隐藏（它们不参与计算）", after.blockHidden === true);

// ── 切回组内平均 ⇒ 再次置灰（来回切换必须幂等）──
await page.evaluate(() => {
  const on = document.getElementById("gcOn");
  on.checked = true;
  on.dispatchEvent(new Event("change", { bubbles: true }));
});
await new Promise((r) => setTimeout(r, 500));
const back = await page.evaluate(() => {
  const TREND = ["structure", "momentum", "support", "momentum_rsi", "drawdown"];
  return TREND.every((k) => document.getElementById("t_" + k)?.disabled === true);
});
ok("切回组内平均后 5 个滑块再次置灰（来回切换幂等）", back === true);

ok("页面不出现 i18n key 字面量（weights.* / undefined）",
   !/\bweights\.[a-z_]+/.test(state.bodyText) && !/\bundefined\b/.test(state.bodyText),
   (state.bodyText.match(/\b(?:weights\.[a-z_]+|undefined)\b/g) || []).join(","));
ok("页面无 JS 错误", jsErrors.length === 0, jsErrors.slice(0, 3).join(" | "));

console.log(`\n结果：${pass} passed, ${fail} failed`);
await browser.close();
process.exit(fail === 0 ? 0 : 1);
