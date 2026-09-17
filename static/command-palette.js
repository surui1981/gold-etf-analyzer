/*!
 * command-palette.js —— 全局命令面板（V0.68.0）
 *
 * 用法：<script src="/static/command-palette.js" defer></script>
 *
 * 唤起：⌘K（macOS）/ Ctrl+K（其他）；快捷键不依赖焦点（在任何地方按都行）
 *
 * 命令源（静态 + 动态）：
 * - 静态：7 页导航 + 4 个常用动作（评分档位 / 时间区间 / 刷新 / 主题切换）
 * - 动态：当前账本 / 持仓标的 / 评分档位（仅 hint，未集成数据源，避免 7 页硬耦合）
 *
 * 行为：
 * - 输入框即时过滤；↑↓ 选择；Enter 跳转 / 执行；Esc 关闭
 * - 命令面板开关触发 TL.track('palette_open' / 'palette_query' / 'palette_select')
 *
 * 设计：纯原生（无 framework），与 nav-drawer.js 共享样式 ID 命名空间（pm-cmd-*）
 */
(function () {
  'use strict';

  // 静态命令清单（label, kind, action, hint?）
  // action 类型：
  //   - { kind: 'href', url: '/path' }
  //   - { kind: 'fn', run: function() {...} }   // 仅当前页生效
  //   - { kind: 'range', interval: 'D' }          // 趋势页 / 复盘页时间区间
  //   - { kind: 'theme', mode: 'dark' }           // V0.69.0 主题切换
  var COMMANDS = [
    { label: '📈 趋势追踪', hint: '技术 / 宏观 / 消息面', action: { kind: 'href', url: '/static/trend.html' } },
    { label: '💼 持仓与决策', hint: '开仓 / 加减仓 / 综合指数', action: { kind: 'href', url: '/portfolio' } },
    { label: '📜 交易历史', hint: '流水 / 业绩分析', action: { kind: 'href', url: '/trades' } },
    { label: '⚖️ 权重配置', hint: '评分因子权重', action: { kind: 'href', url: '/weights' } },
    { label: '📰 消息面评估', hint: '当日消息打分', action: { kind: 'href', url: '/news' } },
    { label: '🔍 研判复盘', hint: 'T+N 命中与历史依据', action: { kind: 'href', url: '/review' } },
    { label: '🏛️ 央行购金统计', hint: '季度购金 / T12M', action: { kind: 'href', url: '/central-bank' } },
    { label: '🔄 刷新当前页', hint: '重拉行情 / 打分', action: { kind: 'fn', run: function () { location.reload(); } } },
    { label: '📊 切换时间区间 1 日', hint: '趋势页 K 线', action: { kind: 'range', interval: 'D' } },
    { label: '📊 切换时间区间 5 日', hint: '趋势页 K 线', action: { kind: 'range', interval: '5D' } },
    { label: '📊 切换时间区间 1 月', hint: '趋势页 K 线', action: { kind: 'range', interval: 'M' } },
    { label: '🎨 主题切换（V0.69.0 预埋）', hint: '亮 / 暗 / 跟随系统', action: { kind: 'theme', mode: 'auto' } },
    { label: '❓ 帮助（首次访问引导）', hint: '重看功能导览', action: { kind: 'fn', run: function () { window.PM_Help && window.PM_Help.show(); } } }
  ];

  function injectStyle() {
    if (document.getElementById('cmdPaletteStyle')) return;
    var css = [
      '.pm-cmd-mask {',
      '  position: fixed; inset: 0; background: rgba(0,0,0,.5);',
      '  opacity: 0; pointer-events: none; transition: opacity .15s ease;',
      '  z-index: 300;',
      '}',
      'body.pm-cmd-open { overflow: hidden; }',
      'body.pm-cmd-open .pm-cmd-mask { opacity: 1; pointer-events: auto; }',
      '.pm-cmd {',
      '  position: fixed; top: 14vh; left: 50%; transform: translate(-50%, -8px);',
      '  width: 560px; max-width: 92vw; background: #ffffff;',
      '  border-radius: 12px; box-shadow: 0 12px 40px rgba(0,0,0,.3);',
      '  opacity: 0; pointer-events: none; transition: opacity .14s ease, transform .14s ease;',
      '  z-index: 301; overflow: hidden;',
      '}',
      'body.pm-cmd-open .pm-cmd { opacity: 1; transform: translate(-50%, 0); pointer-events: auto; }',
      '.pm-cmd-input {',
      '  width: 100%; box-sizing: border-box; padding: 14px 18px;',
      '  font-size: 16px; border: none; border-bottom: 1px solid #e6e8eb;',
      '  outline: none; color: #1f2329; background: #fff;',
      '}',
      '.pm-cmd-list { max-height: 56vh; overflow-y: auto; padding: 6px 0; }',
      '.pm-cmd-item {',
      '  padding: 10px 18px; cursor: pointer; display: flex;',
      '  justify-content: space-between; gap: 12px; align-items: center;',
      '}',
      '.pm-cmd-item:hover, .pm-cmd-item.pm-cmd-active { background: #f1f3f5; }',
      '.pm-cmd-item .pm-cmd-label { color: #1f2329; font-size: 14.5px; }',
      '.pm-cmd-item .pm-cmd-hint { color: #8a919f; font-size: 12.5px; }',
      '.pm-cmd-empty { padding: 20px; text-align: center; color: #8a919f; font-size: 13px; }',
      '.pm-cmd-foot {',
      '  padding: 8px 18px; border-top: 1px solid #e6e8eb; background: #f7f8fa;',
      '  font-size: 12px; color: #8a919f; display: flex; gap: 14px;',
      '}',
      '.pm-cmd-foot kbd {',
      '  background: #fff; border: 1px solid #d6d9dd; border-radius: 4px;',
      '  padding: 1px 6px; font-size: 11px; font-family: inherit;',
      '}'
    ].join('\n');
    var el = document.createElement('style');
    el.id = 'cmdPaletteStyle';
    el.textContent = css;
    document.head.appendChild(el);
  }

  function buildDom() {
    if (document.querySelector('.pm-cmd')) return;

    var mask = document.createElement('div');
    mask.className = 'pm-cmd-mask';
    mask.addEventListener('click', close);
    document.body.appendChild(mask);

    var panel = document.createElement('div');
    panel.className = 'pm-cmd';
    panel.setAttribute('role', 'dialog');
    panel.setAttribute('aria-label', '全局命令面板');
    panel.innerHTML =
      '<input class="pm-cmd-input" placeholder="搜索页面、动作、时间区间…" aria-label="搜索命令">' +
      '<div class="pm-cmd-list" role="listbox"></div>' +
      '<div class="pm-cmd-foot">' +
      '  <span><kbd>↑↓</kbd> 选择</span>' +
      '  <span><kbd>Enter</kbd> 执行</span>' +
      '  <span><kbd>Esc</kbd> 关闭</span>' +
      '  <span style="margin-left:auto"><kbd>⌘K</kbd> / <kbd>Ctrl K</kbd> 唤起</span>' +
      '</div>';
    document.body.appendChild(panel);

    panel._input = panel.querySelector('.pm-cmd-input');
    panel._list = panel.querySelector('.pm-cmd-list');
    panel._active = 0;
    panel._filtered = COMMANDS.slice();

    panel._input.addEventListener('input', function () { filter(panel, panel._input.value); });
    panel._input.addEventListener('keydown', function (e) {
      if (e.key === 'ArrowDown') { e.preventDefault(); move(panel, 1); }
      else if (e.key === 'ArrowUp') { e.preventDefault(); move(panel, -1); }
      else if (e.key === 'Enter') { e.preventDefault(); select(panel, panel._active); }
      else if (e.key === 'Escape') { e.preventDefault(); close(); }
    });
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape' && document.body.classList.contains('pm-cmd-open')) close();
    });
  }

  function filter(panel, q) {
    q = (q || '').trim().toLowerCase();
    var list = q ? COMMANDS.filter(function (c) {
      return (c.label || '').toLowerCase().indexOf(q) >= 0 ||
             (c.hint || '').toLowerCase().indexOf(q) >= 0;
    }) : COMMANDS.slice();
    panel._filtered = list;
    panel._active = 0;
    render(panel);
    if (q && window.TL) window.TL.track('palette_query', { q_len: q.length });
  }

  function render(panel) {
    var html = '';
    if (!panel._filtered.length) {
      html = '<div class="pm-cmd-empty">无匹配命令</div>';
    } else {
      for (var i = 0; i < panel._filtered.length; i++) {
        var c = panel._filtered[i];
        var cls = 'pm-cmd-item' + (i === panel._active ? ' pm-cmd-active' : '');
        html += '<div class="' + cls + '" data-idx="' + i + '" role="option">' +
                '<span class="pm-cmd-label">' + escHtml(c.label) + '</span>' +
                '<span class="pm-cmd-hint">' + escHtml(c.hint || '') + '</span>' +
                '</div>';
      }
    }
    panel._list.innerHTML = html;
    // 点击
    var items = panel._list.querySelectorAll('.pm-cmd-item');
    for (var k = 0; k < items.length; k++) {
      items[k].addEventListener('click', (function (idx) {
        return function () { select(panel, idx); };
      })(k));
    }
  }

  function move(panel, delta) {
    var n = panel._filtered.length;
    if (!n) return;
    panel._active = (panel._active + delta + n) % n;
    render(panel);
  }

  function select(panel, idx) {
    var c = panel._filtered[idx];
    if (!c) return;
    if (window.TL) {
      window.TL.track('palette_select', {
        label: (c.label || '').slice(0, 30),
        kind: c.action ? c.action.kind : 'unknown'
      });
    }
    close();
    var act = c.action;
    if (!act) return;
    if (act.kind === 'href') {
      location.href = act.url;
    } else if (act.kind === 'fn') {
      try { act.run && act.run(); } catch (e) { console.error(e); }
    } else if (act.kind === 'range') {
      // 趋势页 / 复盘页：触发自定义事件，页面侧监听并切换
      try {
        document.dispatchEvent(new CustomEvent('pm-range-change', { detail: { interval: act.interval } }));
        if (window.TL) window.TL.track('range_change', { source: 'palette', interval: act.interval });
      } catch (e) { /* 静默 */ }
    } else if (act.kind === 'theme') {
      try {
        document.dispatchEvent(new CustomEvent('pm-theme-change', { detail: { mode: act.mode } }));
        if (window.TL) window.TL.track('theme_change', { source: 'palette', mode: act.mode });
      } catch (e) { /* 静默 */ }
    }
  }

  function escHtml(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&', '<': '<', '>': '>', '"': '"', "'": '&#39;' }[c];
    });
  }

  function open() {
    if (window.TL) window.TL.track('palette_open', {});
    document.body.classList.add('pm-cmd-open');
    var panel = document.querySelector('.pm-cmd');
    if (!panel) buildDom();
    panel = document.querySelector('.pm-cmd');
    panel._input.value = '';
    filter(panel, '');
    // 下一帧聚焦（确保过渡已开始）
    setTimeout(function () {
      try { panel._input.focus(); } catch (e) { /* 静默 */ }
    }, 30);
  }

  function close() {
    document.body.classList.remove('pm-cmd-open');
  }

  function toggle() {
    if (document.body.classList.contains('pm-cmd-open')) close();
    else open();
  }

  function installHotkey() {
    document.addEventListener('keydown', function (e) {
      // ⌘K (mac) 或 Ctrl+K (其他)
      if ((e.metaKey || e.ctrlKey) && (e.key === 'k' || e.key === 'K')) {
        // 不在 input/textarea 内才拦截（避免与系统冲突）
        var tag = (e.target && e.target.tagName) || '';
        if (tag === 'INPUT' || tag === 'TEXTAREA') return;
        e.preventDefault();
        toggle();
      }
    });
  }

  // 暴露 API
  var CP = { open: open, close: close, toggle: toggle, COMMANDS: COMMANDS };
  window.PM_CmdPalette = CP;

  function init() {
    injectStyle();
    buildDom();
    installHotkey();
  }
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
