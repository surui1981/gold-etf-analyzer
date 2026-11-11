# 应用版本状态（单一真源）

> **基线：V0.126.0** ｜ **最近更新**：2026-11-11 ｜ **状态**：代码一致，**服务已重启**（运行中 = `0.126.0`）**
>
> 这份文档回答一个问题：**「这个应用现在到底是哪个版本？」**
> 答案散落在 6 个地方（4 处代码版本号 + CHANGELOG + git tag + release notes），
> 历史上它们互相矛盾过。本文档把结论收在一处，并把每个结论的**验证方式**写出来 ——
> 你可以自己跑命令复核，不必相信本文。

## 一句话结论

**当前版本 = 0.126.0**，代码里 4 处版本号完全一致，**运行中的 8888 服务也报 `0.126.0`**
（已用 systemd 重启 ⇒ 「代码 = 服务」）。
**V0.117.0 是「规划中」，一行代码都还没写**（它是改进方向记录，不是交付）。

---

## 一、当前版本

| 位置 | 文件 | 值 | 谁读它 |
|---|---|---|---|
| 运行时真源 | [src/app/__init__.py](../src/app/__init__.py) `__version__` | `0.126.0` | FastAPI `version=` → `/openapi.json` 的 `info.version` |
| 包元数据 | [pyproject.toml](../pyproject.toml) `[project].version` | `0.126.0` | `pip` / `uv` 装包 |
| 锁文件 | [uv.lock](../uv.lock) `package.gold-etf-analyzer` | `0.126.0` | `uv sync --frozen`（CI） |
| PWA 缓存 | [static/sw.js](../static/sw.js) `const VERSION` | `v0.126.0` | Service Worker 缓存名 `gold-shell-*` / `gold-runtime-*` |

**运行中验证**（主入口 `192.168.0.204:8888`）：

```
GET /openapi.json  →  info.version = 0.126.0   ← 与代码一致 ✅
GET /              →  307 → /static/trend.html → 200
```

> ✅ **服务已用 systemd 重启**（`gold-etf-analyzer.service`，2026-11-07 10:06 首次拉起、
> 2026-11-11 重启加载 V0.126.0）。这台机器上 8888 本来就是 systemd 托管的，
> **不需要**手动 `kill` + `setsid` 起进程 —— 用下面这条即可：

```bash
sudo systemctl restart gold-etf-analyzer.service
sleep 12 && curl -s http://192.168.0.204:8888/openapi.json | grep -o '"version":"[^"]*"'
```

> 📌 unit 文件：`/etc/systemd/system/gold-etf-analyzer.service`
> （`WorkingDirectory=/home/surui/gold-etf-analyzer`、
> `EnvironmentFile=…/.env.prod`、`Environment=PYTHONPATH=…/src`、
> `ExecStart=…/.venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 8888 --no-access-log`、
> `Restart=on-failure`）。
> ⚠ **用 systemd 而不是手动起进程**：手动起的实例不会跟着 systemd 走
> （机器重启后就没了），而且会和 systemd 的实例**抢 8888 端口**。
> ⚠ 旧的「`kill <pid>` + `setsid`」写法仍可用于**临时**实例，
> 但**不要**用它替代 systemd（`setsid` 脱离会话是为了会话结束后进程不死 ——
> 这在 systemd 托管下是多余的）。

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
| `__version__` bump 史 | **87** 个版本 | 哪些版本真正 bump 过版本号（= 发过版） |
| [CHANGELOG.md](../CHANGELOG.md) | **62** 段 / 61 个唯一版本号 | 发版史的**人读**记录 |
| [docs/releases/](releases/) | **12** 份**里程碑文档**（V0.120.5 起替代逐版 notes） | 阶段的演进脉络（根因 / 修法 / 验证 / 教训） |
| git tag | **123** 个（**本地 123 / 远端 123** ✅ 一致） | 按版本 checkout 的锚点 |

> ⚠️ **上表 4 个计数是 V0.121.0 逐项实测改写的** —— 上一版写的是
> 「74 / 49 段·48 个 / 58 份 / 113 个」，其中 **3 个都偏低**
> （实测 bump 史 78 而非 74、CHANGELOG 53 段而非 49、releases 已合并为 7 份而非 58 份）。
> ⇒ 这正是 §3.3 说的那类「**内容腐化**」：**门禁只校验版本号，不校验计数**，
> 所以计数腐化不会报红，只能靠人工复核 —— 本轮顺手订正。
> （V0.121.2 只加了 1 段 CHANGELOG / 1 次 bump / 1 个 tag ⇒ 79→80、54 段→55 段、115→116；
> V0.121.3 同理 ⇒ 80→81、55 段→56 段、116→117；
> V0.121.4 同理 ⇒ 81→82、56 段→57 段、117→118；
> V0.122.0 同理 ⇒ 82→83、57 段→58 段、118→119，**另加 1 份里程碑文档**（M7）⇒ 7→8 份；
> V0.123.0 同理 ⇒ 83→84、58 段→59 段、119→120，**另加 1 份里程碑文档**（M8）⇒ 8→9 份；
> V0.124.0 同理 ⇒ 84→85、59 段→60 段、120→121，**另加 1 份里程碑文档**（M9）⇒ 9→10 份；
> V0.125.0 同理 ⇒ 85→86、60 段→61 段、121→122，**另加 1 份里程碑文档**（M10）⇒ 10→11 份；
> V0.126.0 同理 ⇒ 86→87、61 段→62 段、122→123，**另加 1 份里程碑文档**（M11）⇒ 11→12 份。）
>
> **60 段 ≠ 59 个唯一版本号**：`V0.97.2` 有 2 段 —— `## [V0.97.2 hotfix]` 在前、
> `## [V0.97.2]` 在后。hotfix **没有 bump 版本号**（该段自己写明了这点），
> 所以它是同一个版本号的第 2 段，不是重复 bug。门禁 `check_version_sync.py`
> 把 hotfix 后缀排在同版本基础段**之上**，因此这段顺序是合法的。
>
> **121 个 tag = 120 个版本号 tag + 1 个 `v0.97.2-hotfix`**（后者不是版本号形态的 tag，
> 但确实是真实存在的发布锚点，**而且它也是 annotated**）。
> 其中 annotated **115** / lightweight **6**（115 + 6 = **121** ✅ 自洽）。
> （**已推送的 114 个**此前逐个比对 `git rev-parse <tag>^{commit}` 与
> `git ls-remote --tags` 的 `^{}` 行，**指向不一致的 0 个** ⇒ 本地与远端一致；
> 本轮新增的 2 个也已逐一比对：`v0.121.1` → `a3153db`、`v0.121.2` → `f823909`，**均一致**。）
> （⚠️ 上一版此处写的「annotated 102 / lightweight 7」**两个数都差 1** —— lightweight 实为 6 个
> （v0.51.0 / v0.51.1 / v0.64.0 / v0.65.0 / v0.66.0 / v0.82.0，见本文件下方那张表）。
> 本版按 `git for-each-ref --format='%(objecttype)'` **实测**改写。）
> 📌 **V0.122.0 又订正了一处**：上一版写「annotated 111 / lightweight 6」⇒ 和为 117，
> **与它自己写的 118 个 tag 对不上**；实测 118 个里有 **112** 个 annotated，
> 加本轮新 tag（annotated）⇒ **113**。这类「同一段里两个数互相矛盾」只有实测能发现。
>
> ✅ **V0.121.1 与 V0.121.2 都已推送**（2026-11-07）—— 远端与本地**一致**。
> - 起因是**本机 DNS 解析不了境外域名**（路由器 `192.168.0.1` 只解析国内域名；
>   `ping 8.8.8.8` 通、`getent hosts github.com` 不通）⇒ 首次推送失败；
>   收尾时 DNS 已恢复（`getent hosts github.com` → `20.205.243.166`、`curl https://github.com` → 200）。
> - 推送走 **`GH_TOKEN` 环境变量 + `gh auth git-credential`** ⇒ token **不进 argv、不落盘、
>   不进 `remote.origin.url`**。
> - ✅ **远端已核实**：`git ls-remote --tags` 去掉 `^{}` 行后 **116 个**（此前 114）
>   ⇒ 本地与远端一致；`v0.121.1` → `a3153db`、`v0.121.2` → `f823909`；
>   `refs/heads/main` = `eec4ddd` = 本地 HEAD。
> - ⚠️ 本枚 PAT 在 chat 里明文出现过 ⇒ **建议用完即轮换**。
>
> ✅ **V0.121.3 已推送**（2026-11-07 11:01）—— 远端与本地**一致**。
>
> | 项 | 值 |
> |---|---|
> | `refs/heads/main` | `1e41af5` = 本地 HEAD ✅ |
> | `refs/tags/v0.121.3` | tag 对象 `ac170e8`；`^{}` 行 = `1e41af5` ✅ 与本地 `git rev-parse v0.121.3^{commit}` 一致 |
> | 远端 tag 数（去掉 `^{}` 行） | **117** = 本地 117 ✅ |
>
> **这次推送是被网络逼出来的**：本机到 GitHub 的通道**绝大部分时间是断的** ——
> 路由器 DNS `192.168.0.1` 解析 `baidu.com` 成功、解析 `github.com` / `pypi.org` 超时；
> 12+ 个裸 IP（`curl --resolve`）绝大多数超时，SSH 22/443 不通；本机**没有 IPv6**。
> ⇒ 走的是「**持续重试直到窗口打开**」的路子：
> ① 先用 **DoH**（`dns.alidns.com` / `doh.pub`）绕开系统 DNS 拿到 GitHub IP；
> ② 并行探测这些 IP，通了就用 **git 2.43 的 `http.curloptResolve`**（`host:port:address`，
>    SNI 仍带 github.com）**完全绕开 DNS**；
> ③ **不依赖 `git push` 管道末尾的 `tail`**（它的退出码恒为 0，会把失败伪装成成功）——
>    必须取 `${PIPESTATUS[0]}` 或不接管道；
> ④ 成功判据 = **`ls-remote` 读回的 `refs/heads/main` == 本地 HEAD**，不是「命令没报错」。
>
> ⚠️ **两个独立的前提**：网络窗口 + **classic PAT**（gh keyring 里那枚
> `github_pat_` fine-grained 的**没有写权限**，只有 classic 能 push）。
> 本枚 classic PAT 同样在 chat 里明文出现过 ⇒ **用完即轮换**。
>
> ⚠️ **annotated tag 在 `ls-remote` 里占两行** —— `refs/tags/v0.120.1` 是 **tag 对象**
> 的 SHA，`refs/tags/v0.120.1^{}` 才是它指向的 **commit** SHA；统计数量时
> 必须把 `^{}` 行去掉再数，否则 114 个 tag 会数成 222 行左右（实测 `ls-remote --tags` 原始行数
> = 220 + 2 = 222）。**本地与远端的 116 个同理**（`v0.121.1` 与 `v0.121.2` 都是 annotated
> ⇒ 原始行数已从 222 变成 **222 + 2 + 2 = 226**，实测 `ls-remote --tags` 原始行数 **226**，与推算一致）。
> （`v0.121.3` 也是 annotated ⇒ 本地 `ls-remote --tags` 原始行数将为 **228**。）

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
| `__version__` | ❌ 未 bump（V0.117.0 是方向文档，**不占版本号**） |
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

### 本轮：V0.126.0（2026-11-11 发版）

| 项 | 状态 |
|---|---|
| 内容 | ✅ **生产库从 SQLite 正式切到 MySQL 8.0.46** —— 用户诉求：「当前主机已经安装了 MYSQL，我们准备数据迁移到 MYSQL 数据库」。本版交付：结构 + 历史数据**全迁**（**25 张表 / 88 284 行**，逐表「行数 + SHA-256 内容校验和」一致），停机窗口实测 **30 秒**（预算 5–30 分钟）。同时把**方言差异收进一层抽象**（`repositories/upsert.py` + `repositories/sql_expr.py`），并让**备份链路双方言统一** |
| 用户拍板 | ✅ 三件事：① **目标形态 = 生产库正式切到 MySQL**（不是「留个影子库」）；② **历史数据 = 结构 + 全迁**；③ **停机窗口 = 可停 5–30 分钟**（实测只用掉 **30 秒**） |
| 目标 schema 照谁建 | ✅ 照**生产 SQLite 的 `sqlite_master`**，**不是** ORM —— 实测 ORM 与生产库有 **42 处差异**（ORM 里 `news_source` 是 `String(32)`、生产库里还是 `TEXT`）⇒ 用 ORM `create_all` 生成目标结构 = 顺手改掉 42 处没人审过的东西。只有 **3 处**例外（`COLUMN_TYPE_OVERRIDES`：`news_source`/`site_name` 改 VARCHAR 因为 MySQL 的 UNIQUE/INDEX 不能建在 TEXT 上；`country_iso` 放宽到 `VARCHAR(16)` 因为库里装着 8 字符的伪 ISO `WGC_AGGR`） |
| MySQL 上不跑 Alembic | ✅ 那 32 个迁移是「从零建库」脚本，在已有表的库上会中途失败、留下**半迁移 schema** 且版本号已推进 ⇒ 两道防线：`migrations/env.py` 对 MySQL **硬性拒绝** + `main.py::_migrate_db` 的 MySQL 分支只做**只读校验**（表齐不齐、`alembic_version` 对不对），对不上就**启动失败并说清楚**。MySQL 的 `alembic_version` 由迁移脚本**从 SQLite 一起搬过去**（`t2u3v4w5x6y`） |
| 9 个方言坑 | ✅ ① **会话时区**（MySQL 的 `CURRENT_TIMESTAMP` 用会话时区 ⇒ 连接层钉 `SET time_zone='+00:00'`；⚠ **不能**改 server 级 `default-time-zone` —— 这台机器上还跑着别的库）；② **`rowcount` 语义**（MySQL 报「改动行数」⇒ 开 `CLIENT_FOUND_ROWS`；⚠ SQLAlchemy 的 asyncmy 实现了 `_found_rows_client_flag()` 但**基类从不调用它** ⇒ 必须自己设）；③ **行别名 `new.<col>` 只暴露 INSERT 列清单里出现过的列**（⇒ 少一列就是 error 1054）；④ **`VALUES(col)` vs `AS new`**（SQLAlchemy 按 `server_version_info` 自己换形态，**离线 `dialect()` 不设这个开关** ⇒ 离线测试必须手工 `_initialize_mysql()`）；⑤ **`strftime` 在 MySQL 8.0 上不存在**（⇒ `date_format`；且同一份表达式必须逐字同时进 `select()` 与 `group_by()`）；⑥ **`sqlite_insert` 在 MySQL 上是硬语法错**；⑦ **UNIQUE/INDEX 不能建在 TEXT 上**（1170）；⑧ **VARCHAR 长度真的会被校验**（1406）；⑨ **TEXT 列不能有字面量默认值**（1101 ⇒ 改 `DEFAULT ('')`） |
| 🐛 顺带修掉的真缺陷 | ① **模型注册漏了 3 张表** —— `models/__init__.py` 缺 `news_feed` / `daily_money_flow_factor` / `user_news_favorite` ⇒ `Base.metadata` 只有 20 张表 ⇒ 启动期 schema 校验会**误报「MySQL 缺表」**；② **整条新闻流在 MySQL 上写不进去** —— payload 不带 `fetched_at`（靠列默认值补）而 `update_columns` 里有它 ⇒ MySQL 报 `Unknown column 'new.fetched_at'`（**只在跑那行 SQL 时才炸**，启动不炸）；③ **`cb_gold` 因子写不进去** —— `country_iso VARCHAR(3)` 装 8 字符的 `WGC_AGGR` ⇒ 严格模式报 1406；④ **两条备份工具各写各的目录**（`data/backup/` vs `data/backups/`）⇒ 同一个库两份互不相干的备份 ⇒ 目录名统一为 `backups`；⑤ **COMEX 库存卡的「1 年」变化率恒为「—」**（**与 MySQL 无关**，是被新数据触发的时间炸弹）—— 回看窗口卡在 `latest - 365d`，而源是**交易日频**（周末缺行）⇒ 恰好等于那天的观测常常不存在 ⇒ 基线被挡在窗口之外 ⇒ 1y 恒为 `None`。2026-11-09 新观测写入后窗口前移 3 天 ⇒ 窗口内最早一条（2025-11-10）比基线目标（2025-11-09）晚一天 ⇒ 1y 显示「—」。⚠ **反向验证**：同一段计算在**迁移前的 SQLite 备份数据**上跑出**同样的 None** ⇒ 与 MySQL 无关。修法：回看窗口多取 **10 天余量** ⇒ 实测 1y 变成 `base=2025-11-07 / -39.05%`。⚠ 老单测用**每天一行**的序列（没有缺口）⇒ 这条边界永远测不到 ⇒ 补了 1 条**带缺口**的回归测试（撤销修复 ⇒ **实测变红**） |
| 备份链路 | ✅ 统一成一条口径：`scripts/daily_backup.sh`（systemd timer，每日 03:00）+ `watchdog.py` 都读 `.env.prod` 的 `DATABASE_URL` 前缀自动分流 —— SQLite ⇒ `.backup()` + `integrity_check`；MySQL ⇒ `mysqldump --single-transaction`（**不停写**的一致性快照）。⚠ 凭据走 **0600 临时 defaults 文件** ⇒ 密码不进 argv、不进环境变量、不进日志 |
| 三库分工 | ✅ **生产 = MySQL**（`.env.prod`，迁移工具维护，**零 Alembic**）/ **开发测试 = SQLite**（`.env`，Alembic 32 个迁移照旧）/ **一次性凭据 = `.env.mysql`**（0600，已在 `.gitignore` 里） |
| 切换后复核 | ✅ 当日再跑一次 `--verify`：**21 张表逐表 SHA-256 仍与切换瞬间的 SQLite 快照一致**；**4 张表不同** —— 全部因**线上调度器在 MySQL 上持续写入**（`gold_inventory_daily` +1 · `news_feed_items` +21 · `telemetry_events` +220 · `news_feed_daily` 行数不变但内容被重算）⇒ **迁移保真**与**应用真的在 MySQL 上写**同时得到验证 |
| 时区实测 | ✅ 切换后新写入的行 `fetched_at = 2026-11-11 07:12:54` = **UTC**（日志本地时间 15:12:54 = UTC+8）⇒ **没偏 8 小时**；`news_feed_items` 3 584 → **3 600**（+16 新行，与调度器 `upserted=16` 一致）⇒ **upsert 在 MySQL 上真的成功** |
| `__version__` | ✅ 已 bump 到 `0.126.0`（4 处同步：`__init__.py` / `pyproject.toml` / `uv.lock` / `sw.js`） |
| 迁移 | ✅ **零 Alembic 迁移**（MySQL 分支压根不跑）；SQLite 侧的结构照旧由 32 个迁移管 |
| 静态资源 | ✅ **未改 `static/*.html|js|css`**（只 bump 了 `sw.js` 的 `VERSION` 常量）⇒ 无 SW 缓存击穿风险 |
| 测试 | ✅ `tests/test_repositories/` **334 passed**（其中 `test_upsert_dialect.py` **5 passed** —— **纯离线**，只断言编译出来的 SQL、不连库 ⇒ CI（只有 SQLite）也能跑）；`tests/test_services/test_gold_inventory.py` **15 passed**（含 1 条新回归测试）⇒ 合计 **349 passed** |
| 门禁 | ✅ `ruff check src tests scripts` **0** / `ruff format --check src tests` **0** / `check_pwa_assets`（SW `v0.126.0` == 应用版本，54 条 SHELL_ASSETS）/ `check_deps`（`src/` 14 个三方 import 全在 dependencies）/ `check_i18n_keys`（**0 missing / 582 in-scope**）/ `check_static_js`（22 页 + 39 脚本）/ `check_freshness_consistency` / `check_links`（**31** 份文档 / **446** 条内部链接 + 4 个锚点）/ `check_routes`（**20 条路由**全部返回期望 status）/ `check_version_sync`（4 处版本号 + CHANGELOG 降序 + 里程碑登记 + 基线） |
| 浏览器门禁 | ✅ DB 换了后端 ⇒ 重跑 DB 相关页面：`_verify_nav_8` **27/0** · `_verify_home_report` **49/0** · `_verify_home_verdict` **55/0** · `_verify_home_metals` **39/0**（连跑 4 次）· `_verify_scoring_robust` **8/0** · `_verify_report_archive` **43/0** · `_verify_central_bank_aggregate` **18/0** · `_verify_top20` / `_verify_date_nav` 无失败项 |
| 反向验证 | ✅ 撤销 `_mysql_update_expressions`（改回 `{col: stmt.inserted[col]}`）⇒ 编译结果里重新出现 `new.fetched_at` ⇒ **测试变红**（实测过 ⇒ 再改回）；另加一条 `test_mysql_dialect_uses_row_alias_form` 专门钉住「生产用的行别名形态」，防止其余断言因 SQLAlchemy 换形而**假绿** |
| 回滚 | ✅ 备份文件 `data/backups/gold_etf-cutover-20261111-151153.db` **原样保留** + 回滚脚本 `/tmp/cutover_rollback.sh`（停服务 → `.env.prod` 切回 SQLite → 用备份覆盖 `data/gold_etf.db` → 起服务）。⚠ 回滚**不 bump 版本**（代码层两个方言都支持，回滚只是改一行配置） |
| 文档 | ✅ 新增**第 12 份里程碑文档 M11 · 生产库切到 MySQL（V0.126）**（`docs/releases/milestones/m11-mysql-production-migration-v0.126.md`，含 9 个方言坑的逐条剖析）+ 登记进 [docs/releases/index.md](releases/index.md)；[docs/roadmap.md](roadmap.md) 记录本次迁移 |
| 服务 | ✅ **已用 systemd 重启**（`sudo systemctl restart gold-etf-analyzer.service`）⇒ `/openapi.json` → `info.version = **0.126.0**`；启动日志 `MySQL schema 校验通过：25 张表，alembic_version=t2u3v4w5x6y（迁移工具已写入）` |

#### 推送状态：⏳ **待推送**（本地已就绪：3 个 commit + annotated tag `v0.126.0`）

| 项 | 状态 |
|---|---|
| 本地 | ✅ 3 个 commit（`fix(gold-inventory)` → `chore(release)` → `docs(v0.126.0)`）+ annotated tag `v0.126.0`（tag 对象 `8084f81` → commit `7f0f571` = HEAD） |
| 阻塞 ① | ⚠ **凭据**：gh keyring 里只有一枚 **fine-grained PAT**（`github_pat_` 前缀）⇒ **无写权限**（历史上 `git push` 直接 403：`Permission to surui1981/gold-etf-analyzer.git denied to surui1981`）⇒ **只有 classic PAT（`ghp_` 前缀）能 push** |
| 阻塞 ② | ⚠ **网络**：本机到 GitHub 的通道**此刻是断的**（系统 DNS 解析不了 `github.com`；DoH 能拿到 IP，但 `140.82.114.3` / `20.205.243.166` 两个 IP 都探测不通）⇒ 走「DoH 拿 IP + `http.curloptResolve` 绕 DNS + 持续重试」的老路 |
| 已在跑 | ✅ `/tmp/push_v126.sh` 后台持续重试（每 15s 一次 DoH + 探测 + 推送）；**判据 = 远端回读**（`ls-remote` 的 `refs/heads/main` 与 `refs/tags/v0.126.0^{}`），**不信 `git push \| tail` 的退出码**（它恒为 0，失败会伪装成成功） |
| token 卫生 | ✅ 推完仍要 `sed -i -e '/ghp_/d' -e '/GH_TOKEN/d' ~/.bash_history`；**本轮推送前自查 5 处严格形态（`ghp_[A-Za-z0-9]{20,}`）全 0**：`~/.bash_history` 0 / `~/.gitconfig` 0 / 仓库 0 / `/tmp` 0 / memory 目录 0；`remote.origin.url` 不带 token |

### 上一轮：V0.125.0（2026-11-10 发版）

| 项 | 状态 |
|---|---|
| 内容 | ✅ **首页「今日市场研究报告」入口** —— 用户诉求：「在首页提供一个今日市场研究报告的连接，**只显示最新的那份上传报告**」。本版交付：新端点 `GET /api/v1/reports/latest`（**只返回最新上传的那一份**，不是列表）+ 首页新增 `.home-report` 条带（标题 / 日期 chip / 分类·大小·上传于 / 摘要 / 「查看报告 →」/「全部报告 →」）+ 3 语 i18n（`home.report_*` **7 键**） |
| 口径决策 | ✅ **「最新」= 最新上传**（`created_at` 倒序 + `id` 兜底），**不是**报告自身日期最新 —— 补录旧报告是常态，按 `report_date` 排会把刚拿到的那份挤下去。排序口径**只在仓储层写一份**，列表与 latest 共用 ⇒ 首页那份**永远**是存档列表第一行（有一条测试钉住这个不变式） |
| 空库契约 | ✅ `200 {"item": null}`（**不是 404**）—— 首页要能区分「还没上传过」（正常）与「接口挂了」（降级）；前端用 `hasOwnProperty(payload,'item')` 判定，**绝不把故障说成空库** |
| 安全关键点 | ✅ 报告本体走 `/api/v1/reports/{id}/content`（响应带 **CSP sandbox** ⇒ opaque origin）⇒ 只能 `<a target="_blank" rel="noopener noreferrer">` **新标签页**打开，**不能 iframe、不能 fetch 完塞 innerHTML** |
| 🐛 顺带修掉的真缺陷 | ① **i18n 门禁的扫描盲区** —— `scripts/check_i18n_keys.py` 此前只扫 `i18n: "k"` / `I18n.t('k')` / `tr('k')` / `T('k')` **4 种**形式，**漏掉小写 `t('k')`** —— 而 home.js / ask.js / auth.js / favorites.js / report-archive.js **5 个文件**都定义了小写包装器 `t(key, fallback)` ⇒ 这 5 个文件的 key **完全不在门禁视野内**（漏 zh-TW/en-US 不报错，运行时悄悄显示中文）。补上后实测：in-scope **501 → 582（+81）**，其中**唯一真缺失**是 `ai.streaming`（ask.js:829，三语都缺 ⇒ en-US/zh-TW 一直在显示中文兜底串）—— **已补齐 3 语**；② **`created_at` 是 UTC 而前端当本地时间解析** —— SQLite 的 `CURRENT_TIMESTAMP` 是 UTC（实测与 `date -u` 逐秒相同），SQLAlchemy 读回是 naive datetime ⇒ Pydantic 输出 `"2026-11-08T22:15:34"`（**不带 Z**）⇒ `new Date(...)` 按本地时间解析 ⇒ **显示值比真实时刻早 8 小时** ⇒ 首页改用显式的 UTC 解析器（实测：报告 id=20 真实上传时刻 = BJT 11-09 06:15，不补 `'Z'` 会显示成 11-08 22:15） |
| 已知遗留（未做） | ⚠ `static/report-archive.js::fmtBjt` **仍是本地时间解析** ⇒ 存档页「上传于」**比真实时刻早 8 小时**（改它要连带重验 `_verify_report_archive.mjs` 的既有断言 ⇒ 单独立一轮） |
| 🔧 顺带修好的**既有坏门禁** | ✅ `scripts/_verify_nav_8.mjs` **间歇性挂死** —— 根因（**抓 CDP 原始事件实测**）：`/static/*.html` 响应头无 `Cache-Control` ⇒ Chrome 启发式缓存 ⇒ **主文档命中磁盘缓存时 Chrome 不发 `Page.lifecycleEvent`** ⇒ puppeteer 的 `waitUntil`（`domcontentloaded`/`load`/`networkidle0`/`networkidle2` **全都**）永不 settle ⇒ `page.goto` 无限期挂死（挂起时页面其实早已加载完）。⚠ **与本版改动无关**（换回 HEAD 静态文件 + 重启服务后照样挂）；⚠ 初版把根因写成「SW 拦截」是**错的** —— LAN 入口非安全上下文 ⇒ `navigator.serviceWorker` 为 `undefined` ⇒ SW 根本不参与。⇒ 修法：`setCacheEnabled(false)`（**本项目既有惯例**，`_verify_money_flow.mjs` 等 5 个门禁早有）+ `domcontentloaded` + 每断言点 `waitForSelector` ⇒ **连跑 4 次 27 passed / 0 failed** |
| 🔧 附带修好的**第二个**不稳定源 | ✅ **限流假红** —— 服务端按 IP 做 60s 滑动窗口限速（`RATE_LIMIT_PER_MIN=600`），而**首页一次加载打 ~20 个 `/api/v1/favorites/exists/{external_id}`** ⇒ 5 个首页门禁连着跑就把真实 IP 的额度耗光 ⇒ **429** ⇒ 跟被测功能无关的断言（i18n 文案 / chip）跟着挂（实测 4 次连跑里挂了 3 次）。⇒ 本轮 5 个门禁各配一个**独立限流桶**（`X-Forwarded-For` 假 IP；服务端**只对限流**信任它，认证默认不看：`trust_proxy_headers=False`）。⚠ **首页那 20 个请求本身是真问题**（用户刷新几次就可能撞 429）⇒ 批量 favorites 查询端点属应用层改动，**另立一轮** |
| `__version__` | ✅ 已 bump 到 `0.125.0`（4 处同步：`__init__.py` / `pyproject.toml` / `uv.lock` / `sw.js`） |
| 迁移 | ✅ **零 schema 变更、零 alembic 迁移、零生产库写入** |
| 静态资源 | ⚠ **改了 `static/home.html` + `static/home.js` + 3 个 `static/i18n/*.js`** ⇒ 按 V0.100.1 规则**必须 bump `sw.js` VERSION**（本轮已 bump 到 `v0.125.0`）；⚠ 新条带刻意**不进** `.home-scenes` 网格 —— 那 8 张是 260px 纯链接磁贴，且 **4 个门禁脚本硬编码「场景卡 = 8 张」** ⇒ 独立 `<section>` 零断言改动 |
| 测试 | ✅ `tests/test_api/test_reports.py` **43 passed**（**6 条新增**：路由顺序不被 `/{report_id}` 吞掉 / 空库返回 `item=null` / 返回刚上传那份 / **上传时间 ≠ 报告日期** / **首页那份 == 存档列表第一行** / 多用户隔离） |
| 门禁 | ✅ `check_version_sync`（4 处版本号 + CHANGELOG 降序 + 里程碑登记 + 基线）/ `check_i18n_keys`（**0 missing / 582 in-scope**）/ `check_pwa_assets`（SW `v0.125.0` == 应用版本，54 条 SHELL_ASSETS）/ `check_static_js`（22 页 + 39 脚本）/ `check_docs_claims`（149 处端点引用全部可在 `app.openapi()` 找到） |
| 稳定性复测 | ✅ **5 个首页门禁 × 连续 4 次 = 20/20 全绿**（`_verify_nav_8` 27/0 ×4、`_verify_home_report` **49**/0 ×4、`_verify_home_metals` 39/0 ×4、`_verify_home_verdict` 55/0 ×4、`_verify_report_archive` 43/0 ×4）。⚠ **修之前的对照组**：同一串命令下 `_verify_home_report` 4 次挂 1 次、`_verify_home_verdict` 4 次挂 2 次 ⇒ **一次绿不算数，连跑不翻才算** |
| 文档 | ✅ 新增**第 11 份里程碑文档 M10 · 首页研报入口（V0.125）**（`docs/releases/milestones/m10-home-latest-report-v0.125.md`）+ 登记进 [docs/releases/index.md](releases/index.md)；[docs/api-reference.md](api-reference.md) §5 **补上此前整段缺失的 9 个报告端点** |
| 服务 | ✅ **已用 systemd 重启**（`sudo systemctl restart gold-etf-analyzer.service`）⇒ `/openapi.json` → `info.version = **0.125.0**`；线上实测 `GET /api/v1/reports/latest` → `{"item": {"id": 21, "report_date": "2026-11-10", "view_url": "/api/v1/reports/{id}/content"（实际 id=21）…}}`，且 `GET /api/v1/reports?limit=3` 的**第一行同样是 id=21** ⇒ 不变式在线上成立（⚠ `id` 逐日递增：每日 BJT 06:15 自动上传一份 ⇒ 不变式由测试 + 门禁钉住，不依赖具体 id） |

#### 推送状态：✅ **已推送**（`refs/heads/main` + tag `v0.125.0`）

**结论先行：代码、门禁、文档、提交、tag 全部就绪，且已全部推到 GitHub。**

| 项 | 远端 | 本地 | 一致 |
|---|---|---|---|
| `refs/heads/main`（**发版那一刻**） | `a99f214` | `a99f214` | ✅ |
| tag 数（去掉 `^{}` 行） | **122** | **122** | ✅ |
| `refs/tags/v0.125.0` | tag 对象 `4136cd6d` | `4136cd6d` | ✅ |
| `refs/tags/v0.125.0^{}` | `a99f214` | `a99f214` | ✅（tag 指向**发版** commit；其后这条「推送状态」commit 会再推一次 ⇒ 远端 main 与本地 HEAD 始终相等） |

> 📌 **判据不是「`git push` 没报错」**，而是**远端回读** —— `git push | tail` 的退出码恒为 0
> ⇒ 失败会被伪装成成功。本轮 `git push origin main v0.125.0` 的**真实退出码为 0**
> （不接管道，直接取 `$?`），且回读 `refs/heads/main` 与本地 HEAD 相等、
> tag 对象与 `^{}` 行都相等、远端 tag 数与本地相等。
>
> ⚠️ **annotated tag 在 `ls-remote` 里占两行** —— `refs/tags/v0.125.0` 是 **tag 对象**的 SHA，
> `refs/tags/v0.125.0^{}` 才是它指向的 **commit** SHA。统计数量必须把 `^{}` 行去掉再数。
>
> ⚠️ **main 的 SHA 故意不写死在这条判据里**：写进去的那条 commit 自己就会推动 HEAD ⇒ 判据当场失效。
> 上表里的 `a99f214` 是**发版那一刻**的读数（＝ tag 的 `^{}`，可以写死）；
> **当前**的远端 main 用 `git ls-remote origin refs/heads/main` 与 `git rev-parse HEAD` 对比。

**这次推送前踩到的一个前置**（实测过）：

| 前置 | 实测 | 结论 |
|---|---|---|
| **网络** | `curl -s -m 15 https://github.com/` → **HTTP 200**（0.85s） | ✅ 通道正常（不必用 DoH + `http.curloptResolve` 绕路） |
| **凭据** | gh keyring 里**只有一枚 fine-grained PAT** ⇒ `git push --dry-run` **403**（`Permission to surui1981/gold-etf-analyzer.git denied to surui1981`） | ⚠️ **只有 classic PAT（`ghp_` 前缀）能 push**（本轮用的是用户在 chat 提供的一枚 classic PAT） |
| **credential helper** | `git config --get credential.helper` 为空 ⇒ git 不知道去哪拿凭据 | ⚠️ **必须先配** `credential.https://github.com.helper = '!gh auth git-credential'`（`gh auth git-credential` 会**优先读 `GH_TOKEN`**）。⚠️ 本轮发现 **global 与 local 各有一条** ⇒ helper 被调两次 ⇒ 已 `git config --local --unset-all` 去掉重复，只留 global 那条 |

> 🔐 **凭据卫生**：推送走 **`GH_TOKEN` 环境变量 + `gh auth git-credential`**
> ⇒ token **不进 argv、不落盘、不进 `remote.origin.url`**；
> 推完立刻 `sed -i -e '/ghp_/d' -e '/GH_TOKEN/d' ~/.bash_history`，
> 并复查 5 处 token 痕迹（严格形态 `ghp_[A-Za-z0-9]{20,}`）：
> `~/.bash_history` **0** / `~/.gitconfig` **0** / 仓库（含未跟踪）**0** / `/tmp` **0** / memory 目录 **0**
> ⇒ **全部干净**；`git config --get remote.origin.url` 仍是**不带 token** 的
> `https://github.com/surui1981/gold-etf-analyzer.git`。
>
> ⚠️ **这枚 classic PAT 在 chat 里明文出现过** ⇒ **已算泄露**。
> 本地已清理的都是**可清理的**；会话记录（`.claude/projects/…/*.jsonl`）里的副本**清不掉**
> ⇒ **只能靠轮换**。（本轮的 push **一次过、未触发 auto-mode 分类器**
> ⇒ 没有产生新的含 token 转储副本；会话目录里现存的 `auto-mode-classifier-error.txt`
> 是 2026-11-09 的旧转储，**不含本轮 token**。）

### 上一轮：V0.124.0（2026-11-09 发版）

| 项 | 状态 |
|---|---|
| 内容 | ✅ **宏观面 35% 的第一次真正测量**（roadmap C6 收口）—— 此前生产库 `daily_macro_factors` 只有 **201 天**、4 个低频因子不足 33 行 ⇒ h=60 非重叠采样只剩 ~3 个样本 ⇒ **连测量资格都没有**。本版交付三样东西：① **历史深度**：新建纯 Python 重建模块 `src/app/services/macro_history.py`（point-in-time 单一真源，生产回填与证据脚本**共用**）⇒ 生产库补到 **20 086 行**（11 因子 × 5 年 × **日历日**，2021-11-10 → 2026-11-09，每因子 1826 行）；② **第一次真正的三问复测**（生产真实打分口径 + 20 年重建 + h=60/20 + GLD/518880）：**16 个读数全部未过线**（`macro_all` / `macro_daily` / `macro_lowfreq` / `zscore_all` 候选）⇒ 宏观面 35% 是「**描述当下**」的读数，**不是前瞻指标** ⇒ **权重与因子方向一律不动**（roadmap C6 明令）；③ **可复算**：新增 `scripts/verify_macro_face.py` + 共用管线 `scripts/_evidence_core.py`（V0.123.0 的 `verify_flow_face.py` 改为从它导入，**13 条旧测试全绿**）+ **23 条离线测试** |
| 🐛 顺带修掉的 2 个生产缺陷 | ① **`sqlite3.OperationalError: too many SQL variables`** —— 深回填一次要写 2 万行 × 6 绑定变量 = **12 万变量**，远超 SQLite 的 `SQLITE_LIMIT_VARIABLE_NUMBER`（本机实测 **32766**）⇒ 单语句**整批回滚、零行落库**（不是「写了一半」）⇒ 改为按 `UPSERT_CHUNK_SIZE = 1000` 行分块写；② **窗口第一天整行缺失** —— Yahoo 是**唯一按窗口取数**的源（H.15 / FRED / Eurostat 都是全量历史）⇒ 窗口第一天的「当时能拿到的最新读数」必须来自窗口**之前**的一次观测 ⇒ 新增 `YAHOO_LOOKBACK_DAYS = 30` |
| X1 / X2 交叉验证 | ✅ **X1 绿**：脚本重建 ≡ 生产表**逐行相等**（**20 086 行相同 / 不同 0 / 只在一侧 0**）⇒ 证明脚本量的是**生产口径**；✅ **X2 有效**：撤销 point-in-time（把可得日退回观测日）⇒ 重叠区间内 **17 540 行不一致**（相同仅 2 546）⇒ 前视守卫能判红。⚠ X1 判据在比对**两窗口的交集**（脚本测 20 年 / 生产表 5 年 ⇒ 脚本独有的行不是不一致） |
| roadmap C6 | ✅ **关闭**：C6「宏观面缺短周期择时力」原为 ⚪（前置是补历史深度）⇒ 现已实测 ⇒ 16 个读数**通过 0 项** ⇒ 结论「宏观面描述当下、不预测」⇒ **权重不动、因子方向不动**；唯一机械过线的单因子（`macro_daily`·GLD·h=20，`pc_fwd +0.1975`、`p=0.002`）**比值 1.20 < 1.3 仍不过线** ⇒ 不构成 roadmap 触发条件 |
| 线上分数影响 | ✅ **已实测、不藏**：宏观面 **45.8 → 45.5（−0.3）**；综合指数 **42.2 → 42.2（0.0）**（⚠ 同一份行情快照下的前后对照；**综合指数本身还会随金价动** —— 发版时线上读数已是 38.9，而**宏观面仍是 45.5**）；逐因子 `us10y −3.0` / `us30y −2.1` / `real10y +0.8` / `dxy −0.6`（**触底被 0 截断**）/ 其余 7 个不变 |
| `__version__` | ✅ 已 bump 到 `0.124.0`（4 处同步：`__init__.py` / `pyproject.toml` / `uv.lock` / `sw.js`） |
| 迁移 | ✅ **零 schema 变更、零 alembic 迁移**；但**有生产库写入**（`daily_macro_factors` +19 660 行，**写前已备份** ⇒ 备份在 `data/backups/`） |
| 静态资源 | ⚠ **只改了 `static/sw.js` 的 `const VERSION`**（未改任何 `static/*.html|js|css` 内容）⇒ 按 V0.100.1 仍换代，但**无需清 SW 缓存内容** |
| 测试 | ✅ `tests/test_scripts/test_verify_macro_face.py`（**23**）+ `tests/test_scripts/test_verify_flow_face.py`（**13**，V0.123.0 安全网）+ `tests/test_services/test_macro_history.py` + `tests/test_services/test_macro_backfill.py`（+2 回看余量）+ `tests/test_repositories/test_macro_factor_history.py`（+2 分块）⇒ 全绿 |
| 反向验证 | ✅ **5 个变异点全部变红**：① 关掉分块 ⇒ 重现 `too many SQL variables` ② 去掉 Yahoo 回看 ⇒ 窗口第一天缺 1 行（X1 转红）③ 撤销 point-in-time ⇒ X2 判红（17 540 行不同）④ 静态带按符号取反 ⑤ 滚动带方向翻转。**X1 判据自身也反向验过**：把 `DATABASE_URL` 指回回填前的备份库 ⇒ X1 报 1278 处不同、退出码 1 |
| 文档 | ✅ 新增**第 10 份里程碑文档 M9 · 宏观面证据复算（V0.124）**（`docs/releases/milestones/m9-macro-face-evidence-v0.124.md`）+ 登记进 [docs/releases/index.md](releases/index.md)；[docs/roadmap.md](roadmap.md) §〇 指针 + §三·C6 段落改成**实测结论** + §六「已完成」登记本条 |
| 服务 | ✅ **已用 systemd 重启**（`sudo systemctl restart gold-etf-analyzer.service`）⇒ `/openapi.json` → `info.version = **0.124.0**`；线上宏观面 11 个因子**全部 `tier=live`**（无一条退回静态兜底） |

#### 推送状态：✅ **已推送**（`refs/heads/main` + tag `v0.124.0`）

**结论先行：代码、门禁、文档、提交、tag 全部就绪，且已全部推到 GitHub。**

| 项 | 远端 | 本地 | 一致 |
|---|---|---|---|
| `refs/heads/main` | `8a4d908` | `8a4d908` | ✅ |
| tag 数（去掉 `^{}` 行） | **121** | **121** | ✅ |
| `refs/tags/v0.124.0` | tag 对象 `75d2062` | `75d2062` | ✅ |
| `refs/tags/v0.124.0^{}` | `8a4d908` | `8a4d908` | ✅（tag 指向**发版** commit；其后这条「推送状态」commit 会再推一次 ⇒ 远端 main 与本地 HEAD 始终相等） |

> 📌 **判据不是「`git push` 没报错」**，而是**远端回读** —— `git push | tail` 的退出码恒为 0
> ⇒ 失败会被伪装成成功。本轮 `git push origin main v0.124.0` 的**真实退出码为 0**，
> 且回读 `refs/heads/main` 与本地 HEAD 相等、tag 对象与 `^{}` 行都相等。
>
> ⚠️ **annotated tag 在 `ls-remote` 里占两行** —— `refs/tags/v0.124.0` 是 **tag 对象**的 SHA，
> `refs/tags/v0.124.0^{}` 才是它指向的 **commit** SHA。统计数量必须把 `^{}` 行去掉再数。
>
> ⚠️ **main 的 SHA 故意不写死在这条判据里**：写进去的那条 commit 自己就会推动 HEAD ⇒ 判据当场失效。

**这次推送前踩到的一个前置**（实测过）：

| 前置 | 实测 | 结论 |
|---|---|---|
| **网络** | `curl -sI https://github.com` → **HTTP/2 200**；DNS → `20.205.243.166`；`git ls-remote` 通 | ✅ 通道正常（不必用 DoH + `http.curloptResolve` 绕路） |
| **凭据** | gh keyring 里**只有一枚 fine-grained PAT** ⇒ `git push` **403**（`Permission to surui1981/gold-etf-analyzer.git denied`）；`GET /repos/…` 的 `permissions` 显示 `push: true` —— **那是用户角色，不是 token 权限** | ⚠️ **只有 classic PAT（`ghp_` 前缀）能 push**（本轮用的是用户在 chat 提供的一枚 classic PAT） |

> 🔐 **凭据卫生**：推送走 **`GH_TOKEN` 环境变量 + `gh auth git-credential`**
> ⇒ token **不进 argv、不落盘、不进 `remote.origin.url`**；
> 推完立刻 `sed -i -e '/ghp_/d' -e '/GH_TOKEN/d' ~/.bash_history`，
> 并复查 5 处 token 痕迹（严格形态 `ghp_[A-Za-z0-9]{20,}`）：
> `~/.bash_history` **0** / `~/.gitconfig` **0** / 仓库（含未跟踪）**0** / `/tmp` **0** / memory 目录 **0**
> ⇒ **全部干净**；`git config --get remote.origin.url` 仍是**不带 token** 的
> `https://github.com/surui1981/gold-etf-analyzer.git`。
>
> ⚠️ **这枚 classic PAT 在 chat 里明文出现过** ⇒ **已算泄露**。
> 本地已清理的都是**可清理的**；会话记录（`.claude/projects/…/*.jsonl`）里的副本**清不掉**
> ⇒ **只能靠轮换**。（本轮未触发 auto-mode 分类器 ⇒ 没有新的
> `auto-mode-classifier-error.txt` 转储副本。）

### 上一轮：V0.123.0（2026-11-09 发版）

| 项 | 状态 |
|---|---|
| 内容 | ✅ **资金流面证据复算（零生产代码改动）** —— 把 V0.122.0 的结论拿到**生产真实打分口径**（0~100 截断分 + 滚动分位带）上重测。① **单因子证据逐位复现**：GLD 年内五分位 Q1 − Q5 = **+5.835pp**、三段 **+10.463 / +4.864 / +1.747pp** 全部为正 ⇒ **`cot_gold_net` 的负号（拥挤度口径）保留，不回滚**；② ⚠ **订正 V0.122.0 的一处推论**：「改号后资金流面 composite 前瞻主导」**不成立** —— 现状/改号前 × GLD/518880 四组**三问全不过**（功效 / 比值 > 1.3 / 三段同向）⇒ 资金流面 composite 是「当下资金状态」的读数，**不是前瞻指标**（当初错在：用了 z 分数而非 0~100 打分，且面内权重最大的 `gold_etf_flow`（22%）依赖的上交所份额序列当时是坏的）；③ 新增**可复算证据脚本** `scripts/verify_flow_face.py`（含 `--cache` 离线模式）+ **13 条离线测试** `tests/test_scripts/test_verify_flow_face.py` 守住它的分析口径（脚本依赖外网 ⇒ 不在 CI 门禁集，口径靠测试守） |
| 🐛 顺带修掉的 4 个口径缺陷 | ① **静态兜底带按符号取反**（负号因子在样本不足段方向整个反过来 —— 服务里 `hardcode[key] = (rule["best"], rule["worst"])` **不带符号**，符号只决定**滚动分位**里 P10/P90 谁当 best）② 滚动带为空时索引类型不是 datetime ⇒ `reindex(method="ffill")` 抛 `TypeError` ③ 「观测点」= 按索引去重（索引本来就唯一 ⇒ 等于没去重）⇒ 改成**值变化点** ④ 因子与价格日历不同 ⇒ 前瞻窗口取**并集行数**（GLD 的「60 交易日」其实是 60 个 A 股交易日）⇒ 改成按**标的自己的日历**取窗 |
| roadmap C5/C6/C7 | ✅ 三条待办给出**可复算结论**：**C5**（面内离散度）❌ **不进规则表**（两个标的都不过三问）· **C6**（宏观面缺短周期择时力）⚪ **先补历史深度**（生产库 `daily_macro_factors` 仅 **200 天**、11 个因子里 4 个不足 15 行 ⇒ h=60 非重叠采样只剩 ~3 个样本 ⇒ **连测量资格都没有**）· **C7**（共识度独立维度）❌ **不新增维度**（5 个候选读数无一同时过三问；唯一机械过线的是在册因子的水平代理 ⇒ 进表即**重复计权**） |
| `__version__` | ✅ 已 bump 到 `0.123.0`（4 处同步：`__init__.py` / `pyproject.toml` / `uv.lock` / `sw.js`） |
| 迁移 | ✅ **零 schema 变更、零 alembic 迁移、零生产库写入**（只动 `scripts/` + `tests/` + `docs/` + `static/sw.js` 的 VERSION 常量） |
| 静态资源 | ⚠ **只改了 `static/sw.js` 的 `const VERSION`**（未改任何 `static/*.html|js|css` 内容）⇒ 按 V0.100.1 仍换代，但**无需清 SW 缓存内容** |
| 测试 | ✅ `pytest tests/test_scripts/test_verify_flow_face.py` → **13 passed**；`python scripts/verify_flow_face.py --cache data/verify/flow_face_cache.pkl` → **结果：2 passed**（退出码 0） |
| 门禁缺口 | ✅ 顺带补上两处**会让 CI 变红**的缺口：① 新测试直接 `import numpy / pandas` ⇒ `check_deps.py` 判红（该门禁只扫 `src/` 与 `tests/`）⇒ `dev` extra 补声明（两者运行时本就由 akshare 传递带入 ⇒ **不增加安装体积**）+ `uv lock` 同步；② `tests/test_services/test_scoring_wide.py` 的 `ruff format` 失败是 **V0.121.3 hotfix 引入的预存红**（本版之前 main 就是红的）⇒ 纯格式化修掉，**零行为变化**。本版起 `ruff check` / `ruff format --check` 全绿 |
| 反向验证 | ✅ **6 个变异点**全部变红（静态带翻转 / 滚动带方向 / 五分位方向 / 五分位边界 pos·n / 不做日历对齐 / 观测点=全部行）⇒ 恢复后 13 passed |
| 文档 | ✅ 新增**第 9 份里程碑文档 M8 · 资金流面证据复算（V0.123）**；M7 里加**订正框**（订正推论、不订正符号）；[docs/composite-trend-index.md](../docs/composite-trend-index.md) 加「资金流面 composite 的定位」小节；[docs/roadmap.md](../docs/roadmap.md) §〇 指针 + C5/C6/C7 三条处置 |
| 服务 | ✅ **已用 systemd 重启**（`sudo systemctl restart gold-etf-analyzer.service`）⇒ `/openapi.json` → `info.version = **0.123.0**`（本版**零生产代码改动**，重启只为让版本号与代码一致） |

#### 推送状态：✅ **已推送**（`refs/heads/main` + tag `v0.123.0`）

**结论先行：代码、门禁、文档、提交、tag 全部就绪，且已全部推到 GitHub。**

| 项 | 远端 | 本地 | 一致 |
|---|---|---|---|
| `refs/heads/main` | `bff3371` | `bff3371` | ✅ |
| tag 数（去掉 `^{}` 行） | **120** | **120** | ✅ |
| `refs/tags/v0.123.0` | tag 对象 `c7ae5b4` | `c7ae5b4` | ✅ |
| `refs/tags/v0.123.0^{}` | `bff3371` | `bff3371` | ✅（tag 指向**发版** commit；其后这条「推送状态」commit 会再推一次 ⇒ 远端 main 与本地 HEAD 始终相等） |

> ⚠️ **main 的 SHA 故意不写死在这条判据里**：写进去的那条 commit 自己就会推动 HEAD ⇒ 判据当场失效。
> 首推时远端读到 `bff3371`（= 当时的 HEAD）；其后这条「推送状态」commit 再推一次 ⇒ **远端 main 与本地 HEAD 始终相等**。
>
> ⚠️ **annotated tag 在 `ls-remote` 里占两行** —— `refs/tags/v0.123.0` 是 **tag 对象**的 SHA，
> `refs/tags/v0.123.0^{}` 才是它指向的 **commit** SHA。统计数量必须把 `^{}` 行去掉再数。
>
> 📌 **判据不是「`git push` 没报错」**，而是**远端回读** —— `git push | tail` 的退出码恒为 0
> ⇒ 失败会被伪装成成功。本轮两次 `git push` 的**真实退出码均为 0**，且回读 `refs/heads/main` 与本地 HEAD 相等。

**这次推送前踩到的两个前置**（都实测过）：

| 前置 | 实测 | 结论 |
|---|---|---|
| **网络** | DNS 解析 `github.com` → `20.205.243.166` 成功；`curl -sI https://github.com` → **HTTP/2 200**；SSH 22 与 `ssh.github.com:443` 均通 | ✅ 通道正常（不必再用 DoH + `http.curloptResolve` 绕路） |
| **凭据** | gh keyring 里**只有一枚 fine-grained PAT** ⇒ `git push` **403**（`Permission to … denied`）、`PATCH git/refs/heads/main`（同 SHA 的 no-op）也 **403** `Resource not accessible by personal access token`；而 `GET /repos/…` 的 `permissions` 字段显示 `push: true` —— **那是用户角色，不是 token 权限** | ⚠️ **只有 classic PAT（`ghp_` 前缀）能 push**（本轮用的是用户在 chat 提供的一枚 classic PAT） |

> 🔐 **凭据卫生**：推送走 **`GH_TOKEN` 环境变量 + `gh auth git-credential`**
> ⇒ token **不进 argv、不落盘、不进 `remote.origin.url`**；
> 推完立刻 `sed -i -e '/ghp_/d' -e '/GH_TOKEN/d' ~/.bash_history`，
> 并复查 5 处 token 痕迹（严格形态 `ghp_[A-Za-z0-9]{20,}`）：
> `~/.bash_history` **0** / `~/.gitconfig` **0** / 仓库（含未跟踪）**0** / `/tmp` **0** / memory 目录 **0**
> ⇒ **全部干净**；`git config --get remote.origin.url` 仍是**不带 token** 的
> `https://github.com/surui1981/gold-etf-analyzer.git`。
>
> ⚠️ **这枚 classic PAT 在 chat 里明文出现过** ⇒ **已算泄露**。
> 本地已清理的都是**可清理的**；会话记录（`.claude/projects/…/*.jsonl`）与几份
> `auto-mode-classifier-error.txt` 错误转储里的副本**清不掉** ⇒ **只能靠轮换**。
> （用户已计划**周五轮换**。）

### 上一轮：V0.122.0（2026-11-08 发版）

| 项 | 状态 |
|---|---|
| 内容 | ✅ **资金流面 `cot_gold_net` 符号治本（拥挤度口径）** —— 起因是用户框架「衡量金价 / 对比当前评估参数有什么数值改进措施 / 考虑一个核心标的 / **资金的共识才是投资的价值**」⇒ 落到可执行一步（用户拍板「先修已确认的符号缺陷」+「核心标的 = COMEX/GLD 美元金价」）。实测判定「净多占 OI 越高越利多黄金」**方向反了**（GLD 年内五分位：Q1 前瞻 60 交易日 **+6.45%** vs Q5 **+0.62%** ⇒ 差 **5.84pp**；三个子区间同向）⇒ 符号 `+` → `−`，静态带 `best`/`worst` 对调（best = P10 = 6.49% / worst = P90 = 34.10%），**权重 18% 不动** |
| ⚠ 两条独立代码路 | 静态带（`best`/`worst`）与**滚动分位**（`services/macro_thresholds.py` 读 `positive` 决定 P90/P10 谁当 best）是**两条路** ⇒ 必须同改，否则滚动分位一接管就把符号翻回去 |
| 测量方法 | ✅ 入库：**年内去均值**（年份固定效应）+ **非重叠采样** + **控制当期金价水平** + **前瞻/回看对称性检验**；证据可用 `python scripts/verify_cot_sign.py` 复算（需联网，不在 CI 门禁集） |
| 证据边界 | ✅ 同时写进源码模块文档（不是只写注释）：**单因子本身不通过对称性检验**（h=60：前瞻 +0.027 vs 回看 +0.168）· 效果**逐年衰减**（2023-26 段相关≈0，518880 该段**反向** −2.08pp）· 短窗 h=20/30 改善不出现 ⇒ 拥挤度口径**近期偏弱** |
| `__version__` | ✅ 已 bump 到 `0.122.0`（4 处同步：`__init__.py` / `pyproject.toml` / `uv.lock` / `sw.js`） |
| 迁移 | ✅ **零 schema 变更、零 alembic 迁移**（只改符号与阈值带方向）⇒ 回滚代价低 |
| 静态资源 | ⚠ **改了 `static/help.js` + `static/weights.html`** ⇒ 按 V0.100.1 **必须** bump `sw.js` 的 `VERSION` 到 `v0.122.0`（已做） |
| 测试 | ✅ `tests/test_services/test_money_flow_service.py` + `tests/test_services/test_macro_thresholds.py` → **58 passed**；新增 2 条守卫测试（静态带方向 vs `positive` 不变式 · 滚动分位路径方向一致）+ 改写 1 条原本**隐含绑着符号**的旧测试 |
| 反向验证 | ✅ 撤 `best`/`worst` 对调 ⇒ **3 条红**；破坏 `macro_thresholds.py` 负号分支 ⇒ **4 条红**（含新增的滚动路径测试）⇒ 恢复后全绿 |
| 服务 | ✅ **已用 systemd 重启**（`sudo systemctl restart gold-etf-analyzer.service`）⇒ `/openapi.json` → `info.version = **0.122.0**` |
| 线上实测 | ✅ `192.168.0.204:8888/api/v1/market/gold/ny-trend?days=60` → 资金流面 47.4/100；`cot_gold_net` = **25.9574 %**（data_date 2026-11-03，tier=live）→ **score 77.1 / bullish / 权重 18% / 贡献 13.88**。**符号翻转在线上可观测**：用生产库复算滚动窗口（728 天 / 104 个周频样本）得 **p10 = 22.8774、p90 = 36.3515** ⇒ 负号口径 `(v−p90)/(p10−p90)×100 = **77.14**`（与线上 77.1 一致）；**旧的正号口径会给出 22.86** ⇒ 改号确实在生效，不是巧合 |
| 综合指数 | ✅ `index` = **36.4**、level `down`、direction `bearish`；summary「= 技术面 16.8×33% + 宏观参考 45.7×47% + 资金流面 47.4×20%（消息面未打分，综合指数待定；已剔除并按剩余面权重归一化）」⇒ 资金流面在「消息面缺席」时被提到 20% 权重（名义 15%） |
| git tag | ✅ `v0.122.0`（annotated，指向 `904654c`）**已创建并已推送**；远端 tag 数 **119 = 本地 119** ✅ |

#### 推送状态：✅ **已推送**（`refs/heads/main` + tag `v0.122.0`）

**结论先行：代码、门禁、文档、提交、tag 全部就绪，且已全部推到 GitHub。**

| 项 | 远端 | 本地 | 一致 |
|---|---|---|---|
| `refs/heads/main` | `904654c` | `904654c` | ✅ |
| tag 数（去掉 `^{}` 行） | **119** | **119** | ✅ |
| `refs/tags/v0.122.0^{}` | `904654c` | `904654c` | ✅（tag 指向**发版** commit，纯文档 commit 排在 tag 之后，与 `v0.121.3` / `v0.121.4` 先例一致） |

> ⚠️ **main 的 SHA 故意不写死在这条判据里**：写进去的那条 commit 自己就会推动 HEAD ⇒ 判据当场失效。
> 首次推送时远端读到 `904654c`（= 当时的 HEAD）；其后这条「推送状态」commit 会再推一次 ⇒ **远端 main 与本地 HEAD 始终相等**。
>
> ⚠️ **annotated tag 在 `ls-remote` 里占两行** —— `refs/tags/v0.122.0` 是 **tag 对象**的 SHA
> （本次 `bbafedd`），`refs/tags/v0.122.0^{}` 才是它指向的 **commit** SHA（`904654c`）。
> 统计数量必须把 `^{}` 行去掉再数：本地原始行数 **232** = 119 个 tag + 113 个 annotated 的第二行 ✅。

> 🔐 **凭据卫生**：推送走 **`GH_TOKEN` 环境变量 + `gh auth git-credential`**
> ⇒ token **不进 argv、不落盘、不进 `remote.origin.url`**；
> 推完立刻 `sed -i '/ghp_/d' ~/.bash_history`（并 `shred` 掉备份副本），
> 并复查 5 处 token 痕迹：`~/.bash_history` / `~/.gitconfig` / 仓库（含未跟踪）/ `/tmp` / memory 目录
> ⇒ **全部干净**（仓库与 memory 里只有裸前缀 `ghp_` 的形态说明，**没有完整 token**）。
>
> ⚠️ **这枚 classic PAT 在 chat 里明文出现过**（用户自己粘贴的）⇒ **建议用完即轮换**。
> 轮换是**唯一**能一次性作废所有副本的办法 —— 包括本次会话自身的记录文件（`.claude/projects/…/*.jsonl`）
> 与几份 `auto-mode-classifier-error.txt` 错误转储（里面也可能含该命令原文）。
> 本地已清理的都是**可清理的**；会话记录属于历史，**只能靠轮换**。
>
> 📌 **判据不是「`git push` 没报错」**，而是**远端回读** —— `git push | tail` 的退出码恒为 0
> ⇒ 失败会被伪装成成功。本轮 `git push` 的真实退出码 **0**，且回读 `refs/heads/main` 与本地 HEAD 相等。

### 上一轮：V0.121.4（2026-11-07 发版）

| 项 | 状态 |
|---|---|
| 内容 | ✅ **央行购金口径治本** —— 起因是用户诉求「世界黄金协会央行三季度购金 321 吨，写到主页」；核对时发现首页那个数（以及 `/central-bank` 的 KPI、宏观因子 `cb_gold`）**是重复计数算出来的**。根因：`central_bank_purchases` 表里同时住着**两类语义不同的行** —— **WGC 全球合计行**（含未披露国家的估算）与**各国明细行**（仅已披露国家）；旧代码算「季度合计」用的是**全表按季度求和** ⇒ **合计 + 明细** ⇒ 重复计数（2026Q2 实测：**336.7 = 合计 288.9 + 各国 47.8**）。且**从未有人质疑过它**，因为它看起来完全合理。修法：全球合计行用**独立伪 ISO `WGC_AGGR`** 标记，仓储 / 服务层一律「**有合计行就只取合计行，没有才退回各国之和**」，两者**永不相加**；`country_count` 与 `top_buyers()` **排除**合计行；前端堆叠图剔除合计行（明细表仍可见） |
| 取数链 | ✅ **报告版本逐版回退**（WGC 每年只发 q1/q2/q3，Q4 无独立报告页 ⇒ URL 404）：`q3 → q2 → q1 → 去年 q3 …`；**图表按结构签名识别**（合计图 = series 名 `Q1..Q4` 且类目轴是年份；国别图 = series 含 `Net purchases`/`Net sales` 且类目轴不是年份）⇒ 因为同一版报告里标题都含 "central bank" 的图有好几张，**只靠标题取图不会报错、只会静默换口径**。⚠ **Q3 2026 的 Chart 11 标题写着 "reported central bank purchases" 但它是按区域** ⇒ 结构签名把它正确排除；📌 **不伪造 Q3 国别明细**（Q3 报告只有区域图 ⇒ 最新国别仍是 Q2 2026 的 H1，23 国） |
| 🐛 **同批第二个缺陷** | ✅ **手工补丁覆盖了 WGC 自己的国别值** —— upsert 是「同键后写覆盖」，手工补丁排在最后 ⇒ 盖掉 WGC 数据。实测 UZB 2026 H1：WGC = **41.4 吨**，手工估读 = **4 吨**（差 10 倍）。修法：写入顺序改为「**全球合计 → 手工补丁 → 国别明细**」⇒ WGC 有数时以 WGC 为准 |
| 数值更正 | ✅ **2026Q3 = 321.2 吨**（WGC GDT Q3 2026 合计行）｜滚动 12 月 **842.6 → 885.1**（旧窗口 2025Q3–2026Q2，同窗口真值 **790.2**；新窗口 2025Q4–2026Q3 = 209.9 + 57.7 + 296.3 + 321.2）｜国家数 **25 → 24**（旧口径把「全球合计」当成一个国家）｜宏观因子 `cb_gold` 取 `t12m_total` ⇒ 随本次修正；`STATIC_REF` 兜底常量 **1019.0 → 885.1**（它此前也在撒谎） |
| `__version__` | ✅ 已 bump 到 `0.121.4`（4 处同步：`__init__.py` / `pyproject.toml` / `uv.lock` / `sw.js`） |
| 迁移 | ✅ **零 schema 变更、零 alembic 迁移**（只是多写一种 `country_iso` 的行）⇒ 回滚代价低 |
| 静态资源 | ⚠ **改了 `static/home.js` + `static/central_bank.html` + 3 语字典** ⇒ 按 V0.100.1 **必须** bump `sw.js` 的 `VERSION` 到 `v0.121.4`（已做） |
| 生产库写入 | ✅ **写前已备份**：`data/backups/gold_etf.v0121.4.20261107_155450.db`；ETL 导入 **149 行**（合计行 51 + 国别 H1 46 + 月报估读 52；其中 **2 行 UZB 被 WGC 覆盖** ⇒ 手工补丁不再压过 WGC，正是本次修复的效果） |
| 服务 | ✅ **已用 systemd 重启**（`sudo systemctl restart gold-etf-analyzer.service`）⇒ `/openapi.json` → `0.121.4` |
| 线上实测 | ✅ `192.168.0.204:8888`（服务已加载 V0.121.4）：`/central-bank/purchases` → `current_quarter = 2026Q3`、`current_quarter_total = **321.2**`（旧 336.7）、`t12m_total = **885.1**`（旧 842.6，同窗口真值 790.2）、`country_count = **24**`（旧 25）、`top_buyers[0] = POL 82.2`（合计行不在排名里）；首页卡 3「央行购金变化」主值 **+321.2**，副标题「数据截止 2026Q3 · 来源：世界黄金协会 GDT 全球合计」 |
| 测试 | ✅ `pytest tests/test_services/test_central_bank.py tests/test_repositories/test_central_bank_data.py tests/test_services/test_irfcl_fetcher.py` → **102 passed**；`check_pwa_assets` / `check_i18n_keys` / `check_static_js` 全绿 |
| 门禁 | ✅ 新增 `scripts/_verify_central_bank_aggregate.mjs`（**18 条**）；扩 `scripts/_verify_home_metals.mjs`（+6 条）⇒ 合计 **39 passed** / **18 passed** |
| git tag | ✅ `v0.121.4`（annotated，指向 `e431f80`）**已创建并已推送**；远端 tag 数 **118 = 本地 118** ✅ |

> **反向验证**（撤销 ⇒ 变红 ⇒ 恢复 ⇒ 变绿），共 **6 处**：
> 撤 `summary()` 的合计优先 ⇒ `test_summary_prefers_aggregate_over_country_sum` 变红；
> 撤 `t12m_total()` 的合计优先 ⇒ `test_t12m_total_prefers_aggregate` 变红；
> 撤 `top_buyers()` 的跳过 ⇒ `test_top_buyers_excludes_aggregate_row` 变红；
> 放宽国别图结构签名 ⇒ `test_regional_chart_is_not_country_level` 变红；
> 撤堆叠图剔除合计行 ⇒ `_verify_central_bank_aggregate.mjs` 退出码 1；
> 撤首页卡读 `WGC_AGGR` ⇒ `_verify_home_metals.mjs` 退出码 1。
> ⚠ **后两条必须重启服务**才测得到（浏览器门禁打的是**运行中的服务**）——
> 第一次做反向验证时因为**没重启**而「假绿」，这本身又是一次
> 「**门禁读到还没准备好的东西**」的复现。

#### 推送状态：✅ **已推送**（`refs/heads/main` + tag `v0.121.4`）

**结论先行：代码、数据库、服务、门禁、文档、提交、tag 全部就绪，且已全部推到 GitHub。**

| 项 | 远端 | 本地 | 一致 |
|---|---|---|---|
| `refs/heads/main` | == 本地 HEAD | == 本地 HEAD | ✅ |
| tag 数 | **118** | **118** | ✅ |
| `refs/tags/v0.121.4^{}` | `e431f80` | `e431f80` | ✅（tag 指向**发版** commit，纯文档 commit 排在 tag 之后，与 `v0.121.3` 先例一致） |

> ⚠ **main 的 SHA 故意不写死**：写进去的那条 commit 自己就会推动 HEAD ⇒ 判据当场失效。
> 首次推送时远端读到 `0bac4f0`（= 当时的 HEAD）；其后这条「推送状态订正」commit 会再推一次 ⇒ **远端 main 与本地 HEAD 始终相等**。

⚠ 判据**不是「`git push` 没报错」**，而是**远端回读** ——
本轮回读时 DNS 又断了一次（`Could not resolve host: github.com`），
靠 **DoH 拿 IP + `git -c http.curloptResolve=github.com:443:<IP>`** 才读到 tag 列表。

**卡住的那一环：凭据（不是网络）。** 实测证据链：

1. `git push origin main` → `remote: Permission to surui1981/gold-etf-analyzer.git denied` / HTTP **403**
2. `GET /repos/surui1981/gold-etf-analyzer` 的 `permissions` 字段
   → `{"admin": true, "push": true, ...}` —— **这是假的** ⚠
   那是**用户角色**，不是 token 权限
3. `PATCH /repos/.../git/refs/heads/main`（no-op，同一个 SHA，body 必须是合法 JSON）
   → HTTP **403** `Resource not accessible by personal access token` ⇒ 写路径确实没权限
   ⚠ 用 `-f force=false` 会先吃 **422**（`force` 不是 boolean）—— 那个 422 是「请求体没过」，
   **不是**「权限过了」，别把它当好消息
4. 同时 `git push` 的网络层是好的：DNS 正常、`https://github.com` → **200**、SSH 22/443 都通

⇒ 根因：**gh keyring 里只有一枚 fine-grained PAT（`github_pat_` 前缀），它没有写权限**；
**只有 classic PAT（`ghp_` 前缀）能 push**（classic 才带 `x-oauth-scopes: repo` 头）。

**本轮的实际推送方式**（用户在 chat 提供一枚 classic PAT，走**环境变量**，
token 不进 git 的 argv、不落盘、不进 `remote.origin.url`）：

```bash
export GH_TOKEN='<classic PAT>'
git -c credential.helper='!gh auth git-credential' push origin main
git -c credential.helper='!gh auth git-credential' push origin v0.121.4
unset GH_TOKEN
# 成功判据 = 远端回读（不是「命令没报错」）：
git ls-remote origin refs/heads/main refs/tags/v0.121.4
#   ⇒ refs/heads/main 应 == `git rev-parse HEAD` 的值
#     （⚠ 用 HEAD 而不是发版 commit：其后还排着纯文档 commit，写死 SHA 会把「推送成功」误判成失败）
#   ⇒ refs/tags/v0.121.4 的 ^{} 行应 == e431f80（tag 指向发版 commit，文档 commit 在其后）
```

📌 **推完已清 token 痕迹**（4 处自查全 0）：`~/.bash_history`（`ghp_` / `GH_TOKEN`）、
`~/.gitconfig`、仓库内（严格形态 `ghp_[A-Za-z0-9]{20,}`）、`/tmp`；
`git config --get remote.origin.url` 仍是**不带 token** 的
`https://github.com/surui1981/gold-etf-analyzer.git`。

⚠ 那枚 classic PAT 在 chat 里明文出现过 ⇒ **已算泄露 ⇒ 请立即轮换**。

### 上一轮：V0.121.3（2026-11-07 发版）

| 项 | 状态 |
|---|---|
| 内容 | ✅ **P0-2 收尾 hotfix** —— V0.121.2 发版后的**线上复测**发现「命中分析上涨天数」**没修干净**：`ScoringSummaryBucket` 这一个 schema 被**三个端点**共用（`/scoring/summary` / `/scoring/hit-stats` / `/scoring/hit-stats-all`），但桶聚合被**抄了三份**，V0.121.1 只改了 `summary()` 那一份 ⇒ 另外两份**漏填** `up_days` / `down_days` / `known_days` ⇒ Pydantic 用 schema 默认值 `0` 兜上 ⇒ **API 返回 0**。⚠ **0 与 null 语义不同**：前端只对 `known_days == null` 兜底「—」，`0` 会被**如实渲染**成「上涨 0 · 下跌 0」—— 正是 P0-2 要消灭的那种假结论。修法：抽出 `_bucket_direction_stats(rows) -> (up, down, known)`，**三处统一走它**（口径只剩一份，改一处即改三处）。**零 schema 变更、零迁移** |
| 数据回填 | ✅ 宽表按**补齐后**的价格日历重算（`scripts/backfill_scoring_wide.py --from 2026-09-07 --to 2026-11-07`，62 行、幂等）：`price_direction` 非空 **28 → 45** / `hit_t1` 非空 **13 → 22** / `hit_t5` 非空 **11 → 21** / `gold_ny_close` 非空 **28 → 45** / 总行数 62（未增删）。**前后用备份库逐项对拍**（不是凭印象）。⚠ 回填前已备份：`data/backups/gold_etf.v0121.3.20261107_100741.db` |
| 剩余空值 | ✅ **都是诚实的**：`price_direction` 剩余 17 行**全是周六/周日**（无交易日 ⇒ 方向未知）；`hit_t1` 剩余空值只剩三类 —— **非交易日 / 无消息方向（不该判定）/ 未来未到** |
| `__version__` | ✅ 已 bump 到 `0.121.3`（4 处同步：`__init__.py` / `pyproject.toml` / `uv.lock` / `sw.js`） |
| 静态资源 | ⚠ **本版只改了 `static/sw.js` 的 `VERSION`**（未改任何 `static/*.html|js|css` 内容）⇒ 按 V0.100.1 仍换代，但**无需清 SW 缓存内容** |
| 服务 | ✅ **已用 systemd 重启**（`sudo systemctl restart gold-etf-analyzer.service`）⇒ `/openapi.json` → `0.121.3`，**这是 V0.121.x 三批里第一次「代码 = 服务」** |
| 线上实测 | ✅ `192.168.0.204:8888`（服务已加载 V0.121.3）：`/scoring/hit-stats-all` t0·2026-10 **涨 0 · 跌 0 · 已知 0 → 涨 4 · 跌 6 · 已知 10**；`/scoring/hit-stats` t1·2026-09 **涨 0 · 跌 0 · 已知 0 → 涨 5 · 跌 6 · 已知 11**；`/scoring/summary` 2026-10 涨 9 · 跌 13 · 已知 22（**三处口径已一致**） |
| 测试 | ✅ `pytest tests/test_services/test_scoring_wide.py` → **26 passed**；`ruff check src tests scripts` → All checks passed |
| git tag | ✅ `v0.121.3`（annotated）**已推送** —— 远端 `refs/tags/v0.121.3^{}` = `1e41af5` = 本地 `git rev-parse v0.121.3^{commit}`（远端 tag 对象 `ac170e8`）；远端 tag 数（去掉 `^{}` 行）**117** = 本地 117 |

> **反向验证**（撤销 ⇒ 变红 ⇒ 恢复 ⇒ 变绿）：
> 撤 `hit_stats()` 桶的三字段 ⇒ **2 条测试变红、另 1 条仍绿**（证明断言不是恒真）；
> 撤 `hit_stats_all_horizons()` 桶的三字段 ⇒ **另 2 条测试变红**；
> 恢复 ⇒ **26 passed**。

### 上一轮：V0.121.2（2026-11-07 发版）

| 项 | 状态 |
|---|---|
| 内容 | ✅ **诚实性与数据链批次**（「把显示假的逐条修回来」三批计划的**第 3 批 / 收尾批**）。① **价格日历永远追不到今天**（B1）—— 根因有**两层**：`ensure_price_calendar()` 在 `force=False` 时「区间内已有数据就整段跳过」（all-or-nothing ⇒ 只补过一次就永远不再补）**且**调用点套着 `if not cov.usable:`（覆盖 deemed 可用时压根不调用回填）⇒ 修法是新增 `_calendar_gap_days()` **按交易日**算缺口、只补缺口那一段，调用点改成「每次都尝试追平」；⚠ 窗口大小按 **bar 数**（`df.tail(days)`）而不是日历天算，容忍度按**交易日**算（窗口起点常落在周末 ⇒ 用日历天判断会每次触发一次无用抓取）。② **`group_combine` 下 5 个权重滑块是装饰**（P0-7）—— 真正参与合成的是 `trend.py` 的**模块级常量** `GROUP_WEIGHTS`，页面让用户调的是**另外 5 个维度权重** ⇒ 用户拖滑块 → 显示「100% 绿」→ 保存成功 → **对结果零影响**；按用户拍板「置灰 + 说明 + 补组权重入口」处理：新增 `GroupWeightConfig`（带「和为 1」校验器）+ `WeightService.group_weights()` + `combine_by_group()` 接受真实生效值 + 5 个滑块**真 `disabled`** + 3 个组权重滑块（默认 0.50/0.30/0.20）。③ **三页的「数据时效保护」是假的**（P0-6）—— 计划里写「4 处」，**实测是 3 处**（`portfolio.html` / `trades.html` 调 `window.FreshnessBar.load()` 却**没引 `freshness.js`** ⇒ 恒 `undefined` ⇒ 守卫静默跳过；`settings.html` 引了脚本但**没有容器** ⇒ 每 60 秒空轮询一次外网）⇒ 删掉那 3 处误导性调用 + 新增通用门禁 `scripts/check_freshness_consistency.py`（「引了 `freshness.js` ⇒ 必须有容器」+「调了 `window.FreshnessBar` ⇒ 必须引脚本」）。④ **AI token 一栏永远不显示**（P0-5）—— **两层原因叠加**：客户端 `case 'message_stop'` **从不读** `payload.usage`（且 `|| null` 会把合法的 0 也吞掉 ⇒ 改 `?? null`）；服务端拿不到的输入 token 写 **0**（= 谎称「用了 0 个」）⇒ 改写 **NULL**。⚠ 实测比计划更深一层：miniMax 代理**照发** `message_start`，但 `usage.input_tokens` 要么**缺失**、要么**报 0** —— 请求必带 system prompt + tools + 历史 ⇒ 真实输入 token **不可能为 0** ⇒ 代理的 0 其实是「没数」⇒ 判据定成「**字段缺失 或 值为 0 ⇒ 未知**」（解析层 `claude.py` 保留原值，策略放在落库层，一处说了算）。详见 [releases/milestones/m6-truthful-signals-v0.121.md](releases/milestones/m6-truthful-signals-v0.121.md) |
| 🐛 **顺带修好的更大缺陷** | ⚠️ `static/ask.js` 的 `var userMsg` 在 `sendMessage()` 的作用域里，而 `handleEvent()` 在 `sendMessageStream()` 里 —— **两个不同的函数作用域** ⇒ `user_saved` 事件一进来就 `ReferenceError: userMsg is not defined` ⇒ **整条 SSE 流当场死掉** ⇒ 每次提问都**静默降级**到同步端点 ⇒ **/ask 的「流式」自 V0.98 C5 起从未真正生效过**（页面看起来能用，所以没人发现）。这是本轮 P0-5 能被端到端门禁抓到的直接原因 |
| `__version__` | ✅ 已 bump 到 `0.121.2`（4 处同步：`__init__.py` / `pyproject.toml` / `uv.lock` / `sw.js`） |
| 迁移 | ✅ **零 schema 变更、零 alembic 迁移** ⇒ 回滚代价低 |
| 生产库写入 | ⚠️ **本批未写生产库**（B1 的回填只发生在**跑回测时**按需触发，线上实测触发的是「新增行」，不改动既有行；P0-7 的组权重实测改过又**已还原**为 0.50/0.30/0.20） |
| git tag | ✅ `v0.121.2`（annotated，指向 `f823909`）**已推送**；`v0.121.1`（annotated，指向 `a3153db`）**已推送** —— 远端 tag 计数 **114 → 116**，与本地一致（`ls-remote` 去掉 `^{}` 行后实测） |
| 线上实测 | ⚠️ **本批当时 8888 未重启**（重启命令被环境策略拦下 —— 不能 `kill` 非本会话创建的进程）⇒ 实测改用**临时的 loopback 实例**（8891 / 8892，跑的是**新代码**，自带 `timeout` 自毁）完成：**B1** `ny` 80→97 行 / 最新 2026-10-14→**2026-11-06**、`etf` 73→80 行 / 最新 2026-10-28→**2026-11-06**、回测覆盖报告 `price_calendar_days` 15→**22** / `returns_available_days` 12→**18**；**P0-7** 组权重 (0.5/0.3/0.2)→(0.1/0.1/0.8) ⇒ 技术面 **16.4 → 4.7**，还原 ⇒ **回到 16.4**（证明组权重真的参与计算）；**P0-5** 真 SSE 抓包 `message_stop.usage = {"input_tokens": null, "output_tokens": 1874}`、落库 `(input_tokens=NULL, output_tokens=1874)`（修复前是 `0`）。✅ **后续已在 V0.121.3 轮次用 systemd 重启 ⇒ 本批修复现已生效** |
| 浏览器门禁 | ✅ 新增 `scripts/_verify_ask_tokens.mjs`（**6 条断言**，假 SSE 驱动 ⇒ 不调真模型、不花 token；`LIVE=1` 可打真实模型跑整条链）；新增 `scripts/_verify_weights_group.mjs`（组权重滑块态 + 组权重真的影响结果）；新增 `scripts/check_freshness_consistency.py`（P0-6 这类缺陷以后会自己变红） |
| 测试 | ✅ 目标测试文件全绿（详见 milestone 文档的实测表）；`ruff check src tests scripts` → All checks passed |
| ⚠️ **留给用户的 3 步** | ① ~~**重启 8888**~~ ⇒ ✅ **已完成**（V0.121.3 轮次用 systemd 重启，服务已加载 `0.121.3`）；② `LIVE=1 node scripts/_verify_ask_tokens.mjs`（打真实模型，消耗 token ⇒ 默认不跑）；③ 归档本轮实测留下的 **4 条**测试对话（「一句话说明今天金价的主要驱动」）—— 走 `DELETE /api/v1/ai/conversations/{id}` 是软删除，具体 4 个 id 见 [M6 里程碑文档](releases/milestones/m6-truthful-signals-v0.121.md) §V0.121.2 |

> **反向验证**（每条修复都做过「撤销 ⇒ 变红 ⇒ 恢复 ⇒ 变绿」）：
> B1 撤掉调用点的追平逻辑 ⇒ **新测试变红** ⇒ 恢复；
> P0-7 撤掉「组权重真正参与计算」⇒ **3 个测试变红**；去掉滑块的 `disabled` ⇒ **浏览器门禁红** ⇒ 恢复；
> P0-6 恢复那 3 处误导性调用 ⇒ **新门禁红** ⇒ 恢复；
> P0-5 客户端去掉 usage 读取 ⇒ **浏览器门禁 3 条红**；服务端去掉 `if saw_input_usage else None` ⇒ **2 个测试红** ⇒ 恢复。

### 上一轮：V0.121.1（2026-11-06 发版）

| 项 | 状态 |
|---|---|
| 内容 | ✅ **可信度 P0 批次**（「把显示假的逐条修回来」三批计划的**第 2 批**）。① **`?days=` 参数此前完全失效** —— `served_cache` 的 key 是 `(target, interval, on_date)`，**没有 `days`** ⇒ `?days=30/60/120` 返回完全相同的结果（趋势页 52W 按钮画的是 12 周）⇒ key 加 `days` 维度，`invalidate` 仍按 `(target, interval)` 匹配以覆盖所有 days 变体。② **命中分析「上涨天数」恒为 0** —— 治本（新增 `price_direction VARCHAR(8)` 列 + 迁移 `t2u3v4w5x6y` + 停掉消息面方向对 `direction` 列的覆写 + 聚合新增 `known_days`）；唯一可信的源是 `gold_price_daily.change_pct` 的符号，**不用快照 close 兜底**（实测两源方向只有 44% 一致且快照 close 滞后一天 ⇒ 系统性错位比留空更坏）。③ **64% 历史行带伪造消息面 50 分** —— 治源头（`daily_snapshots.news_index` 改可空、`services/snapshot.py` 不再兜底 50、宽表 ETL 不再继承快照的 `news_index`、消费侧 `news_w > 0` 且为 NULL 时**跳过该日**）+ 幂等回填 `scripts/backfill_news_truth.py`（**清掉 26 个伪造命中**、29 行被消息面方向污染的 `direction`，8 行用户真打的 50 分全部保留）。④ **`/headlines` 渲染 i18n key 字面量** —— 字典里的 key 是复数（`time.minutes_ago` 等）而代码写的是单数（`time.min_ago` 等）⇒ 三语字典里都没有 ⇒ `I18n.t()` 返回 key 字面量；顺带修掉「`(I18n.t(key)) || "分钟前"` 永远不触发」的兜底写法；门禁严格清单纳入 `"time."` 并**默认输出清单外缺失数 + 位置**。详见 [releases/milestones/m6-truthful-signals-v0.121.md](releases/milestones/m6-truthful-signals-v0.121.md) |
| `__version__` | ✅ 已 bump 到 `0.121.1`（4 处同步：`__init__.py` / `pyproject.toml` / `uv.lock` / `sw.js`） |
| 迁移 | ✅ `t2u3v4w5x6y`（`scoring_daily_wide` 增 `price_direction` + `daily_snapshots.news_index` 改可空）—— 先在副本库上验过 upgrade / downgrade / 往返，再上生产 |
| 生产库回填 | ✅ 快照 **49 行**修正（32 → NULL / 17 → 当日聚合值）+ 宽表 ETL 重跑 **61/61 天**；幂等自查二次规划 **0 行** |
| git tag | ✅ `v0.121.1`（annotated，指向 `a3153db`）—— **已于 2026-11-07 与 V0.121.2 一起推送**（当时 DNS 解析不了境外域名 ⇒ 首次推送失败；DNS 恢复后补推）。远端 `^{}` 行 = `a3153db` ⇒ 指向一致 |
| 线上实测 | ✅ `192.168.0.204:8888`：`/openapi.json` → `0.121.1`；`ny-trend?days=30/60/120` → **30 / 60 / 120** 个点（修复前三次返回完全相同）；`scoring/summary` 61 桶 `up 11 / down 17 / known 28`；`scoring` 里 `news_slot_count=0` 的 32 行 `news_index` / `hit_t1` 非 NULL 均为 **0**；`/headlines` 上次刷新显示 **「8 小时前」**（修复前显示 `time.hour_ago`） |
| 浏览器门禁 | ✅ 新增 `scripts/_verify_v0121_truth.mjs`（**13 条断言**，可判红）—— 反向验证：删掉「方向已知」列 ⇒ 红；3 个 i18n key 改回单数 ⇒ 红（`#valLastRefresh` 复现出 `time.hour_ago`）⇒ 恢复 ⇒ **13 passed / 0 failed** |
| 测试 | ✅ `pytest` 6 个目标文件 → **157 passed / 0 failed**；`ruff check src tests scripts` → All checks passed |

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

### 推送（**V0.121.3 已推送；下面是同类场景的备用命令**）

```bash
cd /home/surui/gold-etf-analyzer

# 前置条件（两个都要满足）：
#   ① 网络能解析并连上 github.com：getent hosts github.com && curl -sI https://github.com | head -1
#   ② 一枚 **classic PAT**（gh keyring 里那枚 fine-grained 的没有写权限）

export GH_TOKEN='<classic PAT>'      # token 走环境变量 → 不进 argv、不落 remote URL
git -c credential.helper='!gh auth git-credential' push origin main --tags
unset GH_TOKEN

# ✅ 必做：清掉可能被记进 history 的 token
sed -i -e '/ghp_/d' -e '/GH_TOKEN/d' ~/.bash_history
grep -c 'ghp_' ~/.bash_history ~/.gitconfig   # 两个都应为 0

# 推送后核对远端
git ls-remote --tags origin | grep -v '\^{}' | wc -l   # 期望 121（去掉 ^{} 行）
git ls-remote origin refs/heads/main                   # 期望 = 本地 git rev-parse HEAD
```

> ⚠️ `sed` 之前**不要** `cp ~/.bash_history /tmp/x.bak` —— 那会造出第二份 token 副本；
> 要备份就 `shred -u` 掉。

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
- [releases/milestones/m10-home-latest-report-v0.125.md](releases/milestones/m10-home-latest-report-v0.125.md) — 当前里程碑（V0.125 首页研报入口线）
- [releases/milestones/m9-macro-face-evidence-v0.124.md](releases/milestones/m9-macro-face-evidence-v0.124.md) — 上一里程碑（V0.124 宏观面证据复算线）
- [releases/milestones/m8-flow-face-evidence-v0.123.md](releases/milestones/m8-flow-face-evidence-v0.123.md) — 更早里程碑（V0.123 资金流面证据复算线）
- [releases/milestones/m6-truthful-signals-v0.121.md](releases/milestones/m6-truthful-signals-v0.121.md) — V0.121 可信度修复线
- [CHANGELOG.md](../CHANGELOG.md) — 发版史
