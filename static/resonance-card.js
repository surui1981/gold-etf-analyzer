/*!
 * resonance-card.js —— 共振信号卡（V0.70.0 P2 #7）
 *
 * 在 trend 页头部渲染「宏观 / 技术 / 消息面」三维度共振信号：
 * - STRONG_UP / STRONG_DOWN：强共振（4 色高亮）
 * - WEAK_UP：弱多信号（橙色）
 * - DIVERGENT：背离（紫色）
 * - NEUTRAL：中性（灰色）
 *
 * 用法：trend.html 中加入 <section id="resonanceCard"></section> 并引入本脚本；
 * window.PM_Resonance.load() 由 trend.init() 调用，60s 周期刷新。
 *
 * 公开 API：window.PM_Resonance = { load, openModal }
 *
 * 设计要点：
 * - IIFE + window.PM_* 模式（与 PM_Help / PM_CmdPalette 一致）；
 * - 自注入 <style id="resonanceCardStyle">（不污染全局 theme.css）；
 * - 复用 theme.css 已有的 --up / --down / --accent / --muted 变量，4 主题自适应；
 * - 点击卡片 → 弹窗显示 components 表 + STRONG_UP 命中率链接；
 * - 埋点：resonance_card_click（首次点击）。
 */
(function () {
  'use strict';

  var REFRESH_MS = 60000;
  var FETCH_TIMEOUT_MS = 15000;

  // 4 类信号 → 视觉映射（颜色全部走 CSS 变量，自适应 4 主题）
  var SIGNAL_META = {
    strong_up:   { cls: 'rc-strong-up',   label: '强共振看多', icon: '🟢' },
    strong_down: { cls: 'rc-strong-down', label: '强共振看空', icon: '🔴' },
    weak_up:     { cls: 'rc-weak-up',     label: '弱多信号',   icon: '🟠' },
    divergent:   { cls: 'rc-divergent',   label: '技术/宏观反向', icon: '🟣' },
    neutral:     { cls: 'rc-neutral',     label: '中性震荡',   icon: '⚪' }
  };

  var CSS = [
    '#resonanceCard { padding: 14px 16px; min-height: 64px; cursor: pointer;',
    '  transition: box-shadow 0.15s, transform 0.15s; }',
    '#resonanceCard:hover { box-shadow: 0 2px 12px rgba(0,0,0,0.08); transform: translateY(-1px); }',
    '#resonanceCard:focus-visible { outline: 3px solid var(--focus-ring); outline-offset: 2px; }',
    '.rc-row { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }',
    '.rc-signal { display: inline-flex; align-items: center; gap: 8px; font-size: 18px; font-weight: 700; }',
    '.rc-signal .rc-icon { font-size: 22px; }',
    '.rc-conf { font-size: 13px; color: var(--muted); }',
    '.rc-conf b { color: var(--text); font-weight: 700; font-size: 16px; }',
    '.rc-summary { font-size: 13px; color: var(--muted); margin-top: 6px; line-height: 1.5; }',
    '.rc-meta { font-size: 11px; color: var(--muted); margin-top: 6px; }',
    '.rc-meta a { color: var(--accent); text-decoration: none; border-bottom: 1px dashed var(--accent); }',
    '.rc-meta a:hover { background: var(--accent); color: var(--bg); }',
    /* 4 主题下都用语义色（直接引用 theme.css 的 4 色） */
    '.rc-strong-up { color: var(--up); }',
    '.rc-strong-up .rc-conf b { color: var(--up); }',
    '.rc-strong-down { color: var(--down); }',
    '.rc-strong-down .rc-conf b { color: var(--down); }',
    '.rc-weak-up { color: var(--accent); }',
    '.rc-divergent { color: #7048e8; }',
    '[data-theme="dark"] .rc-divergent { color: #b197fc; }',
    '[data-theme="hc"] .rc-divergent { color: #ffff00; }',
    '.rc-neutral { color: var(--muted); }',
    /* 加载 / 错误态 */
    '.rc-loading { color: var(--muted); font-size: 13px; }',
    '.rc-error { color: var(--down); font-size: 13px; font-weight: 600; }'
  ].join('\n');

  function ensureStyle() {
    if (document.getElementById('resonanceCardStyle')) return;
    var s = document.createElement('style');
    s.id = 'resonanceCardStyle';
    s.textContent = CSS;
    document.head.appendChild(s);
  }

  function fetchJSON(url) {
    var ctl = typeof AbortController !== 'undefined' ? new AbortController() : null;
    var timer = ctl ? setTimeout(function () { ctl.abort(); }, FETCH_TIMEOUT_MS) : null;
    return fetch(url, ctl ? { signal: ctl.signal } : undefined).then(function (r) {
      if (timer) clearTimeout(timer);
      if (!r.ok) throw new Error('HTTP ' + r.status);
      return r.json();
    });
  }

  function render(signal) {
    var card = document.getElementById('resonanceCard');
    if (!card) return;
    var meta = SIGNAL_META[signal.signal] || SIGNAL_META.neutral;
    var comps = signal.components || {};
    var compsStr = '技术 ' + Math.round(comps.tech || 50)
      + ' · 宏观 ' + Math.round(comps.macro || 50)
      + ' · 消息 ' + Math.round(comps.news || 50);
    card.innerHTML =
      '<div class="rc-row ' + meta.cls + '">' +
        '<span class="rc-signal">' +
          '<span class="rc-icon">' + meta.icon + '</span>' +
          '<span>' + (signal.label || meta.label) + '</span>' +
        '</span>' +
        '<span class="rc-conf">置信度 <b>' + (signal.confidence || 0).toFixed(1) + '</b> / 100</span>' +
      '</div>' +
      '<div class="rc-summary">' + (signal.direction_summary || '') + '</div>' +
      '<div class="rc-meta">' +
        '点击查看历史 + STRONG_UP 命中率 · ' +
        '<a href="/api/v1/resonance/strength-up?days=90&amp;horizon=1" target="_blank" rel="noopener">API</a>' +
      '</div>';
  }

  function renderError(msg) {
    var card = document.getElementById('resonanceCard');
    if (!card) return;
    card.innerHTML = '<div class="rc-error">⚠ 共振信号加载失败：' + msg + '（不影响页面其他数据）</div>';
  }

  function load() {
    var card = document.getElementById('resonanceCard');
    if (!card) return Promise.resolve();
    if (card.dataset.loaded !== '1') {
      card.dataset.loaded = '1';
      card.setAttribute('tabindex', '0');
      card.setAttribute('role', 'button');
      card.setAttribute('aria-label', '共振信号详情（点击展开历史与命中统计）');
      // 点击 / 回车 → 弹窗（暂用新窗口打开 strength-up JSON；后续可换 modal）
      card.addEventListener('click', openModal);
      card.addEventListener('keydown', function (e) {
        if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); openModal(); }
      });
    }
    var base = location.port === '8888' ? '' : 'http://127.0.0.1:8888';
    return fetchJSON(base + '/api/v1/resonance/signal')
      .then(render)
      .catch(function (e) { renderError(e.message); });
  }

  function openModal() {
    // 埋点：共振卡片点击
    if (window.TL && typeof window.TL.track === 'function') {
      window.TL.track('resonance_card_click', { url: location.pathname });
    }
    // V0.70.0 MVP：弹窗用浏览器原生 confirm，列出 components + 历史链接
    var base = location.port === '8888' ? '' : 'http://127.0.0.1:8888';
    Promise.all([
      fetchJSON(base + '/api/v1/resonance/signal').catch(function () { return null; }),
      fetchJSON(base + '/api/v1/resonance/strength-up?days=90&horizon=1').catch(function () { return null; })
    ]).then(function (results) {
      var sig = results[0];
      var stats = results[1];
      var lines = [];
      if (sig) {
        lines.push('今日信号：' + (sig.label || sig.signal));
        lines.push('置信度：' + (sig.confidence || 0).toFixed(1) + ' / 100');
        lines.push('维度：' + (sig.direction_summary || '-'));
      } else {
        lines.push('信号加载失败');
      }
      if (stats) {
        lines.push('');
        lines.push('STRONG_UP 命中率（90 天 / T+1）：');
        lines.push('  样本 ' + (stats.resolved || 0) + ' 天，命中 ' + (stats.hits || 0) + ' 天');
        lines.push('  命中率：' + (stats.hit_rate != null ? stats.hit_rate + '%' : '数据不足'));
        if (stats.sample_warning) lines.push('  ⚠ 样本不足，仅供参考');
      } else {
        lines.push('（命中统计加载失败）');
      }
      alert(lines.join('\n'));
    });
  }

  function boot() {
    ensureStyle();
    load();
    setInterval(load, REFRESH_MS);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot);
  } else {
    boot();
  }

  window.PM_Resonance = { load: load, openModal: openModal };
})();
