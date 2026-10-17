#!/usr/bin/env node
/*!
 * scripts/check_nav_context.mjs — V0.98 C6 nav-context.js 单元测试
 *
 * 用 node + jsdom-like polyfills 验证 3 个新 helper：
 * 1. bindToFilters — change 事件 → 写 LS + 触发 updateUrl + debounce
 * 2. crossLink — 拼装跨页 URL
 * 3. setContext / initCrossTabSync — 跨 tab 同步
 *
 * 不是正式的 e2e 探针（puppeteer 那种）；只是防止 V0.98 C6 新加的
 * helper 改坏了已有功能。
 */

import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";

const __dirname = dirname(fileURLToPath(import.meta.url));
const NAV_CTX_PATH = resolve(__dirname, "../static/nav-context.js");

// ── 极简 DOM polyfill（够 nav-context.js 用）──

class FakeStorageEvent {
  constructor(key, newValue) {
    this.key = key;
    this.newValue = newValue;
  }
}

const localStorageData = {};
const localStorage = {
  getItem: (k) => (k in localStorageData ? localStorageData[k] : null),
  setItem: (k, v) => { localStorageData[k] = String(v); },
  removeItem: (k) => { delete localStorageData[k]; },
  clear: () => { Object.keys(localStorageData).forEach((k) => delete localStorageData[k]); },
};

let currentSearch = "";
let currentPathname = "/scoring";
let currentHash = "";

const historyState = [];

const document = {
  dispatchEvent: () => true,
  addEventListener: () => {},
  removeEventListener: () => {},
  querySelector: () => null,
  createElement: () => ({ addEventListener: () => {}, style: {}, classList: { add: () => {}, remove: () => {} } }),
};

const window = {
  PM_NavContext: null,
  addEventListener: (ev, fn) => {
    if (ev === "storage") window._storageListener = fn;
  },
  removeEventListener: () => {},
  _storageListener: null,
};

globalThis.localStorage = localStorage;
globalThis.document = document;
globalThis.window = window;
globalThis.location = {
  get search() { return currentSearch; },
  set search(v) { currentSearch = v; },
  get pathname() { return currentPathname; },
  get hash() { return currentHash; },
};
globalThis.history = {
  replaceState: (state, title, url) => {
    historyState.push(url);
    if (url) {
      const u = new URL(url, "http://localhost");
      currentPathname = u.pathname;
      currentSearch = u.search;
      currentHash = u.hash;
    }
  },
  pushState: () => {},
};
globalThis.CustomEvent = class {
  constructor(type, init) {
    this.type = type;
    this.detail = init && init.detail;
  }
};
globalThis.URLSearchParams = URLSearchParams;
globalThis.URL = URL;

// ── 加载 nav-context.js ──
const code = readFileSync(NAV_CTX_PATH, "utf8");
const wrapped = `(function() {\n${code}\n})();`;
eval(wrapped);

const NC = window.PM_NavContext;
if (!NC) {
  console.error("FAIL: window.PM_NavContext not exposed");
  process.exit(1);
}

// ── 辅助：清状态 ──
function reset() {
  localStorage.clear();
  historyState.length = 0;
  currentSearch = "";
  currentPathname = "/scoring";
  currentHash = "";
}

// ── 测试 ──
let passed = 0;
let failed = 0;

function check(name, cond, detail) {
  if (cond) {
    passed++;
    console.log(`  ✅ ${name}`);
  } else {
    failed++;
    console.error(`  ❌ ${name}${detail ? ": " + detail : ""}`);
  }
}

console.log("\n=== T1: 基础 get/write/buildQuery/updateUrl ===");
reset();
NC.write("days", "30");
check("write days=30 → LS has pm_ctx_v1_days=30", localStorage.getItem("pm_ctx_v1_days") === "30");
check("get('days') returns 30", NC.get("days") === "30");

// URL 优先
currentSearch = "?days=90&horizon=t1";
check("URL 优先 over LS", NC.get("days") === "90");
check("URL: get('horizon') = t1", NC.get("horizon") === "t1");

const q = NC.buildQuery(["days", "horizon"]);
check("buildQuery returns ?days=90&horizon=t1", q === "?days=90&horizon=t1");

NC.updateUrl(["days", "horizon", "fStart"]);
check("updateUrl writes to location.search", currentSearch === "?days=90&horizon=t1");

console.log("\n=== T2: V0.98 C6 新 helpers ===");
reset();

// bindToFilters
check("bindToFilters 是函数", typeof NC.bindToFilters === "function");
check("crossLink 是函数", typeof NC.crossLink === "function");
check("setContext 是函数", typeof NC.setContext === "function");
check("initCrossTabSync 是函数", typeof NC.initCrossTabSync === "function");

// crossLink
currentSearch = "?from=2024-10-10&to=2024-10-17&target=GLD";
currentPathname = "/scoring";
const cl = NC.crossLink(["from", "to", "target"], "/backtest");
check(
  "crossLink 拼 /backtest?from=...&to=...&target=GLD",
  cl === "/backtest?from=2024-10-10&to=2024-10-17&target=GLD",
  `got: ${cl}`,
);

// setContext
reset();
NC.setContext("days", "60");
check("setContext 写入 LS", localStorage.getItem("pm_ctx_v1_days") === "60");
check("setContext 触发 get 返回 60", NC.get("days") === "60");

// initCrossTabSync
reset();
let externalChange = null;
NC.initCrossTabSync((k, v) => { externalChange = { k, v }; });
check("initCrossTabSync 注册 storage listener", typeof window._storageListener === "function");
// 模拟其他 tab 修改 LS
window._storageListener(new FakeStorageEvent("pm_ctx_v1_days", "180"));
check("跨 tab 同步触发 onExternalChange", externalChange && externalChange.k === "days" && externalChange.v === "180");

// bindToFilters 行为：模拟一个 fake input + 调 bindToFilters → change → 看 LS + URL
reset();
const fakeInput = { value: "90", addEventListener: (ev, fn) => { fakeInput._handler = fn; }, removeEventListener: () => {} };
// 模拟 querySelector
const origQSA = document.querySelector;
document.querySelector = (sel) => (sel === "#testInput" ? fakeInput : null);
const unbind = NC.bindToFilters({ days: "#testInput" }, { debounce: 50 });
check("bindToFilters 返回 unbind 函数", typeof unbind === "function");
// 触发 change
fakeInput._handler();
// 不等 debounce：LS 应已写（write 是同步）
check("change 立即写 LS", localStorage.getItem("pm_ctx_v1_days") === "90");
// 等 debounce 后看 URL
await new Promise((r) => setTimeout(r, 80));
check("debounce 后 updateUrl 写 URL", currentSearch.includes("days=90"), `search=${currentSearch}`);
unbind();
document.querySelector = origQSA;

console.log("\n=== T3: 边界 ===");
reset();
// 白名单
check("get('malicious') returns null (白名单)", NC.get("malicious") === null);
check("write('malicious', 'x') 不写 LS", localStorage.getItem("pm_ctx_v1_malicious") === null);
// 空值
NC.write("days", "");
check("write('') 删除 LS key", localStorage.getItem("pm_ctx_v1_days") === null);

// 总结
console.log(`\n=== 结果：${passed} passed, ${failed} failed ===`);
if (failed > 0) process.exit(1);
