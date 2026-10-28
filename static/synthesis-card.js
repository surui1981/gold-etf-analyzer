/*!
 * synthesis-card.js —— 综合研判结论卡（V0.75.1）
 *
 * 把散落在「实时评估摘要 / 共振信号卡 / 决策引擎」三处的判断原料**收敛**成一张
 * 置顶结论卡，让首页一屏即可完成综合数据判断：
 *   ① 结论先行：趋势评估指数 + 等级 + 行动建议 + 行动置信度 + 一句话总判
 *   ② 分面构成：技术 / 宏观 / 消息 / 资金流 4 个面的分值条（红=利多 绿=利空，配文字箭头）
 *   ③ 一致性：显式指出共振三维「同向还是打架」——单看几个数字看不出分歧结构
 *   ④ 仓位对照：建议仓位 vs 当前持仓状态
 *   ⑤ 决策依据 + 待办事项 + 数据质量折损提示
 *
 * 公开 API：window.PM_Synthesis = { mount, load, setAsset, getAsset }
 *
 * 设计要点
 * --------
 * - **口径同源**：三维一致性**不在前端重算**，一律取 `/api/v1/resonance/signal`
 *   （V0.75.1 起该端点支持 target，黄金/白银共用阈值 55/45 + 标准差折扣）。
 *   前端若自行判断「是否共振」，一旦后端调阈值就会出现两处口径打架。
 * - **仓位诚实**：`positions.position_ratio` 目前恒为 0（账户本金未录入，见
 *   services/position.py），因此**不展示「当前仓位 X%」**，只展示
 *   「空仓 / 持有 N 份 · 浮盈 X%」。用一个假数字去判超配/低配是误导。
 * - **i18n 兜底**：`T(key, zh)` 在字典缺 key 时回退中文，绝不把 key 字面量
 *   渲染到页面上（V0.75.0 曾因悬空 key 把页脚中文静默替换成 `warn.data_source`）。
 * - **降级可用**：三接口用 allSettled 并行取，任一失败只降级对应区块并显式提示，
 *   不让整张卡空白（决策 / 共振是增强项，趋势是必需项）。
 * - **IIFE + window.PM_*** 模式，与 PM_Help / PM_Resonance / PM_CmdPalette 一致；
 *   自注入 <style> 不污染 theme.css，复用 --up / --down / --muted / --accent 适配 4 主题。
 */
(function () {
  'use strict';

  var REFRESH_MS = 60000;
  var FETCH_TIMEOUT_MS = 20000;
  var LS_ASSET = 'pm_synthesis_asset';
  var DEFAULT_ASSET = 'gold';
  var DEFAULT_CONTAINER = 'synthesisCard';

  /* 品种 → 数据源映射。
     gold  走 /market/gold/trend?target=etf（518880），与共振端点默认 target=etf 对齐；
     silver 走 /market/silver/trend（端点内固定 silver_etf），decision/signal 用 silver_etf。
     三者必须同品种，否则「指数」与「共振」会来自两个标的。 */
  var ASSETS = {
    gold: {
      key: 'gold',
      i18n: 'syn.asset_gold',
      fallback: '黄金',
      trend: '/api/v1/market/gold/trend?days=60&target=etf',
      target: 'etf'
    },
    silver: {
      key: 'silver',
      i18n: 'syn.asset_silver',
      fallback: '白银',
      trend: '/api/v1/market/silver/trend?days=60',
      target: 'silver_etf'
    }
  };

  var ASSET_ORDER = ['gold', 'silver'];

  /* 分面定义（V0.120.0 起共 4 个面：技术 / 宏观 / 消息 / 资金流）。
     **权重不在这里写死** —— 综合指数的面权重由后端下发：
       index.face_weights         = 实际生效（已剔除无分值的面并归一化）
       index.face_weights_nominal = 配置原值（被剔除的面只能从这里取权重）
     旧代码硬编码「技术 30% + 宏观 40% + 消息 30%」有两个后果：
       ① 消息面未打分时该面被剔除、其余面权重重新归一化，卡片标题会显示一个
          与实际算法不符的公式（公式 ≠ 算法）；
       ② V0.120.0 加了资金流面后，资金流根本没出现在这张卡上。
     nominal 只在**后端没下发**（老后端 / 旧缓存）时兜底。 */
  var DIMS = [
    { key: 'tech', i18n: 'trend.comp_tech', fallback: '技术面', nominal: 0.25 },
    { key: 'macro', i18n: 'trend.comp_macro', fallback: '宏观参考', nominal: 0.35 },
    { key: 'news', i18n: 'trend.comp_news', fallback: '消息面', nominal: 0.25 },
    { key: 'flow', i18n: 'trend.comp_flow', fallback: '资金流面', nominal: 0.15 }
  ];

  /* 共振 5 类 → 一致性措辞（tone 决定配色）。
     文案必须说明「结构」而非只给形容词：用户要判断的正是「几个维度是否打架」。
     ⚠️ 共振口径**仍只有 3 个面**（技术/宏观/消息）—— 资金流面暂未纳入共振判定
     （见 docs/api-reference.md §6.4 已知缺口），故措辞写「共振三维」而不是
     「三维」—— 否则用户看到 4 根分值条却读到「三维背离」会以为漏了一面。 */
  var CONSISTENCY = {
    strong_up: { tone: 'up', i18n: 'syn.cons_strong_up', fallback: '共振三维（技术/宏观/消息）同向看多（各 ≥55）→ 共振成立，结构最干净' },
    strong_down: { tone: 'down', i18n: 'syn.cons_strong_down', fallback: '共振三维（技术/宏观/消息）同向看空（各 ≤45）→ 反向共振成立，结构最干净' },
    weak_up: { tone: 'weak', i18n: 'syn.cons_weak_up', fallback: '共振三维中 2 维看多 → 弱共振，方向偏多但强度不足' },
    divergent: { tone: 'diverge', i18n: 'syn.cons_divergent', fallback: '共振三维中出现显著背离（任意两维分差 ≥15）→ 反转/分歧结构，最需警惕' },
    neutral: { tone: 'neutral', i18n: 'syn.cons_neutral', fallback: '共振三维均在中性区（45~55）→ 无有效方向，等市场表态' }
  };

  /* V0.78.0：背离维度对 → i18n 键。缺失时回退服务端返回的 subtype_label（中文），
     避免英文环境下显示裸 key（与本文件 T(key, fallback) 的兜底约定一致）。 */
  var DIVERGENT_I18N = {
    tech_macro: 'syn.dvg_tech_macro',
    tech_news: 'syn.dvg_tech_news',
    macro_news: 'syn.dvg_macro_news'
  };

  var CONF_I18N = { low: 'syn.conf_low', medium: 'syn.conf_medium', high: 'syn.conf_high' };
  var CONF_FALLBACK = { low: '低', medium: '中', high: '高' };

  var LEVEL_FALLBACK = {
    strong_up: '强势上升', up: '上升', sideways: '震荡整理',
    down: '下降', strong_down: '弱势下降'
  };

  var CSS = [
    '#synthesisCard { padding: 16px; }',
    '.syn-head { display: flex; align-items: center; justify-content: space-between;',
    '  gap: 10px; flex-wrap: wrap; margin-bottom: 12px; }',
    '.syn-title { font-size: 15px; font-weight: 600; }',
    '.syn-hint { font-weight: 400; font-size: 11px; color: var(--muted); margin-left: 6px; }',
    '.syn-switch { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }',
    '.syn-tab { font: inherit; font-size: 12.5px; padding: 4px 14px; border-radius: 999px;',
    '  border: 1px solid var(--border); background: transparent; color: var(--muted); cursor: pointer; }',
    '.syn-tab:hover { border-color: var(--accent); color: var(--text); }',
    '.syn-tab.active { background: var(--accent); border-color: var(--accent); color: #fff; font-weight: 600; }',
    '.syn-tab:focus-visible { outline: 3px solid var(--focus-ring); outline-offset: 2px; }',
    '.syn-time { font-size: 11px; color: var(--muted); margin-left: 4px; }',
    /* 结论区 */
    '.syn-concl { display: flex; align-items: center; gap: 20px; flex-wrap: wrap;',
    '  padding-bottom: 14px; border-bottom: 1px dashed var(--border); }',
    '.syn-score { text-align: center; min-width: 92px; }',
    '.syn-score .n { font-size: 34px; font-weight: 700; line-height: 1.05; }',
    '.syn-score .l { font-size: 11px; color: var(--muted); margin-top: 4px; }',
    '.syn-main { flex: 1; min-width: 240px; }',
    '.syn-act { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; margin-bottom: 6px; }',
    '.syn-action { font-size: 19px; font-weight: 700; }',
    '.syn-chip { font-size: 11px; font-weight: 600; padding: 1px 9px; border-radius: 999px;',
    '  background: var(--chip-dim-bg); color: var(--chip-dim-fg); }',
    '.syn-level { font-size: 12.5px; color: var(--muted); margin-bottom: 6px; }',
    '.syn-verdict { font-size: 13px; line-height: 1.65; }',
    '.syn-verdict b { color: var(--text); }',
    /* 分面分值条 */
    '.syn-bars { margin: 14px 0 4px; }',
    '.syn-bars-head { font-size: 11px; color: var(--muted); margin-bottom: 8px; }',
    '.syn-row { display: grid; grid-template-columns: 64px 1fr 44px 34px 62px; gap: 8px;',
    '  align-items: center; font-size: 12.5px; margin-bottom: 7px; }',
    '.syn-row .nm { color: var(--muted); }',
    '.syn-row .track { display: block; height: 8px; border-radius: 4px;',
    '  background: var(--bg); border: 1px solid var(--border); overflow: hidden; }',
    '.syn-row .track i { display: block; height: 100%; }',
    '.syn-row .val { text-align: right; font-weight: 600; }',
    '.syn-row .wt { text-align: right; color: var(--muted); font-size: 11.5px; }',
    '.syn-row .dir { text-align: right; }',
    '.syn-row.syn-row-miss { opacity: .72; }',
    /* 一致性 */
    '.syn-consensus { border-radius: 10px; padding: 10px 12px; font-size: 12.5px;',
    '  line-height: 1.6; margin: 14px 0; border: 1px solid var(--border); }',
    '.syn-consensus .k { font-weight: 600; margin-right: 6px; }',
    '.syn-consensus .prov { display: block; font-size: 11px; color: var(--muted); margin-top: 4px; }',
    '.syn-tone-up { background: var(--chip-ok-bg); border-color: var(--chip-ok-bd); }',
    '.syn-tone-down { background: var(--chip-bad-bg); border-color: var(--chip-bad-bd); }',
    '.syn-tone-weak { background: var(--chip-delay-bg); border-color: var(--chip-delay-bd); }',
    '.syn-tone-diverge { background: var(--chip-warn-bg); border-color: var(--chip-warn-bd); }',
    '.syn-tone-neutral { background: var(--chip-dim-bg); border-color: var(--chip-dim-bd); }',
    /* 依据 / 待办 / 页脚 */
    '.syn-sub { font-size: 11px; color: var(--muted); margin-bottom: 6px; }',
    '.syn-reasons { margin: 0 0 14px; padding-left: 18px; font-size: 12.5px; line-height: 1.75; }',
    '.syn-todo { display: flex; align-items: center; gap: 10px; flex-wrap: wrap;',
    '  padding-top: 12px; border-top: 1px dashed var(--border); }',
    '.syn-todo .k { font-size: 11px; color: var(--muted); }',
    '.syn-btn { font-size: 12.5px; text-decoration: none; padding: 4px 12px; border-radius: 8px;',
    '  border: 1px solid var(--border); color: var(--accent); background: transparent; }',
    '.syn-btn:hover { background: var(--accent); color: #fff; border-color: var(--accent); }',
    '.syn-btn.warn { border-color: var(--chip-warn-bd); background: var(--chip-warn-bg); color: var(--chip-warn-fg); font-weight: 600; }',
    '.syn-qual { margin-top: 12px; padding-top: 10px; border-top: 1px dashed var(--border);',
    '  font-size: 11px; color: var(--muted); line-height: 1.7; }',
    '.syn-qual .k { font-weight: 600; color: var(--text); }',
    '.syn-qual ul { margin: 4px 0 0; padding-left: 16px; }',
    '.syn-qual a { color: var(--accent); }',
    '.syn-loading { color: var(--muted); font-size: 13px; }',
    '.syn-error { color: var(--down); font-size: 13px; font-weight: 600; }',
    '.syn-degraded { color: var(--chip-warn-fg); font-size: 11px; margin-top: 6px; }'
  ].join('\n');

  var state = {
    containerId: DEFAULT_CONTAINER,
    asset: DEFAULT_ASSET,
    loaded: false,
    inflight: false
  };

  /* ───────────────── i18n（带中文兜底，绝不渲染 key 字面量） ───────────────── */

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
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }

  /* ───────────────── 工具 ───────────────── */

  function base() {
    // V0.106.2 整合：去掉 8888 硬编码（同源）
    return '';
  }

  function fetchJSON(url) {
    var ctl = typeof AbortController !== 'undefined' ? new AbortController() : null;
    var timer = ctl ? setTimeout(function () { ctl.abort(); }, FETCH_TIMEOUT_MS) : null;
    return fetch(url, ctl ? { signal: ctl.signal } : undefined).then(function (r) {
      if (timer) clearTimeout(timer);
      if (!r.ok) throw new Error('HTTP ' + r.status);
      return r.json();
    }).catch(function (e) {
      if (timer) clearTimeout(timer);
      throw e;
    });
  }

  function track(evt, payload) {
    if (window.TL && typeof window.TL.track === 'function') {
      try { window.TL.track(evt, payload || {}); } catch (e) { /* 埋点失败不影响渲染 */ }
    }
  }

  /* 方向 → 颜色 + 文字箭头（不能只靠颜色区分，色盲用户要能读） */
  function dirMeta(direction) {
    if (direction === 'bullish') return { color: 'var(--up)', arrow: '↑', text: '看多' };
    if (direction === 'bearish') return { color: 'var(--down)', arrow: '↓', text: '看空' };
    return { color: 'var(--muted)', arrow: '→', text: '中性' };
  }

  /* 数据质量标注。
     判据优先用后端给的 **tier** 字段（V0.118.1：`live` / `lkg` 末次落库 /
     `static` 内置常量），tier 缺失时才退回匹配 source 的占位标记字面量。
     **不能**用「不是 H.15 就算静态」这种启发式——宏观因子里还有
     「世界黄金协会 GDT」这类正当季度源（央行购金），用启发式会把真数据
     误标成兜底值，正好违背本卡「不夸大可信度」的目的。 */
  function macroTier(f) {
    if (f.tier) return f.tier;
    var s = f.source ? String(f.source) : '';
    if (s.indexOf('末次落库') >= 0) return 'lkg';
    if (s.indexOf('静态参考值') >= 0) return 'static';
    return 'live';
  }

  function qualityNotes(trend, missDims, weights) {
    var notes = [];
    var factors = (trend.macro && trend.macro.factors) || [];
    var statics = factors.filter(function (f) { return macroTier(f) === 'static'; });
    var lkgs = factors.filter(function (f) { return macroTier(f) === 'lkg'; });
    /* 权重文案取**实际生效**权重（被剔除的面没有生效权重，退回配置权重），
       不再写死「该维度权重 40%」—— 权重可在权重配置页改，写死就是撒谎。 */
    var macroW = weights && weights.macro
      ? (weights.macro.effective != null ? weights.macro.effective : weights.macro.nominal)
      : 0.35;
    var macroWPct = fmtW(macroW * 100);
    if (lkgs.length) {
      var lnames = lkgs.map(function (f) { return f.name; }).filter(Boolean);
      var lshown = lnames.slice(0, 4).join('、') + (lnames.length > 4 ? ' 等' : '');
      var ldates = lkgs.map(function (f) { return f.data_date; }).filter(Boolean).sort();
      notes.push(T('syn.q_macro_lkg',
        '宏观因子 {n}/{m} 项为降级读数（{names}；最新数据日 {d}，上游数据源当时不可用，用上次真实读数顶替）→ 该维度权重 {w}%，结论可信度相应打折',
        { n: lkgs.length, m: factors.length, names: lshown,
          d: ldates.length ? ldates[ldates.length - 1] : '—', w: macroWPct }));
    }
    if (statics.length) {
      var names = statics.map(function (f) { return f.name; }).filter(Boolean);
      var shown = names.slice(0, 4).join('、') + (names.length > 4 ? ' 等' : '');
      var dates = statics.map(function (f) { return f.data_date; }).filter(Boolean).sort();
      notes.push(T('syn.q_macro_static',
        '宏观因子 {n}/{m} 项为静态参考值（{names}；最新数据日 {d}，非实时行情）→ 该维度权重 {w}%，结论可信度相应打折',
        { n: statics.length, m: factors.length, names: shown,
          d: dates.length ? dates[dates.length - 1] : '—', w: macroWPct }));
    }
    /* V0.120.0：资金流面同款降级披露（宏观面有、资金流面没有 ⇒ 两张卡口径不一致，
       用户会以为资金流面的读数一定比宏观面「新鲜」）。 */
    var ff = (trend.flow && trend.flow.factors) || [];
    var fstatics = ff.filter(function (f) { return macroTier(f) === 'static'; });
    var flkgs = ff.filter(function (f) { return macroTier(f) === 'lkg'; });
    var flowW = weights && weights.flow
      ? (weights.flow.effective != null ? weights.flow.effective : weights.flow.nominal)
      : 0.15;
    var flowWPct = fmtW(flowW * 100);
    if (flkgs.length) {
      var fnames = flkgs.map(function (f) { return f.name; }).filter(Boolean);
      var fshown = fnames.slice(0, 4).join('、') + (fnames.length > 4 ? ' 等' : '');
      var fdates = flkgs.map(function (f) { return f.data_date; }).filter(Boolean).sort();
      notes.push(T('syn.q_flow_lkg',
        '资金流因子 {n}/{m} 项为降级读数（{names}；最新数据日 {d}，上游数据源当时不可用，用上次真实读数顶替）→ 该维度权重 {w}%，结论可信度相应打折',
        { n: flkgs.length, m: ff.length, names: fshown,
          d: fdates.length ? fdates[fdates.length - 1] : '—', w: flowWPct }));
    }
    if (fstatics.length) {
      var fn2 = fstatics.map(function (f) { return f.name; }).filter(Boolean);
      var fs2 = fn2.slice(0, 4).join('、') + (fn2.length > 4 ? ' 等' : '');
      var fd2 = fstatics.map(function (f) { return f.data_date; }).filter(Boolean).sort();
      notes.push(T('syn.q_flow_static',
        '资金流因子 {n}/{m} 项为静态参考值（{names}；最新数据日 {d}，非实时行情）→ 该维度权重 {w}%，结论可信度相应打折',
        { n: fstatics.length, m: ff.length, names: fs2,
          d: fd2.length ? fd2[fd2.length - 1] : '—', w: flowWPct }));
    }
    var newsPending = !!(trend.news && trend.news.scored === false);
    if (newsPending) {
      /* V0.100.0 起消息面未打分是**被剔除**（不是「按中性 50 计入」）——
         后端把该面从 faces 里剔掉、其余面权重重新归一化（见 services/trend.py）。
         旧文案「按中性 50 计入（占权重 30%）」与实际算法矛盾，已改正。 */
      var newsW = weights && weights.news
        ? (weights.news.effective != null ? weights.news.effective : weights.news.nominal)
        : 0.25;
      notes.push(T('syn.q_news_unscored',
        '消息面今日尚未打分，已剔除并按其余面权重归一化（该面配置权重 {w}%）',
        { w: fmtW(newsW * 100) }));
    }
    /* 某面数据不足被剔除：结论的「覆盖面」变了，必须显式告知（V0.78.0 Step D）。
       不能只把那一行画成「—」而不解释 —— 客户看到综合指数却不知少算了一面。
       消息面「尚未打分」已由上一条单独说明（性质不同：待打分 vs 数据源挂了），
       这里不再重复列它。 */
    var missOther = (missDims || []).filter(function (d) {
      return !(newsPending && d.key === 'news');
    });
    if (missOther.length) {
      notes.push(T('syn.q_face_missing',
        '「{names}」数据不足，未参与综合指数（其余维度已按有效维度归一化）→ 本次结论的覆盖面低于常态',
        { names: missOther.map(function (d) { return T(d.i18n, d.fallback); }).join('、') }));
    }
    if (trend.degraded) {
      var srcMap = trend.data_sources || {};
      var all = Object.keys(srcMap);
      var mocks = all.filter(function (k) { return srcMap[k] === 'mock'; });
      notes.push(T('syn.q_degraded',
        '行情源降级：{n}/{m} 个市场为演示(Mock)数据，非真实行情',
        { n: mocks.length, m: all.length }));
    }
    return notes;
  }

  /* 一句话总判：由「指数等级 + 一致性结构 + 行动建议 + 仓位差距」拼装，
     全部来自接口字段，不引入新的判断口径。 */
  function buildVerdict(assetName, idx, res, dec, confTxt) {
    var level = LEVEL_FALLBACK[idx.level] || idx.level || '—';
    var parts = [];
    parts.push(assetName + ' 趋势评估指数 <b>' + (idx.score != null ? idx.score.toFixed(1) : '—')
      + '</b>，处于<b>' + esc(level) + '</b>');

    if (res && CONSISTENCY[res.signal]) {
      var ci = CONSISTENCY[res.signal];
      var txt = T(ci.i18n, ci.fallback);
      if (res.signal === 'divergent') {
        /* 背离须标明「哪两维在打架」—— 只说「反向」用户无法定位（V0.78.0） */
        var dkey = DIVERGENT_I18N[res.subtype];
        var pair = dkey ? (T(dkey, '') || res.subtype_label || '') : (res.subtype_label || '');
        if (pair) { txt += '（' + pair + '）'; }
      }
      parts.push('共振结构：' + esc(txt));
    }
    if (dec) {
      parts.push('决策引擎给出<b>' + esc(dec.action_label || '—') + '</b>（' + esc(confTxt) + '置信度）');
      var sug = dec.suggested_position;
      var hasPos = !!(dec.position && dec.position.has_position);
      if (sug != null) {
        parts.push(hasPos
          ? '参考仓位 <b>' + sug + '%</b>，请对照自有持仓评估超配/低配'
          : '参考仓位 <b>' + sug + '%</b>，当前空仓 → 可据此分批建仓');
      }
    }
    return parts.join('；') + '。';
  }

  /* ───────────────── 渲染 ───────────────── */

  /* 缺失面与「中性 50」必须区分（V0.78.0 Step D）：
     后端在某一面不可用时**不再下发该 key**（原先下发中性 50 会把「没数据」显示成
     「多空平衡」），故这里以「key 是否存在」判定能否展示，缺则显示「— 未计入」。 */
  function hasFace(components, key) {
    return Object.prototype.hasOwnProperty.call(components, key) && components[key] != null;
  }

  /* 当前缺哪些面（顺序与 DIMS 一致），用于行渲染与数据质量提示 */
  function missingFaces(components) {
    return DIMS.filter(function (d) { return !hasFace(components, d.key); });
  }

  /* 面权重解析：优先后端下发，缺失时在本地按 nominal 重新归一化。
     返回 { key: { effective, nominal } }：
       effective = 实际生效权重（该面有分值时才有；被剔除的面为 null）
       nominal   = 配置权重（被剔除的面用它展示「配置上占多少」） */
  function resolveFaceWeights(idx, components) {
    var eff = (idx && idx.face_weights && typeof idx.face_weights === 'object') ? idx.face_weights : null;
    var nom = (idx && idx.face_weights_nominal && typeof idx.face_weights_nominal === 'object')
      ? idx.face_weights_nominal : null;
    var out = {};
    var presentTotal = 0;
    DIMS.forEach(function (d) {
      var n = (nom && typeof nom[d.key] === 'number') ? nom[d.key] : d.nominal;
      out[d.key] = { effective: null, nominal: n, present: hasFace(components, d.key) };
      if (out[d.key].present) presentTotal += n;
    });
    DIMS.forEach(function (d) {
      var e = (eff && typeof eff[d.key] === 'number') ? eff[d.key] : null;
      if (e == null && out[d.key].present && presentTotal > 0) {
        /* 后端没给 face_weights（老后端 / 旧缓存）→ 本地归一化兜底，
           保证「标题里的公式」与实际算法一致。 */
        e = out[d.key].nominal / presentTotal;
      }
      out[d.key].effective = e;
    });
    return out;
  }

  /* 权重百分比格式化：统一 1 位小数（整数百分比加起来未必等于 100，
     而这张卡的价值就是让用户能对着公式复算）。 */
  function fmtW(pct) {
    if (pct == null || isNaN(pct)) return '—';
    return (Math.round(pct * 10) / 10).toFixed(1);
  }

  /* 标题里的公式：只列**实际生效**的面（被剔除的面不进公式），
     权重用实际生效权重 ⇒ 公式加总 = 综合指数。 */
  function dimsFormula(weights, components) {
    return DIMS
      .filter(function (d) { return hasFace(components, d.key); })
      .map(function (d) {
        var w = weights[d.key];
        var pct = (w.effective != null) ? w.effective : w.nominal;
        return T(d.i18n, d.fallback) + ' ' + fmtW(pct * 100) + '%';
      })
      .join(' ＋ ');
  }

  function barRow(dim, components, weights) {
    var w = weights[dim.key];
    if (!hasFace(components, dim.key)) {
      /* 被剔除的面：展示它的**配置权重**（灰显），并标「未计入」——
         它没有生效权重（生效权重已被重新归一化分给其余面）。 */
      return '<div class="syn-row syn-row-miss">'
        + '<span class="nm">' + esc(T(dim.i18n, dim.fallback)) + '</span>'
        + '<span class="track"><i style="width:0%;background:var(--muted)"></i></span>'
        + '<span class="val" style="color:var(--muted)">—</span>'
        + '<span class="wt">' + fmtW(w.nominal * 100) + '%</span>'
        + '<span class="dir" style="color:var(--muted)">' + esc(T('syn.row_excluded', '未计入')) + '</span>'
        + '</div>';
    }
    var score = components[dim.key];
    var pct = (w.effective != null) ? w.effective : w.nominal;
    var m = dirMeta(score >= 55 ? 'bullish' : score <= 45 ? 'bearish' : 'neutral');
    return '<div class="syn-row">'
      + '<span class="nm">' + esc(T(dim.i18n, dim.fallback)) + '</span>'
      + '<span class="track"><i style="width:' + Math.max(0, Math.min(100, score)) + '%;background:' + m.color + '"></i></span>'
      + '<span class="val" style="color:' + m.color + '">' + score.toFixed(1) + '</span>'
      + '<span class="wt">' + fmtW(pct * 100) + '%</span>'
      + '<span class="dir" style="color:' + m.color + '">' + m.text + ' ' + m.arrow + '</span>'
      + '</div>';
  }

  function render(data) {
    var card = document.getElementById(state.containerId);
    if (!card) return;

    var asset = ASSETS[state.asset];
    var assetName = T(asset.i18n, asset.fallback);
    var trend = data.trend;
    var dec = data.decision;
    var res = data.resonance;
    var idx = trend.index || {};
    var components = idx.components || {};
    /* V0.120.0：面权重一律取后端下发（face_weights = 实际生效、已归一化；
       face_weights_nominal = 配置原值）。旧代码硬编码「技术 30% + 宏观 40% +
       消息 30%」—— 消息面未打分时该面被剔除、剩余面权重被重新归一化，
       硬编码会直接说错话（公式 ≠ 实际算法）。 */
    var weights = resolveFaceWeights(idx, components);

    var level = LEVEL_FALLBACK[idx.level] || idx.level || '—';
    var idxColor = idx.direction === 'bullish' ? 'var(--up)'
      : idx.direction === 'bearish' ? 'var(--down)' : 'var(--muted)';

    var confTxt = dec ? T(CONF_I18N[dec.confidence] || '', CONF_FALLBACK[dec.confidence] || '—') : '—';

    /* ① 结论区 */
    var actHtml = '';
    if (dec) {
      var actKey = 'portfolio.action_' + String(dec.action || '').toLowerCase();
      var actTxt = T(actKey, dec.action_label || '—');
      var actColor = { BUY: 'var(--up)', ADD: 'var(--up)', HOLD: 'var(--text)',
        REDUCE: 'var(--down)', SELL: 'var(--down)', WAIT: 'var(--muted)' }[dec.action] || 'var(--text)';
      actHtml =
        '<div class="syn-act">'
        + '<span class="syn-action de-action" tabindex="0" role="button" aria-label="' + esc(actTxt)
        + '" data-de-action="' + esc(dec.action || '') + '"'
        + ' style="color:' + actColor + ';cursor:help;text-decoration:underline dotted">'
        + esc(actTxt) + '</span>'
        + '<span class="syn-chip">' + esc(dec.action || '—') + '</span>'
        + '<span class="syn-time">' + esc(T('syn.conf_label', '行动置信度')) + ' ' + esc(confTxt) + '</span>'
        + '</div>'
        + '<div class="syn-level">' + esc(level) + ' · '
        + esc(T('syn.resonance_strength', '共振强度')) + ' '
        + (res && res.confidence != null ? res.confidence.toFixed(1) : '—') + '/100</div>';
    } else {
      actHtml = '<div class="syn-act"><span class="syn-action">' + esc(T('syn.dec_missing', '决策不可用')) + '</span></div>'
        + '<div class="syn-level">' + esc(level) + '</div>';
    }

    var posHtml = '';
    if (dec) {
      var p = dec.position || {};
      var cur = p.has_position
        ? (T('syn.hold_n', '持有 {n} 份', { n: (p.quantity != null ? p.quantity : 0) })
          + (p.pnl_pct != null ? ' · ' + (p.pnl_pct >= 0 ? T('syn.pnl_gain', '浮盈') : T('syn.pnl_loss', '浮亏'))
            + ' ' + Math.abs(p.pnl_pct).toFixed(2) + '%' : ''))
        : T('syn.hold_none', '当前空仓');
      posHtml = '<div class="syn-level">' + esc(T('syn.suggested_position', '建议仓位')) + ' <b>'
        + (dec.suggested_position != null ? dec.suggested_position + '%' : '—') + '</b>（'
        + esc(dec.position_level || '—') + '） · ' + esc(T('syn.current_position', '当前持仓')) + ' '
        + esc(cur) + '</div>';
    }

    var levelTxt = LEVEL_FALLBACK[idx.level] || idx.level || '—';
    var verdict = buildVerdict(assetName, idx, res, dec, confTxt);

    /* ③ 一致性 */
    var consHtml = '';
    if (res && CONSISTENCY[res.signal]) {
      var c = CONSISTENCY[res.signal];
      consHtml = '<div class="syn-consensus syn-tone-' + c.tone + '">'
        + '<span class="k">' + esc(T('syn.consistency', '一致性')) + '</span>'
        + esc(T(c.i18n, c.fallback))
        + '<span class="prov">' + esc(res.direction_summary || '')
        + ' · ' + esc(T('syn.cons_prov', '由后端共振口径判定（阈值 55/45 + 标准差折扣），与共振卡同源'))
        + '</span></div>';
    }

    /* ④ 依据 */
    var reasonsHtml = '';
    var items = (dec && dec.reason_items) || [];
    if (items.length) {
      reasonsHtml = '<div class="syn-sub">' + esc(T('syn.reasons', '决策依据')) + '</div>'
        + '<ul class="syn-reasons">'
        + items.map(function (r) {
          var m = dirMeta(r.direction);
          return '<li style="color:' + (m.color === 'var(--muted)' ? 'var(--text)' : m.color) + '">'
            + esc(r.text) + '</li>';
        }).join('')
        + '</ul>';
    }

    /* ⑤ 待办（原「今日操作清单」收敛：指数与仓位已在本卡，只留真正要动的两项） */
    var todo = [];
    if (trend.news && trend.news.scored === false) {
      todo.push({ href: '/news', label: T('syn.goto_score', '去打分'), warn: true });
    }
    if (dec && !(dec.position && dec.position.has_position)) {
      todo.push({ href: '/portfolio', label: T('syn.goto_open', '去开仓'), warn: false });
    } else if (dec) {
      todo.push({ href: '/portfolio', label: T('syn.goto_manage', '去管理持仓'), warn: false });
    }
    var todoHtml = todo.length
      ? '<div class="syn-todo"><span class="k">' + esc(T('syn.next_step', '下一步')) + '</span>'
        + todo.map(function (t) {
          return '<a class="syn-btn' + (t.warn ? ' warn' : '') + '" href="' + esc(t.href) + '">'
            + esc(t.label) + '</a>';
        }).join('') + '</div>'
      : '';

    /* ⑥ 数据质量 + 下钻入口 */
    var missDims = missingFaces(components);
    var notes = qualityNotes(trend, missDims, weights);
    var deg = [];
    if (!dec) deg.push(T('syn.deg_decision', '决策接口暂不可用，以上不含行动建议与仓位参考'));
    if (!res) deg.push(T('syn.deg_resonance', '共振接口暂不可用，缺共振一致性判定'));
    var qualHtml = '<div class="syn-qual">'
      + '<span class="k">' + esc(T('syn.quality', '数据质量')) + '</span>'
      + (notes.length
        ? '<ul>' + notes.map(function (n) { return '<li>' + esc(n) + '</li>'; }).join('') + '</ul>'
        : ' ' + esc(T('syn.q_none', '无异常')))
      + (deg.length
        ? '<div class="syn-degraded">' + deg.map(esc).join('；') + '</div>' : '')
      + ' · <a href="#" class="syn-detail">' + esc(T('syn.detail_link', '共振详情（历史 + 强信号胜率）')) + '</a>'
      + '</div>';

    var servedAt = trend.served_at ? new Date(trend.served_at) : null;
    var pad = function (n) { return String(n).padStart(2, '0'); };
    var timeTxt = servedAt
      ? pad(servedAt.getMonth() + 1) + '-' + pad(servedAt.getDate()) + ' ' + pad(servedAt.getHours()) + ':' + pad(servedAt.getMinutes())
      : '—';

    var tabs = ASSET_ORDER.map(function (k) {
      var a = ASSETS[k];
      return '<button type="button" class="syn-tab' + (k === state.asset ? ' active' : '') + '" '
        + 'data-asset="' + k + '" aria-pressed="' + (k === state.asset) + '">'
        + esc(T(a.i18n, a.fallback)) + '</button>';
    }).join('');

    card.innerHTML =
      '<div class="syn-head">'
      + '<div class="syn-title">' + esc(T('syn.title', '综合研判结论'))
      + '<span class="syn-hint">' + esc(T('syn.hint', '一屏定调')) + '</span></div>'
      + '<div class="syn-switch" role="group" aria-label="' + esc(T('syn.switch_aria', '切换品种')) + '">'
      + tabs + '<span class="syn-time">' + esc(T('syn.as_of', '数据时点')) + ' ' + esc(timeTxt) + '</span></div>'
      + '</div>'

      + '<div class="syn-concl">'
      + '<div class="syn-score">'
      + '<div class="n" style="color:' + idxColor + '">'
      + (idx.score != null ? idx.score.toFixed(1) : '—') + '</div>'
      + '<div class="l">' + esc(T('syn.idx_label', '趋势评估指数 /100')) + '</div>'
      + '<div class="l">' + esc(levelTxt) + '</div>'
      + '</div>'
      + '<div class="syn-main">' + actHtml + posHtml
      + '<div class="syn-verdict">' + verdict + '</div>'
      + '</div></div>'

      + '<div class="syn-bars">'
      + '<div class="syn-bars-head">'
      + esc(T('syn.dims_head', '分面构成 · 加权 {formula}（红=利多 绿=利空）',
        { formula: dimsFormula(weights, components) }))
      + (missDims.length
        ? ' · <span style="color:var(--chip-warn-fg)">'
          + esc(T('syn.dims_head_miss', '本次未计入：{names}（其余面权重已按有效面归一化）',
            { names: missDims.map(function (d) { return T(d.i18n, d.fallback); }).join('、') }))
          + '</span>'
        : '')
      + '</div>'
      + DIMS.map(function (d) { return barRow(d, components, weights); }).join('')
      + '</div>'

      /* V0.86.0：决策可解释性 · 拆解（综合指数按权加权）+ 对比（按当前建议加减） */
      + (dec && window.PM_DecisionExplainer ? window.PM_DecisionExplainer.compareCard(dec) : '')
      + (dec && window.PM_DecisionExplainer ? window.PM_DecisionExplainer.renderBreakdown(dec) : '')

      + consHtml + reasonsHtml + todoHtml + qualHtml;

    state.loaded = true;
    /* V0.86.0：决策行动 chip hover tooltip（每次重渲染重新挂载，避免 stale 监听） */
    if (dec && window.PM_DecisionExplainer) {
      var actEl = card.querySelector('.de-action');
      if (actEl) window.PM_DecisionExplainer.attachTooltip(actEl, dec.action, dec);
    }
    track('synthesis_card_view', { asset: state.asset, signal: res ? res.signal : null });
  }

  function renderError(msg) {
    var card = document.getElementById(state.containerId);
    if (!card) return;
    var body = esc(msg == null ? '' : msg);
    card.innerHTML = '<div class="syn-error">'
      + esc(T('syn.error', '综合研判加载失败')) + '：' + body
      + '（不影响页面其他数据）</div>';
  }

  function renderLoading() {
    var card = document.getElementById(state.containerId);
    if (!card) return;
    card.innerHTML = '<div class="syn-loading">'
      + esc(T('syn.loading', '综合研判加载中…')) + '</div>';
  }

  /* ───────────────── 取数 ───────────────── */

  /* i18n 字典就绪信号（V0.120.0）
   *
   * ⚠ 卡片内容是 innerHTML 拼出来的，**没有 data-i18n 标记** ⇒ i18n.js 的
   * apply() 扫不到它。字典没就绪就渲染 ⇒ 卡片锁定在默认语言，且永不更新
   * （实测：zh-TW 字典延迟 4s ⇒ 标题停在「分面构成」而非「分面構成」）。
   * 这里在取数前等一次 ready，把「渲染语言」与「字典加载」彻底解耦。
   */
  function i18nReady() {
    try {
      if (window.I18n && window.I18n.ready && typeof window.I18n.ready.then === 'function') {
        return window.I18n.ready.catch(function () { /* 失败也要继续渲染 */ });
      }
    } catch (e) { /* ignore */ }
    return Promise.resolve();
  }

  function load() {
    var card = document.getElementById(state.containerId);
    if (!card) return Promise.resolve();
    if (state.inflight) return Promise.resolve();  // 防重入：60s 轮询与手动刷新叠加
    state.inflight = true;

    var asset = ASSETS[state.asset];
    var t = asset.target;
    return i18nReady().then(function () {
      return Promise.allSettled([
        fetchJSON(base() + asset.trend),
        fetchJSON(base() + '/api/v1/decision/etf?days=60&target=' + encodeURIComponent(t)),
        fetchJSON(base() + '/api/v1/resonance/signal?target=' + encodeURIComponent(t))
      ]);
    }).then(function (rs) {
      var trend = rs[0].status === 'fulfilled' ? rs[0].value : null;
      if (!trend) throw new Error(rs[0].reason && rs[0].reason.message ? rs[0].reason.message : '趋势数据不可用');
      render({
        trend: trend,
        decision: rs[1].status === 'fulfilled' ? rs[1].value : null,
        resonance: rs[2].status === 'fulfilled' ? rs[2].value : null
      });
    }).catch(function (e) {
      renderError(e && e.message ? e.message : String(e));
    }).then(function () {
      state.inflight = false;
    });
  }

  function setAsset(key) {
    if (!ASSETS[key] || key === state.asset) return;
    var from = state.asset;
    state.asset = key;
    try { localStorage.setItem(LS_ASSET, key); } catch (e) { /* 隐私模式 */ }
    track('synthesis_card_target_switch', { from: from, to: key });
    renderLoading();
    load();
  }

  function onCardClick(ev) {
    var tab = ev.target.closest && ev.target.closest('.syn-tab');
    if (tab) {
      setAsset(tab.getAttribute('data-asset'));
      return;
    }
    var detail = ev.target.closest && ev.target.closest('.syn-detail');
    if (detail) {
      ev.preventDefault();
      track('synthesis_card_detail_click', { asset: state.asset, url: location.pathname });
      /* 复用既有共振卡弹窗，避免重复实现「历史 + STRONG_UP 胜率」下钻。
         必须传当前 target：白银态下钻要看白银，否则会串成黄金的数据。 */
      if (window.PM_Resonance && typeof window.PM_Resonance.openModal === 'function') {
        window.PM_Resonance.openModal(ASSETS[state.asset].target);
      }
    }
  }

  function mount(containerId) {
    state.containerId = containerId || DEFAULT_CONTAINER;
    var card = document.getElementById(state.containerId);
    if (!card) return;

    try {
      var saved = localStorage.getItem(LS_ASSET);
      if (saved && ASSETS[saved]) state.asset = saved;
    } catch (e) { /* 隐私模式 */ }

    card.setAttribute('aria-live', 'polite');
    if (card.dataset.synBound !== '1') {
      card.dataset.synBound = '1';
      /* 事件委托：切换按钮每次重渲染都会重建，不能在按钮上直接绑定 */
      card.addEventListener('click', onCardClick);
      /* 语言切换后重渲染（否则卡片停留在旧语言） */
      document.addEventListener('i18n:change', function () {
        if (state.loaded) load();
      });
    }
    renderLoading();
    load();
    if (!state.timer) state.timer = setInterval(load, REFRESH_MS);
  }

  window.PM_Synthesis = {
    mount: mount,
    load: load,
    setAsset: setAsset,
    getAsset: function () { return state.asset; }
  };

  /* 自动挂载：页面存在容器则启动（trend.html / silver.html 共用） */
  function boot() {
    var s = document.createElement('style');
    s.id = 'synthesisCardStyle';
    s.textContent = CSS;
    document.head.appendChild(s);
    if (document.getElementById(DEFAULT_CONTAINER)) mount(DEFAULT_CONTAINER);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot);
  } else {
    boot();
  }
})();
