/*!
 * warning.js —— V0.84.0 投资警示 disclosure 行为（roadmap §4.1 N）
 *
 * 用法：页面加 `<details id="statusPanel" class="status-panel">`，summary 内
 *       包含 `#freshnessInline`（数据时效 chips mount 点）+ `<span data-warn-count>`
 *       （⚠️ 警示条数 pill），body 内含 `<ol class="warn-list">` 与
 *       `<input data-warn-dismiss>`。并引入本脚本即可。脚本会：
 *         1. 根据 `ol.warn-list` 实际 li 数动态写入 `data-warn-count` 文本
 *         2. sessionStorage 记忆「本次会话不再展开」（`pm_warn_dismissed_session`）
 *         3. 当页 hash 含 #status / #warn 时主动展开（深链）
 *         4. 勾选 dismiss → 折叠 + 写 sessionStorage
 *
 * 设计要点
 * --------
 * - **V0.84.0**：从 `<details id="warnFooter">`（页底）合并为 `<details id="statusPanel">`
 *   （顶 nav 紧后）。summary 内同时承载数据时效 + 警示计数 pill；点开看警示全文。
 * - **极轻量**：纯原生 IIFE（~40 行），无外部依赖，挂在 window.WarnDisclosure 命名空间。
 * - **不绑 i18n**：count 文本由 I18n.fmt 渲染（页面自带的 data-i18n 已含 {n} 占位符），
 *   脚本只设置 `<span data-warn-count>` 的 textContent 数字，让 i18n.js 在加载后
 *   重新渲染带格式的字符串。
 * - **可降级**：脚本加载失败时 `<details>` 仍可手点（native 控件）。
 */
(function () {
  "use strict";

  var STORAGE_KEY = "pm_warn_dismissed_session";

  function boot() {
    var panel = document.getElementById("statusPanel");
    if (!panel) return;
    var dismiss = panel.querySelector("[data-warn-dismiss]");

    // 1. 动态计算警示条数 → 写 count pill
    //    文本格式由 i18n.js 负责（key: status.warn_count，{n} 占位符）。
    //    我们只写数字，i18n.js 加载后会自动格式化为「5 条要点」等。
    var list = panel.querySelector(".warn-list");
    var countEl = panel.querySelector("[data-warn-count]");
    if (list && countEl) {
      var n = list.querySelectorAll("li").length;
      countEl.textContent = String(n);
    }

    // 2. 默认折叠态：dismissed=开 / 否则关（节省首屏空间，仅 1 行 summary）
    var dismissed = false;
    try { dismissed = sessionStorage.getItem(STORAGE_KEY) === "1"; } catch (e) {}

    if (dismissed || !panel.hasAttribute("open")) {
      panel.removeAttribute("open");
    }

    // 3. hash 深链：#status / #warn（旧链接兼容）主动展开
    if (location.hash === "#status" || location.hash === "#warn") {
      panel.setAttribute("open", "");
    }

    // V0.84.0：监听 hashchange —— 同一文档内 #status 跳转（同页 / dismiss 后想再看警示）
    // 不会触发 reload，warning.js 不会再跑一遍，需手动响应。
    window.addEventListener("hashchange", function () {
      if (location.hash === "#status" || location.hash === "#warn") {
        panel.setAttribute("open", "");
      }
    });

    // 4. dismiss checkbox 行为
    if (dismiss) {
      dismiss.checked = dismissed;
      // V0.83 C1 · a11y：把 hint span 与 checkbox 关联
      if (!dismiss.hasAttribute("aria-describedby")) {
        var hint = document.getElementById("warnDismissHint");
        if (hint) dismiss.setAttribute("aria-describedby", "warnDismissHint");
      }
      dismiss.addEventListener("change", function () {
        try {
          if (dismiss.checked) {
            sessionStorage.setItem(STORAGE_KEY, "1");
            panel.removeAttribute("open");
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
