// V0.103 · 我的收藏（今日要闻「收藏 / 永久存储 / 档案管理」）
// 入口：DOMContentLoaded → init() → 拉 status / sites / tags / items + 渲染统计侧栏
// 交互：工具栏（range / site / tag / importance / sort）+ 卡片（⭐ 重要度 / tag chip
//       点击加筛 / 笔记 inline 编辑 / 取消收藏）
//
// 关键设计：
// - 列表分页用 limit/offset 简单实现（首屏 50 条，UI 滚动到底触发加载更多）
// - PATCH 笔记：textarea 失焦 + 顶部「保存」按钮双保险（避免误关丢笔记）
// - 重要度点击 ⭐：PATCH → 重渲染该卡片（不刷新整页）
// - 重复 POST → 409 → toast「已收藏」（幂等）
// - V0.77.1 失败态不伪装：拉失败显示「加载失败」+ amber chip，列表保留末次

(function () {
  "use strict";

  // V0.106.2 整合：去掉 8888 硬编码（同源）
  const API_BASE = "";

  // 状态
  let currentDays = 7;
  let currentSite = "";
  let currentTag = "";
  let currentImpMin = 0;
  let currentSort = "recent";
  let currentLimit = 50;
  let currentOffset = 0;
  let totalAvailable = 0;
  let statsCache = null;
  let sitesCache = [];
  let tagsCache = [];

  // ── HTTP ──

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
      if (resp.status === 204) return null;
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

  function t(key, fallback) {
    return (window.I18n && I18n.t(key)) || fallback || key;
  }

  function toast(msg, type) {
    if (window.PMToast && window.PMToast.show) {
      window.PMToast.show(msg, type || "info");
    }
  }

  // ── 时间格式化 ──

  function fmtBjtDateTime(iso) {
    if (!iso) return "--";
    const d = new Date(iso);
    if (isNaN(d.getTime())) return "--";
    // 转 BJT（+08:00）
    const bjt = new Date(d.getTime() + 8 * 3600 * 1000);
    const Y = bjt.getUTCFullYear();
    const M = String(bjt.getUTCMonth() + 1).padStart(2, "0");
    const D = String(bjt.getUTCDate()).padStart(2, "0");
    const h = String(bjt.getUTCHours()).padStart(2, "0");
    const m = String(bjt.getUTCMinutes()).padStart(2, "0");
    return `${Y}-${M}-${D} ${h}:${m}`;
  }

  // ── 状态行渲染 ──

  function renderStatus(s) {
    document.getElementById("valTotal").textContent = s.total;
    document.getElementById("val3Star").textContent = s.by_importance[3] || 0;
    document.getElementById("val7d").textContent = s.last_7d_count;
    document.getElementById("valSites").textContent = (s.by_site || []).length;
  }

  // ── 统计侧栏渲染 ──

  function renderStats(s) {
    // 重要度分布
    const $imp = document.getElementById("statsImportance");
    const impTotal = Object.values(s.by_importance).reduce((a, b) => a + b, 0) || 1;
    let impHtml = "<h3>" + escapeHtml(t("favorites.stats_by_importance", "按重要度")) + "</h3>";
    for (let star = 1; star <= 3; star++) {
      const cnt = s.by_importance[star] || 0;
      const pct = (cnt / impTotal) * 100;
      impHtml += `<div class="row"><span class="name">${"★".repeat(star)}</span><span class="count">${cnt}</span></div>`;
      impHtml += `<div class="bar"><div class="bar-fill" style="width:${pct}%"></div></div>`;
    }
    $imp.innerHTML = impHtml;

    // tag 分布
    const $tag = document.getElementById("statsTag");
    let tagHtml = "<h3>" + escapeHtml(t("favorites.stats_by_tag", "按标签")) + "</h3>";
    if (s.by_tag && s.by_tag.length > 0) {
      const tagMax = s.by_tag[0].count || 1;
      for (const tg of s.by_tag.slice(0, 10)) {
        const pct = (tg.count / tagMax) * 100;
        tagHtml += `<div class="row"><span class="name">${escapeHtml(tg.tag)}</span><span class="count">${tg.count}</span></div>`;
        tagHtml += `<div class="bar"><div class="bar-fill" style="width:${pct}%"></div></div>`;
      }
    } else {
      tagHtml += `<div class="row" style="color:var(--muted)">${escapeHtml(t("favorites.empty", "暂无数据"))}</div>`;
    }
    $tag.innerHTML = tagHtml;

    // 来源站分布
    const $site = document.getElementById("statsSite");
    let siteHtml = "<h3>" + escapeHtml(t("favorites.stats_by_site", "按来源站")) + "</h3>";
    if (s.by_site && s.by_site.length > 0) {
      const siteMax = s.by_site[0].count || 1;
      for (const st of s.by_site.slice(0, 5)) {
        const pct = (st.count / siteMax) * 100;
        siteHtml += `<div class="row"><span class="name">${escapeHtml(st.site_name)}</span><span class="count">${st.count}</span></div>`;
        siteHtml += `<div class="bar"><div class="bar-fill" style="width:${pct}%"></div></div>`;
      }
    } else {
      siteHtml += `<div class="row" style="color:var(--muted)">${escapeHtml(t("favorites.empty", "暂无数据"))}</div>`;
    }
    $site.innerHTML = siteHtml;

    // 月度归档
    const $month = document.getElementById("statsMonth");
    let monthHtml = "<h3>" + escapeHtml(t("favorites.stats_by_month", "按月归档")) + "</h3>";
    if (s.by_month && s.by_month.length > 0) {
      const monthMax = s.by_month[0].count || 1;
      for (const m of s.by_month.slice(0, 6)) {
        const pct = (m.count / monthMax) * 100;
        monthHtml += `<div class="row"><span class="name">${escapeHtml(m.month)}</span><span class="count">${m.count}</span></div>`;
        monthHtml += `<div class="bar"><div class="bar-fill" style="width:${pct}%"></div></div>`;
      }
    } else {
      monthHtml += `<div class="row" style="color:var(--muted)">${escapeHtml(t("favorites.empty", "暂无数据"))}</div>`;
    }
    $month.innerHTML = monthHtml;

    // KPI
    document.getElementById("kpi30d").textContent = s.last_30d_count;
  }

  // ── 列表渲染 ──

  function renderCard(item) {
    const imp = item.importance || 1;
    const impClass = `s${imp}`;
    const impLabel = "★".repeat(imp) + ` ${imp}`;
    const tagsHtml = (item.user_tags || [])
      .map(
        (tg) =>
          `<span class="tag-chip" data-tag="${escapeHtml(tg)}">${escapeHtml(tg)}</span>`
      )
      .join("");
    const noteText = item.user_note || "";
    return `
      <article class="fav-card" data-id="${item.id}" data-ext="${item.news_external_id}">
        <div class="actions">
          <button type="button" class="unarchive" title="${escapeHtml(
            t("favorites.btn_unarchive", "取消收藏")
          )}" data-i18n-title="favorites.btn_unarchive">🗑</button>
        </div>
        <div class="head">
          <span class="imp ${impClass}">${escapeHtml(impLabel)}</span>
          <span class="site">${escapeHtml(item.site_name || "--")}</span>
          <span class="time">${escapeHtml(fmtBjtDateTime(item.publish_date))}</span>
          <span class="time" style="color:var(--muted)">📌 ${escapeHtml(
            fmtBjtDateTime(item.archived_at)
          )}</span>
        </div>
        <h3><a href="${escapeHtml(item.url)}" target="_blank" rel="noopener noreferrer">${escapeHtml(
      item.title
    )}</a></h3>
        ${item.summary ? `<div class="summary">${escapeHtml(item.summary)}</div>` : ""}
        ${
          tagsHtml
            ? `<div class="tags">${tagsHtml}</div>`
            : ""
        }
        <div class="meta">
          <button type="button" class="imp-up" title="${escapeHtml(
            t("favorites.btn_imp_up", "提升重要度")
          )}">↑★</button>
          <button type="button" class="imp-down" title="${escapeHtml(
            t("favorites.btn_imp_down", "降低重要度")
          )}">↓★</button>
          <button type="button" class="note-toggle" title="${escapeHtml(
            t("favorites.btn_edit_note", "编辑笔记")
          )}" data-i18n-title="favorites.btn_edit_note">📝 ${escapeHtml(
      t("favorites.btn_edit_note", "编辑笔记")
    )}</button>
        </div>
        <div class="note-area" hidden>
          <textarea placeholder="${escapeHtml(
            t("favorites.note_placeholder", "记录你的想法...")
          )}">${escapeHtml(noteText)}</textarea>
          <div class="note-row">
            <button type="button" class="note-cancel" data-i18n="favorites.note_cancel">取消</button>
            <button type="button" class="note-save save" data-i18n="favorites.note_save">保存</button>
          </div>
        </div>
      </article>
    `;
  }

  function renderList(items) {
    const $list = document.getElementById("favList");
    if (!items || items.length === 0) {
      $list.innerHTML = `<div class="empty-state" data-i18n="favorites.empty">${escapeHtml(
        t("favorites.empty", "暂无收藏")
      )}</div>`;
      return;
    }
    $list.innerHTML = items.map(renderCard).join("");
    bindCardEvents();
  }

  // ── 卡片交互 ──

  function bindCardEvents() {
    const $list = document.getElementById("favList");
    $list.querySelectorAll(".fav-card").forEach((card) => {
      const id = parseInt(card.dataset.id, 10);

      // 取消收藏
      card.querySelector(".unarchive").addEventListener("click", async () => {
        if (!confirm(t("favorites.confirm_unarchive", "确定要取消收藏这条吗？"))) return;
        try {
          await fetchJSON(`${API_BASE}/api/v1/favorites/items/${id}`, {
            method: "DELETE",
            timeoutMs: 10000,
          });
          toast(t("favorites.toast_unarchived", "已取消收藏"), "success");
          card.remove();
          // 重新拉统计
          loadStats();
        } catch (e) {
          toast(t("favorites.toast_load_failed", "操作失败") + ": " + e.message, "error");
        }
      });

      // 提升重要度
      card.querySelector(".imp-up").addEventListener("click", () =>
        updateImportance(id, parseInt(card.querySelector(".imp").textContent.match(/\d+/)?.[0] || "1", 10) + 1)
      );
      // 降低重要度
      card.querySelector(".imp-down").addEventListener("click", () =>
        updateImportance(id, parseInt(card.querySelector(".imp").textContent.match(/\d+/)?.[0] || "1", 10) - 1)
      );

      // 笔记切换
      const $noteArea = card.querySelector(".note-area");
      const $textarea = $noteArea.querySelector("textarea");
      card.querySelector(".note-toggle").addEventListener("click", () => {
        $noteArea.hidden = !$noteArea.hidden;
        if (!$noteArea.hidden) $textarea.focus();
      });
      $noteArea.querySelector(".note-cancel").addEventListener("click", () => {
        $noteArea.hidden = true;
      });
      $noteArea.querySelector(".note-save").addEventListener("click", async () => {
        const note = $textarea.value;
        try {
          await fetchJSON(`${API_BASE}/api/v1/favorites/items/${id}`, {
            method: "PATCH",
            body: { user_note: note },
            timeoutMs: 10000,
          });
          toast(t("favorites.toast_note_saved", "笔记已保存"), "success");
          $noteArea.hidden = true;
        } catch (e) {
          toast(t("favorites.toast_load_failed", "操作失败") + ": " + e.message, "error");
        }
      });

      // tag chip 点击 → 加进 tag 筛选
      card.querySelectorAll(".tag-chip").forEach((chip) => {
        chip.addEventListener("click", () => {
          const tag = chip.dataset.tag;
          currentTag = tag;
          document.getElementById("tagSel").value = tag;
          loadList(true);
        });
      });
    });
  }

  async function updateImportance(id, newImp) {
    if (newImp < 1 || newImp > 3) return;
    try {
      await fetchJSON(`${API_BASE}/api/v1/favorites/items/${id}`, {
        method: "PATCH",
        body: { importance: newImp },
        timeoutMs: 10000,
      });
      loadList(true);
      loadStats();
    } catch (e) {
      toast(t("favorites.toast_load_failed", "操作失败") + ": " + e.message, "error");
    }
  }

  // ── 数据加载 ──

  async function loadList(reset = true) {
    if (reset) {
      currentOffset = 0;
      const $list = document.getElementById("favList");
      $list.innerHTML = `<div class="empty-state">${escapeHtml(
        t("favorites.loading", "加载中…")
      )}</div>`;
    }
    const params = new URLSearchParams();
    if (currentDays > 0) params.set("days", String(currentDays));
    if (currentSite) params.set("site_name", currentSite);
    if (currentTag) params.set("tag", currentTag);
    if (currentImpMin > 0) params.set("importance_min", String(currentImpMin));
    if (currentSort) params.set("sort", currentSort);
    params.set("limit", String(currentLimit));
    params.set("offset", String(currentOffset));
    try {
      const data = await fetchJSON(
        `${API_BASE}/api/v1/favorites/items?${params.toString()}`,
        { timeoutMs: 15000 }
      );
      totalAvailable = data.total;
      renderList(data.items);
    } catch (e) {
      const $list = document.getElementById("favList");
      $list.innerHTML = `<div class="error-state">${escapeHtml(
        t("favorites.load_failed", "加载失败")
      )}: ${escapeHtml(e.message)}</div>`;
    }
  }

  async function loadStats() {
    try {
      const s = await fetchJSON(`${API_BASE}/api/v1/favorites/stats`, {
        timeoutMs: 10000,
      });
      statsCache = s;
      renderStatus(s);
      renderStats(s);
    } catch (e) {
      // V0.77.1 失败态不伪装：保留末次，不弹错
      console.warn("favorites stats load failed:", e);
    }
  }

  async function loadSites() {
    try {
      const sites = await fetchJSON(`${API_BASE}/api/v1/favorites/sites`, {
        timeoutMs: 10000,
      });
      sitesCache = sites || [];
      const $sel = document.getElementById("siteSel");
      $sel.innerHTML =
        `<option value="">${escapeHtml(t("favorites.site_all", "全部"))}</option>` +
        sitesCache
          .map((s) => `<option value="${escapeHtml(s)}">${escapeHtml(s)}</option>`)
          .join("");
    } catch (e) {
      console.warn("favorites sites load failed:", e);
    }
  }

  async function loadTags() {
    try {
      const tags = await fetchJSON(`${API_BASE}/api/v1/favorites/tags`, {
        timeoutMs: 10000,
      });
      tagsCache = tags || [];
      const $sel = document.getElementById("tagSel");
      $sel.innerHTML =
        `<option value="">${escapeHtml(t("favorites.tag_all", "全部"))}</option>` +
        tagsCache
          .map((tg) => `<option value="${escapeHtml(tg)}">${escapeHtml(tg)}</option>`)
          .join("");
    } catch (e) {
      console.warn("favorites tags load failed:", e);
    }
  }

  // ── 工具栏事件 ──

  function bindToolbar() {
    document.querySelectorAll("#rangeBtns button").forEach((btn) => {
      btn.addEventListener("click", () => {
        document.querySelectorAll("#rangeBtns button").forEach((b) =>
          b.classList.remove("active")
        );
        btn.classList.add("active");
        currentDays = parseInt(btn.dataset.days, 10) || 0;
        loadList(true);
      });
    });
    document.getElementById("siteSel").addEventListener("change", (e) => {
      currentSite = e.target.value;
      loadList(true);
    });
    document.getElementById("tagSel").addEventListener("change", (e) => {
      currentTag = e.target.value;
      loadList(true);
    });
    document.getElementById("impSel").addEventListener("change", (e) => {
      currentImpMin = parseInt(e.target.value, 10) || 0;
      loadList(true);
    });
    document.getElementById("sortSel").addEventListener("change", (e) => {
      currentSort = e.target.value;
      loadList(true);
    });
  }

  // ── 启动 ──

  async function init() {
    bindToolbar();
    await Promise.all([loadSites(), loadTags(), loadStats(), loadList(true)]);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
