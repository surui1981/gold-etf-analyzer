# 开发与产品路线图

> ⚠️ **本文件已转为历史档案（2026-10-22 标注）。** 它的基线停在 **V0.100.0**、
> 「当前焦点」还写着 V0.101，实际已发到 **V0.116.0**（落后 16 个版本）；
> §2.2 把 V0.111.0 描述成「阈值口径可覆盖」，而 V0.111.0 实际交付的是「宏观因子手动校准」。
>
> **当前推进计划见 [next-steps.md](next-steps.md)**（V0.117.0 起，全部条目已实测复现）。
> 本文件的 §2.2 / §2.3 内容仍然有效，已并入 next-steps.md §三。
>
> ⚠️ **另见 [app-improvement-path.md](app-improvement-path.md)（2026-10-23 新增）** ——
> 应用整体改进路径。它实测发现本文件 §2.3 的前提是错的：
> 原文写「已有 ~21,900 条评估基线」，实测 `scoring_daily_wide` 只有 **47 行**。
> **K 项（§2.3）的 go/no-go 依据必须先按 app-improvement-path §二 B2 修正。**

> **目标读者**：开发者（路线决策）｜ **状态**：⚠️ 历史档案 ｜ **最近更新**：2026-08~10
>
> **配套文档**：
> - [version-status.md](version-status.md) — **应用版本状态（单一真源）**：现在到底是哪个版本 / 4 处版本号一致性 / 各来源覆盖矩阵与已知缺口 / 怎么自己查
> - [app-improvement-path.md](app-improvement-path.md) — **应用整体改进路径**（四层演进路线，全部条目已实测）
> - [next-steps.md](next-steps.md) — 当前推进计划（V0.117.0 起，缺陷清单）
> - [improvement-path.md](improvement-path.md) — ⚠️ 已归档（V0.50~V0.78 实施路线与 UX 度量，内容全部交付）
> - [parameter-evaluation.md](parameter-evaluation.md) — 参数评估（11 项改进需求与诊断，10/11 已交付）
> - [development.md §11](development.md) — 历史改进计划 / P1-P3 大路线（已全部落地）
> - [ux-roadmap.md](ux-roadmap.md) — V0.68-V0.76 UX 应用/能力路线（**整份已交付，作为历史档案保留**）
> - [improvement-path.md](improvement-path.md) — 改进路径 + 部署状态 + 验收度量（**大部分已交付**，保留作历史档案与部署速查）
> - [docs/reports/](reports/) — 阶段性分析报告（版本差距 / UX 评估 / 推进路线 / 内部复盘）

> **本文件范围**：把前三份文档的活跃内容**聚类重组**到一处 —— 单一历史里程碑表 + 当前焦点 + 推进主线 + V0.96+ backlog + 维护线。
>
> **基线版本**：**V0.100.0**（commit `5c1eeef`，2026-10-17）
> **当前焦点**：V0.101 Python 3.13 迁移收口（C1-C3a 已落，C3b/C4 待 commit）
> **历史链已在 §1 收敛到一处** —— 文中其它位置不再重复列举版本号。

---

## §0 一页总览

```
                            2026-10              2026-11              2026-12+
V0.100.0  ──┬────────────┬────────────┬─────────────────────▶ 持续
(基线)      │            │            │
            ▼            ▼            ▼
        V0.101        V0.102        V0.103+
       "Python 3.13    "K 项 ·       持续维护
        迁移收口"       多市场独立校准"
        1 周内         3-4 周         持续
        ──────────────────────────────────────
        并行线:
        维护线 V0.100.x / V0.101.x ── hotfix / 依赖升级 / 测试扩充（每 2 周 1 个）
        AI 助手深化 / 移动端 PWA 深化 ── 按用户优先级
```

### 关键决策
- **V0.78-V0.100 全部交付**：参数口径统一、决策矩阵、回测异步、银 / 多市场、AI 助手、双层导航、SSE 流式、消息面 pending、Python 3.13 迁移中。详见 §1。
- **K 项（多市场独立校准）仍是 P3 唯一未交付项**：[`parameter-evaluation.md` §4.3](parameter-evaluation.md) 评估投入 3-4 周；详见 §3 K 项。
- **维护线持续运转**：bugfix / 依赖升级 / 测试扩充不阻塞主版本。

---

## §1 历史里程碑（截至 V0.100.0）

**单一权威来源** —— 文中其它章节仅引用本表，不重复列举版本号。

### 工程化阶段（V0.50-V0.77）

| 版本 | 日期 | 主题 |
|---|---|---|
| V0.50 | 2026-08-末 | P0 稳定可信 + P1 高频 + P2 快照自动捕获 |
| V0.51 | | 投资指引基准切换为纽约金（COMEX） |
| V0.51.1 | | 启动健壮性修复（Alembic 子进程化 + WAL checkpoint） |
| V0.52-V0.55 | | 易用性 P3（时效条 + 响应式 + 决策可解释 + 操作防错 + 主动提醒） |
| V0.57.0 | | 央行购金数据化与自动化 |
| V0.58.0 | | 新手引导与帮助体系（tour + glossary + 15 项 inline tooltip） |
| V0.59.0 | | 行情源配置化（4 provider） |
| V0.60.0 | | 行情实时性增强（缓存 TTL + 日内 4 时点刷新） |
| V0.61.0 | | 交易闭环 + 业绩分析（收益曲线 / 获利分析） |
| V0.62.0 | | 单用户多账本 + 交易历史查询页 |
| V0.62.1 | | 收益回放口径修复 |
| V0.63.0 | | 评估指数历史曲线升级（4 条线 + 区间切换） |
| V0.64.0 | | 多时间框架（60D / 52W / 24M + ISO 周界 / 年月聚合） |
| V0.65.0 | | 消息面每日 3 次打分（1:2:3 加权） |
| V0.66.0 | | 研判复盘与准确率校准（T+1/T+3/T+5 + 校准曲线） |
| V0.67.0 | | 框架基础补齐（CI/CD + X-Request-ID + 价格 schema 校验） |
| V0.68.0 | | UX 启动版：导航折叠 + ⌘K 命令面板 + telemetry 埋点底座 |
| V0.69.0 | | 4 主题切换（light / dark / auto / hc）+ 键盘导航 + 价格日历扩窗 |
| V0.70.0 | | 共振信号卡（4 类）+ 克数持仓 + 双口径收益曲线 |
| V0.71.0 | | 白银 K 线 + 回测可视化（3 维权重网格 + 阈值带扫描） |
| V0.72.0 | | 推送渠道（SMTP + Server酱 + Web Push）+ PWA + 公开部署 |
| V0.73.0 | | i18n 繁中全量 61.2% + 后端国家名解耦 |
| V0.74.0 | | 仪表盘自定义（拖拽）+ 告警规则 CRUD（🟡 PDF 导出未做） |
| V0.75.0-V0.75.3 | | 多用户登录 + 数据隔离 + 找回密码（3 段递进） |
| V0.76.0 | | 首页内嵌消息面打分器（增补） |
| V0.77.0 | | 界面聚类分组（13 页审计 23 处→ 5 处改造 + 3 处修复） |
| V0.77.1 | | 信任修复：失败态不再伪装正常（/data-health 全绿 → 「—」未知） |
| V0.77.2 | | 数据不丢与交互安全（basis / review_note 补齐 + 输入不清空 + 二次确认） |

### 一致性收口 + 决策补全（V0.78-V0.80）

| 版本 | 日期 | 主题 |
|---|---|---|
| **V0.78.0** | 2026-10-05 | **阈值口径统一 + 决策补全**（Step A-D：阈值常量四组 IntEnum + 决策 9 档 + 共振反向识别 + 兜底差异化） |
| V0.78.1 | 2026-10-05 | SW 缓存版本脱钩 + PWA 门禁 + 3 道机械门禁 |
| V0.78.2 | 2026-10-05 | 门禁可信度修复（CI 八道门禁 + 14 例常驻回归） |
| **V0.79.0** | 2026-10-07 | **阈值动态化 + 回测增强**（Step G/E/F/H：WeightGrid 嵌套 + 异步回测 + 技术面组内平均 + 样本阈值分层） |
| **V0.80.0** | 2026-10-08 | 决策网格化 + 仓位结合（暂存为 P3 #12 待闭环） |

### UX 与可信度持续打磨（V0.81-V0.86）

| 版本 | 日期 | 主题 |
|---|---|---|
| V0.80.1 / V0.81.0-V0.82.0 | 2026-10-08 至 09 | admin token 双通道 + LAN 多终端（V0.82 主题由「多市场」调整为 LAN 痛点） |
| V0.83.0-V0.83.4 | 2026-10-10 | 主页 UI 改版 + 共享 topnav + i18n 110 gap + 限速 + freshness 降级 |
| V0.84.0 | 2026-10-10 | 状态条方案 C · 数据时效 + 警示合并 1 行 disclosure |
| V0.85.0 | 2026-10-11 | 时效迁移 /data-health + 健康摘要 chip + 主页紧凑化 |
| V0.86.0 | 2026-10-11 | 决策可解释性增强（拆解 + 对比 + tooltip 三件套） |
| V0.86.1 | 2026-10-11 | 数据健康跳转 404 hotfix |

### 维护线 + 测试扩充（V0.87-V0.92）

| 版本 | 日期 | 主题 |
|---|---|---|
| V0.87.0 | 2026-10-11 | `scripts/check_routes.py` HTTP 门禁 + 27 例路由冒烟 |
| V0.88.0 | 2026-10-12 | 维护线 src/ 87→90%+（admin 19 例 + grams 100% + import_central_bank 98%） |
| V0.90.0 | 2026-10-12 | 版本号 bump（V0.89 跳过） |
| V0.91.0 | 2026-10-12 | 复盘报告 PDF 一键导出 |
| V0.92.0 | 2026-10-14 | 历史打分数据汇总 · scoring_daily_wide 物化宽表 + 5 端点 |

### Scoring 与多市场深化（V0.92.1-V0.95.1）

| 版本 | 日期 | 主题 |
|---|---|---|
| V0.92.1 | 2026-10-15 | 行级命中筛选（hit=yes 红 #dc2626） + T+0 outcome + verdict card |
| V0.93.0 | | |
| V0.94.0 | | |
| V0.95.0 | 2026-10-15 | 4 指数时序表「横盘日数」→「NY 金美元/盎司收盘」 + backfill 28/39 |
| V0.95.1 | 2026-10-15 | 4 指数时序桶排序降序（最近→远期自上而下） |

### 后向能力大爆发（V0.96-V0.100）

| 版本 | 日期 | 主题 |
|---|---|---|
| **V0.96.0** | 2026-10-16 | 命中分析 Tab + /hit-stats-all + 4 horizon 1 次取 + 4 dataset 柱状图 + 3 mini card |
| **V0.97.0** | 2026-10-XX | AI 智能分析页（/ask 3 pane chat + 5 tool 只读 + ClaudeClient httpx） |
| V0.97.1 / V0.97.2 | | 3 级降级兜底（miniMax proxy_fallbacks + L1 同时平铺 tool_use/tool_result） |
| **V0.98.0** | 2026-10-XX | 双层导航 7 顶场景 + 4 子场景 + /ask SSE 流式（sse-starlette + EventSource） |
| **V0.99.0** | 2026-10-XX | 白银 SGE + 3-market 页面重构（em+sina 备援 + SGE provider + 3 端点 + silver.js 拆 + 升贴水表） |
| **V0.100.0** | 2026-10-17 | 消息面未打分 → 综合指数 pending（NewsScoreOut.score=None 替代 50 兜底，trend.html / silver.html 参数分两栏 + pending chip） |

### 今日要闻产品线 + 数据时效透明化（V0.102-V0.109.2）

> V0.110.0 补记：本段此前缺失，导致 §1 里程碑表在 V0.100.0 处断了 9 个版本。
> **这条产品线（今日要闻）是 V0.102 之后唯一的持续投入方向**，且从 V0.106.0
> 起已从"子页"提级为**顶级场景**（顶 nav 第 2 位）。

| 版本 | 日期 | 主题 |
|---|---|---|
| **V0.102.0** | 2026-10-18 | 今日要闻 readhub 财经流（`news_feed_items` 表 + fetcher 5min cache + 6h 调度 + `/headlines` 页） |
| V0.103.0 | 2026-10-19 | 我的收藏（收藏 / 永久存储 / 档案管理页 + 9 端点） |
| V0.104.0 | 2026-10-19 | headlines 按日期分页（单日模式 + 日期导航） |
| V0.105.0 | 2026-10-19 | headlines 分类筛选（5 类关键词分类器 + 与日期/site 正交叠加） |
| V0.106.0 | 2026-10-19 | 今日要闻提级为**顶级场景** + 调度 6h→4h 加密 |
| V0.106.1 / V0.106.2 | 2026-10-19 | home 场景卡 5→7 同步顶 nav；16 文件去掉 8888 硬编码（CORS 根因修复） |
| V0.107.0 / V0.107.1 | 2026-10-19 | 按天聚合 + 刷新 UX；分类聚焦 + 弃入「其他」+ page_size 20→50 |
| V0.108.0 / V0.109.0 | 2026-10-20 | 站点黑白名单 + 财经加强；分类词边界修复 + 发布词精度 |
| V0.109.1 | 2026-10-20 | 白银 3-market 页面重构（em+sina 备援 / SGE provider / silver.js 拆分） |
| **V0.109.2** | 2026-10-20 | 白银数据时效透明化（`data_as_of` + staleness 检测 + 滞后 chip） |
| **V0.110.0** | 2026-10-21 | **宏观因子手动校准**（`/weights` 页录入当日读数，覆盖 dxy/vix 过期常量）+ docs 整理 |
| **V0.118.0** | 2026-10-25 | **宏观面 5 因子 → 8 因子**（+美债 2Y / +10Y-2Y 利差 / +10Y 实际利率）；`dxy`/`vix` 接实时源；**阈值滚动分位首次生效**（回填 252 个交易日） |

> 逐版本细节见 [releases/index.md](releases/index.md) §1.4.1。

### 当前（V0.118.0，宏观面参数扩容 + 阈值动态化）

| 版本 | 进度 | 主题 |
|---|---|---|
| **V0.118.0** | ✅ 已落 | 宏观面 8 因子 + 全因子实时源 + 滚动分位阈值生效（见 §2.1b） |
| **V0.110.0** | ✅ 已落 | 宏观因子手动校准 + docs 整理（见 §2.1） |

> 完整技术实现细节（V0.78 Step A-D、Step G/E/F/H、V0.80 决策网格化等）见 [附录 E 历史实现细节](#附录-e--历史实现细节v078-v080)。

---

## §2 推进主线（V0.101+ 主动作）

按"必须做 vs 可选择"分级。

### 2.1 V0.110.0 · 评估参数可维护化（✅ 已落）

**主题**：「有些核心评估参数更新不及时」—— 让用户能自己录入，而不是等我们改代码。

**根因**：`MacroFactorService` 的 5 个因子里，`dxy` / `vix` **根本没有自动源**，
用的是 `STATIC_REF` 里 **2026-08-28** 的硬编码常量（96.5 / 18.5）。两者在宏观面
内部合计权重 0.40，宏观面又占综合指数 0.40 —— **综合指数的 16% 建立在两个半月前的
常量上**，而且 UI 上完全看不出来（数字照常显示，没有任何时效标注）。

**做法**（详见 [releases/v0.110.0.md](releases/v0.110.0.md)）：

1. `app_settings` 新增 key `macro_factor_overrides`（5 因子 × 值/日期/备注）
2. `_collect()` 优先级链改为：**用户手动覆盖 > 自动源 > 内置常量**
3. `/weights` 页新增「宏观因子手动校准」卡片：同屏显示「当前生效值 + 数据日期 +
   来源标记」，5 行 number/date/text 输入
4. 覆盖生效后 `source` 标为「手动输入」，滞后 > 1 交易日显示琥珀 chip
5. 保存即失效宏观评分 10min 缓存 —— 不然用户填完看到旧指数会以为没生效

**边界**：只解决"**输入值**过期"。"**阈值口径**过期"（因子的 best/worst、
4 组 IntEnum）见 §2.2。

> **V0.118.0 补记**：本节描述的「`dxy` / `vix` 根本没有自动源」已不成立 ——
> 两者分别改用 Yahoo `DX-Y.NYB` 与 FRED `VIXCLS`（同尺度，存量手动校准值不失效），
> 手动校准卡从「补空缺」降级为「人工顶替」。阈值侧的 best/worst 也已由滚动分位接管。
> 本节保留为历史脉络。

### 2.1b V0.118.0 · 宏观面 5 因子 → 8 因子 + 阈值动态化（✅ 已落）

**主题**：宏观面原来只有 5 个因子，其中 2 个（`dxy` / `vix`）**没有自动源**、
3 个（`us10y` / `us30y` / `cb_gold`）长期贴着硬编码阈值触底 —— 35% 的宏观权重
贡献恒为 0（宏观面 40%、综合指数 40% ⇒ 综合指数的 **14% 是死重**）。

**做法**（详见 [releases/v0.118.0.md](releases/v0.118.0.md)）：

1. 因子集扩到 8 个：+ `us2y`（2Y 收益率）、+ `curve_10y2y`（10Y−2Y 利差）、
   + `real10y`（10Y TIPS 实际利率，权重 20% —— 零息实物资产的定价锚）
2. `dxy` → Yahoo `DX-Y.NYB`、`vix` → FRED `VIXCLS`（**同尺度**，存量校准值不失效）
3. 回填 252 个交易日历史到 `daily_macro_factors`
   （`scripts/backfill_macro_factors.py`），**V0.79.0 造的滚动 90/10 分位机制首次生效**
4. 静态兜底值不再写入历史表 —— 判定函数是 `is_persistable_source`；
   否则一次上游故障就会把假常量写进滚动窗口，把阈值带偏
5. 旧 5 键权重配置按比例缩放迁移到 8 键（`_migrate_missing_factors`），
   存量用户的自定义权重**不被静默重置**

**顺带修**：`/backtest` 的「宏观内部权重」一直是坏的 —— 键写的是中文维度名，
与快照 `macro_detail` 的因子 key 对不上，启用后永远跑出 0 行。V0.118.0 改成因子 key。

**顺带修 2（更严重）**：滚动分位的 `best/worst` 方向此前**一律 P90**，
对 6 个负相关因子（美元 / 三档美债 / 实际利率 / 利差，占宏观权重 65%）整个反了。
该缺陷自 V0.79.0 起一直休眠（样本不足 → 从未激活），**回填历史让它一次性接管时
必现**（宏观指数一度从 39.7 分判成 71.2 分，方向反了）。V0.118.0 按每个因子的
`positive` 标志取分位方向，并加 3 个回归用例逐因子核对。

**边界**：新增 3 个因子从 V0.118.0 起才落快照，回测网格暂不覆盖（历史快照没有它们）。

### 2.2 V0.111.0 · 阈值口径可覆盖（下一步，2-3 周）

**主题**：把「阈值」也做成可维护的，而不是散落在源码里的常量。

**问题清单**（V0.110.0 盘点得出，全部 🔒 硬编码、零 UI）：

| 参数 | 当前值 | 位置 | 影响 |
|------|--------|------|------|
| 宏观因子 `best` / `worst` | 8 因子硬编码兜底值 | `services/macro.py:57-136` | **V0.118.0 已大幅缓解**：样本充足时改用近 252 日滚动 90/10 分位，硬编码值降级为兜底；剩余问题只剩「用户想手动改阈值」这一层 UI |
| `DirectionThreshold` 6 档 | 70/55/60/40/45/25 | `schemas/thresholds.py:19-36` | 20+ 处消费点 |
| `LevelThreshold` 4 档 | 75/55/45/25 | `schemas/thresholds.py:39-51` | 等级 + 仓位档位 |
| `OpportunityWindowThreshold` 3 档 | 70/55/40 | `schemas/thresholds.py:54-66` | 机会窗口 |
| `DecisionThreshold` 5 档 | 75/65/55/50/40 | `schemas/thresholds.py:69-89` | 9 档决策矩阵 |
| `GROUP_WEIGHTS` 3 组 | 0.50/0.30/0.20 | `services/trend.py:78-84` | 组内平均模式下的技术面合成 |
| 动态阈值预热门槛 | 60 样本 / 252 日 | `services/macro_thresholds.py:57-58` | **V0.118.0 已解**：新环境用 `scripts/backfill_macro_factors.py` 从 H.15 / FRED / Yahoo 自带历史回填 252 个交易日，门槛不再是死结 |

**实施步骤**：

1. `schemas/thresholds.py` 增加一份 `ThresholdConfig` Pydantic 模型承载全部档位
   （默认值 = 现有 IntEnum 值，**向后兼容**）
2. 新增 `settings` key `threshold_config` + `GET/PUT /settings/thresholds`
3. 把 ~20 处 `int(DirectionThreshold.X)` 改为读注入的 config；
   `TrendService` / `DecisionService` / `ScoringService` / `ResonanceService` 统一注入
4. `/weights` 页加「阈值」tab（与权重、宏观校准并列）
5. **顺带修一个现存 UX 陷阱**：`group_combine=True`（默认）时，技术面 5 个滑块
   **完全不参与计算**（`trend.py:817-888` 走 `GROUP_WEIGHTS`），用户拖了没反应。
   要么让滑块在组内模式下改写组权重，要么在 UI 上明确置灰 + 提示

**风险**：🔴 **中高**。20+ 处消费点，且 `tests/test_services/test_thresholds.py`
把现有值锁死了。**必须逐服务替换 + 每服务单独回归**，不能批量正则替换。

**价值**：高。这是"参数可信度"的核心 —— 权重错了用户看得见（能对比预览），
阈值错了用户**完全看不见**，但决策矩阵直接用它下买卖建议。

### 2.3 K 项 · 多市场独立校准（3-4 周，原 V0.102 计划，仍未交付）

**主题**：黄金 / 白银 / ETF 三套独立权重与阈值。

**前置**：V0.111.0 阈值可覆盖落地后做才不会返工。

**实施步骤（概览）**：
1. `schemas/settings.py`：权重 / 阈值配置改为 `target_keyed: dict[target, WeightConfig]`
2. `services/trend.py` / `services/macro.py`：参数解析按 target 取值
3. 回测支持 cross-market 验证（NY vs SGE vs ETF 共 3×3=9 组对照）
4. UI：`static/weights.html` 加 target 切换 tab
5. 文档同步：parameter-evaluation.md §4.3 验证结论

**风险**：
- 🟡 数据量大（已有 3 market × 至少 730 天 × 5 维技术面 + 5 因子宏观 = ~21,900 条评估基线）
- 🟢 物化宽表 V0.92.0 + 回测引擎 V0.79 已就绪

**价值**：
- 高 —— 11 项 parameter-evaluation 项里**唯一**未交付
- 中 —— 用户可见性低（仅在 settings 与回测页有入口），但"参数可信度"本身就是该工具核心价值

### 2.4 其他候选

详见 [§3 V0.96+ Backlog](#3-v096-backlog) —— 候选 B-G 中尚未交付的项目继续推进。

---

## §3 V0.96+ Backlog

> V0.92.0 物化宽表已稳定 + V0.92.1/V0.93.0/V0.94.0/V0.95.x UX 改进系列已落，按"数据深度 + UX 深化 + K 项"三条线展开。
>
> **2026-10 已交付**：候选 A（V0.96.0 命中分析） / 候选 H 部分（V0.97.0 AI / V0.98.0 双层导航 + SSE / V0.99.0 多市场重构）。
> **剩余**：候选 B-G 中尚未交付的项目 + K 项正式化。

### 3.1 数据深度类

#### 候选 A · 打分命中率分布可视化 ✅ 已交付 V0.96.0

> 见 [docs/releases/v0.96.0.md](releases/v0.96.0.md) —— 4 dataset 柱状图（4 horizon × 5 dataset）+ 3 mini card（最近 30 天 / MoM / 最佳 horizon）。

#### 候选 B · 胜率随 horizon 退化曲线（V0.96+ 候选）

**目标**：verdict card 旁边 1 张 mini 折线图 —— x 轴 horizon (t0/t1/t3/t5)，y 轴命中率。

- 一眼看到"T+0 → T+5 命中率衰减有多快" → 策略稳定性度量
- 复用 V0.86.0 decision-explainer.js 的 `dimensionBars` 横向条形图组件

**工作量**：1-2 天 ｜ **风险**：🟢 0 ｜ **价值**：中

#### 候选 C · 跨市场对照扩展

**目标**：trend.html「NY / SGE / ETF」对照从纯指数曲线升级为"价 × 涨跌 × 状态"三维。

- 主图保留 3 曲线
- 副图：x 时间，y marker（NY / SGE / ETF），颜色按涨跌，状态 chip（实时/缓存/演示）

**工作量**：5-7 天 ｜ **风险**：🟡 中（重构 trend.html sge/cmp 区）｜ **价值**：中

### 3.2 UX 体验深化类

#### 候选 D · 移动端 PWA 体验收口

**状态**：V0.72.0 基础 PWA 已就绪，V0.83.0 触控 ≥44px 部分达成；剩余缺口：

- [ ] 顶栏移动端汉堡菜单全局审计（V0.83.2 topnav 抽离后未补 ≤768px 折叠）
- [ ] iOS / Android 主屏图标 + splash 验证（Android Chrome 实际安装测试）
- [ ] PWA manifest `start_url` / `display` / `theme_color` 字段完整化
- [ ] SW `SHELL_ASSETS` 已含 9 个业务页（V0.92.0 补 scoring.html），确认 /home /ask 也入内

**工作量**：1 周 ｜ **风险**：🟢 0 ｜ **价值**：中

#### 候选 E · AI 助手深化（V0.97.0 后的延伸）

**状态**：V0.97.0 /ask 已上线 5 tool 只读 + ClaudeClient httpx + SSE 流式。剩余可深化方向：

- 写操作前置审查（tool 增加建议写入，但需用户确认）
- 多轮对话的 session 持久化（目前每次刷新重置）
- 跨页上下文带过去（目前只 snapshot 当前 trend）

**工作量**：1-2 周 ｜ **风险**：🟡 中（影响 trust 边界）｜ **价值**：高

#### 候选 F · 错误降级 UX 收口

**状态**：V0.77.1 / V0.83.4 / V0.85.0 / V0.100.0 已有零散修复。剩余：

- [ ] `static/error-toast.js` 共享模块（toast + retry + 末次数据保留）9 业务页统一接入
- [ ] `check_cluster_render.mjs` 加"失败态渲染"断言扩展（V0.77.1 的 §7 已起步）

**工作量**：3-5 天 ｜ **风险**：🟡 中 ｜ **价值**：高（消除用户最大痛点"为什么我看到红框"）

#### 候选 G · 命中筛选 / T+0 联动快捷键（V0.92.1 / V0.93.0 后续）

**目标**：scoring 页键盘快捷键减少点击。

- `1` / `2` / `3` 切 全部/是/否（V0.92.1 已实现 UI，可补键盘）
- `Tab` 切 horizon t0 / t1 / t3 / t5
- `←` / `→` 翻月份
- `Esc` 关 verdict card 详情弹窗

**工作量**：1-2 天 ｜ **风险**：🟢 0 ｜ **价值**：中

### 3.3 K 项（候选 H → V0.102 正式版）

见 [§2.3 V0.102](#23-k-项--多市场独立校准3-4-周原-v0102-计划仍未交付)。

---

## §4 维护线（每 2 周一个补丁版）

### 4.1 已建立的维护节奏

| 周期 | 主题 | 来源 |
|---|---|---|
| **每 2 周** | hotfix / 依赖升级 / 测试扩充 / backfill 脚本化 | 历史（V0.78.x-V0.95.x） |
| **每 4 周** | sw.js VERSION + 4 处同步清单（pyproject / main.py / CHANGELOG / README）+ pwa_assets 门禁 | V0.88.0 教训 + 4 处同步清单 memory（`sw-version-sync-gate`）|
| **持续** | 7 道机械门禁维护 | 见 §6 门禁清单 |

### 4.2 维护任务清单（每小版本至少 1 项）

- [ ] `ruff check` 警告清零
- [ ] 依赖升级：`uv lock --upgrade` → 跑全量回归（**谨慎**：V0.78.2 sqlalchemy 2.0→2.1 跨大版本崩溃前科）
- [ ] 测试扩充：新功能 PR 至少 +10 测试
- [ ] 文档同步：版本号、页数、端点数刷新
- [ ] 静态门禁：JS + 渲染 + 文档声明 三关全绿
- [ ] 检查 `pwa_assets` / `check_routes` 清单是否需要同步
- [ ] 检查 `feature-alignment.md` 是否已登记本次偏差

### 4.3 维护线累计护栏（截至 V0.100.0）

- 14+ HTTP alias（V0.87 check_routes 持续护栏；V0.99 / /home /ask /scoring /central-bank /silver /data-health 等新增 alias）
- 16+ 静态 HTML + 30+ 共享 JS（V0.92.0 scoring.html / V0.98.0 /home /ask /central-bank-page 等）
- src/ 覆盖率 90%+ 基线（V0.88 admin 19 + grams 100% + import_central_bank 98%）
- 7 道门禁：check_routes / check_pwa_assets / check_static_js / check_cluster_render / check_i18n_keys / check_docs_claims / pytest

---

## §5 风险与缓解

### 5.1 跨版持续风险

| 风险 | 概率 | 影响 | 缓解 |
|---|---|---|---|
| **sw.js VERSION 与 pyproject 漂移** | 中 | 高（用户长期"HTML 新 + JS 旧"） | `sw-version-sync-gate` memory + `pwa_assets.py` 必跑 + 4 处同步清单 |
| **文档声明与代码漂移** | 中 | 中（误用/调试找不到 key） | `check_docs_claims.py` 必跑 +390+ 处自动校验；feature-alignment.md SKIP_FILES 例外处理 |
| **维护线覆盖率萎缩** | 低 | 中 | V0.79.2 目标 ≥60%，V0.88 已 90%+，下阶段加 puppeteer 视觉回归 |
| **i18n 繁中同步再次掉队** | 低 | 中 | V0.73.0 zh-TW 覆盖率 10.9%→61.2%，V0.83.1 110 gap 修复；`check_i18n_keys` 0 missing 持续护栏 |
| **行号漂移导致审计报告失准** | 中 | 低（仅跨文档比对时） | 报告中标注"[○] 子代理审计" vs "[✓] 亲自复核"；下次审计时重新定位 |
| **CI matrix 与本地 Python 版本不一致** | 中 | 中（dev 能跑，CI 挂） | V0.101 C2 已收口为 3.13 only |

### 5.2 主动作风险

| 主动作 | 风险 | 缓解 |
|---|---|---|
| **V0.101 Python 3.13 迁移** | 🟡 asyncio / pydantic typing 弃用警告洪水 | ruff 全绿 + 离线回归 100% 通过方可发版 |
| **V0.102 K 项** | 🟡 数据量大回测慢 | 复用 V0.92.0 物化宽表 + V0.79 5min 节流 cache |
| **候选 E AI 写操作** | 🟡 trust 边界 | 默认 review-only；要"建议写入"必须显式用户确认 |

---

## §6 立即可启动的下一步

**今天（2026-10-18）可做**：

### V0.101 收口（C3b / C4）

1. **本地启动验证**（V0.101 C3b）：
   ```bash
   uv run python -m pytest -q --ignore=tests/test_services/test_irfcl_fetcher.py \
     --ignore=tests/test_services/test_h15_fetcher.py
   ```
   预期：V0.100.0 离线基线 866+ 用例 0 failed，3.13 下应同等。

2. **手测 mock provider**：
   ```bash
   MARKET_PROVIDER=mock uv run uvicorn app.main:app --port 8899
   ```
   验证：GET /api/v1/health 200，访问 /portfolio /trend /scoring /ask /central-bank 均不报错。

3. **5 处版本号同步**（V0.101 C4）：
   - `pyproject.toml` `version = "0.101.0"`
   - `static/sw.js` `const VERSION = "v0.101.0"`
   - `static/manifest.json`（如有版本字段）
   - `README.md` 当前版本徽章
   - `docs/CHANGELOG.md` 新增条目

4. **发版说明**：`docs/releases/v0.101.0.md` 写 4 commit 链 + 门禁快照 + 验证步骤。

5. **commit 链**（建议 1 个 PR）：
   ```
   test(python): V0.101 C3b · Python 3.13 离线回归全绿
   chore(release): V0.101 C4 · 5 处版本同步 + release notes
   ```

### V0.102 准备（K 项，如本周 V0.101 落定后启动）

按 [§2.3](#23-k-项--多市场独立校准3-4-周原-v0102-计划仍未交付) 步骤估算工作量，但不立即开始 —— 等 V0.101 tag 推送 + 镜像验证通过再启动。

---

## 附录 A · parameter-evaluation.md 对账

| parameter-evaluation 项 | 状态 | 落地版本 |
|---|---|---|
| A 统一阈值常量 | ✅ | V0.78.0 Step A |
| B 决策矩阵档位补全 | ✅ | V0.78.0 Step B |
| C 共振信号扩展反向 | ✅ | V0.78.0 Step C |
| D 兜底策略差异化 | ✅ | V0.78.0 Step D |
| E 动态化宏观阈值 | ✅ | V0.79.0 Step E |
| F 技术面 5 维度重构 | ✅ | V0.79.0 Step F |
| G 回测权重嵌套扩展 | ✅ | V0.79.0 Step G |
| H 样本阈值分层 | ✅ | V0.79.0 Step H |
| I 阈值带自适应 | ✅（部分，V0.80.0 Step I） | V0.80.0 |
| J 决策矩阵网格化 + 仓位结合 | 🟡 半成品 | V0.80.0 Step J（待闭环）|
| **K 多市场独立校准** | ❌ 未交付 | **V0.102 正式项** |

**11 项中 10 项已交付**，K 项为唯一未交付。

---

## 附录 B · development.md §11 改进计划对账

| development.md §11 项 | 状态 | 路线图覆盖 |
|---|---|---|
| P1 #1-6（CI / Alembic / 行情源 / 多账户） | ✅ | — |
| P2 #7-11（共振 / 克数 / 多时间框架 / 回测 / 多品种） | ✅ | — |
| P3 #12 仓位推荐 | 🟡 半成品 | V0.80.0 Step J 闭环 |
| P3 #13 模拟交易 | 🟡 半成品 | 暂缓（V0.84.0+ 排期） |
| P3 #14 指数曲线 | ✅ | — |
| P3 #15 监控告警 | 🟡 | 维护线排期 |
| P3 #16 公开部署 | 🟡 | 待用户提供域名 + 证书 |
| 6.5 个性化与上下文记忆 | 🟡 | V0.79.0 Step F 部分 |
| 6.9 加载与离线 | ✅ | V0.72.0 PWA |
| 6.11 研判复盘 | ✅ | V0.66.0 |
| V0.75.0 认证 | 🟡 第①步 | V0.75.0-V0.75.3 |
| V0.75.1 结论卡 | ✅ | V0.75.1 |
| V0.76.0 消息面打分器 | ✅ | V0.76.0 |
| V0.100.0 消息面 pending | ✅ | V0.100.0 |

---

## 附录 C · 不变项（Invariants，源自 ux-roadmap.md §四）

| # | 不变项 |
|---|---|
| 1 | **基线只增不减**：路线图制定时是 7 页 + 40 端点 + 454 测试；**V0.100.0 实测 16+ 静态 HTML + 16+ alias + 30+ 共享 JS + 866+ 测试**（每次迭代只许新增，既有的页面 / 端点 / 用例不得因新功能失效） |
| 2 | **数据表只读扩展**（`gold_price_daily` / `daily_snapshots` / `news_scores` / `accounts` / `positions` / `trades` / `scoring_daily_wide` —— 只加列，不改主键） |
| 3 | **现有 JS 资产不重写只扩展**（命名空间稳定；新资产通过 `window.PM_xxx` IIFE 自注入） |
| 4 | **`pm_help_seen_version` 升级强制重看行为保留**（V0.58.0 帮助体系） |
| 5 | **Chart.js 4.4.x 本地 vendor + 无新框架 / 构建工具**（保持"纯静态 + 内联 JS"原则） |
| 6 | **`freshness.js` / `health-summary.js` 三态时效条静默语义保留**（主题切换不得破坏降级角标） |
| 7 | **`gold_account_id` localStorage 键名不变**（V0.62.0 起向后兼容） |
| 8 | **telemetry 数据本地落库、不外发**（单机部署隐私；埋点只在 `telemetry_events` 表，`sendBeacon` 走同源） |
| 9 | **`AUTH_ENABLED=false` 单用户模式行为零回归**（V0.75.0 后所有中间件短路；多用户模式需显式 ENV 开启） |
| 10 | **消息面 pending 兜底**：未打分时 `NewsScoreOut.score = None`，绝不再静默回退到中性 50（V0.100.0 设计纪律） |

---

## 附录 D · 部署状态速查（源自 improvement-path.md §五）

**截至 V0.100.0 / V0.101 in progress**：

| 项 | 状态 | 入口 |
|---|---|---|
| 监听地址 | 默认 `127.0.0.1` 或 LAN `0.0.0.0:8889`（用户偏好 LAN-only，192.168.0.204） | `lan-only-deployment` memory |
| 三市场支持 | NY / SGE / ETF / 白银 ETF + SGE + NY | V0.99.0 |
| REST 接口面 | 16+ alias（健康 / 行情 / 复盘 / scoring / ask / push / auth） | `app.openapi()['paths']` |
| src/ 覆盖率 | 90%+ | V0.88.0 |
| 离线回归 | 866+ 用例 / 离线 ~822 passed / 0 failed | `pytest --ignore=…irfcl --ignore=…h15` |
| 公开部署 | 🟡 Docker + Nginx 模板已就绪（HTTPS 待用户提供域名 + 证书） | [deployment.md](deployment.md) |

---

## 附录 E · 历史实现细节（V0.78-V0.80）

> 本附录保留 V0.78 Step A-D、Step G/E/F/H 的实现细节作为技术参考。
> **代码已落定**，本文档仅作"为什么这样设计"的索引。实操请直接读代码 + [`docs/releases/v0.79.0.md`](releases/v0.79.0.md) + [`v0.80.0.md`](releases/v0.80.0.md)。

### E.1 V0.78.0 阈值口径统一 + 决策补全

**Step A · 统一阈值常量** ✅ 2026-10-05

`schemas/thresholds.py` 四组 IntEnum：

```python
class DirectionThreshold(IntEnum):
    STRONG_BULLISH = 70   # 强多（决策 BUY_HEAVY）
    BULLISH = 55          # 看多（消息面 / 共振 / 单维度中性偏多）
    NEUTRAL_HIGH = 60     # 中性偏上（单维度方向判定）
    NEUTRAL_LOW = 40      # 中性偏下
    BEARISH = 45          # 看空
    STRONG_BEARISH = 25   # 综合指数 STRONG_DOWN 触发

class LevelThreshold(IntEnum):
    STRONG_UP = 75; UP = 55; SIDEWAYS = 45; DOWN = 25

class DecisionThreshold(IntEnum):
    BUY_HEAVY = 75; BUY = 65; BUY_LIGHT = 55  # BUY 拆 3 档
    HOLD = 50; HOLD_LOW = 40; REDUCE = 40      # 新缓冲档 HOLD_CAUTIOUS

class OpportunityWindowThreshold(IntEnum):     # 新增（独立语义）
    pass
```

**设计纪律**：硬编码不是一种语义而是四种 —— 着色 55/40 属产品语义有意保留，路线图"预期只剩一处定义"未达成且不打算达成。

测试：`tests/test_services/test_thresholds.py` 25 例（含 AST 遍历断言服务层不再出现裸阈值）。

**Step B · 决策矩阵档位补全** ✅

BUY 拆 3 档（30% / 60% / 80%），消除 [60, 70) × [-10%, +15%] 卡死区，新增 idx [40, 45) HOLD_CAUTIOUS 缓冲档。

`schemas/decision.py::DecisionAction = StrEnum(BUY_HEAVY / BUY / BUY_LIGHT / ADD / HOLD / HOLD_CAUTIOUS / REDUCE / SELL / WAIT)`。

`StrEnum` 而非 `str, Enum`（ruff UP042）。

**Step C · 共振信号扩展反向** ✅

`DIVERGENT` 阈值 `_DIVERGENT_THRESHOLD = 15`，取幅度最大的达标对（**非**首达），3 子类型（tech_macro / tech_news / macro_news）。

`resonance.py::_build_signal()` 用 `pairs = [(tech, macro), (tech, news), (macro, news)]` 遍历。

**Step D · 兜底策略差异化** ✅

技术面 5 维度 score 改 `Optional[float]`，数据不足返回 `(None, "数据不足：< 14 个交易日")`，前端灰色 "—"。

最低数据量集中 `services/trend.py::DIM_MIN_BARS`（结构 40 / 动量 21 / 支撑 20 / 动能 15 / 回撤 10），并有测试断言键集合与 `TREND_WEIGHTS` 一致。

顺带修：`_rsi` 守卫错位导致恰好 15 根收盘价时 HTTP 500（IndexError），改 `< period + 2`。

W/M 视图技术面旁路保留 50 中性但**补披露**（见 `tech_note`），避免「沉默的假中性」。

### E.2 V0.79.0 阈值动态化 + 回测增强

**Step G · 回测权重嵌套扩展** ✅ 3 commits（dbf9239 / 77d33a5 / 43cab52）

```python
class NestedWeights(BaseModel):
    weights: list[dict[str, float]] = Field(..., min_length=1, max_length=10)

class TrendWeights(NestedWeights):
    _expected_fields = ("结构", "动量", "支撑", "动能", "回撤")
class MacroWeights(NestedWeights):
    _expected_fields = ("美元", "利率", "通胀", "地缘", "避险")

class WeightGrid(BaseModel):
    tech: list[float]; macro: list[float]; news: list[float]
    trend_weights: TrendWeights | None = None
    macro_weights: MacroWeights | None = None
```

异步端点：`POST /backtest/run-async` → `202 + Location: /backtest/result/{task_id}` + `GET /backtest/result/{task_id}`。

后台任务抽到 `services/background.py::_spawn_background`（endpoint 反向 import main 循环依赖规避）。

**Step E · 动态化宏观阈值** ✅ 4 commits

`MacroThresholdCalculator`：252 日滚动 90/10 分位，24h TTL 缓存。数据不足回退硬编码默认值。

`scheduler.py::daily_capture_loop` 每日 07:00 BJT 预热缓存。

`GET /market/gold/trend` 响应 `freshness.thresholds.macro_dynamic: bool`。

**Step F · 技术面 5 维度重构（组内平均）** ✅ 5 commits

```python
GROUP_WEIGHTS = {"trend": 0.50, "overbought": 0.30, "risk": 0.20}
GROUP_MAPPING = {
    "结构": "trend", "动量": "trend",
    "动能": "overbought", "支撑": "overbought",
    "回撤": "risk",
}
```

`WeightConfig.group_combine: bool = True` 用户可关闭回归单维度。

**Step H · 样本阈值分层** ✅ 1 commit

```python
MIN_SAMPLES_OVERALL = 10   # 总体命中率
MIN_SAMPLES_BUCKET = 5     # 分维度
```

`review.py` 响应 `sample_warning: Optional[str]`，前端灰色小字「样本 N < 10，仅供参考」。

### E.3 V0.80.0 决策网格化 + 仓位结合

**Step I · 阈值带自适应** ✅ 部分

`ThresholdBand` 默认 `bullish=[50, 55, 60, 65, 70]` × `bearish=[50, 45, 40, 35, 30]`，5×5=25 组。

**Step J · 决策矩阵网格化 + 仓位结合** 🟡 半成品

`schemas/decision.py::DecisionMatrix = dict[(idx_bucket, pnl_bucket, position_state), DecisionOut]` 已定义；查表逻辑与 `_suggest_position()` 结合 `accounts.current_capital` 计算 `position_ratio` 待闭环。

---

## 附录 F · V0.96+ 候选对账（2026-10 已交付部分）

| 原 §12 候选 | 2026-10 落地版本 | 备注 |
|---|---|---|
| A 打分命中率分布可视化 | ✅ V0.96.0 | 见 [releases/v0.96.0.md](releases/v0.96.0.md) |
| B 胜率随 horizon 退化曲线 | ⏳ 未交付 | 候选，保持 |
| C 跨市场对照扩展 | ⏳ 未交付 | 候选，V0.99.0 部分覆盖（3-market 重构） |
| D 数据自动刷新 | ⏳ 未交付 | 候选 |
| E 错误降级 UX 重构 | 🟡 部分（V0.77.1 / V0.83.4 / V0.85 / V0.100 零散） | 候选 F 收口 |
| F 移动端 PWA 体验优化 | 🟡 部分（V0.72.0 / V0.83.0 触控） | 候选 D 收口 |
| G 命中筛选 / T+0 联动快捷键 | 🟡 部分（V0.92.1 UI / V0.93.0 T+0） | 候选，键盘层待补 |
| H K 项 · 多市场独立校准 | 🟡 部分（V0.99.0 3-market 重构） | **V0.102 正式项** |

**6 条已落 / 2 条部分覆盖（推进中）/ 0 条纯搁置** —— candidate saturation 良好，未交付的多为"长尾收口"而非战略性遗漏。

---

**文档完成时间**：2026-10-18（V0.100.0 发版 + V0.101 收口 + 三份文档聚类重组）
**下次更新时机**：V0.101 发版后更新 §1 历史里程碑 + §2 推进主线；V0.102 K 项启动时更新 §3 backlog 状态
