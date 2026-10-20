import puppeteer from "puppeteer-core";
const browser = await puppeteer.launch({
  executablePath: "/home/surui/.cache/puppeteer/chrome/linux-153.0.8010.36/chrome-linux64/chrome",
  headless: "new",
  args: ["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"],
});
const page = await browser.newPage();
await page.setViewport({ width: 1280, height: 1400 });
await page.goto("http://127.0.0.1:8888/home", { waitUntil: "networkidle2", timeout: 30000 });
await new Promise(r => setTimeout(r, 6000));
// Screenshot bottom section (今日要闻)
const section = await page.$(".home-bottom");
const box = await section.boundingBox();
await page.screenshot({ path: "/tmp/home_section.png", clip: box });
const text = await page.evaluate(() => {
  const section = document.querySelector(".home-bottom");
  return section ? section.innerText : "no section";
});
console.log("=== TEXT CONTENT ===");
console.log(text);
console.log("=== HTML SNIPPET ===");
const html = await page.evaluate(() => {
  const list = document.getElementById("homeNewsList");
  return list ? list.outerHTML.slice(0, 1500) : "no list";
});
console.log(html);
await browser.close();
