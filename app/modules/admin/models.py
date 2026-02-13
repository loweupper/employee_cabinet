from sqlalchemy import Column, BigInteger, String, Text, DateTime, Index, Enum as SqlEnum, ForeignKey, Boolean, Integer
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from core.database import Base
from datetime import datetime
import enum
from sqlalchemy.dialects.postgresql import JSONB



class LogLevel(str, enum.Enum):
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


# ===================================
# User-Agent таблица (нормализация)
# ===================================
class UserAgentCache(Base):
    """Кеш User-Agent строк для нормализации"""
    __tablename__ = "user_agent_cache"

    id = Column(BigInteger, primary_key=True, index=True, autoincrement=True)
    user_agent = Column(Text, nullable=False, unique=True)
    
    # Статистика использования
    usage_count = Column(Integer, default=1, nullable=False)
    first_seen = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    last_seen = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    
    def __repr__(self):
        return f"<UserAgentCache id={self.id} usage={self.usage_count}>"


# ===================================
# Audit Logs (основная таблица)
# ===================================
class AuditLog(Base):
    """Модель для хранения логов аудита"""
    __tablename__ = "audit_logs"

    id = Column(BigInteger, primary_key=True, index=True, autoincrement=True)
    
    # Request ID для трейсинга (UUID)
    request_id = Column(String(36), nullable=True, index=True)  # UUID в виде строки

    # Trace ID для распределённого трейсинга
    trace_id = Column(String(36), nullable=True, index=True)  # UUID в виде строки

    # Уровень лога
    level = Column(SqlEnum(LogLevel, native_enum=False), nullable=False, index=True)
    
    # Событие (login, register, user_activated, etc.)
    event = Column(String(100), nullable=False, index=True)
    
    # Сообщение
    message = Column(Text, nullable=True)
    
    # Метаданные (JSON)
    # metadata = Column(Text, nullable=True)  # Храним как JSON string, если не используем PostgreSQL, иначе можно использовать JSONB
    extra_data = Column(JSONB, nullable=True)  # Храним как JSONB для удобства запросов
    
    # Пользователь (опционально)
    user_id = Column(BigInteger, nullable=True, index=True)
    user_email = Column(String(255), nullable=True, index=True)
    
    # IP-адрес
    ip_address = Column(String(45), nullable=True, index=True)  # IPv6 до 45 символов
    
    # User-Agent (FK к кешу)
    user_agent_id = Column(BigInteger, ForeignKey("user_agent_cache.id"), nullable=True, index=True)
    user_agent = relationship("UserAgentCache", backref="audit_logs")
    
    # ✅ HTTP метод и путь (для API логов)
    http_method = Column(String(10), nullable=True, index=True)
    http_path = Column(String(512), nullable=True, index=True)
    http_status = Column(Integer, nullable=True, index=True)

    # ✅ Время выполнения запроса (мс)
    duration_ms = Column(Integer, nullable=True, index=True)

    # ✅ TTL флаг (для автоочистки)
    is_archived = Column(Boolean, default=False, nullable=False, index=True)
    expires_at = Column(DateTime(timezone=True), nullable=True, index=True)  # Дата удаления

    # Timestamp
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)
    
    __table_args__ = (

        Index("ix_audit_logs_level_created", "level", "created_at"),
        Index("ix_audit_logs_event_created", "event", "created_at"),
        Index("ix_audit_logs_user_created", "user_id", "created_at"),
        Index("ix_audit_logs_request_id", "request_id"),
        Index("ix_audit_logs_expires", "expires_at", "is_archived"),
        Index("ix_audit_logs_status_created", "http_status", "created_at"),
    )

    def __repr__(self):
        return f"<AuditLog id={self.id} level={self.level} event={self.event} request_id={self.request_id}>"