# M6 · 可信度修复（V0.121）

> **发版区间**：V0.121.0 – V0.121.4（三批已全部发版 + 1 个 hotfix 收尾 + 1 个口径治本版）｜ **状态**：活跃（最新里程碑）
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
| 收尾 | V0.121.3 | **批次 2 发版后的线上复测发现 P0-2 没修干净**（桶聚合三处各写一份，两处漏填）⇒ 统一口径 + 宽表按补齐后的日历重算 |
| 口径治本 | V0.121.4 | **央行购金「季度合计」此前是重复计数**（WGC 全球合计行 + 各国明细行一起求和）⇒ 合计行独立标记、两者永不相加；首次取到 **2026Q3 = 321.2 吨**；报告版本逐版回退 + 图表按**结构**识别；手工补丁不再覆盖 WGC 国别值 |

✅ **三批已全部落地**（V0.121.0 / .1 / .2）+ 1 个收尾 hotfix（V0.121.3）+ 1 个口径治本版（V0.121.4）⇒ 这条线**已收官**。
批次 3（能力建设：C1 阈值口径可覆盖 / C2 多市场独立校准 / C3 判定阈值可评估 /
D1 命中分析的「为什么这次错」/ D2 verdict 置信度校准）**不在本 3 版内**，
见 [../../roadmap.md](../../roadmap.md)。

**批次 0 排在最前不是因为它最重要，而是因为它最必要** ——
门禁坏着的时候，批次 1/2 的每一个修复都没有地方验证。

## 一、版本一览

| 版本 | 主题 | 关键交付 |
|---|---|---|
| V0.121.0 | **门禁自愈** | `check_v084.mjs` 0/27 → **27/27**；`_verify_sw_update.mjs` 0 条断言 → **8 条**（含「缓存无陈旧副本」）；`_verify_mobile.mjs` 聚焦断言改确定性轮询；roadmap 过期记录订正 |
| V0.121.1 | **可信度 P0** | `?days=` 修复（缓存 key 加维度）；`price_direction` 新列 + 迁移 `t2u3v4w5x6y`（上涨天数 0 → 11）；伪造消息面 50 分治源头 + 幂等回填（清 26 个伪造命中）；`/headlines` i18n key 字面量修好 |
| V0.121.2 | **诚实性与数据链** | 价格日历**增量**补齐（`ny` 最新 2026-10-14 → **2026-11-06**）；组权重**真正生效**（技术面 16.4 → 4.7 → 还原 16.4）+ 5 个装饰性滑块置灰；删掉 3 处误导性时效调用 + 新门禁；AI token 显示出来了（**顺手修好「流式从未生效」**这个更大的缺陷） |
| V0.121.3 | **P0-2 收尾（hotfix）** | 桶聚合**三处统一一份口径**（`hit_stats` / `hit_stats_all_horizons` 此前漏填 ⇒ 上涨天数恒 0）；宽表按补齐后的日历**重算**（`price_direction` 覆盖 28 → **45** 行，`hit_t1` 13 → **22** 行）；**服务已重启** ⇒ 首次「代码 = 服务」 |
| V0.121.4 | **央行购金口径治本** | 全球合计行用伪 ISO `WGC_AGGR` 单独标记，**与各国明细永不相加**（旧：2026Q2 336.7 = 288.9 + 47.8）；当季 **2026Q3 = 321.2 吨**、滚动 12 月 **842.6 → 885.1**、国家数 25 → **24**；报告版本 q3→q2→q1 逐版回退 + 图表按**结构签名**识别（Q3 报告只有区域图 ⇒ **不伪造** Q3 国别明细）；手工补丁不再覆盖 WGC 国别值（UZB H1：4 吨 → **41.4 吨**）；首页卡标注「来源：世界黄金协会 GDT 全球合计」；宏观因子 `cb_gold` 同步更正 |

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

### V0.121.1 · 可信度 P0（fix · 1 个 alembic 迁移 + 1 次生产库回填）

**背景/问题**：批次 0 把门禁修成「能判红」之后，本批逐条修 P0。
动手前先**实测复核**了每一条的根因 —— 有两条与旧记录的结论**不一样**，
这直接决定了修法（见下）。

#### P0-1 · `?days=` 参数完全失效

*根因*：`served_cache` 的 key 是 `(target, interval, on_date)` —— **没有 `days`**。
⇒ `?days=30` 先算完进缓存，后面 `?days=60/120` **直接命中同一份缓存** ⇒ 返回完全相同的结果。

*修法*：`_key()` 增加 `days` 维度；`invalidate` 仍按 `(target, interval)` 匹配
⇒ 覆盖该 target 的**所有** days 变体。
⚠ 若只改 key 不改失效逻辑，就会留下**读不到也删不掉**的孤儿缓存。

*反向验证*：monkeypatch 把 `_key` 换回 3 元组 ⇒ **3/3 变红** ⇒ 恢复 ⇒ 3/3 绿。
（用 monkeypatch 而不是改源码 ⇒ 验证过程**不碰**生产代码，也不需要 worktree。）

#### P0-2 · 命中分析「上涨天数」恒为 0 —— 治本（加列 + 迁移 + 停覆写）

*实测复核的结论比旧记录更狠*：**这不是「一个词写错了」，是三层根因叠在一起。**

| 层 | 事实 | 证据 |
|---|---|---|
| ① 口径根本不是「当日涨跌」 | `daily_snapshots.direction` = 「收盘价 vs MA20 + MA20 斜率」⇒ 语义是 60 日窗口**趋势**方向 | 生产库 60 行：`down` 56 / `sideways` 4 / **`up` 0** |
| ② `change_pct` 也不是当日涨跌 | `snapshot.py` 调 `trend.analyze(days=60)` ⇒ 是 **60 日区间**涨跌幅 | 实测值 `-12.68` / `-11.83` |
| ③ 宽表列被**消息面方向**覆写 | `row.direction = direction_of(effective).value` 把消息面方向写进了**价格**方向列 | 宽表 60 行：`bullish` 7 / `bearish` 14 / `neutral` 8 / `down` 31 —— **一个列两套词表** |

⇒ `up = sum(1 for r in grp if r.direction == "up")` **永远加不上**。

*唯一可信的源*：`gold_price_daily.change_pct` 的符号（模型注释明写「相对前一交易日的涨跌幅 %」）。

*⚠ 已排除的兜底方案*：不能拿 `daily_snapshots.close` 兜底 ——
实测两源同时有数的 **27 天里方向只有 12 天一致（44%）**，
且快照 close 多数是 `gold.close(d−1)` ⇒ 兜底会**系统性错位一天**，比留空更坏。

*修法*：新增 `price_direction VARCHAR(8)`（可空）+ ETL 只从该源取值（无价格行 ⇒ NULL）
⇒ 聚合改用 `price_direction`，并新增 `known_days`（方向**已知**的天数）
⇒ 前端显示「方向已知 N / M」，**分母摊开**。

*反向验证*：让 `price_direction` 回退到 `direction` ⇒ **3 个测试变红** ⇒ 恢复 ⇒ 绿。

#### P0-3 · 64% 历史行带伪造消息面 50 分 —— 治源头 + 连带清假命中

*污染链*：

```
trend.news.score = None（今天没打分）
   └─ services/snapshot.py → news_index = 50.0            ← 源头伪造
        └─ daily_snapshots NOT NULL                        ← 源头锁死
             └─ 宽表 ETL 继承 snap.news_index              ⇒ 32 行假 50
                  └─ direction_of(50.0) = NEUTRAL（不是 None！）
                       └─ judge_hit(NEUTRAL, chg) → 按 ±0.3% 横盘判定
                            ⇒ 伪造出 14 个 hit_t1 / 12 个 hit_t5
```

*修法（4 步）*：① 改源头（模型 / schema / ETL / 补列 SQL 四处一致改成可空）；
② 宽表 ETL 不再从快照继承 `news_index`；
③ 顺带拆分 `_set_outcome`（`actual_change_pct_t*` 是**事实**，`hit_t*` 是**判定**）；
④ 消费侧 null-safe（`backtest.py`：`news_w > 0` 且 `news_index IS NULL` ⇒ **跳过该日**）。

*回填*（`scripts/backfill_news_truth.py`，幂等，先 `--dry-run` 再落库）：

| 项 | 回填前 | 回填后 |
|---|---|---|
| 快照 `news_index` = 50 | **57** | **8**（真实分，全部保留） |
| 快照 `news_index` = NULL | 0 | **32** |
| 宽表 slot=0 组 `news_index` 非 NULL | **32** | **0** |
| 宽表 slot=0 组 hit_t0 / t1 / t5 非 NULL | **14 / 14 / 12** | **0 / 0 / 0** |
| 宽表 `direction` 取值 | bullish 7 / bearish 14 / neutral 8 / down 30 / sideways 2 | **down 55 / sideways 6** |
| 宽表 `price_direction` | 全 NULL（列刚加） | **down 17 / up 11 / NULL 33** |

幂等自查：二次规划 **0 行**待修正。

*⚠ 判据是「当天有没有 `news_scores` 记录」，不是「值是不是 50」* ——
宽表 `news_slot_count >= 1` 的 29 行里有 **8 行恰好 = 50**（用户真实打了 50）⇒ 一律不动。
（判据选错 ⇒ 会误伤这 8 行。）

*反向验证*：把 `snapshot.py` 改回 `else 50.0` ⇒ **新测试变红**
（「未打分的消息面被写成了 50.0」）；恢复 ⇒ 13 passed。

#### P0-4 · `/headlines` 渲染 i18n key 字面量

*根因*：字典里的 key 是**复数**（`time.minutes_ago` / `time.hours_ago` / `time.days_ago`，
模板 `{n} 分钟前`），而 `headlines.js` 写的是 `time.min_ago` / `time.hour_ago` / `time.day_ago`
⇒ 三语字典里**都没有** ⇒ `I18n.t()` 返回 **key 字面量** ⇒ 页面正文显示 `time.hour_ago`。

*附带一个更隐蔽的坑*：原来的兜底写法 `(I18n.t(key)) || "分钟前"` **永远不会触发**
—— key 字面量是 truthy ⇒ 改用 `freshness.js:132-138` 的正确形式（`v !== key` 才算命中）。

*门禁扩容*：`check_i18n_keys.py` 的严格清单加进 `"time."`；
并让门禁**默认**输出「清单外缺失数 + 逐条位置」
⇒ 实测 404 个清单外 key 里藏着这 3 个真缺失，现在**可见**了
（位置信息还能让人一眼分出「注释里的示例」与「代码里的真引用」）。

*反向验证*：把 3 个 key 改回错的 ⇒ **门禁 9 missing / 499 in-scope** ⇒ 恢复 ⇒ **0 missing**。

#### 迁移 `t2u3v4w5x6y`

`scoring_daily_wide` 增 `price_direction VARCHAR(8)`；
`daily_snapshots.news_index` 改 **nullable**。
⚠ SQLite **不能** `ALTER TABLE ... DROP NOT NULL` ⇒ 必须用
`op.batch_alter_table(recreate="always")`（重建表 ⇒ 索引要重新确认还在）。
先在**副本库**上验过 upgrade / downgrade / 往返（索引与 61 行数据都保住），再上生产。

#### 变更清单

| 文件 | 改动 |
|---|---|
| `src/app/services/cache.py` | `_key()` 加 `days` 维度；`get/set/invalidate` 同步 |
| `src/app/services/trend.py` | `analyze()` 的缓存读写带上 `days` |
| `migrations/versions/t2u3v4w5x6y_price_direction_and_nullable_news.py` | 新增（`down_revision = r2s3t4u5v6w`） |
| `src/app/models/scoring_wide.py` | 加 `price_direction`；`direction` 注释订正（它不再承载消息面方向） |
| `src/app/models/snapshot.py` / `schemas/snapshot.py` | `news_index` 改可空 |
| `src/app/services/snapshot.py` | 不再兜底 50；订正一句撒谎的注释 |
| `src/app/utils/db_migrate.py` | 补列表 `("news_index", "FLOAT", "NULL")` |
| `src/app/repositories/scoring_wide.py` | upsert 白名单加 `price_direction`（不加 ⇒ 同日再 ETL 时永不更新） |
| `src/app/services/scoring_wide.py` | 停消息面方向覆写；`_price_direction_of()`；拆 `_set_outcome`；聚合加 `known_days` |
| `src/app/services/backtest.py` | `news_index IS NULL` ⇒ 跳过该日（不是记 0、不是记中性 50） |
| `src/app/schemas/scoring_wide.py` | `ScoringSummaryBucket.known_days`；`ScoringWideOut.price_direction` |
| `scripts/backfill_news_truth.py` | 新增（幂等回填 + 自查） |
| `scripts/check_i18n_keys.py` | 严格清单加 `"time."`；默认输出「清单外缺失数 + 位置」；usage 带行号 |
| `scripts/_verify_v0121_truth.mjs` | 新增浏览器门禁（13 条断言，覆盖 P0-2 / P0-4 的**页面**行为） |
| `static/headlines.js` | 相对时间 key 改正 + 兜底写法改正 + `tr()` 支持 `{n}` |
| `static/scoring.js` | 新增「方向已知」列（`known_days / days`） |
| `static/i18n/{zh-CN,en-US,zh-TW}.js` | 加 `scoring.known_days` / `scoring.known_days_desc` |
| `static/sw.js` | VERSION → `v0.121.1`；`scoring.js` / `headlines.js` 加进 activate 清理清单 |
| `src/app/__init__.py` / `pyproject.toml` / `uv.lock` | 4 处版本号 → `0.121.1` |

**验证**：

| 项 | 结果 |
|---|---|
| `pytest tests/test_services/test_{scoring_wide,snapshot_service,backtest_service,trend,daily_cache}.py` | **139 passed / 0 failed** |
| `python scripts/check_i18n_keys.py` | **0 missing / 501 in-scope**（反向验证时 9 missing / 499 in-scope） |
| 生产库回填（副本上先验） | 快照 49 行修正 / 宽表 ETL 61/61 天 / 二次规划 **0 行** |
| 快门禁 | `check_version_sync` / `check_pwa_assets` / `check_i18n_keys` / `check_docs_claims` / `check_links` / `check_static_js` 全绿 |

**线上实测**（`192.168.0.204:8888`，服务重启后实测）：

| 项 | 实测输出 |
|---|---|
| `/openapi.json` | `info.version = 0.121.1` |
| **P0-1** | `/api/v1/market/gold/ny-trend?days=30/60/120` → **30 / 60 / 120** 个点（修复前三次返回**完全相同**） |
| **P0-2** | `/api/v1/scoring/summary?group_by=day` → 61 桶，`up_days` **11** / `down_days` **17** / `known_days` **28**；`direction` 只剩 `down 55 / sideways 6`；`price_direction` = `down 17 / up 11 / NULL 33` |
| **P0-3** | `/api/v1/scoring` → `news_slot_count=0` 的 **32 行**里 `news_index` 非 NULL **0 行**、`hit_t1` 非 NULL **0 行** |
| **P0-4** | `/headlines` 的「上次刷新」= **"8 小时前"**（修复前显示 `time.hour_ago`） |
| 浏览器门禁 | `scripts/_verify_v0121_truth.mjs` → **13 passed / 0 failed**（反向验证时 6 failed） |

**浏览器门禁的反向验证**（`scripts/_verify_v0121_truth.mjs`，13 条断言）：

| 撤掉什么 | 门禁表现 |
|---|---|
| 「方向已知」列（表头 + 单元格） | ✗ 命中分析表存在「方向已知」列 → **红** |
| 3 个 i18n key 改回 `time.min_ago/hour_ago/day_ago` | ✗ 4 条红；`#valLastRefresh` 复现出 **`time.hour_ago`** |
| 全部恢复 | **13 passed / 0 failed** |

✅ **推送状态（如实记录）**：本地已提交 `a3153db`、打好 annotated tag `v0.121.1`，
**已于 2026-11-07 与 V0.121.2 一起推送**（发版当时 DNS 解析不了境外域名 ⇒ 首次推送失败；
DNS 恢复后补推）。
⇒ 远端 tag 计数 **114 → 116**，与本地一致；`v0.121.1` 的 `^{}` 行 = `a3153db` ⇒ 指向一致。

**教训**：

1. **一个列可以有两套词表 —— 而这在类型层面完全合法。**
   `direction` 里同时装着 `down`（趋势）和 `bullish`（消息面），
   `sum(... == "up")` 一行代码都不会报错，只会**永远返回 0**。
   ⇒ 「统计恒为 0」的第一嫌疑不是「写错了」，而是「**这列根本不是那个东西**」。
2. **兜底值是最难查的一类 bug，因为它让下游全部「看起来正常」。**
   `50.0` 兜底 ⇒ `direction_of(50.0)` 返回 **NEUTRAL 而不是 None**
   ⇒ 判定逻辑照跑 ⇒ 26 个命中是凭空造的。
   ⇒ 兜底值必须能被下游区分（NULL / None），否则它就是**沉默的造假器**。
3. **「值恰好等于可疑默认值」不等于「这个值是假的」。**
   8 行用户真打了 50 分 —— 判据若写成「值 == 50 就清掉」会误伤它们。
   ⇒ 判据必须是「**当天有没有事实记录**」，而不是「值长得像不像兜底值」。
4. **门禁要能看见「清单外」的缺口。**
   404 个清单外的 key 里藏着 3 个真缺失 —— 只要门禁只报「清单内」，
   这类 bug 就会**永远绿**。⇒ 让缺口可见（带位置）比让缺口消失更有用。
5. **改 static 之前先问「这个文件在 SHELL_ASSETS 里吗」。**
   `/static/scoring.js` 与 `/static/headlines.js` **都不在**（只有 `.html` 在）
   ⇒ 只 bump VERSION 不够，还要按 V0.92.0 模式进 activate 的 RUNTIME_CACHE 清理清单。
6. **写门禁的人，也可能写出「空转恒真」的门禁。**
   本轮新写的 `scripts/_verify_v0121_truth.mjs` 自己踩了两次：
   ① 表头按 `head === "涨"` 精确匹配 —— 而表头文案来自 i18n 字典（zh-CN 是**「上涨日数」**，
      JS 兜底串才是「涨」）⇒ 索引 `-1` ⇒ `r[-1]` 是 `undefined`
      ⇒ 求和**结构性恒为 0** ⇒ 门禁报「上涨天数非 0」失败，**而页面其实是对的**；
   ② 按 `.time-ago` / `[class*=ago]` 泛扫相对时间元素 ⇒ 扫到 **0 个**
      ⇒ 「不含 key 字面量」这条断言**恒真**，什么也没测。
   ⇒ 教训：**门禁要能先证明「它测到了东西」**。
   断言元素要**指名道姓**（`#valLastRefresh`），列定位要**有兜底断言**
   （先断言三列都定位到了，再去求和），统计要**对全表**（只看前 5 行会把
   「数据缺口」误判成「修复没生效」—— 本轮价格日历只追到 2026-10-14，最新几天必然是 0/N）。
   ⇒ 这正是「崩的门禁不是门禁」的同族病：**空转的门禁更隐蔽**，因为它比崩的更让人放心。

---

### V0.121.2 · 诚实性与数据链（fix · 零 schema 变更、零迁移）

**背景**：批次 1 修的是「可信度」—— 用户看到的**结论**与事实不符。
批次 2 修的是「诚实性」—— 用户看到的**数字本身**是假的，或者**根本没在算**。
这一批的 4 条里有 3 条的共同点是：**页面上有一个控件，但它对结果零影响**。

---

#### B1 · 价格日历永远追不到今天（数据链）

**背景**：`gold_price_daily` **不是调度任务写的** —— 它是 `backtest.ensure_price_calendar()`
在**用户跑回测时按需回填**的。实测 `ny` 目标最新行 **2026-10-14**（落后 21 天）、
`etf` 2026-10-28（落后 7 天）。

**根因有 layers 层**（旧文档只写了一层）：

| 层 | 事实 | 后果 |
|---|---|---|
| ① | `ensure_price_calendar()` 在 `force=False` 时「**区间内已有数据就整段跳过**」 | all-or-nothing ⇒ 只补过一次之后**永远不会再补** |
| ② | 调用点套着 `if not cov.usable:` | 覆盖 deemed 可用时**压根不调用回填** |

⇒ 两层任一成立，价格日历就停在原地。

**修法**：

1. 新增 `_calendar_gap_days()` —— 按**交易日**算缺口，只补缺口那一段
   （尾部滞后 / 头部不足 / 中段空洞三选一，取最大）；
2. 调用点从「`cov.usable` 才回填」改成「**每次都尝试追平**」。

**两个必须记下来的口径坑**：

- ⚠ **窗口大小按「bar 数」而不是「日历天」算** —— `market_providers` 的 `days` 是
  **K 线根数**（`df.tail(days)`）⇒ 用日历天当窗口会**多取一倍**；
- ⚠ **容忍度按交易日算** —— 窗口起点常落在周末 ⇒ 用日历天判断「头部缺了」
  ⇒ 每次回测都触发一次无用抓取。

**线上实测**（临时 loopback 实例跑新代码，8888 未重启）：

| 目标 | 修复前 | 修复后 |
|---|---|---|
| `ny` | 80 行 / 最新 **2026-10-14**（落后 21 天） | **97 行 / 最新 2026-11-06** |
| `etf` | 73 行 / 最新 2026-10-28（落后 7 天） | **80 行 / 最新 2026-11-06** |
| 回测覆盖报告 | `price_calendar_days=15` · `returns_available_days=12` | **22 · 18** |

**反向验证**：撤掉调用点的追平逻辑 ⇒ 新增测试变红 ⇒ 恢复。

---

#### P0-7 · `group_combine` 下 5 个权重滑块是装饰（诚实性）

**根因**：`trend.py` 的 `GROUP_WEIGHTS = {trend:0.50, overbought:0.30, risk:0.20}` 是
**模块级常量** ⇒ 真正参与合成的是它；而页面让用户调的是**另外 5 个维度权重**
⇒ 用户拖滑块 → 数字变 → 求和校验显示「100% 绿」→ 保存成功 → **对结果零影响**。

**修法**（用户拍板：**置灰 + 说明 + 补组权重入口**）：

| 层 | 改动 |
|---|---|
| schema | `schemas/settings.py::WeightConfig` 加 `group_weights: GroupWeightConfig`（trend / overbought / risk，**带「和为 1」校验器**，与 `MacroWeightConfig` 同型） |
| service | `services/settings.py::WeightService` 加 `group_weights() -> dict[str, float]` |
| 计算 | `services/trend.py::combine_by_group()` 接受真实生效的组权重（缺省仍回退模块常量）；`TrendService.analyze()` 把 `group_weights` 一路传到合成层 |
| 前端 | 组内平均模式下 5 个滑块**真 `disabled`**（不是「看起来灰」）+ 一行说明「生效的是下方 3 个组权重」+ 新增 3 个组权重滑块（默认 0.50/0.30/0.20） |

**线上实测**（改组权重 → 看技术面分 → 还原）：

```
group_weights (0.5/0.3/0.2) → (0.1/0.1/0.8)  ⇒  技术面 16.4 → 4.7
还原 (0.5/0.3/0.2)                          ⇒  技术面 回到 16.4
```

⇒ 组权重**确实参与计算**（不是又一个装饰性控件）。
⚠ 实测用的组权重**已还原**为生产默认值（0.50/0.30/0.20）。

**反向验证**：① 撤掉「组权重真正参与计算」⇒ **3 个测试变红**；
② 去掉滑块的 `disabled` ⇒ **浏览器门禁红** ⇒ 恢复。

⚠ **写测试时踩到的坑**：`TrendService` 的结果走 `served_cache` ⇒ 改了组权重却不
`invalidate_cached_results()` ⇒ 测试会命中旧缓存 ⇒ **断言恒真 = 空转**。

---

#### P0-6 · 三页的「数据时效保护」是假的（诚实性）

**实测与计划的差异（如实记录）**：计划里写「4 处」，**实测是 3 处**。

| 页 | 事实 | 后果 |
|---|---|---|
| `portfolio.html` / `trades.html` | 调 `window.FreshnessBar.load()`，但**没引 `freshness.js`** | 该对象恒为 `undefined` ⇒ 守卫静默跳过 ⇒ **死代码** |
| `settings.html` | 引了 `freshness.js` 但**没有容器** | 脚本每 60 秒空轮询一次外网接口并渲染到不存在的节点 ⇒ 纯浪费 |
| `news.html` | 有 `#freshnessBar` 容器 | **正当用法** ⇒ 不动 |

**修法**：**删掉那 3 处误导性调用**（比补容器 + 补脚本 + 补设计更诚实、成本更低）。

**新增通用门禁 `scripts/check_freshness_consistency.py`**：
「引了 `freshness.js` ⇒ 必须有容器」+「调了 `window.FreshnessBar` ⇒ 必须引脚本」
⇒ **这类**缺陷以后会自己变红，不再靠人工复核。

**反向验证**：恢复那 3 处调用 ⇒ 门禁红 ⇒ 恢复。

---

#### P0-5 · AI token 一栏永远不显示（诚实性）

**两层原因叠加**，而且第二层比计划更深：

| 层 | 事实 | 修法 |
|---|---|---|
| 客户端 | `case 'message_stop'` **从不读** `payload.usage`；`currentRound.inputTokens/outputTokens` 恒为初值 ⇒ commit 写的是 `null` ⇒ 页面 token 栏**永远不显示** | **先读 usage 再 commit**（顺序反了就挂不上）；初值改 `null`（未知）；`|| null` 改 `?? null`（0 是合法值，`\|\|` 会把它也变成 null） |
| 服务端 | 拿不到的输入 token 写 **0**（= 谎称「用了 0 个 token」）⇒ 改写 **NULL** | 加 `saw_input_usage` 标志：真收到过 `StreamMessageStart` 才算「已知」 |
| ⚠ **解析层** | `claude.py` 的 `int(usage.get("input_tokens") or 0)` 把「**字段缺失**」洗成了「0」；而 miniMax 代理**照发** `message_start`，只是 `usage.input_tokens` 要么缺失、要么**报 0** —— 请求必带 system prompt + tools + 历史 ⇒ 真实输入 token **不可能为 0** ⇒ 代理的 0 其实是「**没数**」 | 解析层保留原值（缺失 ⇒ `None`）；**策略放在落库层**：「字段缺失 **或** 值为 0 ⇒ 未知」⇒ 一处说了算 |

**线上实测**（真 SSE 抓包）：

```
message_stop.usage = {"input_tokens": null, "output_tokens": 1874}
落库               = (input_tokens=NULL, output_tokens=1874)      ← 修复前是 0
```

**🐛 顺带修好一个更严重的缺陷（此前从未被发现）**：

`static/ask.js` 的 `var userMsg` 在 `sendMessage()` 的作用域里，
而 `handleEvent()` 在 `sendMessageStream()` 里 —— **两个不同的函数作用域**
⇒ `user_saved` 事件一进来就 `ReferenceError: userMsg is not defined`
⇒ **整条 SSE 流当场死掉** ⇒ 每次提问都**静默降级**到同步端点
⇒ **/ask 的「流式」自 V0.98 C5 起从未真正生效过**（页面看起来能用，所以没人发现）。

这是本轮 P0-5 能被端到端门禁抓到的直接原因 ——
**「token 不显示」这个表象下面还藏着一个「流式根本没跑」的病**。

**新增浏览器门禁 `scripts/_verify_ask_tokens.mjs`**（6 条断言）：

- 用**假 SSE** 驱动 ⇒ 不调真模型、不花 token、不产生真实对话；
- 场景 1：上游报了 usage ⇒ 必须显示 `↓ 10` / `↑ 42`；
- 场景 2：上游没报 ⇒ **一个都不显示**（不拿 0 充数）；
- `LIVE=1` 模式打**真实模型**跑整条链（会消耗 token + 建一条对话 ⇒ 默认不跑）。

⚠ **写门禁时又踩了一次「空转恒真」**：场景 2 原本查「剩下的 meta 都不含 ↓/↑」，
而剩下的数组**是空的** ⇒ 断言恒真 ⇒ 加了「第 2 条 assistant 消息真的渲染出来了」
（`asstCount === 2`）前置断言。

**反向验证**：客户端去掉 usage 读取 ⇒ **浏览器门禁 3 条红**；
服务端去掉 `if saw_input_usage else None` ⇒ **2 个测试红** ⇒ 恢复。

---

#### 变更清单

| 文件 | 改动 |
|---|---|
| `src/app/services/backtest.py` | `ensure_price_calendar()` 增量补齐；`_calendar_gap_days()`；调用点每次追平 |
| `src/app/services/trend.py` | `combine_by_group()` 接受 `group_weights`；`analyze()` 传真实生效值 |
| `src/app/schemas/settings.py` | `GroupWeightConfig`（和为 1 校验器）；`WeightConfig.group_weights` |
| `src/app/services/settings.py` | `WeightService.group_weights()` |
| `src/app/services/ai_chat/service.py` | `saw_input_usage` / `saw_output_usage`；未知写 **NULL**；`bump_stats` 只统计已知值 |
| `src/app/services/llm/claude.py` | `StreamMessageStart.input_tokens: int \| None`；解析层不再 `or 0` |
| `static/ask.js` | `message_stop` 先读 usage 再 commit；初值 `null`；`?? null`；**修 `userMsg` 作用域 bug** |
| `static/weights.html` | 5 个滑块 `disabled` + 说明 + 3 个组权重滑块 |
| `static/{portfolio,trades,settings}.html` | 删掉 3 处误导性时效调用 |
| `static/i18n/{zh-CN,en-US,zh-TW}.js` | 组权重相关文案（3 语） |
| `static/sw.js` | VERSION → `v0.121.2`（V0.100.1 铁律：`ask.js` 已在 `SHELL_ASSETS` ⇒ 换代即重新 precache） |
| `scripts/check_freshness_consistency.py` | 新增（P0-6 这类缺陷的通用门禁） |
| `scripts/_verify_weights_group.mjs` | 新增（组权重滑块态 + 真的影响结果） |
| `scripts/_verify_ask_tokens.mjs` | 新增（P0-5 端到端，含 `LIVE=1` 模式） |
| `src/app/__init__.py` / `pyproject.toml` / `uv.lock` | 4 处版本号 → `0.121.2` |

**验证**：

| 项 | 结果 |
|---|---|
| `pytest` 5 个目标文件（price_calendar / trend / settings_service / ai_chat_endpoints / llm_client） | **136 passed / 0 failed** |
| `ruff check src tests scripts` | All checks passed |
| 快门禁 | `check_version_sync` / `check_pwa_assets` / `check_i18n_keys` / `check_docs_claims` / `check_links` / `check_static_js` 全绿 |

**线上实测**（⚠ **8888 未重启** —— 本轮的重启命令被环境策略拦下：
不能 `kill` 非本会话创建的进程 ⇒ 改用**临时 loopback 实例**（8891 / 8892）跑新代码，
自带 `timeout` 自毁）：

| 项 | 实测输出 |
|---|---|
| **B1** | `ny` 80→**97** 行 / 最新 2026-10-14→**2026-11-06**；`etf` 73→**80** 行 / 最新 2026-10-28→**2026-11-06**；回测覆盖 `price_calendar_days` 15→**22** / `returns_available_days` 12→**18** |
| **P0-7** | 组权重 (0.5/0.3/0.2)→(0.1/0.1/0.8) ⇒ 技术面 **16.4 → 4.7**；还原 ⇒ **回到 16.4**（生产设置已还原） |
| **P0-5** | 真 SSE `message_stop.usage = {"input_tokens": null, "output_tokens": 1874}`；落库 `(NULL, 1874)` |

✅ **推送状态（如实记录）**：本地已提交 `f823909`、打好 annotated tag `v0.121.2`，
**并已推送**。
- 发版途中本机 DNS 解析不了境外域名 ⇒ 首次推送失败；
  收尾时 DNS 已恢复（`getent hosts github.com` → `20.205.243.166`、
  `curl https://github.com` → **200**）。
- 推送走 **`GH_TOKEN` 环境变量 + `gh auth git-credential`** ⇒ token **不进 argv、
  不落盘、不进 `remote.origin.url`**。
- ✅ **远端已核实**：`ls-remote --tags` 去掉 `^{}` 行后 **116 个**（此前 114）；
  `v0.121.1` → `a3153db`、`v0.121.2` → `f823909`；
  `refs/heads/main` = `eec4ddd` = 本地 HEAD。

⚠️ **留给用户的 3 步**（本轮环境策略拦下，只能由用户在主机上执行）：

1. ~~**重启 8888**~~ ⇒ ✅ **已完成**（V0.121.3 轮次里用 systemd 重启，
   服务已加载 `0.121.3`；V0.121.2 的修复随之全部生效）；
2. `LIVE=1 node scripts/_verify_ask_tokens.mjs`（打真实模型，消耗 token ⇒ 默认不跑）；
3. 归档本轮实测留下的 **4 条**测试对话（「一句话说明今天金价的主要驱动」）——
   生产库里，`DELETE` 被环境策略拦下。走 API 是**软删除**（`is_archived=True`）：

   ```bash
   for id in b2ea29fa-ba3f-4caa-9d8c-b050e096ecb5 \
             7b429ee1-712b-4f45-8880-b1923eb6622e \
             ff0d6630-a526-4873-b81c-7b7b7ae858f1 \
             8a86a363-b9dc-4c66-82e1-9f6f331619c2; do
     curl -s -o /dev/null -w "%{http_code} $id\n" -X DELETE \
       "http://192.168.0.204:8888/api/v1/ai/conversations/$id"
   done
   ```

   （本机 `AUTH_ENABLED=false` ⇒ 不需要带凭据；若生产开了认证，需先取 session cookie。）

**教训**：

1. **「增量」和「全量」只差一个条件判断，但语义天差地别。**
   `ensure_price_calendar()` 写的是「区间内**已有数据就整段跳过**」——
   这话读起来像一种优化，实际上把补齐变成了**一次性**。
   ⇒ 凡是「补数据」的代码，条件必须是「**有没有缺口**」，不是「有没有数据」。
2. **窗口参数的口径必须对着调用方看，不能对着字面看。**
   `days=60` 在行情源那边是 **60 根 K 线**，不是 60 个日历天 ——
   按字面理解会多取一倍。按日历天算的「头部是否充足」判断，
   又会因为起点落在周末而**每次都判定为缺失** ⇒ 每次回测都触发无用抓取。
3. **「页面上有个控件」不等于「这个控件参与计算」。**
   5 个权重滑块能拖、能保存、能显示 100% 绿 —— 因为它们**本来就该是绿的**：
   求和校验检查的是**它们自己**，而合成读的是**另一套常量**。
   ⇒ 凡是「调参类」控件，都要有一条**端到端的因果断言**：
   「改了参数 ⇒ 结果变了」。本轮的门禁就是这么写的。
4. **装饰性控件的最优修法通常是「置灰 + 说清楚」，不是「删掉」。**
   删掉会让老用户以为「我以前调的那个东西没了」；
   置灰 + 一行说明 + 补上**真正生效的那个入口** ⇒ 用户既知道发生了什么，又能继续调。
5. **上游报 0 和上游没报，是两件事。**
   请求必带 system prompt + tools + 历史 ⇒ 真实输入 token 不可能为 0
   ⇒ 代理报 0 一定是「**没数**」⇒ 落库写 NULL 才诚实。
   ⇒ **「0」和「未知」必须用两个不同的值表示**（这是 V0.78.0 Step D 纪律的延伸：
   数据不足 ≠ 中性）。`or 0` 是把两者合并的惯用写法 ⇒ 也是惯用的 bug。
6. **一个表象下面可能藏着一个更大的病 —— 端到端门禁是唯一的照妖镜。**
   「token 不显示」的表象下面藏着「**SSE 流从未跑过**」。
   只查「页面上有没有那个数字」的测试**照样绿**；
   只有**把整条链跑通**（真 SSE → 客户端 → 页面）才会发现
   `ReferenceError` 把流掐死在第一帧。
7. **变量声明在哪个函数里，是有语义的。**
   `var userMsg` 写在 `sendMessage()` 里，`handleEvent()` 在 `sendMessageStream()` 里
   ⇒ 一个 `ReferenceError` ⇒ 静默降级 ⇒ 流式功能「看起来能用」地死了半年。
   ⇒ 浏览器门禁必须**断言降级没发生**（本轮加的就是这条：
   页面 console 里出现 `SSE stream failed` ⇒ 直接判红），而不只是断言「结果对」。

---

### V0.121.3 · P0-2 收尾：桶聚合三处各写一份（hotfix · 零 schema 变更、零迁移）

#### 一句话结论

> V0.121.1 把「上涨天数」修好了，但**只修好了三处里的第一处** ——
> 命中分析页真正取数的那两个端点**仍然返回 0**。

#### 根因：桶聚合被抄了三份，P0-2 只改了其中一份

`ScoringSummaryBucket` 这一个 schema 被**三个端点**共用：

| 端点 | 聚合函数 | V0.121.1 之后填没填 `up/down/known` |
|---|---|---|
| `/scoring/summary` | `summary()` | ✅ 填了 |
| `/scoring/hit-stats` | `hit_stats()` | ❌ **没填** |
| `/scoring/hit-stats-all` | `hit_stats_all_horizons()` | ❌ **没填** |

三处各自写了一份「按月分桶 → 构造 `ScoringSummaryBucket`」的代码。
V0.121.1 改了 `summary()` 里那一份 —— 另外两份是**抄出来的副本**，
抄的时候没带这三个字段 ⇒ Pydantic 用 schema 默认值 `0` 兜上 ⇒ **API 返回 0**。

⚠ **为什么 0 比 null 更坏**：

```js
const kd = (b.known_days == null) ? '—' : `${b.known_days} / ${b.days}`;
```

前端对 `null` 有「—」兜底（= 承认「不知道」），
但 `0` 会被**如实渲染**成「上涨 0 · 下跌 0」——
这正是 P0-2 要消灭的**那种假结论**，只是换了个端点出现。

（命中分析 Tab 本身只画命中率柱状图，不显示涨跌天数 ⇒ **用户可见路径没错**；
但 API 契约已经在说假话，任何后续消费方都会踩中。）

#### 修法：口径只剩一份

抽出 `_bucket_direction_stats(rows) -> (up, down, known)`，
三处桶聚合统一走它 —— 口径从此**只有一份**，改一处即改三处。

#### 数据回填：宽表按补齐后的价格日历重算

B1 把价格日历追到了 2026-11-06，但 **10-15 之后的宽表行是日历补齐前算的**
⇒ `price_direction` 为空；10-13/10-14 这类行连 T+1 结果都算不出。
⇒ 用 `scripts/backfill_scoring_wide.py` 重跑 2026-09-07 ~ 2026-11-07（62 行，幂等）。

| 指标 | 回填前 | 回填后 | 说明 |
|---|---|---|---|
| `price_direction` 非空 | 28 | **45** | 覆盖 2026-09-07 ~ 2026-11-06 |
| `hit_t1` 非空 | 13 | **22** | T+1 结果补齐 |
| `hit_t5` 非空 | 11 | **21** | T+5 结果补齐 |
| `gold_ny_close` 非空 | 28 | **45** | NY 金收盘价补齐 |
| 总行数 | 62 | 62 | 未增删行 |

✅ **剩下的空值都是诚实的**：

- `price_direction` 剩余 17 行 ⇒ **全是周六/周日**（无交易日 ⇒ 方向未知）；
- `hit_t1` 剩余空值只剩三类 ⇒ **非交易日 / 无消息方向（不该判定）/ 未来未到**。

（回填前后用**备份库**逐项对拍，不是凭印象。）

#### 验证

| 项 | 方式 | 结果 |
|---|---|---|
| 反向验证 ① | 撤 `hit_stats` 的三字段 | 2 条测试变红、另一条仍绿 ✅ |
| 反向验证 ② | 撤 `hit_stats_all_horizons` 的三字段 | 2 条测试变红、另一条仍绿 ✅ |
| 恢复 | — | `26 passed` ✅ |
| 线上实测 | `/scoring/hit-stats-all` t0·2026-10 | 涨 0 · 跌 0 · 已知 0 → **涨 4 · 跌 6 · 已知 10** ✅ |
| 线上实测 | `/scoring/hit-stats` t1·2026-09 | 涨 0 · 跌 0 · 已知 0 → **涨 5 · 跌 6 · 已知 11** ✅ |
| 线上实测 | `/scoring/summary` 2026-10 | 涨 9 · 跌 13 · 已知 22（与上两处口径一致）✅ |

#### 教训

1. **schema 共用 ≠ 口径共用。** 三个端点返回**同一个** `ScoringSummaryBucket`，
   却不代表三处**按同一口径填**它。
   ⇒ 共用 schema 的地方，口径要抽成**一个函数**，而不是各写各的。
2. **「修好了」要按**端点**数，不按**函数**数。**
   P0-1/2/3/4 四条修完，V0.121.1 的验收是「主表有数了」——
   而**用户看的那张表**恰好是唯一被改过的那处 ⇒ 复测才暴露剩下两处。
   ⇒ **验收要遍历所有返回该 schema 的端点**，而不是挑一个看。
3. **默认值的语义要审计。** `up_days: int = 0` 这个默认值，
   在有数据时是**兜底**，在没填时是**一句假话**。
   ⇒ 聚合类字段宁可 `int | None = None`（前端已有「—」兜底），
   也不要 `= 0` —— **0 会被当成结论**。

#### 推送状态（如实记录）

✅ **已于 2026-11-07 11:01 推送到 GitHub。**

| 项 | 值 |
|---|---|
| `refs/heads/main` | `1e41af5` = 本地 HEAD ✅ |
| `refs/tags/v0.121.3` | tag 对象 `ac170e8`；`^{}` 行 = `1e41af5` ✅ 与本地 `git rev-parse v0.121.3^{commit}` 一致 |
| 远端 tag 数（去掉 `^{}` 行） | **117** = 本地 117 ✅ |

**这次推送是被网络逼出来的** —— 本机到 GitHub 的通道绝大部分时间是断的：
路由器 DNS 只解析国内域名（`baidu.com` 成功、`github.com` / `pypi.org` 超时）、
12+ 个裸 IP 绝大多数超时、本机**没有 IPv6** ⇒ 走的是「**持续重试直到窗口打开**」：

1. 用 **DoH**（`dns.alidns.com` / `doh.pub`）绕开系统 DNS 拿到 GitHub IP；
2. 并行探测这些 IP，通了就用 **git 2.43 的 `http.curloptResolve`**（`host:port:address`，
   SNI 仍带 `github.com`）**完全绕开 DNS**；
3. ⚠️ **不依赖 `git push` 管道末尾的 `tail`** —— 它的退出码恒为 0，
   会把「推送失败」伪装成「推送成功」；必须取 `${PIPESTATUS[0]}`；
4. **成功判据 = `ls-remote` 读回的 `refs/heads/main` == 本地 HEAD**，不是「命令没报错」。

⚠️ 另一个前提是 **classic PAT** —— gh keyring 里那枚 `github_pat_` fine-grained 的
**没有写权限**。本枚 classic PAT 同样在 chat 里明文出现过 ⇒ **用完即轮换**。

### V0.121.4 · 央行购金口径治本：「合计 + 明细」的重复计数（fix · 零 schema 变更、零迁移）

> 起因是一句用户诉求：「**世界黄金协会央行三季度购金 321 吨，写到主页**」。
> 核对时发现：首页那个数（以及 `/central-bank` 页的 KPI、宏观因子 `cb_gold`）
> **是重复计数算出来的** —— 而且**从未有人质疑过它**，因为它看起来完全合理。

#### 一、根因：两类行被放进同一张表，然后被一起求和

`central_bank_purchases` 表里同时住着两类**语义完全不同**的行：

| 行类型 | 口径 | 谁写的 |
|---|---|---|
| **全球合计行** | WGC 对**全部**央行的**估算**（含未披露国家） | WGC GDT 报告的「按季合计」图 |
| **各国明细行** | **已披露**（reported）国家的实际值 | WGC GDT 报告的「按国家」图 |

而旧代码算「季度合计」的方式是 **全表按季度求和** ⇒
**合计 + 明细** ⇒ 重复计数。实测（用备份库对拍，不是回忆）：

| 指标 | 修复前 | 修复后 | 说明 |
|---|---|---|---|
| 最新季度 | 2026Q2 | **2026Q3** | 取到了新一版报告 |
| 当季合计（KPI「截至当季」） | **336.7** | **321.2** | 336.7 = 合计 288.9 + 各国 47.8 |
| 滚动 12 月合计 | **842.6**（窗口 2025Q3–2026Q2，同窗口真值 **790.2**） | **885.1**（窗口 2025Q4–2026Q3） | 同一个错法在窗口上重复 |
| 参与国家数 | 25 | **24** | 旧口径把「全球合计」当成了一个国家 |

⚠️ 注意「25 → 24」这一行：旧口径**把「全球合计」当成一个国家算了进去**
⇒ 用户看到的「25 个国家」里有一个根本不是国家。

#### 二、修法：合计行独立标记，两者**永不相加**

1. 全球合计行用**独立伪 ISO** `WGC_AGGR` 标记（`COUNTRY_NAMES` 里给它中文名「全球合计」）；
2. 仓储 `t12m_total()`：**有合计行就只取合计行**；没有才退回各国之和（口径不同，但好过没有数）；
3. 服务 `summary()` 的当季合计同规则；`country_count` **排除**合计行；
4. `top_buyers()` **跳过**合计行 —— 它是合计口径，不是「买家」，
   混进排名会把真正的小买家挤出 Top 10，还让人误以为「全球合计」是个国家；
5. 前端堆叠图**剔除**合计行（否则柱状图又是「合计 + 明细」）；
   但**明细表里仍可见**（数据没被藏起来，来源标记为「WGC 合计」）。

#### 三、取数链：报告版本回退 + 图表按**结构**识别

WGC 每年只发 q1/q2/q3 三版报告页（**Q4 没有独立报告页，URL 直接 404**）⇒ 候选按「新 → 旧」逐版回退：
`q3 → q2 → q1 → 去年 q3 …`。

⚠️ **同一版报告里，标题都含 "central bank" 的图有好几张**（Q3 2026 的 Chart 2 / 10 / 11）。
只靠标题取图 ⇒ **取错图不会报错，只会静默给出另一个口径的数**。⇒ 改为按**结构签名**判定：

| 图类型 | 结构签名 | 依据 |
|---|---|---|
| 按季合计图 | series 名是 `Q1..Q4` **且** 类目轴是年份 | WGC 固定画法 |
| 按国家图 | series 含 `Net purchases` / `Net sales` **且** 类目轴**不是**年份 | WGC 国别图固定命名 |

⚠️ **Q3 2026 的 Chart 11 标题写着 "reported central bank purchases"，但它是按区域**
（China / Rest of Asia / Poland / Rest of Europe …）⇒ 结构签名把它**正确排除**。
这条是本轮最容易踩的坑：**标题对、结构错**。

📌 **不伪造 Q3 国别明细**：Q3 报告只发区域图 ⇒ 最新可用的国别明细仍是 **Q2 2026 的 H1**（23 国）。
宁可少一季，也不拿区域值冒充国别值 —— 这与「未知记『—』不记 0」是同一条纪律。

#### 四、同批发现的第二个缺陷：手工补丁**覆盖**了 WGC 自己的国别值

upsert 是「同键后写覆盖」⇒ 列表里**靠后的才生效**。原来手工补丁排在最后
⇒ 它盖掉了 WGC 的国别数据。实测 **UZB 2026 H1**：WGC Chart 9 = **41.4 吨**，
手工估读 = **4 吨**（差 10 倍）。

修法：写入顺序改为「**全球合计 → 手工补丁 → 国别明细**」⇒ WGC 有数时以 WGC 为准，
手工补丁只填空缺。**导入后核对**：UZB 2026Q1/Q2 = 6.7 / 34.7（来自 WGC H1），不再是 2 / 2。

#### 五、连带更正：宏观因子 `cb_gold`

该因子取 `summary.t12m_total` ⇒ 随本次修正从 **842.6 → 885.1**；
`STATIC_REF` 兜底常量也从重复计数的 **1019.0** 更正为 **885.1**
（该常量只在表读不到时才用，但它此前也在撒谎）。

#### 六、线上实测（`192.168.0.204:8888`，服务已用 systemd 重启到 V0.121.4）

```
GET /api/v1/central-bank/purchases
  summary.current_quarter       = 2026Q3
  summary.current_quarter_total = 321.2      ← 旧 336.7
  summary.t12m_total            = 885.1      ← 旧 842.6
  summary.t12m_window           = 2025Q4–2026Q3
  summary.country_count         = 24         ← 旧 25（含伪合计行）
  top_buyers[0]                 = POL 82.2   ← 合计行不在排名里
```

首页贵金属卡 3「央行购金变化」主值 = **+321.2**，副标题「数据截止 2026Q3 · 来源：世界黄金协会 GDT 全球合计」。

#### 七、门禁与单测（每条都反向验证过）

| 新增 | 断言的事 |
|---|---|
| `scripts/_verify_central_bank_aggregate.mjs`（**18 条**，新建） | KPI 当季 = 合计行；KPI T12M = 窗口内合计行之和；T12M 窗口内全表求和**确实**会虚高（重复计数的活现场）；合计行**不进** Top 排名 / 堆叠图；明细表里合计行仍可见且来源标记为「WGC 合计」 |
| `scripts/_verify_home_metals.mjs`（+6 条） | 首页卡主值 / 角标 / T12M / 国家数必须与 API 的**合计口径**一致 |
| `tests/test_services/test_central_bank.py`（+4 条） | 合计行不进 `t12m_total` / `current_quarter_total` / `country_count` / `top_buyers`；没有合计行时退回各国之和 |
| `tests/test_repositories/test_central_bank_data.py`（+13 条） | 报告版本顺序与回退；结构签名**拒绝**区域图；最新版优先 |

📉 **反向验证**（撤销修复 ⇒ 必须变红 ⇒ 恢复 ⇒ 变绿）：

| 撤销的修复 | 变红的断言 |
|---|---|
| `summary()` 改回全表求和 | `test_summary_prefers_aggregate_over_country_sum` |
| `t12m_total` 改回全表求和 | `test_t12m_total_prefers_aggregate` |
| `top_buyers` 不再跳过合计行 | `test_top_buyers_excludes_aggregate_row` |
| 国别图结构签名放宽 | `test_regional_chart_is_not_country_level` |
| 堆叠图不再剔除合计行 | `_verify_central_bank_aggregate.mjs` → 退出码 1 |
| 首页卡不再读 `WGC_AGGR` | `_verify_home_metals.mjs` → 退出码 1 |

⚠️ 后两条**必须重启服务**才测得到（浏览器门禁打的是**运行中的服务**，
静态文件是磁盘直出所以不用重启）—— 第一次做反向验证时因为没重启而「假绿」，
这本身又是一次「**门禁读到还没准备好的东西**」的复现。

#### 八、这一版的通用教训

> **两个口径不同的东西放进同一张表，就迟早会被加在一起。**
> 而它们加起来**看起来完全合理** —— 336.7 不比 288.9 离谱，842.6 不比 885.1 离谱。
> ⇒ 表结构上就要**让它们不可能被加在一起**（独立伪 ISO + 仓储层显式优先），
> 而不是靠「记得别相加」。

> **取错图不会报错，只会静默换口径。** 所以识别对象要靠**结构**（数据的形状），
> 不能靠**标题**（人写的、每季都改）。

> **数据缺一季 ≠ 可以编一季。** Q3 没有国别图，就让国别明细停在 H1，
> 并在 `source` 里写清覆盖到哪一季。

#### 推送状态（如实记录）

⚠ **本轮未推送 —— 被凭据挡住**（不是网络问题）。

| 项 | 值 |
|---|---|
| 本地 commit | `e431f80` = `HEAD` ✅ |
| 本地 tag | `v0.121.4`（annotated）→ `e431f80` ✅ |
| 远端 `refs/heads/main` | 仍是 `41df7c8` ⇒ **未推送** |
| 远端 tag 数 | **117**（本地 118） |

**三次实测都指向「权限」而非「网络」**：DNS 正常、`https://github.com` → 200、SSH 22/443 都通；
但 `git push` 403、REST 写接口 403。
⇒ gh keyring 里只有一枚 **fine-grained PAT**（`github_pat_` 前缀）⇒ **无写权限**。
⚠ `GET /repos/.../permissions` 报 `push: true` —— **这个字段是假的**，
no-op `PATCH /git/refs/heads/main` 直接 403 才暴露真相。
⇒ 只有 classic PAT（`ghp_` 前缀）能 push；本机已无 classic PAT 副本 ⇒ 需用户重新提供。

---

## 三、这一阶段的通用教训

三批合起来看，这条线反复撞上的是同一件事：

> **「看起来对」和「真的对」之间，隔着一条「谁在算」的链。**
> 而这条链上的每一环，都可能是一个**恒真的断言**、一个**恒真的兜底值**、
> 一个**从来没被执行过的分支**。

| 批次 | 表面症状 | 真正的原因 |
|---|---|---|
| V0.121.0 | 「门禁全绿」 | 门禁自己崩了 / 断言数为 0 |
| V0.121.1 | 「上涨天数恒为 0」 | 那一列**根本不是那个东西**（两套词表） |
| V0.121.1 | 「命中率能看」 | 命中本身有 26 个是**兜底值造出来的** |
| V0.121.2 | 「token 不显示」 | 客户端从不读 usage，而**上游也从来没报过** |
| V0.121.2 | 「滑块保存成功」 | 保存的是**另一套常量之外**的数 |
| V0.121.2 | 「价格日历在维护」 | 它只会被**补一次** |
| V0.121.3 | 「上涨天数修好了」 | 同一份 schema 抄了三份，**只改了第一份** |
| V0.121.4 | 「央行购金 321 吨」 | 那个数是**「合计 + 明细」**加出来的 |

⇒ 共同的解法也是同一个：**把断言打在「结果真的变了」上，而不是打在「函数被调用了」上**。
V0.121.0 让门禁**能判红**，V0.121.1 让判定**基于真实观测**，V0.121.2 让每一处修复
都有一条**端到端因果断言**（改了参数 ⇒ 结果变了；上游报了 ⇒ 页面显示；日历缺了 ⇒ 补上）。

⇒ 由此延伸出一条操作性纪律（本轮又验证了一次）：
**凡是要「统计/断言」某类东西，先证明「你统计到了东西」。**
本轮三次踩中同一个坑 —— V0.121.1 的 `r[-1]` 越界、
V0.121.2 的空数组恒真、`_verify_weights_group.mjs` 的空转断言。
**空转的断言比崩掉的断言更危险**，因为它比崩掉的更让人放心。

