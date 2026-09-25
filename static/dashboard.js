/* ─────────────────────────────────────────────────────────────────────────
 * V0.74.0 N+17 · Portfolio 仪表盘自定义 · 卡片拖拽排序 + 布局持久化
 *
 * 设计要点（§四 不变项）：
 *   • #2 a11y 全程 ── 键盘替代（Space 抓取 / ↑↓ 移动 / Space 放下）+ aria-live 公告
 *   • #3 只扩展不重写 ── 不动现有 .card 样式，仅加 data-card-key
 *   • #5 单一 CDN ── 零新依赖，原生 HTML5 dragstart/dragover/drop
 *   • #6 单进程状态隔离 ── 纯 localStorage，不引入单例内存
 *
 * 复用：
 *   • lsGet/lsSet ── help.js:233-243 try/catch 模式
 *   • window.I18n.t ── i18n.js (lang 切换时 aria-live 文案自动本地化)
 *   • window.TL.track ── telemetry.js
 *   • showUndoToast ── portfolio.html:437-446（仅在调用方提供 onUndo 时复用）
 *
 * 持久化：
 *   key: pm_dashboard_layout
 *   value: JSON.stringify(["decision","open","positions",...])  ← card-key 数组
 *   缺失 / 损坏 ── 回到默认顺序（原 DOM 顺序 = 业务推荐序）
 * ───────────────────────────────────────────────────────────────────────── */

(function () {
  "use strict";

  const LS_KEY = "pm_dashboard_layout";
  const VERSION = "V0.74.0";  // 与未来升级重置布局的可识别锚

  /* 7 张卡片 key ── 必须与 portfolio.html data-card-key 一一对应 */
  const CARD_KEYS = [
    "decision",   // ETF 购买决策建议
    "open",       // 开仓买入表单
    "positions",  // 当前持仓
    "trade",      // 加仓 / 减仓内联面板（默认 display:none）
    "equity",     // 收益曲线
    "perf",       // 获利分析
    "accounts",   // 账本管理
  ];

  /* ── LS helpers（复用 help.js 风格） ───────────────────────────────── */
  function lsGet(key) {
    try { return localStorage.getItem(key); } catch (e) { return null; }
  }
  function lsSet(key, val) {
    try { localStorage.setItem(key, val); } catch (e) { /* privacy mode */ }
  }

  /* ── 工具 ─────────────────────────────────────────────────────────── */
  function _t(key, fallback) {
    try {
      if (typeof window.I18n !== "undefined" && typeof window.I18n.t === "function") {
        var v = window.I18n.t(key);
        if (v && v !== key) return v;
      }
    } catch (e) { /* ignore */ }
    return fallback;
  }

  function announce(msg) {
    var live = document.getElementById("dashboardLive");
    if (!live) return;
    // 重置文本以触发 SR 重读
    live.textContent = "";
    setTimeout(function () { live.textContent = msg; }, 30);
  }

  function debounce(fn, ms) {
    var t = null;
    return function () {
      var args = arguments, ctx = this;
      clearTimeout(t);
      t = setTimeout(function () { fn.apply(ctx, args); }, ms);
    };
  }

  function track(name, props) {
    try {
      if (typeof window.TL !== "undefined" && typeof window.TL.track === "function") {
        window.TL.track(name, props || {});
      }
    } catch (e) { /* ignore */ }
  }

  function hashOrder(arr) {
    // 简单 fingerprint 给 reset 埋点用，不做密码学强求
    return arr.join("|");
  }

  /* ── DOM 获取 ─────────────────────────────────────────────────────── */
  var root = null;       // <div id="dashboardRoot">
  var cards = [];        // [{ key, el }, ...] 当前 DOM 顺序

  function collectCards() {
    root = document.getElementById("dashboardRoot");
    if (!root) return [];
    var nodes = root.querySelectorAll("[data-card-key]");
    var out = [];
    for (var i = 0; i < nodes.length; i++) {
      var el = nodes[i];
      var k = el.getAttribute("data-card-key");
      if (CARD_KEYS.indexOf(k) >= 0) out.push({ key: k, el: el });
    }
    return out;
  }

  /* ── 布局：加载 / 应用 / 保存 ─────────────────────────────────────── */
  function defaultOrder() {
    return CARD_KEYS.slice();
  }

  function loadLayout() {
    var raw = lsGet(LS_KEY);
    if (!raw) return defaultOrder();
    try {
      var arr = JSON.parse(raw);
      if (!Array.isArray(arr)) return defaultOrder();
      // 过滤未知 key + 补齐缺失 key（防御 LS 写入被剪裁 / 升级后新增卡片）
      var known = arr.filter(function (k) { return CARD_KEYS.indexOf(k) >= 0; });
      CARD_KEYS.forEach(function (k) {
        if (known.indexOf(k) < 0) known.push(k);
      });
      // 去重
      var seen = {};
      var out = [];
      known.forEach(function (k) {
        if (!seen[k]) { seen[k] = true; out.push(k); }
      });
      return out;
    } catch (e) {
      return defaultOrder();
    }
  }

  function applyLayout(order) {
    if (!root) return;
    order.forEach(function (k) {
      var item = cards.find(function (c) { return c.key === k; });
      if (item) root.appendChild(item.el);  // appendChild 自动移动节点
    });
  }

  function saveLayout(order) {
    lsSet(LS_KEY, JSON.stringify(order));
  }

  var persistDebounced = debounce(function (order) {
    saveLayout(order);
  }, 300);

  function currentOrder() {
    return cards.map(function (c) { return c.key; });
  }

  /* ── 拖拽（原生 HTML5 DnD API） ──────────────────────────────────── */
  function setupDragDrop() {
    cards.forEach(function (item) {
      var el = item.el;
      el.setAttribute("draggable", "true");
      el.setAttribute("tabindex", "0");            // 键盘可达
      el.setAttribute("role", "region");
      // aria-label 已在 HTML 写死 h2 标题，依赖 SR 自动读 h2

      el.addEventListener("dragstart", function (e) {
        e.dataTransfer.effectAllowed = "move";
        e.dataTransfer.setData("text/plain", item.key);
        el.classList.add("is-dragging");
        el.setAttribute("aria-grabbed", "true");
      });

      el.addEventListener("dragend", function () {
        el.classList.remove("is-dragging");
        el.setAttribute("aria-grabbed", "false");
        cards.forEach(function (c) { c.el.classList.remove("drop-target"); });
      });

      el.addEventListener("dragover", function (e) {
        e.preventDefault();  // 允许 drop
        e.dataTransfer.dropEffect = "move";
      });

      el.addEventListener("dragenter", function () {
        if (!el.classList.contains("is-dragging")) {
          el.classList.add("drop-target");
        }
      });

      el.addEventListener("dragleave", function () {
        el.classList.remove("drop-target");
      });

      el.addEventListener("drop", function (e) {
        e.preventDefault();
        e.stopPropagation();
        var srcKey = e.dataTransfer.getData("text/plain");
        if (!srcKey || srcKey === item.key) return;
        // 找到 src 与 dst 在 cards 数组中的索引，重排 DOM
        var src = cards.find(function (c) { return c.key === srcKey; });
        var dst = item;
        if (!src) return;
        var srcIdx = cards.indexOf(src);
        var dstIdx = cards.indexOf(dst);
        cards.splice(srcIdx, 1);
        cards.splice(dstIdx, 0, src);
        applyLayout(currentOrder());
        var newOrder = currentOrder();
        persistDebounced(newOrder);
        track("dashboard_drag_end", {
          card_id: srcKey,
          from_idx: srcIdx,
          to_idx: dstIdx,
        });
        var pos = newOrder.indexOf(srcKey) + 1;
        announce(_t("dashboard.a11y_moved_to", "已移动到第 N 位").replace("N", pos));
      });
    });
  }

  /* ── 键盘替代（a11y · §四 不变项 #2） ─────────────────────────────── */
  var grabbedKey = null;       // 当前键盘抓取的 card-key
  var grabbedIdx = -1;

  function setupKeyboardReorder() {
    document.addEventListener("keydown", function (e) {
      // 不在 dashboard 焦点范围内时忽略
      var active = document.activeElement;
      if (!active || !active.hasAttribute || !active.hasAttribute("data-card-key")) return;
      var key = active.getAttribute("data-card-key");
      if (CARD_KEYS.indexOf(key) < 0) return;
      var idx = cards.findIndex(function (c) { return c.key === key; });
      if (idx < 0) return;

      if (e.key === " " || e.code === "Space") {
        e.preventDefault();
        if (!grabbedKey) {
          // 抓取
          grabbedKey = key;
          grabbedIdx = idx;
          active.setAttribute("aria-grabbed", "true");
          active.classList.add("is-grabbed");
          announce(_t("dashboard.a11y_grabbed", "已抓取，使用上下方向键移动，再次按空格放下"));
        } else if (grabbedKey === key) {
          // 取消抓取（再次按空格在原位 = 放下但不移动）
          releaseGrab(active);
        } else {
          // 放下到当前位置
          var src = cards.find(function (c) { return c.key === grabbedKey; });
          if (src && src.el !== active) {
            cards.splice(grabbedIdx, 1);
            cards.splice(idx, 0, src);
            applyLayout(currentOrder());
            var newOrder = currentOrder();
            persistDebounced(newOrder);
            track("dashboard_drag_end", {
              card_id: grabbedKey,
              from_idx: grabbedIdx,
              to_idx: idx,
            });
          }
          releaseGrab(active);
          active.focus();
          var pos = newOrder.indexOf(grabbedKey) + 1;
          announce(_t("dashboard.a11y_moved_to", "已移动到第 N 位").replace("N", pos));
        }
      } else if (grabbedKey === key) {
        if (e.key === "ArrowUp" && idx > 0) {
          e.preventDefault();
          swapByIdx(idx, idx - 1);
        } else if (e.key === "ArrowDown" && idx < cards.length - 1) {
          e.preventDefault();
          swapByIdx(idx, idx + 1);
        } else if (e.key === "Escape") {
          e.preventDefault();
          releaseGrab(active);
        }
      }
    });
  }

  function releaseGrab(active) {
    if (active) {
      active.setAttribute("aria-grabbed", "false");
      active.classList.remove("is-grabbed");
    }
    grabbedKey = null;
    grabbedIdx = -1;
  }

  function swapByIdx(from, to) {
    var src = cards[from];
    cards.splice(from, 1);
    cards.splice(to, 0, src);
    grabbedIdx = to;
    applyLayout(currentOrder());
    persistDebounced(currentOrder());
    var pos = to + 1;
    announce(_t("dashboard.a11y_moved_to", "已移动到第 N 位").replace("N", pos));
  }

  /* ── 恢复默认布局（带撤销 toast） ─────────────────────────────────── */
  function resetLayout() {
    var prev = currentOrder();
    var def = defaultOrder();
    if (prev.join("|") === def.join("|")) {
      announce(_t("dashboard.a11y_already_default", "已经是默认布局"));
      return;
    }
    applyLayout(def);
    saveLayout(def);
    track("dashboard_layout_reset", { prev_layout_hash: hashOrder(prev) });
    announce(_t("dashboard.a11y_reset_done", "已恢复默认布局"));

    // 撤销入口（仅当调用方提供 showUndoToast 时复用 portfolio.html 已有的撤销条）
    if (typeof window.showUndoToast === "function") {
      try {
        window.showUndoToast(
          _t("dashboard.reset_toast_msg", "已恢复默认布局"),
          function () {
            applyLayout(prev);
            saveLayout(prev);
            announce(_t("dashboard.a11y_undone", "已撤销"));
          }
        );
      } catch (e) { /* portfolio.html 未加载时忽略 */ }
    }
  }

  /* ── 初始化 ──────────────────────────────────────────────────────── */
  function init() {
    cards = collectCards();
    if (cards.length < 2) return;  // 不足 2 张不启用
    var order = loadLayout();
    applyLayout(order);

    setupDragDrop();
    setupKeyboardReorder();

    // 重置按钮（仅当存在时绑定）
    var btn = document.getElementById("btnResetLayout");
    if (btn) {
      btn.addEventListener("click", function (e) {
        e.preventDefault();
        resetLayout();
      });
    }

    // 暴露 reset 给外部（如打印 / 其他按钮）
    window.PM_Dashboard = window.PM_Dashboard || {};
    window.PM_Dashboard.resetLayout = resetLayout;
    window.PM_Dashboard.currentOrder = currentOrder;
    window.PM_Dashboard.defaultOrder = defaultOrder;
  }

  // DOM ready
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();