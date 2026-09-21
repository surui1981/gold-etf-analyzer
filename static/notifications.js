/* V0.72.0 P3-b · 通知抽屉（notifications.js）
 * ─────────────────────────────────────────
 * 职责：
 *   - 从 /api/v1/telemetry/stats 拉近 7 天事件聚合
 *   - 渲染「推送统计 · 近 7 天」侧抽屉
 *
 * 设计：
 *   - IIFE + window.PM_Notifications 命名空间
 *   - 抽屉与 nav-drawer 共用视觉风格，独立 ID（pmNotifDrawer）避免冲突
 *   - 数据零依赖（settings.html 注入 DOM）
 */
(function () {
  "use strict";

  const TELEMETRY_STATS = "/api/v1/telemetry/stats?days=7";

  // 事件类型 → 中文标签 + 图标（与后端 ALLOWED_EVENT_TYPES 对齐）
  const EVENT_LABELS = {
    alert_email_sent: { lbl: "邮件告警", ico: "📧" },
    alert_wechat_sent: { lbl: "微信告警", ico: "💬" },
    alert_browser_click: { lbl: "浏览器通知点击", ico: "🔔" },
    pwa_installed: { lbl: "PWA 安装", ico: "📲" },
    pwa_install_prompted: { lbl: "PWA 安装提示", ico: "📱" },
    push_channel_click: { lbl: "Web Push 订阅", ico: "📨" },
    alert_rule_save: { lbl: "告警规则保存", ico: "⚙️" },
  };

  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, (c) => (
      { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]
    ));
  }

  function open() {
    document.body.classList.add("pm-notif-open");
    load();
  }

  function close() {
    document.body.classList.remove("pm-notif-open");
  }

  async function load() {
    const body = document.getElementById("notifStatsBody");
    if (!body) return;
    body.innerHTML = '<div class="notif-empty">加载中…</div>';
    try {
      const r = await fetch(TELEMETRY_STATS);
      if (!r.ok) throw new Error("HTTP " + r.status);
      const data = await r.json();
      render(body, data);
    } catch (e) {
      body.innerHTML = '<div class="notif-empty">加载失败：' + esc(e.message) + '</div>';
    }
  }

  function render(body, data) {
    const byType = {};
    if (data && data.by_type) {
      data.by_type.forEach((row) => { byType[row.event_type] = row; });
    }
    // 关心的 7 类事件
    const keys = Object.keys(EVENT_LABELS);
    let html = "";
    let total = 0;
    let hasAny = false;
    keys.forEach((k) => {
      const row = byType[k];
      const c7d = row ? (row.count_7d || 0) : 0;
      const c24h = row ? (row.count_24h || 0) : 0;
      if (c7d > 0) hasAny = true;
      total += c7d;
      const meta = EVENT_LABELS[k];
      html += '<div class="stat-row">'
        + '<span class="lbl">' + meta.ico + ' ' + esc(meta.lbl) + '</span>'
        + '<span class="val">' + c7d + ' <span style="font-size:11px;color:#9aa0a6">(' + c24h + '/24h)</span></span>'
        + '</div>';
    });
    if (!hasAny && total === 0) {
      html += '<div class="notif-empty">近 7 天暂无推送 / 通知事件<br><span style="font-size:11px">保存规则、订阅 Web Push、测试发送后会出现在这里</span></div>';
    }
    // 总计
    html += '<div class="stat-row" style="margin-top:12px;padding-top:12px;border-top:1px solid rgba(255,255,255,.15)">'
      + '<span class="lbl" style="color:#f5d97a">总计</span>'
      + '<span class="val">' + total + '</span>'
      + '</div>';
    body.innerHTML = html;
  }

  function bindUi() {
    const mask = document.getElementById("pmNotifMask");
    const closeBtn = document.getElementById("pmNotifClose");
    if (mask) mask.addEventListener("click", close);
    if (closeBtn) closeBtn.addEventListener("click", close);
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape" && document.body.classList.contains("pm-notif-open")) close();
    });
  }

  window.PM_Notifications = { open, close, load };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", bindUi);
  } else {
    bindUi();
  }
})();
