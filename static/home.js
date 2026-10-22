/*!
 * static/home.js — V0.98 C4 场景化首页数据加载
 *
 * 8 端点并发拉（Promise.allSettled 一个挂不影响其他）：
 * 1. /api/v1/market/gold        → hero 金价 chip
 * 2. /api/v1/market/freshness   → hero 时效 chip
 * 3. /api/v1/news-feed/items?days=2&limit=20 → 底部今日要闻 Top 20（V0.102 readhub 财经流）
 * 4. /api/v1/news-feed/status   → 今日要闻标题旁 chip（last_refresh + 24h 新增）
 * 5. /api/v1/news-feed/daily    → 今日要闻按 BJT 日聚合摘要行（V0.107）
 * 6. /api/v1/market/gold/trend  → 贵金属卡 1 金价走势（V0.115.0）
 * 7. /api/v1/market/gold/etf-quote + gram-quote → 卡 1 的 ETF / 克价副行
 * 8. /api/v1/market/gold/inventory → 贵金属卡 2 COMEX 库存（V0.115.0 新端点）
 * 9. /api/v1/central-bank/purchases → 贵金属卡 3 央行购金（V0.115.0）
 *
 * 设计纪律（memory）：
 * - i18n-init-await：等待 i18n.ready 后再渲染（防 undefined 注入）
 * - frontend-undefined-rendering：所有字符串用 textContent（防 XSS）
 * - 不伪造数据：失败显示 "--" + toast 兜底
 * - V0.102：今日要闻换为 readhub 财经流（语义更对：section 标题「今日要闻」对应外部新闻，
 *   而非用户自己的消息面打分记录；后者保留在 /news 页）
 * - V0.115.0：三个「取不到」的判定条件都读**后端真实存在的字段**。原先 hero 两个
 *   chip 读的是 `.price` / `.overall_status`，后端压根不返回这两个键，于是
 *   `typeof undefined === 'number'` 恒不成立，两个 chip 从上线起一直停在「--」，
 *   看上去像「今天没取到数据」。字段名对不上是静默失效最难查的一类。
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

  // ── 3. 并发拉 8 个端点（allSettled = 一个挂不影响其他） ──
  // V0.107：+ 1 个 daily 聚合（O(1) 行替代实时 GROUP BY）
  // V0.115.0：+ 3 个贵金属走势端点（金价趋势 / ETF 报价 / 库存 / 央行购金）
  const bjtToday = (() => {
    const d = new Date();
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
  })();
  const getJSON = (url) =>
    fetch(url, { headers: { accept: 'application/json' } })
      .then((r) => (r.ok ? r.json() : null))
      .catch(() => null);
  const [
    gold, fresh, headlines, headStatus, daily,
    goldTrend, goldEtf, goldGram, goldInv, goldCb,
  ] = await Promise.allSettled([
    getJSON('/api/v1/market/gold'),
    getJSON('/api/v1/market/freshness'),
    // V0.102：今日要闻换为 readhub 财经新闻流（最近 2 天 + 5 条）
    getJSON('/api/v1/news-feed/items?days=2&limit=20'),
    getJSON('/api/v1/news-feed/status'),
    // V0.107：按 BJT 日聚合
    getJSON(`/api/v1/news-feed/daily?date=${bjtToday}`),
    // V0.115.0 贵金属走势三卡
    getJSON('/api/v1/market/gold/trend?days=60&target=ny&interval=D'),
    getJSON('/api/v1/market/gold/etf-quote'),
    getJSON('/api/v1/market/gold/gram-quote'),
    getJSON('/api/v1/market/gold/inventory?days=90'),
    getJSON('/api/v1/central-bank/purchases'),
  ]);

  // ── 4. 渲染金价 chip ──
  // ⚠ V0.115.0 修：原先读 `gold.value.price` 和 `gold.value.currency` ——
  // GoldQuoteOut **两个字段都没有**（是 `price_usd`，且不带 currency）。
  // 判断 `typeof undefined === 'number'` 永远不成立 ⇒ 这个 chip 从上线起
  // 一直显示「金价 --」，看上去像「今天没取到数据」。真值实测：
  //   {"symbol":"XAU","price_usd":4094.5,"change_pct":-0.26,"updated_at":"..."}
  const goldEl = document.getElementById('homeGoldPrice');
  if (goldEl) {
    goldEl.classList.remove('is-loading');
    if (gold.status === 'fulfilled' && gold.value && typeof gold.value.price_usd === 'number') {
      goldEl.textContent = `金价 ${gold.value.price_usd.toFixed(2)} USD/oz`;
    } else {
      goldEl.textContent = '金价 --';
    }
  }

  // ── 5. 渲染时效 chip ──
  // ⚠ V0.115.0 修：原先读 `fresh.value.overall_status`，而 FreshnessOut
  // 只有 `server_time` / `markets` / `degraded` / `summary` —— 同样从不成立，
  // 「时效」chip 也一直在显示「时效 --」。改用真实存在的 `degraded` 布尔。
  const freshEl = document.getElementById('homeFreshness');
  if (freshEl) {
    freshEl.classList.remove('is-loading');
    if (fresh.status === 'fulfilled' && fresh.value && typeof fresh.value.degraded === 'boolean') {
      freshEl.textContent = fresh.value.degraded ? '🟡 降级' : '🟢 实时';
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
      headlines.value.items.slice(0, 20).forEach((item) => {
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
        // ⚠ V0.114.0：源没给链接时**不建 <a>**。原先 `item.url || '#'` 造出一个
        // 点得动却什么也不发生的假链接（金十/东财快讯实测 0/20 条有链接）——
        // V0.77.1 不给假 affordance。改渲染成不可点的纯文本，样式保持一致。
        let titleEl;
        if (item.url) {
          const a = document.createElement('a');
          a.className = 'home-news-title';
          a.textContent = title;
          a.href = item.url;
          a.target = '_blank';
          a.rel = 'noopener noreferrer';
          titleEl = a;
        } else {
          const span = document.createElement('span');
          span.className = 'home-news-title home-news-title-nourl';
          span.textContent = title;
          span.title = t('headlines.no_url_title', '该来源未提供原文链接');
          titleEl = span;
        }

        li.appendChild(timeSpan);
        li.appendChild(siteSpan);
        li.appendChild(titleEl);

        // V0.103 ⭐ 收藏按钮
        const favBtn = document.createElement('button');
        favBtn.type = 'button';
        favBtn.className = 'home-news-fav';
        favBtn.textContent = '☆';
        favBtn.title = '收藏';
        // ⚠ V0.114.0：多源后 external_id 不再全局唯一，必须连 source 一起用。
        // data-ext 保持字符串 —— 金十 id 是 20 位（≈2e19），超出 JS 安全整数
        // 范围 2249 倍，后端为此把它序列化成字符串，这里**不能** parseInt。
        const itemSource = item.source || 'readhub';
        favBtn.dataset.ext = String(item.external_id);
        favBtn.dataset.source = itemSource;
        favBtn.addEventListener('click', async (e) => {
          e.preventDefault();
          e.stopPropagation();
          if (favBtn.classList.contains('archived')) {
            location.href = '/favorites';
            return;
          }
          favBtn.disabled = true;
          try {
            const resp = await fetch('/api/v1/favorites/items', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({
                news_external_id: item.external_id,
                news_source: itemSource,
              }),
              credentials: 'same-origin',
            });
            if (resp.ok) {
              favBtn.classList.add('archived');
              favBtn.textContent = '★';
              if (window.PM_Toast) window.PM_Toast.show('已收藏', 'success');
            } else if (resp.status === 409) {
              favBtn.classList.add('archived');
              favBtn.textContent = '★';
              if (window.PM_Toast) window.PM_Toast.show('已收藏', 'success');
            } else {
              const err = await resp.text().catch(() => '');
              if (window.PM_Toast) window.PM_Toast.show('收藏失败: HTTP ' + resp.status, 'error');
              console.warn('fav failed', err);
            }
          } catch (err) {
            if (window.PM_Toast) window.PM_Toast.show('收藏失败: ' + err.message, 'error');
          } finally {
            favBtn.disabled = false;
          }
        });
        // 幂等：先查一次是否已收藏
        // ⚠ V0.114.0：原先写死 ?source=readhub。四源并存时会把别的源的收藏态
        // 画到这张卡片上（id 撞号时）。必须用这条自己条目的 source。
        fetch(`/api/v1/favorites/exists/${encodeURIComponent(String(item.external_id))}?source=${encodeURIComponent(itemSource)}`, { credentials: 'same-origin' })
          .then((r) => r.ok ? r.json() : null)
          .then((d) => {
            if (d && d.id) {
              favBtn.classList.add('archived');
              favBtn.textContent = '★';
            }
          })
          .catch(() => {});
        li.appendChild(favBtn);

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

  // ── 9. V0.107 渲染按 BJT 日聚合摘要（标题下方一行）──
  const dailyEl = document.getElementById('homeDaily');
  if (dailyEl) {
    if (daily.status === 'fulfilled' && daily.value && typeof daily.value.total_count === 'number') {
      const d = daily.value;
      const $fin = document.getElementById('homeDailyFinance');
      const $tech = document.getElementById('homeDailyTech');
      const $vc = document.getElementById('homeDailyVc');
      const $biz = document.getElementById('homeDailyBiz');
      const $other = document.getElementById('homeDailyOther');
      const $total = document.getElementById('homeDailyTotal');
      if ($fin) $fin.textContent = d.finance_count;
      if ($tech) $tech.textContent = d.tech_count;
      if ($vc) $vc.textContent = d.vc_count;
      if ($biz) $biz.textContent = d.biz_count;
      if ($other) $other.textContent = d.other_count;
      if ($total) $total.textContent = d.total_count;
      dailyEl.hidden = false;
    }
    // 当日为空时 daily.value=null → 隐藏整行（避免显示「0 财经 0 科技…」干扰）
  }

  // ══════════════════════════════════════════════════════════════
  //  V0.115.0 · 贵金属走势三卡（金价变化 / 黄金库存变化 / 央行购金变化）
  // ══════════════════════════════════════════════════════════════

  /** 折线图辅助：数值数组 → SVG path（线 + 面积）。
   *  返回 false 表示画不了（点少于 2、或全等值），调用方据此跳过而不是画一条
   *  贴着底边的假线 —— 那条线看着像「持平」，其实是「没有数据」。
   */
  const drawSpark = (svg, values) => {
    if (!svg) return false;
    const pts = (values || []).filter((v) => typeof v === 'number' && isFinite(v));
    if (pts.length < 2) return false;
    const W = 120;
    const H = 36;
    const min = Math.min.apply(null, pts);
    const max = Math.max.apply(null, pts);
    const span = max - min;
    // 全等值时给一个人造高度差，否则除零得到 NaN 坐标 → path 属性变成 "NaN"
    const y = (v) => (span === 0 ? H / 2 : H - ((v - min) / span) * (H - 4) - 2);
    const step = pts.length > 1 ? W / (pts.length - 1) : W;
    const coords = pts.map((v, i) => `${(i * step).toFixed(2)},${y(v).toFixed(2)}`);
    const line = `M${coords.join('L')}`;
    const area = `${line}L${W},${H}L0,${H}Z`;
    svg.textContent = '';
    const areaEl = document.createElementNS('http://www.w3.org/2000/svg', 'path');
    areaEl.setAttribute('d', area);
    areaEl.setAttribute('class', 'metal-spark-area');
    const lineEl = document.createElementNS('http://www.w3.org/2000/svg', 'path');
    lineEl.setAttribute('d', line);
    lineEl.setAttribute('class', 'metal-spark-line');
    svg.appendChild(areaEl);
    svg.appendChild(lineEl);
    return true;
  };

  /** 涨跌率 → 带色 class 的文本。null 一律显示「—」，绝不显示 0%（V0.78.0）。 */
  const chgClass = (v) => (typeof v !== 'number' || !isFinite(v) ? 'metal-flat'
    : v > 0 ? 'metal-up' : v < 0 ? 'metal-down' : 'metal-flat');
  const fmtChg = (v, suffix) => (typeof v === 'number' && isFinite(v)
    ? `${v > 0 ? '+' : ''}${v.toFixed(2)}${suffix || '%'}` : '—');

  /** 卡片不可用时的统一降级：值「—」+ 徽章说明原因。
   *  绝不用 0 或空字符串占位 —— 那是把「没数据」说成「数据是 0」。 */
  const markUnavailable = (cardId, badgeId, noteId, reason) => {
    const card = document.getElementById(cardId);
    const badge = document.getElementById(badgeId);
    const note = document.getElementById(noteId);
    if (!card) return;
    card.classList.add('is-empty');
    if (badge) {
      badge.classList.add('is-warn');
      badge.textContent = t('home.metals_unavailable', '暂不可用');
    }
    if (note) note.textContent = reason || '';
  };

  const setText = (id, text) => {
    const el = document.getElementById(id);
    if (el) el.textContent = text;
  };

  // ── 卡 1：金价变化 ──
  // ⚠ 三个口径不能混：XAU 是美元/盎司，518880 是元/份，Au99.99 是元/克。
  //   /market/gold 与 /market/gold/gram-quote 的价格字段**都叫** price_usd
  //   （gram 那个是元/克），/market/gold/etf-quote 才叫 price。
  {
    const q = gold.status === 'fulfilled' ? gold.value : null;
    const ok = q && typeof q.price_usd === 'number';
    if (ok) {
      setText('metalPriceValue', q.price_usd.toFixed(2));
      const chgEl = document.getElementById('metalPriceChg');
      if (chgEl) {
        chgEl.className = `metal-chg ${chgClass(q.change_pct)}`;
        chgEl.textContent = fmtChg(q.change_pct);
      }
      setText('metalPriceBadge', t('home.metals_xau', '纽约金 XAU'));
      setText('metalPriceNote', (q.updated_at || '').slice(0, 10));
    } else {
      markUnavailable('metalCardPrice', 'metalPriceBadge', 'metalPriceNote',
        t('home.metals_price_fail', '金价取数失败'));
    }

    const etf = goldEtf.status === 'fulfilled' ? goldEtf.value : null;
    setText('metalPriceEtf', etf && typeof etf.price === 'number'
      ? `${etf.price.toFixed(3)} (${fmtChg(etf.change_pct)})` : '—');
    const gram = goldGram.status === 'fulfilled' ? goldGram.value : null;
    setText('metalPriceGram', gram && typeof gram.price_usd === 'number'
      ? `${gram.price_usd.toFixed(2)} (${fmtChg(gram.change_pct)})` : '—');

    const trend = goldTrend.status === 'fulfilled' ? goldTrend.value : null;
    const closes = trend && Array.isArray(trend.points)
      ? trend.points.map((p) => p.close)
      : [];
    drawSpark(document.getElementById('metalPriceSpark'), closes);
  }

  // ── 卡 2：黄金库存变化（COMEX）──
  {
    const inv = goldInv.status === 'fulfilled' ? goldInv.value : null;
    const ok = inv && typeof inv.latest_tonnes === 'number' && Array.isArray(inv.points);
    if (ok) {
      setText('metalInvValue', inv.latest_tonnes.toFixed(2));
      // 主变化率取 1y —— COMEX 去库存在实务上被解读为近月合约支撑增强的信号，
      // 是这张卡最该被一眼看到的信息。1y 无基线时退回 1m。
      const by = {};
      (inv.changes || []).forEach((c) => { by[c.window] = c; });
      const main = (by['1y'] && typeof by['1y'].change_pct === 'number')
        ? by['1y'] : (by['1m'] || {});
      const chgEl = document.getElementById('metalInvChg');
      if (chgEl) {
        chgEl.className = `metal-chg ${chgClass(main.change_pct)}`;
        chgEl.textContent = `${t('home.metals_win_1y', '1 年')} ${fmtChg(main.change_pct)}`;
      }
      setText('metalInv1w', fmtChg(by['1w'] && by['1w'].change_pct));
      setText('metalInv1m', fmtChg(by['1m'] && by['1m'].change_pct));
      setText('metalInv1y', fmtChg(by['1y'] && by['1y'].change_pct));
      setText('metalInvBadge', t('home.metals_inv_comex', 'COMEX 库存'));
      // ⚠ 数据截止日必须显示：源是日频，周末/停更时最新观测会比今天早 2-3 天，
      //   不标出来用户会以为这就是实时值。
      setText('metalInvNote', `${t('home.metals_as_of', '数据截止')} ${inv.as_of || '—'}`);
      drawSpark(document.getElementById('metalInvSpark'),
        (inv.points || []).map((p) => p.tonnes));
    } else {
      markUnavailable('metalCardInv', 'metalInvBadge', 'metalInvNote',
        t('home.metals_inv_fail', '库存取数失败'));
    }
  }

  // ── 卡 3：央行购金变化（WGC Gold Demand Trends）──
  {
    const cb = goldCb.status === 'fulfilled' ? goldCb.value : null;
    // 全球合计行的 country_iso 固定是 WGC_AGGR；WGC 每季都发合计行，
    // 所以这里能拿到一条连续的季度序列（实测 50 季）。
    const agg = cb && Array.isArray(cb.items)
      ? cb.items.filter((i) => i.country_iso === 'WGC_AGGR')
      : [];
    if (agg.length > 0) {
      const latest = agg[0];  // /purchases 按 quarter 倒序
      setText('metalCbValue', `${latest.tonnes_net > 0 ? '+' : ''}${latest.tonnes_net.toFixed(1)}`);
      const prev = agg[1];
      const chgEl = document.getElementById('metalCbChg');
      if (chgEl) {
        if (prev && typeof prev.tonnes_net === 'number') {
          // 季度净购金**没有涨跌率**这个天然口径（基期常常接近 0 或为负，
          // 百分比会放大成误导性的巨值）。这里直接显示两季的吨数差。
          const delta = latest.tonnes_net - prev.tonnes_net;
          chgEl.className = `metal-chg ${chgClass(delta)}`;
          chgEl.textContent = `${t('home.metals_cb_qoq', '较上季')} ${delta > 0 ? '+' : ''}${delta.toFixed(1)} 吨`;
        } else {
          chgEl.className = 'metal-chg metal-flat';
          chgEl.textContent = t('home.metals_cb_qoq_na', '无上季可比');
        }
      }
      const sum = cb.summary || {};
      setText('metalCbT12m', `${(sum.t12m_total || 0).toFixed(1)} 吨`);
      setText('metalCbCountries', `${sum.country_count || 0}`);
      setText('metalCbBadge', latest.quarter);
      setText('metalCbNote',
        `${t('home.metals_as_of', '数据截止')} ${sum.latest_data_quarter || latest.quarter}`);
      // 倒序 → 画图要升序（折返线看着像暴跌又暴涨）
      const series = agg.slice(0, 12).reverse().map((i) => i.tonnes_net);
      drawSpark(document.getElementById('metalCbSpark'), series);
    } else {
      markUnavailable('metalCardCb', 'metalCbBadge', 'metalCbNote',
        t('home.metals_cb_fail', '央行购金取数失败'));
    }
  }

  // ── 10. 贵金属区总状态 chip ──
  {
    const chip = document.getElementById('homeMetalsChip');
    if (chip) {
      chip.classList.remove('is-loading');
      const cards = document.querySelectorAll('.metal-card');
      const okCount = cards.length - document.querySelectorAll('.metal-card.is-empty').length;
      chip.textContent = `${okCount}/${cards.length}`;
      if (okCount < cards.length) chip.classList.add('is-warn');
    }
  }
})();
