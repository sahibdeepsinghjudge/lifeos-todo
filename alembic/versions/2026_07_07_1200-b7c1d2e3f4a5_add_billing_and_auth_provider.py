"""add billing fields and auth provider to users

Revision ID: b7c1d2e3f4a5
Revises: f68b6748034d
Create Date: 2026-07-07 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b7c1d2e3f4a5'
down_revision: Union[str, None] = 'f68b6748034d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('users', sa.Column('auth_provider', sa.String(length=20), nullable=False, server_default='password'))
    op.add_column('users', sa.Column('subscription_status', sa.String(length=20), nullable=False, server_default='none'))
    op.add_column('users', sa.Column('subscription_plan', sa.String(length=20), nullable=True))
    op.add_column('users', sa.Column('trial_started_at', sa.DateTime(), nullable=True))
    op.add_column('users', sa.Column('subscription_expires_at', sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column('users', 'subscription_expires_at')
    op.drop_column('users', 'trial_started_at')
    op.drop_column('users', 'subscription_plan')
    op.drop_column('users', 'subscription_status')
    op.drop_column('users', 'auth_provider')
