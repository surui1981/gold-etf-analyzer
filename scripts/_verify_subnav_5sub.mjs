// scripts/_verify_subnav_5sub.mjs
// V0.103.1 C3 验证：5 个情报子页 subnav 显示一致性
// - 期望：5 个子页的 .subnav width = 1352px (1400 viewport - 48px margin)
// - 期望：bg / border / padding / border-radius 在 5 个子页完全一致
// - 期望：5 个 tab 全部可见，active 高亮
import puppeteer from "puppeteer-core";

const subs = [
  { name: "news",          url: "/news" },
  { name: "central_bank",  url: "/central-bank" },
  { name: "silver",        url: "/static/silver.html" },
  { name: "headlines",     url: "/headlines" },
  { name: "favorites",     url: "/favorites" },
];

const browser = await puppeteer.launch({
  executablePath: "/home/surui/.cache/puppeteer/chrome/linux-153.0.8010.36/chrome-linux64/chrome",
  headless: "new",
  args: ["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"],
});

const page = await browser.newPage();
await page.setViewport({ width: 1400, height: 600 });

const results = [];
for (const s of subs) {
  const fullUrl = "http://127.0.0.1:8888" + s.url;
  await page.goto(fullUrl, { waitUntil: "networkidle0", timeout: 15000 });
  await new Promise(r => setTimeout(r, 1500));

  const r = await page.evaluate(() => {
    const sn = document.querySelector(".subnav");
    if (!sn) return { found: false };
    const rect = sn.getBoundingClientRect();
    const cs = getComputedStyle(sn);
    return {
      found: true,
      width: Math.round(rect.width),
      x: Math.round(rect.x),
      bg: cs.backgroundColor,
      border: cs.border,
      borderRadius: cs.borderRadius,
      padding: cs.padding,
      marginBottom: cs.marginBottom,
      boxShadow: cs.boxShadow,
      tabs: Array.from(sn.querySelectorAll("a")).map(a => ({
        text: a.textContent.trim().replace(/\s+/g, " "),
        active: a.classList.contains("active"),
        href: a.getAttribute("href"),
      })),
    };
  });
  results.push({ name: s.name, url: s.url, ...r });

  // 截图
  if (r.found) {
    // 先滚动到 subnav 顶部
    await page.evaluate((y) => window.scrollTo(0, Math.max(0, y - 20)), r.y);
    await new Promise(rs => setTimeout(rs, 200));
    const newRect = await page.evaluate(() => {
      const sn = document.querySelector(".subnav");
      const rect = sn.getBoundingClientRect();
      return { x: Math.round(rect.x), y: Math.round(rect.y), w: Math.round(rect.width), h: Math.round(rect.height) };
    });
    await page.screenshot({
      path: `/tmp/subnav_${s.name}.png`,
      clip: { x: newRect.x, y: newRect.y, width: newRect.w, height: newRect.h },
    });
  }
}
await browser.close();

console.log("\n=== V0.103.1 · 5 子页 subnav 一致性 ===");
const widths = results.filter(r => r.found).map(r => r.width);
const allWidth = widths.every(w => w === widths[0]);
console.log(`width: ${JSON.stringify(widths)} ${allWidth ? "✅" : "❌"}`);

const bgs = new Set(results.filter(r => r.found).map(r => r.bg));
console.log(`bg (${bgs.size}种): ${[...bgs].join(" | ")} ${bgs.size === 1 ? "✅" : "❌"}`);

const bdr = new Set(results.filter(r => r.found).map(r => r.borderRadius));
console.log(`border-radius (${bdr.size}种): ${[...bdr].join(" | ")} ${bdr.size === 1 ? "✅" : "❌"}`);

const tabs = new Set(results.filter(r => r.found).map(r => r.tabs.length));
console.log(`tab 数量 (${tabs.size}种): ${[...tabs].join(" | ")} ${tabs.size === 1 ? "✅" : "❌"}`);

console.log("\n=== 各页详情 ===");
for (const r of results) {
  if (!r.found) {
    console.log(`❌ ${r.name} (${r.url}) - 没找到 .subnav`);
    continue;
  }
  console.log(`\n[${r.name}] ${r.url}`);
  console.log(`  width=${r.width}px x=${r.x}px bg=${r.bg} radius=${r.borderRadius} padding=${r.padding}`);
  console.log(`  tabs: ${r.tabs.length} 个`);
  r.tabs.forEach(t => {
    console.log(`    ${t.active ? "🟡" : "⚪"} ${t.text} → ${t.href}`);
  });
}
