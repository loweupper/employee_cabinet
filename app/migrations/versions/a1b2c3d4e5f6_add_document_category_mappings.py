"""add_document_category_mappings

Revision ID: a1b2c3d4e5f6
Revises: 5700b245002e
Create Date: 2026-03-03 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = '5700b245002e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'document_category_mappings',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('category', sa.String(length=50), nullable=False),
        sa.Column('department_id', sa.BigInteger(), nullable=True),
        sa.Column('description', sa.String(length=500), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['department_id'], ['departments.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('category')
    )
    op.create_index(
        op.f('ix_document_category_mappings_category'),
        'document_category_mappings',
        ['category'],
        unique=True
    )

    # Начальные данные
    op.execute(sa.text("""
        INSERT INTO document_category_mappings (category, department_id, description, created_at, updated_at)
        VALUES
            ('general',    NULL,                                                                        'Общие документы - доступны всем',    NOW(), NOW()),
            ('technical',  (SELECT id FROM departments WHERE name='Технический отдел'  LIMIT 1),       'Технические документы',              NOW(), NOW()),
            ('accounting', (SELECT id FROM departments WHERE name='Бухгалтерия'        LIMIT 1),       'Бухгалтерские документы',            NOW(), NOW()),
            ('hr',         (SELECT id FROM departments WHERE name='Отдел кадров'       LIMIT 1),       'Кадровые документы',                 NOW(), NOW()),
            ('legal',      (SELECT id FROM departments WHERE name='Юридический отдел'  LIMIT 1),       'Юридические документы',              NOW(), NOW()),
            ('safety',     (SELECT id FROM departments WHERE name='Охрана труда'       LIMIT 1),       'Охрана труда',                       NOW(), NOW())
        ON CONFLICT (category) DO NOTHING
    """))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(
        op.f('ix_document_category_mappings_category'),
        table_name='document_category_mappings'
    )
    op.drop_table('document_category_mappings')
