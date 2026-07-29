"""early-access waitlist requests

Revision ID: b8c9d0e1f2a3
Revises: a7b8c9d0e1f2
Create Date: 2026-07-29 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "b8c9d0e1f2a3"
down_revision: Union[str, None] = "a7b8c9d0e1f2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "access_requests",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("will_help", sa.String(length=20), nullable=False, server_default=""),
        sa.Column(
            "status", sa.String(length=20), nullable=False, server_default="pending"
        ),
        sa.Column("onboarded_at", sa.DateTime(), nullable=True),
        sa.Column("ip_hash", sa.String(length=32), nullable=False, server_default=""),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_access_requests_id"), "access_requests", ["id"])
    op.create_index(
        op.f("ix_access_requests_email"), "access_requests", ["email"], unique=True
    )
    op.create_index(op.f("ix_access_requests_status"), "access_requests", ["status"])
    op.create_index(op.f("ix_access_requests_ip_hash"), "access_requests", ["ip_hash"])
    op.create_index(
        op.f("ix_access_requests_created_at"), "access_requests", ["created_at"]
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_access_requests_created_at"), table_name="access_requests")
    op.drop_index(op.f("ix_access_requests_ip_hash"), table_name="access_requests")
    op.drop_index(op.f("ix_access_requests_status"), table_name="access_requests")
    op.drop_index(op.f("ix_access_requests_email"), table_name="access_requests")
    op.drop_index(op.f("ix_access_requests_id"), table_name="access_requests")
    op.drop_table("access_requests")
