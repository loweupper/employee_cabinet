"""Create category_department_mapping table

Revision ID: a1b2c3d4e5f6
Revises: 5700b245002e
Create Date: 2026-03-03

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = '5700b245002e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'category_department_mappings',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('category', sa.String(), nullable=False),
        sa.Column('departments', postgresql.ARRAY(sa.String()), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()')),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('category')
    )
    op.create_index(op.f('ix_category_department_mappings_id'), 'category_department_mappings', ['id'], unique=False)
    op.create_index('ix_category_department_mappings_category', 'category_department_mappings', ['category'], unique=False)

    # Вставляем начальные данные на основе существующих констант
    op.execute("""
        INSERT INTO category_department_mappings (category, departments) VALUES
        ('general', ARRAY[]::varchar[]),
        ('accounting', ARRAY['Бухгалтерия']),
        ('safety', ARRAY['Охрана труда']),
        ('technical', ARRAY['Технический отдел']),
        ('legal', ARRAY['Юридический']),
        ('hr', ARRAY['Отдел кадров'])
    """)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_category_department_mappings_category', table_name='category_department_mappings')
    op.drop_index(op.f('ix_category_department_mappings_id'), table_name='category_department_mappings')
    op.drop_table('category_department_mappings')
