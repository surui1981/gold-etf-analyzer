// scripts/_verify_multi_source.mjs
// V0.114.0 验证：多源新闻 UI 实跑（不是读代码推断）
//
// 钉的 5 件事，每条都对应一个「不跑浏览器就发现不了」的缺陷：
//  1. 4 源卡片都真的渲染出来（failover 换了源，UI 不能跟着瞎）
//  2. 无链接条目的标题**不是 <a>** —— 原先 `it.url || "#"` 是假 affordance
//     （V0.77.1）：金十/东财实测 0/20 条有链接，点了什么也不发生
//  3. 有链接条目的标题是 <a href> 且 href 非 "#"
//  4. fav 按钮带 data-source，收藏 POST 带 news_source
//     —— 原先两处都写死 readhub，多源下会收藏到「另一条同号新闻」
//  5. 金十 20 位 external_id 全程**字符串**（JS Number 装不下 2.02e19，
//     parseInt 会静默舍入成 …7000，收藏落到不存在的行）
//
// 视口 1352×900：默认 800×600 下 sticky 顶栏会盖住按钮，click 静默失效
//（见 puppeteer-viewport-sticky-nav）
import puppeteer from "puppeteer-core";

const BASE = process.env.BASE_URL || "http://192.168.0.204:8888";
const CHROME =
  "/home/surui/.cache/puppeteer/chrome/linux-153.0.8010.36/chrome-linux64/chrome";

let pass = 0;
let fail = 0;
function chk(ok, name, extra = "") {
  if (ok) {
    pass++;
    console.log(`  [OK]   ${name}`);
  } else {
    fail++;
    console.log(`  [FAIL] ${name}${extra ? " :: " + extra : ""}`);
  }
}

const browser = await puppeteer.launch({
  executablePath: CHROME,
  headless: "new",
  args: ["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"],
});
const page = await browser.newPage();
await page.setViewport({ width: 1352, height: 900 });
await page.setCacheEnabled(false);

// 拦 favorites/exists：60 张卡 init 会打满 rate limit（V0.83.2 实测）
const existsCalls = [];
await page.setRequestInterception(true);
page.on("request", (req) => {
  const u = req.url();
  if (u.includes("/favorites/exists/")) {
    existsCalls.push(u);
    req.respond({ status: 200, contentType: "application/json", body: "{}" });
  } else {
    req.continue();
  }
});
const pageErrors = [];
// /favicon.ico 是**全站性**的既存 404（20 个页面都没 rel=icon，服务端也没有该
// 路由），与本轮多源改动无关，剔掉免得淹没真错误（V0.113.0 settings.js 那条
// 裸调 apiJson 的 ReferenceError 同理）
const IGNORABLE = [/favicon\.ico/];
const isIgnorable = (t) => IGNORABLE.some((re) => re.test(t));
const skipped = [];
page.on("pageerror", (e) => {
  const t = String(e);
  isIgnorable(t) ? skipped.push(t) : pageErrors.push(t);
});
page.on("console", (m) => {
  if (m.type() !== "error") return;
  const t = m.text();
  if (isIgnorable(t)) return skipped.push(t);
  // 「Failed to load resource: the server responded with a status of NNN」是
  // response 事件的**无 URL 重复消息** —— 带 URL 的那条下面已经判过了，
  // 这里再记一遍会把已豁免的 404 重新算成错误。
  // net::ERR_* 不放行：那是压根没拿到 response 的真网络失败。
  if (/Failed to load resource: the server responded with a status of/.test(t))
    return skipped.push(t);
  pageErrors.push(t);
});
page.on("response", (r) => {
  if (r.status() < 400) return;
  const t = `HTTP ${r.status()} ${r.url()}`;
  isIgnorable(t) ? skipped.push(t) : pageErrors.push(t);
});

console.log("=== V0.114.0 多源新闻 UI 实跑 ===");
await page.goto(`${BASE}/headlines`, { waitUntil: "networkidle2", timeout: 60000 });
await page.waitForSelector(".news-card", { timeout: 30000 });
await new Promise((r) => setTimeout(r, 1200));

// ── 1. 多源渲染 ────────────────────────────────────────────────
const bySource = await page.evaluate(() => {
  const out = {};
  document.querySelectorAll(".news-card").forEach((c) => {
    const s = c.dataset.source || "(none)";
    out[s] = (out[s] || 0) + 1;
  });
  return out;
});
const srcKeys = Object.keys(bySource);
console.log(`  卡片按源分布: ${JSON.stringify(bySource)}`);
chk(srcKeys.length >= 2, "至少 2 个源的卡片渲染出来了", `实际 ${srcKeys.join(",")}`);
chk(srcKeys.includes("wallstcn"), "首选源 wallstcn 的卡片存在");

// ── 2/3. 有无链接的标题可点性 ─────────────────────────────────
const links = await page.evaluate(() => {
  const withUrl = [];
  const noUrl = [];
  document.querySelectorAll(".news-card").forEach((c) => {
    const src = c.dataset.source;
    const h3 = c.querySelector("h3");
    const a = h3 && h3.querySelector("a");
    const rec = {
      src,
      ext: c.dataset.ext,
      isAnchor: !!a,
      href: a ? a.getAttribute("href") : null,
      hasNoUrlSpan: !!(h3 && h3.querySelector("span.no-url")),
      h3Tag: h3 ? h3.firstElementChild.tagName : null,
    };
    (a ? withUrl : noUrl).push(rec);
  });
  return { withUrl, noUrl };
});
console.log(
  `  有 <a> 标题 ${links.withUrl.length} 张；无 <a> 标题 ${links.noUrl.length} 张`
);
chk(links.withUrl.length > 0, "有链接条目的标题是 <a>");
chk(
  links.withUrl.every((r) => r.href && r.href !== "#"),
  "没有 href='#' 假链接",
  JSON.stringify(links.withUrl.filter((r) => !r.href || r.href === "#").slice(0, 3))
);
chk(links.noUrl.length > 0, "无链接条目的标题不是 <a>（V0.77.1 无假 affordance）");
chk(
  links.noUrl.every((r) => r.h3Tag === "SPAN" && r.hasNoUrlSpan),
  "无链接条目标题是 span.no-url 纯文本",
  JSON.stringify(links.noUrl.filter((r) => !(r.h3Tag === "SPAN" && r.hasNoUrlSpan)).slice(0, 3))
);
chk(
  links.noUrl.every((r) => !r.src || r.src !== "readhub"),
  "无链接的确实来自金十/东财（不是有链接的源被渲染坏了）",
  JSON.stringify(links.noUrl.slice(0, 3))
);

// ── 4. fav 按钮 data-source ───────────────────────────────────
const favAttrs = await page.evaluate(() => {
  const bs = [...document.querySelectorAll(".fav-btn")];
  return {
    total: bs.length,
    withSource: bs.filter((b) => b.dataset.source).length,
    sources: [...new Set(bs.map((b) => b.dataset.source))],
  };
});
console.log(`  fav 按钮 ${favAttrs.total} 个；带 data-source ${favAttrs.withSource} 个`);
chk(favAttrs.total > 0 && favAttrs.withSource === favAttrs.total,
  "每个 fav 按钮都带 data-source", `total=${favAttrs.total} withSource=${favAttrs.withSource}`);
chk(
  favAttrs.sources.includes("wallstcn") || favAttrs.sources.length >= 2,
  "data-source 覆盖多个源（不是全写死 readhub）",
  JSON.stringify(favAttrs.sources)
);

// exists 查询必须带各自 source，且不是全 readhub
const badExists = existsCalls.filter((u) => u.includes("source=readhub"));
chk(existsCalls.length > 0, "exists 回填请求发出来了");
chk(
  badExists.length < existsCalls.length,
  "exists 查询不再一律 source=readhub",
  `${badExists.length}/${existsCalls.length} 仍是 readhub`
);

// ── 5. 20 位 id 保持字符串 ────────────────────────────────────
const idTypes = await page.evaluate(() => {
  const seen = new Set();
  const big = [];
  document.querySelectorAll(".news-card").forEach((c) => {
    const e = c.dataset.ext;
    seen.add(e.length > 15 ? "long" : "short");
    if (e.length > 15) big.push(e);
  });
  return { seen: [...seen], big };
});
chk(
  !idTypes.big.some((e) => /[eE.]/.test(e)),
  "20 位 external_id 是纯数字串（无科学计数法 / 无精度丢失）",
  JSON.stringify(idTypes.big.slice(0, 3))
);

// ── 收藏点击：POST 体必须带 news_source ───────────────────────
const posts = [];
let postStatus = null;
page.on("request", (req) => {
  if (req.method() === "POST" && req.url().includes("/favorites/items")) {
    try { posts.push(JSON.parse(req.postData() || "{}")); } catch { posts.push({ __raw: req.postData() }); }
  }
});
// 只断言「请求发出去了」不够 —— 服务端 4xx/5xx 时前端同样会发请求。
// 记下真实响应码，才能区分「收藏成功」和「请求被拒」。
page.on("response", (r) => {
  if (r.request().method() === "POST" && r.url().includes("/favorites/items")) postStatus = r.status();
});
// 点一张**无链接**的卡片（金十/东财）——它们以前根本收藏不了
const clicked = await page.evaluate(() => {
  const c = document.querySelector('.news-card[data-source="jin10"], .news-card[data-source="eastmoney"]');
  if (!c) return null;
  const btn = c.querySelector(".fav-btn");
  btn.scrollIntoView({ block: "center" });
  return { ext: c.dataset.ext, src: c.dataset.source };
});
if (!clicked) {
  chk(false, "找到无链接源（jin10/eastmoney）的卡片可点收藏");
} else {
  // 先删掉上一轮留下的收藏，让本轮走 **200 新增** 而不是 409 幂等分支。
  // 不做这步的话脚本只能绿一次（第二次点必然 409），那种脚本不算门禁。
  // 用 API 删而不是直连 sqlite：.venv/bin/python -c "...DELETE..." 不写
  // commit() 的话连接关闭即回滚，我第一版就是这么把 409 又请回来的。
  try {
    const fl = await (await fetch(`${BASE}/api/v1/favorites/items?limit=200`)).json();
    for (const f of fl.items || []) {
      if (String(f.news_external_id) === String(clicked.ext) && f.news_source === clicked.src) {
        const del = await fetch(`${BASE}/api/v1/favorites/items/${f.id}`, { method: "DELETE" });
        console.log(`  清上一轮收藏 id=${f.id} → HTTP ${del.status}`);
      }
    }
  } catch (e) {
    console.log(`  清理收藏失败（继续走 409 路径）：${e.message}`);
  }
  await new Promise((r) => setTimeout(r, 300));
  await page.click(`.news-card[data-source="${clicked.src}"] .fav-btn`);
  await new Promise((r) => setTimeout(r, 2500));
  console.log(`  点击了 ${clicked.src} 的收藏按钮（ext=${clicked.ext}）`);
  chk(posts.length > 0, "收藏 POST 发出来了", JSON.stringify(posts));
  // 201 是 FastAPI POST 的默认成功码，2xx 都算（写死 200 会自己把自己判红）
  chk(postStatus >= 200 && postStatus < 300,
    "收藏 POST 真返回 2xx（不是只发出请求就当成功）", `实际 HTTP ${postStatus}`);
  const p = posts[0];
  if (p) {
    chk(p.news_source === clicked.src, "POST 带上了正确的 news_source",
      `期望 ${clicked.src}，实际 ${p.news_source}`);
    chk(
      String(p.news_external_id) === String(clicked.ext),
      "POST 的 external_id 与卡片 data-ext 一致（没有 parseInt 改写）",
      `期望 ${clicked.ext}，实际 ${p.news_external_id}`
    );
    chk(
      String(p.news_external_id).length > 15
        ? String(p.news_external_id) === clicked.ext
        : true,
      "20 位 id 原样透传（未被 JS 舍入）"
    );
  }
}

// ── 5b. 收藏**要有反馈** ───────────────────────────────────────
// V0.98 C3 起 toast.js 只导出 info/success/warn/err，全站却有 14 处调
// PM_Toast.show(...) —— show 从未导出。headlines.js/home.js 的 guard 只查
// `window.PM_Toast`（对象在）→ 抛 TypeError；favorites.js/report-archive.js 的
// guard 查到 .show 为 falsy → 整个 toast 静默不弹。
// 两种坏法的用户可见后果**完全一样**：点了收藏，POST 成功了，屏幕毫无反应。
// 只读代码容易判成「既有小瑕疵」，必须实跑点一下看 toast 到底出不出现。
const toastState = await page.evaluate(() => {
  const t = window.PM_Toast || {};
  const box = document.getElementById("pm-toast-container");
  const kids = box ? [...box.children] : [];
  return {
    hasShow: typeof t.show === "function",
    exports: Object.keys(t),
    rendered: kids.map((e) => (e.className || "") + "|" + (e.textContent || "").trim().slice(0, 24)),
  };
});
console.log(`  PM_Toast 导出: ${JSON.stringify(toastState.exports)}`);
chk(toastState.hasShow, "PM_Toast.show 存在（V0.98 起 14 处调用从未有过此函数）",
  `实际导出 ${JSON.stringify(toastState.exports)}`);
chk(
  toastState.rendered.some((r) => /已收藏|收藏失败/.test(r)),
  "点收藏后真的弹出了 toast（有反馈，不是静默 POST）",
  JSON.stringify(toastState.rendered)
);

// ── 6. i18n：3 语都无 key 字面量泄漏 ──────────────────────────
for (const lang of ["zh-CN", "zh-TW", "en-US"]) {
  await page.evaluate((l) => { localStorage.setItem("lang", l); }, lang);
  await page.reload({ waitUntil: "networkidle2" });
  await page.waitForSelector(".news-card", { timeout: 30000 });
  await new Promise((r) => setTimeout(r, 900));
  const texts = await page.evaluate(() => {
    const meta = [...document.querySelectorAll(".news-card .meta")].slice(0, 3).map((e) => e.textContent.trim());
    const nourl = document.querySelector(".news-card h3 span.no-url");
    return { meta, title: nourl ? nourl.getAttribute("title") : null };
  });
  const leak = [...texts.meta, texts.title || ""].some((t) => /headlines\.[a-z_]+/.test(t));
  chk(!leak, `${lang}：无 i18n key 字面量泄漏`, JSON.stringify(texts));
}

chk(pageErrors.length === 0, "无 JS 运行时错误", pageErrors.slice(0, 3).join(" | "));
console.log(`  （豁免 ${skipped.length} 条：${[...new Set(skipped)].slice(0, 2).join(" ; ")}）`);

console.log("\n" + "=".repeat(60));
console.log(`结果：${pass} passed / ${fail} failed`);
await browser.close();
process.exit(fail ? 1 : 0);