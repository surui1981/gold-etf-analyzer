/*!
 * nav-drawer.js —— 顶栏汉堡抽屉（V0.68.0）
 *
 * 用法：<script src="/static/nav-drawer.js" defer></script>
 *
 * 行为：
 * - 桌面端（≥769px）：保持横排显示，无副作用
 * - 移动端（≤768px）：在 .topnav 注入汉堡按钮 + 抽屉；点击展开 .links
 * - 点击链接 / 点击遮罩 / Esc / 路由跳转后自动关闭
 * - 抽屉开关触发 TL.track('nav_drawer_open' / 'nav_drawer_select')
 *
 * 设计：纯原生（无 framework），复用现 .topnav 结构，不改 HTML
 */
(function () {
  'use strict';

  var MQ = '(max-width: 768px)';
  var STATE_OPEN = 'pmNavDrawerOpen';

  function injectStyle() {
    if (document.getElementById('navDrawerStyle')) return;
    var css = [
      '@media ' + MQ + ' {',
      '  .topnav { flex-wrap: nowrap !important; }',
      '  .topnav .links {',
      '    display: none !important;',
      '  }',
      '  .topnav .nav-toggle {',
      '    display: inline-flex !important;',
      '  }',
      '  body.pm-drawer-open { overflow: hidden; }',
      '  body.pm-drawer-open .pm-drawer {',
      '    transform: translateX(0);',
      '  }',
      '  body.pm-drawer-open .pm-drawer-mask {',
      '    opacity: 1; pointer-events: auto;',
      '  }',
      '}',
      '.topnav .nav-toggle {',
      '  display: none;',
      '  align-items: center; justify-content: center;',
      '  background: rgba(255,255,255,.1); color: #d6d9dd;',
      '  border: 1px solid rgba(255,255,255,.18); border-radius: 8px;',
      '  width: 36px; height: 36px; font-size: 18px; cursor: pointer;',
      '  margin-left: 4px; padding: 0; line-height: 1;',
      '}',
      '.topnav .nav-toggle:hover { background: rgba(255,255,255,.2); color: #fff; }',
      '.pm-drawer-mask {',
      '  position: fixed; inset: 0; background: rgba(0,0,0,.45);',
      '  opacity: 0; pointer-events: none; transition: opacity .18s ease;',
      '  z-index: 200;',
      '}',
      '.pm-drawer {',
      '  position: fixed; top: 0; right: 0; bottom: 0;',
      '  width: 280px; max-width: 80vw; background: #1f2329;',
      '  box-shadow: -4px 0 12px rgba(0,0,0,.3);',
      '  transform: translateX(100%); transition: transform .22s ease;',
      '  z-index: 201; padding: 16px; overflow-y: auto;',
      '}',
      '.pm-drawer .pm-drawer-title {',
      '  color: #f5d97a; font-weight: 700; font-size: 15px;',
      '  margin-bottom: 12px; padding-bottom: 8px;',
      '  border-bottom: 1px solid rgba(255,255,255,.1);',
      '}',
      '.pm-drawer .pm-drawer-links { display: flex; flex-direction: column; gap: 4px; }',
      '.pm-drawer .pm-drawer-links a {',
      '  color: #d6d9dd; text-decoration: none;',
      '  padding: 12px 14px; border-radius: 8px; font-size: 14px;',
      '}',
      '.pm-drawer .pm-drawer-links a:hover { background: rgba(255,255,255,.1); color: #fff; }',
      '.pm-drawer .pm-drawer-links a.active {',
      '  background: #c9a227; color: #1f2329; font-weight: 600;',
      '}',
      '.pm-drawer .pm-drawer-hint {',
      '  margin-top: 16px; padding-top: 12px;',
      '  border-top: 1px solid rgba(255,255,255,.1);',
      '  font-size: 12px; color: #9aa0a6;',
      '}'
    ].join('\n');
    var el = document.createElement('style');
    el.id = 'navDrawerStyle';
    el.textContent = css;
    document.head.appendChild(el);
  }

  function open() {
    document.body.classList.add('pm-drawer-open');
    try { sessionStorage.setItem(STATE_OPEN, '1'); } catch (e) { /* 静默 */ }
    if (window.TL) window.TL.track('nav_drawer_open', {});
  }

  function close() {
    document.body.classList.remove('pm-drawer-open');
    try { sessionStorage.removeItem(STATE_OPEN); } catch (e) { /* 静默 */ }
  }

  function toggle() {
    if (document.body.classList.contains('pm-drawer-open')) close();
    else open();
  }

  function build() {
    var nav = document.querySelector('.topnav');
    var linksEl = nav && nav.querySelector('.links');
    if (!nav || !linksEl) return;

    // 1. 汉堡按钮
    if (!nav.querySelector('.nav-toggle')) {
      var btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'nav-toggle';
      btn.setAttribute('aria-label', '打开导航菜单');
      btn.title = '导航菜单';
      btn.innerHTML = '☰';
      btn.addEventListener('click', toggle);
      // 紧贴品牌右侧（在 .links 之前）
      nav.insertBefore(btn, linksEl);
    }

    // 2. 抽屉 + 遮罩
    if (!document.querySelector('.pm-drawer')) {
      var mask = document.createElement('div');
      mask.className = 'pm-drawer-mask';
      mask.addEventListener('click', close);
      document.body.appendChild(mask);

      var drawer = document.createElement('aside');
      drawer.className = 'pm-drawer';
      drawer.setAttribute('aria-label', '主导航');
      var brand = nav.querySelector('.brand');
      var brandText = brand ? brand.textContent.trim() : '导航';

      // 拷贝 .links 的所有 a
      var linkHtml = '';
      var links = linksEl.querySelectorAll('a');
      for (var i = 0; i < links.length; i++) {
        var a = links[i];
        var cls = a.className;
        var href = a.getAttribute('href');
        var txt = a.textContent;
        linkHtml += '<a href="' + href + '" class="' + cls + '">' + txt + '</a>';
      }

      drawer.innerHTML =
        '<div class="pm-drawer-title">' + brandText + '</div>' +
        '<nav class="pm-drawer-links">' + linkHtml + '</nav>' +
        '<div class="pm-drawer-hint">⌘K / Ctrl+K 全局搜索</div>';
      document.body.appendChild(drawer);

      // 点击抽屉里的链接：埋点 + 关闭（跳转是浏览器默认行为）
      var drawerLinks = drawer.querySelectorAll('a');
      for (var k = 0; k < drawerLinks.length; k++) {
        drawerLinks[k].addEventListener('click', function (e) {
          if (window.TL) {
            window.TL.track('nav_drawer_select', {
              href: this.getAttribute('href') || '',
              label: (this.textContent || '').slice(0, 30)
            });
          }
          close();
        });
      }
    }

    // 3. Esc 关闭
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape' && document.body.classList.contains('pm-drawer-open')) close();
    });
  }

  // 暴露 API（供命令面板 / 测试调用）
  var ND = { open: open, close: close, toggle: toggle, build: build };
  window.PM_NavDrawer = ND;

  function init() {
    injectStyle();
    build();
  }
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
