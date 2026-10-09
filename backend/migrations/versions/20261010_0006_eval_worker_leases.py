"""Add evaluation worker lease columns.

Revision ID: 20261010_0006
Revises: 20261010_0005
Create Date: 2026-10-10
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20261010_0006"
down_revision: Union[str, None] = "20261010_0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("eval_runs", sa.Column("worker_id", sa.String(length=128), nullable=True))
    op.add_column("eval_runs", sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("eval_runs", sa.Column("last_heartbeat_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_eval_runs_lease_expires_at", "eval_runs", ["lease_expires_at"])


def downgrade() -> None:
    op.drop_index("ix_eval_runs_lease_expires_at", table_name="eval_runs")
    op.drop_column("eval_runs", "last_heartbeat_at")
    op.drop_column("eval_runs", "lease_expires_at")
    op.drop_column("eval_runs", "worker_id")
