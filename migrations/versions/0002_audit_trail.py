"""audit trail — enrich decisions + add append-only audit_events

Revision ID: 0002_audit_trail
Revises: 0001_initial
Create Date: 2026-09-25
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "0002_audit_trail"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # New audit columns on the existing decisions table. Added nullable / with
    # server defaults so the migration is safe against rows already present.
    with op.batch_alter_table("decisions") as batch:
        batch.add_column(sa.Column("ai_recommendation", sa.String(length=32), server_default="", nullable=True))
        batch.add_column(sa.Column("rules_fired", sa.Text(), server_default="[]", nullable=True))
        batch.add_column(sa.Column("model_version", sa.String(length=64), server_default="", nullable=True))
        batch.add_column(sa.Column("requested_by", sa.String(length=120), server_default="", nullable=True))
        batch.add_column(sa.Column("status", sa.String(length=24), server_default="pending_review", nullable=True))
        batch.add_column(sa.Column("resolved_by", sa.String(length=120), nullable=True))
        batch.add_column(sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("resolution_note", sa.Text(), nullable=True))

    op.create_index("ix_decisions_status", "decisions", ["status"])

    # Backfill status for any pre-existing rows from their machine decision.
    op.execute("UPDATE decisions SET status = 'auto_approved' WHERE decision = 'auto_approved'")
    op.execute("UPDATE decisions SET status = 'auto_rejected' WHERE decision = 'rejected'")
    op.execute("UPDATE decisions SET status = 'pending_review' WHERE decision = 'needs_human_review'")

    op.create_table(
        "audit_events",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("decision_id", sa.Integer(), nullable=False),
        sa.Column("step", sa.String(length=32), nullable=False),
        sa.Column("actor", sa.String(length=120), nullable=True),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.ForeignKeyConstraint(["decision_id"], ["decisions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_audit_events_decision_id", "audit_events", ["decision_id"])
    op.create_index("ix_audit_events_step", "audit_events", ["step"])


def downgrade() -> None:
    op.drop_index("ix_audit_events_step", table_name="audit_events")
    op.drop_index("ix_audit_events_decision_id", table_name="audit_events")
    op.drop_table("audit_events")

    op.drop_index("ix_decisions_status", table_name="decisions")
    with op.batch_alter_table("decisions") as batch:
        batch.drop_column("resolution_note")
        batch.drop_column("resolved_at")
        batch.drop_column("resolved_by")
        batch.drop_column("status")
        batch.drop_column("requested_by")
        batch.drop_column("model_version")
        batch.drop_column("rules_fired")
        batch.drop_column("ai_recommendation")
