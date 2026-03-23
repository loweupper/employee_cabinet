"""Add safety department entities and document access rules

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-03-19

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d4e5f6a7b8c9"
down_revision: Union[str, Sequence[str], None] = "c3d4e5f6a7b8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "safety_profiles",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "is_external", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
        sa.Column("first_name", sa.String(length=255), nullable=True),
        sa.Column("last_name", sa.String(length=255), nullable=True),
        sa.Column("middle_name", sa.String(length=255), nullable=True),
        sa.Column("full_name", sa.String(length=255), nullable=False),
        sa.Column("position", sa.String(length=255), nullable=True),
        sa.Column("department_name", sa.String(length=255), nullable=True),
        sa.Column("phone", sa.String(length=20), nullable=True),
        sa.Column("avatar_url", sa.String(length=512), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_by", sa.BigInteger(), nullable=False),
        sa.Column("updated_by", sa.BigInteger(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_safety_profiles_user", "safety_profiles", ["user_id"], unique=False
    )
    op.create_index(
        "ix_safety_profiles_full_name", "safety_profiles", ["full_name"], unique=False
    )
    op.create_index(
        "ix_safety_profiles_is_external",
        "safety_profiles",
        ["is_external"],
        unique=False,
    )

    op.create_table(
        "safety_profile_objects",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("profile_id", sa.BigInteger(), nullable=False),
        sa.Column("object_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["profile_id"], ["safety_profiles.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["object_id"], ["objects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("profile_id", "object_id", name="uq_safety_profile_object"),
    )
    op.create_index(
        "ix_safety_profile_objects_profile",
        "safety_profile_objects",
        ["profile_id"],
        unique=False,
    )
    op.create_index(
        "ix_safety_profile_objects_object",
        "safety_profile_objects",
        ["object_id"],
        unique=False,
    )

    op.create_table(
        "document_meta_extensions",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("document_id", sa.BigInteger(), nullable=False),
        sa.Column("owner_profile_id", sa.BigInteger(), nullable=True),
        sa.Column("expiry_date", sa.Date(), nullable=True),
        sa.Column("reminder_days", sa.BigInteger(), nullable=True),
        sa.Column(
            "is_department_common",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("department_code", sa.String(length=50), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["owner_profile_id"], ["safety_profiles.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("document_id"),
    )
    op.create_index(
        "ix_document_meta_extensions_department",
        "document_meta_extensions",
        ["department_code"],
        unique=False,
    )

    op.create_table(
        "safety_document_bindings",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("profile_id", sa.BigInteger(), nullable=False),
        sa.Column("document_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["profile_id"], ["safety_profiles.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "profile_id", "document_id", name="uq_safety_profile_document"
        ),
    )
    op.create_index(
        "ix_safety_document_bindings_profile",
        "safety_document_bindings",
        ["profile_id"],
        unique=False,
    )
    op.create_index(
        "ix_safety_document_bindings_document",
        "safety_document_bindings",
        ["document_id"],
        unique=False,
    )

    op.create_table(
        "document_access_rules",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("document_id", sa.BigInteger(), nullable=False),
        sa.Column("subject_type", sa.String(length=30), nullable=False),
        sa.Column("subject_value", sa.String(length=255), nullable=False),
        sa.Column("granted_by", sa.BigInteger(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["granted_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "document_id",
            "subject_type",
            "subject_value",
            name="uq_document_access_rule",
        ),
    )
    op.create_index(
        "ix_document_access_rules_document",
        "document_access_rules",
        ["document_id"],
        unique=False,
    )
    op.create_index(
        "ix_document_access_rules_subject_type",
        "document_access_rules",
        ["subject_type"],
        unique=False,
    )
    op.create_index(
        "ix_document_access_rules_subject_value",
        "document_access_rules",
        ["subject_value"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_document_access_rules_subject_value", table_name="document_access_rules"
    )
    op.drop_index(
        "ix_document_access_rules_subject_type", table_name="document_access_rules"
    )
    op.drop_index(
        "ix_document_access_rules_document", table_name="document_access_rules"
    )
    op.drop_table("document_access_rules")

    op.drop_index(
        "ix_safety_document_bindings_document", table_name="safety_document_bindings"
    )
    op.drop_index(
        "ix_safety_document_bindings_profile", table_name="safety_document_bindings"
    )
    op.drop_table("safety_document_bindings")

    op.drop_index(
        "ix_document_meta_extensions_department", table_name="document_meta_extensions"
    )
    op.drop_table("document_meta_extensions")

    op.drop_index(
        "ix_safety_profile_objects_object", table_name="safety_profile_objects"
    )
    op.drop_index(
        "ix_safety_profile_objects_profile", table_name="safety_profile_objects"
    )
    op.drop_table("safety_profile_objects")

    op.drop_index("ix_safety_profiles_is_external", table_name="safety_profiles")
    op.drop_index("ix_safety_profiles_full_name", table_name="safety_profiles")
    op.drop_index("ix_safety_profiles_user", table_name="safety_profiles")
    op.drop_table("safety_profiles")
