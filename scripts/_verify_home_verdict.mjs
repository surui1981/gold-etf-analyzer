// scripts/_verify_home_verdict.mjs
// V0.120.4 验证：首页 hero 右侧「综合评估」结论块（综合趋势评估指数 + 4 面分数条 + 因子明细）
//
// ⚠ 必须打 8888（主入口）。8889/gold/ 是备用入口且全站 /api/v1/* 404，
//   在那里跑只会得到与本改动无关的假失败。见记忆 lan-only-deployment。
// ⚠ 视口必须 1352×900：默认 800×600 下顶 nav 会盖住按钮，page.click 静默失效。
//   见记忆 puppeteer-viewport-sticky-nav。
// ⚠ Service Worker 会接管页面 ⇒ mock/拦截静默失效；本脚本不拦截，但要
//   setBypassServiceWorker(true) 否则可能读到旧缓存的 home.html。
//   见记忆 puppeteer-sw-silently-bypasses-interception。
import puppeteer from "puppeteer-core";

const BASE = process.env.BASE_URL || "http://127.0.0.1:8888";
const CHROME =
  "/home/surui/.cache/puppeteer/chrome/linux-153.0.8010.36/chrome-linux64/chrome";

let pass = 0;
let fail = 0;
function ok(name, cond, extra = "") {
  if (cond) { pass++; console.log(`  ✓ ${name}`); }
  else { fail++; console.log(`  ✗ ${name}${extra ? " → " + extra : ""}`); }
}

const browser = await puppeteer.launch({
  executablePath: CHROME,
  headless: "new",
  args: ["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"],
});
const page = await browser.newPage();
await page.setViewport({ width: 1352, height: 900 });
// ⚠ 必须禁用浏览器缓存（V0.125.0 定位的挂死根因）：
//   `/static/*.html` 无 `Cache-Control` ⇒ Chrome 启发式缓存 ⇒ 主文档从磁盘缓存
//   命中时**不发 `Page.lifecycleEvent`** ⇒ `waitUntil` 永不 settle ⇒ goto 挂死。
await page.setCacheEnabled(false);
// ⚠ 给门禁**独立的限流桶**（V0.125.0）：服务端按 IP 做 60s 滑动窗口限速
//   （`rate_limit_per_min = 600`），而**首页一次加载会打 ~20 个
//   `/api/v1/favorites/exists/*`** ⇒ 多个首页门禁连着跑就把真实 IP 的额度耗光
//   ⇒ 429 ⇒ 跟被测功能无关的断言（i18n 文案）跟着挂。
//   ⇒ 门禁改用 RFC 5737 文档保留网段的假 IP ⇒ 每个门禁一个**独立桶**，互不干扰。
//   ⚠ 服务端**只对限流**信任 `X-Forwarded-For`：认证默认不看（`trust_proxy_headers=False`，
//     实测 .env.prod 未设该项）；即便开启，XFF 也只用于「审计展示 + 登录节流」，
//     **不做安全判定**（见 middleware/auth.py:124 client_ip 的 docstring）。
await page.setExtraHTTPHeaders({ "X-Forwarded-For": "198.51.100.4" });
// ── 门禁豁免：把首页那 20 个 /api/v1/favorites/exists 请求打桩掉 ──
//   它与本门禁要测的东西无关，却占掉一次 /home 加载 **32 个 API 请求里的 20 个**
//   （实测脚本 scripts/_diag_home_req_count.mjs）⇒ 多个首页门禁连着跑就把服务端
//   `RATE_LIMIT_PER_MIN=600` 的额度吃光 ⇒ **429** ⇒ 跟被测功能无关的断言
//   （i18n 文案 / chip）跟着挂 —— 实测本门禁连跑 4 次就挂过 1 次。
//   ⇒ 打桩成「未收藏」（真实端点在未收藏时返回 200 + body `null`）。
//   ⚠ **豁免失效的条件**：若哪天有门禁要断言**收藏态**，必须先撤掉这条打桩。
await page.setRequestInterception(true);
page.on("request", async (req) => {
  if (req.url().includes("/api/v1/favorites/exists/")) {
    return req.respond({ status: 200, contentType: "application/json", body: "null" });
  }
  return req.continue();
});
await page.setBypassServiceWorker(true);

// 三处错误来源分别收集 —— console 和 response 会把同一个 4xx 重复报一遍，
// 去重后打印，避免刷屏时看不出有几处真问题。见记忆 exemption-lists-rot-silently。
const errs = new Set();
page.on("pageerror", (e) => errs.add(`pageerror: ${String(e)}`));
page.on("console", (m) => { if (m.type() === "error") errs.add(`console: ${m.text()}`); });
page.on("response", (r) => {
  if (r.status() >= 400) errs.add(`HTTP ${r.status()} ${r.url()}`);
});

// ─── 1. 结论块存在 + 桌面端落在 hero 右半边 ───
console.log("【1】结论块存在与版面位置");
await page.goto(`${BASE}/home`, { waitUntil: "networkidle2" });
// 等真实值而不是固定 sleep：判据是 .hv-num 拿到数字（不是 "—"）。
await page.waitForFunction(
  () => {
    const n = document.getElementById("hvNum");
    return n && /\d/.test(n.textContent);
  },
  { timeout: 30000 }
).catch(() => {});

const geom = await page.evaluate(() => {
  const hero = document.querySelector(".hero");
  const block = document.getElementById("homeVerdict");
  if (!hero || !block) return null;
  const h = hero.getBoundingClientRect();
  const b = block.getBoundingClientRect();
  return {
    heroW: h.width,
    blockLeftInHero: Math.round(b.left - h.left),
    blockW: Math.round(b.width),
    blockRightGap: Math.round(h.right - b.right),
    // 8 张场景卡没被动过
    scenesCount: document.querySelectorAll(".home-scene").length,
    firstSceneIsHeadlines: (document.querySelector(".home-scene")?.className || "")
      .includes("scene-headlines"),
    // 贵金属区仍在底部要闻之前
    metalsBeforeBottom: !!(
      document.querySelector(".home-metals") &&
      (document.querySelector(".home-metals").compareDocumentPosition(
        document.querySelector(".home-bottom")) & 4)
    ),
  };
});
ok("hero 里有 #homeVerdict 结论块", geom !== null);
ok("结论块落在 hero 右半边（不是叠在文案上）",
  !!geom && geom.blockLeftInHero > geom.heroW * 0.5,
  geom ? `left=${geom.blockLeftInHero} heroW=${geom.heroW}` : "");
ok("结论块没有溢出 hero 右边界",
  !!geom && geom.blockRightGap >= 0, geom ? `gap=${geom.blockRightGap}` : "");
ok("板块卡仍是 8 张（没动场景 grid）", geom?.scenesCount === 8, `实际 ${geom?.scenesCount}`);
ok("grid 首张仍是今日要闻磁贴", !!geom?.firstSceneIsHeadlines);
ok("贵金属区仍在底部今日要闻之前", !!geom?.metalsBeforeBottom);

// ─── 2. 分数与 API 真值一致 ───
console.log("【2】分数 / 等级 / 说明 与 API 同源");
const api = await page.evaluate(async () => {
  const r = await fetch("/api/v1/market/gold/trend?days=60&target=ny&interval=D");
  return r.json();
});
const dom = await page.evaluate(() => ({
  num: document.getElementById("hvNum")?.textContent.trim() || "",
  badge: document.getElementById("hvBadge")?.textContent.trim() || "",
  badgeHidden: !!document.getElementById("hvBadge")?.hidden,
  summary: document.getElementById("hvSummary")?.textContent.trim() || "",
  scope: document.getElementById("hvScope")?.textContent.trim() || "",
  pendingHidden: !!document.getElementById("hvPending")?.hidden,
  pendingText: document.getElementById("hvPending")?.textContent.trim() || "",
  faces: [...document.querySelectorAll(".hv-face")].map((r) => ({
    name: r.querySelector(".hv-face-name")?.textContent.trim() || "",
    val: r.querySelector(".hv-face-val")?.textContent.trim() || "",
    width: r.querySelector(".hv-bar > i")?.style.width || "",
  })),
  detailOpen: !!document.getElementById("hvDetail")?.open,
  groups: [...document.querySelectorAll(".hv-factor-group")].map((g) => ({
    head: g.querySelector(".hv-factor-head")?.textContent.trim() || "",
    rows: [...g.querySelectorAll(".hv-factor")].length,
  })),
  dirty: (() => {
    const txt = document.body.innerText;
    return ["undefined", "NaN", "home.idx_", "trend.comp_", "trend.level_"]
      .filter((k) => txt.includes(k));
  })(),
}));
const faceKeyByName = {
  "技术面": "tech", "技術面": "tech", "Technical": "tech",
  "宏观参考": "macro", "宏觀面": "macro", "Macro": "macro",
  "消息面": "news", "News": "news",
  "资金流面": "flow", "資金流面": "flow", "Money flow": "flow",
};

ok("大数字与 API index.score 一致",
  dom.num === Number(api.index.score).toFixed(1), `页面 "${dom.num}" / API ${api.index.score}`);
ok("等级徽章已显示", !dom.badgeHidden && dom.badge.length > 0, `实际 "${dom.badge}"`);
ok("说明含公式且含各面分值",
  Object.values(api.index.components).every((v) => dom.summary.includes(v.toFixed(1))),
  dom.summary);
// ⚠ 公式里的**权重**必须逐个对上 face_weights（实际生效）——
//   只断言「含分值」抓不到「用 face_weights_nominal 拼公式」这种错：
//   反向验证时把公式改成 nominal，分值照样在，断言照样绿。
//   （消息面被剔除时 nominal=25%/35%/15% vs 实际 33%/47%/20%，差异肉眼可见。）
for (const f of dom.faces) {
  const key = faceKeyByName[f.name];
  if (!key || typeof api.index.components[key] !== "number") continue;
  const comp = api.index.components[key];
  const pct = Math.round(api.index.face_weights[key] * 100);
  ok(`说明里 ${f.name} 的权重是 ${pct}%（face_weights 实际生效值）`,
    dom.summary.includes(`${f.name} ${comp.toFixed(1)}×${pct}%`),
    `实际 "${dom.summary}"`);
}
ok("脚注标明了口径与快照时间",
  /COMEX/i.test(dom.scope) && /\d{2}:\d{2}/.test(dom.scope), dom.scope);
ok("正好 4 条分数条（技术/宏观/消息/资金流）", dom.faces.length === 4,
  `实际 ${dom.faces.length}: ${dom.faces.map((f) => f.name).join("/")}`);
ok("页面没有 undefined / NaN / key 字面量", dom.dirty.length === 0, dom.dirty.join(", "));


// 权重口径：页面显示的百分比必须等于 face_weights（**实际生效**权重），
// 不是 face_weights_nominal —— 消息面被剔除时两者不同。
for (const f of dom.faces) {
  const key = faceKeyByName[f.name];
  if (!key) { ok(`未知面名 "${f.name}"`, false); continue; }
  const comp = api.index.components[key];
  const w = api.index.face_weights[key];
  const nominal = api.index.face_weights_nominal[key];
  if (typeof comp === "number") {
    ok(`${f.name} 分值与 components 一致（${comp}）`, f.val.includes(comp.toFixed(1)), f.val);
    ok(`${f.name} 权重与 face_weights 一致（${Math.round(w * 100)}%）`,
      f.val.includes(`${Math.round(w * 100)}%`), f.val);
    ok(`${f.name} 条宽 = 分值百分比`, f.width === `${comp}%`, f.width);
  } else {
    // 被剔除的面：显示配置权重并标「未计入」（不是生效权重）
    ok(`${f.name} 被剔除时显示配置权重 ${Math.round(nominal * 100)}% 且值是「—」`,
      f.val.includes("—") && f.val.includes(`${Math.round(nominal * 100)}%`), f.val);
    ok(`${f.name} 条宽为 0（没画假条）`, f.width === "0%", f.width);
  }
}

// pending 语义：消息面未打分 ⇒ 整面剔除、权重归一化、页面显示 pending chip
if (api.news && api.news.scored === false) {
  ok("消息面未打分 ⇒ 显示 pending chip", !dom.pendingHidden, dom.pendingText);
  ok("pending 时公式里没有消息面", !dom.summary.includes("消息面"), dom.summary);
  ok("pending 时 components 里确实没有 news",
    !(typeof api.index.components.news === "number"));
} else {
  ok("消息面已打分 ⇒ 不显示 pending chip", dom.pendingHidden, dom.pendingText);
}

// ─── 3. 因子明细（默认折叠，展开后每面都有）───
console.log("【3】各面因子明细");
ok("明细默认折叠", !dom.detailOpen);
await page.evaluate(() => { document.getElementById("hvDetail").open = true; });
await new Promise((r) => setTimeout(r, 300));
const groups = await page.evaluate(() =>
  [...document.querySelectorAll(".hv-factor-group")].map((g) => ({
    head: g.querySelector(".hv-factor-head")?.textContent.trim() || "",
    rows: [...g.querySelectorAll(".hv-factor")].map((r) => r.textContent.trim()),
  })));
ok("展开后有 4 组（4 个面）", groups.length === 4, `实际 ${groups.length}`);
for (const g of groups) {
  ok(`${g.head} 组有内容`, g.rows.length > 0, `rows=${g.rows.length}`);
}
const macroGroup = groups.find((g) => /宏观|Macro/.test(g.head));
ok("宏观面明细不是空壳", !!macroGroup && macroGroup.rows.length > 0);
const techGroup = groups.find((g) => /技术|Technical/.test(g.head));
ok("技术面明细不是空壳", !!techGroup && techGroup.rows.length > 0);

// ─── 4. 三语 ───
console.log("【4】三语渲染（查 textContent，不查 data-lang）");
const LANGS = [
  ["zh-CN", "综合趋势评估指数", "下降", "技术面", "纽约金 XAU"],
  ["zh-TW", "趨勢評估指數", "偏空", "技術面", "紐約金 XAU"],
  ["en-US", "Composite Trend Index", "Down", "Technical", "COMEX XAU"],
];
for (const [lang, title, level, face, jsText] of LANGS) {
  // ⚠ localStorage 键是 pm_lang，全局是 window.I18n —— 写错任何一个都只是静默 no-op。
  await page.evaluate(async (l) => {
    localStorage.setItem("pm_lang", l);
    if (window.I18n?.setLang) await window.I18n.setLang(l);
  }, lang);
  await page.reload({ waitUntil: "networkidle2" });
  await page.waitForFunction(
    () => /\d/.test(document.getElementById("hvNum")?.textContent || ""),
    { timeout: 30000 }
  ).catch(() => {});
  const got = await page.evaluate(() => ({
    title: document.querySelector(".hv-title")?.textContent.trim() || "",
    badge: document.getElementById("hvBadge")?.textContent.trim() || "",
    face: document.querySelector(".hv-face-name")?.textContent.trim() || "",
    toggle: document.querySelector(".hv-detail > summary")?.textContent.trim() || "",
    // JS 拼的文案（V0.120.4 修了 window.PM_I18N → window.I18n 这个 bug）
    jsText: document.getElementById("metalPriceBadge")?.textContent.trim() || "",
  }));
  ok(`${lang} 结论块标题`, got.title === title, `实际 "${got.title}"`);
  ok(`${lang} 等级徽章`, got.badge === level, `实际 "${got.badge}"`);
  ok(`${lang} 面名`, got.face === face, `实际 "${got.face}"`);
  ok(`${lang} 明细开关有文案`, got.toggle.length > 0, `实际 "${got.toggle}"`);
  // ⚠ 断言要打**字典里的期望值**，不能只判「是不是中文」——
  //   zh-TW 本身就是中文（繁体），用「含汉字即失败」会把正确的翻译判成错。
  ok(`${lang} JS 拼的文案 = 字典值（V0.120.4 修的 window.PM_I18N bug）`,
    got.jsText === jsText, `实际 "${got.jsText}" 期望 "${jsText}"`);
}

// ─── 5. 移动端不横向溢出 ───
console.log("【5】移动端 390px");
await page.setViewport({ width: 390, height: 900 });
await new Promise((r) => setTimeout(r, 600));
const mob = await page.evaluate(() => ({
  scrollW: document.documentElement.scrollWidth,
  clientW: document.documentElement.clientWidth,
  num: document.getElementById("hvNum")?.textContent.trim() || "",
}));
ok("390px 下无横向溢出", mob.scrollW <= mob.clientW, `scrollW=${mob.scrollW} clientW=${mob.clientW}`);
ok("390px 下仍渲染出分数", /\d/.test(mob.num), `实际 "${mob.num}"`);

// ─── 6. 无前端错误 ───
console.log("【6】错误收口");
const errList = [...errs].filter((e) => !/favicon/i.test(e));
ok("无 console / pageerror / HTTP>=400", errList.length === 0, errList.slice(0, 5).join(" | "));

await browser.close();
console.log(`\n结果：${pass} passed, ${fail} failed`);
process.exit(fail === 0 ? 0 : 1);
