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
| V0.121.1 | **可信度 P0** | `?days=` 修复（缓存 key 加维度）；`price_direction` 新列 + 迁移 `t2u3v4w5x6y`（上涨天数 0 → 11）；伪造消息面 50 分治源头 + 幂等回填（清 26 个伪造命中）；`/headlines` i18n key 字面量修好 |

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

## 三、这一阶段的通用教训

（批次 2 落地后补齐。）
