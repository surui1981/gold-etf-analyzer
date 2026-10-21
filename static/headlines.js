// V0.102 / V0.104 / V0.105 · 今日要闻（readhub 财经新闻流）
// 入口：DOMContentLoaded → init() → 拉 status / sites / languages / categories / items
// 4 渲染区：status chip（last_refresh + total + 24h）+ toolbar（range / site / lang / V0.105 category / V0.104 日期导航）
//          + 日分组卡片（day-label → N news-card）+ 手动 refresh 按钮
//
// 关键设计：
// - V0.84 freshness 降级：refresh 失败 → 保留末次数据 + status chip 转 amber，不抛错到 UI
// - 拉数失败时显示「加载失败」+ amber chip，但已加载的卡片继续展示（V0.77.1 失败态不再伪装正常）
// - 所有日期按浏览器本地时区渲染（readhub publishDate 是 UTC ISO，转本地后分组）
// - V0.104 单日模式：currentDate 非空时 API 改用 date=YYYY-MM-DD + tz_offset_minutes，
//   与 1/7/30 天范围互斥；响应多 3 字段（current_date/has_older/has_newer）翻页用
// - V0.105 类目筛选：currentCategory 非空时 API 加 ?category=X；与 date/days/site/language 正交叠加
//   类目下拉动态从 GET /api/v1/news-feed/categories 取（distinct + 频次降序），启动过渡期可能为空 → 仅显示「全部」

(function () {
  "use strict";

  // V0.106.2 整合：去掉 8888 硬编码（16 文件统一用同源相对 URL）
  // 问是：当 uvicorn 跑在 8888/8890/8891 任一端口时，JS 应走同源，
  //       而不是 fallback 到 8888（否则 CORS 拦截 + 永远连错实例）
  const API_BASE = "";

  // V0.105：5 类固定标签（与后端 news_classifier.CATEGORIES 保持一致；启动 backfill 后下拉数据来自 DB）
  const FIXED_CATEGORIES = ["财经", "科技", "创投", "商业", "其他"];

  // 状态
  let currentDays = 7;
  let currentDate = "";     // V0.104：YYYY-MM-DD；空串 = 走 days 模式
  let currentSite = "";
  let currentLang = "";
  let currentCategory = "";  // V0.105："" = 全部（不限）

  // V0.104 · 工具函数（时区 / 日期）
  function todayLocal() {
    // 浏览器本地今天的 YYYY-MM-DD
    const d = new Date();
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
  }
  function tzOffsetMinutes() {
    // JS getTimezoneOffset 返回 WEST 偏移（分钟），东八区 = -480；反转后 = +480
    return -new Date().getTimezoneOffset();
  }
  function addDaysIso(yyyyMmDd, n) {
    // YYYY-MM-DD 加 N 天（按浏览器本地日期），返回新 YYYY-MM-DD
    const parts = yyyyMmDd.split("-");
    if (parts.length !== 3) return todayLocal();
    const d = new Date(Number(parts[0]), Number(parts[1]) - 1, Number(parts[2]));
    d.setDate(d.getDate() + n);
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
  }

  async function fetchJSON(url, opts = {}) {
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), opts.timeoutMs || 15000);
    try {
      const resp = await fetch(url, {
        signal: ctrl.signal,
        method: opts.method || "GET",
        headers: opts.body ? { "Content-Type": "application/json" } : {},
        body: opts.body ? JSON.stringify(opts.body) : undefined,
        credentials: "same-origin",
      });
      if (!resp.ok) {
        const text = await resp.text().catch(() => "");
        throw new Error("HTTP " + resp.status + (text ? ": " + text.slice(0, 120) : ""));
      }
      return await resp.json();
    } finally {
      clearTimeout(timer);
    }
  }

  function escapeHtml(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  // V0.114.0：i18n 取值。字典没命中就返回 fallback，而不是像 I18n.t 那样
  // 返回 key 字面量（页面会显示 "headlines.no_url_title" 这种东西）。
  // 写成 tr("key", "fb") 形式是有意的 —— scripts/check_i18n_keys.py 的
  // tr_call_re 只认字符串字面量实参，这样新 key 才进门禁的严格前缀扫描。
  //
  // ⚠ 本文件**故意**不叫 t()：全站其它文件（favorites.js:65 / report-archive.js:68）
  // 的惯例是模块级 function t(key, fallback)，但本页 fmtBjtDate() 内部有
  // `const t = new Date(iso)`（见下方 124 行）—— 同名会把翻译函数在那个函数
  // 体内整个遮蔽，是个留给下一个人的地雷。tr 无此歧义。
  //
  // ⚠ V0.114.0：本页此前**从没有**模块级 t()，却在收藏按钮处理器里裸调了 2 处
  // t("favorites.toast_archived", ...) → 抛 `ReferenceError: t is not defined`。
  // 那 2 处在 catch 块内，异常无人接管 → 变成未处理拒绝，**收藏成功/409 两条
  // 路径都不弹 toast**（用户点了收藏屏幕毫无反应）。已改成 tr()。
  // 教训：加翻译助手前先 grep 本文件有没有同名调用方，别默认「惯例是 t()」。
  function tr(key, fallback) {
    try {
      const v = window.I18n && window.I18n.t && window.I18n.t(key);
      if (v && typeof v === "string") return v;
    } catch (_) { /* fall through */ }
    return fallback || key;
  }

  // V0.114.0：source key → 展示名。
  // 原先直接渲染 `it.source`（"readhub" / "jin10"），单源时看着还行；四源之后
  // 满屏 "jin10" "eastmoney" 是给用户看的吗？
  //
  // ⚠ 这里**必须把 4 个 key 逐一写成字面量**，不能拿 source 动态拼 key ——
  // 门禁 check_i18n_keys.py 的 tr_call_re 只认**字符串字面量实参**，
  // 拼出来的前缀会被它截成一个**不存在的伪 key**（前缀 + 空格 + 引号），
  // 然后报「该 key 3 语都没定义」。
  //
  // 顺带一个同族教训：**这段注释自己就踩了那个坑**。原先为了举例，在注释里
  // 写了带引号的完整调用形式，门禁不剥 JS 注释，于是把注释里的举例当成真代码
  // 扫了出来，立刻报 3 个伪 missing。写「注释里有断言要跳过的模式」时，
  // 连注释本身也别写那个模式 —— 参见 assertions-must-ignore-comments。
  const SOURCE_LABELS = {
    wallstcn: () => tr("headlines.source_wallstcn", "华尔街见闻"),
    jin10: () => tr("headlines.source_jin10", "金十数据"),
    eastmoney: () => tr("headlines.source_eastmoney", "东方财富"),
    readhub: () => tr("headlines.source_readhub", "ReadHub"),
  };

  function sourceLabel(source) {
    const key = source || "readhub";
    const fn = SOURCE_LABELS[key];
    return fn ? fn() : key;
  }

  // ── 状态行渲染 ──

  function fmtRelative(iso) {
    if (!iso) return "--";
    const t = new Date(iso);
    if (isNaN(t.getTime())) return "--";
    const diffMs = Date.now() - t.getTime();
    const min = Math.round(diffMs / 60000);
    if (min < 1) return (window.I18n && I18n.t("time.just_now")) || "刚刚";
    if (min < 60) return min + " " + ((window.I18n && I18n.t("time.min_ago")) || "分钟前");
    const hr = Math.round(min / 60);
    if (hr < 24) return hr + " " + ((window.I18n && I18n.t("time.hour_ago")) || "小时前");
    const day = Math.round(hr / 24);
    return day + " " + ((window.I18n && I18n.t("time.day_ago")) || "天前");
  }

  function renderStatus(status) {
    const $last = document.getElementById("valLastRefresh");
    const $total = document.getElementById("valTotal");
    const $24h = document.getElementById("val24h");
    const $chipLR = document.getElementById("chipLastRefresh");
    if ($last) $last.textContent = fmtRelative(status.last_refresh_at);
    if ($total) $total.textContent = status.total_items;
    if ($24h) $24h.textContent = status.last_24h_count;
    // V0.84 降级：如果 last_refresh 缺失（DB 空）→ 标 amber
    if ($chipLR) {
      $chipLR.classList.remove("warn", "bad");
      if (!status.last_refresh_at) $chipLR.classList.add("warn");
    }
  }

  // V0.107 · 按 BJT 日聚合摘要渲染
  // 入参：daily 行（NewsFeedDailyOut）或 null（当日为空）
  function renderDaily(daily) {
    const $sum = document.getElementById("dailySummary");
    if (!$sum) return;
    $sum.dataset.loading = "false";
    $sum.hidden = false;
    const $fin = document.getElementById("dailyFinance");
    const $tech = document.getElementById("dailyTech");
    const $vc = document.getElementById("dailyVc");
    const $biz = document.getElementById("dailyBiz");
    const $other = document.getElementById("dailyOther");
    const $total = document.getElementById("dailyTotal");
    if (daily) {
      if ($fin) $fin.textContent = daily.finance_count;
      if ($tech) $tech.textContent = daily.tech_count;
      if ($vc) $vc.textContent = daily.vc_count;
      if ($biz) $biz.textContent = daily.biz_count;
      if ($other) $other.textContent = daily.other_count;
      if ($total) $total.textContent = daily.total_count;
    } else {
      // 当日为空 → 全部显示 0
      if ($fin) $fin.textContent = 0;
      if ($tech) $tech.textContent = 0;
      if ($vc) $vc.textContent = 0;
      if ($biz) $biz.textContent = 0;
      if ($other) $other.textContent = 0;
      if ($total) $total.textContent = 0;
    }
  }

  // ── 工具栏下拉渲染 ──

  function renderSiteOptions(sites) {
    const sel = document.getElementById("siteSel");
    if (!sel) return;
    const placeholder = (window.I18n && I18n.t("headlines.site_all")) || "全部";
    let html = `<option value="">${escapeHtml(placeholder)}</option>`;
    for (const s of sites || []) {
      html += `<option value="${escapeHtml(s)}">${escapeHtml(s)}</option>`;
    }
    sel.innerHTML = html;
    sel.value = currentSite;
  }

  function renderLangOptions(langs) {
    const sel = document.getElementById("langSel");
    if (!sel) return;
    const placeholder = (window.I18n && I18n.t("headlines.lang_all")) || "全部";
    let html = `<option value="">${escapeHtml(placeholder)}</option>`;
    for (const l of langs || []) {
      html += `<option value="${escapeHtml(l)}">${escapeHtml(l)}</option>`;
    }
    sel.innerHTML = html;
    sel.value = currentLang;
  }

  // V0.105 · 类目下拉：合并「DB 现有类目 + 固定 5 类兜底」并去重，保证 5 类一定可选
  function renderCategoryOptions(dbCats) {
    const sel = document.getElementById("categorySel");
    if (!sel) return;
    const placeholder = (window.I18n && I18n.t("headlines.site_all")) || "全部";
    // 合并：DB 频次降序 + 固定 5 类（去重 + 保持 5 类顺序）
    const set = new Set();
    const ordered = [];
    for (const c of dbCats || []) {
      if (!set.has(c)) { set.add(c); ordered.push(c); }
    }
    for (const c of FIXED_CATEGORIES) {
      if (!set.has(c)) { set.add(c); ordered.push(c); }
    }
    let html = `<option value="">${escapeHtml(placeholder)}</option>`;
    for (const c of ordered) {
      const i18nKey = "headlines.cat_" + ({
        "财经": "finance", "科技": "tech", "创投": "vc",
        "商业": "business", "其他": "other",
      }[c] || c);
      const label = (window.I18n && I18n.t(i18nKey)) || c;
      html += `<option value="${escapeHtml(c)}">${escapeHtml(label)}</option>`;
    }
    sel.innerHTML = html;
    sel.value = currentCategory;
  }

  // ── 列表渲染（日分组）──

  function fmtBjtDate(iso) {
    // readhub publishDate 是带 tz 的 ISO，转 BJT 后取 YYYY-MM-DD
    const d = new Date(iso);
    if (isNaN(d.getTime())) return "--";
    // 浏览器时区本身就是用户时区；按浏览器显示日期
    const y = d.getFullYear();
    const m = String(d.getMonth() + 1).padStart(2, "0");
    const day = String(d.getDate()).padStart(2, "0");
    return `${y}-${m}-${day}`;
  }

  function fmtBjtTime(iso) {
    const d = new Date(iso);
    if (isNaN(d.getTime())) return "";
    const hh = String(d.getHours()).padStart(2, "0");
    const mm = String(d.getMinutes()).padStart(2, "0");
    return `${hh}:${mm}`;
  }

  function renderItems(items) {
    const list = document.getElementById("newsList");
    if (!list) return;
    if (!items || !items.length) {
      const empty = (window.I18n && I18n.t("headlines.empty")) || "暂无新闻";
      list.innerHTML = `<div class="empty-state">${escapeHtml(empty)}</div>`;
      return;
    }
    // 按日分组
    const groups = new Map();
    for (const it of items) {
      const day = fmtBjtDate(it.publish_date);
      if (!groups.has(day)) groups.set(day, []);
      groups.get(day).push(it);
    }
    const today = fmtBjtDate(new Date().toISOString());
    const yesterday = fmtBjtDate(new Date(Date.now() - 86400000).toISOString());
    let html = "";
    for (const [day, arr] of groups) {
      let label = day;
      if (day === today) label = (window.I18n && I18n.t("headlines.today")) || "今日";
      else if (day === yesterday) label = (window.I18n && I18n.t("headlines.yesterday")) || "昨日";
      html += `<div class="day-group"><div class="day-label">${escapeHtml(label)}</div>`;
      for (const it of arr) {
        html += renderCard(it);
      }
      html += `</div>`;
    }
    list.innerHTML = html;
    // V0.103 ⭐ 收藏按钮 + 检查已收藏状态
    bindFavButtons();
    void markArchivedFavs();
  }

  // V0.103 ⭐ 收藏按钮：点击 POST /favorites/items；重复 → 409 → 提示「已收藏」
  function bindFavButtons() {
    const $list = document.getElementById("newsList");
    if (!$list) return;
    $list.querySelectorAll(".fav-btn").forEach((btn) => {
      if (btn.dataset.bound) return;
      btn.dataset.bound = "1";
      btn.addEventListener("click", async (e) => {
        e.preventDefault();
        e.stopPropagation();
        // ⚠ V0.114.0 两个「不能想当然」的点：
        // 1. 多源后 external_id **不再全局唯一** —— 同一个数字可能同时是华尔街
        //    见闻的 3182985 和金十的某条。必须连 source 一起传，否则收藏到的
        //    是「另一条同号新闻」。
        // 2. 金十 id 是 20 位（≈2e19），超出 JS Number.MAX_SAFE_INTEGER ≈2249
        //    倍，后端为此把它序列化成**字符串**。这里**绝不能** parseInt ——
        //    那是把已经绕开的精度坑亲手挖回来（页面会把收藏发到不存在的行）。
        //    当不透明标识符透传即可。
        const extId = btn.dataset.ext;
        const src = btn.dataset.source || "readhub";
        if (btn.classList.contains("archived")) {
          // 已收藏 → 跳到 /favorites 页（避免误以为点了会取消）
          location.href = "/favorites";
          return;
        }
        btn.disabled = true;
        try {
          await fetchJSON(
            `${API_BASE}/api/v1/favorites/items`,
            {
              method: "POST",
              body: { news_external_id: extId, news_source: src },
              timeoutMs: 10000,
            }
          );
          btn.classList.add("archived");
          btn.textContent = "★";
          if (window.PM_Toast) window.PM_Toast.show(tr("favorites.toast_archived", "已收藏"), "success");
        } catch (err) {
          // 409 = 已收藏（幂等）
          if (err.message && err.message.includes("409")) {
            btn.classList.add("archived");
            btn.textContent = "★";
            if (window.PM_Toast) window.PM_Toast.show(tr("favorites.toast_archived", "已收藏"), "success");
          } else {
            if (window.PM_Toast) window.PM_Toast.show("收藏失败: " + err.message, "error");
          }
        } finally {
          btn.disabled = false;
        }
      });
    });
  }

  // V0.103 幂等：批量 GET /favorites/exists/{ext} 检查当前列表哪些已收藏
  async function markArchivedFavs() {
    const $list = document.getElementById("newsList");
    if (!$list) return;
    const pairs = Array.from($list.querySelectorAll(".fav-btn"))
      .map((b) => ({ ext: b.dataset.ext, source: b.dataset.source || "readhub" }))
      .filter((p) => p.ext !== undefined && p.ext !== "");
    if (pairs.length === 0) return;
    // ⚠ V0.114.0：查「是否已收藏」必须带 source，且回填时要按 (ext, source)
    // 双向定位 —— 原先写死 `?source=readhub` + 只按 data-ext 找按钮，多源下会
    // 把 A 源的收藏态画到 B 源的同号卡片上。
    await Promise.all(
      pairs.map(async ({ ext, source }) => {
        try {
          const data = await fetchJSON(
            `${API_BASE}/api/v1/favorites/exists/${ext}?source=${encodeURIComponent(source)}`,
            { timeoutMs: 8000 }
          );
          if (data && data.id) {
            const btn = $list.querySelector(
              `.fav-btn[data-ext="${ext}"][data-source="${source}"]`
            );
            if (btn) {
              btn.classList.add("archived");
              btn.textContent = "★";
            }
          }
        } catch (_) {
          // 静默失败（拉失败不影响列表渲染）
        }
      })
    );
  }

  function renderCard(it) {
    const title = escapeHtml(it.title || "");
    const summary = it.summary ? `<div class="summary">${escapeHtml(it.summary)}</div>` : "";
    const site = escapeHtml(it.site_name || "");
    const time = `${fmtBjtDate(it.publish_date)} ${fmtBjtTime(it.publish_date)}`;
    const src = escapeHtml(it.source || "readhub");
    const author = it.author_name
      ? `<span class="meta"> · ${escapeHtml(it.author_name)}</span>`
      : "";
    const langTag = it.language
      ? `<span class="meta"> · ${escapeHtml(it.language)}</span>`
      : "";
    // ⚠ V0.114.0：源没有给链接时，标题渲染成**不可点的纯文本**。
    // 原先是 `it.url || "#"` —— 那是 V0.77.1 说的「假 affordance」：看起来
    // 能点，点了却什么也不发生（金十/东财快讯实测 0/20 条有链接）。
    const titleHtml = it.url
      ? `<a href="${escapeHtml(it.url)}" target="_blank" rel="noopener noreferrer">${title}</a>`
      : `<span class="no-url" title="${escapeHtml(tr("headlines.no_url_title", "该来源未提供原文链接"))}">${title}</span>`;
    // V0.103 ⭐ 收藏按钮：外置用 `data-ext` 给 fetchJSON 复用。
    // data-ext 保持**字符串**（金十 id 超 JS 安全整数范围，见 bindFavButtons 注释）
    return `<article class="news-card" data-ext="${it.external_id}" data-source="${src}">
      <button type="button" class="fav-btn" data-ext="${it.external_id}" data-source="${src}" title="${escapeHtml(tr("headlines.fav_add", "收藏"))}">☆</button>
      <div class="head">
        <span class="site">${site}</span>
        <span class="time">${escapeHtml(time)}</span>
      </div>
      <h3>${titleHtml}</h3>
      ${summary}
      <div class="meta">${escapeHtml(sourceLabel(it.source))}${author}${langTag}</div>
    </article>`;
  }

  function renderError(msg) {
    const list = document.getElementById("newsList");
    if (!list) return;
    const text = (window.I18n && I18n.t("headlines.load_failed")) || "加载失败";
    list.innerHTML = `<div class="empty-state warn">⚠️ ${escapeHtml(text)}${msg ? " · " + escapeHtml(msg) : ""}</div>`;
  }

  // ── 数据加载 ──

  async function loadAll() {
    try {
      // 并发 4 个只读端点（status / sites / languages / V0.105 categories）+ 1 个 list
      // V0.107：+ 1 个 daily 聚合（O(1) 行替代实时 GROUP BY）
      const url = new URL(API_BASE + "/api/v1/news-feed/items", location.origin);
      if (currentDate) {
        // V0.104 单日模式：date + tz_offset_minutes（date 优先于 days）
        url.searchParams.set("date", currentDate);
        url.searchParams.set("tz_offset_minutes", String(tzOffsetMinutes()));
      } else {
        url.searchParams.set("days", String(currentDays));
      }
      url.searchParams.set("limit", "100");
      if (currentSite) url.searchParams.set("site_name", currentSite);
      if (currentLang) url.searchParams.set("language", currentLang);
      if (currentCategory) url.searchParams.set("category", currentCategory);  // V0.105

      // V0.107：daily 端点用 BJT 今日；单日模式用 currentDate
      const dailyDate = currentDate || todayLocal();
      const dailyUrl = `${API_BASE}/api/v1/news-feed/daily?date=${encodeURIComponent(dailyDate)}`;

      const [status, sites, langs, cats, list, daily] = await Promise.all([
        fetchJSON(API_BASE + "/api/v1/news-feed/status"),
        fetchJSON(API_BASE + "/api/v1/news-feed/sites"),
        fetchJSON(API_BASE + "/api/v1/news-feed/languages"),
        fetchJSON(API_BASE + "/api/v1/news-feed/categories").catch(() => []),  // V0.105：启动过渡期可能 404
        fetchJSON(url.toString()),
        fetchJSON(dailyUrl).catch(() => null),  // V0.107：当日空时返回 null，不算错
      ]);
      renderStatus(status);
      renderSiteOptions(sites);
      renderLangOptions(langs);
      renderCategoryOptions(cats);  // V0.105
      renderDaily(daily);  // V0.107
      renderItems(list.items);
      // V0.104 单日模式：根据 has_older/has_newer 翻页按钮 disabled
      if (currentDate) {
        const prev = document.getElementById("btnPrevDay");
        const next = document.getElementById("btnNextDay");
        const today = document.getElementById("btnToday");
        if (prev) prev.disabled = !list.has_older;
        if (next) next.disabled = !list.has_newer;
        if (today) today.hidden = (currentDate === todayLocal());
      }
    } catch (e) {
      console.warn("headlines loadAll failed:", e);
      renderError(e.message || String(e));
    }
  }

  // V0.104 · 同步 dateNav UI 与 currentDate
  function refreshDateNav() {
    const nav = document.getElementById("dateNav");
    const dp = document.getElementById("datePicker");
    const today = document.getElementById("btnToday");
    if (currentDate) {
      // 单日模式：显示 dateNav，datePicker 同步 currentDate
      if (nav) nav.hidden = false;
      if (dp) dp.value = currentDate;
      // 「回到今日」仅在非今日时显示（与 loadAll 中 has_older/has_newer 独立；这里保证 loadAll 失败时也对）
      if (today) today.hidden = (currentDate === todayLocal());
    } else {
      // 范围模式：隐藏 dateNav，datePicker 复位到今天
      if (nav) nav.hidden = true;
      if (dp) dp.value = todayLocal();
      if (today) today.hidden = true;  // 范围模式永远不需要「回到今日」
    }
  }

  async function refresh() {
    const btn = document.getElementById("refreshBtn");
    if (btn) {
      btn.classList.add("refreshing");
      btn.disabled = true;
    }
    try {
      const result = await fetchJSON(API_BASE + "/api/v1/news-feed/refresh", {
        method: "POST",
        timeoutMs: 30000,
      });
      if (result.ok) {
        // V0.107：success toast（之前仅 fail 弹 toast，success 静默）
        const n = result.upserted || 0;
        const i18nKey = n > 0
          ? "headlines.toast_refreshed_n"
          : "headlines.toast_refreshed_zero";
        const msg = (window.I18n && I18n.t(i18nKey, { n })) ||
          (n > 0 ? `刷新成功，新增 ${n} 条` : "已是最新，0 条新增");
        if (window.PM_Toast) PM_Toast.show(msg, n > 0 ? "success" : "info");
      } else {
        const msg = result.error || "unknown";
        if (window.PM_Toast) PM_Toast.show("⚠️ " + msg, "warn");
      }
    } catch (e) {
      if (window.PM_Toast) PM_Toast.show("⚠️ " + (e.message || e), "warn");
    } finally {
      if (btn) {
        btn.classList.remove("refreshing");
        btn.disabled = false;
      }
      await loadAll();
    }
  }

  // ── 绑定 ──

  function bindToolbar() {
    const ranges = document.getElementById("rangeBtns");
    if (ranges) {
      ranges.addEventListener("click", (e) => {
        const btn = e.target.closest("button[data-days]");
        if (!btn) return;
        const d = parseInt(btn.getAttribute("data-days"), 10);
        if (isNaN(d) || d === currentDays) return;
        currentDays = d;
        currentDate = "";  // V0.104：点范围按钮 = 退出单日模式
        for (const b of ranges.querySelectorAll("button")) b.classList.remove("active");
        btn.classList.add("active");
        refreshDateNav();
        loadAll();
      });
    }
    const siteSel = document.getElementById("siteSel");
    if (siteSel) siteSel.addEventListener("change", () => {
      currentSite = siteSel.value;
      loadAll();
    });
    const langSel = document.getElementById("langSel");
    if (langSel) langSel.addEventListener("change", () => {
      currentLang = langSel.value;
      loadAll();
    });
    // V0.105 · 类目筛选（与 date/days/site/language 正交叠加，不清其他 state）
    const catSel = document.getElementById("categorySel");
    if (catSel) catSel.addEventListener("change", () => {
      currentCategory = catSel.value;
      loadAll();
    });
    const btn = document.getElementById("refreshBtn");
    if (btn) btn.addEventListener("click", refresh);

    // V0.104 · 日期导航 4 控件
    const prevBtn = document.getElementById("btnPrevDay");
    const nextBtn = document.getElementById("btnNextDay");
    const todayBtn = document.getElementById("btnToday");
    const datePicker = document.getElementById("datePicker");

    // 进入单日模式：清空所有 rangeBtns active
    function enterDateMode(date) {
      currentDays = 0;  // 标记（让 rangeBtns active 都不亮）
      currentDate = date;
      const ranges = document.getElementById("rangeBtns");
      if (ranges) {
        for (const b of ranges.querySelectorAll("button")) b.classList.remove("active");
      }
      refreshDateNav();
      loadAll();
    }
    if (prevBtn) prevBtn.addEventListener("click", () => {
      if (currentDate === "") return;
      enterDateMode(addDaysIso(currentDate, -1));
    });
    if (nextBtn) nextBtn.addEventListener("click", () => {
      if (currentDate === "") return;
      enterDateMode(addDaysIso(currentDate, 1));
    });
    if (todayBtn) todayBtn.addEventListener("click", () => {
      enterDateMode(todayLocal());
    });
    if (datePicker) datePicker.addEventListener("change", (e) => {
      const v = e.target.value;
      if (v) enterDateMode(v);
    });
  }

  // ── 初始化 ──

  function init() {
    bindToolbar();
    loadAll();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }

  // 暴露给调试 / 测试
  window.PM_Headlines = { loadAll, refresh };
})();
