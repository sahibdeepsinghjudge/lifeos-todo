"""google play purchase token on users

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-07-12 16:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "f6a7b8c9d0e1"
down_revision: Union[str, None] = "e5f6a7b8c9d0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("google_play_purchase_token", sa.String(length=255), nullable=True),
    )
    op.create_index(
        "ix_users_google_play_purchase_token",
        "users",
        ["google_play_purchase_token"],
    )


def downgrade() -> None:
    op.drop_index("ix_users_google_play_purchase_token", table_name="users")
    op.drop_column("users", "google_play_purchase_token")
