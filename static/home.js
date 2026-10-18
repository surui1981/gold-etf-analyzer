/*!
 * static/home.js — V0.98 C4 场景化首页数据加载
 *
 * 4 端点并发拉（Promise.allSettled 一个挂不影响其他）：
 * 1. /api/v1/market/gold        → hero 金价 chip
 * 2. /api/v1/market/freshness   → hero 时效 chip
 * 3. /api/v1/news-feed/items?days=2&limit=5 → 底部今日要闻 Top 5（V0.102 readhub 财经流）
 * 4. /api/v1/news-feed/status   → 今日要闻标题旁 chip（last_refresh + 24h 新增）
 *
 * 设计纪律（memory）：
 * - i18n-init-await：等待 i18n.ready 后再渲染（防 undefined 注入）
 * - frontend-undefined-rendering：所有字符串用 textContent（防 XSS）
 * - 不伪造数据：失败显示 "--" + toast 兜底
 * - V0.102：今日要闻换为 readhub 财经流（语义更对：section 标题「今日要闻」对应外部新闻，
 *   而非用户自己的消息面打分记录；后者保留在 /news 页）
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

  // ── 3. 并发拉 4 个端点（allSettled = 一个挂不影响其他） ──
  const [gold, fresh, headlines, headStatus] = await Promise.allSettled([
    fetch('/api/v1/market/gold', { headers: { accept: 'application/json' } })
      .then((r) => (r.ok ? r.json() : null))
      .catch(() => null),
    fetch('/api/v1/market/freshness', { headers: { accept: 'application/json' } })
      .then((r) => (r.ok ? r.json() : null))
      .catch(() => null),
    // V0.102：今日要闻换为 readhub 财经新闻流（最近 2 天 + 5 条）
    fetch('/api/v1/news-feed/items?days=2&limit=5', { headers: { accept: 'application/json' } })
      .then((r) => (r.ok ? r.json() : null))
      .catch(() => null),
    fetch('/api/v1/news-feed/status', { headers: { accept: 'application/json' } })
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

  // ── 7. 渲染今日要闻 Top 5（V0.102：readhub 财经流）──
  const newsListEl = document.getElementById('homeNewsList');
  if (newsListEl) {
    if (
      headlines.status === 'fulfilled' &&
      headlines.value &&
      Array.isArray(headlines.value.items) &&
      headlines.value.items.length > 0
    ) {
      newsListEl.textContent = ''; // 清空 skeleton
      headlines.value.items.slice(0, 5).forEach((item) => {
        const li = document.createElement('li');

        // 时间（HH:MM BJT）
        const pubDate = item.publish_date ? new Date(item.publish_date) : null;
        const hh = pubDate && !isNaN(pubDate.getTime())
          ? String(pubDate.getHours()).padStart(2, '0')
          : '';
        const mm = pubDate && !isNaN(pubDate.getTime())
          ? String(pubDate.getMinutes()).padStart(2, '0')
          : '';
        const timeSpan = document.createElement('span');
        timeSpan.className = 'home-news-date';
        timeSpan.textContent = hh ? `${hh}:${mm}` : '--';

        // 来源站（badge）
        const site = (item.site_name || '').toString();
        const siteSpan = document.createElement('span');
        siteSpan.className = 'home-news-site';
        siteSpan.textContent = site;

        // 标题（点击新 tab 跳原文）
        const title = (item.title || '').toString();
        const titleAnchor = document.createElement('a');
        titleAnchor.className = 'home-news-title';
        titleAnchor.textContent = title;
        titleAnchor.href = item.url || '#';
        titleAnchor.target = '_blank';
        titleAnchor.rel = 'noopener noreferrer';

        li.appendChild(timeSpan);
        li.appendChild(siteSpan);
        li.appendChild(titleAnchor);
        newsListEl.appendChild(li);
      });
    } else {
      // 失败 / 空：清空 skeleton，渲染中性占位
      newsListEl.textContent = '';
      const li = document.createElement('li');
      li.className = 'home-news-error';
      li.textContent = t('home.news_empty', '暂无今日要闻');
      newsListEl.appendChild(li);
      if (window.PM_Toast) {
        window.PM_Toast.warn(t('home.news_load_fail', '今日要闻加载失败'), { duration: 3000 });
      }
    }
  }

  // ── 8. 渲染今日要闻 section 标题旁状态 chip（V0.102 新增）──
  const headChipEl = document.getElementById('homeHeadlinesChip');
  if (headChipEl) {
    headChipEl.classList.remove('is-loading');
    if (
      headStatus.status === 'fulfilled' &&
      headStatus.value &&
      typeof headStatus.value.total_items === 'number'
    ) {
      const total = headStatus.value.total_items;
      const last24 = headStatus.value.last_24h_count || 0;
      headChipEl.textContent = `📰 ${total} 条 · 24h +${last24}`;
      // V0.84 降级：DB 完全空 → amber
      if (total === 0) headChipEl.classList.add('is-warn');
    } else {
      headChipEl.textContent = '📰 --';
    }
  }
})();
