"""daily_snapshots 增加资金流面两列（V0.120.0）

Revision ID: r2s3t4u5v6w
Revises: n2o3p4q5r6a1
Create Date: 2026-10-28 15:40:00.000000

背景
----
V0.120.0 上了第 4 个评分面「资金流面」，但 ``daily_snapshots`` 里**没有它的位置**：

- ``tech_index`` / ``macro_index`` / ``news_index`` / ``macro_detail`` / ``tech_detail``
  都有 ⇒ 回测网格能重建「三维内部权重」；
- 资金流面既没有**面分**（``flow_index``）也没有**因子明细**（``flow_detail``）
  ⇒ 回测网格**永远进不去资金流面**（``_aggregate_from_detail`` 找不到任一维度
  即返回 None ⇒ 整根快照被跳过 ⇒ 跑出来是 0 行 —— V0.118.0 修过的同一个 bug）。

**现在不建网格**（V0.120.0 刻意不动：资金流面今天没有任何历史快照，
加了会让回测出 0 行），但**历史必须从今天开始攒** ——
资金流面约 1 年后才有资格进网格，届时若没有 per-factor 明细，
这 1 年就白等了。所以本迁移先把两列铺好：

- ``flow_index``（Float，可空）：资金流面分 0-100。
  **可空是刻意的**：``MoneyFlowIndexOut.score`` 允许为 ``None``
  （本轮一个因子都没取到真实读数 ⇒ 整面从综合指数剔除，**不是 0 分**），
  存成 0.0 会把「没数」误读成「极度利空」；
- ``flow_detail``（Text，可空）：6 个因子的 ``{value, score, direction, unit, data_date}``
  JSON，与 ``macro_detail`` 同构 ⇒ 将来加「资金流面内部权重」网格时可直接复用
  ``_aggregate_from_detail``。

历史行（迁移前已有的快照）两列都是 NULL ⇒ 语义是「该日没有资金流面数据」，
消费方**必须显式跳过**而不是用 50 兜底
（沿用 V0.78.0 Step D「数据不足 ≠ 中性」的纪律）。

幂等
----
列已存在时直接返回（可重复执行）。
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "r2s3t4u5v6w"
down_revision: Union[str, Sequence[str], None] = "n2o3p4q5r6a1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLE = "daily_snapshots"


def _columns() -> set[str]:
    """当前表里已有的列名（幂等判定用）。"""
    insp = sa.inspect(op.get_bind())
    return {c["name"] for c in insp.get_columns(TABLE)}


def upgrade() -> None:
    cols = _columns()
    if "flow_index" not in cols:
        op.add_column(
            TABLE,
            sa.Column(
                "flow_index",
                sa.Float(),
                nullable=True,
                comment="资金流面指数 0-100（V0.120.0；NULL=该日整面不可用，非 0 分）",
            ),
        )
    if "flow_detail" not in cols:
        op.add_column(
            TABLE,
            sa.Column(
                "flow_detail",
                sa.Text(),
                nullable=True,
                comment="资金流因子 JSON（V0.120.0 起 6 因子）",
            ),
        )


def downgrade() -> None:
    cols = _columns()
    if "flow_detail" in cols:
        op.drop_column(TABLE, "flow_detail")
    if "flow_index" in cols:
        op.drop_column(TABLE, "flow_index")
