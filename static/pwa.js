/* V0.72.0 P3-b：PWA install banner + Service Worker 注册 + Web Push 订阅
 * ─────────────────────────────────────────────────────────────
 * V0.98 C3 更新：
 *   - 内联 style → pwa.css 外部样式（更易维护 / cache 不破规则）
 *   - 加 appinstalled 监听 → PM_Toast.success 庆祝
 *   - dismiss 改 TTL：pm_pwa_install_dismissed_until（7 天）
 *   - install / iOS 文案走 i18n（pwa.install_* 三个 key）
 * 模式：IIFE + window.PM_PWA 命名空间
 * 依赖：telemetry.js（埋点）/ help.js（HELP 引用）/ PM_Toast（可选）/ PM_I18N（可选）
 *
 * 不依赖 jQuery / 任何打包工具（项目无构建步骤）。
 */

(function () {
    "use strict";

    if (!("serviceWorker" in navigator)) return;

    const VERSION = "v0.73.0";
    const LS_SEEN = "pm_pwa_seen_version";
    const LS_DISMISSED_UNTIL = "pm_pwa_install_dismissed_until";
    const LS_INSTALLED = "pm_pwa_installed";
    const DISMISS_TTL_MS = 7 * 24 * 60 * 60 * 1000; // 7 天

    function t_(key, fallback) {
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

    function isDismissed() {
        try {
            const until = localStorage.getItem(LS_DISMISSED_UNTIL);
            if (!until) return false;
            const ts = Date.parse(until);
            if (Number.isNaN(ts)) return false;
            return Date.now() < ts;
        } catch (_) {
            return false;
        }
    }

    function markDismissed() {
        try {
            const until = new Date(Date.now() + DISMISS_TTL_MS).toISOString();
            localStorage.setItem(LS_DISMISSED_UNTIL, until);
        } catch (_) { /* 隐私模式 */ }
    }

    // ── 1. SW 注册 ────────────────────────────────────────
    navigator.serviceWorker
        .register("/sw.js", { scope: "/" })
        .catch((err) => console.warn("SW register failed:", err));

    // ── 2. VAPID 公钥 → 订阅 push ─────────────────────────
    function urlBase64ToUint8Array(base64String) {
        const padding = "=".repeat((4 - (base64String.length % 4)) % 4);
        const base64 = (base64String + padding).replace(/-/g, "+").replace(/_/g, "/");
        const rawData = atob(base64);
        const output = new Uint8Array(rawData.length);
        for (let i = 0; i < rawData.length; ++i) {
            output[i] = rawData.charCodeAt(i);
        }
        return output;
    }

    async function ensurePushSubscribed() {
        if (!("PushManager" in window)) {
            return { ok: false, reason: "browser-no-push" };
        }
        const perm = await Notification.requestPermission();
        if (perm !== "granted") {
            return { ok: false, reason: "permission-denied" };
        }
        const reg = await navigator.serviceWorker.ready;
        let sub = await reg.pushManager.getSubscription();
        if (!sub) {
            try {
                const r = await fetch("/api/v1/push/vapid-public-key");
                if (!r.ok) return { ok: false, reason: "vapid-fetch-failed" };
                const { key } = await r.json();
                sub = await reg.pushManager.subscribe({
                    userVisibleOnly: true,
                    applicationServerKey: urlBase64ToUint8Array(key),
                });
            } catch (err) {
                console.warn("Push subscribe failed:", err);
                return { ok: false, reason: "subscribe-failed" };
            }
        }
        // 同步订阅到后端
        try {
            await fetch("/api/v1/push/subscribe", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(sub.toJSON()),
            });
        } catch (err) {
            console.warn("Push backend sync failed:", err);
        }
        if (window.telemetry?.track) {
            window.telemetry.track("push_channel_click", { channel: "webpush" });
        }
        return { ok: true };
    }

    // ── 3. install banner（Chrome / Edge） ─────────────────
    let deferredPrompt = null;
    window.addEventListener("beforeinstallprompt", (e) => {
        e.preventDefault();
        deferredPrompt = e;
        if (localStorage.getItem(LS_SEEN) === VERSION) return;
        if (isDismissed()) return;
        showInstallBanner();
    });

    function showInstallBanner() {
        // 避免重复渲染
        if (document.getElementById("pmPwaBanner")) return;

        const banner = document.createElement("div");
        banner.id = "pmPwaBanner";
        banner.className = "pm-install-banner";
        banner.setAttribute("role", "dialog");
        banner.setAttribute("aria-live", "polite");

        const textWrap = document.createElement("div");
        textWrap.className = "pm-install-banner-text";
        const title = document.createElement("div");
        title.className = "pm-install-banner-title";
        title.textContent = "📱 " + t_("pwa.install_title", "添加到主屏");
        const desc = document.createElement("div");
        desc.className = "pm-install-banner-desc";
        desc.textContent = t_("pwa.install_desc", "离线浏览 · 主屏启动 · 实时通知");
        textWrap.appendChild(title);
        textWrap.appendChild(desc);

        const installBtn = document.createElement("button");
        installBtn.id = "pmPwaInstall";
        installBtn.type = "button";
        installBtn.className = "pm-install-banner-btn";
        installBtn.textContent = t_("pwa.install_btn", "安装");

        const dismissBtn = document.createElement("button");
        dismissBtn.id = "pmPwaDismiss";
        dismissBtn.type = "button";
        dismissBtn.className = "pm-install-banner-dismiss";
        dismissBtn.setAttribute("aria-label", "close");
        dismissBtn.textContent = "×";

        banner.appendChild(textWrap);
        banner.appendChild(installBtn);
        banner.appendChild(dismissBtn);
        document.body.appendChild(banner);

        installBtn.onclick = async () => {
            if (!deferredPrompt) return;
            deferredPrompt.prompt();
            const { outcome } = await deferredPrompt.userChoice;
            if (outcome === "accepted" && window.telemetry?.track) {
                window.telemetry.track("pwa_installed", {});
            }
            banner.remove();
            localStorage.setItem(LS_SEEN, VERSION);
        };

        dismissBtn.onclick = () => {
            banner.remove();
            markDismissed();
            localStorage.setItem(LS_SEEN, VERSION);
        };

        if (window.telemetry?.track) {
            window.telemetry.track("pwa_install_prompted", {});
        }
    }

    // ── 4. iOS Safari 永久指引卡 ────────────────────────
    function showIOSInstallHint() {
        if (document.getElementById("pmIosHint")) return;
        const isStandalone = window.matchMedia("(display-mode: standalone)").matches;
        if (isStandalone) return;

        const card = document.createElement("div");
        card.id = "pmIosHint";
        card.className = "pm-ios-hint";
        card.setAttribute("role", "dialog");
        card.setAttribute("aria-live", "polite");

        const title = document.createElement("div");
        title.className = "pm-ios-hint-title";
        title.textContent = "📱 " + t_("pwa.install_title", "添加到主屏");

        const body = document.createElement("div");
        body.className = "pm-ios-hint-body";
        // iOS hint 文本与 banner desc 共用，文案窄就 i18n 友好。
        body.textContent = t_("pwa.install_desc", "离线浏览 · 主屏启动 · 实时通知");

        const dismissBtn = document.createElement("button");
        dismissBtn.id = "pmIosDismiss";
        dismissBtn.type = "button";
        dismissBtn.className = "pm-ios-hint-dismiss";
        dismissBtn.setAttribute("aria-label", "close");
        dismissBtn.textContent = "×";

        card.appendChild(title);
        card.appendChild(body);
        card.appendChild(dismissBtn);
        document.body.appendChild(card);
        dismissBtn.onclick = () => card.remove();
    }

    // ── 5. appinstalled 监听 → toast 庆祝 ─────────────────
    window.addEventListener("appinstalled", () => {
        try { localStorage.setItem(LS_INSTALLED, "1"); } catch (_) { /* 隐私模式 */ }
        if (window.PM_Toast && typeof window.PM_Toast.success === "function") {
            try {
                window.PM_Toast.success(
                    t_("pwa.installed_toast", "已添加到主屏，享受原生体验"),
                    { duration: 6000, i18n: "pwa.installed_toast" }
                );
            } catch (_) { /* 静默 */ }
        }
    });

    const isIOS = /iPad|iPhone|iPod/.test(navigator.userAgent) && !window.MSStream;
    const isStandalone = window.matchMedia("(display-mode: standalone)").matches;
    if (isIOS && !isStandalone) {
        if (document.readyState === "loading") {
            document.addEventListener("DOMContentLoaded", showIOSInstallHint);
        } else {
            showIOSInstallHint();
        }
    }

    // ── 6. 暴露 API ──────────────────────────────────────
    window.PM_PWA = { ensurePushSubscribed, VERSION };
})();
