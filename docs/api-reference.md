# API 参考与核心模型

> **目标读者**：用户 + 开发者（核心契约）｜ **状态**：活跃 ｜ **最近更新**：2026-10-18
>
> 本指南已拆分为 5 部分，本文件包含 **API 参考（§5）+ 核心模型（§6）**。
> 其他部分：[overview](overview.md) · [getting-started](getting-started.md) ·
> [architecture](architecture.md) · [development](development.md)

## 5. API 参考

| 方法 | 路径 | 说明 | 关键参数 |
|------|------|------|----------|
| GET | `/` | 趋势追踪页 | - |
| GET | `/portfolio` | 个人交易跟踪与购买决策页 | - |
| GET | `/weights` | 评估权重配置页 | - |
| GET | `/news` | 消息面评估页 | - |
| GET | `/central-bank` | **世界央行购金统计页** | - |
| GET | `/trades` | **交易历史查询页** | - |
| GET | `/login` | **登录 / 注册页（307 跳 `/static/login.html`，V0.75.0）** | - |
| GET | `/api/v1/health` | 健康检查 | - |
| GET | `/api/v1/market/health` | 数据源健康度统计 | - |
| GET | `/api/v1/market/freshness` | 三市场数据时效与交易时段 | - |
| POST | `/api/v1/analysis/opportunity` | 宏观机会评分 | body: `factors{dxy, us10y_yield, real_rate, inflation_expectation, risk_off}` |
| GET | `/api/v1/analysis/history` | 历史分析记录 | `limit`(1-100) |
| GET | `/api/v1/market/gold` | 黄金ETF最新报价 | - |
| GET | `/api/v1/market/gold/trend` | 趋势追踪 + 评估指数（**默认纽约金 COMEX 为投资指引基准**） | `days`(20-750)、`target`(ny/etf/gram，默认 ny)、`interval`(D/W/M，默认 D) |
| GET | `/api/v1/market/gold/ny-trend` | 纽约金 60 天趋势曲线（美元/盎司，等价于 `/gold/trend?target=ny`） | `days`(20-750)、`interval`(D/W/M，默认 D) |
| GET | `/api/v1/market/gold/compare` | ETF vs 黄金克价对照（points 含真实价 `etf_price`/`gram_price` + 归一化 `etf`/`gram`） | `days`(20-250) |
| GET | `/api/v1/market/gold/etf-quote` | **黄金ETF报价（元/份，估值与交易专用口径）** | - |
| GET | `/api/v1/market/gold/gram-quote` | **上海金 Au99.99 克价（元/克，P2 #8 V0.70.0）** | - |
| GET | `/api/v1/market/silver/quote` | **纽约白银 SI 报价（美元/盎司，P3-a P2 #11 V0.71.0）** | - |
| GET | `/api/v1/market/silver/etf-quote` | **白银 ETF 562800 报价（元/份，P3-a P2 #11 V0.71.0）** | - |
| GET | `/api/v1/market/silver/trend` | **白银 ETF 趋势追踪 + 评估指数（P3-a P2 #11 V0.71.0）** | `days`(20-750)、`interval`(D/W/M) |
| GET | `/api/v1/market/silver/ny-trend` | **纽约白银趋势曲线（美元/盎司，P3-a P2 #11 V0.71.0）** | `days`(20-750)、`interval`(D/W/M) |
| GET | `/api/v1/market/silver/compare` | **白银 ETF vs 纽约白银 对照（归一化，P3-a P2 #11 V0.71.0）** | `days`(20-250) |
| POST | `/api/v1/backtest/run` | **参数回测（权重网格 × 阈值带 → Sharpe/最大回撤/命中率，5 分钟节流，P3-a P2 #10 V0.71.0）** | body: `BacktestRequestIn`（days/target/weight_grid/threshold_bands）；header: `X-Backtest-Cached: true\|false` |
| GET | `/api/v1/backtest/coverage` | **回测数据覆盖期报告（start/end/available_days/sample_warning，P3-a P2 #10 V0.71.0）** | `target`(ny/etf/gram/silver_ny/silver_etf)、`days`(20-365) |
| GET | `/api/v1/backtest/config` | **回测预设配置读取（settings 表 key=backtest_config，60s 缓存，P3-a P2 #10 V0.71.0）** | - |
| PUT | `/api/v1/backtest/config` | **回测预设配置保存（P3-a P2 #10 V0.71.0）** | body: `BacktestConfigIn` |
| POST | `/api/v1/positions` | 开仓买入 | body: `{symbol, quantity, price, fee}`；query: `account_id`（缺省=默认账本） |
| GET | `/api/v1/positions` | 持仓列表（实时盈亏） | `include_closed`、`account_id`（缺省=全部账本） |
| GET | `/api/v1/positions/export` | 持仓 + 流水 CSV 导出 | `account_id` |
| POST | `/api/v1/positions/{id}/trades` | 加仓/减仓 | body: `{side, quantity, price}` |
| POST | `/api/v1/positions/{id}/close` | 按市价清仓 | - |
| DELETE | `/api/v1/positions/{id}` | 软删除持仓（可撤销） | - |
| POST | `/api/v1/positions/{id}/restore` | 撤销软删除 | - |
| GET | `/api/v1/positions/{id}/trades` | 某持仓成交流水（倒序） | - |
| GET | `/api/v1/portfolio/equity-curve` | **账户收益曲线（流水+历史价回放，含最大回撤）** | `days`(20-250)、`account_id` |
| GET | `/api/v1/portfolio/performance` | **获利分析总结（已实现/浮动盈亏、胜率、盈亏比 + 中文总结）** | `account_id` |
| GET | `/api/v1/accounts` | 账本清单（含持仓/流水统计） | query: `include_archived` |
| POST | `/api/v1/accounts` | 新建账本 | body: `{name, note, is_default}` |
| PATCH | `/api/v1/accounts/{id}` | 改名 / 备注 / 排序 / 设为默认 | body: `{name?, note?, sort_order?, is_default?}` |
| POST | `/api/v1/accounts/{id}/archive` | 归档账本（数据保留） | - |
| POST | `/api/v1/accounts/{id}/restore` | 恢复已归档账本 | - |
| GET | `/api/v1/trades` | 交易历史查询（分页 + 汇总） | query: `account_id/side/position_id/symbol/keyword/start/end/page/page_size` |
| GET | `/api/v1/trades/export` | 交易历史 CSV 导出（含汇总） | 同上（无分页） |
| GET | `/api/v1/decision/etf` | 购买决策（趋势指数×持仓 + 仓位推荐 + 红绿理由） | `days`(20-250)、`account_id` |
| GET/PUT | `/api/v1/settings/weights` | 权重配置读取/保存 | body: `{trend, macro, combine:{tech,macro,news,flow}, flow:{6 因子}, group_combine}` |
| GET/PUT | `/api/v1/news-score` | 消息面打分（客户评估；当日 3 槽位 + 加权有效分值） | body: `{score, notes, slot?, basis?, review_note?, score_date?}` |
| DELETE | `/api/v1/news-score/{slot}` | 撤销当日某一次打分（释放槽位） | `score_date`（可选，默认当日） |
| GET | `/api/v1/news-score/history` | 历史打分记录（跨日回看） | `limit`(1-100) |
| POST | `/api/v1/snapshots/capture` | 捕获当日评估快照 | - |
| GET | `/api/v1/snapshots` | 历史评估快照（自动补当日） | `limit` |
| GET | `/api/v1/central-bank/summary` | **央行购金摘要（T12M 总量 / 参与国数 / 最新季度）** | - |
| GET | `/api/v1/central-bank/top-buyers` | **某年度 Top N 买家** | `year`(2020-2030)、`limit`(1-20) |
| GET | `/api/v1/central-bank/purchases` | **央行购金明细（按国家 / 季度范围筛选）** | `from_q`、`to_q`、`country` |
| GET | `/api/v1/review/meta` | **复盘元信息（标的 / 判定窗口 / 12 个依据标签 / 价格日历覆盖）** | `target`(ny/etf/gram，默认 ny) |
| GET | `/api/v1/review/journal` | **研判日志（按日期倒序：基准收盘 → T+N 收盘 + 命中判定）** | `days`(1-365)、`horizon`(1/3/5)、`target` |
| GET | `/api/v1/review/stats` | **复盘统计（命中率 / 方向分组 / 窗口分组 / 分值分箱校准 / 标签胜率）** | `days`(1-730)、`horizon`、`target` |
| GET | `/api/v1/review/hint` | **打分校准提示（该分值区间历史命中率与上涨概率）** | `score`(0-100)、`days`、`target` |
| GET | `/api/v1/review/horizons` | 可用判定窗口（T+1 / T+3 / T+5）与默认值 | - |
| POST | `/api/v1/review/backfill` | **回填历史金价日历（幂等，建立对比基准）** | `days`(5-730)、`target` |
| GET | `/api/v1/resonance/signal` | **当日共振信号（4 类 + confidence 0-100，P2 #7 V0.70.0；V0.75.1 起支持 `target` 切换黄金/白银口径）** | `target`（`ny`/`etf`/`gram`/`silver_etf`/`silver_ny`/`silver_gram`，默认 `etf`，非法值 422） |
| GET | `/api/v1/resonance/history` | **共振信号历史回放（按日期倒序）** | `days`(1-365) |
| GET | `/api/v1/resonance/strength-up` | **STRONG_UP 命中率统计（样本<20 时 sample_warning=true）** | `days`(1-730)、`horizon`(1-30) |
| GET | `/api/v1/settings/alert-rules` | **告警规则读取（P3-b #15 V0.72.0）** | - |
| PUT | `/api/v1/settings/alert-rules` | **告警规则保存（PUT admin 守卫；channel 至少 1 项 + 不重复；波动阈值 0.1-20）** | body: `{level_crossing_enabled, volatility_enabled, volatility_pct, quiet_hours:{start,end}, channels:[]}` |
| POST | `/api/v1/settings/test-email` | **测试邮件发送（admin 守卫；dev 模式无 ADMIN_TOKEN 时 skip；返回 `{channel,success,message}`）** | - |
| POST | `/api/v1/settings/test-wechat` | **测试微信发送（admin 守卫；Server 酱 SendKey 验证）** | - |
| GET | `/api/v1/push/vapid-public-key` | **VAPID 公钥（首次自动生成 EC P-256 持久化到 app_settings，P3-b #15 V0.72.0）** | - |
| POST | `/api/v1/push/subscribe` | **Web Push 订阅 upsert by endpoint（push_subscriptions 表，P3-b #15 V0.72.0）** | body: `{endpoint, keys:{p256dh,auth}, user_agent?}` |
| DELETE | `/api/v1/push/subscribe` | **退订（按 endpoint 硬删）** | query: `endpoint` |
| POST | `/api/v1/push/test` | **管理员测试 push 推送（admin 守卫）** | - |
| GET | `/api/v1/auth/status` | **认证状态（公开；`{auth_enabled, allow_registration, authenticated, user?}`，V0.75.0）** | - |
| POST | `/api/v1/auth/register` | **注册并直接登录（首个用户自动成为 `owner`；受 `ALLOW_REGISTRATION` 约束）** | body: `{email, password, display_name?}` |
| POST | `/api/v1/auth/login` | **登录（签发 `pm_session` HttpOnly cookie + `pm_csrf` 可读 cookie）** | body: `{email, password}` |
| POST | `/api/v1/auth/logout` | **登出（幂等；撤销当前会话并清 cookie，无需先登录）** | - |
| GET | `/api/v1/auth/me` | **当前登录用户（未登录 401）** | - |
| POST | `/api/v1/auth/change-password` | **修改口令（保留当前会话，撤销其余全部会话）** | body: `{current_password, new_password}` |

### 5.1 机会分析示例

```jsonc
// POST /api/v1/analysis/opportunity
{
  "factors": {
    "dxy": 96.0, "us10y_yield": 3.6, "real_rate": 1.4,
    "inflation_expectation": 3.0, "risk_off": 9
  },
  "gold_price_usd": 2350.5
}
// 响应：score 94.5 / window "strong" / signal "bullish"
//       factors[] 每项含 direction（bullish/bearish/neutral）供红绿着色
```

### 5.2 趋势追踪示例

```jsonc
// GET /api/v1/market/gold/trend?days=60&interval=D  （默认 target=ny：纽约金 COMEX；target=etf/gram 返回对应市场；interval=D/W/M 支持多时间框架）
{
  "symbol": "GC", "name": "纽约金COMEX", "unit": "美元/盎司", "days": 60,
  "points": [/* 60 个 {date, close, ma5, ma20, ma40} */],
  "metrics": { /* start/end/change_pct/high/low/ma20/ma40/direction/summary */ },
  "indicators": [ /* 5 个维度 {name, value, score, direction, weight, contribution, detail} */ ],
  "macro": { /* 宏观面指数 + 11 因子明细 */ },
  "flow": { /* 资金流面指数 + 6 因子明细（V0.120.0；score 可为 null） */ },
  "index": { "score": 95.0, "level": "strong_up", "direction": "bullish", "summary": "..." }
}
```

---

## 6. 核心模型

### 6.1 宏观机会评分模型（PM-Evaluator 架构）

| 因子 | 权重 | 与黄金关系 | 友好度100分位 | 友好度0分位 |
|------|------|-----------|--------------|------------|
| 实际利率 | 35% | 强负相关 | 1.5% | 2.5% |
| 美元指数 DXY | 30% | 负相关 | 95 | 105 |
| 美债10Y收益率 | 15% | 负相关 | 3.5% | 4.5% |
| 通胀预期 | 10% | 正相关 | 3.0% | 2.0% |
| 避险情绪 | 10% | 正相关 | 10 | 0 |

- 综合评分 = Σ(因子友好度 × 权重)
- 窗口：`≥70 strong` / `≥55 medium` / `≥40 weak` / `<40 standby`
- 配置位置：`services/scoring.py::FACTOR_RULES`

### 6.2 市场趋势评估追踪指数

| 维度 | 权重 | 评分依据 |
|------|------|----------|
| 结构 | 30% | 均线排列（MA5/20/40 多空）+ MA20 斜率 |
| 动量 | 20% | 近 20 日涨跌幅 |
| 支撑 | 20% | 收盘价相对 MA20/MA40 乖离 |
| 动能 | 15% | RSI(14) |
| 回撤 | 15% | 距区间高点回撤 |

- 指数 = Σ(维度评分 × **有效权重**)，0-100
- 等级：`≥75 强势上升` / `≥55 上升` / `≥45 震荡` / `≥25 下降` / `<25 弱势下降`
- 配置位置：`services/trend.py::TREND_WEIGHTS`

**数据不足不再伪装中性 50（V0.78.0 Step D）**：

- 每个维度有最低数据量要求（`services/trend.py::DIM_MIN_BARS`）：结构 40 / 动量 21 /
  支撑 20 / 动能 15 / 回撤 10 个交易日。
- 不足时该维度 `score = null`、`value = "—"`、`reason` 说明原因，且**不参与合成**。
- 有效维度按 `Σ(有效配置权重)` 归一化：`contribution = score × 有效权重`，故
  `Σcontribution` 恒等于上级指数分值。`weight` 字段**始终是配置值**，不被改写。
- 5 个维度全部不足时技术面指数 `score = null`（不再是一个看起来正常的 50）。
- `50.0` 只表示「有数据且真的中性」（如均线交叉整理），与「没算出来」严格区分：
  前者 `reason = null`，后者 `reason` 非空。
- 页面表现：趋势页 / 白银页该行显示灰色「— 未计入」+ 原因，进度条留空。
- **W/M（周 / 月 K）视图不做 5 维度分解**（打分标定按日 K 的 ±5% 量级设计，聚合后量纲
  不匹配）：`indicators` 为空、技术面按中性 50 计入，并在 `index.summary` 中显式说明
  「技术面 5 维度对 W/M K 不适用，已按中性 50 计入（非『数据不足』）」。该披露是 V0.78.0
  Step D 补上的 —— 原文案写在内部对象上，从未进入响应。

### 6.3 宏观参考指数（综合趋势指数 = 技术面 × 25% + 宏观面 × 35% + 消息面 × 25% + 资金流面 × 15%）

| 因子 | 权重 | 与黄金关系 | 友好度100分位 | 友好度0分位 | 数据源 |
|------|------|-----------|--------------|------------|-------|
| 美元指数 DXY | 13% | 负相关 | 94 | 107 | Yahoo `DX-Y.NYB` |
| 美债2Y收益率 | 5% | 负相关 | 3.0% | 5.0% | 美联储 H.15 |
| 美债10Y收益率 | 7% | 负相关 | 3.8% | 5.4% | 美联储 H.15 |
| 美债30Y收益率 | 5% | 负相关 | 4.3% | 5.7% | 美联储 H.15 |
| 美债10Y-2Y利差 | 9% | 负相关（倒挂利多） | -0.5% | 1.5% | 派生（10Y − 2Y） |
| 美债10Y实际利率 | 18% | 负相关 | 0.8% | 3.2% | FRED `DFII10` |
| VIX恐慌指数 | 9% | 正相关（避险） | 30 | 13 | FRED `VIXCLS` |
| 国际央行购金量 | 22% | 正相关（结构性） | 1200吨/年 | 500吨/年 | WGC GDT 季度 |
| 美国政府债务/GDP | 5% | 正相关（债务↑利多，debasement） | 140% | 60% | FRED `GFDEGDQ188S` 季度 |
| 中国政府债务/GDP | 4% | 正相关（债务↑利多，debasement） | 95% | 40% | FRED `GGGDTACNA188N` 年度 |
| 欧洲政府债务/GDP | 3% | 正相关（债务↑利多，debasement） | 95% | 60% | Eurostat `GOV_10Q_GGDEBT` 季度（EU27_2020） |

- 宏观参考指数 = Σ(因子友好度 × 权重)，0-100；**随宏观参数动态变化**（V0.119.0 起
  11 个因子全部有自动源：美债 2Y·10Y·30Y 取美联储 H.15，美元指数取 Yahoo `DX-Y.NYB`，
  VIX 与 10Y 实际利率取 FRED `VIXCLS` / `DFII10`，10Y-2Y 利差由 10Y−2Y 派生，
  央行购金为年度数据，美国/中国债务取 FRED `GFDEGDQ188S`（季度）/ `GGGDTACNA188N`（年度），
  欧洲债务取 Eurostat `GOV_10Q_GGDEBT`（季度，`EU27_2020` 口径））
- **阈值口径（V0.118.0 起默认动态）**：表中的 100/0 分位是**兜底值**。当
  `daily_macro_factors` 里该因子的样本 ≥ 60 个交易日时，改用**近 252 日滚动 90/10
  分位**，阈值跟随市场自动调整。响应里 `macro.macro_dynamic` 是「全部可滚动因子
  都动态」的布尔摘要，`macro.dynamic_factors` 给出逐因子明细。
  ⚠️ 滚动分位的方向跟每个因子的**符号约定**走：负相关因子（美元 / 三档美债 /
  实际利率 / 10Y-2Y 利差）取 `best = P10、worst = P90`（值越低越利多黄金），
  正相关因子（VIX / 央行购金 / 3 个政府债务）取 `best = P90、worst = P10`。
- **可滚动因子清单由后端给出**（V0.119.0）：`macro.rolling_factors` 是一个字符串数组，
  列出**实际参与**滚动分位的因子 key（当前 7 个）。前端「N/M 因子使用滚动分位」的
  M 直接读它的长度，**不再硬编码**排除清单。央行购金与 3 个政府债务因子是
  季度 / 年度低频序列，**不进**该清单（日频落表会把同一个值重复几十次 ⇒ P10 == P90
  ⇒ 阈值退化）。
- **低频因子的滞后口径**（V0.119.0）：每个 `macro.factors[]` 元素带 `cadence`
  （`daily` / `quarterly` / `annual`）与 `max_lag_days`（日频 4 / 季度 300 / 年度 1100）。
  滞后告警阈值按 `max_lag_days` 逐因子判定 —— 季度 / 年度因子的 `data_date`
  天然滞后几百天，用日频的 4 天阈值会**永久亮红灯**（常亮的告警等于没有告警）。
- 综合趋势指数 = 技术面 × 25% + 宏观面 × 35% + 消息面 × 25% + **资金流面 × 15%**
  （`services/macro.py::TECH_WEIGHT/MACRO_WEIGHT/NEWS_WEIGHT/FLOW_WEIGHT`，用户可在 `/weights` 调整）
- **任一面不可用时剔除该面、按剩余面权重归一化（V0.78.0 Step D）**：技术面可能不可用
  （5 个维度全部数据不足），**资金流面也可能不可用**（V0.120.0：5 个外部源全挂时
  `flow.score = null`）。此时 `index.components` **不含**该 key、`index.summary` 注明
  「已剔除并按剩余面权重归一化」，`/weights` 预览同步按剩余面归一化。
  消息面未打分同样是 **`null`**（V0.100 起：未打分 ⇒ 消息面**不参与**综合指数，
  其配置权重被剔除、其余面按有效面归一化）。宏观面有静态参考兜底、结构上恒有值。
- **`index.face_weights` / `index.face_weights_nominal`（V0.120.0 新增）** ——
  前端**不重算权重**（用户可在 `/weights` 改权重，写死在前端必然与实际算法对不上）：
  | 字段 | 含义 | 用途 |
  |---|---|---|
  | `face_weights` | 各面**实际生效**权重（已剔除不可用的面并按剩余面归一化） | 「运算方法」公式、结论卡分面权重条 —— 公式必须等于实际算法 |
  | `face_weights_nominal` | 各面**配置权重**（剔除/归一化之前的原值，恒含 4 个面） | 说明「消息面 X% 权重被剔除」—— 被剔除的面**不在** `face_weights` 里，只能从这里取 |
  两者同时给，是为了让前端既能算「现在按什么加权」，又能说清「谁没参与、原本占多少」。
  ⚠️ 老 client 用 Pydantic v2 默认 `extra="ignore"` 解析新 response 不报错。
- ⚠ **已知下游耦合**：`services/resonance.py::compute_resonance` 对缺失维度按中性 50 兜底
  （其原设计如此），故上述边角场景下共振信号仍按 50 参与 —— 已记入 `docs/roadmap.md`
  的 V0.79.0 待办。

### 6.4 资金流面（第 4 个评分面，V0.120.0）

**只收流量 / 数量类读数，不收价格类读数** —— 汇率、利率、SHIBOR 归宏观面，
避免同一条逻辑计两遍。

| 因子 | 节奏 | 面内权重 | 与黄金关系 | 友好度100分位 | 友好度0分位 | 数据源 |
|------|------|---------|-----------|--------------|------------|-------|
| 黄金投机净多占 OI | 周 | 18% | 正相关（仓位拥挤度） | 34.10% | 6.49% | CFTC 分类持仓（年文件） |
| 黄金投机净多 4 周变化 | 周 | 14% | 正相关（钱在不在买） | +41,616 张 | -43,005 张 | CFTC 分类持仓 |
| 黄金 ETF 4 周累计净申赎 | 周 | 22% | 正相关（国内真金白银进场） | +74.25 亿元 | -20.84 亿元 | 上交所 518880 官方份额 |
| 美元净流动性 4 周变化 | 月 | 14% | 正相关（钱在系统里的总量） | +130,328 $M | -252,039 $M | FRED `WALCL`/`WTREGEN`/`RRPONTSYD` |
| A股融资余额月变动 | 月 | 16% | **负相关**（机会成本口径） | -4.30% | +6.03% | 上交所 + 深交所融资余额 |
| 中国 M1-M2 剪刀差 | 月 | 16% | **负相关**（机会成本口径） | -11.2 pp | -3.1 pp | PBoC `macro_china_money_supply` |

- **周频合计 54% / 月频合计 46%**（用户明确要求「关注近期的资金数据，按周和月的关键因子」）。
  `flow.weekly_weight` / `flow.monthly_weight` 直接给出这两个比例，前端据此分组展示。
- **负号口径**：`cn_margin_flow` / `cn_money_gap` 取**机会成本**符号 —— 值越高越利空黄金
  （杠杆钱留在股市 / 钱淤积在定期存款 ⇒ 抗通胀资产需求下降）。
  它们与正号因子共用同一套 `score = clamp((value − worst) / (best − worst) × 100, 0, 100)`
  公式，方向差异只体现在 `best` / `worst` 的取值上。
- **滚动分位按观测节奏取窗（V0.120.0 新机制）**：周频因子窗口 **728 日（104 周）**、
  月频 **1826 日（60 月）**，不用日频的 252 日 —— 日频落表会把同一个周值重复约 5 次、
  把 P10/P90 压平成同一条线（阈值退化，`best == worst` 恒返回 50）。
  历史表 `daily_money_flow_factors.snapshot_date` 存**因子自身的观测日**，
  只在出现新观测时写一行 ⇒ 窗口内天然是不同观测。
- **`flow.score` 可空（与宏观面不同）**：一个因子都没取到读数时 `score = null`，
  **整面从综合指数里剔除**（不按 0 分计入）—— 0 分会被读成「极度利空」。
- **降级链复用宏观面三件套**：`tier` 字段区分 `live`（本次真的观测到）/ `lkg`
  （末次落库的真实读数）/ `static`（内置常量兜底，**不是市场读数**）；
  静态兜底值与末次落库值都**不写历史表**（`is_persistable_source`）。
- **观测锚点（V0.120.0 修掉的真缺陷）**：周频因子锚在 **ISO 周的最后一个交易日**，
  月频因子锚在**已过完的月的日历月末**（观测值按「该日当天或之前最近的一条」取值）——
  实时采集 / 历史回填 / 静态标定**三处共用同一份锚点函数**
  （`repositories/money_flow_sources.py::week_end_days()` / `month_end_days()`）。
  ⚠️ `us_liq_net` 的**源是周更**（FRED H.4.1），但它的值是「**4 周变化**」⇒
  按周采样时相邻两次观测**重叠 3/4**，有效样本只剩名义值的 1/4（`min_samples` 达标是假象）
  ⇒ 所以它的**观测节奏是月**，不是周。因子里返回的 `data_date` 会显示实际窗口
  （如 `2026-08-31~2026-09-30`）。
- **滞后口径**：周频因子 `max_lag_days = 14`、月频 `60` —— 超过才亮红灯。
- 配置位置：`services/money_flow.py::MONEY_FLOW_FACTOR_RULES`；阈值滚动分位由
  `services/macro_thresholds.py` 统一计算（按因子的 `window_days` 取窗）。
- ⚠️ **共振信号尚未纳入本面**：`services/resonance.py` 至今只读 tech / macro / news
  三个面 ⇒ 首页「一致性判定」暂时看不到资金流面。这是**已知缺口**，不是设计。

### 6.5 告警规则 + Web Push 订阅（V0.72.0）

**alert_rules**（持久化到 `app_settings` 表，key=`alert_rules`；与 weight_config / backtest_config 同表）：

| 字段 | 类型 | 默认 | 说明 |
|------|------|------|------|
| `level_crossing_enabled` | bool | True | 档位穿越告警（BULLISH↔BEARISH 主轴翻转；SIDEWAYS 抖动忽略） |
| `volatility_enabled` | bool | True | 单日波动告警（按 `volatility_pct` 阈值） |
| `volatility_pct` | float (0.1-20) | 3.0 | 波动阈值百分比（绝对值 ≥ 此值触发） |
| `quiet_hours.start` | HH:MM | "22:00" | 静默起始（BJT） |
| `quiet_hours.end` | HH:MM | "07:00" | 静默结束（BJT，跨夜有效） |
| `channels` | list[NotifyChannel] | ["browser"] | 推送渠道偏好（按顺序尝试；至少 1 项 + 不重复） |
| `updated_at` | datetime \| null | — | 上次保存时间（BJT） |

**NotifyChannel**：`"browser" \| "webpush" \| "email" \| "wechat"`（4 选 N，Literal 校验）

**push_subscriptions** 表（迁移 `9e2f4a1b8c7d_push_subscriptions.py`）：

| 列 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `id` | Integer | PK | 自增主键 |
| `endpoint` | String(512) | UNIQUE NOT NULL | FCM / Mozilla 推送端点 URL |
| `p256dh` | Text | NOT NULL | 椭圆曲线公钥（base64url） |
| `auth` | Text | NOT NULL | 认证密钥（base64url） |
| `user_agent` | String(256) | NULL | 订阅时浏览器 UA |
| `created_at` | DateTime(timezone) | DEFAULT CURRENT_TIMESTAMP | 创建时间 |
| `archived_at` | DateTime(timezone) | NULL + INDEX | 410 Gone 时设；查询 `WHERE archived_at IS NULL` 过滤活跃订阅 |

**vapid_keys**（持久化到 `app_settings` 表，key=`vapid_keys`，BaseModel）：
- `private_key`: PEM 编码 EC P-256 私钥（启动时若不存在则自动生成一次）
- `public_key`: base64url 编码的 X962 UncompressedPoint（暴露给前端订阅）

### 6.6 认证与账号体系（V0.75.0 第 ① 步）

> ⚠️ **本版是「认证骨架」**：已具备凭证校验、会话与权限守卫的完整链路，但业务表（持仓 / 账本 / 消息面 / 快照等）**尚未加 `user_id` 列**，因此**尚无数据隔离** —— 能登录进来的人看到的是同一份数据。数据隔离在 V0.75.2 落地，找回密码 + 用户管理在 V0.75.3 落地。

**users** 表（迁移 `d5f81a3c9b47_auth_users_sessions.py`）：

| 列 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `id` | Integer | PK | 自增主键；`LEGACY_USER_ID = 1` 为单用户模式下的隐式主体 |
| `email` | String(255) | UNIQUE + INDEX | 登录名，入库前经 `normalize_email()` 小写 + 去空白 |
| `display_name` | String(64) | NULL | 显示名（顶栏徽章） |
| `password_hash` | String(255) | NOT NULL | **bcrypt**（cost 由 `BCRYPT_COST` 控制，默认 12）；**永不随响应返回** |
| `role` | String(16) | DEFAULT `member` | `owner` / `member`；首个注册用户自动 `owner` |
| `is_active` | Boolean | DEFAULT true | 禁用后无法登录（文案与密码错误完全一致，不泄露账号状态） |
| `created_at` / `updated_at` / `last_login_at` | DateTime | 朴素 UTC | 与 SQLite 存储格式对齐（`utcnow()` / `as_naive_utc()`） |

**sessions** 表（**服务端会话**，可即时撤销）：

| 列 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `id` | String(64) | PK | 不透明令牌 `secrets.token_urlsafe(32)`（43 字符）；**不放 JWT，不存用户信息** |
| `user_id` | Integer | INDEX | 归属用户 |
| `expires_at` | DateTime | INDEX | 过期时刻（`SESSION_TTL_HOURS`，默认 336h = 14 天） |
| `last_seen_at` | DateTime | — | 滑动续期（`SESSION_TOUCH_SECONDS`，默认 300s 内不重复写） |
| `revoked_at` | DateTime | NULL | 撤销时刻；登出 / 改密 / 禁用用户时写入 |
| `user_agent` / `ip` | String | NULL | 审计用 |
| `created_at` | DateTime | — | 签发时刻 |

> 复合索引 `ix_sessions_user_revoked (user_id, revoked_at)` 支撑「用户有效会话列表」与「批量撤销」；**无外键**（与 `push_subscriptions` 理由一致：SQLite 上便于迁移与清理）。

**关键行为约定**

| 项 | 口径 |
|----|----|
| 密码策略 | 长度 ≥ 8、≤ 72 字节（**bcrypt 硬上限，超长直接拒绝而非静默截断**）、非纯数字、不在弱口令黑名单 |
| 登录限流 | 进程内滑动窗口 `LoginThrottle`，`user:<email>` 与 `ip:<ip>` **双维度**；`LOGIN_MAX_ATTEMPTS=5` / 窗口 15min / 锁定 15min；超限返回 429 `login_throttled` |
| 时间攻击缓解 | 账号不存在时仍执行一次等成本的**虚拟哈希**，避免「响应快 = 账号不存在」的侧信道 |
| 会话 Cookie | `pm_session`：`HttpOnly` + `SameSite=Strict` + `Path=/` + `SESSION_COOKIE_SECURE` 可配 |
| CSRF | **双提交**：可读 cookie `pm_csrf` + 请求头 `X-CSRF-Token`，`secrets.compare_digest` 恒时比较；仅校验写方法（POST/PUT/PATCH/DELETE） |
| 中间件顺序 | `CORSMiddleware → RateLimitMiddleware → TraceIdMiddleware → AuthMiddleware → CsrfMiddleware → routes`（**先注册即内层**，故 401/403 响应仍带 CORS 头、审计日志仍带 trace_id、暴力破解先被 per-IP 限流拦下） |
| 单用户兼容 | `AUTH_ENABLED=false`（默认）时两个中间件**读完配置即 return**，不读 cookie、不访问 DB、不 set-cookie → 行为与 V0.74.3 逐字节一致 |
| 公开路径白名单 | `/api/v1/health`、`/api/v1/auth/{status,login,register,logout}`、`/api/v1/telemetry/ingest`（telemetry 需保留匿名上报能力） |
| 文档暴露 | `AUTH_ENABLED=true` 且 `APP_ENV=prod` 时自动关闭 `/docs` / `/redoc` / `/openapi.json` |
| 审计埋点 | `login_success` / `login_fail` / `logout` / `authz_violation` 四类事件进前后端同一白名单 |

### 6.7 首页综合研判结论卡（V0.75.1）

> 设计出发点：**缺的不是数据，是收敛**。首页此前把综合指数 / 分面分值 / 共振类别 / 决策建议 / 建议仓位 / 理由明细平铺在 6 个面板里，用户需要自己横向扫一遍再心算「到底该不该动」。结论卡只做一件事——**把这些原料按决策顺序排成一条线**。

| 口径 | 规则 |
|------|------|
| 三大数据源 | `GET /api/v1/market/gold/trend?days=60&target=` （必需）+ `GET /api/v1/decision/etf?days=60&target=` + `GET /api/v1/resonance/signal?target=`（后两者失败仅降级对应区块，`Promise.allSettled`） |
| 结论行 | 行动建议与置信度**一律取后端 `decision`**（`action` / `action_label` / `confidence` ∈ low·medium·high），前端不自造阈值 |
| 分面分值 | 技术面 25% / 宏观面 35% / 消息面 25% / 资金流面 15%（V0.120.0 起四面），权重与 `/weights` 页面同源（`index.components`）；红=利多 绿=利空 **且附 ↑↓→ 文字符号**（满足色觉障碍可读性） |
| 一致性判定 | **不在前端重算** —— 直接取 `/api/v1/resonance/signal` 的 `signal`（5 类：`strong_up` / `strong_down` / `weak_up` / `divergent` / `neutral`）。后端阈值引用 `schemas/thresholds.py` 的 `DirectionThreshold.BULLISH`(55) / `BEARISH`(45)（V0.78.0 起不再裸写字面量），`confidence = avg × (1 - stdev/55)`。**`divergent` 自 V0.78.0 起改为「三维任意一对分差 ≥ 15」**（⚠️ 共振信号**至今仍只看 tech/macro/news 三个面**，资金流面未纳入 —— 见 §6.4）（原仅判 tech vs macro 且要求方向相反，会整类漏掉「消息面看多 + 技术看空」这类反转先行信号），取**幅度最大**的一对，并由 `subtype` 标明维度对 `tech_macro` / `tech_news` / `macro_news`、`subtype_label` 给中文说明（前端 i18n 键缺失时回退它）。**理由**：若前端另立一套阈值，后端调参后两处口径必然打架 |
| 仓位对照 | 后端 `position_ratio` 恒为 `0`（`services/position.py` 注释「账户本金未知，暂不估算」）→ 卡片**不展示「当前仓位 X%」**，只显示「空仓 / 持有 N 份 · 浮盈浮亏」，避免用 0 编造出「仓位 0%」的假信号 |
| 数据质量折损 | ① 宏观因子的**取值层级** `MacroFactorOut.tier`（V0.118.1）：`live`（本次真的观测到）/ `lkg`（上游源当时不可用，用上次成功落库的真实读数顶替）/ `static`（内置常量兜底，非市场读数）。`lkg` 与 `static` 各自的项数 / 名称 / 最新数据日分别提示（`syn.q_macro_lkg` / `syn.q_macro_static`）。判据**优先用 tier 字段**，tier 缺失时才退回匹配 source 的占位标记字面量；**不能**用「非 H.15 即静态」这类启发式——央行购金来源是 `世界黄金协会 GDT Q2 2026`，属正当季度源；② 消息面 `scored=false` 时提示未打分；③ `trend.degraded=true` 时报出 mock 源市场数。三者都直接扣减「结论可信度」的提示，**如实标注优先于观感统一** |
| 品种切换 | 黄金 `etf` / 白银 `silver_etf`，一次切换使 trend / decision / resonance **三个 target 同步生效**，选择记忆于 `localStorage.pm_synthesis_asset` |
| 刷新 | 60s 轮询 + `inflight` 重入保护（防止慢响应叠加）；`i18n:change` 事件触发重渲染；`aria-live="polite"` 播报结论变化 |
| i18n | 自持 `T(key, fallback)` 包装：缺失 key 时**回落到中文硬编码**（`I18n.t()` 查不到会返回 key 字面量，若不兜底页面上会直接出现 `syn.cons_strong_up` 这种裸 key）；三语各 49 个 `syn.*` 键，并由 2 条门禁守住（脚本引用键三语齐全 + 三语键集合严格一致） |

### 6.8 首页内嵌消息面打分器（V0.76.0）

`static/news-score-widget.js`（IIFE + `window.PM_NewsScore = { mount, load, openSlot, getState }`，自注入 `<style>` 并全部走 `--up/--down/--muted/--accent/--border/--card` 变量 → 4 主题免覆盖），自动挂载到 `trend.html` 的 `#newsScoreCard`（位于 `#synthesisCard` 之下、实时评估摘要之上）。

| 方面 | 说明 |
|------|------|
| 起因 | 消息面占综合评估指数 **30%**（V0.120.0 起 25%），却是各面中唯一**由用户自己产出**的维度。V0.75.1 收敛「今日操作清单」后，首页只剩 `#newsFactor` 一行只读展示 —— 想打一次分必须整页跳到 `/news` |
| 组件构成 | ① **3 槽位状态一览**（分值 / 权重 1:2:3 / 方向 / 提交时刻 / 备注 / 补录标记 + 逐槽「修改」「撤销」）② **当日有效分值** + **后端算式原样展示**（`(1×45 + 2×70) ÷ 3 = 61.7`）③ **内嵌编辑器**（滑杆 + 快捷档位 + 沿用上次 + 方向判定 + 研判备注 + 12 依据标签 + 复盘批注）④ **状态提示条**（未打分 / 还有 N 次 / 三次已用完，三态配色走 `--chip-*-bg/fg/bd`） |
| 接口 | 复用既有 `GET|PUT|DELETE /api/v1/news-score`（**未新增任何端点**，`app.openapi()` 仍为 67 paths / 76 operations）；依据标签取 `GET /api/v1/review/meta` 的 `basis_tags`（失败时回落到内置 6 个标签，不阻塞打分主流程） |
| 口径同源 | 方向阈值（>55 看多 / <45 看空）与当日有效分值 **1:2:3 加权**一律取后端（`services.news.aggregate_slots`，与 `/news`、复盘页同源）；**前端只做展示与提交，绝不重算加权** |
| 保存后刷新 | 派发 `news-score-changed` → `trend.html` 监听后调 `refreshTrendQuotes()` 重算评估口径；同时直接调 `window.PM_Synthesis.load()` 刷新置顶结论卡。**全程不跳页** |
| ⚠️ 数据守门 | 载入既有槽位时**必须回填 `notes` / `basis` / `review_note`**：仓库层 `upsert` 的 UPDATE 分支对 `notes` 与 `basis` 是**硬覆盖**，不回传即被静默清空（2026-09-30 实测确认）；而 `review_note` 写的是 `review_note or existing.review_note` → **空值保留旧值、根本清不掉**（回填它是为了让用户看到真值，**不要**当它是可清空字段） |
| 刻意不轮询 | 打分器含可拖拽滑杆与文本框，定时重渲染会打断输入（滑杆跳回、光标丢失）；分值只因「有人提交」而变，提交后自渲染即可。只读的 `#newsFactor` 仍由首页既有 60s 轮询保持新鲜 |
| 与 `/news` 的关系 | `/news`（563 行）**本版未改动**，仍保留投行参考来源链接 + 跨日历史记录，是「完整详情页」；首页打分器是其**轻量通道**，两处共用同一接口与口径 |
| i18n | 三语各 64 个 `nsw.*` 键，由 2 条门禁守住（从脚本源码反推引用键三语齐全 + 三语键集合严格一致）；同样自持 `T(key, zh)` 中文兜底 |
| 已知边界 | 保存会触发后端 `TrendService.invalidate_for_news()` 让评估缓存失效 → 首页随即重算。**数据源不可达时该重算较慢**（本机 DNS 故障环境下实测 `GET /market/gold/trend` 首次重算 **23.26s**，缓存命中仅 0.017s），正常联网时应为亚秒级 |

---

### 6.9 阈值常量（V0.78.0）

`src/app/schemas/thresholds.py` 集中管理全部分数阈值，取代原先散落在 6 个服务模块里的裸字面量。四组枚举**语义互不相同，不可互相套用**：

| 枚举 | 取值 | 判定方式 | 服务于 |
|------|------|----------|--------|
| `DirectionThreshold` | `STRONG_BULLISH` 70 / `BULLISH` 55 / `NEUTRAL_HIGH` 60 / `NEUTRAL_LOW` 40 / `BEARISH` 45 / `STRONG_BEARISH` 25 | 消息面与共振用**严格**不等号；单维度方向用 60/40 | 消息面打分 / 共振信号 / 单维度方向 |
| `LevelThreshold` | `STRONG_UP` 75 / `UP` 55 / `SIDEWAYS` 45 / `DOWN` 25 | **含端点**（≥55 即 UP） | 综合指数等级；决策页仓位档位复用同一套分界点 |
| `OpportunityWindowThreshold` | `STRONG` 70 / `MEDIUM` 55 / `WEAK` 40 | 含端点 | 宏观机会评分 → 强 / 中 / 弱投资窗口 |
| `DecisionThreshold` | `BUY_HEAVY` 75 / `BUY` 65 / `BUY_LIGHT` 55 / `HOLD` 50 / `HOLD_LOW` 40 | 含端点 | 决策矩阵档位（BUY 拆 3 档 + HOLD 缓冲档） |

**三套方向口径并存是有意设计，不是冲突** —— 它们回答的是不同问题：

| 口径 | 分值恰好 55 时 | 用在哪 | 为何不同 |
|------|----------------|--------|----------|
| 消息面 | 中性（须严格 `> 55` 才算看多） | `services/news.py` | 消息面是**客户主观打分**，跨过中线即算表态 |
| 综合指数等级 | 上升（`≥ 55` 即 UP） | `services/trend.py` | 等级是**分档展示**，含端点更符合直觉 |
| 单维度方向 | 看多（`≥ 60` 才算，比消息面更严） | `services/scoring.py` / `services/macro.py` | 单维度的中性区更宽，避免噪声因子频繁翻转 |

**唯一已知不对称**：`decision._build_reason_items` 为结论卡「参数面」着色时用 `55 / 40`，其中 40 故意不同于 `DirectionThreshold.BEARISH`(45) —— 显示层需要更早示警。改动它属产品语义决策，不由本次口径收口处理；现状由测试显式锁死而非默默保留。

改任何阈值前，请按 `docs/parameter-evaluation.md` §6.2 的三维交叉验证（Sharpe + 最大回撤 + 命中率 / 校准）评估新值效果，而非直接拍数。全部阈值边界由 `tests/test_services/test_thresholds.py` 锁住，该文件还以 AST 机械保证「服务层判定逻辑不再出现裸阈值字面量」。
