"""Lifetime introductory allowance and durable simulation runs."""
from alembic import op
import sqlalchemy as sa

revision = "20261023_0008"
down_revision = "20261019_0007"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("runs", sa.Column("intro_state", sa.String(16), nullable=True))
    # Existing owned workflows count conservatively; deploy only after draining.
    op.execute(sa.text("""UPDATE runs SET intro_state = CASE
        WHEN lifecycle_status = 'queued' THEN 'reserved'
        WHEN lifecycle_status IN ('running', 'completed') THEN 'consumed'
        WHEN EXISTS (SELECT 1 FROM run_events WHERE run_events.run_id = runs.run_id
            AND run_events.event_type IN ('run.started', 'run.claimed')) THEN 'consumed'
        ELSE 'released' END WHERE owner_github_user_id IS NOT NULL"""))
    op.create_table("simulation_runs",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("request_key", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("result", sa.JSON(), nullable=False),
        sa.UniqueConstraint("user_id", "request_key"))
    op.create_index("ix_simulation_runs_user_id", "simulation_runs", ["user_id"])


def downgrade():
    op.drop_table("simulation_runs")
    op.drop_column("runs", "intro_state")
