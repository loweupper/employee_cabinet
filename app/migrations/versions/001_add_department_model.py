"""Add department model and update user table

Revision ID: 001
Revises: 
Create Date: 2026-02-13 09:30:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '001'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create departments table
    op.create_table(
        'departments',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('description', sa.String(length=512), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_departments_id'), 'departments', ['id'], unique=False)
    op.create_index(op.f('ix_departments_name'), 'departments', ['name'], unique=True)
    
    # Add department_id column to users table
    op.add_column('users', sa.Column('department_id', sa.BigInteger(), nullable=True))
    op.create_index(op.f('ix_users_department_id'), 'users', ['department_id'], unique=False)
    op.create_foreign_key('fk_users_department_id', 'users', 'departments', ['department_id'], ['id'], ondelete='SET NULL')
    
    # Initialize standard departments
    op.execute("""
        INSERT INTO departments (name, description) VALUES
        ('Бухгалтерия', 'Финансовый отдел компании'),
        ('Кадры', 'Отдел по управлению персоналом'),
        ('Инженерия', 'Технический отдел'),
        ('Юридический', 'Юридический отдел'),
        ('Администрация', 'Административный отдел'),
        ('Общий', 'Общий отдел для сотрудников')
    """)
    
    # Migrate existing data: set default department for existing users
    # Users with department text will need manual migration or can be left as is
    # For now, we'll set all users without a department to "Общий" (General)
    op.execute("""
        UPDATE users 
        SET department_id = (SELECT id FROM departments WHERE name = 'Общий')
        WHERE department_id IS NULL
    """)
    
    # Drop the old department column (after data migration)
    op.drop_column('users', 'department')


def downgrade() -> None:
    # Add back the old department column
    op.add_column('users', sa.Column('department', sa.String(length=255), nullable=True))
    op.create_index('ix_users_department', 'users', ['department'], unique=False)
    
    # Migrate data back from department_id to department text
    op.execute("""
        UPDATE users 
        SET department = (SELECT name FROM departments WHERE id = users.department_id)
        WHERE department_id IS NOT NULL
    """)
    
    # Drop foreign key and department_id column
    op.drop_constraint('fk_users_department_id', 'users', type_='foreignkey')
    op.drop_index(op.f('ix_users_department_id'), table_name='users')
    op.drop_column('users', 'department_id')
    
    # Drop departments table
    op.drop_index(op.f('ix_departments_name'), table_name='departments')
    op.drop_index(op.f('ix_departments_id'), table_name='departments')
    op.drop_table('departments')
