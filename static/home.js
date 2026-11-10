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
 * 10. /api/v1/reports/latest       → 「今日市场研究报告」入口（V0.125.0）
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
      // ⚠ V0.120.4 修：i18n.js 导出的是 **window.I18n**（含 ready / t / setLang），
      //   window.PM_I18N 不存在 ⇒ 这个 await 恒不成立 ⇒ 每次加载都白等 2 秒兜底，
      //   且**字典还没到**就渲染（非默认语言下 JS 拼的文案会落回中文）。
      const i18n = window.I18n;
      if (i18n && typeof i18n.ready?.then === 'function') {
        i18n.ready.then(resolve).catch(resolve);
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
  // ⚠ V0.120.4 修：原先读的是 `window.PM_I18N.t` —— 但 i18n.js 导出的对象叫
  //   **window.I18n**（`window.PM_I18N` 根本不存在，只有 `window.PM_I18N_ZH_CN`
  //   这种「字典本体」是全局的）。⇒ 这个条件恒为假 ⇒ **首页 JS 拼的所有文案
  //   一直回退到中文**：静态 markup 有 data-i18n（i18n.js 自己 apply，会翻译），
  //   JS 拼的（徽章/备注/结论）不翻译 ⇒ 切到 en-US 时中英混排。
  //   实测（V0.120.4 前置核查）：en-US 下 `.metal-title`="Gold Price"（已译）
  //   但 metalPriceBadge="纽约金 XAU"（没译）。
  // 修法：改读 window.I18n.t，并保留「字典里没这个 key → 用中文兜底」的语义
  //   （i18n.t 找不到 key 时返回 **key 字面量**，不是空串 —— 直接透传会把
  //   "home.metals_xau" 这种字面量渲染到页面上）。
  const t = (key, fallback, params) => {
    let s = null;
    try {
      const i18n = window.I18n;
      if (i18n && typeof i18n.t === 'function') {
        const v = i18n.t(key, params);
        // 字典里没这个 key ⇒ t() 返回 key 字面量 ⇒ 走中文兜底
        if (v && typeof v === 'string' && v !== key) s = v;
      }
    } catch (_) { /* fall through */ }
    if (s == null) s = fallback || key;
    // 兜底文案也要吃 params（否则 {score} 会原样留在页面上）
    if (params && typeof s === 'string') {
      s = s.replace(/\{(\w+)\}/g, (m, k) => (params[k] != null ? String(params[k]) : m));
    }
    return s;
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
    latestReport,
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
    // V0.125.0：最新上传的一份研报（首页「今日市场研究报告」入口）
    getJSON('/api/v1/reports/latest'),
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
        favBtn.title = t('headlines.fav_add', '收藏');
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
              if (window.PM_Toast) window.PM_Toast.show(t('favorites.toast_archived', '已收藏'), 'success');
            } else if (resp.status === 409) {
              favBtn.classList.add('archived');
              favBtn.textContent = '★';
              if (window.PM_Toast) window.PM_Toast.show(t('favorites.toast_archived', '已收藏'), 'success');
            } else {
              const err = await resp.text().catch(() => '');
              if (window.PM_Toast) window.PM_Toast.show(t('favorites.toast_load_failed', '收藏失败') + ': HTTP ' + resp.status, 'error');
              console.warn('fav failed', err);
            }
          } catch (err) {
            if (window.PM_Toast) window.PM_Toast.show(t('favorites.toast_load_failed', '收藏失败') + ': ' + err.message, 'error');
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

  // ══════════════════════════════════════════════════════════════
  //  V0.125.0 · 今日市场研究报告（首页直达最新一份上传的研报）
  // ══════════════════════════════════════════════════════════════

  /** 把后端的无时区时间串当 **UTC** 解析。
   *
   *  ⚠ 后端 `created_at` 来自 SQLite 的 `CURRENT_TIMESTAMP` —— 它是 **UTC**
   *    （实测：sqlite CURRENT_TIMESTAMP 与 `date -u` 逐秒相同），而 SQLAlchemy
   *    读回来是**无时区**的 naive datetime，Pydantic 序列化成
   *    "2026-11-08T22:15:34"（**不带 Z**）。
   *    `new Date("2026-11-08T22:15:34")` 按 ES2015 规范当作**本地时间**解析
   *    ⇒ 在 CST（UTC+8）机器上显示值比真实时刻**早 8 小时**。
   *    补 'Z' 才是对的。实测：报告 id=20 的真实上传时刻 = BJT 11-09 06:15，
   *    不补 'Z' 会显示成 11-08 22:15（/report-archive.js 的 fmtBjt 此前就是这个坑）。
   */
  const parseUtc = (s) => {
    if (!s) return null;
    const str = String(s);
    const hasTz = /(?:Z|[+-]\d{2}:?\d{2})$/i.test(str);
    const d = new Date(hasTz ? str : str + 'Z');
    return isNaN(d.getTime()) ? null : d;
  };

  /** 上传时间 → "YYYY-MM-DD HH:MM"（按浏览器本地时区 = 站点的 BJT 口径）。 */
  const fmtDateTime = (s) => {
    const d = parseUtc(s);
    if (!d) return '—';
    const p = (n) => String(n).padStart(2, '0');
    return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
  };

  /** 字节数 → 人类可读（与 report-archive.js 的 fmtSize 同一口径）。 */
  const fmtSize = (bytes) => {
    const n = Number(bytes) || 0;
    if (n < 1024) return `${n} B`;
    if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
    return `${(n / 1024 / 1024).toFixed(1)} MB`;
  };

  const renderReport = () => {
    const sec = document.getElementById('homeReport');
    const body = document.getElementById('homeReportBody');
    const chip = document.getElementById('homeReportChip');
    if (!sec || !body || !chip) return;
    chip.classList.remove('is-loading');

    // ⚠ 必须用 hasOwnProperty 判定「接口回来了」—— `latestReport.value` 为 null
    //   与「请求失败」在 allSettled 里长得一样（前者 fulfilled+null，后者 rejected）。
    const payload = latestReport.status === 'fulfilled' ? latestReport.value : null;
    const ok = payload && typeof payload === 'object'
      && Object.prototype.hasOwnProperty.call(payload, 'item');

    if (!ok) {
      // 取不到 ⇒ 明确说「加载失败」，**不**说「暂无报告」（那是把故障说成空库）
      sec.classList.add('is-empty');
      body.textContent = '';
      const p = document.createElement('p');
      p.className = 'home-report-empty';
      p.textContent = t('home.report_load_fail', '报告加载失败');
      body.appendChild(p);
      chip.textContent = '—';
      return;
    }

    sec.classList.remove('is-empty');
    body.textContent = '';
    const item = payload.item;

    if (!item) {
      // 真的没上传过（正常状态，不是故障）
      chip.textContent = '—';
      const p = document.createElement('p');
      p.className = 'home-report-empty';
      p.textContent = t('home.report_none', '还没有上传过报告 —— 去「报告存档」上传一份。');
      body.appendChild(p);
      return;
    }

    // chip = 报告自身日期（不是上传日）—— 用户要看的是「哪一天的研报」
    chip.textContent = item.report_date
      ? String(item.report_date).slice(0, 10)
      : t('home.report_no_date', '未填日期');

    const wrap = document.createElement('div');
    wrap.className = 'home-report-item';

    // ⚠ 标题即链接 → 报告本体。/content 的响应带 CSP sandbox（opaque origin），
    //   ⇒ 只能新标签页打开，不能 iframe、也不能 fetch 完塞 innerHTML。
    const viewUrl = item.view_url || `/api/v1/reports/${item.id}/content`;
    const title = document.createElement('a');
    title.className = 'home-report-title';
    title.textContent = item.title || '(未命名报告)';
    title.href = viewUrl;
    title.target = '_blank';
    title.rel = 'noopener noreferrer';
    wrap.appendChild(title);

    // meta：分类 · 大小 · 上传于
    const meta = document.createElement('div');
    meta.className = 'home-report-meta';
    if (item.category) {
      const cat = document.createElement('span');
      cat.className = 'cat';
      cat.textContent = item.category;
      meta.appendChild(cat);
    }
    const size = document.createElement('span');
    size.textContent = fmtSize(item.size_bytes);
    meta.appendChild(size);
    const up = document.createElement('span');
    up.textContent = t('home.report_uploaded', '上传于 {dt}', { dt: fmtDateTime(item.created_at) });
    meta.appendChild(up);
    wrap.appendChild(meta);

    // 摘要摘录（单行省略由 CSS 做；正文一律 textContent，不拼 HTML）
    if (item.summary) {
      const sum = document.createElement('p');
      sum.className = 'home-report-sum';
      sum.textContent = item.summary;
      wrap.appendChild(sum);
    }

    // CTA
    const cta = document.createElement('a');
    cta.className = 'home-report-cta';
    cta.textContent = t('home.report_view', '查看报告 →');
    cta.href = viewUrl;
    cta.target = '_blank';
    cta.rel = 'noopener noreferrer';
    wrap.appendChild(cta);

    body.appendChild(wrap);
  };

  // ══════════════════════════════════════════════════════════════
  //  贵金属三卡 + 状态 chip
  //  V0.120.4：抽成函数 —— 切换语言时要能整体重绘（i18n.js 的 apply 只管
  //  data-i18n 元素，JS 拼的徽章/备注不会被它翻译）。
  // ══════════════════════════════════════════════════════════════
  const renderMetals = () => {
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
      // V0.121.4：注明数据来源 —— 这个数是 WGC 的**全球合计**口径
      //   （含未披露国家的估算），与下方「覆盖国家」的已上报明细不是一个口径。
      setText('metalCbNote',
        `${t('home.metals_as_of', '数据截止')} ${sum.latest_data_quarter || latest.quarter}`
        + ` · ${t('home.metals_cb_source', '来源：世界黄金协会 GDT 全球合计')}`);
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
  };  // ← renderMetals 结束

  // ══════════════════════════════════════════════════════════════
  //  V0.120.4 · 综合评估结论块（hero 右栏）
  // ══════════════════════════════════════════════════════════════
  //
  // ⚠ **口径**：首页用 target=ny（纽约金 COMEX）⇒ 与 /static/trend.html 的
  //   「实时评估摘要」同源（实测 38.7）；而趋势页那张 synthesis-card 用的是
  //   target=etf（37.8，技术面口径不同）—— 两个数字别混，故卡片脚注写明口径。
  // ⚠ **index.summary 是服务端直出中文** ⇒ 非中文界面下会露馅，这里按
  //   components + face_weights 自己重算公式（照抄 synthesis-card.js 的 dimsFormula）。
  // ⚠ **权重用 face_weights**（实际生效：不可用面已剔除、权重归一化给其余面），
  //   face_weights_nominal 只用来标注「被剔除的那个面原本占多少」。
  // ⚠ **index.composed_by 恒为 "weighted"**（后端漏传，trend.py:657-665），
  //   真实值在顶层 tech_composed_by —— 别用 index.composed_by。
  const FACE_KEYS = {
    tech: 'trend.comp_tech',
    macro: 'trend.comp_macro',
    news: 'trend.comp_news',
    flow: 'trend.comp_flow',
  };
  const FACE_ORDER = ['tech', 'macro', 'news', 'flow'];
  const LEVEL_KEYS = {
    strong_up: 'trend.level_strong_up',
    up: 'trend.level_up',
    sideways: 'trend.level_sideways',
    down: 'trend.level_down',
    strong_down: 'trend.level_strong_down',
  };

  /** 方向 → 颜色/箭头/文案。阈值 55/45 与后端等级阈值同源
   *  （UP=55 / SIDEWAYS=45，见 src/app/schemas/thresholds.py），
   *  与 synthesis-card.js 的 dirMeta 同一口径。 */
  const dirMeta = (score) => {
    if (score >= 55) {
      return { color: 'var(--up)', arrow: '↑', text: t('home.idx_dir_bullish', '看多') };
    }
    if (score <= 45) {
      return { color: 'var(--down)', arrow: '↓', text: t('home.idx_dir_bearish', '看空') };
    }
    return { color: 'var(--muted)', arrow: '→', text: t('home.idx_dir_neutral', '中性') };
  };

  /** 因子明细：按 |contribution| 取前 N 条（相同时按权重排）。
   *  ⚠ 不能按后端返回的原始顺序取前 N —— 那个顺序不是「重要度」顺序。 */
  const topFactors = (list, n) => (Array.isArray(list) ? list.slice() : [])
    .sort((a, b) => {
      const ca = Math.abs(typeof a.contribution === 'number' ? a.contribution : 0);
      const cb = Math.abs(typeof b.contribution === 'number' ? b.contribution : 0);
      if (ca !== cb) return cb - ca;
      const wa = typeof a.weight === 'number' ? a.weight : 0;
      const wb = typeof b.weight === 'number' ? b.weight : 0;
      return wb - wa;
    })
    .slice(0, n);

  const renderVerdict = () => {
    const numEl = document.getElementById('hvNum');
    const badgeEl = document.getElementById('hvBadge');
    const sumEl = document.getElementById('hvSummary');
    const facesEl = document.getElementById('hvFaces');
    const factorsEl = document.getElementById('hvFactors');
    const scopeEl = document.getElementById('hvScope');
    const pendingEl = document.getElementById('hvPending');
    const degradedEl = document.getElementById('hvDegraded');
    if (!numEl || !facesEl) return;

    const trend = goldTrend.status === 'fulfilled' ? goldTrend.value : null;
    const idx = trend && trend.index ? trend.index : null;

    // 取数失败：显示「—」+ 一句说明 ——
    // ⚠ 绝不拿 0 或中性 50 冒充（V0.78.0 教训：没数据 ≠ 数据是 0/中性）
    if (!idx) {
      numEl.textContent = '—';
      numEl.style.color = 'var(--muted)';
      if (badgeEl) badgeEl.hidden = true;
      if (pendingEl) pendingEl.hidden = true;
      if (degradedEl) degradedEl.hidden = true;
      if (sumEl) sumEl.textContent = t('home.idx_fail', '综合指数取数失败，暂不显示');
      if (factorsEl) factorsEl.textContent = '';
      if (scopeEl) scopeEl.textContent = '';
      return;
    }

    const comps = idx.components || {};
    const faceW = idx.face_weights || {};
    const faceNominal = idx.face_weights_nominal || {};
    const score = typeof idx.score === 'number' ? idx.score : null;
    const dirColor = idx.direction === 'bullish' ? 'var(--up)'
      : idx.direction === 'bearish' ? 'var(--down)' : 'var(--muted)';

    // 大数字（score 可能是 null ⇒ 显示「—」，不显示 50）
    numEl.textContent = score != null ? score.toFixed(1) : '—';
    numEl.style.color = score != null ? dirColor : 'var(--muted)';

    // 等级徽章（走 i18n key —— 不抄 trend.html:615 那张硬编码中文表）
    if (badgeEl) {
      const lvKey = LEVEL_KEYS[idx.level];
      badgeEl.hidden = false;
      badgeEl.textContent = lvKey ? t(lvKey, idx.level || '—') : (idx.level || '—');
      badgeEl.style.background = dirColor;
    }

    // 消息面 pending（V0.100.0 同款）：未打分 ⇒ 整面剔除、权重归一化给其余面
    const news = trend.news || {};
    const newsScored = news.scored !== false;
    if (pendingEl) {
      if (!newsScored && score != null) {
        const n = typeof faceNominal.news === 'number'
          ? (faceNominal.news * 100).toFixed(0) : '—';
        pendingEl.hidden = false;
        pendingEl.textContent = t('trend.pending_chip', '消息面 pending');
        pendingEl.title = t('trend.pending_tooltip',
          '消息面尚未打分，综合指数按其余各面权重归一计算（暂未含消息面 {n}% 权重）', { n });
      } else {
        pendingEl.hidden = true;
        pendingEl.title = '';
      }
    }

    // 数据降级：琥珀 chip —— 用户可见路径上**不**显示红色失败框
    if (degradedEl) {
      degradedEl.hidden = trend.degraded !== true;
      if (trend.degraded === true) {
        degradedEl.textContent = t('home.idx_degraded', '部分数据降级');
        degradedEl.title = t('home.idx_degraded_hint', '部分行情源用了兜底值，结论仅供参考');
      }
    }

    // 说明：前端按 components + face_weights 重算公式（三语可用）
    const present = FACE_ORDER.filter((k) => typeof comps[k] === 'number');
    const formula = present
      .map((k) => `${t(FACE_KEYS[k], k)} ${comps[k].toFixed(1)}×${((faceW[k] || 0) * 100).toFixed(0)}%`)
      .join(' + ');
    const levelTxt = LEVEL_KEYS[idx.level]
      ? t(LEVEL_KEYS[idx.level], idx.level || '—') : (idx.level || '—');
    if (sumEl) {
      sumEl.textContent = t('home.idx_summary_fmt',
        '综合趋势评估指数 {score}/100，等级【{level}】；= {formula}',
        { score: score != null ? score.toFixed(1) : '—', level: levelTxt, formula: formula || '—' });
    }

    // 4 面分数条
    facesEl.textContent = '';
    FACE_ORDER.forEach((k) => {
      const row = document.createElement('div');
      row.className = 'hv-face';
      const nameEl = document.createElement('span');
      nameEl.className = 'hv-face-name';
      nameEl.textContent = t(FACE_KEYS[k], k);

      const bar = document.createElement('div');
      bar.className = 'hv-bar';
      const fill = document.createElement('i');
      const v = typeof comps[k] === 'number' ? comps[k] : null;
      const meta = v != null ? dirMeta(v) : null;
      fill.style.width = (v != null ? Math.max(0, Math.min(100, v)) : 0) + '%';
      fill.style.background = meta ? meta.color : 'var(--muted)';
      bar.appendChild(fill);

      const valEl = document.createElement('span');
      valEl.className = 'hv-face-val';
      if (v != null) {
        const b = document.createElement('b');
        b.textContent = v.toFixed(1);
        valEl.appendChild(b);
        valEl.appendChild(document.createTextNode(
          ` ${meta.arrow} ${((faceW[k] || 0) * 100).toFixed(0)}%`));
        row.title = `${t(FACE_KEYS[k], k)}：${v.toFixed(1)}/100 · ${meta.text}`
          + ` · 权重 ${((faceW[k] || 0) * 100).toFixed(0)}%`;
      } else {
        // 被剔除的面：显示它的**配置权重**并标「未计入」
        const nom = typeof faceNominal[k] === 'number' ? (faceNominal[k] * 100).toFixed(0) : '—';
        valEl.textContent = `— ${nom}%`;
        row.title = t('home.idx_face_excluded', '{face} 未计入（配置权重 {w}% 已剔除并归一化给其余面）',
          { face: t(FACE_KEYS[k], k), w: nom });
      }
      row.appendChild(nameEl);
      row.appendChild(bar);
      row.appendChild(valEl);
      facesEl.appendChild(row);
    });

    // 因子明细（4 面各取贡献最大的 3 条）
    if (factorsEl) {
      factorsEl.textContent = '';
      const factorGroups = [
        {
          key: 'tech',
          items: topFactors(trend.indicators, 3).map((i) => ({
            name: i.name || '—',
            value: i.value || i.detail || '—',
            tier: null,
          })),
        },
        {
          key: 'macro',
          items: topFactors(trend.macro && trend.macro.factors, 3).map((f) => ({
            name: f.name || f.key || '—',
            value: (f.value != null ? String(f.value) : '—') + (f.unit ? ` ${f.unit}` : ''),
            tier: f.tier,
          })),
        },
        {
          key: 'news',
          items: [],
          note: newsScored
            ? (news.note || t('home.idx_news_hint', '消息面来自你在「消息面评估」页的投行展望打分'))
            // ⚠ 不用 trend.news_pending_hint —— 那句写的是「去**下方**『今日消息面打分』」，
            //   「下方」是趋势页的说法；首页没有那个区块，会指错路。
            : t('home.idx_news_pending',
              '消息面未打分（{n}% 权重已剔除，不参与综合指数）',
              { n: typeof faceNominal.news === 'number'
                ? (faceNominal.news * 100).toFixed(0) : '—' }),
          link: { href: '/news', text: t('home.idx_news_goto', '去消息面评估 →') },
        },
        {
          key: 'flow',
          items: topFactors(trend.flow && trend.flow.factors, 3).map((f) => ({
            name: f.name || f.key || '—',
            value: (f.value != null ? String(f.value) : '—') + (f.unit ? ` ${f.unit}` : ''),
            tier: f.tier,
          })),
        },
      ];
      factorGroups.forEach((g) => {
        const gEl = document.createElement('div');
        gEl.className = 'hv-factor-group';
        const head = document.createElement('div');
        head.className = 'hv-factor-head';
        const gs = typeof comps[g.key] === 'number' ? comps[g.key].toFixed(1) : '—';
        head.textContent = `${t(FACE_KEYS[g.key], g.key)} · ${gs}`;
        gEl.appendChild(head);
        if (g.note) {
          const noteEl = document.createElement('div');
          noteEl.className = 'hv-factor';
          noteEl.textContent = g.note;
          gEl.appendChild(noteEl);
        }
        g.items.forEach((it) => {
          const row = document.createElement('div');
          row.className = 'hv-factor';
          const nm = document.createElement('span');
          nm.className = 'hv-factor-name';
          nm.textContent = it.name;
          nm.title = it.name;
          const vl = document.createElement('span');
          vl.className = 'hv-factor-val';
          vl.textContent = it.value;
          vl.title = it.value;
          row.appendChild(nm);
          row.appendChild(vl);
          // tier ≠ live ⇒ 标「降级 / 静态兜底」（琥珀 chip，不标红）
          if (it.tier && it.tier !== 'live') {
            const chip = document.createElement('span');
            chip.className = 'hv-chip hv-warn';
            chip.textContent = it.tier === 'lkg'
              ? t('home.idx_tier_lkg', '降级')
              : t('home.idx_tier_static', '静态兜底');
            row.appendChild(chip);
          }
          gEl.appendChild(row);
        });
        if (g.link) {
          const a = document.createElement('a');
          a.className = 'hv-factor-link';
          a.href = g.link.href;
          a.textContent = g.link.text;
          gEl.appendChild(a);
        }
        factorsEl.appendChild(gEl);
      });
    }

    // 脚注：口径 + 快照时间
    if (scopeEl) {
      const servedAt = trend.served_at ? new Date(trend.served_at) : null;
      const pad = (n) => String(n).padStart(2, '0');
      const hhmm = servedAt && !isNaN(servedAt.getTime())
        ? `${pad(servedAt.getHours())}:${pad(servedAt.getMinutes())}` : '—';
      scopeEl.textContent = `${t('home.idx_scope_target', '纽约金 COMEX')} · ${t('home.idx_snapshot', '快照')} ${hhmm}`;
      scopeEl.title = t('home.idx_scope_hint',
        '口径：纽约金 COMEX 日线，综合指数与「趋势追踪」页同一算法与权重');
    }
  };

  renderMetals();
  renderVerdict();
  renderReport();

  // 切换语言 ⇒ 重绘 JS 拼的内容（i18n.js 的 apply 只管 data-i18n 元素）
  document.addEventListener('i18n:change', () => {
    renderMetals();
    renderVerdict();
    renderReport();
    // 要闻列表**不整体重渲染** —— 那会重新触发 20 次 favorites/exists 请求；
    // 只换掉 JS 拼的 tooltip 文案。
    document.querySelectorAll('.home-news-title-nourl').forEach((el) => {
      el.title = t('headlines.no_url_title', '该来源未提供原文链接');
    });
    document.querySelectorAll('.home-news-fav').forEach((el) => {
      el.title = t('headlines.fav_add', '收藏');
    });
  });
})();
