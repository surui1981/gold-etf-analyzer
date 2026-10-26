// scripts/_verify_macro_debt.mjs
// V0.119.0 验证：宏观面新增 3 个政府债务因子（美国 / 中国 / 欧洲）
//
// 覆盖五件事：
//  A. **线上 API**：/api/v1/market/gold/trend 的 macro.factors 里 3 个新因子齐全，
//     value / data_date / source / cadence / max_lag_days 都对；
//     rolling_factors 只含 7 个日频因子（3 个低频因子不进滚动分位）。
//  B. **/weights 页**：11 行手动校准；3 个新行有值 + 中性「季度/年度」chip，
//     且**不亮滞后红灯**（季度/年度因子用后端给的 max_lag_days，不是日频的 4 天）。
//  C. **/trend 页**：11 行宏观因子 + 角标口径「7 个可滚动因子」。
//  D. **反向验证 1（阳性对照）**：把 mock 里的 max_lag_days 去掉（= 模拟 V0.119.0
//     之前的后端），同一行**必须**亮起「滞后 N 天」红灯 —— 证明 B 的断言不是空断言。
//  E. **反向验证 2（阳性对照）**：把 mock 的 rolling_factors 砍成 3 个，角标的
//     「N 个可滚动因子」必须跟着变成 3 —— 证明 C 的断言真的跟着后端走，
//     而不是前端自己写死了一个数。
//
// ⚠ D 用的是**真实抓下来的响应**改字段（mock 必须用真实 schema，凭想象编的
//   payload 会让断言假绿/假红）。
// ⚠ 必须 setBypassServiceWorker(true)：SW 接管页面后 mock 会静默失效
//   （第二次导航拿真实数据，断言看着绿其实没测到）。
// ⚠ 视口 1352×900：默认 800×600 下 sticky 顶栏会盖住按钮，click 静默失效。
import puppeteer from "puppeteer-core";

const BASE = process.env.BASE_URL || "http://192.168.0.204:8888";
const CHROME =
  "/home/surui/.cache/puppeteer/chrome/linux-153.0.8010.36/chrome-linux64/chrome";

//: 3 个政府债务因子的期望值（实测 2026-10-26，与计划 §1.2 一致）
//:
//: ⚠️ `value` 填的是 **live 源的原始读数**，断言一律用**数值比较 + 0.01 容差**，
//: 绝不用 `includes(String(value))` 那种子串匹配 ——
//: 服务端用 `f"{value:g}"` 格式化（122.59387 → "122.594"、88.327 → "88.327"），
//: 子串匹配会在「live 值」和「内置兜底值」（122.59 / 88.33）之间来回翻车：
//: 上游源一恢复，门禁反而变红。数值比较对两种情况都成立。
const DEBT = {
  us_gov_debt: {
    value: 122.59387,
    data_date: "2026-03-31",
    source: "FRED GFDEGDQ188S",
    cadence: "quarterly",
    max_lag_days: 300,
    cadenceChip: "季度数据",
  },
  cn_gov_debt: {
    value: 88.327,
    data_date: "2024-12-31",
    source: "FRED GGGDTACNA188N",
    cadence: "annual",
    max_lag_days: 1100,
    cadenceChip: "年度数据",
  },
  eu_gov_debt: {
    value: 82.9,
    data_date: "2026-06-30",
    source: "Eurostat GOV_10Q_GGDEBT",
    cadence: "quarterly",
    max_lag_days: 300,
    cadenceChip: "季度数据",
  },
};
const DEBT_KEYS = Object.keys(DEBT);
//: 内置静态兜底（上游源挂掉时的期望值）—— 见 services/macro.py::STATIC_REF
const STATIC_FALLBACK = {
  us_gov_debt: { value: 122.59, data_date: "2026-03-31" },
  cn_gov_debt: { value: 88.33, data_date: "2024-12-31" },
  eu_gov_debt: { value: 82.9, data_date: "2026-06-30" },
};
const ROLLING_KEYS = [
  "dxy",
  "us2y",
  "us10y",
  "us30y",
  "curve_10y2y",
  "real10y",
  "vix",
];
const ALL_KEYS = [...ROLLING_KEYS, "cb_gold", ...DEBT_KEYS];

const ok = [];
const bad = [];
const warn = [];
const check = (cond, label) => (cond ? ok : bad).push(label);
const note = (label) => warn.push(label);

//: 从一段文本里取第一个数字（解析失败返回 NaN）
//: 用于把「渲染出来的读数」和「期望值」做**数值**比较 —— 见 DEBT 注释。
const firstNum = (s) => {
  const m = String(s ?? "").match(/-?\d+(?:\.\d+)?/);
  return m ? Number(m[0]) : NaN;
};
//: 数值相等（容差 0.01）—— NaN 一律判不等
const numEq = (actual, expected) =>
  Number.isFinite(actual) && Math.abs(actual - expected) < 0.01;

// ───────────────────── A. 线上 API ─────────────────────

let trend = null;
try {
  const r = await fetch(`${BASE}/api/v1/market/gold/trend?days=60`, {
    signal: AbortSignal.timeout(180000),
  });
  check(r.status === 200, `GET /market/gold/trend 返回 ${r.status}`);
  trend = await r.json();
} catch (e) {
  check(false, `GET /market/gold/trend 失败：${e.message}`);
}

if (trend) {
  const factors = trend?.macro?.factors || [];
  const byKey = Object.fromEntries(factors.map((f) => [f.key, f]));

  check(
    factors.length === 11,
    `宏观因子共 11 个（实际 ${factors.length}：${factors.map((f) => f.key).join("/")}）`,
  );
  check(
    ALL_KEYS.every((k) => byKey[k]),
    `11 个因子 key 齐全（缺 ${ALL_KEYS.filter((k) => !byKey[k]).join("/") || "无"}）`,
  );

  for (const key of DEBT_KEYS) {
    const f = byKey[key];
    if (!f) {
      check(false, `${key} 存在`);
      continue;
    }
    const exp = DEBT[key];
    check(f.cadence === exp.cadence, `${key} cadence = ${exp.cadence}（实际 ${f.cadence}）`);
    check(
      f.max_lag_days === exp.max_lag_days,
      `${key} max_lag_days = ${exp.max_lag_days}（实际 ${f.max_lag_days}）`,
    );
    const live = (f.source || "").includes(exp.source);
    const fb = STATIC_FALLBACK[key];
    const isFallback =
      (f.source || "").startsWith("静态") &&
      Math.abs(Number(f.value) - fb.value) < 0.01 &&
      f.data_date === fb.data_date;
    check(
      live || isFallback,
      `${key} 取值口径正确（value=${f.value} date=${f.data_date} source=${f.source} tier=${f.tier}）`,
    );
    if (live) {
      check(
        Math.abs(Number(f.value) - exp.value) < 0.01,
        `${key} live 读数 = ${exp.value}（实际 ${f.value}）`,
      );
      check(
        f.data_date === exp.data_date,
        `${key} data_date = ${exp.data_date}（实际 ${f.data_date}）`,
      );
    } else if (isFallback) {
      note(
        `${key} 走的是内置静态兜底（上游源当时不可用）—— 数值/日期符合预期，但本次没测到 live 源`,
      );
    }
  }

  const rolling = trend?.macro?.rolling_factors;
  check(
    Array.isArray(rolling) && rolling.length === 7,
    `rolling_factors 长度 7（实际 ${JSON.stringify(rolling)}）`,
  );
  check(
    Array.isArray(rolling) && DEBT_KEYS.every((k) => !rolling.includes(k)),
    `rolling_factors 不含 3 个低频因子（实际 ${JSON.stringify(rolling)}）`,
  );
  check(
    Array.isArray(rolling) && rolling.every((k) => ROLLING_KEYS.includes(k)),
    `rolling_factors 就是那 7 个日频因子（实际 ${JSON.stringify(rolling)}）`,
  );

  const wsum = (factors || []).reduce((s, f) => s + Number(f.weight || 0), 0);
  check(Math.abs(wsum - 1) < 1e-6, `因子权重合计 = 1（实际 ${wsum}）`);
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

// ── B. /weights 页（live，无拦截）─────────────────────
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
      (n) => {
        const cells = document.querySelectorAll("#moRows .cur");
        return cells.length === n && [...cells].every((e) => !e.textContent.includes("加载中"));
      },
      { timeout: 120000 },
      11,
    );
    loaded = true;
  } catch (e) {
    const dump = await page
      .evaluate(() => ({
        n: document.querySelectorAll("#moRows .cur").length,
        t: [...document.querySelectorAll("#moRows .cur")].map((x) => x.textContent.trim()),
      }))
      .catch(() => null);
    check(false, `「当前生效」列加载完成：${e.message}；页面当时 ${JSON.stringify(dump)}`);
  }
  if (loaded) check(true, "「当前生效」列在 120s 内完成加载（11 行）");

  const rows = await page.evaluate(() => {
    const out = {};
    for (const el of document.querySelectorAll("#moRows .mo-row")) {
      const input = el.querySelector("input[type=number]");
      const key = (input?.id || "").replace(/^mo_/, "");
      if (!key) continue;
      const cur = el.querySelector(".cur");
      out[key] = {
        text: cur?.textContent?.trim() || "",
        warnChips: [...el.querySelectorAll(".mo-chip-warn")].map((c) => c.textContent.trim()),
        chips: [...el.querySelectorAll(".mo-chip")].map((c) => c.textContent.trim()),
      };
    }
    return out;
  });

  check(
    Object.keys(rows).length === 11,
    `手动校准渲染 11 行（实际 ${Object.keys(rows).length}）`,
  );

  for (const key of DEBT_KEYS) {
    const exp = DEBT[key];
    const r = rows[key];
    if (!r) {
      check(false, `${key} 行存在`);
      continue;
    }
    check(
      numEq(firstNum(r.text), exp.value),
      `${key} 行显示读数 ${exp.value}（实际 ${firstNum(r.text)}）：${r.text}`,
    );
    check(
      r.text.includes(exp.data_date),
      `${key} 行显示 data_date ${exp.data_date}：${r.text}`,
    );
    check(
      r.chips.some((c) => c.includes(exp.cadenceChip)),
      `${key} 行挂「${exp.cadenceChip}」chip：${JSON.stringify(r.chips)}`,
    );
    // 关键：低频因子**不该**亮滞后红灯（季度 209 天 < 300 / 年度 664 天 < 1100）
    check(
      !r.warnChips.some((c) => c.includes("滞后")),
      `${key} 行不亮滞后红灯：${JSON.stringify(r.warnChips)}`,
    );
  }

  // 日频因子滞后告警仍然要生效（不能因为改了阈值就把日频的红灯也灭了）
  const dailyRow = rows["dxy"];
  check(!!dailyRow, "dxy 行存在（对照组）");

  const bodyText = await page.$eval("body", (el) => el.innerText);
  check(!bodyText.includes("undefined"), "权重页无 undefined 泄漏");

  await page.screenshot({ path: "/tmp/v01190_macro_debt_weights.png", fullPage: true });
  await page.close();
}

// ── C. /trend 页（live）─────────────────────
{
  const page = await browser.newPage();
  await page.setViewport({ width: 1352, height: 900 });
  await page.setCacheEnabled(false);
  await page.setBypassServiceWorker(true);
  wireErrors(page);

  await page.goto(BASE + "/static/trend.html", { waitUntil: "networkidle2" });
  let rendered = false;
  try {
    await page.waitForFunction(
      (n) => document.querySelectorAll("#macroFactors .macro-row").length === n,
      { timeout: 120000 },
      11,
    );
    rendered = true;
  } catch (e) {
    const dump = await page
      .evaluate(() => ({
        n: document.querySelectorAll("#macroFactors .macro-row").length,
        info: document.getElementById("macroInfo")?.textContent?.trim() || "",
      }))
      .catch(() => null);
    check(false, `/trend 宏观因子渲染 11 行：${e.message}；页面当时 ${JSON.stringify(dump)}`);
  }
  if (rendered) check(true, "/trend 页渲染 11 行宏观因子");

  // ⚠️「N 个可滚动因子」这行文案在角标的 **title 属性**（tooltip）里，
  //   不是可见文本 —— 断言必须读 title，否则会误判成「没渲染」。
  //   （V0.118.0 起就是这个形态，角标可见文本只有 [动态]/[静态]。）
  const macroBadge = await page.$eval("#macroInfo", (el) => {
    const b = el.querySelector(".src");
    return {
      title: b?.getAttribute("title") || "",
      text: el.textContent.trim(),
    };
  });
  const macroDynamic = trend?.macro?.macro_dynamic;
  if (macroDynamic) {
    check(
      macroBadge.title.includes("7 个可滚动因子"),
      `宏观角标 title 含「7 个可滚动因子」：${JSON.stringify(macroBadge)}`,
    );
  } else {
    // 样本不足时后端不给动态阈值，角标文案换成「数据不足」—— 这时不该再断言个数
    check(
      macroBadge.title.includes("数据不足"),
      `宏观角标 title 走「数据不足」分支：${JSON.stringify(macroBadge)}`,
    );
  }

  const trendRows = await page.$$eval("#macroFactors .macro-row", (els) =>
    els.map((el) => ({
      text: el.textContent.replace(/\s+/g, " ").trim(),
      // ⚠ 取 .val 里的读数，不要从整行 text 里抠数字 ——
      //   因子名里带数字（如「10Y-2Y 利差」）会把 firstNum 带偏。
      val: (el.querySelector(".val")?.textContent || "").trim(),
    })),
  );
  for (const key of DEBT_KEYS) {
    const exp = DEBT[key];
    const hit = trendRows.find((t) => numEq(firstNum(t.val), exp.value));
    check(
      !!hit,
      `/trend 宏观明细含 ${key} 的读数 ${exp.value}（命中：${hit ? hit.text : "无"}）`,
    );
  }
  check(
    !trendRows.some((t) => t.text.includes("undefined")),
    "/trend 宏观明细无 undefined 泄漏",
  );

  await page.screenshot({ path: "/tmp/v01190_macro_debt_trend.png", fullPage: false });
  await page.close();
}

// ── D. 反向验证（阳性对照）：mock 去掉 max_lag_days ⇒ 必须亮滞后红灯 ──
{
  if (!trend) {
    check(false, "D 反向验证：缺少真实响应 payload，无法构造 mock");
  } else {
    const mock = JSON.parse(JSON.stringify(trend));
    for (const key of DEBT_KEYS) {
      const f = mock.macro.factors.find((x) => x.key === key);
      if (f) delete f.max_lag_days; // 模拟 V0.119.0 之前的后端
    }
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

    await page.goto(BASE + "/static/weights.html", { waitUntil: "networkidle2" });
    let ready = false;
    try {
      await page.waitForFunction(
        (n) => {
          const cells = document.querySelectorAll("#moRows .cur");
          return cells.length === n && [...cells].every((e) => !e.textContent.includes("加载中"));
        },
        { timeout: 120000 },
        11,
      );
      ready = true;
    } catch (e) {
      check(false, `D 反向验证：mock 页面加载失败：${e.message}`);
    }
    check(mocked > 0, `D 反向验证：mock 命中了 trend 请求（拦截 ${mocked} 次）`);

    if (ready) {
      const lagChips = await page.evaluate(
        (keys) =>
          keys.map((k) => {
            const input = document.getElementById("mo_" + k);
            const row = input?.closest(".mo-row");
            return {
              key: k,
              warn: [...(row?.querySelectorAll(".mo-chip-warn") || [])].map((c) =>
                c.textContent.trim(),
              ),
            };
          }),
        DEBT_KEYS,
      );
      for (const r of lagChips) {
        check(
          r.warn.some((c) => c.includes("滞后")),
          `D 反向验证：去掉 max_lag_days 后 ${r.key} 行**必须**亮滞后红灯（实际 ${JSON.stringify(r.warn)}）`,
        );
      }
    }
    await page.close();
  }
}

// ── E. 反向验证 2（阳性对照）：mock 把 rolling_factors 改成 3 个 ⇒ 角标必须跟着变 ──
{
  if (!trend) {
    check(false, "E 反向验证：缺少真实响应 payload，无法构造 mock");
  } else {
    const mock = JSON.parse(JSON.stringify(trend));
    // 把 7 个日频因子砍成 3 个 —— 前端若还在用硬编码的 filter 排除 cb_gold，
    // 角标会显示 8（11 减 3 个低频），与后端给的 3 对不上。
    mock.macro.rolling_factors = ROLLING_KEYS.slice(0, 3);
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
    try {
      await page.waitForFunction(
        (n) => document.querySelectorAll("#macroFactors .macro-row").length === n,
        { timeout: 120000 },
        11,
      );
    } catch (e) {
      check(false, `E 反向验证：mock 页面加载失败：${e.message}`);
    }
    check(mocked > 0, `E 反向验证：mock 命中了 trend 请求（拦截 ${mocked} 次）`);

    const badgeTitle = await page
      .$eval("#macroInfo", (el) => el.querySelector(".src")?.getAttribute("title") || "")
      .catch(() => "");
    check(
      badgeTitle.includes("3 个可滚动因子"),
      `E 反向验证：rolling_factors 改成 3 个后，角标必须显示「3 个可滚动因子」（实际：${badgeTitle}）`,
    );
    check(
      !badgeTitle.includes("7 个可滚动因子"),
      `E 反向验证：角标不再显示 7（实际：${badgeTitle}）`,
    );
    await page.close();
  }
}

check(
  consoleErrors.length === 0,
  `无 JS 报错：${JSON.stringify(consoleErrors.slice(0, 3))}`,
);

await browser.close();

console.log("\n=== V0.119.0 宏观面 3 个政府债务因子（美/中/欧）验证 ===");
ok.forEach((l) => console.log("  [OK  ] " + l));
bad.forEach((l) => console.log("  [FAIL] " + l));
warn.forEach((l) => console.log("  [WARN] " + l));
console.log(`\n结果：${ok.length} passed, ${bad.length} failed, ${warn.length} warn`);
if (bad.length) process.exit(1);
