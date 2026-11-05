# 开发路线图（唯一活跃路线）

> **目标读者**：开发者 / 决策者 ｜ **状态**：活跃 ｜ **最近更新**：2026-11-05 ｜ **基线**：V0.120.4
>
> **本文件是 `docs/` 里唯一的「下一步」真源。**
> 它合并了原 6 份互相重叠的规划文档（`improvement-path.md` / `ux-roadmap.md` / `roadmap.md` /
> `next-steps.md` / `app-improvement-path.md` / `feature-alignment.md`），
> 并在合并时**逐条复核了每一条在当前基线上的真实状态** ——
> 旧文档的基线停在 V0.77 ~ V0.116，**其中一半的结论已经过时或已被修掉**。
>
> **合并原则**：只写**仍然成立**的问题；已修的直接写进 §四「已完成」，不再当待办。
> 每条待办都带**可复现的实测判据** —— 没有实测过的判断不写进来。

---

## 〇 一页结论 · 当前最该做的 5 件事

| 优先 | 问题 | 一句话 | 状态 |
|---|---|---|---|
| **P0** | **`days` 参数完全失效** | `?days=30/60/120` 返回**完全相同**的结果 ⇒ 52W 按钮画的是 12 周 | 🔴 仍存在（实测 2026-11-05） |
| **P0** | **命中分析「上涨日数」恒为 0** | `direction` 取值里根本没有 `"up"` ⇒ 计数永远加不上 | 🔴 仍存在 |
| **P0** | **64% 的历史评分行带伪造消息面 50 分** | 38/59 行 `news_index = 50`（=「没打分」被写成中性） | 🔴 仍存在 |
| **P0** | **`/headlines` 渲染出 i18n key 字面量** | 页面可见 `time.hour_ago`（字典里是复数 `time.hours_ago`） | 🔴 仍存在 |
| **P1** | **门禁自身有 4 处失效** | 坏门禁比没门禁更坏：它让人以为有保护 | 🔴 仍存在 |

> **P0-4（`window.PM_I18N` 从未定义）已在 V0.120.4 修复**（4 个文件、12 处调用），
> 修完首页首屏从 ~2.2s 降到 ~0.4s。详见 [releases/milestones/m5-four-faces-and-ai-usability-v0.116-v0.120.md](releases/milestones/m5-four-faces-and-ai-usability-v0.116-v0.120.md)。

---

## 一、可信度层（最高优先 · 用户会被误导的地方）

### A1 · 命中分析的「上涨日数」恒等于 0 🔴

**现象**：命中分析页每个时间桶的「上涨天数」永远是 0。

**实测（2026-11-05）**：`scoring_daily_wide.direction` 的取值分布 ——

| direction | 行数 |
|---|---|
| `down` | 30 |
| `bearish` | 14 |
| `neutral` | 8 |
| `bullish` | 7 |
| **`up`** | **0（不存在）** |

而代码 `src/app/services/scoring_wide.py:293` 算的是
`up = sum(1 for r in grp if r.direction == "up")` ⇒ **永远加不上**。

**根因**：`direction` 存的是**趋势指数方向**（`bullish`/`bearish`/`neutral`）与
另一个口径（`down`）混在一列里，而统计代码按「价格涨跌方向 `up`/`down`」去找。

**修法建议**：要么把统计口径改成 `bullish`（与列里已有的值对齐），
要么在 ETL 落库时**单独写一列价格方向**（`price_direction`）——
后者更干净：趋势方向和价格方向本来就不是一回事，混在一列里早晚还会踩。

### A2 · 64% 的历史评分行带着伪造的中性消息面 50 分 🔴

**实测（2026-11-05）**：`scoring_daily_wide` 59 行里 **`news_index = 50` 的有 38 行（64%）**，
`news_index IS NULL` 的 **0 行**。

**为什么 50 是假的**：50 = 「中性」= **「没打分」**的占位值。
V0.100.0 已经把「未打分」改成 `score=None` + 综合指数挂 pending chip，
但**历史宽表里的旧行没被回填**，于是：
- 命中分析里这些行**参与了消息面均值**（把 50 当成真实打分）；
- 而同一个综合指数在实时接口里是 **pending** ⇒ **同一个日子两个结论**。

**修法建议**：对 `news_index = 50` 且当天 `news_scores` 无记录的行，
ETL 落库时写 `NULL` 而不是 50；已落库的 38 行需要一次回填。

### A3 · `days` 参数完全失效 ⇒ 52W / 24M 按钮画的是 12 周 🔴 ⭐

**这是本清单最严重的一条**（一个字符的错误，解释了三个假象）。

**实测（2026-11-05，线上 `192.168.0.204:8888`）**：

```
/api/v1/market/gold/trend?days=30   → metrics.start_date=2026-09-24  points=30  index=39.5
/api/v1/market/gold/trend?days=60   → metrics.start_date=2026-09-24  points=30  index=39.5
/api/v1/market/gold/trend?days=120  → metrics.start_date=2026-09-24  points=30  index=39.5
```

**三个不同的请求返回完全相同的结果** —— `days` 根本没进计算。

**根因**：`src/app/services/cache.py:35` 的缓存 key 是
`(target, interval, on_date)` —— **没有 `days`**。
⇒ `?days=30` 先算完进缓存，后面 `?days=60` / `?days=120` **直接命中同一份缓存**。

**连带影响**：趋势页的「52W / 24M」按钮画的是 12 周 / 4 个月；
回测算不出收益率（价格日历取到的永远是 30 天）；价格回填只有 60 行。

**修法建议**：`days` 加进缓存 key（如 `(target, interval, on_date, days)`）。
⚠ 注意 `invalidate_cached_results()` 的失效逻辑要一起改，否则改完 key 会留下旧 key 的孤儿缓存。

### A4 · 命中分析缺「为什么这次错」⚪

**状态**：待设计。命中分析给了命中率与分位数，但没有把「错在哪一环」拆出来
（是方向反了，还是幅度不够？）。

**实测（2026-11-05）**：回测的**可用观测已从 1 个涨到 38 天**
（`daily_snapshots` 与 `gold_price_daily` 的日期交集 38 天）⇒
原先「建立在 1 个观测上」的告警已不成立，但样本量仍然很薄，
**分位数类指标现在还不可信**。

### A5 · `group_combine` 开启时，5 个技术面权重滑块完全是装饰 🔴

**实测（2026-11-05）**：`src/app/services/trend.py:796` 仍然只读写死的
`GROUP_WEIGHTS = {trend:0.50, overbought:0.30, risk:0.20}`；
`weights.html` 的 5 个滑块**没有 disabled、没有任何提示**。
⇒ 用户拖动滑块 → 数字变 → 求和校验显示 100% 绿 → 保存成功 → **对技术面指数零影响**。

**修法建议（三选一）**：
1. 组内模式下把 5 个滑块**置灰 + 明确说明**「当前为组内平均模式，单维度权重不参与计算」，
   同时给真正生效的 `GROUP_WEIGHTS` 补一个可编辑入口；
2. 让滑块在组内模式下改写组权重（交互复杂，容易误解，不推荐）；
3. 组内模式下隐藏滑块只留组权重（会打断用户的肌肉记忆）。

### A6 · AI 助手的 token 统计失真，页面上渲染成 `↓ 0` 🔴

**实测（2026-11-05）**：
- 客户端 `static/ask.js:860` 初始化 `inputTokens: 0`，**全文件没有任何一处给它赋值**
  （`text`/`toolName`/`toolInput` 都有赋值，唯独两个 token 字段没有）；
- 服务端 `service.py:454` 的 `total_in_tok` 初值 0，**只在收到 `StreamMessageStart` 事件时**才赋值
  —— miniMax 代理不发该事件时就是 0。

**语义混淆**：0 的意思是「**未知**（没拿到 usage）」，不是「用了 0 个 token」，
但落库和渲染都当成 0。

**修法建议**：① 客户端接 `message_stop` 的 `usage` 填进 `currentRound`；
② 服务端 `input_tokens` 改 `NULL` 表示未知；③ 前端把 0 一并视为「未取到」。

### A7 · `/headlines` 渲染出 i18n key 字面量 🔴

**实测（2026-11-05，线上页面正文里能直接看到）**：`time.hour_ago`。

**根因**：`static/headlines.js:140/142/144` 用的是**单数** key
（`time.min_ago` / `time.hour_ago` / `time.day_ago`），
而三份字典里只有**复数**（`time.minutes_ago` / `time.hours_ago` / `time.days_ago`）。
且写法是 `I18n.t(key) || "分钟前"` —— key 字面量是 truthy，`||` 右边永远不触发。

**修法建议**：三个 key 改复数；兜底写法统一成
`if (v && v !== key) return v;`（`static/freshness.js:134` 是正确样板）。
⚠ 建议同时加门禁：扫全站 `[data-i18n]` 的**渲染结果**，禁止匹配 `^[a-z_]+\.[a-z_.]+$`。

### A8 · 三处页面的数据时效条从未渲染过 🔴

**实测（2026-11-05）**：`portfolio.html` / `trades.html` 里 `#freshnessInline`
只出现在 **HTML 注释**中（`portfolio.html:158` / `trades.html:64`）——**没有真实容器**，
且这两个页面**没有引 `freshness.js`** ⇒ `window.FreshnessBar` 不存在
⇒ `if (window.FreshnessBar && ...)` 守卫**静默跳过**。
`settings.html` 同样没有容器，但引了脚本 ⇒ `freshness.js` 空转、**每 60 秒跑一次无用调度**。

**修法建议**：这三页不是数据时效的重点页 ⇒ **删掉那 4 处误导性调用**比补容器更诚实。

---

## 二、数据纵深层

### B1 · 核心价格链落库停了 🔴

**实测（2026-11-05，生产库）**：

| 表 | 行数 | 最新日期 |
|---|---|---|
| `daily_snapshots` | 59 | **2026-11-04**（今天，在写） |
| `gold_price_daily`（target=etf） | 73 | 2026-10-28（**停写 7 天**） |
| `gold_price_daily`（target=ny） | 80 | **2026-10-14**（**停写 21 天**） |
| `news_scores` | 30 | 2026-11-04 |

⇒ **快照在写，价格链没写**。`gold_price_daily` 是回测与「数据可信度」的底座，
停写 ⇒ 回测样本越用越旧 ⇒ A4 的「38 天」会逐月退化。

**修法建议**：先查 `gold_price_daily` 的写入路径为什么停了（ETL 任务是否还在跑、
是否被 `served_cache` 的孤儿 key 挡住），再补一次回填。

### B2 · 仍缺的数据源

按优先级（完整清单在旧 `app-improvement-path.md` §二 B4，V0.120.5 已归档，原文见 git 历史）：
CFTC 黄金净多的连续周序列 → 美元净流动性的日频 → 黄金 ETF 份额直采（替代成交量÷换手率重建）。

---

## 三、参数可信度层

### C1 · 阈值口径可覆盖（价值最高 · 长期未交付）

**实测**：V0.111.0 交付的是「宏观因子手动校准」，**不是**「阈值口径可覆盖」。
→ 本条**仍未交付**。

**含义**：现在阈值口径改一次，用户手里的历史评估结论就跟着变一次，
但用户**无法在 UI 上看到「这次评估用的是哪套阈值」**。

### C2 · K 项 · 多市场独立校准

**状态**：未交付。`scoring_daily_wide` 只有 59 行，
**远不足以支撑分市场（黄金/白银/克价）独立校准**。

### C3 · 新增：判定阈值本身要可评估

现在评估质量只能用「命中率」这一个粗指标；需要能回答
「阈值定在 55 是不是比 50 好」—— 即**阈值本身要进入回测网格**。

---

## 四、决策闭环层

### D1 · verdict card 的置信度没有校准依据

置信度目前是规则给的，不是从历史命中率反推的。

### D2 · 参数 → 实盘的闭环还差最后一跳

从「调权重 → 看回测 → 落到买卖建议」之间，缺一环**把回测结论回流到建议侧**的机制。

---

## 五、工程纪律（门禁健康度）

> **坏门禁比没门禁更坏** —— 它让人以为有保护。以下 4 处**实测仍然存在**（2026-11-05）。

| # | 门禁 | 实测状态 | 修法建议 |
|---|---|---|---|
| 1 | `scripts/check_v084.mjs` | 🔴 断言 `#statusPanel` 里有 `#freshnessInline`，但 V0.84 已把它合并进状态条（现存 id 是 `#homeFreshness`）⇒ **100% 失败** | 改成断言合并后的真实 id；或直接删（V0.84 的行为已被 `_verify_home_metals` 覆盖） |
| 2 | `scripts/_verify_sw_update.mjs` | 🔴 **没有通过计数**（脚本里没有任何 `ok()`）⇒ 无法判红 ⇒ 永远绿 | 补计数与判红逻辑 |
| 3 | `scripts/_verify_mobile.mjs` | ⚠ 「打开时搜索框自动聚焦」历史上 flaky（3 跑 2 红 1 绿） | 聚焦断言要等「可见」而非等固定时长（见记忆 `visibility-hidden-blocks-focus`） |
| 4 | `tests/test_api/test_ai_chat_endpoints.py::test_send_message_stream_error_event_yields_error` | ⚠ 跨 event loop fixture（`is bound to a different event loop`） | 已知**预存缺陷**（早于本清单存在），不阻塞发版；修法是统一 loop 作用域策略 |

**已修复的**：`window.PM_I18N` 从未定义（12 处调用）—— V0.120.4 修完。

---

## 六、已完成 / 已失效（不再列为待办）

| 曾经的条目 | 现在的状态 |
|---|---|
| `window.PM_I18N` 从未定义（12 处） | ✅ **V0.120.4 已修**（首页首屏 2.2s → 0.4s） |
| `/ask` 状态条渲染 `status.warnings` / `status.dismiss` | ✅ 已修（`ask.html` 里已无这两个 key） |
| 回测建立在 1 个观测上 | ✅ 已缓解（可用观测 38 天）；但样本仍薄，见 A4 |
| 首页顶部导航 9→8 项 / 数据健康降为子页 | ✅ V0.111.1 已落地（见 M1 里程碑） |
| 5 处「显示假的」+ 4 处坏门禁（V0.117.0 计划） | 🟡 部分落地：A1/A2/A3/A7/A8 仍在，见上文 |
| 功能对账（`feature-alignment.md` 的用途） | ✅ **已由门禁自动化**：`check_docs_claims.py` 每次都核对文档里的表名 / key / 页面 / 端点是否真实存在 |

---

## 七、本文件怎么用

1. **新问题写进来之前先实测复现** —— 没有复现判据的判断不写。
2. **状态字段只有三种**：`🔴 仍存在` / `🟡 部分` / `✅ 已修`（已修的挪进 §六，不要留在待办里）。
3. **每条带一条可复现命令**（本文件里的都是实测输出，可直接复制重跑）。
4. **修完一条就更新状态 + 挪进 §六** —— 免得半年后又出现「已修的还在待办里」。

### 复核记录（2026-11-05）

本文档合并时对每一条都做了实测复核（生产库 + 线上 API + 浏览器）。
复核方式与结论见各条的「实测」小节。

> ⚠️ **门禁只做存在性断言，不校验版本号、测试数、日期** ——
> 这类「内容腐化」只能靠人工复核。本文件基线停在 V0.120.4，
> 下次复核建议在 **V0.125 左右**做一次。

---

## 附 · 合并自哪些旧文档

| 旧文档 | 行数 | 处置 |
|---|---|---|
| `docs/app-improvement-path.md` | 757 | 主体并入本文 §一~§四 |
| `docs/next-steps.md` | 261 | P0/P1 条目并入 §一/§五 |
| `docs/roadmap.md` | 779 | 历史里程碑表 → 改由 [releases/index.md](releases/index.md) + [releases/milestones/](releases/milestones/) 承载 |
| `docs/improvement-path.md` | 571 | 已归档（V0.50–V0.72 全部交付）⇒ 随 git 历史留存 |
| `docs/ux-roadmap.md` | 412 | 已归档（V0.68–V0.77 全部交付）⇒ 随 git 历史留存 |
| `docs/feature-alignment.md` | 287 | 已被门禁自动化 ⇒ 随 git 历史留存 |

**逐版原始 release notes** 同样在 git 历史里（tag 与原文件名同名）：
`git show v0.118.0:docs/releases/v0.118.0.md`。
