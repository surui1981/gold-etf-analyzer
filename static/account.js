/*!
 * account.js —— 账本切换器（P1 #6 单用户多账本，V0.62.0）
 *
 * 全站共享，零依赖。用法：
 *   1) 页面 <body> 末尾（页面自身脚本之前）引入：
 *        <script src="/static/account.js"></script>
 *   2) 自动在 .topnav 内注入下拉框（无需改 HTML 结构）；
 *   3) 页面脚本按需使用：
 *        await Acc.ready;                       // 账本清单已就绪
 *        fetch(Acc.url('/api/v1/positions'));   // 自动追加 ?account_id=N（"全部账本"时不追加）
 *        Acc.onReady(() => reload());           // 就绪后回调（含首次加载）
 *        document.addEventListener('account-changed', e => reload());  // 用户切换
 *   4) localStorage 记忆选择（key: gold_account_id）。
 *
 * 语义约定：
 *   - "全部账本"（value ""）→ 合并视图，url() 不追加参数，后端按全部账本聚合；
 *   - 开仓 / 加仓等**写入**场景用 Acc.targetAccountId()：合并视图下落到默认账本，
 *     避免「看着合并视图下单，持仓却不知道进了哪个账本」。
 */
(function () {
  'use strict';

  var STORE_KEY = 'gold_account_id';
  var API = '/api/v1/accounts';
  var ALL = ''; // "全部账本"的取值

  var state = {
    accounts: [],
    defaultId: '',
    current: null, // string，'' 表示全部
    loaded: false
  };

  var readyResolve;
  var readyPromise = new Promise(function (resolve) { readyResolve = resolve; });
  var readyCallbacks = [];

  /* ─────────────── 样式（自注入，避免改动 5 个页面各自的 CSS） ─────────────── */
  function injectStyle() {
    if (document.getElementById('accStyle')) return;
    var css = [
      '.topnav .acc-wrap{display:flex;align-items:center;gap:6px;margin-left:auto;}',
      '.topnav select.acc-sel{background:#2b3038;color:#f5d97a;border:1px solid rgba(245,217,122,.35);',
      '  border-radius:8px;padding:5px 8px;font-size:13px;max-width:190px;cursor:pointer;}',
      '.topnav select.acc-sel:hover{border-color:rgba(245,217,122,.65);}',
      '.topnav .acc-btn{background:rgba(255,255,255,.1);color:#d6d9dd;border:1px solid rgba(255,255,255,.15);',
      '  border-radius:8px;padding:5px 10px;font-size:12.5px;cursor:pointer;white-space:nowrap;}',
      '.topnav .acc-btn:hover{background:rgba(255,255,255,.2);color:#fff;}',
      '.topnav .acc-sum{font-size:12px;color:#9aa0a6;white-space:nowrap;}'
    ].join('\n');
    var el = document.createElement('style');
    el.id = 'accStyle';
    el.textContent = css;
    document.head.appendChild(el);
  }

  /* ─────────────── 渲染 ─────────────── */
  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }

  function buildBar() {
    var nav = document.querySelector('.topnav');
    if (!nav) return null;
    var wrap = nav.querySelector('.acc-wrap');
    if (wrap) return wrap;

    wrap = document.createElement('div');
    wrap.className = 'acc-wrap';

    var sel = document.createElement('select');
    sel.className = 'acc-sel';
    sel.id = 'accountSelect';
    sel.title = '切换账本：持仓、流水、收益曲线与决策均按所选账本统计';
    sel.addEventListener('change', function () {
      state.current = sel.value;
      try { localStorage.setItem(STORE_KEY, sel.value); } catch (e) { /* 隐私模式忽略 */ }
      render();
      document.dispatchEvent(new CustomEvent('account-changed', {
        detail: { accountId: sel.value, isAll: sel.value === ALL, name: accountName(sel.value) }
      }));
    });

    var sum = document.createElement('span');
    sum.className = 'acc-sum';
    sum.id = 'accountSummary';

    wrap.appendChild(sel);
    wrap.appendChild(sum);
    nav.appendChild(wrap);
    return wrap;
  }

  function render() {
    var sel = document.getElementById('accountSelect');
    if (!sel) return;
    var opts = ['<option value="">全部账本（合并）</option>'];
    state.accounts.forEach(function (a) {
      var n = a.stats ? a.stats.open_count : 0;
      var tag = a.is_default ? '（默认）' : '';
      opts.push('<option value="' + esc(a.id) + '">' + esc(a.name) + tag +
        (n ? ' · 持仓' + n : '') + '</option>');
    });
    sel.innerHTML = opts.join('');
    sel.value = state.current == null ? state.defaultId : state.current;

    var sum = document.getElementById('accountSummary');
    if (sum) {
      if (state.current === ALL) {
        var total = state.accounts.reduce(function (acc, a) {
          return acc + ((a.stats && a.stats.open_count) || 0);
        }, 0);
        sum.textContent = total ? '合并 ' + state.accounts.length + ' 个账本 · ' + total + ' 笔持仓' : '';
      } else {
        var cur = state.accounts.filter(function (a) { return String(a.id) === state.current; })[0];
        sum.textContent = cur && cur.stats ? (cur.stats.trade_count + ' 笔流水') : '';
      }
    }
  }

  function accountName(id) {
    if (id === ALL || id == null || id === '') return '全部账本';
    var hit = state.accounts.filter(function (a) { return String(a.id) === String(id); })[0];
    return hit ? hit.name : ('账本 ' + id);
  }

  /* ─────────────── 加载 ─────────────── */
  function load() {
    return fetch(API, { headers: { Accept: 'application/json' } })
      .then(function (r) {
        if (!r.ok) throw new Error('HTTP ' + r.status);
        return r.json();
      })
      .then(function (data) {
        state.accounts = (data.items || []);
        state.defaultId = String(data.current_account_id || '');
      })
      .catch(function () {
        state.accounts = [];
        state.defaultId = '';
      })
      .then(function () {
        var stored = null;
        try { stored = localStorage.getItem(STORE_KEY); } catch (e) { stored = null; }
        var known = state.accounts.map(function (a) { return String(a.id); });
        if (stored === ALL) {
          state.current = ALL; // 用户显式选择过"全部账本"
        } else if (stored && known.indexOf(stored) >= 0) {
          state.current = stored;
        } else {
          state.current = state.defaultId || ALL;
        }
        state.loaded = true;
        injectStyle();
        buildBar();
        render();
        readyCallbacks.forEach(function (fn) {
          try { fn(state); } catch (e) { console.error(e); }
        });
        readyCallbacks = [];
        readyResolve(state);
        return state;
      });
  }

  /* ─────────────── 对外 API ─────────────── */
  var Acc = {
    ready: readyPromise,
    ALL: ALL,

    /** 账本清单（已剔除归档账本） */
    list: function () { return state.accounts.slice(); },

    /** 默认账本 ID（字符串） */
    defaultAccountId: function () { return state.defaultId; },

    /** 当前选中值：'' = 全部账本 */
    currentId: function () { return state.current == null ? state.defaultId : state.current; },

    isAll: function () { return Acc.currentId() === ALL; },

    /** 写入场景的落点：合并视图下用默认账本 */
    targetAccountId: function () {
      var cur = Acc.currentId();
      return cur && cur !== ALL ? cur : state.defaultId;
    },

    accountName: accountName,

    /** 给 URL 追加当前账本参数（"全部账本"时原样返回） */
    url: function (path) {
      var cur = Acc.currentId();
      if (!cur || cur === ALL) return path;
      return path + (path.indexOf('?') >= 0 ? '&' : '?') + 'account_id=' + encodeURIComponent(cur);
    },

    /** 就绪回调（已就绪则立即执行），返回卸载函数 */
    onReady: function (fn) {
      if (state.loaded) { fn(state); return function () {}; }
      readyCallbacks.push(fn);
      return function () {
        var i = readyCallbacks.indexOf(fn);
        if (i >= 0) readyCallbacks.splice(i, 1);
      };
    },

    /** 手动刷新账本清单（新建/归档账本后调用） */
    reload: load
  };

  window.Acc = Acc;

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', load);
  } else {
    load();
  }
})();
