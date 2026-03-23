"""add safety document sets

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-03-20

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e5f6a7b8c9d0"
down_revision: Union[str, Sequence[str], None] = "d4e5f6a7b8c9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "safety_document_sets",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("expiry_date", sa.Date(), nullable=True),
        sa.Column(
            "all_company",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("created_by", sa.BigInteger(), nullable=False),
        sa.Column("updated_by", sa.BigInteger(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_safety_document_sets_title",
        "safety_document_sets",
        ["title"],
        unique=False,
    )

    op.create_table(
        "safety_document_set_users",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("set_id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["set_id"], ["safety_document_sets.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("set_id", "user_id", name="uq_safety_document_set_user"),
    )
    op.create_index(
        "ix_safety_document_set_users_set",
        "safety_document_set_users",
        ["set_id"],
        unique=False,
    )
    op.create_index(
        "ix_safety_document_set_users_user",
        "safety_document_set_users",
        ["user_id"],
        unique=False,
    )

    op.add_column(
        "document_meta_extensions",
        sa.Column(
            "set_id",
            sa.BigInteger(),
            sa.ForeignKey("safety_document_sets.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_document_meta_extensions_set_id",
        "document_meta_extensions",
        ["set_id"],
        unique=False,
    )

    op.execute(
        sa.text(
            """
            INSERT INTO safety_document_sets (
                title,
                expiry_date,
                all_company,
                created_by,
                updated_by,
                created_at,
                updated_at
            )
            SELECT
                d.title,
                MAX(m.expiry_date) AS expiry_date,
                COALESCE(BOOL_OR(r.subject_type = 'all_company'), FALSE) AS all_company,
                MIN(d.created_by) AS created_by,
                MIN(d.created_by) AS updated_by,
                NOW(),
                NOW()
            FROM documents d
            JOIN document_meta_extensions m ON m.document_id = d.id
            LEFT JOIN document_access_rules r ON r.document_id = d.id
            WHERE m.is_department_common = TRUE
              AND d.category = 'safety'
              AND d.deleted_at IS NULL
              AND d.is_active = TRUE
            GROUP BY d.title
            """
        )
    )

    op.execute(
        sa.text(
            """
            UPDATE document_meta_extensions m
            SET set_id = s.id,
                expiry_date = s.expiry_date
            FROM documents d
            JOIN safety_document_sets s ON s.title = d.title
            WHERE m.document_id = d.id
              AND m.is_department_common = TRUE
              AND d.category = 'safety'
              AND d.deleted_at IS NULL
              AND d.is_active = TRUE
              AND m.set_id IS NULL
            """
        )
    )

    op.execute(
        sa.text(
            """
            INSERT INTO safety_document_set_users (set_id, user_id, created_at)
            SELECT DISTINCT
                m.set_id,
                CAST(r.subject_value AS BIGINT),
                NOW()
            FROM document_meta_extensions m
            JOIN document_access_rules r ON r.document_id = m.document_id
            WHERE m.set_id IS NOT NULL
              AND r.subject_type = 'user'
              AND r.subject_value ~ '^[0-9]+$'
            ON CONFLICT (set_id, user_id) DO NOTHING
            """
        )
    )


def downgrade() -> None:
    op.drop_index(
        "ix_document_meta_extensions_set_id",
        table_name="document_meta_extensions",
    )
    op.drop_column("document_meta_extensions", "set_id")

    op.drop_index(
        "ix_safety_document_set_users_user",
        table_name="safety_document_set_users",
    )
    op.drop_index(
        "ix_safety_document_set_users_set",
        table_name="safety_document_set_users",
    )
    op.drop_table("safety_document_set_users")

    op.drop_index("ix_safety_document_sets_title", table_name="safety_document_sets")
    op.drop_table("safety_document_sets")
