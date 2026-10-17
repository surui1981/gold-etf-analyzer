/* V0.91.0 · 跨页上下文保留
 * nav-context.js — 9 业务页 filter / range / 账本 等状态的「跨页持久化」
 *
 * 设计动机：9 个业务页（trend / portfolio / trades / weights / news / review /
 * central-bank / silver / backtest）的筛选 / 范围 / 账本状态过去全 DOM-based，
 * 跨页跳转即丢 —— 在 /news 看完当日打分跳去 /review，日期 / 账本 / 标的
 * 全部重置，要重新点选（agent 调研确认）。
 *
 * 设计取舍：
 * 1. **统一命名空间 pm_ctx_v1_*** —— 借鉴 pm_help_seen_version 升级机制
 *    （V0.58.0 help.js）；未来字段增删可改 v2 强制重置，零迁移成本。
 * 2. **避用 URL hash 存 context** —— review.html 的 #status hash 已被
 *    warning.js 占用做 statusPanel 深链展开（agent 警告 R1）。本模块
 *    全部用 `?` query 串做 URL 载体 + localStorage 兜底。
 * 3. **mount 时读 + change 时写** —— 与 account.js / synthesis-card.js
 *    范式一致；不监听 storage 事件（多 tab 同步不必要）。
 * 4. **不监听 i18n:change** —— context 是结构化数据，无 i18n 需求。
 * 5. **零新依赖** —— 纯浏览器 API（localStorage / URLSearchParams /
 *    history.replaceState / CustomEvent）。
 * 6. **页面 mount 时按需 apply** —— 各页在 bottom 调一次
 *    `NavContext.apply(map)`，map 形如 {fStart: "#fStart", days: "#selDays"}，
 *    找到对应 input/select 并设值；空值不设。
 * 7. **页面 change 时单点写** —— 各页在 input.onChange 调
 *    `NavContext.write('fStart', el.value)`，单点写避免重复触发。
 * 8. **导出按钮 / 跨页链接** —— `NavContext.buildQuery(keys)` 返回
 *    "?k1=v1&k2=v2" 串，供 <a href> 与 window.open 拼装。
 *
 * 加载方式：9 页 head 同步追加（无 defer，与 topnav.js 一致避免 FOUC）：
 *   <script src="/static/nav-context.js"></script>
 * 必须在 topnav.js 之后、account.js 之前加载（account-changed 事件可能
 * 触发本模块重写 URL）。
 *
 * 兼容性：所有现代浏览器；URLSearchParams IE 不支持（项目早就不支持 IE）。
 */

(function () {
  "use strict";

  // 命名空间
  const NS = "pm_ctx_v1_";
  // 支持的 key 清单（白名单：避免 LS 任意键污染）
  // 实际使用中各页只读自己关心的子集。
  // V0.98 C6：扩到 21 个 key（含 portfolio/sort/period/account_id + 通用 from/to）
  const SUPPORTED = [
    "fStart", "fEnd", "fSide", "fPosition", "fKeyword", "fSize",  // trades
    "target", "horizon", "days",                                  // review / backtest
    "snapDays", "klineDays", "klineInterval",                     // trend
    "filterCountry", "filterFrom", "filterTo",                    // central-bank
    "compressThreshold",                                          // (V0.90.1 timeline 用)
    // V0.98 C6：URL 状态化扩面
    "account_id", "sort", "period",                               // portfolio
    "category",                                                   // news
    "group_by", "hit",                                            // scoring
    "equity_days", "slippage",                                    // backtest
    "tag_filter",                                                 // review
    "from", "to",                                                 // 通用日期窗口（跨页链接用）
  ];

  function lsKey(k) { return NS + k; }

  function safeGet(k) {
    try { return localStorage.getItem(lsKey(k)); } catch (e) { return null; }
  }
  function safeSet(k, v) {
    try {
      if (v == null || v === "") localStorage.removeItem(lsKey(k));
      else localStorage.setItem(lsKey(k), String(v));
    } catch (e) { /* 隐私模式 */ }
  }

  /**
   * 读单个 key —— 优先 URL query 串，再回退 localStorage。
   * @param {string} key
   * @returns {string|null}
   */
  function get(key) {
    if (SUPPORTED.indexOf(key) < 0) return null;
    try {
      const u = new URLSearchParams(location.search);
      const q = u.get(key);
      if (q != null && q !== "") return q;
    } catch (e) { /* URLSearchParams 不可用 */ }
    return safeGet(key);
  }

  /**
   * 写单个 key 到 localStorage（不更新 URL；如需 URL 同步另调 updateUrl）。
   * @param {string} key
   * @param {string|number|null} value 空值/0/false 也允许写入（与 get 对称）
   */
  function write(key, value) {
    if (SUPPORTED.indexOf(key) < 0) return;
    safeSet(key, value);
    // 派发事件：跨组件同步（与 account-changed 范式一致）
    document.dispatchEvent(new CustomEvent("nav-context-changed", { detail: { key, value } }));
  }

  /**
   * 应用到 DOM —— 按 map 把当前值写到对应 input/select。
   * @param {Object<string,string|HTMLElement>} map 例如 {fStart: "#fStart", days: "#selDays"}
   * @param {Object<string,string>} [defaults] 例如 {fSize: "50"}（get 不到时的兜底）
   */
  function apply(map, defaults) {
    if (!map) return;
    defaults = defaults || {};
    Object.keys(map).forEach(function (key) {
      const sel = map[key];
      const el = typeof sel === "string" ? document.querySelector(sel) : sel;
      if (!el) return;
      const v = get(key) || defaults[key];
      if (v == null || v === "") return;
      // <input type=date|number|text|search> / <select> 都支持直接设 value
      try { el.value = String(v); } catch (e) { /* 防御：奇葩控件 */ }
    });
  }

  /**
   * 绑定变更监听 —— change 事件触发时写入 LS。
   * @param {Object<string,string|HTMLElement>} map
   * @param {function(string,string):void} [onAfter] 写入后回调（供业务侧触发 reload）
   */
  function bind(map, onAfter) {
    if (!map) return;
    Object.keys(map).forEach(function (key) {
      const sel = map[key];
      const el = typeof sel === "string" ? document.querySelector(sel) : sel;
      if (!el) return;
      const handler = function () {
        write(key, el.value);
        if (typeof onAfter === "function") onAfter(key, el.value);
      };
      el.addEventListener("change", handler);
    });
  }

  /**
   * 拼装 query 串 —— 供 <a href> 与 window.open 使用。
   * @param {string[]} keys
   * @returns {string} 形如 "?fStart=2026-10-05&days=90"（无值时返回 ""）
   */
  function buildQuery(keys) {
    if (!keys || !keys.length) return "";
    const parts = [];
    keys.forEach(function (k) {
      if (SUPPORTED.indexOf(k) < 0) return;
      const v = get(k);
      if (v != null && v !== "") parts.push(encodeURIComponent(k) + "=" + encodeURIComponent(v));
    });
    return parts.length ? "?" + parts.join("&") : "";
  }

  /**
   * 同步当前 URL —— 把指定 keys 写到 location.search（replaceState 不留历史）。
   * @param {string[]} keys
   */
  function updateUrl(keys) {
    if (!keys || !keys.length) return;
    const u = new URLSearchParams(location.search);
    keys.forEach(function (k) {
      if (SUPPORTED.indexOf(k) < 0) return;
      const v = get(k);
      if (v != null && v !== "") u.set(k, String(v));
      else u.delete(k);
    });
    const qs = u.toString();
    const newUrl = location.pathname + (qs ? "?" + qs : "") + location.hash;
    try { history.replaceState(null, "", newUrl); } catch (e) { /* file:// 或权限问题 */ }
  }

  /**
   * 拼装报告入口 URL —— 顶栏导出按钮 / 各页跳转报告都用。
   * 报告页硬约束：days ≤ 250（兼容 decision/etf 接口 250 上限）。
   * @param {Object} opt
   * @param {string} [opt.from] 起始日期 YYYY-MM-DD
   * @param {string} [opt.to] 结束日期 YYYY-MM-DD
   * @param {string|number} [opt.days] 预设窗口（7/30/90/180）
   * @returns {string}
   */
  function buildReportUrl(opt) {
    opt = opt || {};
    const params = [];
    if (opt.from) params.push("from=" + encodeURIComponent(opt.from));
    if (opt.to) params.push("to=" + encodeURIComponent(opt.to));
    if (opt.days != null && opt.days !== "") params.push("days=" + encodeURIComponent(opt.days));
    // 携带账本（account.js 用 gold_account_id，不在 SUPPORTED 内；直接读 LS）
    try {
      const acc = localStorage.getItem("gold_account_id");
      if (acc && acc !== "all") params.push("account_id=" + encodeURIComponent(acc));
    } catch (e) { /* ignore */ }
    return "/report" + (params.length ? "?" + params.join("&") : "");
  }

  // V0.98 C6：bindToFilters —— 一键绑定多个 filter + 自动 updateUrl + debounce
  /**
   * 批量绑定 input/select 的 change 事件 + 写 LS + 自动 updateUrl + debounce。
   * @param {Object<string,string|HTMLElement>} map 例如 {fStart: "#fStart", days: "#selDays"}
   * @param {Object} [opts] { debounce: 200, writeUrl: true, onAfter: fn }
   * @returns {function():void} 卸载函数（解绑所有事件）
   */
  function bindToFilters(map, opts) {
    if (!map) return function () {};
    opts = opts || {};
    const debounce = typeof opts.debounce === "number" ? opts.debounce : 200;
    const writeUrl = opts.writeUrl !== false; // 默认 true
    const onAfter = opts.onAfter;
    const handlers = [];

    // per-key debounce 计时器
    const timers = {};

    Object.keys(map).forEach(function (key) {
      const sel = map[key];
      const el = typeof sel === "string" ? document.querySelector(sel) : sel;
      if (!el) return;
      const handler = function () {
        write(key, el.value);
        if (writeUrl) {
          // debounce: 200ms 内多次 change 只 updateUrl 1 次
          clearTimeout(timers[key]);
          timers[key] = setTimeout(function () {
            try { updateUrl([key]); } catch (e) { /* ignore */ }
          }, debounce);
        }
        if (typeof onAfter === "function") onAfter(key, el.value);
      };
      el.addEventListener("change", handler);
      handlers.push({ el, handler });
    });

    // 返回卸载函数
    return function unbind() {
      handlers.forEach(function (h) {
        try { h.el.removeEventListener("change", h.handler); } catch (e) { /* ignore */ }
      });
      Object.keys(timers).forEach(function (k) { clearTimeout(timers[k]); });
    };
  }

  // V0.98 C6：crossLink —— 拼装跨页跳转 URL（带当前 context）
  /**
   * 拼装跨页链接 URL —— 在当前 context 基础上叠加指定 keys。
   * @param {string[]} keys 需要携带的 key 列表
   * @param {string} [basePath] 目标路径（默认当前 location.pathname）
   * @returns {string} 形如 "/scoring?from=2024-10-01&to=2024-10-17"
   */
  function crossLink(keys, basePath) {
    const path = basePath || location.pathname;
    const q = buildQuery(keys);
    return path + q;
  }

  // V0.98 C6：setContext —— 写 context + 跨 tab 同步
  /**
   * 写 context 并广播 nav-context-changed 事件（同 tab 内 dispatch 即可）。
   * 跨 tab 同步：监听 'storage' 事件，当其他 tab 写同 NS key 时自动 reload。
   *
   * 注意：浏览器 storage 事件只在 OTHER tabs 触发（同 tab 不触发，避免死循环）。
   */
  function setContext(key, value) {
    write(key, value);
  }

  // V0.98 C6：initCrossTabSync —— 跨 tab 同步（mount 时调一次）
  let _storageBound = false;
  function initCrossTabSync(onExternalChange) {
    if (_storageBound) return;
    _storageBound = true;
    window.addEventListener("storage", function (e) {
      if (!e.key || e.key.indexOf(NS) !== 0) return;
      const k = e.key.slice(NS.length);
      if (SUPPORTED.indexOf(k) < 0) return;
      if (typeof onExternalChange === "function") {
        onExternalChange(k, e.newValue);
      } else {
        // 默认：派发 nav-context-changed 事件（同 tab 同形式）
        document.dispatchEvent(new CustomEvent("nav-context-changed", {
          detail: { key: k, value: e.newValue, external: true }
        }));
      }
    });
  }

  // 暴露 API
  window.PM_NavContext = {
    SUPPORTED: SUPPORTED,
    get: get,
    write: write,
    apply: apply,
    bind: bind,
    buildQuery: buildQuery,
    updateUrl: updateUrl,
    buildReportUrl: buildReportUrl,
    // V0.98 C6
    bindToFilters: bindToFilters,
    crossLink: crossLink,
    setContext: setContext,
    initCrossTabSync: initCrossTabSync,
  };
})();
