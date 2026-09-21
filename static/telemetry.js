/*!
 * telemetry.js —— 前端埋点底座（V0.68.0）
 *
 * 用法（页面 <body> 末尾）：
 *   <script src="/static/telemetry.js" defer></script>
 *
 * 提供：
 *   TL.track('page_view', { url: location.pathname });         // 立即缓冲
 *   TL.track('action_click', { target: '#saveBtn' });           // 立即缓冲
 *   TL.flush();                                                // 强制 flush
 *
 * 设计：
 * - 事件缓冲：内存队列每 4s / 20 条自动 flush（满足其一）
 * - 页面隐藏（visibilitychange / pagehide）→ 用 sendBeacon 兜底上报，避免丢数据
 * - 服务端白名单（ALLOWED_EVENT_TYPES）由后端校验；前端常量同名，便于静态分析
 * - session_id：localStorage.pm_telemetry_session_id（UUIDv4 hex），首次访问生成
 * - 不抛错：fetch 失败 / 网络异常一律 console.warn，不影响业务
 *
 * 全站共享，零依赖。
 */
(function () {
  'use strict';

  var INGEST_URL = '/api/v1/telemetry/ingest';
  var STORE_KEY = 'pm_telemetry_session_id';
  var FLUSH_MS = 4000;
  var FLUSH_MAX = 20;
  var SESSION_LEN = 32; // UUIDv4 hex（去掉连字符 = 32 字符）

  // 与后端 services/telemetry.py ALLOWED_EVENT_TYPES 同步
  var ALLOWED_EVENT_TYPES = {
    page_view: 1, action_click: 1, range_change: 1, error_caught: 1,
    palette_open: 1, palette_query: 1, palette_select: 1,
    nav_drawer_open: 1, nav_drawer_select: 1,
    theme_change: 1,
    resonance_card_click: 1,
    grams_trade_open: 1,
    equity_curve_switch_unit: 1,
    // V0.71.0 P3-a：白银 / 回测 页面事件
    silver_page_view: 1,
    silver_nav_click: 1,
    backtest_run: 1,
    backtest_param_change: 1,
    // V0.72.0 P3-b：告警规则 + 推送渠道
    alert_rule_save: 1,
    alert_email_sent: 1,
    alert_wechat_sent: 1,
    alert_browser_click: 1,
    // V0.72.0 P3-b：PWA + Web Push funnel
    pwa_install_prompted: 1,
    pwa_installed: 1,
    push_channel_click: 1
  };

  var queue = [];
  var timer = null;

  /* ─────────────── 工具 ─────────────── */

  function uuidv4Hex() {
    // 32-char hex UUID（无连字符）
    var hex = '0123456789abcdef';
    var out = '';
    var bytes;
    if (window.crypto && window.crypto.getRandomValues) {
      bytes = new Uint8Array(16);
      window.crypto.getRandomValues(bytes);
    } else {
      bytes = new Array(16);
      for (var i = 0; i < 16; i++) bytes[i] = Math.floor(Math.random() * 256);
    }
    for (var j = 0; j < 16; j++) {
      var b = bytes[j];
      out += hex[(b >> 4) & 0xf] + hex[b & 0xf];
    }
    return out;
  }

  function getSessionId() {
    try {
      var s = localStorage.getItem(STORE_KEY);
      if (s && /^[0-9a-f]{32}$/.test(s)) return s;
      s = uuidv4Hex();
      localStorage.setItem(STORE_KEY, s);
      return s;
    } catch (e) {
      return uuidv4Hex(); // 隐私模式：每次新建（不持久）
    }
  }

  function nowIso() {
    try { return new Date().toISOString(); } catch (e) { return null; }
  }

  /* ─────────────── 入队 ─────────────── */

  function track(eventType, payload) {
    if (!eventType || !ALLOWED_EVENT_TYPES[eventType]) {
      // 静默丢弃：未在白名单的事件（防止业务侧拼错）
      return;
    }
    var p = payload && typeof payload === 'object' ? payload : {};
    // payload 字段数上限（与服务端校验对齐，节省内存）
    if (Object.keys(p).length > 50) return;

    queue.push({
      event_type: eventType,
      page: location.pathname + (location.search || ''),
      payload: p,
      session_id: getSessionId(),
      client_ts: nowIso()
    });

    if (queue.length >= FLUSH_MAX) flush();
    else scheduleFlush();
  }

  function scheduleFlush() {
    if (timer) return;
    timer = setTimeout(function () {
      timer = null;
      flush();
    }, FLUSH_MS);
  }

  /* ─────────────── 上报 ─────────────── */

  function flush() {
    if (!queue.length) return;
    var batch = queue.splice(0, queue.length);
    if (timer) { clearTimeout(timer); timer = null; }

    var body = JSON.stringify({ events: batch });

    // 优先 sendBeacon（pagehide / 卸载时也能投递）
    if (navigator.sendBeacon) {
      try {
        var blob = new Blob([body], { type: 'application/json' });
        if (navigator.sendBeacon(INGEST_URL, blob)) return;
      } catch (e) { /* 回退到 fetch */ }
    }

    // 回退 fetch（keepalive 防止页面关闭丢请求）
    try {
      fetch(INGEST_URL, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: body,
        keepalive: true
      }).catch(function () { /* 静默 */ });
    } catch (e) { /* 静默 */ }
  }

  /* ─────────────── 生命周期 ─────────────── */

  // 页面隐藏时立刻 flush（sendBeacon）
  document.addEventListener('visibilitychange', function () {
    if (document.visibilityState === 'hidden') flush();
  });
  window.addEventListener('pagehide', flush);

  // 全局异常兜底（不影响业务，仅埋点）
  window.addEventListener('error', function (e) {
    try {
      track('error_caught', {
        msg: String(e.message || '').slice(0, 200),
        src: String(e.filename || '').slice(0, 200),
        line: e.lineno || 0,
        col: e.colno || 0
      });
    } catch (_) { /* 静默 */ }
  });

  // 暴露 API
  var TL = {
    track: track,
    flush: flush,
    sessionId: getSessionId,
    ALLOWED: Object.keys(ALLOWED_EVENT_TYPES)
  };
  window.TL = TL;

  // 首屏 page_view（DOM 就绪后立即触发）
  function emitPageView() {
    track('page_view', { title: document.title || '' });
  }
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', emitPageView);
  } else {
    emitPageView();
  }
})();
