/* V0.98 C3：断网检测 + 主动探活 + 顶 banner
 * ─────────────────────────────────────────────────────
 * 模式：IIFE；挂 window.PM_NetStatus 命名空间
 * 依赖：window.PM_Toast（必须先加载 toast.js）+ toast.css
 *
 * 设计要点：
 *  - 监听 window 'online' / 'offline' 事件
 *  - 每 30s 主动探活 /api/v1/health（仅在 navigator.onLine === true 时）
 *  - 失败 3 次连续 → 视为离线 → 顶部 banner + PM_Toast.err（duration:0 不自动消失）
 *  - 恢复 → banner 自动隐藏 + PM_Toast.success
 *  - 探活 / online 事件触发恢复时，主动关闭任何在飞的网络异常 toast
 *  - 防御性：PM_Toast 不存在时降级到只显示 banner，不抛错
 *  - 不阻挡输入（pointer-events: none，仅占位）
 */
(function () {
  "use strict";

  const PROBE_INTERVAL_MS = 30 * 1000;
  const PROBE_FAIL_THRESHOLD = 3;
  const PROBE_TIMEOUT_MS = 8 * 1000;
  const HEALTH_URL = "/api/v1/health";

  let failStreak = 0;
  let probeTimer = null;
  let bannerEl = null;
  let bannerText = null;
  let activeNetErrToastId = null;

  function ensureBanner() {
    if (bannerEl) return bannerEl;
    bannerEl = document.createElement("div");
    bannerEl.id = "pm-net-banner";
    bannerEl.className = "pm-net-banner";
    bannerEl.hidden = true;
    bannerEl.setAttribute("role", "status");
    bannerEl.setAttribute("aria-live", "polite");
    bannerText = document.createElement("span");
    bannerText.id = "pm-net-banner-text";
    bannerEl.appendChild(bannerText);
    // 用 attach 而不是 appendChild：banner 自身有 safe-area 顶部贴边样式
    if (document.body) {
      document.body.appendChild(bannerEl);
    } else {
      document.addEventListener("DOMContentLoaded", function () {
        if (!bannerEl.parentNode) document.body.appendChild(bannerEl);
      }, { once: true });
    }
    return bannerEl;
  }

  function setBannerText(s) {
    if (!bannerEl) return;
    if (!bannerText) ensureBanner();
    if (bannerText) bannerText.textContent = s;
  }

  function t(key, fallback) {
    if (key && typeof window.PM_I18N !== "undefined"
        && window.PM_I18N
        && typeof window.PM_I18N.t === "function") {
      try {
        const v = window.PM_I18N.t(key);
        if (v && v !== key) return v;
      } catch (_) { /* 静默 */ }
    }
    return fallback;
  }

  function toastApi() {
    return (typeof window.PM_Toast !== "undefined" && window.PM_Toast) || null;
  }

  function showBanner() {
    const el = ensureBanner();
    setBannerText(t("net.banner_text", "📡 网络异常，部分功能暂不可用"));
    el.hidden = false;
  }

  function hideBanner() {
    if (bannerEl) bannerEl.hidden = true;
  }

  function markOffline(reason) {
    if (bannerEl && bannerEl.hidden === false) return; // 已在显示
    showBanner();
    const api = toastApi();
    if (!api) return;
    // 关闭任何已存在的 network 异常 toast，避免叠加
    if (activeNetErrToastId) {
      try { api.dismiss(activeNetErrToastId); } catch (_) {}
      activeNetErrToastId = null;
    }
    const msg = t("toast.net_lost", "网络异常，请检查连接");
    try {
      activeNetErrToastId = api.err(msg, { duration: 0, i18n: "toast.net_lost" });
    } catch (_) { /* 静默 */ }
  }

  function markOnline() {
    hideBanner();
    // 关闭任何 in-flight network 异常 toast
    const api = toastApi();
    if (activeNetErrToastId && api) {
      try { api.dismiss(activeNetErrToastId); } catch (_) {}
      activeNetErrToastId = null;
    }
    if (!api) return;
    const msg = t("toast.net_restored", "网络已恢复");
    try {
      api.success(msg, { duration: 4000, i18n: "toast.net_restored" });
    } catch (_) { /* 静默 */ }
  }

  async function probeOnce() {
    // 仅在 navigator.onLine === true 时探活；浏览器原生 offline 事件更可靠
    if (typeof navigator !== "undefined" && navigator.onLine === false) {
      failStreak = PROBE_FAIL_THRESHOLD; // 强制进入离线态
      markOffline("navigator-offline");
      return;
    }
    if (typeof fetch !== "function") return;
    const ctl = (typeof AbortController !== "undefined") ? new AbortController() : null;
    const timer = ctl ? setTimeout(function () { try { ctl.abort(); } catch (_) {} }, PROBE_TIMEOUT_MS) : null;
    try {
      const res = await fetch(HEALTH_URL, { cache: "no-store", signal: ctl ? ctl.signal : undefined });
      if (res && res.ok) {
        failStreak = 0;
        // 只在 banner 当前显示时切到 online（避免每次成功都重复 toast）
        if (bannerEl && bannerEl.hidden === false) {
          markOnline();
        }
      } else {
        failStreak += 1;
        if (failStreak >= PROBE_FAIL_THRESHOLD) markOffline("probe-fail-" + res.status);
      }
    } catch (_) {
      failStreak += 1;
      if (failStreak >= PROBE_FAIL_THRESHOLD) markOffline("probe-throw");
    } finally {
      if (timer) clearTimeout(timer);
    }
  }

  function startProbing() {
    if (probeTimer) return;
    probeTimer = setInterval(probeOnce, PROBE_INTERVAL_MS);
  }

  function stopProbing() {
    if (probeTimer) {
      clearInterval(probeTimer);
      probeTimer = null;
    }
  }

  function init() {
    // window 事件
    window.addEventListener("online", function () {
      // 主动探一次，确认后端可达再宣告恢复
      probeOnce();
    });
    window.addEventListener("offline", function () {
      failStreak = PROBE_FAIL_THRESHOLD;
      markOffline("browser-offline-event");
    });

    // 首次进入：如果浏览器一上来就 offline，立刻显示 banner（不弹 toast，等用户确认）
    if (typeof navigator !== "undefined" && navigator.onLine === false) {
      failStreak = PROBE_FAIL_THRESHOLD;
      showBanner();
      // 主动探一次：探测失败时才升级到 toast
      probeOnce();
    }

    startProbing();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init, { once: true });
  } else {
    init();
  }

  window.PM_NetStatus = {
    probe: probeOnce,
    markOnline: markOnline,
    markOffline: markOffline,
    isOffline: function () {
      return !!(bannerEl && bannerEl.hidden === false);
    },
  };
})();