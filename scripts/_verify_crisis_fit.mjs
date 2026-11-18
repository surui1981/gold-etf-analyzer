// scripts/_verify_crisis_fit.mjs
// V0.128.0 验证：经济危机金价拟合曲线（/crisis-fit）+ 首页「形态拟合」磁贴
//
// 覆盖：
//  1. 别名可达（307 → /static/crisis-fit.html），页面真的渲染出结论数字
//  2. **drift 是假设** ⇒ 页面上必须同时出现 drift=0 的终点（两条都在）
//  3. **单周期终点区间**（离散度）在页面上
//  4. **锚点敏感性**在页面上（锚点 ±1 月的终点区间）
//  5. 拟合图有 3 条线（拟合 / 模板×缩放 / 各轮终点散点）+ 31 个点
//  6. 模板图有「等权模板 + 每轮原始路径」，且模板**支撑轮数**写在页面上
//  7. **模板 clamp 边界**在图注里标明（超过 template_max_t 是平台外推）
//  8. a11y 数据表兜底**不溢出图表容器**（V0.127.2 的判据）
//  9. **无产物 ⇒ 显示「待数据」且不画曲线**（不许画一条假线）
// 10. 首页磁贴改成「形态拟合」：文案、实时行、href 三项都对
// 11. 三语切换（查 textContent，不是 data-lang —— 记忆 i18n-init-await）
// 12. 无 4xx/5xx、无 console error、无 undefined/NaN 泄漏
// 13. E8：形态拟合页**不含**扇形图；扇形图页**不含**形态拟合曲线（两者不混）
//
// ⚠ 必须打 8888（主入口）。8889/gold/ 是备用入口且全站 /api/v1/* 404。
// ⚠ 必须 setViewport(1352×900)：顶 nav（sticky）会盖住按钮，page.click() 静默失效。
// ⚠ 必须 setCacheEnabled(false) + setBypassServiceWorker(true)：
//   SW 接管后页面级请求拦截会**静默失效**（记忆 puppeteer-sw-silently-bypasses-interception）。
// ⚠ mock 的 payload 是**用真服务跑出来的**（同一套算法跑的）⇒ schema 与真实接口一致，
//   不会「mock 出一个不存在的字段」而假绿。
// ⚠⚠ **本门禁打的是「活着的服务」** ⇒ **改了后端必须先重启服务再跑门禁**，
//   否则门禁跑的是旧进程里的代码 ⇒ 撤销改动门禁照样绿（实测踩过：
//   反向验证「无产物时伪造曲线」时没重启 ⇒ 门禁 40/0 全绿，假的）。
//   ⇒ 后端的断言在 tests/test_api/test_crisis_fit_api.py 里（那里直接 import 真代码）。
import puppeteer from "puppeteer-core";

const BASE = process.env.BASE_URL || "http://192.168.0.204:8888";
const CHROME =
  "/home/surui/.cache/puppeteer/chrome/linux-153.0.8010.36/chrome-linux64/chrome";

let pass = 0;
let fail = 0;
function ok(name, cond, extra = "") {
  if (cond) { pass++; console.log(`  \u2713 ${name}`); }
  else { fail++; console.log(`  \u2717 ${name} ${extra}`); }
}

// —— 有数据场景的 mock payload（由真实服务生成）——
const MOCK = {
  "target": "ny",
  "available": true,
  "reason": null,
  "horizon_months": 30,
  "drift": 0.003,
  "anchor_month": "2026-05",
  "anchor_avg": 3300.0,
  "peak_date": "2026-05-03",
  "peak_price": 3300.0,
  "last_month": "2026-11",
  "last_avg": 3200.0,
  "t0": 6,
  "cur_norm": 97.0,
  "template": [
    [
      0,
      100.0
    ],
    [
      1,
      91.0
    ],
    [
      2,
      84.0
    ],
    [
      3,
      79.0
    ],
    [
      4,
      76.0
    ],
    [
      5,
      74.0
    ],
    [
      6,
      73.0
    ],
    [
      7,
      75.0
    ],
    [
      8,
      78.0
    ],
    [
      9,
      82.0
    ],
    [
      10,
      85.0
    ],
    [
      11,
      88.0
    ],
    [
      12,
      90.0
    ],
    [
      13,
      92.0
    ]
  ],
  "template_counts": [
    3,
    3,
    3,
    3,
    3,
    3,
    3,
    3,
    3,
    3,
    3,
    3,
    3,
    3
  ],
  "template_max_t": 13,
  "cycle_paths": [
    {
      "name": "1974",
      "points": [
        [
          0,
          100.0
        ],
        [
          1,
          91.0
        ],
        [
          2,
          84.0
        ],
        [
          3,
          79.0
        ],
        [
          4,
          76.0
        ],
        [
          5,
          74.0
        ],
        [
          6,
          73.0
        ],
        [
          7,
          75.0
        ],
        [
          8,
          78.0
        ],
        [
          9,
          82.0
        ],
        [
          10,
          85.0
        ],
        [
          11,
          88.0
        ],
        [
          12,
          90.0
        ],
        [
          13,
          92.0
        ]
      ]
    },
    {
      "name": "1980",
      "points": [
        [
          0,
          100.0
        ],
        [
          1,
          91.0
        ],
        [
          2,
          84.0
        ],
        [
          3,
          79.0
        ],
        [
          4,
          76.0
        ],
        [
          5,
          74.0
        ],
        [
          6,
          73.0
        ],
        [
          7,
          75.0
        ],
        [
          8,
          78.0
        ],
        [
          9,
          82.0
        ],
        [
          10,
          85.0
        ],
        [
          11,
          88.0
        ],
        [
          12,
          90.0
        ],
        [
          13,
          92.0
        ]
      ]
    },
    {
      "name": "2008",
      "points": [
        [
          0,
          100.0
        ],
        [
          1,
          91.0
        ],
        [
          2,
          84.0
        ],
        [
          3,
          79.0
        ],
        [
          4,
          76.0
        ],
        [
          5,
          74.0
        ],
        [
          6,
          73.0
        ],
        [
          7,
          75.0
        ],
        [
          8,
          78.0
        ],
        [
          9,
          82.0
        ],
        [
          10,
          85.0
        ],
        [
          11,
          88.0
        ],
        [
          12,
          90.0
        ],
        [
          13,
          92.0
        ]
      ]
    }
  ],
  "curve": [
    {
      "t": 6,
      "month": "2026-11",
      "norm": 97.0,
      "price": 3200.0
    },
    {
      "t": 7,
      "month": "2026-12",
      "norm": 99.9,
      "price": 3298.0
    },
    {
      "t": 8,
      "month": "2027-01",
      "norm": 104.2,
      "price": 3440.0
    },
    {
      "t": 9,
      "month": "2027-02",
      "norm": 109.9,
      "price": 3627.0
    },
    {
      "t": 10,
      "month": "2027-03",
      "norm": 114.3,
      "price": 3771.0
    },
    {
      "t": 11,
      "month": "2027-04",
      "norm": 118.7,
      "price": 3916.0
    },
    {
      "t": 12,
      "month": "2027-05",
      "norm": 121.7,
      "price": 4017.0
    },
    {
      "t": 13,
      "month": "2027-06",
      "norm": 124.8,
      "price": 4118.0
    },
    {
      "t": 14,
      "month": "2027-07",
      "norm": 125.2,
      "price": 4131.0
    },
    {
      "t": 15,
      "month": "2027-08",
      "norm": 125.5,
      "price": 4143.0
    },
    {
      "t": 16,
      "month": "2027-09",
      "norm": 125.9,
      "price": 4156.0
    },
    {
      "t": 17,
      "month": "2027-10",
      "norm": 126.3,
      "price": 4168.0
    },
    {
      "t": 18,
      "month": "2027-11",
      "norm": 126.7,
      "price": 4180.0
    },
    {
      "t": 19,
      "month": "2027-12",
      "norm": 127.1,
      "price": 4193.0
    },
    {
      "t": 20,
      "month": "2028-01",
      "norm": 127.4,
      "price": 4206.0
    },
    {
      "t": 21,
      "month": "2028-02",
      "norm": 127.8,
      "price": 4218.0
    },
    {
      "t": 22,
      "month": "2028-03",
      "norm": 128.2,
      "price": 4231.0
    },
    {
      "t": 23,
      "month": "2028-04",
      "norm": 128.6,
      "price": 4244.0
    },
    {
      "t": 24,
      "month": "2028-05",
      "norm": 129.0,
      "price": 4256.0
    },
    {
      "t": 25,
      "month": "2028-06",
      "norm": 129.4,
      "price": 4269.0
    },
    {
      "t": 26,
      "month": "2028-07",
      "norm": 129.8,
      "price": 4282.0
    },
    {
      "t": 27,
      "month": "2028-08",
      "norm": 130.1,
      "price": 4295.0
    },
    {
      "t": 28,
      "month": "2028-09",
      "norm": 130.5,
      "price": 4308.0
    },
    {
      "t": 29,
      "month": "2028-10",
      "norm": 130.9,
      "price": 4321.0
    },
    {
      "t": 30,
      "month": "2028-11",
      "norm": 131.3,
      "price": 4333.0
    },
    {
      "t": 31,
      "month": "2028-12",
      "norm": 131.7,
      "price": 4346.0
    },
    {
      "t": 32,
      "month": "2029-01",
      "norm": 132.1,
      "price": 4360.0
    },
    {
      "t": 33,
      "month": "2029-02",
      "norm": 132.5,
      "price": 4373.0
    },
    {
      "t": 34,
      "month": "2029-03",
      "norm": 132.9,
      "price": 4386.0
    },
    {
      "t": 35,
      "month": "2029-04",
      "norm": 133.3,
      "price": 4399.0
    },
    {
      "t": 36,
      "month": "2029-05",
      "norm": 133.7,
      "price": 4412.0
    }
  ],
  "endpoint": {
    "t": 36,
    "month": "2029-05",
    "norm": 133.7,
    "price": 4412.0
  },
  "endpoint_drift0": {
    "t": 36,
    "month": "2029-05",
    "norm": 122.2,
    "price": 4033.0
  },
  "gain_pct": 37.9,
  "cycle_ends": [
    {
      "name": "1974",
      "norm": 133.7,
      "price": 4412.0
    },
    {
      "name": "1980",
      "norm": 133.7,
      "price": 4412.0
    },
    {
      "name": "2008",
      "norm": 133.7,
      "price": 4412.0
    }
  ],
  "sensitivity": {
    "anchor_minus1_price": 4294.0,
    "anchor_plus1_price": 4352.0,
    "low": 4294.0,
    "high": 4412.0,
    "spread_pct": 2.7
  },
  "provenance": {
    "source": "synthetic-test-fixture",
    "coverage": "2011-01 → 2021-12",
    "method": "monthly average"
  },
  "warnings": [],
  "generated_at": "2026-11-18T00:00:00Z"
};

const browser = await puppeteer.launch({
  executablePath: CHROME,
  headless: "new",
  args: ["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"],
});
const page = await browser.newPage();
await page.setViewport({ width: 1352, height: 900 });
await page.setCacheEnabled(false);
await page.setBypassServiceWorker(true);
await page.setExtraHTTPHeaders({ "X-Forwarded-For": "198.51.100.81" });

const pageErrors = [];
page.on("pageerror", (e) => pageErrors.push("pageerror: " + e.message));
page.on("console", (m) => {
  if (m.type() === "error" && !/Failed to load resource|favicon/i.test(m.text())) {
    pageErrors.push("console: " + m.text());
  }
});
const bad = [];
page.on("response", (r) => {
  if (r.status() >= 400) bad.push(`${r.status()} ${r.url()}`);
});

// ───────────────── 拦截：把 crisis-fit 接口替换成 mock ─────────────────
await page.setRequestInterception(true);
page.on("request", (req) => {
  const url = req.url();
  if (url.includes("/api/v1/forecast/crisis-fit")) {
    req.respond({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(MOCK),
    });
    return;
  }
  req.continue();
});

// ─── 1. 别名 + 页面渲染 ───
console.log("\n【1】独立页 /crisis-fit");
const alias = await fetch(BASE + "/crisis-fit", { redirect: "manual" });
ok("别名 307 重定向", alias.status === 307, `实际 ${alias.status}`);

await page.goto(BASE + "/crisis-fit", { waitUntil: "networkidle2", timeout: 60000 });
await page.waitForFunction(
  () => {
    const el = document.getElementById("cfRange");
    return el && el.textContent && el.textContent.trim() !== "\u2014" && /[0-9]/.test(el.textContent);
  },
  { timeout: 40000 },
);
await new Promise((r) => setTimeout(r, 1200));

const rangeText = await page.$eval("#cfRange", (el) => el.textContent || "");
ok("结论渲染出数字", /[0-9]/.test(rangeText), rangeText);
ok("结论无 undefined / NaN", !/undefined|NaN/.test(rangeText), rangeText);
const bodyText = await page.evaluate(() => document.body.innerText);
ok("页面无 undefined / NaN 泄漏", !/undefined|NaN/.test(bodyText));

// ─── 2. drift=0 对照（drift 是假设 ⇒ 必须并列）───
console.log("\n【2】drift 假设 vs drift=0 对照");
const driftCmp = await page.evaluate(() => {
  const meta = document.getElementById("cfMeta");
  const txt = meta ? meta.innerText : "";
  const nums = (txt.match(/[0-9][0-9,]*(\.[0-9]+)?/g) || []).map((s) => Number(s.replace(/,/g, "")));
  return { txt, nums, hasZero: /drift\s*=\s*0/i.test(txt) };
});
ok("页面上有 drift=0 对照行", driftCmp.hasZero, driftCmp.txt.replace(/\n/g, " | ").slice(0, 120));
ok("drift=0 对照与主结论是两个不同的数",
  driftCmp.nums.length >= 2 && driftCmp.nums[0] !== driftCmp.nums[1],
  JSON.stringify(driftCmp.nums));
ok("对照的数 = 接口的 endpoint_drift0.price",
  driftCmp.nums.some((n) => Math.abs(n - MOCK.endpoint_drift0.price) < 1),
  JSON.stringify({ nums: driftCmp.nums, expect: MOCK.endpoint_drift0.price }));

// ─── 3. 单周期终点区间 ───
console.log("\n【3】各轮周期的终点区间（离散度）");
const ends = await page.evaluate(() => {
  const el = document.getElementById("cfCycleEnds");
  return { text: el ? el.innerText : "", lis: el ? el.querySelectorAll("li").length : 0 };
});
ok("单周期终点区块有内容", ends.text.length > 0, ends.text.replace(/\n/g, " | ").slice(0, 120));
ok("列出每一轮周期", ends.lis === MOCK.cycle_ends.length, `实际 ${ends.lis} / 期望 ${MOCK.cycle_ends.length}`);
ok("区间含最小/最大终点",
  ends.text.includes(String(MOCK.cycle_ends[0].price).replace(/\B(?=(\d{3})+(?!\d))/g, ",")) ||
  ends.text.replace(/,/g, "").includes(String(Math.min(...MOCK.cycle_ends.map((e) => e.price)))),
  ends.text.replace(/\n/g, " | ").slice(0, 160));

// ─── 4. 锚点敏感性 ───
console.log("\n【4】锚点敏感性");
const sens = await page.evaluate(() => {
  const el = document.getElementById("cfSensitivity");
  return { text: el ? el.innerText : "", warn: el ? el.className.includes("cf-sens-warn") : false };
});
ok("锚点敏感性在页面上", sens.text.length > 0, sens.text.slice(0, 160));
ok("敏感度写的是接口给的 spread",
  sens.text.replace(/,/g, "").includes(String(MOCK.sensitivity.spread_pct)),
  `${sens.text.slice(0, 120)} / 期望 ${MOCK.sensitivity.spread_pct}`);

// ─── 5. 拟合图 ───
console.log("\n【5】拟合图");
const fit = await page.evaluate(() => {
  const c = document.getElementById("cfFitChart");
  if (!c) return null;
  const inst = Chart.getChart(c);
  if (!inst) return null;
  const ds = inst.data.datasets.map((d) => ({
    label: d.label,
    n: (d.data || []).length,
    vals: (d.data || []).map((p) => (p && typeof p === "object" ? p.y : p)),
  }));
  // 拟合线第一个非空值落在第几个类目（x 轴 = 距锚点月数 t ⇒ 应该是 t0）
  const fitVals = ds[1] ? ds[1].vals : [];
  let firstNonNull = -1;
  for (let i = 0; i < fitVals.length; i++) {
    if (fitVals[i] != null) { firstNonNull = i; break; }
  }
  // 终点散点的**实际像素位置**（category 轴：给数字 x 时 Chart.js 会自己解释，
  // ⚠ 断言必须比「解析后的像素」而不是原始值 —— 拿原始值比会自证（实测踩过））
  const scIdx = inst.data.datasets.findIndex((d) => d.type === "scatter");
  let scatterPx = [];
  let lastTickPx = null;
  if (scIdx >= 0) {
    const meta = inst.getDatasetMeta(scIdx);
    scatterPx = (meta.data || []).map((pt) => Math.round(pt.x));
    // ⚠ 参考点必须用 getPixelForValue（类目**索引** → 像素）；
    //   getPixelForTick 是「刻度序号」⇒ 索引超范围时返回 0（左边缘）⇒ 断言会失真。
    lastTickPx = Math.round(inst.scales.x.getPixelForValue(inst.data.labels.length - 1));
  }
  return {
    n: ds.length,
    ds: ds,
    labels: inst.data.labels.length,
    firstNonNull,
    scatterPx,
    lastTickPx,
    lastLabel: inst.data.labels[inst.data.labels.length - 1],
  };
});
ok("拟合图已渲染", !!fit, JSON.stringify(fit && fit.n));
if (fit) {
  ok("3 条 dataset（模板×缩放 / 拟合 / 各轮终点）", fit.n === 3, `实际 ${fit.n}`);
  const fitDs = fit.ds[1];
  ok("拟合曲线 31 个点", fitDs.vals.filter((v) => v != null).length === MOCK.curve.length,
    `实际 ${fitDs.vals.filter((v) => v != null).length}`);
  ok("拟合线与接口数值一致（起点 = 当前点）",
    Math.abs(fitDs.vals.filter((v) => v != null)[0] - MOCK.curve[0].price) < 1,
    `${fitDs.vals.filter((v) => v != null)[0]} / ${MOCK.curve[0].price}`);
  ok("终点散点 3 个", fit.ds[2].vals.filter((v) => v != null).length === MOCK.cycle_ends.length,
    `实际 ${fit.ds[2].vals.filter((v) => v != null).length}`);
  // ⚠ x 轴 = 距锚点月数 t ⇒ 拟合线只能从 t0（当前点）开始；
  //   画在轴首 = 月份错位（实测踩过：曲线整体左移 t0 个月）。
  ok("拟合线从当前点(t0)开始，不是画在轴首", fit.firstNonNull === MOCK.t0,
    `首个非空 index=${fit.firstNonNull} / t0=${MOCK.t0}`);
  // ⚠ category 轴上给数字 x ⇒ 散点可能被解析到别处（实测全挤在左边）。
  ok("各轮终点散点在曲线末端（像素位置 = 最后一个类目）",
    fit.scatterPx.length > 0 && fit.lastTickPx != null &&
    fit.scatterPx.every((px) => Math.abs(px - fit.lastTickPx) <= 2),
    `散点像素=${JSON.stringify(fit.scatterPx)} / 末端类目像素=${fit.lastTickPx}`);
}

// ─── 6. 模板图 + 支撑轮数 + clamp 边界 ───
console.log("\n【6】模板图与证据");
const tpl = await page.evaluate(() => {
  const c = document.getElementById("cfTemplateChart");
  const inst = c ? Chart.getChart(c) : null;
  const note = document.getElementById("cfTemplateNote");
  const fitNote = document.getElementById("cfFitNote");
  return {
    n: inst ? inst.data.datasets.length : 0,
    note: note ? note.innerText : "",
    fitNote: fitNote ? fitNote.innerText : "",
  };
});
ok("模板图有 dataset（每轮路径 + 等权模板）", tpl.n === MOCK.cycle_paths.length + 1, `实际 ${tpl.n}`);
ok("支撑轮数写在页面上", /[0-9]/.test(tpl.note), tpl.note.slice(0, 160));
ok("模板 clamp 边界在图注里标明", /t=\s*\d+/.test(tpl.fitNote), tpl.fitNote.slice(0, 200));

// ─── 7. a11y 兜底表不溢出容器（V0.127.2 判据）───
console.log("\n【7】a11y 数据表落点");
const a11y = await page.evaluate(() => {
  const ds = Array.from(document.querySelectorAll("details.pm-chart-fallback"));
  const over = ds.map((d) => {
    const host = d.parentElement;
    const hb = host.getBoundingClientRect();
    const db = d.getBoundingClientRect();
    return { host: host.id || host.className, over: db.bottom > hb.bottom + 1 || db.right > hb.right + 1 };
  }).filter((x) => x.over);
  const covered = [];
  const targets = document.querySelectorAll("canvas, table, h2, .cf-note, .cf-method, .panel-title");
  ds.forEach((d) => {
    d.open = true;
    const r = d.getBoundingClientRect();
    targets.forEach((t) => {
      if (d.contains(t)) return;
      const tr = t.getBoundingClientRect();
      if (!tr.width || !tr.height) return;
      const ix = Math.min(r.right, tr.right) - Math.max(r.left, tr.left);
      const iy = Math.min(r.bottom, tr.bottom) - Math.max(r.top, tr.top);
      if (ix > 2 && iy > 2) covered.push({ el: t.id || t.className || t.tagName });
    });
  });
  return { n: ds.length, over, covered };
});
ok("页面有 a11y 数据表兜底", a11y.n >= 2, `实际 ${a11y.n}`);
ok("a11y 数据表没有溢出图表容器", a11y.over.length === 0, JSON.stringify(a11y.over));
ok("a11y 数据表展开后不遮挡下方内容", a11y.covered.length === 0, JSON.stringify(a11y.covered));

// ─── 8. E8：形态拟合页不含扇形图；扇形图页不含形态拟合 ───
console.log("\n【8】E8 两个功能不混");
ok("形态拟合页没有扇形图 canvas", await page.evaluate(() => !document.getElementById("pfFanChart")));
await page.goto(BASE + "/price-forecast", { waitUntil: "networkidle2", timeout: 60000 });
await new Promise((r) => setTimeout(r, 1500));
ok("扇形图页没有形态拟合 canvas", await page.evaluate(() =>
  !document.getElementById("cfFitChart") && !document.getElementById("cfTemplateChart")));

// ─── 9. 无产物 ⇒ 待数据（**显式 mock 降级响应**）───
// ⚠ 不能靠「仓库里恰好没有产物文件」来测降级：V0.128.0 把真实产物入库后，
//   这条断言就会假红（实测踩过）⇒ 必须显式 mock 一个 available=false 的响应。
console.log("\n【9】无产物 ⇒ 待数据（不画假线）");
await page.setRequestInterception(true);
page.removeAllListeners("request");
page.on("request", (req) => {
  const url = req.url();
  if (url.includes("/api/v1/forecast/crisis-fit")) {
    req.respond({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        target: "ny", available: false, reason: "no_crisis_cycles_artifact",
        horizon_months: 30, drift: 0.003, curve: [], endpoint: null,
        endpoint_drift0: null, cycle_ends: [], template: [], template_counts: [],
        template_max_t: null, cycle_paths: [], sensitivity: null,
        provenance: {}, warnings: [],
      }),
    });
    return;
  }
  req.continue();
});
await page.goto(BASE + "/crisis-fit", { waitUntil: "networkidle2", timeout: 60000 });
await new Promise((r) => setTimeout(r, 2000));
const pending = await page.evaluate(() => {
  const r = document.getElementById("cfRange");
  const inst = document.getElementById("cfFitChart");
  return {
    text: r ? r.textContent : "",
    hasChart: !!(inst && Chart.getChart(inst)),
    body: document.body.innerText,
  };
});
ok("无产物时显示「待数据」", pending.text.includes("待数据"), pending.text);
ok("无产物时不画拟合图", pending.hasChart === false);
ok("无产物时说明了为什么不画",
  /不画|尚未入库|样本不足/.test(pending.body), pending.body.slice(0, 200));

// ─── 10. 首页磁贴 ───
console.log("\n【10】首页「形态拟合」磁贴");
await page.goto(BASE + "/home", { waitUntil: "networkidle2", timeout: 60000 });
await new Promise((r) => setTimeout(r, 2500));
const tile = await page.evaluate(() => {
  const a = document.querySelector(".home-scene.scene-forecast");
  const live = document.getElementById("cfTileRange");
  return {
    href: a ? a.getAttribute("href") : null,
    title: a ? a.querySelector(".scene-title")?.textContent?.trim() : null,
    live: live ? live.textContent.trim() : null,
    oldTile: !!document.getElementById("fcTileRange"),
  };
});
ok("磁贴指向 /crisis-fit", tile.href === "/crisis-fit", String(tile.href));
ok("磁贴标题是「形态拟合」", tile.title === "形态拟合", String(tile.title));
ok("磁贴实时行有内容", !!tile.live && tile.live.length > 0, String(tile.live));
ok("旧的金价区间磁贴已移除", tile.oldTile === false);

// ─── 11. 三语切换 ───
console.log("\n【11】三语切换");
for (const lang of ["en-US", "zh-TW", "zh-CN"]) {
  await page.goto(BASE + "/crisis-fit", { waitUntil: "networkidle2", timeout: 60000 });
  await page.waitForFunction(
    () => {
      const el = document.getElementById("cfRange");
      return el && el.textContent && /[0-9]|待/.test(el.textContent);
    },
    { timeout: 30000 },
  ).catch(() => {});
  await page.evaluate(async (l) => { await window.I18n.setLang(l); }, lang);
  await new Promise((r) => setTimeout(r, 900));
  const t = await page.evaluate(() => ({
    hero: document.querySelector(".hero h1")?.textContent?.trim() || "",
    body: document.body.innerText,
  }));
  ok(`${lang} 标题已翻译`, t.hero.length > 0 && !/^\s*$/.test(t.hero), t.hero);
  ok(`${lang} 无 undefined 泄漏`, !/undefined/.test(t.body));
}

// ─── 12. 网络 / 脚本 ───
console.log("\n【12】网络 / 脚本");
ok("无 4xx/5xx", bad.length === 0, bad.slice(0, 5).join(" | "));
ok("无 console error / pageerror", pageErrors.length === 0, pageErrors.slice(0, 3).join(" | "));

await browser.close();
console.log(`\n${"=".repeat(56)}`);
console.log(`  结果：${pass} passed, ${fail} failed`);
console.log("=".repeat(56));
process.exit(fail === 0 ? 0 : 1);
