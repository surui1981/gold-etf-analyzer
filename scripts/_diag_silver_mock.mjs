// scripts/_diag_silver_mock.mjs
// 诊断（`_` 前缀 = 诊断脚本，非门禁）：
//   /silver「多市场升贴水表」实跑取证 —— A5「同一张表里白银有两个价格，差 7 倍」。
//   跑法：node scripts/_diag_silver_mock.mjs   （需 8888 服务在跑）
//   判据：输出里 ETF 列折美元/oz ≈ $7.5，NY 列 ≈ $54.6，比值 ≈ 7.3×；
//         且 sourceBar 显示 sge_silver 为 mock。
// ⚠ 视口必须显式设 1352×900（默认 800×600 下 sticky nav 盖内容）。
import puppeteer from 'puppeteer-core';
const CHROME='/home/surui/.cache/puppeteer/chrome/linux-153.0.8010.36/chrome-linux64/chrome';
const b = await puppeteer.launch({executablePath:CHROME,args:['--no-sandbox','--disable-dev-shm-usage']});
const p = await b.newPage();
await p.setViewport({width:1352,height:900});
await p.goto('http://127.0.0.1:8888/static/silver.html',{waitUntil:'networkidle2',timeout:60000});
await new Promise(r=>setTimeout(r,3000));
const out = await p.evaluate(()=>{
  const r={};
  const bar=document.getElementById('sourceBar');
  r.sourceBar = bar? bar.className+' | '+bar.textContent.trim().slice(0,200) : '（无 #sourceBar）';
  // 升贴水表
  const t=[...document.querySelectorAll('table')].find(x=>/溢价|升贴水|premium/i.test(x.textContent));
  r.premiumTable = t ? [...t.querySelectorAll('tr')].slice(0,6).map(tr=>[...tr.querySelectorAll('th,td')].map(c=>c.textContent.trim()).join(' | ')) : '（未找到升贴水表）';
  r.pageHasMockWord = /演示数据|mock/i.test(document.body.innerText);
  r.mockMentions = (document.body.innerText.match(/[^\n]*演示数据[^\n]*/g)||[]).slice(0,4);
  return r;
});
console.log(JSON.stringify(out,null,1));
await b.close();
