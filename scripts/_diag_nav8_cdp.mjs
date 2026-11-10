// 临时排障脚本（用完即删）：抓 CDP 原始事件，看第 4 次导航到底缺了哪个事件
import puppeteer from "puppeteer-core";

const BASE = process.env.BASE_URL || "http://192.168.0.204:8888";
const CHROME =
  "/home/surui/.cache/puppeteer/chrome/linux-153.0.8010.36/chrome-linux64/chrome";

const browser = await puppeteer.launch({
  executablePath: CHROME,
  headless: "new",
  args: ["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"],
});
const page = await browser.newPage();
await page.setBypassServiceWorker(true);
if (process.env.MODE === "cacheoff") await page.setCacheEnabled(false);

const cdp = await page.createCDPSession();
await cdp.send("Network.enable");
await cdp.send("Page.enable");
await cdp.send("Performance.enable");

const events = [];
let t0 = Date.now();
const stamp = () => String(Date.now() - t0).padStart(6, " ");
function rec(tag, extra = "") {
  events.push(`${stamp()}ms  ${tag} ${extra}`);
  if (events.length > 4000) events.shift();
}

cdp.on("Network.requestWillBeSent", (e) =>
  rec("reqWillBeSent", `${e.requestId.slice(0, 6)} ${e.type.padEnd(10)} ${e.request.url.replace(BASE, "")}`));
cdp.on("Network.responseReceived", (e) =>
  rec("respReceived ", `${e.requestId.slice(0, 6)} ${e.type.padEnd(10)} ${e.response.url.replace(BASE, "")} ${e.response.status} fromCache=${e.response.fromDiskCache}`));
cdp.on("Network.requestServedFromCache", (e) => rec("servedFromCache", e.requestId.slice(0, 6)));
cdp.on("Network.loadingFinished", (e) => rec("loadingFinish ", e.requestId.slice(0, 6)));
cdp.on("Network.loadingFailed", (e) => rec("loadingFailed ", `${e.requestId.slice(0, 6)} ${e.errorText}`));
cdp.on("Page.frameNavigated", (e) =>
  rec("frameNavigated", `${e.frame.loaderId.slice(0, 6)} ${e.frame.url.replace(BASE, "")} type=${e.frame.type}`));
cdp.on("Page.lifecycleEvent", (e) =>
  rec("lifecycle     ", `${e.name.padEnd(16)} loader=${e.loaderId.slice(0, 6)}`));
cdp.on("Page.frameStartedLoading", (e) => rec("frameStartedLoading", e.frameId.slice(0, 6)));
cdp.on("Page.frameStoppedLoading", (e) => rec("frameStoppedLoading", e.frameId.slice(0, 6)));
cdp.on("Page.navigatedWithinDocument", (e) => rec("navigatedWithinDoc", e.url.replace(BASE, "")));
cdp.on("Page.frameRequestedNavigation", (e) => rec("reqNavigation", `${e.url.replace(BASE, "")} reason=${e.reason}`));

async function go(url, tag) {
  console.log(`\n=== goto ${url} (${tag}) ===`);
  events.length = 0;
  t0 = Date.now();
  const wait = process.env.WAIT || "domcontentloaded";
  try {
    await Promise.race([
      page.goto(`${BASE}${url}`, { waitUntil: wait, timeout: 15000 }),
      new Promise((_, rej) => setTimeout(() => rej(new Error("goto 超时 15s")), 15000)),
    ]);
    console.log("  ✓ 完成");
  } catch (e) {
    console.log(`  ✗ ${e.message}`);
    console.log(events.join("\n"));
    await browser.close();
    process.exit(1);
  }
}

await go("/home", "n1");
await go("/weights", "n2");
await go("/data-health", "n3");
await go("/home", "n4");
await go("/weights", "n5");
console.log("全部导航完成");
await browser.close();
