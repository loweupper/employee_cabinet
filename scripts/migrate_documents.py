"""
Миграция документов из старой структуры в новую
Из: /files/objects/15/doc.pdf
В: /files/2026/01/15/doc.pdf
"""
import sys
import os
import shutil
from pathlib import Path
from datetime import datetime
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("migrate")

# Add the app directory to sys.path so core.config can be imported
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))

from core.config import settings


def migrate_documents():
    old_base = Path(settings.FILES_PATH) / "objects"

    if not old_base.exists():
        logger.info("No old files directory found, skipping migration")
        return

    # Текущий месяц
    now = datetime.now()
    year = str(now.year)
    month = f"{now.month:02d}"

    # Перемещаем все файлы
    for object_dir in old_base.iterdir():
        if not object_dir.is_dir():
            continue

        object_id = object_dir.name
        new_object_dir = Path(settings.FILES_PATH) / year / month / object_id

        # Создаём новую директорию
        new_object_dir.mkdir(parents=True, exist_ok=True)

        # Перемещаем файлы
        for file in object_dir.glob("*"):
            if file.is_file():
                new_file = new_object_dir / file.name
                shutil.move(str(file), str(new_file))
                logger.info(f"✅ Migrated: {file.name} → {new_file}")

        # Удаляем пустую директорию
        try:
            object_dir.rmdir()
        except OSError:
            pass

    # Удаляем старую папку objects если пуста
    try:
        old_base.rmdir()
        logger.info("✅ Removed old 'objects' directory")
    except OSError:
        logger.warning("Could not remove old 'objects' directory")


if __name__ == "__main__":
    migrate_documents()
    logger.info("✅ Migration complete!")
