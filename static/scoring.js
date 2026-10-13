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
    };
  }

  async function refresh() {
    const p = getParams();
    await Promise.all([
      loadSummary(p),
      loadTagStats(p),
      loadHitStats(p),
      loadList(p),
    ]);
  }

  async function loadSummary(p) {
    const url = `${API_BASE}/summary?from=${p.from}&to=${p.to}&group_by=${p.group_by}${p.tag ? '&tag=' + encodeURIComponent(p.tag) : ''}`;
    const data = await fetchJson(url);
    renderSummaryTable(data);
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
  function renderSummaryTable(data) {
    const el = document.getElementById('summaryTable');
    if (!data.buckets || data.buckets.length === 0) {
      el.innerHTML = `<div class="empty">${T('scoring.empty', '暂无打分数据')}</div>`;
      return;
    }
    let html = '<table><thead><tr>';
    html += `<th>${T('report.cover_period', '期间')}</th>`;
    html += `<th>${T('scoring.trend_index_mean', '综合指数均值')}</th>`;
    html += `<th>${T('scoring.trend_index_median', '综合指数中位')}</th>`;
    html += `<th>${T('scoring.news_index_mean', '消息面均值')}</th>`;
    html += `<th>${T('scoring.hit_rate_t1', 'T+1 命中率')}</th>`;
    html += `<th>${T('scoring.hit_rate_t3', 'T+3 命中率')}</th>`;
    html += `<th>${T('scoring.hit_rate_t5', 'T+5 命中率')}</th>`;
    html += `<th>${T('scoring.up_days', '涨')}</th>`;
    html += `<th>${T('scoring.down_days', '跌')}</th>`;
    html += `<th>${T('scoring.sideways_days', '横盘')}</th>`;
    html += '</tr></thead><tbody>';
    for (const b of data.buckets) {
      html += '<tr>';
      html += `<td>${b.period}</td>`;
      html += `<td class="num">${fmt(b.trend_index_mean, 1)}</td>`;
      html += `<td class="num">${fmt(b.trend_index_median, 1)}</td>`;
      html += `<td class="num">${fmt(b.news_index_mean, 1)}</td>`;
      html += `<td class="num">${fmtPct(b.hit_rate_t1)}</td>`;
      html += `<td class="num">${fmtPct(b.hit_rate_t3)}</td>`;
      html += `<td class="num">${fmtPct(b.hit_rate_t5)}</td>`;
      html += `<td class="num">${b.up_days}</td>`;
      html += `<td class="num">${b.down_days}</td>`;
      html += `<td class="num">${b.sideways_days}</td>`;
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
  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
