#!/usr/bin/env node
/*!
 * SW 更新门禁（V0.121.0 重写）
 *
 * ⚠ **V0.121.0 之前这个脚本一条断言都没有** ——
 *   它只 `console.log` 诊断信息，退出码恒为 0 ⇒ **永远绿、永远不能判红**
 *   （「崩的门禁不是门禁」的同类：坏门禁比没门禁更坏，因为它让人以为有保护）。
 *
 * 本脚本现在断言 4 件**能判红**的事：
 *   ① SW 已注册且**真的接管了页面**（controller 非空）+ scriptURL 指向 /sw.js
 *   ② 浏览器装的是**当前版本** SW（active SW 里的 VERSION == 服务端 sw.js 的 VERSION）
 *   ③ **缓存里没有陈旧副本**：SHELL/RUNTIME 缓存的 `/static/*` 正文
 *      必须与网络上的当前正文**逐字节一致**
 *      ⇒ 「改了 static 却忘了 bump sw.js VERSION」会被这条直接抓住
 *      （V0.92.0 / V0.100.1 的教训）
 *   ④ activate 后**旧版本缓存已清空**（只剩当前版本的 shell / runtime cache）
 *
 * 另有 1 条页面级断言：首页要闻卡**已渲染完**（骨架屏消失）——
 *   ⚠ 不能只按「li 数 > 0」判：骨架屏本身就是 5 个 li（记忆
 *   「首页新闻卡有骨架屏，按 li 数判断会假绿」）。
 *
 * 用法：
 *   node scripts/_verify_sw_update.mjs                 # 默认打 127.0.0.1:8888
 *   BASE_URL=http://127.0.0.1:8888 node scripts/_verify_sw_update.mjs
 *
 * ⚠ **必须用 127.0.0.1 / localhost，不能用 LAN IP** ——
 *   Service Worker 只在**安全上下文**（HTTPS 或 localhost）里可用，
 *   `http://192.168.0.204:8888` 下 `navigator.serviceWorker` 是 **undefined**
 *   （实测：本脚本最初用 LAN IP 时直接 `Cannot read properties of undefined` 崩掉）。
 *   ⇒ **SW 在 LAN IP 上根本不生效**，只有本地回环才是安全上下文。
 *
 * ⚠⚠ **必须用持久化 profile（`userDataDir`）** ——
 *   puppeteer 默认每次启动都是**全新的临时 profile** ⇒ SW 每次都是**重新 install** ⇒
 *   `cache.addAll(SHELL_ASSETS)` 每次都把**当前**文件重新 precache 一遍
 *   ⇒ 「缓存里的正文 == 网络正文」**永远成立** ⇒ 陈旧检测是**结构性失效**的（假绿）。
 *   实测：puppeteer 默认 profile 下，往 `static/home.js` 追加一行再跑本脚本，
 *   缓存里的 home.js **已经**是新内容（因为 SW 被重新 install 过）⇒ 断言抓不到。
 *   持久化 profile 才能复现真实场景：**用户的 SW 是上一次访问时装的**，
 *   「改了 static 却忘了 bump sw.js VERSION」⇒ 用户下次打开看到的还是旧版。
 */
import puppeteer from "puppeteer-core";

const BASE = process.env.BASE_URL || "http://127.0.0.1:8888";
const PROFILE = process.env.SW_PROFILE_DIR || "/tmp/gold-sw-gate-profile";
const CHROME =
  process.env.CHROME_PATH ||
  "/home/surui/.cache/puppeteer/chrome/linux-153.0.8010.36/chrome-linux64/chrome";

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

let pass = 0;
let fail = 0;
const failures = [];

/** 断言 + 计数（**必须有计数**：没有计数的门禁无法判红）。 */
function ok(label, cond, detail = "") {
  if (cond) {
    pass++;
    console.log(`  [OK]   ${label}`);
  } else {
    fail++;
    failures.push(label + (detail ? ` —— ${detail}` : ""));
    console.log(`  [FAIL] ${label}${detail ? ` —— ${detail}` : ""}`);
  }
}

const browser = await puppeteer.launch({
  executablePath: CHROME,
  headless: "new",
  // ⚠ 持久化 profile：让 SW 注册与缓存**跨次运行存活**（见文件头说明）
  userDataDir: PROFILE,
  args: ["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"],
});
const page = await browser.newPage();
await page.setViewport({ width: 1352, height: 900 });

// 1st visit: install SW
await page.goto(`${BASE}/home`, { waitUntil: "networkidle2", timeout: 60000 });
await sleep(4000);

// ⚠ 非安全上下文（HTTP + 非 localhost）下 `navigator.serviceWorker` 是 undefined ——
//   早前用 LAN IP 时整脚本直接崩（`Cannot read properties of undefined`），
//   崩掉的门禁 = 没有门禁 ⇒ 先判一次，给出可读结论再退出。
const swAvailable = await page.evaluate(() => typeof navigator.serviceWorker !== "undefined");
if (!swAvailable) {
  console.log(`  [FAIL] 当前地址不是安全上下文（${BASE}）⇒ Service Worker 不可用`);
  console.log("");
  console.log("========================================");
  console.log("结果：0 passed / 1 failed");
  console.log("[FAIL] SW 更新门禁未通过：");
  console.log(`  - 非安全上下文（${BASE}）：navigator.serviceWorker undefined`);
  await browser.close();
  process.exit(1);
}

// 等待 SW controller（首次访问需要等 install + activate + claim）
await page.evaluate(async () => {
  if (!navigator.serviceWorker.controller) {
    await new Promise((r) =>
      navigator.serviceWorker.addEventListener("controllerchange", r, { once: true }),
    );
  }
});
// 等 SW 真正 ready（activate 阶段的旧缓存清理在 ready 之后才保证跑完）
await page.evaluate(async () => {
  await navigator.serviceWorker.ready;
});

// ── 断言 ① ──
const swInfo = await page.evaluate(async () => {
  const reg = await navigator.serviceWorker.getRegistration();
  return {
    hasController: !!navigator.serviceWorker.controller,
    scope: reg?.scope || "",
    scriptURL: reg?.active?.scriptURL || "",
    state: reg?.active?.state || "",
  };
});
console.log(`  SW state: ${JSON.stringify(swInfo)}`);
ok("SW 已注册且接管了页面（controller 非空）", swInfo.hasController);
ok("SW scriptURL 指向 /sw.js", /\/sw\.js(\?|$)/.test(swInfo.scriptURL), swInfo.scriptURL);
ok("SW 作用域覆盖 /home", swInfo.scope.includes("/home") || swInfo.scope === BASE + "/", swInfo.scope);

// 2nd + 3rd visit: SW 接管后应命中缓存
await page.reload({ waitUntil: "networkidle2" });
await sleep(4000);
await page.goto(`${BASE}/home`, { waitUntil: "networkidle2" });
await sleep(4000);

// ── 断言 ②：浏览器装的是当前版本 SW ──
const versionCheck = await page.evaluate(async () => {
  const pick = (s) => {
    const m = s.match(/const\s+VERSION\s*=\s*"([^"]+)"/);
    return m ? m[1] : null;
  };
  const reg = await navigator.serviceWorker.getRegistration();
  const activeSrc = await (await fetch(reg.active.scriptURL, { cache: "no-store" })).text();
  // ⚠ `/static/sw.js` 会被 SW 的 cache-first 接管（`caches.match` 忽略 query 是 false，
  //   加 `?_bust=` 才能绕过缓存拿到真身）—— 不加 bust 会拿缓存跟自己比 = 假绿。
  const liveSrc = await (
    await fetch("/static/sw.js?_bust=" + Date.now(), { cache: "no-store" })
  ).text();
  return { active: pick(activeSrc), live: pick(liveSrc) };
});
ok(
  "浏览器装的是当前版本 SW（active VERSION == 服务端 sw.js VERSION）",
  !!versionCheck.active && versionCheck.active === versionCheck.live,
  `active=${versionCheck.active} live=${versionCheck.live}`,
);

// ── 断言 ③ + ④：缓存无陈旧副本 / 旧版本缓存已清 ──
const cacheCheck = await page.evaluate(async () => {
  const live = await (
    await fetch("/static/sw.js?_bust=" + Date.now(), { cache: "no-store" })
  ).text();
  const v = (live.match(/const\s+VERSION\s*=\s*"([^"]+)"/) || [])[1] || null;
  const out = { v, stale: [], checked: 0, cacheNames: [], oldCaches: [] };
  if (!v) return out;
  const shell = await caches.open(`gold-shell-${v}`);
  const runtime = await caches.open(`gold-runtime-${v}`);
  for (const url of ["/static/home.html", "/static/home.js", "/static/theme.css"]) {
    // 加 bust 参数绕过 SW 的 cache-first，拿到网络真身
    const net = await (await fetch(url + "?_bust=" + Date.now(), { cache: "no-store" })).text();
    for (const [name, c] of [
      ["shell", shell],
      ["runtime", runtime],
    ]) {
      const hit = await c.match(url);
      if (!hit) continue;
      out.checked++;
      const body = await hit.text();
      if (body !== net) out.stale.push(`${name}:${url}`);
    }
  }
  out.cacheNames = await caches.keys();
  out.oldCaches = out.cacheNames.filter(
    (k) => /gold-(shell|runtime)-/.test(k) && !k.endsWith(v),
  );
  return out;
});
ok(
  "缓存里的静态资源与网络当前正文一致（无陈旧副本）",
  cacheCheck.stale.length === 0,
  `陈旧条目：${cacheCheck.stale.join(", ") || "无"}（比对 ${cacheCheck.checked} 条）`,
);
ok(
  "activate 后旧版本缓存已清空（只剩当前版本）",
  cacheCheck.oldCaches.length === 0,
  `残留：${cacheCheck.oldCaches.join(", ") || "无"}｜现存：${cacheCheck.cacheNames.join(", ")}`,
);

// ── 断言 ⑤：首页要闻卡已渲染完（骨架屏消失）──
const newsState = await page.evaluate(() => {
  const list = document.getElementById("homeNewsList");
  if (!list) return { missing: true };
  const items = Array.from(list.querySelectorAll("li"));
  return {
    missing: false,
    skeleton: items.filter((li) => li.classList.contains("home-news-skeleton")).length,
    real: items.filter((li) => !li.classList.contains("home-news-skeleton")).length,
    error: items.filter((li) => li.classList.contains("home-news-error")).length,
    sample: items.slice(0, 3).map((li) => ({
      time: li.querySelector(".home-news-date")?.textContent?.trim() || "",
      site: li.querySelector(".home-news-site")?.textContent?.trim() || "",
      title: (li.querySelector(".home-news-title")?.textContent || "").trim().slice(0, 40),
    })),
  };
});
ok("首页要闻卡存在", !newsState.missing);
ok(
  "首页要闻卡已渲染完（骨架屏消失，且进入「有内容」或「空态」终态）",
  !newsState.missing && newsState.skeleton === 0 && newsState.real > 0,
  `skeleton=${newsState.skeleton} real=${newsState.real} error=${newsState.error}`,
);

await page.screenshot({ path: "/tmp/home_after_sw_update.png", fullPage: false });
await browser.close();

console.log("");
console.log("========================================");
console.log(`结果：${pass} passed / ${fail} failed`);
if (fail > 0) {
  console.log("[FAIL] SW 更新门禁未通过：");
  for (const f of failures) console.log(`  - ${f}`);
  process.exit(1);
}
console.log("[OK] SW 更新门禁通过：SW 已接管、版本一致、缓存无陈旧副本、旧缓存已清");
