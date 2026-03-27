"""Add can_access_safety permission

Revision ID: c8d9e0f1a2b3
Revises: b7c8d9e0f1a2
Create Date: 2026-03-24

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c8d9e0f1a2b3"
down_revision: Union[str, Sequence[str], None] = "b7c8d9e0f1a2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create safety access permission and assign it to roles."""
    op.execute(
        sa.text(
            """
            INSERT INTO permissions (key, description, category)
            VALUES ('can_access_safety', 'Доступ к разделу Охрана труда', 'section_access')
            ON CONFLICT (key) DO NOTHING
            """
        )
    )

    op.execute(
        sa.text(
            """
            INSERT INTO role_permissions (role_name, permission_id)
            SELECT role_name, p.id
            FROM (VALUES ('admin'), ('safety')) AS roles(role_name)
            JOIN permissions p ON p.key = 'can_access_safety'
            ON CONFLICT (role_name, permission_id) DO NOTHING
            """
        )
    )


def downgrade() -> None:
    """Remove safety access permission."""
    op.execute(
        sa.text(
            """
            DELETE FROM role_permissions
            WHERE permission_id IN (
                SELECT id FROM permissions WHERE key = 'can_access_safety'
            )
            """
        )
    )

    op.execute(
        sa.text(
            """
            DELETE FROM permissions
            WHERE key = 'can_access_safety'
            """
        )
    )
