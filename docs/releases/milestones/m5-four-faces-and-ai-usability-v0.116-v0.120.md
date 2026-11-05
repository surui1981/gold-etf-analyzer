# M5 · 四面评估与 AI 可用性（V0.116 – V0.120）

> **发版区间**：V0.116.0 – V0.120.5（15 个版本）｜ **状态**：活跃（最新里程碑）
> **本文件定位**：把该区间的 14 份 release notes 合并成一条**可读的演进脉络**。
> **逐版原始全文**在 git 历史里（tag 与原文件名同名）：`git show v0.120.4:docs/releases/v0.120.4.md`
> **注意**：本里程碑覆盖到当前版本，**应用当前正在用的版本号以 [../../version-status.md](../../version-status.md) 为准**。

## 〇 一页结论

1. **综合指数从三维变四维**：V0.118.0 把宏观面从 5 因子扩到 8（+2Y / +10Y-2Y 利差 / +10Y 实际利率），V0.119.0 再扩到 11（+美国 / 中国 / 欧洲政府债务占 GDP，组权重 12%）；V0.120.0 新增第 4 个评分面「资金流面」（6 因子，周 3 / 月 3）。合成权重随之从 tech 30 / macro 40 / news 30 改为 **tech 25 / macro 35 / news 25 / flow 15**。
2. **主线不是「加功能」，是「让已经在显示的东西变成真的」**：V0.117.0 把整条链的链头定位到一行代码（`src/app/services/cache.py:35` 的缓存 key 漏了 `days`）；V0.118.0 回填历史让滚动分位第一次真的生效，随即引爆了「6 个负相关因子分位方向整个写反」的死分支 bug。
3. **兜底层被反复证明是真正的契约**：V0.118.1 在实时源与内置常量之间插入「末次落库」层（`live` / `lkg` / `static` 三档 + source 前缀 + 前端 chip 三件套）；V0.120.0 把这套降级链原样复用到资金流面，并补上第 4 层语义 —— 整面一个真实观测都没有时 `score = None`，**剔除而不是记 0 分**。
4. **AI 可用性是一条连续演进的线**：V0.116.0 文本格式重做（正则清洗器换成 DOM 白名单）→ V0.116.1 CI 修绿 → V0.116.2 / V0.116.3 / V0.116.4 三处静默失效 + 命令面板聚焦与落点 → V0.120.2 `tool_input` 契约错位导致整个对话 500 → V0.120.3 miniMax 原生协议外泄 + 工具层两个真缺陷 + 正文为空的安全网。
5. **门禁本身成了主要工作对象**：这一阶段至少修了 10 处「坏门禁」—— 扫描口径不一致（`check_i18n_keys.py` 只看顶层目录）、断言命中注释里的字面量、谓词引用 Node 侧变量、Service Worker 让拦截静默失效、门禁启动即崩、「只能绿一次」、读到还没准备好的页面、把 bug 当成期望、429 限流被误判成页面缺陷。
6. **留下的**：V0.116.2 §5 记录的 3 条**要动生产数据库**的问题（生产库 `users` 表缺 `role` 列）到本阶段末仍未修；V0.117.0 定位的「显示假的」5 条（A1–A5，含 A3 那一行 cache key）在这 14 份 release notes 里**没有任何实施记录**；资金流面今天不进回测网格（约 1 年后才够格），也不参与共振信号与决策卡（源文件自己标为「已知的口径缺口」）。

## 一、版本一览

| 版本 | 主题 | 关键交付 |
|---|---|---|
| V0.116.0 | AI 对话文本格式重做 | DOM 白名单清洗器 / 移动端 390px 不裁切 / 排版补齐 + 去双气泡 / `enhanceBubble` 增强管道 / 提示词显式要 markdown / `_verify_ask_format.mjs` 97 条断言 |
| V0.116.1 | CI 修绿 + 版本状态整合 | ruff 290 → 0、format 79 文件重排 → 0、pytest 10 failed → 0；顺带挖出 4 处真 bug；4 处版本号纳入 `check_version_sync.py` 门禁 |
| V0.116.2 | 3 处静默失效 + 2 处坏门禁 | admin 页整页 i18n 键字面量 / `/ask` 状态条永久不可见 / dismiss 勾选框没接线；`check_i18n_keys.py` 改递归（20 → 21 页）；浏览器门禁 23 → 42 条 |
| V0.116.3 | 命令面板自动聚焦被无障碍修复打没 | 跨版本因果链（V0.68.0 ↔ V0.113.0）；`focusWhenVisible()` 等计算样式而非等毫秒；`transition-delay` 才是对的判据杠杆 |
| V0.116.4 | 命令面板「输入决策」落到趋势页 | 场景落地页提到组首；8 场景通用断言；`renderHitStats` 守卫；429 窄口径豁免；`_verify_scoring_robust.mjs` 新建 |
| V0.117.0 | 应用整体改进方向（**planning · 未实施**） | 一行 cache key 领衔的 5 处「显示假的」（A1–A5）+ 4 处坏门禁 + 4 条新门禁（H1–H4）+ 排期依赖链；**零代码改动** |
| V0.118.0 | 宏观面 5 → 8 因子 + 实时源 + 滚动分位回填 | +2Y / +10Y-2Y / +10Y 实际利率；dxy / vix 接 Yahoo / FRED；历史回填激活滚动分位；**修掉 6 个负相关因子分位方向写反**；4 道坏门禁 |
| V0.118.1 | 宏观因子「末次落库」兜底层 | 优先级链 手动 > 实时 > 末次落库 > 常量；`tier` 字段 + 降级 chip；顺带修 `/ask` 工具的 `macro` 位置参数误传 |
| V0.119.0 | 宏观面 +3 个政府债务因子（8 → 11） | 美 / 中 / 欧债务占 GDP，组权重 12%；`cadence` + `max_lag_days` 低频滞后口径；后端自报 `rolling_factors`；`_verify_macro_debt.mjs` 5 段 |
| V0.120.0 | 新增第 4 个评分面「资金流面」 | 6 因子（周 3 / 月 3）；综合权重 flow 15%；滚动分位按观测节奏取窗；修观测网格与声明 cadence 不符；i18n 竞态与门禁盲区 |
| V0.120.1 | 资金流观测网格「今天」可注入 | `week_end_days(today=...)` 透传；`FIXED_TODAY = date(2026, 10, 28)`；零 schema / 零接口 / 零配置 / 零前端 |
| V0.120.2 | `/ask`「加载对话失败：Internal Server Error」 | `tool_input` Text 列 ↔ dict 契约在 schema 边界加 `mode="before"` 解码器；坏 JSON 置 `None` 不兜底 `{}` |
| V0.120.3 | `/ask` 回复不可读：协议外泄 + 工具层真缺陷 | 补 assistant(tool_use) 回合；`protocol_strip.py` 读时清洗；`get_user_portfolio` / `get_scoring_summary` 两个真缺陷；正文为空的安全网 |
| V0.120.4 | 首页 hero 右侧「综合评估」结论块 | hero 改两栏 grid；**零新增网络请求**（复用已有 trend payload）；修 `window.PM_I18N` vs `window.I18n` 的静默回退中文；`_verify_home_verdict.mjs` |
| V0.120.5 | 文档收敛 | 60 份逐版 release notes → **6 份里程碑文档**；6 份重叠规划文档 → **1 份 roadmap.md**；5 份分析报告 → **1 份评估汇总**；门禁契约改为「当前版本在里程碑里有发布记录」 |

## 二、逐版本记录

### V0.116.0 · AI 对话文本格式重做（清洗器 / 移动端裁切 / 排版）

**背景/问题**：用户提出「当前应用在 AI 对话中对文本格式支持不够完善」。诊断一度误判「marked 没加载、所有回复都退化成纯文本」—— 翻 `static/marked.min.js` 才发现这版（v12.0.2）**不暴露 `.version` 字段**，`window.marked` 本身好好的：**markdown 引擎没坏，坏的是它外面的东西**。下面 6 条全部是实测出来的。

| 缺陷 | 现象（实测） |
|---|---|
| P0 · 安全 | 清洗器是正则且写错了：`onc(?:lick｜load｜error｜mouseover｜focus｜blur｜change｜submit)` 里 `on` 后多了个 `c` ⇒ **8 个事件处理器只拦住 `onclick`**，其余 7 个永远接不到；`<img src=y onerror="…">` 属性**原样进了 DOM**（`onerror` 没触发只是因为图片加载成功） |
| P1 · 移动端裁切 | 390px 视口下表格 389 ✅ / `<pre>` **431 ❌**（裁 17px）/ 长 URL **613 ❌**（裁约 200px）；根因是 flex item 默认 `min-width: auto`，包含块自己先变宽了 |
| P2 · 零间距 | `ask.html` 的 `* { margin: 0 }` 清零后只补回了 `p / ul / ol / table / blockquote`，**漏了 `h1`–`h6` 和 `hr`**（`h2` 字号 19.5px 挤在 13px 正文里；`hr` top=682 紧贴下一段 top=684） |
| P3 · 双气泡 | `renderAssistantMsg` 建了一个 `.bubble` 又建一个把它塞进去 ⇒ 两层边框 + 16px/24px 内边距 |
| P4 · 表格 | 气泡里的表格没套全站 11 张表在用的 `.table-scroll` 约定 |
| P5 · 体验 | 代码块无复制按钮（AI 常返回 JSON/JS）；链接无 `target/rel`（点进去丢对话状态） |

**修法**：**C1** 删掉正则版 `sanitizeHtml`，换成 DOM 遍历白名单 —— `new DOMParser().parseFromString(html, 'text/html')` 解析到**游离文档**（不碰当前 document）；DROP 集合（`script` / `style` / `iframe` / `object` / `embed` / `noscript` / `template` / `svg` / `math` / `textarea` / `title` / `xmp` / `frame` / `frameset` / `base` / `link` / `meta` / `form` / `input` / `button` / `select` / `option` / `audio` / `video` / `source` / `img`）连子节点一起删；KEEP 集合之外的标签 unwrap（保留文字，丢标签）；属性**只允许** `a[href]`（限 http/https/mailto/`/`/`#`）与 `a[title]`，`on*` 与 `style` 无条件 `removeAttribute` —— 不靠正则判断，靠「不在白名单就删」；**不放 `img`**（避免外链追踪像素）。**C2** 补 `min-width: 0` 链条（`.ask-main` / `.message-stream` / `.message` / `.bubble`）+ `overflow-wrap: anywhere`（`anywhere` 与 `break-word` 的关键差别在 **min-content 计算**）。**C3** h1–h6 字号阶梯 17 / 15.5 / 14 / 13 / 13 / 13 px + `margin: 10px 0 4px`，`hr { margin: 10px 0 }`，`renderAssistantMsg` 去掉外层多余 `.bubble` 改用只做布局的 `.bubble-wrap`。**C4** 新增 `enhanceBubble(bubble, isFinal)`：表格套 `.table-scroll`（带 `tabindex="0" role="region"`）、`<pre>` 加复制按钮（放自己的**工具条行**，不叠在代码上 —— 滚动容器的 `padding-right` 只在滚动末端生效）、链接补 `target="_blank" rel="noopener noreferrer"`；挂在 `renderAssistantMsg`（`isFinal=true`）与 `flushBubble`（流式 80ms 节流，`isFinal=false`、不挂按钮，否则每秒重建 12 次按钮）两处。**C5** 提示词新增第 5 条「显式要 markdown」，后面几条顺次后移（6/7/8），配 5 条 pytest（含**规则号 1..N 连续无重复**）。**C6** 新建 `scripts/_verify_ask_format.mjs`（97 条断言）。

**变更清单**：

| 文件 | 改动 |
|---|---|
| `static/ask.js` | 删掉正则版 `sanitizeHtml` 换成 DOM 白名单；新增 `enhanceBubble(bubble, isFinal)`；`renderAssistantMsg` 去掉外层 `.bubble` |
| `static/ask.html` | `min-width: 0` 链条 + `overflow-wrap: anywhere`；h1–h6 / `hr` 排版补齐 |
| `src/app/services/ai_chat/prompts.py` | 提示词新增第 5 条「显式要 markdown」，后面几条顺次后移（6/7/8） |
| `scripts/_verify_ask_format.mjs` | **新建**：97 条断言（5 组） |
| `scripts/_diag_ask_*.mjs` | 诊断脚本（`_` 前缀 = 诊断，非门禁），留在仓库里当复现证据 |

**验证**：门禁覆盖 5 组 —— 清洗器（18 个用例 + 8 个事件处理器 + 源码形态检查）、移动端 390px（4 种内容 × 2 种真实形状）、计算样式直接断言 `overflowWrap` / `minWidth`、排版（无嵌套 `.bubble` / `h2` 间距 / `hr` 间距与 ≥ 8px 间隙）、真实对话 + `enhanceBubble` 真路径（含幂等 ×3、流式不挂按钮）。门禁自己踩了 5 个坑，全部靠反向验证抓出来（`DOMParser` 把开头的 `<script>` / `<style>` 路由进 `<head>`；布局断言分不清是 `min-width:0` 撑住还是 `overflow-wrap` 断行；`pre` 在 `overflow-x:auto` 里右缘超出视口是应有之义；从模块作用域正则抠函数；几何断言单用不够）。诊断脚本 `_diag_ask_*.mjs` 留在仓库里作复现证据。版本号 `0.116.0` 四处同步（`src/app/__init__.py` / `pyproject.toml` / `uv.lock` / `static/sw.js` VERSION）。

**教训**：正则清洗器「漏写一个字符」就会静默放行 7 个事件处理器；**无正则 ⇒ 不存在「漏写一个字符」这类坑**；属性判据不能被布局副作用替代（`position !== "absolute"` 要单独钉死）；`word-wrap` 是 `overflow-wrap` 的**别名**，同优先级下后者静默覆盖前者。**不做**：不修 `input_tokens = 0`（后端数据问题，另开）、不改 AI 回复的实质内容/口径、不 vendor 第三方库。

### V0.116.1 · CI 修绿（ruff lint / ruff format / pytest）+ 版本状态整合

**背景/问题**：CI 从 **V0.108.0（2026-10-16）起每一次 push 都是 failure**，失败步骤始终是同 3 步（其余 11 步全绿）：

| 步骤 | 状态 | 实测基线 |
|---|---|---|
| `ruff lint`（`uv run ruff check src tests`） | ✗ 预存红 | **290 errors**（257 可 `--fix`） |
| `ruff format check` | ✗ 预存红 | **79 files would be reformatted**（211 已合规） |
| `pytest (offline regression)` | ✗ 预存红 | **10 failed** / 1777 passed（16 分 30 秒） |

用 `git worktree add /tmp/wt_pre HEAD~2` 对拍逐条确认这 3 步全是**预存**红。两个持续的坏后果：**「CI 绿」在这仓库不能当质量信号**（得先看是哪个步骤红）；每次发版都要重新花 25 分钟 + 一个 worktree 对拍，才能确定「不是我这次搞坏的」。

**修法**：`ruff check --fix` 自动修 **254 条**，剩 **24 条手工改**（每条都判过语义：`SIM201` 等价改写、`E402` 提到顶部前**先验证无循环依赖**、`RUF012` 只改注解运行时不变、`B904` 补异常链、`SIM117` 合并 `async with` 而 `continue` 仍正确退出两层 CM、`pytest.raises(Exception)` 收窄成 `pytest.raises(FrozenInstanceError)` 等），`ruff format` 重排 **79 + 11** 个文件。⚠ CI **只 lint `src tests`，不 lint `scripts/`** ⇒ 新写的脚本 CI 抓不到，本轮把 `scripts/` 的 **36 个错**也一并修了。**语义零变化**用逐文件 `ast.dump` 比对证明：99 个改动的 Python 文件里 **49 个 AST 完全等价**，其余 50 个的实质改动逐条列出并人工核对。用 ruff 官方的 `# fmt: off` / `# fmt: on` 保住 `news_classifier.py` 四张关键词表的紧凑排版（分组注释只在紧凑排版下读得懂）—— 该文件 **638 → 340 行**，`ruff format --check` 依然全绿（仓库第一处 `# fmt: off`）。pytest 10 条全修：**9 条单跑即红 + 1 条必须整文件跑才红**（`sse_starlette` 的 `AppStatus.should_exit_event` 是**类级全局**且惰性创建，`anyio.Event` 首次 await 时把 `_loop` 绑死，pytest-asyncio 每个用例新建 loop ⇒ 后面的用例 await 了别的 loop 上的 Event）。顺带把一条**绿着但什么都没保护**的断言改成真断言：`test_root_alias_count_matches` 断言的是「常量 == 常量」⇒ 改成与 `app.routes` 双向集合比对 + 逐条查跳转目标文件真实存在。

**变更清单**：

| 文件 | 改动 |
|---|---|
| `src/` + `tests/` + `scripts/` | ruff 自动修 254 条 + 手工改 24 条；`ruff format` 重排 79 + 11 个文件；`scripts/` 的 36 个错一并修（CI 不 lint 它） |
| `src/app/api/v1/endpoints/market.py` | 补 `HTTPException` import（否则本该 503 却变 500） |
| `src/app/dependencies.py` | 删掉重复遮蔽的 `get_scoring_wide_service` / `get_scoring_wide_repository` |
| `news_classifier.py` | 删掉被遮蔽的第二份 `_SITE_HINTS`；加 `# fmt: off` / `# fmt: on` 保住四张关键词表的紧凑排版 |
| `scripts/check_docs_claims.py` | SIM103 改回（自动改写把后半段判据压成了死代码） |
| `tests/conftest.py` | 加 autouse fixture，每个用例前重置 `should_exit_event` **与** `should_exit`（只重置前者不够） |
| `scripts/_verify_i18n_keys.mjs` | **新建**：23 条断言（3 语实跑，查 DOM 值不是查 `data-lang`） |
| `scripts/check_version_sync.py` | 4 处版本号 + CHANGELOG 降序 + 基线未过期纳入门禁 |

**验证**：`ruff` 290 → 0、format 79 → 0、`pytest` 10 failed → 0。测试数对账用 collect-only 排序比对：HEAD **1831** → 工作区 **1833**（**5 删 7 增，净 +2**，逐条对得上，没有一条「消失得莫名其妙」）。新增门禁 `scripts/_verify_i18n_keys.mjs`（**23 条断言**，查 `getAttribute("placeholder")` 的值而**不是**查 `data-lang`），**反向验证过**：把 `data-i18n-placeholder` 改回 `data-i18n-attr` 后门禁真的红 3 条。版本状态整合：4 处版本号纳入 `scripts/check_version_sync.py` 门禁；CHANGELOG 版本段严格降序、无重复 ⇒ **抓出历史 4 处版本归属错位**；「单一真源文档会过期」⇒ `version-status.md` 的基线版本也进门禁。

**教训**：**「断言『个数』而不是『集合相等』」是同源病根**（3 条 `check_routes.py` + 1 条 alias 计数共 4 处）—— 数目对不上 ⇒ 恒红；数目碰巧对上但内容错了 ⇒ 假绿；`SIM103` 这类「把 if 压成 return」的自动改写**必须**回头看被压掉的分支有没有后续逻辑（AST 比对当场抓到 `check_docs_claims.py` 被改出死代码）；ruff 顺带挖出 4 处真 bug —— `market.py` 的 `HTTPException` 没 import ⇒ 本该 503 却变 500；`dependencies.py` 两份**字节完全相同**的 `get_scoring_wide_service` 后一份**遮蔽**前一份（改其中一份不生效）；`news_classifier.py` 两份**内容不同**的 `_SITE_HINTS`（40 条 vs 34 条）后一份把前一份变成死代码；`ai_chat/service.py` 的 `had_error` 赋值 4 次从未被读。

### V0.116.2 · 3 处静默失效的前端缺陷 + 2 处「绿着但什么都没保护」的门禁缺陷

**背景/问题**：CI 修绿之后「CI 绿」已不再是瓶颈，于是继续往下挖前端，挖出 **3 处「不报错、不红屏、就是少一块东西」** 的缺陷。它们的共同点比缺陷本身更值得记：**没有任何机制会告诉你坏了** —— 没有异常、没有 console 报错、没有测试失败、门禁全绿。

| # | 症状 | 根因 |
|---|---|---|
| 1 | `/static/admin/users.html` 整页显示 `admin.h_title` / `admin.sub` / `admin.denied` / `reset.btn_back_login` | `<head>` 只引了 `i18n.js` + `auth.js`，**漏引 `/static/i18n/zh-CN.js`** |
| 2 | `/ask` 顶部**没有**「数据时效 / 警示计数」那一行（别的页都有） | `<details id="statusPanel" class="status-panel" hidden>` —— 全站 **12 个**带 `#statusPanel` 的页面里**只有 `ask.html` 写了 `hidden`** |
| 3 | 「本次会话不再展开」勾选框点了没反应 | HTML 用 `id="warnDismiss"`，`warning.js` 查的是 `[data-warn-dismiss]` ⇒ `querySelector` 返回 `null` ⇒ 整段 dismiss 逻辑**静默跳过** |

缺陷 1 最反直觉 —— i18n 的加载逻辑是**分叉**的：非默认语言（en-US / zh-TW）**动态插 `<script>`** 加载字典，漏引也能取到 ⇒ 页面正常；**默认语言 zh-CN** 走 `syncLoadDefault()` 只读 `window.PM_I18N_ZH_CN` ⇒ 字典没引就是 `undefined` ⇒ **全页回落成键字面量**。所以现象是「中文坏了，英文和繁体中文好好的」。

**修法**：缺陷 1 补 `<script src="/static/i18n/zh-CN.js"></script>`；缺陷 2 去掉 `hidden`（与另外 11 页对齐）；缺陷 3 保留 `id`（不破坏既有选择器）并补上 `data-warn-dismiss`。**门禁为什么没拦住才是真正的成因**：`scripts/check_i18n_keys.py` 的 `check_dict_loaded()` 用 `os.listdir(STATIC_DIR)` —— **只列顶层** ⇒ `static/admin/users.html` 永远扫不到 ⇒ 一路绿灯；而**同一个脚本**里的 `extract_html_keys()` 用的是递归 glob ⇒ **两处口径不一致**（同类问题本仓库已踩过两次：`check_docs_claims.py` 漏扫 `docs/releases/`、`check_i18n_keys.py` 漏扫 `static/admin/`）。改成递归后扫描面 **20 → 21 页**。浏览器门禁 `_verify_i18n_keys.mjs` 扩展到 **42 条断言**（新增 19 条），其中第 ③ 组是**泛化断言**：任何 `data-i18n` 元素的正文若恰好等于自己的键就算失败。

**变更清单**：

| 文件 | 改动 |
|---|---|
| `static/admin/users.html` | +1 行：补 `<script src="/static/i18n/zh-CN.js"></script>` |
| `static/ask.html` | `#statusPanel` 去掉 `hidden`；`#warnDismiss` 补 `data-warn-dismiss` |
| `scripts/check_i18n_keys.py` | `check_dict_loaded()` 改递归 glob（扫描面 **20 → 21 页**） |
| `scripts/_verify_i18n_keys.mjs` | 23 → **42 条断言**（新增 19 条，含 1 组泛化「无键字面量」断言） |
| `src/app/__init__.py` / `pyproject.toml` / `uv.lock` / `static/sw.js` | 版本号 4 处 → `0.116.2` |

**验证**：`scripts/_verify_i18n_keys.mjs` **42 passed / 0 failed**（含 3 组反向验证：把 `hidden` 加回 ⇒ 3 条红；去掉 `data-warn-dismiss` ⇒ 1 条红；去掉字典行 ⇒ 4 条红、残留 key 字面量计数实测 **10 个**）。Python 门禁：`check_i18n_keys.py` 21 页全引字典 + V0.83 命名空间 **307 键** 3 语全覆盖，`check_static_js` / `check_docs_claims` / `check_pwa_assets` / `check_version_sync`（9 passed）/ `check_links` / `check_deps` 全绿，`ruff check src tests scripts` 0。浏览器门禁在 **1352×900** 视口下跑，且**没有同时跑全量 pytest**（两者抢同一个 SQLite 写锁，门禁会超时被殺，「已终止」≠ 红）。

**已知问题（本轮未修 —— 要动生产数据库）**：生产 SQLite 的 `users` 表**缺 `role` 列**（还多 `username` / `is_default`），`telemetry_events` 多 `client_ts`；20 张模型表全部存在，`alembic_version = s1t2u3v4w5x` = 迁移链头（27 条 revision 全部「已应用」）—— **记录的迁移状态与实际表结构对不上**。连带影响：`GET /api/v1/admin/users` **500**（`no such column: users.role`）、`POST /api/v1/admin/users/{id}/reset-password` **500**、`GET /api/v1/auth/me` **500**（`DetachedInstanceError`，被 `static/auth.js` 静默吞掉 ⇒ 顶栏不崩但用户态显示是错的）。另有一处认证边界问题：单用户模式（`AUTH_ENABLED=false`）下 `require_owner` **接受匿名调用者** —— **补 `role` 列时必须同时收紧这一条**，否则等于把一个 500 换成一个越权。

**教训**：「页面显示成键字面量」永远先怀疑 `<script>` 标签而不是翻译；同一个脚本里两处扫描口径不一致，就是下一个漏扫的位置；**「静默跳过」比「报错」更危险**；**门禁绿 ≠ 覆盖到了**。

### V0.116.3 · 命令面板自动聚焦被 V0.113.0 的无障碍修复顺手打没了

**背景/问题**：在移动端门禁 `scripts/_verify_mobile.mjs` 身上挖出一条线索 ——「打开时搜索框自动聚焦」那条断言**有时绿有时红**（同一个代码、同一个服务，跑三次得到 33/0、32/1、33/0）。按门禁的常识，红了就是实现坏了，但这里**红不红和实现对不对无关** —— 它红是因为**等待时间是个运气阈值**。把断言的时间轴摊开，牵出一条跨版本的因果链：

| 版本 | 提交 | 做了什么 |
|---|---|---|
| V0.68.0 | `5d0d81c` | 命令面板打开后**自动聚焦**搜索框：`setTimeout(() => input.focus(), 30)` |
| V0.113.0 | `8f75b16` | 移动端无障碍整改：给 `.pm-cmd` 加 `visibility: hidden`，让**关闭态的面板真正退出 tab 序列**（WCAG 2.4.3 焦点顺序） |

V0.113.0 那次改动是对的（`opacity: 0` 的元素**仍在 tab 序列里**，键盘用户一进页面 Tab 到的第一个东西就是这个看不见的搜索框，还落在 sticky 顶栏底下，看着像「点不动」）。但它给 `.pm-cmd` 加了 `visibility` **过渡**，于是三个事实叠在一起：①`visibility: hidden` 的元素不能接收焦点，浏览器会**静默丢弃** `focus()`（不抛异常、不打 console 警告）；②`visibility` 参与过渡 ⇒ 面板从 `hidden` 翻到 `visible` 需要**一帧**；③旧实现写死 `setTimeout(..., 30)` ⇒ 这 30ms 和那一帧**赛跑**。赛跑的结果是**看运气**的 ⇒ 面板偶尔开着但没焦点，直接打字没反应，必须先用鼠标点一下搜索框。

**修法**：新增 `focusWhenVisible(panel)` —— **判据是计算样式，不是「等多少毫秒」**（`getComputedStyle(panel).visibility === 'visible'`）；**重试到 `document.activeElement` 真的落上去**为止（不止试一次）；用**时间截止（2.5s）而不是帧数**（低帧率机器上 60 帧可能只有 300ms，遇上被人为拉长的过渡就会假红）。判据本身换了 4 版：固定 350ms 等待（测机器快慢）→ 2000ms 轮询（**还是假绿**：旧实现那 30ms 的 `focus()` 有一半以上概率 succeeds，轮询立刻抓到焦点）→ 把 `transition-duration` 拉长（**方向就是错的**：`visibility` 是**离散插值**，过渡一旦开始第一帧就翻成 `visible`，实测 t=16ms 时 `vis=hidden`、t=29ms 时已 `vis=visible` 而过渡才过了 1.3%）→ **`transition-delay`**（过渡期间属性保持起始值，于是可见时刻被推到确定的 400ms 之后）。

**验证**：`_verify_mobile.mjs` 修复版 **35 passed / 0 failed**；**回退实现 34 passed / 1 failed**，连跑 2 次结果一致 ⇒ 确定性红；`_verify_cmd_palette.mjs` 30 passed；`_diag_cmd_focus.mjs` 12 次 open/close **12/12** 落焦、0 个 JS 错误（旧实现 **8/12**，落焦耗时 16–34ms；修复后 16–77ms）。范围检查：`static/settings.js:341` 有形状一样的代码（`$("ruleModal").hidden = false` + `setTimeout(() => $("modalVolPct").focus(), 30)`）但**确认不受影响** —— 它用 `hidden` 属性 ⇒ `display: none`，`.modal` 的 CSS 里**没有任何 transition**，可见时刻是同步确定的。另加一条**判据自检断言**（「面板确实是延迟可见的」，`visibleAt > 300ms`），保证这个前提真的生效、免得判据退化成「什么都没测」而门禁还是绿的。

**教训**：`visibility: hidden` 的元素不能接收焦点，`focus()` 会被浏览器**静默丢弃**；**无障碍修复不是「纯加法」** —— 它改变了元素的**可见时刻**，而更早的功能**依赖**旧的可见时刻，跨版本的因果链只有把两边都翻出来才看得见；「等固定时间」和「轮询到截止」都可能是假绿 —— **判据必须让目标行为变成确定性的**；**要推迟的是 delay，不是 duration**（我在这个坑里绕了一轮，是靠逐毫秒采样才发现的）；第一版判据连跑两次都是「34 passed, 0 failed」—— **断言没被证伪过，就不算数**。

### V0.116.4 · 命令面板「输入决策」落到趋势追踪 —— 场景落地页被第一个子页顶掉了

**背景/问题**：用户反馈「**点击决策的时候看到的页面是趋势追踪**」。第一反应是「顶栏的决策点错了」—— 但实测不是：`scripts/_diag_decision_nav.mjs` 扫了 **17 个页面**上所有文案含「决策」的链接/按钮（**60+ 个**），逐个记 href，**全部指向 `/scoring`**，全站没有任何一个「决策」链接指向 trend。往下查一层才找到命令面板：输入「决策」后列出 5 条，第 0 条是「▶选中 📈 趋势追踪 `/static/trend.html`」，第 1 条才是「🎯 打分汇总 `/scoring`」，第 2–4 条是参数回测 / 研判复盘 / 持仓与决策。面板的默认选中项就是**第一条命中**的行（`filter()` 里 `panel._active = 0`）⇒ 「输入决策 → 回车」= 趋势追踪。

**根因**：命令面板的清单是**从 `topnav.js` 导出的 `SCENES` 惰性派生**的（V0.112.0 起命令面板与顶栏同源），派生时组内**先铺子页**。「决策」场景的 `path` 是 `/scoring`，而它的 4 个子页是趋势追踪 `/static/trend.html` / **打分汇总 `/scoring`** / 参数回测 `/static/backtest.html` / 研判复盘 `/review` ⇒ 场景自身那条被**去重逻辑吃掉了**（`covered = true`），组内剩下 4 条**全都命中「决策」**（`section` 就是场景名）⇒ 第一条命中 = 趋势追踪。**去重逻辑本身是对的**（不去重就会出现两条一模一样的 `/scoring`），**错的是排序** —— 去重之后落地页应该被**提到组首**。

**修法**：把落地页提到组首（`rows.unshift(rows.splice(landingIdx, 1)[0])`；没有同 path 子页时场景自身排组首）。效果是「输入场景名 → 回车」与「点顶栏 / 首页场景卡 / 手机抽屉」落到同一个页面 —— 顶栏、首页场景卡、手机抽屉三处**一直是对的**（`/scoring`），只有命令面板这一处落到趋势页。门禁新增【2b】段写成**通用循环**（8 个场景全受约束，新增场景自动受约束），检索词用**面板里实际渲染出来的组名**而不是 `SCENES[i].fb` —— `fb` 只是 i18n 缺失时的兜底文案（AI 场景 `fb = "AI 智能分析"`，而 zh-CN 的 `nav.ask = "智能分析"`）⇒ 用 `fb` 检索**一条都匹配不到**（实测 0 条），断言会以「null」的形式假红。

**顺带修的 2 处**：`static/scoring.js` 的 `renderHitStats` 守卫 —— `fetchJson` 在任何失败（429 / 网络抖动 / 500）时返回**通用空壳** `{ rows, buckets, tags }`，这个壳没有 `sample_size` / `by_direction`；而守卫写的是 `data.sample_size === 0` ⇒ 兜底场景下是 `undefined`，`undefined !== 0` ⇒ **守卫不生效** ⇒ 落进 `for (const d of data.by_direction)` ⇒ `undefined is not iterable` ⇒ TypeError ⇒ **整个「命中分析」Tab 渲染不出来**，描述行还露出 `sample=undefined` 字面量（同文件的 `renderSummaryTable` / `renderTagTable` / `renderCalendar` 都是用「字段缺失或数组为空」做守卫的，只有这里漏了）。另有两道浏览器门禁把服务端 **429 限流**（600 req/min per IP）误判成「页面 JS 错误」⇒ 门禁连续跑几次就 flap ⇒ 加**窄口径**豁免（只匹配 `HTTP 429: Too Many Requests`）并**显式打印条数与条件**。

**验证**：`_verify_cmd_palette.mjs` **39 passed / 0 failed**，回退实现 **38 passed / 1 failed**（只有「决策」这一条变红 ⇒ 判据精确，不是一刀切）；`_verify_scoring_robust.mjs` **新建 8 条断言**（A. 兜底空壳 ⇒ 必须显示空态、零 JS 错误、无 `undefined` 泄漏；B. 正常 payload ⇒ **必须真的渲染出方向卡**，防「修成永远空态」），回退守卫 **6 passed / 2 failed**；`_verify_mobile.mjs` 35 passed；`_diag_decision_nav.mjs` 17 页 × 60+ 个「决策」链接全部 `/scoring`。

**教训**：同一个入口可以有四种落点，而其中三处是对的 —— 顶栏 / 场景卡 / 抽屉共用 `SCENES` 的 `path`，面板是**另外派生**的 ⇒ 漂移就发生在派生那一层，**同源派生的东西要连「顺序」一起同源**，不只是「集合」同源；**去重会改变顺序，顺序也是行为**（面板里「第一条命中」有语义：默认选中 + 回车）；门禁要断言「同一个动作的多个入口落点一致」而不是逐个入口断言；**豁免必须写明失效条件**（否则就是永久放行）；**flap 的门禁比红的门禁更坏** —— 它让人不再相信它，本轮 3 次连跑才暴露出 429 误分类和 scoring 崩溃两个问题。

### V0.117.0 · 应用整体改进方向（一行 cache key 领衔）

> ⚠️ **本版本尚未开始编码。** 源文件标 `planning · 未实施` —— 一行代码都没写，**不 bump 版本号、无 tag、无 CHANGELOG 段**（与 [../../version-status.md](../../version-status.md) 的记载一致）。它记录的是「已定位到行、已实测复现」的缺陷与修复方向，不是发布说明。

**背景/问题**：用户要一份**应用级**改进路线（不局限于此前的缺陷清单），覆盖功能、UX、数据可信度、架构四个维度。**结果是：没有新功能可列** —— 一轮实测下来，最先要做的不是加功能，是**把已经在显示的东西变成真的**。**核心发现：整条链的链头只有一行代码** —— `src/app/services/cache.py:35` 的 `_key(target, interval, on_date)` 返回 `(target, interval, on_date)`，**key 里没有 `days`**。V0.60.0 给它加过时间戳、V0.64.0 给它加过 `interval`，唯独漏了 `days` —— 而 `days` 是唯一决定**响应里装多少条数据**的参数（`interval` 只改聚合粒度，底层数据不变）。

```
60D 按钮带 class="active"（页面默认先发）
   └─► 60 点结果写进 key=(ny, D, today)
         ├─► 52W 按钮显示 12 周 · 用户以为是 1 年
         ├─► 24M 按钮显示 4 个月 · 用户以为是 2 年
         └─► review.backfill(days=…) 走同一路径 ⇒ gold_price_daily 只有 60-80 行
               └─► /backtest/coverage 的 returns_available_days 恒为 1
                     └─► sharpe / 最大回撤 / 年化 全是空壳
```

**铁证**：同一个 URL，**9 秒内返回两种长度**（后台每 2 秒轮询 `GET /trend?days=730&interval=D`：`05:13:30 points=60` / `05:13:39 points=730`，TTL 600s 到期后覆盖）。命中之后 `days=60 / 365 / 730` 全部返回 730 点 ⇒ **现在点「60D」会拿到 3 年的日 K**，而前端三种标签共用这一份数据画图。**数据源是好的** —— 直连 `AkshareGoldHistoryProvider.get_history(days=730)` 返回 n=730（`2023-10-18 → 2026-10-22`，3 年历史完好）⇒ **一行绕过缓存的调用，把「数据源不行」和「缓存挡路」彻底分开**。

**修法**：—（本版未实施；文中给出的是修复方向与排期）。5 处「显示假的」：A3 `days` 参数完全失效（**1 行**，归一化到 60/250/500/750 档位）；A1 命中分析「上涨日数」**恒为 0**（`scoring_wide.py:294-295` 数 `"up"` / `"down"`，而 `DirectionSignal` 只有 bullish/bearish/neutral，全表 0 行 `up`；另 19/47 行用正确词汇却被丢弃）；A2 **60% 的历史行带伪造消息面 50 分**（实测 `news_index=50.0` 的有 **28/47** 行）；A4 回测 sharpe/回撤建立在 **1 个观测**上（`usable = returns_ok > 0` ⇒ 改成 `>= MIN_SAMPLES_RETURNS`，且 `available_days=14` 刚好越过 `MIN_SAMPLES_OVERALL=10`，两道门一起放行）；A5 白银升贴水表里白银有**两个价格**、差 7.28 倍（ETF 列 $7.50/oz vs NY 列 $54.62/oz）。另有承接 `next-steps.md` 的 5 条 P0（装饰性权重滑块 / AI token 统计失真 / i18n key 字面量外泄 / `window.PM_I18N` 从未定义 / freshness 时效条 3 页从未渲染）。

**验证**：—（无交付验证）。源文件「证据索引」段给出的是**复现命令**：provider 有 3 年历史 / `days` 失效 / 同一 URL 两种结果 / 上涨日数恒为 0 / 60% 假 50 / 回测 1 天可用 / 升贴水表内部矛盾 / 命中分析表全 0。另有两个诊断脚本 `_diag_hit_months.mjs` 与 `_diag_silver_mock.mjs`（`_` 前缀 = 诊断，不是门禁）。

**教训**：排期与依赖**不能乱序**（V0.117.0 → V0.118.0 → V0.119.0 → V0.120.0 → V0.121.0+）；**A3 排第一不是因为它最严重，是因为它最便宜且解锁最多**（一处改动同时解开 A4、B3 和「52W/24M 骗人」）；**参数层必须排在数据层之后** —— `scoring_daily_wide` 只有 **47 行**、其中 60% 带伪造的 news=50，**在这批数据上调阈值 = 在噪声上调参**；`roadmap.md:246` 声称「已有 ~21,900 条评估基线」，实测 47 行，**差 466 倍**（这条是 K 项的 go/no-go 依据）。**不做**：不新增任何页面/场景/功能；不动 A2 的历史数据之前不做参数层。

### V0.118.0 · 宏观面 5 因子 → 8 因子（+2Y / +10Y-2Y 利差 / +10Y 实际利率）+ dxy/vix 接实时源 + 滚动分位回填

**背景/问题**：用户诉求「宏观面的选定参数需要进行调整，添加 2Y 的美国国债收益率，再考虑添加一下其他的决定因子或者调整」。拆开看不是「多一个输入框」，而是三层问题叠在一起。

1. **因子太少，且 35% 的权重是死重**：`us10y`（4.96%，硬编码 best/worst 3.5 / 4.5）与 `us30y`（5.29%，4.0 / 5.0）**长期触底输出 0 分**；两因子合计权重 35%、宏观面占综合指数 40% ⇒ **综合指数的 14% 是恒为 0 的死重**（`docs/parameter-evaluation.md` §3.2 在两版前就提过，一直没做）。
2. **滚动分位机制造了但从未生效**：V0.79.0 Step E 造的「近 252 个交易日滚动 90/10 分位」要求单因子 ≥ 60 样本才肯切动态阈值，而 `daily_macro_factors` 表在 2026-10-25 只有 **18 天**样本 ⇒ **全部因子都钉死在 2020–2023 的硬编码 best/worst 上**，而那些阈值在 2024–2026 的市场结构下早已越界。**数据一直都在，只是没被采集。**
3. **两个关键因子停在两个半月前的常量上**：`dxy`（96.5）与 `vix`（18.5）用 `STATIC_REF` 里 2026-08-28 的硬编码值；两者在宏观面内部合计权重 0.40、宏观面又占综合指数 0.40 ⇒ **综合指数的 16% 建立在两个半月前的常量上**。

**修法**：三个设计问题问了用户并全部采纳推荐项（8 因子 / 回填历史让滚动分位立刻生效 / 两个都换实时源）。新增 `us2y`（6%，美联储 H.15 **新增列**）、`curve_10y2y`（10%，**派生** = 10Y − 2Y）、`real10y`（20%，FRED `DFII10`，权重仅次于央行购金，因为这是理论上与金价负相关最干净的一个因子）；存量 5 个权重重排（dxy 25→15、us10y 20→8、us30y 15→6、vix 15→10、cb_gold 25→25 结构性需求唯一不动）。dxy 接 Yahoo `DX-Y.NYB`（实测 **101.75**）、vix 接 FRED `VIXCLS`（**19.03**）—— ⚠ **必须同尺度**：FRED 的 `DTWEXBGS`（广义美元指数）实测 ≈ 121，与 DXY 不是同一个尺度，换了它存量手动校准值与硬编码 best/worst 会**同时失效**。三个源三套 User-Agent 规则（实测各测 2 次结果稳定）：

| 源 | `Mozilla/5.0` | 不发 UA | 结论 |
|---|---|---|---|
| FRED | **读超时**（15s） | ✅ 1.0s | **不发 UA** |
| Yahoo chart | ✅ 0.5s | ❌ HTTP 403 | 必须 Mozilla |
| 美联储 H.15 | ✅ 1.2s | ❌ HTTP 403 | 必须 Mozilla |

（FRED 的 WAF 有一份**客户端工具白名单**，名单外的 UA 会被**挂起** —— 连接建立但响应永不返回，表现为**读超时而不是 403**，极易被误判成「网络抖动」。）新增 `macro_backfill.py` + `scripts/backfill_macro_factors.py` 把三源自带的多年历史灌进表（美联储 H.15 CSV 实测全量 **12417** 行、`DFII10` 2003 至今、`VIXCLS` 1990 至今、`DX-Y.NYB` 2 年日线），**幂等**按 `(target, snapshot_date, factor_key)` 覆盖写、已达 60 样本的因子直接跳过。**静态回退值不落表**（`is_persistable_source` 按 `source.startswith("静态")` 过滤，派生利差继承 —— 两个输入只要有一个是静态的，利差也标成静态）—— 假数据把 P10/P90 带偏，**动态阈值反而比硬编码更糟**。`is_dynamic_active` 口径从写死的 `>= 4` 改成**按可滚动因子总数**判定（否则 badge 会说「使用滚动分位」，但仍有 3 个因子其实还在用硬编码阈值）。

**验证**：`pytest tests/` **1885 passed / 0 failed**（基线 1833 @V0.116.1，**+52**）；新增 `test_macro_backfill.py` 9 passed、`test_macro_sources.py` 13 passed、`test_macro_thresholds.py` +3、`test_h15_fetcher.py` +6、`test_settings_service.py` +5、`test_scheduler.py` +1。生产库回填实测各因子 **173–178 行**，`macro.macro_dynamic` 由 `false` 翻成 `true`，`dynamic_factors` = **7**（`cb_gold` 按设计跳过）。浏览器门禁全绿：`_verify_macro_factors.mjs` **56 passed**、`_verify_macro_override.mjs` 15 passed、`check_cluster_render.mjs` **461 passed**、`_verify_i18n_keys.mjs` 42、`_verify_mobile.mjs` 35、`_verify_nav_8.mjs` 26、`_verify_cmd_palette.mjs` 39、`_verify_scoring_robust.mjs` 8、`_verify_category_filter.mjs` 18 项、`_verify_multi_source.mjs` 28、`_verify_date_nav.mjs` 13 项。

**教训**：**回填激活滚动分位后，立刻暴露了第二个真 bug：分位方向整个反了** —— `_compute_uncached` 对**所有**因子一律 `best = P90` / `worst = P10`，但 8 个因子里 **6 个是负相关**（`MACRO_FACTOR_RULES` 里 `best < worst` 就是这个约定的编码）⇒ 修复前 `us2y` 4.65%（处在 8 个月高位、偏鹰）拿到 **89.2 分「最利多黄金」**、`real10y` 2.64% 拿到 86.8 分 ⇒ **宏观指数整体判反：71.2（bullish）→ 修好后 39.7（bearish）**。之所以以前没炸，是因为这个机制**从未真正激活**（样本不足 ⇒ 全部回退硬编码 ⇒ 硬编码的方向本来就是对的）⇒ **一个从未执行过的分支，藏着方向性 bug**。另修两个真 bug：回测的「启用宏观内部权重」永远跑出 0 行（`MACRO_DIM_FIELDS` 写 5 个**中文维度名**，而快照 `macro_detail` 的键一直是因子 key）；权重页的「合计 101%」（后端按比例迁出的 `0.128` / `0.096` 小数权重被前端逐个 `Math.round` ⇒ 页面标红 + 后端 `_sum_to_one` 拒收 ⇒ **用户什么都保存不了**）⇒ 改用**最大余额法**归一。**四道坏门禁**也在本轮修好：谓词引用 Node 侧常量（页面里 `ReferenceError` 被 puppeteer 吞掉只报超时）；断言查的是注释里的字面量（`trend.html` 假绿 / `silver.html` 真红）；**Service Worker 让请求拦截在第 2 次导航后静默失效**（`page.setCacheEnabled(false)` 修不了，要 `setBypassServiceWorker(true)`）；门禁启动即崩（`Illegal invocation`）。

### V0.118.1 · 宏观因子「末次落库」兜底层 + 手动校准页降级可见

**背景/问题**：V0.118.0 给 8 个宏观因子都接上了实时源，但**兜底层没跟着换** —— 上游源一挂，宏观面就静默退回 2026-08-28 的内置常量，而历史表里明明存着前几轮抓到的真值。用户在权重页「宏观因子手动校准」的「当前生效」列看到的是两个半月前的数字，且**没有任何降级提示**：

| 因子 | 页面显示 | 数据日期 | 源标识 | 同一刻的真值 | 真值数据日期 | 真值源 |
|---|---|---|---|---|---|---|
| 美元指数 | 96.5 点位 | 2026-08-28 | 静态参考值 | **101.81** | 2026-10-23 | Yahoo `DX-Y.NYB` |
| VIX | 18.5 点位 | 2026-08-28 | 静态参考值 | **19.03** | 2026-10-22 | FRED `VIXCLS` |
| 美债 2Y / 10Y / 30Y | 4.40 % 等 | 2026-08-28 | 静态参考值 | 4.65 / 4.96 / 5.29 | 2026-10-22 | 美联储 H.15 |
| 10Y 实际利率 | — | 2026-08-28 | 静态参考值 | **2.64** | 2026-10-22 | FRED `DFII10` |

**美元指数差了 5.3 个点**，且落在 `dxy` 的 best/worst 区间（94 / 107）内 —— 足以改变因子的黄金友好度评分，进而改变综合指数。触发条件是上游源不可用：实测到的具体故障是**本机 DNS 解析不了境外域名**（路由器 192.168.0.1 只解析国内域名，Yahoo / FRED / 美联储一律超时；直连 8.8.8.8 / 1.1.1.1 / 223.5.5.5 的 53 端口也全被拦）—— **间歇性发生**：同日 09:27 服务重启时源仍不可用，09:27 源恢复，宏观指数在两次请求间从「末次落库」切回「实时」。3 个宏观自动源**全部**是境外域名 ⇒ 一次 DNS 抖动就让 7 个市场因子同时失去实时源。另有一处顺带发现：滞后 chip 的条件是 `cur.source === "手动输入"` ⇒ **只有手动录入的值才提示滞后**，自动源退回常量（滞后 59 天）时页面上一个警告都没有。

**修法**：新的优先级链 **用户手动覆盖 > 自动数据源 > 末次落库的真实读数 > STATIC_REF 内置常量**。「末次落库」= `daily_macro_factors` 表里每个因子**最近一条**落库记录（新增 `MacroFactorHistoryRepository.get_latest_per_factor()`），它是**真实市场读数**，只是属于过去某一刻；源正常时行为不变、全新部署（历史表空）时仍退常量、手动覆盖优先级最高。**降级必须可辨认**，三件套缺一不可：source 前缀变成 `末次落库·<原源>`（前端据此挂琥珀色 chip）、API 新增 `MacroFactorOut.tier` 字段（`live` / `lkg` / `static`，前端**不靠匹配中文前缀**判断降级 —— 那种做法一改文案就失效）、**降级值不再落表**（`is_persistable_source()` 排除 `末次落库` 前缀；旧读数写进今天的 `snapshot_date` 等于谎报观测时间，会把滚动分位窗口压平）。派生因子 `curve_10y2y` 的两个输入**取更弱的一档**：都 live ⇒ `派生 10Y-2Y`（可落表）；掺了末次落库 ⇒ `末次落库·派生 10Y-2Y`（不可落表，混了不同日期的读数）；掺了静态常量 ⇒ `静态参考值`；历史表里已有的末次落库利差**不会**被更弱的静态派生值盖掉（降级方向不能反着来）。前端滞后 chip 从「只对手动值生效」改成覆盖所有源（自动源滞后 > 4 个日历日即提示，手动值维持 > 1 天即提示）。

**验证**：`pytest tests/` **1898 passed / 0 failed**（基线 1885 @V0.118.0，**+13** = 8 条服务层 + 5 条仓储层）。上游源全部打桩失败后跑一次 `_collect()`：8 个因子全部 `tier=lkg`（`dxy` 101.80999755859375 / `vix` 19.03 / `us2y` 4.65 / `us10y` 4.96 / `us30y` 5.29 / `curve_10y2y` 0.31 / `real10y` 2.64 / `cb_gold` 842.6），`可落表的因子: （无）` ✓。真实故障下的自动恢复也有生产环境实测（DNS 先不通、后恢复，同一次响应里的因子全部是 `tier=live`）；**兜底层在真实浏览器门禁期间也被触发过**（10:06 DNS 再次抖动，8 个因子再次降级，**所有页面门禁依然全绿**）。浏览器门禁 `_verify_synthesis_quality.mjs` **新建 7 条断言**，**反向验证过**（撤掉 `synthesis-card.js` 的改动后 2 条断言变红、exit 1）。

**教训**：**「加了实时源」不等于「实时源是唯一口径」** —— 兜底层才是决定「源挂掉时系统说什么」的那一层；**降级必须可辨认** —— 一个「看起来是当前读数」的陈旧值比一个明显的错误值更危险；**每一处消费降级信号的地方都要一起改** —— 本次就漏了综合卡的「数据质量」提示（它只认 `静态参考值` 一档，新加的 `lkg` 档对它完全隐形）；**位置参数是最容易错的一处** —— `TrendService(repo, macro, ...)` 的第 2 位传成了 `MarketDataRepository` ⇒ `await self._macro.evaluate()` 抛 `AttributeError` ⇒ 被 tool 层兜住 ⇒ `/ask` 的 `get_user_portfolio` 类工具**线上每次都失败**却没有日志告警、没有 500（而 `/api/v1/ai/health` 还显示 5 个工具已启用）；**新门禁要反向验证** ——「一直绿的断言」和「有效的断言」不是一回事。

### V0.119.0 · 宏观面新增 3 个政府债务因子（美国 / 中国 / 欧洲）

**背景/问题**：宏观面此前的 8 个因子**全部是市场价格或准市场价格**（美元 / 美债 / VIX / 央行购金）—— 没有一个因子反映「政府资产负债表」这条线，而 2025–2026 年市场的主线叙事恰恰是财政（债务上限、期限溢价、货币贬值交易）。本版把美国 / 中国 / 欧洲三国的**政府债务占 GDP** 加进宏观面（8 → **11 因子**），并为此补上两处模型原本缺的能力：**低频因子的滞后口径**与**后端自己声明「哪些因子可滚动」**。符号方向是两条互相冲突的通道（debasement「债务↑ → 利多」vs 挤出「债务↑ → 实际利率↑ → 利空」），历史证据显示**符号是 regime 依赖的**：

| 区间 | 美国债务/GDP | 黄金 | 是否符合 debasement |
|---|---|---|---|
| 2008-2012 | 52% → 82% | 833 → 1660（+99%） | ✅ |
| 2012-2016 | 82% → 105% | 1660 → 1150（−31%） | ❌ |
| 2022-2025 | 128% → 122%（回落） | 1810 → 3400+（+75%） | ❌ |

**取舍**：模型里已经有 `real10y` 在承担「实际利率↑ → 金价跌」这条通道，若债务因子也取负号等于把同一条逻辑数两遍 ⇒ 取正号（debasement）才是模型里**真正缺的那条轴**，三个因子同号 `positive=True`。阈带沿用现有惯例 —— **「债务真正影响黄金的那段区间」**，而不是 1960s–80s 低债务时代：`us_gov_debt` 140 / 60、`cn_gov_debt` 95 / 40、`eu_gov_debt` 95 / 60。权重：新增 3 个因子是**同一个全球财政周期信号的三份读数**，高度共线 ⇒ 按「一个组」定总权重 **12% = 美 5 / 中 4 / 欧 3**（美国是储备货币发行国、债务率五年从 59% 冲到 88% 的中国与模型里全是美国口径的因子相关性最低、欧央行几乎不购金故欧洲 beta 最小），旧 8 个按 **×0.88 等比缩放**（相对比例完全不动）。

**修法**：三个源**逐个实测可用**（非推测）：FRED `GFDEGDQ188S`（CBO）**122.59** / 2026Q1 / 季度、FRED `GGGDTACNA188N`（IMF WEO）**88.33** / 2024 / 年度、Eurostat `GOV_10Q_GGDEBT` **82.9** / 2026-Q2 / 季度。⚠ **欧洲口径 = 欧盟 27 国**（`EU27_2020`），不是欧元区 20 国（`EA20` = 89.3）。⚠ **FRED 的低频序列只有实际值**（预测值不进这条序列）⇒ 中国年度序列的观测年**本身就落后日历 1–2 年**。⚠ **所有低频 `data_date` 必须归一到 ISO 期末日期**（FRED 季度用季初 `2026-01-01`、年度用年首 `2024-01-01`；Eurostat 用 `"2026-Q2"` ⇒ `Date.parse` 是 `NaN`）—— 这是本版最容易静默出错的一处。UA 规则：FRED = **不带 UA**；Yahoo / 美联储 H.15 = `Mozilla/5.0`；Eurostat = **无 UA 限制**。`fetch_fred_latest(lookback_days=30)` 永远找不到季度 / 年度序列 ⇒ 改用按序列独立的 lookback（季度 **200 天** / 年度 **900 天**）。**低频因子的滞后口径**：因子规则新增 `cadence`（daily / quarterly / annual）与 `max_lag_days`（日频 4 / 季度 300 / 年度 **1100**），经 API 字段透出；前端对 `cadence != daily` 的因子改挂**中性「季度 / 年度」chip**，滞后告警只在超过 `max_lag_days`（= 源真的断了）时才亮 —— 三个新因子的滞后分别是 209 / 118 / 664 天，若沿用硬编码的 4 天阈值就是**每次都亮红灯**，而**常亮的告警等于没有告警**。年度阈值从 550 改成 **1100 天**（≈3 年 = 「WEO 连续 2 次年更没更新」才算源真的断了）。**后端自报可滚动因子**：`MacroIndexOut.rolling_factors`（此前前端是 `factors.filter(f => f.key !== "cb_gold").length` 这种两处硬编码列表，必然腐化）；3 个新因子与 `cb_gold` 一起进 `SKIP_ROLLING_FACTORS` —— 季度 / 年度因子若参与 252 日滚动分位，日频落表会把同一个值重复几十次 ⇒ **P10 == P90 ⇒ 阈值退化**。**迁移守卫**新增 `LEGACY_MACRO_8_DEFAULTS`（V0.118 的 8 键默认）与 5 键默认并列判断。**回测网格不动**（仍是 5 键）—— 新因子没有历史快照，加进去会让 `_aggregate_from_detail` 对每个历史快照返回 `None` ⇒ 回测出 0 行。

**验证**：`pytest tests/` **1921 passed / 0 failed**（基线 1898 @V0.118.1，**+23**；耗时 33:47）；`ruff check src/ tests/ scripts/` **0 error**；`check_version_sync.py` **9 passed**；`check_pwa_assets.py` 通过（SW 与应用版本一致，SHELL_ASSETS 53 条 / manifest 8 个目标 / 21 页 `rel=icon`）；`check_i18n_keys.py` **0 missing / 307 in-scope**；`check_docs_claims.py` 351 处引用；`check_links.py` 81 份文档 / 386 条链接；`check_routes.py` **20 条路由**全部返回期望 status。`_verify_macro_debt.mjs` **新建 5 段验证**（A 线上 API / B 权重页 / C 趋势页 / D 反向验证 / E 反向验证）**52 passed / 0 failed / 0 warn**（直接打**生产实例** 8888）；`_verify_macro_factors.mjs` 68 passed。线上实测：2026-10-26 宏观面 **38.9**（BEARISH，方向不变），旧 8 个单独归一后 **33.6**，**债务组净抬升 +5.3 分**；2026-10-27 复测 **38.1 / 32.65 / +5.47 分** ⇒ 抬升来自**因子本身**（债务组自身均分 77.8 / 78.2），不是某一天的读数巧合。

**教训**：**共线因子要按「一个组」定总权重**，组内再按各自对黄金的相关性分配（三份各给权重 = 同一件事说三遍）；**诚实地说出这组因子的性质** —— 它是**近乎恒定的偏移**、不是择时信号，债务水平一年才动 1–4 次，把它当 12% 权重等于把「结构性看多黄金」固化进模型，价值在**分散化 + 一个慢锚**；**方向断点不是常数** —— 计划期按静态阈值估算的「组权重 ≈18.7% 时跳到 NEUTRAL」在线上不成立，因为那 7 个日频因子走的是**滚动分位**、分值会随市场漂移 ⇒ 断点也跟着动（10-26 读数下 ≈25.6%、10-27 读数下 ≈27.1%）；**门禁的期望值必须写成「源的真实输出」** —— 用 `text.includes(String(exp.value))` 子串匹配时，`exp.value` 写的是内置兜底值 `88.33`，源一恢复渲染成 `88.327` ⇒ 子串不在里面 ⇒ **门禁翻红** ⇒ 改成数值比较 + 0.01 容差。

### V0.120.0 · 新增第 4 个评分面「资金流面」—— 按资金流向各种市场判断

**背景/问题**：用户原话两条 ——「制定计划，按照资金流动走向各种市场来判断，作为一个资金流面，什么建议」＋「我们关注的是近期的资金数据，进行周 和月的关键因子。」现有三维里**没有任何一维在看「钱本身」**：技术面看价格 / 均线 / RSI / 回撤（日频），宏观面看美元 / 利率 / VIX / 央行购金 / 政府债务（价格与存量口径），消息面看用户对投行展望的主观打分 ⇒ 「钱在流入黄金还是在撤离」这个最直接的问题**只能从价格反推**，而价格已经把信息折价完毕。新面**只收流量 / 数量类读数**（钱进黄金多少、钱在股市多少、钱的总量在增在减），**不收任何价格类读数**（不收 SHIBOR、不收汇率、不收利率）—— 价格类归宏观面，避免同一条逻辑计两遍。**范围限定**：只看**近期**资金数据，分**周**（更近）与**月**（更稳）两档。

**修法**：6 个因子（周 3 / 月 3），打分沿用宏观面公式 `score = clamp((value − worst) / (best − worst) × 100, 0, 100)`，`positive=True` 表示值越高越利多黄金；周频三个因子合计 **54%**、月频三个 **46%**：

| # | key | 名称 | 节奏 | 权重 | 符号 | 当前读数 | 当前分 |
|---|---|---|---|---|---|---|---|
| 1 | `cot_gold_net` | 黄金投机净多占 OI | 周 | **18%** | + | 25.90% | 22.5 |
| 2 | `cot_gold_flow` | 黄金投机净多 4 周变化 | 周 | **14%** | + | **−23,183 张** | 21.4 |
| 3 | `gold_etf_flow` | 黄金 ETF 4 周累计净申赎 | 周 | **22%** | + | +16.40 亿元 | 37.3 |
| 4 | `us_liq_net` | 美元净流动性 4 周变化 | 月 | **14%** | + | +14,170 $M | 69.6 |
| 5 | `cn_margin_flow` | A 股融资余额月环比 | 月 | **16%** | **−** | **−3.60%** | 94.4 |
| 6 | `cn_money_gap` | 中国 M1−M2 剪刀差 | 月 | **16%** | **−** | −4.0 pp | 11.1 |

三处拍板：资金流面在综合指数的权重 = **15%** ⇒ tech 25 / macro 35 / news 25 / **flow 15**；中国两个因子取「机会成本」负号口径；黄金 ETF 因子用 **4 周累计净申赎**（单周口径信噪比 ≈ 1 不可用）。数据源逐个实测可用：CFTC `fut_disagg_txt_YYYY.zip`（**2026-10-20 管理基金净多 104,206 张、OI 402,279、占 OI 25.90%**，已下 2019–2026 共 407 周历史）、上交所 518880 **官方每日份额**（`TOT_VOL`，近 4 周累计 **+16.40 亿元**，窗口 09-25 ~ 10-23）、FRED `WALCL` / `WTREGEN` / `RRPONTSYD`（净流动性 = 资产负债表 − TGA − RRP，4 周 **+14,170 $M**）、沪深融资余额（**上一个完整月** 2026-09 月环比 **−3.60%**）、央行 M1/M2（2026-09：M1 同比 3.2%、M2 同比 7.2% ⇒ 剪刀差 **−4.0 pp**）。**实测改掉设计**：计划初稿打算用「成交量 ÷ 换手率」**重建**份额，并据此判定周度信噪比 ≈ 1 不可用；实测时发现上交所有官方每日 ETF 份额接口（2026-10-22 **1,221,434.08 万份** → 10-26 **1,206,314.08 万份**，4 天净赎回 **5,120 万份**）⇒ **重建口径整条废弃**，官方份额没有 ±0.2% 的量化误差 ⇒ 「单周信噪比 ≈ 1 不可用」那个结论**建立在错的源上**。另有 5 个**已排除**的候选写进文档以免后人重蹈（北向资金 2024-08 起已停更 / 社融存量同比名不副实 / WGC 404 / SPDM GLD 403 / SHIBOR 是价格不是流量）。五处新机制：①滚动分位窗口必须按**观测节奏**而不是日历天（周频 104 周 = 728 天、月频 60 月 = 1826 天；`daily_money_flow_factors.snapshot_date` 存**因子自身的观测日**，只在出现新观测时写一行）；②组合权重 3 键 → 4 键的迁移守卫 `LEGACY_COMBINE_3_DEFAULTS = {tech:0.30, macro:0.40, news:0.30}`；③降级链复用 + **第 4 层语义**（一个因子都没取到读数 ⇒ 整面 `score = None`，从综合指数**剔除**，**不是记 0 分** —— 0 分会被当成「资金正在撤离黄金」，而真相是「没数」）；④**修一个真缺陷** —— 3 个声明周频/月频的因子实际在写更密的行（`gold_etf_flow` 写最新交易日、`cn_margin_flow` 写当月至今最后一个交易日、`us_liq_net` 写最新一周），修法是实时采集 / 回填 / 标定**三处同款**统一锚点（周频锚 ISO 周最后一个交易日、月频只取**已过完**的月份、`us_liq_net` 锚日历月末按 as-of 取值），并新增 `delete_factor()` + 回填 CLI 的 `--reset` 重建历史（103 行 / 53 行 / **60 行**）；⑤回测网格**不动**但把 `flow_index` / `flow_detail` 两列铺好（迁移 `r2s3t4u5v6w`），**历史从今天开始攒**。

**验证**：`pytest tests/` **2007 passed / 0 failed**（37m37s；基线 1921 @V0.119.0，**+86**）；`check_cluster_render.mjs` **461 passed / 0 failed**；`_verify_money_flow.mjs`（新建 11 段，含 2 段反向验证）**194 passed / 0 failed**；i18n 严格覆盖 **492 键 / 0 missing**。线上实测：`index.score = 29.7`、`face_weights = {tech: 0.3333, macro: 0.4667, flow: 0.2}`、`face_weights_nominal = {tech: 0.25, macro: 0.35, news: 0.25, flow: 0.15}`、`flow.score = 41.9`、`flow.flow_dynamic = True`（`dynamic_factors = 6/6`）、6 个因子 `tier` 全部 live；换 `?target=etf` 时技术面 3.9、综合指数 26.9，而**资金流面 41.9 与宏观 36.9 纹丝不动**（资金流面本身与 target 无关）。

**教训**：**声明的 cadence 必须由「观测日的推进方式」保证**，而不是靠调度器的调用频率（调度器每天跑一次，但**写不写新行**取决于观测日变没变）；**因子本身是「变化量」时，相邻观测天然重叠**（4 周变化按周采样 ⇒ 重叠 3/4 ⇒ 有效样本只剩名义值的 1/4）⇒ 「样本数达标」是假象（`min_samples` 骗了自己），变化量因子要按**变化窗口的长度**选观测节奏；**前端不重算权重也不复述权重** —— 「生效权重」从 `index.face_weights` 拿、「被剔除面的配置权重」从 `index.face_weights_nominal` 拿（此前前端文案一直写「按中性 50 参与评估（占 30% 权重）」，而算法是**剔除该面 + 其余面归一化**，**文案与算法相反**）；**i18n 的 `init()` 从不广播 `i18n:change`** ⇒ 非默认语言下 `innerHTML` 拼的组件**永久锁死简体**（实测把 `zh-TW.js` 延迟 4s ⇒ 「分面構成」变「分面构成」且不恢复），修法三处缺一不可：`init()` 广播（**仅非默认语言**）+ 暴露 `I18n.ready` / `loadLang()` 并发去重 + 组件渲染前 `await I18n.ready`；**被替换掉的调用方不是契约** —— 回测的「价格日历回填」只要收盘价却走 `analyze()`，顺带把四个面各拉一遍外网（`MoneyFlowService.evaluate()` 单次 **8.25s**）⇒ 异步回测 15s 预算直接超时（`1 failed / 10 passed`，31.3s）⇒ 新增轻路径 `fetch_price_bars()`（**1.90s** / 90 根 bar / source=live）；建表迁移还有一个真坑（`m1n2o3p4q5r6` 漏了 `primary_key=True` ⇒ `IntegrityError: NOT NULL constraint failed`，修法是重建表）。

### V0.120.1 · 资金流观测网格「今天」可注入（bugfix）

**背景/问题**：V0.120.0 的两个资金流用例在 **2026-10-31（周六）** 跑就失败，而远程 CI 在 10-29 是 **success** —— 同一份代码、同一个测试，只因为**时钟前进了两天**。失败断言里 `obs_date` 是 **10-30**（周五），而用例期望 **10-16 / 10-23**；数据构造本身没问题（交易日硬编码到 2026-10-30，被「未发布」的份额日是 10-23）。根因：用例把「今天是 2026-10-28」只写进**注释**，实际日期由 `week_end_days(trading_days)` 内部的 `date.today()` 决定。`week_end_days()` 的语义是「每个**已过完的周**的最后一个交易日」，而「已过完」的判据是**某周的周五是否严格早于今天**（周五当天不算 —— 盘中收盘价未定）：

| 传 `today` | 末周末日 | 用例期望 | 结果 |
|---|---|---|---|
| 2026-10-28（周三） | 2026-10-23 | 10-23 | ✅ 绿 |
| 2026-10-29（周四） | 2026-10-23 | 10-23 | ✅ 绿（CI 跑在这一天） |
| 2026-10-30（周五） | 2026-10-23 | 10-23 | ✅ 绿（周五「当天」不算已过完） |
| **2026-10-31（周六）** | **2026-10-30** | 10-23 | ❌ **红** |

⚠ 一旦过周六，**永久红**（数据最大只到 10-30，锚点最多推进到 10-30，再也不会回到 10-23）；同文件还有两条**月频**用例用 2026-10 的当月数据构造，靠「当月还没过完」才成立 ⇒ **11-01 起同样变红**。**关键点：这不是「测试写错日期」那么简单** —— 注释写得完全正确，问题在于**这句话没有变成代码**：`_collect_etf()` 调用 `week_end_days(trading_days)` 时**没有把 today 透传下去**，测试根本没有办法表达「现在假装是 10-28」。**对照证据：同一仓库的回填路径早就是这么做的** —— `src/app/services/money_flow_backfill.py:162` 调用 `week_end_days(trading_days, today=end)`，把回填终点显式传进去；只有**实时采集**这条路径漏了透传，而测试恰好只测实时采集。

**修法**：三个私有采集方法（`_collect_etf` / `_collect_us_liquidity` / `_collect_cn_margin`）接受可选 `today` 参数并**透传**下去（`_collect_cn_margin` 里还要丢掉**还没过完**的当月 —— 它的「月末值」其实是月内至今值）。**生产行为不变的最强证据**：`_collect()` 里的 `asyncio.gather` 调用这三个方法时**全部不传参数** ⇒ `today = None` ⇒ 回落 `date.today()`，与修复前**逐字相同** —— 改动只是多了一个「测试可用、生产不用」的入口。测试加一个常量 `FIXED_TODAY = date(2026, 10, 28)`（注释里写明「必须**显式固定**，不要让它随系统时钟漂移」）与 **6 处传参**（`_collect_cn_margin` ×2、`_collect_etf` ×2、`_collect_us_liquidity` ×2），其中 4 处是**当下就红或即将红**的用例、2 处是同一节里同源但尚未引爆的。给 `_collect_us_liquidity` 也加参数的理由：它的月频锚点来自 `month_end_days(..., today=...)`，默认同样取系统日期 —— **同一个缺陷模式**，一并堵掉，避免下个月再来一轮。

**验证**：负向验证（证明 today 真被使用，而不是碰巧变绿）—— 同数据下直接调用，传 2026-10-28 ⇒ `obs_date` = **2026-10-23**（用例期望值）；传 2026-10-31 / 2026-11-09 / `None`（系统时钟 = 2026-10-31）⇒ 2026-10-30 ⇒ `obs_date` 随注入值变化，**参数真的被消费**。`test_money_flow_service.py` **28 passed**；全量回归 **1957 passed**（原 2 failed 消失；另有 1 个 `test_main_app.py` teardown 竞态 error，单独复跑该文件 38 passed 零 error，与本次改动无因果关系）；`check_cluster_render.mjs` **461 passed / 0 failed**；`ruff check` / `ruff format --check` All checks passed / 304 files already formatted。

**教训**：**注释里的日期不是代码** —— 注释写得再对，只要没变成可注入参数就随时钟漂移变红；跨周末 / 跨月是**永久红**，CI 当时绿只是**跑得早**；**同一仓库里的回填路径往往早就是对的**，实时采集路径漏了透传 ⇒ 对照另一条路径是定位这类缺陷最快的办法。**遗留**：其它时间依赖测试未全面排查（`test_macro_thresholds.py` 等文件里也有多处 `date.today()`，目前靠「相对今天构造数据」侥幸稳定）；`test_main_app.py` 的 teardown 竞态（`_warm_cache()` 后台任务在事件循环关闭时仍 pending）；`scripts/check_routes.py` 的 5s 启动阈值低于本项目 8–25s 的冷启动需要。

### V0.120.2 · /ask 页「加载对话失败：Internal Server Error」（bugfix）

**背景/问题**：在 `/ask` 智能分析页使用对话功能，打开一个**用过工具的对话** ⇒ 前端弹「加载对话失败：Internal Server Error」—— **整个对话打不开**，不是只坏一条消息。服务端日志的真相在一行：`pydantic_core ValidationError: 1 validation error for AIMessageOut / tool_input / Input should be a valid dictionary / input_value='{"from": "2025-09-01", "to": "2026-03-29"}' / input_type=str`。缺陷链是 3 处代码 + 2 个方向不一致：

| # | 位置 | 事实 |
|---|---|---|
| 1 | `repositories/ai_chat.py:172` | 落库：`json.dumps(tool_input, ensure_ascii=False) if tool_input else None` ⇒ 存的是**字符串** |
| 2 | `models/ai_chat.py:148` | 列定义 `Mapped[str | None] = mapped_column(Text, ...)` ⇒ 存储层**自洽** |
| 3 | `schemas/ai_chat.py:65` | 对外契约 `tool_input: dict[str, Any] | None = None` ⇒ 与存储层**不一致** |
| 4 | `endpoints/ai.py:144` | `AIMessageOut.model_validate(m)`（`from_attributes=True`）⇒ 原始字符串进 dict 校验 ⇒ **ValidationError ⇒ 500** |

**落库侧是对的，错的是接口边界没解码** —— 这与 `SnapshotOut.macro_detail`（同样是 Text JSON 列、同样对外声明 dict）完全同类，而**那个 schema 早就有解码器**（V0.79.0 起）⇒ 说明「Text JSON 列」在本项目里是**已知模式**，只是这次漏了一处。之所以是「整个对话打不开」而不是「一条消息坏掉」：`GET /conversations/{id}` 一次性返回该对话的**全部**消息，其中**任意一条** `tool_use` 消息的 `tool_input` 是字符串，整个列表序列化就失败 ⇒ **一个坏字段 = 整个对话不可用**。受影响的路径有两条：`GET /api/v1/ai/conversations/{id}` **500**（用户报的就是这条）与 `POST .../messages`（同步回退）**500**；SSE 那条不受影响（走 `tool_input` 事件流，不经 `AIMessageOut`）。**为什么测试没抓到**：mock LLM 的 tool_use 入参是**空 dict `{}`** ⇒ `if tool_input else None` 把它判成 falsy ⇒ 落库 NULL ⇒ 校验通过 ⇒ 用例绿；而真实 LLM 传非空入参（实测 `get_scoring_summary({"from": "2025-09-01", "to": "2026-03-29"})`）⇒ 存成 JSON 字符串 ⇒ 才炸。⚠ `grep -rn "tool_input" tests/` 修复前返回 **0 行** —— 该字段**零覆盖**。

**修法**：在 **schema 边界**加一个 `field_validator("tool_input", mode="before")` 解码器（不落库层、不改列类型 —— SQLite 无 JSON 类型，改列要重写历史行且「接口边界该做的事不该推给存储」）。三条设计纪律（与 `snapshot.py::_parse_macro_detail` 对齐）：①**坏 JSON → 置 `None` + log warning，不抛异常** ⇒ 一个坏字段不该让整个对话打不开；②**不兜底为 `{}`** ⇒ 数据不足 ≠ 中性，空对象会被前端 `summarizeInput` 当成「工具没带参数」渲染，是**另一种假数据**；③**顶层不是 dict（JSON 数组 / 数字）也置 `None`** ⇒ 契约是 `dict[str, Any]`，不是「能解析就行的 JSON」。前端契约：`static/ask.js::summarizeInput(tool, input)` 按 `input.from` / `input.to` / `input.days` 取值 ⇒ 对外必须是对象；此前 SSE 流式路径已经是对象，**只有 GET 路径是字符串** ⇒ 修完两条路径形状一致，前端无需改动。

**验证**：反向验证（撤销修复后重跑 2 条新用例）⇒ **2 failed**（`test_tool_input_nonempty_roundtrips_as_dict` 与 `test_get_conversation_survives_corrupt_tool_input`），失败点正是两处受影响端点（`ai.py:222` 同步 POST 与 `ai.py:144` GET 详情），异常均为 `ValidationError: 1 validation error for AIMessageOut` ⇒ **用例确实在测这个缺陷**。线上实测：`GET /api/v1/ai/conversations/9ae50e30-…` 由 **HTTP 500 → HTTP 200**，该对话 **47 条**消息（含 5 条 `get_scoring_summary` 工具调用），`tool_input` 形状变为 dict `{'from': '2025-09-01', 'to': '2026-03-29'}`。`tests/test_api/test_ai_chat_endpoints.py` **17 passed**（原 15 条全绿 + 新增 2 条回归用例）。全库扫描 4 个 Text 列 ⇒ `ai_messages.tool_input` 是全库唯一一处「Text 列 ↔ dict 契约」的漏网，已补齐。

**教训**：**为什么 2007 条测试全绿** —— 空入参把真缺陷藏住了（`if tool_input else None` 这一行是分水岭）；**空 dict 落库成 NULL 是既有语义**（无入参 ⇒ 不存），改动它会波及历史行为，而 schema 侧已能同时处理 NULL 与字符串两种情况，故不动；历史脏数据仍是 `None`（实测生产库 175 条 `ai_messages` 中**仅 1 条**含非空入参，即触发 500 的那条，无其它脏数据）—— 但**对话能打开**。

### V0.120.3 · /ask 回复不可读：miniMax 原生协议外泄 + 工具层真缺陷（bugfix）

**背景/问题**：用户报「对话给出的格式 不方便阅读」，贴出的原文长这样：`我先查询今天的黄金行情及金价相关指标。]<]minimax[>[<invoke` ＋ `{"name":"get_market_data","arguments":{"query":"今天黄金现货价格、COMEX黄金期货、上海金Au99.99，以及涨跌幅和更新时间"}}`。**这不是「排版丑」，是上游把它的原生 tool-call 协议当成正文吐了出来** —— `]<]minimax[>` 是 miniMax 的协议哨兵，`<invoke` / `{"name":…}` 是它的内部调用格式。根因链 **4 层，逐层剥**：

| # | 层 | 事实 |
|---|---|---|
| 1 | 请求侧 | 回传给上游的会话**缺 assistant 的 tool_use 回合** ⇒ 协议畸形 ⇒ 上游 400 / 退化成本地协议 |
| 2 | 读取侧 | 历史库里 **10 条** assistant 消息**已被污染**（落的就是协议原文）⇒ 打开旧对话照样是垃圾 |
| 3 | 工具层 | `get_user_portfolio` 调错类、`get_scoring_summary` 强制要 from/to ⇒ 工具 100% 报错 ⇒ 模型反复重试 ⇒ **正文为空** |
| 4 | 兜底层 | 工具轮次耗尽时没有「强制作答」路径 ⇒ 用户看到的是**空白回复**（不是格式问题） |

**修法**：**第 1 层（主因）** —— Anthropic 协议要求 `assistant(tool_use) → user(tool_result)` **配对**，原实现（`ai_chat/service.py`）在拿到 tool_use 后**只** append 了 `user(tool_result)` ⇒ 上游收到的是「连续两条 user 消息，且 tool_result 找不到配对的 tool_use」。直连上游的 A/B 证据：`[user, user(tool_result)]` ⇒ **HTTP 400**；`[user, assistant(tool_use), user(tool_result)]` ⇒ **HTTP 200 + 完整 Markdown 答案**。同步与 SSE **两处**都补回合；⚠ 多个 tool_result 必须放在**同一条** user 消息里（拆成多条同样是畸形会话）。历史回放 `serializers.py::_to_claude_messages` 原来**整条跳过 tool 消息**、**从不重建 tool_use 块** ⇒ 从第 2 轮起模型看不到任何工具数据；现在按「回合」重建：回合里只有 1 个 tool 消息 ⇒ 原生 tool_use / tool_result 块且 id 严格配对；多个 ⇒ DB 只留了第一个 tool_use、无法 1:1 配对 ⇒ **退化成纯文本描述**（宁可退化也不能发畸形配对）。**第 2 层** —— 新建 `src/app/utils/protocol_strip.py`（`strip_protocol_markup()` 批量 + `ProtocolStripper` 流式）：哨兵（含 U+200B/200C/200D/2060/FEFF 变体）触发清洗，**没有哨兵则原样返回**（保护正常答案）；`<tool_call>` / `<invoke>` / `<ut>` 等标签整段删除；形如 `{"name":…,"arguments":{…}}` 的整行 JSON 整行删除；裸标识符前缀删除；3 个以上连续空行折叠为 1 个。⚠ **只清洗 assistant 正文** —— tool 消息正文**本身就是** JSON（含 `name` 键），清洗规则 3 会把工具数据整段毁掉。流式路径用 `ProtocolStripper` 在**字节流**上边喂边清，跨 delta 切断的哨兵也能识别（哨兵长度 ≤15，窗口 24）。**第 3 层（工具层的真缺陷，线上 100% 报错）** —— 这两条是**旧缺陷**，不是本次引入的，是「协议修好后工具真的跑起来了」才暴露出来：`get_user_portfolio` 原实现调 `self._position.equity_curve(...)` / `performance(...)`，但生产 wiring 注入的是 **`PositionService`**（它只有 `summary` / `list_positions`，那两个方法在 `PortfolioAnalyticsService` 上）⇒ 结果恒为 `AttributeError` ⇒ 模型反复重试 ⇒ 轮次耗尽 ⇒ 最终正文为空；`get_scoring_summary` 模型经常**漏掉** from/to ⇒ 原实现直接返 `{"error": "from/to required"}` ⇒ 同样的死循环 ⇒ 改为缺省取「近 30 天」并去掉 schema 的 `required`，在返回体里报告**实际使用的区间**（不产生假数据）。**第 4 层（安全网）** —— 整轮无正文时补一次**不带工具**的调用强制作答；⚠ 为什么不复用 `messages` 列表：那是 `assistant(tool_use)` / `user(tool_result)` 块，miniMax 代理对 tool_use_id 配对极敏感（2013）⇒ **纯文本 = 零协议风险**；失败不抛（宁可正文为空也不要整轮 500）。

**验证**：6 组新断言**逐条反向验证**（撤销 `_exec_portfolio` / `_exec_scoring` / 规则 9 / 安全网 / assistant 回合 / 读时清洗 ⇒ 对应用例变红 ⇒ 恢复 ⇒ 变绿）。目标 4 个测试文件 **50 passed**；全量 `pytest tests/` **2024 passed / 0 failed**（45:56，2026-11-03 实测）；`ruff` 全绿；快门禁全绿（`check_version_sync` 9 passed / `check_pwa_assets` SHELL_ASSETS 54 / `check_docs_claims` 351 处引用 / `check_links` **86 份文档 · 413 条链接** / `check_i18n_keys` 0 missing）。线上实测（SSE 流式主路径）：`events: user_saved → tool_call_start×3 → tool_result×3 → text_delta×27 → message_stop`，正文长度 **661**，含协议哨兵 False、含 tool_call 标记 False、含裸 `"name":` payload False。历史污染行的读取验证：生产库 **10 条**污染行逐条过一遍 —— **4 条清成空**（本来就只有协议）、**6 条保留可读散文**（含 `## 数据支撑` / `### 结论` 小标题）、**残留标记 0 条**；正常消息**字节级不变**；`role=tool` 的消息**保留原始 JSON**（那是工具数据，不是协议残留）。

**教训**：**「协议畸形」的表现是「格式脏」，根因却在请求侧** —— 用户报的是「排版不便阅读」，实际是**上游协议对不上** ⇒ 看到协议原文外泄，先查请求形状，别先调 CSS；**读时清洗优于改库**（对历史 + 新行同时生效，不写生产库、不用迁移，原始数据留作证据）；**「旧缺陷」常被「新修复」暴露** —— **别把「暴露」当成「引入」**；**桩藏住被替换的调用方**（第 3 次踩）—— 桩自己实现了被调方**没有**的方法 ⇒ 5 条 tool 测试全绿、线上 100% 坏，通用解法是用 `ast` 把「代码调的方法」与「真实类的方法集」对账（⚠ 用正则会把 docstring 里那段历史说明也扫进来 ⇒ 假红）；**正文为空 ≠ 格式问题** —— 任何多轮 agent 都要有「强制作答」的兜底路径；安全网自己也有坑 —— 上游已经报 429「已达到 Token Plan 用量上限」时它又调了一次上游、白等 ~15 秒 ⇒ 加 `llm_failed` 标志（3 个上游错误分支置位）；**「今天」必须可注入**（第 2 次踩）—— `cn_today(now=None)`，测试里写死「今天」跨周末 / 跨月**永久红**。

### V0.120.4 · 首页 hero 右侧「综合评估」结论块（feat）

**背景/问题**：用户要求「首页没有显示综合评估指数和说明，构思一下结构，让首页有版面可以显示综合评估指数。」用户拍板：**位置 = hero 右侧结论块**、**说明粒度 = 结论 + 每面因子明细**。问题在于首页（`/home`）上**一个评分都没有** —— hero 里只有金价 / 时效 / AI 三个 chip，8 张场景卡是纯导航磁贴，贵金属三卡显示的是**价格涨跌幅**不是评分；应用最核心的判断（综合趋势评估指数）只出现在趋势页，用户不回趋势页就看不到。**同时暴露的版面问题**：hero 的**右半边（约 600px）是死区** —— 文案全靠左对齐，右边一直空着。

**修法**：hero 改成两栏 grid（`minmax(0,1fr) minmax(320px,400px)`），≥980px 两栏、<980px 单栏（结论块落到文案下方）；**因子明细默认折叠**（`<details>`）—— 4 面 × 3 条展开会把 hero 撑高一倍多；样式只用 theme 变量（`--card` / `--border` / `--text` / `--muted` / `--up` / `--down` / `--accent`）⇒ 3 主题自适应；**8 张场景卡没动** —— 3 个门禁脚本硬编码了 `scenesCount === 8`（`_verify_nav_8.mjs` / `_verify_report_archive.mjs` / `_verify_home_metals.mjs`），结论块是**独立元素**，不进 `.home-scenes` grid。**关键发现 —— 零新增网络请求**：`static/home.js:81` **早就在拉** `/api/v1/market/gold/trend?days=60&target=ny&interval=D`（14KB），但只用 `points[].close` 画 sparkline —— **`response.index` 整块（score / level / direction / components / face_weights）已经在手，只是没用** ⇒ 本次**没有新增任何接口调用**，首页请求数保持 **10 个**不变。展示项全部来自已有 payload（大数字 = `index.score`；等级徽章 = `index.level` → `trend.level_*`；颜色 = `index.direction`；4 面分数条 = `index.components` + `index.face_weights`；消息面 pending = `news.scored === false` + `face_weights_nominal.news`；技术面因子 = 顶层 `indicators[]` 5 维度；宏观面因子 = `macro.factors[]` 11 因子；资金流面因子 = `flow.factors[]` 6 因子）。因子明细按 **|contribution|** 排序取前 3（**不是**按后端返回顺序 —— 那个顺序不是重要度顺序）。

**口径**：两个指数别混 —— 首页与趋势页「实时评估摘要」都用 `target=ny`（实测综合指数 **28.3 ~ 38.7**，随行情变），而趋势页 synthesis-card 用 `etf`（技术面口径不同，3.7 vs 0.1）⇒ 首页沿用 `home.js` 原有的 `target=ny`，并在卡片脚注显式写「纽约金 COMEX · 快照 HH:MM」，免得用户在趋势页看到另一个数字以为两处打架。**三个必须照抄 app 内既有口径的地方**：①公式前端重算 —— 后端 `index.summary` 是**服务端直出中文**，非中文界面下会露馅 ⇒ 前端按 `components` + `face_weights` 自己拼（照抄 `synthesis-card.js:426-435` 的 `dimsFormula`）；②权重用 `face_weights`（**实际生效**）而不是 `face_weights_nominal`（配置原值）—— 消息面未打分时该面被**剔除**、剩余面权重被**重新归一化**（实测技术 25%→33%、宏观 35%→47%、资金流 15%→20%），用配置原值会让页面上的公式和实际算法对不上；③**别用 `index.composed_by`** —— 它恒为 `"weighted"`（后端漏传），真实值在顶层 `tech_composed_by`。

**顺带修掉的 i18n 静默失效**：切到 en-US 时静态 markup 是英文，但 JS 拼的文案还是中文（`纽约金 XAU` / `COMEX 库存` / `数据截止 2026-10-29`）。根因：`home.js` 的 `t()` 读的是 `window.PM_I18N.t` —— 但 `i18n.js` 导出的对象叫 **`window.I18n`**（`window.PM_I18N` 根本不存在，只有 `window.PM_I18N_ZH_CN` 这种「字典本体」是全局的）⇒ 条件恒为假 ⇒ **首页 JS 拼的所有文案一直回退到中文**。修法：改读 `window.I18n.t`，并保留「字典里没这个 key ⇒ 用中文兜底」的语义（`i18n.t` 找不到 key 时返回 **key 字面量**，直接透传会把 `home.metals_xau` 渲染到页面上）；同时把三张贵金属卡抽成 `renderMetals()` 并加 `i18n:change` 监听（`i18n.js` 的 `apply()` 只管 `data-i18n` 元素，管不到 JS 拼的内容）。**同一个错名还污染了另外 4 处**（`home.js:32` 的等字典 `await` 也读错全局 ⇒ 每次加载白等 2 秒兜底超时且字典没到就渲染，改读 `window.I18n.ready` 后**首页首屏从 ~2.2s 降到 ~0.4s**；`toast.js:47` 的 i18n 分支从没进过、且命中分支写的是 `return key`（把 key 字面量当译文返回）；`pwa.js:26` 的 PWA 提示语；`net-status.js:58` 的断网提示条）。修完 i18n ⇒ 顶栏文案变了 ⇒ **暴露出一条「把 bug 当成期望」的门禁**：`_verify_nav_8.mjs` 断言顶栏里有「**AI 智能分析**」，追下去发现那**正是 bug**（zh-CN 顶栏 AI 项显示的是 `topnav.js` 的兜底 fb，en-US 显示的是字典值 —— 同一处顶栏两种语言两种文案）⇒ 改成**按 href 认人**（8 个稳定路径）+ 文案另与**字典值**比对（读 `zh-CN.js` 的 `nav.ask`）。

**验证**：新门禁 `scripts/_verify_home_verdict.mjs` **55 passed / 0 failed**（改动清单段记为 52 条断言）；既有门禁未回归（`_verify_nav_8` 27/0、`_verify_report_archive` 43/0、`_verify_home_metals` 34/0）；**4 组反向验证**（撤掉 `renderVerdict()` 调用 / 把 `t()` 改回 `window.PM_I18N` / 公式改用 `face_weights_nominal` / 说明直接用服务端中文 `index.summary`）；快门禁全绿；线上实测大数字与 `GET /api/v1/market/gold/trend?target=ny` 的 `index.score` **逐位相等**，4 面分数条权重 = 33% / 47% / 20%，消息面未打分 ⇒ 显示「— 25%」+ pending chip + 公式里没有消息面；移动端 390px 无横向溢出（`scrollW == clientW`），结论块堆叠到文案下方。

**教训**：**搬数据前先看现有请求拿到了什么** —— 首页早就在拉完整 trend payload，只是没用 `index` 那一块，「加个接口」往往不如「把已在手的数据用起来」；**后端直出中文的字段不能直接上多语页面** —— `index.summary` 必须在前端按结构化字段重算；**i18n 取值的全局对象名要核对** —— `window.I18n` vs `window.PM_I18N` 差一个前缀，写错就是**静默回退中文**，页面照常显示、看不出任何报错（⇒ 断言要打**字典里的期望值**，zh-TW 本身是中文，用「含汉字即失败」会把正确翻译判成错）；**门禁红了先别急着改断言 —— 先问「它断言的是契约，还是当时的样子？」** 按当时的样子写的断言，会在修好 bug 时一起变成阻力。**高度代价**：hero 由 ~215px 变成 ~328px（**+113px**）—— 这是「拿首屏空间换首屏结论」的自觉取舍：原来那 600px 是**纯空白**，现在是有内容的版面。

### V0.120.5 · 文档收敛：60 份小版本 → 6 份里程碑（docs）

**背景/问题**：`docs/` 下堆了 24 份根文档 + 61 份 release notes（13,031 行）+ 8 份分析报告，
其中**规划类文档互相重叠且基线严重过期**：

| 旧文档 | 行数 | 基线 | 问题 |
|---|---|---|---|
| `improvement-path.md` | 571 | V0.50–V0.72 | 已归档，全部交付 |
| `ux-roadmap.md` | 412 | V0.68–V0.77 | 已归档，全部交付 |
| `roadmap.md` | 779 | V0.100.0 | **落后 20 个版本** |
| `next-steps.md` | 261 | V0.116.0 | 与 `app-improvement-path` 重叠 |
| `app-improvement-path.md` | 757 | V0.116.0 | 与 `next-steps` 互引 |
| `feature-alignment.md` | 287 | **V0.80.0** | **落后 40 个版本**，且引用了已删除的文档 |

⇒ 「哪个是当前路线」要读 6 份文档才能拼出来，而其中 4 份的结论已经被后续版本推翻或修掉。

**修法**（用户拍板）：
1. **60 份逐版 release notes → 6 份里程碑文档**（`docs/releases/milestones/m0`–`m5`），
   按能力主题切分：M0 立项底座 → M1 评估底座与工程化 → M2 AI 与多市场 →
   M3 今日要闻与消息面 → M4 存档/移动端/新闻容灾 → M5 四面评估与 AI 可用性。
   逐版原文**留在 git 历史**（tag 与原文件名同名：`git show v0.118.0:docs/releases/v0.118.0.md`）。
2. **6 份规划文档 → 1 份 `docs/roadmap.md`**，且**逐条实测复核**每一条在 V0.120.4 上的真实状态
   （已修的挪进「已完成」，不再当待办）。
3. **5 份分析报告 → 1 份 `docs/reports/历史评估汇总-202609.md`**，补「当时的建议 → 实际落地版本」对照表。
4. **`check_version_sync.py` 的契约跟着改**：从「`docs/releases/v<版本>.md` 存在」
   改成「**当前版本号出现在某份里程碑文档里**」，且该里程碑必须在 `releases/index.md` 登记。

**验证**：
- `check_links.py`：**87 份文档 → 24 份**（355 条内部链接 + 4 个锚点全有效）
- `check_docs_claims.py`：350 处声明 → 224 处，仍全绿
- `check_version_sync.py`：改契约后仍能抓出「版本号没在里程碑里登记」
- `tests/test_scripts_check_links.py`：锚点夹具从「真实文档」改成 `tmp_path` 现场造
  （原来依赖已删除的 `improvement-path.md`）—— 18 passed

**教训**：**归档文档最该做的是「删掉并留 git 历史」，不是「留在原地打个归档抬头」** ——
留在 `docs/` 根的归档文档仍在门禁扫描范围内（`glob("*.md")` 非递归），
既占着入口，又随时可能因为内容过期而误导人。

---

## 三、这一阶段的通用教训

1. **「造了机制但没喂数据」等于没造；「这行代码从来没被执行过」本身就是风险信号。**
   V0.118.0 的滚动分位从 V0.79.0 起是死代码（样本永远不够），里面「一律 `best = P90`」把 6 个负相关因子的方向整个写反；V0.120.0 的 §4.4 是同款 —— 声明的 cadence 不等于观测节奏。⇒ **机制交付时必须包含「让它真的跑起来」的那一步**，而且那一步之后要**逐因子核对方向**。反过来，「从未执行过的分支」值得在全量 grep 里单独标出来审一遍。

2. **兜底层才是真正的契约；降级必须可辨认。**
   V0.118.1 在实时源与内置常量之间插入「末次落库」层（`live` / `lkg` / `static` 三档 + source 前缀 + 前端 chip），V0.120.0 原样复用并加第 4 层语义（整面 `score = None`，剔除而不是记 0 分），V0.118.0 规定静态回退值**不落表**。⇒ **加实时源 ≠ 换口径**：源挂时系统说什么，由兜底决定；而一个「看起来是当前读数」的陈旧值比一个明显的错误值更危险。

3. **门禁必须自己反向验证一次；「绿着但什么都没保护」比没有门禁更危险。**
   这一阶段至少修了 10 处坏门禁：扫描口径不一致（`check_i18n_keys.py` 只看顶层）、断言命中注释里的字面量、谓词引用 Node 侧变量（puppeteer 吞掉异常只报超时）、Service Worker 让请求拦截静默失效、门禁启动即崩（`Illegal invocation`）、只能绿一次（子串匹配 `"88.33"` vs `"88.327"`）、读到还没准备好的页面（冷 `served_cache`）、把 bug 当成期望（顶栏 fb）、429 限流被误判成页面缺陷、`DOMParser` 把 `<script>` 路由进 `<head>`。⇒ **「门禁跑了」不等于「门禁生效了」** —— 先问一句：*它控制的东西，此刻真的在它手里吗？*

4. **静默失效比报错更危险：不抛异常、不报错、门禁全绿，页面只是少一块或显示成别的东西。**
   V0.116.0（清洗器正则漏 7 个事件处理器）、V0.116.2（漏引字典 ⇒ 整页键字面量；`hidden` 属性；`querySelector` 返回 `null`）、V0.120.4（`window.PM_I18N` vs `window.I18n` ⇒ 首页文案一直回退中文）—— 三处症状完全不同，病根是同一个。

5. **桩藏住被替换掉的调用方；空入参 / 同名遮蔽 / 假路径会藏住真缺陷。**
   V0.120.3 的 `_FakePosition` **自己实现了** `equity_curve` / `performance` ⇒ 5 条 tool 测试全绿、线上 100% 坏；V0.120.2 的 mock LLM 传空 dict ⇒ 落库 NULL ⇒ 校验通过；V0.116.1 的两份字节完全相同的 `get_scoring_wide_service` 后一份遮蔽前一份；V0.120.0 的桩自己实现了 `analyze()` 走假路径。⇒ 通用解法：AST / 数值 / 集合相等对账，而不是靠桩自己「保持正确」。

6. **「旧默认值」本身也是一种用户状态，迁移必须分两支。**
   V0.118.0 的 `LEGACY_MACRO_DEFAULTS`、V0.119.0 的 `LEGACY_MACRO_8_DEFAULTS`、V0.120.0 的 `LEGACY_COMBINE_3_DEFAULTS` 都是同一形状：存量值**恰好等于旧默认** ⇒ 用户从没自定义过 ⇒ 直接落新默认；是别的值 ⇒ 真实自定义 ⇒ 按比例保留偏好。只做按比例缩放的话，会让这批用户拿到一组**谁都没设计过**的权重。

7. **「今天」必须可注入，注释里的日期不是代码。**
   V0.120.1（`week_end_days` 内部的 `date.today()` ⇒ 10-31 周六起永久红，11-01 起两条月频用例同样变红）、V0.120.3（`cn_today(now=None)`）、V0.116.1（`test_news_feed` 的 seed 写死 2026-10-19 ⇒ 随日历腐烂）。⇒ CI 当时绿只是**跑得早**。

8. **跨版本的因果链只有把两边都翻出来才看得见；门禁红了先问它断言的是契约还是当时的样子。**
   V0.116.3（V0.68.0 的自动聚焦被 V0.113.0 的无障碍修复打没）、V0.116.4（V0.112.0 的 `SCENES` 派生 + 去重把落地页挤到第 2 位）、V0.118.1（V0.110.0 的手动校准设计被 V0.118.0 的换源绕开）—— 三条链跨越 40+ 个版本。⇒ 而 V0.120.4 的 `_verify_nav_8` 断言顶栏含「AI 智能分析」，追下去发现那**正是 bug**：按当时的样子写的断言，会在修好 bug 时一起变成阻力。
