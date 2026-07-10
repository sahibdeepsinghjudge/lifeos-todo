"""subscriptions, payments ledger, token usage, admin

Revision ID: c3d4e5f6a7b8
Revises: b7c1d2e3f4a5
Create Date: 2026-07-10 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "c3d4e5f6a7b8"
down_revision: Union[str, None] = "b7c1d2e3f4a5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── users: admin flag + provider handles ──────────────────────────────
    op.add_column(
        "users",
        sa.Column("is_admin", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "users", sa.Column("subscription_provider", sa.String(length=20), nullable=True)
    )
    op.add_column(
        "users", sa.Column("razorpay_customer_id", sa.String(length=64), nullable=True)
    )
    op.add_column(
        "users",
        sa.Column("razorpay_subscription_id", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "users", sa.Column("expiry_reminder_sent_at", sa.DateTime(), nullable=True)
    )
    op.create_index(
        "ix_users_razorpay_subscription_id",
        "users",
        ["razorpay_subscription_id"],
    )

    # ── payments ledger ───────────────────────────────────────────────────
    op.create_table(
        "payments",
        sa.Column("id", sa.Integer(), primary_key=True, index=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("provider", sa.String(length=20), nullable=False),
        sa.Column("event", sa.String(length=50), nullable=False),
        sa.Column("plan", sa.String(length=20), nullable=True),
        sa.Column("amount", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("currency", sa.String(length=8), nullable=False, server_default="INR"),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="success"),
        sa.Column("provider_payment_id", sa.String(length=80), nullable=True),
        sa.Column("provider_subscription_id", sa.String(length=80), nullable=True),
        sa.Column("provider_event_id", sa.String(length=120), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_payments_user_id", "payments", ["user_id"])
    op.create_index(
        "ix_payments_provider_payment_id", "payments", ["provider_payment_id"]
    )
    op.create_index(
        "ix_payments_provider_subscription_id",
        "payments",
        ["provider_subscription_id"],
    )
    op.create_index(
        "ix_payments_provider_event_id",
        "payments",
        ["provider_event_id"],
        unique=True,
    )

    # ── token usage ───────────────────────────────────────────────────────
    op.create_table(
        "token_usage",
        sa.Column("id", sa.Integer(), primary_key=True, index=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("model", sa.String(length=80), nullable=False, server_default=""),
        sa.Column("prompt_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("completion_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("usage_date", sa.Date(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_token_usage_user_id", "token_usage", ["user_id"])
    op.create_index("ix_token_usage_usage_date", "token_usage", ["usage_date"])


def downgrade() -> None:
    op.drop_table("token_usage")
    op.drop_table("payments")
    op.drop_index("ix_users_razorpay_subscription_id", table_name="users")
    op.drop_column("users", "expiry_reminder_sent_at")
    op.drop_column("users", "razorpay_subscription_id")
    op.drop_column("users", "razorpay_customer_id")
    op.drop_column("users", "subscription_provider")
    op.drop_column("users", "is_admin")
