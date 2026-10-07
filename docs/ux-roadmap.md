# UX & 应用能力路线（V0.68.0 → V0.78.0）

> 适用版本：**V0.80.0**（当前）· 待做 V0.75.2 / V0.75.3 ｜ 制定日期：2026-09-18 ｜ 最近更新：2026-10-05（**V0.78.2 门禁可信度修复（补丁版）** —— V0.78.1 刚立起三道门禁，本版修的是**门禁自身会不会被误读**：① CI 的八道门禁全部加 `if: always() && steps.install.outcome == 'success'` —— GitHub 默认 `if: success()` 会让前序失败后的所有 step 变成 **skipped**，而 skipped 在界面上与「通过」仅一线之隔（本仓 docker job 曾因 `on.push` 未声明 `tags` 而从未执行却被读成「CI 全绿」，掩盖 20+ 版本的容器启动崩溃）；② `check_pwa_assets.py` 补 **14 例常驻回归测试**（把输入路径参数化，使负向验证从「手工做一次」变为可重复执行）；③ `SHELL_ASSETS` 的 6 条 307 条目**确认不可改**并写清理由 —— V0.78.1 记的「建议改写最终 URL」是错的，改了会让离线访问 `/portfolio` 落到 `offline.html`；④ ruff 0.16.6 → 0.16.10、五个 Action 升到 Node 24。用例 972 → **986**（+14），模块 66 → **67**）上版 2026-10-05（**V0.78.1 收口与门禁补齐（补丁版）** —— 三个先收口、再加护栏：① **SW 缓存版本脱钩**（用户可见的静默缺陷）：`static/sw.js` 的 `const VERSION` 自 2026-09-21 起停在 `v0.77.1`，而 V0.77.2 与 V0.78.0 **都改过静态资源** —— `/static/` 走 cache-first 且不后台更新，sw.js 字节未变就不触发浏览器重装 SW，即便重装，`activate` 按 VERSION 清缓存也因名字没变而失效 ⇒ **已装 PWA 的用户长期「HTML 新 + JS 旧」错配**（比整站皆旧更难排查）；② **PWA 快捷方式两条 404**：`manifest.json` 的 `shortcuts` 指向 `/silver` 与 `/backtest`（实测 404）；③ **共振缺维不再伪装中性**：`compute_resonance` 原把缺失维度按 50 参与方向与幅度判定（实测 `macro=50, news=65, tech` 缺失时会标成 `tech_news`，而技术面根本没有数据），现只把**有效维度**纳入判定、任一维缺失的维度对直接跳过，并新增响应字段 `missing_dimensions`；④ 补 `starlette` 依赖声明（`src/` 直接 import 却未写进 `dependencies`，与偏差 #60 同类，属**隐患**）。**护栏**：新增**三道机械门禁**并接入 CI（质量门禁由 5 道增至 **8 道**）—— `check_pwa_assets.py`（SW 缓存版本 == 应用版本 / `SHELL_ASSETS` 逐条可解析 / `manifest.json` 目标存在）、`check_links.py`（20 份文档 109 条内部链接 + 锚点）、`check_deps.py`（`src/**` 三方 import 必须在 `dependencies`）；三道门禁的断言均先经**负向测试**验证能报错。**接口新增 1 个响应字段** `missing_dimensions`（非新端点）；用例 945 → **972**（+27 = check_links 10 + check_deps 11 + 共振缺维 6），模块 64 → **66**。）上版 2026-10-05（**V0.78.0 一致性收口已落地** —— 本版属**工程路线专项**（详见 [roadmap.md](./roadmap.md)），不在本 UX 路线图范围内，但直接影响客户看到的数字：① 阈值常量集中为四组语义互不相同的 IntEnum，解决「55 到底是看多还是中性」的口径分裂；② 决策档位 4 → **9 档**（新增缓冲档 `HOLD_CAUTIOUS`≥40），消除「指数 60-70 × 盈亏 -10%~+15% 什么都不做」的卡死区；③ 共振 `DIVERGENT` 扩为**三维幅度判定 + 子类型**，补齐「消息面 vs 另两面」整类漏判；④ **兜底差异化** —— 修掉**两种「不足却显示中性 50」**：技术面 5 维度数据不足时 `score` 返回 `None`（前端灰色「— 未计入」）而非 50，综合指数按**有效维度**归一化；W/M 视图保留 50 但补披露。**接口零新增**，用例 867 → **945**，模块 63 → **64**。）上版 2026-10-03（**V0.77.2 数据不丢与交互安全已落地**：本版修的是 V0.77.1 的下一层 —— 「操作明明点了保存，数据却悄悄丢了」与「操作没成功，界面却毫无反应」，四条的共同特征是**页面看起来完全正常**（所以能存活至今），只在客户的复盘数据与决策依据上留下不可逆的空洞：① `/news` 保存打分时 `basis` / `review_note` **从未进请求体**（页面有回填、后端也写库，唯独提交漏了这两字段→ 勾选的 12 个研判依据每次保存即归零、复盘「依据胜率」永远为空），修复须注意 `selectedBasis` 是 `Set`；② `/portfolio` 开仓价格框被轮询**反复清空**（两分支同值 = 恒清空，抹掉初始化预填的 ETF 最新价）；③ `/review` 空态指引**指路到不存在的功能**（打分页并无日期控件）→ 改为可执行路径并如实说明补录未开放；④ `/weights`「恢复默认」**无确认、无错误处理**（一次误点即不可逆覆盖并立刻改变决策，失败还静默）→ 加二次确认 + `try/catch` + 失败提示。**门禁** `check_cluster_render.mjs` 102 → **125 条**（新增第 9 节，真实执行四条静默错误的源码片段 + 反向断言）；**接口零新增、用例数不变 867**。）上版 2026-10-02（**V0.77.1 信任修复已落地**：起因是 V0.77.0 的客户交互易用性评估给出 55/100，结论为「功能覆盖完整，但**信任层**有结构性短板」—— 多数地方做对了（降级会明示、mock 有警示、时效条透明、空态有引导），却在关键路径上给出**与事实不符的正向信号**，而对投资决策工具「客户发现某个数字与事实不符」会一次性击穿整套决策依据。本版只修「取数失败 / 缺数据时界面给出错误正向信号」这一整类，5 条：① `/data-health` 接口失败时 4 张概览卡由**全绿**改为**「—」未知态**（根因：`load()` 在 catch 里静默兜底成 `{sources:{}}`，于是 `total=0`、`live=0`，而判定式 `live === total` 在 `0 === 0` 时**成立** → 「实时」判 ok；`stale`/`mock` 因「>0 才告警」也不成立 → 同样判 ok，而真实情况是一个源都没取到），失败说明同时从页面底部（紧贴 footer）移到概览区、与它解释的卡片同屏；② `/news` 当日有效分的静态默认 `50.0` 改为占位 `—`（根因：`renderAll()` 开头 `if (!d) return`，接口失败时静态值永远留在页面上，而 50 恰是「中性」、又真占综合指数 30% 权重 → 会被当成「今天消息面中性」的结论），新增 `fmtScore`（缺值一律「—」，真实的 0 仍显示 0.0）与 `renderLoadFailure`（占位 + 禁用保存 + 明说「不代表今日中性 50」）；③ `/silver` 失败后加载条**永久停留**在「数据加载中…（首次约 10-30 秒）」（隐藏只写在 `renderMain` 成功分支里，失败路径永远走不到）→ 改由 `finally` 收起，错误从页面下方的图表区提到首屏 `#alertBar`，并去掉「请确认服务已启动（127.0.0.1:8888）」这类对客户不可执行、又暴露部署细节的文案；④ 回测校准曲线的「理论概率」正名为**完美校准基准线**（取值即每桶分数中值，不由模型算出）+ 图下说明，并**停止绘制恒为 0 的「实际命中率」假线** —— 复核发现 `_bucket_data` 在后端**从未存在过**（`services/backtest.py:44` 定义了 `_CALIBRATION_BUCKETS` 五桶常量但全仓无调用点），该曲线自 V0.71.0 起一直是恒 0 假线（缺数据 ≠ 命中率 0%）；⑤ Service Worker 的只读 API 由 stale-while-revalidate 改 **network-first** —— 原策略先回缓存、后台再更新，而缓存**没有 TTL**，于是**在线**也可能拿到上次会话的响应（`review`/`news`/`weights`/`backtest` 只拉一次数据、不自我校正）；现网络优先，仅网络失败时回退且须满足两道闸：**价格类端点永不回退**（过期价格比无数据更危险）、其余回退须在 **30 分钟**内（超期即删除并让页面报错），回退时注入 `X-SW-Cached-At` 由时效条披露「本页数据来自离线缓存（时点）」，顺带不再把 4xx/5xx 写入缓存。**门禁**：`check_cluster_render.mjs` 由 33 条扩到 **102 条**，新增第 7 节「失败态渲染」与第 8 节「接线与 SW 缓存护栏」（本包五条全在失败路径，正常请求走不到、人工点页面看不出来，故直接构造「接口挂掉」输入执行各页真实失败分支：桩 fetch 端到端跑通 `load()` 接线、桩 caches + 真实 `Response` 真实执行 SW 的缓存护栏；并含反向断言保证正常态未被改坏）。**接口零新增、用例数不变 867**。）上版 2026-10-01（**V0.77.0 界面聚类分组已落地**：全站 13 页审计出 23 处「同类项平铺 / 同一数据多出口」—— 同类信息平铺在一个容器里、没有分组标题，用户得一条条读完再自己归类；同一份数据在多处渲染、字段互补却要人肉横向对照。本版新增**全站统一的聚类样式基元**（`theme.css` 的 `.pmc-cluster` / `.pmc-tabs` / `.pmc-group` / `.pmc-grid-title` / `.pmc-count`；只用主题变量故 light / dark / hc 自动适配，前缀 `pmc-` 避开 `.card` / `.panel` / `.section` / `.kpi` 等页面私有类名），落地 5 处：① 首页 `#cards` 8 张 KPI 磁贴 → **3 组**（价格 / 涨跌 / 均线），`#sgeCards` 6 张 → 2 组；② `/trades` 6 张 KPI → **2 簇**（成交规模 / 成本与收益）、9 个筛选字段 → 2 组（查询条件 / 输出动作）；③ `/data-health` 同一批 6 个数据源从「6 张状态卡 + 6 行时效表」两处渲染**合并为一处**、按 `SOURCE_LABELS` 的天然分组聚成**黄金 / 白银**两组、状态与时效同卡，并去掉暴露内部键名的「键: etf」技术噪音（`renderFreshnessTable` 整体移除）；④ `/review` 三组同构横条（按方向 / 按窗口 / 按分值档位，同由 `barRow()` 渲染、同取一份 `stats`，却散在两张卡里）**并为 1 个「统计分面」簇 + Tab**（←/→ 键盘切换），独立「分值校准」卡并入第三个 tab。同批修复 3 处既有缺陷：首页 4 张快照卡用 `class="val"`（样式表只有 `.card .value`）致数值**一直无字号字重样式**；`/news` 历史表**表头 7 列 vs 数据 8 列错位**；央行页顶栏**缺「研判复盘」链接**且堆叠图图例只显示 ISO 代码、与表格中文国名对不上。**新增第 4 道门禁** `scripts/check_cluster_render.mjs`（提取**真实的聚类代码块**、最小 DOM 桩在 Node 里**真实执行**、断言产出的 HTML 结构共 33 条），补上「静态门禁全绿 ≠ 渲染正确」的盲区。用例 866 → **867**。）上版 2026-09-30（**V0.76.0 首页内嵌消息面打分器已落地**：消息面占综合评估指数 30%，是三维里唯一**由用户自己产出**的维度；V0.75.1 收敛「今日操作清单」后首页只剩 `#newsFactor` **一行只读**展示，想记一次判断必须整页跳到 `/news`。本版把打分能力**内联到趋势追踪页**（`static/news-score-widget.js`，IIFE + `window.PM_NewsScore`，自注入 CSS 适配 4 主题，自动挂载 `#newsScoreCard`）：① 3 槽位状态一览（分值 / 权重 1:2:3 / 方向 / 提交时刻 / 备注 / 补录 + 逐槽修改·撤销）；② 当日有效分值 + **后端算式原样展示**（`(1×45 + 2×70) ÷ 3 = 61.7`，**前端不重算加权**，与 `/news`、复盘页同源）；③ 内嵌编辑器（滑杆 + 快捷档位 + 沿用上次 + 研判备注 + 12 依据标签 + 复盘批注）；④ **保存后即时刷新**结论卡与消息面评估行，全程不跳页。**接口零新增**（复用 `GET|PUT|DELETE /api/v1/news-score`）；`/news` 保留为完整详情页。**刻意不轮询**（含滑杆与文本框，定时重渲染会打断输入）。**数据守门**：载入既有槽位必须回填 `notes` / `basis`（仓储层 UPDATE 对这两项是**硬覆盖**，不回传即静默清空）。用例 864 → **866**。）上版 2026-09-29（**V0.75.1 首页综合研判结论卡已落地**：把散落在「实时评估摘要 / 共振信号卡 / 今日操作清单」的判断原料**收敛成一张置顶卡**（`static/synthesis-card.js`）—— 一行结论 + 三维分值条（技术 30%/宏观 40%/消息 30%）+ **一致性判定**（5 类，复用后端 `compute_resonance()` 口径，不在前端重算）+ 建议仓位 vs 当前持仓 + 决策依据 + **数据质量折损提示**（宏观静态参考值项数 / Mock 降级市场数如实标注），并支持**黄金 ↔ 白银一键切换**；为使白银口径可用，`GET /api/v1/resonance/signal` 新增 `target` 参数，顺带修复「白银页共振卡写死 `etf`、一直显示黄金分值」与「`PM_Resonance.mount()` 未导出」两处既有缺陷。**V0.75.0 认证骨架已落地**：`users` / `sessions` 表 + 6 个认证端点 + `login.html` + 顶栏账号菜单 + CSRF 双提交 + 登录节流；**默认 `AUTH_ENABLED=false` 单用户模式**，既有 728 用例零破坏。M8「多用户独立数据，零越权事件」**尚未达成** —— 按三步递进拆分，认证骨架 V0.75.0 已落地，数据隔离顺延 V0.75.2、找回密码顺延 V0.75.3）｜ 视角：应用能力 + 用户体验
>
> **工程路线**（CI / 可观测 / 部署）见 [docs/improvement-path.md §三·五](./improvement-path.md#三五下一阶段路线v0670--v0720-工程化补齐--业务深度--产品化)；
> **已落地 UX**（6.1 时效 / 6.2 响应式 / 6.3 决策可解释 / 6.4 操作防错 / 6.6 主动提醒 / 6.8 帮助 / 6.10 央行购金 / 6.11 研判复盘 / 6.12 框架基础）见 [docs/improvement-path.md §六](./improvement-path.md)。
>
> 本文档与 §三·五 形成 **「应用 vs 工程」双视图**：重叠版本（V0.68.0 / V0.69.0 / V0.71.0 / V0.72.0）在两文档里互相 cross-link，避免双线维护失同步。

---

## 〇 North-star metric

| 指标 | 当前（V0.67.0） | 目标（V0.75.3） |
|---|---|---|
| **端到端首次操作耗时**（打第一条分 → 看到综合指数） | ≤ 3 分钟 | **≤ 1 分钟** |
| **每日回访率**（连续 7 天 ≥ 1 次访问） | 无埋点基线 | ≥ 60% |
| **持久化命中率**（localStorage / settings 覆盖用户行为） | 50%（账本已 100%，其余 0） | ≥ 90% |
| **每日操作总时长** | ≤ 90 秒 | ≤ 60 秒 |

**支撑手段**：V0.68.0 起的 `telemetry_events` 表记录所有关键点击，4 个指标均从埋点 SQL 实时聚合。

---

## 一 8 版本总览表

| 版本 | 主题 | 主要交付 | 用户价值 | 风险 | 人天 |
|---|---|---|---|---|---|
| **V0.68.0** | 导航折叠 + 全局搜索 + 客户端埋点底座 | ① 汉堡抽屉式顶栏（≤768px 自动折叠）<br>② `Cmd/Ctrl+K` 全局命令面板<br>③ `telemetry.js` + `telemetry_events` 表（5 类事件） | 移动端首屏 ≤ 1 跳可达任意功能；高级用户操作提速 50%；功能使用可量化 | 🟡 中（汉堡菜单影响 7 页布局） | 3.5 |
| **V0.69.0** | 主题切换 + 无障碍扩面 | ① 4 主题（light / dark / auto / **high-contrast**）<br>② Chart.js canvas 加 `role="img"` + 数据表 fallback<br>③ 全站 axe-core 0 critical + 键盘 Tab 序修复 | 暗光环境舒适；色盲/低视力可访问；WCAG 2.1 AA 通过 | 🟡 中（Chart.js a11y 需手工包） | 4 |
| **V0.70.0** | 共振卡片 + 克数持仓 UX | ① 趋势页顶部"宏观×技术×消息面"三色共振信号卡<br>② `/portfolio` 克数持仓并列展示<br>③ 双口径收益曲线（按份 / 按克） | 中期反转可视化；实物金闭环 | 🟢 低（复用 §三·五 V0.70.0 后端） | 4 |
| **V0.71.0** | 多品种 UI + 回测可视化 | ① `/silver.html`（白银 K 线 / 评估 / 决策）<br>② `/backtest.html`（权重 / 阈值 / 阈值穿越回测 + 命中率/夏普曲线） | 贵金属全景；参数可信度闭环 | 🟡 中（回测计算可能慢，需节流） | 5 |
| **V0.72.0** | 推送渠道 + PWA 安装 | ① 邮件（SMTP）+ 微信（Server酱 webhook）<br>② `manifest.json` + 安装横幅 + 通知中心抽屉<br>③ 浏览器通知升级为 Web Push（VAPID + SW push） | 离线 / 后台也能收到；iOS / Android 可装桌面 | 🟡 中（Web Push 需 VAPID 密钥） | 4 |
| **V0.73.0** | i18n 框架 + 英文版 | ① `data-i18n` 属性 + `i18n.js` + 简繁英三语字典<br>② 顶栏语言切换器（zh-CN / en-US / zh-TW）<br>③ 货币 / 日期 / 百分比自动 locale 化 | 海外华人 + 港台 + 英文用户可用 | 🟢 低（已有 `toLocaleString("zh-CN")` 基础） | 4 |
| **V0.74.0** | 仪表盘自定义 + 通知偏好 | ① 卡片拖拽排序（纯原生）<br>② 提醒规则面板（≥X% 波动 / 指数跨档 / T+N 命中 / 自定义时段）<br>③ 打印友好 CSS + 一键 PDF 导出 | 个性化首页；通知降噪；月度报告 | 🟡 中（拖拽需无障碍实现） | 5 |
| **V0.75.0** | 多用户登录 + 数据隔离 | ① bcrypt 密码 + session cookie（HttpOnly + SameSite=Strict）+ CSRF token<br>② `user_id` 透传到所有业务表；`AUTH_ENABLED` 兼容开关<br>③ `/login` + `/register` + 找回密码（邮件 token） | 家庭 / 合伙多用户独立数据 | 🔴 高（数据迁移 + 安全审计） | 6 |
| **V0.75.1**（增补） | 首页综合研判结论卡 | ① `synthesis-card.js` 置顶结论卡（结论 / 三维分值 / 一致性 / 仓位对照 / 决策依据 / 数据质量折损）<br>② 黄金 ↔ 白银一键切换（三接口 target 同步）<br>③ `GET /api/v1/resonance/signal?target=` | 首页从「六个面板自己横着扫」变为「一眼看结论」；同时**显式暴露**数据可信度折损 | 🟢 低（纯前端收敛 + 复用既有后端口径） | 1.5 |

| **V0.76.0**（增补） | 首页内嵌消息面打分器（客户评价上首页） | ① `news-score-widget.js`：3 槽位状态 + 当日有效分值（**后端算式原样展示**）+ 内嵌编辑器（滑杆 / 快捷档位 / 沿用上次 / 12 依据标签 / 复盘批注）<br>② 挂载 `trend.html#newsScoreCard`，保存后派发 `news-score-changed` **即时刷新结论卡与消息面评估行**<br>③ 逐槽修改·撤销；**刻意不轮询**（含输入控件，避免打断输入） | 判断的「录入」环节从「整页跳 `/news`」变为「首页原地完成」，闭合「看结论 → 录判断 → 回看命中」回路；`/news` 降为深度详情页 | 🟢 低（纯前端 + 复用既有 3 个端点，**接口零新增**） | 1 |
| **V0.77.0**（增补） | 界面聚类分组（同类项归簇） | ① 新增**全站聚类样式基元**（`.pmc-cluster` / `.pmc-tabs` / `.pmc-group` / `.pmc-grid-title` / `.pmc-count`，4 主题自动适配）<br>② 首页 8 张 KPI 磁贴 → **3 组**、上海金 6 张 → 2 组<br>③ `/trades` 6 张 KPI → **2 簇**、9 个筛选字段 → 2 组<br>④ `/data-health` 同一批 6 个数据源**从两处渲染合并为一处**、按黄金/白银分组、状态与时效同卡<br>⑤ `/review` 三组同构横条并为一个 **Tab 分面**（←/→ 键盘切换）<br>⑥ 同批修 3 处既有缺陷（`class="val"` 致数值无样式 / 历史表表头错列 / 央行页缺导航链接且图例口径不符） | 同类信息不再平铺让人自己归类；同一份数据不再渲染两遍让人肉对照 | 🟢 低（纯前端样式与渲染收敛，**接口零新增**） | 1.5 |
| **V0.77.1**（补丁） | 信任修复：失败态不再伪装成正常 | ① `/data-health` 接口失败 / 零数据源 → 概览卡走 **「—」未知态**（新增 `.vl.unknown`）+ 失败说明与卡片同屏<br>② `/news` 静态默认分 `50.0` → 占位 `—`，新增 `fmtScore` / `renderLoadFailure`（占位 + 禁用保存 + 明说「不代表中性 50」）<br>③ `/silver` 加载条改由 `finally` 收起、错误提到首屏 `#alertBar`、去掉本机地址文案<br>④ 校准曲线「理论概率」→「完美校准基准线」，停止绘制恒为 0 的「实际命中率」假线（`_bucket_data` 后端从未实现）<br>⑤ SW 只读 API 改 **network-first**；价格类端点永不回退缓存，其余回退限 30 分钟内并注入 `X-SW-Cached-At`，4xx/5xx 不再入缓存 | 客户不会再看到「取数挂了却显示一切正常」—— 失败明说、缺数据留白，而不是给一个看起来确定的假值（`50.0` / 全绿 / 0% 曲线） | 🟢 低（纯前端 + 渲染分支，**接口零新增**） | 1.5 |
| **V0.77.2**（补丁） | 数据不丢与交互安全 | ① `/news` 保存打分补齐 `basis` / `review_note` 提交（原先请求体只有 `{score, direction, notes, slot}` → 客户勾的 12 个研判依据每次保存即归零、复盘「依据胜率」永远为空，而客户会以为是自己没勾；补齐时须注意 `selectedBasis` 是 `Set`）<br>② `/portfolio` 开仓价格框不再被轮询清空（原 `d.trend_index ? 空串 : 空串` 两分支同值 = 恒清空，抹掉 `fillPrice()` 初始化填好的 ETF 最新价，且可能让人按空价提交）→ 改为「客户输入过就不动」+ `priceTouched`<br>③ `/review` 空态指引由「可在该页填写并指定日期」（而打分页并无日期控件 → 断死）改为可执行路径，并如实说明补录入口尚未开放<br>④ `/weights`「恢复默认」加二次确认（含 Esc 取消）+ `try/catch` + 失败提示（原无确认、无 `else` → 一次误点即不可逆覆盖自定义权重并立刻改变决策，失败还静默无反应） | 客户的操作结果不再「看起来成功、实际丢失」—— 该记住的依据会记住、该填的价格不会被抹掉、该走的入口真实存在、不可逆的覆盖必须先确认 | 🟢 低（纯前端补丁，**接口零新增**、用例数不变） | 0.5 |
| **V0.78.0** | 一致性收口（**工程路线专项**，非本 UX 路线图项） | ① 阈值常量集中为四组语义互不相同的 IntEnum（`DirectionThreshold` / `LevelThreshold` / `DecisionThreshold` / `OpportunityWindowThreshold`），替换 5 个模块的裸字面量<br>② 决策档位 4 → **9 档**（新增缓冲档 `HOLD_CAUTIOUS`≥40），消除「指数 60-70 × 盈亏 -10%~+15% 什么都不做」的卡死区<br>③ 共振 `DIVERGENT` 扩为**三维幅度判定 + 子类型**，补齐「消息面 vs 另两面」整类漏判<br>④ **兜底差异化**：5 维度 `score` 改 `Optional[float]`，数据不足返回 `None`（前端灰色「— 未计入」）而非伪装中性 50；维度级与面级双归一化 | 客户不再看到「数据不足却显示中性 50」的假确定性 —— 该留白的留白、该归一化的归一化，`None`（没算出来）与 `50.0`（算出来是中性）不再同形 | 🟢 低（**接口零新增**、无 DB 迁移） | 3 |
| **新增门禁**（V0.77.1 / V0.77.2 扩展） | 渲染行为验证 `check_cluster_render.mjs` | 从各页源码提取**真实的代码块**，用最小 DOM 桩在 Node 里**真实执行**并断言产出的 HTML 结构与**失败态结果**（V0.77.0 起 33 条聚类断言 → **V0.77.1 扩至 102 条**，新增第 7 节「失败态渲染」：构造「接口挂掉」输入执行 `renderOverall` / `showTrendError` / `renderLoadFailure`；第 8 节「接线与 SW 缓存护栏」：桩 fetch 跑通 `load()` 全程、桩 caches + 真实 `Response` 执行 `serveStaleApi` / `cacheApiResponse`；**V0.77.2 扩至 125 条**，新增第 9 节「数据不丢与交互安全」：真实跑 `save()` 抓请求体、真实跑轮询价格逻辑、真实执行确认弹窗与 `resetAll`） | 补上「静态门禁全绿 ≠ 渲染正确」的盲区（`check_static_js.py` 只查语法 / 未定义调用 / DOM id）；失败路径人工点页面看不出来，只能靠构造输入验证 | 🟢 低 | 1 |

**完成度（2026-10-05）**：V0.68.0 ~ V0.74.3 已全部落地（V0.74.0 标 🟡，打印 / PDF 导出未做）；**V0.75.1 / V0.76.0 / V0.77.0 / V0.77.1 / V0.77.2 增补落地**（前两者原路线图未列，属「易用性收敛」缺口补齐；V0.77.0 聚类分组与 V0.77.1 信任修复是两轮界面评估的直接产出，同为原路线图未列的专项，**接口零新增**）；**V0.78.0 一致性收口**（阈值口径统一 / 决策档位 4 → 9 档 / 共振反向识别 / 兜底差异化）属**工程路线专项**（详见 [roadmap.md](./roadmap.md)），不在本 UX 路线图范围内。
**V0.75.0 拆为三步递进**：① 认证骨架 ✅ 已落地 ② 数据隔离 📋 V0.75.2 ③ 找回密码 + 用户管理 📋 V0.75.3（中间 `0.75.1` 让位给上述增补，保持版本单调递增）。

**合计**：~38 人天（约 7.5-8 周全职开发）。

---

## 二 各版本设计要点

### V0.68.0 · 导航折叠 + 全局搜索 + 客户端埋点底座

- **目标**：移动端首屏 ≤ 1 跳可达任意功能；操作可量化。
- **关键能力**：
  1. 顶栏在 ≤768px 自动折叠为汉堡菜单，桌面端 ≥769px 保留横排
  2. `Cmd/Ctrl+K` 唤起命令面板（输入即搜：标的 / 页面 / 时间区间 / 常用打分档位）
  3. 前端埋点底座（`telemetry.js`）：5 类事件（`page_view` / `action_click` / `range_change` / `theme_change` / `error_caught`）+ `sendBeacon` 批量上报 + `telemetry_events` 本地表
- **复用模式**：`static/account.js:20-220` IIFE + 自注入 CSS + `window.PM_Acc` 命名空间 → 抽屉 / 命令面板 / 埋点均沿用此模式；`static/help.js:21` `tourPrefix` + `localStorage.pm_help_seen_version` 升级重看机制
- **依赖**：§三·五 V0.68.0 已规划 SW（用于离线兜底）；本文档不重复
- **验证**：DevTools 模拟 360 / 480 / 768 / 1024 四档；埋点表 24h 内有数据；`Cmd+K` 在 5 页都生效
- **自身可观测性**：搜索成功率（`palette_query` → `palette_open` 比）、汉堡菜单触发率
- **人天**：3.5

### V0.69.0 · 主题切换 + 无障碍扩面

- **目标**：暗光环境舒适；WCAG 2.1 AA 通过。
- **关键能力**：
  1. 4 主题（light / dark / auto / **high-contrast**），CSS 变量统一切换
  2. Chart.js canvas 加 `role="img"` + `aria-label` + 数据表 fallback（点击展开）
  3. 全站 axe-core 0 critical + 键盘 Tab 序修复 + skip-to-content 链接
- **复用模式**：`static/help.css` 暗色主题 CSS 变量体系（V0.58.0 已有）→ 抽到 `static/themes.css` 全局；`static/freshness.js:9-156` 三态时效条（**主题切换不得破坏降级角标**）
- **依赖**：§三·五 V0.69.0 已规划主题基础（3 主题）；本文档扩面到 high-contrast + Chart.js a11y
- **验证**：axe-core 0 critical；high-contrast 在 lighthouse 对比度 100%；`prefers-reduced-motion` 友好
- **自身可观测性**：主题切换率（`theme_change` 事件分布）、dark 用户回访率
- **人天**：4

### V0.70.0 · 共振卡片 + 克数持仓 UX ✅ 已落地（V0.70.0）

- **目标**：把"判断准不准"做成日常可视化；实物金闭环。
- **关键能力**：
  1. 趋势页顶部"宏观×技术×消息面"三色共振信号卡（4 类信号：共振上行 / 共振下行 / 背离 / 中性）— `static/resonance-card.js` + 趋势页头部 `<section id="resonanceCard">`，点击弹窗显示 components 表 + STRONG_UP 命中率
  2. `/portfolio` 克数持仓并列展示（实物 / 积存金按克）— `positions.grams_held` 字段 + 持仓表 `<th>克数</th>` + 开/加/减仓均支持 `grams` 字段（与 `quantity` XOR 校验）
  3. 双口径收益曲线（按份 / 按克），切换不丢上下文 — `<button id="btnEquityUnit">单位：份</button>` + `drawEquityChart()` 在克数模式下右侧 Y 轴显示「g」
- **复用模式**：§六 6.4 `validateTrade` / `confirmDialog`（克数交易二次确认）；`static/trend.html:224-226` range-btn + `chart.destroy()` 模式；`static/portfolio.html` 既有 `confirmDialog` 复用
- **依赖**：§三·五 V0.70.0 后端 `services/resonance.py` + `positions.grams_held` 已合并
- **后端新增**（V0.70.0 P2 #7/#8）：
  - `GET /api/v1/resonance/signal` — 当日 4 类信号 + confidence 0-100
  - `GET /api/v1/resonance/history?days=N` — 历史回放（默认 30）
  - `GET /api/v1/resonance/strength-up?days=90&horizon=1` — STRONG_UP 命中率统计（样本 < 20 时 `sample_warning=true`）
  - `GET /api/v1/market/gold/gram-quote` — Au99.99 元/克实时报价
- **端点数**：40 → 43（+3）
- **测试增量**：+25 → 510 用例（共振 service 11 + API 3 + position service 10 + API 4 = +28；端到端含 `gold_gram_quote` 共振 API 共 +25）
- **验证**：共振卡片信号与回盘历史命中率 ≥ 70%（MVP 弹窗用 alert 显示；待 V0.71+ 接 sparkline）；克数交易平均操作 ≤ 30 秒（XOR 校验 + `gramsFromQty` 实时预览）
- **自身可观测性**：共振信号卡点击渗透率（`resonance_card_click`）；克数交易占比（`grams_trade_open`）；克/份切换（`equity_curve_switch_unit`）
- **人天**：4

### V0.71.0 · 多品种 UI + 回测可视化 ✅ 已落地（V0.71.0）

- **目标**：贵金属全景；参数可信度闭环。
- **关键能力**：
  1. `/silver.html`（白银 K 线 / 评估 / 决策三模块，复用 7 页骨架）
  2. `/backtest.html`（权重 / 阈值 / 阈值穿越回测配置 + 命中率 / 夏普曲线）
- **复用模式**：现有 7 页骨架（`portfolio.html` / `trend.html` 等），参数面 80% 复用；§六 6.7 回测可视化原则（已记录但未实现）
- **依赖**：§三·五 V0.71.0 已规划白银后端 + 回测引擎；本文档专注前端
- **验证**：白银页 K 线 / 决策 / 评估 三模块齐；回测页可配置 ≥ 3 维度参数并即时计算
- **自身可观测性**：白银用户占比；回测使用深度（每次会话参数调整次数）
- **人天**：5
- **落地交付**（2026-09-20）：
  - `static/silver.html`（530 行，深蓝色系，复用 trend.html FOUC / chart.js / chart-a11y / theme / responsive / help 6 处头部注入）：hero（白银 ETF 562800 + COMEX SI 双市场 + 与黄金联动提示） + 实时评估摘要（趋势指数 + 宏观因子 + 消息面） + 共振信号卡（V0.70.0 复用 silver 数据驱动） + 趋势参数维度 + 白银 ETF vs 纽约白银 对照（归一化双轴图 + 表格 + leader/gap） + 白银趋势主图（D/W/M 多时间框架切换） + 双市场报价卡 + 60 秒自动刷新 + 手动刷新
  - `static/backtest.html`（~480 行，金黄色系）：参数区（基准标的 5 选 1 + 回看窗口 + 权重候选 chips + 阈值带 chips + 立即回测按钮）+ 回测结果（5 张 summary 卡 + Sharpe 柱状图 + 最大回撤折线图 + 5 桶校准曲线 + 命中详情表前 30 行） + 5 分钟节流缓存角标（cachedBadge 同步 X-Backtest-Cached header） + 500ms debounce 自动重算 + 控件变更埋点 + 启动时 GET /config 应用用户保存的默认配置
  - `static/backtest-chart.js`（210 行）：IIFE + `window.PM_Backtest` + 自注入 CSS（缓存角标 / 表格 / summary 样式）+ 3 张 Chart.js + destroyCharts 显式释放内存 + ChartA11y.wrapChart 包裹
  - 9 页 nav 注入：trend / portfolio / trades / weights / news / review / central-bank / silver / backtest（每页 2 个新链接）
  - help 升级：VERSION V0.58.0 → V0.71.0（major 升级触发重看 tour）+ silver.html 4 步 tour + backtest.html 3 步 tour + GLOSSARY 加 562800/SI/Sharpe/最大回撤/校准曲线/回测 6 个术语 + renderGuideTab 加 V0.71.0 新增章节
  - 埋点同步：前后端 ALLOWED_EVENT_TYPES 加 silver_page_view / silver_nav_click / backtest_run / backtest_param_change 4 项

### V0.72.0 · 推送渠道 + PWA 安装

- **目标**：离线 / 后台也能收到；移动端可装桌面。
- **关键能力**：
  1. 邮件（SMTP）+ 微信（Server酱 webhook），用户配置中心
  2. `manifest.json` + 安装横幅（iOS Safari + Android Chrome）+ 通知中心抽屉
  3. 浏览器通知升级为 Web Push（需 VAPID 密钥 + SW push handler）
- **复用模式**：`src/app/middleware/trace.py` V0.67.0 纯 ASGI 中间件模式 → 新增 `PushSubscription` 仓储；`static/account.js` 配置中心 UI 模式
- **依赖**：§三·五 V0.72.0 已规划 SMTP / Server酱；本文档聚焦 Web Push + PWA 安装
- **验证**：iOS Safari 添加到主屏 → 启动为 standalone；邮件 / 微信收到测试告警
- **自身可观测性**：PWA 安装转化率（`pwa_install_prompted` → `pwa_installed` 漏斗）；邮件 / 微信 / Web Push 三渠道点击率
- **人天**：4
- **落地交付**（2026-09-21）：
  - **后端推送全栈**：Notifier Protocol + aiosmtplib SMTP + httpx Server 酱 + `send_with_retry` 5s/30s/5min 退避；AlertDispatcher 单例（`_sent_today` 去重 + `_quiet_queue` 静默时段累积）；BULLISH↔BEARISH 主轴翻转 + 单日波动 ≥3% 触发；`alert_rules` 复用 `app_settings` 表；scheduler `_capture_and_warm` 末尾钩入告警评估；`GET/PUT /api/v1/settings/alert-rules` + `POST /settings/test-email` + `POST /settings/test-wechat`（admin 守卫）；`pywebpush` + `py-vapid` + `cryptography` 依赖
  - **Web Push + PWA**：VAPID EC P-256 持久化到 `app_settings.vapid_keys`；`push_subscriptions` 表（迁移 `9e2f4a1b8c7d`，endpoint unique + archived_at index）；4 端点 `/api/v1/push/{vapid-public-key,subscribe,test}`（`subscribe` 兼 `POST` 订阅 / `DELETE` 取消）；`static/manifest.json`（192/512/maskable 图标 + start_url /portfolio + shortcuts）+ `static/sw.js`（gold-shell-v0.72.0 + gold-runtime-v0.72.0 双 cache + install/activate/fetch network-first HTML + cache-first /static/ + SWR /api/ GET + push handler + notificationclick）+ `static/offline.html`；`/sw.js` 路由 root scope `Service-Worker-Allowed: /` header；`static/pwa.js` SW 注册 + beforeinstallprompt 横幅 + iOS Safari 永久指引卡 + `urlBase64ToUint8Array` + `ensurePushSubscribed`；9 页统一加 manifest link + apple-touch-icon + pwa.js
  - **通知中心**：`static/settings.html`（10 页第 10 个，5 区：管理员 Token / 告警规则 + 4 渠道勾选 / SMTP 状态 + 测试 / Server 酱状态 + 测试 / PWA + Web Push 订阅）+ `static/settings.js`（表单 + GET/PUT alert-rules + test-email + test-wechat + push subscribe UI）+ `static/notifications.js` 推送统计抽屉（拉 /telemetry/stats 7d 聚合）
  - **安全前置**：`middleware/admin_auth.py` `require_admin` Depends `X-Admin-Token` 头 `secrets.compare_digest`，无 `ADMIN_TOKEN` env 时 skip（dev 友好）；`middleware/rate_limit.py` per-IP 60s sliding window 120 req/min 默认，`app_env!=test` 才注册（避免测试 429 误伤）；写端点全覆盖
  - **公开部署**：多阶段 Dockerfile（builder python:3.12-slim + gcc → runtime python:3.12-slim + curl + non-root appuser + HEALTHCHECK，镜像 1.2GB → 280MB）；`docker-compose.prod.yml` 5 服务（app / nginx / certbot / backup-cron / volumes app_data+certbot_www+certbot_conf+backups + network gold_net）；`nginx/conf.d/gold.conf` 80→443 redirect + TLS 1.2/1.3 + HSTS + X-Frame-Options DENY + `/static/` 直出 7d immutable + `/api/` 反代；`deploy/init-letsencrypt.sh` webroot 挑战幂等 + `--dry-run`
  - **help 升级**：VERSION V0.71.0 → V0.72.0 + GLOSSARY 加 PWA/SMTP/Server酱/WebPush/VAPID 5 个术语 + settings.html 5 步 tour + renderGuideTab V0.72.0 节
  - **埋点同步**：前后端 ALLOWED_EVENT_TYPES 加 `pwa_install_prompted` / `pwa_installed` / `push_channel_click` / `notification_center_open` / `notification_browser_click` 5 项

### V0.73.0 · i18n 框架 + 英文版 ✅ 已落地（2026-09-22）

- **目标**：海外华人 / 港台 / 英文用户可用；繁中覆盖达 60%；后端国家名解耦前端 i18n 字典。
- **关键能力**：
  1. **PR-N+7 · i18n 框架** —— `static/i18n.js` IIFE（`t/setLang/apply/fmt.{number,currency,date,dateTime,time,percent,relative}` 基于 `Intl.NumberFormat` / `Intl.DateTimeFormat`）+ 三语字典 `static/i18n/{zh-CN,zh-TW,en-US}.js` + 顶栏 `<select class="lang-sel">` 切换器（持久化 `localStorage.pm_lang`）+ FOUC guard inline head script
  2. **PR-N+8 · 英文版全 10 页覆盖** —— portfolio（已在 N+7）+ trend / weights / news / review / trades / silver / backtest / settings / central_bank 共 9 页全部标记 `data-i18n`；zh-CN 626 / en-US 627 / zh-TW 33 个 key
  3. **PR-N+9 · 繁中全量 + locale 格式化 + 后端解耦** —— ① zh-TW 扩展至 391 个 key，覆盖率 10.9% → 61.2%（country.* 33 + portfolio/trend/backtest/central_bank 全部 chrome + 6 页 h1/intros/col_*/footers + fresh.* 13）；② `static/freshness.js` `fmtAge` 改 `I18n.fmt.relative()`，tooltip / 警示 / 错误文案走 `fresh.*` 字典 13 key；③ 后端 `schemas/central_bank.py` `country_name: str \| None = None`（DB 列保留向后兼容）；`services/central_bank.py` `_resolve_country_name()` 兜底链 `DB → COUNTRY_NAMES[iso] → iso`；前端 `central_bank.html` 渲染链 `I18n.t('country.' + iso) → country_name → iso`；④ 新增 `test_i18n_format.py` 15 + `test_i18n_coverage.py` 7 + 阈值 10%→60%
- **落地交付**（2026-09-22）：
  - **PR-N+7**（已合 `ffabc9b`）：i18n.js + 三语字典 + 切换器 + portfolio 英文版 + 22 个 i18n 测试
  - **PR-N+8**（已合 `566063b`）：9 页英文版全覆盖（trend/weights/news/review/trades/silver/backtest/settings/central_bank）
  - **PR-N+9**（本次）：zh-TW 391 个 key + freshness.js 全本地化 + 后端 schema Optional + Service 兜底链 + 前端渲染链
  - **测试**：22 → 53（+31，含 format 15 + coverage 7 + 阈值升级），基线 621 → **644**
  - **目标分**：91.0 → **91.5**
- **复用模式**：`static/trades.html:215, 219` 现有 `toLocaleString("zh-CN")` 模式 → 全局 `format(num, locale)`；`static/account.js` 切换器 UI；后端 `COUNTRY_NAMES` dict（central_bank_data.py:55）→ 前端 `I18n.t('country.' + iso)`
- **依赖**：无（纯前端 + 后端 schema Optional 微调）
- **验证**：英文 / 繁中版 9 页无残留中文；语言切换 ≤ 200ms；货币日期按 locale 渲染；后端 `country_name` 兜底链永不返回 None
- **自身可观测性**：英文 / 繁中用户占比；语言切换频率；`i18n_fallback_hit` 埋点
- **人天**：6

### V0.74.0 · 仪表盘自定义 + 通知偏好

> 🟡 **部分落地（2026-09-26）**：① 卡片拖拽排序 ✅（N+17，`static/dashboard.js`）② 提醒规则面板 ✅（N+18，`settings.html` `#ruleModal` 四种 kind）③ 打印友好 CSS + 一键 PDF 导出 ⏳ **未落地**（仅 `portfolio.html` 有 `@media print` 隐藏拖拽控制条，无 `window.print()` 入口、无 `pdf_export_click` 埋点）—— 因此 M7 验收项「PDF 导出 ≤ 2 页」尚未满足。

- **目标**：个性化首页；通知降噪；月度报告。
- **关键能力**：
  1. 卡片拖拽排序（纯原生 `dragstart / dragover / drop`，无需 react-dnd）
  2. 提醒规则面板（≥X% 波动 / 指数跨档 / T+N 命中 / 自定义时段）
  3. 打印友好 CSS + 一键 PDF 导出（`window.print()` + `@media print`）
- **复用模式**：`static/help.js:21` `localStorage.pm_help_seen_version` 升级重看机制 → 新 `localStorage.pm_dashboard_layout` 持久化布局；§六 6.4 操作防错（拖拽须配合撤销 toast）
- **依赖**：无（纯前端 + `news_scores` 提醒规则扩展）
- **验证**：布局持久化跨刷新；通知规则触发准确率 ≥ 95%；PDF 导出 ≤ 2 页
- **自身可观测性**：自定义渗透率（默认 vs 自定义布局比）；提醒规则使用深度
- **人天**：5

### V0.75.0 · 多用户登录 + 数据隔离

> 🟡 **第一步（认证骨架）已于 2026-09-29 落地**，本版拆为三步递进：
>
> | 步骤 | 范围 | 状态 |
> |---|---|---|
> | **① 认证骨架**（本次） | `users` / `sessions` 表（迁移 `d5f81a3c9b47`）· bcrypt cost=12 · 服务端会话 + 撤销 · `HttpOnly`/`SameSite=Strict` cookie · CSRF 双提交 · 登录失败账号+IP 双维度节流 · `/api/v1/auth/{status,register,login,logout,me,change-password}` · `static/login.html` · 12 页顶栏账号菜单 · `AUTH_ENABLED` 开关（默认 false） | ✅ 已落地 |
> | **② 数据隔离** | `user_id` 透传业务表 + 复合索引 + 仓储层作用域 + `authz_violation` 审计 + 单租户→多租户迁移脚本 | 📋 V0.75.2 |
> | **③ 找回密码 + 用户管理** | 邮件 token（30 分钟过期，依赖 V0.72.0 SMTP）+ `/forgot-password` `/reset-password` + 管理员用户列表 / 禁用 | 📋 V0.75.3 |
>
> ⚠️ **第一步落地后的能力边界（务必知悉）**：开启 `AUTH_ENABLED=true` 后
> **除健康检查 / 登录注册登出 / 埋点外的全部 API 都要求登录** ——
> 即「登录才可用」成立，但**用户之间尚未隔离**（所有人看到同一份数据），
> 故 M8 验收口号「零越权事件」**尚未满足**。单机自用建议保持 `AUTH_ENABLED=false`。
>
> 落地细节（实现取舍）：
>
> - **服务端会话而非签名 cookie**：cookie 只放不透明随机串（`secrets.token_urlsafe(32)`），
>   会话事实存 `sessions` 表 → 登出 / 改密 / 禁用可**即时撤销**，并可审计在线设备。
> - **bcrypt 72 字节上限显式拒绝**：中文密码 24 个汉字即触顶；不静默截断，
>   避免「用户以为设了长密码、后半段其实无效」。未知账号也跑一次同代价伪哈希，打平耗时侧信道。
> - **CSRF 用全局 fetch 补丁而非逐个改调用点**：`static/auth.js` 包裹 `window.fetch`
>   自动回填 `X-CSRF-Token`，既有 11 个页面几十处写请求**一行未改**；
>   新增写端点也自动受保护（`sendBeacon` 埋点按协议豁免）。
> - **中间件注册在 `TraceIdMiddleware` 之前**（LIFO → 成为内层）：
>   401/403 响应仍带 CORS 头、Audit 日志带 trace_id、登录爆破先被 per-IP 限速拦一道。
> - **`/docs` 在 `APP_ENV=prod` + 开启认证时自动关闭**：否则接口清单对公网裸奔。
> - **`/auth/logout` 列为公开路径**：已登出后再点退出返回 `200 {revoked:false}` 而非 401
>   （旧标签页 / 重复点击是常态，报错反而像功能坏了）。

- **目标**：家庭 / 合伙多用户独立数据。
- **关键能力**：
  1. bcrypt 密码（cost=12）+ session cookie（HttpOnly + SameSite=Strict + Secure）+ CSRF token
  2. `user_id` 透传到 `accounts` / `positions` / `trades` / `news_scores` / `snapshots` / `gold_price_daily`；`AUTH_ENABLED` 环境变量兼容开关（单用户模式默认 `false`）
  3. `/login` + `/register` + 找回密码（邮件 token，依赖 V0.72.0 SMTP）
- **复用模式**：`src/app/middleware/trace.py` 纯 ASGI 中间件（V0.67.0）→ 新增 `AuthMiddleware`（在 trace 之前注册）；§三·五 V0.67.0 `set_trace_id` / `reset_trace_id` 手动管理 → 新 `set_user_id` / `reset_user_id`；§六 6.4 操作防错模式（注册 / 找回密码二次确认）
- **依赖**：V0.72.0 SMTP（找回密码）；Alembic 迁移（加 `user_id` 列 + 索引 + 复合主键调整）
- **验证**：单用户模式（`AUTH_ENABLED=false`）行为 100% 兼容 V0.74.0；多用户模式 A 用户看不到 B 用户数据；密码 bcrypt cost=12
- **自身可观测性**：登录成功率；多用户模式下数据隔离零越权事件（审计日志）
- **人天**：6

### V0.75.1 · 首页综合研判结论卡（增补）

> ✅ **已落地（2026-09-29）**：原路线图未列此版（0.75.1 原属「数据隔离」），实际落地时把「数据隔离」顺延为 V0.75.2，本版让位给**首页易用性收敛缺口**。

- **目标**：首页从「六个面板各自为政」变为「一眼看结论」。
- **关键能力**：
  1. **置顶结论卡**（`static/synthesis-card.js`，IIFE + `window.PM_Synthesis`，自注入 CSS 适配 4 主题）：一行结论（趋势指数 + 等级 + 行动建议 + 行动置信度 + 一句话总判）
  2. **三维分值条**：技术 30% / 宏观 40% / 消息 30%（权重与 `/weights` 同源），红=利多 绿=利空 **且附 ↑↓→ 文字符号**
  3. **一致性判定**：5 类结构（强同向看多/看空、弱同向、**技术 vs 宏观分歧**、中性）——**不在前端重算**，一律取 `/api/v1/resonance/signal`
  4. **仓位对照**：建议仓位 vs 当前持仓（`position_ratio` 后端恒为 `0` → 只显示「空仓 / 持有 N 份 · 浮盈浮亏」，**不臆造仓位占比**）
  5. **数据质量折损提示**：宏观静态参考值项数 / 名称 / 最新数据日 + 消息面未打分 + 行情源 Mock 降级市场数
  6. **黄金 ↔ 白银一键切换**：一次切换使 trend / decision / resonance **三个 target 同步生效**（`localStorage.pm_synthesis_asset`）
- **后端改动（唯一一处）**：`GET /api/v1/resonance/signal` 新增 `target`（`ny`/`etf`/`gram`/`silver_etf`/`silver_ny`/`silver_gram`，默认 `etf`，非法值 422）——此前白银页共振卡**写死 `etf`、一直在显示黄金的三维分值**。
- **收敛去重**：首页移除独立 `#resonanceCard` 与「今日操作清单」两块重复面板（能力并入结论卡，「共振详情」模态与「历史 + STRONG_UP 胜率」下钻保留）。
- **复用模式**：`services/resonance.py::compute_resonance()`（阈值 55/45 + `confidence = avg × (1 - stdev/55)`）作为**唯一一致性口径来源** —— 前端只消费不重算，避免后端调阈值后两处打架；`resonance-card.js` 的 `mount(containerId, opts)` 模式（V0.75.1 补齐导出）用于多页复用。
- **依赖**：无新依赖（纯前端 + 一个 query 参数）。
- **验证**：headless Chrome `--virtual-time-budget=75000` 快进跨过 60s 轮询后截图确认；黄金态指数 54.4 / 观望(WAIT) / 置信度低，白银态指数 52.8 / 技术面 58.4 —— 两态分值确实不同（旧版两者恒等，即缺陷所在）。
- **自身可观测性**：`localStorage.pm_synthesis_asset` 可反映黄金/白银关注度比（当前未接埋点）。
- **人天**：1.5

### V0.76.0 · 首页内嵌消息面打分器（增补）

> ✅ **已落地（2026-09-30）**：原路线图未列此版；承接 V0.75.1 的信息架构收敛 —— 结论卡解决了「一眼看结论」，但「录入判断」仍要整页跳 `/news`，决策回路没闭合。

- **目标**：把「客户评价 / 消息面打分」这个**用户唯一亲自产出**的维度搬到首页，做到「看结论 → 录判断 → 回看命中」全程不跳页。
- **关键能力**：
  1. **3 槽位状态一览**（`static/news-score-widget.js`，IIFE + `window.PM_NewsScore`，自注入 CSS 适配 4 主题）：每槽显示分值 / 权重（1:2:3）/ 方向徽标 / 提交时刻 / 备注摘要 / 是否补录，并可逐槽「修改」「撤销」。
  2. **当日有效分值 + 后端算式原样展示**：直接显示后端返回的 `formula`（如 `(1×45 + 2×70) ÷ 3`），**前端不重算加权**，与 `/news`、复盘页同源。
  3. **内嵌编辑器**：滑杆 + 快捷档位 / 沿用上次 + 方向判定 + 研判备注 + 12 个研判依据标签（取 `GET /api/v1/review/meta`）+ 复盘批注。
  4. **保存后即时刷新**：组件派发 `news-score-changed`，首页监听后重算口径并刷新结论卡与消息面评估行。
  5. **三次用尽不静默覆盖**：三槽打满后默认编辑目标保持第 3 槽并显式提示「将覆盖原值」。
- **后端改动**：**零**（复用 `GET|PUT|DELETE /api/v1/news-score` 与 `GET /api/v1/review/meta`）—— 写当日打分仍会触发 `TrendService.invalidate_for_news()` 缓存失效，首页随即重算。
- **刻意不轮询**：打分器含可拖拽滑杆与文本框，60s 定时重渲染会打断输入（滑杆跳回、光标丢失）；只读的 `#newsFactor` 交给首页既有轮询保鲜。
- **数据守门**：载入既有槽位时必须回填 `notes` / `basis` —— 仓储层 UPDATE 对这两项是**硬覆盖**（不传即清空）；而 `review_note` 走 `x or existing`（空值保留旧值、**无法经 API 清空**）。
- **复用模式**：沿用 `synthesis-card.js` 确立的组件范式（IIFE + `window.PM_*` + 自注入 `<style>` + `T(key, zh)` 中文兜底 + `[data-act]` 事件委托 + `i18n:change` 重渲染），新增脚本照此实现即可零成本接入导航与主题。
- **依赖**：无新依赖（纯前端）。
- **验证**：headless Chrome `--virtual-time-budget=75000` 跨过一次 60s 轮询后截图；另用**真实点击**的端到端探针覆盖「修改回填 / 直接保存不清空 / 快捷档位 / 沿用上次 / 切依据不丢文本 / 逐槽撤销复原」六条路径（全绿，跑完清理数据）。
- **自身可观测性**：⏳ **未新增埋点**（复用 `page_view`）。
- **人天**：1

---

## 三 与工程路线 §三·五 的关系

### 3.1 重叠版本双视角对照

| 版本 | §三·五 工程视角 | 本文档 UX 视角 | 协同点 |
|---|---|---|---|
| V0.68.0 | Prometheus / 跨源一致性 / 性能基准 | 导航折叠 + 全局搜索 + 埋点底座 | 埋点事件入 Prometheus 一起出 dashboard |
| V0.69.0 | 主题切换（3 主题 light/dark/auto）+ 全站 a11y + backfill 60→365 天 | 4 主题（含 high-contrast）+ Chart.js canvas a11y + axe-core 0 critical | backfill 扩窗支撑长期数据可视化 |
| V0.71.0 | 白银后端 + 回测引擎 | `/silver.html` + `/backtest.html` | UI 与算法同步发布；回测结果埋点观测 |
| V0.72.0 | 邮件 / 微信 + 公开部署 | Web Push + PWA 安装 + 通知中心抽屉 | 推送渠道合并测试；部署阶段 PWA 必须 ready |

### 3.2 仅本文档独有

- **V0.70.0** —— §三·五 已规划克数后端 + 共振算法，但**前端可视化是 UX 视角独占**（共振信号卡 + 双口径收益曲线）
- **V0.73.0** —— §三·五 完全未覆盖；i18n 是纯前端能力
- **V0.74.0** —— §三·五 完全未覆盖；仪表盘自定义 + 通知偏好是 UX 维度
- **V0.75.0** —— §三·五 完全未覆盖；多用户登录涉及数据迁移 + 安全审计，超出 §三·五 工程债范围
- **V0.75.1（增补）** —— §三·五 完全未覆盖；属**前端信息架构收敛**（把既有后端原料重排成决策顺序），不新增后端能力（除 `resonance/signal?target=` 一个 query 参数）
- **V0.76.0（增补）** —— §三·五 完全未覆盖；属**前端能力下沉**（把 `/news` 的打分器内联进首页 `#newsScoreCard`），后端**接口零新增**（复用既有 `news-score` 三端点 + `review/meta`）

### 3.3 不在本文档的 7 项

| 项 | 理由 |
|---|---|
| 回测引擎深度优化（多目标 / 蒙特卡洛） | 留给 V0.76+；V0.71.0 只做基础回测 UI |
| 白银完整交易闭环（多账本 / 收益曲线 / 复盘） | V0.71.0 只做行情 + 评估 + 决策三件套 |
| 移动原生 App（iOS / Android） | Web PWA（V0.72.0）足够；原生需 React Native 等新栈 |
| 新 CDN / 构建工具（Vite / Webpack） | 保持"纯静态 + 内联 JS"原则；首屏可缓存 |
| ML 预测 / 神经网络 | 留 V0.76+；当前 7 页决策够用 |
| 社交分享 / 评论 / 多用户互动 | 单机部署无后端支撑；留 V0.76+ |
| 对外 API（OAuth / 第三方接入） | 多用户（V0.75.0）后才考虑 |

---

## 四 不变项（Invariants）

| # | 不变项 |
|---|---|
| 1 | **基线只增不减**：路线图制定时是 7 页 + 40 端点 + 454 测试；**V0.76.0 实测 13 页 + 67 路径（76 端点）+ 866 测试 / 23 共享脚本**（每次迭代只许新增，既有的页面 / 端点 / 用例不得因新功能失效） |
| 2 | **数据表只读扩展**（`gold_price_daily` / `daily_snapshots` / `news_scores` / `accounts` / `positions` / `trades` —— 只加列，不改主键） |
| 3 | **现有 JS 资产不重写只扩展**（`account.js` / `help.js` / `freshness.js` / `responsive.css` 命名空间稳定；新增资产通过 `window.PM_xxx` IIFE 自注入） |
| 4 | **`pm_help_seen_version` 升级强制重看行为保留**（V0.58.0 帮助体系不变） |
| 5 | **Chart.js 4.4.3 本地 vendor（`static/vendor/chart.umd.min.js`，V0.74.3 起不再走 CDN）+ 无新框架 / 构建工具**（保持"纯静态 + 内联 JS"原则） |
| 6 | **`freshness.js` 三态时效条静默语义保留**（主题切换不得破坏降级角标的颜色与可读性） |
| 7 | **`gold_account_id` localStorage 键名不变**（与 V0.62.0 起向后兼容；多账本记忆不被破坏） |
| 8 | **telemetry 数据本地落库、不外发**（单机部署隐私；埋点只在 `telemetry_events` 表，`sendBeacon` 走同源） |

---

## 五 里程碑 M1-M10

| 里程碑 | 版本 | 验收口号 |
|---|---|---|
| **M1** | V0.68.0 | "首屏 ≤ 1 跳达标，埋点有数据" |
| **M2** | V0.69.0 | "暗色主题全站 OK + axe-core 0 critical" |
| **M3** | V0.70.0 | "共振卡片信号与历史命中率 ≥ 70% + 克数闭环" |
| **M4** | V0.71.0 | "白银 / 回测可独立跑（≥ 3 维参数）" |
| **M5** | V0.72.0 | "PWA 可装 + 三渠道推送全通" |
| **M6** | V0.73.0 | "英文版完整可用，切换 ≤ 200ms" |
| **M7** | V0.74.0 | "首页可个性化，PDF 导出 ≤ 2 页"（🟡 个性化 ✅ / PDF 导出 ⏳） |
| **M8** | V0.75.0 | "多用户独立数据，零越权事件"（⏳ **认证骨架 ✅，数据隔离未做 → 口号尚未达成**，顺延 V0.75.2） |
| **M9** | V0.75.1（增补） | "首页一眼看结论，数据可信度如实暴露"（✅ 结论卡 + 三维 + 一致性 + 仓位对照 + 数据质量折损提示；**不追求「看起来可信」，而追求「知道哪里不可信」**） |
| **M10** | V0.76.0（增补） | "看结论 → 录判断 → 回看命中，全程不跳页"（✅ 首页内嵌打分器把「客户评价」这条**用户唯一亲自产出**的维度收回首页；**不追求「更多面板」，而追求「决策回路闭合」**） |

---

## 六 Cross-doc references

- **已落地 UX**（6.1 ~ 6.12）→ [docs/improvement-path.md §六](./improvement-path.md)
- **工程路线**（V0.68.0 → V0.72.0）→ [docs/improvement-path.md §三·五](./improvement-path.md)
- **应用能力 + 架构说明**（功能清单 + API 表 + 数据源）→ [docs/application-guide.md](./application-guide.md)
- **文档对账**（代码 vs 文档 vs README）→ [docs/feature-alignment.md](./feature-alignment.md)
- **项目主页**（版本 + 测试数 + 功能清单）→ [README.md](../README.md)

---

## 附录 A · 工时估算汇总

| 版本 | 人天 | 累计 |
|---|---|---|
| V0.68.0 | 3.5 | 3.5 |
| V0.69.0 | 4 | 7.5 |
| V0.70.0 | 4 | 11.5 |
| V0.71.0 | 5 | 16.5 |
| V0.72.0 | 4 | 20.5 |
| V0.73.0 | 4 | 24.5 |
| V0.74.0 | 5 | 29.5 |
| V0.75.0 | 6 | 35.5 |
| V0.75.1（增补，原路线图未列） | 1.5 | 37 |
| V0.76.0（增补，原路线图未列） | 1 | 38 |

**合计**：~38 人天（约 7.5-8 周全职开发）。

---

## 附录 B · 每个版本的验证清单

实施每个版本时必跑：

1. **本地手测**：`MARKET_PROVIDER=mock` 启动新端口（8899）实例，按版本"验证"段逐项检查
2. **JS 门禁**：`python scripts/check_static_js.py`（每个新 JS 文件都要过）
3. **测试**：
   - 服务层 ≥ 5 个新测试（参数计算 / schema 校验 / 边界）
   - 前端 ≥ 2 个 Playwright 测试（拖拽 / 命令面板 / 主题切换 / 命令面板）
4. **埋点**：版本上线后 24h 检查 `telemetry_events` 表有该版本对应事件
5. **文档三方同步**：每个版本结束时 README + application-guide + feature-alignment + 本文档 同步更新

---

## 附录 C · 每版本「自身可观测性」总表

| 版本 | 埋点事件 | 派生指标 |
|---|---|---|
| V0.68.0 | `palette_open` / `palette_query` / `nav_drawer_open` / `telemetry_page_view` | 搜索成功率 / 汉堡菜单触发率 / 7 日回访率 |
| V0.69.0 | `theme_change` / `a11y_skip_link_click` | 主题切换率 / dark 用户占比 / 对比度合规率 |
| V0.70.0 | `resonance_card_click` / `grams_trade_open` / `equity_curve_switch_unit` | 共振卡渗透率 / 克数交易占比 |
| V0.71.0 | `silver_page_view` / `backtest_run` / `backtest_param_change` | 白银用户占比 / 回测使用深度 |
| V0.72.0 | `pwa_install_prompted` / `pwa_installed` / `push_channel_click` | PWA 安装转化率 / 三渠道点击率 |
| V0.73.0 | `lang_change` / `i18n_fallback_hit` | 英文用户占比 / 翻译覆盖率 |
| V0.74.0 | `dashboard_drag_end` / `notification_rule_save` / `pdf_export_click`(⏳) | 自定义渗透率 / 提醒规则使用深度 |
| V0.75.0 | `login_success` / `login_fail` / `logout` / `authz_violation` | 登录成功率 / 越权事件计数（应恒为 0；`authz_violation` 待 V0.75.2 数据隔离后才有数据） |
| V0.75.1 | ⏳ **未新增埋点**（结论卡复用 `page_view`；`localStorage.pm_synthesis_asset` 已落盘但未上报） | ⏳ 黄金/白银关注度比（待接埋点才可派生） |
| V0.76.0 | ⏳ **未新增埋点**（打分器复用 `page_view`） | ⏳ 首页打分转化率（首页直接打分 / 跳 `/news` 打分 之比，待接埋点才可派生） |

---

## 附录 D · V0.75.x 落地后的配置速查

> V0.75.1（结论卡）/ V0.76.0（首页打分器）**均未新增任何环境变量**；下表为 V0.75.0 认证体系引入的全部开关。

| 变量 | 默认 | 说明 |
|---|---|---|
| `AUTH_ENABLED` | `false` | 总开关。false = 单用户模式（Auth/Csrf 中间件纯透传、不查库、不下发 cookie） |
| `ALLOW_REGISTRATION` | `true` | 关闭后只有已有用户可登录；**库中无用户时首个注册者始终可建号**（防「没人能建号」死锁） |
| `SESSION_TTL_HOURS` | `336`（14 天） | 绝对过期，不随活跃度顺延 |
| `SESSION_COOKIE_NAME` / `CSRF_COOKIE_NAME` | `pm_session` / `pm_csrf` | 会话 cookie 为 HttpOnly；CSRF cookie 必须非 HttpOnly（double-submit 需 JS 读取） |
| `SESSION_COOKIE_SECURE` | `false` | ⚠️ 生产必须 `true` + HTTPS；本地 http 下设 true 会导致「登录成功却立刻要求再登录」 |
| `BCRYPT_COST` | `12` | 改值不影响既有哈希（cost 写在哈希串里） |
| `LOGIN_MAX_ATTEMPTS` / `LOGIN_ATTEMPT_WINDOW_MINUTES` / `LOGIN_LOCKOUT_MINUTES` | `5` / `15` / `15` | 账号与 IP 双维度计数，任一命中即锁 |
| `SESSION_TOUCH_SECONDS` | `300` | `last_seen_at` 落库节流（避免每请求一次 UPDATE） |
| `TRUST_PROXY_HEADERS` | `false` | nginx / CDN 前置时置 `true`（取 XFF 首跳做审计 IP；⚠️ XFF 可伪造，不用于安全判定） |