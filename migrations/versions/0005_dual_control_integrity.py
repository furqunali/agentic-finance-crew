"""dual control, tamper-evident audit chain, history lookup keys

Revision ID: 0005_dual_control_integrity
Revises: 0004_observability
Create Date: 2026-11-16
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.orm import Session

# revision identifiers, used by Alembic.
revision = "0005_dual_control_integrity"
down_revision = "0004_observability"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("decisions") as batch:
        batch.add_column(sa.Column("employee_key", sa.String(120), server_default="", nullable=True))
        batch.add_column(sa.Column("expense_date", sa.String(32), server_default="", nullable=True))
        batch.add_column(sa.Column("approvals_required", sa.Integer(), server_default="1", nullable=True))
        batch.add_column(sa.Column("first_approved_by", sa.String(120), nullable=True))
        batch.add_column(sa.Column("first_approved_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("record_hash", sa.String(64), server_default="", nullable=True))
        batch.add_column(sa.Column("head_hash", sa.String(64), server_default="", nullable=True))
        batch.create_index("ix_decisions_employee_key", ["employee_key"])
    with op.batch_alter_table("audit_events") as batch:
        batch.add_column(sa.Column("prev_hash", sa.String(64), server_default="", nullable=True))
        batch.add_column(sa.Column("hash", sa.String(64), server_default="", nullable=True))

    # Existing rows get their identity keys, record digests and chain links.
    from finance_crew.integrity import backfill

    session = Session(bind=op.get_bind())
    backfill(session)
    session.flush()


def downgrade() -> None:
    with op.batch_alter_table("audit_events") as batch:
        batch.drop_column("hash")
        batch.drop_column("prev_hash")
    with op.batch_alter_table("decisions") as batch:
        batch.drop_index("ix_decisions_employee_key")
        for col in ("head_hash", "record_hash", "first_approved_at", "first_approved_by",
                    "approvals_required", "expense_date", "employee_key"):
            batch.drop_column(col)
