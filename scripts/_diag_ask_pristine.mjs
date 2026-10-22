// 诊断 6：不注入任何东西，只量 /ask 页在 390px 的真实布局
import puppeteer from "puppeteer-core";
const CHROME = "/home/surui/.cache/puppeteer/chrome/linux-153.0.8010.36/chrome-linux64/chrome";
const BASE = "http://127.0.0.1:8888";

const browser = await puppeteer.launch({
  executablePath: CHROME, headless: "new",
  args: ["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"],
});
for (const [w, h] of [[390, 844], [1352, 900]]) {
  const page = await browser.newPage();
  await page.setViewport({ width: w, height: h });
  await page.goto(`${BASE}/ask`, { waitUntil: "networkidle2" });
  const r = await page.evaluate(() => {
    const pick = (sel) => {
      const e = document.querySelector(sel);
      if (!e) return null;
      const r = e.getBoundingClientRect();
      const s = getComputedStyle(e);
      return { w: Math.round(r.width), left: Math.round(r.left), right: Math.round(r.right),
               display: s.display, overflowX: s.overflowX, minWidth: s.minWidth, flex: s.flex };
    };
    const widest = [...document.querySelectorAll("body *")]
      .map((e) => ({ sel: e.tagName + "." + (e.className || "").toString().split(" ")[0], r: e.getBoundingClientRect().right }))
      .filter((x) => x.r > 391)
      .slice(0, 8);
    return {
      viewport: innerWidth,
      docScrollW: document.documentElement.scrollWidth,
      docClientW: document.documentElement.clientWidth,
      bodyScrollW: document.body.scrollWidth,
      askShell: pick(".ask-shell"),
      main: pick(".ask-main"),
      chat: pick(".ask-chat"),
      stream: pick("#messageStream"),
      inputWrap: pick(".ask-input, .composer, #askInput") ,
      overflowing: widest,
    };
  });
  console.log(JSON.stringify(r, null, 2));
  await page.close();
}
await browser.close();