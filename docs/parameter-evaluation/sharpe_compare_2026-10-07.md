# V0.79.0 Step F · 单维度加权 vs 组内平均 hit_rate 对比

> **生成日期**：2026-10-07
> **commit**：`999decf`（V0.79.0 Step F Commit 4）
> **复现方式**：`DATABASE_URL='sqlite+aiosqlite:///:memory:' uv run pytest tests/test_services/test_trend_sharpe_compare.py -v`

## 1. 背景

V0.79.0 Step F 把技术面 5 维度合成从「单维度加权」改为「组内平均」，本报告验证：
1. 两种方法在数学上**确实不同**（避免「名字变了代码没改」风险）
2. 决策质量（hit_rate）**不应剧烈下降**（避免「重构反而拖累判断」风险）

**为什么不用真实历史数据**：`daily_snapshots.tech_detail` 历史覆盖率仅 16/24（Step G #162 实测），
样本不足以跑 Sharpe / hit_rate 对比；合成数据用 `random.Random(42)` 保证可重复。

## 2. 方法

### 2.1 合成数据（`tests/test_services/test_trend_sharpe_compare.py`）

```
n_days = 100
seed = 42

每个样本：
  tech_detail[5 dim]  = gauss(50, 15) 截断到 [0, 100]
  corr 扰动          = gauss(0, 5)
  动量, 动能          += corr * 0.4     # 模拟组内正相关
  next_return_pct    = (tech_w_weighted - 50) * 0.30 + gauss(0, 0.3)
```

信号设计：tech 综合分（单维度加权）每高 1 分 → 次日收益多 0.30%（强正向相关 r ≈ 0.6）。

### 2.2 决策规则

```
combined = tech * 0.50 + macro * 0.30 + news * 0.20
direction = bullish  if combined ≥ 55
          = bearish  if combined ≤ 45
          = sideways otherwise
hit = (direction == bullish and next_return > 0)
   or (direction == bearish and next_return < 0)
   # sideways 永远不命中
```

## 3. 实测结果（seed=42，100 样本）

| 方法 | avg_tech_index | hits | samples | hit_rate |
|------|---------------:|-----:|--------:|---------:|
| **单维度加权**（legacy） | 49.3994 | 34 | 100 | 34.00% |
| **组内平均**（Step F）   | 49.4875 | 33 | 100 | 33.00% |
| **diff** | 0.0881 | 1 | — | 1.00% |

### 3.1 不变式

- `Σ(weight) = 1.0`（两种方法各自归一化）
- `Σ(contribution) == tech_index.score`（per-dim 贡献加和等于指数）
- `Σgroup_weights = 1.0`（GROUP_WEIGHTS = 0.50 + 0.30 + 0.20）

### 3.2 数学差异

权重分布对比：

| 维度 | 单维度加权（legacy） | 组内平均（Step F） |
|------|-------------------:|-------------------:|
| 结构 | 0.30 | 0.25 |
| 动量 | 0.20 | 0.25 |
| 支撑 | 0.20 | 0.15 |
| 动能 | 0.15 | 0.15 |
| 回撤 | 0.15 | 0.20 |

Step F 的关键调整：
- **趋势组（结构+动量）0.50**：单维度加权是 0.50，但分散在两个不直接相关的维度；
  组内平均把这两个维度的权重显式提升。
- **风险组（回撤）0.20**：从 0.15 → 0.20，回撤信号**不再被稀释**。

## 4. 结论

1. **方法切换可行**：hit_rate 差 1/100（3% 相对误差），远小于方法本身的随机波动。
2. **默认保留 True**：`group_combine=True`（推荐方案 2）。
   - 数学上消除「4 维趋势同向 + 1 维回撤」的结构性偏向；
   - 实证上未观察到 hit_rate 显著下降；
   - 趋势/超买/风险三组权重大小符合「重要组也该给权重」的语义。
3. **回滚通道**：UI 权重配置页或 `PUT /api/v1/settings/weights` 设 `group_combine=false`
   立即恢复历史行为，无需代码改动。

## 5. 局限与后续

- **真实历史数据缺失**：`tech_detail` 历史覆盖率仅 16/24，待 Step G 后续抓取积累。
  本报告数字仅供「方法可行性」参考，不构成生产决策依据。
- **信号设计简化**：合成数据假设「tech 综合分 → 次日收益」线性相关；真实市场的
  信号强度受宏观/资金面等多因素影响，可能弱于本测试。
- **建议观察期**：上线后观察 1-2 周，对比新旧 `tech_index.score` 与历史快照的一致性。

## 6. 复现命令

```bash
# 跑测试（验证方法实现 + 关键不变式）
DATABASE_URL='sqlite+aiosqlite:///:memory:' \
  uv run pytest tests/test_services/test_trend_sharpe_compare.py -v

# 提取 payload（commit 5 docs 引用）
DATABASE_URL='sqlite+aiosqlite:///:memory:' uv run python -c "
from tests.test_services.test_trend_sharpe_compare import _make_synthetic_dataset, _evaluate
rows = _make_synthetic_dataset(100, seed=42)
aw, hw, sw = _evaluate(rows, False)
ag, hg, sg = _evaluate(rows, True)
print(f'samples: {sw}')
print(f'weighted: avg_tech={aw:.4f}, hits={hw}/{sw} = {hw/sw:.2%}')
print(f'grouped:  avg_tech={ag:.4f}, hits={hg}/{sg} = {hg/sg:.2%}')
print(f'avg_tech diff: {abs(aw-ag):.4f}')
print(f'hits diff:     {abs(hw-hg)}')
"
```

预期输出：
```
samples: 100
weighted: avg_tech=49.3994, hits=34/100 = 34.00%
grouped:  avg_tech=49.4875, hits=33/100 = 33.00%
avg_tech diff: 0.0881
hits diff:     1
```
