/*!
 * auth.js —— 认证客户端（V0.75.0 认证骨架）
 *
 * 用法：页面 <body> 末尾
 *   <script src="/static/auth.js" defer></script>
 *
 * 提供（window.PM_AUTH）：
 *   PM_AUTH.api(path, init)     // fetch 包装：自动带 X-CSRF-Token + 401 跳登录
 *   PM_AUTH.loadStatus()        // 重新拉取 /auth/status
 *   PM_AUTH.status              // 最近一次状态快照
 *   PM_AUTH.logout()            // 登出并跳登录页
 *   PM_AUTH.csrfToken()         // 读 pm_csrf cookie
 *   PM_AUTH.t(key, fallback)    // 取 i18n 文案（I18n 未就绪时用 fallback）
 *
 * 设计要点
 * --------
 * 1. **全局 fetch 打补丁**：写请求自动附加 `X-CSRF-Token` 头。
 *    这样既有 11 个页面里几十处 `fetch(..., {method:'POST'})` **完全不用改**，
 *    新增写端点也不会漏掉 CSRF 头 —— 比逐个改调用点更不易腐坏。
 * 2. **V0.80.1 同步补丁 X-Admin-Token**：prod 部署下所有写端点都有
 *    ``Depends(require_admin)``，需要 ``X-Admin-Token`` 头。从 localStorage
 *    读 ``pm_admin_token``（与 settings.js 共用 key），自动附加。
 *    ⇒ news.html / portfolio.html / weights.html 等几十处裸 fetch
 *    **完全不用改**就能在 prod 下工作。
 * 2.5 **V0.81.1 admin token 缺失提示横幅**：401 + ``detail="admin token required"``
 *    时弹顶部横幅引导用户去设置页（避免 LAN 跨 origin 用户踩同一坑）。
 *    每个 session 只弹一次（sessionStorage 标记）。
 * 3. **AUTH_ENABLED=false 时零副作用**：不注入任何 UI、不做跳转、
 *    不修改 fetch 行为（仍打补丁，但读不到 csrf cookie 时不加头），
 *    保证单用户模式与 V0.74.3 观感完全一致。
 * 4. **401 全局兜底**：会话过期后任意请求返回 401 → 跳登录页并带 `?next=`，
 *    用户登录后回到原来那一页，不用重新点导航。
 * 5. 纯原生 IIFE + `window.PM_AUTH` 命名空间（与 PM_Help / PM_PWA 一致）。
 */
(function () {
  "use strict";

  var STATUS_URL = "/api/v1/auth/status";
  var LOGIN_URL = "/api/v1/auth/login";
  var REGISTER_URL = "/api/v1/auth/register";
  var LOGOUT_URL = "/api/v1/auth/logout";
  var CHANGE_PWD_URL = "/api/v1/auth/change-password";
  var LOGIN_PAGE = "/static/login.html";
  var CSRF_COOKIE = "pm_csrf";
  var CSRF_HEADER = "X-CSRF-Token";
  var ADMIN_TOKEN_KEY = "pm_admin_token";  // V0.80.1：与 settings.js 共用 localStorage key
  var ADMIN_TOKEN_HEADER = "X-Admin-Token";
  var WRITE_METHODS = { POST: 1, PUT: 1, PATCH: 1, DELETE: 1 };
  // V0.81.1：admin token 缺失横幅 —— sessionStorage 标记防止重复弹
  var ADMIN_TOKEN_HINT_FLAG = "pm_admin_token_hint_shown";

  var state = {
    loaded: false,
    authEnabled: false,
    authenticated: false,
    user: null,
    userCount: 0,
    allowRegistration: true
  };

  /* ─────────────── 工具 ─────────────── */

  function t(key, fallback) {
    try {
      if (window.I18n && typeof window.I18n.t === "function") {
        var s = window.I18n.t(key);
        if (s && s !== key) return s;
      }
    } catch (e) { /* ignore */ }
    return fallback != null ? fallback : key;
  }

  function csrfToken() {
    var m = document.cookie.match(new RegExp("(?:^|; )" + CSRF_COOKIE + "=([^;]*)"));
    return m ? decodeURIComponent(m[1]) : "";
  }

  // V0.80.1：从 localStorage 读 admin token（与 settings.js 共用 LS_ADMIN key）
  // 不在 settings.js 里调用是因为 auth.js 必须独立可加载（auth.js 是全站基座，
  // settings.js 仅 settings 页加载），不能有反向依赖。
  function adminToken() {
    try {
      var v = localStorage.getItem(ADMIN_TOKEN_KEY);
      return v && String(v).trim() ? String(v).trim() : "";
    } catch (e) {
      return "";  // Safari 隐私模式 / cookie 禁用 → 视为未设
    }
  }

  /* ─────────────── admin token 缺失提示横幅（V0.81.1） ─────────────── */

  var ADMIN_HINT_CSS = [
    ".pm-admin-hint { position: fixed; top: 0; left: 0; right: 0; z-index: 9999;",
    "  display: flex; align-items: center; gap: 12px; padding: 12px 18px;",
    "  background: linear-gradient(90deg, #fff7e0 0%, #ffe9b8 100%);",
    "  color: #5b4500; border-bottom: 2px solid #f0b429;",
    "  box-shadow: 0 4px 16px rgba(0,0,0,.12);",
    "  font-family: inherit; font-size: 13.5px; line-height: 1.4;",
    "  animation: pmAdminHintSlide .35s ease-out; }",
    "@keyframes pmAdminHintSlide { from { transform: translateY(-100%); } to { transform: translateY(0); } }",
    ".pm-admin-hint-icon { font-size: 18px; flex-shrink: 0; }",
    ".pm-admin-hint-msg { flex: 1; min-width: 0; }",
    ".pm-admin-hint-btn { display: inline-block; padding: 6px 14px; border-radius: 6px;",
    "  background: #f0b429; color: #1f1d18; font-weight: 600; text-decoration: none;",
    "  border: 1px solid #d49a1c; cursor: pointer; flex-shrink: 0; font-size: 13px; }",
    ".pm-admin-hint-btn:hover { background: #e0a616; }",
    ".pm-admin-hint-close { background: transparent; border: 0; color: #5b4500;",
    "  font-size: 20px; line-height: 1; cursor: pointer; padding: 0 4px; flex-shrink: 0;",
    "  opacity: .6; }",
    ".pm-admin-hint-close:hover { opacity: 1; }",
    "@media (max-width: 640px) { .pm-admin-hint { font-size: 12.5px; padding: 10px 12px; gap: 8px; }",
    "  .pm-admin-hint-btn { padding: 5px 10px; } }"
  ].join("\n");

  function injectAdminHintStyle() {
    if (document.getElementById("pmAdminHintStyle")) return;
    var el = document.createElement("style");
    el.id = "pmAdminHintStyle";
    el.textContent = ADMIN_HINT_CSS;
    document.head.appendChild(el);
  }

  // V0.81.1：401 + "admin token required" 时弹出顶部横幅，引导用户去设置页
  // sessionStorage 标记每个会话只弹一次（避免反复 401 时刷屏）
  function showAdminTokenRequiredHint() {
    try {
      if (sessionStorage.getItem(ADMIN_TOKEN_HINT_FLAG)) return;
      sessionStorage.setItem(ADMIN_TOKEN_HINT_FLAG, "1");
    } catch (e) { /* 隐私模式 → 不阻止弹 */ }
    if (document.getElementById("pmAdminTokenHint")) return;

    injectAdminHintStyle();

    // 设置页 URL：与 LAN nginx /static/ location 对齐（不论 /gold/ 还是 /static/ 入口都能找到）
    var settingsUrl = (location.pathname.indexOf("/gold/") !== -1 ? "/gold/" : "/") + "static/settings.html";

    var banner = document.createElement("div");
    banner.id = "pmAdminTokenHint";
    banner.className = "pm-admin-hint";
    banner.setAttribute("role", "alert");
    banner.innerHTML =
      '<span class="pm-admin-hint-icon" aria-hidden="true">🔑</span>' +
      '<span class="pm-admin-hint-msg"></span>' +
      '<a class="pm-admin-hint-btn" href="' + settingsUrl + '"></a>' +
      '<button type="button" class="pm-admin-hint-close" aria-label="close" title="关闭">×</button>';

    banner.querySelector(".pm-admin-hint-msg").textContent = t(
      "admin_token.missing",
      "当前浏览器未设置管理员令牌，所有写操作被拒绝"
    );
    banner.querySelector(".pm-admin-hint-btn").textContent = t(
      "admin_token.go_settings",
      "去设置"
    );
    banner.querySelector(".pm-admin-hint-close").addEventListener("click", function () {
      banner.remove();
    });

    document.body.appendChild(banner);
  }

  function isLoginPage() {
    return location.pathname.indexOf("login.html") !== -1;
  }

  function sameOrigin(input) {
    try {
      var url = typeof input === "string" ? input : (input && input.url) || "";
      if (!url) return true; // Request 对象拿不到 url 时按同源处理（浏览器会再拦一层）
      return new URL(url, location.origin).origin === location.origin;
    } catch (e) {
      return true;
    }
  }

  function hasHeader(init, name) {
    var h = init && init.headers;
    if (!h) return false;
    if (typeof h === "object" && !(h instanceof Headers)) {
      return Object.keys(h).some(function (k) { return k.toLowerCase() === name.toLowerCase(); });
    }
    if (h instanceof Headers) return h.has(name);
    return false; // 数组形式忽略（既有代码未使用）
  }

  /* ─────────────── fetch 打补丁 ─────────────── */

  var nativeFetch = window.fetch ? window.fetch.bind(window) : null;

  function patchedFetch(input, init) {
    init = init || {};
    var method = String(init.method || (input && input.method) || "GET").toUpperCase();

    if (WRITE_METHODS[method] && sameOrigin(input)) {
      // 1) CSRF 头：cookie 读得到才附加
      if (!hasHeader(init, CSRF_HEADER)) {
        var csrf = csrfToken();
        if (csrf) {
          if (init.headers instanceof Headers) {
            init.headers.set(CSRF_HEADER, csrf);
          } else if (init.headers && typeof init.headers === "object") {
            init.headers = Object.assign({}, init.headers);
            init.headers[CSRF_HEADER] = csrf;
          } else {
            init.headers = {};
            init.headers[CSRF_HEADER] = csrf;
          }
        }
      }
      // 2) V0.80.1 Admin 头：localStorage 读得到才附加（dev 模式后端不要求 → 留空也无所谓）
      if (!hasHeader(init, ADMIN_TOKEN_HEADER)) {
        var adm = adminToken();
        if (adm) {
          if (init.headers instanceof Headers) {
            init.headers.set(ADMIN_TOKEN_HEADER, adm);
          } else if (init.headers && typeof init.headers === "object") {
            init.headers = Object.assign({}, init.headers);
            init.headers[ADMIN_TOKEN_HEADER] = adm;
          } else {
            init.headers = {};
            init.headers[ADMIN_TOKEN_HEADER] = adm;
          }
        }
      }
    }

    init.credentials = init.credentials || "same-origin";

    return nativeFetch(input, init).then(async function (resp) {
      // 会话过期 / 未登录：跳登录页并记住来路（登录后原路返回）
      if (resp.status === 401 && state.authEnabled && !isLoginPage()) {
        var next = encodeURIComponent(location.pathname + location.search);
        location.replace(LOGIN_PAGE + "?next=" + next);
      }
      // V0.81.1：admin token 缺失提示横幅
      // 后端 admin_auth.py:55 返回 401 + detail="admin token required" → 弹横幅引导去设置页
      // 用 clone() 读 body 不影响调用方 resp.json()
      if (resp.status === 401 && !isLoginPage()) {
        try {
          var peek = resp.clone();
          var body = await peek.json();
          if (body && body.detail === "admin token required") {
            showAdminTokenRequiredHint();
          }
        } catch (e) { /* 不是 JSON 或 body 为空，跳过 */ }
      }
      return resp;
    });
  }

  if (nativeFetch) window.fetch = patchedFetch;

  /** 统一的 API 调用（同源 + 自动 CSRF），返回 Response。 */
  function api(path, init) {
    return patchedFetch(path, init);
  }

  /** 调用 API 并解析 JSON；失败时抛带 `code` 的 Error（供 UI 分支）。 */
  function apiJson(path, init) {
    return api(path, init).then(function (resp) {
      return resp.json().catch(function () { return {}; }).then(function (body) {
        if (resp.ok) return body;
        var detail = body && body.detail;
        var code = (detail && detail.code) || body.code || ("http_" + resp.status);
        var message = (detail && detail.message) || (typeof detail === "string" ? detail : "") ||
          t("login.err_network", "请求失败，请稍后重试");
        var err = new Error(message);
        err.code = code;
        err.status = resp.status;
        throw err;
      });
    });
  }

  /* ─────────────── 状态 ─────────────── */

  function loadStatus() {
    return nativeFetch(STATUS_URL, { credentials: "same-origin" })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (data) {
        if (!data) throw new Error("status failed");
        state.loaded = true;
        state.authEnabled = !!data.auth_enabled;
        state.authenticated = !!data.authenticated;
        state.userCount = data.user_count || 0;
        state.allowRegistration = data.allow_registration !== false;
        document.documentElement.setAttribute(
          "data-auth",
          state.authEnabled ? (state.authenticated ? "in" : "out") : "off"
        );
        return state;
      })
      .catch(function (err) {
        console.warn("[auth] 状态获取失败，按「未启用认证」降级", err);
        state.loaded = true;
        state.authEnabled = false;
        return state;
      });
  }

  function fetchMe() {
    return apiJson("/api/v1/auth/me");
  }

  /* ─────────────── UI：顶栏账号 chip ─────────────── */

  var CSS = [
    ".pm-user { position: relative; display: flex; align-items: center; margin-left: 8px; }",
    ".pm-user-chip { display: inline-flex; align-items: center; gap: 6px; cursor: pointer;",
    "  background: rgba(255,255,255,.1); border: 1px solid rgba(255,255,255,.18);",
    "  color: #e6e9ee; border-radius: 999px; padding: 4px 10px 4px 4px; font-size: 12.5px;",
    "  font-family: inherit; line-height: 1; }",
    ".pm-user-chip:hover { background: rgba(255,255,255,.2); }",
    ".pm-user-avatar { width: 24px; height: 24px; border-radius: 50%; background: var(--accent, #806014);",
    "  color: #fff; display: inline-flex; align-items: center; justify-content: center;",
    "  font-weight: 700; font-size: 12px; flex-shrink: 0; }",
    ".pm-user-menu { position: absolute; top: calc(100% + 6px); right: 0; min-width: 190px;",
    "  background: var(--card, #fff); color: var(--text, #1f2329); border: 1px solid var(--border, #e6e8eb);",
    "  border-radius: 10px; box-shadow: 0 8px 24px rgba(0,0,0,.18); padding: 6px; z-index: 260; display: none; }",
    ".pm-user-menu.open { display: block; }",
    ".pm-user-menu .pm-user-head { padding: 8px 10px 6px; border-bottom: 1px solid var(--border, #e6e8eb); margin-bottom: 4px; }",
    ".pm-user-menu .pm-user-mail { font-size: 12.5px; font-weight: 600; word-break: break-all; }",
    ".pm-user-menu .pm-user-role { font-size: 11px; color: var(--muted, #5b6470); margin-top: 2px; }",
    ".pm-user-menu button { display: block; width: 100%; text-align: left; background: transparent;",
    "  border: 0; border-radius: 6px; padding: 8px 10px; font-size: 13px; cursor: pointer;",
    "  color: inherit; font-family: inherit; }",
    ".pm-user-menu button:hover { background: var(--bg, #f7f8fa); }",
    /* 修改密码模态 */
    ".pm-auth-mask { position: fixed; inset: 0; background: rgba(0,0,0,.45); z-index: 400;",
    "  display: flex; align-items: center; justify-content: center; padding: 20px; }",
    ".pm-auth-modal { background: var(--card, #fff); color: var(--text, #1f2329); width: 100%; max-width: 380px;",
    "  border: 1px solid var(--border, #e6e8eb); border-radius: 12px; padding: 18px;",
    "  box-shadow: 0 12px 32px rgba(0,0,0,.28); }",
    ".pm-auth-modal h3 { font-size: 16px; margin-bottom: 12px; }",
    ".pm-auth-modal label { display: block; font-size: 12.5px; color: var(--muted, #5b6470); margin: 10px 0 4px; }",
    ".pm-auth-modal input { width: 100%; padding: 9px 11px; font-size: 14px; border-radius: 8px;",
    "  border: 1px solid var(--border, #e6e8eb); background: var(--bg, #f7f8fa); color: inherit;",
    "  font-family: inherit; }",
    ".pm-auth-modal input:focus { outline: 2px solid var(--focus-ring, #1971c2); outline-offset: 1px; }",
    ".pm-auth-err { color: var(--down, #1f7a35); font-size: 12.5px; margin-top: 8px; min-height: 16px; }",
    ".pm-auth-ok { color: var(--up, #c92a2a); font-size: 12.5px; margin-top: 8px; }",
    ".pm-auth-actions { display: flex; gap: 8px; justify-content: flex-end; margin-top: 16px; }",
    ".pm-auth-actions button { padding: 8px 14px; font-size: 13px; border-radius: 8px; cursor: pointer;",
    "  font-family: inherit; border: 1px solid var(--border, #e6e8eb); background: transparent; color: inherit; }",
    ".pm-auth-actions button.pm-primary { background: var(--accent, #806014); border-color: var(--accent, #806014);",
    "  color: #fff; font-weight: 600; }",
    ".pm-auth-actions button[disabled] { opacity: .6; cursor: not-allowed; }",
    "@media (max-width: 640px) { .pm-user-name { display: none; } }"
  ].join("\n");

  function injectStyle() {
    if (document.getElementById("pmAuthStyle")) return;
    var el = document.createElement("style");
    el.id = "pmAuthStyle";
    el.textContent = CSS;
    document.head.appendChild(el);
  }

  function initialOf(user) {
    var src = (user && (user.display_name || user.email)) || "?";
    return src.trim().charAt(0).toUpperCase();
  }

  function buildUserWidget(user) {
    var wrap = document.createElement("div");
    wrap.className = "pm-user";
    wrap.id = "pmUserWidget";

    var chip = document.createElement("button");
    chip.type = "button";
    chip.className = "pm-user-chip";
    chip.setAttribute("aria-haspopup", "true");
    chip.setAttribute("aria-expanded", "false");
    chip.setAttribute(
      "aria-label",
      t("login.chip_aria", "账号菜单：{name}").replace("{name}", user.display_name || user.email)
    );
    chip.innerHTML =
      '<span class="pm-user-avatar" aria-hidden="true"></span>' +
      '<span class="pm-user-name"></span><span aria-hidden="true">▾</span>';
    chip.querySelector(".pm-user-avatar").textContent = initialOf(user);
    chip.querySelector(".pm-user-name").textContent = user.display_name || user.email;

    var menu = document.createElement("div");
    menu.className = "pm-user-menu";
    menu.setAttribute("role", "menu");

    var head = document.createElement("div");
    head.className = "pm-user-head";
    var mail = document.createElement("div");
    mail.className = "pm-user-mail";
    mail.textContent = user.email;
    var role = document.createElement("div");
    role.className = "pm-user-role";
    role.textContent =
      user.role === "owner" ? t("login.role_owner", "管理员") : t("login.role_member", "成员");
    head.appendChild(mail);
    head.appendChild(role);

    var btnPwd = document.createElement("button");
    btnPwd.type = "button";
    btnPwd.setAttribute("role", "menuitem");
    btnPwd.textContent = "🔑 " + t("login.btn_change_pwd", "修改密码");

    var btnOut = document.createElement("button");
    btnOut.type = "button";
    btnOut.setAttribute("role", "menuitem");
    btnOut.textContent = "↩ " + t("login.btn_logout", "退出登录");

    // V0.75.3：用户管理入口，**仅 owner 可见**。
    // ⚠ 前端隐藏只是提示 —— 真正的鉴权在 `dependencies.require_owner`，
    // 直接打API 仍会被403拦下。两层都要有。
    var btnAdmin = document.createElement("button");
    btnAdmin.type = "button";
    btnAdmin.setAttribute("role", "menuitem");
    btnAdmin.textContent = "👥 " + t("admin.menu_entry", "用户管理");

    menu.appendChild(head);
    menu.appendChild(btnPwd);
    if (user.role === "owner") {
      menu.appendChild(btnAdmin);
    }
    menu.appendChild(btnOut);
    wrap.appendChild(chip);
    wrap.appendChild(menu);

    function toggle(open) {
      var next = open == null ? !menu.classList.contains("open") : open;
      menu.classList.toggle("open", next);
      chip.setAttribute("aria-expanded", next ? "true" : "false");
    }

    chip.addEventListener("click", function (e) {
      e.stopPropagation();
      toggle();
    });
    document.addEventListener("click", function () { toggle(false); });
    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape") toggle(false);
    });

    btnPwd.addEventListener("click", function (e) {
      e.stopPropagation();
      toggle(false);
      openChangePasswordDialog(user);
    });
    btnAdmin.addEventListener("click", function (e) {
      e.stopPropagation();
      toggle(false);
      // ⚠ 用**绝对路径**跳走：本页可能被部署在子目录（/static/admin/），
      // 相对路径 "./users.html" 在某些部署形态下会解析到错误位置。
      window.location.href = "/static/admin/users.html";
    });
    btnOut.addEventListener("click", function (e) {
      e.stopPropagation();
      doLogout();
    });

    return wrap;
  }

  function mountUserWidget(user) {
    if (!user) return;
    var nav = document.querySelector(".topnav");
    if (!nav) return; // 页面无顶栏（如登录页）→ 不注入
    var existing = document.getElementById("pmUserWidget");
    if (existing) existing.remove();
    var widget = buildUserWidget(user);
    nav.appendChild(widget);
  }

  /* ─────────────── 修改密码对话框 ─────────────── */

  function openChangePasswordDialog(user) {
    if (document.getElementById("pmAuthModalMask")) return;
    injectStyle();

    var mask = document.createElement("div");
    mask.className = "pm-auth-mask";
    mask.id = "pmAuthModalMask";
    mask.innerHTML =
      '<div class="pm-auth-modal" role="dialog" aria-modal="true" aria-labelledby="pmAuthModalTitle">' +
      '<h3 id="pmAuthModalTitle"></h3>' +
      '<label for="pmPwdCur"></label><input id="pmPwdCur" type="password" autocomplete="current-password">' +
      '<label for="pmPwdNew"></label><input id="pmPwdNew" type="password" autocomplete="new-password">' +
      '<label for="pmPwdConfirm"></label><input id="pmPwdConfirm" type="password" autocomplete="new-password">' +
      '<div class="pm-auth-err" id="pmPwdErr" role="alert"></div>' +
      '<div class="pm-auth-actions">' +
      '<button type="button" id="pmPwdCancel"></button>' +
      '<button type="button" id="pmPwdSave" class="pm-primary"></button>' +
      "</div></div>";

    mask.querySelector("#pmAuthModalTitle").textContent = t("login.modal_title", "修改密码");
    mask.querySelector('label[for="pmPwdCur"]').textContent = t("login.pwd_current", "当前密码");
    mask.querySelector('label[for="pmPwdNew"]').textContent = t("login.pwd_new", "新密码");
    mask.querySelector('label[for="pmPwdConfirm"]').textContent = t("login.pwd_confirm", "确认新密码");
    mask.querySelector("#pmPwdCancel").textContent = t("common.cancel", "取消");
    mask.querySelector("#pmPwdSave").textContent = t("common.save", "保存");

    document.body.appendChild(mask);

    var errEl = mask.querySelector("#pmPwdErr");
    var saveBtn = mask.querySelector("#pmPwdSave");
    var cur = mask.querySelector("#pmPwdCur");
    cur.focus();

    function close() {
      mask.remove();
    }
    mask.querySelector("#pmPwdCancel").addEventListener("click", close);
    mask.addEventListener("click", function (e) {
      if (e.target === mask) close();
    });
    document.addEventListener("keydown", function onEsc(e) {
      if (e.key === "Escape") {
        close();
        document.removeEventListener("keydown", onEsc);
      }
    });

    saveBtn.addEventListener("click", function () {
      var curVal = cur.value;
      var newVal = mask.querySelector("#pmPwdNew").value;
      var confirmVal = mask.querySelector("#pmPwdConfirm").value;
      errEl.className = "pm-auth-err";
      errEl.textContent = "";

      if (!curVal || !newVal) {
        errEl.textContent = t("login.err_password_weak", "密码不符合要求");
        return;
      }
      if (newVal !== confirmVal) {
        errEl.textContent = t("login.pwd_mismatch", "两次输入的新密码不一致");
        return;
      }

      saveBtn.disabled = true;
      saveBtn.textContent = t("login.busy", "处理中…");
      apiJson(CHANGE_PWD_URL, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ current_password: curVal, new_password: newVal })
      })
        .then(function (data) {
          errEl.className = "pm-auth-ok";
          errEl.textContent = t(
            "login.pwd_changed",
            "密码已修改，其他设备已退出登录（{n} 台）"
          ).replace("{n}", String(data.revoked_sessions || 0));
          setTimeout(close, 1600);
        })
        .catch(function (err) {
          errEl.className = "pm-auth-err";
          errEl.textContent = errMessage(err);
          saveBtn.disabled = false;
          saveBtn.textContent = t("common.save", "保存");
        });
    });
  }

  /* ─────────────── 登出 ─────────────── */

  function doLogout() {
    track("logout", {});
    return apiJson(LOGOUT_URL, { method: "POST" })
      .catch(function () { /* 幂等：即便撤销失败也清 cookie 并跳转 */ })
      .then(function () {
        location.replace(LOGIN_PAGE);
      });
  }

  function track(eventType, payload) {
    try {
      if (window.TL && typeof window.TL.track === "function") {
        window.TL.track(eventType, payload || {});
      }
    } catch (e) { /* ignore */ }
  }

  /** 把服务端 code 映射为本地化文案（字典缺失时回退服务端 message）。 */
  function errMessage(err) {
    var code = err && err.code;
    var byCode = {
      invalid_credentials: t("login.err_invalid_credentials", "账号或密码不正确"),
      login_throttled: t("login.err_login_throttled", "登录失败次数过多，请稍后再试"),
      registration_disabled: t("login.err_registration_disabled", "管理员已关闭自助注册"),
      email_taken: t("login.err_email_taken", "该邮箱已注册，请直接登录"),
      password_weak: t("login.err_password_weak", "密码不符合要求（至少 8 位、非纯数字）"),
      email_invalid: t("login.err_email_invalid", "邮箱格式不正确"),
      csrf_failed: t("login.err_csrf_failed", "页面已过期，请刷新后重试"),
      unauthenticated: t("login.err_unauthenticated", "登录状态已失效，请重新登录")
    };
    return byCode[code] || (err && err.message) || t("login.err_network", "网络异常，请稍后重试");
  }

  /* ─────────────── 启动 ─────────────── */

  function boot() {
    return loadStatus().then(function (s) {
      if (!s.authEnabled) {
        // 单用户模式：不注入 UI、不跳转，与 V0.74.3 观感完全一致
        if (isLoginPage() && window.PM_AUTH_PAGE) window.PM_AUTH_PAGE.renderDisabled(s);
        return s;
      }
      if (!s.authenticated) {
        if (!isLoginPage()) {
          var next = encodeURIComponent(location.pathname + location.search);
          location.replace(LOGIN_PAGE + "?next=" + next);
        } else if (window.PM_AUTH_PAGE) {
          window.PM_AUTH_PAGE.renderLogin(s);
        }
        return s;
      }
      // 已登录
      if (isLoginPage()) {
        // 已登录还停在登录页 → 直接回首页（除非刚点过"切换账号"）
        if (!location.search.match(/[?&]stay=1/)) {
          location.replace("/static/trend.html");
          return s;
        }
      }
      injectStyle();
      return fetchMe()
        .then(function (me) {
          state.user = me;
          mountUserWidget(me);
          if (isLoginPage() && window.PM_AUTH_PAGE) window.PM_AUTH_PAGE.renderLoggedIn(me);
          return state;
        })
        .catch(function () {
          // /me 拿不到（会话刚失效）→ 交回未登录分支处理
          if (!isLoginPage()) location.replace(LOGIN_PAGE);
          return state;
        });
    });
  }

  window.PM_AUTH = {
    api: api,
    apiJson: apiJson,
    errMessage: errMessage,
    csrfToken: csrfToken,
    logout: doLogout,
    loadStatus: loadStatus,
    boot: boot,
    t: t,
    track: track,
    mountUserWidget: mountUserWidget,
    openChangePasswordDialog: openChangePasswordDialog,
    LOGIN_PAGE: LOGIN_PAGE,
    LOGIN_URL: LOGIN_URL,
    REGISTER_URL: REGISTER_URL,
    get status() { return state; }
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
