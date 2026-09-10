/* PM-Help · 新手引导与帮助体系（V0.58.0, UX Roadmap 6.8）
 *
 * 自包含脚本，挂在 window.PM_Help 命名空间。
 * 入口：右下角悬浮 ? 按钮（#pmHelpBtn）。
 *
 * 功能：
 *   - showModal()    打开 3 tab modal（操作指南 / 术语速查 / 数据来源）
 *   - showTour()     启动当前页 tour 浮层（高亮 + 蒙层 + 步骤切换）
 *   - closeTour()    关闭 tour（标记 localStorage 不再自动弹出）
 *   - attachInline() 注入 12 项关键术语 inline tooltip
 *
 * localStorage 命名空间（与 portfolio.html 的 pm_alert_on 一致）：
 *   - pm_help_tour_<page>   "1"      per-page tour 已完成
 *   - pm_help_seen_version  "V0.58.0" 帮助版本（升级时强制重看）
 */

(function () {
  "use strict";

  const VERSION = "V0.58.0";
  const LS = {
    tourPrefix: "pm_help_tour_",
    seenVer: "pm_help_seen_version",
  };

  /* ── 路径识别（兼容 /static/xxx.html 与 /xxx 路由） ───────────────── */
  const PATH_MAP = {
    "/static/trend.html": "/static/trend.html",
    "/trend.html": "/static/trend.html",
    "/": "/static/trend.html",
    "/portfolio": "/portfolio",
    "/static/portfolio.html": "/portfolio",
    "/weights": "/weights",
    "/static/weights.html": "/weights",
    "/news": "/news",
    "/static/news.html": "/news",
    "/central-bank": "/central-bank",
    "/static/central_bank.html": "/central-bank",
  };
  function pageKey() {
    const p = window.location.pathname;
    return PATH_MAP[p] || p;
  }

  /* ── 30+ 术语速查表（modal 第二 tab） ────────────────────────────── */
  const GLOSSARY = {
    "评估指数类": {
      "综合指数": "0-100 量化多空：技术面 30% + 宏观面 40% + 消息面 30% 加权",
      "技术面": "5 维度（结构/动量/支撑/动能/回撤）加权合成 0-100",
      "宏观面": "5 因子（美元/美债10Y·30Y/VIX/央行购金）合成 0-100",
      "消息面": "客户基于投行展望打分 0-100（占 30% 权重）",
      "RSI(14)": "14 日相对强弱指数，>70 超买 / <30 超卖",
    },
    "指标/均线类": {
      "MA5 / MA20 / MA40": "5/20/40 日移动均线，反映短/中/长期趋势",
      "T12M": "Trailing 12 Months，滚动 12 个月合计",
      "同比 / 环比": "同比 = 与去年同期比；环比 = 与上一期比",
      "回撤": "价格从区间高点回落幅度，越大说明调整越深",
    },
    "宏观因子类": {
      "DXY (美元指数)": "美元对一篮子货币的综合强弱，与黄金负相关",
      "美债 10Y / 30Y": "美国 10 年/30 年期国债收益率，与黄金负相关",
      "VIX": "标普 500 波动率指数（恐慌指数），与黄金正相关（避险）",
      "cb_gold": "国际央行季度净购金（吨），结构性正相关",
    },
    "品种代码类": {
      "Au99.99": "上海黄金交易所 99.99% 纯度黄金现货（元/克）",
      "COMEX": "纽约商品交易所，黄金期货基准（美元/盎司）",
      "SGE": "Shanghai Gold Exchange 上海黄金交易所",
      "518880": "华安黄金 ETF，场内份额基金，跟踪 Au99.99",
      "ETF": "Exchange-Traded Fund 交易所交易基金",
    },
    "交易动作类": {
      "开仓": "首次买入建仓",
      "加仓 / 减仓": "在已有持仓上增加/减少份额",
      "清仓": "全部卖出，结束持仓",
      "软删除": "持仓隐藏但数据保留，8 秒内可撤销",
      "撤销": "恢复软删除的持仓",
      "仓位推荐": "评估指数→建议持仓比例（80/60/40/20/10%）",
    },
    "系统状态类": {
      "live": "实时数据（数据源成功）",
      "stale": "缓存数据（数据源暂不可达，使用上次成功值）",
      "mock": "演示数据（数据源全部失败，前端兜底）",
      "T-1": "昨日数据；用于说明非实时场景",
    },
    "时段类": {
      "BJT": "北京时间 UTC+8",
      "实时": "数据与市场同步",
      "延时": "数据存在 15 分钟以上延迟",
    },
  };

  /* ── 12 项关键术语 inline tooltip 配置 ────────────────────────────── */
  // pageKey → [{ selector, term, def }]
  const INLINE = {
    "/static/trend.html": [
      { selector: ".index-panel .index-info .badge, .headline .index-panel .badge", term: "综合指数" },
      { selector: "#macroFactors .ftitle, #macroFactors h2, #macroFactors h3", term: "宏观面" },
      { selector: "#macroFactors [data-key='cb_gold'], #macroFactors .factor[data-name*='cb'], #macroFactors .row[data-key='cb']", term: "cb_gold" },
      { selector: "#chartArea .chart-legend, .legend", term: "MA5 / MA20 / MA40" },
      { selector: ".indicators [data-name*='RSI'], .indicators .ind[data-key*='动能']", term: "RSI(14)" },
      { selector: ".ny-panel .ny-title, .ny-card .title", term: "COMEX" },
      { selector: ".gram-panel .gram-title, .gram-card .title", term: "Au99.99" },
    ],
    "/portfolio": [
      { selector: "#alertBar", term: "live" },
      { selector: ".decision-card, [class*='decision'] h2", term: "仓位推荐" },
      { selector: "#posArea, .positions-list", term: "518880" },
    ],
    "/weights": [
      { selector: ".w-row input[type=range]", term: "综合指数" },
    ],
    "/news": [
      { selector: ".chip", term: "消息面" },
    ],
    "/central-bank": [
      { selector: "#stackedChart", term: "T12M" },
      { selector: ".kpi-card", term: "T12M" },
      { selector: ".panel-title", term: "WGC" },
    ],
  };

  // 用于 fallback 显示的术语默认定义（如果 GLOSSARY 没收录）
  const INLINE_DEF_FALLBACK = GLOSSARY["评估指数类"]["综合指数"]; // 占位

  /* ── Tour 步骤（per page） ────────────────────────────────────────── */
  const TOUR_STEPS = {
    "/static/trend.html": [
      { selector: ".topnav", text: "顶栏 5 个页面：趋势追踪 / 持仓决策 / 权重 / 消息面 / 央行购金。点击切换。", pos: "bottom" },
      { selector: ".headline .index-panel, .index-panel", text: "综合趋势评估指数（0-100），技术 30% × 宏观 40% × 消息 30% 加权", pos: "top" },
      { selector: "#macroFactors", text: "5 大宏观因子：美元 / 美债 10Y·30Y / VIX / 央行购金；颜色标识 live / stale / mock", pos: "top" },
      { selector: "#chartArea", text: "60 天趋势曲线 + MA5/20/40 均线，鼠标悬停看日数据", pos: "top" },
    ],
    "/portfolio": [
      { selector: ".topnav", text: "切换其他页面（趋势/权重/消息/央行）", pos: "bottom" },
      { selector: "#alertBar", text: "顶部提醒条（开启 🔔 后档位切换或价格异动 ≥2% 触发）", pos: "bottom" },
      { selector: ".decision-card, .panel", text: "今日购买决策 + 仓位推荐 + 红绿理由对照", pos: "top" },
      { selector: "#posArea", text: "当前持仓 + 实时盈亏；支持软删除 / 撤销 / CSV 导出", pos: "top" },
    ],
    "/weights": [
      { selector: ".topnav", text: "切换其他页面", pos: "bottom" },
      { selector: ".w-row input[type=range]", text: "权重滑块：调整后实时影响综合指数计算（持久化到 app_settings）", pos: "top" },
      { selector: ".preview", text: "调整后综合指数 · 实时预览", pos: "top" },
    ],
    "/news": [
      { selector: ".topnav", text: "切换其他页面", pos: "bottom" },
      { selector: ".chip", text: "快捷档位（看多 70 / 中性 50 / 看空 30）+ 沿用昨日打分", pos: "top" },
    ],
    "/central-bank": [
      { selector: ".topnav", text: "切换其他页面", pos: "bottom" },
      { selector: "#stackedChart", text: "季度 × 国家堆叠柱状图（Top 10 + Other）", pos: "top" },
      { selector: ".kpi-card", text: "4 个 KPI：T12M / 本季合计 / 参与国数 / 数据截止季", pos: "bottom" },
    ],
  };

  /* ── localStorage helpers ─────────────────────────────────────────── */
  function lsGet(key) { try { return localStorage.getItem(key); } catch (e) { return null; } }
  function lsSet(key, val) { try { localStorage.setItem(key, val); } catch (e) { /* ignore */ } }
  function tourDone() {
    if (lsGet(LS.seenVer) !== VERSION) return false;  // 版本升级 → 强制重看
    return lsGet(LS.tourPrefix + pageKey()) === "1";
  }
  function markTourDone() {
    lsSet(LS.tourPrefix + pageKey(), "1");
    lsSet(LS.seenVer, VERSION);
  }

  /* ── Modal HTML 渲染 ─────────────────────────────────────────────── */
  function renderGuideTab() {
    return `
      <h3>每日 5 步流程</h3>
      <ol class="pmh-guide">
        <li><b>看趋势</b> → <a href="/static/trend.html">趋势追踪页</a>：综合指数 + 宏观因子 + 60 天曲线</li>
        <li><b>打消息面</b> → <a href="/news">消息面评估页</a>：基于投行展望打分（30% 权重）</li>
        <li><b>看决策</b> → <a href="/portfolio">持仓与决策页</a>：今日动作 + 仓位推荐 + 红绿理由</li>
        <li><b>记交易</b> → 持仓决策页底部：开仓/加仓/减仓/清仓（含二次确认）</li>
        <li><b>看央行</b> → <a href="/central-bank">央行购金页</a>：T12M / Top 10 / 季度明细</li>
      </ol>
      <p class="pmh-tip">💡 综合指数 &gt; 75 强势上升 / &gt; 55 上升 / &gt; 45 震荡 / &gt; 25 下降 / 其他弱势下降</p>
    `;
  }

  function renderTermsTab() {
    let html = '<div class="pmh-terms">';
    for (const [cat, terms] of Object.entries(GLOSSARY)) {
      html += `<section><h3>${cat}</h3><dl>`;
      for (const [term, def] of Object.entries(terms)) {
        html += `<dt>${escapeHtml(term)}</dt><dd>${escapeHtml(def)}</dd>`;
      }
      html += "</dl></section>";
    }
    html += "</div>";
    return html;
  }

  function renderSourceTab() {
    return `
      <h3>⚠️ 投资警示</h3>
      <p class="pmh-warn">本工具输出为<strong>研究参考</strong>，不构成投资建议。市场有风险，决策需谨慎。</p>

      <h3>数据来源</h3>
      <dl class="pmh-source">
        <dt>纽约金（COMEX GC）</dt>
        <dd>主源 AKShare <code>futures_foreign_hist</code>（英为财情）｜ 备选 <code>futures_global_hist_em</code>（东方财富 GC00Y）｜ 美元/盎司</dd>

        <dt>上海金（SGE Au99.99）</dt>
        <dd>AKShare <code>spot_hist_sge</code>（上海黄金交易所）｜ 元/克</dd>

        <dt>黄金 ETF（518880）</dt>
        <dd>主源 AKShare <code>fund_etf_hist_sina</code>（新浪）｜ 备选 <code>fund_etf_hist_em</code>（东方财富）｜ 元</dd>

        <dt>美债 10Y / 30Y</dt>
        <dd>AKShare <code>bond_zh_us_rate</code>（中债收益率）｜ 实时</dd>

        <dt>央行购金（V0.57.0+）</dt>
        <dd>WGC Gold Demand Trends HTML chart JS（<code>fsapi.gold.org/api/v12/charts/js/...</code>）｜ 月度自动拉取 ｜ <a href="/central-bank">查看</a></dd>
      </dl>

      <h3>数据时效</h3>
      <p>三市场交易时段：</p>
      <ul>
        <li>纽约金 CME Globex：周日至周五 18:00–17:00（次日，BJT），几乎全天</li>
        <li>上海金 SGE：工作日 09:00–11:30 / 13:30–15:30 / 20:00–02:30</li>
        <li>ETF（518880）：A 股交易时段 09:30–11:30 / 13:00–15:00</li>
      </ul>
      <p>页面顶部 <code>freshness.js</code> 时效条会标识实时 / 缓存 / 演示三态。</p>

      <h3>采集容错</h3>
      <p>数据源失败时自动降级 Mock（演示数据），UI 同步显示红色 mock 角标，绝不静默。详见 <a href="/static/trend.html">趋势页</a>。</p>
    `;
  }

  /* ── Modal 渲染主函数 ────────────────────────────────────────────── */
  function showModal() {
    let modal = document.getElementById("pmHelpModal");
    if (modal) { modal.hidden = false; return; }

    modal = document.createElement("div");
    modal.id = "pmHelpModal";
    modal.hidden = false;
    modal.innerHTML = `
      <div class="pmh-backdrop"></div>
      <div class="pmh-panel" role="dialog" aria-labelledby="pmh-title">
        <header>
          <h2 id="pmh-title">使用帮助</h2>
          <button class="pmh-close" aria-label="关闭">×</button>
        </header>
        <nav class="pmh-tabs">
          <button data-tab="guide" class="active">操作指南</button>
          <button data-tab="terms">术语速查</button>
          <button data-tab="source">数据来源</button>
        </nav>
        <div class="pmh-body" id="pmhBody"></div>
        <footer>
          <button class="pmh-replay">▶ 再走一次引导</button>
        </footer>
      </div>
    `;
    document.body.appendChild(modal);

    document.getElementById("pmhBody").innerHTML = renderGuideTab();

    // 事件绑定
    modal.querySelector(".pmh-close").addEventListener("click", closeModal);
    modal.querySelector(".pmh-backdrop").addEventListener("click", closeModal);
    modal.querySelector(".pmh-replay").addEventListener("click", () => { closeModal(); showTour(true); });
    modal.querySelectorAll(".pmh-tabs button").forEach((btn) => {
      btn.addEventListener("click", () => switchTab(btn.dataset.tab));
    });
    document.addEventListener("keydown", escHandler);
  }

  function switchTab(tab) {
    const body = document.getElementById("pmhBody");
    if (!body) return;
    if (tab === "guide") body.innerHTML = renderGuideTab();
    else if (tab === "terms") body.innerHTML = renderTermsTab();
    else if (tab === "source") body.innerHTML = renderSourceTab();
    document.querySelectorAll(".pmh-tabs button").forEach((b) => {
      b.classList.toggle("active", b.dataset.tab === tab);
    });
  }

  function closeModal() {
    const modal = document.getElementById("pmHelpModal");
    if (modal) modal.hidden = true;
    document.removeEventListener("keydown", escHandler);
  }
  function escHandler(e) { if (e.key === "Escape") closeModal(); }

  /* ── Tour 浮层 ────────────────────────────────────────────────────── */
  let tourStepIdx = 0;
  let tourSteps = [];

  function showTour(forceRestart) {
    const key = pageKey();
    tourSteps = TOUR_STEPS[key] || [];
    if (!tourSteps.length) return;

    if (!forceRestart && tourDone()) return;

    // 清理上一次
    closeTour();

    // 蒙层
    const mask = document.createElement("div");
    mask.id = "pmhTourMask";
    document.body.appendChild(mask);

    // 高亮框
    const spot = document.createElement("div");
    spot.id = "pmhTourSpot";
    document.body.appendChild(spot);

    // 提示框
    const tip = document.createElement("div");
    tip.id = "pmhTourTip";
    tip.innerHTML = `
      <div class="pmh-tip-body"></div>
      <div class="pmh-tip-foot">
        <span class="pmh-step-counter"></span>
        <button class="pmh-tip-skip">跳过</button>
        <button class="pmh-tip-next">下一步</button>
      </div>
    `;
    document.body.appendChild(tip);

    tip.querySelector(".pmh-tip-skip").addEventListener("click", closeTour);
    tip.querySelector(".pmh-tip-next").addEventListener("click", () => {
      if (tourStepIdx < tourSteps.length - 1) {
        tourStepIdx++;
        renderTourStep();
      } else {
        closeTour();
      }
    });

    tourStepIdx = 0;
    renderTourStep();
  }

  function renderTourStep() {
    const step = tourSteps[tourStepIdx];
    if (!step) return;
    const target = document.querySelector(step.selector);
    const spot = document.getElementById("pmhTourSpot");
    const tip = document.getElementById("pmhTourTip");
    if (!spot || !tip) return;

    if (!target) {
      // 元素不存在：跳过此步
      tip.querySelector(".pmh-tip-body").textContent = `（找不到元素 ${step.selector}，跳过）`;
      positionTip(tip, spot, null, step.pos || "bottom");
      return;
    }

    const rect = target.getBoundingClientRect();
    spot.style.left = rect.left + "px";
    spot.style.top = rect.top + "px";
    spot.style.width = rect.width + "px";
    spot.style.height = rect.height + "px";

    tip.querySelector(".pmh-tip-body").textContent = step.text;
    tip.querySelector(".pmh-step-counter").textContent = `${tourStepIdx + 1} / ${tourSteps.length}`;
    tip.querySelector(".pmh-tip-next").textContent = tourStepIdx === tourSteps.length - 1 ? "完成" : "下一步";

    positionTip(tip, spot, rect, step.pos || "bottom");
  }

  function positionTip(tip, spot, rect, pos) {
    const tipW = 320;
    const tipH = tip.offsetHeight || 120;
    const margin = 12;
    let top, left;
    if (rect) {
      if (pos === "top") {
        top = Math.max(margin, rect.top - tipH - margin);
        left = rect.left + rect.width / 2 - tipW / 2;
      } else if (pos === "left") {
        top = rect.top + rect.height / 2 - tipH / 2;
        left = Math.max(margin, rect.left - tipW - margin);
      } else if (pos === "right") {
        top = rect.top + rect.height / 2 - tipH / 2;
        left = rect.left + rect.width + margin;
      } else { // bottom
        top = rect.top + rect.height + margin;
        left = rect.left + rect.width / 2 - tipW / 2;
      }
    } else {
      // 元素不存在：屏幕中央
      top = window.innerHeight / 2 - tipH / 2;
      left = window.innerWidth / 2 - tipW / 2;
    }
    // viewport 边界保护
    left = Math.max(margin, Math.min(window.innerWidth - tipW - margin, left));
    top = Math.max(margin, Math.min(window.innerHeight - tipH - margin, top));
    tip.style.left = left + "px";
    tip.style.top = top + window.scrollY + "px";
  }

  function closeTour() {
    ["pmhTourMask", "pmhTourSpot", "pmhTourTip"].forEach((id) => {
      const el = document.getElementById(id);
      if (el) el.remove();
    });
    markTourDone();
  }

  /* ── Inline Tooltip 注入 ─────────────────────────────────────────── */
  function attachInline() {
    const key = pageKey();
    const items = INLINE[key] || [];
    items.forEach(({ selector, term }) => {
      const def = lookupDef(term);
      if (!def) return;
      document.querySelectorAll(selector).forEach((el) => {
        if (el.querySelector(".pmh-q[data-term='" + term + "']")) return;  // 防重复
        const q = document.createElement("span");
        q.className = "pmh-q";
        q.textContent = "?";
        q.dataset.term = term;
        q.title = def;  // native fallback
        q.addEventListener("click", (e) => {
          e.stopPropagation();
          showPopover(q, term, def);
        });
        el.appendChild(q);
      });
    });

    // 点击外部关闭 popover
    document.addEventListener("click", () => {
      const pop = document.getElementById("pmhPopover");
      if (pop) pop.remove();
    });
  }

  function lookupDef(term) {
    for (const cat of Object.values(GLOSSARY)) {
      if (term in cat) return cat[term];
    }
    return INLINE_DEF_FALLBACK;
  }

  function showPopover(anchor, term, def) {
    const existing = document.getElementById("pmhPopover");
    if (existing) existing.remove();
    const pop = document.createElement("div");
    pop.id = "pmhPopover";
    pop.innerHTML = `<b>${escapeHtml(term)}</b><p>${escapeHtml(def)}</p>`;
    document.body.appendChild(pop);
    const rect = anchor.getBoundingClientRect();
    const popW = 280;
    pop.style.left = Math.max(8, Math.min(window.innerWidth - popW - 8, rect.left)) + "px";
    pop.style.top = (rect.bottom + window.scrollY + 8) + "px";
  }

  /* ── 工具 ─────────────────────────────────────────────────────────── */
  function escapeHtml(s) {
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  /* ── 入口：注入悬浮按钮 + 启动逻辑 ───────────────────────────────── */
  function init() {
    if (document.getElementById("pmHelpBtn")) return;

    const btn = document.createElement("button");
    btn.id = "pmHelpBtn";
    btn.type = "button";
    btn.title = "使用帮助";
    btn.setAttribute("aria-label", "使用帮助");
    btn.textContent = "?";
    btn.addEventListener("click", showModal);
    document.body.appendChild(btn);

    // 注入 inline tooltip
    attachInline();

    // 首访 tour（DOMContentLoaded 已触发，DOM 已就绪）
    if (!tourDone()) {
      // 延迟 800ms 让首屏数据先到位
      setTimeout(() => showTour(false), 800);
    }
  }

  // 暴露 API（便于测试和外部触发）
  window.PM_Help = {
    showModal,
    showTour,
    closeTour,
    closeModal,
    attachInline,
    GLOSSARY,
    INLINE,
    TOUR_STEPS,
    version: VERSION,
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
