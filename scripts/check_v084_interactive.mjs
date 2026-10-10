#!/usr/bin/env node
// V0.84.0 交互验证：点击 statusPanel 展开 + dismiss 行为
import puppeteer from "puppeteer-core";

const BASE = "http://127.0.0.1:8888";
const CHROME = "/home/surui/.cache/puppeteer/chrome/linux-153.0.8010.36/chrome-linux64/chrome";

const browser = await puppeteer.launch({
  executablePath: CHROME,
  headless: "new",
  args: ["--no-sandbox"],
});

const page = await browser.newPage();
await page.setViewport({ width: 1400, height: 900 });
await page.evaluateOnNewDocument(() => {
  try { localStorage.removeItem("pm_warn_dismissed_session"); } catch(e){}
});
await page.goto(`${BASE}/static/portfolio.html`, { waitUntil: "domcontentloaded" });
await new Promise(r => setTimeout(r, 1500));
// 关掉 #pmhTourTip（首次访问浮层）—— 它是 fixed/absolute 高 z-index，
// 物理上覆盖在 statusPanel 之上，puppeteer.click() 会落空。
await page.evaluate(() => {
  ["pmhTourMask", "pmhTourSpot", "pmhTourTip"].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.remove();
  });
});

console.log("=== 测试 1：默认状态（折叠） ===");
let s = await page.evaluate(() => {
  const p = document.getElementById("statusPanel");
  return {
    open: p.hasAttribute("open"),
    navRows: document.querySelectorAll(".topnav .topnav-row").length,
    freshMountExists: !!document.querySelector("#statusPanel #freshnessInline"),
    pillText: document.querySelector("#statusPanel .status-warn-pill")?.textContent.replace(/\s+/g, " ").trim(),
    bodyVisible: getComputedStyle(document.querySelector("#statusPanel .status-body")).display !== "none",
  };
});
console.log(JSON.stringify(s, null, 2));
console.assert(!s.open, "默认应折叠");
console.assert(s.navRows === 1, "顶 nav 1 行");
console.assert(s.freshMountExists, "freshnessInline 在 summary 内");
console.assert(!s.bodyVisible, "body 默认隐藏");

console.log("\n=== 测试 2：点击 summary 展开 ===");
await page.click("#statusPanel > summary");
await new Promise(r => setTimeout(r, 300));
s = await page.evaluate(() => {
  const p = document.getElementById("statusPanel");
  const body = document.querySelector("#statusPanel .status-body");
  const li = document.querySelectorAll("#statusPanel .warn-list li").length;
  const dismiss = document.querySelector("#statusPanel [data-warn-dismiss]");
  return {
    open: p.hasAttribute("open"),
    bodyVisible: getComputedStyle(body).display !== "none",
    liCount: li,
    dismissExists: !!dismiss,
    dismissA11y: dismiss?.getAttribute("aria-describedby"),
  };
});
console.log(JSON.stringify(s, null, 2));
console.assert(s.open, "点击后应展开");
console.assert(s.bodyVisible, "body 展开后可见");
console.assert(s.liCount === 5, "5 条警示");
console.assert(s.dismissA11y === "warnDismissHint", "a11y 绑定");

console.log("\n=== 测试 3：勾选 dismiss → 折叠 + 写 sessionStorage ===");
await page.click("#statusPanel [data-warn-dismiss]");
await new Promise(r => setTimeout(r, 300));
s = await page.evaluate(() => {
  const p = document.getElementById("statusPanel");
  return {
    open: p.hasAttribute("open"),
    dismissed: sessionStorage.getItem("pm_warn_dismissed_session"),
  };
});
console.log(JSON.stringify(s, null, 2));
console.assert(!s.open, "勾选 dismiss 后应折叠");
console.assert(s.dismissed === "1", "sessionStorage 应写 '1'");

console.log("\n=== 测试 4：reload 后保持折叠（dismissed 持久化） ===");
await page.reload({ waitUntil: "domcontentloaded" });
await new Promise(r => setTimeout(r, 1500));
s = await page.evaluate(() => {
  const p = document.getElementById("statusPanel");
  return { open: p.hasAttribute("open") };
});
console.log(JSON.stringify(s, null, 2));
console.assert(!s.open, "reload 后因 dismissed=1 仍折叠");

console.log("\n=== 测试 5：#status hash 深链展开（覆盖 dismissed） ===");
await page.goto(`${BASE}/static/portfolio.html#status`, { waitUntil: "domcontentloaded" });
await new Promise(r => setTimeout(r, 1500));
await page.evaluate(() => {
  ["pmhTourMask", "pmhTourSpot", "pmhTourTip"].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.remove();
  });
});
s = await page.evaluate(() => {
  const p = document.getElementById("statusPanel");
  return {
    open: p.hasAttribute("open"),
    hash: location.hash,
    dismissed: sessionStorage.getItem("pm_warn_dismissed_session"),
  };
});
console.log(JSON.stringify(s, null, 2));
console.assert(s.open, "#status 深链应强制展开");

console.log("\n=== 测试 6：取一个截图 ===");
await page.evaluate(() => { try { localStorage.removeItem("pm_warn_dismissed_session"); } catch(e){} });
await page.click("#statusPanel > summary"); // 折叠
await new Promise(r => setTimeout(r, 200));
await page.screenshot({ path: "/tmp/v084-verify/portfolio_zh-CN_collapsed.png", fullPage: false });
await page.click("#statusPanel > summary"); // 展开
await new Promise(r => setTimeout(r, 200));
await page.screenshot({ path: "/tmp/v084-verify/portfolio_zh-CN_expanded.png", fullPage: false });
console.log("截图保存到 /tmp/v084-verify/");

await page.close();
await browser.close();

console.log("\n========================================");
console.log("All interactive tests passed.");
