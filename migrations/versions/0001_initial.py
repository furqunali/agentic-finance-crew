"""initial schema — decisions table

Revision ID: 0001_initial
Revises:
Create Date: 2026-09-25
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "decisions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("request_id", sa.String(length=64), nullable=False),
        sa.Column("employee", sa.String(length=120), nullable=False),
        sa.Column("category", sa.String(length=40), nullable=False),
        sa.Column("amount", sa.Float(), nullable=False),
        sa.Column("currency", sa.String(length=8), nullable=True),
        sa.Column("decision", sa.String(length=32), nullable=False),
        sa.Column("risk_score", sa.Integer(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("rationale", sa.Text(), nullable=True),
        sa.Column("engine", sa.String(length=20), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_decisions_request_id", "decisions", ["request_id"])
    op.create_index("ix_decisions_employee", "decisions", ["employee"])
    op.create_index("ix_decisions_decision", "decisions", ["decision"])


def downgrade() -> None:
    op.drop_index("ix_decisions_decision", table_name="decisions")
    op.drop_index("ix_decisions_employee", table_name="decisions")
    op.drop_index("ix_decisions_request_id", table_name="decisions")
    op.drop_table("decisions")
