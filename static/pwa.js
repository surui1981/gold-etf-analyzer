/* V0.72.0 P3-b：PWA install banner + Service Worker 注册 + Web Push 订阅
 * ─────────────────────────────────────────────────────────────
 * 模式：IIFE + window.PM_PWA 命名空间
 * 依赖：telemetry.js（埋点）/ help.js（HELP 引用）
 *
 * 不依赖 jQuery / 任何打包工具（项目无构建步骤）。
 */

(function () {
    "use strict";

    if (!("serviceWorker" in navigator)) return;

    const VERSION = "v0.73.0";
    const LS_SEEN = "pm_pwa_seen_version";
    const LS_DISMISSED = "pm_pwa_install_dismissed";

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
        if (localStorage.getItem(LS_DISMISSED) === "1") return;
        showInstallBanner();
    });

    function showInstallBanner() {
        // 避免重复渲染
        if (document.getElementById("pmPwaBanner")) return;

        const banner = document.createElement("div");
        banner.id = "pmPwaBanner";
        banner.style.cssText =
            "position:fixed;bottom:24px;left:24px;right:24px;max-width:480px;margin:0 auto;" +
            "background:#1f2329;color:#e5e7eb;padding:14px 18px;border-radius:10px;" +
            "box-shadow:0 6px 20px rgba(0,0,0,0.5);z-index:9999;display:flex;align-items:center;gap:12px;" +
            "font:14px/1.4 -apple-system,BlinkMacSystemFont,'PingFang SC',sans-serif;";
        banner.innerHTML = `
            <div style="flex:1">
                <div style="font-weight:600;color:#d4a857">📱 安装到桌面</div>
                <div style="font-size:12px;color:#9ca3af;margin-top:2px">离线也能用，自动接收档位告警</div>
            </div>
            <button id="pmPwaInstall" style="background:#d4a857;color:#1f2329;border:0;padding:8px 14px;border-radius:6px;cursor:pointer;font-weight:600;font-size:13px">安装</button>
            <button id="pmPwaDismiss" style="background:transparent;color:#9ca3af;border:0;font-size:20px;cursor:pointer;padding:0 4px">×</button>
        `;
        document.body.appendChild(banner);

        document.getElementById("pmPwaInstall").onclick = async () => {
            if (!deferredPrompt) return;
            deferredPrompt.prompt();
            const { outcome } = await deferredPrompt.userChoice;
            if (outcome === "accepted" && window.telemetry?.track) {
                window.telemetry.track("pwa_installed", {});
            }
            banner.remove();
            localStorage.setItem(LS_SEEN, VERSION);
        };

        document.getElementById("pmPwaDismiss").onclick = () => {
            banner.remove();
            localStorage.setItem(LS_DISMISSED, "1");
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
        card.style.cssText =
            "position:fixed;bottom:24px;left:24px;right:24px;max-width:480px;margin:0 auto;" +
            "background:#1f2329;color:#e5e7eb;padding:14px 18px;border-radius:10px;" +
            "box-shadow:0 6px 20px rgba(0,0,0,0.5);z-index:9999;" +
            "font:14px/1.5 -apple-system,BlinkMacSystemFont,'PingFang SC',sans-serif;";
        card.innerHTML = `
            <div style="font-weight:600;color:#d4a857;margin-bottom:6px">📱 iOS 用户</div>
            <div style="font-size:13px;color:#9ca3af">
                点击底部分享按钮 <strong style="color:#e5e7eb">⬆️</strong> → <em style="color:#e5e7eb">添加到主屏</em>，安装后可接收档位告警
            </div>
            <button id="pmIosDismiss" style="position:absolute;top:8px;right:8px;background:transparent;color:#9ca3af;border:0;font-size:18px;cursor:pointer">×</button>
        `;
        document.body.appendChild(card);
        document.getElementById("pmIosDismiss").onclick = () => card.remove();
    }

    const isIOS = /iPad|iPhone|iPod/.test(navigator.userAgent) && !window.MSStream;
    const isStandalone = window.matchMedia("(display-mode: standalone)").matches;
    if (isIOS && !isStandalone) {
        if (document.readyState === "loading") {
            document.addEventListener("DOMContentLoaded", showIOSInstallHint);
        } else {
            showIOSInstallHint();
        }
    }

    // ── 5. 暴露 API ──────────────────────────────────────
    window.PM_PWA = { ensurePushSubscribed, VERSION };
})();
