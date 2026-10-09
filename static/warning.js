/*!
 * warning.js —— 投资警示 disclosure 双向 toggle + sessionStorage 记忆（V0.83）
 *
 * 用法：页面加 `<details id="warnFooter">` + `<button data-warn-toggle>` + `<input data-warn-dismiss>`
 *       并引入本脚本即可。脚本会：
 *         1. 把页面原有 warn-footer 默认设为关闭（节省首屏空间）
 *         2. 顶 nav 按钮 ↔ 底部 details open 态双向同步（aria-expanded）
 *         3. 「本次会话不再展开」勾选 → sessionStorage 标记 → 下次会话前不再打开
 *         4. 当页 hash 含 #warn 时主动展开（深链）
 *
 * 设计要点
 * --------
 * - **极轻量**：纯原生 IIFE（~40 行），无外部依赖，挂在 window.WarnDisclosure 命名空间。
 * - **不绑 i18n**：toggle/dismiss 文案直接走 data-i18n，脚本只切换状态。
 * - **可降级**：脚本加载失败时 `<details>` 仍可手点（native 控件）。
 */
(function () {
  "use strict";

  var STORAGE_KEY = "pm_warn_dismissed_session";

  function boot() {
    var footer = document.getElementById("warnFooter");
    var toggles = document.querySelectorAll("[data-warn-toggle]");
    var dismiss = document.querySelector("[data-warn-dismiss]");
    if (!footer) return;

    // sessionStorage 检查 —— 已勾选过「不再展开」则跳过默认展开
    var dismissed = false;
    try { dismissed = sessionStorage.getItem(STORAGE_KEY) === "1"; } catch (e) {}

    // 默认状态：dismissed=开 / 否则关（节省首屏空间）
    if (dismissed) {
      footer.removeAttribute("open");
    } else if (!footer.hasAttribute("open")) {
      // 保持关闭 —— 用户点 summary 或顶 nav 按钮再展开
      footer.removeAttribute("open");
    }

    // hash 深链：#warn 主动展开
    if (location.hash === "#warn") {
      footer.setAttribute("open", "");
    }

    // 顶 nav 按钮 ↔ details open 态同步
    function syncToggle() {
      var open = footer.hasAttribute("open");
      toggles.forEach(function (b) {
        b.setAttribute("aria-expanded", open ? "true" : "false");
      });
    }

    toggles.forEach(function (btn) {
      btn.addEventListener("click", function (e) {
        e.preventDefault();
        if (footer.hasAttribute("open")) {
          footer.removeAttribute("open");
        } else {
          footer.setAttribute("open", "");
        }
        syncToggle();
      });
    });

    footer.addEventListener("toggle", syncToggle);
    syncToggle();

    // 「本次会话不再展开」勾选
    if (dismiss) {
      dismiss.checked = dismissed;
      // V0.83 C1 · a11y：把 hint span 与 checkbox 关联，让屏幕阅读器在聚焦时朗读「本次会话不再展开」
      if (!dismiss.hasAttribute("aria-describedby")) {
        var hint = document.getElementById("warnDismissHint");
        if (hint) dismiss.setAttribute("aria-describedby", "warnDismissHint");
      }
      dismiss.addEventListener("change", function () {
        try {
          if (dismiss.checked) {
            sessionStorage.setItem(STORAGE_KEY, "1");
            footer.removeAttribute("open");
            syncToggle();
          } else {
            sessionStorage.removeItem(STORAGE_KEY);
          }
        } catch (e) { /* 隐私模式：忽略 */ }
      });
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }

  window.WarnDisclosure = { STORAGE_KEY: STORAGE_KEY };
})();
