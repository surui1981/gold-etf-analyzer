# 下一步完善路径（V0.117.0 起）

> **状态**：待启动 ｜ **基线**：V0.116.0（commit `b747b00`，2026-10-22）
>
> **本文件的每一条都经过实测复现**，并附了复现判据。没有实测过的猜测不写进来。
>
> **为什么单开一份**：[roadmap.md](roadmap.md) 的基线停在 V0.100.0、「当前焦点」还写着
> V0.101 Python 3.13 迁移收口 —— **落后 16 个版本**，且 §2.2 把 V0.111.0 描述成
> 「阈值口径可覆盖」，但 V0.111.0 实际交付的是「宏观因子手动校准」。
> 那份文件的 §2.2 / §2.3 内容仍然有效，已并入本文 §三。

---

## §零 一句话结论

**当前最大的风险不是缺功能，是「看起来能用其实没用」。** 本轮排查在**没有报任何错**的
情况下找出 5 处用户会被误导的功能 + 4 处坏掉的门禁，全部已定位到具体行。
门禁坏了比没门禁更坏 —— 它让人以为有保护。

---

## §一 P0 · 用户被误导（全部已实测复现）

### 1. `group_combine` 开启时，5 个技术面权重滑块**完全是装饰**

**这是本轮最严重的一条。**

| 环节 | 实测结果 |
|---|---|
| 默认开关 | `group_combine=True`（`weights.html:292` `gcOn` 默认勾选） |
| 计算分支 | `trend.py:831-834` → `use_group_combine=True` → `combine_by_group(dim_scores)` |
| 实际用的权重 | `trend.py:712-714` 只读 `GROUP_WEIGHTS`，即 `trend.py:79` **写死**的 `{trend:0.50, overbought:0.30, risk:0.20}` |
| per-dim 权重 | `trend.py:834` 的分组分支**完全不读** `weights` 参数 |
| UI 表现 | `weights.html` 的 5 个滑块**没有 `disabled`、没有置灰、没有任何提示** |
| 用户操作 | 拖动 → 百分比数字跟着变 → 求和校验显示 100% 绿 → 保存成功 |
| 实际效果 | **对技术面指数零影响** |

即：用户以为自己在调参，实际在给一个不参与计算的字段写数据库。
`GROUP_WEIGHTS` 本身**也没有任何 UI 入口**（`settings` 层完全没有 group_weights 概念）。

**修法**（三选一，建议 1）：

1. 组内模式下把 5 个滑块**置灰 + 明确说明**「当前为组内平均模式，组内 5 个维度均分其组贡献，
   单维度权重不参与计算；如需按维度调权重请切到『单维度加权』」——
   同时给 `GROUP_WEIGHTS` 补一个可编辑入口（这是真正生效的那个参数）
2. 让滑块在组内模式下**改写组权重**（交互复杂，容易误解，不推荐）
3. 组内模式下**隐藏**滑块只留组权重 —— 会打断用户的肌肉记忆

### 2. AI 助手 token 统计失真，页面上渲染成 `↓ 0`

**实测数据**（`data/gold_etf.db`，46 条 assistant 消息）：

| 指标 | 值 |
|---|---|
| `input_tokens = 0` 的 assistant 消息 | **18 / 46（39%）** |
| `output_tokens = 0` | 0 / 46 |
| 会话级 `total_input_tokens` 合计 | 13760（**系统性低估**） |

**两条独立根因**：

- **客户端**：`ask.js:860` 初始化 `currentRound.inputTokens = 0`，但全文件
  **没有任何一处给它赋值**（`currentRound.text` / `toolName` / `toolInput` 都有赋值，
  唯独两个 token 字段没有）。而服务端 `service.py:489` 在 `message_stop` 里
  **明明发了** `usage: {input_tokens, output_tokens}` —— 客户端没接。
- **服务端**：`service.py:346/348` 的 `total_in_tok` 初值 0，**只在收到
  `StreamMessageStart` 事件时**才赋值。miniMax 代理不发该事件时就是 0。

**语义混淆**：0 在这里的意思是「**未知**」（没拿到 usage），不是「用了 0 个 token」，
但落库和渲染都当成 0。

**修法**：① 客户端接 `message_stop` 的 usage 填进 `currentRound`；
② 服务端 `input_tokens` 改 `NULL` 而非 0 表示未知；③ `ask.js:581` 的
`if (m.input_tokens != null)` 保持，但把 0 一并视为「未取到」并显示 `—` 或不显示。

### 3. i18n key 字面量外泄（3 处，**页面上直接看得见**）

**根因是同一个**：`i18n.js:76` 找不到 key 时 `return key`（返回 key 本身），
而各处 `window.I18n.t(key) || "中文兜底"` 的 `||` 右边**永远不触发**，
因为 key 字面量是非空字符串（truthy）。

实测复现：

| 页面 | 实测渲染结果 | 代码 | 字典里实际是 |
|---|---|---|---|
| `/ask` 状态条 | `status.warnings` | `ask.html:350` | **三份字典 0 命中** |
| `/ask` 状态条 | `status.dismiss` | `ask.html:353` | **三份字典 0 命中** |
| `/headlines` | `8 time.hour_ago` | `headlines.js:140/142/144` 查 `time.min_ago`/`hour_ago`/`day_ago` | `time.minutes_ago`/`hours_ago`/`days_ago`（**复数**） |
| `/home` | `home.title` | 某处 key 未收录 | — |

（第 139 行的 `time.just_now` 是存在的，那行正常。）

**修法**：把各处的兜底写法统一成 `static/freshness.js:134` 的正确形式
`if (v && v !== key) return v;`，**不要**用 `|| fallback`。
`headlines.js` 三个 key 改复数；`ask.html` 两个 key 要么补进三份字典、要么删掉
`data-i18n` 属性（内联的「警示」「不再提示」本来就对，补字典更好）。
建议同时加一条门禁：**扫全站 `[data-i18n]` 的渲染结果，禁止匹配 `^[a-z_]+\.[a-z_.]+$`**
（这类正则要剥注释，`assertions-must-ignore-comments` 记的正是这个坑）。

### 4. `window.PM_I18N` 从未定义（12 处调用）

`static/i18n.js:237` 导出的是 `window.I18n`，**全仓没有任何一处赋值给
`window.PM_I18N`**（只有 `PM_I18N_ZH_CN` 等三个**字典**）。受影响：
`home.js:32,33,47`、`net-status.js:58-62`、`pwa.js:26-30`、`toast.js:47-52` ——
共 12 处调用，这 4 个文件的 `t()` 全部落进硬编码中文兜底。

> ⚠️ **影响面要说准，不要夸大。** 实测首页 `/home`：80 个 `[data-i18n]` 元素里
> **只有 2 个没翻**，8 张场景卡标题**全部正确翻译成英文**。
> 所以这不是「首页整页中文」，而是「JS 动态渲染的那部分文案 + 断网横幅 + PWA 安装提示
> + toast 约 15 条」不翻译。

> ⚠️ **修它之前必须先修另一处**：`toast.js:53` 写的是 `if (v && v !== key) return key;`
> —— **应是 `return v`**。全项目另有 **5** 个语义完全相同的 i18n 包装函数
> （`dashboard.js:52` / `net-status.js:63` / `freshness.js:134` / `health-summary.js:97` /
> `pwa.js:31`）**全部是 `return v`**，只有 `toast.js:53` 是 `return key`。
> 现在被问题 4 掩盖着（`PM_I18N` 不存在，整个 if 块不进）；一旦修好问题 4，
> **所有带 i18n 的 toast 会立刻退化成显示 key 字面量**。两处必须同一个 commit 改。

### 5. freshness 时效条在 3 个页面上从未渲染过

| 页面 | 容器 | 脚本 | 调用 | 后果 |
|---|---|---|---|---|
| `settings.html` | ❌ 无 | ✅ 引了 `freshness.js` | — | `freshness.js:280` 提前 return，但 `boot()` 仍在跑，**每 60 秒空转一次调度** |
| `portfolio.html` | ❌ 无 | ❌ 无 | 2 处 `FreshnessBar.load()` | **双重失效**：守卫 `window.FreshnessBar &&` 直接跳过，无声 |
| `trades.html` | ❌ 无 | ❌ 无 | 2 处 `FreshnessBar.load()` | 同上 |

`portfolio.html:632` 的注释明写「同步拉 freshness」，调用在 `:636-637`，说明本意是要显示的 ——
守卫写法把「缺脚本」变成了无声跳过而不是报错。

**修法**：要么补齐容器 + 脚本，要么**删掉那 4 处误导性调用**（页面本来就没这个需求）。
倾向后者：这三页不是数据时效的重点页。

---

## §二 P1 · 门禁健康度

> 门禁坏了比没门禁更坏 —— 它让人以为有保护。以下 4 处**本轮实测确认**。

### 6. `check_v084.mjs` / `check_v084_interactive.mjs` —— 100% 失败

断言 `#statusPanel` 内存在 `#freshnessInline`（`check_v084.mjs:79`），
但 V0.84 已把它合并进状态条，现存的 id 是 `#homeFreshness`（home.html:240）/
`#freshnessBar`（news.html:133）。**两个门禁从合并那天起就一直红**，没人修也没人拦。

**修法**：断言改到现行 DOM 结构。

### 7. `_verify_mobile.mjs`「打开时搜索框自动聚焦」—— flaky（3 跑 2 红 1 绿）

```
run 1: 结果：32 passed, 1 failed
run 2: 结果：32 passed, 1 failed
run 3: 结果：33 passed, 0 failed
```

在断言前插**一行 `console.log`** 后连跑变 `33 passed, 0 failed` —— 典型的时序竞态。

**功能本身是好的**（单独实测：`open()` 后 `document.activeElement` 确实落到了
`.pm-cmd-input`，`same: true`）。`command-palette.js:403` 用
`setTimeout(focus, 30)`，而门禁固定等 350ms。

**修法**：断言改成**轮询等待**（`waitForFunction` 最多 1s）而不是固定 `setTimeout`。
顺带：`_verify_mobile` 在并发跑多个 puppeteer 门禁时会因 Chrome 资源抢占**整个崩掉、
一条 `结果：` 都不输出** —— 门禁串行跑，别并发。

### 8. `_verify_sw_update.mjs` —— 没有通过计数，无法判红

只 dump 一坨原始 JSON（`chipText` / `hasScore` / `hasAnyScoreField`），退出码 0，
**不打印 `结果：N passed`，也不产出 ✗**。按「崩的门禁不是门禁」的纪律，
**这个脚本目前不算门禁**。要么补断言与计数，要么改名 `_diag_*` 明确它是诊断脚本。

### 9. `test_send_message_stream_error_event_yields_error` —— 跨 loop fixture

```
RuntimeError('<asyncio.locks.Event object at ...> is bound to a different event loop')
```

**已确认与本次改动无关**：`git stash` 后同一组合跑同样失败（19 passed / 1 failed → 24 passed / 1 failed，
新增的 5 条全过）。属于记忆里那条既有 conftest 测试隔离缺陷的同一类。
**修法**：fixture 的 event loop 作用域对齐（`asyncio_default_fixture_loop_scope` 或改
`pytest-asyncio` 的 loop 策略），修完整个 `tests/test_api` 组合应该能全绿。

---

## §三 P2 · 战略项（原 roadmap §2.2 / §2.3，至今未交付）

### 10. 阈值口径可覆盖（价值最高）

grep 确认 `ThresholdConfig` / `threshold_config` / `/settings/thresholds` **全都不存在**。
roadmap §2.2 已经把问题清单列得很准（7 类硬编码参数、20+ 消费点、
`tests/test_services/test_thresholds.py` 把现有值锁死）。风险评级 🔴 中高是对的 ——
**必须逐服务替换 + 每服务单独回归，不能批量正则替换**。

建议在 P0 修完之后做：阈值错了用户**完全看不见**，而权重错了至少还能对比预览 ——
先解决更隐蔽的那一类。

### 11. K 项 · 多市场独立校准

`parameter-evaluation.md` 的 11 项里**唯一未交付**的一项。前置是第 10 项。

---

## §四 P3 · 文档收敛

- [roadmap.md](roadmap.md) 头部基线 / 当前焦点已陈旧 16 个版本；
  §2.2 与 V0.111.0 实际交付内容不符。**要么按现状重写 §0/§2，要么在本文件里标注
  它是历史档案**（本文开头已标注，但 roadmap.md 自己还不知道）。
- `docs/releases/index.md` 的能力表需要给 V0.111.1→V0.116.0 补登记（本次只补了 V0.116.0）。

---

## §五 建议排期

| 版本 | 内容 | 理由 |
|---|---|---|
| **V0.117.0** | **§一 全部 5 项 + §二 全部 4 项** | 每一项都已定位到行、改动小、互相耦合少。**更重要的是：门禁坏了就没法验证后面任何东西** —— 4 个坏门禁意味着当前所有「全绿」的结论都缺 4 块证据 |
| **V0.118.0** | §三-10 阈值可覆盖 | 价值最高的战略项 |
| **V0.119.0** | §三-11 K 项多市场独立校准 | 11 项评估需求里唯一未交付的 |

### 常态化：把门禁健康度纳入发版流程

每次发版**跑全量门禁并逐条记录通过计数**，任何长期红的门禁要么修、要么进**显式豁免清单
并写明失效条件**（豁免清单不加失效条件就会自我腐化 —— 已经腐化过一次：
`check_v084` 就是因为「没人看」而烂掉的）。

**判据统一**：门禁必须输出 `结果：N passed`；没输出就不是门禁。

---

## §六 已确认无问题的部分（避免下次重复排查）

> 本节分两类：**「本轮我亲自复核过」**（下面第 1 条）可以直接引用；
> 其余是本轮静态排查的产出、我抽查过但没有逐条复现的结论，**引用前请自行复核**。

- **5 个 AI tool 全部只读**（本轮亲自复核：`grep` 全文件无 `.insert()` / `.update()` /
  `.create()` / `.delete()` 等写库调用，5 个工具名全是 `get_*` 前缀） —— `services/llm/tools.py` 里 5 个全是 `get_*` 前缀
  （`get_market_overview` / `get_scoring_summary` / `get_user_portfolio` /
  `get_warning_summary` / `get_etf_recent_flows`），全文件无 `.insert()` / `.update()` /
  `.create()` / `.delete()` 等写库调用。
- **跨文件调用不存在的导出：0 处** —— 枚举全部 26 个 `window.*` 导出（36 个成员）
  逐个比对所有 `Xxx.yyy(` 调用点，零缺失。
- **DOM id 引用不匹配：仅 freshness 三页那 5 处**（见 §一-5），其余全部命中真实 id。
- **`addEventListener` 绑到不存在的 id：0 处** —— 31 处无守卫的绑定逐一核对，全部命中。
- **模板字符串字段名** —— 对照后端 Pydantic schema 核过 17 个文件，
  仅 `silver.js:498`（`data.index.method` 应为 `composed_by`）与
  `silver.js:526`（`news.summary` 已从后端移除）两处死字段，**且都有兜底分支、用户无感**。

---

## §附 · 本轮怎么查的（方法可复用）

1. **先复现再下结论**。每一条都写了「实测判据」，写不出来的就不写进本文。
2. **子代理的结论要自己复核**。一次静态排查给出「首页整页仍是简体中文」的说法，
   实跑发现首页 80 个 `data-i18n` 只漏 2 个、8 张场景卡全部正确翻译 ——
   **夸大 5 倍以上**。另一个子代理把 `/` 当成首页，实测 `/` 是 307 跳 `trend.html`，
   真正的首页是 `/home`。
3. **「0 个失败断言」不等于通过**。批量跑门禁时 12 个脚本里 7 个「失败断言=0」，
   实际是并发跑导致 Chrome 抢占、**一个都没输出通过计数**。必须逐个串行复跑。