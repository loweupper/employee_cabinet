"""Populate departments and create category mappings

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-03-03

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = 'b2c3d4e5f6a7'
down_revision: Union[str, Sequence[str], None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema - populate departments and create mappings."""

    # 1. Вставляем отделы в departments (если их ещё нет)
    op.execute(sa.text("""
        INSERT INTO departments (name, description, created_at, updated_at)
        VALUES
            ('Технический отдел', 'Технические специалисты и разработчики', NOW(), NOW()),
            ('Бухгалтерия', 'Финансовое управление и учёт', NOW(), NOW()),
            ('Отдел кадров', 'Управление персоналом и кадровыми вопросами', NOW(), NOW()),
            ('Юридический отдел', 'Юридическое сопровождение и консультации', NOW(), NOW()),
            ('Охрана труда', 'Безопасность и охрана труда', NOW(), NOW())
        ON CONFLICT (name) DO NOTHING
    """))

    # 2. Обновляем document_category_mappings с правильными department_id
    op.execute(sa.text("""
        UPDATE document_category_mappings
        SET department_id = (
            SELECT id FROM departments 
            WHERE (
                (document_category_mappings.category = 'technical' AND departments.name = 'Технический отдел') OR
                (document_category_mappings.category = 'accounting' AND departments.name = 'Бухгалтерия') OR
                (document_category_mappings.category = 'hr' AND departments.name = 'Отдел кадров') OR
                (document_category_mappings.category = 'legal' AND departments.name = 'Юридический отдел') OR
                (document_category_mappings.category = 'safety' AND departments.name = 'Охрана труда')
            )
            LIMIT 1
        )
        WHERE category IN ('technical', 'accounting', 'hr', 'legal', 'safety')
    """))


def downgrade() -> None:
    """Downgrade schema."""
    op.execute(sa.text("""
        UPDATE document_category_mappings
        SET department_id = NULL
        WHERE category IN ('technical', 'accounting', 'hr', 'legal', 'safety')
    """))
    op.execute(sa.text("""
        DELETE FROM departments 
        WHERE name IN ('Технический отдел', 'Бухгалтерия', 'Отдел кадров', 'Юридический отдел', 'Охрана труда')
    """))
