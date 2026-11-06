"""scoring_daily_wide 增 price_direction 列 + daily_snapshots.news_index 改可空（V0.121.1）

Revision ID: t2u3v4w5x6y
Revises: r2s3t4u5v6w
Create Date: 2026-11-06 06:00:00.000000

背景
----
本迁移一次性处理 V0.121.1 的两个 P0（都落在同一张表上，分两次 schema 变更
两次发版没有意义）：

**P0-2 · 「上涨天数」恒为 0 —— 治本（加列）**

命中分析页的「上涨天数」永远是 0，实测是**三层根因叠在一起**：

1. 口径根本不是「当日涨跌」—— ``daily_snapshots.direction`` = ``_detect_direction(
   closes, ma20)``（收盘价 vs MA20 + MA20 斜率），语义是「60 日窗口**趋势**方向」；
2. ``change_pct`` 也不是当日涨跌 —— 快照走 ``trend.analyze(days=60)``，
   ``change_pct`` 是 **60 日区间涨跌幅**（生产库实测 -12.68 / -11.83 / -10.64）；
3. 宽表列被**消息面方向**覆写 —— ``scoring_wide.py`` 里
   ``row.direction = direction_of(effective).value`` 把消息面方向
   （bullish / bearish / neutral）写进了**价格**方向列 ⇒ 一个列两套词表。

⇒ ``sum(1 for r in grp if r.direction == "up")`` 永远加不上。

**唯一可信的「当日涨跌」源**是 ``gold_price_daily.change_pct`` ——
模型注释明写「相对前一交易日的涨跌幅 %」。
⇒ 本迁移新增 ``price_direction`` 列（up / down / flat，**可空**）：
当日**没有**价格行时为 NULL（未知），**不兜底**（沿用 V0.78.0 Step D
「数据不足 ≠ 中性」的纪律）。
旧的 ``direction`` 列保留 —— 但它的语义被收窄为「趋势方向」，
不再承载消息面方向（覆写在代码侧删除，见本版 ETL 改动）。

**P0-3 · 64% 历史行带伪造消息面 50 分 —— 治源头（改可空）**

污染链（本轮实测打通）::

    trend.news.score = None（今天没打分）
       └─ services/snapshot.py → news_index = 50.0            ← 源头伪造
            └─ models/snapshot.py NOT NULL DEFAULT 50          ← 源头锁死
                 └─ 宽表 ETL 继承 snap.news_index               ⇒ 31 行假 50
                      └─ direction_of(50.0) = NEUTRAL（不是 None！）
                           └─ judge_hit(NEUTRAL, chg) → 按 ±0.3% 横盘判定
                                ⇒ 伪造出 14 个 hit_t1 / 12 个 hit_t5

⇒ ``daily_snapshots.news_index`` 必须**改可空**：只有「当天有 news_scores
记录」的日天才有分；没有 ⇒ NULL（未知），消费方显式跳过，不是中性 50。

SQLite 注意
-----------
SQLite 的 ``ALTER TABLE`` 不能直接去掉 ``NOT NULL`` ⇒ 必须走
``op.batch_alter_table(recreate="always")`` 重建表。
重建后**必须**核对 ``ix_daily_snapshots_snapshot_date``（UNIQUE）与
``idx_daily_snapshots_snapshot_date`` 两个索引仍在（batch 模式按反射结果重建）。

回滚说明
--------
``downgrade`` 把 ``news_index IS NULL`` 的行填回 50.0 —— 因为回滚目标
是**旧代码**（旧代码认为 news_index 恒非空，且用 50 表示「未打分」）。
这一步等于**主动重新引入伪造的 50 分**，只应作为紧急回滚路径使用；
一旦按新语义跑过一段时间，就**不应该**再回滚。

幂等
----
两个操作都先查现状（列是否已存在 / 是否已可空），可重复执行。
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "t2u3v4w5x6y"
down_revision: Union[str, Sequence[str], None] = "r2s3t4u5v6w"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SNAP = "daily_snapshots"
WIDE = "scoring_daily_wide"


def _columns(table: str) -> set[str]:
    """当前表里已有的列名（幂等判定用）。"""
    insp = sa.inspect(op.get_bind())
    return {c["name"] for c in insp.get_columns(table)}


def _is_nullable(table: str, column: str) -> bool:
    """该列当前是否可空（不可空时返回 False）。"""
    insp = sa.inspect(op.get_bind())
    for c in insp.get_columns(table):
        if c["name"] == column:
            return bool(c.get("nullable", True))
    return True


def upgrade() -> None:
    # ── P0-2：新增 price_direction 列（可空）──
    if "price_direction" not in _columns(WIDE):
        op.add_column(
            WIDE,
            sa.Column(
                "price_direction",
                sa.String(8),
                nullable=True,
                comment="当日涨跌方向 up/down/flat（NULL=当日无价格行，未知；V0.121.1）",
            ),
        )

    # ── P0-3：daily_snapshots.news_index 改可空 ──
    if not _is_nullable(SNAP, "news_index"):
        with op.batch_alter_table(SNAP, recreate="always") as batch_op:
            batch_op.alter_column(
                "news_index",
                existing_type=sa.Float(),
                nullable=True,
            )


def downgrade() -> None:
    # ── P0-3 逆：news_index 改回 NOT NULL ──
    # ⚠ SQLite 不允许 NULL ⇒ 先把 NULL 行填回 50.0（旧代码的「未打分」语义）。
    #    这一步等于重新引入伪造的 50 分，仅供紧急回滚使用。
    if _is_nullable(SNAP, "news_index"):
        op.execute(
            sa.text(
                f"UPDATE {SNAP} SET news_index = 50.0 WHERE news_index IS NULL"
            )
        )
        with op.batch_alter_table(SNAP, recreate="always") as batch_op:
            batch_op.alter_column(
                "news_index",
                existing_type=sa.Float(),
                nullable=False,
            )

    # ── P0-2 逆：删 price_direction 列 ──
    if "price_direction" in _columns(WIDE):
        with op.batch_alter_table(WIDE, recreate="always") as batch_op:
            batch_op.drop_column("price_direction")
