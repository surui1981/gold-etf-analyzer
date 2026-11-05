# M6 · 可信度修复（V0.121）

> **发版区间**：V0.121.0 – （进行中）｜ **状态**：活跃（最新里程碑）
> **本文件定位**：把 V0.121 线的逐版 release notes 合并成一条**可读的演进脉络**。
> **逐版原始全文**在 git 历史里（tag 与原文件名同名）：`git show v0.121.0:docs/releases/v0.121.0.md`
> **注意**：本里程碑覆盖到当前版本，**应用当前正在用的版本号以 [../../version-status.md](../../version-status.md) 为准**。

## 〇 一页结论

这一条线的起点是一句诊断：**「显示假的」不全是显示层的问题**。

V0.120.5 做文档收敛时，把 6 份互相重叠的旧规划文档合并成 1 份 `roadmap.md`，
并对每一条待办做了**实测复核** —— 结果是旧文档的结论**一半已过时、一半仍然成立但从未修**。
仍然成立的有 10 条，全部是「用户看到的数字与事实不符」：

| 类别 | 条目 | 症状 |
|---|---|---|
| 可信度 P0 | `days` 参数完全失效 | `?days=30/60/120` 返回完全相同的结果 ⇒ 52W 按钮画的是 12 周 |
| 可信度 P0 | 命中分析「上涨天数」恒为 0 | 三重根因叠在一起（口径错 + 列被覆写 + 取值词表不一致） |
| 可信度 P0 | 64% 历史行带伪造消息面 50 分 | 同一个日子两个结论；并伪造了 14 个 hit_t1 / 12 个 hit_t5 |
| 可信度 P0 | `/headlines` 渲染 i18n key 字面量 | 用户直接看见 `time.hour_ago` |
| 诚实性 | AI token 统计失真 | 页面上 token 一栏永远不显示 |
| 诚实性 | 三页的数据时效条从未渲染 | 用户以为有时效保护，实际没有 |
| 诚实性 | `group_combine` 下 5 个权重滑块是装饰 | 调参无效却显示「保存成功」 |
| 数据链 | 价格日历不追最新 | `ny` 目标最新行落后 21 天 ⇒ 回测观测窗口越用越旧 |
| 工程纪律 | 4 处门禁自身失效 | **坏门禁比没门禁更坏**：它让人以为有保护 |

⇒ **分 3 批发版**（用户拍板）：

| 批次 | 版本 | 内容 |
|---|---|---|
| **批次 0** | **V0.121.0** | **门禁自愈** —— 先修「验证手段」，再修「被验证的东西」 |
| 批次 1 | V0.121.1 | 可信度 P0（`days` / 上涨天数 / 伪造消息面 / i18n 字面量）· 含 1 个 alembic 迁移 |
| 批次 2 | V0.121.2 | 诚实性与数据链（token / 时效条 / 权重滑块 / 价格日历） |

**批次 0 排在最前不是因为它最重要，而是因为它最必要** ——
门禁坏着的时候，批次 1/2 的每一个修复都没有地方验证。

## 一、版本一览

| 版本 | 主题 | 关键交付 |
|---|---|---|
| V0.121.0 | **门禁自愈** | `check_v084.mjs` 0/27 → **27/27**；`_verify_sw_update.mjs` 0 条断言 → **8 条**（含「缓存无陈旧副本」）；`_verify_mobile.mjs` 聚焦断言改确定性轮询；roadmap 过期记录订正 |

## 二、逐版本记录

### V0.121.0 · 门禁自愈（chore · 零业务逻辑改动）

**背景/问题**：V0.120.5 的文档收敛留下一份诚实的 `roadmap.md`，
其中「§五 工程纪律（门禁健康度）」列了 4 条门禁自身的失效。本批把它们逐条修掉。
**动手前先逐条复核**（结论与 roadmap 的记录**不完全一致**）：

| # | roadmap 的记录 | 实测复核结论 |
|---|---|---|
| G1 | `check_v084.mjs` 100% 失败 | ✅ 成立 —— 且**唯一**的失败项是那条过期的 `#freshnessInline` 断言 |
| G2 | `_verify_sw_update.mjs` 没有通过计数 | ✅ 成立 —— 脚本里 `ok()` 出现 **0 次**，退出码恒 0 |
| G3 | `_verify_mobile.mjs` 聚焦断言 flaky | ❌ **已不成立** —— V0.116.3 已经修好（连续 3 跑 35/35） |
| G4 | `test_ai_chat_endpoints.py` 跨 event loop | ❌ **已不成立** —— `tests/conftest.py::_reset_sse_app_status` 已修（该文件 21 passed，`tests/test_api/` 355 passed） |

⇒ **roadmap 的两条记录是过期的**（它写于 V0.120.5，基线 V0.120.4），
本批只做**记录订正**，不假装修了一个已经修好的东西 ——
「修好」与「本来就好」在发版说明里必须分得开。

**G1 · `scripts/check_v084.mjs`：0/27 → 27/27**

*根因*：断言查的是 `#statusPanel` 内存在 `#freshnessInline`，
但 **V0.85.0**「数据时效迁移到 /data-health.html」已把它换成
`<a id="healthSummary" class="hs-chip-link">`（data-health 页上是
`<span id="healthSummary" class="hs-panel">`）⇒ **9 页 × 3 语 = 27 个组合全部失败**。

*修法*：断言**当前真实结构**（`panel.querySelector("summary #healthSummary")`），
并加一条**反向断言**（`#freshnessInline` 不得复活）——
反向断言的价值在于：下次谁再把它换回去，门禁会立刻红，而不是等到「全都红」才发现。

*反向验证*：把 `static/trend.html` 的 `id="healthSummary"` 改名 ⇒ **3/27 变红**
（trend × 3 语，正好是改动波及的那一页）⇒ 恢复 ⇒ 27/27。
（不是 27/27 全红，正是因为断言落在**真实结构**上：改一页的 id 只该红那一页的 3 个语言组合；
若改的是断言本身或某个公共挂载点，才应该 27 个组合一起红。
**「红几个」本身就是断言落点是否精确的证据**。）

**G2 · `scripts/_verify_sw_update.mjs`：0 条断言 → 8 条**

*现状*：脚本只 `console.log` 诊断信息，退出码恒为 0 ⇒ **永远绿、永远不能判红**。

*修法*：补「断言计数 + 失败即退出码非 0」，断言 5 组：

1. SW 已注册且**真的接管了页面**（`controller` 非空）+ `scriptURL` 指向 `/sw.js`；
2. 浏览器装的是**当前版本** SW（active SW 里的 `VERSION` == 服务端 `sw.js` 的 `VERSION`）；
3. **缓存里没有陈旧副本**：shell / runtime 两个 cache 的 `/static/*` 正文
   必须与网络当前正文**逐字节一致**
   ⇒ 「改了 static 却忘了 bump `sw.js` VERSION」会被这条直接抓住
   （V0.92.0 / V0.100.1 的教训）；
4. `activate` 后**旧版本缓存已清空**（`caches.keys()` 里只剩当前版本）；
5. 首页要闻卡**已渲染完**（骨架屏消失）
   ⇒ ⚠ 不能只按「li 数 > 0」判：**骨架屏本身就是 5 个 li**。

*两个坑*：

- **(a) Service Worker 只在安全上下文可用。** 用 LAN IP（`http://192.168.0.204:8888`）时
  `navigator.serviceWorker` 是 **`undefined`** ⇒ 脚本第一版直接崩在
  `Cannot read properties of undefined (reading 'controller')`。
  ⇒ 加**显式守卫**：不是安全上下文 ⇒ 打印可读结论 + 退出码 1（而不是崩）。
  （副产品：一个真实发现 —— **SW 在 LAN IP 上根本不生效**，只有本地回环才是安全上下文。）
- **(b) puppeteer 默认每次启动都是全新的临时 profile。** ⇒ SW 每次都是**重新 install**
  ⇒ `cache.addAll(SHELL_ASSETS)` 每次都把**当前**文件重新 precache 一遍
  ⇒ 「缓存里的正文 == 网络正文」**永远成立**
  ⇒ **陈旧检测是结构性失效的（假绿）**。
  ⇒ 改用**持久化 `userDataDir`**（`/tmp/gold-sw-gate-profile`），
  才能复现真实场景：**用户的 SW 是上一次访问时装的**。

*反向验证*：往 `static/home.js` 追加一行 ⇒ **7 passed / 1 failed**，
报 `陈旧条目：shell:/static/home.js（比对 4 条）` ⇒ 恢复 ⇒ 8/8。
（这条断言在换成持久化 profile **之前**是绿的 —— 即「第一版门禁抓不到它要抓的东西」。）

**G3 · `scripts/_verify_mobile.mjs`：固定等待 → 确定性轮询**

关闭命令面板后的可见性断言，原写法是「等固定 350ms 再读 `visibility`」⇒ 与 CSS 过渡赛跑。
改成**轮询到 `visibility === "hidden"` 为止**（上限 2s，每 25ms 一步）⇒ 不依赖时间常数。

**G4 · 跨 event loop：已由 `tests/conftest.py::_reset_sse_app_status` 修掉**

`tests/test_api/test_ai_chat_endpoints.py` **21 passed**；
整个 `tests/test_api/` **355 passed / 0 failed**（311s）⇒ **不需要修，只需订正记录**。

**变更清单**：

| 文件 | 改动 |
|---|---|
| `scripts/check_v084.mjs` | 过期断言 → 真实结构断言 + 反向断言；末尾补「结果：N passed / N failed」计数行 |
| `scripts/_verify_sw_update.mjs` | 整脚本重写：0 → 8 条断言、退出码判红、持久化 profile、非安全上下文守卫 |
| `scripts/_verify_mobile.mjs` | 关闭后固定 350ms 等待 → 轮询到 `visibility === "hidden"` |
| `src/app/__init__.py` / `pyproject.toml` / `uv.lock` / `static/sw.js` | 4 处版本号 → `0.121.0` / `v0.121.0` |
| `docs/roadmap.md` | §五 门禁健康度 4 条 → 逐条标注实际状态；G3/G4 订正为「已由 V0.116.3 / conftest 修掉」 |
| `docs/releases/index.md` / `docs/version-status.md` / `docs/README.md` | 登记 M6 里程碑 + 基线版本同步 |

**验证**：

| 项 | 结果 |
|---|---|
| `node scripts/check_v084.mjs` | **27 passed / 0 failed**（修复前 **0 / 27**） |
| `node scripts/_verify_sw_update.mjs` | **8 passed / 0 failed**（修复前 0 条断言） |
| `node scripts/_verify_mobile.mjs` | **35 / 35**（连续 3 跑） |
| `pytest tests/test_api/` | **355 passed / 0 failed**（311s） |
| 快门禁 | `check_version_sync` / `check_pwa_assets` / `check_i18n_keys` / `check_docs_claims` / `check_links` / `check_static_js` 全绿 |

**教训**：

1. **「崩的门禁不是门禁」—— 但「永远绿的门禁」更坏。**
   `check_v084` 崩在一条过期断言上（27/27 全红，**一眼就能看见**），
   `_verify_sw_update` 一条断言都没有（**永远绿，看起来最健康**）。
   ⇒ 后者才是真正危险的形态：**它让人以为有保护**。
2. **「门禁跑了」不等于「门禁生效了」—— 先问：它控制的东西，此刻真的在它手里吗？**
   puppeteer 的全新临时 profile 让「缓存陈旧」这条断言**永远为真**；
   只有把 profile 持久化，断言才真的握住了它要保护的东西。
3. **断言要打在真实结构上，并且要有反向断言。**
   过期断言（`#freshnessInline`）会让「修好 bug」这件事在门禁里变成阻力
   （记忆：「门禁红了先问它断言的是契约，还是当时的样子？」）；
   而反向断言（`#freshnessInline` 不得复活）把「修好」这个结论**钉死**。
4. **「修好」与「本来就好」在发版说明里必须分得开。**
   G3/G4 复核后发现**早已被修掉**（V0.116.3 / `conftest.py`）
   ⇒ 诚实地写成「订正记录」，而不是假装又修了一遍。

---

## 三、这一阶段的通用教训

（待批次 1 / 批次 2 落地后补齐。）
