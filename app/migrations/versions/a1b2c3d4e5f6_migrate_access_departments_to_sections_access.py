"""Migrate access_departments to sections_access

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


def upgrade():
    # Migrate data: access_departments → sections_access
    op.execute("""
        UPDATE object_accesses
        SET sections_access = CASE
            WHEN access_departments IS NULL OR array_length(access_departments, 1) IS NULL
            THEN '["general"]'::jsonb
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

    # Drop the old column
    op.drop_column('object_accesses', 'access_departments')


def downgrade():
    # NOTE: This downgrade only restores the column structure.
    # Data previously stored in access_departments cannot be recovered from sections_access.
    op.add_column(
        'object_accesses',
        sa.Column('access_departments', postgresql.ARRAY(sa.String()), nullable=True)
    )
