// scripts/_verify_ask_format.mjs
// V0.116.0 验证：/ask 对话气泡的文本格式
//   ① 清洗器（真跑 ask.js 里的 sanitizeHtml，不是抄一份）
//   ② 移动端 390px 内容驱动横向裁切
//   ③ 排版：标题/分隔线间距 + 无双气泡
//   ④ 真实会话渲染 + 增强管道（.table-scroll / 复制按钮 / 链接 target）
//
// ⚠ 必须打 8888（主入口），见记忆 lan-only-deployment。
// ⚠ 视口必须显式设 1352×900（默认 800×600 下 sticky nav 盖按钮），见记忆 puppeteer-viewport-sticky-nav。
import puppeteer from "puppeteer-core";
import fs from "node:fs";

const BASE = process.env.BASE_URL || "http://127.0.0.1:8888";
const CHROME =
  "/home/surui/.cache/puppeteer/chrome/linux-153.0.8010.36/chrome-linux64/chrome";

let pass = 0, fail = 0;
const failures = [];
function ok(name, cond, extra = "") {
  if (cond) { pass++; console.log(`  ✓ ${name}`); }
  else { fail++; failures.push(name); console.log(`  ✗ ${name}${extra ? " → " + extra : ""}`); }
}

const browser = await puppeteer.launch({
  executablePath: CHROME,
  headless: "new",
  args: ["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"],
});

// 清洗/增强函数都在 ask.js 的 IIFE 内部，浏览器里通过 window.__askTest
// （照既有 window.I18n.__test_setLang 的做法）调到**真正在跑的那份实现**。
// ⚠ 不能照抄一份到测试里 —— 抄的和线上代码会各自腐化，这正是本门禁要抓的那类 bug。
// ⚠ 但只测运行时不够：万一有人把 DOM 清洗换回正则，运行时仍可能「碰巧」过。
//    所以额外对磁盘源码做形状断言（见下方 ASK_JS）。
const ASK_JS = fs.readFileSync(new URL("../static/ask.js", import.meta.url), "utf8");

// ─── 1. 清洗器 ───
console.log("【1】HTML 清洗器（真跑 static/ask.js 里的实现）");
const page = await browser.newPage();
await page.setViewport({ width: 1352, height: 900 });
await page.goto(`${BASE}/ask`, { waitUntil: "networkidle2" });

// 源码形状断言：清洗器必须是 DOM 白名单，不能退回正则。
// ⚠ **必须先剥注释**——ask.js 里那段「旧实现为什么错」的说明注释本身就写着
//   `onc(?:lick|load|error|...)`，不剥就会让这条断言永远假红。
//   见记忆「断言必须先剥注释」：注释里的代码样文字专治这种朴素 grep。
const ASK_JS_CODE = ASK_JS
  .replace(/\/\*[\s\S]*?\*\//g, "")     // 块注释
  .replace(/^\s*\/\/.*$/gm, "");        // 行注释
ok("源码（剥注释后）不再有旧的 onc(?:lick 正则", !ASK_JS_CODE.includes("onc(?:lick"));
ok("源码使用 DOMParser 白名单清洗",
  ASK_JS_CODE.includes("new DOMParser()")
  && ASK_JS_CODE.includes("SANITIZE_DROP")
  && ASK_JS_CODE.includes("SANITIZE_KEEP"));
ok("源码对 on* 属性走「不在白名单即删除」而非正则",
  ASK_JS_CODE.includes("child.removeAttribute"));

const sanitizeResult = await page.evaluate(() => {
  const api = window.__askTest;
  if (!api) return { missingHook: true };
  const HANDLERS = ["onclick","onload","onerror","onmouseover","onfocus","onblur","onchange","onsubmit"];
  const handlers = {};
  for (const h of HANDLERS) {
    handlers[h] = api.sanitizeHtml(`<div ${h}="alert(1)">x</div>`);
  }
  const cases = {
    "style-js-url":   api.sanitizeHtml('<div style="background:url(javascript:alert(1))">y</div>'),
    "href-js-quoted": api.sanitizeHtml('<a href="javascript:alert(1)">x</a>'),
    "href-js-plain":  api.sanitizeHtml('<a href=javascript:alert(1)>x</a>'),
    "img-onerror":    api.sanitizeHtml('<img src=y onerror="alert(1)">'),
    "svg-onload":     api.sanitizeHtml('<svg onload=alert(1)><circle/></svg>'),
    // ⚠ 下面几个危险标签必须放在**正文流里**（前面顶一个 <p>）才有判别力。
    //   HTML 解析器会把「出现在文档开头」的 <script>/<style>/<title> 归入 <head>，
    //   而 sanitizeHtml 只取 doc.body.innerHTML ⇒ 那种写法无论 DROP 还是 unwrap
    //   都会「看起来被清了」，属于假绿。顶个 <p> 把它们逼进 body。
    "script-tag":     api.sanitizeHtml("<p>x</p><script>alert(1)</script>tail"),
    "style-tag":      api.sanitizeHtml("<p>x</p><style>body{display:none}</style>tail"),
    "iframe":         api.sanitizeHtml('<p>x</p><iframe src="//evil"></iframe>tail'),
    "form-input":     api.sanitizeHtml('<p>x</p><form action="/x"><input name="a"></form>tail'),
    "data-uri-img":   api.sanitizeHtml('<img src="data:text/html,<script>alert(1)</script>">'),
    "noscript-mxss":  api.sanitizeHtml('<noscript><p title="</noscript><img src=x onerror=alert(1)>">'),
    "unknown-tag":    api.sanitizeHtml("<marquee>keep text</marquee>"),
    // 正常 markdown 不能被误伤
    "keep-h2":        api.sanitizeHtml("<h2>标题</h2>"),
    "keep-table":     api.sanitizeHtml("<table><thead><tr><th>a</th></tr></thead><tbody><tr><td>1</td></tr></tbody></table>"),
    "keep-pre":       api.sanitizeHtml("<pre><code>x=1</code></pre>"),
    "keep-safe-link": api.sanitizeHtml('<a href="https://example.com/a">l</a>'),
    "keep-rel-link":  api.sanitizeHtml('<a href="/ask">l</a>'),
    "keep-anchor":    api.sanitizeHtml('<a href="#x">l</a>'),
  };
  const md = api.renderMarkdown("## 标题\n\n**粗** | `code`\n\n| a | b |\n|---|---|\n| 1 | 2 |\n");
  return { handlers, cases, md };
});
ok("window.__askTest 钩子已挂上", !sanitizeResult.missingHook);

for (const [h, out] of Object.entries(sanitizeResult.handlers)) {
  ok(`${h} 被清除`, !new RegExp(h, "i").test(out), `残留 "${out}"`);
}
const C = sanitizeResult.cases;
ok("style 属性被清除", !/style/i.test(C["style-js-url"]), C["style-js-url"]);
ok("href=javascript:（带引号）被清除", !/javascript:/i.test(C["href-js-quoted"]), C["href-js-quoted"]);
ok("href=javascript:（无引号）被清除", !/javascript:/i.test(C["href-js-plain"]), C["href-js-plain"]);
ok("<img> 整个删除", !/<img/i.test(C["img-onerror"]), C["img-onerror"]);
ok("<svg onload> 整个删除", !/onload|<svg/i.test(C["svg-onload"]), C["svg-onload"]);
// ⚠ 判据必须是「标签和内容都没了」，不能只看标签消失。
//   DROP 与 unwrap 对无子节点的标签（img/iframe/input）结果一样，只查标签会假绿；
//   而 <script>/<style> 这类**带文本内容**的，一旦从 DROP 挪走就会被 unwrap
//   成明文塞进气泡（"alert(1)" / CSS 文本直接显示给用户）。所以断言整体输出。
ok("<script> 连内容一起删除", C["script-tag"] === "<p>x</p>tail", JSON.stringify(C["script-tag"]));
ok("<style> 连内容一起删除", C["style-tag"] === "<p>x</p>tail", JSON.stringify(C["style-tag"]));
ok("<iframe> 整个删除", C["iframe"] === "<p>x</p>tail", JSON.stringify(C["iframe"]));
ok("<form>/<input> 整个删除", C["form-input"] === "<p>x</p>tail", JSON.stringify(C["form-input"]));
ok("data: URI 图片被清除", !/data:/i.test(C["data-uri-img"]), C["data-uri-img"]);
ok("noscript mXSS 向量被清除", !/onerror|<img/i.test(C["noscript-mxss"]), C["noscript-mxss"]);
ok("未知标签 unwrap 但文字保留", !/<marquee/i.test(C["unknown-tag"]) && /keep text/.test(C["unknown-tag"]), C["unknown-tag"]);
// 反向：正常内容必须活着
ok("h2 保留", /<h2>标题<\/h2>/.test(C["keep-h2"]), C["keep-h2"]);
ok("表格保留", /<table>/.test(C["keep-table"]) && /<th>a<\/th>/.test(C["keep-table"]), C["keep-table"]);
ok("代码块保留", /<pre><code>x=1<\/code><\/pre>/.test(C["keep-pre"]), C["keep-pre"]);
ok("https 链接保留", /href="https:\/\/example\.com\/a"/.test(C["keep-safe-link"]), C["keep-safe-link"]);
ok("站内链接保留", /href="\/ask"/.test(C["keep-rel-link"]), C["keep-rel-link"]);
ok("页内锚点保留", /href="#x"/.test(C["keep-anchor"]), C["keep-anchor"]);
ok("renderMarkdown 端到端出 h2 + table",
  /<h2>/.test(sanitizeResult.md) && /<table>/.test(sanitizeResult.md), sanitizeResult.md.slice(0, 120));

// ─── 2. 移动端 390px 内容驱动裁切 ───
console.log("\n【2】移动端 390px：内容驱动的横向裁切");
const mob = await browser.newPage();
await mob.setViewport({ width: 390, height: 844 });
await mob.goto(`${BASE}/ask`, { waitUntil: "networkidle2" });

const CASES = {
  table: `| 周期 | 命中率 | 样本 | 最佳月 | 夏普 | 回撤 | 备注 |\n|---|---|---|---|---|---|---|\n| t0 | 62.3% | 128 | 2026-03 | 1.42 | -8.1% | 无 |`,
  pre: "```json\n" + JSON.stringify({ symbol: "XAU", price_usd: 4094.5, change_pct: -0.26, updated_at: "2026-10-22T07:00:00+08:00" }, null, 2) + "\n```",
  longurl: "见 https://www.example.com/a/very/long/path/that/has/no/spaces/at/all/segment1234567890 了解更多",
  longtoken: "`aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa`",
};
for (const [name, md] of Object.entries(CASES)) {
  // 两种真实形状都要跑：
  //   assistant → .message > .bubble-wrap > .bubble（markdown 渲染）
  //   user      → .message > .bubble 直接挂，文本走 textContent、**没有 <p> 包裹**
  // ⚠ 用户那条路径是补上的：按 `p/li/td/th` 写 overflow-wrap 命中不到纯文本节点，
  //   漏了它用户发条长 URL 就能把气泡撑到 525px（视口 352px），尾巴滚不到。
  for (const who of ["assistant", "user"]) {
    const r = await mob.evaluate(({ md, who }) => {
      document.getElementById("emptyState")?.remove();
      const stream = document.getElementById("messageStream");
      stream.innerHTML = "";
      const wrap = document.createElement("div");
      wrap.className = "message " + who;
      wrap.innerHTML = `<div class="avatar">${who === "user" ? "我" : "AI"}</div>`;
      const b = document.createElement("div");
      b.className = "bubble";
      if (who === "user") b.textContent = md;
      else b.innerHTML = window.marked.parse(md, { gfm: true, breaks: true });
      if (who === "assistant") {
        const outer = document.createElement("div");
        outer.className = "bubble-wrap";
        outer.appendChild(b);
        wrap.appendChild(outer);
      } else {
        wrap.appendChild(b);
      }
      stream.appendChild(wrap);
      const vw = document.documentElement.clientWidth;
      // ⚠ 横向滚动容器（pre / .table-scroll）**内部**的元素本来就该比视口宽 ——
      //   那正是「能横滚」的含义。判据只算「够不着」的内容：既超出视口右缘、
      //   又不在任何 overflow-x:auto/scroll 的祖先里。
      const inScroller = (el) => {
        let n = el.parentElement;
        while (n && n !== document.body) {
          const ox = getComputedStyle(n).overflowX;
          if (ox === "auto" || ox === "scroll") return true;
          n = n.parentElement;
        }
        return false;
      };
      const clipped = [...b.querySelectorAll("table,pre,p,li,a,code,h2,div")]
        .map((e) => ({ tag: e.tagName, right: Math.round(e.getBoundingClientRect().right), scrollable: inScroller(e) }))
        .filter((x) => x.right > vw + 1 && !x.scrollable);
      return {
        vw,
        docScrollW: document.documentElement.scrollWidth,
        streamW: stream.clientWidth,
        bubbleRight: Math.round(b.getBoundingClientRect().right),
        clipped,
      };
    }, { md, who });
    ok(`${who}/${name}：气泡右缘在视口内`, r.bubbleRight <= r.vw + 1, `bubble right=${r.bubbleRight} vw=${r.vw}`);
    ok(`${who}/${name}：对话列不撑破视口`, r.streamW <= r.vw + 1, `streamW=${r.streamW} vw=${r.vw}`);
    ok(`${who}/${name}：没有元素超出视口右缘`, r.clipped.length === 0, JSON.stringify(r.clipped));
    ok(`${who}/${name}：文档不横向溢出`, r.docScrollW <= r.vw + 1, `scrollW=${r.docScrollW} vw=${r.vw}`);
  }
}
// 直接断言计算样式：布局断言只看「有没有超出」，无法区分「靠 min-width:0 撑住」
// 还是「靠 overflow-wrap 断行」。这两条规则各自负责一件事，必须分别钉住。
const wrapRules = await mob.evaluate(() => {
  document.getElementById("emptyState")?.remove();
  const stream = document.getElementById("messageStream");
  stream.innerHTML = "";
  const mk = (who) => {
    const w = document.createElement("div");
    w.className = "message " + who;
    const b = document.createElement("div");
    b.className = "bubble";
    b.textContent = "x";
    w.appendChild(b);
    stream.appendChild(w);
    const cs = getComputedStyle(b);
    return { overflowWrap: cs.overflowWrap, minWidth: cs.minWidth };
  };
  const user = mk("user");
  const streamCs = getComputedStyle(stream);
  return { user, streamMinWidth: streamCs.minWidth };
});
ok("用户气泡 overflow-wrap=anywhere（长 URL 靠它断行）",
  wrapRules.user.overflowWrap === "anywhere", wrapRules.user.overflowWrap);
ok("气泡 min-width=0（否则自身撑不开）",
  wrapRules.user.minWidth === "0px", wrapRules.user.minWidth);
ok("对话列 min-width=0（否则整列被 <pre> 顶宽）",
  wrapRules.streamMinWidth === "0px", wrapRules.streamMinWidth);
await mob.close();

// ─── 3. 排版 ───
console.log("\n【3】排版：标题 / 分隔线 / 双气泡");
const typo = await page.evaluate(() => {
  const wrap = document.createElement("div");
  wrap.className = "message assistant";
  wrap.innerHTML = '<div class="avatar">AI</div>';
  const outer = document.createElement("div");
  outer.className = "bubble-wrap";
  const b = document.createElement("div");
  b.className = "bubble";
  b.innerHTML = window.marked.parse(
    "## 第一个标题\n\n正文一\n\n## 第二个标题\n\n正文二\n\n---\n\n结尾",
    { gfm: true, breaks: true });
  outer.appendChild(b);
  wrap.appendChild(outer);
  document.getElementById("messageStream").appendChild(wrap);

  const h2s = [...b.querySelectorAll("h2")];
  const hr = b.querySelector("hr");
  const cs = (e) => (e ? getComputedStyle(e) : null);
  return {
    nestedBubble: !!b.querySelector(".bubble"),
    h2Count: h2s.length,
    firstH2Mt: h2s[0] ? cs(h2s[0]).marginTop : null,
    secondH2Mt: h2s[1] ? cs(h2s[1]).marginTop : null,
    secondH2Mb: h2s[1] ? cs(h2s[1]).marginBottom : null,
    h2Fs: h2s[0] ? cs(h2s[0]).fontSize : null,
    bubbleFs: cs(b).fontSize,
    hrMt: hr ? cs(hr).marginTop : null,
    hrMb: hr ? cs(hr).marginBottom : null,
    hrBorderTop: hr ? cs(hr).borderTopWidth : null,
    // hr 与后续段落之间必须真的有间距
    hrToNextGap: (() => {
      if (!hr) return null;
      const next = hr.nextElementSibling;
      if (!next) return null;
      return Math.round(next.getBoundingClientRect().top - hr.getBoundingClientRect().bottom);
    })(),
  };
});
ok("气泡内不再嵌套 .bubble（无双边框）", typo.nestedBubble === false);
ok("渲染出 2 个 h2", typo.h2Count === 2, `实际 ${typo.h2Count}`);
ok("第一个 h2 上边距为 0（贴合气泡顶）", typo.firstH2Mt === "0px", typo.firstH2Mt);
ok("后续 h2 上边距非 0（不再贴脸）", parseFloat(typo.secondH2Mt) > 0, typo.secondH2Mt);
ok("h2 下边距非 0", parseFloat(typo.secondH2Mb) > 0, typo.secondH2Mb);
ok("h2 字号小于浏览器默认 1.5em（19.5px）",
  parseFloat(typo.h2Fs) < parseFloat(typo.bubbleFs) * 1.5, `h2=${typo.h2Fs} body=${typo.bubbleFs}`);
ok("hr 上下留白非 0", parseFloat(typo.hrMt) > 0 && parseFloat(typo.hrMb) > 0, `${typo.hrMt}/${typo.hrMb}`);
ok("hr 与下一段之间确有间距", typo.hrToNextGap >= 8, `${typo.hrToNextGap}px`);

// ─── 4. 真实会话：增强管道 ───
console.log("\n【4】真实会话 + 增强管道");
const errs = new Set();
page.on("pageerror", (e) => errs.add(`pageerror: ${e}`));
page.on("console", (m) => { if (m.type() === "error") errs.add(`console: ${m.text()}`); });
page.on("response", (r) => { if (r.status() >= 400) errs.add(`HTTP ${r.status()} ${r.url()}`); });

await page.goto(`${BASE}/ask`, { waitUntil: "networkidle2" });
const convCount = await page.evaluate(() => {
  const items = [...document.querySelectorAll("#convList .conv-item")];
  if (items.length) items[0].click();
  return items.length;
});
await new Promise((r) => setTimeout(r, 2500));

const real = await page.evaluate(() => {
  const asst = [...document.querySelectorAll("#messageStream .message.assistant")];
  const nested = asst.filter((a) => a.querySelector(".bubble .bubble")).length;
  const borders = asst.map((a) => {
    const b = a.querySelector(".bubble");
    return b ? getComputedStyle(b).borderTopWidth : "none";
  });
  return {
    assistantCount: asst.length,
    nested,
    distinctBorders: [...new Set(borders)],
    convTitle: document.getElementById("convTitle")?.textContent.trim() || "",
  };
});
ok(`会话列表有 ${convCount} 条`, convCount > 0, `实际 ${convCount}`);
ok("真实会话渲染出 assistant 气泡", real.assistantCount > 0, `实际 ${real.assistantCount}`);
ok("真实会话无双气泡", real.nested === 0, `${real.nested} 处嵌套`);
ok("真实会话气泡只有 1 种边框宽度", real.distinctBorders.length === 1, JSON.stringify(real.distinctBorders));

// 增强管道：走**真实的 renderMarkdown + enhanceBubble**（window.__askTest），
// 不能自己 innerHTML 塞一份 —— 那样测的就不是线上跑的那条路径了。
const enhance = await page.evaluate(() => {
  const api = window.__askTest;
  document.getElementById("emptyState")?.remove();
  const stream = document.getElementById("messageStream");
  stream.innerHTML = "";
  const md = "### 标题\n\n| a | b |\n|---|---|\n| 1 | 2 |\n\n```js\nconst x = 1;\n```\n\n[外链](https://example.com) 与 [站内](/ask) 与 [锚点](#x)";
  const wrap = document.createElement("div");
  wrap.className = "message assistant";
  wrap.innerHTML = '<div class="avatar">AI</div>';
  const outer = document.createElement("div");
  outer.className = "bubble-wrap";
  const b = document.createElement("div");
  b.className = "bubble";
  b.innerHTML = api.renderMarkdown(md);
  api.enhanceBubble(b, true);
  outer.appendChild(b);
  wrap.appendChild(outer);
  stream.appendChild(wrap);
  const tbl = b.querySelector("table");
  const scroll = b.querySelector(".table-scroll");
  const links = [...b.querySelectorAll("a")];
  return {
    tableExists: !!tbl,
    scrollExists: !!scroll,
    scrollRole: scroll?.getAttribute("role") || null,
    scrollTabindex: scroll?.getAttribute("tabindex") || null,
    scrollWrapsTable: !!scroll && scroll.contains(tbl),
    copyBtn: b.querySelector(".copy-code-btn")?.textContent || null,
    // ⚠ 按钮必须挂在**不滚动的包装层**里：<pre> 自己 overflow-x:auto，
    //   按钮放进去横向一滚就跟着滚走了（用户滚到长行末尾想复制，按钮不在右上角）。
    btnInWrapper: !!b.querySelector(".code-block > .copy-code-btn"),
    btnInPre: !!b.querySelector("pre .copy-code-btn"),
    // 几何判据（不是 padding 代理）：按钮矩形与 <pre> 矩形**不得相交**。
    // ⚠ 曾经想用「给 pre 加 padding-right」来腾位置 —— 错。滚动容器的
    //   padding-right 只在滚动末端生效，scrollLeft=0 时长代码行照样从按钮
    //   底下穿过去（截图实测：第一行 JSON 被 ⧉ 压住）。
    btnPosition: getComputedStyle(b.querySelector(".copy-code-btn")).position,
    btnOverlapsPre: (() => {
      const btn = b.querySelector(".copy-code-btn"), pre = b.querySelector("pre");
      if (!btn || !pre) return null;
      const a = btn.getBoundingClientRect(), c = pre.getBoundingClientRect();
      return a.left < c.right && a.right > c.left && a.top < c.bottom && a.bottom > c.top;
    })(),
    linkHrefs: links.map((a) => a.getAttribute("href")),
    linkTargets: links.map((a) => a.getAttribute("target")),
    linkRels: links.map((a) => a.getAttribute("rel")),
    // 幂等：再跑一次不能套出两层 .table-scroll / 两个按钮
  };
});
ok("表格存在", enhance.tableExists);
ok("enhanceBubble 套了 .table-scroll", enhance.scrollExists);
ok(".table-scroll 带 role=region", enhance.scrollRole === "region", String(enhance.scrollRole));
ok(".table-scroll 带 tabindex=0（键盘可横滚）", enhance.scrollTabindex === "0", String(enhance.scrollTabindex));
ok(".table-scroll 确实包住了 table", enhance.scrollWrapsTable);
ok("代码块有复制按钮", enhance.copyBtn === "⧉", String(enhance.copyBtn));
ok("复制按钮挂在 .code-block 包装层（横滚时不被带走）", enhance.btnInWrapper && !enhance.btnInPre,
  `wrapper=${enhance.btnInWrapper} inPre=${enhance.btnInPre}`);
// ⚠ 几何断言单用不够：把按钮改回 position:absolute 时，包装层是 static，
//   绝对定位解析到别处去了，两矩形**恰好不相交** ⇒ 96 passed 假绿（实测过）。
//   所以同时钉死「不在常规流之外」这条属性。
ok("复制按钮在常规流里（不在代码块上叠压）", enhance.btnPosition !== "absolute",
  enhance.btnPosition);
ok("复制按钮不与代码块重叠（工具条行，不遮挡内容）", enhance.btnOverlapsPre === false,
  `overlaps=${enhance.btnOverlapsPre}`);
ok("外链拿到 target=_blank", enhance.linkTargets[0] === "_blank", JSON.stringify(enhance.linkTargets));
ok("外链拿到 rel=noopener noreferrer", enhance.linkRels[0] === "noopener noreferrer", JSON.stringify(enhance.linkRels));
ok("站内链接不开新窗", enhance.linkTargets[1] === null, JSON.stringify(enhance.linkTargets));
ok("页内锚点不开新窗", enhance.linkTargets[2] === null, JSON.stringify(enhance.linkTargets));

// 幂等性：enhanceBubble 连跑两次不能叠加
const idem = await page.evaluate(() => {
  const api = window.__askTest;
  const stream = document.getElementById("messageStream");
  const b = stream.querySelector(".bubble");
  api.enhanceBubble(b, true);
  api.enhanceBubble(b, true);
  return {
    scrolls: b.querySelectorAll(".table-scroll").length,
    copyBtns: b.querySelectorAll(".copy-code-btn").length,
    codeBlocks: b.querySelectorAll(".code-block").length,
    tables: b.querySelectorAll("table").length,
  };
});
ok("enhanceBubble 幂等：table-scroll 只有 1 层", idem.scrolls === 1, `${idem.scrolls}`);
ok("enhanceBubble 幂等：复制按钮只有 1 个", idem.copyBtns === 1, `${idem.copyBtns}`);
ok("enhanceBubble 幂等：code-block 包装只有 1 层", idem.codeBlocks === 1, `${idem.codeBlocks}`);
ok("enhanceBubble 幂等：table 只有 1 个", idem.tables === 1, `${idem.tables}`);

// 流式路径（isFinal=false）不该挂复制按钮
const streaming = await page.evaluate(() => {
  const api = window.__askTest;
  const b = document.createElement("div");
  b.className = "bubble";
  b.innerHTML = api.renderMarkdown("```js\nlet y = 2;\n```");
  api.enhanceBubble(b, false);
  return { copyBtns: b.querySelectorAll(".copy-code-btn").length };
});
ok("流式期间不挂复制按钮", streaming.copyBtns === 0, `${streaming.copyBtns}`);

const errList = [...errs].filter((e) => !/favicon/i.test(e));
ok("无 console / pageerror / HTTP>=400", errList.length === 0, errList.slice(0, 4).join(" | "));

await browser.close();
console.log(`\n结果：${pass} passed, ${fail} failed`);
if (fail) console.log(`失败项：\n  - ${failures.join("\n  - ")}`);
process.exit(fail === 0 ? 0 : 1);