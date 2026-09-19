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

  const VERSION = "V0.71.0";
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
    "/trades": "/trades",
    "/static/trades.html": "/trades",
    "/static/silver.html": "/static/silver.html",
    "/static/backtest.html": "/static/backtest.html",
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
      "Sharpe": "夏普比率：mean(日收益−无风险) / std(日收益) × √252；衡量风险调整后收益，越高越好",
      "最大回撤": "区间内净值自最高点的最大跌幅百分比，越低越好",
      "校准曲线": "把综合分 0-100 分 5 桶（0-20/20-40/40-60/60-80/80-100），看每桶的实际胜率是否接近理论概率",
      "回测": "在历史 daily_snapshots 上重算不同参数组合的 Sharpe / 最大回撤 / 命中率（事前重算）",
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
      "562800": "易方达白银 ETF，场内份额基金，跟踪白银现货",
      "SI": "COMEX 白银期货主力合约（美元/盎司）",
    },
    "交易动作类": {
      "开仓": "首次买入建仓",
      "加仓 / 减仓": "在已有持仓上增加/减少份额",
      "清仓": "全部卖出，结束持仓",
      "软删除": "持仓隐藏但数据保留，8 秒内可撤销",
      "撤销": "恢复软删除的持仓",
      "仓位推荐": "评估指数→建议持仓比例（80/60/40/20/10%）",
    },
    "账本与业绩类": {
      "账本": "资金分账容器：持仓、流水、收益曲线与决策均按账本独立统计；「全部账本」为合并视图。归档仅隐藏，数据保留",
      "已实现盈亏": "卖出时才兑现的盈亏 =（卖出价 − 摊薄成本）× 卖出份额 − 卖出手续费；买入不产生已实现盈亏",
      "均价法": "摊薄成本法：买入后成本 =（原成本 + 本次买入金额）÷ 总份额；卖出时成本单价不变，故不产生「卖出价 vs 现价」歧义",
      "手续费": "券商佣金等交易费用；计入「累计投入本金」与已实现盈亏，但不计入摊薄成本单价",
      "成交后份额": "该笔成交完成后该持仓剩余份数（按成交流水逐笔回放得出）",
      "净流出": "买入金额 − 卖出金额：正值表示资金净投入，负值表示已净收回",
      "胜率": "已实现盈亏为正的平仓笔数 ÷ 总平仓笔数",
      "盈亏比": "总盈利 ÷ 总亏损（profit factor），>1 表示整体赚钱",
      "最大回撤": "区间内收益率自最高点回落的最大幅度，衡量持有体验",
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
    "/trades": [
      { selector: ".acc-hint", term: "账本" },
      { selector: "#kpiArea", term: "已实现盈亏" },
      { selector: "table.trades th:nth-child(9)", term: "成交后份额" },
      { selector: ".filters", term: "净流出" },
    ],
    "/static/silver.html": [
      { selector: "#cards .card:nth-child(1) .label, .cards .card .label", term: "562800" },
      { selector: "#cards .card:nth-child(2) .label, .cards .card .label", term: "SI" },
    ],
    "/static/backtest.html": [
      { selector: "#paramsPanel .panel-title, #paramsPanel h3", term: "Sharpe" },
      { selector: "#cachedBadge", term: "Sharpe" },
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
    "/trades": [
      { selector: ".topnav", text: "顶栏新增「交易历史」；右上角可切换账本（含「全部账本」合并视图）", pos: "bottom" },
      { selector: ".filters", text: "筛选：方向 / 日期区间 / 持仓 / 关键字；右侧可导出 CSV（导出全部匹配行）", pos: "top" },
      { selector: "#kpiArea", text: "汇总覆盖全部匹配结果：笔数 / 买卖金额 / 净流出 / 手续费 / 已实现盈亏", pos: "top" },
      { selector: "table.trades", text: "每笔卖出附「已实现盈亏」与「成交后份额」（均价法逐笔回放）", pos: "top" },
    ],
    "/static/silver.html": [
      { selector: ".topnav", text: "V0.71.0 新增「白银追踪」与「参数回测」两个页面", pos: "bottom" },
      { selector: ".freshness, .freshness-bar, .data-badge, .source-bar", text: "白银数据时效：白银 ETF 562800 + COMEX SI 期货（silver_mock 演示数据可降级）", pos: "top" },
      { selector: "#resonanceCard", text: "共振信号卡复用：白银版与黄金版口径一致，便于跨品种对照", pos: "top" },
      { selector: "#chartArea", text: "白银趋势主图（60D / 52W / 24M 三档区间切换）", pos: "top" },
    ],
    "/static/backtest.html": [
      { selector: ".topnav", text: "顶栏 9 个页面 · 「参数回测」是 V0.71.0 新增的复盘工具", pos: "bottom" },
      { selector: "#paramsPanel", text: "参数区：基准标的（5 选 1）+ 回看窗口 + 权重网格（≤125 组合）+ 阈值带", pos: "top" },
      { selector: "#resultsPanel", text: "回测结果：Sharpe + 最大回撤 双轴图 + 命中详情表 + 5 桶校准曲线", pos: "top" },
      { selector: "#cachedBadge", text: "5 分钟节流：相同参数 5 分钟内直接返回缓存（X-Backtest-Cached header）", pos: "left" },
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
      <h3>V0.71.0 新增（白银 + 回测）</h3>
      <ol class="pmh-guide">
        <li><b>白银追踪</b> → <a href="/static/silver.html">白银页</a>：白银 ETF 562800 + COMEX SI 双市场 + 趋势评估指数</li>
        <li><b>参数回测</b> → <a href="/static/backtest.html">回测页</a>：在历史 daily_snapshots 上扫权重网格 + 阈值带，输出 Sharpe / 最大回撤 / 校准曲线（5 分钟节流）</li>
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
