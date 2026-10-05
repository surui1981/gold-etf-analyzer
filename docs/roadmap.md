# 开发版本推进线路图（V0.78.0 → V0.82.0+）

> **配套文档**：
> - [parameter-evaluation.md](parameter-evaluation.md) — **8 项参数问题诊断 + 推荐新值**（本路线图的输入）
> - [development.md](development.md) §11 改进计划 — **P0-P3 大路线 + 状态补遗**
> - [ux-roadmap.md](ux-roadmap.md) — **应用 / UX 路线**（V0.68.0 → V0.77.2 已完成）
>
> **本文件范围**：把 parameter-evaluation.md 的改进项 + 其他后台任务排进具体版本，给出**每版本的实施步骤、commit 切分、测试与文档同步**。
>
> **基线版本**：V0.77.2（commit `5ffc650`，2026-10-03）
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
| A | 统一阈值常量 | P0 | 0.5 天 | §3.1 |
| B | 决策矩阵档位补全 | P0 | 1-2 天 | §3.4 |
| C | 共振信号扩展反向 | P1 | 0.5 天 | §3.5 | ✅ 已实现 2026-10-05 |
| D | 兜底策略差异化 | P0 | 1 天 | §3.7 |

### 1.2 详细实施步骤

#### Step A · 统一阈值常量（Day 1 上午）

**目标**：建 `schemas/thresholds.py`，把 5/45/55/60/70 五个常量从代码里抽出来集中管理。

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

### 2.1 改进项

| ID | 改进 | 优先级 | 工作量 | 来自 parameter-evaluation.md |
|----|------|--------|--------|----------------------------|
| G | 回测权重嵌套扩展 | P0 | 1 周 | §3.6 |
| E | 动态化宏观阈值 | P0 | 1-2 周 | §3.2 |
| F | 技术面 5 维度重构（组内平均） | P1 | 2-3 周 | §3.3 |
| H | 样本阈值分层 | P2 | 0.5 天 | §3.8 |

**依赖**：F 必须等 G 完成（否则无法回测扫内部权重）。

### 2.2 详细实施步骤

#### Step G · 回测权重嵌套扩展（Week 1）

**目标**：`WeightGrid` 支持嵌套（`trend_5` / `macro_5` 字典形式），上限 125 → 1000。

**文件改动**：
1. `src/app/schemas/backtest.py`：
   ```python
   class WeightGrid(BaseModel):
       tech_macro_news: list[tuple[float, float, float]] = [(0.30, 0.40, 0.30), (0.40, 0.40, 0.20), (0.30, 0.30, 0.40), (0.40, 0.30, 0.30), (0.50, 0.40, 0.10)]
       trend_5: list[dict[str, float]] | None = None
       # 例: [{"结构": 0.30, "动量": 0.20, "支撑": 0.20, "动能": 0.15, "回撤": 0.15}, ...]
       macro_5: list[dict[str, float]] | None = None
   ```

2. `src/app/services/backtest.py:itertools.product(...)`：组合计算改为笛卡尔积嵌套，先 tech_macro_news 再 trend_5 再 macro_5。**上限校验**改为 1000。

3. 新增异步接口 `POST /api/v1/backtest/run-async`：
   - 返回 `task_id`，客户端轮询 `GET /backtest/result/{task_id}`
   - 任务用 `asyncio.create_task` 或 FastAPI BackgroundTasks
   - UI 用进度条（`static/backtest.html` 改造）

4. `static/backtest.html`：UI 加 "高级模式" 折叠面板，暴露 trend_5 / macro_5 编辑器（5 个数值 input，必须和=1.0）。

**测试改动**：
- `tests/test_services/test_backtest.py`：增 10 例
  - 嵌套权重笛卡尔积计算正确性
  - 上限 1000 校验
  - 异步任务接口响应格式
  - 任务取消时清理

**commit 切分**：3 个 commit
1. `feat(backtest): WeightGrid 支持嵌套 + 上限提升`
2. `feat(backtest): 异步回测接口`
3. `feat(ui): 回测页高级模式 · 内部权重编辑器`

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

**实施步骤**：
1. 加 `migrations/versions/<hash>_add_user_id_to_business_tables.py`：
   - `positions.user_id` / `accounts.user_id` / `news_scores.user_id` / `daily_snapshots.user_id` / `gold_price_daily.user_id` / `analysis_history.user_id` / `central_bank_purchases.user_id` / `central_bank_settings.user_id`
   - 索引：`idx_{table}_user_id`
2. 仓储层：`PositionRepository.list()` / `AccountRepository.list()` 等所有读路径加 `WHERE user_id = :current_user_id`
3. API 层：所有业务接口加 `Depends(get_current_user)`，从 contextvar 取 user_id
4. 测试：每个 API 接口增 2 例——「用户 A 创建的持仓，用户 B 不能读到 / 不能改」
5. 数据迁移：现有数据归入 `LEGACY_USER_ID = 1`

### 5.2 V0.75.3 · 找回密码 + 用户管理

**预计时间**：1-2 周
- 邮件发送：复用 V0.72.0 SMTPNotifier
- Token 表：`password_reset_tokens`（24h TTL）
- 用户管理页 `/static/admin/users.html`：列出所有用户、改密、禁用、删除

---

## 6. 维护线：每 2 周一个 V0.7x.y 小版本

| 小版本 | 时间 | 内容 |
|--------|------|------|
| V0.78.1 | 10 月底 | Bugfix：使用 V0.78.0 后社区反馈 / 监控告警 |
| V0.79.1 | 11 月底 | Bugfix + 依赖升级（`uv lock --upgrade`） |
| V0.79.2 | 12 月中 | 测试扩充（覆盖率从 0 起步建基线，**目标 ≥ 60%**） |
| V0.80.1 | 2027-02 | Bugfix + 文档同步 |

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

## 8. 立即可启动的下一步（V0.78.0 Day 1）

今天（2026-10-05）可以做的：

1. **建分支**（不在 main 上直接改）：
   ```bash
   git checkout -b feat/v0.78.0-threshold-unification
   ```

2. **Step A 启动**：创建 `src/app/schemas/thresholds.py`，按 §1.2 Step A 模板填入。

3. **替换硬编码**：用 grep 列出所有 `>= 55` / `> 55` / `< 45` / `<= 45` / `>= 70` 位置，逐一替换。

4. **跑测试**：先跑 `tests/test_services/test_decision.py` `test_resonance.py` `test_news.py` `test_trend.py` 4 个核心文件，验证抽常量不改变行为。

5. **commit**：`refactor(schemas): 统一阈值常量到 schemas/thresholds.py`

预计 Day 1 上午即可完成 Step A，下午推进 Step B（决策矩阵档位补全）。

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
| 2027-01 中 | V0.75.3 | 认证 · 找回密码 |
| 2027-01-31 | V0.80.0 | 决策网格化 + 仓位结合 |
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
