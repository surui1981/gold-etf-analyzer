import puppeteer from "puppeteer-core";
const browser = await puppeteer.launch({
  executablePath: "/home/surui/.cache/puppeteer/chrome/linux-153.0.8010.36/chrome-linux64/chrome",
  headless: "new",
  args: ["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"],
});
const page = await browser.newPage();
await page.setViewport({ width: 1400, height: 900 });

await page.goto("http://127.0.0.1:8888/news", { waitUntil: "networkidle0", timeout: 20000 });
await new Promise(r => setTimeout(r, 2500));

// scroll to subnav and screenshot
const navEl = await page.$('.subnav');
if (navEl) {
  const box = await navEl.boundingBox();
  console.log('subnav box:', JSON.stringify(box));
  await page.screenshot({ path: '/tmp/intel_subnav_only.png', clip: box });
  // also inspect all 5 tabs
  const tabsData = await page.evaluate(() => {
    const tabs = document.querySelectorAll('.subnav a');
    return Array.from(tabs).map(a => {
      const r = a.getBoundingClientRect();
      return { text: a.textContent.trim(), x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width), visible: r.x >= 0 && r.x + r.width <= window.innerWidth };
    });
  });
  console.log('Tabs:', JSON.stringify(tabsData, null, 2));
} else {
  console.log('no subnav found');
}

// also check /headlines
await page.goto("http://127.0.0.1:8888/headlines", { waitUntil: "networkidle0", timeout: 20000 });
await new Promise(r => setTimeout(r, 1500));
const navEl2 = await page.$('.subnav');
if (navEl2) {
  const box2 = await navEl2.boundingBox();
  console.log('headlines subnav box:', JSON.stringify(box2));
  await page.screenshot({ path: '/tmp/headlines_subnav_only.png', clip: box2 });
  const tabsData2 = await page.evaluate(() => {
    const tabs = document.querySelectorAll('.subnav a');
    return Array.from(tabs).map(a => {
      const r = a.getBoundingClientRect();
      return { text: a.textContent.trim(), x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width), visible: r.x >= 0 && r.x + r.width <= window.innerWidth };
    });
  });
  console.log('headlines tabs:', JSON.stringify(tabsData2, null, 2));
}

await browser.close();
