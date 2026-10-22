"""Add isolated sandbox billing ledger.

Revision ID: 20261019_0007
Revises: 20261010_0006
"""
from alembic import op
import sqlalchemy as sa

revision = "20261019_0007"
down_revision = "20261010_0006"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("billing_accounts", sa.Column("user_id", sa.BigInteger(), primary_key=True))
    op.create_table("billing_checkouts",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("request_key", sa.String(64), nullable=False),
        sa.Column("provider_id", sa.String(128), unique=True),
        sa.Column("order_id", sa.String(128), unique=True),
        sa.Column("product_id", sa.String(128), nullable=False),
        sa.Column("state", sa.String(32), nullable=False),
        sa.Column("url", sa.String(2048)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("user_id", "request_key"))
    op.create_index("ix_billing_checkouts_user_id", "billing_checkouts", ["user_id"])
    op.create_table("billing_entries",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("source", sa.String(255), nullable=False, unique=True),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("delta", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_billing_entries_user_id", "billing_entries", ["user_id"])
    op.create_table("billing_events",
        sa.Column("id", sa.String(255), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))


def downgrade():
    op.drop_table("billing_events")
    op.drop_table("billing_entries")
    op.drop_table("billing_checkouts")
    op.drop_table("billing_accounts")
