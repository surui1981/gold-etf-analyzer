/* V0.98 C3：全局 toast 系统（window.PM_Toast）
 * ─────────────────────────────────────────────────────
 * 模式：IIFE + window.PM_Toast 命名空间
 * 依赖：无（vanilla JS）；可选联动 window.PM_I18N.t(key) 与 window.PM_I18N.lang
 *
 * 设计要点：
 *  - 顶部居中 stacked（toast-container z-index 99999，与 banner 99998 共存）
 *  - 最多 3 个同时，超额挤掉最老（先 dismiss 再插入新）
 *  - 默认 auto-dismiss：info/success/warn = 4s，err = 8s；duration:0 = 不自动消失
 *  - ARIA role=alert/status + aria-live；键盘可达（Tab 在 action → close → 下一 toast）
 *  - Esc 关闭最顶部 toast
 *  - 点 toast 任何位置 / 点 ✕ 关闭
 *  - i18n：优先 window.PM_I18N.t(opts.i18n) ；缺 i18n / 缺函数 → 用 msg 字面量
 *  - 防御性：所有外部依赖 typeof 检查；不抛错
 */
(function () {
  "use strict";

  const MAX_VISIBLE = 3;
  const DEFAULT_DURATION = 4000;
  const ERR_DURATION = 8000;

  const container = (function () {
    if (document.getElementById("pm-toast-container")) {
      return document.getElementById("pm-toast-container");
    }
    const el = document.createElement("div");
    el.id = "pm-toast-container";
    el.className = "pm-toast-container";
    el.setAttribute("aria-live", "polite");
    el.setAttribute("aria-relevant", "additions text");
    // 提前挂到 <body>，避免异步插入位置错乱
    if (document.body) {
      document.body.appendChild(el);
    } else {
      document.addEventListener("DOMContentLoaded", function () {
        if (!el.parentNode) document.body.appendChild(el);
      }, { once: true });
    }
    return el;
  })();

  let counter = 0;
  const active = []; // 存 toastId

  function t(key, fallback) {
    if (key && typeof window.PM_I18N !== "undefined"
        && window.PM_I18N
        && typeof window.PM_I18N.t === "function") {
      try {
        const v = window.PM_I18N.t(key);
        // PM_I18N.t 找不到 key 时返回 key 字符串；这时退回 fallback
        if (v && v !== key) return key;
      } catch (_) { /* 静默 */ }
    }
    return fallback;
  }

  function resolveMsg(msg, opts) {
    if (opts && typeof opts.i18n === "string" && opts.i18n) {
      const translated = t(opts.i18n, msg);
      // 如果 i18n 拿到的不是 key 本身，就用它；否则用 msg
      if (translated !== opts.i18n) return translated;
    }
    return msg;
  }

  function removeToast(toastId) {
    const idx = active.indexOf(toastId);
    if (idx >= 0) active.splice(idx, 1);
    const el = document.getElementById(toastId);
    if (el && el.parentNode) el.parentNode.removeChild(el);
  }

  function dismiss(toastId) {
    removeToast(toastId);
  }

  function clear() {
    // 倒序避免 splice 索引错位
    for (let i = active.length - 1; i >= 0; i--) {
      removeToast(active[i]);
    }
  }

  function makeToast(level, msg, opts) {
    opts = opts || {};
    counter += 1;
    const id = "pm-toast-" + level + "-" + counter;
    const isAlert = level === "warn" || level === "err";

    const el = document.createElement("div");
    el.id = id;
    el.className = "pm-toast pm-toast-" + level;
    el.setAttribute("role", isAlert ? "alert" : "status");
    el.setAttribute("aria-live", isAlert ? "assertive" : "polite");
    el.setAttribute("aria-atomic", "true");
    el.tabIndex = 0; // 让 toast 整体可被 Tab 聚焦（保持键盘可达）

    const msgEl = document.createElement("span");
    msgEl.className = "pm-toast-msg";
    msgEl.textContent = resolveMsg(msg, opts);
    el.appendChild(msgEl);

    if (opts.action && typeof opts.action === "object"
        && typeof opts.action.label === "string"
        && typeof opts.action.onClick === "function") {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "pm-toast-action";
      btn.textContent = opts.action.label;
      btn.addEventListener("click", function (e) {
        e.stopPropagation();
        try { opts.action.onClick(); } catch (_) { /* 静默 */ }
        removeToast(id);
      });
      el.appendChild(btn);
    }

    const close = document.createElement("button");
    close.type = "button";
    close.className = "pm-toast-close";
    close.setAttribute("aria-label", "close");
    close.textContent = "×";
    close.addEventListener("click", function (e) {
      e.stopPropagation();
      removeToast(id);
    });
    el.appendChild(close);

    el.addEventListener("click", function () {
      removeToast(id);
    });
    el.addEventListener("keydown", function (e) {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        removeToast(id);
      }
    });

    return el;
  }

  function show(level, msg, opts) {
    opts = opts || {};
    // 超额挤掉最老的（保留可读 FIFO 语义）
    while (active.length >= MAX_VISIBLE) {
      removeToast(active[0]);
    }
    const el = makeToast(level, msg, opts);
    container.appendChild(el);
    const toastId = el.id;
    active.push(toastId);

    // 自动消失
    let dur;
    if (typeof opts.duration === "number") {
      dur = opts.duration;
    } else {
      dur = level === "err" ? ERR_DURATION : DEFAULT_DURATION;
    }
    if (dur > 0) {
      setTimeout(function () { removeToast(toastId); }, dur);
    }

    return toastId;
  }

  // Esc 关闭最顶部 toast
  document.addEventListener("keydown", function (e) {
    if (e.key !== "Escape" && e.key !== "Esc") return;
    if (!active.length) return;
    // 顶部 = 最后一个（最新）
    const top = active[active.length - 1];
    const el = document.getElementById(top);
    if (el && document.activeElement && el.contains(document.activeElement)) {
      removeToast(top);
    } else if (el) {
      // 即便焦点不在 toast 上，Esc 也接受：用户期望"按 Esc 关闭弹窗"
      removeToast(top);
    }
  });

  // show(msg, type)：全站 14 处调用方用的就是这个签名（含 favorites.js /
  // report-archive.js 的 guard `window.PM_Toast && window.PM_Toast.show`）。
  // V0.114.0 之前这里**没有导出** show → 两类坏法：
  //   · headlines.js / home.js 只 guard `window.PM_Toast`，对象存在但 .show 是
  //     undefined → 抛 TypeError，会连带中断后面的语句（收藏成功了却没提示）
  //   · favorites.js / report-archive.js guard 到 .show，为 falsy → 整个 toast
  //     静默不弹，用户点了收藏完全没有反馈
  // 两类都是「点了收藏没反应」。这里补一个派发器一次性修好 14 处调用方。
  const _LEVEL_ALIAS = { error: "err", danger: "err", warning: "warn", ok: "success" };
  window.PM_Toast = {
    info: function (msg, opts) { return show("info", msg, opts); },
    success: function (msg, opts) { return show("success", msg, opts); },
    warn: function (msg, opts) { return show("warn", msg, opts); },
    err: function (msg, opts) { return show("err", msg, opts); },
    // 第二参既接受 level 字符串（info/success/warn/err，或调用方习惯的
    // error/warning…），也接受 opts 对象（与 info/success 同签名）；
    // 未知值退回 info，绝不抛错
    show: function (msg, type, opts) {
      if (type !== null && typeof type === "object") {
        return show("info", msg, type);
      }
      const raw = typeof type === "string" ? type.toLowerCase() : "info";
      const level = _LEVEL_ALIAS[raw] || raw;
      const known = ["info", "success", "warn", "err"].indexOf(level) !== -1;
      return show(known ? level : "info", msg, opts);
    },
    dismiss: dismiss,
    clear: clear,
  };
})();