// scripts/_diag_hit_months.mjs
// 诊断（`_` 前缀 = 诊断脚本，非门禁，按仓库既有约定）：
//   /scoring「命中分析」Tab 实跑 dump 全部表格 —— A1「上涨日数恒为 0」的复现证据。
//   跑法：node scripts/_diag_hit_months.mjs   （需 8888 服务在跑）
//   判据：12 列「统计区间」表的每一行，「上涨日数」都是 0。
// ⚠ 视口必须显式设 1352×900（默认 800×600 下 sticky nav 盖 Tab 按钮）。
import puppeteer from 'puppeteer-core';
const CHROME='/home/surui/.cache/puppeteer/chrome/linux-153.0.8010.36/chrome-linux64/chrome';
const b = await puppeteer.launch({executablePath: CHROME, args:['--no-sandbox','--disable-dev-shm-usage']});
const p = await b.newPage();
await p.setViewport({width:1352,height:900});
await p.goto('http://127.0.0.1:8888/static/scoring.html',{waitUntil:'networkidle2',timeout:60000});
await new Promise(r=>setTimeout(r,2500));
// 切到第 3 个 tab
const tabs = await p.$$eval('[role="tab"],.tab,button', els=>els.map(e=>e.textContent.trim()).filter(t=>t.includes('命中')));
console.log('tabs containing 命中:', JSON.stringify(tabs));
const clicked = await p.evaluate(()=>{
  const el=[...document.querySelectorAll('button,[role=tab],.tab')].find(e=>e.textContent.includes('命中'));
  if(!el) return false; el.click(); return true;
});
console.log('clicked:', clicked);
await new Promise(r=>setTimeout(r,3000));
const rows = await p.evaluate(()=>{
  const out=[];
  document.querySelectorAll('table').forEach(t=>{
    const th=[...t.querySelectorAll('thead th')].map(x=>x.textContent.trim());
    // 不筛列：全部 dump
    t.querySelectorAll('tbody tr').forEach(tr=>{
      out.push([...tr.querySelectorAll('td')].map(x=>x.textContent.trim()));
    });
    out.unshift(th);
  });
  return out;
});
console.log('命中分析表（含期间/涨/跌列）:');
rows.forEach(r=>console.log('  '+JSON.stringify(r)));
await p.screenshot({path:'/tmp/shot_hit.png',fullPage:false});
await b.close();
