"""Migrate access_departments to sections_access

Revision ID: 0010_migrate_access
Revises: 5700b245002e
Create Date: 2026-03-03 12:00:00

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = '0010_migrate_access'
down_revision: Union[str, Sequence[str], None] = '5700b245002e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Migrate data from access_departments to sections_access"""

    # Создаём временный столбец для миграции
    op.add_column('object_accesses', sa.Column('sections_access_new', postgresql.JSONB(), nullable=True))

    # Мигрируем данные: каждый department → соответствующая секция
    op.execute("""
        UPDATE object_accesses
        SET sections_access_new = CASE
            WHEN access_departments IS NULL OR array_length(access_departments, 1) IS NULL THEN '["general"]'::jsonb
            ELSE (
                SELECT jsonb_agg(DISTINCT section) FROM (
                    SELECT CASE
                        WHEN dept = 'accounting' THEN 'accounting'
                        WHEN dept = 'hr' THEN 'hr'
                        WHEN dept = 'technical' THEN 'technical'
                        WHEN dept = 'legal' THEN 'legal'
                        WHEN dept = 'safety' THEN 'safety'
                        ELSE 'general'
                    END as section
                    FROM unnest(access_departments) as dept
                ) AS sections
            )
        END || '["general"]'::jsonb
    """)

    # Убеждаемся, что есть хотя бы "general"
    op.execute("""
        UPDATE object_accesses
        SET sections_access_new = sections_access_new || '["general"]'::jsonb
        WHERE NOT (sections_access_new @> '["general"]'::jsonb)
    """)

    # Удаляем старое поле
    op.drop_column('object_accesses', 'access_departments')

    # Переименовываем новое поле в sections_access (заменяет старое)
    op.drop_column('object_accesses', 'sections_access')
    op.alter_column('object_accesses', 'sections_access_new', new_column_name='sections_access')

    # Устанавливаем NOT NULL
    op.alter_column('object_accesses', 'sections_access', nullable=False)

    # Добавляем updated_at
    op.add_column('object_accesses', sa.Column(
        'updated_at',
        sa.DateTime(timezone=True),
        server_default=sa.func.now(),
        nullable=False
    ))


def downgrade() -> None:
    """Rollback migration"""

    op.drop_column('object_accesses', 'updated_at')

    op.add_column('object_accesses', sa.Column('access_departments', postgresql.ARRAY(sa.String()), nullable=True))

    op.execute("""
        UPDATE object_accesses
        SET access_departments = ARRAY(
            SELECT elem
            FROM jsonb_array_elements_text(sections_access) AS elem
            WHERE elem != 'general'
        )
    """)
