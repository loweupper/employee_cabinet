"""Add expires_at and granted_by to acls table

Revision ID: a1b2c3d4e5f6
Revises: 2f0480f9b25a
Create Date: 2026-03-02 09:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = '2f0480f9b25a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add expires_at and granted_by columns to acls table."""
    op.add_column('acls', sa.Column('granted_by', sa.Integer(), nullable=True))
    op.add_column('acls', sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True))
    op.create_foreign_key(
        'fk_acls_granted_by_users',
        'acls', 'users',
        ['granted_by'], ['id'],
        ondelete='SET NULL'
    )


def downgrade() -> None:
    """Remove expires_at and granted_by columns from acls table."""
    op.drop_constraint('fk_acls_granted_by_users', 'acls', type_='foreignkey')
    op.drop_column('acls', 'expires_at')
    op.drop_column('acls', 'granted_by')
