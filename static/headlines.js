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

  const API_BASE = location.port === "8888" ? "" : "http://127.0.0.1:8888";

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
        const extId = parseInt(btn.dataset.ext, 10);
        if (btn.classList.contains("archived")) {
          // 已收藏 → 跳到 /favorites 页（避免误以为点了会取消）
          location.href = "/favorites";
          return;
        }
        btn.disabled = true;
        try {
          await fetchJSON(
            `${API_BASE}/api/v1/favorites/items`,
            { method: "POST", body: { news_external_id: extId }, timeoutMs: 10000 }
          );
          btn.classList.add("archived");
          btn.textContent = "★";
          if (window.PMToast) window.PMToast.show(t("favorites.toast_archived", "已收藏"), "success");
        } catch (err) {
          // 409 = 已收藏（幂等）
          if (err.message && err.message.includes("409")) {
            btn.classList.add("archived");
            btn.textContent = "★";
            if (window.PMToast) window.PMToast.show(t("favorites.toast_archived", "已收藏"), "success");
          } else {
            if (window.PMToast) window.PMToast.show("收藏失败: " + err.message, "error");
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
    const extIds = Array.from($list.querySelectorAll(".fav-btn"))
      .map((b) => parseInt(b.dataset.ext, 10))
      .filter((n) => !isNaN(n));
    if (extIds.length === 0) return;
    // 并发查每个 external_id 是否已收藏（最多 50 个，超过会慢但用并发）
    await Promise.all(
      extIds.map(async (ext) => {
        try {
          const data = await fetchJSON(
            `${API_BASE}/api/v1/favorites/exists/${ext}?source=readhub`,
            { timeoutMs: 8000 }
          );
          if (data && data.id) {
            const btn = $list.querySelector(`.fav-btn[data-ext="${ext}"]`);
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
    const url = escapeHtml(it.url || "#");
    const author = it.author_name
      ? `<span class="meta"> · ${escapeHtml(it.author_name)}</span>`
      : "";
    const langTag = it.language
      ? `<span class="meta"> · ${escapeHtml(it.language)}</span>`
      : "";
    // V0.103 ⭐ 收藏按钮：外置用 `data-ext` 给 fetchJSON 复用
    return `<article class="news-card" data-ext="${it.external_id}">
      <button type="button" class="fav-btn" data-ext="${it.external_id}" title="收藏">☆</button>
      <div class="head">
        <span class="site">${site}</span>
        <span class="time">${escapeHtml(time)}</span>
      </div>
      <h3><a href="${url}" target="_blank" rel="noopener noreferrer">${title}</a></h3>
      ${summary}
      <div class="meta">${escapeHtml(it.source || "readhub")}${author}${langTag}</div>
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

      const [status, sites, langs, cats, list] = await Promise.all([
        fetchJSON(API_BASE + "/api/v1/news-feed/status"),
        fetchJSON(API_BASE + "/api/v1/news-feed/sites"),
        fetchJSON(API_BASE + "/api/v1/news-feed/languages"),
        fetchJSON(API_BASE + "/api/v1/news-feed/categories").catch(() => []),  // V0.105：启动过渡期可能 404
        fetchJSON(url.toString()),
      ]);
      renderStatus(status);
      renderSiteOptions(sites);
      renderLangOptions(langs);
      renderCategoryOptions(cats);  // V0.105
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
      if (!result.ok) {
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
