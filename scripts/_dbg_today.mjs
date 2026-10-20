import puppeteer from "puppeteer-core";
const b = await puppeteer.launch({
  executablePath: "/home/surui/.cache/puppeteer/chrome/linux-153.0.8010.36/chrome-linux64/chrome",
  headless: "new", args: ["--no-sandbox"],
});
const p = await b.newPage();
await p.setCacheEnabled(false);
await p.setRequestInterception(true);
p.on("request", r => r.url().includes("/favorites/exists/") ? r.respond({status:200,contentType:"application/json",body:"{}"}) : r.continue());
p.on("console", m => console.log("[CONSOLE]", m.type(), m.text().slice(0, 200)));
p.on("pageerror", e => console.log("[ERR]", e.message));
p.on("response", async r => {
  if (r.url().includes("/api/v1/news-feed/items") && !r.url().includes("/favorites")) {
    let b; try { b = await r.json(); } catch (e) { b = "ERR"; }
    console.log("[RESP]", r.status(), "→", JSON.stringify({total: b.total, current_date: b.current_date, has_older: b.has_older, has_newer: b.has_newer, items_len: b.items?.length}).slice(0, 200));
  }
});
await p.goto("http://127.0.0.1:8888/headlines", { waitUntil: "networkidle0" });
await new Promise(r => setTimeout(r, 3000));
const today = await p.evaluate(() => {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,"0")}-${String(d.getDate()).padStart(2,"0")}`;
});
console.log("browser today:", today);
await p.evaluate((t) => {
  const dp = document.getElementById("datePicker");
  const desc = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value");
  desc.set.call(dp, t);
  dp.dispatchEvent(new Event("change", { bubbles: true }));
}, today);
await new Promise(r => setTimeout(r, 4000));
const s = await p.evaluate(() => ({
  todayHidden: document.getElementById("btnToday").hidden,
  listCount: document.querySelectorAll(".news-card").length,
  dpValue: document.getElementById("datePicker").value,
}));
console.log("state:", JSON.stringify(s));
await b.close();
