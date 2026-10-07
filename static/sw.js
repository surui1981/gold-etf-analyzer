/* V0.73.0 P3-c：Service Worker（PWA + 离线 + 后台推送 + i18n precache）
 * ─────────────────────────────────────────────────────────
 * 缓存策略：
 *   - HTML 页面：network-first（回退到 cache → offline.html）
 *   - 静态资产（/static/）：cache-first（随 VERSION 换代清理）
 *   - API GET：network-first（V0.77.1 A4 起；网络失败时才按护栏回退缓存，
 *              价格类端点永不回退，详见 PRICE_API_RE 处注释）
 *   - 写 API：不拦截，pass-through
 *   - push：showNotification + tag
 *   - notificationclick：focus 已有窗口或 openWindow
 *
 * 注意：sw.js 必须在 / 根 scope（不是 /static/），由 main.py 的 /sw.js 路由
 * + Service-Worker-Allowed: / 头实现。
 */

const VERSION = "v0.80.1";
const SHELL_CACHE = `gold-shell-${VERSION}`;
const RUNTIME_CACHE = `gold-runtime-${VERSION}`;
const OFFLINE_URL = "/static/offline.html";

/* V0.77.1 A4：只读 API 的新鲜度护栏。
 * 原策略是「一律 stale-while-revalidate」—— 先返回缓存、后台再更新缓存。
 * 问题有三层：① 缓存没有 TTL，命中的可能是【上次会话】的响应，且「在线」也会命中；
 * ② review / news / weights / backtest 这几页只拉一次数据、不自我校正，于是客户看到的
 *    可能是数天前的行情；③ 上游的 4xx/5xx 也会被写进缓存，之后被当成正常响应反复回放。
 * 现改为 network-first，并给「网络失败时的缓存回退」加两道闸：
 *   ① 价格类端点（/market/gold*、/market/silver*）一律不回退 —— 过期价格会直接误导
 *      买卖判断，宁可让页面明示「取数失败」，也不拿旧价冒充现价；
 *   ② 其余端点回退的缓存必须足够新（MAX_API_STALE_MS 内），超期即视为不可用并清除。
 * 回退时会注入 X-SW-Cached-At（真实缓存时点）供页面披露「此数据来自离线缓存」。
 */
const PRICE_API_RE = /^\/api\/v1\/market\/(gold|silver)\b/;
const MAX_API_STALE_MS = 30 * 60 * 1000;
const STORED_AT_HEADER = "X-SW-Stored-At";

// ⚠ 每条 URL 都必须是服务端真实存在的路径。cache.addAll() 是【原子操作】：任一请求失败
//   整批回滚 → 整个 SHELL_CACHE 为空，离线能力归零且无任何用户可见提示。
//   历史上 /central_bank、/backtest、/silver 三条均为 404（服务端只注册了 /central-bank，
//   白银与回测页走 /static/*.html），导致 precache 从未成功过一次。
//
// ⚠⚠ 下面 6 条（`/` 与 5 个 RESTful 路由）**看着也是「绕了一道」，但必须保留原样** ——
//   它们响应 307 → /static/*.html，很容易被当成冗余项「优化」成直连地址。改了就坏：
//   本文件「HTML 页面」分支是 network-first，离线兜底为 `caches.match(request)`，
//   而 `request.url` 就是**用户地址栏里的 /portfolio** —— 缓存 key 必须与之一致
//   才可能命中。若改写成 /static/portfolio.html，离线访问 /portfolio 会查不到缓存，
//   直接落到 offline.html（用户看到「离线」，而非他要的页面）。
//   `cache.addAll()` 会跟随 307，并以**原始 URL** 为 key 缓存最终响应体，这是有意为之。
//   回归锁：tests/test_scripts_check_pwa_assets.py::test_restful_nav_entries_are_precached
const SHELL_ASSETS = [
    "/",
    "/portfolio",
    "/review",
    "/news",
    "/central-bank",
    "/trades",
    "/static/backtest.html",
    "/static/silver.html",
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
    // V0.74.3 依赖本地化：Chart.js 由 CDN 改为随应用分发（离线 / 无外网环境可用）
    "/static/vendor/chart.umd.min.js",
    // V0.73.0 i18n：默认 locale 同步加载，必须 precache 离线可用
    "/static/i18n.js",
    "/static/i18n/zh-CN.js",
    // V0.75.0 认证骨架：登录页与认证客户端须离线可打开
    // （否则离线时任意页面都跳登录页 → 落进 offline.html，无法解释原因）
    "/static/login.html",
    // V0.75.3：找回密码落地页。照抄 login.html 的既有做法：
    // 直链形式登记 + `main.py` 里另配一个无 .html 的 RESTful 别名（/reset-password）。
    // ⚠ **两个都要有**：RESTful 别名供邮件里的链接与地址栏使用（好读、可收藏），
    // 直链条目供 `cache.addAll()` 预缓存。⚠ 别名不是可选的 ——
    // 邮件链接若指向未注册的路径会得到 404，离线场景下「找回密码」直接不可用。
    "/static/reset-password.html",
    // ⚠ 下面这两条**顺序有意义**：用户管理页依赖 auth.js 的登录态，
    // 离线打开会显示「无权访问」而非崩溃（页面自身做了 role 检查）。
    "/static/auth.js",
    "/static/admin/users.html",
    // V0.75.1 综合研判结论卡：宿在首页顶部，离线打开时必须能渲染
    "/static/synthesis-card.js",
    // V0.76.0 首页内嵌消息面打分器：宿在首页顶部，离线打开时必须能渲染
    "/static/news-score-widget.js",
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

// ─── 只读 API 的缓存写入 / 回退（V0.77.1 A4）──────────────────
/** 写入缓存：只缓存成功响应（避免把 4xx/5xx 回放成「正常」），并打上存入时刻。
 *  存入时刻由 SW 自己记，不依赖上游可能被中间层剥掉的 Date 头。 */
function cacheApiResponse(request, response) {
    if (!response.ok) return;
    const copy = response.clone();
    caches.open(RUNTIME_CACHE).then(async (c) => {
        try {
            const buf = await copy.arrayBuffer();
            const headers = new Headers(copy.headers);
            headers.set(STORED_AT_HEADER, new Date().toISOString());
            await c.put(request, new Response(buf, {
                status: copy.status,
                statusText: copy.statusText,
                headers,
            }));
        } catch (err) {
            console.warn("SW: cache api response failed", err);
        }
    });
}

/** 网络不可用时的缓存回退。不满足护栏条件即抛错 —— 让页面走「取数失败」错误态，
 *  而不是静默拿到一个旧值。抛错比回放旧数据更安全。 */
async function serveStaleApi(request) {
    const pathname = new URL(request.url).pathname;
    if (PRICE_API_RE.test(pathname)) {
        throw new Error("SW: price endpoints are never served from cache");
    }
    const cached = await caches.match(request);
    if (!cached) throw new Error("SW: no cached response");
    const storedAt = Date.parse(cached.headers.get(STORED_AT_HEADER) || cached.headers.get("date") || "");
    const ageMs = Number.isNaN(storedAt) ? Infinity : Date.now() - storedAt;
    if (ageMs > MAX_API_STALE_MS) {
        // 超期缓存直接清除：留着只会在下次离线时再被顶上
        const cache = await caches.open(RUNTIME_CACHE);
        await cache.delete(request);
        throw new Error("SW: cached response is too old");
    }
    const headers = new Headers(cached.headers);
    headers.set("X-SW-Cached-At", new Date(storedAt).toISOString());
    const body = await cached.blob();
    return new Response(body, { status: cached.status, statusText: cached.statusText, headers });
}

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

    // API GET（只读端点）：network-first（V0.77.1 A4 起，原先为 stale-while-revalidate）
    // 在线必新；仅网络失败时按 serveStaleApi 的护栏回退缓存，护栏不过就抛错让页面报错。
    if (url.pathname.startsWith("/api/") && request.method === "GET") {
        event.respondWith(
            fetch(request)
                .then((response) => {
                    cacheApiResponse(request, response);
                    return response;
                })
                .catch(() => serveStaleApi(request)),
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
