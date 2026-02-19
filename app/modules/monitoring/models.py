from sqlalchemy import Column, BigInteger, String, Text, DateTime, Boolean, Enum as SqlEnum
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import func
from core.database import Base
from datetime import datetime
import enum


class AlertSeverity(str, enum.Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class AlertType(str, enum.Enum):
    SECURITY_EVENT = "security_event"
    MULTIPLE_FAILED_LOGINS = "multiple_failed_logins"
    SUSPICIOUS_IP = "suspicious_ip"
    SYSTEM_ERROR = "system_error"
    CUSTOM = "custom"


class Alert(Base):
    __tablename__ = "alerts"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime(timezone=True), server_default=func.now(), index=True)

    severity = Column(SqlEnum(AlertSeverity, native_enum=False), nullable=False, index=True)
    type = Column(SqlEnum(AlertType, native_enum=False), nullable=False, index=True)

    message = Column(Text, nullable=False)

    user_id = Column(BigInteger, nullable=True, index=True)
    ip_address = Column(String(45), nullable=True, index=True)

    details = Column(JSONB, nullable=True)

    resolved = Column(Boolean, default=False, nullable=False, index=True)
    resolved_at = Column(DateTime(timezone=True), nullable=True)
    resolved_by = Column(BigInteger, nullable=True)
