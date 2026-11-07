// scripts/_verify_ask_tokens.mjs
// V0.121.2（P0-5）线上实测门禁：/ask 的 token 栏必须**真的显示出来**
//
//   P0-5 真缺陷（客户端侧）：
//     `static/ask.js` 的 `case 'message_stop'` **从不读** `payload.usage`
//     ⇒ `currentRound.inputTokens/outputTokens` 永远是初值
//     ⇒ commit 写进消息的是 `null` ⇒ 页面上 token 一栏**永远不显示**。
//     （服务端其实一直有发 usage —— 是客户端把它扔了。）
//
//   本门禁断言（用**假 SSE** 驱动，不调真模型、不花 token）：
//     ① `message_stop` 带 usage ⇒ assistant 消息上出现 `↓ 10` 与 `↑ 42`
//     ② usage 为 null（上游没报）⇒ **不显示** `↓`/`↑`（不拿假值充数）
//     ③ 页面无 JS 错误、无 i18n key 字面量
//
// ⚠ 必须打 192.168.0.204:8888（主入口）。见记忆 lan-only-deployment。
// ⚠ 必须 setViewport(1352×900)。见记忆 puppeteer-viewport-sticky-nav。
// ⚠ 必须 setBypassServiceWorker(true)。见记忆 puppeteer-sw-silently-bypasses-interception。
// ⚠ 幂等：全程拦截 AI 端点，**不产生任何真实对话、不消耗 token**。
import puppeteer from "puppeteer-core";

const BASE = process.env.BASE_URL || "http://192.168.0.204:8888";
const CHROME =
  "/home/surui/.cache/puppeteer/chrome/linux-153.0.8010.36/chrome-linux64/chrome";

/**
 * Chrome 启动参数。
 * 默认**保留浏览器自带的沙箱**（namespace sandbox；本机 uid=1000 且
 * unprivileged_userns_clone=1 ⇒ 可用）。若环境不满足（跑在 root 容器里、
 * 没有 userns），用 ``CHROME_NO_SANDBOX=1`` 退回 —— 仓库里其余 15 个浏览器
 * 门禁默认就是 ``--no-sandbox``，所以两边都留了路。
 */
function chromeArgs() {
  const args = ["--disable-dev-shm-usage"];
  if (process.env.CHROME_NO_SANDBOX === "1") args.unshift("--no-sandbox");
  return args;
}

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

/** 造一条 SSE 响应体。usage 为 null 时报「未知」。 */
function sseBody(usage) {
  const evs = [
    { event: "user_saved", msg_id: "m-user-1" },
    { event: "text_delta", delta: "这是**门禁**用的假回复。" },
    { event: "message_stop", usage },
  ];
  return evs
    .map((e) => `event: ${e.event}\ndata: ${JSON.stringify(e)}\n\n`)
    .join("");
}

const browser = await puppeteer.launch({
  executablePath: CHROME,
  headless: "new",
  args: chromeArgs(),
});
const page = await browser.newPage();
await page.setViewport({ width: 1352, height: 900 });
await page.setBypassServiceWorker(true);

const jsErrors = [];
let sawFallback = false;
page.on("pageerror", (e) => jsErrors.push(String(e)));
page.on("console", (m) => {
  if (m.type() === "error") jsErrors.push(m.text());
  // ⚠ 客户端降级时会 console.warn('SSE stream failed...') ⇒ 必须打出来，
  //   否则「为什么回退到同步端点」只能靠猜。
  else if (m.type() === "warning" || m.type() === "warn") {
    if (m.text().includes("SSE stream failed")) sawFallback = true;
    console.log(`  WARN: ${m.text()}`);
  }
});
// 门禁自诊断：4xx/5xx 一律打印（不然「没渲染」和「接口挂了」分不清）
const httpFails = [];
page.on("response", (r) => {
  if (r.status() >= 400) httpFails.push(`${r.status()} ${r.url()}`);
});

// ── 拦截 AI 端点：全部用假响应，**不碰真实模型** ──
// ⚠ LIVE=1 ⇒ **不拦截**，打真实模型（会消耗 token + 在生产库建一条对话）。
//    只在发版前人工跑一次「线上实测」时用；默认门禁跑法永远是假 SSE。
const LIVE = process.env.LIVE === "1";
let mode = "known"; // known | unknown
if (!LIVE) {
  await page.setRequestInterception(true);
  page.on("request", (req) => {
    const url = req.url();
    const method = req.method();
    // ⚠ 顺序要紧：SSE 的 URL 也含 `/api/v1/ai/conversations` 且也是 POST
    //   ⇒ 先判 stream，否则建对话的假响应会把 SSE 顶掉（假门禁假绿）。
    if (url.includes("/messages/stream")) {
      const usage =
        mode === "known"
          ? { input_tokens: 10, output_tokens: 42 }
          : { input_tokens: null, output_tokens: null };
      return req.respond({
        status: 200,
        contentType: "text/event-stream; charset=utf-8",
        headers: { "Access-Control-Allow-Origin": "*" },
        body: sseBody(usage),
      });
    }
    if (url.endsWith("/api/v1/ai/conversations") && method === "POST") {
      return req.respond({
        status: 201,
        contentType: "application/json",
        headers: { "Access-Control-Allow-Origin": "*" },
        body: JSON.stringify({
          id: "gate-conv-1",
          title: "门禁测试对话",
          message_count: 0,
          last_message_at: new Date().toISOString(),
        }),
      });
    }
    return req.continue();
  });
}

console.log("\n[P0-5] /ask token 栏");
await page.goto(`${BASE}/ask`, { waitUntil: "networkidle2", timeout: 90000 });
// 等页面自己把 health / 会话列表拉完（子组件 fetch 后才渲染）
await page
  .waitForFunction(
    () => {
      const t = document.getElementById("msgInput");
      return !!t && !document.getElementById("askLayout")?.hidden;
    },
    { timeout: 30000 },
  )
  .catch(() => {});
await new Promise((r) => setTimeout(r, 800));

async function sendAndReadMeta() {
  await page.evaluate(() => {
    const t = document.getElementById("msgInput");
    t.value = "门禁问一句";
    t.dispatchEvent(new Event("input", { bubbles: true }));
  });
  await page.click("#btnSend");
  await page
    .waitForFunction(
      () => {
        const txt = document.querySelector(".ask-main .message.assistant .meta");
        return !!txt && /\d/.test(txt.textContent || "");
      },
      { timeout: 20000 },
    )
    .catch(() => {});
  await new Promise((r) => setTimeout(r, 500));
  return page.evaluate(() => {
    const metas = Array.from(
      document.querySelectorAll(".ask-main .message.assistant .meta"),
    ).map((m) => (m.textContent || "").trim());
    const stream = document.getElementById("messageStream");
    return {
      metas,
      body: document.body.innerText,
      msgNodes: stream ? stream.children.length : -1,
      asstCount: document.querySelectorAll(".message.assistant").length,
      streamText: stream ? (stream.innerText || "").slice(0, 200) : "",
    };
  });
}

// ── 场景 1：上游报了 usage ⇒ 必须显示 ↓10 / ↑42 ──
let r;
if (LIVE) {
  // ── LIVE：打真实模型，验证**整条链**（真 SSE → 客户端 → 页面）──
  console.log("  ⚠ LIVE 模式：会调用真实模型（消耗 token）并建一条对话");
  await page.evaluate(() => {
    const t = document.getElementById("msgInput");
    t.value = "一句话说明今天金价的主要驱动";
    t.dispatchEvent(new Event("input", { bubbles: true }));
  });
  await page.click("#btnSend");
  await page
    .waitForFunction(
      () => {
        const msgs = document.querySelectorAll(".ask-main .message.assistant");
        const last = msgs[msgs.length - 1];
        return !!last && !!(last.querySelector(".meta") || last.querySelector(".bubble")?.textContent);
      },
      { timeout: 180000 },
    )
    .catch(() => {});
  await new Promise((r2) => setTimeout(r2, 1500));
  r = await page.evaluate(() => {
    const metas = Array.from(
      document.querySelectorAll(".ask-main .message.assistant .meta"),
    ).map((m) => (m.textContent || "").trim());
    const stream = document.getElementById("messageStream");
    return {
      metas,
      body: document.body.innerText,
      msgNodes: stream ? stream.children.length : -1,
      asstCount: document.querySelectorAll(".message.assistant").length,
      streamText: stream ? (stream.innerText || "").slice(-300) : "",
    };
  });
  console.log(`  meta(实跑): ${JSON.stringify(r.metas)}`);
  console.log(`  诊断: asstCount=${r.asstCount} stream=${JSON.stringify(r.streamText)}`);
  const outM = r.metas.map((m) => m.match(/↑\s*(\d+)/)).find(Boolean);
  ok(
    "真实回答有正文（流式真的跑起来了）",
    r.asstCount >= 1 && r.streamText.length > 20,
    `asstCount=${r.asstCount}`,
  );
  ok(
    "真实输出 token 显示出来了（↑ N，N>0）",
    !!outM && parseInt(outM[1], 10) > 0,
    JSON.stringify(r.metas),
  );
  ok(
    "输入 token 未知 ⇒ **不显示** ↓（不拿 0 充数）",
    !r.metas.some((m) => /↓/.test(m)),
    JSON.stringify(r.metas),
  );
  ok(
    "SSE 没降级到同步端点（流式路径真的通了）",
    !sawFallback,
    sawFallback ? "页面 console.warn('SSE stream failed...')" : "",
  );
} else {
  r = await sendAndReadMeta();
  console.log(`  meta: ${JSON.stringify(r.metas)}`);
  console.log(
    `  诊断: msgNodes=${r.msgNodes} asstCount=${r.asstCount} stream=${JSON.stringify(r.streamText)}`,
  );
  if (httpFails.length) console.log(`  诊断: 4xx/5xx = ${httpFails.join(" | ")}`);
  ok(
    "assistant 消息显示了输入 token（↓ 10）",
    r.metas.some((m) => /↓\s*10\b/.test(m)),
    JSON.stringify(r.metas),
  );
  ok(
    "assistant 消息显示了输出 token（↑ 42）",
    r.metas.some((m) => /↑\s*42\b/.test(m)),
    JSON.stringify(r.metas),
  );

  // ── 场景 2：上游**没报** usage ⇒ 不得显示假值（不显示 ↓/↑）──
  mode = "unknown";
  r = await sendAndReadMeta();
  console.log(`  meta(未知): ${JSON.stringify(r.metas)}`);
  // ⚠ 断言必须**非空**：第 2 条 assistant 消息真的渲染出来了（asstCount=2），
  //   而带 token 的 meta 仍然只有第 1 条 —— 若这里只查「剩下的都不含 ↓/↑」，
  //   剩下的数组为空 ⇒ 断言**恒真** = 假绿（本仓库的老坑）。
  ok(
    "第 2 条 assistant 消息真的渲染出来了（断言非空，防假绿）",
    r.asstCount === 2,
    `asstCount=${r.asstCount} msgNodes=${r.msgNodes}`,
  );
  ok(
    "上游没报 usage 时**不显示**任何 token（不拿 0 充数）",
    r.metas.filter((m) => /↓|↑/.test(m)).length === 1,
    JSON.stringify(r.metas),
  );
}

ok(
  "页面不出现 i18n key 字面量（ai.* / undefined）",
  !/\bai\.[a-z_]+/.test(r.body) && !/\bundefined\b/.test(r.body),
  (r.body.match(/\b(?:ai\.[a-z_]+|undefined)\b/g) || []).join(","),
);
ok("页面无 JS 错误", jsErrors.length === 0, jsErrors.slice(0, 3).join(" | "));

console.log(`\n结果：${pass} passed, ${fail} failed`);
await browser.close();
process.exit(fail === 0 ? 0 : 1);
