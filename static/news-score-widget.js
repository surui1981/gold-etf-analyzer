/*!
 * news-score-widget.js —— 首页内嵌「消息面打分 · 客户评价」（V0.76.0）
 *
 * 背景：消息面占当日综合评估指数 30% 权重，但 V0.75.1 收敛「今日操作清单」后，
 * 首页只剩 `#newsFactor` 一行**只读**展示，打分入口无处可去 —— 用户必须跳到
 * `/news` 才能记录一次判断。首页是每日必看的落地页，为了打一次分而整页跳转，
 * 是本页最大的易用性缺口。本组件把打分能力**内联**到首页，保存后即时刷新
 * 上方「综合研判结论卡」，全程不跳页。
 *
 * 公开 API：`window.PM_NewsScore = { mount, load, openSlot, getState }`
 *
 * 设计要点（改这块前务必先读）
 * ----------------------------
 * 1. **口径同源**：分值方向阈值（>55 看多 / <45 看空）与当日有效分值 1:2:3 加权
 *    **一律取后端**（`services.news.aggregate_slots`，与 `/news`、复盘页同源）。
 *    本组件只做展示与提交，绝不在前端重算加权。返回体里的 `formula` 是后端给的
 *    可读算式，直接显示即可。
 *
 * 2. **⚠️ 修改既有槽位时必须回填 `notes` / `basis`，否则被静默清空**：
 *    写接口是**全量 upsert**，仓库层 UPDATE 分支对这两项是**硬覆盖**
 *    （`repositories/news.py::upsert` 中 `existing.notes = notes`、
 *    `existing.basis = basis`）→ 「只改分值、不带 notes/basis」的请求会把用户
 *    此前在 `/news` 写下的研判备注与依据标签**无声抹掉**（2026-09-30 实测确认：
 *    写入 notes='KEEP-NOTES' basis=['美元指数'] 后发一次不带这两项的 PUT，
 *    回读二者分别变成 '' 与 []）。
 *    因此 `openSlot()` 载入既有槽位时必须把 `notes / basis / review_note` 全部
 *    回填进编辑器，`save()` 再原样回传。
 *
 *    ⚠️ 同一处还有个**反直觉的不对称**，别照直觉改：`review_note` 那一行写的是
 *    `existing.review_note = review_note or existing.review_note`（空值保留旧值，
 *    注释「复盘批注可就地补充，不必重打分数」）→ **空字符串清不掉既有批注**。
 *    仍回填它是为了让用户在框里看到真值；但**不要**把它当成「可清空」字段，
 *    也别据此断言「清空保存后会变空」—— 真要支持清空，得先改仓库层的 `or` 语义。
 *
 * 3. **不轮询**（与 PM_Synthesis 的 60s 轮询不同）：
 *    打分器带可拖拽滑杆与文本框，定时重渲染会**打断正在进行的输入**（滑杆跳回、
 *    光标丢失）。分值只会因"有人提交"而变化，本组件在提交后自行重渲染即可；
 *    只读的 `#newsFactor` 由首页既有的 60s 轮询保持新鲜。
 *
 * 4. **i18n 兜底**：`T(key, zh)` 在字典缺 key 时回退中文，绝不把 key 字面量
 *    渲染到页面上（V0.75.0 曾因悬空 key 把页脚中文静默替换成 `warn.data_source`）。
 *
 * 5. **主题自适应**：自注入 `<style>`（照 synthesis-card.js 的做法，省一次请求），
 *    颜色一律走 `--up / --down / --muted / --accent / --border / --card` 等变量，
 *    4 套主题（light / dark / auto / hc）无需额外覆盖。方向徽标用
 *    `border: 1px solid currentColor` + 语义色文字，避免 hc 模式下"实心底色 + 白字"
 *    对比度不足的问题。
 *
 * 6. 红涨绿跌口径：`--up` 红 = 看多/利多，`--down` 绿 = 看空/利空。
 */
(function () {
  'use strict';

  var DEFAULT_CONTAINER = 'newsScoreCard';
  var ABS_BASE = 'http://127.0.0.1:8888';
  var NEWS_PATH = '/api/v1/news-score';
  var META_PATH = '/api/v1/review/meta';
  var FETCH_TIMEOUT_MS = 20000;
  var MAX_SLOTS = 3;
  var FALLBACK_BASIS = ['美元指数', '美债收益率', '实际利率', '央行购金', '地缘风险', '技术面'];

  /* 方向阈值必须与后端一致（services/news.py::direction_of）：
     >55 看多（利多黄金，红）/ <45 看空（利空黄金，绿）/ 其间中性。 */
  var UP_COLOR = 'var(--up)';
  var DOWN_COLOR = 'var(--down)';
  var NEUTRAL_COLOR = 'var(--muted)';

  /* JS 字符串里拼 HTML 时无法用 data-i18n 属性，统一走 T(key, 中文兜底)。 */

  var state = {
    container: null,
    containerId: DEFAULT_CONTAINER,
    today: null,          // GET /news-score 的最新返回体
    editSlot: 1,          // 编辑器当前目标槽位
    loadedSlot: null,     // 已回填进编辑器的槽位（避免重复回填打断拖动）
    selectedBasis: null,  // Set<string>
    basisOptions: [],
    inflight: false,      // 防重入
    bound: false
  };

  /* ─────────────── 工具 ─────────────── */

  function apiBase() {
    /* 与 trend.html 同口径：同源 8888 直开用相对路径；跨源（如预览通道）走绝对地址，
       否则 fetch 根相对路径会打到错误端口。 */
    return location.port === '8888' ? '' : ABS_BASE;
  }

  function T(key, fallback, params) {
    try {
      if (window.I18n && typeof window.I18n.t === 'function') {
        var v = window.I18n.t(key, params);
        if (typeof v === 'string' && v !== '' && v !== key) return v;
      }
    } catch (e) { /* 字典未就绪 → 用兜底 */ }
    if (params && typeof fallback === 'string') {
      return fallback.replace(/\{(\w+)\}/g, function (_m, k) {
        return params[k] != null ? String(params[k]) : ('{' + k + '}');
      });
    }
    return fallback;
  }

  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c];
    });
  }

  function dirOf(v) { return v > 55 ? 'bullish' : v < 45 ? 'bearish' : 'neutral'; }

  function dirColor(d) {
    return d === 'bullish' ? UP_COLOR : d === 'bearish' ? DOWN_COLOR : NEUTRAL_COLOR;
  }

  function dirTxt(d) {
    if (d === 'bullish') return T('nsw.dir_up', '看多展望（利多黄金）');
    if (d === 'bearish') return T('nsw.dir_down', '看空展望（利空黄金）');
    return T('nsw.dir_neutral', '中性展望');
  }

  function fmtTime(iso) {
    if (!iso) return '—';
    var d = new Date(iso);
    if (isNaN(d.getTime())) return '—';
    var p = function (n) { return String(n).padStart(2, '0'); };
    return p(d.getMonth() + 1) + '-' + p(d.getDate()) + ' ' + p(d.getHours()) + ':' + p(d.getMinutes());
  }

  function num(v, digits) {
    var n = Number(v);
    return isNaN(n) ? '—' : n.toFixed(digits == null ? 1 : digits);
  }

  async function fetchJSON(url, init) {
    var ctrl = new AbortController();
    var timer = setTimeout(function () { ctrl.abort(); }, FETCH_TIMEOUT_MS);
    try {
      var opts = Object.assign({ signal: ctrl.signal }, init || {});
      var resp = await fetch(url, opts);
      if (!resp.ok) {
        var msg = 'HTTP ' + resp.status;
        try {
          var body = await resp.json();
          if (body && body.detail) {
            msg = typeof body.detail === 'string' ? body.detail : (body.detail.message || msg);
          }
        } catch (e) { /* 非 JSON 错误体 → 保留 HTTP 状态码 */ }
        throw new Error(msg);
      }
      return await resp.json();
    } finally {
      clearTimeout(timer);
    }
  }

  function track(name, extra) {
    try {
      if (window.TL && typeof window.TL.track === 'function') {
        window.TL.track(name, Object.assign({ url: location.pathname }, extra || {}));
      }
    } catch (e) { /* 埋点失败不影响功能 */ }
  }

  function bySlot(n) {
    if (!state.today || !state.today.slots) return null;
    for (var i = 0; i < state.today.slots.length; i++) {
      if (state.today.slots[i].slot === n) return state.today.slots[i];
    }
    return null;
  }

  function el(id) { return document.getElementById(id); }

  /* ─────────────── 样式（自注入，作用域 .nsw-* 前缀） ─────────────── */

  var CSS = [
    '.nsw-head { display: flex; align-items: baseline; justify-content: space-between;',
    '  gap: 10px; flex-wrap: wrap; margin-bottom: 4px; }',
    '.nsw-title { font-size: 15px; font-weight: 600; }',
    '.nsw-tag { font-size: 11.5px; font-weight: 600; padding: 2px 10px; border-radius: 999px;',
    '  border: 1px solid var(--border); color: var(--muted); white-space: nowrap; }',
    '.nsw-sub { font-size: 12px; color: var(--muted); line-height: 1.7; margin-bottom: 10px; }',
    /* 当日有效分值 */
    '.nsw-eff { display: flex; align-items: center; gap: 20px; flex-wrap: wrap;',
    '  border: 1px solid var(--border); border-radius: 10px; padding: 12px 16px; margin-bottom: 10px; }',
    '.nsw-eff .n { font-size: 36px; font-weight: 800; line-height: 1; min-width: 96px; }',
    '.nsw-eff .l { font-size: 11px; color: var(--muted); margin-top: 4px; }',
    '.nsw-eff-meta { flex: 1; min-width: 220px; }',
    '.nsw-formula { font-size: 11.5px; color: var(--muted); margin-top: 6px;',
    '  font-family: ui-monospace, Consolas, monospace; word-break: break-all; }',
    '.nsw-prog { display: flex; gap: 6px; margin-top: 8px; max-width: 260px; }',
    '.nsw-prog span { flex: 1; height: 6px; border-radius: 999px; background: var(--border); }',
    '.nsw-prog span.on { background: var(--accent); }',
    '.nsw-hint { font-size: 11.5px; color: var(--muted); margin-top: 7px; line-height: 1.6; }',
    /* 方向徽标：文字与描边同色 → 4 主题自动适配，无对比度风险 */
    '.nsw-pill { display: inline-block; padding: 1px 10px; border-radius: 999px;',
    '  font-size: 11.5px; font-weight: 600; border: 1px solid currentColor; }',
    /* 槽位卡 */
    '.nsw-slots { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));',
    '  gap: 10px; margin-bottom: 12px; }',
    '.nsw-slot { border: 1px solid var(--border); border-radius: 10px; padding: 10px 12px; }',
    '.nsw-slot.filled { border-color: var(--accent); }',
    '.nsw-slot.editing { box-shadow: 0 0 0 2px var(--focus-ring); }',
    '.nsw-slot .hd { display: flex; justify-content: space-between; align-items: center; gap: 8px; }',
    '.nsw-slot .nm { font-size: 12.5px; font-weight: 700; }',
    '.nsw-slot .wt { font-size: 11px; color: var(--muted); }',
    '.nsw-slot .sc { font-size: 24px; font-weight: 800; margin: 5px 0 3px; }',
    '.nsw-slot .tm { font-size: 11px; color: var(--muted); margin-top: 5px; }',
    '.nsw-slot .nt { font-size: 11.5px; color: var(--muted); margin-top: 5px; line-height: 1.6;',
    '  max-height: 44px; overflow: hidden; }',
    '.nsw-slot .empty { font-size: 12px; color: var(--muted); margin: 6px 0; }',
    '.nsw-slot .ops { margin-top: 8px; display: flex; gap: 6px; flex-wrap: wrap; }',
    /* 编辑器 */
    '.nsw-editor { border-top: 1px dashed var(--border); padding-top: 12px; }',
    '.nsw-editor-title { font-size: 13px; font-weight: 600; margin-bottom: 2px; }',
    '.nsw-desc { font-size: 11.5px; color: var(--muted); line-height: 1.7; margin-bottom: 8px; }',
    '.nsw-range-row { display: flex; align-items: center; gap: 12px; margin: 10px 0 6px; }',
    '.nsw-range-row .cap { font-size: 12px; color: var(--muted); white-space: nowrap; }',
    '.nsw-range-row input[type=range] { flex: 1; min-width: 120px; accent-color: var(--accent); height: 8px; }',
    '.nsw-range-row .v { font-size: 24px; font-weight: 700; width: 62px; text-align: center; }',
    '.nsw-gauge { position: relative; height: 10px; border-radius: 999px; margin: 2px 0 3px;',
    '  background: linear-gradient(90deg, var(--down), var(--muted) 50%, var(--up)); }',
    '.nsw-gauge i { position: absolute; top: -4px; width: 3px; height: 18px;',
    '  background: var(--text); border-radius: 2px; transform: translateX(-50%); }',
    '.nsw-markers { display: flex; justify-content: space-between; font-size: 11px; color: var(--muted); }',
    '.nsw-row { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; margin-top: 10px; }',
    '.nsw-row .cap { font-size: 12px; color: var(--muted); }',
    /* 按钮 / 标签 */
    '.nsw-btn { font: inherit; font-size: 12.5px; font-weight: 500; padding: 6px 14px;',
    '  border-radius: 8px; border: 1px solid var(--border); background: transparent;',
    '  color: var(--text); cursor: pointer; }',
    '.nsw-btn:hover:not(:disabled) { border-color: var(--accent); }',
    '.nsw-btn:disabled { opacity: .55; cursor: not-allowed; }',
    '.nsw-btn.primary { background: var(--text); color: var(--bg); border-color: var(--text); }',
    '.nsw-btn.primary:hover:not(:disabled) { opacity: .88; border-color: var(--text); }',
    '.nsw-btn.on { background: var(--accent); color: var(--bg); border-color: var(--accent); font-weight: 600; }',
    '.nsw-btn:focus-visible { outline: 3px solid var(--focus-ring); outline-offset: 2px; }',
    '.nsw-basis { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 6px; }',
    '.nsw-ta { width: 100%; box-sizing: border-box; font: inherit; font-size: 12.5px;',
    '  line-height: 1.6; padding: 8px 10px; border-radius: 8px; border: 1px solid var(--border);',
    '  background: var(--card); color: var(--text); resize: vertical; min-height: 56px;',
    '  margin-top: 6px; }',
    '.nsw-ta:focus-visible { outline: 3px solid var(--focus-ring); outline-offset: 1px; }',
    '.nsw-acts { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; margin-top: 12px; }',
    '.nsw-link { font-size: 12.5px; color: var(--accent); text-decoration: none; }',
    '.nsw-link:hover { text-decoration: underline; }',
    '.nsw-msg { margin-top: 8px; font-size: 12.5px; min-height: 18px; line-height: 1.6; }',
    '.nsw-msg.ok { color: var(--down); }',
    '.nsw-msg.err { color: var(--up); font-weight: 600; }',
    '.nsw-alert { font-size: 12px; line-height: 1.65; padding: 8px 12px; border-radius: 8px;',
    '  border: 1px solid var(--border); margin-bottom: 10px; color: var(--text); }',
    '.nsw-alert.warn { border-color: var(--chip-warn-bd); background: var(--chip-warn-bg); color: var(--chip-warn-fg); }',
    '.nsw-alert.info { border-color: var(--chip-delay-bd); background: var(--chip-delay-bg); color: var(--chip-delay-fg); }',
    '.nsw-alert.ok { border-color: var(--chip-ok-bd); background: var(--chip-ok-bg); color: var(--chip-ok-fg); }',
    '.nsw-loading { color: var(--muted); font-size: 13px; }',
    '.nsw-error { color: var(--up); font-size: 13px; font-weight: 600; }'
  ].join('\n');

  /* ─────────────── 渲染 ─────────────── */

  function meta() {
    var d = state.today || {};
    var used = d.used_slots == null ? 0 : d.used_slots;
    var max = d.max_slots == null ? MAX_SLOTS : d.max_slots;
    var remaining = d.remaining_slots == null ? Math.max(0, max - used) : d.remaining_slots;
    return { used: used, max: max, remaining: remaining, scored: !!d.scored };
  }

  function hintLine() {
    var m = meta();
    if (!m.scored) {
      return { cls: 'info', html: T('nsw.hint_none', '尚未打分，当前按 <b>中性 50</b> 参与评估（占综合指数 30%）。今日还有 <b>3</b> 次机会。') };
    }
    if (m.remaining > 0) {
      return {
        cls: 'info',
        html: T('nsw.hint_partial', '今日已打分 <b>{u}</b> 次，还有 <b>{r}</b> 次机会。越晚的一次权重越高（1:2:3），对当日指数影响越大。', { u: m.used, r: m.remaining })
      };
    }
    return { cls: 'ok', html: T('nsw.hint_full', '今日 <b>3</b> 次机会已用完，已按 1:2:3 加权汇入综合评估。如需修正，点对应槽位的「修改」。') };
  }

  function slotCard(n) {
    var s = bySlot(n);
    var editing = state.editSlot === n ? ' editing' : '';
    if (!s) {
      return '<div class="nsw-slot' + editing + '">' +
        '<div class="hd"><span class="nm">' + T('nsw.slot_n', '第 {n} 次', { n: n }) + '</span>' +
        '<span class="wt">' + T('nsw.weight', '权重 {w}', { w: n }) + '</span></div>' +
        '<div class="empty">' + T('nsw.not_scored', '未打分') + '</div>' +
        '<div class="ops"><button type="button" class="nsw-btn" data-act="edit" data-slot="' + n + '">' +
        T('nsw.do_score_n', '打第 {n} 次', { n: n }) + '</button></div></div>';
    }
    var backfilled = s.backfilled ? ' <span class="nsw-pill" style="color:var(--muted)">' + T('nsw.backfilled', '补录') + '</span>' : '';
    return '<div class="nsw-slot filled' + editing + '">' +
      '<div class="hd"><span class="nm">' + T('nsw.slot_n', '第 {n} 次', { n: s.slot }) + '</span>' +
      '<span class="wt">' + T('nsw.weight', '权重 {w}', { w: s.weight }) + '</span></div>' +
      '<div class="sc" style="color:' + dirColor(s.direction) + '">' + num(s.score) + '</div>' +
      '<div><span class="nsw-pill" style="color:' + dirColor(s.direction) + '">' + esc(dirTxt(s.direction)) + '</span>' + backfilled + '</div>' +
      '<div class="tm">' + T('nsw.submitted_at', '提交于 {t}', { t: esc(fmtTime(s.scored_at)) }) + '</div>' +
      (s.notes ? '<div class="nt">' + esc(s.notes) + '</div>' : '') +
      '<div class="ops">' +
      '<button type="button" class="nsw-btn" data-act="edit" data-slot="' + s.slot + '">' + T('nsw.modify', '修改') + '</button>' +
      '<button type="button" class="nsw-btn" data-act="del" data-slot="' + s.slot + '">' + T('nsw.revoke', '撤销') + '</button>' +
      '</div></div>';
  }

  function editTargetLabel() {
    var s = bySlot(state.editSlot);
    var base = T('nsw.editor_title', '📝 第 {n} 次打分（权重 {w}）', { n: state.editSlot, w: state.editSlot });
    return s ? base + ' · ' + T('nsw.editing', '修改') : base;
  }

  function render() {
    var card = state.container;
    if (!card) return;
    if (!state.today) { card.innerHTML = '<div class="nsw-loading">' + T('nsw.loading', '消息面打分加载中…') + '</div>'; return; }

    var d = state.today;
    var m = meta();
    var hint = hintLine();
    var over = !m.scored ? NEUTRAL_COLOR : dirColor(d.direction);

    var tagHtml = m.scored
      ? T('nsw.tag_scored', '今日已打 {u}/{max} 次 · 有效 {v}', { u: m.used, max: m.max, v: num(d.score) })
      : T('nsw.tag_unscored', '今日未打分（中性 50）');

    var byS = bySlot(state.editSlot);
    var saveLabel = byS
      ? T('nsw.btn_update', '💾 更新第 {n} 次打分', { n: state.editSlot })
      : T('nsw.btn_save', '💾 保存第 {n} 次打分', { n: state.editSlot });

    var reuseHtml = '';
    if (d.last_score != null) {
      reuseHtml = '<button type="button" class="nsw-btn" data-act="reuse">' +
        T('nsw.reuse', '沿用上次（{d}：{v}）', { d: esc(d.last_date || '—'), v: Math.round(d.last_score) }) + '</button>';
    }

    var slotsHtml = '';
    for (var n = 1; n <= MAX_SLOTS; n++) slotsHtml += slotCard(n);

    card.innerHTML =
      '<div class="nsw-head">' +
        '<div class="nsw-title">' + T('nsw.title', '✍️ 今日消息面打分 · 客户评价') + '</div>' +
        '<span class="nsw-tag">' + tagHtml + '</span>' +
      '</div>' +
      '<div class="nsw-sub">' + T('nsw.sub', '综合主流财经网站投行黄金展望后打分：<b>50 中性</b> ｜ &gt;55 看多（利多黄金） ｜ &lt;45 看空（利空黄金）。每日 3 次机会，越晚一次权重越高。') + '</div>' +

      '<div class="nsw-alert ' + hint.cls + '">' + hint.html + '</div>' +

      '<div class="nsw-eff">' +
        '<div><div class="n">' + (m.scored ? num(d.score) : '50.0') + '</div>' +
        '<div class="l" style="color:' + over + '">' +
          (m.scored ? esc(dirTxt(d.direction)) : T('nsw.neutral_default', '中性参考（未打分）')) +
        '</div></div>' +
        '<div class="nsw-eff-meta">' +
          '<div style="font-size:12px;color:var(--muted)">' + T('nsw.eff_label', '当日有效消息面分值（占综合指数 30%）') + '</div>' +
          '<div class="nsw-formula">' + (d.formula
            ? esc(T('nsw.formula', '加权口径：{f} = {v}', { f: d.formula, v: num(d.score) }))
            : esc(d.scored ? T('nsw.formula_single', '仅 1 次打分，直接采用该次分值')
                           : T('nsw.formula_none', '尚未打分，按中性 50 参与评估'))) + '</div>' +
          '<div class="nsw-prog">' + [1, 2, 3].map(function (k) {
            return '<span class="' + (k <= m.used ? 'on' : '') + '"></span>';
          }).join('') + '</div>' +
          '<div class="nsw-hint">' + T('nsw.prog_label', '已用 {u}/{max} 次机会（第 1/2/3 次权重 1:2:3）', { u: m.used, max: m.max }) + '</div>' +
        '</div>' +
      '</div>' +

      '<div class="nsw-slots">' + slotsHtml + '</div>' +

      '<div class="nsw-editor">' +
        '<div class="nsw-editor-title">' + editTargetLabel() +
          (m.remaining === 0 && byS ? ' <span class="nsw-pill" style="color:var(--up)">' + T('nsw.will_overwrite', '将覆盖原值') + '</span>' : '') +
        '</div>' +
        '<div class="nsw-desc">' + T('nsw.editor_desc', '拖拽或点击快捷档位给出您对黄金<b>后续走势的看多强度</b>；备注可记录所参考的投行观点。') + '</div>' +

        '<div class="nsw-range-row">' +
          '<span class="cap">' + T('nsw.cap_bear', '看空 0') + '</span>' +
          '<input type="range" id="nswScore" min="0" max="100" step="1" value="50" ' +
            'aria-label="' + esc(T('nsw.aria_score', '消息面客户评价打分（0 看空 - 100 看多）')) + '">' +
          '<span class="cap">' + T('nsw.cap_bull', '100 看多') + '</span>' +
          '<div class="v" id="nswScoreVal">50</div>' +
        '</div>' +
        '<div class="nsw-gauge"><i id="nswGaugeMark" style="left:50%"></i></div>' +
        '<div class="nsw-markers"><span>' + T('nsw.mk_bear', '看空展望') + '</span><span>' +
          T('nsw.mk_neutral', '中性') + '</span><span>' + T('nsw.mk_bull', '看多展望') + '</span></div>' +

        '<div class="nsw-row"><span class="cap">' + T('nsw.quick', '快捷档位：') + '</span>' +
          '<button type="button" class="nsw-btn" data-act="preset" data-v="30">' + T('nsw.preset_bear', '看空 30') + '</button>' +
          '<button type="button" class="nsw-btn" data-act="preset" data-v="50">' + T('nsw.preset_neutral', '中性 50') + '</button>' +
          '<button type="button" class="nsw-btn" data-act="preset" data-v="70">' + T('nsw.preset_bull', '看多 70') + '</button>' +
          reuseHtml +
        '</div>' +

        '<div class="nsw-row"><span class="cap">' + T('nsw.dir_label', '方向判定：') + '</span><span id="nswDirBox"></span></div>' +

        '<div style="margin-top:10px">' +
          '<div class="nsw-desc" style="margin-bottom:0">' + T('nsw.notes_label', '研判备注（记录您参考的投行观点 / 链接）') + '</div>' +
          '<textarea class="nsw-ta" id="nswNotes" maxlength="2000" placeholder="' +
            esc(T('nsw.notes_ph', '例：高盛上调金价目标至 X 美元/盎司，摩根看多中短期走势……')) + '"></textarea>' +
        '</div>' +

        '<div style="margin-top:10px">' +
          '<div class="nsw-desc" style="margin-bottom:0">' + T('nsw.basis_label', '研判依据（可多选，用于复盘统计「哪类依据更可靠」）') + '</div>' +
          '<div class="nsw-basis" id="nswBasis"></div>' +
        '</div>' +

        '<div style="margin-top:10px">' +
          '<div class="nsw-desc" style="margin-bottom:0">' + T('nsw.review_label', '复盘批注（可选，结果出来后再回填反思）') + '</div>' +
          '<textarea class="nsw-ta" id="nswReview" maxlength="2000" placeholder="' +
            esc(T('nsw.review_ph', '例：本次高估了央行购金的影响，低估了美元反弹的压制……')) + '"></textarea>' +
        '</div>' +

        '<div class="nsw-acts">' +
          '<button type="button" class="nsw-btn primary" id="nswSave" data-act="save">' + saveLabel + '</button>' +
          '<button type="button" class="nsw-btn" id="nswCancel" data-act="cancel" style="display:none">' + T('nsw.cancel_edit', '恢复原值') + '</button>' +
          '<a class="nsw-link" href="/news">' + T('nsw.more', '投行参考来源与历史记录 →') + '</a>' +
        '</div>' +
        '<div class="nsw-msg" id="nswMsg" role="status" aria-live="polite"></div>' +
      '</div>';

    /* 编辑器状态回填：仅在目标槽位变化时执行，避免打断正在拖动的手感 */
    if (state.loadedSlot !== state.editSlot) {
      var s = bySlot(state.editSlot);
      var rangeEl = el('nswScore');
      if (rangeEl) rangeEl.value = s ? Math.round(s.score) : 50;
      var notesEl = el('nswNotes');
      if (notesEl) notesEl.value = s ? (s.notes || '') : '';
      var revEl = el('nswReview');
      /* ⚠️ 三个字段都必须回填（见文件头「设计要点 2」）：
         notes / basis 在仓库层是**硬覆盖**，不回填就会被静默清空；
         review_note 走 `or` 语义不会被清空，回填是为了让用户看到真值。 */
      if (revEl) revEl.value = s ? (s.review_note || '') : '';
      state.selectedBasis = new Set(s && s.basis ? s.basis : []);
      state.loadedSlot = state.editSlot;
    }
    renderBasis();
    updateGauge();
    if (bySlot(state.editSlot)) el('nswCancel').style.display = 'inline-block';
  }

  function renderBasis() {
    var box = el('nswBasis');
    if (!box) return;
    if (!state.basisOptions.length) {
      box.innerHTML = '<span class="nsw-desc">' + T('nsw.basis_loading', '标签加载中…') + '</span>';
      return;
    }
    var sel = state.selectedBasis || new Set();
    box.innerHTML = state.basisOptions.map(function (tag) {
      return '<button type="button" class="nsw-btn' + (sel.has(tag) ? ' on' : '') +
        '" data-act="basis" data-tag="' + esc(tag) + '" aria-pressed="' + (sel.has(tag) ? 'true' : 'false') + '">' +
        esc(tag) + '</button>';
    }).join('');
  }

  /* 只更新滑杆联动部分：不重渲染整个编辑器，否则会清空 textarea 里已输入的内容 */
  function updateGauge() {
    var rangeEl = el('nswScore');
    if (!rangeEl) return;
    var v = parseInt(rangeEl.value, 10);
    if (isNaN(v)) v = 50;
    el('nswScoreVal').textContent = v;
    el('nswGaugeMark').style.left = v + '%';
    var d = dirOf(v);
    el('nswDirBox').innerHTML = '<span class="nsw-pill" style="color:' + dirColor(d) + '">' + esc(dirTxt(d)) + '</span>';
  }

  function setMsg(text, cls) {
    var m = el('nswMsg');
    if (!m) return;
    m.className = 'nsw-msg' + (cls ? ' ' + cls : '');
    m.textContent = text;
  }

  /* ─────────────── 数据 ─────────────── */

  async function loadBasisOptions() {
    try {
      var d = await fetchJSON(apiBase() + META_PATH);
      state.basisOptions = (d && d.basis_tags) || [];
    } catch (e) {
      /* 标签接口不可用不应挡住打分主流程 → 用内置兜底标签可继续提交 */
      state.basisOptions = FALLBACK_BASIS.slice();
    }
    if (!state.basisOptions.length) state.basisOptions = FALLBACK_BASIS.slice();
    renderBasis();
  }

  async function load() {
    if (state.inflight) return;
    state.inflight = true;
    try {
      var d = await fetchJSON(apiBase() + NEWS_PATH);
      state.today = d;
      /* 默认编辑目标：优先下一个空闲槽位；三次用尽时落在最后一次（权重最高、
         最可能需修正），并显式标注「将覆盖原值」，绝不静默覆盖。 */
      state.editSlot = d.next_slot || MAX_SLOTS;
      render();
    } catch (e) {
      if (state.container) {
        state.container.innerHTML = '<div class="nsw-error">' +
          T('nsw.load_failed', '消息面打分加载失败：{e}', { e: esc(e.message) }) +
          '　<a class="nsw-link" href="/news">前往完整页</a></div>';
      }
    } finally {
      state.inflight = false;
    }
  }

  function openSlot(n, announce) {
    state.editSlot = n;
    render();
    if (announce) {
      var s = bySlot(n);
      setMsg(s
        ? T('nsw.msg_editing', '正在修改第 {n} 次打分，保存后将覆盖原值（复盘批注已带入，不会丢失）。', { n: n })
        : T('nsw.msg_filling', '正在填写第 {n} 次打分。', { n: n }), '');
      var ed = state.container.querySelector('.nsw-editor');
      if (ed && ed.scrollIntoView) ed.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    }
  }

  async function save() {
    if (!state.today) return;
    var btn = el('nswSave');
    var rangeEl = el('nswScore');
    if (!rangeEl) return;
    var v = parseInt(rangeEl.value, 10);
    if (isNaN(v)) { setMsg(T('nsw.msg_bad_value', '分值无效，请重新选择。'), 'err'); return; }
    var target = state.editSlot;
    var existing = bySlot(target);

    /* 全量 upsert：notes / basis / review_note 都必须回传编辑器里的原值
       （已由 render 回填），否则 notes 与 basis 会被静默清空。 */
    var body = {
      score: v,
      direction: dirOf(v),
      notes: el('nswNotes').value,
      basis: Array.from(state.selectedBasis || []),
      review_note: el('nswReview') ? el('nswReview').value : '',
      slot: target
    };

    if (btn) { btn.disabled = true; }
    setMsg(T('nsw.msg_saving', '保存中…'), '');
    try {
      var d = await fetchJSON(apiBase() + NEWS_PATH, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body)
      });
      state.today = d;
      var wasOverwrite = !!existing;
      state.editSlot = d.next_slot || MAX_SLOTS;
      state.loadedSlot = null;   // 强制下一轮 render 重新回填
      render();
      setMsg(T('nsw.msg_saved', '✅ 第 {n} 次打分已保存，当日有效分值更新为 {v}（已汇入综合指数与决策）。',
        { n: target, v: num(d.score) }), 'ok');
      track('news_score_save', { slot: target, score: v, overwrite: wasOverwrite });
      afterWrite();
    } catch (e) {
      setMsg(T('nsw.msg_save_failed', '保存失败：{e}', { e: e.message }), 'err');
    } finally {
      if (btn) { btn.disabled = false; }
    }
  }

  async function removeSlot(n) {
    if (!state.today) return;
    var ok = false;
    try { ok = window.confirm(T('nsw.confirm_del', '确定撤销今日第 {n} 次打分？该槽位将被释放，当日有效分值会按剩余次数重新加权。', { n: n })); }
    catch (e) { ok = false; }
    if (!ok) return;
    setMsg(T('nsw.msg_deleting', '撤销中…'), '');
    try {
      var d = await fetchJSON(apiBase() + NEWS_PATH + '/' + n, { method: 'DELETE' });
      state.today = d;
      state.editSlot = d.next_slot || MAX_SLOTS;
      state.loadedSlot = null;
      render();
      setMsg(T('nsw.msg_deleted', '🗑️ 已撤销第 {n} 次打分，当日有效分值更新为 {v}。', { n: n, v: num(d.score) }), 'ok');
      track('news_score_delete', { slot: n });
      afterWrite();
    } catch (e) {
      setMsg(T('nsw.msg_delete_failed', '撤销失败：{e}', { e: e.message }), 'err');
    }
  }

  /* 写成功后：① 让宿主页立即刷新评估口径；② 刷新置顶结论卡。
     消息面占综合指数 30%，打完分若不刷新，用户会看到"结论没变"而误判无效。 */
  function afterWrite() {
    try {
      window.dispatchEvent(new CustomEvent('news-score-changed'));
    } catch (e) { /* IE 级环境忽略 */ }
    if (window.PM_Synthesis && typeof window.PM_Synthesis.load === 'function') {
      window.PM_Synthesis.load();
    }
  }

  /* ─────────────── 事件（容器级委托：重渲染会重建按钮，不能逐按钮绑定） ─────────────── */

  function onClick(ev) {
    var t = ev.target.closest && ev.target.closest('[data-act]');
    if (!t) return;
    var act = t.getAttribute('data-act');
    if (act === 'preset') {
      var rangeEl = el('nswScore');
      if (rangeEl) { rangeEl.value = t.getAttribute('data-v'); updateGauge(); }
      return;
    }
    if (act === 'reuse') {
      var r2 = el('nswScore');
      if (r2 && state.today && state.today.last_score != null) {
        r2.value = Math.round(state.today.last_score);
        updateGauge();
        setMsg(T('nsw.msg_reused', '已填入上次打分 {v}，确认后点击保存。', { v: Math.round(state.today.last_score) }), '');
      }
      return;
    }
    if (act === 'basis') {
      var tag = t.getAttribute('data-tag');
      if (!state.selectedBasis) state.selectedBasis = new Set();
      if (state.selectedBasis.has(tag)) state.selectedBasis.delete(tag);
      else state.selectedBasis.add(tag);
      renderBasis();   /* 只重渲染标签区 → 保住 textarea 内容 */
      return;
    }
    if (act === 'edit') { openSlot(parseInt(t.getAttribute('data-slot'), 10), true); return; }
    if (act === 'del') { removeSlot(parseInt(t.getAttribute('data-slot'), 10)); return; }
    if (act === 'save') { save(); return; }
    if (act === 'cancel') {
      state.loadedSlot = null;   // 丢弃改动 → 从 state.today 重新回填原值
      render();
      setMsg(T('nsw.msg_restored', '已恢复该槽位的已保存内容。'), '');
      return;
    }
  }

  function onInput(ev) {
    if (ev.target && ev.target.id === 'nswScore') updateGauge();
  }

  /* ─────────────── 挂载 ─────────────── */

  function mount(containerId) {
    var card = document.getElementById(containerId || DEFAULT_CONTAINER);
    if (!card) return false;
    state.container = card;
    state.containerId = containerId || DEFAULT_CONTAINER;
    card.classList.add('nsw-root');
    card.setAttribute('role', 'region');
    card.setAttribute('aria-label', T('nsw.title', '✍️ 今日消息面打分 · 客户评价'));

    if (!state.bound) {
      state.bound = true;
      card.addEventListener('click', onClick);
      card.addEventListener('input', onInput);
      /* 语言切换后重渲染（否则卡片停留在旧语言） */
      document.addEventListener('i18n:change', function () {
        if (state.today) { state.loadedSlot = null; render(); }
      });
    }
    render();
    loadBasisOptions();
    load();
    return true;
  }

  window.PM_NewsScore = {
    mount: mount,
    load: load,
    openSlot: openSlot,
    getState: function () { return state.today; }
  };

  function boot() {
    var s = document.createElement('style');
    s.id = 'newsScoreWidgetStyle';
    s.textContent = CSS;
    document.head.appendChild(s);
    mount(DEFAULT_CONTAINER);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot);
  } else {
    boot();
  }
})();
