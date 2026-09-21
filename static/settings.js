/* V0.72.0 P3-b · 通知中心（settings.html 业务脚本）
 * ─────────────────────────────────────────────
 * 职责：
 *   - 管理员 Token 持久化（localStorage）
 *   - GET/PUT /api/v1/settings/alert-rules
 *   - POST /api/v1/settings/test-email + test-wechat（含 X-Admin-Token 头）
 *   - 订阅/退订 Web Push（window.PM_PWA）
 *   - 显示 SMTP / Server 酱配置状态（用 test 端点 404 / 400 区分）
 *
 * 设计：
 *   - IIFE + window.PM_Settings 命名空间
 *   - 全部 fetch 走 _adminFetch() 自动注入 admin 头
 *   - 通知抽屉用 #pmNotifDrawer（与 .pm-drawer 共存，不与 nav-drawer 冲突）
 */
(function () {
  "use strict";

  const API = {
    alertRules: "/api/v1/settings/alert-rules",
    testEmail: "/api/v1/settings/test-email",
    testWechat: "/api/v1/settings/test-wechat",
    pushVapidKey: "/api/v1/push/vapid-public-key",
  };
  const LS_ADMIN = "pm_admin_token";

  /* ── Admin Token 持久化 ─────────────────────────── */
  function getAdminToken() {
    try { return localStorage.getItem(LS_ADMIN) || ""; } catch (e) { return ""; }
  }
  function setAdminToken(v) {
    try {
      if (v) localStorage.setItem(LS_ADMIN, v);
      else localStorage.removeItem(LS_ADMIN);
    } catch (e) { /* ignore */ }
  }
  function adminHeaders() {
    const t = getAdminToken();
    return t ? { "X-Admin-Token": t } : {};
  }
  async function adminFetch(url, opts) {
    opts = opts || {};
    opts.headers = Object.assign({}, opts.headers || {}, adminHeaders());
    opts.headers["Content-Type"] = opts.headers["Content-Type"] || "application/json";
    const r = await fetch(url, opts);
    if (!r.ok) {
      const body = await r.json().catch(() => ({}));
      const err = new Error(body.detail || `HTTP ${r.status}`);
      err.status = r.status;
      throw err;
    }
    return r.json();
  }

  /* ── 工具 ─────────────────────────────────────── */
  function $(id) { return document.getElementById(id); }
  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, (c) => (
      { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]
    ));
  }
  function track(eventType, payload) {
    if (window.TL && typeof window.TL.track === "function") {
      window.TL.track(eventType, payload || {});
    }
  }

  /* ── 1. 管理员 Token UI ────────────────────────── */
  function bindAdminTokenUi() {
    const input = $("adminToken");
    const hint = $("adminTokenHint");
    const clear = $("btnClearToken");
    if (!input) return;
    const cur = getAdminToken();
    if (cur) {
      input.value = cur;
      hint.textContent = "已保存（" + cur.length + " 字符）";
      hint.style.color = "var(--up)";
    }
    input.addEventListener("change", () => {
      const v = (input.value || "").trim();
      setAdminToken(v);
      hint.textContent = v ? "已保存（" + v.length + " 字符）" : "未保存";
      hint.style.color = v ? "var(--up)" : "var(--muted)";
    });
    clear.addEventListener("click", () => {
      input.value = "";
      setAdminToken("");
      hint.textContent = "未保存";
      hint.style.color = "var(--muted)";
    });
  }

  /* ── 2. 告警规则 ────────────────────────────────── */
  function readRulesFromForm() {
    const channels = Array.from(document.querySelectorAll("#channelBox .channel input:checked"))
      .map((cb) => cb.value);
    return {
      level_crossing_enabled: $("ruleLevelCrossing").checked,
      volatility_enabled: $("ruleVolatility").checked,
      volatility_pct: parseFloat($("ruleVolPct").value) || 3.0,
      quiet_hours: {
        start: $("quietStart").value || "22:00",
        end: $("quietEnd").value || "07:00",
      },
      channels: channels,
    };
  }

  function writeRulesToForm(rules) {
    $("ruleLevelCrossing").checked = !!rules.level_crossing_enabled;
    $("ruleVolatility").checked = !!rules.volatility_enabled;
    $("ruleVolPct").value = rules.volatility_pct != null ? rules.volatility_pct : 3.0;
    $("quietStart").value = (rules.quiet_hours && rules.quiet_hours.start) || "22:00";
    $("quietEnd").value = (rules.quiet_hours && rules.quiet_hours.end) || "07:00";
    document.querySelectorAll("#channelBox .channel").forEach((box) => {
      const ch = box.dataset.ch;
      const cb = box.querySelector("input");
      const on = (rules.channels || []).indexOf(ch) >= 0;
      cb.checked = on;
      box.classList.toggle("checked", on);
    });
  }

  function bindChannelUi() {
    // 切换 checked 样式
    document.querySelectorAll("#channelBox .channel").forEach((box) => {
      box.addEventListener("click", (e) => {
        if (e.target.tagName !== "INPUT") {
          const cb = box.querySelector("input");
          cb.checked = !cb.checked;
        }
        box.classList.toggle("checked", box.querySelector("input").checked);
      });
    });
  }

  async function loadRules() {
    try {
      const rules = await adminFetch(API.alertRules);
      writeRulesToForm(rules);
      $("rulesErr").textContent = "";
    } catch (e) {
      $("rulesErr").textContent = "加载失败：" + e.message;
    }
  }

  async function saveRules() {
    const errEl = $("rulesErr");
    const okEl = $("rulesOk");
    errEl.textContent = "";
    okEl.textContent = "";
    const payload = readRulesFromForm();
    // 客户端兜底校验
    if (!payload.channels.length) {
      errEl.textContent = "请至少选择一个推送渠道";
      return;
    }
    if (payload.volatility_pct < 0.1 || payload.volatility_pct > 20) {
      errEl.textContent = "波动阈值必须在 0.1 - 20 之间";
      return;
    }
    try {
      const saved = await adminFetch(API.alertRules, {
        method: "PUT",
        body: JSON.stringify(payload),
      });
      writeRulesToForm(saved);
      okEl.textContent = "✅ 已保存（" + (saved.updated_at || new Date().toISOString()) + "）";
      setTimeout(() => { okEl.textContent = ""; }, 4000);
      track("alert_rule_save", { channels: payload.channels.join(","), vol_pct: payload.volatility_pct });
    } catch (e) {
      errEl.textContent = "保存失败：" + e.message + (e.status === 401 ? "（管理员 Token 缺失或错误）" : "");
    }
  }

  /* ── 3. SMTP / Server 酱 测试 ───────────────────── */
  async function detectChannelStatus() {
    // 用 test 端点判断：401 = 配置未就绪 / dev 模式无 ADMIN_TOKEN 会通过；返回 success=false 即未配置
    let smtp = "未配置（dev 模式无法远程探测，仅依据 .env 是否设置 SMTP_HOST）";
    let wechat = "未配置（同上，依据 .env 是否设置 SERVERCHAN_SENDKEY）";
    // 直接通过 test 返回值判定（dev 模式：SMTP 未配置时 success=false，message 含「SMTP 未配置」）
    try {
      const r = await adminFetch(API.testEmail);
      smtp = r.success ? "✅ 已配置（测试发送成功）" : "❌ " + (r.message || "未配置或发送失败");
    } catch (e) {
      smtp = "❌ " + e.message;
    }
    try {
      const r = await adminFetch(API.testWechat);
      wechat = r.success ? "✅ 已配置（测试发送成功）" : "❌ " + (r.message || "未配置或发送失败");
    } catch (e) {
      wechat = "❌ " + e.message;
    }
    $("smtpStatus").value = smtp;
    $("wechatStatus").value = wechat;
  }

  async function testChannel(which) {
    const okEl = $(which === "email" ? "emailOk" : "wechatOk");
    const errEl = $(which === "email" ? "emailErr" : "wechatErr");
    okEl.textContent = "";
    errEl.textContent = "";
    const url = which === "email" ? API.testEmail : API.testWechat;
    const label = which === "email" ? "邮件" : "微信";
    try {
      const r = await adminFetch(url, { method: "POST" });
      if (r.success) {
        okEl.textContent = "✅ 测试" + label + "已发送，请检查收件箱";
        track(which === "email" ? "alert_email_sent" : "alert_wechat_sent", { test: true });
      } else {
        errEl.textContent = "❌ " + (r.message || "发送失败");
      }
    } catch (e) {
      errEl.textContent = "❌ " + e.message + (e.status === 401 ? "（管理员 Token 缺失或错误）" : "");
    }
  }

  /* ── 4. PWA + Web Push ──────────────────────────── */
  function updatePwaUi() {
    const titleEl = $("pwaTitle");
    const subEl = $("pwaSub");
    const iconEl = $("pwaIcon");
    if (!titleEl) return;
    const isStandalone = window.matchMedia("(display-mode: standalone)").matches;
    const isIOS = /iPad|iPhone|iPod/.test(navigator.userAgent) && !window.MSStream;
    const hasSw = "serviceWorker" in navigator;
    const hasPush = "PushManager" in window;
    let title, sub, icon;
    if (!hasSw) {
      title = "当前浏览器不支持 PWA"; sub = "请使用 Chrome / Edge / Safari 16.4+"; icon = "❌";
    } else if (isIOS && !isStandalone) {
      title = "iOS 需先添加到主屏"; sub = "底部分享按钮 → 添加到主屏"; icon = "📱";
    } else if (isStandalone) {
      title = "✅ 已安装到桌面"; sub = "可离线访问 + 接收 Web Push"; icon = "📲";
    } else {
      title = "可安装到桌面"; sub = "Chrome / Edge 浏览器会自动弹出安装提示"; icon = "📱";
    }
    titleEl.textContent = title;
    subEl.textContent = sub;
    iconEl.textContent = icon;
  }

  async function getCurrentSubscription() {
    if (!("serviceWorker" in navigator) || !("PushManager" in window)) return null;
    try {
      const reg = await navigator.serviceWorker.ready;
      return await reg.pushManager.getSubscription();
    } catch (e) { return null; }
  }

  async function bindPwaUi() {
    updatePwaUi();
    const sub = await getCurrentSubscription();
    const btnUnsub = $("btnUnsubscribePush");
    if (sub) {
      $("pwaOk").textContent = "✅ 已订阅 Web Push（endpoint " + sub.endpoint.slice(0, 30) + "...）";
      btnUnsub.style.display = "";
    } else {
      btnUnsub.style.display = "none";
    }
    $("btnSubscribePush").addEventListener("click", async () => {
      $("pwaErr").textContent = "";
      $("pwaOk").textContent = "";
      if (!window.PM_PWA || !window.PM_PWA.ensurePushSubscribed) {
        $("pwaErr").textContent = "PWA 脚本未就绪";
        return;
      }
      const r = await window.PM_PWA.ensurePushSubscribed();
      if (r && r.ok) {
        $("pwaOk").textContent = "✅ 已订阅 Web Push";
        const s = await getCurrentSubscription();
        if (s) btnUnsub.style.display = "";
      } else {
        $("pwaErr").textContent = "❌ 订阅失败：" + (r && r.reason ? r.reason : "未知原因");
      }
    });
    $("btnUnsubscribePush").addEventListener("click", async () => {
      $("pwaErr").textContent = "";
      $("pwaOk").textContent = "";
      try {
        const s = await getCurrentSubscription();
        if (s) {
          await s.unsubscribe();
          await fetch("/api/v1/push/subscribe?endpoint=" + encodeURIComponent(s.endpoint), { method: "DELETE" });
        }
        $("pwaOk").textContent = "✅ 已退订";
        btnUnsub.style.display = "none";
      } catch (e) {
        $("pwaErr").textContent = "❌ " + e.message;
      }
    });
    $("btnOpenNotifDrawer").addEventListener("click", () => {
      if (window.PM_Notifications && window.PM_Notifications.open) {
        window.PM_Notifications.open();
      }
      track("notification_center_open", { from: "settings" });
    });
  }

  /* ── 5. 入口 ────────────────────────────────────── */
  function init() {
    bindAdminTokenUi();
    bindChannelUi();
    $("btnSaveRules").addEventListener("click", saveRules);
    $("btnReloadRules").addEventListener("click", loadRules);
    $("btnTestEmail").addEventListener("click", () => testChannel("email"));
    $("btnTestWechat").addEventListener("click", () => testChannel("wechat"));
    loadRules();
    detectChannelStatus();
    bindPwaUi();
  }

  window.PM_Settings = {
    init,
    loadRules,
    saveRules,
    testChannel,
    adminFetch,
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
