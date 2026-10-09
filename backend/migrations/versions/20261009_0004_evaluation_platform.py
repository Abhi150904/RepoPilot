"""Add durable evaluation platform tables.

Revision ID: 20261009_0004
Revises: 20261009_0003
Create Date: 2026-10-09
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20261009_0004"
down_revision: Union[str, None] = "20261009_0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "eval_suites",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.String(length=2048), nullable=True),
        sa.Column("eval_type", sa.String(length=32), nullable=False),
        sa.Column("version", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name", "version", name="uq_eval_suites_name_version"),
    )
    op.create_table(
        "eval_cases",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("suite_id", sa.Integer(), nullable=False),
        sa.Column("case_key", sa.String(length=255), nullable=False),
        sa.Column("input_json", sa.JSON(), nullable=False),
        sa.Column("expected_json", sa.JSON(), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["suite_id"], ["eval_suites.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("suite_id", "case_key", name="uq_eval_cases_suite_case_key"),
    )
    op.create_index("ix_eval_cases_suite_id", "eval_cases", ["suite_id"])
    op.create_table(
        "eval_runs",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("suite_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("configuration_json", sa.JSON(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", sa.String(length=255), nullable=True),
        sa.Column("error_type", sa.String(length=255), nullable=True),
        sa.Column("safe_error_message", sa.String(length=2048), nullable=True),
        sa.Column("idempotency_key", sa.String(length=255), nullable=True),
        sa.Column("idempotency_owner_key", sa.String(length=255), nullable=True),
        sa.Column("payload_hash", sa.String(length=64), nullable=True),
        sa.ForeignKeyConstraint(["suite_id"], ["eval_suites.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("idempotency_owner_key", "idempotency_key", name="uq_eval_runs_idempotency_owner_key"),
    )
    op.create_index("ix_eval_runs_suite_id", "eval_runs", ["suite_id"])
    op.create_table(
        "eval_case_results",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("eval_run_id", sa.String(length=64), nullable=False),
        sa.Column("eval_case_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("output_json", sa.JSON(), nullable=False),
        sa.Column("measurements_json", sa.JSON(), nullable=False),
        sa.Column("error_type", sa.String(length=255), nullable=True),
        sa.Column("safe_error_message", sa.String(length=2048), nullable=True),
        sa.Column("duration_ms", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["eval_case_id"], ["eval_cases.id"]),
        sa.ForeignKeyConstraint(["eval_run_id"], ["eval_runs.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("eval_run_id", "eval_case_id", name="uq_eval_case_results_run_case"),
    )
    op.create_index("ix_eval_case_results_eval_run_id", "eval_case_results", ["eval_run_id"])
    op.create_index("ix_eval_case_results_eval_case_id", "eval_case_results", ["eval_case_id"])
    op.create_table(
        "eval_metrics",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("eval_run_id", sa.String(length=64), nullable=False),
        sa.Column("metric_name", sa.String(length=255), nullable=False),
        sa.Column("metric_value", sa.Float(), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(["eval_run_id"], ["eval_runs.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("eval_run_id", "metric_name", name="uq_eval_metrics_run_metric"),
    )
    op.create_index("ix_eval_metrics_eval_run_id", "eval_metrics", ["eval_run_id"])
    op.create_table(
        "llm_usage_events",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("run_id", sa.String(length=64), nullable=True),
        sa.Column("eval_run_id", sa.String(length=64), nullable=True),
        sa.Column("eval_case_id", sa.Integer(), nullable=True),
        sa.Column("request_id", sa.String(length=128), nullable=True),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("model", sa.String(length=255), nullable=False),
        sa.Column("role", sa.String(length=64), nullable=False),
        sa.Column("usage_source", sa.String(length=32), nullable=False),
        sa.Column("prompt_tokens", sa.Integer(), nullable=True),
        sa.Column("completion_tokens", sa.Integer(), nullable=True),
        sa.Column("total_tokens", sa.Integer(), nullable=True),
        sa.Column("estimated_cost_usd", sa.Float(), nullable=True),
        sa.Column("duration_ms", sa.Float(), nullable=True),
        sa.Column("success", sa.Boolean(), nullable=False),
        sa.Column("retry_count", sa.Integer(), nullable=False),
        sa.Column("repair_attempt", sa.Integer(), nullable=True),
        sa.Column("error_type", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_llm_usage_events_run_id", "llm_usage_events", ["run_id"])
    op.create_index("ix_llm_usage_events_eval_run_id", "llm_usage_events", ["eval_run_id"])
    op.create_index("ix_llm_usage_events_eval_case_id", "llm_usage_events", ["eval_case_id"])


def downgrade() -> None:
    op.drop_index("ix_llm_usage_events_eval_case_id", table_name="llm_usage_events")
    op.drop_index("ix_llm_usage_events_eval_run_id", table_name="llm_usage_events")
    op.drop_index("ix_llm_usage_events_run_id", table_name="llm_usage_events")
    op.drop_table("llm_usage_events")
    op.drop_index("ix_eval_metrics_eval_run_id", table_name="eval_metrics")
    op.drop_table("eval_metrics")
    op.drop_index("ix_eval_case_results_eval_case_id", table_name="eval_case_results")
    op.drop_index("ix_eval_case_results_eval_run_id", table_name="eval_case_results")
    op.drop_table("eval_case_results")
    op.drop_index("ix_eval_runs_suite_id", table_name="eval_runs")
    op.drop_table("eval_runs")
    op.drop_index("ix_eval_cases_suite_id", table_name="eval_cases")
    op.drop_table("eval_cases")
    op.drop_table("eval_suites")
