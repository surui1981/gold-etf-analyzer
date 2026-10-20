import puppeteer from "puppeteer-core";
const browser = await puppeteer.launch({
  executablePath: "/home/surui/.cache/puppeteer/chrome/linux-153.0.8010.36/chrome-linux64/chrome",
  headless: "new",
  args: ["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"],
});
const page = await browser.newPage();
await page.setViewport({ width: 1400, height: 900 });

const errors = [];
page.on("pageerror", e => errors.push("PAGEERROR: " + e.message));
page.on("console", m => { if (m.type() === "error") errors.push("CONSOLE: " + m.text()); });

await page.goto("http://127.0.0.1:8888/favorites", { waitUntil: "networkidle0", timeout: 20000 });
await new Promise(r => setTimeout(r, 2000));

const r = await page.evaluate(() => {
  return {
    title: document.title,
    h1: document.querySelector("h1")?.textContent || null,
    topnavLinks: Array.from(document.querySelectorAll("#topnav-mount a")).map(a => a.textContent.trim()).slice(0, 20),
    activeLink: document.querySelector("#topnav-mount a.active")?.textContent?.trim() || null,
    toolbarExists: !!document.querySelector(".toolbar"),
    cardCount: document.querySelectorAll(".news-card, .fav-card").length,
    chipTotal: document.getElementById("valTotal")?.textContent || null,
    chipSites: document.getElementById("valSites")?.textContent || null,
    bodyText: document.body.innerText.slice(0, 500),
  };
});
console.log("TITLE:", r.title);
console.log("H1:", r.h1);
console.log("ACTIVE_LINK:", r.activeLink);
console.log("TOPNAV_LINKS:", r.topnavLinks);
console.log("TOOLBAR_EXISTS:", r.toolbarExists);
console.log("CARD_COUNT:", r.cardCount);
console.log("CHIP_TOTAL:", r.chipTotal);
console.log("CHIP_SITES:", r.chipSites);
console.log("BODY_TEXT_PREVIEW:");
console.log(r.bodyText);
console.log("ERRORS:", errors.length === 0 ? "(none)" : errors);
await page.screenshot({ path: "/tmp/fav_page.png" });
console.log("Screenshot: /tmp/fav_page.png");
await browser.close();
