// V0.111.0 · 报告存档（HTML 报告上传 + 元数据登记表 + 新标签页查看）
// 入口：DOMContentLoaded → init() → 拉 stats / categories / 列表 + 渲染侧栏
// 交互：工具栏（搜索 / 分类 / 标签）+ 卡片（查看 / 下载 / 编辑登记表 / 删除）+ 上传表单
//
// 关键设计：
// - **「查看」用 window.open 而非 <a href> 直接链**：/content 的响应带
//   Content-Security-Policy: sandbox，新标签页里文档处于 opaque origin ——
//   读不到本页的 localStorage，且 connect-src 'none' 调不动 /api/v1/*。
//   页面本身没有任何需要跨页传递的状态，所以 opener 不必回读。
// - 上传走 FormData（multipart），**不走 fetchJSON** —— 那里的 opts.body 是
//   JSON.stringify 的，multipart 必须让浏览器自己设 multipart boundary。
// - V0.77.1 失败态不伪装：列表拉失败显示 .error-state + 原因；
//   统计 / 分类等辅助请求失败只 console.warn，保留末次状态。
// - V0.106.2：API_BASE 同源相对，不写端口判断。

(function () {
  "use strict";

  const API_BASE = "";
  const LIST_URL = API_BASE + "/api/v1/reports";
  const STATS_URL = API_BASE + "/api/v1/reports/stats";
  const CATS_URL = API_BASE + "/api/v1/reports/categories";
  const UPLOAD_URL = API_BASE + "/api/v1/reports/upload";
  const PAGE_SIZE = 50;

  // 状态
  let currentQ = "";
  let currentCat = "";
  let currentTag = "";
  let offset = 0;
  let totalAvailable = 0;
  let categoriesCache = [];
  let pendingFile = null;

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
    if (window.PM_Toast && window.PM_Toast.show) {
      window.PM_Toast.show(msg, type || "info");
    }
  }

  // ── 格式化 ──

  function fmtSize(bytes) {
    const n = Number(bytes) || 0;
    if (n < 1024) return n + " B";
    if (n < 1024 * 1024) return (n / 1024).toFixed(1) + " KB";
    return (n / 1024 / 1024).toFixed(1) + " MB";
  }

  function fmtDateOnly(s) {
    if (!s) return "";
    return String(s).slice(0, 10);
  }

  function fmtBjt(iso) {
    if (!iso) return "--";
    const d = new Date(iso);
    if (isNaN(d.getTime())) return "--";
    const p = (n) => String(n).padStart(2, "0");
    return (
      d.getFullYear() + "-" + p(d.getMonth() + 1) + "-" + p(d.getDate()) +
      " " + p(d.getHours()) + ":" + p(d.getMinutes())
    );
  }

  // ── 列表 ──

  function buildQuery(limit, off) {
    const p = new URLSearchParams();
    if (currentQ) p.set("q", currentQ);
    if (currentCat) p.set("category", currentCat);
    if (currentTag) p.set("tag", currentTag);
    p.set("limit", String(limit));
    p.set("offset", String(off));
    return p.toString();
  }

  async function loadList(reset) {
    if (reset) offset = 0;
    const list = document.getElementById("repList");
    try {
      const data = await fetchJSON(LIST_URL + "?" + buildQuery(PAGE_SIZE, offset));
      const items = data.items || [];
      totalAvailable = data.total || 0;
      if (reset) list.innerHTML = "";
      if (!items.length && reset) {
        list.innerHTML = `<div class="empty-state" data-i18n="reports.empty">${
          escapeHtml(t("reports.empty", "还没有报告。点右上角「＋ 上传报告」开始存档。"))
        }</div>`;
      } else {
        list.insertAdjacentHTML("beforeend", items.map(renderCard).join(""));
      }
      offset += items.length;
      bindCardEvents();
      updateChips();
    } catch (e) {
      // V0.77.1 失败态不伪装：整页换错误块，不留半截列表装作正常
      if (reset) {
        list.innerHTML = `<div class="error-state">${escapeHtml(
          t("reports.load_fail", "报告列表加载失败")
        )}<br><small>${escapeHtml(e.message)}</small></div>`;
      }
    }
  }

  function renderCard(r) {
    const tags = (r.tags || [])
      .map((tg) => `<span class="tag-chip" data-tag="${escapeHtml(tg)}">${escapeHtml(tg)}</span>`)
      .join("");
    return (
      `<div class="rep-card" data-id="${r.id}">` +
        `<div class="actions">` +
          `<a class="view" href="${escapeHtml(r.view_url || LIST_URL + "/" + r.id + "/content")}" ` +
             `target="_blank" rel="noopener noreferrer" data-i18n="reports.act_view">查看</a>` +
          `<a href="${escapeHtml(r.view_url || LIST_URL + "/" + r.id + "/content")}" ` +
             `download data-i18n="reports.act_download">下载</a>` +
          `<button type="button" class="edit" data-i18n="reports.act_edit">编辑</button>` +
          `<button type="button" class="del" data-i18n="reports.act_delete">删除</button>` +
        `</div>` +
        `<div class="head">` +
          `<span class="cat">${escapeHtml(r.category || "")}</span>` +
          `<span class="rdate">${escapeHtml(fmtDateOnly(r.report_date))}</span>` +
        `</div>` +
        `<h3>${escapeHtml(r.title)}</h3>` +
        `<div class="fname">${escapeHtml(r.original_name)} · ${escapeHtml(fmtSize(r.size_bytes))}</div>` +
        (r.summary ? `<div class="summary">${escapeHtml(r.summary)}</div>` : "") +
        (tags ? `<div class="tags">${tags}</div>` : "") +
        `<div class="meta">${escapeHtml(
          t("reports.meta_uploaded", "上传于 {dt}").replace("{dt}", fmtBjt(r.created_at))
        )}</div>` +
        `<div class="meta-area" hidden>` +
          `<div class="grid">` +
            `<div><label data-i18n="reports.field_title">标题</label>` +
              `<input type="text" class="f-title" maxlength="200" value="${escapeHtml(r.title)}"></div>` +
            `<div><label data-i18n="reports.field_date">报告日期</label>` +
              `<input type="date" class="f-date" value="${escapeHtml(fmtDateOnly(r.report_date))}"></div>` +
            `<div><label data-i18n="reports.field_category">分类</label>` +
              `<input type="text" class="f-cat" maxlength="32" value="${escapeHtml(r.category)}"></div>` +
            `<div><label data-i18n="reports.field_tags">标签</label>` +
              `<input type="text" class="f-tags" value="${escapeHtml((r.tags || []).join(", "))}"></div>` +
          `</div>` +
          `<label data-i18n="reports.field_summary">摘要</label>` +
          `<textarea class="f-summary" maxlength="2000">${escapeHtml(r.summary || "")}</textarea>` +
          `<div class="row">` +
            `<button type="button" class="cancel" data-i18n="reports.btn_cancel">取消</button>` +
            `<button type="button" class="save" data-i18n="reports.btn_save">保存</button>` +
          `</div>` +
        `</div>` +
      `</div>`
    );
  }

  function bindCardEvents() {
    document.querySelectorAll(".rep-card").forEach((card) => {
      const id = card.getAttribute("data-id");

      card.querySelectorAll(".tag-chip").forEach((chip) => {
        chip.addEventListener("click", () => {
          currentTag = chip.getAttribute("data-tag") || "";
          const sel = document.getElementById("tagSel");
          if (sel) sel.value = currentTag;
          loadList(true);
        });
      });

      const editBtn = card.querySelector(".edit");
      const area = card.querySelector(".meta-area");
      if (editBtn && area) {
        editBtn.addEventListener("click", () => {
          area.hidden = !area.hidden;
        });
        area.querySelector(".cancel").addEventListener("click", () => {
          area.hidden = true;
        });
        area.querySelector(".save").addEventListener("click", async () => {
          const payload = {
            title: area.querySelector(".f-title").value.trim(),
            report_date: area.querySelector(".f-date").value || null,
            category: area.querySelector(".f-cat").value.trim(),
            tags: area.querySelector(".f-tags").value,
            summary: area.querySelector(".f-summary").value.trim(),
          };
          try {
            await fetchJSON(LIST_URL + "/" + id, { method: "PATCH", body: payload });
            area.hidden = true;
            toast(t("reports.saved", "已保存"), "ok");
            loadList(true);
            loadStats();
            loadCategories();
          } catch (e) {
            toast(t("reports.save_fail", "保存失败") + "：" + e.message, "err");
          }
        });
      }

      const delBtn = card.querySelector(".del");
      if (delBtn) {
        delBtn.addEventListener("click", async () => {
          if (!window.confirm(t("reports.confirm_del", "确认删除这份报告？磁盘文件也会一并删除。"))) {
            return;
          }
          try {
            await fetchJSON(LIST_URL + "/" + id, { method: "DELETE" });
            card.remove();
            toast(t("reports.deleted", "已删除"), "ok");
            loadStats();
            loadCategories();
            updateChips();
          } catch (e) {
            toast(t("reports.del_fail", "删除失败") + "：" + e.message, "err");
          }
        });
      }
    });
  }

  // ── 上传 ──

  function toggleUploadCard(force) {
    const card = document.getElementById("uploadCard");
    const show = typeof force === "boolean" ? force : card.hidden;
    card.hidden = !show;
    if (!show) resetUploadForm();
  }

  function resetUploadForm() {
    pendingFile = null;
    document.getElementById("fileInput").value = "";
    ["upTitle", "upDate", "upCategory", "upTags", "upSummary"].forEach((id) => {
      document.getElementById(id).value = "";
    });
    const picked = document.getElementById("pickedName");
    picked.hidden = true;
    picked.textContent = "";
  }

  function onFilePicked(file) {
    const picked = document.getElementById("pickedName");
    if (!file) {
      pendingFile = null;
      picked.hidden = true;
      return;
    }
    pendingFile = file;
    picked.hidden = false;
    picked.textContent =
      file.name + " · " + fmtSize(file.size) +
      (/\.x?html?$/i.test(file.name) ? "" : t("reports.bad_ext", "（不是 .html，将被拒绝）"));
    // 标题留空时后端取文件名；这里只在用户没手填时预填，减少一次输入
    const title = document.getElementById("upTitle");
    if (!title.value) title.placeholder = file.name.replace(/\.x?html?$/i, "");
  }

  async function doUpload() {
    if (!pendingFile) {
      toast(t("reports.no_file", "请先选择 HTML 文件"), "err");
      return;
    }
    const btn = document.getElementById("btnUpload");
    btn.disabled = true;
    btn.textContent = t("reports.uploading", "上传中…");
    const fd = new FormData();
    fd.append("file", pendingFile);
    const title = document.getElementById("upTitle").value.trim();
    if (title) fd.append("title", title);
    const d = document.getElementById("upDate").value;
    if (d) fd.append("report_date", d);
    const cat = document.getElementById("upCategory").value.trim();
    if (cat) fd.append("category", cat);
    const tg = document.getElementById("upTags").value.trim();
    if (tg) fd.append("tags", tg);
    const sm = document.getElementById("upSummary").value.trim();
    if (sm) fd.append("summary", sm);

    try {
      // FormData 必须让浏览器自己设 boundary，所以不走 fetchJSON（它会
      // JSON.stringify + 手动设 Content-Type，那样 boundary 丢失后端解析不了）
      const resp = await fetch(UPLOAD_URL, {
        method: "POST",
        body: fd,
        credentials: "same-origin",
      });
      if (!resp.ok) {
        const text = await resp.text().catch(() => "");
        let msg = text;
        try {
          const j = JSON.parse(text);
          msg = j.detail || text;
        } catch (e) { /* 非 JSON，原样带出 */ }
        throw new Error("HTTP " + resp.status + " " + String(msg).slice(0, 200));
      }
      toast(t("reports.upload_ok", "已存档"), "ok");
      toggleUploadCard(false);
      loadList(true);
      loadStats();
      loadCategories();
    } catch (e) {
      toast(t("reports.upload_fail", "上传失败") + "：" + e.message, "err");
    } finally {
      btn.disabled = false;
      btn.textContent = t("reports.btn_upload", "上传并存档");
    }
  }

  // ── 辅助数据 ──

  async function loadStats() {
    try {
      const s = await fetchJSON(STATS_URL);
      document.getElementById("kpi30d").textContent = String(s.last_30d_count ?? 0);
      renderCategoryStats(s.by_category || []);
      document.getElementById("valTotal").textContent = String(s.total ?? 0);
      document.getElementById("val30d").textContent = String(s.last_30d_count ?? 0);
      document.getElementById("valSize").textContent = fmtSize(s.total_bytes || 0);
    } catch (e) {
      // 辅助请求失败只记日志，不动列表（V0.77.1）
      console.warn("stats 加载失败", e);
    }
  }

  function renderCategoryStats(rows) {
    const box = document.getElementById("statsCategory");
    if (!rows.length) {
      box.innerHTML =
        `<h3 data-i18n="reports.stats_by_category">按分类</h3>` +
        `<div class="row"><span class="name" data-i18n="reports.empty_cat">暂无</span></div>`;
      return;
    }
    const max = Math.max.apply(null, rows.map((r) => r.count || 0));
    box.innerHTML =
      `<h3 data-i18n="reports.stats_by_category">按分类</h3>` +
      rows
        .map(
          (r) =>
            `<div class="row"><span class="name">${escapeHtml(r.category)}</span>` +
            `<span class="count">${r.count}</span></div>` +
            `<div class="bar"><div class="bar-fill" style="width:${
              max ? Math.round(((r.count || 0) / max) * 100) : 0
            }%"></div></div>`
        )
        .join("");
  }

  async function loadCategories() {
    try {
      const data = await fetchJSON(CATS_URL);
      categoriesCache = data.categories || [];
      const sel = document.getElementById("catSel");
      const keep = currentCat;
      sel.innerHTML =
        `<option value="" data-i18n="reports.cat_all">全部</option>` +
        categoriesCache
          .map((c) => `<option value="${escapeHtml(c)}">${escapeHtml(c)}</option>`)
          .join("");
      sel.value = keep;
      const dl = document.getElementById("categoryOptions");
      if (dl) {
        dl.innerHTML = categoriesCache
          .map((c) => `<option value="${escapeHtml(c)}"></option>`)
          .join("");
      }
    } catch (e) {
      console.warn("分类列表加载失败", e);
    }
  }

  function updateChips() {
    const el = document.getElementById("valShown");
    if (el) el.textContent = String(totalAvailable);
  }

  // ── 启动 ──

  function init() {
    document.getElementById("btnToggleUpload").addEventListener("click", () => toggleUploadCard());
    document.getElementById("btnCancelUpload").addEventListener("click", () => toggleUploadCard(false));
    document.getElementById("btnUpload").addEventListener("click", doUpload);
    document.getElementById("fileInput").addEventListener("change", (e) => {
      onFilePicked(e.target.files && e.target.files[0]);
    });

    const drop = document.getElementById("dropZone");
    ["dragenter", "dragover"].forEach((ev) =>
      drop.addEventListener(ev, (e) => {
        e.preventDefault();
        drop.classList.add("over");
      })
    );
    ["dragleave", "drop"].forEach((ev) =>
      drop.addEventListener(ev, (e) => {
        e.preventDefault();
        drop.classList.remove("over");
      })
    );
    drop.addEventListener("drop", (e) => {
      const f = e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files[0];
      if (f) onFilePicked(f);
    });

    let searchTimer = null;
    document.getElementById("searchInput").addEventListener("input", (e) => {
      clearTimeout(searchTimer);
      const v = e.target.value.trim();
      searchTimer = setTimeout(() => {
        currentQ = v;
        loadList(true);
      }, 300);
    });
    document.getElementById("catSel").addEventListener("change", (e) => {
      currentCat = e.target.value;
      loadList(true);
    });
    document.getElementById("tagSel").addEventListener("change", (e) => {
      currentTag = e.target.value;
      loadList(true);
    });

    // 切语言后重渲染 JS 生成的 DOM（i18n.js 只自动扫 data-i18n，
    // innerHTML 拼出来的必须手动重来一遍）
    window.addEventListener("i18n:change", () => {
      loadList(true);
      loadStats();
      loadCategories();
    });

    loadCategories();
    loadStats();
    loadList(true);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
