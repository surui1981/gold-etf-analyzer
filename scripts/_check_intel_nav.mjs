import puppeteer from "puppeteer-core";
const browser = await puppeteer.launch({
  executablePath: "/home/surui/.cache/puppeteer/chrome/linux-153.0.8010.36/chrome-linux64/chrome",
  headless: "new",
  args: ["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"],
});
const page = await browser.newPage();
await page.setViewport({ width: 1400, height: 900 });

await page.goto("http://127.0.0.1:8888/news", { waitUntil: "networkidle0", timeout: 20000 });
await new Promise(r => setTimeout(r, 1500));

const r = await page.evaluate(() => {
  const subnav = document.querySelector('.subnav');
  if (!subnav) return { error: 'no subnav' };
  const tabs = Array.from(subnav.querySelectorAll('a'));
  const tabsInfo = tabs.map(a => {
    const r = a.getBoundingClientRect();
    return { text: a.textContent.trim(), top: Math.round(r.top), left: Math.round(r.left), w: Math.round(r.width), h: Math.round(r.height) };
  });
  const subRect = subnav.getBoundingClientRect();
  return {
    subnavW: Math.round(subRect.width),
    subnavH: Math.round(subRect.height),
    tabs: tabsInfo,
    cssRow: getComputedStyle(subnav.querySelector('.subnav-tabs') || subnav).flexWrap,
  };
});
console.log(JSON.stringify(r, null, 2));
await page.screenshot({ path: '/tmp/intel_nav_news.png', fullPage: false });
console.log('Screenshot: /tmp/intel_nav_news.png');

// Try also on /central-bank to see the same subnav
await page.goto("http://127.0.0.1:8888/central-bank", { waitUntil: "networkidle0", timeout: 20000 });
await new Promise(r => setTimeout(r, 1500));
const r2 = await page.evaluate(() => {
  const subnav = document.querySelector('.subnav');
  if (!subnav) return null;
  const tabs = Array.from(subnav.querySelectorAll('a'));
  return tabs.map(a => {
    const r = a.getBoundingClientRect();
    return { text: a.textContent.trim(), top: Math.round(r.top), left: Math.round(r.left) };
  });
});
console.log('central-bank subnav tabs:');
console.log(JSON.stringify(r2, null, 2));

await page.screenshot({ path: '/tmp/intel_nav_central_bank.png', fullPage: false });
await browser.close();
