# 开发版本推进线路图（V0.78.0 → V0.82.0+）

> **配套文档**：
> - [parameter-evaluation.md](parameter-evaluation.md) — **8 项参数问题诊断 + 推荐新值**（本路线图的输入）
> - [development.md](development.md) §11 改进计划 — **P0-P3 大路线 + 状态补遗**
> - [ux-roadmap.md](ux-roadmap.md) — **应用 / UX 路线**（V0.68.0 → V0.77.2 已完成）
>
> **本文件范围**：把 parameter-evaluation.md 的改进项 + 其他后台任务排进具体版本，给出**每版本的实施步骤、commit 切分、测试与文档同步**。
>
> **基线版本**：V0.77.2（commit `5ffc650`，2026-10-03） —— 本路线图据此规划；**V0.78.0 已于 2026-10-05 发布**（§1 四步 A/B/C/D 全部交付，用例 867 → 945），一致性收口收尾；**V0.78.1（补丁版）同日发布** —— 修 `static/sw.js` 缓存版本脱钩（并新增 PWA 资源门禁强制二者一致）+ PWA 快捷方式两条 404 + `compute_resonance` 缺维按 50 兜底 + 补 `starlette` 依赖声明，另新增死链 / 依赖声明两道门禁并接入 CI（质量门禁 5 道 → **8 道**），用例 945 → 972。
> **预计路线终点**：V0.82.0，约 6 个月（2027-Q1 末）

---

## 0. 路线图总览（一图）

```
                          2026                  2027
V0.77.2 ──┬───────────┬───────────┬───────────┬───────────▶ 持续
(当前)    │           │           │           │
          ▼           ▼           ▼           ▼
       V0.78.0    V0.79.0    V0.80.0    V0.82.0+
       10月中旬    11月中旬    12月-1月     Q1-Q2
       "一致性"    "自适应"    "可执行化"   "多市场 + 收尾"
       5 天        4-6 周      2-3 月      2-3 月
       ─────────────────────────────────────
       并行线:
       V0.75.2 数据隔离 ─┐
       V0.75.3 找回密码 ─┴─── 认证收尾（独立路线）
       V0.78.x 测试扩充 / 依赖升级 / bugfix ──── 维护线
```

**关键决策**：
- **以「参数评估改进」为主路线**，因为 parameter-evaluation.md 已识别 8 项具体问题。
- **认证收尾（V0.75.2 / V0.75.3）独立推进**——它面向公开发布前置条件，与参数调优解耦。
- **维护线持续运转**——bugfix / 依赖升级 / 测试扩充不阻塞主版本，但每 2 周一个 V0.7x.y 小版本。
- **每个大版本都带 1-2 个 P0 改进 + 1-2 个 P1 改进**，避免一次改动过大难回归。

---

## 1. V0.78.0 · 阈值口径统一 + 决策补全

**主题**：**一致性收口**——把所有"55 是 UP 还是中性"的口径冲突解决，让方向判定在 5 个模块里口径一致。
**预计时间**：5 天（2026-10-08 至 2026-10-13）
**预计 commit 数**：4-6 个

### 1.1 改进项

| ID | 改进 | 优先级 | 工作量 | 来自 parameter-evaluation.md |
|----|------|--------|--------|----------------------------|
| A | 统一阈值常量 | P0 | 0.5 天 | §3.1 | ✅ 已实现 2026-10-05 |
| B | 决策矩阵档位补全 | P0 | 1-2 天 | §3.4 | ✅ 已实现 2026-10-05 |
| C | 共振信号扩展反向 | P1 | 0.5 天 | §3.5 | ✅ 已实现 2026-10-05 |
| D | 兜底策略差异化 | P0 | 1 天 | §3.7 | ✅ 已实现 2026-10-05 |

### 1.2 详细实施步骤

#### Step A · 统一阈值常量（Day 1 上午）

**目标**：建 `schemas/thresholds.py`，把 5/45/55/60/70 五个常量从代码里抽出来集中管理。

**状态**：✅ 已实现（2026-10-05 收口）。**收口时的关键结论 —— 硬编码不是一种语义，
是四种**，本节模板只列了 5 个模块的替换位置，实际执行时按语义分了三类处理：

| 类别 | 位置 | 处理 |
|------|------|------|
| 单维度方向 60/40 | `macro.py` + `scoring._to_signal`（两处完全相同） | 复用 `DirectionThreshold.NEUTRAL_HIGH/LOW` |
| 仓位档位 75/55/45/25 | `decision._suggest_position` | 复用 `LevelThreshold`（与 `trend._to_level` 同源） |
| 投资窗口 70/55/40 | `scoring._to_window` / `_summarize` | 语义独立 → **新增** `OpportunityWindowThreshold` |
| 指数着色 55/40 | `decision._build_reason_items` | **有意保留**：显示层着色，40 故意不同于 `BEARISH`(45) 以更早示警，属产品语义决策 |

另新增 `tests/test_services/test_thresholds.py`（25 例，本节模板要求的「约 15 例」
一直缺失），其中以 **AST 遍历**机械保证「服务层判定逻辑不再出现裸阈值字面量」——
用 AST 而非 grep，因 grep 会命中 docstring 与注释、也扛不住行号漂移。

模板下方那段「校验：预期只剩 `schemas/thresholds.py` 一处定义」**未达成且不打算达成**：
剩余字面量分属不同语义（`win_rate >= 50` 胜率、`len(closes) < 40` 交易日根数、
`payload keys > 50` 安全上限）与有意保留项，不属于本枚举要收口的对象。

**文件改动**：
1. 新建 `src/app/schemas/thresholds.py`：
   ```python
   """集中管理 0-100 分制下的方向/等级/决策阈值常量。"""
   from enum import IntEnum

   class DirectionThreshold(IntEnum):
       """方向判定阈值（与 0-100 分制对齐）"""
       STRONG_BULLISH = 70   # 强多（决策 BUY_HEAVY 触发）
       BULLISH = 55          # 看多（消息面 > 55、共振 ≥ 55、单维度 ≥ 60 中性偏多）
       NEUTRAL_HIGH = 60     # 中性偏上（单维度方向判定）
       NEUTRAL_LOW = 40      # 中性偏下
       BEARISH = 45          # 看空
       STRONG_BEARISH = 25   # 弱势下降（综合指数 STRONG_DOWN 触发）

   class LevelThreshold(IntEnum):
       """综合指数等级阈值（含端点）"""
       STRONG_UP = 75
       UP = 55
       SIDEWAYS = 45
       DOWN = 25

   class DecisionThreshold(IntEnum):
       """决策矩阵档位阈值"""
       BUY_HEAVY = 75        # ≥ 75 重仓买入（80%）
       BUY = 65              # ≥ 65 普通买入（60%）
       BUY_LIGHT = 55        # ≥ 55 轻仓试仓（30%）
       HOLD = 50             # ≥ 50 持有
       HOLD_LOW = 40         # ≥ 40 观望持有
       REDUCE = 40           # < 40 减仓
   ```

2. **替换硬编码**（按出现位置）：
   - `src/app/services/news.py:40-41` → `DirectionThreshold.BULLISH.value` / `BEARISH.value`
   - `src/app/services/trend.py:645-651` → `DirectionThreshold.NEUTRAL_HIGH/LOW.value`
   - `src/app/services/trend.py:654-664` → `LevelThreshold.*`
   - `src/app/services/decision.py:118-159` → `DecisionThreshold.*`
   - `src/app/services/resonance.py:38-39` → `DirectionThreshold.BULLISH/BEARISH.value`

3. **校验**：
   ```bash
   grep -rnE "(55\.0|45\.0|>55|<45|>= 55|>= 45)" src/app/services/ \
     | grep -v test_ | grep -v __pycache__
   ```
   预期输出：只剩 `schemas/thresholds.py` 一处定义。

**测试改动**：
- `tests/test_services/test_thresholds.py`（新增，约 15 例）
- 验证：所有现有决策 / 共振 / 消息面 / 单维度方向测试**零修改通过**（验证抽常量不改变行为）。

**commit 切分**：1 个 commit `refactor(schemas): 统一阈值常量到 schemas/thresholds.py`

---

#### Step B · 决策矩阵档位补全（Day 1 下午 ~ Day 2）

**目标**：BUY 拆 3 档（30% / 60% / 80%），消除 [60, 70) × [-10%, +15%] 卡死区，新增 idx [40, 45) HOLD 缓冲档。

**文件改动**：
1. `src/app/schemas/decision.py`：
   ```python
   class DecisionAction(str, Enum):
       BUY_HEAVY = "buy_heavy"   # 80% 仓位
       BUY = "buy"               # 60% 仓位
       BUY_LIGHT = "buy_light"   # 30% 仓位
       ADD = "add"
       HOLD = "hold"
       HOLD_CAUTIOUS = "hold_cautious"   # 新增：观望持有（idx [40, 45)）
       REDUCE = "reduce"
       SELL = "sell"
       WAIT = "wait"
   ```

2. `src/app/services/decision.py:_decide()`：
   - **无持仓分支**（`decision.py:139-146` 替换为）：
     ```python
     if idx >= DecisionThreshold.BUY_HEAVY:  # ≥ 75
         return BUY_HEAVY, "high"
     elif idx >= DecisionThreshold.BUY:  # ≥ 65
         return BUY, "high"
     elif idx >= DecisionThreshold.BUY_LIGHT:  # ≥ 55
         return BUY_LIGHT, "medium"
     elif idx >= DecisionThreshold.HOLD:  # ≥ 50
         return WAIT, "low"
     else:
         return WAIT, "medium"
     ```
   - **有持仓分支**（`decision.py:148-159` 替换为）：
     ```python
     if pnl_pct >= 15 and idx < 60:
         return SELL, "high"
     elif pnl_pct <= -10 and idx < 40:
         return REDUCE, "high"
     elif idx >= DecisionThreshold.BUY_HEAVY:  # ≥ 75
         return ADD, "high"
     elif idx >= DecisionThreshold.BUY_LIGHT:  # ≥ 55
         return HOLD, "medium"
     elif idx >= DecisionThreshold.HOLD_LOW:  # ≥ 40
         return HOLD_CAUTIOUS, "low"   # 新增缓冲档
     else:
         return REDUCE, "medium"
     ```

3. `src/app/api/v1/endpoints/portfolio.py`：决策接口返回 `BUY_LIGHT` / `HOLD_CAUTIOUS` 等新动作，前端 `static/portfolio.html` 决策面板加对应中文映射（轻仓买入 / 观望持有）。

4. **回测联动**：`services/backtest.py` 的 action 统计表增 3 个新动作。

**测试改动**：
- `tests/test_services/test_decision.py`：
  - 删除 6 个旧测试，替换为 12 个新测试覆盖 50 格决策矩阵的关键 12 个分支
  - 新增 `test_decision_no_dead_zone_*`（消除卡死区）
  - 新增 `test_decision_buy_light_*`（轻仓买入触发）

**commit 切分**：1 个 commit `feat(decision): 决策矩阵档位补全 + BUY 拆 3 档`

---

#### Step C · 共振信号扩展反向（Day 3 上午）

**目标**：DIVERGENT = 「任意两维反向幅度 ≥ 15」，新增 `news_vs_macro` / `news_vs_tech` 子类。

**状态**：✅ 已实现（2026-10-05）。实现与本节模板的**两处有意偏差**，照抄本节会踩：

1. **取幅度最大的达标对，而非 `_DIVERGENT_PAIRS` 中首个达标**。本节模板的 `for` + `return`
   会在宏观落于中性区时选 tech-macro 的 15 分差，从而掩盖 tech-news 可能存在的
   30 分显著背离 —— 而后者才是 §3.5 关心的场景。复现：`tech=35, macro=50, news=65`。
2. **`DivergentSubtype` 用 `StrEnum`**，不是 `str, Enum`（ruff UP042 会拒），
   与 `DecisionAction` 保持同一约定。

**文件改动**：
1. `src/app/services/resonance.py:38-40` 加常量：
   ```python
   _DIVERGENT_THRESHOLD = 15   # 反向幅度阈值
   ```

2. `src/app/services/resonance.py:89-95` 替换为：
   ```python
   # DIVERGENT：任意两维反向幅度 ≥ 15
   pairs = [
       ("tech_macro", tech, macro),
       ("tech_news", tech, news),
       ("macro_news", macro, news),
   ]
   for name, a, b in pairs:
       if abs(a - b) >= _DIVERGENT_THRESHOLD:
           return SignalResult(
               signal="divergent",
               subtype=name,
               confidence=clip((max(a, b) - min(a, b)) * 0.5, 0, 100),
               ...
           )
   ```

3. `src/app/schemas/resonance.py`：`DivergentSubtype` 枚举增 `tech_news` / `macro_news`。

4. `static/synthesis-card.js`：结论卡显示 `divergent` 时附 subtype（如「技术 vs 消息面反向」）。

**测试改动**：
- `tests/test_services/test_resonance.py`：增 6 例
  - `test_resonant_tech_vs_news_divergent`
  - `test_resonant_macro_vs_news_divergent`
  - `test_resonant_divergent_confidence_formula`
  - 边界：幅度 = 14（不触发）、= 15（触发）

**commit 切分**：1 个 commit `feat(resonance): 扩展 DIVERGENT 识别 + subtype`

---

#### Step D · 兜底策略差异化（Day 3 下午 ~ Day 4）

**目标**：技术面 5 维度 score 改 `Optional[float]`，数据不足显示 `—` 占位。

**状态**：✅ 已实现（2026-10-05）。实现与本节模板的**三处有意偏差**：

1. **本节模板只点出了「50 兜底」这一种，实际是两种，且第二种更隐蔽**：
   `_alignment_score` 在均线不足时返回 `50 + "均线数据不足"`，与「均线交叉整理」的
   **真实** 50 分**完全同形** —— 页面与接口都看不出区别。故本版把「数据不足」与
   「真实中性」的区别落在**返回类型**上（`None` vs `50.0`），而非依赖文案区分。
   `_rsi` 同理：不足时由 `50.0` 改 `None`，否则页面显示「RSI(14) = 50.0」，
   与「RSI 真的是 50」无法区分。
2. **最低数据量集中为 `services/trend.py::DIM_MIN_BARS`**（结构 40 / 动量 21 / 支撑 20 /
   动能 15 / 回撤 10），而不是各维度函数里各写一遍 `if len(closes) < N`；并有测试断言
   该常量表的键集合与 `TREND_WEIGHTS` 一致（防将来加维度时漏给门槛）。
   顺带修掉一个会误导的口径：**动量**原本在不足 21 根时**静默退化为「与首根比较」
   却仍标注「近20日」**，本版改为不足即 `None`。`动能` 的门槛不写进常量表，而由
   `_rsi` 自身返回 `None` 实现 —— 避免同一条件在两处漂移。
3. **W/M 多时间框架的技术面旁路仍按中性 50 计**（**未**改成 `None`），但**补上了披露**。
   保留 50 的理由有二：① 「口径不适用」与「数据不足」不是同一类问题，后者才是本步的对象；
   ② 丢掉技术面会让 52W/24M 的指数相对 60D 出现**结构性**（非市场）落差，破坏跨周期可比性。
   改动它属产品决策，需与「是否在聚合序列上重算技术面」一并评估。
   **⚠ 立项时发现一处既有缺陷**：原代码把「已按中性 50 处理」写在 `tech_index.summary` 里，
   而 `_build_index` 返回的 `tech_index` 除 `.score` 外**从不进入响应**（实测其全部引用点
   都只读 `.score`）⇒ **那句话等于从未披露**，52W/24M 视图上的 50 是沉默的假中性。
   本版把披露落到**对外可见的 `index.summary`**（新增 `tech_note`），并修掉趋势页
   `idxMethod` 在该视图下输出「技术面 = 。」的半句话。由
   `test_w_and_m_interval_discloses_neutral_tech_in_summary` 断言**响应里可见的那句话**。

4. **顺带修掉一个既有崩溃（本步实测发现，非模板内容）**：`_rsi` 的守卫写
   `len(closes) <= period`，而循环最低要读 `closes[-(period + 2)]` ⇒ **恰好 15 根收盘价时
   IndexError 冒泡成 HTTP 500**，而该维度本应判「数据不足」。改为 `< period + 2` 即归入
   `None`，由 `test_rsi_returns_none_when_insufficient` 锁住（把曾经的崩溃点写成断言）。
   同时发现该函数循环 `range(-period - 1, -1)` **不含 -1** ⇒ **最新一根的涨跌不参与计算**
   （RSI 实为截至前一根的值、滞后一根，已实测比对确认）。此项**只记录不修改**：修它会让
   所有 RSI 值变化并传导至动能分、综合指数、决策与历史快照，属口径变更，须先做三维回测
   交叉验证；现状由 `test_rsi_ignores_latest_bar_is_known_not_accidental` 锁死，
   属**显式记录**而非默默保留。

**下游耦合（本版未处理，留待 V0.79.0）**：`services/resonance.py::compute_resonance`
对缺失维度按中性 `50.0` 兜底（其原设计如此），故「技术面整面被剔除」时共振信号仍按
50 参与。当前仅在「K 线少于 15 根」这一极边角场景触发（现有标的均 ≥ 42 根），故未改动
Step C 刚校准过的共振口径；若要改，须与 §3.5 的背离阈值一并回归。

**文件改动**：
1. `src/app/schemas/trend.py`：
   ```python
   class DimensionScore(BaseModel):
       name: str           # 结构 / 动量 / ...
       value: Optional[float]   # None 表示数据不足
       reason: Optional[str] = None   # 数据不足时的原因说明
   ```

2. `src/app/services/trend.py:501-595`：5 维度计算函数改返回 `Optional[float]`，数据不足时返回 `(None, "数据不足：< 14 个交易日")`。

3. `src/app/services/trend.py:354-359`：综合指数合成改为：
   ```python
   valid_dims = [(name, v) for name, v in dims.items() if v is not None]
   if not valid_dims:
       combined = None   # 整张图数据不足
   else:
       total_w = sum(TREND_WEIGHTS[n] for n, _ in valid_dims)
       combined = sum(TREND_WEIGHTS[n] * v for n, v in valid_dims) / total_w
   ```

4. `static/trend.html`：5 维度展示改 `value === null ? '—' : value.toFixed(0)`，鼠标悬停显示 `reason`。

5. `static/synthesis-card.js`：结论卡若 `combined === null`，显示「数据不足，结论待补」。

**测试改动**：
- `tests/test_services/test_trend.py`：增 4 例
  - `test_trend_dim_insufficient_returns_none`
  - `test_trend_combined_re_normalize_when_partial`
  - `test_trend_combined_none_when_all_insufficient`
  - `test_trend_dim_reason_populated`

**commit 切分**：1 个 commit `feat(trend): 兜底差异化 · 数据不足显示占位 + 综合指数归一化`

---

### 1.3 发布前 Checklist

```bash
# 1. 全量回归
uv run python -m pytest -q --ignore=tests/test_services/test_irfcl_fetcher.py \
  --ignore=tests/test_services/test_h15_fetcher.py
# 预期：864+ collected, 0 failed（V0.77.2 是 823 离线 + ~40 新增）

# 2. ruff
ruff check src tests
ruff format --check src tests

# 3. JS 门禁
uv run python scripts/check_static_js.py

# 4. 渲染门禁
node scripts/check_cluster_render.mjs   # V0.77.0 起 125 条

# 5. 文档门禁
uv run python scripts/check_docs_claims.py
# 预期：390+ 处引用全部命中

# 6. 同步更新文档
# - docs/api-reference.md §6 核心模型增「阈值常量表」
# - docs/development.md §10 版本历史新增 V0.78.0 条目
# - docs/ux-roadmap.md V0.78.0 段落

# 7. 标签
git tag -a v0.78.0 -m "V0.78.0 · 阈值口径统一 + 决策补全"

# 8. 推送（用户需提供 classic PAT）
git push https://oauth2:<PAT>@github.com/surui1981/gold-etf-analyzer.git main --tags
```

---

## 2. V0.79.0 · 阈值动态化 + 回测增强

**主题**：**参数自适应**——让阈值跟随市场滚动变化，让回测能扫到内部权重。
**预计时间**：4-6 周（2026-10-14 至 2026-11-22）
**预计 commit 数**：15-20 个

**当前进度**（截至 2026-10-07）：
- Step G（回测权重嵌套扩展）：✅ 完成（3/3 commit：dbf9239 + 77d33a5 + 43cab52）
- Step E（动态化宏观阈值）：✅ 完成（4/4 commit：3ac95ca + 3d47b9d + 0722f74 + 04f2fa2）
- Step F（技术面 5 维度重构）：✅ 完成（5/5 commit：45044f6 + 020ab5e + 479bd32 + 999decf，2026-10-07）
- Step H（样本阈值分层）：✅ 完成（1 commit：5df2707，2026-10-07）

### 2.1 改进项

| ID | 改进 | 优先级 | 工作量 | 来自 parameter-evaluation.md | 状态 |
|----|------|--------|--------|----------------------------|------|
| G | 回测权重嵌套扩展 | P0 | 1 周 | §3.6 | ✅ 完成（43cab52） |
| E | 动态化宏观阈值 | P0 | 1-2 周 | §3.2 | ✅ 完成（04f2fa2） |
| F | 技术面 5 维度重构（组内平均） | P1 | 2-3 周 | §3.3 | ✅ 完成（999decf，2026-10-07） |
| H | 样本阈值分层 | P2 | 0.5 天 | §3.8 | ✅ 完成（5df2707） |

**依赖**：F 必须等 G 完成（否则无法回测扫内部权重）。

### 2.2 详细实施步骤

#### Step G · 回测权重嵌套扩展（Week 1）

**目标**：`WeightGrid` 支持嵌套（`trend_5` / `macro_5` 字典形式），上限 125 → 1000，
加异步回测端点让大网格扫描不阻塞页面。

**状态**：🟡 进行中（2/3 commit 已合并）
- ✅ Commit 1 `dbf9239`：WeightGrid 嵌套 + 上限 1000
- ✅ Commit 2 `77d33a5`：异步回测接口 + task_registry + task_id 轮询
- ⏳ Commit 3：UI 高级模式编辑器 + 异步进度条（下一批启动）

**最终 schema 形态**（与原计划不同 —— 见 Commit 1 实现）：
```python
class NestedWeights(BaseModel):
    weights: list[dict[str, float]] = Field(..., min_length=1, max_length=10)
    _expected_fields: ClassVar[tuple[str, ...]] = ()  # 子类覆盖

class TrendWeights(NestedWeights):
    _expected_fields = ("结构", "动量", "支撑", "动能", "回撤")
class MacroWeights(NestedWeights):
    _expected_fields = ("美元", "利率", "通胀", "地缘", "避险")

class WeightGrid(BaseModel):
    tech: list[float]
    macro: list[float]
    news: list[float]
    trend_weights: TrendWeights | None = None
    macro_weights: MacroWeights | None = None
```

**最终端点形态**（与原计划不同 —— 异步 + 轮询是 2 个端点不是 1 个）：
- `POST /api/v1/backtest/run-async` → 202 Accepted + `Location: /api/v1/backtest/result/{task_id}`
- `GET  /api/v1/backtest/result/{task_id}` → status + BacktestResultOut / error

**关键决策（实现过程中沉淀）**：

| 决策 | 落点 | 与原计划差异 |
|------|------|--------------|
| `WeightGrid` 字段 | 仍拆成 `tech` / `macro` / `news` 三个独立 `list[float]` + 2 个 Optional 嵌套 | 原计划用 `tech_macro_news: list[tuple]`，但前端表单已是独立字段，强行打包会破坏 `BacktestConfigIn` 向后兼容 |
| 共享 5 维字段常量 | 提到 schema 顶部 `TREND_DIM_FIELDS` / `MACRO_DIM_FIELDS` | 原计划要等 Step F 提取到 `static/backtest-fields.js`；Step G 内嵌即可（Step F 仍然要做） |
| 后台任务持有 | 抽到 `services/background.py::_spawn_background` | 原计划共用 `main.py::_spawn_background`；但 endpoint 反向 import main 会循环依赖，故提取独立模块 |
| 强引用 set 隔离 | `conftest._reset_db` 开头 `_BACKGROUND_TASKS.clear()` | 原计划用 `asyncio.gather`；实测发现**前一个测试可能用已关闭 loop spawn** task，gather 报「attached to a different loop」—— 直接 clear + 单元测试显式 await `_wait_for_status` 更稳 |

**Commit 3 · UI 高级模式编辑器（下一批启动）**：

1. `static/backtest.html`：`<details id="advPanel">` 折叠面板 + 5×2 个 number input + `#asyncOn` 复选 + `#runBtnAsync` + `#asyncProgress` 进度条
2. `static/backtest-chart.js`：CSS 注入 `.adv-panel` / `.progress-bar` / `.grp-grid`
3. `static/i18n/{zh-CN,en-US,zh-TW}.js`：3 文件同步加 `backtest.advanced_title` 等 7 个 key
4. `getSelectedParams()` 加 `trend_weights` / `macro_weights` 分支；新增 `runBacktestAsync()` + `pollBacktask()` 函数

**commit 切分**：3 个 commit
1. ✅ `dbf9239` `feat(backtest): WeightGrid 支持嵌套 + 上限 1000`
2. ✅ `77d33a5` `feat(backtest): 异步回测接口 + task_id 轮询`
3. ⏳ `feat(ui): 回测页高级模式 · trend_5/macro_5 编辑器 + 异步进度`

---

#### Step E · 动态化宏观阈值（Week 2-3）

**目标**：`best = 近 252 日 90 分位`，`worst = 10 分位`，每日 07:00 BJT 与快照同步刷新。

**文件改动**：
1. 新建 `src/app/services/macro_thresholds.py`：
   ```python
   class MacroThresholdCalculator:
       """滚动百分位阈值计算器"""

       WINDOW_DAYS = 252
       HIGH_PCT = 90   # 90 分位 = friendly_score = 100
       LOW_PCT = 10    # 10 分位 = friendly_score = 0

       async def compute(self, target: str, history: list[dict]) -> dict:
           """返回 {best: float, worst: float}"""
           ...

       async def get_or_compute(self, target: str) -> tuple[float, float]:
           """带 24h TTL 缓存"""
           ...
   ```

2. `src/app/services/macro.py:_friendly_score()`：把硬编码的 `best/worst` 改为运行时调用 `MacroThresholdCalculator`。
   - 数据不足（< 60 个交易日）→ 回退硬编码默认值（V0.77.2 现状）

3. `src/app/services/scheduler.py`：每日 07:00 BJT 在 `daily_capture_loop` 内串联预热 `MacroThresholdCalculator` 缓存。

4. `src/app/api/v1/endpoints/market.py`：`GET /market/gold/trend` 响应 `freshness.thresholds` 字段新增 `macro_dynamic: bool`，告诉用户当前用的是动态还是静态阈值。

5. `static/trend.html`：在「宏观因子」面板加小角标 `[动态 / 静态]`。

**测试改动**：
- `tests/test_services/test_macro_thresholds.py`（新增，约 20 例）
  - 滚动百分位计算正确性（已知历史数据 → 期望 90/10 分位）
  - 数据不足回退
  - 24h TTL 缓存命中/失效
  - 缓存 key 隔离（target + date）
- `tests/test_services/test_macro.py`：增 5 例验证 `_friendly_score` 改用动态值

**commit 切分**：4 个 commit
1. `feat(macro): MacroThresholdCalculator · 滚动百分位`
2. `refactor(macro): _friendly_score 改用动态阈值`
3. `feat(scheduler): 每日 07:00 BJT 预热宏观阈值缓存`
4. `feat(api): /market/gold/trend 暴露 macro_dynamic 字段`

---

#### Step F · 技术面 5 维度重构（Week 3-5）

**目标**：保留 5 维度 UI，内部按组平均（趋势组 / 超买组 / 风险组），降低内部相关性。

**文件改动**：
1. `src/app/services/trend.py:501-595`：维度计算输出 `DimensionScore`（Step D 已引入）后，**合成阶段**改为：
   ```python
   GROUP_WEIGHTS = {
       "trend": 0.50,    # 结构 + 动量
       "overbought": 0.30,   # RSI + 支撑（乖离）
       "risk": 0.20,    # 回撤
   }
   GROUP_MAPPING = {
       "结构": "trend", "动量": "trend",
       "动能": "overbought", "支撑": "overbought",
       "回撤": "risk",
   }
   def combine_by_group(dims: dict[str, Optional[float]]) -> float:
       groups = {"trend": [], "overbought": [], "risk": []}
       for name, val in dims.items():
           if val is not None:
               groups[GROUP_MAPPING[name]].append(val)
       return sum(
           GROUP_WEIGHTS[g] * (sum(vs) / len(vs) if vs else 50)
           for g, vs in groups.items()
       )
   ```

2. `schemas/settings.py`：`WeightConfig` 增字段 `group_combine: bool = True`，用户可关闭回归单维度加权。

3. `static/weights.html`：UI 加 "维度组合方式" 选项（单维度 / 组内平均）。

4. **回测联动**：用 V0.79.0 Step G 的内部权重扫描能力，**先用 `services/backtest.py` 在 2024-2026 历史数据上对比两种方案**，选出 Sharpe 更优的作为默认。

**测试改动**：
- `tests/test_services/test_trend.py`：增 8 例
  - 5 维度全有效时组内平均正确性
  - 单维度缺失时该组用 50 兜底
  - 整组缺失时（罕见）其它组权重归一
  - `group_combine=False` 时回退旧单维度加权

**commit 切分**：5 个 commit
1. `refactor(trend): combine_by_group · 组内平均`
2. `feat(settings): WeightConfig 增 group_combine 开关`
3. `feat(ui): 权重配置页维度组合方式选择`
4. `test(backtest): 对比单维度 vs 组内平均 Sharpe`
5. `docs: parameter-evaluation §3.3 验证结论`

---

#### Step H · 样本阈值分层（Week 5）

**目标**：总样本 10 / 分维度 5；UI 灰色小字 "样本 N，仅供参考"。

**文件改动**：
1. `src/app/services/backtest.py:41` + `review.py:71` + `resonance.py:40` 三处硬编码抽常量：
   ```python
   MIN_SAMPLES_OVERALL = 10   # 总体命中率
   MIN_SAMPLES_BUCKET = 5     # 分维度（方向 / horizon / basis）
   ```

2. `src/app/api/v1/endpoints/review.py`：响应增 `sample_warning: Optional[str]`，当 `n < MIN_SAMPLES_OVERALL` 时填 "样本 N < 10，仅供参考"。

3. `static/review.html`：命中统计卡片在 `sample_warning` 非空时显示灰色小字。

**测试改动**：
- 3 处各增 2 例样本阈值边界
- 共 6 例

**commit 切分**：1 个 commit `refactor: 样本阈值分层 · 总体 10 / 分维度 5`

---

### 2.3 V0.79.0 发布前 Checklist

```bash
# 同 V0.78.0，外加：
uv run python scripts/check_docs_claims.py   # 410+ 处
git tag -a v0.79.0 -m "V0.79.0 · 阈值动态化 + 回测增强"
```

**Step G Commit 3（UI 收口）启动前的前置门禁**：
```bash
uv run python -m pytest tests/test_api/test_async_backtest.py tests/test_api/test_backtest_api.py tests/test_services/test_backtest_service.py -q   # 56 例应全绿
uv run ruff check src tests   # 0 error
node scripts/check_clus_render.mjs   # UI 渲染断言（待 Commit 3 后回归）
uv run python scripts/check_static_js.py   # 静态 JS 引用一致性
```

---

## 3. V0.80.0 · 决策网格化 + 仓位结合

**主题**：**决策可执行化**——决策矩阵网格化、`position_ratio` 真正结合账户本金（P3 #12 闭环）。
**预计时间**：2-3 月（2026-11-23 至 2027-01-31）
**预计 commit 数**：10-15 个

### 3.1 改进项

| ID | 改进 | 优先级 | 工作量 | 来自 parameter-evaluation.md |
|----|------|--------|--------|----------------------------|
| I | 阈值带自适应 | P2 | 2 月 | §3.8 + parameter-evaluation §4.3 |
| J | 决策矩阵网格化 + 仓位结合 | P2 | 2 月 | §3.4 + P3 #12 |

**前置**：依赖 V0.78.0 决策补全 + V0.79.0 回测增强。

### 3.2 详细实施步骤（概览）

#### Step I · 阈值带自适应

1. `schemas/backtest.py`：`ThresholdBand` 默认值改为 `bullish=[50, 55, 60, 65, 70]` × `bearish=[50, 45, 40, 35, 30]`（5×5=25 组）
2. `static/backtest.html`：UI 显示 25 组扫描热力图（x=bullish, y=bearish, color=Sharpe）
3. 文档：`docs/parameter-evaluation.md` §3.1 同步说明

#### Step J · 决策矩阵网格化 + 仓位结合

1. `src/app/schemas/decision.py`：决策矩阵改为 `DecisionMatrix = dict[(idx_bucket, pnl_bucket, position_state), DecisionOut]`
2. `src/app/services/decision.py`：决策函数改为查表（O(1) 而非多 if/elif）
3. `src/app/services/decision.py:_suggest_position()`：结合 `accounts.current_capital` 计算 `position_ratio = position_value / capital`，不再是恒为 0
4. `src/app/services/position.py`：`portfolio_summary()` 返回 `current_capital`（聚合所有账本未平仓持仓成本）
5. `static/synthesis-card.js`：结论卡显示「建议仓位 60% · 当前本金 ¥X · 应持仓 ¥Y」

### 3.3 V0.80.0 发布

合并 4 周开发 → V0.80.0 标签发布。

---

## 4. V0.82.0+ · 多市场独立校准 + 长线

**主题**：**多市场 + 收尾**。
**预计时间**：2-3 月（2027-02-01 至 2027-04-30）
**预计 commit 数**：8-12 个

### 4.1 改进项

| ID | 改进 | 优先级 | 工作量 | 备注 |
|----|------|--------|--------|------|
| K | 多市场参数差异化（白银 / 黄金 / ETF） | P3 | 2 月 | parameter-evaluation §4.3 |

### 4.2 长线方向（V0.83.0+）

- **公开部署真实域名**（P3 #16）—— 等用户提供域名 + 证书
- **模拟交易**（P3 #13）—— 不落真实流水，验证策略后切主路径
- **多设备同步**（P3 长线）—— 业务表 `user_id` 隔离后支持云端同步
- **主题 / 无障碍完善**（P3 长线）—— axe-core 自动化守卫

---

## 5. 并行线：V0.75.2 / V0.75.3 认证收尾

**与主路线解耦**，独立推进。建议穿插在 V0.78.0 与 V0.79.0 之间。

### 5.1 V0.75.2 · 数据隔离（业务表加 user_id）

**预计时间**：2-3 周（2026-10 中旬开始）
**风险**：高（涉及几乎所有业务表 + API）

> ⚠ **本清单已于 2026-10-06 按本地库 `PRAGMA table_info` 实测重写。** 原文的 8 张表里有
> **4 处与实现脱节**：写了一个并不存在的「央行设置」表、把 `analysis_records` 记成了
> ``analysis_history``、并把 `gold_price_daily` 与 `central_bank_purchases` 这两张
> **全局市场数据**当成用户数据；同时**漏列了 4 张真正的用户数据表**。
> 照原文施工会白做一部分，又恰好漏掉真正的泄露面。

**隔离清单（按实测分类）**

一、**用户数据 · 已有 `user_id` 列**（V0.62.0 起就在，库内取值确为 1）
- `accounts`、`positions`、`sessions`、`telemetry_events`
- ⚠ 缺陷**不在「有没有列」，而在「没人读它」**：仓储签名写作 `user_id: int = 1`
  （字面量默认值），全仓无一处传入真实用户 ⇒ 过滤条件恒等于「不过滤」。
- 更严重的是 ID 寻址的方法**完全没有用户过滤**：`get()` / `list_trades()` 可凭 id
  跨用户读，`add_trade()` / `soft_delete()` / `restore()` 可跨用户写。

二、**用户数据 · 需新增 `user_id` 列**（列入本版迁移）
- `trade_records`（交易流水）、`news_scores`（用户消息面打分）、
  `analysis_records`（机会分析记录）、`push_subscriptions`（推送订阅；其模型注释
  本就写明「V0.75+ 多用户时加 user_id 列 + 扩唯一键」）

三、**混合表 · 需单独设计**（不能一次性全表加列）
- `app_settings` 以 `key` 为主键，而表内 `weight_config`（用户权重）与
  `vapid_keys`（**服务级**推送密钥）**混在一起**。直接加 `user_id` 并全表过滤，
  会把服务密钥一并圈进用户维度、打断推送。计划：改 `(user_id, key)` 复合主键，
  服务级键以约定值（如 `user_id=0`）落库并在用户级查询里显式排除。

四、**全局数据 · 明确不加 `user_id`**
- `gold_price_daily`（行情日历）、`central_bank_purchases`（IMF IRFCL / WGC 各国
  季度净购金，唯一键是「国家 + 季度」）、`daily_snapshots`（每日评估基线序列）
- `daily_snapshots` 尤其要注意：它由**调度器**在后台任务里用
  `TrendService(settings=None, news=None)` 写入（无请求上下文），且回测直接读整条
  序列。加 `user_id` 会同时破坏调度器与回测；若要让快照「按用户」，那是另一个
  产品决策（每人一条序列 + 每人一份回测），**不在本版范围**。

**实施步骤**
1. 迁移：仅对「第二类」4 张表加 `user_id`（默认 1）+ 索引 `ix_{table}_user_id`；
   把现有行归入 `LEGACY_USER_ID = 1`。
   ⚠ 勿在迁移前 `create_all`（争锁 → 启动 hang）。
2. 仓储层：所有查询解析当前用户 —— **这才是本版的核心，不是「加列」**。
   - ✅ **已交付（2026-10-06 · 第 1 批）**：新增 `src/app/utils/user_scope.py`
     （把 `user_id` 的 contextvar 抽到中立模块 + `current_user_id()` 解析器）；
     `PositionRepository` / `AccountRepository` 共 **22 处**恢复真实用户解析，
     并**补齐 ID 寻址方法的过滤与归属校验**；新增回归测试
     `tests/test_services/test_user_isolation.py`（**8 例**，覆盖读/写越权与
     解析器三条语义）。
   - ⏳ 待办：`NewsScoreRepository` / `AnalysisRepository` / `PushRepository`
     同样处理（依赖第 1 步的加列）。
3. API 层：**实测无需**「给所有业务接口加 `Depends(get_current_user)`」——
   `AuthMiddleware` 在 `AUTH_ENABLED=true` 时已对全部 `/api/` 做 401 门禁，并把用户
   写进 contextvar；缺的只是仓储层去读。真正要做的是两件事：
   - 给仓储层被**系统级调用**的入口显式传 `user_id`（已改：
     `main._ensure_default_account` 传 `LEGACY_USER_ID`），否则多用户模式下解析器
     会抛 `MissingUserContextError` —— 这是**有意的**：静默回退到 1 号用户会让
     匿名/越权调用读到他人数据；
   - 越权一律返回 404 而非 403，避免以状态码差异泄露「该 id 存在但不属于你」。
4. 测试：每个接口增 2 例 —— 「用户 A 创建的持仓，用户 B 不能读到 / 不能改」。
   仓储层已覆盖（8 例）；**API 层（真登录两个账号、带 cookie 与 CSRF）待补**。
5. 数据迁移：现有数据归入 `LEGACY_USER_ID = 1`（`accounts` / `positions` 已是 1，
   新增列的 4 张表需回填）。

### 5.2 V0.75.3 · 找回密码 + 用户管理 ✅ 已交付（2026-10-08，V0.81.0）

**预计时间**：1-2 周（实际 1 天完成，5 个 commit）
- 邮件发送：复用 V0.72.0 SMTPNotifier
- Token 表：`password_reset_tokens`（24h TTL，**只存 sha256 哈希**）
- 用户管理页 `/static/admin/users.html`：列出所有用户、改密、禁用、删除
- 鉴权：`require_owner` 角色鉴权（与服务级 `X-Admin-Token` 是两个维度，勿混）+ 三条防自锁
- 发版说明：见 `docs/releases/v0.81.0.md`；次日 hotfix 见 `docs/releases/v0.81.1.md`

---

## 6. 维护线：每 2 周一个 V0.7x.y 小版本

| 小版本 | 时间 | 内容 |
|--------|------|------|
| V0.78.2 | ✅ 2026-10-05（**同日第二个补丁版**） | 门禁可信度修复：八道门禁加 `if: always()`、PWA 门禁补 14 例常驻测试、`SHELL_ASSETS` 307 条目确认不可改并写清理由 + 加回归锁、ruff 升级、五个 Action 升 Node 24。**刻意不做 `uv lock --upgrade`**（含 `sqlalchemy 2.0 → 2.1` 跨大版本，有容器启动崩溃前科）→ 记入 V0.79.1 |
| V0.78.1 | ✅ 2026-10-05（**早于 10 月底排期**） | Bugfix 收口：SW 缓存版本脱钩 + PWA 快捷方式两条 404 + `compute_resonance` 缺维兜底 + 补 `starlette` 依赖声明；并新增 PWA 资源 / 死链 / 依赖声明三道门禁接入 CI。原排期的「社区反馈 / 监控告警」顺延至后续补丁版 |
| V0.79.1 | 11 月底 | Bugfix + 依赖升级（`uv lock --upgrade`） |
| V0.79.2 | 12 月中 | 测试扩充（覆盖率从 0 起步建基线，**目标 ≥ 60%**） |
| V0.80.1 | ✅ 2026-10-08（**提前**） | Bugfix：prod 写端点自动附加 `X-Admin-Token`（`auth.js` 全局 fetch 打补丁）。原排期 2027-02 |
| V0.81.1 | ✅ 2026-10-08（**同日第二个补丁版**） | Bugfix：admin token 缺失提示横幅（401 + `admin token required` 时引导去设置页，每会话一次）。**提前于任何排期** —— 是 V0.80.1 的直接后遗症。见 `docs/releases/v0.81.1.md` |
| V0.82.0 | ✅ 2026-10-09（**提前于 2027-04 排期**） | LAN 多终端 admin token 修：双通道（header + cookie）+ 单用户模式 `AUTH_ENABLED=false` 整体豁免；settings 页「设置 Session」按钮一次配置整浏览器生命周期有效。含中间件测试隔离修复（`f46838b`）。**重大语义调整**：原本 V0.82 规划是「多市场独立校准」，改为优先解决 LAN 真实痛点（多终端写操作被 401）；多市场 K 顺延至 V0.83+。见 `docs/releases/v0.82.0.md` |

**维护任务清单**（每小版本至少 1 项）：
- [ ] `ruff check` 警告清零
- [ ] 依赖升级：`uv lock --upgrade` → 跑全量回归
- [ ] 测试扩充：新功能 PR 至少 +10 测试
- [ ] 文档同步：版本号、页数、端点数刷新
- [ ] 静态门禁：JS + 渲染 + 文档声明 三关全绿

---

## 7. 路线图甘特图（文字版）

```
       W40   W41   W42   W43   W44   W45   W46   W47   W48   W49   W50   W51   W52
2026  ──┬────┬────┬────┬────┬────┬────┬────┬────┬────┬────┬────┬────┬────
        │    │    │    │    │    │    │    │    │    │    │    │    │
主路线  │V78 ──┤    V79 ──────────────────┤    V80 ──────────────────┤  V82+
        │ A B │    G  │  E  │  F  │  H   │    I  │  J                │  K
        │ C D │       │     │     │      │                          │
认证    │     │ V75.2 ───────┤V75.3─┤                              │
        │     │             │      │                              │
维护    │  .1 │             │  .1  │                              │  .1
        │    │             │      │                              │
       ──┴────┴────┴────┴────┴────┴────┴────┴────┴────┴────┴────┴────┴────
       10-08  10-15 10-22 10-29 11-05 11-12 11-19 11-26 12-03 12-10 12-17 12-24
```

---

## 8. 立即可启动的下一步（V0.79.0 Step G Commit 3）

今天（2026-10-06）可以做的：

1. **不需要建分支**：Step G Commit 1（`dbf9239`）+ Commit 2（`77d33a5`）已在 main 合并，Commit 3 沿用同一主线。

2. **读 Commit 1 实现沉淀**：先看 `src/app/schemas/backtest.py:14-41`（`TREND_DIM_FIELDS` / `MACRO_DIM_FIELDS` 常量）、`NestedWeights` 基类，确认 UI 要暴露的字段名集合。

3. **UI 改造**（按 §2.2 Step G Commit 3 计划）：
   - `static/backtest.html`：`<details id="advPanel">` + 5×2 number input + `#runBtnAsync` + `#asyncProgress`
   - `static/backtest-chart.js`：`injectCSS()` 加 `.adv-panel` / `.progress-bar` / `.grp-grid`
   - `static/i18n/{zh-CN,en-US,zh-TW}.js`：3 文件同步 7 个新 key

4. **端到端手测**（必须有真实浏览器或 puppeteer）：
   ```bash
   MARKET_PROVIDER=mock uvicorn app.main:app --port 8899 &
   # 在 backtest 页勾选「启用 trend_5」→ 填 5 个值（验证 sum≈1.0 提示）→ 提交 → 应自动切到 /run-async 并显示进度条
   ```
   ⚠ **MEMORY 规则**：「前端 undefined 字面量排查」—— UI 渲染必须用 puppeteer 实跑，参考 `/tmp/check_portfolio.mjs`，不能仅凭静态阅读断言。

5. **跑门禁**：
   ```bash
   node scripts/check_clus_render.mjs
   uv run python scripts/check_docs_claims.py
   uv run python scripts/check_static_js.py
   uv run ruff check src tests
   uv run ruff format --check src tests
   ```

6. **commit**：`feat(ui): 回测页高级模式 · trend_5/macro_5 编辑器 + 异步进度`

预计半天即可完成 Commit 3，之后即可启动 Step E（动态化宏观阈值，§2.2 Week 2-3）。

---

## 9. 风险与缓解

| 风险 | 概率 | 影响 | 缓解 |
|------|------|------|------|
| **决策矩阵改档位 → 现有用户的 BUY 信号消失** | 高 | 中 | 在 `static/portfolio.html` 决策面板加「旧档位 vs 新档位」对比卡，标注「本版本起调整」 |
| **动态宏观阈值回退默认值时与历史数据回测不可比** | 中 | 中 | 回测结果保留 `thresholds_mode: dynamic / static` 字段，让用户对比 |
| **V0.75.2 数据隔离改太多 API 导致回归测试大面积失败** | 中 | 高 | 先在测试分支做 1 周的「逐步迁移」（每个 API 单独改 + 测试），不一次性全改 |
| **V0.78.0 抽阈值后某个边界场景被遗漏** | 中 | 低 | 全量回归 + 比对参数化测试（parametrize）覆盖所有 0-100 分边界 |
| **UI 渲染门禁（V0.77.0 起 125 条）随版本增长膨胀** | 低 | 低 | 每 100 条做一次重构（按场景合并） |

---

## 10. 关键里程碑与发布节奏

| 日期 | 版本 | 里程碑 |
|------|------|--------|
| 2026-10-13 | V0.78.0 | 阈值口径统一 + 决策补全 |
| 2026-11-22 | V0.79.0 | 阈值动态化 + 回测增强 |
| 2026-12 底 | V0.75.2 | 认证 · 数据隔离 |
| ✅ 2026-10-08（原排期 2027-01 中） | V0.75.3 | 认证 · 找回密码 + 用户管理页（**已交付**，收口于 V0.81.0） |
| ✅ 2026-10-07（原排期 2027-01-31） | V0.80.0 | 决策网格化 + 仓位结合 |
| ✅ 2026-10-08 | V0.81.0 | V0.75.3 收口发版（同日 hotfix V0.81.1） |
| 2027-04-30 | V0.82.0 | 多市场独立校准 |

**发布周期**：
- 主版本（V0.78 / V0.79 / V0.80 / V0.82）：6-12 周一个
- 小版本（V0.7x.y）：2 周一个，仅维护性

---

## 附录 A · 当前路线图与 parameter-evaluation.md 的对应关系

| 路线图版本 | 包含 parameter-evaluation 改进项 |
|------------|-------------------------------|
| V0.78.0 | A, B, C, D |
| V0.79.0 | E, F, G, H |
| V0.80.0 | I, J |
| V0.82.0+ | K |

**11 项改进全部覆盖**，无遗漏。

---

## 附录 B · 与 development.md §11 改进计划的对账

| development.md §11 项 | 状态 | 路线图覆盖 |
|----------------------|------|------------|
| P1 #1-6（CI / Alembic / 行情源 / 多账户） | ✅ 已完成 | — |
| P2 #7-11（共振 / 克数 / 多时间框架 / 回测 / 多品种） | ✅ 已完成 | — |
| P3 #12 仓位推荐 | 🟡 半成品 | **V0.80.0 J** 闭环 |
| P3 #13 模拟交易 | 🟡 半成品 | **V0.83.0+** |
| P3 #14 指数曲线 | ✅ | — |
| P3 #15 监控告警 | 🟡（数据源失败告警未做） | **V0.79.x 维护线** 排期 |
| P3 #16 公开部署 | 🟡 | **V0.83.0+** 等用户提供域名 |
| 6.5 个性化与上下文记忆 | 🟡 | **V0.79.0 F** 部分覆盖 |
| 6.9 加载与离线 | ✅ | — |
| 6.11 研判复盘 | ✅ | — |
| V0.75.0 认证 | 🟡 第①步 | **V0.75.2 / V0.75.3** |
| V0.75.1 结论卡 | ✅ | — |
| V0.76.0 消息面打分器 | ✅ | — |

---

**文档完成时间**：2026-10-05
**下次更新时机**：V0.78.0 发布后，更新"已完成"状态与"实际耗时 vs 预计"对账
