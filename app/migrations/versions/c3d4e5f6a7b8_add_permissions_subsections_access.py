"""Add permissions, subsections and user access control

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-03-03

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'c3d4e5f6a7b8'
down_revision: Union[str, Sequence[str], None] = 'b2c3d4e5f6a7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create permissions, subsections and user access tables."""

    # 1. Create permissions table
    op.create_table(
        'permissions',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('key', sa.String(length=100), nullable=False),
        sa.Column('description', sa.String(length=255), nullable=False),
        sa.Column('category', sa.String(length=50), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('key'),
    )
    op.create_index(op.f('ix_permissions_key'), 'permissions', ['key'], unique=True)

    # 2. Create role_permissions table
    op.create_table(
        'role_permissions',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('role_name', sa.String(length=50), nullable=False),
        sa.Column('permission_id', sa.BigInteger(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.ForeignKeyConstraint(['permission_id'], ['permissions.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('role_name', 'permission_id'),
    )
    op.create_index(op.f('ix_role_permissions_role_name'), 'role_permissions', ['role_name'], unique=False)

    # 3. Create user_permissions table
    op.create_table(
        'user_permissions',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('user_id', sa.BigInteger(), nullable=False),
        sa.Column('permission_id', sa.BigInteger(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.ForeignKeyConstraint(['permission_id'], ['permissions.id']),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'permission_id'),
    )

    # 4. Create subsections table
    op.create_table(
        'subsections',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('section_id', sa.BigInteger(), nullable=False),
        sa.Column('description', sa.String(length=512), nullable=True),
        sa.Column('icon', sa.String(length=100), nullable=True),
        sa.Column('order', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.ForeignKeyConstraint(['section_id'], ['departments.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('section_id', 'name'),
    )

    # 5. Create user_subsection_access table
    op.create_table(
        'user_subsection_access',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('user_id', sa.BigInteger(), nullable=False),
        sa.Column('subsection_id', sa.BigInteger(), nullable=False),
        sa.Column('can_read', sa.Boolean(), nullable=True),
        sa.Column('can_write', sa.Boolean(), nullable=True),
        sa.Column('can_delete', sa.Boolean(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.ForeignKeyConstraint(['subsection_id'], ['subsections.id']),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'subsection_id'),
    )

    # 6. Insert initial permissions
    op.execute(sa.text("""
        INSERT INTO permissions (key, description, category) VALUES
            ('can_create_objects', 'Создавать объекты', 'object_management'),
            ('can_edit_objects', 'Редактировать объекты', 'object_management'),
            ('can_delete_objects', 'Удалять объекты', 'object_management'),
            ('can_view_reports', 'Просматривать отчёты', 'section_access'),
            ('can_manage_users', 'Управлять пользователями', 'user_management'),
            ('can_manage_subsections', 'Управлять подразделами', 'section_access')
        ON CONFLICT (key) DO NOTHING
    """))

    # 7. Assign all permissions to admin role
    op.execute(sa.text("""
        INSERT INTO role_permissions (role_name, permission_id)
        SELECT 'admin', id FROM permissions
        ON CONFLICT (role_name, permission_id) DO NOTHING
    """))

    # 8. Insert subsections for each department
    op.execute(sa.text("""
        INSERT INTO subsections (name, section_id, description, "order")
        SELECT sub.name, d.id, sub.description, sub.ord
        FROM (VALUES
            ('Бухгалтерия', 'Финансы',       'Финансовый учёт и планирование',           1),
            ('Бухгалтерия', 'Налоги',         'Налоговая отчётность и расчёты',           2),
            ('Бухгалтерия', 'Зарплата',       'Расчёт и выплата заработной платы',        3),
            ('Бухгалтерия', 'Амортизация',    'Учёт амортизации основных средств',        4),
            ('Отдел кадров', 'Найм',          'Подбор и найм персонала',                  1),
            ('Отдел кадров', 'Увольнения',    'Оформление увольнений',                    2),
            ('Отдел кадров', 'Обучение',      'Обучение и развитие персонала',            3),
            ('Отдел кадров', 'Льготы',        'Управление льготами сотрудников',          4),
            ('Технический отдел', 'Инфраструктура', 'Управление IT-инфраструктурой',      1),
            ('Технический отдел', 'Разработка',     'Разработка программного обеспечения',2),
            ('Технический отдел', 'Тестирование',   'Тестирование и обеспечение качества',3),
            ('Юридический отдел', 'Контракты',      'Подготовка и анализ контрактов',     1),
            ('Юридический отдел', 'Претензии',      'Работа с претензиями',               2),
            ('Юридический отдел', 'Соответствие',   'Соответствие нормативным требованиям',3)
        ) AS sub(dept_name, name, description, ord)
        JOIN departments d ON d.name = sub.dept_name
        ON CONFLICT (section_id, name) DO NOTHING
    """))

    # 9. Grant default read+write access to users for subsections in their department
    op.execute(sa.text("""
        INSERT INTO user_subsection_access (user_id, subsection_id, can_read, can_write, can_delete)
        SELECT u.id, s.id, TRUE, TRUE, FALSE
        FROM users u
        JOIN subsections s ON s.section_id = u.department_id
        WHERE u.department_id IS NOT NULL
          AND u.deleted_at IS NULL
        ON CONFLICT (user_id, subsection_id) DO NOTHING
    """))


def downgrade() -> None:
    """Remove permissions, subsections and user access tables."""
    op.drop_table('user_subsection_access')
    op.drop_table('subsections')
    op.drop_table('user_permissions')
    op.drop_table('role_permissions')
    op.drop_index(op.f('ix_permissions_key'), table_name='permissions')
    op.drop_table('permissions')
