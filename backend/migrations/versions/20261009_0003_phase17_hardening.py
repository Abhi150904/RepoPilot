"""Harden Phase 17 persistence tables.

Revision ID: 20261009_0003
Revises: 20261008_0002
Create Date: 2026-10-09
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20261009_0003"
down_revision: Union[str, None] = "20261008_0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint("uq_runs_idempotency_key", "runs", type_="unique")
    op.add_column("runs", sa.Column("idempotency_owner_key", sa.String(length=255), nullable=True))
    op.add_column("runs", sa.Column("worker_id", sa.String(length=128), nullable=True))
    op.add_column("runs", sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("runs", sa.Column("last_heartbeat_at", sa.DateTime(timezone=True), nullable=True))
    op.execute(
        "UPDATE runs "
        "SET idempotency_owner_key = "
        "CASE "
        "WHEN owner_github_user_id IS NULL THEN 'anonymous' "
        "ELSE 'github:' || owner_github_user_id::text "
        "END "
        "WHERE idempotency_key IS NOT NULL"
    )
    op.alter_column("runs", "owner_github_user_id", existing_type=sa.Integer(), type_=sa.BigInteger())
    op.alter_column("runs", "owner_installation_id", existing_type=sa.Integer(), type_=sa.BigInteger())
    op.create_unique_constraint(
        "uq_runs_idempotency_owner_key",
        "runs",
        ["idempotency_owner_key", "idempotency_key"],
    )

    op.create_table(
        "github_identities",
        sa.Column("github_user_id", sa.BigInteger(), nullable=False),
        sa.Column("github_login", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("github_user_id"),
    )
    op.create_table(
        "github_installations",
        sa.Column("installation_id", sa.BigInteger(), nullable=False),
        sa.Column("account_login", sa.String(length=255), nullable=True),
        sa.Column("repository", sa.String(length=512), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("installation_id"),
    )
    op.create_table(
        "publish_results",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("run_id", sa.String(length=64), nullable=False),
        sa.Column("mode", sa.String(length=32), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=True),
        sa.Column("branch_name", sa.String(length=255), nullable=True),
        sa.Column("pr_url", sa.String(length=1024), nullable=True),
        sa.Column("summary", sa.String(length=2048), nullable=True),
        sa.Column("result", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_publish_results_run_id", "publish_results", ["run_id"])


def downgrade() -> None:
    op.drop_index("ix_publish_results_run_id", table_name="publish_results")
    op.drop_table("publish_results")
    op.drop_table("github_installations")
    op.drop_table("github_identities")
    op.drop_constraint("uq_runs_idempotency_owner_key", "runs", type_="unique")
    op.drop_column("runs", "last_heartbeat_at")
    op.drop_column("runs", "lease_expires_at")
    op.drop_column("runs", "worker_id")
    op.drop_column("runs", "idempotency_owner_key")
    op.alter_column("runs", "owner_installation_id", existing_type=sa.BigInteger(), type_=sa.Integer())
    op.alter_column("runs", "owner_github_user_id", existing_type=sa.BigInteger(), type_=sa.Integer())
    op.create_unique_constraint("uq_runs_idempotency_key", "runs", ["idempotency_key"])
