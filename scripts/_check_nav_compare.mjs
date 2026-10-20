import puppeteer from "puppeteer-core";
const browser = await puppeteer.launch({
  executablePath: "/home/surui/.cache/puppeteer/chrome/linux-153.0.8010.36/chrome-linux64/chrome",
  headless: "new",
  args: ["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"],
});
const page = await browser.newPage();
await page.setViewport({ width: 1400, height: 900 });

async function inspect(url, label) {
  await page.goto(url, { waitUntil: "networkidle0", timeout: 20000 });
  await new Promise(r => setTimeout(r, 1500));
  const data = await page.evaluate(() => {
    const subnav = document.querySelector('.subnav');
    if (!subnav) return { error: 'no subnav' };
    const tabs = Array.from(subnav.querySelectorAll('a'));
    return {
      tabsCount: tabs.length,
      subnavClass: subnav.className,
      label: subnav.querySelector('.subnav-label')?.textContent.trim() || null,
      subnavBg: getComputedStyle(subnav).backgroundColor,
      subnavBorder: getComputedStyle(subnav).borderBottom,
      subnavPadding: getComputedStyle(subnav).padding,
      tabsBg: tabs[0] ? getComputedStyle(tabs[0]).backgroundColor : null,
      tabsColor: tabs[0] ? getComputedStyle(tabs[0]).color : null,
      tabsPad: tabs[0] ? getComputedStyle(tabs[0]).padding : null,
      tabsRadius: tabs[0] ? getComputedStyle(tabs[0]).borderRadius : null,
    };
  });
  console.log(label, '->', JSON.stringify(data, null, 2));
  await page.screenshot({ path: `/tmp/nav_${label}.png`, clip: { x: 0, y: 130, width: 1400, height: 130 } });
}

await inspect("http://127.0.0.1:8888/news", "intel_news");
await inspect("http://127.0.0.1:8888/portfolio", "portfolio");
await inspect("http://127.0.0.1:8888/weights", "config_weights");
await inspect("http://127.0.0.1:8888/scoring", "decision_scoring");
await browser.close();
