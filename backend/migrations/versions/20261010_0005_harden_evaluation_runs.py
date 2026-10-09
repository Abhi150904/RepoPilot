"""Harden evaluation run ownership and benchmark snapshots.

Revision ID: 20261010_0005
Revises: 20261009_0004
Create Date: 2026-10-10
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20261010_0005"
down_revision: Union[str, None] = "20261009_0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("eval_runs", sa.Column("owner_key", sa.String(length=255), nullable=False, server_default="anonymous"))
    op.add_column("eval_runs", sa.Column("benchmark_snapshot_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")))
    op.create_index("ix_eval_runs_owner_key", "eval_runs", ["owner_key"])
    op.alter_column("eval_runs", "owner_key", server_default=None)
    op.alter_column("eval_runs", "benchmark_snapshot_json", server_default=None)


def downgrade() -> None:
    op.drop_index("ix_eval_runs_owner_key", table_name="eval_runs")
    op.drop_column("eval_runs", "benchmark_snapshot_json")
    op.drop_column("eval_runs", "owner_key")
