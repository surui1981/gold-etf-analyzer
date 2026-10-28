// scripts/_verify_money_flow.mjs
// V0.120.0 验证：新增第 4 个评分面「资金流面」（钱往哪儿流）
//
// 覆盖五件事：
//  A. **线上 API**：/api/v1/market/gold/trend 的 flow 段 —— 6 个因子齐全，
//     cadence（周度 3 / 月度 3）、window_days（周 728 / 月 1826）、
//     面内权重合计 = 1，weekly_weight + monthly_weight = 1。
//  B. **综合指数 4 面**：index.face_weights_nominal 4 键且合计 = 1（配置原值）；
//     index.face_weights = **实际生效**的面（被剔除的面不在里面），合计 = 1、
//     每个 > 0、且是 nominal 的子集。
//  C. **/weights 页**：6 个资金流面滑块 + 4 个合成滑块，两组合计各 100%；
//     页面正文**不含 undefined**（模板串字段名写错会静默渲染 undefined）。
//  D. **/trend 页**：6 行资金流因子 + 中性「周度/月度」chip，
//     且**不亮滞后红灯**（周/月频因子用后端 max_lag_days，不拿日频 4 天判）；
//     「运算方法」公式显示**实际生效**的面（不再硬编码 30/40/30）。
//  D2. **首页综合研判结论卡**（synthesis-card.js / decision-explainer.js）：
//     4 个面各一行；标题公式的权重合计 = 100%（数值比对）；
//     被剔除的面标「未计入」且分值为「—」；
//     **决策拆解各面贡献相加 = 综合指数**（老 bug：公式 ≠ 算法）。
//  E. **反向验证（阳性对照）**：把真实响应里的 flow 段与 face_weights.flow
//     一起删掉（= 模拟 V0.120.0 之前的后端），趋势页**不得**出现资金流面区块，
//     公式**不得**出现「资金流面」—— 证明 A~D 的断言不是空断言。
//  F. **反向验证（阳性对照）**：把 face_weights mock 成**旧的 3 面权重 30/40/30**，
//     结论卡标题必须照着画 30/40/30 —— 证明权重来自后端而不是前端硬编码。
//
// ⚠ mock 必须用**真实抓下来的响应**改字段（凭想象编 payload 会假绿/假红）。
// ⚠ 必须 setBypassServiceWorker(true)：SW 接管页面后 mock 会静默失效
//   （第二次导航拿真实数据，断言看着绿其实没测到）。
// ⚠ 视口 1352×900：默认 800×600 下 sticky 顶栏会盖住按钮，click 静默失效。
// ⚠ 不能与全量 pytest 同时跑（两者抢 SQLite 锁，门禁会被超时杀掉）。
import puppeteer from "puppeteer-core";

const BASE = process.env.BASE_URL || "http://192.168.0.204:8888";
const CHROME =
  "/home/surui/.cache/puppeteer/chrome/linux-153.0.8010.36/chrome-linux64/chrome";

//: 6 个资金流因子（key → 期望的节奏 / 窗口 / 面内权重）
//:
//: ⚠ 权重用**数值比较**（容差 1e-6），不用子串匹配 —— 服务端按用户配置下发，
//: 用户在权重页改过就是别的值，字符串比对会永远假红。
const FACTORS = {
  cot_gold_net: { cadence: "weekly", window_days: 728, weight: 0.18 },
  cot_gold_flow: { cadence: "weekly", window_days: 728, weight: 0.14 },
  gold_etf_flow: { cadence: "weekly", window_days: 728, weight: 0.22 },
  us_liq_net: { cadence: "monthly", window_days: 1826, weight: 0.14 },
  cn_margin_flow: { cadence: "monthly", window_days: 1826, weight: 0.16 },
  cn_money_gap: { cadence: "monthly", window_days: 1826, weight: 0.16 },
};
const FACTOR_KEYS = Object.keys(FACTORS);
const WEEKLY_KEYS = FACTOR_KEYS.filter((k) => FACTORS[k].cadence === "weekly");
const MONTHLY_KEYS = FACTOR_KEYS.filter((k) => FACTORS[k].cadence === "monthly");
const FACES = ["tech", "macro", "news", "flow"];
/* 各面的中文标签。趋势页的「宏观参考」与别处的「宏观面」是**不同措辞但同一个面**
   —— 断言时必须用对，否则会误判成「缺了一面」。 */
const FACE_TXT = { tech: "技术面", macro: "宏观参考", news: "消息面", flow: "资金流面" };
/* 持仓页「指数构成」与 news.html intro 用「宏观面」（结论卡/趋势页用「宏观参考」）——
   两种措辞指同一个面，断言时别用错词，否则会误判成「缺一面」。 */
const FACE_TXT_ALT = { ...FACE_TXT, macro: "宏观面" };
const CADENCE_CHIP = { weekly: "周度", monthly: "月度" };

const ok = [];
const bad = [];
const warn = [];
const check = (cond, label) => (cond ? ok : bad).push(label);
const note = (label) => warn.push(label);

const numEq = (a, b, tol = 1e-6) => Number.isFinite(a) && Math.abs(a - b) < tol;

// ───────────────────── A. 线上 API ─────────────────────

let trend = null;
try {
  const r = await fetch(`${BASE}/api/v1/market/gold/trend?days=60`, {
    signal: AbortSignal.timeout(240000),
  });
  check(r.status === 200, `GET /market/gold/trend 返回 ${r.status}`);
  trend = await r.json();
} catch (e) {
  check(false, `GET /market/gold/trend 失败：${e.message}`);
}

if (trend) {
  const flow = trend?.flow;
  check(!!flow, "响应里有 flow 段（资金流面）");
  if (flow) {
    const factors = Array.isArray(flow.factors) ? flow.factors : [];
    const byKey = Object.fromEntries(factors.map((f) => [f.key, f]));
    check(
      factors.length === 6,
      `资金流因子共 6 个（实际 ${factors.length}：${factors.map((f) => f.key).join("/")}）`,
    );
    check(
      FACTOR_KEYS.every((k) => byKey[k]),
      `6 个因子 key 齐全（缺 ${FACTOR_KEYS.filter((k) => !byKey[k]).join("/") || "无"}）`,
    );
    for (const k of FACTOR_KEYS) {
      const f = byKey[k];
      if (!f) {
        check(false, `${k} 存在`);
        continue;
      }
      const exp = FACTORS[k];
      check(f.cadence === exp.cadence, `${k} cadence = ${exp.cadence}（实际 ${f.cadence}）`);
      check(
        f.window_days === exp.window_days,
        `${k} window_days = ${exp.window_days}（实际 ${f.window_days}）`,
      );
      check(
        ["live", "lkg", "static"].includes(f.tier),
        `${k} tier 合法（实际 ${f.tier}）`,
      );
      check(
        Number.isFinite(Number(f.value)) && f.value !== "",
        `${k} value 是数值（实际 ${JSON.stringify(f.value)}）`,
      );
      check(!!f.data_date, `${k} 有 data_date（实际 ${f.data_date}）`);
      check(!!f.source, `${k} 有 source（实际 ${f.source}）`);
    }
    const wsum = factors.reduce((s, f) => s + Number(f.weight || 0), 0);
    check(numEq(wsum, 1, 1e-6), `面内权重合计 = 1（实际 ${wsum}）`);
    check(
      numEq(Number(flow.weekly_weight || 0) + Number(flow.monthly_weight || 0), 1, 1e-6),
      `weekly_weight + monthly_weight = 1（实际 ${flow.weekly_weight} + ${flow.monthly_weight}）`,
    );
    // 周度合计应等于 3 个周频因子的权重之和（默认 0.54）
    const weeklySum = WEEKLY_KEYS.reduce((s, k) => s + Number(byKey[k]?.weight || 0), 0);
    check(
      numEq(Number(flow.weekly_weight || 0), weeklySum, 1e-6),
      `weekly_weight 与周频因子权重之和一致（${flow.weekly_weight} vs ${weeklySum}）`,
    );
    const monthlySum = MONTHLY_KEYS.reduce((s, k) => s + Number(byKey[k]?.weight || 0), 0);
    check(
      numEq(Number(flow.monthly_weight || 0), monthlySum, 1e-6),
      `monthly_weight 与月频因子权重之和一致（${flow.monthly_weight} vs ${monthlySum}）`,
    );

    // ── 动态阈值自洽：布尔摘要必须与逐因子明细一致 ──
    // flow_dynamic 是「全部可滚动因子都走滚动分位」的摘要，dynamic_factors 是明细。
    // 两者由不同代码路径算出（一个是 is_dynamic_active，一个是逐因子列表）
    // ⇒ 必须交叉验证，否则用户会看到「badge 说静态、明细却写着 6 个动态」。
    const dynCount = (flow.dynamic_factors || []).length;
    const rollTotal = (flow.rolling_factors || []).length;
    check(
      Number(flow.flow_dynamic) === Number(dynCount === rollTotal && rollTotal > 0),
      `flow_dynamic 与 dynamic_factors 明细自洽（flow_dynamic=${flow.flow_dynamic}，动态 ${dynCount}/${rollTotal}）`,
    );
  }

  // ── B. 综合指数 4 面 ──
  //
  // ⚠ 口径（别写成「face_weights 必须有 4 个键」）：face_weights 是**实际生效**
  // 的面 —— 某个面没打分（消息面未打分 / 资金流面数据源全挂）时它被**剔除**，
  // 剩下三个面的权重重新归一化。所以 face_weights 只会有 3 个键。
  // 「配置原值」在 face_weights_nominal（4 个键齐全），前端要说明
  // 「消息面 X% 权重被剔除」只能从那里取。
  //
  // 不变式（这才是真正要断言的）：
  //   ① nominal 含全部 4 面且合计 = 1；
  //   ② effective ⊆ nominal，每个 > 0，合计 = 1；
  //   ③ effective 缺的键 = 被剔除的面（这里至少能断言 news 被剔除时它确实不在里面，
  //      而它在 nominal 里 —— 即「被剔除 ≠ 配置丢失」）。
  const nw = trend?.index?.face_weights_nominal;
  check(
    !!nw && typeof nw === "object" && FACES.every((f) => nw[f] != null),
    `index.face_weights_nominal 含全部 4 个面（实际 ${JSON.stringify(nw)}）`,
  );
  if (nw && typeof nw === "object") {
    const s = FACES.reduce((acc, f) => acc + Number(nw[f] || 0), 0);
    check(numEq(s, 1, 1e-3), `face_weights_nominal 合计 = 1（实际 ${s}）`);
  }
  const fw = trend?.index?.face_weights;
  check(
    !!fw && typeof fw === "object",
    `index.face_weights 存在（实际 ${JSON.stringify(fw)}）`,
  );
  if (fw && typeof fw === "object") {
    const s = Object.values(fw).reduce((acc, v) => acc + Number(v || 0), 0);
    check(numEq(s, 1, 1e-3), `face_weights 合计 = 1（实际 ${s}）`);
    const effKeys = Object.keys(fw);
    check(
      effKeys.every((k) => FACES.includes(k)),
      `face_weights 只含已知的 4 个面（实际 ${effKeys.join("/")}）`,
    );
    check(
      effKeys.every((k) => Number(fw[k]) > 0),
      `face_weights 里每个面的权重都 > 0（实际 ${JSON.stringify(fw)}）`,
    );
    check(
      effKeys.every((k) => nw && nw[k] != null),
      `生效的面在 nominal 里也都有（实际 ${effKeys.join("/")}）`,
    );
    // 被剔除的面：配置还在（nominal）但不在 effective 里
    const dropped = FACES.filter((f) => nw && nw[f] != null && fw[f] == null);
    const scored = trend?.news?.scored;
    if (scored === false) {
      check(
        dropped.includes("news"),
        `消息面未打分 ⇒ 它被剔除（不在 face_weights 里，实际剔除：${dropped.join("/") || "无"}）`,
      );
      check(
        nw && nw.news != null && Number(nw.news) > 0,
        `消息面被剔除但配置权重仍在 nominal（${nw?.news}）`,
      );
    }
  }
}

// ───────────────────── 浏览器 ─────────────────────

const browser = await puppeteer.launch({
  executablePath: CHROME,
  headless: "new",
  args: ["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"],
});

const consoleErrors = [];
function wireErrors(page) {
  page.on("pageerror", (e) => consoleErrors.push("pageerror: " + e.message));
  page.on("console", (m) => {
    const url = (m.location() && m.location().url) || "";
    if (m.type() === "error" && !url.includes("favicon")) {
      consoleErrors.push("console: " + m.text() + " @ " + url);
    }
  });
}

// ── C. /weights 页（live）─────────────────────
{
  const page = await browser.newPage();
  await page.setViewport({ width: 1352, height: 900 });
  await page.setCacheEnabled(false);
  await page.setBypassServiceWorker(true);
  wireErrors(page);

  await page.goto(BASE + "/static/weights.html", { waitUntil: "networkidle2" });
  let loaded = false;
  try {
    await page.waitForFunction(
      () => {
        const el = document.getElementById("f_cot_gold_net");
        return el && Number(el.value) > 0;
      },
      { timeout: 60000 },
    );
    loaded = true;
  } catch (e) {
    const dump = await page
      .evaluate(() => ({
        flowRows: document.querySelectorAll("#flowRows .w-row").length,
        combineRows: document.querySelectorAll("#combineRows .w-row").length,
        flowSum: document.getElementById("flowSum")?.textContent?.trim() || "",
      }))
      .catch(() => null);
    check(false, `资金流滑块加载完成：${e.message}；页面当时 ${JSON.stringify(dump)}`);
  }
  if (loaded) check(true, "资金流 6 个滑块在 60s 内载入（f_cot_gold_net > 0）");

  const w = await page.evaluate(() => {
    const rows = (sel) =>
      [...document.querySelectorAll(sel + " .w-row")].map((el) => ({
        id: el.querySelector("input[type=range]")?.id || "",
        value: Number(el.querySelector("input[type=range]")?.value || 0),
        label: el.querySelector(".nm")?.textContent?.trim() || "",
        pct: el.querySelector(".pct")?.textContent?.trim() || "",
      }));
    const sumOf = (id) => document.getElementById(id)?.textContent?.trim() || "";
    const bodyText = document.body.innerText || "";
    return {
      flow: rows("#flowRows"),
      combine: rows("#combineRows"),
      flowSum: sumOf("flowSum"),
      combineSum: sumOf("combineSum"),
      hasUndefined: bodyText.includes("undefined"),
      undefinedSnippets: bodyText
        .split("\n")
        .filter((l) => l.includes("undefined"))
        .slice(0, 3),
    };
  });

  check(w.flow.length === 6, `资金流面渲染 6 个滑块（实际 ${w.flow.length}）`);
  for (const k of FACTOR_KEYS) {
    const hit = w.flow.find((s) => s.id === "f_" + k);
    check(!!hit, `滑块 f_${k} 存在`);
    if (hit) {
      check(hit.pct === hit.value + "%", `f_${k} 百分比标签与滑块一致：${hit.pct}`);
      check(hit.label.length > 0, `f_${k} 有中文标签：${hit.label}`);
    }
  }
  const flowTotal = w.flow.reduce((s, r) => s + r.value, 0);
  check(flowTotal === 100, `资金流面滑块合计 = 100%（实际 ${flowTotal}%）`);
  check(w.flowSum === "100%", `资金流面合计显示 100%（实际 ${w.flowSum}）`);

  check(w.combine.length === 4, `合成权重渲染 4 个滑块（实际 ${w.combine.length}）`);
  for (const f of FACES) {
    check(
      !!w.combine.find((s) => s.id === "c_" + f),
      `合成滑块 c_${f} 存在`,
    );
  }
  const combineTotal = w.combine.reduce((s, r) => s + r.value, 0);
  check(combineTotal === 100, `合成权重合计 = 100%（实际 ${combineTotal}%）`);
  check(w.combineSum === "100%", `合成合计显示 100%（实际 ${w.combineSum}）`);

  check(!w.hasUndefined, `权重页正文不含 undefined（实际 ${JSON.stringify(w.undefinedSnippets)}）`);
  await page.close();
}

// ── D. /trend 页（live）─────────────────────
{
  const page = await browser.newPage();
  await page.setViewport({ width: 1352, height: 900 });
  await page.setCacheEnabled(false);
  await page.setBypassServiceWorker(true);
  wireErrors(page);

  /* V0.120.0：捕获**页面实际拿到的** payload，而不是门禁顶层提前 fetch 的那份。
     两个理由：
     ① 顶层 fetch 与页面 fetch 之间可能隔几十秒 —— 这段时间里消息面一旦被打分，
        face_weights 就从「消息面被剔除」变成「消息面计入」，拿顶层那份去对账
        页面渲染就是**假红**；
     ② 顶层那份的 URL（?days=60）与页面里结论卡自己拉的（?days=60&target=etf）
        不是同一个 served_cache key ⇒ 分值本来就可能不同。
     结论卡用 trend?target=etf 的 index，决策拆解用 decision/etf 的 trend_index，
     趋势页「运算方法」用 trend?interval=D 的 index —— 三者分别取，不能混用。 */
  const captured = [];
  page.on("response", (resp) => {
    let u;
    try {
      u = new URL(resp.url());
    } catch (e) {
      return;
    }
    if (u.pathname !== "/api/v1/market/gold/trend" && u.pathname !== "/api/v1/decision/etf") return;
    resp
      .text()
      .then((txt) => {
        captured.push({
          path: u.pathname,
          params: Object.fromEntries(u.searchParams.entries()),
          body: JSON.parse(txt),
        });
      })
      .catch(() => {});
  });

  await page.goto(BASE + "/static/trend.html", { waitUntil: "networkidle2" });
  let ready = false;
  try {
    await page.waitForFunction(
      (n) => document.querySelectorAll("#flowFactors .macro-row").length === n,
      { timeout: 120000 },
      6,
    );
    ready = true;
  } catch (e) {
    const dump = await page
      .evaluate(() => ({
        rows: document.querySelectorAll("#flowFactors .macro-row").length,
        info: document.getElementById("flowInfo")?.textContent?.trim() || "",
      }))
      .catch(() => null);
    check(false, `趋势页资金流面渲染 6 行：${e.message}；页面当时 ${JSON.stringify(dump)}`);
  }
  if (ready) check(true, "趋势页资金流面渲染 6 行");

  /* 结论卡（synthesis-card.js）与决策拆解（decision-explainer.js）各自**另外发一个
     fetch**（?days=60&target=etf 与 /api/v1/decision/etf）⇒ 渲染时刻晚于趋势页主体。
     冷缓存（服务器刚重启 / served_cache 未命中）下这两个请求要几秒，
     不显式等就会在卡片还没画出来时就去断言 ⇒ **假红**（实测踩过：
     门禁首跑 174 passed / 12 failed，全部是 D2 的「渲染 0 个面」）。 */
  try {
    await page.waitForFunction(
      () =>
        document.querySelectorAll("#synthesisCard .syn-bars .syn-row").length === 4 &&
        document.querySelectorAll("#synthesisCard .de-breakdown .de-row").length === 4,
      { timeout: 60000 },
    );
    check(true, "结论卡 + 决策拆解各渲染 4 行");
  } catch (e) {
    const dump = await page
      .evaluate(() => ({
        syn: document.querySelectorAll("#synthesisCard .syn-bars .syn-row").length,
        de: document.querySelectorAll("#synthesisCard .de-breakdown .de-row").length,
      }))
      .catch(() => null);
    check(false, `结论卡 + 决策拆解各渲染 4 行：${e.message}；页面当时 ${JSON.stringify(dump)}`);
  }

  const pick = (path, pred) => {
    const hits = captured.filter((c) => c.path === path && pred(c.params));
    return hits.length ? hits[hits.length - 1].body : null;
  };
  // 趋势页主体自己用的 payload（?interval=D）/ 结论卡（?target=etf）/ 决策拆解（decision/etf）
  const pageIdx =
    pick("/api/v1/market/gold/trend", (p) => p.interval === "D")?.index || trend?.index || null;
  const cardIdx = pick("/api/v1/market/gold/trend", (p) => p.target === "etf")?.index || null;
  const decIdx = pick("/api/v1/decision/etf", () => true)?.trend_index || null;
  check(
    !!pageIdx?.face_weights && typeof pageIdx.face_weights === "object",
    "页面实际拿到的响应含 index.face_weights",
  );

  const t = await page.evaluate(() => {
    const rows = [...document.querySelectorAll("#flowFactors .macro-row")].map((el) => ({
      name: el.querySelector(".nm")?.textContent?.trim() || "",
      val: el.querySelector(".val")?.textContent?.trim() || "",
      dt: el.querySelector(".dt")?.textContent?.trim() || "",
      chips: [...el.querySelectorAll(".nm .src")].map((c) => c.textContent.trim()),
      warnChips: [...el.querySelectorAll(".src")].filter(
        (c) => c.textContent.includes("滞后") || c.textContent.includes("滞后"),
      ),
    }));
    return {
      rows,
      info: document.getElementById("flowInfo")?.textContent?.trim() || "",
      method: document.getElementById("idxMethod")?.textContent?.trim() || "",
      hasUndefined: (document.body.innerText || "").includes("undefined"),
    };
  });

  for (const row of t.rows) {
    check(row.name.length > 0, `资金流行有名称：${row.name}`);
    check(
      row.chips.some((c) => c === "周度" || c === "月度"),
      `资金流行挂周度/月度 chip：${row.name} → ${JSON.stringify(row.chips)}`,
    );
    check(
      !row.chips.some((c) => c.includes("滞后")),
      `资金流行不亮滞后红灯：${row.name} → ${JSON.stringify(row.chips)}`,
    );
  }
  const weeklyRows = t.rows.filter((r) => r.chips.includes("周度")).length;
  const monthlyRows = t.rows.filter((r) => r.chips.includes("月度")).length;
  check(weeklyRows === 3, `3 个周频因子挂「周度」（实际 ${weeklyRows}）`);
  check(monthlyRows === 3, `3 个月频因子挂「月度」（实际 ${monthlyRows}）`);

  check(t.info.length > 0, `资金流面标题行有内容：${t.info}`);
  check(t.info.includes("周度") && t.info.includes("月度"), `标题行含周/月权重：${t.info}`);

  // 公式必须显示**实际生效**的面（被剔除的面不进公式 —— 公式 = 实际算法）。
  // ⚠ 不能无条件断言「消息面必在公式里」：消息面未打分时它被剔除，
  //   公式里就不该有它（硬塞进去 = 公式 ≠ 算法）。判据取后端下发的
  //   index.face_weights（实际生效），不是配置原值 face_weights_nominal。
  const faceW = pageIdx?.face_weights;
  check(!!faceW && typeof faceW === "object", "响应含 index.face_weights");
  if (faceW && typeof faceW === "object") {
    for (const f of FACES) {
      const inFormula = t.method.includes(FACE_TXT[f]);
      if (faceW[f] != null) {
        check(inFormula, `「运算方法」含生效面「${FACE_TXT[f]}」：${t.method}`);
        // 权重取自后端（整数百分比，toFixed(0)）—— 用数值比对，容差 1
        const pct = Math.round(faceW[f] * 100);
        check(
          t.method.includes(`${FACE_TXT[f]}×${pct}%`),
          `「运算方法」里「${FACE_TXT[f]}」权重 = ${pct}%（实际 ${t.method}）`,
        );
      } else {
        check(!inFormula, `「运算方法」不含被剔除的面「${FACE_TXT[f]}」：${t.method}`);
      }
    }
  }
  check(
    !/×\s*30%\s*\+\s*宏观[^%]*×\s*40%/.test(t.method),
    `「运算方法」不再是硬编码 30/40（实际 ${t.method}）`,
  );
  check(!t.hasUndefined, "趋势页正文不含 undefined");

  // ── D2. 首页综合研判结论卡（synthesis-card.js）：4 个面 + 权重来自后端 ──
  const syn = await page.evaluate(() => {
    const card = document.getElementById("synthesisCard");
    const headEl = card?.querySelector(".syn-bars-head");
    const head = headEl?.textContent?.trim() || "";
    /* 公式本体是 head 的**第一个文本节点**；后面的 <span> 是「本次未计入：…」提示。
       两者混在一起判会把「未计入提示里提到某面」误判成「公式里含该面」。 */
    const headFormula = headEl?.firstChild?.textContent?.trim() || "";
    const rows = [...(card?.querySelectorAll(".syn-bars .syn-row") || [])].map((el) => ({
      name: el.querySelector(".nm")?.textContent?.trim() || "",
      val: el.querySelector(".val")?.textContent?.trim() || "",
      wt: el.querySelector(".wt")?.textContent?.trim() || "",
      dir: el.querySelector(".dir")?.textContent?.trim() || "",
      miss: el.classList.contains("syn-row-miss"),
    }));
    const bdRows = [...(card?.querySelectorAll(".de-breakdown .de-row") || [])].map((el) => ({
      name: el.querySelector(".de-nm")?.textContent?.trim() || "",
      wt: el.querySelector(".de-wt")?.textContent?.trim() || "",
      contrib: el.querySelector(".de-contrib")?.textContent?.trim() || "",
      miss: el.classList.contains("de-row-miss"),
    }));
    const bdFormula = card?.querySelector(".de-formula")?.textContent?.trim() || "";
    const verdict = card?.querySelector(".syn-verdict")?.textContent?.trim() || "";
    /* 卡片自己请求的是 ?days=60&target=etf，与门禁顶层 fetch 的 ?days=60 不是同一份
       缓存 ⇒ 综合指数分值可能不同。对比必须用**卡片页面上显示的那个数**。 */
    const cardScore = parseFloat(
      (card?.querySelector(".syn-score .n")?.textContent || "").trim(),
    );
    return { head, headFormula, rows, bdRows, bdFormula, verdict, cardScore };
  });

  check(syn.rows.length === 4, `结论卡渲染 4 个面（实际 ${syn.rows.length}）`);
  for (const f of FACES) {
    const row = syn.rows.find((r) => r.name.includes(FACE_TXT[f]));
    check(!!row, `结论卡有「${FACE_TXT[f]}」行：${JSON.stringify(syn.rows.map((r) => r.name))}`);
  }
  // 标题公式：只含生效面；权重合计 = 100%（数值比对，不做子串匹配）
  const headPcts = (syn.headFormula.match(/(\d+(?:\.\d+)?)%/g) || []).map((s) => parseFloat(s));
  const headSum = headPcts.reduce((a, b) => a + b, 0);
  check(
    numEq(headSum, 100, 0.6),
    `结论卡标题公式权重合计 = 100%（实际 ${headSum}%，来自 ${JSON.stringify(headPcts)}）`,
  );
  // 结论卡的判据用**它自己那份 payload**（?target=etf）的 face_weights，不是门禁顶层那份
  const cardFaceW = cardIdx?.face_weights || faceW;
  for (const f of FACES) {
    const inHead = syn.headFormula.includes(FACE_TXT[f]);
    if (cardFaceW && cardFaceW[f] != null) {
      check(inHead, `结论卡标题公式含生效面「${FACE_TXT[f]}」：${syn.headFormula}`);
    } else {
      check(!inHead, `结论卡标题公式不含被剔除的面「${FACE_TXT[f]}」：${syn.headFormula}`);
    }
  }
  check(
    !/技术\s*30%/.test(syn.headFormula) && !/宏观\s*40%/.test(syn.headFormula),
    `结论卡标题不再是硬编码 30/40（实际 ${syn.headFormula}）`,
  );
  // 被剔除的面必须标「未计入」（不能画成中性 50 —— 那会把「没数据」说成「多空平衡」）
  if (cardFaceW && typeof cardFaceW === "object") {
    for (const f of FACES) {
      const row = syn.rows.find((r) => r.name.includes(FACE_TXT[f]));
      if (!row) continue;
      if (cardFaceW[f] == null) {
        check(row.miss && row.val === "—", `结论卡「${FACE_TXT[f]}」标未计入且分值为 —：${JSON.stringify(row)}`);
      } else {
        check(!row.miss && row.val !== "—", `结论卡「${FACE_TXT[f]}」有分值：${JSON.stringify(row)}`);
      }
    }
  }
  // 决策拆解：4 行；各面贡献相加 = 综合指数（公式 ≠ 算法的老 bug 就是这里）
  check(syn.bdRows.length === 4, `决策拆解渲染 4 行（实际 ${syn.bdRows.length}）`);
  const contribs = syn.bdRows
    .filter((r) => !r.miss)
    .map((r) => parseFloat((r.contrib.match(/[-+]?\d+(?:\.\d+)?/) || ["NaN"])[0]))
    .filter((n) => Number.isFinite(n));
  const contribSum = contribs.reduce((a, b) => a + b, 0);
  const idxScore = syn.cardScore;
  check(
    Number.isFinite(idxScore) && Math.abs(contribSum - idxScore) <= 0.25,
    `决策拆解各面贡献相加 = 卡片上的综合指数 ${idxScore}（实际 ${contribSum}）`,
  );
  // 决策拆解的权重来自 /api/v1/decision/etf 的 trend_index（与结论卡那份不是同一个 key）
  const decFaceW = decIdx?.face_weights || cardFaceW;
  check(
    syn.bdFormula.includes(FACE_TXT.flow) || (decFaceW && decFaceW.flow == null),
    `决策拆解公式含资金流面：${syn.bdFormula}`,
  );
  check(!syn.verdict.includes("undefined"), "结论卡一句话总判不含 undefined");

  await page.close();
}

// ── E. 反向验证（阳性对照）：mock 掉 flow 段 ⇒ 页面不得出现资金流面 ──
{
  if (!trend) {
    check(false, "E 反向验证：缺少真实响应 payload，无法构造 mock");
  } else {
    const mock = JSON.parse(JSON.stringify(trend));
    delete mock.flow;
    if (mock.index && mock.index.face_weights) delete mock.index.face_weights.flow;
    if (mock.index && mock.index.face_weights_nominal) delete mock.index.face_weights_nominal.flow;
    const mockBody = JSON.stringify(mock);

    const page = await browser.newPage();
    await page.setViewport({ width: 1352, height: 900 });
    await page.setCacheEnabled(false);
    await page.setBypassServiceWorker(true);
    wireErrors(page);
    let mocked = 0;
    await page.setRequestInterception(true);
    page.on("request", (req) => {
      if (req.url().includes("/api/v1/market/gold/trend")) {
        mocked++;
        req.respond({
          status: 200,
          contentType: "application/json; charset=utf-8",
          body: mockBody,
        });
        return;
      }
      req.continue();
    });

    await page.goto(BASE + "/static/trend.html", { waitUntil: "networkidle2" });
    let ready = false;
    try {
      await page.waitForFunction(
        () => document.getElementById("idxNum")?.textContent?.trim() !== "",
        { timeout: 60000 },
      );
      ready = true;
    } catch (e) {
      check(false, `E 反向验证：mock 页面加载失败：${e.message}`);
    }
    check(mocked > 0, `E 反向验证：mock 命中了 trend 请求（拦截 ${mocked} 次）`);

    if (ready) {
      const e = await page.evaluate(() => ({
        rows: document.querySelectorAll("#flowFactors .macro-row").length,
        info: document.getElementById("flowInfo")?.textContent?.trim() || "",
        method: document.getElementById("idxMethod")?.textContent?.trim() || "",
      }));
      check(
        e.rows === 0,
        `E 反向验证：mock 掉 flow 后**不得**渲染资金流行（实际 ${e.rows} 行）`,
      );
      check(
        !e.info.includes("资金流面"),
        `E 反向验证：mock 掉 flow 后标题行**不得**出现「资金流面」（实际 ${e.info}）`,
      );
      check(
        !e.method.includes("资金流面"),
        `E 反向验证：mock 掉 flow 后公式**不得**出现「资金流面」（实际 ${e.method}）`,
      );
    }
    await page.close();
  }
}

// ── F. 反向验证（阳性对照）：把 face_weights 换成**旧的 3 面权重** 30/40/30 ──
//
// 目的：证明结论卡标题里的权重**来自后端**而不是前端硬编码。
// 若前端把 25/35/25/15 写死，mock 成 30/40/30 后标题仍是 25/35/25/15 ⇒ 本节必红。
// （E 节证的是「没数据就不画」，F 节证的是「有数据就照着画」。）
{
  if (!trend) {
    check(false, "F 反向验证：缺少真实响应 payload，无法构造 mock");
  } else {
    const mock = JSON.parse(JSON.stringify(trend));
    mock.index = mock.index || {};
    mock.index.face_weights = { tech: 0.3, macro: 0.4, news: 0.3 };
    mock.index.face_weights_nominal = { tech: 0.3, macro: 0.4, news: 0.3 };
    mock.index.components = { tech: 10, macro: 40, news: 60 };
    mock.index.score = 10 * 0.3 + 40 * 0.4 + 60 * 0.3;
    mock.news = { ...(mock.news || {}), scored: true };
    const mockBody = JSON.stringify(mock);

    const page = await browser.newPage();
    await page.setViewport({ width: 1352, height: 900 });
    await page.setCacheEnabled(false);
    await page.setBypassServiceWorker(true);
    wireErrors(page);
    let mocked = 0;
    await page.setRequestInterception(true);
    page.on("request", (req) => {
      if (req.url().includes("/api/v1/market/gold/trend")) {
        mocked++;
        req.respond({
          status: 200,
          contentType: "application/json; charset=utf-8",
          body: mockBody,
        });
        return;
      }
      req.continue();
    });

    await page.goto(BASE + "/static/trend.html", { waitUntil: "networkidle2" });
    let ready = false;
    try {
      await page.waitForFunction(
        () => (document.querySelector("#synthesisCard .syn-bars-head")?.textContent || "").trim() !== "",
        { timeout: 60000 },
      );
      ready = true;
    } catch (e) {
      check(false, `F 反向验证：mock 页面加载失败：${e.message}`);
    }
    check(mocked > 0, `F 反向验证：mock 命中了 trend 请求（拦截 ${mocked} 次）`);

    if (ready) {
      const f = await page.evaluate(() => ({
        head: document.querySelector("#synthesisCard .syn-bars-head")?.textContent?.trim() || "",
        method: document.getElementById("idxMethod")?.textContent?.trim() || "",
        rows: [...document.querySelectorAll("#synthesisCard .syn-bars .syn-row")].map((el) => ({
          name: el.querySelector(".nm")?.textContent?.trim() || "",
          val: el.querySelector(".val")?.textContent?.trim() || "",
          miss: el.classList.contains("syn-row-miss"),
        })),
      }));
      check(
        f.head.includes("技术面 30.0%") && f.head.includes("宏观参考 40.0%") && f.head.includes("消息面 30.0%"),
        `F 反向验证：结论卡标题照着后端的 30/40/30 画（实际 ${f.head}）`,
      );
      check(
        !f.head.includes("25.0%") && !f.head.includes("35.0%"),
        `F 反向验证：结论卡标题**不含**前端写死的 25/35（实际 ${f.head}）`,
      );
      const flowRow = f.rows.find((r) => r.name.includes("资金流面"));
      check(
        !!flowRow && flowRow.miss,
        `F 反向验证：后端没给 flow 时资金流面行标未计入（实际 ${JSON.stringify(flowRow)}）`,
      );
    }
    await page.close();
  }
}

// ── G. i18n 三语实跑（查 textContent，不是 data-lang 属性）──
//
// 只断言「关键文案在 3 种语言下都出现且**互不相同**」—— 非默认语言是动态
// 注入 <script> 取字典，漏引字典文件时只有 zh-CN 正常（见 MEMORY/i18n-dict-default-lang-only）。
//
// ⚠ 等待条件是「标题非空 **且** data-lang 已解析到目标语言」，不是「标题非空」：
//   「非空」只证明渲染过，**证明不了渲染成了哪种语言** ——
//   结论卡是 innerHTML 拼的（没有 data-i18n 标记），字典没到就渲染 ⇒
//   标题照样非空，但内容是**默认语言**（旧实现的真 bug）。
//   等 data-lang（i18n init 解析完语言才写）⇒ 断言落在「语言已定」的稳态上。
{
  const LANGS = [
    { lang: "zh-CN", head: "分面构成", face: "资金流面" },
    { lang: "zh-TW", head: "分面構成", face: "資金流面" },
    { lang: "en-US", head: "Dimension mix", face: "Money flow" },
  ];
  const seenHeads = [];
  for (const L of LANGS) {
    const page = await browser.newPage();
    await page.setViewport({ width: 1352, height: 900 });
    await page.setCacheEnabled(false);
    await page.setBypassServiceWorker(true);
    wireErrors(page);
    await page.evaluateOnNewDocument((lang) => {
      try { localStorage.setItem("pm_lang", lang); } catch (e) {}
    }, L.lang);
    await page.goto(BASE + "/static/trend.html", { waitUntil: "networkidle2" });
    let ready = false;
    try {
      await page.waitForFunction(
        (lang) => {
          const h = (document.querySelector("#synthesisCard .syn-bars-head")?.textContent || "").trim();
          return h !== "" && document.body.getAttribute("data-lang") === lang;
        },
        { timeout: 60000 },
        L.lang,
      );
      ready = true;
    } catch (e) {
      check(false, `G i18n ${L.lang}：页面加载失败：${e.message}`);
    }
    if (ready) {
      const g = await page.evaluate(() => ({
        head: document.querySelector("#synthesisCard .syn-bars-head")?.textContent?.trim() || "",
        body: document.body.innerText || "",
        lang: document.body.getAttribute("data-lang"),
      }));
      check(g.head.includes(L.head), `G i18n ${L.lang}：结论卡标题含「${L.head}」（实际 ${g.head}）`);
      check(g.head.includes(L.face), `G i18n ${L.lang}：结论卡标题含「${L.face}」（实际 ${g.head}）`);
      check(!g.body.includes("undefined"), `G i18n ${L.lang}：页面不含 undefined`);
      seenHeads.push(g.head);
    }
    await page.close();
  }
  check(
    seenHeads.length === LANGS.length,
    `G i18n：3 种语言都渲染出了标题（实际 ${seenHeads.length}/${LANGS.length}）`,
  );
  check(
    new Set(seenHeads).size === seenHeads.length,
    `G i18n：3 种语言的标题文案互不相同（实际 ${JSON.stringify(seenHeads)}）`,
  );
}

// ── G2. i18n 竞态回归：字典晚到也不能把卡片锁死在默认语言 ──
//
// 背景（V0.120.0 实测）：非默认语言的字典靠动态 <script> 取，而结论卡是
// innerHTML 拼出来的（**没有 data-i18n 标记**）⇒ i18n.js 的 apply() 扫不到它。
// 字典尚未加载完就渲染 ⇒ 卡片锁定**默认语言**，而且**永不更新**：
// 此前 init() 不广播 i18n:change（只有手动切语言才广播）⇒ 首次打开页面必错。
//
// 本节把字典请求**延迟 3s**（比 API 慢），断言卡片最终仍渲染成繁体。
// ⚠ 这是本节的**阳性对照**：撤掉「渲染前等 I18n.ready」必须变红。
{
  const page = await browser.newPage();
  await page.setViewport({ width: 1352, height: 900 });
  await page.setCacheEnabled(false);
  await page.setBypassServiceWorker(true);
  wireErrors(page);
  await page.evaluateOnNewDocument(() => {
    try { localStorage.setItem("pm_lang", "zh-TW"); } catch (e) {}
  });
  await page.setRequestInterception(true);
  page.on("request", async (req) => {
    if (req.url().endsWith("/static/i18n/zh-TW.js")) {
      await new Promise((r) => setTimeout(r, 3000));
    }
    req.continue().catch(() => {});
  });
  await page.goto(BASE + "/static/trend.html", { waitUntil: "networkidle2" });
  let head = "";
  try {
    await page.waitForFunction(
      () => (document.querySelector("#synthesisCard .syn-bars-head")?.textContent || "").trim() !== "",
      { timeout: 60000 },
    );
    head = await page.evaluate(
      () => document.querySelector("#synthesisCard .syn-bars-head")?.textContent?.trim() || "",
    );
  } catch (e) {
    check(false, `G2 竞态：结论卡在字典延迟 3s 时始终没渲染出来（${e.message}）`);
  }
  check(
    head.includes("分面構成"),
    `G2 竞态：字典晚到 3s 后结论卡仍是繁体而非默认语言（实际 ${head.slice(0, 40)}）`,
  );
  await page.close();
}

// ── H. 消息面「未打分 ⇒ 被剔除」口径（两处 UI：trend.html 打分器 / news.html 内嵌面板）──
//
// 背景：V0.120.0 之前前端文案写「尚未打分，按**中性 50** 参与评估（占 30% 权重）」——
// 而后端自 V0.100 起就是 score=None：**剔除该面 + 其余面按有效面归一化**。
// 文案与算法相反 ⇒ 用户以为消息面还有一张票，实际它根本没进综合指数。
// 本节断言两处 UI 都不再说「中性 50 计入」，且展示的权重取自后端配置。
{
  let cfg = null;
  try {
    const r = await fetch(BASE + "/api/v1/settings/weights");
    if (r.ok) cfg = (await r.json()).combine || null;
  } catch (e) {
    /* ignore */
  }
  check(
    !!cfg && typeof cfg.news === "number" && typeof cfg.flow === "number",
    `H: 读得到 4 面合成权重配置（实际 ${JSON.stringify(cfg)}）`,
  );
  const newsPct = cfg && typeof cfg.news === "number" ? Math.round(cfg.news * 100) : null;

  // H1. trend.html 的 news-score-widget（#newsScoreCard）
  {
    /* mock 用**真实 schema**（实测今天的返回体原样）—— mock 形状不对时
       前端会走别的分支，门禁就测不到它想测的东西（MEMORY/sig-dict-bug-v083）。 */
    const newsMock = JSON.stringify({
      score_date: "2026-10-28",
      score: null,
      direction: null,
      notes: "",
      scored: false,
      weighted: false,
      slots: [],
      used_slots: 0,
      max_slots: 3,
      remaining_slots: 3,
      next_slot: 1,
      formula: "",
      last_score: 50.0,
      last_date: "2026-10-27",
      last_notes: "",
    });
    const page = await browser.newPage();
    await page.setViewport({ width: 1352, height: 900 });
    await page.setCacheEnabled(false);
    await page.setBypassServiceWorker(true);
    wireErrors(page);
    /* ⚠ 必须显式钉住语言：G 节最后一轮把 pm_lang 留在 en-US，而 puppeteer 的
       browser.newPage() **共用同一个 localStorage** ⇒ 后续页面全是英文，
       中文字面量断言会假红（反过来也会漏判中文错译）。 */
    await page.evaluateOnNewDocument(() => {
      try { localStorage.setItem("pm_lang", "zh-CN"); } catch (e) {}
    });
    let mocked = 0;
    await page.setRequestInterception(true);
    page.on("request", (req) => {
      /* ⚠ 必须按**精确 path** 匹配：`/api/v1/news-score/history?limit=15` 也含这个前缀，
         用 includes() 会把历史记录请求一起 mock 成「今天」的结构 ⇒ 前端拿到对象而不是
         数组 ⇒ 报 "Cannot read properties of undefined (reading 'length')"，
         页面里出现一个与本次改动无关的 undefined，污染断言。 */
      let mp = "";
      try { mp = new URL(req.url()).pathname; } catch (e) { mp = req.url(); }
      if (mp === "/api/v1/news-score") {
        mocked++;
        req.respond({
          status: 200,
          contentType: "application/json; charset=utf-8",
          body: newsMock,
        });
        return;
      }
      req.continue();
    });

    await page.goto(BASE + "/static/trend.html", { waitUntil: "networkidle2" });
    let ready = false;
    try {
      await page.waitForFunction(
        () => (document.querySelector("#newsScoreCard .nsw-alert")?.textContent || "").trim() !== "",
        { timeout: 60000 },
      );
      ready = true;
    } catch (e) {
      check(false, `H1 打分器加载失败：${e.message}`);
    }
    check(mocked > 0, `H1 mock 命中了 news-score 请求（拦截 ${mocked} 次）`);

    if (ready) {
      const h = await page.evaluate(() => ({
        alert: document.querySelector("#newsScoreCard .nsw-alert")?.textContent?.trim() || "",
        score: document.querySelector("#newsScoreCard .nsw-eff .n")?.textContent?.trim() || "",
        effLabel:
          document.querySelector("#newsScoreCard .nsw-eff-meta div")?.textContent?.trim() || "",
        tag: document.querySelector("#newsScoreCard .nsw-tag")?.textContent?.trim() || "",
      }));
      check(
        h.alert.includes("不参与"),
        `H1 打分器提示说消息面「不参与」综合指数：${h.alert}`,
      );
      check(
        !h.alert.includes("中性 50") && !h.tag.includes("中性 50"),
        `H1 打分器不再说「中性 50」（alert=${h.alert} / tag=${h.tag}）`,
      );
      check(
        h.score === "—",
        `H1 未打分时分值显示「—」而不是 50.0（实际 ${JSON.stringify(h.score)}）`,
      );
      check(
        newsPct != null && h.alert.includes(`${newsPct}%`),
        `H1 提示里的权重 = 后端配置权重 ${newsPct}%：${h.alert}`,
      );
      check(
        h.effLabel.includes(`${newsPct}%`),
        `H1 「当日有效消息面分值」标签里的权重 = ${newsPct}%（实际 ${h.effLabel}）`,
      );
    }
    await page.close();
  }

  // H2. news.html 的内嵌打分面板 + intro/页脚的 4 面权重
  {
    const newsMock = JSON.stringify({
      score_date: "2026-10-28",
      score: null,
      direction: null,
      notes: "",
      scored: false,
      weighted: false,
      slots: [],
      used_slots: 0,
      max_slots: 3,
      remaining_slots: 3,
      next_slot: 1,
      formula: "",
      last_score: 50.0,
      last_date: "2026-10-27",
      last_notes: "",
    });
    const page = await browser.newPage();
    await page.setViewport({ width: 1352, height: 900 });
    await page.setCacheEnabled(false);
    await page.setBypassServiceWorker(true);
    wireErrors(page);
    /* ⚠ 必须显式钉住语言：G 节最后一轮把 pm_lang 留在 en-US，而 puppeteer 的
       browser.newPage() **共用同一个 localStorage** ⇒ 后续页面全是英文，
       中文字面量断言会假红（反过来也会漏判中文错译）。 */
    await page.evaluateOnNewDocument(() => {
      try { localStorage.setItem("pm_lang", "zh-CN"); } catch (e) {}
    });
    let mocked = 0;
    await page.setRequestInterception(true);
    page.on("request", (req) => {
      /* ⚠ 必须按**精确 path** 匹配：`/api/v1/news-score/history?limit=15` 也含这个前缀，
         用 includes() 会把历史记录请求一起 mock 成「今天」的结构 ⇒ 前端拿到对象而不是
         数组 ⇒ 报 "Cannot read properties of undefined (reading 'length')"，
         页面里出现一个与本次改动无关的 undefined，污染断言。 */
      let mp = "";
      try { mp = new URL(req.url()).pathname; } catch (e) { mp = req.url(); }
      if (mp === "/api/v1/news-score") {
        mocked++;
        req.respond({
          status: 200,
          contentType: "application/json; charset=utf-8",
          body: newsMock,
        });
        return;
      }
      req.continue();
    });

    await page.goto(BASE + "/static/news.html", { waitUntil: "networkidle2" });
    let ready = false;
    try {
      await page.waitForFunction(
        () => (document.getElementById("scoreAlert")?.textContent || "").trim() !== "",
        { timeout: 60000 },
      );
      ready = true;
    } catch (e) {
      check(false, `H2 news.html 加载失败：${e.message}`);
    }
    check(mocked > 0, `H2 mock 命中了 news-score 请求（拦截 ${mocked} 次）`);

    if (ready) {
      const n = await page.evaluate(() => ({
        alert: document.getElementById("scoreAlert")?.textContent?.trim() || "",
        eff: document.getElementById("effScore")?.textContent?.trim() || "",
        formula: document.getElementById("effFormula")?.textContent?.trim() || "",
        intro: document.getElementById("introWeights")?.textContent?.trim() || "",
        foot: document.getElementById("footNewsWeight")?.textContent?.trim() || "",
        body: document.body.innerText || "",
      }));
      check(
        n.alert.includes("不参与") && !n.alert.includes("中性 50"),
        `H2 news.html 提示条说消息面「不参与」且不含「中性 50」：${n.alert}`,
      );
      check(
        n.eff === "—",
        `H2 news.html 未打分时有效分值显示「—」（实际 ${JSON.stringify(n.eff)}）`,
      );
      check(
        !n.formula.includes("中性 50"),
        `H2 news.html 口径行不含「中性 50」（实际 ${n.formula}）`,
      );
      check(
        newsPct != null && n.alert.includes(`${newsPct}%`),
        `H2 news.html 提示条里的权重 = 后端配置权重 ${newsPct}%：${n.alert}`,
      );
      check(
        newsPct != null && n.foot === `${newsPct}%`,
        `H2 news.html 页脚消息面权重 = ${newsPct}%（实际 ${n.foot}）`,
      );
      // intro：4 个面齐全 + 权重合计 100%
      for (const f of FACES) {
        check(
          n.intro.includes(FACE_TXT_ALT[f]),
          `H2 news.html intro 含「${FACE_TXT_ALT[f]}」：${n.intro}`,
        );
      }
      const introPcts = (n.intro.match(/(\d+(?:\.\d+)?)%/g) || []).map((s) => parseFloat(s));
      const introSum = introPcts.reduce((a, b) => a + b, 0);
      check(
        numEq(introSum, 100, 0.6),
        `H2 news.html intro 四面权重合计 = 100%（实际 ${introSum}%，来自 ${JSON.stringify(introPcts)}）`,
      );
      check(
        !n.intro.includes("技术面 30%") && !n.intro.includes("宏观面 40%"),
        `H2 news.html intro 不再是硬编码 30/40（实际 ${n.intro}）`,
      );
      check(!n.body.includes("undefined"), "H2 news.html 正文不含 undefined");
    }
    await page.close();
  }
}

// ── I. 持仓页「指数构成」：4 面 + 权重来自后端 + 被剔除的面标「未计入」──
//
// 背景：V0.120.0 之前这里硬编码 3 面 30/40/30，且缺失面用 `sc || 0` 渲染 ——
// 消息面未打分时那一行显示「0 分」（红/绿条 0%），看着像「看空 0 分」，
// 而它其实是「没进综合指数」。⇒ 必须显式标「未计入」。
{
  const page = await browser.newPage();
  await page.setViewport({ width: 1352, height: 900 });
  await page.setCacheEnabled(false);
  await page.setBypassServiceWorker(true);
  wireErrors(page);
  await page.evaluateOnNewDocument(() => {
    try { localStorage.setItem("pm_lang", "zh-CN"); } catch (e) {}
  });

  await page.goto(BASE + "/portfolio", { waitUntil: "networkidle2" });
  let ready = false;
  try {
    await page.waitForFunction(
      () => document.querySelectorAll(".composition .comp-row").length > 0,
      { timeout: 60000 },
    );
    ready = true;
  } catch (e) {
    check(false, `I 持仓页「指数构成」未渲染：${e.message}`);
  }

  if (ready) {
    const p = await page.evaluate(() => ({
      title: document.querySelector(".composition .comp-title")?.textContent?.trim() || "",
      rows: [...document.querySelectorAll(".composition .comp-row")].map((el) => ({
        name: el.querySelector(".comp-name")?.textContent?.trim() || "",
        weight: el.querySelector(".comp-weight")?.textContent?.trim() || "",
        score: el.querySelector(".comp-score")?.textContent?.trim() || "",
      })),
      note: document.querySelector(".composition .comp-note")?.textContent?.trim() || "",
    }));
    check(p.rows.length === 4, `I 指数构成渲染 4 行（实际 ${p.rows.length}）`);
    for (const f of FACES) {
      const row = p.rows.find((r) => r.name.includes(FACE_TXT_ALT[f]));
      check(!!row, `I 指数构成有「${FACE_TXT_ALT[f]}」行：${JSON.stringify(p.rows.map((r) => r.name))}`);
    }
    /* ⚠ 只把**生效面**的权重加总：被剔除的面（未计入）显示的是它的**配置权重**，
       那部分权重已被剔除、不参与加权 —— 把 4 行全加起来会得到 125% 之类的假红。 */
    const effPcts = p.rows
      .filter((r) => r.score !== "未计入")
      .map((r) => parseFloat((r.weight.match(/[\d.]+/) || ["NaN"])[0]))
      .filter((n) => Number.isFinite(n));
    const sum = effPcts.reduce((a, b) => a + b, 0);
    check(
      numEq(sum, 100, 0.6),
      `I 指数构成**生效面**权重合计 = 100%（实际 ${sum}%，来自 ${JSON.stringify(effPcts)}）`,
    );
    const droppedRows = p.rows.filter((r) => r.score === "未计入");
    check(
      droppedRows.length <= 1,
      `I 被剔除的面不超过 1 个（实际 ${droppedRows.length}：${JSON.stringify(droppedRows.map((r) => r.name))}）`,
    );
    check(
      !/技术\s*30%/.test(p.title) && !/宏观\s*40%/.test(p.title),
      `I 指数构成标题不再是硬编码 30/40（实际 ${p.title}）`,
    );
    /* 与决策接口的真实 face_weights 对账：行里显示的权重必须等于后端给的值。
       被剔除的面（不在 face_weights 里）显示「未计入」+ 其**配置**权重。 */
    let dw = null;
    try {
      const r = await fetch(BASE + "/api/v1/decision/etf");
      if (r.ok) dw = (await r.json()).trend_index || null;
    } catch (e) {
      /* ignore */
    }
    if (dw && dw.face_weights && typeof dw.face_weights === "object") {
      for (const f of FACES) {
        const row = p.rows.find((r) => r.name.includes(FACE_TXT_ALT[f]));
        if (!row) continue;
        if (dw.face_weights[f] != null) {
          const expect = (dw.face_weights[f] * 100).toFixed(1) + "%";
          check(
            row.weight === expect,
            `I 「${FACE_TXT_ALT[f]}」显示权重 = 后端 face_weights ${expect}（实际 ${row.weight}）`,
          );
          check(
            row.score !== "未计入" && row.score !== "—",
            `I 「${FACE_TXT_ALT[f]}」有分值（实际 ${row.score}）`,
          );
        } else {
          const nominal = dw.face_weights_nominal?.[f];
          const expect = typeof nominal === "number" ? (nominal * 100).toFixed(1) + "%" : null;
          check(
            row.score === "未计入",
            `I 「${FACE_TXT_ALT[f]}」被剔除 ⇒ 标「未计入」（实际 ${row.score}）`,
          );
          check(
            expect == null || row.weight === expect,
            `I 「${FACE_TXT_ALT[f]}」被剔除时显示其配置权重 ${expect}（实际 ${row.weight}）`,
          );
        }
      }
    } else {
      note("I 跳过「权重对账」：决策接口没给 face_weights");
    }
  }
  await page.close();
}

await browser.close();

// ───────────────────── 汇总 ─────────────────────
console.log("\n=== 通过 ===");
for (const l of ok) console.log("  ✓ " + l);
if (warn.length) {
  console.log("\n=== 提示（不算失败，但必须知道这次没测到什么）===");
  for (const l of warn) console.log("  ! " + l);
}
console.log("\n=== 失败 ===");
for (const l of bad) console.log("  ✗ " + l);
if (consoleErrors.length) {
  console.log("\n=== JS 报错 ===");
  for (const l of consoleErrors.slice(0, 8)) console.log("  ! " + l);
}
console.log(`\n结果：${ok.length} passed, ${bad.length} failed`);
if (bad.length || consoleErrors.length) process.exit(1);
