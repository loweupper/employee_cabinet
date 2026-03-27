"""Add granular safety permissions

Revision ID: d9e0f1a2b3c4
Revises: c8d9e0f1a2b3
Create Date: 2026-03-24

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d9e0f1a2b3c4"
down_revision: Union[str, Sequence[str], None] = "c8d9e0f1a2b3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create granular permissions for OT module and assign defaults."""
    op.execute(
        sa.text(
            """
            INSERT INTO permissions (key, description, category) VALUES
                ('can_create_safety_profiles', 'Создавать карточки ОТ', 'section_access'),
                ('can_edit_safety_profiles', 'Редактировать карточки ОТ', 'section_access'),
                ('can_archive_safety_profiles', 'Архивировать и восстанавливать карточки ОТ', 'section_access'),
                ('can_manage_safety_documents', 'Управлять документами карточек ОТ', 'section_access'),
                ('can_manage_safety_common_docs', 'Управлять общими документами ОТ', 'section_access')
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
            JOIN permissions p ON p.key IN (
                'can_create_safety_profiles',
                'can_edit_safety_profiles',
                'can_archive_safety_profiles',
                'can_manage_safety_documents',
                'can_manage_safety_common_docs'
            )
            ON CONFLICT (role_name, permission_id) DO NOTHING
            """
        )
    )


def downgrade() -> None:
    """Remove granular safety permissions."""
    op.execute(
        sa.text(
            """
            DELETE FROM role_permissions
            WHERE permission_id IN (
                SELECT id FROM permissions
                WHERE key IN (
                    'can_create_safety_profiles',
                    'can_edit_safety_profiles',
                    'can_archive_safety_profiles',
                    'can_manage_safety_documents',
                    'can_manage_safety_common_docs'
                )
            )
            """
        )
    )

    op.execute(
        sa.text(
            """
            DELETE FROM permissions
            WHERE key IN (
                'can_create_safety_profiles',
                'can_edit_safety_profiles',
                'can_archive_safety_profiles',
                'can_manage_safety_documents',
                'can_manage_safety_common_docs'
            )
            """
        )
    )
