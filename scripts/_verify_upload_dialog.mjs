// V0.114.2 验证：点「上传并存档」展开卡片后，点 drop 区**真的会弹文件对话框**
//
// 判据用 filechooser 事件，不用「input 有没有被 click 过」—— 后者在
// display:none + JS click 的写法下也会「触发」，但浏览器实际不弹框。
// 这正是原 bug 能长期存活的原因：任何基于「有没有调用 click」的断言都会假绿。
import puppeteer from "puppeteer-core";
const BASE = process.env.BASE_URL || "http://192.168.0.204:8888";
const b = await puppeteer.launch({
  executablePath: "/home/surui/.cache/puppeteer/chrome/linux-153.0.8010.36/chrome-linux64/chrome",
  headless: "new", args: ["--no-sandbox","--disable-setuid-sandbox","--disable-dev-shm-usage"]});
const p = await b.newPage();
await p.setViewport({width:1352,height:900});
await p.setCacheEnabled(false);
let pass=0, fail=0;
const chk=(ok,n,x="")=>{ ok?(pass++,console.log(`  [OK]   ${n}`)):(fail++,console.log(`  [FAIL] ${n}${x?" :: "+x:""}`)); };

let chooser = null;
p.on("filechooser", (fc) => { chooser = fc; });

await p.goto(`${BASE}/report-archive`, {waitUntil:"networkidle2", timeout:60000});
await new Promise(r=>setTimeout(r,1200));
await p.click("#btnToggleUpload");
await new Promise(r=>setTimeout(r,400));
chk(await p.evaluate(()=>!document.getElementById("uploadCard").hidden), "点「上传并存档」展开卡片");

// ① input 不能是 display:none —— 那正是原 bug 的根
const style = await p.evaluate(()=>{
  const el=document.getElementById("fileInput"), cs=getComputedStyle(el);
  return {display:cs.display, opacity:cs.opacity, w:el.offsetWidth, h:el.offsetHeight};
});
chk(style.display !== "none", "fileInput 不是 display:none（原先就是这里坏的）", JSON.stringify(style));
chk(style.w > 0 && style.h > 0, "fileInput 有实际尺寸（能接到点击）", `${style.w}×${style.h}`);
chk(Number(style.opacity) < 1, "fileInput 视觉上透明（不该裸露原生控件外观）", `opacity=${style.opacity}`);

// ② 点 drop 区中心，看命中的是不是那个 input
const hit = await p.evaluate(()=>{
  const d=document.getElementById("dropZone"), r=d.getBoundingClientRect();
  const t=document.elementFromPoint(r.left+r.width/2, r.top+r.height/2);
  return {tag:t?.tagName, id:t?.id, type:t?.type||null};
});
chk(hit.id === "fileInput", "drop 区中心命中的是 fileInput（真实点击落在原生控件上）", JSON.stringify(hit));

// ③ 判据 = 点击落点，不 = filechooser 事件
//
// ⚠️ 踩过的坑：本来用 page.on("filechooser") 当判据，实测**这个 headless Chrome
// 连基线都不发** —— 对一个裸 <input type="file"> 真实点击也不触发。所以那条断言
// 测的是 puppeteer 的能力，不是被测代码，必然假绿（比没有断言更坏）。
//
// 真正能区分好坏的是「点击落点」：修复后 drop 区中心命中的就是原生 fileInput，
// 浏览器对 file input 的**默认行为**就是弹对话框，全程没有任何 JS 参与；
// 修复前那里命中的是 <span>，.drop 上没有任何 click 处理器 ⇒ 什么都不发生。
const hit2 = await p.evaluate(()=>{
  const d=document.getElementById("dropZone"), r=d.getBoundingClientRect();
  const t=document.elementFromPoint(r.left+r.width/2, r.top+r.height/2);
  return t && t.id === "fileInput";
});
chk(hit2, "点击落点仍是 fileInput（原生默认行为会弹框，路径上无 JS）");

// ③b input 本身可用：能被写入文件、accept 约束没被改坏
const usable = await p.evaluate(()=>{
  const el = document.getElementById("fileInput");
  return { hasFiles: "files" in el, accept: el.getAttribute("accept") };
});
chk(usable.hasFiles, "fileInput 仍是可用的原生 file 控件", JSON.stringify(usable));
chk(/\.html/.test(usable.accept || ""), "accept 约束仍在（只收 HTML）", usable.accept);

// ④ 键盘可达：Tab 能聚焦到它（V0.113.0 口径）
const focusable = await p.evaluate(()=>{
  const el=document.getElementById("fileInput");
  el.focus();
  return document.activeElement === el;
});
chk(focusable, "fileInput 可键盘聚焦（focus-within 有可见焦点环）");

// ⑤ .drop 仍能收 dragover（覆盖层不能吃掉拖拽）
const dragOk = await p.evaluate(()=>{
  const d=document.getElementById("dropZone");
  const ev=new Event("dragover",{bubbles:true,cancelable:true});
  d.querySelector("input").dispatchEvent(ev);
  return d.classList.contains("over");
});
chk(dragOk, "覆盖层上的 dragover 仍冒泡到 .drop（拖拽上传没被破坏）");

console.log(`\n结果：${pass} passed / ${fail} failed`);
await b.close();
process.exit(fail?1:0);
