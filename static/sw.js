/* V0.73.0 P3-c：Service Worker（PWA + 离线 + 后台推送 + i18n precache）
 * ─────────────────────────────────────────────────────────
 * 缓存策略：
 *   - HTML 页面：network-first（回退到 cache → offline.html）
 *   - 静态资产（/static/）：cache-first（7d 不可变）
 *   - API GET（news-score / review/meta）：stale-while-revalidate
 *   - 写 API：不拦截，pass-through
 *   - push：showNotification + tag
 *   - notificationclick：focus 已有窗口或 openWindow
 *
 * 注意：sw.js 必须在 / 根 scope（不是 /static/），由 main.py 的 /sw.js 路由
 * + Service-Worker-Allowed: / 头实现。
 */

const VERSION = "v0.73.0";
const SHELL_CACHE = `gold-shell-${VERSION}`;
const RUNTIME_CACHE = `gold-runtime-${VERSION}`;
const OFFLINE_URL = "/static/offline.html";

const SHELL_ASSETS = [
    "/",
    "/portfolio",
    "/review",
    "/news",
    "/central_bank",
    "/trades",
    "/backtest",
    "/silver",
    OFFLINE_URL,
    "/static/manifest.json",
    "/static/icon-192.png",
    "/static/icon-512.png",
    "/static/theme.css",
    "/static/help.css",
    "/static/responsive.css",
    "/static/theme.js",
    "/static/help.js",
    "/static/telemetry.js",
    "/static/nav-drawer.js",
    // V0.73.0 i18n：默认 locale 同步加载，必须 precache 离线可用
    "/static/i18n.js",
    "/static/i18n/zh-CN.js",
];

// ─── install：precache shell + skipWaiting ─────────────────────
self.addEventListener("install", (event) => {
    event.waitUntil(
        caches.open(SHELL_CACHE).then((cache) =>
            cache.addAll(SHELL_ASSETS).catch((err) => {
                // 部分资源失败不阻塞 SW 激活（开发期可接受）
                console.warn("SW install: cache.addAll partial failure", err);
            }),
        ),
    );
    self.skipWaiting();
});

// ─── activate：清理旧版本 cache + clients.claim ───────────────
self.addEventListener("activate", (event) => {
    event.waitUntil(
        caches
            .keys()
            .then((keys) =>
                Promise.all(
                    keys
                        .filter((k) => k !== SHELL_CACHE && k !== RUNTIME_CACHE)
                        .map((k) => caches.delete(k)),
                ),
            )
            .then(() => self.clients.claim()),
    );
});

// ─── fetch：路由分发 ──────────────────────────────────────
self.addEventListener("fetch", (event) => {
    const request = event.request;
    if (request.method !== "GET") return;

    const url = new URL(request.url);
    if (url.origin !== self.location.origin) return;

    // HTML 页面：network-first
    if (request.mode === "navigate" || request.headers.get("accept")?.includes("text/html")) {
        event.respondWith(
            fetch(request)
                .then((response) => {
                    const copy = response.clone();
                    caches.open(RUNTIME_CACHE).then((c) => c.put(request, copy));
                    return response;
                })
                .catch(() =>
                    caches.match(request).then((cached) => cached || caches.match(OFFLINE_URL)),
                ),
        );
        return;
    }

    // 静态资产：cache-first
    if (url.pathname.startsWith("/static/")) {
        event.respondWith(
            caches.match(request).then(
                (cached) =>
                    cached ||
                    fetch(request).then((response) => {
                        const copy = response.clone();
                        caches.open(RUNTIME_CACHE).then((c) => c.put(request, copy));
                        return response;
                    }),
            ),
        );
        return;
    }

    // API GET（只读端点）：stale-while-revalidate
    if (url.pathname.startsWith("/api/") && request.method === "GET") {
        event.respondWith(
            caches.match(request).then((cached) => {
                const fetchPromise = fetch(request)
                    .then((response) => {
                        const copy = response.clone();
                        caches.open(RUNTIME_CACHE).then((c) => c.put(request, copy));
                        return response;
                    })
                    .catch(() => cached);
                return cached || fetchPromise;
            }),
        );
    }
});

// ─── push：后台通知 ──────────────────────────────────────
self.addEventListener("push", (event) => {
    let data = { title: "黄金 ETF 提醒", body: "指数档位变化", tag: "gold-alert" };
    if (event.data) {
        try {
            data = { ...data, ...event.data.json() };
        } catch {
            data.body = event.data.text();
        }
    }
    event.waitUntil(
        self.registration.showNotification(data.title, {
            body: data.body,
            icon: "/static/icon-192.png",
            badge: "/static/icon-192.png",
            tag: data.tag,
            data: { url: data.url || "/portfolio" },
            requireInteraction: false,
            silent: false,
        }),
    );
});

// ─── notificationclick：focus 已有窗口或 openWindow ─────────
self.addEventListener("notificationclick", (event) => {
    event.notification.close();
    const targetUrl = event.notification.data?.url || "/portfolio";
    event.waitUntil(
        self.clients
            .matchAll({ type: "window", includeUncontrolled: true })
            .then((windowClients) => {
                for (const client of windowClients) {
                    if (client.url.includes(targetUrl)) {
                        return client.focus();
                    }
                }
                return self.clients.openWindow(targetUrl);
            }),
    );
});
