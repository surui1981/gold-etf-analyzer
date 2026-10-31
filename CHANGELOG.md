# Changelog

> 黄金 ETF 投资辅助 · 完整发版历史
>
> 详细 release notes 见 [docs/releases/](docs/releases/) 系列

## [V0.120.1] · 2026-10-31

`拆掉资金流观测网格测试的时间炸弹 —— 「今天」改为可注入，不再随系统时钟漂移` — bugfix · 详见 [v0.120.1.md](docs/releases/v0.120.1.md)

> 触发场景：本地同步到 V0.120.0 后跑全量回归，10-31（周六）当天出现 2 个失败，
> 而远程 CI 在 10-29 是绿的 —— **同一份代码、同一个测试，仅因时钟前进两天就从绿变红**。

- ⏰ **修 2 个已在今天变红、且会永久红的用例**（`test_money_flow_service.py`）
  - `test_黄金ETF_窗口末日锚在周末日而不是最新交易日` / `test_黄金ETF_周末日份额未发布时自动往前回退`
  - **根因**：用例把「今天是 2026-10-28」只写进注释，实际由
    `week_end_days(trading_days)` 内部 `date.today()` 自己取系统时钟 ⇒
    10-31（周六）起「本周（10-26~11-01）已过完」成立，锚点由 **10-23 跳到 10-30**
  - ⚠ 同源隐患：两条月频用例（融资余额 / 美元流动性）会在 **11-01 起**变红，本轮一并拆掉
- 🔧 **把「今天」做成可注入参数**（生产路径全部不传 ⇒ `None` → 系统日期，**行为与修复前逐字相同**）：
  - `_collect_etf(today=None)` → `week_end_days(trading_days, today=today)`
  - `_collect_us_liquidity(today=None)` → `fetch_us_net_liquidity_monthly(today=today)`
  - `_collect_cn_margin(today=None)` → `today = today or date.today()`
  - 对照：`money_flow_backfill.py:162` **早就**传了 `today=end`，只有实时采集路径漏透传
- 🧪 **测试加 `FIXED_TODAY = date(2026,10,28)`**，6 个依赖时钟的用例显式传参
  - **负向验证**（证明 `today` 真被使用而非碰巧绿）：同数据下
    `_collect_etf(today=X)` → `10-28⇒10-23` / `10-31⇒10-30` / `11-09⇒10-30` / `None⇒10-30`
- 📌 **教训（通用）**：凡用 `date.today()` 判「周期是否已过完」的逻辑，都要把 today 做成
  可注入参数 —— 否则 CI 绿只代表「CI 那一刻的时间巧合」，测试会随时间腐烂。

## [V0.120.0] · 2026-10-29

`新增第 4 个评分面「资金流面」—— 按资金流向各种市场判断（周 3 因子 / 月 3 因子）` — feature · 详见 [v0.120.0.md](docs/releases/v0.120.0.md)

> 用户：「制定计划，按照资金流动走向各种市场来判断，作为一个资金流面，什么建议」
> 追加：「我们关注的是近期的资金数据，进行周 和月的关键因子。」

- 💧 **新增第 4 个评分面「资金流面」**（权重 15%，权重页 / 趋势页 / 白银页 / 帮助页同步）
  - **只收流量/数量类读数，不收任何价格类读数** —— 不收 SHIBOR、不收汇率、不收利率
    （那些归宏观面，避免同一条逻辑计两遍，V0.119.0 政府债务组就是这个教训）
  - **6 个因子 = 周 3 + 月 3**（按用户要求分「周 / 月」两个节奏）：
    | 因子 | 权重 | 节奏 | 符号 | 口径 | 源 |
    |------|------|------|------|------|-----|
    | `gold_etf_flow` 黄金 ETF 4 周累计净申赎 | 22% | 周 | + | 亿元 | 上交所 518880 份额 |
    | `cot_gold_net` 黄金投机净多占 OI | 18% | 周 | + | % | CFTC 分类持仓 |
    | `cot_gold_flow` 黄金投机净多 4 周变化 | 14% | 周 | + | 张 | CFTC 分类持仓 |
    | `us_liq_net` 美元净流动性 4 周变化 | 14% | 月 | + | $M | FRED `WALCL`−`WTREGEN`−`RRPONTSYD` |
    | `cn_margin_flow` A 股融资余额月环比 | 16% | 月 | **−** | % | 沪深两市融资余额 |
    | `cn_money_gap` 中国 M1−M2 剪刀差 | 16% | 月 | **−** | 百分点 | 央行 M1/M2 |
  - **周 54% / 月 46%** —— 用户要「近期」⇒ 周频（更近、领先性更强）过半，月频（噪声低）作压舱石
  - ⚠️ **两个中国因子取「机会成本」负号口径**（用户拍板）：融资余额**上升** = 股市杠杆加码 =
    黄金承压 ⇒ 值越高越利空；M1−M2 剪刀差**走阔** = 钱淤积在定期存款 = 抗通胀需求上升
    ⇒ 同样是值越高越利空
  - ⚠️ **黄金 ETF 因子用 4 周累计净申赎**（用户拍板）：单周口径信噪比 ≈ 1
    （P10–P90 只有 ±2 亿元，而单日份额重建噪声已达 ±1.9 亿元）⇒ 4 周累计把噪声压到 ≈±0.95 亿
    （※ 拍板时依据的是「成交量÷换手率」重建口径；本轮实测改用上交所官方份额，
    噪声问题本身消失，但**口径仍按拍板保持 4 周累计**）

- ⚖️ **综合指数权重 30/40/30 → 25/35/25/15**
  - 相对次序保持 macro(35) > tech(25) = news(25) > flow(15)；
    新面**没有历史、无法回测** ⇒ 不给压过已有三维的权重
  - 🛡 **3 键 → 4 键的权重迁移守卫** `LEGACY_COMBINE_3_DEFAULTS`（tech .30 / macro .40 / news .30）：
    存量值**恰好等于**旧默认 ⇒ 直落新默认；否则按比例缩放 ⇒ 避免校验失败被静默重置
- 📐 **滚动分位窗口按「观测节奏」取**（周频 104 周 = 728 日 / 月频 60 月 = 1826 日），不是日频 252 日
  - 沿用 252 日窗口 ⇒ 周频只装得下 36 个观测、月频只有 8 个 ⇒ 样本不足 ⇒
    阈值永远退回硬编码（V0.119.0 记过的同一个坑）
  - `daily_money_flow_factors.snapshot_date` 存**因子自身的观测日**（CFTC 周二 / 月末 / FRED 周三），
    不是采集日 —— 按采集日逐日落表会把同一个周值重复 5 次 ⇒ P10 == P90 ⇒ 阈值退化
- ⚠️ **修一个真缺陷：3 个因子的观测节奏与声明的 cadence 不符**（本版自查发现）
  - `gold_etf_flow` 声明**周频**、`cn_margin_flow` / `us_liq_net` 声明**月频**，
    但观测日却跟着「最新数据」逐日推进 ⇒ 每日 07:00 调度会把**同一周 / 同一月**
    反复写进滚动分位窗口（同一个周值重复约 5 次、同一个月值重复约 21 次）⇒ 阈值被压平、样本数虚高
  - 且「**月内至今**」与历史行的「**月末 vs 月末**」根本不是同一个量 ⇒
    实时读数与回填历史**口径不一致**，两套数混进同一个分位窗口
  - ⚠️ `us_liq_net` 还有**更隐蔽的一层**：源是周更，但因子值本身是「**4 周变化**」
    ⇒ 按周采样时相邻两次观测**重叠 3/4**，名义 60 个月的位置里塞了 260 行高度重叠的样本
    ⇒ 有效样本只剩 1/4，`min_samples` 达标是**假象**（样本数骗了自己）
  - 修法：**按观测节奏锚定采样网格** —— 周频锚 **ISO 周的最后一个交易日**（周末日），
    月频只取**已过完**的月（锚点 = 日历月末，观测值按 as-of 取）；
    实时采集 / 历史回填 / 静态标定**三处共用同一个锚点函数**
    （`week_end_days()` / `month_end_days()`，见 `repositories/money_flow_sources.py`）
  - 换网格时旧行**不会被新网格的 upsert 覆盖**（`snapshot_date` 不同 ⇒ 两张网格并存）
    ⇒ 新增 `delete_factor()` + `--reset` 开关，让重建可复现
  - 实测影响：`gold_etf_flow` 65 → **103** 行 / `cn_margin_flow` 54 → **53** 行 /
    `us_liq_net` 260 → **60** 行（总表 482 行）；
    四项分值随口径修正（ETF 因子 38.1 → **37.3** / 融资余额 100.0 → **94.4** /
    美元流动性 71.1 → **69.6** / 资金流面 43.2 → **41.9**）
- 📥 **历史回填 482 行**（6 个因子全部走滚动分位，不靠静态阈带）
  - CFTC 年度包 206 行（2 个因子共用一次下载）/ FRED 美元净流动性 60 行（月末锚点）/
    上交所按日采样 103 行 / 融资余额 53 行 / 央行 M1-M2 60 行
  - `scripts/backfill_money_flow_factors.py` 幂等（按 `(target, snapshot_date, factor_key)` 覆盖写），
    **已挂进每日 07:00 BJT 调度**（与宏观面同款：样本充足即空转）
  - ⚠️ 回填门槛取规则表的 `min_samples`（36~60）而非拍脑袋的常数 ——
    用 30 会出现「回填跑完了、滚动分位仍不激活」的夹层
- 🛡 **「一个因子都没取到读数」⇒ 整面 `score = None`，从综合指数剔除**（不是记 0 分）
  - 0 分会被综合指数当成「资金正在撤离黄金」，而真相是「没数」
  - 判定口径是「**本轮有没有真实观测**（tier = live / lkg）」而不是「有没有值」——
    `STATIC_REF` 恒有值，「有没有值」永远为真 ⇒ 6 个因子**全部只剩静态兜底**
    （外网全挂 **且** 历史表也读不到）时整面一样剔除（降级值能救单个因子，救不了整面）
  - 与消息面的 pending 语义**分开表述**：消息面是「还没打分、待定」，资金流面是「数据源挂了」
- 📡 **实测改掉设计：黄金 ETF 份额改用上交所官方口径**
  - 计划初稿打算用「成交量 ÷ 换手率」**重建**份额，并据此判定周度信噪比 ≈ 1、不可用；
    实测发现上交所有官方每日份额接口（`TOT_VOL`）⇒ **重建口径整条废弃**
    （没有 ±0.2% 量化误差，也不必剔除未收盘 bar —— 份额是结算后的存量）
  - 「单周信噪比 ≈ 1 不可用」那个结论建立在**错的源**上 ⇒ 「先实测再定口径」直接改掉设计
- 🔧 **修 `is_dynamic_active` 的误判**（本版顺带修的既有缺陷）
  - 旧判据是「阈值 ≠ hardcode」⇒ **滚动分位算出的 best/worst 可能与静态带逐位相同**
    （静态带就是拿同一段历史标定的）⇒ 该因子被误报成「还在用静态阈值」
  - 实测 `cn_money_gap`：滚动 P10/P90 = −11.2 / −3.1，与静态带一模一样 ⇒ 旧判据下
    badge 说 5/6、`flow_dynamic=False`，真相是 6/6 都在滚动分位上
  - 修法：计算器**显式记录**本轮真正走了滚动分位的因子集合（`rolling_keys`），
    判定不再靠「值是否恰好相等」反推 —— 宏观面同一处判据一并修正
- 🔧 **修 `trend.py` 丢弃分支丢文案**：消息面与资金流面**同时**不可用时，
  原本只说「消息面未打分」，把消息面的 pending 语义吞掉了 ⇒ 拆成两句分别表述
- 🚫 **回测网格不动**：新面今天没有任何历史快照，加进 `MACRO_DIM_FIELDS` 会让
  `_aggregate_from_detail` 全部返回 `None` ⇒ 回测出 0 行（V0.118.0 刚修过的同一个 bug）
  —— ⚠️ 但**「不动网格」≠「不攒历史」**：约 1 年后本面才有资格进网格，
  届时若快照里没有 per-factor 明细，这 1 年就白等了 ⇒ 本版把
  `daily_snapshots.flow_index`（Float，可空）+ `flow_detail`（Text，可空）两列铺好
  （迁移 `r2s3t4u5v6w`），历史**从今天开始攒**。
  两处易错点已处理并有测试兜底：① 面分**可空** —— 整面不可用时存 NULL 而不是 0 分
  （不学 `news_index` 的 50.0 兜底：消息面是「没打分」，资金流面是「数据源挂了」）；
  ② 仓储 upsert 的 update 分支有**硬编码白名单**（V0.79.0 `tech_detail` 踩过）
  ⇒ 新列漏加则当日第二次捕获不更新
- 🖥️ **前端口径收口（改 3 面 ⇒ 4 面后，前端多处仍在说旧话）**
  - 后端从 V0.100 起就把「消息面未打分」处理成**剔除该面 + 其余面按有效面归一化**
    （`score=None`），而前端文案写的是「按**中性 50** 参与评估（占 30% 权重）」——
    **文案与算法相反**：用户以为消息面还有一张票，实际它根本没进综合指数。
    现改为「消息面**不参与**综合指数（配置权重 X% 已剔除，其余面按有效面归一化）」，
    权重取自后端（`/api/v1/settings/weights`），未打分时分值显示「—」而不是 50.0。
  | 位置 | 原状 | 现状 |
  |---|---|---|
  | `static/synthesis-card.js` 结论卡 | 硬编码 3 面 30/40/30 | 4 面；权重取 `index.face_weights`（生效）/ `face_weights_nominal`（被剔除面的**配置**权重） |
  | `static/decision-explainer.js` 决策拆解 | 同上；且**各面贡献相加 ≠ 综合指数**（27.1 vs 27.2） | 同上；贡献之和 = 卡片上显示的综合指数 |
  | `static/portfolio.html` 指数构成 | 硬编码 3 面；缺失面用 `sc \|\| 0` 渲染成「**0 分**」（看着像看空） | 4 面；被剔除的面标「**未计入**」+ 显示其配置权重 |
  | `static/news.html` + `news-score-widget.js` | 「尚未打分，按中性 50 参与评估（占 30% 权重）」 | 「消息面不参与综合指数（配置权重 X% 已剔除…）」；intro / 页脚的 4 面权重取后端 |
  | `static/silver.js` | `I18n.t(key, "中文兜底")` —— **第 2 参是 `params` 不是兜底** ⇒ 字典里的 `{n}` 原样显示 | 改为 `I18n.t(key, { n: ... })`（全站扫描已归零） |
  | `static/help.js` / `static/trend.html` | 「技术面 30% + 宏观 40% + 消息面 30%」 | 4 面；「运算方法」公式取后端 `face_weights` |
- 🔧 **i18n 门禁有个盲区（本日发现并修）**：门禁只扫 `I18n.t('key')` 与 `tr('key')`
  两种写法，而 `synthesis-card.js` / `news-score-widget.js` / `scoring.js` 各自定义了
  **本地包装器 `T(key, fallback)`** ⇒ `syn.*` / `nsw.*` / `scoring.*` 三个命名空间
  **完全不在门禁视野内**（漏一语不会报错，只会悄悄显示简体）。
  现补 `T('key')` 扫描 + 三个 namespace 进严格清单 ⇒ 严格覆盖 **309 → 492 键**
- 🐛 **修一个真缺陷：非默认语言下结论卡**锁死在简体**（浏览器门禁本日抓出）**
  - 现象：语言设为繁体 / 英文后**首次打开**趋势页，结论卡标题是简体
    （「分面构成」而不是「分面構成」）—— 字典文件里繁体串是齐的，不是漏引字典
  - 根因三处叠加：① 结论卡是 `innerHTML` 拼的，**没有 `data-i18n` 标记**
    ⇒ `i18n.js` 的 `apply()` 扫不到它；② 非默认语言的字典是**动态 `<script>` 异步加载**，
    组件完全可能抢在字典之前渲染完；③ `init()` 解析完语言后**从不广播 `i18n:change`**
    （只有手动切语言才广播）⇒ 字典到了也没人叫它重渲染 ⇒ **永久停在默认语言**
  - 实测复现：把 `/static/i18n/zh-TW.js` 响应延迟 4s ⇒ 卡片标题永远是简体
  - 修法三处：`i18n.js` 的 `init()` 在**非默认语言**时广播 `i18n:change`
    （默认语言字典同步注入，不存在竞态，广播只会让报告页多发一轮请求）、
    暴露 `window.I18n.ready` 且 `loadLang()` 并发去重、字典全局名大小写两种都认
    （`zh-CN.js` 是 `PM_I18N_ZH_CN` 而 `zh-TW.js` 是 `PM_I18N_zh_TW` —— 只认一种就是
    「字典加载成功但读不到」）；`synthesis-card.js` / `news-score-widget.js`
    **渲染前** `await I18n.ready`
  - 顺带修掉一个崩溃：`weights.html` 的 `update()` 在滑块行还没画出来时被调用
    ⇒ `getElementById` 返回 `null` ⇒ `.value` 抛 `Cannot read properties of null`
    ⇒ **整页脚本中断**；改为行还没画时直接返回（既不崩，也不写假的「合计 0%」）
  - 门禁同步加固：G 段的等待条件从「标题非空」改成「标题非空 **且** `data-lang`
    已解析到目标语言」（标题非空只证明渲染过、证明不了渲染成了哪种语言），
    并新增 **G2 段**（字典延迟 3s ⇒ 卡片最终仍须是该语言）做阳性对照
- 🐛 **修第二个真缺陷：回测的「价格日历回填」白等 8 秒外网**（全量 pytest 抓出）
  - 症状：`tests/test_api/test_async_backtest.py::test_run_async_does_not_block_response`
    超时失败（单跑该文件同样失败 ⇒ 不是负载抖动）
  - 根因：回填只需要**收盘价 + 来源标记**，却走 `TrendService.analyze()`
    ⇒ 顺带把宏观面 / 消息面 / **资金流面各拉一遍外网**
    （实测 `MoneyFlowService.evaluate()` 单次 **8.25s**：CFTC 年文件 zip + FRED CSV +
    沪深融资余额 + PBoC M1/M2 + 上交所份额），算出的指数**被整段丢掉**
  - 后果不是「慢一点」而是**功能坏掉**：异步回测用例只有 15s 预算 ⇒ 超时失败
  - 修法：新增轻路径 `TrendService.fetch_price_bars()`（只取价格 + 来源标记，
    **一个评分面都不算**），回填改走它 ⇒ 实测 1.90s / 90 根 bar，整文件 11 passed（7.8s）
  - 回归护栏：`test_backfill_does_not_evaluate_any_scoring_face`
    （断言回填**不调用** `analyze()`）
  - ⚠️ 教训：这条**只有全量回归才暴露** —— 单跑 `test_price_calendar_backfill.py` 全绿，
    因为桩自己实现了 `analyze()`，走的是**假**路径，测不到真实耗时
    ⇒ **被替换掉的调用方不是契约**，替身不跟着改，门禁就永远绿
- 🧪 新增门禁 `scripts/_verify_money_flow.mjs`（11 段：线上 API / 综合指数 4 面 / 权重页 /
  趋势页 + 结论卡 + **反向验证**：mock 掉 `flow` 段后页面**不得**出现资金流面区块、
  公式**不得**出现「资金流面」；mock 成旧 3 面权重后标题**必须**照着画 ——
  证明断言不是空断言；+ i18n 三语实跑 + **G2 竞态回归**（字典延迟 3s ⇒ 卡片仍须是该语言）
  + 消息面「被剔除」口径 2 处 UI + 持仓页指数构成对账）
- 🔧 **修门禁的时序竞态（本日发现）**：D2 段（结论卡 + 决策拆解）在**服务器刚重启、
  `served_cache` 冷**时**假红**（首跑 174 passed / 12 failed，12 条全是「渲染 0 个面」）。
  根因不是产品 bug，是门禁**等错了东西**：`synthesis-card.js` / `decision-explainer.js`
  各自**另外发一个 fetch**（`trend?target=etf` 与 `/api/v1/decision/etf`），
  渲染晚于趋势页主体，而门禁只等到 `#flowFactors` 的 6 行就断言 ⇒ 冷缓存时读到空卡片。
  修法：① 显式等「结论卡 4 行 **且** 决策拆解 4 行」；② 判据换成**页面自己那份 payload**
  （拦截响应体，按 `interval=D` / `target=etf` / `decision/etf` 三处分别取 ——
  此前拿的是门禁顶层提前 fetch 的那份，既不同 `served_cache` key 又隔了几十秒）；
  ③ 反向验证：临时从 `synthesis-card.js` 的 `FACES` 删掉 `flow` 面 ⇒ 9 条断言转红，
  恢复后回到全绿（当时 192/0；本版随后新增 G2 段，现为 **194/0**）
- 📚 新增 65 个资金流测试（服务 28 / 阈值 13 / 源 24）+ 2 条「滚动带 == 静态带」回归测试；
  术语表新增「资金流因子类」7 条 + 「综合指数口径与后端默认权重一致」断言
- ✅ **全量验证**：`pytest tests/` **2007 passed / 0 failed**（基线 1921 @V0.119.0，**+86**，37m37s）；
  浏览器门禁 **194 passed / 0 failed**（冷缓存实跑）；`check_cluster_render.mjs` **461 passed / 0 failed**；
  `check_routes` 20 条路由全对；`ruff check` + `ruff format --check` 干净；
  静态门禁 7 个全绿（i18n 严格覆盖 492 键 / 0 missing）⇒ 见 [v0.120.0.md](docs/releases/v0.120.0.md) §验证
  > ⚠️ 该全量跑之后只追加了「复盘页价格回填」同一处修法（`review.py`）+ 1 条护栏用例，
  > 以**文件级**复跑验证（46 + 17 passed），**未再跑全量**（用户要求减少不必要的测试）

## [V0.119.0] · 2026-10-27

`宏观面 8 → 11 因子（+美国/中国/欧洲 政府债务/GDP）+ 低频因子 cadence/max_lag_days` — feature · 详见 [v0.119.0.md](docs/releases/v0.119.0.md)

> 用户：「我们需要再宏观因子添加 美国 欧洲 和中国政府这些经济体的政府债务，添加到宏观因子，先制定计划，我们分析它的权重。」

- 🏛 **宏观面新增 3 个政府债务因子**（权重页 / 趋势页 / 白银页 / 帮助页同步）
  - 新增 `us_gov_debt`（5%，FRED `GFDEGDQ188S` 季度）/ `cn_gov_debt`（4%，FRED `GGGDTACNA188N` 年度）
    / `eu_gov_debt`（3%，Eurostat `GOV_10Q_GGDEBT` 季度，`EU27_2020` 口径）
  - 实测读数：美 **122.59**（2026Q1）/ 中 **88.33**（2024）/ 欧 **82.9**（2026Q2）
  - ⚠️ **符号取「债务↑ = 利多黄金」（debasement 口径）**：反向通道（债务↑→实际利率↑→金价跌）
    已由 `real10y`（18%）承担，再加一遍是重复计权
  - ⚠️ **新组共 12%，旧 8 个按 ×0.88 等比缩放**（相对比例完全不动）：
    dxy 15→13 / us2y 6→5 / us10y 8→7 / us30y 6→5 / curve 10→9 / real10y 20→18 /
    vix 10→9 / cb_gold 25→22
  - ⚠️ **诚实的保留意见**：这一组是**近乎恒定的偏多偏移**，不是择时信号 ——
    它的价值是分散化 + 一个慢锚。2026-10-26 实测：宏观面 **33.6 → 38.9（+5.3 分）**，
    方向仍是 BEARISH。⚠️ **断点不是常数**：其余 7 个日频因子走滚动分位，分值会漂移，
    当日读数下的断点在组权重 ≈25.6%
  - **2026-10-27 生产实例复测**：绝对分随日频因子漂移（38.9 → **38.1**），但债务组的
    净抬升仍是 **+5.47 分**（32.65 → 38.1）⇒ 抬升来自因子本身，不是某一天的读数巧合；
    断点当天在 ≈27.1%。8888 重启到 `0.119.0` 后 `/api/v1/settings/weights` 返回
    **11 个** macro key（存量 8 键默认被 `LEGACY_MACRO_8_DEFAULTS` 守卫直落新默认），
    `/trend` 的 11 个因子**全部 `tier=live`**
- ⏱ **低频因子的滞后口径**（本版新机制，否则告警**永久亮红灯**）
  - 因子规则新增 `cadence`（daily/quarterly/annual）+ `max_lag_days`（日频 4 / 季度 300 /
    年度 **1100**），经 `MacroFactorOut` 透出；前端对非日频因子改挂**中性「季度/年度」chip**，
    滞后红灯只在超过 `max_lag_days`（= 源真的断了）时才亮
  - ⚠️ **年度阈值 550 → 1100 天**：FRED 的 IMF WEO 年度序列最新观测是 2024-12-31
    （664 天前，年度序列本身落后日历 1~2 年）⇒ 550 天会让中国那一行**永远亮红灯**
    —— 常亮的告警等于没有告警
  - ⚠️ **低频 `data_date` 必须归一到期末日期**：FRED 季度用季初（`2026-01-01`）、
    Eurostat 用 `"2026-Q2"` 标签（`Date.parse` 得 `NaN`）⇒ 统一转成
    `2026-03-31` / `2026-06-30` / `2024-12-31`
- 🔁 **后端自己声明「哪些因子可滚动」**（`MacroIndexOut.rolling_factors`）
  - 原先前端两处硬编码 `f.key !== "cb_gold"` —— 再加 3 个 skip 因子必然腐化；
    现在由后端给出清单，前端只读长度（「7 个可滚动因子」角标）
  - 3 个低频因子与 `cb_gold` 一起进 `SKIP_ROLLING_FACTORS`：日频落表会把同一个季度值
    重复几十次 ⇒ P10 == P90 ⇒ 阈值退化
- 🛡 **8 键 → 11 键的权重迁移守卫**
  - 新增 `LEGACY_MACRO_8_DEFAULTS`（V0.118 的 8 键默认）⇒ 存量 8 键**默认**配置直落新默认，
    存量 8 键**自定义**按 ×0.88 缩放保留用户意图（5 键同口径：默认直落 / 自定义 ×0.56）
- 🚫 **回测网格不动**：新因子没有历史快照，加进 `MACRO_DIM_FIELDS` 会让
  `_aggregate_from_detail` 全部返回 `None` ⇒ 回测出 0 行（V0.118.0 刚修的 bug）
- 🧪 新增门禁 `scripts/_verify_macro_debt.mjs`（5 段：线上 API / 权重页 / 趋势页 +
  **2 处反向验证**——删掉 mock 的 `max_lag_days` 后同一行**必须**亮滞后红灯；
  把 mock 的 `rolling_factors` 砍到 3 个后角标**必须**显示「3 个可滚动因子」，
  两处都证明断言不是空断言）
- 🔁 门禁自身的读数断言从**子串匹配**改成**数值比较 + 0.01 容差**
  （`exp.value` 填 live 源原始读数 `122.59387 / 88.327 / 82.9`）——
  原来写的是内置兜底值 `88.33`：上游源挂着时（`tier=static`）绿，
  **源一恢复**（`tier=live`，渲染成 `88.327`）反而红 ⇒ 门禁「只能绿一次」
- 📚 新增 11 个数据源测试 + 12 个因子/迁移测试；i18n 3 语新增 2 个 cadence chip key
- ✅ **全量验证**：`pytest` **1921 passed / 0 failed**（基线 1898，+23）；`ruff` 0 error；
  7 个文档/脚本门禁全绿；`check_routes` 20 条路由；浏览器门禁 **52 + 68 + 15** 全绿
  （其中 `_verify_macro_debt.mjs` 直接打**生产实例** 8888）

## [V0.118.1] · 2026-10-26

`宏观因子「末次落库」兜底层 + 手动校准页降级可见` — bugfix · 详见 [v0.118.1.md](docs/releases/v0.118.1.md)

> 用户：「宏观因子手动校准的数值没有跟踪关键参数更新来更新，修复这个 BUG」

- 🛟 **宏观因子新增「末次落库」兜底层**（源挂时不再退回 2026-08-28 的内置常量）
  - 新优先级链：手动覆盖 > 自动源 > **末次落库的真实读数** > 内置常量
  - 「末次落库」= `daily_macro_factors` 里每个因子最近一条落库记录
    （新增 `MacroFactorHistoryRepository.get_latest_per_factor()`）
  - 实测：上游全挂时 `dxy` 从常量 **96.5（2026-08-28）** 变成 **101.81（2026-10-23）** ——
    差 5.3 个点，落在 best/worst 区间内，足以改变因子评分进而改变综合指数
  - ⚠️ **降级必须可辨认**：`MacroFactorOut` 新增 `tier` 字段（`live`/`lkg`/`static`），
    降级值 source 带 `末次落库·` 前缀；前端**不靠匹配中文前缀**判断
  - ⚠️ **降级值不再落表**：旧读数写进今天的 `snapshot_date` 等于谎报观测时间，
    会把 V0.79.0 的滚动分位窗口压平（与静态值不落表同一条理由）
- 📉 **权重页「当前生效」列不再骗人**
  - 滞后 chip 原先**只对手动值生效** ⇒ 自动源退回 59 天前的常量时页面上零提示；
    现在所有源都提示（自动源 > 4 日、手动值 > 1 日）
  - 新增降级 chip：`tier=lkg` →「降级·末次读数」/ `tier=static` →「内置常量」
- 🧾 **综合卡「数据质量」提示补上 `lkg` 档**
  - 原判据只认 `source.indexOf('静态参考值')` ⇒ 新增的「末次落库」降级对它**完全隐形**
  - 改用 `tier` 字段判降级；新增 `syn.q_macro_lkg` key × 3 语
  - 新增门禁 `scripts/_verify_synthesis_quality.mjs`（mock 造两档降级；已反向验证会变红）
- 🐛 **顺带修掉一个线上真 bug**：`/ask` 的 `get_market_overview` 工具**每次调用都失败**
  - `main.py` 构造 `TrendService(repo, macro)` 时第 2 位误传 `MarketDataRepository`
    ⇒ `analyze()` 里 `await self._macro.evaluate()` 抛 `AttributeError`，
    被 tool 层兜住 ⇒ 页面表现为「工具没给出数据」，**无告警无 500**
  - `/api/v1/ai/health` 显示 5 个工具已启用 ⇒ 线上活跃路径
- 🧪 新增 13 个测试（仓储 5 + 服务 8）；i18n 3 语各 +2 个 `mo_tier_*` +1 个 `syn.q_macro_lkg`（`mo_*` 33 个 / `syn.*` 49 个）

## [V0.118.0] · 2026-10-25

`宏观面 5 因子 → 8 因子（+2Y / +10Y-2Y 利差 / +10Y 实际利率）+ dxy/vix 接实时源 + 滚动分位回填` — feature · 详见 [v0.118.0.md](docs/releases/v0.118.0.md)

> 用户：「宏观面的选定参数需要进行调整，添加 2Y 的美国国债收益率，再考虑添加一下其他的决定因子或者调整」

- 🌐 **宏观面 5 → 8 因子**（权重页 / 趋势页 / 白银页 / 回测页同步）
  - 新增 `us2y`（6%，H.15）/ `curve_10y2y`（10%，派生 10Y−2Y）/ `real10y`（20%，FRED `DFII10`）
  - 存量 5 因子权重重排：`dxy` 25→15 / `us10y` 20→8 / `us30y` 15→6 / `vix` 15→10 / `cb_gold` 25→25
    （新增：`us2y` 6 / `curve_10y2y` 10 / `real10y` 20）
  - ⚠️ `curve_10y2y` 符号约定是本组**最弱的一档**（倒挂 = 衰退定价 = 利多黄金），
    权重刻意压到 10%；2024-25「牛陡」的反例主因是实际利率下行，已由 `real10y` 单独承担
- 💵 **dxy / vix 从静态常量接实时源**（同尺度是硬约束）
  - `dxy` → Yahoo `DX-Y.NYB`（实测 101.75）；`vix` → FRED `VIXCLS`（实测 19.03）
  - ⚠️ **不换 FRED `DTWEXBGS`**（≈121，与 DXY 不同尺度）—— 换了会让存量手动校准值与
    硬编码 best/worst 同时失效
- 📈 **回填历史，让 V0.79.0 的滚动 90/10 分位真正生效**（此前 18 天样本 < 60 门槛 ⇒ 机制一直是死代码）
  - 新增 `src/app/services/macro_backfill.py` + `scripts/backfill_macro_factors.py`
  - H.15 CSV 实测全量 **12417 行**；FRED `DFII10` / `VIXCLS`、Yahoo `DX-Y.NYB` 各自多年历史
  - **静态回退值不落表**（`is_persistable_source`）—— 一次上游故障就能污染 252 日窗口，
    让动态阈值**比硬编码更差**
  - `is_dynamic_active` 口径收紧：硬编码 `>= 4` 改成「7 个可滚动因子**全部**动态」
    （照抄 `>= 4` 会把语义从「全动态」松成「过半即算」）
- 🐛 **滚动分位的方向整个反了**（V0.79.0 起休眠，回填让机制真正生效时必现）
  - `MacroThresholdCalculator` 此前对**所有**因子一律 `best = P90`，
    而 8 个因子里有 **6 个是负相关**（美元 / 三档美债 / 实际利率 / 10Y-2Y 利差，
    占宏观权重 65%）⇒ 美元指数创 8 个月新高会被判成「最利多黄金」给 100 分
  - 实测：修复前宏观指数 71.2（bullish）→ 修复后 **39.7（bearish）**
  - 修法：按每个因子的 `positive` 标志取分位方向（负相关取 `best = P10`）
  - 回归锁：`tests/test_services/test_macro_thresholds.py::TestRollingSignConvention` 3 个用例
- 🐛 **权重页显示「合计 101%」，用户连保存都做不了**
  - 存量权重迁移后是 `0.128` / `0.096` 这类小数，而滑块是**整数百分比**，
    逐个 `Math.round` 后合计 101% ⇒ 页面标红 + 后端 `_sum_to_one` 拒收
  - 修法：`toIntPercents()` 用**最大余额法**归一化（先取整、再按小数部分补齐），
    对任意 API 返回值都成立
- 🐛 **回测「启用宏观内部权重」永远跑出 0 行**（V0.118.0 之前就存在的缺陷）
  - `MACRO_DIM_FIELDS` 写的是 5 个**中文维度名**，而快照 `macro_detail` 的键一直是**因子 key**
    ⇒ `_aggregate_from_detail` 找不到任一维度即返回 `None` ⇒ 快照被整根跳过
  - 修法：改用因子 key；前端 `backtest.html` 宏观网格同步改用 `data-key="dxy"`
  - ⚠️ 仍是 5 个不是 8 个 —— 新增 3 因子从 V0.118.0 起才落快照，历史快照里没有
- 🔐 **三源三套 User-Agent 规则**（实测，各测 2 次稳定）
  - FRED **不发 UA**（发 Mozilla 会被 WAF **挂起** → 读超时而非 403，极易误判成网络抖动）
  - Yahoo / H.15 **必须发 `Mozilla/5.0`**（不发直接 403）
- 🔁 **存量 5 键权重配置无损迁移**（`MacroWeightConfig._migrate_missing_factors`）
  - 新增因子的默认份额从旧因子里按比例扣除，保留用户对各因子的相对偏好
  - ⚠️ 不做迁移 → 合计变 1.36 → `_sum_to_one` 抛错 → 兜底路径**静默把用户自定义权重重置为默认**
  - **两个分支**：存量值恰好等于旧默认（= 用户从没自定义过）→ **直接落到新默认**；
    是真实自定义值 → 按比例缩放。只做缩放的话「没动过权重」的用户会拿到
    `dxy 16% / us10y 12.8% / cb_gold 16%` 这组谁都没设计过的权重
- 🧪 新增 `tests/test_services/test_macro_backfill.py`（9）+ `tests/test_repositories/test_macro_sources.py`（13）
  - 含 H.15 UA 回归锁（本轮实测踩到：回填静默为空，日志两行都是 INFO，「回填完成」照打）
- 🐛 **单测会真的联网**：调度器 step 3 调回填 ⇒ 测试跑一次往测试库灌几百行真实历史
  ⇒ 加 autouse 打桩 fixture
- 🔧 **顺带修掉四道坏门禁**（本来在骗人）
  - `scripts/_verify_macro_override.mjs`：谓词里引用 Node 侧常量 `EXPECTED_ROWS`
    ⇒ 页面里 `ReferenceError` ⇒ **puppeteer 吞掉异常只报超时**（看着像「功能没生效」）；
    `page.evaluate` 里引用 `KEYS` / `nullOverrides()` 是同一个坑 ⇒ 一并改成传参
  - `scripts/check_cluster_render.mjs`：A7 断言查的是 `trend.html` **注释里**的字面量
    ⇒ 假绿；`silver.html` 那边是真红 ⇒ 改成查代码里才有的标记，并做了反向验证
  - **Service Worker 会让 puppeteer 的请求拦截静默失效**：`static/sw.js` 有
    `skipWaiting()` + `clients.claim()` ⇒ 第 1 次导航后就接管页面，而 **SW 自己的 `fetch()`
    不经过页面级拦截** ⇒ 第 2 次导航的 mock 完全不生效（门禁拿真实数据当 mock 结果）
    ⇒ 所有用 `setRequestInterception` 的门禁加 `page.setBypassServiceWorker(true)`（改了 4 个脚本）
    - `setCacheEnabled(false)` **修不了这个**（已实测）；`performance` 里 `transferSize=0` 是 SW 服务的标志
  - `scripts/_verify_category_filter.mjs` **启动即崩**：`TypeError: Illegal invocation` ——
    `HTMLInputElement.prototype` 永远有 `value` 描述符，`A.prototype || B.prototype` 的兜底
    永远走不到 ⇒ 用 input 的 setter 写 `<select>` ⇒ V0.105.0 改 select 之后就一直崩，
    门禁压根跑不到任何断言

## [V0.116.4] · 2026-10-25

`命令面板「输入决策」落到趋势追踪 —— 场景落地页被第一个子页顶掉了` — 详见 [v0.116.4.md](docs/releases/v0.116.4.md)

> 起因：用户反馈「点击决策的时候看到的页面是趋势追踪」。
> 但**顶栏、首页场景卡、手机抽屉三处「决策」一直都指向 `/scoring`（打分汇总）**，
> 全站 60+ 个「决策」链接实测**没有一个**指向 trend ——
> 唯一的例外是**命令面板**：输入「决策」回车 → 趋势追踪。

### Fixed

- 🐛 **命令面板输入场景名，落到的是该场景的第一个子页而不是落地页**（`static/command-palette.js`）
  - 实测：面板输入「决策」列出 5 条，第 1 条 = 「📈 趋势追踪 /static/trend.html」**且默认选中** ⇒ 回车落到趋势页
  - 根因：面板清单从 `topnav.js` 的 `SCENES` 惰性派生，组内先铺子页；
    而「决策」场景的 `path`（`/scoring`）恰好等于**第 2 个**子页（打分汇总）的 path
    ⇒ 被去重逻辑吃掉 ⇒ 落地页留在第 2 位、第 1 位变成趋势追踪
  - 而面板的过滤是 `label + hint + section` 匹配，组内 4 条**全都命中「决策」**（section 就是场景名）
    ⇒ 第一条命中 = 趋势追踪
  - 修法：场景落地页**提到组首** ⇒ 「输入场景名 → 回车」与「点顶栏 / 首页场景卡 / 手机抽屉」落点一致

### 门禁加固

- 🔧 **新增一条通用断言：8 个场景逐个查「输入场景名 → 第一条命中的 href」必须等于该场景落地页**
  （`_verify_cmd_palette.mjs`）—— 写成循环而不是给「决策」单写一条，
  新增场景时自动受约束
  - ⚠ 检索词用**面板里实际渲染出来的组名**而不是 `SCENES[i].fb`：
    AI 场景 `fb = "AI 智能分析"` 而 zh-CN 的 `nav.ask = "智能分析"`
    ⇒ 用 `fb` 检索一条都匹配不到，断言会以「null」假红
  - 反向验证：回退「落地页提组首」⇒ **38 passed, 1 failed**（只有「决策」那条红）

- 🐛 **新建 `scripts/_verify_scoring_robust.mjs`（8 条断言）**：命中分析 Tab 的异常路径
  - 顺带修掉一处真 bug：`scoring.js` 的 `renderHitStats` 守卫写的是 `data.sample_size === 0`，
    而 `fetchJson` 的错误兜底返回通用空壳 `{rows,buckets,tags}`（**没有** sample_size/by_direction）
    ⇒ `undefined !== 0` 守卫失效 ⇒ `undefined is not iterable`
    ⇒ 整个 Tab 崩掉、描述行还漏 `sample=undefined` 字面量
  - 修法与同文件其它 renderer 一致：`!data.sample_size || !Array.isArray(data.by_direction)`
  - 反向验证：回退守卫 ⇒ **6 passed, 2 failed**；恢复 ⇒ **8 passed, 0 failed**

- 🔧 **两道浏览器门禁不再把「服务端 429 限流」误判成「页面 JS 错误」**
  （`_verify_cmd_palette.mjs` / `_verify_mobile.mjs`）
  - 现象：连续跑几次门禁就 flap（同一份代码，39/0 与 38/1 交替）——
    服务端有 600 req/min per IP 限流，浏览器把被拒的请求记成 console error
  - 修法：窄口径豁免（只匹配 `HTTP 429: Too Many Requests`）+ **显式打印条数与原因**，
    限流真被关掉时这行豁免自然失效

### 验证

- `_verify_cmd_palette.mjs` **39 passed, 0 failed**（回退实现 38/1）
- `_verify_scoring_robust.mjs` **8 passed, 0 failed**（回退实现 6/2）
- `_verify_mobile.mjs` **35 passed, 0 failed**
- 新增 3 个诊断脚本留证：`_diag_decision_nav.mjs`（17 页 × 60+ 个「决策」链接落点普查）/
  `_diag_palette_decision.mjs`（面板输入「决策」的条目与回车落点）/
  `_verify_scoring_robust.mjs`（门禁）

### 范围检查

- 顶栏 / 首页场景卡 / 手机抽屉三处「决策」**实测一直是对的**（都指向 `/scoring`），
  手机抽屉是直接拷贝顶栏 `.links` 的锚点 ⇒ 与顶栏同源，不会漂移
- 唯一漂移发生在**面板的派生层**（另有一套排序规则）

### 已知问题（本轮**未**修）

- 承 V0.116.2 §5：生产 `users` 表缺 `role` 列（admin 2 端点 500）、
  `GET /api/v1/auth/me` 500、单用户模式 `require_owner` 认证边界错
  —— 都要动生产数据库
- **待观察**：`scoring.js` 的 `fetchJson` 错误兜底返回的是**通用空壳**，
  对 hit-stats 端点是错的形状。本轮在渲染层加守卫（最小改动），
  但「每个端点各自的空形状」这件事本身还没收口

## [V0.116.3] · 2026-10-25

`命令面板自动聚焦被 V0.113.0 的无障碍修复顺手打没了` — 详见 [v0.116.3.md](docs/releases/v0.116.3.md)

> 起因：移动端门禁里那条「打开时搜索框自动聚焦」时绿时红（33/0、32/1、33/0）。
> 红不红和实现对不对无关 —— 它红是因为**等待时间是个运气阈值**。
> 把时间轴摊开后牵出一条**跨版本的因果链**。
>
> ⚠ **本轮改了 `static/command-palette.js`**
> ⇒ 按 V0.100.1 规则**必须 bump `sw.js` VERSION** ⇒ 版本号 **V0.116.2 → V0.116.3**（4 处已同步）。

### Fixed

- 🐛 **命令面板打开后搜索框没有焦点，直接打字没反应**（`static/command-palette.js`）
  - 症状：按 `⌘K` / `Ctrl+K` 面板弹出来了，但光标不在搜索框里 ⇒ 打字无反应，必须先用鼠标点一下
  - 根因（跨版本因果链）：
    - V0.68.0（`5d0d81c`）加的自动聚焦：`setTimeout(() => input.focus(), 30)`
    - V0.113.0（`8f75b16`）为修「关闭态面板仍在 tab 序列里」这个**真实无障碍缺陷**，
      给 `.pm-cmd` 加了 `visibility: hidden` + **过渡**
    - 而 **`visibility: hidden` 的元素不能接收焦点** ⇒ 浏览器**静默丢弃** `focus()`
      （不抛异常、不打日志）；固定 30ms 与「visibility 翻成 visible 的那一帧」赛跑 ⇒ **看运气**
  - 实测：旧实现 12 次 open 只有 8 次落焦；修复后 **12/12**
  - 修法：`focusWhenVisible()` —— 等计算样式 `visibility` **真的**翻成 `visible` 再聚焦，
    并重试到 `activeElement` **真的**落上（时间截止 2.5s，不用帧数：低帧率机器会假红）

### 门禁加固

- 🔧 **「打开时搜索框自动聚焦」不再 flaky**：固定 350ms 等待 → 轮询到明确截止（2000ms）
- 🔧 **新增「延迟可见时搜索框仍然自动聚焦」判据**：把 `visibility` 过渡
  `transition-delay` 钉到 400ms ⇒ 旧实现必红、修复版必绿，**确定性**
  - ⚠⚠ 判据的杠杆**试错过一轮**：`transition-duration` 拉长过渡**根本不管用** ——
    `visibility` 是离散插值，过渡**第一帧**就翻成 visible（实测 t=29ms），
    加长 duration 只影响 opacity 淡入 ⇒ 门禁**假绿**
  - 正确的杠杆是 `transition-delay`（延迟期间保持起始值 hidden）
  - 另加一条**自检断言**「判据自检：面板确实是延迟可见的」，
    保证前提真的生效（`visibleAt > 300ms`），免得判据退化成「什么都没测」还照样绿

### 验证

- **反向验证**：回退实现 ⇒ 门禁 **34 passed, 1 failed**，连跑 2 次结果一致（确定性红）；
  恢复修复 ⇒ **35 passed, 0 failed**
- `scripts/_verify_cmd_palette.mjs` 30 passed, 0 failed
- `scripts/_diag_cmd_focus.mjs` 12/12 落焦，0 个 JS 错误
- 新增 3 个诊断脚本留证：`_diag_cmd_focus.mjs` / `_diag_cmd_focus2.mjs` / `_diag_cmd_focus3.mjs`

### 范围检查

- 全站同款「延迟聚焦」写法只有 `static/settings.js:341` 一处，**确认不受影响**：
  它的隐藏机制是 `hidden` 属性（`display:none`）且 `.modal` **没有任何 transition**
  ⇒ 可见时刻同步确定，不存在赛跑

### 已知问题（本轮**未**修，需要动生产数据库）

承 V0.116.2 §5，3 条仍未修：生产 `users` 表缺 `role` 列（admin 2 端点 500）、
`GET /api/v1/auth/me` 500、单用户模式 `require_owner` 认证边界错。
详见 [v0.116.2.md §5](docs/releases/v0.116.2.md)。

## [V0.116.2] · 2026-10-25

`3 处静默失效的前端缺陷` + `2 处「绿着但什么都没保护」的门禁缺陷` — 详见 [v0.116.2.md](docs/releases/v0.116.2.md)

> 起因：V0.116.1 把 CI 修绿之后，继续深挖前端，发现 **3 处「不报错、不红屏、就是少一块东西」** 的缺陷。
> 它们的共同点是**没有任何机制会告诉你坏了** ——
> 没有异常、没有 console 报错、没有测试失败，页面只是少了一块、或者显示成别的东西。
> 门禁也是绿的：因为门禁自己的扫描口径有洞（只扫顶层目录）。
>
> ⚠ **本轮改了 `static/ask.html` 与 `static/admin/users.html`**
> ⇒ 按 V0.100.1 规则**必须 bump `sw.js` VERSION** ⇒ 版本号 **V0.116.1 → V0.116.2**（4 处已同步）。

### Fixed

- 🐛 **「用户管理」页整页渲染成 i18n 键字面量**（`static/admin/users.html`）
  - 症状：页面显示 `admin.h_title` / `admin.denied` / `reset.btn_back_login` 而不是「用户管理」/「仅所有者可访问此页面。」
  - 根因：该页只引了 `i18n.js` + `auth.js`，**漏引 `/static/i18n/zh-CN.js`**
  - 为什么只有默认语言中招：`i18n.js` 里**非默认语言**会动态插 `<script>` 去取字典，
    **唯独默认语言 zh-CN 走 `syncLoadDefault()`**，只读 `window.PM_I18N_ZH_CN` ——
    字典文件没引 ⇒ `window.PM_I18N_ZH_CN` 是 `undefined` ⇒ zh-CN 全页回落成键字面量
    （切到 en-US / zh-TW 反而正常，因为那两条路径会自己去取字典）
  - 修法：补 1 行 `<script src="/static/i18n/zh-CN.js"></script>`
- 🐛 **`/ask` 的数据时效条 + 投资警示 pill 永久不可见**（12 个页面里唯一的一个）
  - 症状：`/ask` 页顶部没有「数据时效 / 警示计数」那一行
  - 根因：`<details id="statusPanel" class="status-panel" hidden>` —— **带 `hidden` 属性**
  - 为什么没人发现：另外 11 页（`trend` / `portfolio` / `silver` / …）的同名元素**都没有** `hidden`；
    而 `warning.js` 只操作 `open` 属性、**从不碰 `hidden`** ⇒ 没有任何脚本会把它救回来
  - 修法：去掉 `hidden`（`hidden` 优先级高于 UA 的 `details { display: block }` ⇒ 实测 `display: none`）
- 🐛 **`/ask` 的「本次会话不再展开」勾选框点了没反应**
  - 症状：勾上「本次会话不再展开」，下次还是自动展开
  - 根因：HTML 写的是 `id="warnDismiss"`，而 `warning.js` 查的是 **`[data-warn-dismiss]`**
    ⇒ `panel.querySelector("[data-warn-dismiss]")` 返回 `null` ⇒ 整段 dismiss 逻辑被**静默跳过**
  - 修法：补上 `data-warn-dismiss` 属性（保留 `id`，不破坏既有选择器）

### Changed

- 🔧 **门禁 `scripts/check_i18n_keys.py` 的字典加载检查改为递归扫描**（这是上面第 1 条能潜伏这么久的直接原因）
  - 原来用 `os.listdir(STATIC_DIR)` + `endswith(".html")` —— **只看顶层**，
    于是 `static/admin/users.html`（在子目录里）**永远扫不到** ⇒ 门禁一路绿灯
  - 同一个脚本里的 `extract_html_keys()` 用的就是递归 glob —— **两处口径不一致**，
    是这类漏扫的温床（同类：`check_docs_claims.py` 漏扫 `docs/releases/`）
  - 改后扫描面 **20 → 21 页**；反向验证：把字典行去掉 ⇒ `[FAIL] admin/users.html 用了 data-i18n 但没引字典文件`
- 🧪 **浏览器门禁 `scripts/_verify_i18n_keys.mjs` 23 → 42 条断言**（新增 19 条）
  - 新增 5 条：`/ask` 的 `#statusPanel` 存在 / 无 `hidden` 属性 / 计算样式不是 `display:none` /
    summary 可见 / 面板内有 `[data-warn-dismiss]`
  - 新增 9 条：`/static/admin/users.html` 在 zh-CN / en-US / zh-TW **三语**下
    标题 / 无权提示 / 返回按钮都是**译文**而不是键字面量
  - 新增 3 条（**泛化断言**）：任何 `data-i18n` 元素的正文若恰好等于自己的键就算失败
  - 新增 2 条：admin 页零 console error / 零 pageerror
  - **每条新断言都做了反向验证**（回退实现必须真的变红）：
    ① 加回 `hidden` ⇒ 红 3 条；② 去掉 `data-warn-dismiss` ⇒ 红 1 条；
    ③ 去掉字典行 ⇒ 红 4 条（且「残留 key 字面量」计数实测 10 个）

### 已知问题（本轮**未**修，需要动生产数据库）

- ⚠️ **生产库 `users` 表缺 `role` 列** ⇒ `GET /api/v1/admin/users` 与
  `POST /api/v1/admin/users/{id}/reset-password` 返回 500
  ⇒ 连带 `GET /api/v1/auth/me` 500（`DetachedInstanceError`），被 `static/auth.js` 吞掉后
  降级成「认证未启用」，顶栏状态显示不正确
  - 修法：新增 alembic 迁移补列 + 回填 `'owner'`，之后 V0.97.0 那个
    `require_user` 里的 `load_only` + `set_committed_value`  workaround 也可以撤掉
  - **本轮没做**：它要改生产 SQLite 库，属于「动生产数据」的动作 ⇒ 留给用户决定
- ⚠️ **单用户模式下 `require_owner` 接受匿名调用者** —— 认证边界不对（虽然当前请求会先 500）

## [V0.116.1] · 2026-10-24

`CI 修绿（ruff lint / ruff format / pytest 三步预存红）` + `版本状态整合（发版史对账 + 单一真源文档 + 版本同步门禁）` — 详见 [v0.116.1.md](docs/releases/v0.116.1.md)

> 起因：CI 从 V0.108.0 起**每一次 push 都是红的**，且失败步骤始终是同 3 步 ——
> `ruff lint`（290 errors）/ `ruff format --check`（79 个文件要重排）/ `pytest`（10 failed）。
> 这 3 步**都不在本轮改动范围内**（对拍 `HEAD~2` 确认全部预存），但**长期红着的 CI 不能当质量信号**
> —— 每次发版都要重新花 25 分钟 + 一个 worktree 对拍才能确定「不是我搞坏的」。
> 本轮把它们修绿，并顺带修掉 ruff 暴露出的真 bug。
>
> ⚠ **本轮改了 `static/*.html` 与 `static/i18n/*.js`**（`ask.html` / `weights.html` / 3 个 i18n 文件）
> ⇒ 按 V0.100.1 规则**必须 bump `sw.js` VERSION** ⇒ 版本号 **V0.116.0 → V0.116.1**（4 处已同步）。
> 详见 [docs/version-status.md](docs/version-status.md)。

### Added

- 📊 **[docs/version-status.md](docs/version-status.md)（新）—— 应用版本状态的单一真源**
  - 4 处版本号（`src/app/__init__.py` / `pyproject.toml` / `uv.lock` / `static/sw.js`）的**位置 / 值 / 谁读它 / 不同步的后果**
  - 4 个来源的**覆盖矩阵**（bump 史 64 / CHANGELOG 39 段 / release notes 48 / tag 100）与**故意保留的缺口**（各附原因与逐个版本号）
  - 「怎么自己查」：可直接复制的 grep 命令 + 门禁命令
- 🚦 **新门禁 `scripts/check_version_sync.py`（9 条断言）** —— 覆盖之前**无人看管**的 `pyproject.toml` ↔ `uv.lock` 一对
  （改了 pyproject 忘了 `uv lock`，本地跑任何门禁都绿，只有 CI 的 `uv sync --frozen` 会炸，而那报错离根因很远）
  - 另含 **CHANGELOG 版本段严格降序、无重复** —— 这条正是抓出下面 4 处历史错位的判据
  - 另含 `version-status.md` 基线版本校验 —— **防这份单一真源文档悄悄过期后开始撒谎**
- 🧪 **`scripts/_reverse_check_version_sync.py`（11 个反向用例）** —— 注入 11 种故障，逐条确认门禁能变红
  - 过程中抓出**门禁自己的一个假绿**：index.md 登记检查原先用裸子串匹配 `v0.116.0.md`，
    改成 `v0.116.0.md.x` 仍全绿 —— 已改为匹配 markdown **链接目标**
- 🏷️ **补打 46 个 git tag**（v0.85.0 ~ v0.116.0 + 6 个从未 bump `__version__` 的版本），tag 总数 54 → 100
  - 版本 → commit 的依据是 **`__version__` bump 史**，不是 commit message 里 grep 版本号
    （后者会撞上「功能批次标签」：V0.101 / V0.102 从未 bump 过版本号）
  - ✅ **已全部推送到 GitHub**（2026-10-24）：远端 100 = 本地 100，逐个比对指向 commit，**不一致 0 个**
    - 📌 **实际推了 48 个，不是 46 个**：本地比远端多 48 个 tag，其中 46 个本轮新建，
      另外 2 个（`v0.83.0` / `v0.83.1`）是**原作者 2026-10-10 就建好但一直忘了推的** ——
      远端原先从 v0.83.2 起才有。也就是说本地原有 54 个里原先只有 52 个在 GitHub 上。
    - 推之前逐个核对过：48 个 tag 指向的 commit **全部是 `origin/main` 的祖先**，不会留悬空 tag。

### Changed

- 🔧 **ruff `check --fix` + `format` 全量跑通（`src` + `tests` + `scripts`，308 个文件）**
  - `ruff check`：**290 → 0 errors**（257 条自动修 + 33 条手工改）
  - `ruff format --check`：**79 个文件要重排 → 0**（`scripts/` 另有 11 个；CI 不 lint `scripts/`，本地一并守）
  - **语义零变化的证明**：逐文件 **AST 比对**（`ast.dump`）——
    99 个改动的 Python 文件里 **49 个 AST 完全等价**（纯格式）；
    其余 50 个的实质改动逐条列出并人工核对（含 1 处**我自己改出**的语义 bug，见下）
  - ⚠ `ruff format` 会把「一行 7 个关键词」的紧凑表炸成一行一个 ⇒
    `news_classifier.py` 的 4 张关键词表用 ruff 官方 `# fmt: off` 保住原有排版
    （分组注释 `# ── 行情 ──` 只在紧凑排版下读得懂）；该文件 638 → 340 行
  - ⚠ **`scripts/check_docs_claims.py` 一度被我改成无条件 `return`**，把「首段是目录名
    ⇒ 判为模块路径」那条判据变成了**死代码**（AST 比对时发现）⇒ 改回
    `return len(segments) >= 4 and segments[3] in {...}`（语义等价且仍过 SIM103）

### Fixed

- 🐛 **CI 的 3 步预存红全部修绿**（`ruff lint` / `ruff format check` / `pytest`）
  - **pytest 10 failed → 0**。10 条全是**预存**（在干净 worktree 里对拍 `HEAD` 逐条复现：
    9 条单跑即红 + 1 条须整文件跑才红），根因逐条修掉：

    | 文件 / 用例 | 根因 | 修法 |
    |---|---|---|
    | `test_ai_chat_endpoints.py::test_send_message_stream_error_event_yields_error` | **同文件内测试顺序污染**（不是 flaky）：`sse_starlette` 的 `AppStatus.should_exit_event` 是**类级全局**且惰性创建，`anyio.Event` 首次 await 时把 `_loop` 绑死；pytest-asyncio 每个用例新建 loop ⇒ 后面的用例 await 了别的 loop 上的 Event | `tests/conftest.py` 加 autouse fixture，每个用例前重置 `should_exit_event` **与** `should_exit`（只重置前者不够，后者同样会短路关闭信号） |
    | `test_news_feed.py::test_list_items_filter_days` | seed 用**写死的 2026-10-19**，而 cutoff 是**相对当下**的 `now - days` ⇒ 测试随日历腐烂 | seed 改**相对今天**（`_D0/_D1/_D2`），`days=2` 留 12 小时余量；实测 400 天 × 24 小时零失败 |
    | `test_i18n_coverage.py::test_all_data_i18n_keys_resolve_in_zh_cn` | `ask.html` 用了 `data-i18n="status.warnings"`，**该键 3 语都没有** | 改用已有的 `status.warn_pill_label` |
    | `test_i18n_dict.py::test_no_empty_values` / `test_no_duplicate_keys` | `weights.mo_loading` **重复定义**；`en-US.js` 的 `ai.msg_count_unit` 是**空串** | 删重复键 + 新增 `weights.mo_loading_short`；`ai.msg_count_unit` 填 `"msgs"` |
    | `test_scripts_check_pwa_assets.py::test_shell_entry_referencing_const_is_expanded` | 夹具造的 HTML **没有 `<link rel="icon">`** ⇒ 门禁正确地判它不合格 | 夹具改成合法 HTML（含 icon link）+ 造出 `icon-192.png` |
    | `test_scripts_check_routes.py` ×3 | 断言**写死的个数**（16 / 15 / 18），alias 数一路涨到 18 后**恒红** | 改成**集合相等**断言（alias ∪ 额外端点）+ 新增「无重复项」断言 |
    | `test_admin_users.py::test_anonymous_returns_401_or_403` | 断言「匿名应被拒」，但 V0.97.0 起单用户模式（`auth_enabled=false`，本仓库默认）`require_user` 会**回退到 LEGACY_USER** ⇒ 实际 200 | 拆成**两条模式专属**用例：单用户模式断言回退身份 + `is_self`；多用户模式（monkeypatch `auth_enabled=true`）断言 401 |

  - 🐛 **顺手修掉 1 条「绿着但什么都没保护」的断言**（`ruff` 的 F841 顺带指出来的）

    | 用例 | 病根 | 修法 |
    |---|---|---|
    | `test_main_app.py::test_root_alias_count_matches` | 这条**在 HEAD 上是绿的**（不是 pytest 失败，是 ruff 的 F841 把它挖出来的）：`assert len(ROOT_ALIASES) == 18` —— **常量比常量**（`ROOT_ALIASES` 是测试文件里自己写的列表），且辛苦算出来的 `root_gets` **从头到尾没被用过** ⇒ 什么都没保护 | 改成与 `app.routes` **双向集合比对** + 逐条查跳转目标文件**真实存在** |

- 🐛 **ruff 顺带抓出 1 处真 bug**（不是 lint 噪音）
  - 🔴 **`market.py` 的 `HTTPException` 没 import** —— SGE 白银行情 / 历史数据失败时
    本该抛 **503**，实际会变成 **NameError → 500**。`ruff` 报 F821 才暴露出来。

- 🐛 **顺手修掉 3 处「重复定义 / 死代码」** —— 这类东西 lint 抓不到，靠逐行读 diff 才发现
  - 🔴 `dependencies.py` 里有**两份字节完全相同**的 `get_scoring_wide_service` ——
    后一份**遮蔽**前一份 ⇒ **改其中一份不生效**，是最难查的那类 bug
    （同类还有一份 `get_scoring_wide_repository`）
  - 🔴 `news_classifier.py` 里有**两份内容不同**的 `_SITE_HINTS`（40 条 vs 34 条）——
    后一份（V0.109.1 的「只有垂直媒体参与兜底」）遮蔽前一份 ⇒ 前一份是**死代码**，
    但读起来完全像生效的。AST 核对确认**区间内无人读它**后才删。
  - 🟡 `ai_chat/service.py` 的 `had_error` 变量 —— 赋值 4 次、**从未被读**

- 🧪 **新增门禁 `scripts/_verify_i18n_keys.mjs`（23 条断言）** —— 本轮改了 3 处 i18n，
  pytest 的 `test_i18n_coverage` 只能证明「键存在」，证不了「**文案真的被翻译到 DOM 上**」
  - ⚠️ 关键点：`ask.html` 原来的 `data-i18n-attr="placeholder|ai.input_placeholder"`
    **i18n.js 根本不读这个属性** ⇒ placeholder **从来没被翻译过**（改前 en-US 下显示中文）
  - ⇒ 改成 `data-i18n-placeholder`（i18n.js 认的 5 个属性之一）
  - ⇒ 门禁查 `getAttribute("placeholder")` 的**实际值**（不是查 `data-lang`），三语各验一遍
  - ⇒ **反向验证过**：改回 `data-i18n-attr` 后门禁真红 3 条（「只绿一次」不算门禁）

- 🐛 **CHANGELOG 的版本归属曾经是乱的** —— 实测到 4 处，查发版史会**查错版本**：

  | 问题 | 实测证据（改前） |
  |---|---|
  | `## [V0.105.0]` 出现两次，第一次是**空壳**（只有 header + `---`） | 全文 35 段 / 32 个唯一版本号 |
  | `## [V0.104.0]` 出现两次，**第一次那段里混装着 5 个别的版本**（V0.102.0 / V0.103.0 / V0.100.1 / V0.100.2 / V0.103.1） | 第一次那段 line 801-845、4809 字 |
  | V0.100.0 的段被拆成两半：主体在 line 846-868，**它的 `### Discipline`（line 900-904）+ `[详情]` 链接被甩到第二个 V0.104.0 段之后**，中间没有任何 `## [V0.100.0]` header | 改前文件共 1154 行 |
  | 顺序错乱：V0.100.0 夹在两个 V0.104.0 之间；V0.107.0 排在 V0.107.1 前面 | — |

  - ⇒ **「今日要闻」那段真实交付原本挂在 V0.104.0 名下**，而 V0.104.0 真正的内容（日期分页）在另一处
  - ⇒ 改法：按**行号切片逐字搬运**（不是重新誊写），重排为严格降序；
    补上此前缺失的 V0.103.1 / V0.103.0 / V0.102.0 / V0.101.0 / V0.100.2 / V0.100.1 六段
  - ⇒ **内容保全已验证**：改前改后全文行多重集比对，**只有 2 行消失**（那两个重复 header 各从 2 份变 1 份），
    新增 32 行 = 29 行包装文字 + 3 行 V0.101.0 的内容 bullet（该 3 个 commit 已核验存在且 subject 对得上）
  - ⇒ 补记了 **V0.101 / V0.102 从未作为版本号发版**的事实 —— 它们只是 commit message 里的功能批次标签
- 🐛 **CHANGELOG 底部的 link reference 定义有 5 条是坏的**（4 条指向不存在的 release notes + 1 条指向 `example.com` 占位 URL）
  - ⇒ 坏的那 5 条已删除；**且今后由 `check_links.py` 门禁管住**（此前根 `CHANGELOG.md` 根本不在死链扫描范围内）
- 🐛 **`## [Unreleased]` 段落原本是空的、且落在文件中间**（line 652，夹在 V0.107.0 与 V0.106.2 之间）
  - ⇒ 已移到文件头，填上本轮内容
- 🐛 **`docs/README.md` 里「39 份 release notes」是过期的**（实际 48 份）—— 已更正，并补上 `version-status.md` 的入口与新门禁

### Discipline

- **版本号只认 4 处**：`src/app/__init__.py` 的 `__version__` 是唯一真源，
  `pyproject.toml` / `uv.lock` / `static/sw.js` 是它的副本 —— 本轮新增门禁把这条从「靠自觉」变成「靠门禁」
- **发版记录的唯一权威是 CHANGELOG 的版本段顺序** —— 顺序乱了 = 版本归属乱了 = 查发版史会查错
- **单一真源文档必须会过期** —— 所以 `version-status.md` 的基线版本进了门禁：
  发版时忘了更新它，门禁立刻变红，而不是让它慢慢开始撒谎

---

## [V0.116.0] · 2026-10-22

`AI 对话文本格式重做（清洗器 / 移动端裁切 / 排版）` — fix · 详见 [v0.116.0.md](docs/releases/v0.116.0.md)

> 用户：「当前应用在 AI 对话中对文本格式支持不够完善，能不能进行很好的改进。」

- 🔐 **清洗器换成本地 DOM 白名单**（约 40 行，无正则、不引第三方）
  - 旧实现是**正则**，而且**正则写错了**：`onc(?:lick|load|error|…)` 里 `on` 后面多了个 `c`
    ⇒ 只能拼出 `onclick`，另外 7 个事件处理器**永远接不到 `onc` 后面**。
    实测 `<img src=y onerror="…">` 属性原样进了 DOM；`style` 属性根本不在清洗范围内
  - ⇒ DROP 集合连子节点一起删，KEEP 集合外 unwrap，属性只留 `a[href]`（限 http/https/mailto/站内）
- 📱 **移动端不再横向裁切**：390px 视口下长 URL 曾把对话列撑到 **613px**、裁掉约 200px 且**滚不到**；
  `<pre>` 代码块撑到 431px（裁 17px）
  - ⇒ `.ask-main` → `.message-stream` → `.message` → `.bubble` 的 flex 链条**一路 `min-width: 0`**
  - ⇒ `overflow-wrap: anywhere`（`break-word` 不影响 min-content，挡不住撑宽）
  - ⇒ 用户气泡走 `textContent` 无 `<p>` 包裹，需要**单独**一条规则
- 🎨 **排版补齐**：`h1`–`h6` 字号阶梯 + 间距、`hr` 分隔线间距（原 `* { margin: 0 }` 把它清零了，
  实测 `hr` top=682 紧贴下一段 top=684）
- 🫧 **去双气泡**：`renderAssistantMsg` 原本内外套了**两个** `.bubble` ⇒ 双边框 + 16px/24px 双份内边距
- ➕ **渲染后增强管道** `enhanceBubble()`：表格套 `.table-scroll`（键盘可横滚）、
  代码块加复制按钮（排在自己的工具条行，**不叠在代码上** —— 滚动容器的 padding-right 只在滚动末端生效，截图实测过）、外链补 `target/blank` + `rel`；流式期间不挂按钮
- 📝 **提示词显式要 markdown**（原来模型只是「碰巧」在用）+ 5 条 pytest（含规则号连续性）
- 🚦 新门禁 `scripts/_verify_ask_format.mjs` **97 条断言**，每条都做过反向验证
  （回退实现确认能变红 —— 过程中抓出 4 处门禁自身的假绿/误报）

## [V0.115.0] · 2026-10-22

`首页贵金属走势区（金价 / 黄金库存 / 央行购金）` — feature · 详见 [v0.115.0.md](docs/releases/v0.115.0.md)

> 用户：「我们在主页页面内容缺少贵金属走势的页面，包括 金价变化、黄金库存变化、央行购金变化，
> 卡片放在今日要闻前面。」

- 🥇 首页新增**贵金属走势区**（`.home-scenes` 8 张板块卡与今日要闻之间的独立整行 section），
  三张卡：**金价变化**（XAU + 518880 + Au99.99 + 60 日走势线）/ **黄金库存变化** /
  **央行购金变化**（WGC 全球合计季度 + 较上季吨数增减）
  - ⇒ `.home-scene` 卡数**仍是 8**，顶 nav `SCENES` 不动，既有门禁断言零影响
- 📦 **COMEX 黄金库存从零建**：模型 + 迁移 `s1t2u3v4w5x` + 子进程隔离 fetcher
  （akshare 内嵌 V8 会崩 uvicorn）+ repo + service + `GET /market/gold/inventory`
  + 每日 08:10 BJT 调度 + CLI。实测 **1234 行 / 2021-10 起 / 最新 727.96 吨 / 近 1 年 -41.65%**
- 🔎 数据源是**实测选出来的**：否掉 `spot_quotations_sge`（无库存字段）与
  `fund_etf_scale_sse`（单截面且陈旧 21 个月、且不是库存口径）
- 🐛 **1y 变化率恒为 `None`** —— `snapshot()` 用 `date.today()` 当回看起点，
  但最新观测日落后今天 2 天，「一年前」那点落到窗口外。1m/3m 正常、**只有 1y 静默为空**
- 🐛 **`IntegrityError: NOT NULL ... source`** —— Core `insert()` **绕过 ORM 的 Python 侧
  `default`**（只认 `server_default`），迁移写了而模型没写 = schema 漂移
- 🐛 **2 处既有静默失效**（顺带）：hero 两个 chip 读的字段后端根本不返回
  （`price` vs `price_usd`、`overall_status` vs 只有 `degraded`）
  ⇒ 金价 / 时效 chip 从上线起一直停在 `金价 --` / `时效 --`
- ✅ 门禁：`_verify_home_metals.mjs` 34 条断言 + **反向验证 4 处**（挪位置 / 打桩
  `drawSpark` / 改回错字段名 / zh-TW 退简体，逐条确认变红）
- ✅ `check_i18n_keys.py` 新增 `"home."` 前缀 —— in-scope 240 → **307**，**0 missing**
  （此前首页文案根本不在严格清单里，漏同步只会静默回落）

---

## [V0.114.2] · 2026-10-22

`修点上传没有文件对话框` — hotfix · 1 处 CSS · 详见 [v0.114.2.md](docs/releases/v0.114.2.md)

> 用户报「点击报告上传，浏览器中没有文件上传的对话框」并附「我用的是 Firefox」。
> **Firefox 是对的线索，但不是原因** —— Chrome 实跑同样不弹。

- 🐛 上传区file input 是 `display: none`，而 `.drop` 上**只挂了 drag 事件、没有
  click 处理器** ⇒ 提示文案承诺的「点击选择」根本没有实现，唯一能用的路径是把
  文件**拖进来**，而文案完全没提。**所有浏览器都一样坏**
- 🔧 修法：把 `display: none` 换成**铺满 `.drop` 的透明覆盖层**（`opacity:0` +
  `position:absolute` + `z-index:2`）。真实点击落在**原生 file input** 上 ⇒
  浏览器默认行为就是弹对话框，**点击路径上不经过任何 JS**
  - ⚠️ **不用**「`display:none` + JS 调 `input.click()`」：Chrome 放行、Firefox
    拒绝（元素未渲染不允许唤起文件选择器）—— 不加注释就会在 Chrome 测得通过、
    上线后只在 Firefox 静默失效
  - ⚠️ 用 `opacity:0` 而非 `visibility:hidden`：后者会让控件在部分浏览器里
    **不可聚焦**，键盘用户彻底够不着（V0.113.0 口径）。配 `:focus-within`
    给 `.drop` 一圈可见焦点环
  - ♿ 拖拽不受影响：drag 事件从覆盖层冒泡到 `.drop`，原有监听器照旧命中
- 🧪 新增 `scripts/_verify_upload_dialog.mjs`（10 断言），**反向验证 6 条变红**，
  含决定性的一条：退回 `display:none` 后 `elementFromPoint` 命中的是无处理器的
  `<SPAN>`
- ⚠️ **判据选错的教训**：第一版用 `page.on("filechooser")` 当判据，结果是红的。
  基线测试证明**这个 headless Chrome 连裸 `<input type=file>` 真实点击都不发
  `filechooser`** —— 那条断言测的是 puppeteer 的能力，**比没有断言更坏（假绿）**。
  换成 `elementFromPoint(落点)` 才是真判据
- ⚠️ **未在 Firefox 实跑验证**：`puppeteer browsers install firefox` 因网络受限
  下不下来，请在 Firefox 里确认一次再收工

## [V0.114.1] · 2026-10-22

`修全站 favicon 404` — hotfix · 无新资源 · 详见 [v0.114.1.md](docs/releases/v0.114.1.md)

> V0.114.0 的 puppeteer 实跑里，`/favicon.ico` 的 404 一直躺在「豁免清单」里，
> 当时的判断是「全站性既存项、纯装饰、不在本轮范围」。**豁免存在过本身就是它坏了
> 的证据** —— 留着它，下次真出同类 4xx 会跟着一起被跳过，门禁从此对这一类失明。

- 🖼️ **根因**：浏览器约定 favicon 在**站点根** `/favicon.ico`，而 `StaticFiles` 只挂
  `/static/`；21 个页面**全部**没声明 `rel="icon"`。20 页虽引了 `rel="manifest"`，
  但 **manifest 的 icons 是 PWA 安装图标，不做标签页 favicon** ⇒ 照样 404
- 🔧 两层修法（分层不是冗余）：
  - **根作用域 `/favicon.ico` 路由**（真正止血的那层）—— 理由与既有 `/sw.js` 完全
    相同。兜旧书签 / 收藏夹 / PWA 安装前首屏 / 不解析 link 的客户端
  - **21 页补 `<link rel="icon">`**（声明式加固）—— 省一次根路径往返，路由若被
    nginx 改写仍有效。`static/icon-192.png` 早就在仓库里，**不新增任何资源**
  - ⚠️ 返回 192px PNG 而非真多尺寸 `.ico`；`content_type` 如实写 `image/png`，
    **不撒谎**（撒谎会让部分浏览器拒绝解析）
- 🧱 门禁：`check_pwa_assets` 从 3 项扩到 **4 项**（每页 rel=icon 存在 + href 指向
  真实文件 + `.png` 须带 type）；`check_routes` 登记 `/favicon.ico` → 200，
  路由数 **19 → 20**
- 🧪 三条反向测试**各自变红**：删标签 / href 指不存在 / 去掉 type。4xx 检测机制本身
  也反向验过（请求拦截器人为造 404，断言如实变红）
- 🎯 验证脚本 **删掉**豁免：puppeteer **23 → 28 passed / 0 failed，零豁免**

## [V0.114.0] · 2026-10-22

`新闻多源容灾` — 4 源链式 failover + 修「收藏无反馈」三层缺陷 · 详见 [v0.114.0.md](docs/releases/v0.114.0.md)

> 今日要闻原本**只有 readhub 一个源**，而这轮实测中 readhub 直接超时了一次 ——
> 单点无冗余不是理论风险，是已经发生过的事。

- 🔁 **4 源链式 failover**（wallstcn ★ → jin10 → eastmoney → readhub 兜底），首个足量即止
  - ✅ 端到端真重启 uvicorn 验 5 种场景：基线 `wallstcn/21` → A 挂 `jin10/16` →
    B 挂 `eastmoney/16` → C 挂 `readhub/14` → **D 四源全挂返回 HTTP 200**
    + `ok=False` + error 列全 4 源，`/items` 仍供末次数据（V0.84：绝不 500）
  - 🧱 `external_id` Integer → **String(32)**。计划里写的是 BigInteger，**实测推翻**：
    SQLite 的 INTEGER 是 int64（≈9.22e18），金十 id ≈2.02e19 ⇒ `OverflowError`。
    再加 `models/base.py::SourceId` TypeDecorator，因为绑定发生在 Python 侧、
    早于 SQLite affinity
  - 🔑 `UNIQUE(external_id)` → `UNIQUE(source, external_id)`：多源后 id **不再全局唯一**，
    同一个数字可能同时是华尔街见闻的 `3182985` 和金十的某条
  - 🌐 实测**金十 / 东财 0/20 条有 url** ⇒ url 改可空，无链接时标题渲染成
    `span.no-url` **不可点纯文本**（不合成 `href="#"`，V0.77.1）
  - ⚠️ 东财成功码是**字符串** `"1"`，`code != 1` 会把成功当失败（踩过）

- 🔔 **修「收藏从头到尾没有任何反馈」（三层，全是既存）**
  - ① `toast.js` 从未导出 `show`，而全站 **14 处**在调 `PM_Toast.show(...)`
  - ② `headlines.js` / `home.js` 只 guard `window.PM_Toast` ⇒ TypeError；
    `favorites.js` / `report-archive.js` guard 到 `.show` 为 falsy ⇒ 静默不弹
  - ③ `headlines.js` **模块作用域没有 `t()`**，却裸调 `t("favorites.toast_archived", ...)`
    ⇒ `ReferenceError`，且抛在 **catch 块内**无人接管 ⇒ 未处理拒绝
  - 三层用户可见后果**完全一样**：点了收藏，POST 成功，屏幕毫无反应
  - 🩹 修法：`toast.js` 补 `show(msg, type)` 派发器（一次修好 14 处，含 `error`→`err`
    别名 + 未知值退回 info 绝不抛错）；`headlines.js` 两处改 `tr()`
  - ⚠️ `headlines.js` **故意**不叫 `t()`：本页 `fmtBjtDate()` 内部有 `const t = new Date(iso)`，
    同名会把翻译函数整个遮蔽

- 🧪 **57 个新测试**（`test_news_sources_fetcher.py`）＋ 6 个多源入库测试 ＋ 5 个收藏服务测试
  · 相关 8 个文件 **195 passed / 1 failed**
  - 🕵️ 那 1 个失败是**既存**（已 `git stash` 在未改动的 main 上复现）：
    `test_list_items_filter_days` 的种子数据写死 2026-10-19，今天 10-22 ⇒ `days=1` 全被过滤。
    修它要连带改 4 个测试语义（tz-offset 用例期望 id 从 1002 翻成 1001），会让发版 diff
    混进无关改动，单独一轮处理
  - 🖥️ puppeteer **23 条断言全绿**：4 源渲染 / 无 `href="#"` 假链接 / fav POST 带
    `news_source` / 金十 20 位 id 全程字符串（点 `20261022055128917800` → POST 原样透传，
    先前 `parseInt` 会静默舍入到 …7000）/ 点收藏真的弹出 toast / 3 语无 key 泄漏
  - 🪞 验证脚本自身也修了两次：① 只能绿一次不算门禁（第二轮点同一张卡必然 409 幂等
    分支）⇒ 点击前经 API 删上一轮收藏；② 只断言「请求发出去了」不够（服务端 4xx 时前端
    同样发请求）⇒ 补真实响应码，顺手发现 POST 返回 **201** 不是 200

- 🔢 版本号 4 处同步 0.114.0（`__init__.py` / `pyproject.toml` / `uv.lock` / `sw.js`）

## [V0.113.0] · 2026-10-22

`移动端可用性` — UI + 门禁 · 无后端改动 · 详见 [v0.113.0.md](docs/releases/v0.113.0.md)

> 本项目第一次**在 390px 真实视口下逐页实测**。此前所有「响应式」都是桌面浏览器
> 缩窄窗口看出来的，没量过触控手指够不够得着。三类缺陷，而且**全都不报错**。

- 📱 **横向溢出 18/18 页归零**（此前 4 页表格溢出：`/scoring` **221px**、
  `/report` 175px、`/silver` 123px、`/central_bank` 71px；另 6 页因引导提示框硬编码
  宽度各多 11px）
  - 🧱 `.table-scroll`（`overflow-x:auto` + `overscroll-behavior-x:contain`）
    基元进 `theme.css`，**11 张宽表**套用：`scoring.js` 3 / `report.js` 5 /
    `silver.js` 1 / `silver.html` 1 / `central_bank.html` 1
  - ♿ 每处带 `tabindex="0"` + `role="region"` + `aria-label`（WCAG 2.1.1
    键盘可滚动）。**CSS 做不到，只能写在标记里**
  - 🌍 `aria-label` **复用小节标题已有的 i18n key**，静态页用 `data-i18n-aria`
    跟着语言翻 ⇒ **本轮新增 0 个 i18n key**
  - ⚠️ 基元**刻意不加** `min-width: max-content`：落地前写过带它的草案，验证时
    发现含长文本的表格在**桌面端**也被拖出滚动条才删掉

- 👆 **44px 触摸目标（WCAG 2.5.5 / Apple HIG 44pt），18/18 页归零**
  （此前 `/headlines` 单页 115 个，其余页零星 1–30 个）
  - 📐 `@media (max-width: 640px), (pointer: coarse)` 取**或** —— 平板横屏不窄
    但一定触摸，手机竖屏很窄但可能接鼠标，只认一个都会漏
  - 🚫 **刻意不放大**正文段落流里的文字链（`/headlines` 有 23 个，撑到 44px 会把
    排版撕碎）与 checkbox/radio 方块本体（触摸区域是包它的 `<label>`）
  - ⚠️ **`responsive.css` 的 40px 会压回 44px** —— 它在各页内联 `<style>` **之后**
    加载、同特异性胜出。光改 `theme.css` 的话全站 20 个按钮仍卡在 40px

- ⌨️ **聚焦被 sticky 顶栏遮挡 17 处 → 0**
  - 🐛 **17 处里 16 处是同一个 bug**：关闭的命令面板只有 `opacity:0`，而
    **`opacity:0` 的元素仍在 tab 序列里**（WCAG 2.4.3 / 2.4.7）。键盘用户进页面
    第一个 Tab 到的就是这个看不见的搜索框，且正好落在顶栏底下 ⇒ 看着像「点不动」。
    18 页里 16 页中招。**只影响键盘用户，鼠标用户完全无感** ⇒ 一直没人发现
  - 💡 关闭态改 `visibility: hidden`（参与 transition，淡出结束后才真正移出 tab
    序列），打开态 `visible`
  - 🎯 `scroll-padding-top`（浏览器滚动对齐预留）跟随顶栏**实测**高度，挂
    `resize` + `ResizeObserver` + `document.fonts.ready` + `i18n:change`

- 🐛 **顺手修 3 个既存缺陷**（验证时撞见的，都属 V0.77.1「静默展示错误内容」）
  - **`/report` + `/reset-password` 漏引 i18n 字典文件 ⇒ 整页渲染成 key 字面量**
    （21 + 11 处）。根因 `i18n.js:46`：非默认语言会动态插 `<script>` 取字典，
    **唯独默认语言 zh-CN 走 `syncLoadDefault()`**，只读 `window.PM_I18N_ZH_CN`，
    不自己去取 ⇒ **漏引没有任何机制会报错**
  - **`/report` 每访问一次吃一个 favicon 404**（单独引 `favicon.svg`，而该文件
    从来不存在；全站仅此一页引，图标已由 manifest.json 承担）
  - **`help.js` 提示框硬编码 320px 宽度** —— 窄屏媒体查询已改成
    `calc(100vw - 24px)`，拿桌面的 320 钳位 ⇒ 6 页各多 11px 横向溢出

- 🚪 **门禁 7 道全绿**，`check_cluster_render` **461 passed / 0 failed**（+28 断言）
  - 🎯 三个新基元都是**静默失效**型（写坏了不报错、DevTools 不显形），必须钉住：
    `.table-scroll` 4 条 / 44px 规则 7 条 / `responsive.css` 同步 2 条 /
    命令面板 `visibility` 2 条 / `topnav` `scroll-padding-top` 2 条 /
    11 张表源码契约 11 条
  - ⚠️ **本轮踩到的最大的坑**：44px 规则为了排版折成两行，换行 + 缩进被 CSS
    解析成**后代组合器**（匹配「input 里的 input」）⇒ 输入框实测停在 27–35px，
    而 `min-height: 44px` 就在文件里、`.matches()` 全绿 —— **就是没生效**。
    所以门禁那条核心断言查的不是「文件里有没有 `min-height: 44px`」（查不出死
    规则），而是「**选择器有没有被折成后代组合器**」
  - ⚠️ **门禁自己也踩了同一个坑**：第一版扫 `.pm-cmd` 规则里的 `visibility: hidden`，
    反向验证时**把真声明删掉门禁依然全绿** —— 因为该规则上方解释「为什么需要它」的
    ⚠ 注释里就写着 `visibility:hidden` 字样。改成**只扫字符串字面量**。这与
    `check_static_js` 里的「注释里的 `<script>` 字面量让正则吞掉真脚本」同类：
    **注释里的「代码样文字」不能当代码**
  - ✅ `check_i18n_keys` 新增字典文件加载检查（20 页）
  - ✅ `check_static_js` 在 `node --check` 前**先剥 HTML 注释**（注释里的
    `<script>` 字面量会让非贪婪 `.*?</script>` 吞到下一个真 `</script>`，
    报出的语法错误指向真实代码之外的行）
  - 🧪 **反向验证 9 个注入缺陷，9 条各自变红**。只看退出码会把崩溃当通过，所以
    每条都要求红在**指定那条**断言上；其中 1 条第一版红在别处（同块里
    `input[type=range]` 也带 44px，把「块内存在 44px 规则」顶住了）⇒ 断言改成
    判「input 规则**确实**带 44px（选择器与声明同属一条规则）」

- ✅ **新增 `scripts/_verify_mobile.mjs`（33 断言，18 页 × 390px 实跑）：全绿**
  逐页横向溢出 + 触摸目标 + 聚焦遮挡（合并在一次 `page.evaluate` 里）· 滚动容器
  真能滚 / `tabindex` / `role` / 无障碍名**不是 i18n key 字面量** · 11 张表源码契约 ·
  三语下 `aria-label` 跟着翻 · 关闭面板不可聚焦**且打开时仍然可见可聚焦**（别把功能
  改没了）· `scroll-padding-top == 顶栏实测高度`
- ✅ **回归全绿**：`_verify_cmd_palette` 30 · `_verify_nav_8` 26 ·
  `_verify_report_archive` 43（本轮动了 `topnav.js` / `command-palette.js` /
  `theme.css` / `responsive.css`，回归面不算小）
- 🔢 版本号 4 处同步 0.113.0（`__init__.py` / `pyproject.toml` / `uv.lock` / `sw.js`）

## [V0.112.0] · 2026-10-21

`命令面板修好` — UI + 门禁修复 · 无后端改动

- ⌘ **修好 ⌘K 命令面板**（V0.68.0 建的设施，此前一直半残）
  - 🐛 **全站没有任何可见入口**：`open()` 只由 Ctrl+K 触发 ⇒ **手机上 100% 打不开**
  - 🐛 **菜单停在两代导航之前**：硬编码的 7 条平铺导航，V0.98 双层导航、V0.111
    收敛到 8 场景后都没跟上 —— 今日要闻 / 报告存档 / 打分汇总 / 参数回测 / 白银 /
    收藏 / 数据健康 / AI 全部缺席
  - 💡 **根因不是忘了改，是没法改**：`SCENES` 只活在 `topnav.js` 的 IIFE 里不导出，
    面板拿不到导航结构只能自己抄一份，抄的那份自然腐化。现导出
    `window.PM_Topnav.SCENES`，面板在 `open()` 时**惰性派生**清单（8 场景 + 子页
    去重后 17 个导航目标 + 2 个动作 = 19 条）—— 加减导航项面板自动跟随，
    结构上不可能再腐化。惰性读取同时解开了与两个 defer 脚本的执行顺序耦合
  - 🚪 **顶栏新增「⌘ 搜索」按钮**（18 个有顶栏的页全有）：手机上唯一能打开面板的
    入口。走 `data-action` + document 委托，与导出按钮同一模式
  - 📱 **9 个页补挂 `command-palette.js`**（此前只挂 9/18）：`ask` / `backtest` /
    `data-health` / `favorites` / `headlines` / `home` / `report-archive` / `report` /
    `silver`。`login` / `offline` / `reset-password` 无顶栏，不补
  - 🧹 **删掉 / 修好 5 条「按下去什么都不发生」的死命令**（V0.77.1「失败态不伪装」同理）
    - 切换时间区间 ×3：派发 `pm-range-change`，全站 **0 个监听方**
    - 主题切换：派发 `pm-theme-change`，同样 0 个；且 `#pmThemeBtn` 本就常驻可见
    - 帮助：V0.68 调的是 `PM_Help.show()`，而 `help.js` 导出的是 `{ showModal,
      showTour, ... }` —— **从来没有 `show()`**。改调 `showModal()`
  - 🎨 **清单按场景分组**、组头不可点；过滤匹配 标题 / URL / 所属场景名；
    标签走 `I18n.t()`（只用 `fb` 会在 en-US 下显示中文，与顶栏对不上像 bug）
  - 📱 **触屏适配**（`pointer: coarse`）：行高提到 44px 触摸目标、面板上移、
    底部提示换成触屏文案；补深色主题样式
  - 🔁 `i18n:change` 时若面板开着则重建，换语言不用关掉重开

- 🎨 **顺带修顶栏按钮样式**：`nav-btn-cmd` / `nav-btn-export` 都是 `<button>`，
  各页内联的 `.topnav a {...}` 规则套不上，`nav-btn-export` 一直以浏览器默认浅灰
  外观落在深色顶栏上。样式补在 `theme.css`（而非散进 18 个内联块）。窄屏下
  `min-height: 44px`、文字标签隐藏只留图标

- 🔒 **修 `escHtml`**：V0.68 写成 `{ '&': '&', '<': '<', '>': '>', '"': '"' }` ——
  前四个映射到自身是 no-op，含 `<` 或 `&` 的标签会原样进 `innerHTML`

- 🚪 **修 `check_cluster_render.mjs` —— 这道门从 V0.99 起就一次都没真正跑过**
  - V0.99 C4 把 `silver.html` 655 行拆成 `silver.html` 332 + `silver.js` 445，
    A2 块要的 3 个函数全在 `silver.js`，门禁仍读 `silver.html` ⇒ `sliceBetween`
    找不到起始标记直接抛异常
  - 新增 `sliceFn()`（按大括号配对截取）。`sliceBetween` 的 `"\n}"` 结束标记
    **只在函数顶格写时成立**，函数一旦缩进（在 IIFE 内）就会一路吞到文件里下一个
    顶格 `}` —— 既可能让 `new Function()` 崩，也可能让 `includes()` 断言**假绿**
    （A2「加载条改由 finally 收起」原本就是这么通过的）
  - A7/A8 的 `sh` 改为 `silver.html + silver.js` 拼接：这些断言里既有查 JS 的
    也有查 CSS 色值的（`#e8f7ee` 还在 html 的 `<style>` 里），拼接的语义就是原意
    「白银这个页包含 X」，下次再拆文件不会又坏一遍
  - 「含 11 条 NAV_LINKS」断言自 V0.98 起一直失配（actual 21）。改为在循环外
    单跑的新块，断言 8 场景 + 21 导航目标 + `PM_Topnav` 导出 + 面板按钮接线
    —— 原断言读 `topnav.js` 却在 9 页循环里，跑 9 遍、失败刷 9 行
  - **结果：433 passed / 0 failed**（修之前是「启动即崩」，无从谈起通过率）

- 🚦 **补 `check_i18n_keys.py` 的扫描缺口**（加 `"cmd."` 到严格清单的前提）
  - 此前 JS 侧只扫 `i18n: "key"` 一种形态，漏掉两大类：`I18n.t('key')`
    （`headlines.js` 11 处）与 `tr('key', 'fallback')`
    —— 后者是本项目**既有约定**（V0.86 `decision-explainer.js` 首用），
    约 15 个 `decision.explain_*` + 本次的 12 个 `cmd.*` 全在门外
  - 补完后 in-scope **211 → 232**，且 **0 missing** ⇒ 这 21 个键三语本来就齐，
    纯粹是门禁看不见。已负向验证：删 zh-TW 的 `cmd.help` / `headlines.empty`
    均 `exit=1`
  - ⚠️ 这是**既存缺口**，不是本次引入 —— `headlines.*` 与 `decision.explain_*`
    在此之前一直不受门禁保护

- 🌐 **i18n**：`nav.cmd_palette` ×3 + `cmd.*` 12 键 ×3 语

## [V0.111.1] · 2026-10-21

`导航收敛` — hotfix · 无后端改动

- 🧭 **数据健康由顶级场景降为「配置」的第 3 个子页，顶 nav 9→8 项**
  （用户诉求：「把 AI 分析也和其他门类做成一样的部署，正好 8 个入口，结构也工整」）
  - 💡 **理由**：数据健康是运维诊断页，不是内容门类。降级后剩下 8 项全是真门类
  - 🏠 **首页仍是 8 张板块**：数据健康**只降 nav 层级、保留自己的首页卡**（它有
    独立摘要信息，是用户常回看的页面）。所以首页卡数（8）与顶 nav 场景数（8）
    相等却**不是一一对应** —— 数据健康有卡、但 nav 里归在「配置」下
  - 🐛 **顺带修两处导航不一致**：`topnav.js` 的 SCENES 与 `home.html` 的场景卡
    **原本顺序不同**（AI 与数据健康在两处是反的）。现在两处同序，AI 两边都排末位
  - 🩺 **数据健康页补挂 `#subnav-mount`**：它原先是独立顶级场景，不渲染二级导航
    行；降级后若不补，进本页顶 nav 只高亮「配置」却看不到自己在这组子页里的位置
    —— 与其余 13 个子页不一致。`.subnav` 样式由 `theme.css` 提供（该页已引），
    无需内联复制
  - 🌐 **i18n ×3**：配置卡补第 3 个 chip（`home.scene_config_3` = 数据健康）、
    描述补「健康」

- 🐛 **修 `_verify_report_archive.mjs` 两个自己的 bug**（不是应用错）
  - `page.click()` 在 puppeteer **默认 800×600** 视口下点不到上传按钮：顶 nav 在
    窄宽下折行撑高，其 sticky 层（z-index 100）正好盖住按钮，点击被派发给顶栏的
    `pmThemeBtn`，脚本表现为「点了没反应 / 上传超时」。1280×720 / 1352×900 实测
    正常 ⇒ 显式 `setViewport(1352×900)`
  - 首页卡数断言 8 → 7（V0.111.1 的改动本身）

## [V0.111.0] · 2026-10-21

`报告存档` — 功能 + 文档

- 📁 **首页新增「报告存档」场景：上传 HTML 报告 + 元数据登记表检索**
  （用户诉求：「首页添加一个报告上传的板块，用户可以上传 html 格式的报告，
  并提供客户查看显示，然后建立存单方便用户查看」；「存单」= 元数据登记表）
  - 🗄️ **存储**：新表 `reports`（user_id / title / stored_name / original_name /
    size_bytes / report_date / category / tags / summary），手写迁移
    `p2q3r4s5t6`。**不复用** `app_settings` KV —— 它无 `user_id`、整值替换、
    内存 TTL 缓存，结构上做不了列表
  - 🌐 **端点**：`/api/v1/reports/*` 8 个（upload / 列表 / 单条 / PATCH /
    DELETE / content / categories / stats）。⚠ `/categories` 与 `/stats`
    必须注册在 `/{report_id}` **之前** —— FastAPI 按声明顺序匹配，否则会被
    当成 `report_id` 报 422（各有一条测试锁住）
  - 🛡️ **上传校验 4 道**：扩展名 / ≤20MB / 去 BOM 后首字节必须是 `<` /
    **分块读累计**（不把伪装成 `.html` 的 500MB 整个读进内存）。入库失败回收孤儿文件
  - 🔒 **报告与主站同源 ⇒ 响应级 CSP sandbox**：
    `sandbox allow-scripts allow-popups; connect-src 'none'; form-action 'none'`
    。当前生产 `.env.prod` 没有 `AUTH_ENABLED` ⇒ 认证关闭、无 cookie、
    `user_id` 恒为 1，连 `ADMIN_TOKEN` 校验都被跳过 —— 所以真实风险不是
    「偷 session」，而是**报告里的 JS 能以你的身份调全部 `/api/v1/*` 写端点**。
    `sandbox` 不带 `allow-same-origin` ⇒ 文档进 **opaque origin**（读不到
    localStorage、够不到父页面）；`connect-src 'none'` 封死
    fetch/XHR/sendBeacon/WebSocket。**刻意不给 `default-src`** —— 那会连带禁掉
    外部 CSS/字体/图片把渲染打残
  - 🗂️ **落盘规矩**：绝不落 `static/`（SW `cache-first` + 限流豁免区，进去就
    永久回放）；用 `uuid4().hex`，原始文件名只作展示元数据、绝不参与路径拼接；
    落 `data/reports/`（systemd `ReadWritePaths` 白名单内，换别处生产会
    `Read-only file system` 而测试照过）
  - 🎨 **UI**：`/report-archive` 新页（工具条搜索/分类/标签 + 卡片列表 +
    侧栏统计 + 拖拽上传卡），卡片内联「编辑登记表」折叠区
  - 🧭 **导航**：独立顶级场景放在「情报」之后 → 顶 nav 8→9 项，首页卡 7→8 张；
    `main.py` 加 `/report-archive` 307 别名
  - 🌐 i18n 51 键 × 3 语（`reports.*` 49 + `nav.archive` + `brand.archive`）；
    `check_i18n_keys.py` 的 `V083_KEY_PREFIXES` 加 `reports.`（13→14 类）
- 🐛 **测试当场逮住一个真 bug：`_escape_like` 转义了但没接上**
  `repositories/reports.py` 把 `%` 转义成 `\%`，但每个 `.like()` 都没传
  SQLAlchemy 的 `escape=`。SQLite 默认不把反斜杠当转义符 ⇒ 搜 `100%` 一条都
  搜不到。**少传 `escape=` 比不转义更糟**：不转义是全命中（结果脏），错误
  转义是零命中（用户以为搜索坏了）。已全部补 `escape="\\"` 并写进 docstring
- 🐛 **修 `scripts/check_routes.py` 门禁假失败（SIGABRT 134）**
  `_start_in_process_server` 返回 thread 但**成功路径从不置 `should_exit`**，
  daemon uvicorn 线程在解释器收尾时仍写 stdout →
  `Fatal Python error: _enter_buffered_busy ... at interpreter shutdown`。
  多一条路由就改变时序（本改动下 4 次炸 1 次，基线 5 次不炸纯属运气）。
  改为返回 server 句柄 + `try/finally` 优雅停机，修后连跑 6 次 exit=0
- ✅ 37 条新测试 `tests/test_api/test_reports.py`；7 个 commit（C1 后端地基 →
  C2 服务层 → C3 端点 → C4 前端 → C5 导航/别名/门禁修复 → C6 sw.js → C7 发版）

## [V0.110.0] · 2026-10-21

`宏观因子手动校准 + docs 整理` — 功能 + 文档

- 🎯 **核心评估参数可由用户手动更新**（用户诉求：「有些核心评估参数更新不及时」）
  - 根因：`dxy` / `vix` **无自动实时源**，用 `STATIC_REF` 里 **2026-08-28** 的硬编码常量
    （96.5 / 18.5）。两者在宏观面内部合计权重 0.40，宏观面占综合指数 0.40
    → **综合指数的 16% 建立在两个半月前的常量上**，UI 上完全看不出来
  - ✏️ **存储**：`app_settings` 新增独立 key `macro_factor_overrides`
    （5 因子 × 值 / 数据日期 / 备注）；复用 `WeightService` 已有的 `SettingRepository`
  - 🔁 **优先级链**：用户手动覆盖 > 自动源（央行购金表 / 美联储 H.15）> 内置常量
  - 🌐 **端点**：`GET/PUT /api/v1/settings/macro-overrides`（PUT 需 admin session）
  - 🎨 **UI**：`/weights` 页新增「宏观因子手动校准」卡片 —— 5 行同屏显示
    「当前生效值 + 数据日期 + 来源标记」，复用已有的 `gold/trend` 响应不新增请求；
    滞后 > 1 交易日显示琥珀 chip；「清除全部覆盖」走二次确认弹窗
  - 🕐 **保存即失效两层缓存**：`MacroFactorService._CACHE`（10min）+ `served_cache`
    （10min，在前者之上）。只清前者时 `/market/gold/trend` 会从 served_cache 回放
    覆盖前的响应 —— 提示"已保存"而数值纹丝不动
  - 🌐 i18n 23 key × 3 语（zh-CN / en-US / zh-TW）
- 🐛 **验证期实跑修掉 4 个缺陷**（`scripts/_verify_macro_override.mjs` 15 项断言暴露）
  - **`served_cache` 漏清 —— 功能等于没做**：上面那条的实测形态。顺带修掉
    `PUT /settings/weights` 的**既有缺陷**（原先一个缓存都不清，改完权重后首页
    最长 10 分钟仍显示旧指数）。新增 `TrendService.invalidate_cached_results()`，
    `invalidate_for_news` 改为转发别名并说明三条调用路径；两条回归锁均验证过
    「去掉修复即 FAIL」
  - **`renderOverrides()` 冲掉用户正在输入的值**：整块 innerHTML 替换 + 首屏
    `loadOverrides()` 与 `loadTrendForPreview()` 并发（冷启动数秒）→ 静默提交全 null，
    表现为"我明明填了却没生效"且一次覆盖被全清。改为重渲染前 `snapshotUserEdits()`
    快照、渲染后写回
  - **备注输入框漏 `class="mo-note"`**：`.mo-row .mo-note` 整条 CSS 失效，
    字段退回默认宽度 → 「清除」按钮被挤到第二行，5 行全折
  - **冷启动显示「暂无读数」**：会被读成"因子丢了"；新增 `macroFactorState`
    （loading/ready/failed），加载期间显示中性「加载中…」
  - 🧹 重命名 `TrendService.invalidate_for_news` → `invalidate_cached_results`
    （名字带 news，但两条写入路径都调它，不改名会说谎；原名保留为转发别名）
- 🐛 **用户实测 hotfix —— 「保存失败：Not Found」**（部署滞后，非功能 bug）
  - 根因：`static/*.html` 由 `StaticFiles` **直接读磁盘**（改完即生效），而 Python
    路由**冻结在进程内存**（必须重启）。`8888` 的 root 进程 10月18日 启动、
    跑着旧代码，页面却已是新版 —— 页面有卡片、后端无端点，保存必然 404
  - **降级本身才是 bug**：首屏 `loadOverrides()` 404 画出的「加载失败」，被紧随其后
    成功的 `loadTrendForPreview() → renderOverrides()` **整个抹掉**，换成 5 行看起来
    完全正常的表单 —— 真实失败被一次后续的成功渲染吃掉了
  - 修：`overrideApiMissing` 置位后只画琥珀色说明块、不画表单、藏起表头与
    保存/清除按钮；`fetchOverrideApi()` 按 status 给可行动文案（404/403/422/5xx/网络），
    不再把裸 `Not Found` 抛给用户；i18n 8 key × 3 语
  - `.mo-ops` / `.mo-head` 的 `display:flex` 会盖掉 `[hidden]`，必须显式写
    `[hidden] { display:none }`；断言里加 `getComputedStyle` 检查防骗
  - 验证：`_verify_mo_degraded.mjs` 9 passed（跑在**真实旧后端** 8888 上，不 mock）
- 📚 **docs 整理**
  - 🐛 **死链门禁当时是红的**（12 条失效链接）：2 条指向已删除的 `application-guide.md`、
    3 条指向仓库外的 `.claude/.../memory/*.md`、1 条相对路径写错、
    5 条 `v0.87.0.md` 里带捕获组的 regex 被 `LINK_RE` 当成链接 —— 全部修掉
  - 🚦 **新增门禁**：`check_links.py` 增加 release notes 索引完整性检查
    （目录里有 `v*.md`、索引里没入口 ⇒ 报红）。此前 `releases/index.md` 停在
    V0.100.2，9 份 release notes 无人索引且无任何门禁报红；实际漏登记 **13** 份，已全部补齐
  - 🆕 **新建 `docs/README.md`**：按「我要做什么」导航 + 目录结构与三条边界 +
    文档门禁矩阵 + 三条踩过的坑；README 顶部补入口
  - 📈 **`roadmap.md` 补 9 个版本**：§1 里程碑表在 V0.100.0 后断了 V0.102–V0.109.2；
    §2 从「V0.101 迁移收口 in progress」（早已完成）改写为
    V0.110.0 已落 + V0.111.0 阈值可覆盖 + K 项多市场独立校准
  - 🏷️ 3 份规划文档补 `状态：` 抬头（`roadmap.md` / `improvement-path.md` / `ux-roadmap.md`）
  - 📑 `releases/index.md` 新增 §1.4.1「今日要闻」逐版本登记表
- ✅ **测试**：+21（API 7 / 宏观服务 7 / 设置服务 4 / 门禁 3）；相关回归 **157 passed**；
  UI 实跑 `_verify_macro_override.mjs` **15 passed / 0 failed**

---

## [V0.109.2] · 2026-10-20

`白银页面数据时效透明化（SGE akshare 数据滞后 2 天暴露）` — 接口透明化 hotfix

- 🐛 **白银 `/silver/sge-quote` 数据「缓存 2 天」伪象根因**
  - `ak.spot_silver_benchmark_sge()` 在生产常见滞后 2-3 个工作日
    （实测 2026-10-20 周二时接口最新数据停在 10-18 周日）
  - 原仓储 `get_silver_sge_quote()` 用历史 K 线末根日期当 `updated_at` + 没告诉前端
    → 用户反复刷新拿同一日数据 → 误以为「缓存 2 天」
  - cache TTL 不是问题（默认 300s = 5min 是合理的）
- ✅ **加 `data_as_of` 字段**到 4 个白银 quote schema（Silver/Etf/Gram/Sge）
  - 字段语义 = 数据真实所属交易日
  - 与 `updated_at` 分离，前端可独立判断 staleness
  - 向后兼容（`None` 默认，老客户端不报错）
- 🔍 **后端 staleness 检测**：`trading_days_between(last_date, today) > 1` → `_mark(ok=False)`
  - 阈值 1 工作日的直觉：Sun→Mon（跨周末挡路）不算 stale；Sun→Tue 算 stale
  - stale 时 source-bar 把 `sge_silver` 标 mock
- 🎨 **前端数据日期显示 + 滞后 chip**：3 个白银卡片下方显示「数据日期 YYYY-MM-DD」
  - 跨日 > 1 日历天时显示琥珀色「⚠ 数据滞后 N 天」chip
  - 复用 `fsh-chip fsh-warn fsh-stale-chip` 样式（freshness.js 已有）
  - `renderSourceBar()` 增强：尾部追加「⚠ 时效滞后: 〈源〉数据至 〈date〉（滞后 N 天）」
- 🛠️ **`utils.market_clock.trading_days_between()`** 简化版工作日数（周一至周五 5×24h）
- 🚫 **不引入新数据源**：akshare 滞后是上游问题；加代理源风险大、收益小
- ✅ **stale 时仍走真数据路径**（不切 mock）：让用户看到真实价 + 滞告提示；假数据会误导

测试增量：+10 全绿（market_clock trading_days_between 7 例 + market API data_as_of 3 例）

## [V0.109.1] · 2026-10-20

`分类架构改为「内容优先、站名兜底」` — 修正 V0.108.0「站名压过内容」的设计失误

- 🐛 **站名压过内容（V0.108.0 设计失误）**
  - V0.108.0 把 33 个优质站名写进内容关键词词典，站名与标题摘要同池、且财经优先级最高 → 站名成了最高优先级信号
  - 实测生产 DB 576 条：**160 条（27.8%）纯靠站名定类**，样例全是与财经无关的通讯社国际新闻
    - `印度东部踩踏致 17 人死亡` → 财经（财联社）
    - `伊拉克首都一弹药仓库发生爆炸` → 财经（财联社）
    - `法国多地大规模抗议 数百人被捕` → 财经（第一财经）
    - `胡塞武装发言人：沙特战斗机对萨那发动袭击` → 财经（格隆汇）
  - 即 V0.108.0 那个「财经 226 条」的漂亮数字主要是假象
- 🔍 **另一条实测推翻 V0.108.0 立论前提**：那 182 条纯站名定类的条目里**没有一条内容字段为空** —— 「白名单为了救空摘要好新闻」在生产数据上不成立，收益全来自科技垂直站
- ✅ **改为两段式**：内容优先（title+summary，财经>科技>创投>商业）→ 站名兜底 → 落「其他」弃入
- 🎯 **站名兜底只对垂直媒体开放**，分界是「垂直媒体 vs 综合通讯社」而非「财经 vs 科技」
  - 兜底：财经垂直（金十数据/同花顺/金融界/证券报/证券时报/每经）+ 科技垂直（techradar/9to5Mac/IT 之家/快科技 等 17 站）+ 创投垂直（36Kr/创业邦/投资界 等）
  - 排除：财联社/格隆汇/第一财经/界面新闻/经济观察报/华尔街见闻 —— 实测它们 14-35 条内容未命中条目里大量是战事灾难；发纯市场内容时仍会被内容词典命中
  - 最长匹配优先（`C114 通信网` / `IT之家` 带后缀）
- 🗑️ **33 个站名移出内容词典**（含 V0.105 起的财联社/华尔街见闻/格隆汇/金十数据）；指数名 `中证/上证/深证/创业板/科创板/沪指/深成指` 不是站名，保留
- 📊 **实测新分布**：科技 248 / 财经 58 / 商业 27 / 创投 5，入流 338，弃入 114，另 124 条黑名单站点不入流
  - 国际**财经**保留：韩国财长谈半导体景气 / 欧央行利率决议 / OPEC+ 减产
  - 国际**战事灾难**丢弃：印度踩踏 / 伊拉克爆炸 / 法国抗议 / 胡塞武装
- ✅ **测试 +7 例**（分类器 51 → 58），全量 115 passed
  - 修正 2 例编码了旧行为的断言（`test_classify_empty_title_uses_site_name` 原用华尔街见闻、`test_classify_whitelist_finance_site_v01080` 原断言 10 站全兜底）
- 🛠️ **新增 `scripts/reclassify_v01090.py`**：全量 sweep，**默认 dry-run**，`--apply` 才写库，`--drop-blocklisted` 连带清理新浪科技 122 + maomu.com 2 条存量；自动重建受影响日期的 `news_feed_daily`
  - 与 `reclassify_v01071.py` 区别：后者只扫 `category='其他'` 的行，修不了「被误判成财经的 28 条科技新闻」
- ⚠️ **已知精度问题**：`基金` 命中「老年基金会」、`经济` 命中村镇治理 —— rule-based 上限，需上下文消歧

## [V0.109.0] · 2026-10-20

`分类词边界修复 + 发布词精度` — PE ⊂ Europe 子串误匹配 + 中文裸词「发布」过泛

- 🐛 **`PE` 命中 `Europe` / `OpenAI`（财经优先级最高，误判代价最大）**
  - `"pe" in "europe"` 为真 → 所有提到欧洲 / OpenAI 的新闻都被判成财经
  - 实测生产 DB 576 条：**28 条科技新闻被误判成财经**（4.9%），含 Oppo / Claude / OpenCode / AWS / iPhone / Sony / Windows / 谷歌开源
  - 修法：长度 ≤3 的纯 ASCII 词（37 个）改走词边界正则 `(?<![a-z])KW(?![a-z])`，长英文词与全部中文词仍走子串
  - 边界定义「字母才算邻居」保证正常用法不受影响：`2026PE`、`科创50ETF`、`pe(ttm)` 照常命中
  - 复合词显式补齐 `AIGC` / `AGI` / `GPU云`（否则 `AIGC` 里的 `AI` 会被边界拒掉）
  - 同类一并修：`ETH ⊂ Ethiopia`、`GP ⊂ GPT`、`AI ⊂ Retail/Chain/Mail`
- 🐛 **中文裸词「发布」过泛**（V0.108.0 release notes 记录的已知问题 1）
  - 会把「警方发布彩叶观赏季安全提示」「中央档案馆集中开放」「俄乌战事通报」判成商业
  - 裸词换成 `发布会` + `发布公告`；实测移除裸词后失去唯一商业依据的恰好就是那 4 条噪声，7 条真发布会新闻全部保留
- 📊 **全量对拍**：生产 DB 576 条，30 条分类变化（5.2%）：财经→科技 28 / 科技→其他 1 / 财经→其他 1，**无一条改错方向**
- ✅ **测试 +9 例**（分类器 41 → 51），全量 108 passed
  - 含双向回归：`test_pe_no_longer_matches_europe`（核心）+ `test_pe_still_matches_standalone`（防修过头）
- ⚠️ **遗留**：历史 576 条仍带旧分类，`scripts/reclassify_v01071.py` 只扫「其他」行、不覆盖本次场景，需全量 sweep（留 V0.109.1）

## [V0.108.0] · 2026-10-20

`今日要闻站点黑白名单 + 财经二次加强` — 站点维度质量治理 + 财经词 67→100+

- 🔻 **fetcher 站点黑名单**（用户方案 B 负向腿）`SITE_BLOCKLIST`
  - 只收 2 个源：`新浪科技`（30 天 26 条里约 4 条地方新闻/文艺活动，ETF 有效内容仅 1 条）、`maomu.com`（加密 spam）
  - 收录纪律（写进代码注释防凭印象扩大）：样本量 ≥10 + 无关比例 ≥60% + 非优质源转载
  - `_normalize` 在 `classify()` **之前**拦 —— 聚合源即使单条能分类（ETF 题材）也不进 4 类流
  - 刻意**不**拉黑 `澎湃新闻`（实测 3 条全优质，初版误列已撤）/ `techradar` / `9to5Mac`
- 🔺 **白名单站点名写入关键词词典**（方案 B 正向腿，复用 classify 通路零新增逻辑）
  - 财经 +9 / 科技 +16 / 创投 +7 = 33 个优质源站名
  - 价值：readhub 财经源常给空摘要，站名即最可靠的类目信号，不再被误判「其他」
  - `IT 之家`/`IT之家`、`IT桔子`/`IT 桔子` 两种空格写法都收
- 📈 **财经二次加强 67 → 100+ 词**（对齐黄金 ETF 分析器的品种与政策变量）
  - 大宗：白银 现货 期权 套期保值 原油 铁矿石 螺纹钢 焦炭 铜价 金价 银价 离岸人民币 人民币中间价 外汇储备 跨境支付 结售汇
  - 监管：证监会 银保监会 金融监管总局 国资委 财政部 发改委 国常会 政治局会议 两会
  - 国际央行：欧央行 ECB 日银 BoJ 英国央行 IMF 世界银行 G7 G20 WTO OPEC
  - 银行险资：六大行 兴业 汇丰 渣打 平安 保监会 险资
  - 人物：潘功胜 周小川 易纲 郭树清 拉加德
- 🛡️ **service gate 复用**：`refresh()` 的既有 tuple 过滤加 `site_name ∉ SITE_BLOCKLIST`，与 category gate 共用一段逻辑不新增分支
- ✅ **测试 +25 例**：分类器 41 / fetcher 28 / service 5 全绿
  - 去重用例当场抓到本次引入的「金十数据」重复（V0.105 已在原 32 词里），已删
  - 修 1 例 V0.107.1 用例站名冲突（「创业邦」进白名单后抢走商业关键词用例的分类，改用中性站名「企业内参」）
- 📊 **只读实测**：真实 readhub 20 raw → 13 normalized，财经占比 52.9% → **61.5%**（+8.6pp），耗时 1250ms
- ⚠️ **已知问题（留 V0.109）**：`_BIZ_KW` 的「发布」过泛，会把战事新闻判成商业（关键词精度问题，非站点问题）；`test_list_items_filter_days` 的日期轮转失败经 `git stash` 验证为 pre-existing

## [V0.107.1] · 2026-10-20

`今日要闻分类聚焦（财经 32→60+ / 科技 33→50+ / 创投 23→35+ / 商业 22→30+）+ fetcher 弃入「其他」+ page_size 50 + service 二次 gate` — 4 commit hotfix

### Added

- ✨ **关键词字典焦点化扩充**（`src/app/repositories/news_classifier.py`）
  - **财经** 32 → 67：新增「行情」（牛市 / K线 / 黄金ETF / PE）、「主体」（比特币 / ETH / 离岸 / 外汇 / 储备）、「宏观」（衰退 / 通缩 / 缩表）、「人物」（鲍威尔 / 耶伦 / 巴菲特 / 芒格）、「机构」（贝莱德 / 桥水 / 高盛 / 中金 / 中信 / 瑞银 / 摩根士丹利）— 用户原话「主要聚焦于财经方面的新闻」重点扩充
  - **科技** 33 → 49：删「英伟达」duplicate（修旧版 L44 bug）+ 硬件公司（比亚迪 / 特斯拉 / SpaceX / 台积电 / 中芯国际 / 宁德时代 / 三星 / 英特尔 / AMD / 高通 / 联发科 / Meta / 亚马逊 / Oracle / IBM）+ 前沿（机器人 / 无人机 / 储能 / 自动驾驶 / 脑机接口 / 可穿戴）+ 节点（3nm / 5nm / 7nm / 5 纳米 / 7 纳米）
  - **创投** 23 → 36：行为（风投 / 退出 / 并购 / M&A / FA / 财顾 / 路演 / BP / 商业计划书）+ 身份（创始人 / 联创 / 合伙人 / GP / LP）+ 事件（增发 / 配股 / 可转债 / 债转股 / 借壳 / 回购 / 对赌）
  - **商业** 22 → 32：扩张（出海 / 跨境 / 国际化 / 海外）+ 渠道（电商 / 直播带货 / 抖音 / 微信 / 品牌）+ 经营（份额 / 用户 / 流量 / 增长 / 净利润 / 扭亏 / 亏损 / 增亏 / 渗透率）
  - 优先级保留 `财经 > 科技 > 创投 > 商业 > 其他` 不变

### Changed

- 🔧 **fetcher 弃入「其他」**（`src/app/repositories/readhub_fetcher.py` L130-146）
  - `_normalize()` 末尾加 `if category == "其他": return None` —— 不写入 DB，落 `logger.debug`
- 🔧 **page_size 20 → 50**（同上 L62）
  - readhub max 100，实测 50 P99 <2s，4h 周期足够覆盖
  - fetcher 文档 + User-Agent V0.102 → V0.107.1 同步
- 🔧 **service 二次 gate**（`src/app/services/news_feed.py` L96-126）
  - `refresh()` 在 fetcher 返回 records 后再 `tuple(...)` filter `category in (财经/科技/创投/商业)`
  - 全被弃入 → 软失败 `ok=False + error='no valid items after category filter'`，保留「保留末次」 UX（参考 V0.84 状态条合并模式）
  - 落入条目打印 `logger.info dropped N`

### Fixed

- 🐛 **`_TECH_KW` 重复「英伟达」bug**（V0.105 旧版 L44 末尾）—— 字典去重

### Discipline

- **测试覆盖**：3 测试文件 + 1 新增文件（test_news_classifier 10→30 / test_readhub_fetcher 16→18 / test_news_feed_service 新建 3 / test_news_feed API +2 / 仓储 test_news_feed 24 不变）；40 测试 PASSED（1 pre-existing failure `test_list_items_filter_days` 由 seed 日期漂移导致，与 V0.107.1 无关，不阻塞发版）
- **维护线覆盖率**：本次仅修改 backend + tests，UI / API schema 不变；`check_pwa_assets.py` sw.js VERSION bump 必跑门禁已通过
- **不在 5 类 list 中间移除「其他」常量**（CATEGORIES 5 类保持兼容；新写入 daily `other_count = 0`）

### Why hotfix 不开 docs 单条

V0.107.1 是 V0.107.0 release 后的数据质量 hotfix（关键词字典 + fetcher 弃入「其他」），无新功能模块；纳入 V0.107 综合 release notes 统一记录，并在 `docs/releases/v0.107.1.md` 留独立 summary。

---

---

## [V0.107.0] · 2026-10-19

`今日要闻 按天聚合 + 刷新 UX 改进` — news_feed_daily 物化宽表 + alembic 双 head 合并 + 刷新 toast

- 🆕 **news_feed_daily 物化宽表**（migration `n1o2p3q4r5`，双 head 合并 + 新表合一）
  - 1 日 1 行（date 主键，仿 scoring_daily_wide · date-as-PK · 无 user_id）
  - 5 类目计数：finance / tech / vc / biz / other
  - unique_sites_count / en_count / zh_count
  - first_publish_at / last_publish_at（UTC，nullable 当日空）
  - last_refresh_at（最近一次 refresh 重建本行时间，UTC）
  - 共 15 列
- 🆕 **2 端点**：
  - `GET /api/v1/news-feed/daily?date=YYYY-MM-DD` —— 单日聚合，无则 null
  - `GET /api/v1/news-feed/daily/list?start=&end=` —— [start, end] 闭区间 + 倒序，最多 90 天
- 🆕 **仓储 4 方法**：`upsert_daily` / `get_daily` / `list_daily` / `backfill_daily`
  - BJT 边界：`datetime.combine(target_date, time.min, tzinfo=BJT)` → SQLAlchemy 自动转 UTC
  - 单条 SQL 聚合 5 类目 + 独立站点 + 中英文 + 首末时间（9 列单行 GROUP BY）
  - 当日为空 → 不创建空行（保留「DB 反映实际数据」原则）
- 🆕 **scheduler 集成**：refresh 末尾**始终**重建 BJT today + BJT yesterday 2 行（self-healing 跨午夜场景）
- 🆕 **启动 lifespan backfill**：`_backfill_news_feed_daily(30 天)` spawn_background（仿 _backfill_news_categories 模式）
- 🆕 **前端 daily 摘要**：
  - `/headlines` 顶 daily-summary 横条（5 类目 pill + 总数 pill，仿 status-row 风格）
  - `/home` 标题下方 daily 一行（同类目 5 + total）
  - `Promise.all +1 daily 端点`，O(1) 行替代实时 GROUP BY
- 🆕 **刷新 UX 改进**：
  - 刷新 success 路径加 toast（之前仅 fail 弹）
    - upserted > 0 → 「刷新成功，新增 N 条」（success 绿）
    - upserted = 0 → 「已是最新，0 条新增」（info 蓝）
  - 刷新按钮 tooltip 改写：「从 readhub 立即拉取最新」
- 🐛 **PMToast → PM_Toast typo 修**（4 文件 11 处，fav toast 之前**静默 dead**）
  - `static/headlines.js` 3 处
  - `static/home.js` 4 处
  - `static/favorites.js` 2 处
  - `static/home.js` 1 处（重复 fav handler）
  - **影响**：fav 收藏成功 / 失败 toast 之前从不见到 —— 因 PMToast 拼错 → undefined.show() TypeError → 静默吞
- 🔧 **alembic 双 head 合并**：`n0a1b2c3d4 (V0.103 收藏) + n0o1p2q3r4 (V0.105 类目) → n1o2p3q4r5 (V0.107 daily)`
  - `down_revision = (n0a1b2c3d4, n0o1p2q3r4)` tuple 自动合并
  - 之后是单一 head（V0.108+ 不再有多 head 状态）
- 🔧 **i18n stale 修**（V0.106 漏改）：`headlines.subtitle` 「每 6 小时」→「每 4 小时」3 语统一
- 端点 17 → 18（+2 daily，-0 移除），仓储 16 → 20 测试
- 静态 JS 49 个全部通过（check_static_js.py）

[详情](docs/releases/v0.107.0.md)

>
> 能力 × 版本对照（"哪个能力在哪个版本落地"）见 [docs/releases/index.md](docs/releases/index.md)

本项目遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/) 与 [Conventional Commits](https://www.conventionalcommits.org/zh-hans/) 规范。

---

## [V0.106.2] · 2026-10-19

`16 静态文件去掉 8888 硬编码（API_BASE 全改同源相对 URL）` — 1 commit hotfix

### Fixed

- 🐛 **/headlines 选日期新闻「加载失败 · Failed to fetch」** —— 16 个静态文件硬编码了 `location.port === "8888" ? "" : "http://127.0.0.1:8888"`，导致 V0.106.1 验证用的 8890 uvicorn 时 JS 全部指向 8888 → **CORS 拦截**（8890 origin fetch 8888 origin），fetch 直接 rejected

  - 表现 1：home 底部 5 条新闻列表为空（home.js fetch 失败被 Promise.allSettled 吞掉）
  - 表现 2：/headlines 选日期显示「⚠️ 加载失败 · Failed to fetch」
  - 表现 3：所有 9 个数据子页（central_bank / weights / trend / news / backtest / review / data-health / silver / favorites）的 API 请求都走错实例

### Changed

- 🔧 **API_BASE 同源统一**（整合 16 个文件的重复 pattern）

  | 文件 | 旧 | 新 |
  |---|---|---|
  | static/headlines.js | `port==="8888"?"":"http://127.0.0.1:8888"` | `""` |
  | static/silver.js | 同 | `""` |
  | static/freshness.js | 同 | `""` |
  | static/resonance-card.js | 同（×2）| `""` |
  | static/synthesis-card.js | 同 | `""` |
  | static/health-summary.js | `port==="8888"‖"8889"?"":"..."` | `""` |
  | static/news-score-widget.js | `ABS_BASE='http://127.0.0.1:8888'` | `""` + 删除 ABS_BASE 概念 |
  | static/favorites.js | 同 | `""` |
  | static/weights.html | 同 | `""` |
  | static/central_bank.html | 同（×2）| `""` |
  | static/trend.html | 同 | `""` |
  | static/news.html | `protocol检测?"":"..."` | `""` |
  | static/backtest.html | 同 | `""` |
  | static/data-health.html | `port==="8888"‖"8889"?"":"..."` | `""` |
  | static/review.html | `protocol检测?"":"..."` | `""` |

- 🗑️ **删除冗余的 ABS_BASE 概念**（news-score-widget.js 独有）
- 📝 **3 处错误提示文案**改用 `location.origin`（central_bank / trend / trades）—— 用户能看到自己实际访问的 origin，不再被强制看到 8888

### Discipline

- 📐 4 处版本同步：__version__ 0.106.1→0.106.2 / pyproject.toml 同 / sw.js v0.106.1→v0.106.2 / uv.lock 同步
- 🧪 4 门禁：pwa_assets ✓ / i18n_keys ✓（0 missing / 179 in-scope）/ static_js ✓ / routes ✓（18 路由 OK）
- 🐛 **Puppeteer 验证**：fix 后 /headlines 初始 2 day group + 选 2026-10-19 显示 36Kr 00:59 文章（fix 前是 empty-state warn）

### Why hotfix 不开 docs

V0.106.2 是 V0.106.1 release 当天的 CORS 拦截修复，非新功能。`docs/releases/` 暂不新增条目，纳入 V0.107 综合 release notes 统一记录。

---

## [V0.106.1] · 2026-10-19

`home 场景卡同步 topnav 8 scene（hotfix · 不发 docs）` — 1 commit

### Changed

- 🏠 **home.html 场景卡 5 → 7 张**（与顶 nav 8 scene 对齐：topnav 8 个 scene 去掉「home」自身）

  - 📢 新增 `scene-headlines` 今日要闻卡（顶 nav 顺序第 2 位）
  - 🩺 新增 `scene-health` 数据健康卡（顶 nav 顺序第 8 位）
  - 📐 重排顺序：今日要闻 → 决策 → 持仓 → 情报 → 配置 → 数据健康 → AI（AI 全宽）
  - 🧹 整合 3 张旧卡的 sub-items 与顶 nav subpages：
    - 决策：3 项 → 4 项（+研判复盘；今日评分→打分汇总）
    - 持仓：3 项 → 2 项（-复盘报告：复盘已归入决策 subpage）
    - 情报：4 项错位 → 4 项对齐（消息面评估 / 央行购金 / 白银追踪 / 我的收藏）
  - 📝 desc 文案同步：决策「趋势 · 打分 · 回测 · 复盘」、持仓「决策 · 流水」、情报「新闻 · 央行 · 白银 · 收藏」

### Discipline

- 📐 **改 static 立即 bump SW**（V0.100.1 教训）：`__version__` 0.106.0 → 0.106.1 + sw.js VERSION v0.106.0 → v0.106.1 + 4 处版本同步
- 🌐 3 语 i18n 同步：zh-CN / en-US / zh-TW 增 11 key + 改 6 key
- 🧪 4 门禁：pwa_assets ✓ / i18n_keys ✓（0 missing / 179 in-scope）/ static_js ✓ / routes ✓（18 路由 OK）

### Why hotfix 不开 docs

V0.106.1 是 V0.106.0 release 当天的 home 页面布局补全（顶 nav 8 scene → home 卡片同步），非新功能。`docs/releases/` 暂不新增条目，纳入 V0.107 综合 release notes 统一记录。

---

## [V0.106.0] · 2026-10-19

`今日要闻顶 nav 提级 + scheduler 6h→4h 加密` — 2 commit

### Added

- 📢 **「今日要闻」提级为顶 nav 第 2 位** —— 用户原话「当前今日要闻页面连接 提升到 导航栏 首页之后 决策之前」

  - 🖥️ `static/topnav.js` `SCENES` 数组 7 → 8 顶 scene
  - 🆕 新增 `key:"headlines"` 顶级场景：`/headlines` 入口、`ico:"📢"`、无 sub-tabs（独立页）
  - 📐 顶 nav 顺序：首页(🏠) → 今日要闻(📢) → 决策(📊) → 持仓(💼) → 情报(📰) → 配置(⚙️) → AI(🤖) → 数据健康(🩺)
  - 🗑️ 「情报」scene 子页 5 → 4（移除今日要闻）：消息面评估 / 央行购金 / 白银追踪 / 我的收藏
  - 📐 独立顶项 3 → 4（首页 / 今日要闻 / AI / 健康）
  - 📝 注释同步更新（V0.98 7-scene 描述 → V0.106 8-scene 描述）

### Changed

- ⏰ **今日要闻 scheduler 6h → 4h 加密** —— 用户原话「更新策略也没有实现，修改成每四小更新一次财经新闻」

  - 🔧 `src/app/services/scheduler.py` `NEWS_FEED_INTERVAL_HOURS` 6 → 4
  - 📐 触发时刻（UTC）：00/06/12/18 (4点/日) → 00/04/08/12/16/20 (6点/日)
  - 📐 触发时刻（BJT ≈）：08/14/20/02 → 08/12/16/20/00/04
  - ♻️ `next_news_feed_run_utc()` 改用 `tuple(range(0, 24, NEWS_FEED_INTERVAL_HOURS))` 自动算小时列表（日志 hours_label 同步动态生成）
  - ♻️ `news_feed_loop()` 日志格式从硬编码 `00/06/12/18` 改为 `hours_label` 动态（将来改间隔只需改 1 个常量）

### Discipline

- 📐 **4 处版本同步**（V0.100.1 教训）：`__version__` / `pyproject.toml` / `sw.js VERSION` 同步 bump `v0.106.0`；`uv.lock` 同步 lockfile
- 📐 **改 static 立即 bump SW**（V0.100.1）：C1 bump `v0.105.0 → v0.105.1`（topnav.js 改动），C2 release bump `v0.105.1 → v0.106.0`
- 🧪 8 个新 scheduler 单测（4h 节奏 6 触发点全覆盖 + 跨日 + 默认 now_utc）

---

## [V0.105.0] · 2026-10-19

`headlines 分类筛选（5 类 + 多 switch）` — 5 commit

### Added

- 🏷️ **headlines 类目筛选** —— 用户原话「主要聚焦页面财经内容」（"主要 聚焦页面财经内容"）

  - 🗄️ `news_feed_items` 表加 `category` 列（V0.105 n0o1p2q3r4，down_revision=m9g0a1b2c3 V0.102）；`String(16) NULL` + 单列索引（5 类 cardinality 仍走 B-tree）
  - 🤖 关键词分类器 `app/repositories/news_classifier.py`（rule-based 5 类：财经/科技/创投/商业/其他；优先级 财经 > 科技 > 创投 > 商业 > 其他；准确率 ~70-80% 是 rule-based 上限，V0.106+ 再升级 LLM）
  - 🛠️ `NewsFeedRepository`：`upsert_bulk` set_ 加 `category=stmt.excluded.category`（关键：防历史行永远 NULL）+ `list_items` 加 `category` filter（与 date/days/site_name/language **正交叠加**）+ 新增 `list_categories()`（distinct + 频次降序）+ `backfill_categories(batch_size=500)` 启动时一次性补齐 ~64378 行
  - 🌐 `readhub_fetcher._normalize()` 入库即调 `classify()` 填入 category；新条目不会留 NULL
  - ⏰ `main.py` lifespan `_backfill_news_categories()`（`spawn_background` 异步，6-10s 完成；启动过渡期少数 NULL 不阻塞）
  - 🔌 `GET /api/v1/news-feed/items` 新增 `category` query param（max_length=16）；新端点 `GET /api/v1/news-feed/categories`（DB distinct + 频次降序）
  - 🏷️ `NewsFeedItemOut` schema 加 `category: str | None` 字段（V0.78.0 NULL 纪律：未分类则 None）
  - 🖥️ `headlines.html` 工具栏新增 `<select id="categorySel">`（5 控件后，第 5 位）
  - 🖥️ `headlines.js` `currentCategory` state + `renderCategoryOptions()`（合并「DB 频次降序 + 固定 5 类兜底」并去重，5 类一定可选；i18n key `headlines.cat_{finance|tech|vc|business|other}`）+ bindToolbar change handler
  - 🌐 i18n +6 keys × 3 语 = 18 条翻译：`headlines.filter_category` / `cat_finance` / `cat_tech` / `cat_vc` / `cat_business` / `cat_other`
  - 🧪 分类器 9 例 + 仓储 7 例（filter / 联 site / 联 date / 联 days / distinct / backfill / 幂等 / upsert 更新）+ API 6 例（filter / 422 / 联 date / 联 days / /categories / 字段回归）+ puppeteer 8 状态验收（`scripts/_verify_category_filter.mjs`）

### Discipline

- 📐 **4 处版本同步**（V0.100.1 教训）：`__version__` / `pyproject.toml` / `sw.js VERSION` 同步 bump `v0.105.0`；`uv.lock` 同步 lockfile
- 📐 **改 static 立即 bump SW**（V0.100.1）：C4 bump `v0.104.0 → v0.104.1`（中间版本），C5 release bump `v0.104.1 → v0.105.0`（最终版本）
- 📐 **5 commit 顺序**：feat(repo) → feat(api) → test → feat(static) → chore(release)（沿用 V0.100/V0.103/V0.104 模式）
- 📐 **正交叠加**：`category` 与 V0.104 `date` / V0.102 `days` / V0.102 `site_name` / V0.102 `language` 完全正交，切换 category 不清其他 state
- 📐 **卡片不显类目 badge**（设计取舍）：让分类纯粹是筛选轴，不污染卡片视觉；用户没要求就不加

---

## [V0.104.0] · 2026-10-19

`headlines 按日期分页（单日模式 + 日期导航）` — 4 commit / 1 hotfix

### Added

- 📅 **headlines 单日模式 + 日期导航** —— 用户原话「我们在 headlines 添加按照新闻日期的分页功能」
  - 🔌 `GET /api/v1/news-feed/items` 新增 2 个 query param：`date`（YYYY-MM-DD）+ `tz_offset_minutes`（带符号，BJT = +480）；与现有 `days` 互斥
  - 🏷️ `NewsFeedListOut` 新增 3 字段：`current_date`（回显的 date）/ `has_older`（前一天是否有新闻）/ `has_newer`（后一天是否有新闻）
  - 🗄️ `NewsFeedRepository.list_items` 新增 `date` + `tz_offset_minutes` 参数；新增 `has_items_outside_day()` 2 个 EXISTS 查询（无 COUNT，走索引）
  - 🖥️ `headlines.html` 工具栏新增 `#dateNav`：◀ / `<input type="date">` / ▶ / 回到今日（4 控件 + 13 行 CSS）
  - 🖥️ `headlines.js` `enterDateMode()` + `refreshDateNav()`：currentDate state + 单日/范围模式互斥 + 翻页按钮 disabled
  - 🌐 i18n +3 keys × 3 语 = 9 条翻译：`headlines.btn_today` / `.btn_prev_day_title` / `.btn_next_day_title`
  - 🧪 仓储 4 例 + API 6 例 + puppeteer 4 状态验收（`scripts/_verify_date_nav.mjs`）

### Fixed

- 🐛 `refreshDateNav()` 同步 `btnToday.hidden`（修复 loadAll 失败时回到今日按钮状态不重置的 UX bug）— **C4 修**

### Discipline

- `total` 字段语义保留 `len(items)`，不升级为「匹配总数」；与现有 6 个测试一致
- 现有 `days` 模式 SQL 与 V0.103 byte-identical（`date=None` 时不进入 date 分支），0 字段破坏
- 时区偏移符号约定：JS `getTimezoneOffset()` 返回 WEST，反转后东八区 = +480；2 个测试用例固化
- 改 static HTML/JS → bump SW VERSION v0.103.2 → v0.104.0（按 V0.100.1 沉淀教训）

[详情](docs/releases/v0.104.0.md)

---

## [V0.103.1] · 2026-10-19

`情报 5 子页 subnav 显示不一致（hotfix）` — 3 commit

### Fixed

- 🔧 **V0.103.1 hotfix · 5 个情报子页 subnav 显示不一致** —— 用户报告「情报下面的五个超链接展示形式和其他页面不一致」

  - 根因：5 个 intel 子页（消息面评估 / 央行购金 / 白银追踪 / 今日要闻 / 我的收藏）渲染同一段 `<nav class="subnav">`（topnav.js 统一生成），但容器 + 样式不一致：news/central_bank/silver 3 老页有内联 `.subnav` CSS + mount INSIDE `.wrap`（900/1040/960px），headlines/favorites 2 新页无内联 CSS + mount OUTSIDE `.wrap`（裸链接铺满 body 宽）
  - 修复：3 commit
    - C1 `b55b035 refactor(theme)`：`.subnav` 18 行从 news.html:112-131 抽到 `static/theme.css`，5 子页共用
    - C2 `6379f42 refactor(static)`：news/central_bank/silver 3 老页 `<div id="topnav-mount">` + `<div id="subnav-mount">` 一起从 `<main>` 内的 `<div class="wrap">` 移到 `<main>` 之前（OUTSIDE 任何宽度限制，与 headlines/favorites 对齐），同时删 3 处 byte-identical 内联 CSS 块
    - C3 验证：puppeteer 5 子页截图比对（`scripts/_verify_subnav_5sub.mjs`），5 个 subnav 统一为 1352px 全宽 + `rgb(255,255,255)` bg + `10px` radius + 5 tabs + 当前页 active 高亮
  - 4 处版本同步 bump 到 `v0.103.1`（`__version__` / `pyproject.toml` / `sw.js VERSION` / `CHANGELOG.md`）—— 改 static HTML 必须 bump SW VERSION 是 V0.100.1 沉淀教训

---

## [V0.103.0] · 2026-10-19

`我的收藏（今日要闻「收藏 / 永久存储 / 档案管理」）` — 7 commit / V0.103 正式发版

### Added

- ⭐ **我的收藏**（今日要闻「收藏 / 永久存储 / 档案管理」）—— 7 commit / V0.103 正式发版

  - 🗄️ `user_news_favorites` 表 + alembic 迁移（V0.103 n0a1b2c3d4，down_revision=m9g0a1b2c3 V0.102）；单表 + 16 字段（11 快照 + 3 user_meta + 2 timestamp）；`UNIQUE(news_external_id, news_source)` dedup 主键 + 3 索引（archived_at 倒序 / (importance, archived_at) 复合 / site_name）
  - 🏗️ ORM `UserNewsFavorite` + `UserNewsFavoriteRepository`（CRUD + 6 维 list：days / site_name / tag LIKE 模式 / importance_min / sort=recent|importance|publish + 分页；3 聚合：list_sites / list_tags 字母序 / get_status 6 维）
  - 🛠️ `UserNewsFavoriteService` 编排（_normalize_tags 去重 + 字母序；add 时优先从 `news_feed_items` 回填快照保证与 readhub 一致，外部 URL 收藏走客户端直传；`DuplicateFavoriteError` → 409）+ 5 Pydantic schema（ItemOut 16 字段 / CreateIn 12 字段 / UpdateIn 3 字段 / ListOut / StatusOut 6 维）
  - 🔌 9 REST 端点：`GET /api/v1/favorites/{items,items/{id},sites,tags,stats,exists/{ext}}` + `POST /items` + `PATCH /items/{id}` + `DELETE /items/{id}`（POST/PATCH/DELETE 走 `Depends(require_user)`，单用户模式自动回退 LEGACY_USER，V0.97.0 hotfix 防 401）
  - 🖥️ `/favorites` 档案管理页（fork headlines.html；toolbar：时间 4 段 / 来源 / 标签 / 重要度 / 排序；4 status chip：总数 / ★3 / 7d / 来源站；主列表：卡片含重要度徽章 + tag chip + inline 笔记 + 重要度升降 + 取消收藏；280px stats 侧栏：5 卡（重要度 / 标签 / 来源 / 月度 / KPI））+ 3 语 i18n 47 keys + topnav intel 第 5 子页
  - 🔗 `/headlines` 与 `/home` 每条新闻加 `⭐ 收藏` 按钮（POST → toast；409 = 幂等；初次渲染 GET /exists/{ext} 并发检查）
  - 🧪 仓储 18 例 + API 22 例 + 单用户回退端到端 1 例（`test_favorites_endpoint_works_in_single_user_mode`）+ 4 门禁同步（`check_routes` 17→18 alias，`check_pwa_assets` SHELL_ASSETS +3 条，`check_i18n_keys` V083_KEY_PREFIXES + `favorites.`，`test_main_app` ROOT_ALIASES 16→17）

[详情](docs/releases/v0.103.0.md)

---

## [V0.102.0] · 2026-10-19

`今日要闻（readhub 财经新闻流）` — 6 commit

> ⚠️ **V0.102 从未作为版本号发版** —— `__version__` 从 `v0.100.2` 直接跳到 `v0.103.0`，
> 本批次**没有 git tag、没有 release notes 文件、没有版本号 bump**。
> 它只是 commit message 里的功能批次标签，代码已上线并随 V0.103.0 一同发布。
> 此处按批次补记，以免「今日要闻」这段真实交付在发版史里查无此文。

### Added

- 📰 **今日要闻**（readhub 财经新闻流） —— 6 commit

  - 🗄️ `news_feed_items` 表 + alembic 迁移（V0.102 m9g0a1b2c3，down_revision=l8f9a0b1c2 ai_chat）；单表 + 5 索引（site_name / language / publish_date / fetched_at + 唯一 external_id）；`external_id` 整型 UNIQUE → dedup 主键
  - 🏗️ ORM 模型 `NewsFeedItem` + `NewsFeedRepository`（4 维查询：days / site_name / language / limit；批量 upsert 走 `sqlite_insert().on_conflict_do_update(index_elements=['external_id'])`）
  - 🌐 `readhub` fetcher（httpx async + 30s timeout + 1 次重试，5min 进程内 cache 避免 scheduler 与手动 refresh 撞车；`_normalize` 缺关键字段自动 drop；`NewsFeedService.refresh()` 失败仅日志 + `ok=False`，不抛异常走 V0.84 保留末次 UX）
  - 🔌 5 REST 端点：`GET /api/v1/news-feed/{items,sites,languages,status}` + `POST /refresh`（admin 守卫，单用户模式自动豁免）
  - ⏰ 6h 调度器（`news_feed_loop` 启动 30s 立即抓 + 00/06/12/18 UTC 4 触发点 ≈ 08/14/20/02 BJT；`NEWS_FEED_AUTO_REFRESH` env 开关，默认启用）
  - 🖥️ `/headlines` 静态页（headlines.html + headlines.js，silver 模式拆分；3 chip 顶栏：last_refresh + total + 24h；工具栏 时间/来源/语种 下拉；BJT 日分组卡片；新 tab 跳原文）+ 3 语 i18n 21 keys + topnav 接入「情报」第 4 子页
  - 🧪 22 测试 + 4 门禁同步（`check_routes` 16→17 alias，`check_pwa_assets` SHELL_ASSETS +3 条，`check_i18n_keys` V083_KEY_PREFIXES + `headlines.`，`test_main_app` ROOT_ALIASES 15→16）

---

## [V0.101.0] · 2026-10-18

`Python 3.13 迁移收口（C1 / C2 / C3a）` — 3 commit

> ⚠️ **V0.101 从未作为版本号发版** —— 同 V0.102，`__version__` 未经过 0.101.0。
> 3 个 commit 已合入主干并随 V0.103.0 发布。

### Changed

- 🐍 `pyproject.toml` `requires-python` 升 `>=3.13` + ruff `target-version = "py313"` + README 同步 — **C1 `21f9fc5`**
- 🐍 CI 矩阵收口 3.13 only（撤掉 3.11 / 3.12 组合） — **C2 `a20d881`**
- 🐳 Dockerfile 双 stage 基础镜像 `3.12-slim` → `3.13-slim` — **C3a `84a0f34`**

---

## [V0.100.2] · 2026-10-19

`home.html 今日要闻 Top 5 → Top 20（hotfix）` — 1 commit

### Fixed

- 🔧 **V0.100.2 hotfix · home.html 今日要闻 Top 5 → Top 20** —— 用户要求首页显示更多新闻

  - 改动：`static/home.js` `limit=5` → `limit=20`、`slice(0, 5)` → `slice(0, 20)`；`static/home.html` 3 骨架 → 5 骨架（视觉占位）
  - 4 处版本同步 bump 到 `v0.100.2`（按 V0.100.1 沉淀的「改 static 必须 bump」教训，参见 memory `v01001-sw-bump-on-static-change`）

[详情](docs/releases/v0.100.2.md)

---

## [V0.100.1] · 2026-10-19

`home.html 今日要闻不显示新闻标题（SW 缓存击穿 hotfix）` — 1 commit

### Fixed

- 🔧 **V0.100.1 hotfix · home.html 今日要闻不显示新闻标题** —— 旧 SW 缓存里 home.html 仍是 news-score 版（含 score 字段），用户报告「没显示新闻标题 / 不要分值」

  - 根因：`static/sw.js` VERSION 卡在 `v0.100.0`，但 home.html / home.js 已在 bfeb39f 改 readhub 流；activate 阶段按 cache name `gold-shell-v0.100.0` / `gold-runtime-v0.100.0` 不清旧 cache，浏览器持续回放 stale 入口（cache-first 命中 `RUNTIME_CACHE` 旧 `/home` 307 + 旧 `/static/home.html`）
  - 修复：`__version__` / `pyproject.toml` / `sw.js VERSION` 同步 bump `v0.100.1`（4 处版本同步门禁，参照 V0.100.0 release notes 第 105-111 行清单）；activate 阶段新增 `/home` + `/static/home.html` 的 `RUNTIME_CACHE` stale 清理（套 V0.92.0 `/scoring` 同模式）；新增 `pwa_assets` 门禁必跑

[详情](docs/releases/v0.100.1.md)

---

## [V0.100.0] · 2026-10-18

`消息面未打分 → 综合指数 pending` — 5 件大项 / 5 个 commit

### Added

- ⏳ 综合指数 pending chip（trend.html + silver.html）—— 消息面未打分时数字降级透明度 0.55 + 「▲ 消息面 pending」chip（复用 freshness.js fsh-warn 样式） — **C3 + C4 ✅**
- 🏷️ NewsIndexOut.pending_reason 字段（中文「今日尚未打分（消息面不参与综合指数）」） — **C1 ✅**
- 🌐 i18n +6 trend.* key × 3 语 = 18 条翻译（pending_chip / pending_tooltip / news_unscored_label / news_unscored_chip / news_pending_hint / combined_pending_news） — **C3 ✅**

### Changed

- 🔄 NewsScoreOut.score / direction：`float` → `float | None`（未打分时 None，替代中性 50 兜底） — **C1 ✅**
- 🔄 NewsIndexOut.score：`float` → `float | None` + 新增 pending_reason — **C1 ✅**
- ♻️ aggregate_slots()：records=[] 返回 `(None, "", False)`（替代 NEUTRAL_SCORE 兜底） — **C1 ✅**
- 📊 综合指数文案分支：`if set(dropped) == {"news"}` → 「消息面未打分，综合指数待定」pending 表述；多面被剔时沿用通用「不可用」 — **C2 ✅**
- 🛠️ snapshot.py news=None 兜底 50.0（DB NOT NULL；配合 macro_detail JSON 保持审计追溯） — **C2 ✅**

### Fixed

- 🐛 后端综合指数不再被「未打分消息面」以中性 50 稀释（剔整面归一化后 macro 自动按 0.4/0.7=57.1% 加权） — **C2 ✅**
- 🐛 test_main_app.ROOT_ALIASES 13 → 15 同步（V0.97.0 /ask + V0.98 /home 后预存漂移） — **C5 ✅**
- 🐛 check_routes / check_routes_test 3 处硬断言同步（14/13/16 → 16/15/18） — **C5 ✅**

### Discipline

- 「剔整面 + 归一化」算法（trend.py:517-524）**保留不动**（V0.78.0 Step D 实测覆盖）
- 既有 `combined is None` 防御分支仍保留（unreachable 兜底）
- `#idxMethod` 运算方法描述**不变**（×30% + ×40% + ×30% 公式维持口径；pending 仅 chip + summary 披露）

[详情](docs/releases/v0.100.0.md)

---

## [V0.99.0] · 2026-10-18

`白银数据修复 + SGE 上海银跟踪 + 页面重构` — 6 件大项 / 6 个 commit

### Added

- 🥈 SGE 上海银基准价 2 端点（`/silver/sge-quote` + `/silver/sge-trend`，CNY/kg） — **C3 ✅**
- 📊 白银页 3-market 视角：ETF（562800）+ NY SI + SGE Ag99.99，5 张卡渲染 — **C5 ✅**
- 📐 多市场升贴水表（以 SGE 为锚；ETF × 1000 / NY × 31.1035 × 7.1 / SGE 0%） — **C5 ✅**
- 🔀 主图市场选择器（3 market-btn：ETF / NY / SGE） + SGE-only 收盘价曲线 — **C5 ✅**
- 🌐 SGE 端点 schema：SilverSgeQuoteOut / SilverSgeTrendOut / SilverSgeTrendMetrics — **C3 ✅**
- 🔄 AkshareSgeSilverHistoryProvider（ak.spot_silver_benchmark_sge，1700+ 行历史） — **C2 ✅**
- 🏷️ SilverQuote.data_source_note 字段：eastmoney 失败时显示「LOF 代理」备注 — **C1 ✅**

### Changed

- ♻️ silver.html 655 行 → silver.html 332 行 + silver.js 445 行（IIFE 包装 + 7 模块函数 + DOMContentLoaded 入口） — **C4 ✅**
- 📊 562800 ETF 历史 K 线：em→sina sz161226（白银基金 LOF）双源降级，与 518880 黄金 ETF 对齐 — **C1 ✅**
- 🎨 headline 标题改 3-market（headline_title_3market） — **C5 ✅**
- 🏷️ sw.js SHELL_ASSETS 加 `/static/silver.js` — **C4 ✅**
- 🌐 i18n +12 silver.* keys × 3 langs = 36 条翻译 — **C5 ✅**

### Fixed

- 🐛 562800 ETF 历史 K 线静默走 mock（eastmoney `RemoteDisconnected`）→ em+sina 双源 — **C1 ✅**
- 🐛 silver.js TDZ bug（`techComposeBadge` 在使用之后才声明） — **C4 修**
- 🐛 renderMain 漏传 market 参数导致切 SGE 抛 `ReferenceError: market is not defined` — **C5 修**
- 🐛 SGE klines 无 ma5/ma20/ma40 字段 → hasMA 守卫只画 1 条收盘价 — **C5 修**

[详情](docs/releases/v0.99.0.md)

---

`体验重塑 + 结构清偿` — 7 件大项 / 11 个 commit

### Added

- 🏠 场景化首页（/home）— 5 大场景卡（决策 / 持仓 / 情报 / 配置 / AI） — **C4 ✅**
- ⚡ /ask SSE 流式响应（`/api/v1/ai/conversations/{id}/messages/stream`） — **C5 ✅**
- 🔗 URL 状态化（6 页）+ 跨页链接器 + 跨 tab 同步 — **C6 ✅**
- 📦 全局 toast 系统（`window.PM_Toast`）+ 断网检测 — **C3 ✅**
- 📥 PWA 安装体验完善（`appinstalled` 监听 + iOS 引导 + 7 天 TTL + manifest 完善） — **C3 ✅**
- 🧭 双层导航 7 顶场景 + 4 子场景 sub-tabs（首页/决策/持仓/情报/配置/AI/健康） — **C7 ✅**
- 📚 CHANGELOG.md + docs/releases 索引 — **C1 ✅**

### Changed

- ♻️ `ai_chat.py` 428 行 → 4 文件拆分（service / prompts / serializers / proxy_fallbacks） — **C2 ✅**
- 🏠 主页布局对齐 `.wrap` + `.hero` 标准模式（commit `94adce4`）
- 🏠 topnav 「🏠 首页」tab 加在最前

### Dependencies

- `+ sse-starlette ^2.0.0`（SSE 流式依赖） — **C5 ✅**

### Fixed

- 🐛 home 新闻加载失败（端点 URL 修正 `/api/v1/news-score/history`） — **C4 hotfix `83a0025`**
- 🐛 home topnav mount 缺失（占位符 → `<div id="topnav-mount">`） — **C4 hotfix `83a0025`**
- 🐛 home topnav CSS 缺失（字体/链接与其他业务页对齐） — **C4 hotfix `7434cda`**
- 🐛 nav-drawer.js:117 `insertBefore` 抛 NotFoundError（pre-existing，`.links` 是 `.topnav-row` 子节点） — **C7 顺手修**

[详情](docs/releases/v0.98.0.md)

---

---

## [V0.97.2 hotfix] · 2026-10-17

`miniMax 代理 2013 三级降级兜底` — tool_result inline 重试 + fresh-only 兜底

- **3 级降级链路**：L1 内联 tool_result 转纯文本 + tools=None 重试；L2 同时把上一条 assistant 的 tool_use 块也转纯文本（在 L1 内完成）；L3 只发用户原问题不传历史
- `_inline_tool_results_as_text()` 增强：除 user 消息的 tool_result blocks，还把前一条 assistant 消息的 tool_use blocks 转为 `[Called name with {input}]` 纯文本，彻底平铺对话
- `send_message()` LLMError 兜底重写为 3 级链：「失败 → L1 inlined tools=None → 仍 2013 → L3 fresh-only → 仍失败才抛」
- 新增测试 `test_tool_result_fallback_l1_also_2013_falls_to_l3_fresh_only`（mock 4 次 LLM 调用）
- 不 bump 版本号，按 `sw-version-sync-gate` 不需要 SW 缓存重建

[详情](docs/releases/v0.97.2-hotfix.md)

---

## [V0.97.2] · 2026-10-17

`/ask 页面布局修复（视口感知 + welcome 卡片）` — 纯前端 CSS + HTML + JS

- 视口感知 flex 三层链布局：`body` → `.wrap` → `.ask-layout(grid)`，所有层级 `min-height: 0` 让 `.message-stream` 可滚动
- 2 栏默认 / 3 栏按需：`grid-template-columns: 240px minmax(0, 1fr)` 默认，`.has-tools` 时切到 `240px minmax(0, 1fr) 280px`
- Welcome 卡片（5 个示例 chip：市场概览 / 持仓 / 命中率 / 风险 / 资金流）替换旧 `empty_state` 文案
- 输入栏微优化：textarea `title="Enter 发送 · Shift+Enter 换行"`、`max-height: 120px`、字数提示 `N / 8000`（>2000 显示，>8000 变红）
- i18n `ai.*` 新增 12 keys × 3 语（empty_title / empty_desc / example_market / _q 等）
- 4 处版本同步：pyproject / `__init__.py` / `sw.js` / `docs/releases/v0.97.2.md`
- 设计纪律：不引依赖、不动后端、不动 DB schema、SHELL_ASSETS 35 条不变

[详情](docs/releases/v0.97.2.md)

---

## [V0.97.1] · 2026-10-XX

`AI 智能分析页 UI hotfix` — 工具调用展示 + 数据来源可验证

- Tool name 中文化 + emoji 标签（`TOOL_LABELS` 字典）：`get_market_overview` → 📈 市场概览 等 5 项
- Tool 输入摘要（`summarizeInput`）：按 tool 白名单抽取关键参数（日期范围 / N / 未知 tool 截断 100 字符）
- Tool 结果摘要（`summarizeResult`）：按 tool 白名单抽取核心数据（1-2 行可读，未知 tool 截断 200 字符）
- 聊天流调整：assistant tool_use 消息不再 spinner 永久，显示「🔧 📈 市场概览」chip；tool 结果用折叠 `<details>` 默收
- 最终 assistant 末尾追加「📊 基于 N 个工具调用 · 右侧查看详情」chip（虚线边框）
- 右侧 trace 面板重做：工具名 + 角色 chip（`→ 调用` / `← 结果`）+ 参数摘要 + 结果摘要 + 折叠原始 JSON
- 4 处版本同步：pyproject / `__init__.py` / sw.js（v0.97.1 + SHELL_ASSETS 加 ask.js）/ docs
- 门禁：check_pwa_assets 33→35 SHELL_ASSETS / check_routes 14→15 alias（/ask）

[详情](docs/releases/v0.97.1.md)

---

## [V0.97.0] · 2026-10-XX

`AI 智能分析页 (/ask)` — 多轮对话 + 5 个只读 tool

- **数据层**：2 张新表（`ai_conversations` / `ai_messages`）+ alembic 迁移 `l8f9a0b1c2` + 4 索引；2 个仓储（`AIConversationRepository` 6 方法 + `AIMessageRepository` 6 方法）
- **服务层**：`ClaudeClient` httpx 直调 Anthropic Messages API（重试退避 2.0/5.0/15.0 + 仅 429/5xx）+ `ToolDispatcher` 5 个只读 tool（get_market_overview / get_scoring_summary / get_user_portfolio / get_warning_summary / get_etf_recent_flows）
- **`AIChatService`**：多轮 tool_use 循环（硬上限 3 轮，命中 end_turn 即停）+ 8000 字符 prompt injection 防护 + LLM 异常时 `msg.delete(user_msg.id)` 失败回滚
- **6 端点**：`GET /health` / `POST /conversations` / `GET /conversations` / `GET /conversations/{id}` / `PATCH/DELETE /conversations/{id}` / `POST /conversations/{id}/messages`
- **`PerUserRateLimitMiddleware`**：per-user 60s 滑动窗口（默认 30 req/min）+ 每日 token 配额（默认 100k/天）
- **前端 3 pane chat UI**：左 240px 对话列表 + 中 flex 消息流 + 右 280px tool trace；marked v12 markdown 解析 + 自写 XSS 清洗
- **i18n**：新增 `ai.*` 36 keys + `nav.ask` × 3 语（zh-CN / en-US / zh-TW）
- **测试**：22 例（service 5 + LLM 6 + endpoint 11）；4 处版本同步清单 + check_pwa_assets / check_routes 门禁

[详情](docs/releases/v0.97.0.md)

---

## [V0.96.0] · 2026-09-XX

`scoring「命中分析」Tab` + 4 horizon 柱状图 + 3 mini card

- 新端点 `GET /api/v1/scoring/hit-stats-all`（不改动 `scoring_daily_wide` 宽表）—— 1 次 fetch 拿 4 horizon (t0/t1/t3/t5) by_month + 3 mini card
- 新 schema：`ScoringHitStatsAllOut`（顶层）+ `ScoringHitStatsAllHorizon`（by_month）+ `ScoringHitStatsAllMiniCard`（30d / mom / best）
- 新 mini card helper `_compute_mini_card()`：最近 30 ready 日 vs 上 30 ready 日 + 最佳 horizon（多 horizon 同分取字典序最小）
- 第 3 Tab「命中分析」panel：canvas#hitChart（Chart.js bar type，4 dataset 4 色叠加）+ 3 mini card（最近 30 天 / 同比上月 / 最佳 horizon）
- 4 色 chart palette：t0=amber / t1=blue / t3=violet / t5=green（避开 V0.92.1 红绿）
- 排序：x 轴按月份降序（V0.95.1 降序约定 · 最近→远期自上而下）
- i18n 新增 9 keys × 3 语（tab_hit / hit_chart_title / hit_mini_30d 等）
- 4 处版本同步：pyproject / `__init__.py` / sw.js（v0.96.0）/ docs
- 旧 `GET /hit-stats?horizon=tN` 单 horizon 端点保留向后兼容

[详情](docs/releases/v0.96.0.md)

---

## [V0.95.1] · 2026-09-XX

`scoring 4 指数时序桶排序降序` — 最近→远期自上而下

- `summary()` 桶迭代 `sorted(...)` → `sorted(..., reverse=True)`（line 282）
- `hit_stats().by_month` 桶迭代同上（line 392）
- **多视图一致性**：日历视图（renderCalendar 早就是 `.reverse()` 倒序 line 328），主表与日历排序方向统一
- **period 字符串设计**：day=`YYYY-MM-DD` / week=`YYYY-Wxx` / month=`YYYY-MM` 都是字典序 == 时间序，`reverse=True` 即可无需自定义 comparator
- puppeteer 视觉确认：4 指数时序表自上而下从 2026-10-14 排到 2026-09-07
- 门禁：check_routes.py 14 OK / check_pwa_assets v0.92.0 OK / check_static_js 17+30 OK
- commit `2e956d3`
- **注**：本版未发版本号（V0.92.0 维护线无 sw.js VERSION 改动需求）

---

## [V0.94.0] · 2026-09-XX

`scoring 预测评估卡` — 顶部 verdict card（方向 + 置信度 + 4 horizon 状态）

- 顶部 verdict card：方向（看多 / 看空 / 中性）+ 置信度（high / medium / low）+ 4 horizon（t0/t1/t3/t5）ready/pending/missing
- 一句话 summary（首段自然语言结论）
- 跟随 toDate 联动（顶部日期 picker 变化时 verdict card 重渲染）
- 与 V0.96.0 第 3 Tab「命中分析」功能不重叠（verdict 是当日决策摘要 + tab 是时序走势）
- i18n 新增 verdict 相关 keys × 3 语
- 门禁：check_routes / check_pwa_assets / check_i18n_keys 全过

---

## [V0.93.0] · 2026-09-XX

`scoring T+0 outcome` — 当日 close vs 上一交易日 close

- 基准：当日 close vs 上一交易日 close（`gold_price_daily.latest_before(target, date)` 自动处理节假日/周末）
- DB 字段：`scoring_daily_wide.actual_change_pct_t0 FLOAT` / `hit_t0 BOOLEAN`（nullable，老行 NULL=pending）
- migration `j6d7e8f9a0b1` 仅 `add_column`，老行 `hit_t0=NULL` = pending；历史回填用 `backfill_scoring_wide`
- horizon 枚举扩为 `^(t0|t1|t3|t5)$`（endpoint Query pattern + service ValueError 校验）
- `hit_col` dict 加 `0: "hit_t0"`，UI 列全显（顺序：t0 / t1 / t3 / t5，默认仍 t1）
- **纪律**：T+0 含打分时刻已发生的盘内信息，**不**用于评估「预测能力」，仅作快速 sanity check
- `ScoringWideRepository.upsert` 字段白名单加 `actual_change_pct_t0` / `hit_t0`（V0.79.0 #162 教训）

---

## [V0.92.1] · 2026-08-XX

`scoring 命中筛选` — 行级 filter（全部 / 是 / 否）+ 「是」用红色

- API 契约 `GET /api/v1/scoring/summary` 新增 `hit`（all / yes / no，默认 all）+ `horizon`（默认 t1）
- 服务端按 `hit_t{horizon}` 在**行级**过滤后再分桶（pending 行被 `yes`/`no` 排除；`all` 保留）
- 默认值改动：`groupBy=month` → `groupBy=day`，`horizon=t5` → `horizon=t1`
- 「是」色 = **红色 `#dc2626`**（用户语义覆盖：常规红=坏，这里红=命中；以后 scoring 页「是」都用此色）
- 「否」色 = 绿色 `#16a34a`（语义化）
- 「待定」色 = `var(--muted)` 灰（pending：等待 T+1/T+3/T+5 就绪）
- `ScoringSummaryBucket` 新增 `hit: bool | None` 字段 —— 仅 `group_by=day` 且桶内恰 1 行时承载
- i18n 新增 8 keys × 3 语（hit_filter / hit_filter_all/yes/no / hit_col / hit_col_yes/no/pending）

---

## [V0.92.0] · 2026-08-XX

`维护线 + 多项修复` — scoring 物化宽表 + 汇总页 + 多项 hotfix

- **`scoring_daily_wide` 物化宽表**（migration `i5d6e7f8a9b0`）：1 行/日，4 指数 + 消息面聚合 + 复盘 outcomes + basis_tags JSON，26 列 + 3 索引，写时 hook ETL
- **5 端点**：`/summary`（按 day/week/month 聚合）/ `/by-date/{date}` / `/hit-stats`（按 horizon + by_direction + by_month + calibration）/ `/by-tag`（basis_tag 维度）/ `/rebuild/{date}`（手动重算）
- **`/scoring` 汇总页** —— 双 Tab：日历视图（每日 4 指数热力图）+ 表格视图（4 指数时间序列 + basis_tag 频次 + 命中率）
- **`backfill_scoring_wide.py` CLI** —— 一次性历史回填（默认从 V0.66.0 上线日 2024-09-01 起）
- 跨日历史查询路径性能：6 个 history 端点 JOIN 4-6 表（100-300ms/次）→ 宽表 O(天数) 直查（<10ms/次）
- 业务页 9 → 10（+ /scoring），RESTful alias 12 → 13
- 端点 28 → 33（+ 5 端点），维护线覆盖率 90%+

[详情](docs/releases/v0.92.0.md)

---

[V0.99.0]: docs/releases/v0.99.0.md
[V0.98.0]: docs/releases/v0.98.0.md
[V0.97.2 hotfix]: docs/releases/v0.97.2-hotfix.md
[V0.97.2]: docs/releases/v0.97.2.md
[V0.97.1]: docs/releases/v0.97.1.md
[V0.97.0]: docs/releases/v0.97.0.md
[V0.96.0]: docs/releases/v0.96.0.md
[V0.92.0]: docs/releases/v0.92.0.md
