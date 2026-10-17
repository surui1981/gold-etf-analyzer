/*!
 * static/home.js — V0.98 C4 场景化首页数据加载
 *
 * 6 端点并发拉（Promise.allSettled 一个挂不影响其他）：
 * 1. /api/v1/market/gold → hero 金价 chip
 * 2. /api/v1/market/freshness → hero 时效 chip
 * 3. /api/v1/news-score/history?limit=3 → 底部今日要闻 Top 3
 *    ⚠ 实际路由 prefix 是 news-score（不是 news）；前者会 404
 *
 * 设计纪律（memory）：
 * - i18n-init-await：等待 i18n.ready 后再渲染（防 undefined 注入）
 * - frontend-undefined-rendering：所有字符串用 textContent（防 XSS）
 * - 不伪造数据：失败显示 "--" + toast 兜底
 */
(async function () {
  'use strict';

  // ── 1. 等待 i18n 初始化 ──
  await new Promise((resolve) => {
    try {
      if (window.PM_I18N && typeof window.PM_I18N.ready?.then === 'function') {
        window.PM_I18N.ready.then(resolve).catch(resolve);
        return;
      }
    } catch (_) { /* fall through */ }
    // 兜底：监听 i18n:change 事件或超时 2s
    let done = false;
    const finish = () => { if (!done) { done = true; resolve(); } };
    document.addEventListener('i18n:change', finish, { once: true });
    setTimeout(finish, 2000);
  });

  // ── 2. 渲染所有 data-i18n 元素 ──
  const t = (key, fallback) => {
    try {
      const v = window.PM_I18N && window.PM_I18N.t && window.PM_I18N.t(key);
      if (v && typeof v === 'string') return v;
    } catch (_) { /* fall through */ }
    return fallback || key;
  };

  document.querySelectorAll('[data-i18n]').forEach((el) => {
    const key = el.getAttribute('data-i18n');
    el.textContent = t(key, el.textContent);
  });

  // ── 3. 并发拉 3 个端点（allSettled = 一个挂不影响其他） ──
  // 注意：新闻端点实际挂在 /api/v1/news-score/*（router prefix = "news-score"），
  // 不是 /api/v1/news/*。后者是 HTML 页静态路径（/static/news.html），已弃用。
  const [gold, fresh, news] = await Promise.allSettled([
    fetch('/api/v1/market/gold', { headers: { accept: 'application/json' } })
      .then((r) => (r.ok ? r.json() : null))
      .catch(() => null),
    fetch('/api/v1/market/freshness', { headers: { accept: 'application/json' } })
      .then((r) => (r.ok ? r.json() : null))
      .catch(() => null),
    fetch('/api/v1/news-score/history?limit=3', { headers: { accept: 'application/json' } })
      .then((r) => (r.ok ? r.json() : null))
      .catch(() => null),
  ]);

  // ── 4. 渲染金价 chip ──
  const goldEl = document.getElementById('homeGoldPrice');
  if (goldEl) {
    goldEl.classList.remove('is-loading');
    if (gold.status === 'fulfilled' && gold.value && typeof gold.value.price === 'number') {
      // GoldQuoteOut: price (XAU/USD), currency, updated_at
      const p = gold.value.price;
      const cur = gold.value.currency || 'USD';
      goldEl.textContent = `金价 ${p.toFixed(2)} ${cur}`;
    } else {
      goldEl.textContent = '金价 --';
    }
  }

  // ── 5. 渲染时效 chip ──
  const freshEl = document.getElementById('homeFreshness');
  if (freshEl) {
    freshEl.classList.remove('is-loading');
    if (fresh.status === 'fulfilled' && fresh.value && fresh.value.overall_status) {
      const status = fresh.value.overall_status;
      // FreshnessReport: overall_status (ok | degraded), markets dict
      const label = status === 'ok' ? '🟢 实时' : '🟡 延迟';
      freshEl.textContent = `时效 ${label}`;
    } else {
      freshEl.textContent = '时效 --';
    }
  }

  // ── 6. AI 配额 chip：项目暂未暴露 /ai/quota 端点（V0.97 仅在错误响应头返回） ──
  // 保留 DOM 占位以备 V0.98.x 接入；当前显示 "AI --"
  const quotaEl = document.getElementById('homeQuota');
  if (quotaEl) {
    quotaEl.classList.remove('is-loading');
    quotaEl.textContent = 'AI --';
  }

  // ── 7. 渲染今日要闻 Top 3 ──
  const newsListEl = document.getElementById('homeNewsList');
  if (newsListEl) {
    if (news.status === 'fulfilled' && news.value && Array.isArray(news.value.items) && news.value.items.length > 0) {
      newsListEl.textContent = ''; // 清空
      news.value.items.slice(0, 3).forEach((item) => {
        const li = document.createElement('li');
        // 防御：每个字段都可能缺失
        const date = (item.score_date || '').toString();
        const dir = item.direction || '';
        const score = (typeof item.score === 'number') ? `${item.score.toFixed(0)} 分` : '';
        const note = (item.notes || '').slice(0, 80);

        const dateSpan = document.createElement('span');
        dateSpan.className = 'home-news-date';
        dateSpan.textContent = date;

        const scoreSpan = document.createElement('strong');
        scoreSpan.textContent = score + (dir ? ` ${dir}` : '');

        const noteSpan = document.createElement('span');
        noteSpan.textContent = note ? ` — ${note}` : '';

        li.appendChild(dateSpan);
        li.appendChild(scoreSpan);
        li.appendChild(noteSpan);
        newsListEl.appendChild(li);
      });
    } else {
      // 失败 / 空：清空 skeleton，渲染中性占位
      newsListEl.textContent = '';
      const li = document.createElement('li');
      li.className = 'home-news-error';
      li.textContent = t('home.news_empty', '暂无最近消息面打分');
      newsListEl.appendChild(li);
      if (window.PM_Toast) {
        window.PM_Toast.warn(t('home.news_load_fail', '今日要闻加载失败'), { duration: 3000 });
      }
    }
  }
})();
