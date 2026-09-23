/*!
 * i18n.js — V0.73.0 国际化控制器
 *
 * 用法：
 *   1) 页面 <head> 在 theme.js 之后插入：
 *        <script src="/static/i18n.js" defer></script>
 *   2) HTML 用 data-i18n / data-i18n-placeholder / data-i18n-title / data-i18n-aria 属性标记
 *   3) JS 端用 window.I18n.t('key.path') 取字符串
 *   4) 用户切换语言：I18n.setLang('en-US')
 *
 * 字典加载策略：
 *   - zh-CN（默认）走 <script src="/static/i18n/zh-CN.js"> 同步加载（precache by sw.js）
 *   - 其他 locale 通过动态 import() 按需 fetch（首次切换后缓存）
 *
 * localStorage 命名空间：
 *   - pm_lang            "zh-CN" | "zh-TW" | "en-US"
 *
 * 事件：
 *   document.addEventListener("i18n:change", e => { e.detail.lang })
 *
 * 命名空间：window.I18n
 */
(function () {
  "use strict";

  const LS_KEY = "pm_lang";
  const DEFAULT_LANG = "zh-CN";
  const SUPPORTED = ["zh-CN", "zh-TW", "en-US"];

  const state = {
    lang: DEFAULT_LANG,
    dict: {},        // lang → dict object
  };

  /* ───────────────── 字典加载 ───────────────── */
  function syncLoadDefault() {
    // zh-CN 默认走 <script> 同步注入（详见 head script）
    if (state.dict[DEFAULT_LANG]) return state.dict[DEFAULT_LANG];
    const dict = (typeof window.PM_I18N_ZH_CN === "object" && window.PM_I18N_ZH_CN) || {};
    state.dict[DEFAULT_LANG] = dict;
    return dict;
  }

  async function loadLang(lang) {
    if (state.dict[lang]) return state.dict[lang];
    if (lang === DEFAULT_LANG) return syncLoadDefault();
    // 动态插入 <script> 标签（避免 ESM 复杂度，与 zh-CN 一致）
    return new Promise(function (resolve) {
      const s = document.createElement("script");
      s.src = `/static/i18n/${lang}.js`;
      s.async = false;  // 同步执行顺序
      s.onload = function () {
        const key = "PM_I18N_" + lang.replace("-", "_");
        state.dict[lang] = (typeof window[key] === "object" && window[key]) || {};
        resolve(state.dict[lang]);
      };
      s.onerror = function () {
        console.warn("[i18n] load", lang, "failed");
        state.dict[lang] = {};
        resolve(state.dict[lang]);
      };
      document.head.appendChild(s);
    });
  }

  /* ───────────────── 字符串查找 ───────────────── */
  function t(key, params) {
    const cur = state.dict[state.lang];
    const fb = state.dict[DEFAULT_LANG];
    let s = (cur && cur[key]) != null ? cur[key] : (fb && fb[key]);
    const hit_fallback = (cur && cur[key]) == null;
    if (s == null) {
      if (window.TL && typeof window.TL.track === "function") {
        window.TL.track("i18n_fallback_hit", { key: key, lang: state.lang });
      }
      return key;  // 字典也找不到 → 返回 key 字面量
    }
    if (params && typeof s === "string") {
      s = s.replace(/\{(\w+)\}/g, function (_m, k) {
        return params[k] != null ? String(params[k]) : ("{" + k + "}");
      });
    }
    if (hit_fallback && window.TL && typeof window.TL.track === "function") {
      window.TL.track("i18n_fallback_hit", { key: key, lang: state.lang });
    }
    return s;
  }

  /* ───────────────── 切换语言 ───────────────── */
  async function setLang(lang) {
    if (SUPPORTED.indexOf(lang) < 0) lang = DEFAULT_LANG;
    await loadLang(lang);
    state.lang = lang;
    try { localStorage.setItem(LS_KEY, lang); } catch (e) { /* 隐私模式 */ }
    apply(document.body);
    document.documentElement.setAttribute("lang", lang);
    document.body.setAttribute("data-lang", lang);
    document.dispatchEvent(new CustomEvent("i18n:change", { detail: { lang: lang } }));
    if (window.TL && typeof window.TL.track === "function") {
      window.TL.track("lang_change", { lang: lang });
    }
  }

  /* ───────────────── 应用到 DOM ───────────────── */
  function apply(root) {
    if (!root) return;
    const nodes = root.querySelectorAll(
      "[data-i18n], [data-i18n-html], [data-i18n-placeholder], [data-i18n-title], [data-i18n-aria]"
    );
    nodes.forEach(function (el) {
      if (el.dataset.i18n) {
        // 保留内联元素子节点（badge / button / icon / sub-span）——只更新直接文本节点
        const translated = t(el.dataset.i18n);
        let textNode = null;
        for (const child of Array.from(el.childNodes)) {
          if (child.nodeType === 3 /* TEXT_NODE */) {
            if (textNode === null) {
              child.nodeValue = translated;
              textNode = child;
            } else {
              el.removeChild(child);
            }
          }
        }
        if (textNode === null) {
          el.insertBefore(document.createTextNode(translated), el.firstChild);
        }
      }
      if (el.dataset.i18nHtml) el.innerHTML = t(el.dataset.i18nHtml);
      if (el.dataset.i18nPlaceholder) el.setAttribute("placeholder", t(el.dataset.i18nPlaceholder));
      if (el.dataset.i18nTitle) el.setAttribute("title", t(el.dataset.i18nTitle));
      if (el.dataset.i18nAria) el.setAttribute("aria-label", t(el.dataset.i18nAria));
    });
  }

  /* ───────────────── 格式化子命名空间 ───────────────── */
  const fmt = {
    number: function (n, opts) {
      opts = opts || {};
      return new Intl.NumberFormat(state.lang, opts).format(n);
    },
    currency: function (n, currency) {
      currency = currency || "CNY";
      return new Intl.NumberFormat(state.lang, { style: "currency", currency: currency }).format(n);
    },
    date: function (d, opts) {
      opts = opts || { dateStyle: "short" };
      return new Intl.DateTimeFormat(state.lang, opts).format(new Date(d));
    },
    dateTime: function (d) {
      return new Intl.DateTimeFormat(state.lang, { dateStyle: "short", timeStyle: "short" }).format(new Date(d));
    },
    time: function (d) {
      return new Intl.DateTimeFormat(state.lang, { timeStyle: "short" }).format(new Date(d));
    },
    percent: function (n, digits) {
      digits = digits == null ? 1 : digits;
      return new Intl.NumberFormat(state.lang, {
        style: "percent",
        minimumFractionDigits: digits,
        maximumFractionDigits: digits,
      }).format(n);
    },
    relative: function (secs) {
      if (secs < 60) return t("time.just_now");
      const m = Math.floor(secs / 60);
      if (m < 60) return t("time.minutes_ago", { n: m });
      const h = Math.floor(m / 60);
      if (h < 24) return t("time.hours_ago", { n: h });
      const d = Math.floor(h / 24);
      return t("time.days_ago", { n: d });
    },
  };

  /* ───────────────── 顶栏语言切换器 ───────────────── */
  function injectSwitcher() {
    if (document.querySelector(".lang-sel")) return;
    if (!document.getElementById("i18nStyle")) {
      const css = "" +
        ".topnav .lang-sel{background:#2b3038;color:#f5d97a;border:1px solid rgba(245,217,122,.35);" +
        "border-radius:8px;padding:5px 8px;font-size:13px;cursor:pointer;margin-left:8px;}" +
        ".topnav .lang-sel:hover{border-color:rgba(245,217,122,.65);}" +
        ".topnav .lang-sel:focus{outline:2px solid #f5d97a;outline-offset:1px;}" +
        "@media (max-width:600px){.topnav .lang-sel{font-size:12px;padding:4px 6px;margin-left:4px;}}";
      const s = document.createElement("style");
      s.id = "i18nStyle";
      s.textContent = css;
      document.head.appendChild(s);
    }
    const nav = document.querySelector(".topnav .links");
    if (!nav) return;
    const sel = document.createElement("select");
    sel.className = "lang-sel";
    sel.setAttribute("aria-label", "Language / 语言");
    sel.title = "切换语言 / Switch language / 切換語言";
    const opts = [
      { v: "zh-CN", l: "简体中文" },
      { v: "zh-TW", l: "繁體中文" },
      { v: "en-US", l: "English" },
    ];
    opts.forEach(function (o) {
      const opt = document.createElement("option");
      opt.value = o.v;
      opt.textContent = o.l;
      if (o.v === state.lang) opt.selected = true;
      sel.appendChild(opt);
    });
    sel.addEventListener("change", function () { setLang(sel.value); });
    nav.appendChild(sel);
    // 监听 i18n:change → 同步切换器显示
    document.addEventListener("i18n:change", function (e) {
      if (sel.value !== e.detail.lang) sel.value = e.detail.lang;
    });
  }

  /* ───────────────── 自动初始化 ───────────────── */
  function getSavedLang() {
    try { return localStorage.getItem(LS_KEY); } catch (e) { return null; }
  }

  function init() {
    syncLoadDefault();
    const saved = getSavedLang();
    state.lang = saved && SUPPORTED.indexOf(saved) >= 0 ? saved : DEFAULT_LANG;
    document.documentElement.setAttribute("lang", state.lang);
    document.body.setAttribute("data-lang", state.lang);
    apply(document.body);
    injectSwitcher();
  }

  // 暴露 API
  window.I18n = {
    t: t,
    setLang: setLang,
    apply: apply,
    fmt: fmt,
    loadLang: loadLang,
    SUPPORTED: SUPPORTED,
    DEFAULT_LANG: DEFAULT_LANG,
    get lang() { return state.lang; },
    // 测试用：直接注入字典 + 切 lang（绕开 setLang 异步加载）
    __test_setLang: function (lang, dict) {
      if (dict) state.dict[lang] = dict;
      state.lang = lang;
    },
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();