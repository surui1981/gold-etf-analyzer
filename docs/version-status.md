# 应用版本状态（单一真源）

> **基线：V0.121.1** ｜ **最近更新**：2026-11-06 ｜ **状态**：一致，无漂移**
>
> 这份文档回答一个问题：**「这个应用现在到底是哪个版本？」**
> 答案散落在 6 个地方（4 处代码版本号 + CHANGELOG + git tag + release notes），
> 历史上它们互相矛盾过。本文档把结论收在一处，并把每个结论的**验证方式**写出来 ——
> 你可以自己跑命令复核，不必相信本文。

## 一句话结论

**当前版本 = 0.121.1**，代码里 4 处版本号完全一致，运行中的服务也报这个版本。
**V0.117.0 是「规划中」，一行代码都还没写**（它是改进方向记录，不是交付）。

---

## 一、当前版本

| 位置 | 文件 | 值 | 谁读它 |
|---|---|---|---|
| 运行时真源 | [src/app/__init__.py](../src/app/__init__.py) `__version__` | `0.121.1` | FastAPI `version=` → `/openapi.json` 的 `info.version` |
| 包元数据 | [pyproject.toml](../pyproject.toml) `[project].version` | `0.121.1` | `pip` / `uv` 装包 |
| 锁文件 | [uv.lock](../uv.lock) `package.gold-etf-analyzer` | `0.121.1` | `uv sync --frozen`（CI） |
| PWA 缓存 | [static/sw.js](../static/sw.js) `const VERSION` | `v0.121.1` | Service Worker 缓存名 `gold-shell-*` / `gold-runtime-*` |

**运行中验证**（主入口 `192.168.0.204:8888`）：

```
GET /openapi.json  →  info.version = 0.121.1
GET /              →  307 → /static/trend.html → 200
```

### 为什么这 4 处必须一样

| 漏同步的后果 | 实测过的现象 |
|---|---|
| `sw.js` 落后 | 浏览器**不重装 SW** ⇒ 不清缓存 ⇒ 「HTML 新 + JS 旧」错配（V0.100.1 home.html 今日要闻不显示标题） |
| `uv.lock` 落后 | CI 的 `uv sync --frozen` 直接失败（lockfile 与 pyproject 不一致） |
| `pyproject.toml` 落后 | 装出来的包版本号是错的，`pip show` 与运行时对不上 |

前两条**有门禁管**（`check_pwa_assets.py` 查 `__init__.py` ↔ `sw.js`；
CI 的 `uv sync --frozen` 查 `pyproject.toml` ↔ `uv.lock`），
但 2026-10-24 之前**本地跑任何门禁都发现不了 `uv.lock` 漂移** ——
所以新增了 `scripts/check_version_sync.py`（见下）。

---

## 二、版本状态矩阵

四个来源对「有哪些版本」的覆盖并不一致 —— **这是正常的**，
因为它们回答的是不同问题。但差异必须**已知且可查**。

| 来源 | 数量 | 回答什么问题 |
|---|---|---|
| `__version__` bump 史 | **78** 个版本 | 哪些版本真正 bump 过版本号（= 发过版） |
| [CHANGELOG.md](../CHANGELOG.md) | **53** 段 / 52 个唯一版本号 | 发版史的**人读**记录 |
| [docs/releases/](releases/) | **7** 份**里程碑文档**（V0.120.5 起替代逐版 notes） | 阶段的演进脉络（根因 / 修法 / 验证 / 教训） |
| git tag | **114** 个（本地 = 远端，已同步；含 `v0.121.0`） | 按版本 checkout 的锚点 |

> ⚠️ **上表 4 个计数是 V0.121.0 逐项实测改写的** —— 上一版写的是
> 「74 / 49 段·48 个 / 58 份 / 113 个」，其中 **3 个都偏低**
> （实测 bump 史 78 而非 74、CHANGELOG 53 段而非 49、releases 已合并为 7 份而非 58 份）。
> ⇒ 这正是 §3.3 说的那类「**内容腐化**」：**门禁只校验版本号，不校验计数**，
> 所以计数腐化不会报红，只能靠人工复核 —— 本轮顺手订正。
>
> **53 段 ≠ 52 个唯一版本号**：`V0.97.2` 有 2 段 —— `## [V0.97.2 hotfix]` 在前、
> `## [V0.97.2]` 在后。hotfix **没有 bump 版本号**（该段自己写明了这点），
> 所以它是同一个版本号的第 2 段，不是重复 bug。门禁 `check_version_sync.py`
> 把 hotfix 后缀排在同版本基础段**之上**，因此这段顺序是合法的。
>
> **114 个 tag = 113 个版本号 tag + 1 个 `v0.97.2-hotfix`**（后者不是版本号形态的 tag，
> 但确实是真实存在的发布锚点）。**tag 本地与远端一致**：
> 逐个比对 `git rev-parse <tag>^{commit}` 与 `git ls-remote --tags` 的 `^{}` 行，
> **指向不一致的 0 个**。其中 annotated **108** / lightweight **6**，两侧分布相同。
> （⚠️ 上一版此处写的「annotated 102 / lightweight 7」**两个数都差 1** —— lightweight 实为 6 个
> （v0.51.0 / v0.51.1 / v0.64.0 / v0.65.0 / v0.66.0 / v0.82.0，见本文件下方那张表）。
> 本版按 `git for-each-ref --format='%(objecttype)'` **实测**改写。）
> ⚠️ **annotated tag 在 `ls-remote` 里占两行** —— `refs/tags/v0.120.1` 是 **tag 对象**
> 的 SHA，`refs/tags/v0.120.1^{}` 才是它指向的 **commit** SHA；统计数量时
> 必须把 `^{}` 行去掉再数，否则 114 个 tag 会数成 222 行左右（实测 `ls-remote --tags` 原始行数
> = 220 + 2 = 222）。

> **本轮把 `## [Unreleased]` 段转正成了 `## [V0.116.1]`** —— 起因是 CI 修绿这轮
> **改了 `static/*.html` 与 `static/i18n/*.js`**（`ask.html` / `weights.html` / 3 个 i18n 文件），
> 按 V0.100.1 规则**必须 bump `sw.js` VERSION** ⇒ 应用代码变了 ⇒ 不能留在 Unreleased。
> 门禁 `check_version_sync.py` 只匹配 `## [V...]`，**不把 Unreleased 当版本段** ——
> 所以 Unreleased 存在不会让「CHANGELOG 最新版本段 == 应用版本」这条断言失真。

### 已知且**故意**保留的缺口

> ⚠️ 下表是 **V0.121.0 逐项实测重算**的（脚本对比「tag 集合 / CHANGELOG 段集合 /
> `__version__` bump 史集合」三个集合的两两差集），
> 口径随 V0.120.5 的文档收敛而变过：**逐版 release notes 已移出仓库**（改由 git tag 承载），
> 所以「有没有 release notes」不再是可查的仓库内事实 —— 缺口改用**可查的三集合**来表述。

| 缺口 | 数量 | 为什么保留 |
|---|---|---|
| 有 tag 但 CHANGELOG 无段 | 63 | V0.10.0~V0.98.0 的早期版本只打了 tag，没进 CHANGELOG（CHANGELOG 体系本身是后建的）。**老版本不追溯补录**，以 git 历史为准 |
| 有 CHANGELOG 段但无 tag | 2 | V0.101.0 / V0.102.0 —— 这两个是**从未 bump 过版本号**的功能批次标签（代码已随 V0.103.0 上线），刻意不占版本号 |
| 有 `__version__` bump 但 CHANGELOG 无段 | 32 | V0.74.0~V0.98.0 的中段版本（bump 了版本号但没写 CHANGELOG 段）。同上，**不追溯补录** |

> **V0.117.0 的 release notes 存在但无 CHANGELOG 段 / 无 `__version__` bump / 无 tag ——
> 这是正确的**。它是**规划文档**，还没发版。三者都缺席 = 状态自洽。
> 详见 [releases/milestones/m5-four-faces-and-ai-usability-v0.116-v0.120.md](releases/milestones/m5-four-faces-and-ai-usability-v0.116-v0.120.md)。

---

## 三、当前在途：V0.117.0（规划中，0% 实施）

| 项 | 状态 |
|---|---|
| 方向文档 | ✅ [releases/milestones/m5-four-faces-and-ai-usability-v0.116-v0.120.md](releases/milestones/m5-four-faces-and-ai-usability-v0.116-v0.120.md)（标 `planning · 未实施`） |
| 完整推理 | ✅ [roadmap.md](roadmap.md) |
| 缺陷清单 | ✅ [roadmap.md](roadmap.md) |
| **代码** | ❌ 一行都没有 |
| `__version__` | ❌ 仍是 `0.118.0`（V0.117.0 是方向文档，不 bump） |
| CHANGELOG 段 | ❌ 无（未发版） |
| git tag | ❌ 无（未发版） |

**判据**：文件头写着 `planning · 未实施` 的 release notes = 方向记录，不是交付记录。
[releases/index.md](releases/index.md) 里对应行带 📋。

### 另一条线：CHANGELOG 的 `## [Unreleased]`（已转正为 V0.116.1）

| 项 | 状态 |
|---|---|
| 内容 | ✅ 版本状态整合（发版史对账 / 单一真源文档 / 两道新门禁 / tag 补推与核对）**+ CI 修绿**（ruff ×2 + 10 个预存 pytest 失败） |
| `__version__` | ✅ 已 bump 到 `0.116.1`（4 处同步） |
| git tag | ✅ `v0.116.1` |

> **原本计划不改版本号**：当时那轮只改**记录与门禁**、不动应用代码，
> 按 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/) 的约定该留在 `[Unreleased]`。
> 后来的 CI 修绿这轮**改了 `static/*.html` 与 `static/i18n/*.js`** ⇒ 按 V0.100.1 必须 bump sw.js
> ⇒ 应用代码变了 ⇒ 整段转正为 `## [V0.116.1]`。
> （仓库里有同样的先例：`V0.97.2 hotfix` 段明确写了「不 bump 版本号」。）

### 更早一轮：V0.116.2（2026-10-25）

同样的规则、同样的判据，又触发了一次**真实发版**：

| 项 | 状态 |
|---|---|
| 内容 | ✅ 3 处静默失效的前端缺陷（`admin/users.html` 整页渲染成 i18n 键字面量 / `/ask` 状态条带 `hidden` 永不可见 / dismiss 勾选框没接上 `warning.js`）+ 2 处门禁缺陷（i18n 门禁只扫顶层目录 / 浏览器门禁缺端到端断言） |
| `__version__` | ✅ 已 bump 到 `0.116.2`（4 处同步） |
| git tag | ✅ `v0.116.2` |

> 触发条件同样是**改了 `static/*.html`**（`ask.html` / `admin/users.html`）
> ⇒ 按 V0.100.1 必须 bump `sw.js` ⇒ 应用代码变了 ⇒ 不能留在 `[Unreleased]`。
> 详见 [releases/milestones/m5-four-faces-and-ai-usability-v0.116-v0.120.md](releases/milestones/m5-four-faces-and-ai-usability-v0.116-v0.120.md)。
>
> 📌 **这轮还留了一件没做的事**：生产库 `users` 表缺 `role` 列
> ⇒ `GET /api/v1/admin/users` / `POST .../reset-password` / `GET /api/v1/auth/me` 三个端点返 500。
> 修它要**改生产 SQLite 库** ⇒ 留给用户决定，本轮只报告不改。
> 详见 [releases/milestones/m5-four-faces-and-ai-usability-v0.116-v0.120.md §5](releases/milestones/m5-four-faces-and-ai-usability-v0.116-v0.120.md)。

### 更早一轮：V0.116.3（2026-10-25）

| 项 | 状态 |
|---|---|
| 内容 | ✅ 命令面板自动聚焦被 V0.113.0 的 `visibility` 过渡打没了（`focus()` 被浏览器**静默丢弃**）+ 聚焦断言从 flaky 改成**确定性**判据（`transition-delay` 钉住可见时刻） |
| `__version__` | ✅ 已 bump 到 `0.116.3`（4 处同步） |
| git tag | ✅ `v0.116.3` |

> 触发条件同样是**改了 `static/*.js`**（`command-palette.js`）
> ⇒ 按 V0.100.1 必须 bump `sw.js` ⇒ 应用代码变了 ⇒ 不能留在 `[Unreleased]`。
> 详见 [releases/milestones/m5-four-faces-and-ai-usability-v0.116-v0.120.md](releases/milestones/m5-four-faces-and-ai-usability-v0.116-v0.120.md)。
>
> 📌 **这轮的一条元教训**：判据本身也会骗人 —— 我第一版判据用
> `transition-duration` 拉长过渡，回退实现后门禁**连报两次「全绿」**；
> 而 `visibility` 是离散插值（第一帧就翻），加长 duration **根本不管用**，
> 正确杠杆是 `transition-delay`。**断言没被证伪过，就不算数。**

### 更早一轮：V0.116.4（2026-10-25）

| 项 | 状态 |
|---|---|
| 内容 | ✅ 命令面板输入「决策」落到趋势追踪（场景落地页被第一个子页顶掉）+ 命中分析 Tab 异常路径不再整块崩 + 门禁不再把 429 限流误判成 JS 错误 |
| `__version__` | ✅ 已 bump 到 `0.116.4`（4 处同步） |
| git tag | ✅ `v0.116.4` |

> 起因是**用户反馈**：「点击决策的时候看到的页面是趋势追踪」。
> 但实测发现**顶栏 / 首页场景卡 / 手机抽屉三处「决策」一直是对的**（都指向 `/scoring`），
> 全站 60+ 个「决策」链接没有一个指向 trend —— 唯一的例外是**命令面板**。
>
> 触发条件是**改了 `static/*.js`**（`command-palette.js` + `scoring.js`）
> ⇒ 按 V0.100.1 必须 bump `sw.js` ⇒ 应用代码变了 ⇒ 不能留在 `[Unreleased]`。
> 详见 [releases/milestones/m5-four-faces-and-ai-usability-v0.116-v0.120.md](releases/milestones/m5-four-faces-and-ai-usability-v0.116-v0.120.md)。
>
> 📌 **这轮的一条教训**：同一个入口（进「决策」）在实现上有 **4 条独立路径**
> —— 顶栏 / 场景卡 / 抽屉 / 面板。前三条共用 `SCENES.path`（同源，不会漂移），
> 面板是**另外派生**的 ⇒ 漂移就发生在派生那一层。
> **同源派生的东西要连「顺序」一起同源**，不只是「集合」同源 ——
> 而面板里「第一条命中」是**有语义的**（默认选中 + 回车）。

### 再上一轮：V0.118.1（2026-10-26）

| 项 | 状态 |
|---|---|
| 内容 | ✅ 宏观因子新增「末次落库」兜底层（上游源挂时退回**真实读数**而不是 2026-08-28 的内置常量，`dxy` 96.5 → 101.81）；`MacroFactorOut` 新增 `tier` 字段让降级可辨认；权重页「当前生效」列的滞后提示覆盖**所有**源（原先只对手动值生效）；顺带修掉 `/ask` 的 `get_market_overview` 工具**每次调用都失败**这个线上真 bug（`TrendService` 第 2 位位置参数误传 `MarketDataRepository`） |
| `__version__` | ✅ 已 bump 到 `0.118.1`（4 处同步） |
| git tag | ✅ `v0.118.1` |

> 起因是**用户诉求**：「宏观因子手动校准的数值没有跟踪关键参数更新来更新，
> 修复这个 BUG」。
>
> 实测触发条件是**本机 DNS 解析不了境外域名**（路由器只解析国内域名，
> 且间歇性发生）⇒ 3 个宏观自动源同时不可用 ⇒ 全部退回 2026-08-28 的常量，
> 而 `daily_macro_factors` 里明明存着前几轮抓到的真值。
> 详见 [releases/milestones/m5-four-faces-and-ai-usability-v0.116-v0.120.md](releases/milestones/m5-four-faces-and-ai-usability-v0.116-v0.120.md)。

### 本轮：V0.121.1（2026-11-06 发版）

| 项 | 状态 |
|---|---|
| 内容 | ✅ **可信度 P0 批次**（「把显示假的逐条修回来」三批计划的**第 2 批**）。① **`?days=` 参数此前完全失效** —— `served_cache` 的 key 是 `(target, interval, on_date)`，**没有 `days`** ⇒ `?days=30/60/120` 返回完全相同的结果（趋势页 52W 按钮画的是 12 周）⇒ key 加 `days` 维度，`invalidate` 仍按 `(target, interval)` 匹配以覆盖所有 days 变体。② **命中分析「上涨天数」恒为 0** —— 治本（新增 `price_direction VARCHAR(8)` 列 + 迁移 `t2u3v4w5x6y` + 停掉消息面方向对 `direction` 列的覆写 + 聚合新增 `known_days`）；唯一可信的源是 `gold_price_daily.change_pct` 的符号，**不用快照 close 兜底**（实测两源方向只有 44% 一致且快照 close 滞后一天 ⇒ 系统性错位比留空更坏）。③ **64% 历史行带伪造消息面 50 分** —— 治源头（`daily_snapshots.news_index` 改可空、`services/snapshot.py` 不再兜底 50、宽表 ETL 不再继承快照的 `news_index`、消费侧 `news_w > 0` 且为 NULL 时**跳过该日**）+ 幂等回填 `scripts/backfill_news_truth.py`（**清掉 26 个伪造命中**、29 行被消息面方向污染的 `direction`，8 行用户真打的 50 分全部保留）。④ **`/headlines` 渲染 i18n key 字面量** —— 字典里的 key 是复数（`time.minutes_ago` 等）而代码写的是单数（`time.min_ago` 等）⇒ 三语字典里都没有 ⇒ `I18n.t()` 返回 key 字面量；顺带修掉「`(I18n.t(key)) || "分钟前"` 永远不触发」的兜底写法；门禁严格清单纳入 `"time."` 并**默认输出清单外缺失数 + 位置**。详见 [releases/milestones/m6-truthful-signals-v0.121.md](releases/milestones/m6-truthful-signals-v0.121.md) |
| `__version__` | ✅ 已 bump 到 `0.121.1`（4 处同步：`__init__.py` / `pyproject.toml` / `uv.lock` / `sw.js`） |
| 迁移 | ✅ `t2u3v4w5x6y`（`scoring_daily_wide` 增 `price_direction` + `daily_snapshots.news_index` 改可空）—— 先在副本库上验过 upgrade / downgrade / 往返，再上生产 |
| 生产库回填 | ✅ 快照 **49 行**修正（32 → NULL / 17 → 当日聚合值）+ 宽表 ETL 重跑 **61/61 天**；幂等自查二次规划 **0 行** |

> **反向验证**（每条修复都做过「撤销 ⇒ 变红 ⇒ 恢复 ⇒ 变绿」）：
> P0-1 monkeypatch 把 `_key` 换回 3 元组 ⇒ **3/3 变红** ⇒ 恢复；
> P0-2 让 `price_direction` 回退到 `direction` ⇒ **3 个测试变红** ⇒ 恢复；
> P0-2 恢复消息面方向覆写 ⇒ **1 个测试变红**（`direction` 又出现 bullish/bearish/neutral）⇒ 恢复；
> P0-3 把 `snapshot.py` 改回 `else 50.0` ⇒ **1 个测试变红**（「未打分的消息面被写成了 50.0」）⇒ 恢复；
> P0-4 把 3 个 i18n key 改回错的 ⇒ **门禁 9 missing / 499 in-scope** ⇒ 恢复 ⇒ **0 missing**。

### 上一轮：V0.121.0（2026-11-06 发版）

| 项 | 状态 |
|---|---|
| 内容 | ✅ **门禁自愈批次**（「把显示假的逐条修回来」三批计划的**第 1 批**）。① `scripts/check_v084.mjs` 从 **0/27 全红**修成 **27/27** —— 根因是断言查的 `#freshnessInline` 已被 V0.85.0 换成 `#healthSummary`；修法是断言**当前真实结构** + 加一条**反向断言**（旧 mount 点不得复活）。② `scripts/_verify_sw_update.mjs` 从 **0 条断言**（永远绿）修成 **8 条** —— 补「SW 已接管 / 版本一致 / **缓存里没有陈旧副本**（逐字节比对）/ activate 后旧缓存已清 / 首页要闻卡骨架屏已消失」。踩中两个坑：Service Worker 只在**安全上下文**可用（LAN IP 下 `navigator.serviceWorker` 是 `undefined`，脚本直接崩 ⇒ 加显式守卫 + 退出码 1）；puppeteer 默认每次都是**全新临时 profile** ⇒ SW 每次重新 install ⇒「缓存正文 == 网络正文」**永远成立** ⇒ 陈旧检测**结构性失效** ⇒ 改用**持久化 `userDataDir`**。③ `scripts/_verify_mobile.mjs` 的关闭后可见性断言从「等固定 350ms」改成**轮询到 `visibility === "hidden"`**。④ **G3/G4 的 roadmap 记录是过期的** —— 聚焦断言早已由 V0.116.3 修好、跨 event loop 早已由 `tests/conftest.py::_reset_sse_app_status` 修好 ⇒ 只做**记录订正**，不假装又修一遍。⑤ 新建**第 7 份里程碑文档 M6 · 可信度修复（V0.121）**。**零业务逻辑改动**（只动 `scripts/` 下 3 个门禁） |
| `__version__` | ✅ 已 bump 到 `0.121.0`（4 处同步：`__init__.py` / `pyproject.toml` / `uv.lock` / `sw.js`） |
| git tag | ✅ `v0.121.0`（annotated；已推送，`ls-remote` 两行分别是 tag 对象与 commit） |

> **反向验证**（每条修复都做过「撤销 ⇒ 变红 ⇒ 恢复 ⇒ 变绿」）：
> G1 把 `static/trend.html` 的 `id="healthSummary"` 改名 ⇒ **3/27 变红**（正好是 trend × 3 语）
> ⇒ 恢复；
> G2 往 `static/home.js` 追加一行 ⇒ **7 passed / 1 failed**，
> 报 `陈旧条目：shell:/static/home.js` ⇒ 恢复。
> 详见 [releases/milestones/m6-truthful-signals-v0.121.md](releases/milestones/m6-truthful-signals-v0.121.md)。

### 上一轮：V0.120.5（2026-11-05 发版）

| 项 | 状态 |
|---|---|
| 内容 | ✅ **文档收敛** —— 用户要求「把这些小版本合并成几个关键的里程碑版本，去掉测试和说明性的重复文档」。① **60 份逐版 release notes → 6 份里程碑文档**（`docs/releases/milestones/m0`–`m5`，按能力主题切分；逐版原文留在 git 历史，tag 与原文件名同名）；② **6 份互相重叠、基线落后 16–43 个版本的规划文档 → 1 份 `docs/roadmap.md`**，且**逐条实测复核**每一条在 V0.120.4 上的真实状态（已修的挪进「已完成」，不再当待办 —— 复核发现 6 条 P0 仍然存在：`days` 参数完全失效 / 上涨日数恒 0 / 64% 历史行带伪造消息面 50 分 / `time.hour_ago` 字面量外泄 / 权重滑块是装饰 / AI token 统计失真）；③ **5 份分析报告（基线 V0.74–V0.77）→ 1 份 `docs/reports/历史评估汇总-202609.md`**（补「当时的建议 → 实际落地版本」对照表）；④ **门禁契约跟着改**：`check_version_sync.py` 从「`docs/releases/v<版本>.md` 存在」改成「当前版本号出现在某份里程碑文档里」且该里程碑须在 `releases/index.md` 登记；⑤ 锚点测试夹具从「真实文档」改成 `tmp_path` 现场造。**规模**：文档 87 → 24 份、链接 413 → 355 条、声明 352 → 224 处 |
| `__version__` | ✅ 已 bump 到 `0.120.5`（4 处同步：`__init__.py` / `pyproject.toml` / `uv.lock` / `sw.js`） |
| git tag | ✅ `v0.120.5`（annotated；tag 对象 `baa3727` → commit `1885041`；已推送，`ls-remote` 两行分别是 tag 对象与 commit） |

### 本轮：V0.120.4（2026-11-04 发版）

| 项 | 状态 |
|---|---|
| 内容 | ✅ **首页 hero 右侧新增「综合评估」结论块** —— 用户报「首页没有显示综合评估指数和说明」：首页此前**一个评分都没有**（hero 只有金价/时效/AI 三个 chip，8 张场景卡是纯导航磁贴，贵金属三卡显示的是**价格涨跌幅**不是评分），而 hero **右半边（约 600px）一直空着**。⇒ hero 改两栏，右栏放结论块：大数字（综合趋势评估指数 0-100）+ 等级徽章 + 一句话说明（含加权公式）+ **4 面分数条**（技术/宏观/消息/资金流 + 生效权重 + 方向箭头）+ **各面因子明细**（默认折叠，每面按 \|contribution\| 取前 3）+ 脚注「口径：纽约金 COMEX · 快照 HH:MM」。⚡ **零新增网络请求**：`home.js` 早就在拉 `/api/v1/market/gold/trend`（只用了 `points[].close`），**`response.index` 整块已经在手只是没用**。🎯 口径钉死 `target=ny`（与趋势页「实时评估摘要」同源；趋势页 synthesis-card 用 `etf`，两个数字不打架）。🐛 顺带修 i18n 静默失效：`home.js` 的 `t()` 读 `window.PM_I18N.t`，但 `i18n.js` 导出的是 **`window.I18n`** ⇒ 首页 JS 拼的文案**一直回退中文**（en-US 下 `纽约金 XAU` 不翻译）⇒ 改读 `window.I18n.t` + 三卡抽函数 + `i18n:change` 重绘。🧪 新门禁 `_verify_home_verdict.mjs`（55 条断言）+ **4 组反向验证**（首轮反向验证抓出门禁自身的漏洞：公式权重没被断言到 ⇒ 已补）。详见 [releases/milestones/m5-four-faces-and-ai-usability-v0.116-v0.120.md](releases/milestones/m5-four-faces-and-ai-usability-v0.116-v0.120.md) |
| `__version__` | ✅ 已 bump 到 `0.120.4`（4 处同步：`__init__.py` / `pyproject.toml` / `uv.lock` / `sw.js`） |
| git tag | ✅ `v0.120.4`（annotated；tag 对象 `bc71b643` → commit `8317136e`；已推送，`ls-remote` 两行分别是 tag 对象与 commit） |

### 本轮：V0.120.3（2026-11-03 发版）

| 项 | 状态 |
|---|---|
| 内容 | ✅ **修 `/ask` 回复不可读** —— 用户报「对话给出的格式 不方便阅读」，原文含 `]<]minimax[>[<invoke` 与 `{"name":"get_market_data",…}`：**这不是排版丑，是上游把原生 tool-call 协议当正文吐了出来**。4 层根因：①**请求侧缺 assistant(tool_use) 回合**（Anthropic 协议要求配对；原实现只 append 了 `user(tool_result)` ⇒ 上游收到畸形会话；**直连 A/B：缺 ⇒ HTTP 400，补 ⇒ HTTP 200 + 完整 Markdown**；同步 + SSE 两处都补，多个 tool_result 必须在**同一条** user 消息里）；②**库里已有 10 条污染行** ⇒ 读时清洗（新 `src/app/utils/protocol_strip.py`；历史 + 新行同时生效、**不写生产库不用迁移**；⚠️ 只清洗 assistant —— tool 消息正文本身就是 JSON，清洗会毁掉工具数据）；③**工具层真缺陷**（`get_user_portfolio` 调错类：`equity_curve`/`performance` 在 `PortfolioAnalyticsService` 上不在 `PositionService` 上 ⇒ 线上 100% 报错；`get_scoring_summary` 强制要 from/to ⇒ 模型漏参就报错 ⇒ 改缺省「近 30 天」+ 报告实际区间；system prompt 加规则 9「今天是几号」）；④**正文为空无兜底** ⇒ 加安全网（整轮无正文 ⇒ 补一次不带工具的调用强制作答，纯文本传递零协议风险）。**历史回放同样修**（`_to_claude_messages` 按回合重建 tool_use/tool_result，1:1 用原生块、多 tool 退化成纯文本）。**教训**：「桩藏住被替换的调用方」第 3 次踩 ⇒ 通用解法：用 `ast` 把「代码调的方法」与「**真实类**的方法集」对账，不依赖桩。详见 [releases/milestones/m5-four-faces-and-ai-usability-v0.116-v0.120.md](releases/milestones/m5-four-faces-and-ai-usability-v0.116-v0.120.md) |
| `__version__` | ✅ 已 bump 到 `0.120.3`（4 处同步：`__init__.py` / `pyproject.toml` / `uv.lock` / `sw.js`） |
| git tag | ✅ `v0.120.3`（annotated；tag 对象 `fea0084c` → commit `8626e8e4`；已推送，`ls-remote` 两行分别是 tag 对象与 commit） |

### 本轮：V0.120.2（2026-11-02 发版）

| 项 | 状态 |
|---|---|
| 内容 | ✅ **修 `/ask` 页「加载对话失败：Internal Server Error」** —— `ai_messages.tool_input` 列存的是 **JSON 字符串**（`json.dumps(...)`），而 `AIMessageOut.tool_input` 对外声明是 **dict**；`from_attributes=True` 把原始字符串直接喂给 dict 校验 ⇒ `ValidationError` ⇒ **整个对话 500**（对话详情一次性返回全部消息，**一条坏消息 = 整个对话打不开**）。修法：在 schema 边界加 `mode="before"` 解码器（**落库侧是对的，错的是接口边界没解码** —— 与 `SnapshotOut.macro_detail` 完全同类，照抄它）；损坏 JSON ⇒ 置 `None` + log warning，**不兜底为 `{}`**。受影响两条路径：`GET /conversations/{id}` + 同步 `POST /messages`（前端 SSE 降级时的回退路径）；SSE 流式路径不受影响。**此前 2007 条测试全绿的原因**：mock 的 tool_use 入参是**空 dict `{}`** ⇒ `if tool_input else None` 判成 falsy ⇒ 落库 NULL ⇒ 校验不炸 —— **空入参把真缺陷藏住了**。详见 [releases/milestones/m5-four-faces-and-ai-usability-v0.116-v0.120.md](releases/milestones/m5-four-faces-and-ai-usability-v0.116-v0.120.md) |
| `__version__` | ✅ 已 bump 到 `0.120.2`（4 处同步：`__init__.py` / `pyproject.toml` / `uv.lock` / `sw.js`） |
| git tag | ✅ `v0.120.2`（annotated；tag 对象 `3f8420b1` → commit `23c7bda3`；已推送，`ls-remote` 两行分别是 tag 对象与 commit） |

### 本轮：V0.120.1（2026-10-31 发版）

| 项 | 状态 |
|---|---|
| 内容 | ✅ **拆掉资金流观测网格测试的时间炸弹** —— `_collect_etf` / `_collect_us_liquidity` / `_collect_cn_margin` 接受可选 `today` 并透传给 `week_end_days` / `fetch_us_net_liquidity_monthly`；**生产路径全部不传 ⇒ `None` → 系统日期，行为与修复前逐字相同**。测试加 `FIXED_TODAY = date(2026,10,28)` 并显式传参。起因：V0.120.0 的两个用例把「今天是 10-28」只写进注释，时钟到 10-31（周六）起锚点从 10-23 跳到 10-30 ⇒ **永久变红**（CI 在 10-29 是绿的），另有 2 条月频用例将在 11-01 变红。详见 [releases/milestones/m5-four-faces-and-ai-usability-v0.116-v0.120.md](releases/milestones/m5-four-faces-and-ai-usability-v0.116-v0.120.md) |
| `__version__` | ✅ 已 bump 到 `0.120.1`（4 处同步：`__init__.py` / `pyproject.toml` / `uv.lock` / `sw.js`） |
| git tag | ✅ `v0.120.1`（annotated；已推送，`ls-remote` 两行分别是 tag 对象与 commit） |

### 本轮：V0.120.0（2026-10-29 发版；跑批实测在 2026-10-28）

| 项 | 状态 |
|---|---|
| 内容 | ✅ 新增**第 4 个评分面「资金流面」**（6 因子 = 周 3 / 月 3：CFTC 黄金投机净多占 OI 18% / CFTC 净多 4 周变化 14% / 黄金 ETF 4 周累计净申赎 22%（**上交所官方份额**，非重建）/ 美元净流动性 4 周变化 14% / A 股融资余额月环比 16%（**负号口径**）/ M1−M2 剪刀差 16%（**负号口径**））；综合指数权重 30/40/30 → **25/35/25/15**；滚动分位**按观测节奏取窗**（周频 728 日 / 月频 1826 日）；历史回填 **482 行**（发版当天快照；每日调度续增），6 个因子全部走滚动分位；`MoneyFlowIndexOut.score` 可空（本轮无**真实观测** ⇒ 整面剔除而非记 0 分）；`LEGACY_COMBINE_3_DEFAULTS` 迁移守卫（3 键默认直落新默认 / 3 键自定义按比例缩放）；**前端口径收口** 6 处（前端原写「消息面按中性 50 参与评估（占 30% 权重）」，与后端 V0.100 起「`news_score=None` ⇒ 整面剔除」矛盾 ⇒ 改为「不参与综合指数（配置权重已剔除，其余面按有效面归一化）」，并新增 `index.face_weights_nominal` 让前端不再自己重算配置权重）；**i18n 门禁盲区**修掉（`T('key')` 本地包装器形式此前扫不到 ⇒ `syn.*` / `nsw.*` / `scoring.*` / `decision.*` 四个命名空间零覆盖 ⇒ 严格扫描 309 → **492** key）；**浏览器门禁时序竞态**修掉（结论卡 / 决策拆解各自另发 fetch，冷缓存下门禁读到空卡片 ⇒ 假红 12 条 ⇒ 改为显式等渲染完成 + 判据换成页面自己那份 payload）；**观测节奏缺陷**修掉（**3 个**因子声明的 cadence 与实际落表频率不符 ⇒ 同一周/同一月被反复写进滚动分位窗口、阈值被压平 ⇒ 周频锚 **ISO 周末** / 月频只取**已过完的月**，实时采集 + 历史回填 + 静态标定三处共用同一锚点函数，换网格时用 `--reset` 可复现重建；其中 `us_liq_net` 是「4 周变化」因子，按周采样会**重叠 3/4** ⇒ 有效样本只剩 1/4，`min_samples` 达标是假象）；**快照两列铺路**（`daily_snapshots` 加 `flow_index` / `flow_detail`）—— 回测网格今天**不动**（没有历史快照，加了会算出 0 行），但历史**从本版起开始攒**，约 1 年后方可进网格 |
| `__version__` | ✅ 已 bump 到 `0.120.0`（4 处同步） |
| git tag | ✅ `v0.120.0`（annotated；tag 对象 `73310b60` → commit `db6e2e40`；已推送，`ls-remote` 两行分别是 tag 对象与 commit） |

> 起因是**用户诉求**：「制定计划，按照资金流动流向各种市场来判断，作为一个资金流面，什么建议」
> 追加：「我们关注的是近期的资金数据，进行周 和月的关键因子。」
>
> 三处已**逐项拍板**：① 资金流面权重 = **15%**（tech 25 / macro 35 / news 25 / flow 15）；
> ② 中国两个因子取**机会成本负号口径**（值越高越利空黄金）；
> ③ 黄金 ETF 因子用 **4 周累计净申赎**（单周信噪比 ≈ 1 不可用）。
>
> 顺带修了 8 处既有缺陷：
> ① `is_dynamic_active` 靠「阈值 ≠ hardcode」反推动态 ⇒ 滚动分位与静态带**逐位相同**
> 时误报（实测 `cn_money_gap`）⇒ 改为计算器**显式记录**滚动集（`rolling_keys`）；
> ② 建表迁移 `m1n2o3p4q5r6` 漏 `primary_key=True` ⇒ 每条 ORM insert 报
> `NOT NULL constraint failed` ⇒ 补迁移 `n2o3p4q5r6a1` 重建表；
> ③ `trend.py` 丢弃分支把「消息面 pending」与「资金流面不可用」混成一句 ⇒ 拆成两句；
> ④ 前端 6 处仍在说「消息面按中性 50 参与评估（占 30% 权重）」的旧话（与后端 V0.100 起
> 的整面剔除矛盾）⇒ 改成「不参与综合指数（配置权重已剔除）」，并新增
> `face_weights_nominal` 让前端不再自己重算配置权重；
> ⑤ i18n 门禁正则只认 `I18n.t(` / `tr(` 两种形式 ⇒ `T(` 本地包装器扫不到 ⇒
> `syn.*` / `nsw.*` / `scoring.*` / `decision.*` 四个命名空间**从未进过门禁视野**
> ⇒ 补 `T(` 正则后严格扫描 309 → **492** key（反向验证：改 zh-TW 一个键 ⇒ 门禁立刻变红）；
> ⑥ 浏览器门禁 D2 段在**服务器刚重启、`served_cache` 冷**时假红（12 条「渲染 0 个面」）——
> 根因是门禁只等到了趋势页主体就断言，而结论卡 / 决策拆解**各自另发一个 fetch** ⇒
> 改为显式等渲染完成 + 判据换成页面自己那份 payload（反向验证：删掉 `FACES` 里的
> `flow` 面 ⇒ 9 条转红）；
> ⑦ **3 个因子的观测节奏与声明的 cadence 不符**（`gold_etf_flow` 声明周频，
> `cn_margin_flow` / `us_liq_net` 声明月频，观测日却随「最新数据」逐日推进）⇒ 每日 07:00 调度会把
> **同一周/同一月**反复写进滚动分位窗口（同一周值重复约 5 次 / 同月值重复约 21 次），
> 阈值被压平、样本数虚高；且「月内至今」与历史行的「月末 vs 月末」**不是同一个量** ⇒
> 修法是**按观测节奏锚定采样网格**（周频锚 ISO 周的最后一个交易日 / 月频只取已过完的月），
> 实时采集 / 历史回填 / 静态标定三处**共用同一个锚点函数**，并补 `delete_factor` +
> `--reset` 让换网格后能可复现地重建（旧网格的行不会被新网格的 upsert 覆盖 ⇒
> 两张网格会并存）。
> ⚠️ `us_liq_net` 还多一层：它的值本身是「**4 周变化**」⇒ 按周采样时相邻两次观测
> **重叠 3/4** ⇒ 名义 60 个月的位置里塞了 260 行高度重叠的样本，**有效样本只剩 1/4**
> ⇒ `min_samples` 达标是**假象**（样本数骗了自己）。改锚到月末后回到 60 行。
> 详见 [releases/milestones/m5-four-faces-and-ai-usability-v0.116-v0.120.md §4.4](releases/milestones/m5-four-faces-and-ai-usability-v0.116-v0.120.md)；
> ⑧ **非默认语言下结论卡锁死在简体**（浏览器门禁抓出）：结论卡是 `innerHTML` 拼的
> （**无 `data-i18n` 标记** ⇒ `i18n.js` 的 `apply()` 扫不到），
> 而非默认语言的字典是**动态 `<script>` 异步加载**，
> 且 `init()` 解析完语言后**从不广播 `i18n:change`**（只有手动切语言才广播）
> ⇒ 组件抢在字典之前渲染完就**永久停在默认语言**（实测：字典延迟 4s ⇒ 标题永远是简体）。
> 修法：`init()` 在**非默认语言**时广播 `i18n:change` + 暴露 `window.I18n.ready`
> （字典就绪信号）+ `loadLang()` 并发去重 + 字典全局名大小写两种都认
> （`zh-CN.js` 是 `PM_I18N_ZH_CN` 而 `zh-TW.js` 是 `PM_I18N_zh_TW`）；
> `synthesis-card.js` / `news-score-widget.js` **渲染前** `await I18n.ready`；
> 顺带修掉 `weights.html` 的 `update()` 在滑块行没画出来时 `.value` 抛异常 ⇒ **整页脚本中断**。
> 门禁同步加固：G 段等待条件改成「标题非空 **且** `data-lang` 已解析」+ 新增 G2 段做阳性对照。
>
> 另外**实测改掉了一处设计**：黄金 ETF 份额原打算用「成交量 ÷ 换手率」重建，
> 实测发现上交所有官方每日份额接口 ⇒ 重建口径整条废弃（计划里「单周信噪比 ≈ 1 不可用」
> 那个结论建立在错的源上）。

>
> 触发条件是**改了 `static/*.html` + `static/*.js`**（`weights.html` / `trend.html` /
> `silver.html` / `silver.js` / `help.js` / `i18n.js` / `synthesis-card.js` /
> `news-score-widget.js` / 3 个 i18n 字典文件）⇒ 按 V0.100.1 必须 bump `sw.js`
> ⇒ 应用代码变了 ⇒ 不能留在 `[Unreleased]`。
> 详见 [releases/milestones/m5-four-faces-and-ai-usability-v0.116-v0.120.md](releases/milestones/m5-four-faces-and-ai-usability-v0.116-v0.120.md)。

### 上一轮：V0.119.0（2026-10-27）

| 项 | 状态 |
|---|---|
| 内容 | ✅ 宏观面 **8 → 11 因子**（+`us_gov_debt` 5% / `cn_gov_debt` 4% / `eu_gov_debt` 3%，旧 8 个按 ×0.88 等比缩放）；符号取「债务↑ = 利多黄金」（debasement 口径）；低频因子新增 `cadence` / `max_lag_days`（日频 4 / 季度 300 / 年度 **1100** 天）避免告警永久亮红灯；`MacroIndexOut.rolling_factors` 让后端自己声明哪些因子可滚动（前端不再硬编码 `f.key !== "cb_gold"`）；`LEGACY_MACRO_8_DEFAULTS` 迁移守卫（8 键默认直落新默认 / 8 键自定义 ×0.88 缩放） |
| `__version__` | ✅ 已 bump 到 `0.119.0`（4 处同步） |
| git tag | ✅ `v0.119.0` |

> 起因是**用户诉求**：「我们需要再宏观因子添加 美国 欧洲 和中国政府这些经济体的政府债务，
> 添加到宏观因子，先制定计划，我们分析它的权重。」
>
> 权重三处已**逐项拍板**：① 符号方向 = 债务↑ 利多黄金（debasement）；
> ② 政府债务组总权重 = **12%**（美 5 / 中 4 / 欧 3），旧 8 个 ×0.88 等比缩放；
> ③ 欧洲口径 = **欧盟 27 国**（`EU27_2020`，不是欧元区 20 国的 89.3）。
>
> 触发条件是**改了 `static/*.html` + `static/*.js`**（`weights.html` / `trend.html` /
> `silver.js` / `help.js` / 3 个 i18n 文件）⇒ 按 V0.100.1 必须 bump `sw.js`
> ⇒ 应用代码变了 ⇒ 不能留在 `[Unreleased]`。
> 详见 [releases/milestones/m5-four-faces-and-ai-usability-v0.116-v0.120.md](releases/milestones/m5-four-faces-and-ai-usability-v0.116-v0.120.md)。

### 再再上一轮：V0.118.0（2026-10-25）

| 项 | 状态 |
|---|---|
| 内容 | ✅ 宏观面 5 → 8 因子（+美债 2Y / +10Y-2Y 利差 / +10Y 实际利率）；`dxy`/`vix` 接实时源；**阈值滚动分位首次生效**（回填 252 个交易日历史）；顺带修掉「回测启用宏观内部权重永远 0 行」这个 V0.118.0 之前就存在的缺陷，以及「滚动分位方向对 6 个负相关因子整个反了」这个 V0.79.0 起休眠、随回填暴露的缺陷 |
| `__version__` | ✅ 已 bump 到 `0.118.0`（4 处同步） |
| git tag | ✅ `v0.118.0` |

> 起因是**用户诉求**：「宏观面的选定参数需要进行调整，添加 2Y 的美国国债收益率，
> 再考虑添加一下其他的决定因子或者调整」。
>
> 触发条件是**改了 `static/*.html` + `static/*.js`**
> （`weights.html` / `backtest.html` / `help.js` / 3 个 i18n 文件）
> ⇒ 按 V0.100.1 必须 bump `sw.js` ⇒ 应用代码变了 ⇒ 不能留在 `[Unreleased]`。
> 详见 [releases/milestones/m5-four-faces-and-ai-usability-v0.116-v0.120.md](releases/milestones/m5-four-faces-and-ai-usability-v0.116-v0.120.md)。
>
> ⚠️ **版本号从 0.116.4 直接跳到 0.118.0**：`V0.117.0` 是**规划文档**
> （`planning · 未实施`，见 [releases/milestones/m5-four-faces-and-ai-usability-v0.116-v0.120.md](releases/milestones/m5-four-faces-and-ai-usability-v0.116-v0.120.md)），
> 一行代码都没有 ⇒ 不是一次发版 ⇒ 版本号不占用。

---

## 四、2026-10-24 这一轮修掉的（都是实测出来的，不是在读代码猜的）

### 4.1 CHANGELOG 的版本归属曾经是乱的

改之前实测到 4 个问题：

| 问题 | 证据（改前的 CHANGELOG 实测） |
|---|---|
| `## [V0.105.0]` 出现两次，第一次是**空壳**（只有 header + `---`，31 字） | 全文 35 段 / 32 个唯一版本号；V0.105.0 段在 line 767 与 771 |
| `## [V0.104.0]` 出现两次，**第一次那段（line 801-845，4809 字）里混装着 5 个别的版本** —— V0.102.0（今日要闻 readhub，line 805）/ V0.103.0（我的收藏，line 815）/ V0.100.1（SW 缓存击穿，line 827）/ V0.100.2（Top 5→20，line 831）/ V0.103.1（subnav 一致性，line 835） | 逐行读原文确认；真正的 V0.104.0 在 line 872 另起一段 |
| V0.100.0 的段被拆成两半：主体（`### Added`/`Changed`/`Fixed`）在 line 846-868，**它的 `### Discipline`（line 900-904）+ `[详情]` 链接（line 906）被甩到了第二个 V0.104.0 段之后**，中间没有任何 `## [V0.100.0]` header —— 读者只会当成 V0.104.0 的内容 | 改前文件共 1154 行，line 910 就是 `## [V0.99.0]` |
| 顺序错乱：V0.100.0 夹在两个 V0.104.0 之间；V0.107.0 排在 V0.107.1 前面 | — |

**后果**：查发版史会**查错版本** —— 「今日要闻」那段真实交付挂在 V0.104.0 名下，
而 V0.104.0 真正的内容（日期分页）在另一处。

**修法**：把 5 段内容**按原文逐字切出来**（行号切片，不是重新誊写），重新拼成严格降序；
补上此前缺失的 V0.103.1 / V0.103.0 / V0.102.0 / V0.101.0 / V0.100.2 / V0.100.1 六段；
V0.101 / V0.102 两段加了显式说明 —— **它们从未 bump 过版本号**，
只是 commit message 里的功能批次标签，代码已随 V0.103.0 上线。

**内容保全已验证**：改前改后做全文行多重集比对，
**只有 2 行消失** —— 就是那两个重复的 header（`## [V0.105.0]` 与 `## [V0.104.0]`
各从 2 份变 1 份）。新增 32 行 = 29 行包装文字（`---` / `###` / `##` / 标题 / 说明 /
`[详情]` 链接）+ **3 行 V0.101.0 的内容 bullet**（Python 3.13 迁移收口；
那 3 个 commit `21f9fc5` / `a20d881` / `84a0f34` 已核验存在且 subject 对得上）。
**被搬运的正文一个字符都没动** —— 没有任何一条 bullet 出现「多了一份」或「少了一份」。

### 4.2 git tag 停在 v0.84.0，落后 40 个版本号

改之前最新 tag 是 `v0.84.0`（2026-10-10），`git describe` 显示 `v0.84.0-204-g638946f`
（`v0.84.0..HEAD` 实测 204 个 commit）。

**本地补打了 46 个 tag**（原有 54 → 现共 100）：

| 来源 | 个数 | 说明 |
|---|---|---|
| `__version__` bump 史里 v0.85.0 ~ v0.116.0 | 40 | 主依据 |
| 从未 bump `__version__` 的版本 | 6 | v0.92.1 / v0.93.0 / v0.94.0 / v0.95.0 / v0.95.1 / v0.97.2-hotfix，按 commit message 逐个定位 |

版本 → commit 的推导依据是 **`__version__` 的 bump 史**：
每个发版点必然 bump 一次版本号，所以 `git log -p` 里 `+__version__ = "X.Y.Z"` 那一行
所属的 commit **就是**发版点。这比在 commit message 里 grep 版本号可靠 ——
后者会撞上「功能批次标签」（V0.101 / V0.102 从未 bump 过版本号，grep 会把它们错认成发版点）。

现在：`git describe --tags` → `v0.118.1-<N>-g<sha>`，tag 总数 106（本地 = 远端）。
（`-5-gd1aff31` 是**在 `d1aff31` 这个 commit 处实测**的快照值 ——
`git describe` 的计数每加一个 commit 就 +1，所以别把它当常量，直接跑命令看当前值。）

> ✅ **tag 已全部推送到 GitHub**（2026-10-24）：远端 100 = 本地 100。
>
> 📌 **实际推了 48 个，不是 46 个** —— 本地比远端多 48 个 tag，
> 但只有 46 个是本轮新建的；另外 **2 个（`v0.83.0` / `v0.83.1`）是原作者
> 2026-10-10 就建好、但一直忘了推的**（远端原先从 v0.83.2 起才有）。
> 也就是说：**本地原有 54 个里，原先只有 52 个在 GitHub 上** ——
> 这个差值比「本轮补打几个」更容易让人以为推漏了，其实是没推过。
> 推之前逐个核过：48 个 tag 指向的 commit **全部是 `origin/main` 的祖先**，
> 不会在 GitHub 上留悬空 tag。
>
> ⚠️ **历史 tag 的两处不一致保持原样，没追溯改写**：
>
> | 现象 | 涉及 tag | 为什么不动 |
> |---|---|---|
> | tag 指向的 commit **不是** `__version__` bump commit | v0.74.0 / v0.75.1 / v0.78.2 / v0.79.0（4 个） | 原作者 tag 的是「发布链路修复」commit（docker 镜像按 uv.lock 还原 / 补声明 bcrypt / 修 setup-uv 的 ref / docs 发版说明），那些 commit 自己没动 `__version__`。改写它们 = 篡改历史 |
> | **lightweight** tag（无 tag 对象、无 message） | v0.51.0 / v0.51.1 / v0.64.0 / v0.65.0 / v0.66.0 / v0.82.0（6 个） | 早期约定与后续不一致。**本轮补打的 46 个全是 annotated**（94 annotated / 6 lightweight） |

### 4.3 新增 `scripts/check_version_sync.py`（9 条断言）

覆盖之前没人管的 4 处版本同步 + CHANGELOG 顺序 + 本文档自身：

| 断言 | 之前有谁管 |
|---|---|
| `pyproject.toml` == `__version__` | ❌ 无 |
| `uv.lock` == `__version__` | ❌ 无（CI 的 `uv sync --frozen` 只在 CI 跑，本地全绿） |
| `sw.js VERSION` == `__version__` | ✅ `check_pwa_assets.py` |
| CHANGELOG 最新版本段 == 应用版本 | ❌ 无 |
| **CHANGELOG 版本段严格降序、无重复** | ❌ 无（**这条正是抓出 4.1 全部问题的判据**） |
| 当前版本有 release notes | ❌ 无 |
| 当前版本在 `index.md` 登记 | ⚠️ `check_links.py` 反向覆盖（note→index） |
| **本文档声明的基线版本 == 应用版本** | ❌ 无（见下） |

**最后一条为什么重要**：本文档是「当前是哪个版本」的单一真源，**发版后必然过期**。
过期而不报红 = 文档开始撒谎 —— 那比没有文档更坏。所以把它纳入门禁：
发版时忘了更新本文档，`check_version_sync.py` 立刻变红。

**解析方式刻意抗干扰**：`__version__` 用 `ast` 解析（注释和文档串里的假值骗不过去）、
`pyproject.toml` / `uv.lock` 用 `tomllib`（`uv.lock` 里几十个包各带一个 `version`，
正则会抓错块）、只有 `sw.js` 才用正则。

**9 条断言全部做过反向验证**（注入故障 → 必须变红）：
`scripts/_reverse_check_version_sync.py`，**11 个用例全绿**。
验证过程中抓出**门禁自己的一个假绿**：登记检查原先用裸子串匹配当前版本的 `vX.Y.Z.md`，
把 index.md 里改成 `vX.Y.Z.md.x` 仍然全绿 —— 已改为匹配 markdown **链接目标**。

### 4.4 死链门禁本身有 2 个盲区 —— 顺手补上（`check_links.py`）

补 4.1 的 CHANGELOG 时顺手发现的。**两处盲区都是「缺陷存在但任何门禁都报不出来」**：

| 盲区 | 实测后果 |
|---|---|
| **根 `CHANGELOG.md` 根本不在死链扫描范围内**（只扫 `README.md` + `docs/**`） | CHANGELOG 正文里 4 条「`[详情]`」链接指向**不存在的** release notes（V0.92.1 / V0.93.0 / V0.94.0 / V0.95.1），一直没人管 |
| **link reference definition（`[label]: target`）压根不被检查** —— 内联链接正则抓不到这种写法 | CHANGELOG 底部 5 条坏定义：4 条指向不存在的 release notes + **1 条指向 `https://example.com/compare/v0.99.0...HEAD`**（模板占位 URL，从来不是真链接） |

**修法**：
- `DOC_FILES` 纳入根 `CHANGELOG.md` ⇒ 上面那 4 条内联死链**当场被抓出来**；
- 新增 `REF_DEF_RE` + `_ref_def_targets()`（**跳过 fenced code block** ——
  代码块里的 `[label]: target` 只是示例文字，markdown 不会把它当定义）⇒ 5 条坏定义被抓出来；
- 坏的那 5 条定义已删；4 条指向不存在 notes 的内联 `[详情]` 也已删
  （那 4 个版本的**记录在 CHANGELOG 段里**，段内容本身没动）。

**新能力也做了反向验证**：`scripts/_reverse_check_links_scope.py`，7 个用例全绿，
其中 2 个是**「不该报红」的防误报用例**（代码块里的定义、外部 URL 的定义）。

> 顺带修了门禁代码里 2 处指向**不存在文件** `_calib_links.py` 的注释引用 ——
> 文档里指向不存在的东西，本身也是一种「看起来能用其实没用」。


---

## 五、怎么自己查

```bash
# 当前版本（4 处一起看）
grep __version__ src/app/__init__.py
grep '^version' pyproject.toml
grep -A1 'name = "gold-etf-analyzer"' uv.lock
grep 'const VERSION' static/sw.js

# 一致性门禁（9 条断言）
python3 scripts/check_version_sync.py

# 门禁的反向验证（注入 11 种故障，逐条确认能变红）
python3 scripts/_reverse_check_version_sync.py

# 死链门禁（含根 CHANGELOG.md 与 link reference definition）
python3 scripts/check_links.py
python3 scripts/_reverse_check_links_scope.py   # 7 个用例，含 2 个防误报

# 按版本 checkout
git checkout v0.116.2        # tag 锚点（checkout 后记得 git checkout main 回来）
git describe --tags           # → v0.116.2-<N>-g<sha>（N 是 tag 之后的 commit 数，每次提交 +1）
```

---

## 六、单一真源约定

| 想改「版本号」 | 改哪里 | 还要做什么 |
|---|---|---|
| 应用版本 | `src/app/__init__.py` 的 `__version__` | `pyproject.toml` + `uv.lock`（`uv lock`）+ `static/sw.js` |
| 发版记录 | `CHANGELOG.md` 加一段 | 段要**严格降序**（门禁会查） |
| **还没发版的变更** | `CHANGELOG.md` 的 `## [Unreleased]` 段 | 放在文件头；**不要**新起版本号（应用代码没变就别 bump） |
| 版本细节 | `docs/releases/milestones/m<N>-*.md` | **V0.120.5 起**：逐版 notes 合并进里程碑文档（逐版原文在 git 历史：`git show vX.Y.Z:docs/releases/vX.Y.Z.md`）；在 `docs/releases/index.md` 登记 |
| **当前版本是哪个** | 本文档 | 基线版本要跟着改（门禁会查） |

**唯一真源是 `src/app/__init__.py`** —— 其余 3 处是它的副本，
`/openapi.json` 的 `info.version` 也从那里读。

**改 `static/*.html|js|css` 必须 bump `sw.js` 的 VERSION**（V0.100.1 沉淀的教训），
否则已安装 PWA 的浏览器会一直用旧缓存。

**改了版本号，就一定要同步改本文档的「基线」** —— 门禁会逼你改。
这是刻意的：**单一真源文档必须会过期，而过期的单一真源比没有更坏。**

---

## 相关文档

- [roadmap.md](roadmap.md) — **当前推进计划**（唯一活跃路线，逐条带实测判据）
- [releases/index.md](releases/index.md) — 能力全景索引
- [releases/milestones/m6-truthful-signals-v0.121.md](releases/milestones/m6-truthful-signals-v0.121.md) — 当前里程碑（V0.121 可信度修复线）
- [CHANGELOG.md](../CHANGELOG.md) — 发版史
