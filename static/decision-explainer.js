/*!
 * decision-explainer.js —— 决策可解释性共享工具（V0.86.0）
 *
 * 你的应用核心是「辅助决策」，决策可信度是用户最关心的——但目前：
 *   ① 综合指数只给一个数字「X.X/100」，用户不知道「为什么是 X」；
 *   ② 持仓旁边只展示「建议仓位 N%」，没有「按当前建议应加减 ¥X」的对比；
 *   ③ 决策行动 chip（BUY_HEAVY / SELL ...）只给一个标签，不知道「触发条件是什么」；
 *
 * 本模块提供 4 个工具函数供 synthesis-card.js / portfolio.html 共用：
 *   ① `breakdownRows(decision)`     — 综合指数拆解（技术 X × 30% + 宏观 Y × 40% + 消息 Z × 30%）
 *   ② `compareCard(decision)`       — 「按建议应加减 ¥X」对比卡
 *   ③ `tooltipFor(action, ctx)`     — hover 决策行动的 3 行解释
 *   ④ `dimensionBars(components)`   — 三维横向条形图（共振可视化）
 *
 * 设计要点
 * --------
 * - **字段名陷阱**：trend_index 来自 DecisionOut（不是 trend），components 是它的子字段
 *   —— V0.75.0 曾因 `${trend_index.comp_*}` 字段名拼错静默渲染 undefined，
 *   这里所有取字段都走 `hasOwn` + 默认值保护（参考 MEMORY/frontend-undefined-rendering）
 * - **i18n 兜底**：T(key, fallback) 字典缺 key 时回退中文，绝不渲染 key 字面量
 * - **数据缺时不崩溃**：trend_index.score 为 null（V0.78.0 Step D）→ 拆解显示「—」
 * - **降级**：decision 为 null 时三件套都不渲染（synthesis-card 已有降级路径）
 * - **货币格式**：¥ + 千分位（按当前行情取整；不依赖后端推算金额，由前端按 pnl_pct 推）
 *
 * 公开 API：window.PM_DecisionExplainer = { breakdownRows, compareCard, tooltipFor, dimensionBars }
 *
 * V0.86.0 仅在 synthesis-card.js + portfolio.html 两处挂载，
 * 改前必须 puppeteer 实跑验证（参考 scripts/check_v086.mjs）。
 */
(function () {
  'use strict';

  /* 维度顺序与默认排序一致：宏观 40% / 技术 30% / 消息 30% */
  var DIM_DEFS = [
    { key: 'tech',  i18n: 'trend.comp_tech',  fallback: '技术面', weight: 30 },
    { key: 'macro', i18n: 'trend.comp_macro', fallback: '宏观面', weight: 40 },
    { key: 'news',  i18n: 'trend.comp_news',  fallback: '消息面', weight: 30 }
  ];

  /* 决策行动 → tooltip 三行解释（hover 显示）。
     行 1：综合指数门槛；行 2：浮盈/浮亏门槛；行 3：反向信号/容差。
     文案必须可由客户直接读懂，不暴露后端枚举值。 */
  var ACTION_RULES = {
    BUY_HEAVY:     { rows: 'decision.explain_buy_heavy' },
    BUY:           { rows: 'decision.explain_buy' },
    BUY_LIGHT:     { rows: 'decision.explain_buy_light' },
    ADD:           { rows: 'decision.explain_add' },
    HOLD:          { rows: 'decision.explain_hold' },
    HOLD_CAUTIOUS: { rows: 'decision.explain_hold_cautious' },
    REDUCE:        { rows: 'decision.explain_reduce' },
    SELL:          { rows: 'decision.explain_sell' },
    WAIT:          { rows: 'decision.explain_wait' }
  };

  /* V0.78.0 阈值（与 schemas/thresholds.py 同源；前端仅展示用，故硬编码可接受） */
  var T = {
    BUY_HEAVY: 75,
    BUY: 65,
    BUY_LIGHT: 55,
    HOLD: 55,
    HOLD_LOW: 40,
    NEUTRAL_HIGH: 60,
    NEUTRAL_LOW: 40,
    PNL_TAKE_PROFIT: 15,   // 浮盈止盈门槛
    PNL_STOP_LOSS: -10     // 浮亏止损门槛
  };

  /* ───────────────── i18n + 工具 ───────────────── */

  function tr(key, fallback, params) {
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

  function fmtPct(v) {
    if (v == null || isNaN(v)) return '—';
    return (v >= 0 ? '+' : '') + v.toFixed(2) + '%';
  }

  function fmtYuan(v) {
    if (v == null || isNaN(v)) return '—';
    var sign = v >= 0 ? '+' : '';
    return sign + '¥' + Math.round(v).toLocaleString('zh-CN');
  }

  /* ───────────────── ① 拆解：综合指数拆成加权三分 X 分 ───────────────── */

  /* trend_index = { score, level, direction, summary, components: { tech, macro, news } }
     任一 component 缺失（V0.78.0 Step D 「数据不足未计入」）→ 显示「— 未计入」，
     不能伪装成 50 或 0。 */
  function breakdownRows(decision) {
    if (!decision) return [];
    var idx = decision.trend_index || {};
    var c = idx.components || {};
    var score = (typeof idx.score === 'number') ? idx.score : null;
    var total = (score != null) ? score : null;

    return DIM_DEFS.map(function (d) {
      var v = (c && Object.prototype.hasOwnProperty.call(c, d.key)) ? c[d.key] : null;
      var present = (typeof v === 'number');
      var contribution = present ? (v * d.weight / 100) : null;
      return {
        key: d.key,
        name: tr(d.i18n, d.fallback),
        weight: d.weight,
        value: v,           // null = 缺失
        contribution: contribution,
        present: present,
        missing: !present,
        total: total
      };
    });
  }

  /* 把 breakdownRows 渲染成 HTML（3 行 + 总分 + 公式）。
     缺失行显示「— 未计入」并降透明度，不参与公式合计（V0.78.0 已归一化）。 */
  function renderBreakdown(decision) {
    var rows = breakdownRows(decision);
    if (!rows.length) return '';
    var sumContribution = 0;
    var validWeights = 0;
    var htmlRows = rows.map(function (r) {
      if (r.missing) {
        return '<div class="de-row de-row-miss">'
          + '<span class="de-nm">' + esc(r.name) + '</span>'
          + '<span class="de-track"><i style="width:0%;background:var(--muted)"></i></span>'
          + '<span class="de-val" style="color:var(--muted)">—</span>'
          + '<span class="de-wt">' + r.weight + '%</span>'
          + '<span class="de-contrib" style="color:var(--muted)">'
          + esc(tr('syn.row_excluded', '未计入')) + '</span>'
          + '</div>';
      }
      sumContribution += r.contribution;
      validWeights += r.weight;
      var color = r.value >= 55 ? 'var(--up)' : r.value <= 45 ? 'var(--down)' : 'var(--muted)';
      var arrow = r.value >= 55 ? '↑' : r.value <= 45 ? '↓' : '→';
      return '<div class="de-row">'
        + '<span class="de-nm">' + esc(r.name) + '</span>'
        + '<span class="de-track"><i style="width:' + Math.max(0, Math.min(100, r.value)) + '%;background:' + color + '"></i></span>'
        + '<span class="de-val" style="color:' + color + '">' + r.value.toFixed(1) + '</span>'
        + '<span class="de-wt">×' + r.weight + '%</span>'
        + '<span class="de-contrib" style="color:' + color + '">+'
        + r.contribution.toFixed(1) + ' ' + arrow + '</span>'
        + '</div>';
    }).join('');

    /* 公式行：直接展示「加权计算式」，让用户验证 30/40/30 加权是否正确 */
    var formula = rows.map(function (r) {
      if (r.missing) return esc(r.name) + '(—)';
      return esc(r.name) + ' ' + r.value.toFixed(1) + ' × ' + r.weight + '%';
    }).join(' ＋ ');
    var totalTxt = (decision.trend_index && typeof decision.trend_index.score === 'number')
      ? decision.trend_index.score.toFixed(1) : '—';

    return '<div class="de-breakdown">'
      + '<div class="de-bd-head">' + esc(tr('decision.explain_breakdown_title', '综合指数拆解（按权加权）')) + '</div>'
      + htmlRows
      + '<div class="de-formula">'
      + esc(tr('decision.explain_formula', '公式')) + '：'
      + esc(formula) + ' ＝ <b>' + totalTxt + '</b>/100'
      + '</div></div>';
  }

  /* ───────────────── ② 对比：按建议应加减 ───────────────── */

  /* decision.position.pnl_pct 与 suggested_position 是相对值；
     「应加减金额」用 pnl_pct 反推当前持仓市值：
       持仓市值 V = 成本 × 数量 × (1 + pnl_pct)
       目标市值 V' = V / (1 + pnl_pct) × suggested_position / position_ratio_current
     但 position_ratio 恒为 0（账户本金未录入），故只能给相对差：
       调整比例 = suggested_position - position_ratio(0) = suggested_position
       调整金额（参考）= 当前持仓市值 × (suggested_position/100) — 当前持仓市值 × (current_ratio/100)
     current_ratio 不可知 → 改用「如果按建议仓位，应补/减多少相对当前持仓」。
     这里采用与 V0.74 简报同口径的「应现装 vs 已装」相对表述：
       Δ% = suggested_position - position.position_ratio(0) → suggested_position%
       文字：「建议仓位 X%」+ 「当前 Y%」 + Δ（「补 Z%」或「减 Z%」）
     因 position_ratio 恒为 0，只能给出「按当前持仓比例调整」的描述性卡，不伪造金额。
     **改 V0.86.1 时如接入本金字段可扩展为「补 ¥X」**。 */
  function compareCard(decision) {
    if (!decision) return '';
    var pos = decision.position || {};
    var sug = (typeof decision.suggested_position === 'number') ? decision.suggested_position : null;
    if (sug == null) return '';

    var currentRatio = (typeof pos.position_ratio === 'number') ? pos.position_ratio : null;
    var curTxt;
    var deltaTxt;
    var deltaSign = 0;

    if (currentRatio != null && currentRatio > 0) {
      var curPct = currentRatio * 100;
      curTxt = curPct.toFixed(1) + '%';
      var delta = sug - curPct;
      deltaSign = delta > 0.5 ? 1 : (delta < -0.5 ? -1 : 0);
      if (deltaSign === 1) {
        deltaTxt = tr('decision.explain_compare_add', '需补仓 +{n}%（至建议仓位）', { n: delta.toFixed(1) });
      } else if (deltaSign === -1) {
        deltaTxt = tr('decision.explain_compare_reduce', '需减仓 {n}%（至建议仓位）', { n: Math.abs(delta).toFixed(1) });
      } else {
        deltaTxt = tr('decision.explain_compare_hold', '当前仓位与建议一致');
      }
    } else {
      curTxt = tr('decision.explain_compare_unknown', '未录入本金');
      if (sug >= 75) {
        deltaTxt = tr('decision.explain_compare_heavy', '建议重仓建仓至 {n}%（分批）', { n: sug.toFixed(0) });
      } else if (sug >= 40) {
        deltaTxt = tr('decision.explain_compare_mid', '建议中仓建仓至 {n}%', { n: sug.toFixed(0) });
      } else if (sug >= 20) {
        deltaTxt = tr('decision.explain_compare_light', '建议轻仓试仓 {n}%', { n: sug.toFixed(0) });
      } else {
        deltaTxt = tr('decision.explain_compare_standby', '建议保持观望（≤10%）');
      }
    }

    var color = deltaSign > 0 ? 'var(--up)' : deltaSign < 0 ? 'var(--down)' : 'var(--muted)';
    var icon = deltaSign > 0 ? '↑' : deltaSign < 0 ? '↓' : '→';

    return '<div class="de-compare">'
      + '<span class="de-cmp-k">' + esc(tr('decision.explain_compare_title', '按当前建议仓位')) + '</span>'
      + '<span class="de-cmp-cur">' + esc(tr('decision.explain_compare_current', '当前仓位')) + ' <b>'
      + esc(curTxt) + '</b></span>'
      + '<span class="de-cmp-sug">' + esc(tr('decision.explain_compare_target', '建议仓位')) + ' <b>'
      + esc(sug.toFixed(1)) + '%</b></span>'
      + '<span class="de-cmp-delta" style="color:' + color + '">' + icon + ' ' + esc(deltaTxt) + '</span>'
      + '</div>';
  }

  /* ───────────────── ③ tooltip：决策行动 3 行解释 ───────────────── */

  /* decision 上下文化（idx, pnl, has_position）；缺失则给默认 0/空。
     输出 3 行数组供前端渲染为 tooltip 行（每行一个解释）。 */
  function tooltipFor(action, decision) {
    var rule = ACTION_RULES[action];
    if (!rule) return [];
    var idx = (decision && decision.trend_index && typeof decision.trend_index.score === 'number')
      ? decision.trend_index.score.toFixed(1) : '—';
    var pnl = (decision && decision.position && typeof decision.position.pnl_pct === 'number')
      ? decision.position.pnl_pct.toFixed(1) : null;
    var hasPos = !!(decision && decision.position && decision.position.has_position);

    var rows = [];
    var k1 = rule.rows + '_line1';
    var k2 = rule.rows + '_line2';
    var k3 = rule.rows + '_line3';
    rows.push(tr(k1, '', { idx: idx, pnl: pnl != null ? pnl : '—', has_pos: hasPos ? '1' : '0' }) || '');
    rows.push(tr(k2, '', { idx: idx, pnl: pnl != null ? pnl : '—', has_pos: hasPos ? '1' : '0' }) || '');
    rows.push(tr(k3, '', { idx: idx, pnl: pnl != null ? pnl : '—', has_pos: hasPos ? '1' : '0' }) || '');
    /* 过滤空行（i18n 字典未配置时降级隐藏该行） */
    return rows.filter(function (s) { return !!s; });
  }

  /* 把 tooltip 数组渲染成 HTML 字符串（hover 弹窗内用） */
  function renderTooltip(action, decision) {
    var rows = tooltipFor(action, decision);
    if (!rows.length) return '';
    return '<div class="de-tip">'
      + rows.map(function (r) { return '<div class="de-tip-row">' + esc(r) + '</div>'; }).join('')
      + '</div>';
  }

  /* ───────────────── ④ 三维横向条形图（共振可视化） ───────────────── */

  /* components: { tech, macro, news } —— 来自 /api/v1/resonance/signal，
     与 trend_index.components 同结构但**阈值口径不同**（共振用 55/45 + 标准差折扣） */
  function dimensionBars(components, opts) {
    if (!components) return '';
    var title = (opts && opts.title) ? opts.title
      : tr('decision.explain_dim_title', '三维共振');
    return '<div class="de-dim">'
      + '<div class="de-dim-head">' + esc(title) + '</div>'
      + DIM_DEFS.map(function (d) {
        var v = (components && Object.prototype.hasOwnProperty.call(components, d.key))
          ? components[d.key] : null;
        if (v == null) {
          return '<div class="de-row de-row-miss">'
            + '<span class="de-nm">' + esc(tr(d.i18n, d.fallback)) + '</span>'
            + '<span class="de-track"><i style="width:0%;background:var(--muted)"></i></span>'
            + '<span class="de-val" style="color:var(--muted)">—</span>'
            + '</div>';
        }
        var color = v >= 55 ? 'var(--up)' : v <= 45 ? 'var(--down)' : 'var(--muted)';
        return '<div class="de-row">'
          + '<span class="de-nm">' + esc(tr(d.i18n, d.fallback)) + '</span>'
          + '<span class="de-track"><i style="width:' + Math.max(0, Math.min(100, v)) + '%;background:' + color + '"></i></span>'
          + '<span class="de-val" style="color:' + color + '">' + v.toFixed(1) + '</span>'
          + '</div>';
      }).join('')
      + '</div>';
  }

  /* ───────────────── CSS 自注入 ───────────────── */

  var CSS = [
    /* 综合指数拆解 */
    '.de-breakdown { margin: 12px 0; padding: 10px 12px; border-radius: 10px;',
    '  border: 1px solid var(--border); background: var(--card-bg, transparent); }',
    '.de-bd-head { font-size: 11.5px; color: var(--muted); margin-bottom: 8px; font-weight: 600; }',
    '.de-row { display: grid; grid-template-columns: 64px 1fr 44px 56px 80px; gap: 8px;',
    '  align-items: center; font-size: 12.5px; margin-bottom: 6px; }',
    '.de-row .de-nm { color: var(--muted); }',
    '.de-row .de-track { display: block; height: 8px; border-radius: 4px;',
    '  background: var(--bg); border: 1px solid var(--border); overflow: hidden; }',
    '.de-row .de-track i { display: block; height: 100%; }',
    '.de-row .de-val { text-align: right; font-weight: 600; }',
    '.de-row .de-wt { text-align: right; color: var(--muted); font-size: 11.5px; }',
    '.de-row .de-contrib { text-align: right; font-size: 12px; font-weight: 600; }',
    '.de-row.de-row-miss { opacity: .72; }',
    '.de-formula { margin-top: 8px; padding-top: 8px; border-top: 1px dashed var(--border);',
    '  font-size: 11.5px; color: var(--muted); line-height: 1.65; }',
    '.de-formula b { color: var(--text); }',
    /* 对比卡 */
    '.de-compare { margin: 10px 0; padding: 10px 12px; border-radius: 10px;',
    '  background: var(--chip-dim-bg); border: 1px solid var(--chip-dim-bd);',
    '  font-size: 13px; display: flex; flex-wrap: wrap; gap: 10px; align-items: baseline; }',
    '.de-cmp-k { font-weight: 600; color: var(--text); }',
    '.de-cmp-cur, .de-cmp-sug { font-size: 12.5px; color: var(--muted); }',
    '.de-cmp-cur b, .de-cmp-sug b { color: var(--text); margin-left: 4px; }',
    '.de-cmp-delta { font-weight: 600; margin-left: auto; }',
    /* tooltip */
    '.de-tip { padding: 8px 10px; font-size: 12px; line-height: 1.7;',
    '  background: var(--card-bg, #1f2329); color: var(--text);',
    '  border: 1px solid var(--border); border-radius: 8px;',
    '  box-shadow: 0 4px 12px rgba(0,0,0,.18); max-width: 320px; }',
    '.de-tip-row + .de-tip-row { margin-top: 4px; padding-top: 4px; border-top: 1px dashed var(--border); }',
    /* 三维条形图（紧凑） */
    '.de-dim { margin: 10px 0; padding: 8px 12px; border-radius: 8px;',
    '  background: var(--bg); border: 1px solid var(--border); }',
    '.de-dim-head { font-size: 11.5px; color: var(--muted); margin-bottom: 6px; font-weight: 600; }',
    '.de-dim .de-row { grid-template-columns: 64px 1fr 44px; gap: 8px; margin-bottom: 4px; }'
  ].join('\n');

  function ensureStyle() {
    if (document.getElementById('decisionExplainerStyle')) return;
    var s = document.createElement('style');
    s.id = 'decisionExplainerStyle';
    s.textContent = CSS;
    document.head.appendChild(s);
  }

  /* ───────────────── 公开 API ───────────────── */

  window.PM_DecisionExplainer = {
    breakdownRows: breakdownRows,
    renderBreakdown: renderBreakdown,
    compareCard: compareCard,
    tooltipFor: tooltipFor,
    renderTooltip: renderTooltip,
    dimensionBars: dimensionBars,
    /* 给 synthesis-card / portfolio 调：挂 tooltip hover 监听 */
    attachTooltip: function (anchorEl, action, decision) {
      if (!anchorEl) return;
      var tipHtml = renderTooltip(action, decision);
      if (!tipHtml) return;
      var tip = document.createElement('div');
      tip.className = 'de-tip';
      tip.innerHTML = tipHtml;
      tip.style.position = 'absolute';
      tip.style.display = 'none';
      tip.style.zIndex = '9999';
      document.body.appendChild(tip);
      var showTip = function (e) {
        tip.style.display = 'block';
        var r = anchorEl.getBoundingClientRect();
        tip.style.left = (window.scrollX + r.left) + 'px';
        tip.style.top = (window.scrollY + r.bottom + 6) + 'px';
        e && e.stopPropagation();
      };
      var hideTip = function () { tip.style.display = 'none'; };
      anchorEl.addEventListener('mouseenter', showTip);
      anchorEl.addEventListener('mouseleave', hideTip);
      anchorEl.addEventListener('focus', showTip);
      anchorEl.addEventListener('blur', hideTip);
    },
    ensureStyle: ensureStyle
  };

  /* 自动挂载：仅注入样式，渲染由 synthesis-card / portfolio 主动调用 */
  function boot() {
    ensureStyle();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot);
  } else {
    boot();
  }
})();