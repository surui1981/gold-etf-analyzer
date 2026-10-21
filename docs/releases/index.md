# 能力 × 版本对照表

> **目标读者**：用户 + 开发者（能力全景）｜ **状态**：活跃 ｜ **最近更新**：2026-10-19
>
> **本表用途**：回答"哪个能力在哪个版本落地"，是 [docs/overview.md](../overview.md) §2 的完整版（原表随 overview.md 聚类重组被分离至此）。
>
> **维护原则**：发版时只改本表 + [docs/roadmap.md §1](../roadmap.md#1-历史里程碑截至-v01000) + [CHANGELOG.md](../../CHANGELOG.md) 三处中的对应行；其它文档（如 overview.md "当前产品能力"）不带版本号，不随之变化。

## §1 能力全景（按能力所属类别组织）

### 1.1 评估体系

| 能力 | 首次落地 | 详情 |
|------|----------|------|
| 三面评估（技术 30% / 宏观 40% / 消息面 30%） | V0.20 | [CHANGELOG](../../CHANGELOG.md) |
| 趋势评估指数（5 维结构 / 动量 / 支撑 / 动能 / 回撤） | V0.11 | [CHANGELOG](../../CHANGELOG.md) |
| 宏观参考因子（美元 / 美债 10Y·30Y / VIX / 央行购金） | V0.20 | [CHANGELOG](../../CHANGELOG.md) |
| 权重配置页（技术 5 维 + 合成比可调） | V0.20 | [CHANGELOG](../../CHANGELOG.md) |
| 阈值口径统一（4 组 IntEnum）+ 决策 9 档 + 共振反向识别 | **V0.78.0** | [CHANGELOG](../../CHANGELOG.md) |
| 动态化宏观阈值（252 日滚动 90/10 分位 + 24h TTL） | **V0.79.0** | [v0.79.0.md](v0.79.0.md) |
| 技术面组内平均（3 组：trend / overbought / risk） | **V0.79.0** | [v0.79.0.md](v0.79.0.md) |
| 样本阈值分层（总体 ≥10 / 分维度 ≥5） | **V0.79.0** | [v0.79.0.md](v0.79.0.md) |
| 回测权重嵌套扩展（WeightGrid 3 维 × 阈值带） | **V0.79.0** | [v0.79.0.md](v0.79.0.md) |
| 消息面未打分 → 综合指数 pending | **V0.100.0** | [v0.100.0.md](v0.100.0.md) |

### 1.2 决策与持仓

| 能力 | 首次落地 | 详情 |
|------|----------|------|
| 个人交易跟踪（开仓 / 加减仓 / 软删除 / CSV） | V0.11 | [CHANGELOG](../../CHANGELOG.md) |
| 购买决策引擎（参数面 × 交易面 → 5 档 + 理由明细） | V0.11 | [CHANGELOG](../../CHANGELOG.md) |
| 仓位推荐（80 / 60 / 40 / 20 / 10%） | V0.20 | [CHANGELOG](../../CHANGELOG.md) |
| 交易闭环（金额↔份数 / 摊薄成本 / 已实现盈亏） | V0.55.0 | [CHANGELOG](../../CHANGELOG.md) |
| ETF 报价口径修正（`etf-quote` 独立端点） | V0.61.0 | [CHANGELOG](../../CHANGELOG.md) |
| 收益曲线（`/portfolio/equity-curve` + 最大回撤） | V0.61.0 | [CHANGELOG](../../CHANGELOG.md) |
| 获利分析（胜率 / 盈亏比 / 平均持仓天数） | V0.61.0 | [CHANGELOG](../../CHANGELOG.md) |
| 收益回放口径修复（行情未覆盖成交归入最后可得交易日） | V0.62.1 | [CHANGELOG](../../CHANGELOG.md) |
| 多账本（accounts 表 + 顶栏切换器 + 默认账户自愈） | V0.62.0 | [CHANGELOG](../../CHANGELOG.md) |
| 交易历史查询页（`/trades` + 多条件 + CSV） | V0.62.0 | [CHANGELOG](../../CHANGELOG.md) |
| 克数持仓（`grams_held` + 份/克切换 + `gram-quote`） | V0.70.0 | [CHANGELOG](../../CHANGELOG.md) |
| 决策可解释性（`ReasonItem` 红绿对照） | V0.54.0 | [CHANGELOG](../../CHANGELOG.md) |
| 决策时间线回放（后端 API） | V0.90.0 | [v0.90.0.md](v0.90.0.md) |
| 共振信号（4 类 + 5 子类 + STRONG_UP 胜率） | V0.70.0 | [CHANGELOG](../../CHANGELOG.md) |

### 1.3 消息面

| 能力 | 首次落地 | 详情 |
|------|----------|------|
| 消息面评估页（每日 3 次打分 1:2:3 加权） | V0.65.0 | [CHANGELOG](../../CHANGELOG.md) |
| 12 个研判依据标签 + 复盘批注 | V0.66.0 | [CHANGELOG](../../CHANGELOG.md) |
| 研判复盘与准确率校准（T+1 / T+3 / T+5 + 校准曲线） | V0.66.0 | [CHANGELOG](../../CHANGELOG.md) |
| 首页综合研判结论卡（黄金 / 白银可切换） | V0.75.1 | [v0.86.0.md](v0.86.0.md)（决策可解释性同期增强） |
| 首页内嵌消息面打分器 | V0.76.0 | [v0.86.0.md](v0.86.0.md) |
| 消息面未打分 → 综合指数 pending chip | V0.100.0 | [v0.100.0.md](v0.100.0.md) |
| **宏观因子手动校准**（用户录入当日读数覆盖过期常量） | **V0.110.0** | [v0.110.0.md](v0.110.0.md) |
| 今日要闻（readhub 财经新闻流） | **V0.102** | 见 [§1.4.1](#141-今日要闻新闻流)（该产品线逐版本登记） |

### 1.4 多市场（NY / SGE / ETF / 白银 / 央行购金）

| 能力 | 首次落地 | 详情 |
|------|----------|------|
| 三市场基础（NY / SGE / ETF） | V0.11 | [CHANGELOG](../../CHANGELOG.md) |
| ETF vs 克价对照 | V0.11 | [CHANGELOG](../../CHANGELOG.md) |
| 多时间框架（60D / 52W / 24M） | V0.64.0 | [CHANGELOG](../../CHANGELOG.md) |
| 评估指数历史曲线（4 条线 + 极值卡） | V0.63.0 | [CHANGELOG](../../CHANGELOG.md) |
| 行情源 provider 配置化（akshare / mock / eastmoney / sina） | V0.59.0 | [CHANGELOG](../../CHANGELOG.md) |
| 行情实时性增强（cache TTL + 4 时点预热） | V0.60.0 | [CHANGELOG](../../CHANGELOG.md) |
| 白银追踪（`/market/silver/*` + `silver.html`） | V0.71.0 | [v0.92.0.md](v0.92.0.md) |
| Yahoo Silver provider + 自动降级 mock | V0.73.0 N+12 | [v0.86.0.md](v0.86.0.md) |
| 央行购金数据化（WGC + 自动调度） | V0.57.0 | [CHANGELOG](../../CHANGELOG.md) |
| 白银 SGE + 3-market 页面重构（升贴水表） | V0.99.0 | [v0.99.0.md](v0.99.0.md) |
| 白银页面数据时效透明化（`data_as_of` + 滞后 chip） | V0.109.2 | [v0.109.2.md](v0.109.2.md) |
| 命中分析（scoring 命中分析 Tab + 4 dataset 柱状图） | V0.96.0 | [v0.96.0.md](v0.96.0.md) |

### 1.4.1 今日要闻（新闻流）

> 本子表是 V0.102 起的一条独立产品线（readhub 财经流），能力密度高、单版本小步快跑，
> 因此**逐版本登记**而非按"首次落地"聚合。

| 能力 | 落地 | 详情 |
|------|------|------|
| 今日要闻新闻流（`news_feed_items` 表 + readhub fetcher） | V0.102.0 | [CHANGELOG](../../CHANGELOG.md) |
| 我的收藏（收藏 / 永久存储 / 档案管理页 + 9 端点） | V0.103.0 | [v0.103.0.md](v0.103.0.md) |
| 按日期分页（单日模式 + 日期导航） | V0.104.0 | [v0.104.0.md](v0.104.0.md) |
| 分类筛选（5 类关键词分类器 + 多 switch 正交叠加） | V0.105.0 | [v0.105.0.md](v0.105.0.md) |
| 提级为顶级场景（独立顶 nav，无 sub-tabs）+ 调度 6h→4h | V0.106.0 | [v0.106.0.md](v0.106.0.md) |
| 按天聚合 + 刷新 UX | V0.107.0 | [v0.107.0.md](v0.107.0.md) |
| 分类聚焦 + 弃入「其他」+ page_size 20→50 | V0.107.1 | [v0.107.1.md](v0.107.1.md) |
| 站点黑白名单 + 财经二次加强 | V0.108.0 | [v0.108.0.md](v0.108.0.md) |
| 分类词边界修复 + 发布词精度 | V0.109.0 | [v0.109.0.md](v0.109.0.md) |
| 分类架构改为「内容优先、站名兜底」 | V0.109.1 | [v0.109.1.md](v0.109.1.md) |
| **多源容灾（4 源链式 failover）+ 收藏有反馈** | **V0.114.0** | [v0.114.0.md](v0.114.0.md) |
| 修全站 favicon 404（21 页 rel=icon + 根作用域路由 + 门禁第 4 项） | V0.114.1 | [v0.114.1.md](v0.114.1.md) |

### 1.5 UI / UX

| 能力 | 首次落地 | 详情 |
|------|----------|------|
| 数据时效透明（freshness 角标 + 健康度） | V0.52.0 | [CHANGELOG](../../CHANGELOG.md) |
| 响应式 + 移动端适配（768 / 480 / 360 三档） | V0.53.0 | [CHANGELOG](../../CHANGELOG.md) |
| **窄屏可用性实测基线**（表格横向滚动容器 + 44px 触摸目标 + 聚焦不被顶栏遮挡） | **V0.113.0** | [v0.113.0.md](v0.113.0.md) |
| 操作闭环防错（二次确认 + 软删除 + 撤销） | V0.55.0 | [CHANGELOG](../../CHANGELOG.md) |
| 主动提醒（浏览器通知 + 提醒条） | V0.56.0 | [CHANGELOG](../../CHANGELOG.md) |
| 新手引导与帮助体系（tour + glossary + 15 项 inline tooltip） | V0.58.0 | [CHANGELOG](../../CHANGELOG.md) |
| 主题切换（4 主题：light / dark / auto / hc） | V0.69.0 | [CHANGELOG](../../CHANGELOG.md) |
| 导航折叠 + ⌘K 命令面板 + 埋点底座 | V0.68.0 | [CHANGELOG](../../CHANGELOG.md) |
| 仪表盘自定义（拖拽 + 键盘替代 + 布局持久化） | V0.74.0 N+17 | [v0.86.0.md](v0.86.0.md) |
| 告警规则 CRUD（discriminated union + UI 模态） | V0.74.0 N+18 | [v0.86.0.md](v0.86.0.md) |
| 界面聚类分组（`.pmc-cluster` 全站基元） | V0.77.0 | [v0.86.0.md](v0.86.0.md) |
| 主页 UI 改版 + 8 页面警示合并 + 静态门禁强化 | V0.83.0 | [v0.83.0.md](v0.83.0.md) |
| 共享 topnav 抽离（跨 9 页复用） | V0.83.2 | [v0.83.2.md](v0.83.2.md) |
| freshness 降级 UX 重设计 + `sig()` 关键 bug 修复 | V0.83.4 | [v0.83.4.md](v0.83.4.md) |
| 数据健康跳转 404 hotfix | V0.86.1 | [v0.86.1.md](v0.86.1.md) |
| 状态条合并（数据时效 + 警示 → 1 个 disclosure） | V0.84.0 | [v0.84.0.md](v0.84.0.md) |
| 数据健康摘要 chip / panel（`/data-health` 4-chip） | V0.85.0 | [v0.85.0.md](v0.85.0.md) |
| 决策可解释性增强（拆解 + 对比 + tooltip 三件套） | V0.86.0 | [v0.86.0.md](v0.86.0.md) |
| i18n 三语（zh-CN / en-US / zh-TW） | V0.73.0 | [v0.86.0.md](v0.86.0.md) |
| 失败态不再伪装正常（信任层修复） | V0.77.1 | [v0.86.0.md](v0.86.0.md) |
| 数据不丢与交互安全（4 处静默错误） | V0.77.2 | [v0.86.0.md](v0.86.0.md) |
| 双层导航（7 顶场景 + 4 子场景） | V0.98.0 | [v0.98.0.md](v0.98.0.md) |
| home.html 今日要闻 SW 缓存击穿（V0.102 部署后） | V0.100.1 | [v0.100.1.md](v0.100.1.md) |
| home.html 今日要闻 Top 5 → Top 20 | V0.100.2 | [v0.100.2.md](v0.100.2.md) |
| 场景卡与顶 nav 同步（5→7 卡） | V0.106.1 | [CHANGELOG](../../CHANGELOG.md) |
| 场景卡与顶 nav 同步（7→8 卡）+ 报告存档顶级场景 | **V0.111.0** | [v0.111.0.md](v0.111.0.md) |
| **报告存档**（HTML 上传 + 元数据登记表 + 新标签页 CSP sandbox 隔离） | **V0.111.0** | [v0.111.0.md](v0.111.0.md) |

### 1.6 推送 / PWA / 部署

| 能力 | 首次落地 | 详情 |
|------|----------|------|
| SMTP 邮件推送 | V0.72.0 | [v0.86.0.md](v0.86.0.md) |
| Server 酱微信推送 | V0.72.0 | [v0.86.0.md](v0.86.0.md) |
| Web Push（VAPID + 订阅闭环） | V0.72.0 | [v0.86.0.md](v0.86.0.md) |
| PWA（manifest + sw.js 双 cache + 离线兜底） | V0.72.0 | [v0.86.0.md](v0.86.0.md) |
| 通知中心（`/static/settings.html` 5 区） | V0.72.0 | [v0.86.0.md](v0.86.0.md) |
| 公开部署（Docker 多阶段 + Nginx + Let's Encrypt） | V0.72.0 | [v0.86.0.md](v0.86.0.md) |
| Chart.js 本地 vendor（`static/vendor/chart.umd.min.js`） | V0.74.3 | [v0.86.0.md](v0.86.0.md) |

### 1.7 认证 / 多用户

| 能力 | 首次落地 | 详情 |
|------|----------|------|
| 认证骨架（bcrypt + 服务端 sessions + CSRF） | V0.75.0 | [v0.86.0.md](v0.86.0.md) |
| 单用户模式零回归（`AUTH_ENABLED=false` 默认） | V0.75.0 | [v0.86.0.md](v0.86.0.md) |
| prod 写端点自动附加 `X-Admin-Token`（hotfix） | V0.80.1 | [v0.80.1.md](v0.80.1.md) |
| 找回密码 + 用户管理页（V0.75.3 收口） | V0.81.0 | [v0.81.0.md](v0.81.0.md) |
| admin token 缺失提示横幅（hotfix） | V0.81.1 | [v0.81.1.md](v0.81.1.md) |
| admin session cookie + 单用户模式豁免（LAN 多终端） | V0.82.0 | [v0.82.0.md](v0.82.0.md) |

### 1.8 智能分析（AI 助手）

| 能力 | 首次落地 | 详情 |
|------|----------|------|
| `/ask` AI 智能分析页（3 pane chat + 5 tool 只读） | V0.97.0 | [v0.97.0.md](v0.97.0.md) |
| SSE 流式（`sse-starlette` + EventSource） | V0.98.0 | [v0.98.0.md](v0.98.0.md) |
| 3 级降级兜底（tool_use+tool_result 平铺 / L3 仅原问题） | V0.97.2 | [v0.97.2.md](v0.97.2.md) |
| `/ask` 工具调用展示调整（UI hotfix） | V0.97.1 | [v0.97.1.md](v0.97.1.md) |
| miniMax 代理 2013 三级降级兜底（hotfix） | V0.97.2 | [v0.97.2-hotfix.md](v0.97.2-hotfix.md) |

### 1.9 维护线

| 能力 | 首次落地 | 详情 |
|------|----------|------|
| CI/CD（GitHub Actions + uv 缓存 + matrix 收口） | V0.67.0 | [CHANGELOG](../../CHANGELOG.md) |
| 测试基础设施修复 + 数据隔离第 2 批 | V0.80.0 | [v0.80.0.md](v0.80.0.md) |
| 限速中间件（`/static/` bypass + 默认 600/min） | V0.83.3 | [v0.83.3.md](v0.83.3.md) |
| X-Request-ID 全链路追踪（contextvars + 日志） | V0.67.0 | [CHANGELOG](../../CHANGELOG.md) |
| 价格日历 schema 校验（close > 0 / source 白名单） | V0.67.0 | [CHANGELOG](../../CHANGELOG.md) |
| Alembic 迁移 + 启动幂等补列 | V0.50.0 | [CHANGELOG](../../CHANGELOG.md) |
| 每日 07:00 BJT 快照 + 央行月度自动调度 | V0.50.0 | [CHANGELOG](../../CHANGELOG.md) |
| `check_static_js.py` 前端内联 JS 门禁 | V0.74.0 | [v0.86.0.md](v0.86.0.md) |
| `check_docs_claims.py` 文档声明门禁 | V0.74.0 | [v0.86.0.md](v0.86.0.md) |
| `check_cluster_render.mjs` 渲染行为门禁（33 → 125 条） | V0.77.0 | [v0.86.0.md](v0.86.0.md) |
| `check_pwa_assets.py` PWA 资源门禁 | V0.78.1 | [v0.86.0.md](v0.86.0.md) |
| `check_links.py` 死链与锚点门禁 | V0.78.1 | [v0.86.0.md](v0.86.0.md) |
| `check_deps.py` 依赖声明门禁 | V0.78.1 | [v0.86.0.md](v0.86.0.md) |
| `check_routes.py` HTTP 路由门禁 | V0.87.0 | [v0.87.0.md](v0.87.0.md) |
| 维护线 src/ 覆盖率 87 → 90%+ | V0.88.0 | [v0.88.0.md](v0.88.0.md) |
| 复盘报告 PDF 一键导出 | V0.91.0 | [v0.91.0.md](v0.91.0.md) |
| 历史打分数据汇总 `scoring_daily_wide` 物化宽表 | V0.92.0 | [v0.92.0.md](v0.92.0.md) |
| Python 3.13 迁移收口 | **V0.101**（in progress） | — |

---

## §2 如何读这份索引

- **能力全景**（本表）回答"项目有什么、什么时候加的"
- **[CHANGELOG.md](../../CHANGELOG.md)** 回答"发版节点"（发行时刻 + 类型分类）
- **[docs/roadmap.md §1](../roadmap.md#1-历史里程碑截至-v01000)** 回答"历史里程碑 + 当前焦点 + 推进主线"
- **[docs/releases/](.)** 单文件 release notes 回答"该版本的实现细节（commit 链 / 验证步骤 / 风险）"

> **三源重复是有意为之** —— 每份文档的读者视角不同：
> - `index.md`（本表）= 想了解"项目有什么 / 什么时候加的"
> - `CHANGELOG.md` = 想看"什么时候发了什么版本"
> - `roadmap.md §1` = 想看"演进逻辑 + 阶段归纳"
>
> 三份互相 **link-back**，发版时三处都要改（3 分钟成本），换来的是"任何入口都能找到答案"。

---

## §3 本表如何维护

**发版时**：

1. 在本表对应能力行的"首次落地"列写新版本号（如果新增了能力）
2. 在本表对应能力行的"详情"列加超链接 `vX.Y.Z.md`（如果该版本已有 release notes）
3. 在 [CHANGELOG.md](../../CHANGELOG.md) 顶部加发版条目
4. 在 [docs/roadmap.md §1](../roadmap.md#1-历史里程碑截至-v01000) 增 1 行（如果属于历史里程碑级别）

**不发版**（小修小补）：**不改**本表。本表只记录"能力首次落地"，不记录后续小修。

**撤销能力**：在该行加删除线 ~~V0.X.Y~~ + 备注"已回滚"。

> **本表不参与 `check_docs_claims.py` 扫描**（与 `docs/reports/` 同原则）—— 本表必然引用"未来版本号"（尚未发布的 V0.101+）与"已废弃的早期实体名"（V0.20 时代）。详见 [scripts/check_docs_claims.py:68-80](https://github.com/surui1981/gold-etf-analyzer/blob/main/scripts/check_docs_claims.py)。
