// V0.92.0 · 历史打分数据汇总
// 4 端点：
//   - GET /api/v1/scoring/summary?from=&to=&group_by=&tag=
//   - GET /api/v1/scoring/by-tag?from=&to=
//   - GET /api/v1/scoring/hit-stats?from=&to=&horizon=
//   - GET /api/v1/scoring  (list 范围，供日历视图取每日 4 指数)

(function () {
  'use strict';

  const API_BASE = '/api/v1/scoring';
  const T = (key, fallback) => (window.I18n ? I18n.t(key) : null) || fallback || key;

  function init() {
    // 默认范围：近 90 天
    const today = new Date();
    const from = new Date(today.getTime() - 90 * 86400000);
    document.getElementById('fromDate').value = from.toISOString().slice(0, 10);
    document.getElementById('toDate').value = today.toISOString().slice(0, 10);

    // 填充 tag 下拉
    populateTagFilter();

    // Tab 切换（按钮 role="tab" + aria-selected，与 login.html 风格一致）
    document.querySelectorAll('[role="tab"]').forEach((t) => {
      t.addEventListener('click', () => switchTab(t.dataset.tab));
    });

    document.getElementById('refreshBtn').addEventListener('click', refresh);
    refresh();
  }

  function populateTagFilter() {
    const sel = document.getElementById('tagFilter');
    const tags = [
      '美元指数', '美债收益率', '实际利率', '通胀预期', '美联储政策',
      '央行购金', '地缘风险', '避险情绪', 'ETF资金流', '人民币汇率',
      '技术面', '投行观点',
    ];
    tags.forEach((t) => {
      const opt = document.createElement('option');
      opt.value = t;
      opt.textContent = t;
      sel.appendChild(opt);
    });
  }

  function switchTab(tab) {
    document.querySelectorAll('[role="tab"]').forEach((t) =>
      t.setAttribute('aria-selected', t.dataset.tab === tab ? 'true' : 'false')
    );
    document.querySelectorAll('.tab-panel').forEach((p) => p.classList.toggle('active', p.id === 'panel-' + tab));
  }

  function getParams() {
    return {
      from: document.getElementById('fromDate').value,
      to: document.getElementById('toDate').value,
      tag: document.getElementById('tagFilter').value || null,
      group_by: document.getElementById('groupBy').value,
      horizon: document.getElementById('horizon').value,
      // V0.92.1 hotfix：行级命中筛选（默认 "all"）
      hit: document.getElementById('hitFilter').value,
    };
  }

  async function refresh() {
    const p = getParams();
    await Promise.all([
      loadSummary(p),
      loadTagStats(p),
      loadHitStats(p),
      loadList(p),
      // V0.94.0：verdict 卡随 toDate 联动（取区间末端，便于查看任意一天）
      loadVerdict(p.to),
    ]);
  }

  async function loadSummary(p) {
    // V0.92.1 hotfix：追加 hit / horizon 参数，命中筛选行级过滤
    const params = new URLSearchParams({
      from: p.from,
      to: p.to,
      group_by: p.group_by,
      horizon: p.horizon,
      hit: p.hit,
    });
    if (p.tag) params.set('tag', p.tag);
    const data = await fetchJson(`${API_BASE}/summary?${params.toString()}`);
    renderSummaryTable(data, p);
  }

  async function loadTagStats(p) {
    const data = await fetchJson(`${API_BASE}/by-tag?from=${p.from}&to=${p.to}`);
    renderTagTable(data);
  }

  async function loadHitStats(p) {
    const data = await fetchJson(`${API_BASE}/hit-stats?from=${p.from}&to=${p.to}&horizon=${p.horizon}`);
    renderHitStats(data, p.horizon);
  }

  async function loadList(p) {
    const data = await fetchJson(`${API_BASE}?from=${p.from}&to=${p.to}`);
    renderCalendar(data);
  }

  // V0.94.0：预测评估卡
  async function loadVerdict(targetDate) {
    if (!targetDate) return;
    const data = await fetchJson(`${API_BASE}/verdict?date=${targetDate}`);
    renderVerdict(data);
  }

  function renderVerdict(data) {
    const el = document.getElementById('verdictBody');
    if (!el) return;
    if (!data || data.no_score) {
      el.innerHTML = `<div class="verdict-no-score">${T('scoring.verdict_no_score', '暂无打分数据（先做 capture_today）')}</div>`;
      return;
    }

    // 顶部：日期 + 你的预测 + 置信度 + 依据
    const dirMap = {
      bullish: { cn: T('scoring.verdict_call_bullish', '看多'), cls: 'bullish' },
      bearish: { cn: T('scoring.verdict_call_bearish', '看空'), cls: 'bearish' },
      neutral: { cn: T('scoring.verdict_call_neutral', '看平'), cls: 'neutral' },
    };
    const dirInfo = data.prediction_direction
      ? dirMap[data.prediction_direction] || { cn: data.prediction_direction, cls: 'neutral' }
      : { cn: T('scoring.verdict_no_score', '暂无研判'), cls: 'none' };
    const confStr = data.prediction_confidence != null
      ? T('scoring.verdict_confidence', '{score} 分').replace('{score}', Math.round(data.prediction_confidence))
      : '—';

    const basisHtml = (data.basis_tags || []).length
      ? `<div class="verdict-basis"><span data-i18n="scoring.verdict_basis">${T('scoring.verdict_basis', '依据')}</span>：${data.basis_tags.map(t => `<span class="basis-chip">${escapeHtml(t)}</span>`).join('')}</div>`
      : '';

    // 4 个 horizon 网格
    const verdictsHtml = (data.verdicts || []).map((v) => {
      const hLabel = v.horizon.toUpperCase();
      let statusCls, statusText, changeHtml = '';
      if (v.status === 'ready') {
        if (v.hit === true) {
          statusCls = 'hit';
          statusText = T('scoring.verdict_hit', '命中');
        } else {
          statusCls = 'miss';
          statusText = T('scoring.verdict_miss', '未命中');
        }
        if (v.actual_change_pct != null) {
          const pct = v.actual_change_pct;
          const sign = pct > 0 ? '+' : '';
          const cls = pct > 0 ? 'pos' : pct < 0 ? 'neg' : '';
          changeHtml = `<div class="vi-change ${cls}">${sign}${pct.toFixed(2)}%</div>`;
        }
      } else if (v.status === 'pending') {
        statusCls = 'pending';
        statusText = T('scoring.verdict_status_pending', '等待收盘');
        if (v.pending_until) {
          changeHtml = `<div class="vi-pending-until">→ ${v.pending_until}</div>`;
        }
      } else {
        statusCls = 'missing';
        statusText = T('scoring.verdict_status_missing', '缺数据');
      }
      return `<div class="verdict-item">
        <div class="vi-horizon">${hLabel}</div>
        <div class="vi-status ${statusCls}">${statusText}</div>
        ${changeHtml}
      </div>`;
    }).join('');

    el.innerHTML = `
      <div class="verdict-header">
        <div class="verdict-date">${data.target_date}</div>
        <div class="verdict-call-block">
          <span class="v-label" data-i18n="scoring.verdict_your_call">${T('scoring.verdict_your_call', '你的预测')}</span>
          <span class="verdict-call ${dirInfo.cls}">${dirInfo.cn}</span>
          <span class="verdict-confidence">${confStr}</span>
        </div>
        ${basisHtml}
      </div>
      <div class="verdict-grid">${verdictsHtml}</div>
      <div class="verdict-summary">${escapeHtml(data.summary || '')}</div>
    `;
  }

  async function fetchJson(url) {
    try {
      const r = await fetch(url, { credentials: 'same-origin' });
      if (!r.ok) {
        if (r.status === 404) return { rows: [], buckets: [], tags: [] };
        throw new Error(`HTTP ${r.status}: ${r.statusText}`);
      }
      return await r.json();
    } catch (err) {
      console.error('fetch failed:', url, err);
      return { rows: [], buckets: [], tags: [] };
    }
  }

  // ── 渲染：4 指数时序表 ──
  function renderSummaryTable(data, p) {
    const el = document.getElementById('summaryTable');
    if (!data.buckets || data.buckets.length === 0) {
      el.innerHTML = `<div class="empty">${T('scoring.empty', '暂无打分数据')}</div>`;
      return;
    }
    // V0.92.1 hotfix：注入"命中"列。
    //   - day 桶：bucket.hit=true→是（红） / false→否（绿） / null→待定（灰）
    //   - week/month 桶：bucket.hit=null（聚合无单值）→ 待定（灰）
    // 该列始终存在；group_by != day 时所有行均"待定"——提示用户切 day 才能看到命中颜色
    let html = '<table><thead><tr>';
    html += `<th>${T('report.cover_period', '期间')}</th>`;
    html += `<th>${T('scoring.trend_index_mean', '综合指数均值')}</th>`;
    html += `<th>${T('scoring.trend_index_median', '综合指数中位')}</th>`;
    html += `<th>${T('scoring.news_index_mean', '消息面均值')}</th>`;
    html += `<th>${T('scoring.hit_col', '命中')}</th>`;
    html += `<th title="${T('scoring.t0_desc', 'T+0 = 当日尾盘 vs 上一交易日（快速反馈，含盘内信息泄露）')}">${T('scoring.hit_rate_t0', 'T+0 命中率')}</th>`;
    html += `<th>${T('scoring.hit_rate_t1', 'T+1 命中率')}</th>`;
    html += `<th>${T('scoring.hit_rate_t3', 'T+3 命中率')}</th>`;
    html += `<th>${T('scoring.hit_rate_t5', 'T+5 命中率')}</th>`;
    html += `<th>${T('scoring.up_days', '涨')}</th>`;
    html += `<th>${T('scoring.down_days', '跌')}</th>`;
    // V0.95.0：横盘日数列替换为 NY 金美元/盎司收盘价（period-end snapshot）
    html += `<th>${T('scoring.gold_ny_close', 'NY金美元/盎司收盘')}</th>`;
    html += '</tr></thead><tbody>';
    for (const b of data.buckets) {
      const hitCls =
        b.hit === true ? 'hit-yes' : b.hit === false ? 'hit-no' : 'hit-pending';
      const hitText =
        b.hit === true
          ? T('scoring.hit_col_yes', '是')
          : b.hit === false
          ? T('scoring.hit_col_no', '否')
          : T('scoring.hit_col_pending', '待定');
      html += '<tr>';
      html += `<td>${b.period}</td>`;
      html += `<td class="num">${fmt(b.trend_index_mean, 1)}</td>`;
      html += `<td class="num">${fmt(b.trend_index_median, 1)}</td>`;
      html += `<td class="num">${fmt(b.news_index_mean, 1)}</td>`;
      html += `<td class="hit-cell ${hitCls}">${hitText}</td>`;
      html += `<td class="num">${fmtPct(b.hit_rate_t0)}</td>`;
      html += `<td class="num">${fmtPct(b.hit_rate_t1)}</td>`;
      html += `<td class="num">${fmtPct(b.hit_rate_t3)}</td>`;
      html += `<td class="num">${fmtPct(b.hit_rate_t5)}</td>`;
      html += `<td class="num">${b.up_days}</td>`;
      html += `<td class="num">${b.down_days}</td>`;
      // V0.95.0：NY 金美元/盎司收盘价 —— 2 位小数 + 千分位；缺数据显示 "—"
      html += `<td class="num">${b.gold_ny_close != null ? fmt2(b.gold_ny_close) : '—'}</td>`;
      html += '</tr>';
    }
    html += '</tbody></table>';
    el.innerHTML = html;
  }

  // ── 渲染：依据标签频次 ──
  function renderTagTable(data) {
    const el = document.getElementById('tagTable');
    if (!data.tags || data.tags.length === 0) {
      el.innerHTML = `<div class="empty">${T('scoring.empty', '暂无打分数据')}</div>`;
      return;
    }
    let html = '<table><thead><tr>';
    html += `<th>${T('scoring.tag_filter', '依据标签')}</th>`;
    html += `<th>${T('scoring.tag_count', '出现次数')}</th>`;
    html += `<th>${T('scoring.hit_rate_t1', 'T+1 命中率')}</th>`;
    html += `<th>${T('scoring.hit_rate_t3', 'T+3 命中率')}</th>`;
    html += `<th>${T('scoring.hit_rate_t5', 'T+5 命中率')}</th>`;
    html += '</tr></thead><tbody>';
    for (const t of data.tags) {
      html += '<tr>';
      html += `<td><span class="tag-chip">${escapeHtml(t.tag)}</span></td>`;
      html += `<td class="num">${t.count}</td>`;
      html += `<td class="num">${fmtPct(t.hit_rate_t1)}</td>`;
      html += `<td class="num">${fmtPct(t.hit_rate_t3)}</td>`;
      html += `<td class="num">${fmtPct(t.hit_rate_t5)}</td>`;
      html += '</tr>';
    }
    html += '</tbody></table>';
    el.innerHTML = html;
  }

  // ── 渲染：命中率分析 ──
  function renderHitStats(data, horizon) {
    const descEl = document.getElementById('hitDesc');
    const el = document.getElementById('hitStats');
    if (!data || data.sample_size === 0) {
      descEl.textContent = T('scoring.empty', '暂无打分数据');
      el.innerHTML = '';
      return;
    }
    descEl.textContent = `horizon=${horizon} · sample=${data.sample_size} · overall_hit_rate=${fmtPct(data.overall_hit_rate)}`;
    let html = '<div class="stat-grid">';
    for (const d of data.by_direction) {
      html += `<div class="stat"><div class="v">${fmtPct(d.hit_rate)}</div><div class="l">${escapeHtml(d.direction)} (${d.hit_count}/${d.total})</div></div>`;
    }
    html += '</div>';
    if (data.calibration && data.calibration.length > 0) {
      html += '<h3 style="font-size:13px; margin:14px 0 6px;">' + T('scoring.section_calibration', '分值校准') + '</h3>';
      html += '<table><thead><tr>';
      html += `<th>${T('scoring.score_bucket', '分值分箱')}</th>`;
      html += `<th>${T('scoring.tag_count', '次数')}</th>`;
      html += `<th>${T('scoring.tag_hit_rate', '命中率')}</th>`;
      html += '</tr></thead><tbody>';
      for (const c of data.calibration) {
        html += `<tr><td>${c.score_bucket}</td><td class="num">${c.total}</td><td class="num">${fmtPct(c.hit_rate)}</td></tr>`;
      }
      html += '</tbody></table>';
    }
    el.innerHTML = html;
  }

  // ── 渲染：日历视图（按月分组）──
  function renderCalendar(data) {
    const el = document.getElementById('calendarView');
    if (!data.rows || data.rows.length === 0) {
      el.innerHTML = `<div class="empty">${T('scoring.empty', '暂无打分数据')}</div>`;
      return;
    }
    const byMonth = {};
    for (const r of data.rows) {
      const m = r.date.slice(0, 7);
      if (!byMonth[m]) byMonth[m] = [];
      byMonth[m].push(r);
    }
    let html = '';
    for (const m of Object.keys(byMonth).sort().reverse()) {
      html += `<div class="cal-month">`;
      html += `<div class="cal-month-title">${m}</div>`;
      html += '<div class="cal-grid">';
      // 7 columns: 0=Mon, 6=Sun (ISO)
      // First day of month
      const [y, mo] = m.split('-').map(Number);
      const first = new Date(y, mo - 1, 1);
      // ISO weekday (Mon=1, Sun=7) → 0-indexed Mon-Sun
      const firstDow = (first.getDay() + 6) % 7;
      for (let i = 0; i < firstDow; i++) {
        html += '<div class="cal-cell empty"></div>';
      }
      const daysInMonth = new Date(y, mo, 0).getDate();
      const rowMap = {};
      for (const r of byMonth[m]) {
        const d = Number(r.date.slice(8, 10));
        rowMap[d] = r;
      }
      for (let d = 1; d <= daysInMonth; d++) {
        const r = rowMap[d];
        if (!r) {
          html += `<div class="cal-cell lv-missing"><div class="cal-day">${d}</div></div>`;
          continue;
        }
        const lvl = r.index_level || (r.trend_index != null ? levelOf(r.trend_index) : 'missing');
        const cls = r.trend_index == null ? 'lv-missing' : 'lv-' + lvl;
        const tr = r.trend_index != null ? r.trend_index.toFixed(0) : '—';
        html += `<div class="cal-cell ${cls}" title="${r.date} trend=${tr}"><div class="cal-day">${d}</div><div class="cal-trend">${tr}</div></div>`;
      }
      html += '</div></div>';
    }
    el.innerHTML = html;
  }

  function levelOf(idx) {
    if (idx >= 70) return 'strong_bullish';
    if (idx >= 55) return 'bullish';
    if (idx >= 45) return 'neutral';
    if (idx >= 30) return 'bearish';
    return 'strong_bearish';
  }

  function fmt(v, dec) {
    if (v == null) return '—';
    return Number(v).toFixed(dec);
  }
  function fmtPct(v) {
    if (v == null) return '—';
    return (v * 100).toFixed(1) + '%';
  }
  // V0.95.0：金额格式化（千分位 + 2 位小数）—— NY 金美元/盎司等美元报价
  function fmt2(v) {
    if (v == null) return '—';
    return Number(v).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  }
  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
