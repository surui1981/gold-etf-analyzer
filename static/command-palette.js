/*!
 * command-palette.js —— 全局命令面板
 *
 * V0.68.0 首版 · V0.112.0 重写命令源
 * ------------------------------------------------------------------
 * 用法：<script src="/static/command-palette.js" defer></script>
 *
 * 唤起：顶栏「⌘ 搜索」按钮（手机唯一入口）/ ⌘K（macOS）/ Ctrl+K（其他）
 *
 * V0.112.0 为什么要重写命令源：
 *   V0.68 首版把命令清单**硬编码**成 7 条平铺导航（趋势/持仓/交易历史/权重/
 *   消息面/复盘/央行），到 V0.98 双层导航、V0.111 收敛到 8 场景时都没跟上 ——
 *   今日要闻、报告存档、打分汇总、参数回测、白银、收藏、数据健康、AI 全部缺席。
 *   根因不是忘了改，而是**没法改**：SCENES 当时只活在 topnav.js 的 IIFE 里，
 *   不导出，面板拿不到导航结构，只能自己抄一份，抄的那份自然腐化。
 *
 *   现在 topnav.js 导出 window.PM_Topnav.SCENES，面板在 **open() 时惰性派生**
 *   清单：8 场景 + 子页去重后 17 个导航目标 + 动作。加减导航项面板自动跟随，
 *   结构上不可能再腐化。惰性读取同时解开了与两个 defer 脚本的执行顺序耦合。
 *
 * 另外删掉了 4 条**本来就没接线的**命令（V0.77.1「失败态不伪装」的同理要求 ——
 * 不能给用户一个按下去什么都不发生的按钮）：
 *   - 切换时间区间 ×3：派发 pm-range-change，全站 **0 个监听方**（已 grep 确认）
 *   - 主题切换：派发 pm-theme-change，同样 0 个监听方；且 #pmThemeBtn 浮动按钮
 *     本来就在 20 个页面上常驻可见，面板里再放一条是冗余
 * 帮助命令**修了并改为按需出现**：V0.68 版调的是 `PM_Help.show()`，而 help.js
 * 导出的是 `{ showModal, showTour, ... }` —— 从来没有 show()，那条也是死命令；
 * 现改调 showModal()。且 help.js 只挂在 10 个页上，PM_Help 不存在时整条不显示。
 *
 * 行为：
 * - 输入框即时过滤（匹配 标题 / URL / 所属场景名）；↑↓ 选择；Enter 执行；Esc 关闭
 * - 清单按 SCENES 顺序分场景分组，组头不可点
 * - i18n:change 事件 → 若面板正开着则重建（换语言后不用关掉重开）
 * - 触屏（pointer: coarse）下加大行高到 44px 触摸目标，底部提示换成触屏文案
 */
(function () {
  'use strict';

  // ────────────── 标签解析（i18n 优先，回落 SCENES.fb）──────────────
  //
  // SCENES 里同时有 i18n key 和中文 fb。直接用 fb 会在 en-US / zh-TW 下显示中文，
  // 而顶栏同一项是翻译过的 —— 面板与顶栏对不上会显得像 bug。
  // I18n.t() 找不到 key 时**返回 key 字面量**（见 i18n.js:76），所以拿返回值和
  // key 比对即可判断是否命中字典。
  function label(item) {
    if (window.I18n && typeof window.I18n.t === 'function' && item.i18n) {
      try {
        var s = window.I18n.t(item.i18n);
        if (s && s !== item.i18n) return s;
      } catch (e) { /* 字典未就绪 → 走 fb */ }
    }
    return item.fb || item.i18n || '';
  }

  function tr(key, fb) {
    if (window.I18n && typeof window.I18n.t === 'function') {
      try {
        var s = window.I18n.t(key);
        if (s && s !== key) return s;
      } catch (e) { /* ignore */ }
    }
    return fb;
  }

  // ────────────── 命令源：从 SCENES 惰性派生 ──────────────

  function buildCommands() {
    var scenes = (window.PM_Topnav && window.PM_Topnav.SCENES) || null;
    var groups = [];

    if (scenes && scenes.length) {
      for (var i = 0; i < scenes.length; i++) {
        var sc = scenes[i];
        var rows = [];
        var subs = sc.subpages || [];

        // 先铺子页（场景入口若与某个子页同 path，会在下面被去重掉，
        // 见 V0.111.1 后 4 个带子页的场景 path 都恰好等于某个子页 path）
        for (var j = 0; j < subs.length; j++) {
          var sp = subs[j];
          rows.push({
            label: (sp.ico ? sp.ico + ' ' : '') + label(sp),
            hint: sp.path,
            search: label(sp) + ' ' + sp.path + ' ' + label(sc),
            section: label(sc),
            action: { kind: 'href', url: sp.path }
          });
        }

        // ⚠ V0.116.4：**场景落地页必须排在组首**。
        //
        // 面板里「输入场景名 → 回车」落到哪一条，取决于组内第一条**命中**的行。
        // 此前子页按 subnav 顺序铺（趋势追踪 / 打分汇总 / 参数回测 / 研判复盘），
        // 而场景自身的 path（决策 = /scoring）恰好等于**第二个**子页的 path，
        // 被去重逻辑吃掉了 ⇒ 输入「决策」时第一条命中的是「趋势追踪」
        // ⇒ 回车把用户送到趋势页 —— 与**点顶栏「决策」**（→ /scoring 打分汇总）
        // 和**点首页「决策」场景卡**（→ /scoring）**不一致**。
        //
        // 现在：场景 path 等于哪个子页的 path，那一条就是落地页，提到组首；
        // 没有同 path 的子页时，场景自身单独成条、同样放组首。
        // ⇒ 「输入场景名 → 回车」与「点顶栏场景入口 / 首页场景卡」落到同一个页面。
        var landingIdx = -1;
        for (var k = 0; k < subs.length; k++) {
          if (subs[k].path === sc.path) { landingIdx = k; break; }
        }
        if (landingIdx >= 0) {
          rows.unshift(rows.splice(landingIdx, 1)[0]);
        } else {
          rows.unshift({
            label: (sc.ico ? sc.ico + ' ' : '') + label(sc),
            hint: sc.path,
            search: label(sc) + ' ' + sc.path,
            section: label(sc),
            action: { kind: 'href', url: sc.path }
          });
        }

        groups.push({ title: label(sc), ico: sc.ico, rows: rows });
      }
    } else {
      // 兜底：topnav.js 没加载（本页无顶栏）时给一条最小可用的刷新动作，
      // 而不是弹一个空面板。
      groups.push({
        title: '', ico: '',
        rows: [{
          label: '🔄 ' + tr('cmd.refresh', '刷新当前页'),
          hint: '',
          search: tr('cmd.refresh', '刷新当前页'),
          section: '',
          action: { kind: 'fn', run: function () { location.reload(); } }
        }]
      });
    }

    // 动作组
    var actions = [{
      label: '🔄 ' + tr('cmd.refresh', '刷新当前页'),
      hint: tr('cmd.refresh_hint', '重拉行情 / 打分'),
      search: tr('cmd.refresh', '刷新当前页') + ' reload refresh',
      section: tr('cmd.action_section', '动作'),
      action: { kind: 'fn', run: function () { location.reload(); } }
    }];
    // help.js 只挂在 10 个页上 —— PM_Help 不存在就不列这条，不给假入口。
    // ⚠ 方法名是 showModal() 不是 show()：V0.68 版调的是 PM_Help.show()，
    //   而 help.js 导出的是 { showModal, showTour, closeTour, ... }，
    //   从来没有 show() —— 那条帮助命令其实一直是按下去什么都不发生的死命令。
    if (window.PM_Help && typeof window.PM_Help.showModal === 'function') {
      actions.push({
        label: '❓ ' + tr('cmd.help', '使用引导'),
        hint: tr('cmd.help_hint', '重看功能导览'),
        search: tr('cmd.help', '使用引导') + ' help guide',
        section: tr('cmd.action_section', '动作'),
        action: { kind: 'fn', run: function () { window.PM_Help.showModal(); } }
      });
    }
    groups.push({ title: tr('cmd.action_section', '动作'), ico: '⚡', rows: actions });

    // 摊平成条目列表（section 保留在每条上，供过滤与渲染用）
    var all = [];
    for (var g = 0; g < groups.length; g++) {
      for (var r = 0; r < groups[g].rows.length; r++) {
        all.push(groups[g].rows[r]);
      }
    }
    return { groups: groups, all: all };
  }

  // ────────────── 样式 ──────────────

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
      // ⚠ V0.113.0：关闭时必须 visibility:hidden，不能只靠 opacity:0。
      //   opacity:0 的元素**仍在 tab 序列里** —— 键盘用户一进页面 Tab 到的第一个
      //   东西就是这个看不见的搜索框（WCAG 2.4.3 焦点顺序 / 2.4.7 焦点可见）。
      //   实测 18 页里有 16 页能把它聚焦到、而且落在 sticky 顶栏底下，看着像
      //   「点不动」，其实是被透明面板吃掉了。
      //   visibility 参与过渡（离散跳变）所以能配 transition，关闭时淡出结束后
      //   才真正移出 tab 序列。
      '  visibility: hidden; transition: opacity .14s ease, transform .14s ease, visibility .14s ease;',
      '}',
      'body.pm-cmd-open .pm-cmd { opacity: 1; transform: translate(-50%, 0); pointer-events: auto; visibility: visible; }',
      '.pm-cmd-input {',
      '  width: 100%; box-sizing: border-box; padding: 14px 18px;',
      '  font-size: 16px; border: none; border-bottom: 1px solid #e6e8eb;',
      '  outline: none; color: #1f2329; background: #fff;',
      '}',
      '.pm-cmd-list { max-height: 56vh; overflow-y: auto; padding: 6px 0; }',
      // V0.112.0 新增：组头（场景名，不可点）。与条目区分开，别让用户以为能点。
      '.pm-cmd-sec {',
      '  padding: 10px 18px 4px; font-size: 11.5px; font-weight: 600;',
      '  color: #8a919f; letter-spacing: .4px; background: #fafbfc;',
      '  border-top: 1px solid #f0f1f3;',
      '}',
      '.pm-cmd-sec:first-child { border-top: none; }',
      '.pm-cmd-item {',
      '  padding: 10px 18px; cursor: pointer; display: flex;',
      '  justify-content: space-between; gap: 12px; align-items: center;',
      '}',
      '.pm-cmd-item:hover, .pm-cmd-item.pm-cmd-active { background: #f1f3f5; }',
      '.pm-cmd-item .pm-cmd-label { color: #1f2329; font-size: 14.5px; }',
      '.pm-cmd-item .pm-cmd-hint { color: #8a919f; font-size: 12.5px; flex: none; }',
      '.pm-cmd-empty { padding: 20px; text-align: center; color: #8a919f; font-size: 13px; }',
      '.pm-cmd-foot {',
      '  padding: 8px 18px; border-top: 1px solid #e6e8eb; background: #f7f8fa;',
      '  font-size: 12px; color: #8a919f; display: flex; gap: 14px;',
      '}',
      '.pm-cmd-foot kbd {',
      '  background: #fff; border: 1px solid #d6d9dd; border-radius: 4px;',
      '  padding: 1px 6px; font-size: 11px; font-family: inherit;',
      '}',
      // V0.112.0 · 触屏：手机上没有 ⌘K/↑↓/Esc，面板得自己能开也能关、行要够高。
      '@media (pointer: coarse) {',
      '  .pm-cmd { top: 6vh; width: 94vw; }',
      '  .pm-cmd-list { max-height: 70vh; }',
      '  .pm-cmd-input { padding: 14px 16px; font-size: 16px; }',  // ≥16px 防 iOS 聚焦缩放
      '  .pm-cmd-item { padding: 13px 16px; min-height: 44px; }',    // 触摸目标基线
      '}',
      // 深色主题（顶栏是 always-dark，面板跟随文档主题）
      '[data-theme="dark"] .pm-cmd { background: #23272e; box-shadow: 0 12px 40px rgba(0,0,0,.6); }',
      '[data-theme="dark"] .pm-cmd-input { background: #23272e; color: #e6e9ee; border-bottom-color: #3a3f47; }',
      '[data-theme="dark"] .pm-cmd-item .pm-cmd-label { color: #e6e9ee; }',
      '[data-theme="dark"] .pm-cmd-item:hover,',
      '[data-theme="dark"] .pm-cmd-item.pm-cmd-active { background: #2f343c; }',
      '[data-theme="dark"] .pm-cmd-sec { background: #1e2228; color: #9aa3af; border-top-color: #343942; }',
      '[data-theme="dark"] .pm-cmd-foot { background: #1e2228; border-top-color: #343942; }',
      '[data-theme="dark"] .pm-cmd-foot kbd { background: #2f343c; border-color: #454b55; }'
    ].join('\n');
    var el = document.createElement('style');
    el.id = 'cmdPaletteStyle';
    el.textContent = css;
    document.head.appendChild(el);
  }

  // ────────────── DOM ──────────────

  function buildDom() {
    if (document.querySelector('.pm-cmd')) return;

    var mask = document.createElement('div');
    mask.className = 'pm-cmd-mask';
    mask.addEventListener('click', close);
    document.body.appendChild(mask);

    var panel = document.createElement('div');
    panel.className = 'pm-cmd';
    panel.setAttribute('role', 'dialog');
    panel.setAttribute('aria-modal', 'true');
    panel.innerHTML =
      '<input class="pm-cmd-input" placeholder="' + escHtml(tr('cmd.search_placeholder', '搜索页面、动作…')) + '"' +
      ' aria-label="' + escHtml(tr('cmd.search_label', '搜索命令')) + '" />' +
      '<div class="pm-cmd-list" role="listbox" aria-label="' + escHtml(tr('cmd.result_label', '搜索结果')) + '"></div>' +
      '<div class="pm-cmd-foot"></div>';
    document.body.appendChild(panel);

    panel._input = panel.querySelector('.pm-cmd-input');
    panel._list = panel.querySelector('.pm-cmd-list');
    panel._foot = panel.querySelector('.pm-cmd-foot');
    panel._active = 0;
    panel._filtered = [];

    renderFoot(panel);

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

  // 底部提示按输入方式切换：触屏没有 ⌘K / ↑↓ / Esc，显示键盘提示只会让人困惑。
  function isTouch() {
    return !!(window.matchMedia && window.matchMedia('(pointer: coarse)').matches);
  }

  function renderFoot(panel) {
    if (isTouch()) {
      panel._foot.innerHTML =
        '<span>' + escHtml(tr('cmd.kbd_touch', '点条目跳转 · 点遮罩关闭')) + '</span>';
    } else {
      panel._foot.innerHTML =
        '<span><kbd>↑↓</kbd> ' + escHtml(tr('cmd.kbd_select', '选择')) + '</span>' +
        '<span><kbd>Enter</kbd> ' + escHtml(tr('cmd.kbd_run', '执行')) + '</span>' +
        '<span><kbd>Esc</kbd> ' + escHtml(tr('cmd.kbd_close', '关闭')) + '</span>' +
        '<span style="margin-left:auto"><kbd>⌘K</kbd> / <kbd>Ctrl K</kbd></span>';
    }
  }

  // ────────────── 过滤 / 渲染 ──────────────

  function filter(panel, q) {
    q = (q || '').trim().toLowerCase();
    var src = buildCommands();
    var list = src.all;
    if (q) {
      list = src.all.filter(function (c) {
        return ((c.label || '') + ' ' + (c.hint || '') + ' ' + (c.section || ''))
          .toLowerCase()
          .indexOf(q) >= 0;
      });
    }
    panel._src = src;
    panel._filtered = list;
    panel._active = 0;
    render(panel);
    if (q && window.TL) window.TL.track('palette_query', { q_len: q.length });
  }

  function render(panel) {
    var list = panel._filtered;
    var html = '';
    if (!list.length) {
      html = '<div class="pm-cmd-empty">' + escHtml(tr('cmd.empty', '无匹配命令')) + '</div>';
    } else {
      // 同组相邻才渲染组头；过滤后组内只剩 1 条时组头仍要保留（否则用户失去上下文）
      var prevSection = null;
      for (var i = 0; i < list.length; i++) {
        var c = list[i];
        if (c.section !== prevSection) {
          html += '<div class="pm-cmd-sec">' + escHtml(c.section) + '</div>';
          prevSection = c.section;
        }
        var cls = 'pm-cmd-item' + (i === panel._active ? ' pm-cmd-active' : '');
        html += '<div class="' + cls + '" data-idx="' + i + '" role="option">' +
                '<span class="pm-cmd-label">' + escHtml(c.label) + '</span>' +
                '<span class="pm-cmd-hint">' + escHtml(c.hint || '') + '</span>' +
                '</div>';
      }
    }
    panel._list.innerHTML = html;

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
    var active = panel._list.querySelector('.pm-cmd-active');
    // 键盘往下走到折叠区外时把它滚进视野，否则长清单里看着像「没动」
    if (active && active.scrollIntoView) active.scrollIntoView({ block: 'nearest' });
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
    }
  }

  // ⚠ escHtml 必须真转义。V0.68 首版这里写成
  //     { '&': '&', '<': '<', '>': '>', '"': '"', "'": '&#39;' }
  //   —— 前四个映射到自身，是 no-op，含 < 或 & 的标签会原样进 innerHTML。
  //   标签来源（SCENES / i18n 字典）目前可控，但这是转义函数的本职，不该留。
  function escHtml(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return {
        '&': '&amp;',
        '<': '&lt;',
        '>': '&gt;',
        '"': '&quot;',
        "'": '&#39;'
      }[c];
    });
  }

  // ────────────── 开关 ──────────────

  // ⚠ V0.116.3：这里**不能**再用「固定 30ms 后 focus()」。
  //
  // .pm-cmd 的 visibility 带 .14s 过渡 —— 那是 V0.113.0 为了让**关闭态**的面板
  // 真正退出 tab 序列（WCAG 2.4.3 焦点顺序）加的。副作用是：过渡期间计算样式
  // 仍是 visibility:hidden，而 **visibility:hidden 的元素不能接收焦点**
  // ⇒ input.focus() 被浏览器**静默丢弃**：不抛异常、不打日志，面板却已经弹开了。
  // 现象：命令面板打开了，但光标不在搜索框里，直接打字没反应。
  //
  // 实测（scripts/_diag_cmd_focus.mjs，12 次 open/close）：
  //   旧实现（固定 30ms）只有 8/12 次真的落上焦点，剩下 4 次**被静默丢弃**。
  // 注意 buildDom() 在 init() 里就调过（页面加载时已建好面板，open() 里那次
  // 会直接 return）⇒ **每一次 open 都走「已有元素 + visibility 过渡」**，
  // 不存在「首次 open 因为 DOM 是新的所以没有过渡」这种特例 ——
  // 丢不丢焦点纯粹看那 30ms 和「首帧把 visibility 翻成 visible」谁先到。
  // 也就是说 V0.113.0 的无障碍修复**顺手打坏了 V0.68.0 的自动聚焦**，
  // 而唯一察觉的 _verify_mobile.mjs 那条断言还是个 flaky 的固定等待。
  //
  // 正确做法：**等到面板真的可见了再聚焦**，并重试到 activeElement 真的落上去。
  //
  // 重试用**时间**截止而不是帧数：帧率低的机器上 60 帧可能只有 300ms，
  // 遇上被人为拉长的 visibility 过渡就会假红（实现没坏）。
  function focusWhenVisible(panel) {
    if (!panel || !panel._input) return;
    var deadline = performance.now() + 2500;
    function attempt() {
      // 已关闭就别再抢焦点（用户开完立刻 Esc 掉的情况）
      if (!document.body.classList.contains('pm-cmd-open')) return;
      if (getComputedStyle(panel).visibility === 'visible') {
        try { panel._input.focus(); } catch (e) { /* 静默 */ }
        if (document.activeElement === panel._input) return; // 聚焦成功
      }
      if (performance.now() < deadline) requestAnimationFrame(attempt);
    }
    requestAnimationFrame(attempt);
  }

  function open() {
    if (window.TL) window.TL.track('palette_open', {});
    document.body.classList.add('pm-cmd-open');
    buildDom();
    var panel = document.querySelector('.pm-cmd');
    // 惰性派生放在这里而不是 init()：topnav.js 与本脚本都是 defer，
    // 脚本间执行顺序不保证，而 PM_Topnav 在 topnav.js 执行完才有。
    renderFoot(panel);
    panel._input.value = '';
    filter(panel, '');
    focusWhenVisible(panel);
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

  // 换语言时若面板开着就重建 —— 否则译文要等到下次打开才生效
  function installLangWatch() {
    document.addEventListener('i18n:change', function () {
      if (!document.body.classList.contains('pm-cmd-open')) return;
      var panel = document.querySelector('.pm-cmd');
      if (!panel) return;
      renderFoot(panel);
      filter(panel, panel._input.value);
    });
  }

  // 暴露 API
  // COMMANDS（V0.68 的静态数组）已移除 —— 全站无引用（已 grep 确认），
  // 保留它等于留一份会腐化的副本。改为 commands() 按需取当前清单。
  var CP = {
    open: open,
    close: close,
    toggle: toggle,
    commands: buildCommands
  };
  window.PM_CmdPalette = CP;

  function init() {
    injectStyle();
    buildDom();
    installHotkey();
    installLangWatch();
  }
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();