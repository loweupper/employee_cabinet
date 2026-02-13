"""Add objects and object_accesses tables

Revision ID: 116918c8d089
Revises: 608e15abed42
Create Date: 2026-02-09

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '116918c8d089'
down_revision = '608e15abed42'
branch_labels = None
depends_on = None


def upgrade():
    # ✅ Шаг 1: Добавляем колонку sections_access с возможностью NULL
    op.add_column(
        'object_accesses',
        sa.Column(
            'sections_access',
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,  # ✅ Сначала разрешаем NULL
            comment='Список разделов документов, к которым есть доступ'
        )
    )
    
    # ✅ Шаг 2: Заполняем существующие записи значением по умолчанию
    op.execute("""
        UPDATE object_accesses
        SET sections_access = '["general", "technical", "accounting", "safety", "legal", "hr"]'::jsonb
        WHERE sections_access IS NULL
    """)
    
    # ✅ Шаг 3: Теперь делаем колонку NOT NULL
    op.alter_column('object_accesses', 'sections_access', nullable=False)
    
    # Добавляем индекс (если его ещё нет)
    op.create_index(op.f('ix_object_accesses_id'), 'object_accesses', ['id'], unique=False)
    
    # Удаляем старые индексы (если они есть)
    # op.drop_index('ix_objects_created_by', table_name='objects')
    # op.drop_index('ix_objects_is_active', table_name='objects')


def downgrade():
    # Откат изменений
    op.drop_column('object_accesses', 'sections_access')
    op.drop_index(op.f('ix_object_accesses_id'), table_name='object_accesses')