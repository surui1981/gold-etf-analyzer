/* =========================================================================
 * theme.js — V0.69.0 主题切换控制器
 *
 * 4 主题：light / dark / auto / hc (WCAG AAA)
 * 命名空间：window.Theme，localStorage key = "pm_theme_mode"
 * FOUC 防护：每页 head 第一行内联脚本（见本文件底部 BOOTSTRAP 注释块）
 *
 * 事件契约：
 *   document.addEventListener("theme:change", e => { e.detail.mode, e.detail.effective })
 *   TL?.track("theme_change", { mode, effective })  when TL 已加载
 * ========================================================================= */
(function () {
  "use strict";

  var LS_KEY = "pm_theme_mode";
  var VALID = ["light", "dark", "auto", "hc"];
  var mql = null;  // 延迟到第一次 apply() 创建（matchMedia SSR 不安全）

  // ── 公共 API ───────────────────────────────────────
  function getMode() {
    try {
      var v = localStorage.getItem(LS_KEY) || "light";
      return VALID.indexOf(v) >= 0 ? v : "light";
    } catch (e) { return "light"; }
  }

  function getEffective() {
    var mode = getMode();
    if (mode === "auto") {
      try {
        var dark = (mql || (mql = window.matchMedia("(prefers-color-scheme: dark)"))).matches;
        return dark ? "dark" : "light";
      } catch (e) { return "light"; }
    }
    if (mode === "hc") return "hc";
    return mode;  // "light" | "dark"
  }

  function apply(effective) {
    if (VALID.indexOf(effective) < 0 && effective !== "dark" && effective !== "light" && effective !== "hc") return;
    document.documentElement.setAttribute("data-theme", effective);
    // Chart.js：reduced-motion 同步（与 prefers-reduced-motion CSS 媒体查询呼应）
    try {
      if (window.Chart && window.Chart.defaults) {
        var reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
        window.Chart.defaults.animation = !reduce;
        window.Chart.defaults.transitions = window.Chart.defaults.transitions || {};
      }
    } catch (e) { /* Chart 未加载或未初始化，静默 */ }
  }

  function setMode(mode, opts) {
    opts = opts || {};
    if (VALID.indexOf(mode) < 0) mode = "light";
    try { localStorage.setItem(LS_KEY, mode); } catch (e) { /* 隐私模式 */ }
    var effective = (mode === "auto") ? getEffective() : (mode === "hc" ? "hc" : mode);
    apply(effective);
    if (!opts.silent) {
      try {
        document.dispatchEvent(new CustomEvent("theme:change", { detail: { mode: mode, effective: effective } }));
      } catch (e) { /* IE 不支持 CustomEvent */ }
      try {
        if (window.TL && typeof window.TL.track === "function") {
          window.TL.track("theme_change", { mode: mode, effective: effective });
        }
      } catch (e) { /* telemetry 缺失静默 */ }
    }
    // 同步切换器 UI（如已挂载）
    syncSwitcherUI();
  }

  function cycleMode() {
    var cur = getMode();
    var idx = VALID.indexOf(cur);
    var next = VALID[(idx + 1) % VALID.length];
    setMode(next);
    return next;
  }

  // ── 切换器 UI（浮动按钮 + 下拉）──────────────────
  var SWITCHER_BTN_ID = "pmThemeBtn";
  var SWITCHER_MENU_ID = "pmThemeMenu";
  var ICONS = { light: "☀", dark: "🌙", auto: "🌓", hc: "◐" };
  var LABELS = {
    light: "浅色模式",
    dark: "深色模式",
    auto: "跟随系统",
    hc: "高对比度"
  };

  function ensureSwitcherDOM() {
    if (document.getElementById(SWITCHER_BTN_ID)) return;
    var btn = document.createElement("button");
    btn.id = SWITCHER_BTN_ID;
    btn.type = "button";
    btn.setAttribute("aria-label", "切换主题");
    btn.setAttribute("aria-haspopup", "true");
    btn.setAttribute("aria-expanded", "false");
    btn.setAttribute("aria-controls", SWITCHER_MENU_ID);
    btn.textContent = ICONS[getEffective()] || "☀";

    var menu = document.createElement("div");
    menu.id = SWITCHER_MENU_ID;
    menu.setAttribute("role", "radiogroup");
    menu.setAttribute("aria-label", "选择主题");
    VALID.forEach(function (mode) {
      var item = document.createElement("button");
      item.type = "button";
      item.setAttribute("role", "radio");
      item.setAttribute("data-mode", mode);
      item.setAttribute("aria-checked", getMode() === mode ? "true" : "false");
      var icon = document.createElement("span");
      icon.className = "pm-mode-icon";
      icon.setAttribute("aria-hidden", "true");
      icon.textContent = ICONS[mode];
      var txt = document.createElement("span");
      txt.textContent = LABELS[mode];
      item.appendChild(icon);
      item.appendChild(txt);
      item.addEventListener("click", function () { setMode(mode); closeMenu(); });
      menu.appendChild(item);
    });

    document.body.appendChild(btn);
    document.body.appendChild(menu);
    btn.addEventListener("click", toggleMenu);
    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape") closeMenu();
    });
    document.addEventListener("click", function (e) {
      if (!menu.contains(e.target) && e.target !== btn) closeMenu();
    });
  }

  function syncSwitcherUI() {
    var btn = document.getElementById(SWITCHER_BTN_ID);
    if (btn) btn.textContent = ICONS[getEffective()] || "☀";
    var menu = document.getElementById(SWITCHER_MENU_ID);
    if (menu) {
      Array.from(menu.querySelectorAll("[data-mode]")).forEach(function (el) {
        el.setAttribute("aria-checked", getMode() === el.getAttribute("data-mode") ? "true" : "false");
      });
    }
  }

  function toggleMenu() {
    var menu = document.getElementById(SWITCHER_MENU_ID);
    var btn = document.getElementById(SWITCHER_BTN_ID);
    if (!menu || !btn) return;
    var open = menu.classList.toggle("open");
    btn.setAttribute("aria-expanded", open ? "true" : "false");
  }
  function closeMenu() {
    var menu = document.getElementById(SWITCHER_MENU_ID);
    var btn = document.getElementById(SWITCHER_BTN_ID);
    if (menu) menu.classList.remove("open");
    if (btn) btn.setAttribute("aria-expanded", "false");
  }

  function bindSwitcher() {
    ensureSwitcherDOM();
    syncSwitcherUI();
    // 跟系统模式变化
    try {
      mql = mql || window.matchMedia("(prefers-color-scheme: dark)");
      var listener = function () {
        if (getMode() === "auto") setMode("auto", { silent: true });
      };
      if (mql.addEventListener) mql.addEventListener("change", listener);
      else if (mql.addListener) mql.addListener(listener);
    } catch (e) { /* matchMedia 不支持 */ }
  }

  // ── 系统主题变化主动通知 ─────────────────────────
  window.addEventListener("DOMContentLoaded", function () {
    bindSwitcher();
    syncSwitcherUI();
  });

  // ── 公共暴露 ─────────────────────────────────────
  window.Theme = {
    getMode: getMode,
    getEffective: getEffective,
    setMode: setMode,
    cycleMode: cycleMode,
    apply: apply,
    bindSwitcher: bindSwitcher
  };
})();

/* =========================================================================
 * FOUC 防护头脚本（需 inline 到每页 <head> 第一行）
 *
 * <script>(function(){
 *   try {
 *     var k="pm_theme_mode", v=localStorage.getItem(k)||"light";
 *     if(!["light","dark","auto","hc"].indexOf(v)>=0) v="light";
 *     var eff=v==="auto"?(matchMedia("(prefers-color-scheme: dark)").matches?"dark":"light"):v;
 *     document.documentElement.setAttribute("data-theme",eff);
 *   } catch(e){ document.documentElement.setAttribute("data-theme","light"); }
 * })();</script>
 * ========================================================================= */