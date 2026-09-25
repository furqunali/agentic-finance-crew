"""observability — per-decision latency + LLM usage columns

Revision ID: 0004_observability
Revises: 0003_users
Create Date: 2026-09-25
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "0004_observability"
down_revision = "0003_users"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("decisions") as batch:
        batch.add_column(sa.Column("latency_ms", sa.Float(), server_default="0", nullable=True))
        batch.add_column(sa.Column("tokens", sa.Integer(), server_default="0", nullable=True))
        batch.add_column(sa.Column("cost_usd", sa.Float(), server_default="0", nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("decisions") as batch:
        batch.drop_column("cost_usd")
        batch.drop_column("tokens")
        batch.drop_column("latency_ms")
