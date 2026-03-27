# core/database.py
"""Модуль для настройки подключения к базе данных и управления сессиями. Здесь
определяется базовый класс для моделей SQLAlchemy, а также функции для
получения сессии и настройки подключения. Этот модуль используется во всех
частях приложения, которые взаимодействуют с базой данных, обеспечивая единый
способ доступа к данным и управления ими. Здесь также можно настроить
параметры подключения, такие как пул соединений, таймауты и другие, чтобы
обеспечить оптимальную производительность и надежность при работе с базой
данных.
"""
import logging

from sqlalchemy import create_engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from core.config import settings

logger = logging.getLogger("app")


class Base(DeclarativeBase):
    """Базовый класс для всех моделей SQLAlchemy."""


engine = create_engine(
    settings.DATABASE_URL,
    pool_size=10,  # Постоянно 10 соединений
    max_overflow=20,  # Дополнительно до 20 соединений при пиковых нагрузках
    pool_timeout=5,  # Не ждём соединение слишком долго под нагрузкой
    future=True,
    pool_pre_ping=True,  # Проверка соединений перед использованием
    pool_recycle=3600,  # Обновление соединений каждые 3600 секунд (1 час).
    pool_reset_on_return="rollback",
    connect_args={
        "connect_timeout": 5,
        "application_name": "employee_cabinet",
        "options": (
            "-c statement_timeout=15000 "
            "-c lock_timeout=5000 "
            "-c idle_in_transaction_session_timeout=15000"
        ),
    },
)


SessionLocal = sessionmaker(
    bind=engine, autoflush=False, autocommit=False, expire_on_commit=False
)


def get_db():
    """Получить сессию базы данных.

    Генерирует сессию SQLAlchemy для использования в зависимостях FastAPI.
    Сессия автоматически закрывается после завершения запроса.

    Yields:
        Session: Активная сессия базы данных
    """
    db: Session = SessionLocal()
    try:
        yield db
    except Exception:
        try:
            db.rollback()
        except SQLAlchemyError as rollback_error:
            logger.error(
                {
                    "event": "db_session_rollback_failed",
                    "error_type": type(rollback_error).__name__,
                }
            )
        try:
            db.invalidate()
        except SQLAlchemyError as invalidate_error:
            logger.error(
                {
                    "event": "db_session_invalidate_failed",
                    "error_type": type(invalidate_error).__name__,
                }
            )
        raise
    finally:
        try:
            db.close()
        except SQLAlchemyError as close_error:
            logger.error(
                {
                    "event": "db_session_close_failed",
                    "error_type": type(close_error).__name__,
                }
            )
            try:
                db.invalidate()
            except SQLAlchemyError:
                pass


# Здесь должно быть 2 пустых строки перед следующим классом/функцией
