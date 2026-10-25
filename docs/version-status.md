# 应用版本状态（单一真源）

> **基线：V0.118.0** ｜ **最近更新：2026-10-25** ｜ **状态：一致，无漂移**
>
> 这份文档回答一个问题：**「这个应用现在到底是哪个版本？」**
> 答案散落在 6 个地方（4 处代码版本号 + CHANGELOG + git tag + release notes），
> 历史上它们互相矛盾过。本文档把结论收在一处，并把每个结论的**验证方式**写出来 ——
> 你可以自己跑命令复核，不必相信本文。

## 一句话结论

**当前版本 = 0.118.0**，代码里 4 处版本号完全一致，运行中的服务也报这个版本。
**V0.117.0 是「规划中」，一行代码都还没写**（它是改进方向记录，不是交付）。

---

## 一、当前版本

| 位置 | 文件 | 值 | 谁读它 |
|---|---|---|---|
| 运行时真源 | [src/app/__init__.py](../src/app/__init__.py) `__version__` | `0.118.0` | FastAPI `version=` → `/openapi.json` 的 `info.version` |
| 包元数据 | [pyproject.toml](../pyproject.toml) `[project].version` | `0.118.0` | `pip` / `uv` 装包 |
| 锁文件 | [uv.lock](../uv.lock) `package.gold-etf-analyzer` | `0.118.0` | `uv sync --frozen`（CI） |
| PWA 缓存 | [static/sw.js](../static/sw.js) `const VERSION` | `v0.118.0` | Service Worker 缓存名 `gold-shell-*` / `gold-runtime-*` |

**运行中验证**（主入口 `192.168.0.204:8888`）：

```
GET /openapi.json  →  info.version = 0.118.0
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
| `__version__` bump 史 | **69** 个版本 | 哪些版本真正 bump 过版本号（= 发过版） |
| [CHANGELOG.md](../CHANGELOG.md) | **44** 段 / 43 个唯一版本号 | 发版史的**人读**记录 |
| [docs/releases/](releases/) | **53** 份 release notes | 单个版本的实现细节（commit 链 / 验证 / 风险） |
| git tag | **105** 个（本地 = 远端，已同步） | 按版本 checkout 的锚点 |

> **44 段 ≠ 43 个唯一版本号**：`V0.97.2` 有 2 段 —— `## [V0.97.2 hotfix]` 在前、
> `## [V0.97.2]` 在后。hotfix **没有 bump 版本号**（该段自己写明了这点），
> 所以它是同一个版本号的第 2 段，不是重复 bug。门禁 `check_version_sync.py`
> 把 hotfix 后缀排在同版本基础段**之上**，因此这段顺序是合法的。
>
> **105 个 tag 本地与远端一致**（2026-10-25 已全部推送，含 V0.118.0）：远端 105 = 本地 105，
> 逐个比对 `git rev-parse <tag>^{commit}` 与 `git ls-remote --tags` 的 `^{}` 行，
> **指向不一致的 0 个**。其中 annotated 98 / lightweight 6，两侧分布相同。

> **本轮把 `## [Unreleased]` 段转正成了 `## [V0.116.1]`** —— 起因是 CI 修绿这轮
> **改了 `static/*.html` 与 `static/i18n/*.js`**（`ask.html` / `weights.html` / 3 个 i18n 文件），
> 按 V0.100.1 规则**必须 bump `sw.js` VERSION** ⇒ 应用代码变了 ⇒ 不能留在 Unreleased。
> 门禁 `check_version_sync.py` 只匹配 `## [V...]`，**不把 Unreleased 当版本段** ——
> 所以 Unreleased 存在不会让「CHANGELOG 最新版本段 == 应用版本」这条断言失真。

### 已知且**故意**保留的缺口

| 缺口 | 数量 | 为什么保留 |
|---|---|---|
| 有 release notes 但 CHANGELOG 无段 | 21 | V0.79.0~V0.91.0（18 个）早期版本只出了 notes 没进 CHANGELOG；V0.98.0 / V0.97.2-hotfix 同理；V0.117.0 尚未发版（见下）。**老版本不追溯补录**，以 release notes 为准 |
| 有 CHANGELOG 段但无 release notes | 11 | V0.92.1 / V0.93.0 / V0.94.0 / V0.95.1 / V0.101.0 / V0.102.0 / V0.103.1 / V0.106.1 / V0.106.2 / V0.111.1 / V0.112.0。段已写清内容，缺的是「独立成篇的 notes」 |
| 有 `__version__` bump 但无 release notes | 18 | V0.74.0~V0.78.2（13 个，notes 体系建立之前）+ V0.103.1 / V0.106.1 / V0.106.2 / V0.111.1 / V0.112.0（5 个 hotfix，段写在 CHANGELOG 里） |

> **V0.117.0 的 release notes 存在但无 CHANGELOG 段 / 无 `__version__` bump / 无 tag ——
> 这是正确的**。它是**规划文档**，还没发版。三者都缺席 = 状态自洽。
> 详见 [releases/v0.117.0.md](releases/v0.117.0.md)。

---

## 三、当前在途：V0.117.0（规划中，0% 实施）

| 项 | 状态 |
|---|---|
| 方向文档 | ✅ [releases/v0.117.0.md](releases/v0.117.0.md)（标 `planning · 未实施`） |
| 完整推理 | ✅ [app-improvement-path.md](app-improvement-path.md) |
| 缺陷清单 | ✅ [next-steps.md](next-steps.md) |
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

### 再下一轮：V0.116.2（2026-10-25）

同样的规则、同样的判据，又触发了一次**真实发版**：

| 项 | 状态 |
|---|---|
| 内容 | ✅ 3 处静默失效的前端缺陷（`admin/users.html` 整页渲染成 i18n 键字面量 / `/ask` 状态条带 `hidden` 永不可见 / dismiss 勾选框没接上 `warning.js`）+ 2 处门禁缺陷（i18n 门禁只扫顶层目录 / 浏览器门禁缺端到端断言） |
| `__version__` | ✅ 已 bump 到 `0.116.2`（4 处同步） |
| git tag | ✅ `v0.116.2` |

> 触发条件同样是**改了 `static/*.html`**（`ask.html` / `admin/users.html`）
> ⇒ 按 V0.100.1 必须 bump `sw.js` ⇒ 应用代码变了 ⇒ 不能留在 `[Unreleased]`。
> 详见 [releases/v0.116.2.md](releases/v0.116.2.md)。
>
> 📌 **这轮还留了一件没做的事**：生产库 `users` 表缺 `role` 列
> ⇒ `GET /api/v1/admin/users` / `POST .../reset-password` / `GET /api/v1/auth/me` 三个端点返 500。
> 修它要**改生产 SQLite 库** ⇒ 留给用户决定，本轮只报告不改。
> 详见 [releases/v0.116.2.md §5](releases/v0.116.2.md)。

### 再下一轮：V0.116.3（2026-10-25）

| 项 | 状态 |
|---|---|
| 内容 | ✅ 命令面板自动聚焦被 V0.113.0 的 `visibility` 过渡打没了（`focus()` 被浏览器**静默丢弃**）+ 聚焦断言从 flaky 改成**确定性**判据（`transition-delay` 钉住可见时刻） |
| `__version__` | ✅ 已 bump 到 `0.116.3`（4 处同步） |
| git tag | ✅ `v0.116.3` |

> 触发条件同样是**改了 `static/*.js`**（`command-palette.js`）
> ⇒ 按 V0.100.1 必须 bump `sw.js` ⇒ 应用代码变了 ⇒ 不能留在 `[Unreleased]`。
> 详见 [releases/v0.116.3.md](releases/v0.116.3.md)。
>
> 📌 **这轮的一条元教训**：判据本身也会骗人 —— 我第一版判据用
> `transition-duration` 拉长过渡，回退实现后门禁**连报两次「全绿」**；
> 而 `visibility` 是离散插值（第一帧就翻），加长 duration **根本不管用**，
> 正确杠杆是 `transition-delay`。**断言没被证伪过，就不算数。**

### 再下一轮：V0.116.4（2026-10-25）

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
> 详见 [releases/v0.116.4.md](releases/v0.116.4.md)。
>
> 📌 **这轮的一条教训**：同一个入口（进「决策」）在实现上有 **4 条独立路径**
> —— 顶栏 / 场景卡 / 抽屉 / 面板。前三条共用 `SCENES.path`（同源，不会漂移），
> 面板是**另外派生**的 ⇒ 漂移就发生在派生那一层。
> **同源派生的东西要连「顺序」一起同源**，不只是「集合」同源 ——
> 而面板里「第一条命中」是**有语义的**（默认选中 + 回车）。

### 再下一轮：V0.118.0（2026-10-25）

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
> 详见 [releases/v0.118.0.md](releases/v0.118.0.md)。
>
> ⚠️ **版本号从 0.116.4 直接跳到 0.118.0**：`V0.117.0` 是**规划文档**
> （`planning · 未实施`，见 [releases/v0.117.0.md](releases/v0.117.0.md)），
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

现在：`git describe --tags` → `v0.118.0-<N>-g<sha>`，tag 总数 105（本地 = 远端）。
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
| 版本细节 | `docs/releases/vX.Y.Z.md` | 在 `docs/releases/index.md` 登记（`check_links.py` 会查） |
| **当前版本是哪个** | 本文档 | 基线版本要跟着改（门禁会查） |

**唯一真源是 `src/app/__init__.py`** —— 其余 3 处是它的副本，
`/openapi.json` 的 `info.version` 也从那里读。

**改 `static/*.html|js|css` 必须 bump `sw.js` 的 VERSION**（V0.100.1 沉淀的教训），
否则已安装 PWA 的浏览器会一直用旧缓存。

**改了版本号，就一定要同步改本文档的「基线」** —— 门禁会逼你改。
这是刻意的：**单一真源文档必须会过期，而过期的单一真源比没有更坏。**

---

## 相关文档

- [app-improvement-path.md](app-improvement-path.md) — 应用整体改进路径（V0.117.0 起）
- [next-steps.md](next-steps.md) — 当前推进计划（缺陷清单）
- [releases/index.md](releases/index.md) — 能力全景索引
- [roadmap.md](roadmap.md) — ⚠️ 已归档（基线停在 V0.100.0）
- [CHANGELOG.md](../CHANGELOG.md) — 发版史
