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
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase, Session
from core.config import settings


class Base(DeclarativeBase):
    """Базовый класс для всех моделей SQLAlchemy."""


engine = create_engine(
    settings.DATABASE_URL,
    pool_size=10,    # Постоянно 10 соединений
    max_overflow=20,   # Дополнительно до 20 соединений при пиковых нагрузках
    future=True,
    pool_pre_ping=True,   # Проверка соединений перед использованием
    pool_recycle=3600    # Обновление соединений каждые 3600 секунд (1 час).
)


SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
    expire_on_commit=False
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
    finally:
        db.close()


# Здесь должно быть 2 пустых строки перед следующим классом/функцией
