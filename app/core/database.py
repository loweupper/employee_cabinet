from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, DeclarativeBase, Session
from core.config import settings


class Base(DeclarativeBase):
    pass


engine = create_engine(
    settings.DATABASE_URL,
    pool_size=10,  # Постоянно 10 соединений
    max_overflow=20, # Дополнительно до 20 соединений при пиковых нагрузках
    future=True,  
    pool_pre_ping=True, # Проверка соединений перед использованием
    pool_recycle=3600  # Recycle connections every hour (security best practice)
)

SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
    expire_on_commit=False
)

def get_db():
    db: Session = SessionLocal()
    try:
        yield db
    finally:
        db.close()
