"""email OTP verification fields on users

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-07-11 11:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "d4e5f6a7b8c9"
down_revision: Union[str, None] = "c3d4e5f6a7b8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "email_verified", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
    )
    op.add_column(
        "users", sa.Column("email_otp_hash", sa.String(length=255), nullable=True)
    )
    op.add_column(
        "users", sa.Column("email_otp_expires_at", sa.DateTime(), nullable=True)
    )
    op.add_column(
        "users",
        sa.Column(
            "email_otp_attempts", sa.Integer(), nullable=False, server_default="0"
        ),
    )
    op.add_column(
        "users", sa.Column("email_otp_sent_at", sa.DateTime(), nullable=True)
    )

    # Everyone who signed up before OTP existed is grandfathered in as
    # verified — this change must never lock out existing accounts.
    op.execute("UPDATE users SET email_verified = true")


def downgrade() -> None:
    op.drop_column("users", "email_otp_sent_at")
    op.drop_column("users", "email_otp_attempts")
    op.drop_column("users", "email_otp_expires_at")
    op.drop_column("users", "email_otp_hash")
    op.drop_column("users", "email_verified")
