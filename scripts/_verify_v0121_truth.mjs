// scripts/_verify_v0121_truth.mjs
// V0.121.1 线上实测门禁：验证「显示假的」两个 P0 在**真实页面**上已修好
//
//   P0-2（命中分析「上涨天数」恒为 0）
//     症状：页面上「上涨」一列全是 0（唯一可信口径是 gold_price_daily.change_pct 的符号）
//     断言：表里有「方向已知」列；前若干行的「上涨」之和 > 0；
//           「方向已知」形如 "N / M"（分母摊开，让缺口可见）
//
//   P0-4（/headlines 渲染 i18n key 字面量）
//     症状：正文可见 "time.hour_ago" 这类**内部 key**
//     根因：I18n.t() 字典缺失时返回 key **字面量**（不是空串）⇒ 旧的 `|| "兜底"` 永不触发
//     断言：相对时间与整页正文都不含 "time.*"；出现中文相对时间文案
//
// ⚠ 必须打 192.168.0.204:8888（主入口）。见记忆 lan-only-deployment。
// ⚠ 必须 setViewport(1352×900)。见记忆 puppeteer-viewport-sticky-nav。
// ⚠ 必须 setBypassServiceWorker(true)。见记忆 puppeteer-sw-silently-bypasses-interception。
// ⚠ 幂等：只读页面，不改任何状态；重复跑结果一致。
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

// ───────── P0-4：/headlines 相对时间不得出现 i18n key 字面量 ─────────
console.log("\n[P0-4] /headlines 相对时间");
await page.goto(`${BASE}/headlines`, { waitUntil: "networkidle2", timeout: 90000 });
await new Promise((r) => setTimeout(r, 3000));
// ⚠ 必须**指名道姓**地取「上次刷新」那个元素（#valLastRefresh）——
//   泛泛地按 class 扫（.time-ago / [class*=ago]）会扫到 0 个元素，
//   于是「不含 key 字面量」这条断言**空转恒真**（本脚本踩过）。
const lr = await page.evaluate(() => {
  const el = document.getElementById("valLastRefresh");
  return el ? (el.textContent || "").trim() : null;
});
console.log(`  #valLastRefresh = ${JSON.stringify(lr)}`);
ok("#valLastRefresh 存在且非空", !!lr, `lr=${JSON.stringify(lr)}`);
ok(
  "上次刷新显示的是真实相对时间，不是 i18n key 字面量",
  !!lr && !/\btime\.[a-z_]+/.test(lr),
  `lr=${JSON.stringify(lr)}`,
);
ok(
  "上次刷新符合「N 分钟前 / N 小时前 / N 天前 / 刚刚」形态",
  !!lr && /^(刚刚|\d+\s*(分钟前|小时前|天前))$/.test(lr),
  `lr=${JSON.stringify(lr)}`,
);
const bodyTxt = await page.evaluate(() => document.body.innerText);
ok(
  "整页正文不含 'time.' key 字面量",
  !/\btime\.[a-z_]+/.test(bodyTxt),
  (bodyTxt.match(/\btime\.[a-z_]+/g) || []).join(","),
);
ok("出现中文相对时间文案", /分钟前|小时前|天前|刚刚/.test(bodyTxt));

// ───────── P0-2：/scoring 命中分析的「方向已知」列 ─────────
console.log("\n[P0-2] /scoring 命中分析");
await page.goto(`${BASE}/scoring`, { waitUntil: "networkidle2", timeout: 90000 });
await new Promise((r) => setTimeout(r, 2500));
const tabClicked = await page.evaluate(() => {
  const btns = [...document.querySelectorAll("button, .tab, [role='tab'], a")];
  const t = btns.find((b) => /命中分析/.test(b.textContent || ""));
  if (t) {
    t.click();
    return true;
  }
  return false;
});
ok("找到并点击「命中分析」Tab", tabClicked);
await new Promise((r) => setTimeout(r, 4000));
const tbl = await page.evaluate(() => {
  const tables = [...document.querySelectorAll("table")];
  const withKnown = tables.find((t) => /方向已知/.test(t.innerText || ""));
  if (!withKnown) return null;
  const head = [...withKnown.querySelectorAll("thead th")].map((th) =>
    (th.textContent || "").trim(),
  );
  const allRows = [...withKnown.querySelectorAll("tbody tr")].map((tr) =>
    [...tr.querySelectorAll("td")].map((td) => (td.textContent || "").trim()),
  );
  return { head, rows: allRows.slice(0, 5), allRows };
});
ok("命中分析表存在「方向已知」列", !!tbl, "未找到含「方向已知」的表");
if (tbl) {
  console.log(`  表头: ${JSON.stringify(tbl.head)}`);
  console.log(`  前 5 行: ${JSON.stringify(tbl.rows)}`);
  const upIdx = tbl.head.findIndex((h) => /涨|Up/i.test(h));
  const downIdx = tbl.head.findIndex((h) => /跌|Down/i.test(h));
  const knownIdx = tbl.head.findIndex((h) => /已知|Known/i.test(h));
  // ⚠ 表头文案来自 i18n 字典（zh-CN 是「上涨日数」，JS 兜底串才是「涨」）
  //   ⇒ **不能**用 `head === "涨"` 精确匹配：匹配不到 ⇒ 索引 -1 ⇒
  //   `r[-1]` 是 undefined ⇒ 求和恒为 0 ⇒ 门禁「全绿但其实啥也没测」。
  //   （这是本脚本自己踩过的坑：先写成 === "涨"，门禁报「上涨天数非 0」失败，
  //     而页面其实是对的 —— upSum 结构性恒 0。）
  ok("定位到「涨 / 跌 / 方向已知」三列", upIdx >= 0 && downIdx >= 0 && knownIdx >= 0,
     `up=${upIdx} down=${downIdx} known=${knownIdx} head=${JSON.stringify(tbl.head)}`);
  // ⚠ 统计必须**对全表**求和，不能只看最新几行：
  //   price_direction 来自 gold_price_daily，而价格日历目前只追到 2026-10-14
  //   （B1：价格日历不增量补齐，属批次 2）⇒ **最新几天必然是 0 / N**。
  //   只看前 5 行会把「数据缺口」误判成「修复没生效」。
  const upSum = tbl.allRows.reduce((a, r) => a + (Number(r[upIdx]) || 0), 0);
  const knownSum = tbl.allRows.reduce(
    (a, r) => a + (parseInt(String(r[knownIdx] || "").split("/")[0], 10) || 0),
    0,
  );
  ok("「上涨天数」全表合计非 0", upSum > 0, `upSum=${upSum} 行数=${tbl.allRows.length}`);
  ok("「方向已知」全表合计非 0", knownSum > 0, `knownSum=${knownSum}`);
  ok(
    "「方向已知」分母已摊开（形如 N / M）",
    tbl.rows.some((r) => /\d+\s*\/\s*\d+/.test(String(r[knownIdx] || ""))),
    JSON.stringify(tbl.rows.map((r) => r[knownIdx])),
  );
  ok(
    "上涨 + 下跌 == 方向已知（方向唯一的两天必须归到上涨或下跌）",
    knownSum === upSum + tbl.allRows.reduce((a, r) => a + (Number(r[downIdx]) || 0), 0),
    `known=${knownSum} up=${upSum} down=${tbl.allRows.reduce((a, r) => a + (Number(r[downIdx]) || 0), 0)}`,
  );
  console.log(`  全表 up 合计=${upSum} known 合计=${knownSum} 行数=${tbl.allRows.length}`);
}
ok("页面无 JS 错误", jsErrors.length === 0, jsErrors.slice(0, 3).join(" | "));

console.log(`\n结果：${pass} passed, ${fail} failed`);
await browser.close();
process.exit(fail === 0 ? 0 : 1);
