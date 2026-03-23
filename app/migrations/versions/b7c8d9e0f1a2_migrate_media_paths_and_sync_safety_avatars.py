"""migrate media paths and sync safety avatars

Revision ID: b7c8d9e0f1a2
Revises: f6a7b8c9d0e1
Create Date: 2026-03-23

"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b7c8d9e0f1a2"
down_revision: Union[str, Sequence[str], None] = "f6a7b8c9d0e1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _workspace_root() -> Path:
    # .../app/migrations/versions -> .../app
    return Path(__file__).resolve().parents[2]


def _static_root() -> Path:
    cwd_static = Path("static")
    if cwd_static.exists() or cwd_static.parent.exists():
        return cwd_static
    return _workspace_root() / "static"


def _move_file_safe(src: Path, dst: Path) -> Path:
    dst.parent.mkdir(parents=True, exist_ok=True)
    if not src.exists() or not src.is_file():
        return dst

    candidate = dst
    index = 1
    while candidate.exists():
        candidate = dst.with_name(f"{dst.stem}_{index}{dst.suffix}")
        index += 1

    shutil.move(str(src), str(candidate))
    return candidate


def _cleanup_empty_legacy_files(folder: Path) -> None:
    if not folder.exists() or not folder.is_dir():
        return
    for child in list(folder.iterdir()):
        if child.is_file():
            child.unlink(missing_ok=True)


def _upgrade_users_avatars(static_root: Path) -> None:
    bind = op.get_bind()
    avatars_root = static_root / "avatars"
    avatars_root.mkdir(parents=True, exist_ok=True)

    rows = bind.execute(
        sa.text("SELECT id, avatar_url FROM users WHERE avatar_url IS NOT NULL")
    ).mappings()

    for row in rows:
        user_id = int(row["id"])
        url = row["avatar_url"]
        if not url:
            continue

        parts = Path(url).parts
        if len(parts) >= 5 and parts[1] == "static" and parts[2] == "avatars":
            # already /static/avatars/{user_id}/file
            continue

        if len(parts) != 4 or parts[1] != "static" or parts[2] != "avatars":
            continue

        filename = parts[3]
        src = avatars_root / filename
        dst = avatars_root / str(user_id) / filename
        moved = _move_file_safe(src, dst)
        new_url = f"/static/avatars/{user_id}/{moved.name}"

        bind.execute(
            sa.text("UPDATE users SET avatar_url = :avatar_url WHERE id = :user_id"),
            {"avatar_url": new_url, "user_id": user_id},
        )

    _cleanup_empty_legacy_files(avatars_root)


def _upgrade_objects_icons(static_root: Path) -> None:
    bind = op.get_bind()
    objects_root = static_root / "objects"
    objects_root.mkdir(parents=True, exist_ok=True)

    rows = bind.execute(
        sa.text("SELECT id, icon_url FROM objects WHERE icon_url IS NOT NULL")
    ).mappings()

    for row in rows:
        object_id = int(row["id"])
        url = row["icon_url"]
        if not url:
            continue

        parts = Path(url).parts
        if len(parts) >= 5 and parts[1] == "static" and parts[2] == "objects":
            # already /static/objects/{object_id}/file
            continue

        if len(parts) != 4 or parts[1] != "static" or parts[2] != "objects":
            continue

        filename = parts[3]
        src = objects_root / filename
        dst = objects_root / str(object_id) / filename
        moved = _move_file_safe(src, dst)
        new_url = f"/static/objects/{object_id}/{moved.name}"

        bind.execute(
            sa.text("UPDATE objects SET icon_url = :icon_url WHERE id = :object_id"),
            {"icon_url": new_url, "object_id": object_id},
        )

    _cleanup_empty_legacy_files(objects_root)


def _sync_safety_profile_avatars() -> None:
    bind = op.get_bind()
    bind.execute(
        sa.text(
            """
            UPDATE safety_profiles sp
            SET avatar_url = u.avatar_url
            FROM users u
            WHERE sp.user_id = u.id
              AND u.avatar_url IS NOT NULL
            """
        )
    )


def _downgrade_users_avatars(static_root: Path) -> None:
    bind = op.get_bind()
    avatars_root = static_root / "avatars"
    avatars_root.mkdir(parents=True, exist_ok=True)

    rows = bind.execute(
        sa.text("SELECT id, avatar_url FROM users WHERE avatar_url IS NOT NULL")
    ).mappings()

    for row in rows:
        user_id = int(row["id"])
        url = row["avatar_url"]
        if not url:
            continue

        parts = Path(url).parts
        if len(parts) != 5 or parts[1] != "static" or parts[2] != "avatars":
            continue

        folder_id = parts[3]
        filename = parts[4]
        if folder_id != str(user_id):
            continue

        src = avatars_root / folder_id / filename
        dst = avatars_root / filename
        moved = _move_file_safe(src, dst)
        new_url = f"/static/avatars/{moved.name}"

        bind.execute(
            sa.text("UPDATE users SET avatar_url = :avatar_url WHERE id = :user_id"),
            {"avatar_url": new_url, "user_id": user_id},
        )


def _downgrade_objects_icons(static_root: Path) -> None:
    bind = op.get_bind()
    objects_root = static_root / "objects"
    objects_root.mkdir(parents=True, exist_ok=True)

    rows = bind.execute(
        sa.text("SELECT id, icon_url FROM objects WHERE icon_url IS NOT NULL")
    ).mappings()

    for row in rows:
        object_id = int(row["id"])
        url = row["icon_url"]
        if not url:
            continue

        parts = Path(url).parts
        if len(parts) != 5 or parts[1] != "static" or parts[2] != "objects":
            continue

        folder_id = parts[3]
        filename = parts[4]
        if folder_id != str(object_id):
            continue

        src = objects_root / folder_id / filename
        dst = objects_root / filename
        moved = _move_file_safe(src, dst)
        new_url = f"/static/objects/{moved.name}"

        bind.execute(
            sa.text("UPDATE objects SET icon_url = :icon_url WHERE id = :object_id"),
            {"icon_url": new_url, "object_id": object_id},
        )


def downgrade_sync_safety_profile_avatars() -> None:
    bind = op.get_bind()
    bind.execute(
        sa.text(
            """
            UPDATE safety_profiles sp
            SET avatar_url = u.avatar_url
            FROM users u
            WHERE sp.user_id = u.id
              AND u.avatar_url IS NOT NULL
            """
        )
    )


def upgrade() -> None:
    static_root = _static_root()
    _upgrade_users_avatars(static_root)
    _upgrade_objects_icons(static_root)
    _sync_safety_profile_avatars()


def downgrade() -> None:
    static_root = _static_root()
    _downgrade_users_avatars(static_root)
    _downgrade_objects_icons(static_root)
    downgrade_sync_safety_profile_avatars()
