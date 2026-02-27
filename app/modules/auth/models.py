from datetime import datetime
from core.constants import UserRole
from enum import Enum

from sqlalchemy import (
    BigInteger,
    Column,
    String,
    Boolean,
    DateTime,
    Enum as SqlEnum,
    ForeignKey,
    func,
    Index,
    Integer,
    text,
)
from sqlalchemy.orm import relationship

from core.database import Base

# ---------------------------------------------------------
# Модель отдела
# ---------------------------------------------------------
class Department(Base):
    __tablename__ = "departments"

    # Основные поля
    id = Column(BigInteger, primary_key=True, index=True, autoincrement=True)
    name = Column(String(255), unique=True, nullable=False, index=True)
    description = Column(String(512), nullable=True)

    # Дата создания и обновления записи
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    # Связь с пользователями
    users = relationship("User", back_populates="department_rel")

    def __repr__(self):
        return f"<Department id={self.id} name={self.name}>"


# ---------------------------------------------------------
# Цели OTP
# ---------------------------------------------------------
class OTPPurpose(str, Enum):
    LOGIN = "login"
    EMAIL_VERIFY = "email_verify"
    PASSWORD_RESET = "password_reset"


# ---------------------------------------------------------
# Модель пользователя
# ---------------------------------------------------------
class User(Base):
    __tablename__ = "users"

    # Основные поля
    id = Column(BigInteger, primary_key=True, index=True, autoincrement=True)

    # Email пользователя
    email = Column(String(255), unique=True, nullable=False, index=True)
    hashed_password = Column(String(255), nullable=False)

    # Роль пользователя
    role = Column(SqlEnum(UserRole, native_enum=False), default=UserRole.EMPLOYEE, nullable=False, index=True)
    is_active = Column(Boolean, default=True, nullable=False)

    # Дополнительные поля профиля
    first_name = Column(String(255), nullable=True)
    last_name = Column(String(255), nullable=True)
    middle_name = Column(String(255), nullable=True)
    phone_number = Column(String(20), nullable=True, unique=True)
    avatar_url = Column(String(512), nullable=True)
    department_id = Column(BigInteger, ForeignKey("departments.id", ondelete="SET NULL"), nullable=True, index=True)
    position = Column(String(255), nullable=True, index=True)
    location = Column(String(255), nullable=True)
    object_id = Column(BigInteger, nullable=True, index=True)

    # Дата создания и обновления записи
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    deleted_at = Column(DateTime(timezone=True), nullable=True, index=True)
    activated_at = Column(DateTime(timezone=True), nullable=True, index=True)

    sessions = relationship(
        "Session",
        back_populates="user",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    department_rel = relationship("Department", back_populates="users")

    __table_args__ = (Index("ix_users_email_lower", func.lower(email), unique=True),)

    def __repr__(self):
        return f"<User id={self.id} email={self.email}>"


# ---------------------------------------------------------
# Refresh-токены (храним хэш токена)
# ---------------------------------------------------------
class Session(Base):
    __tablename__ = "sessions"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)

    token_hash = Column(String(128), nullable=False, index=True)

    user_agent = Column(String(512), nullable=True)
    ip_address = Column(String(45), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    expires_at = Column(DateTime(timezone=True), nullable=False, index=True)
    is_revoked = Column(Boolean, default=False, nullable=False)
    last_used_at = Column(DateTime(timezone=True), nullable=True)
    replaced_by = Column(String(128), nullable=True)

    user = relationship("User", back_populates="sessions", passive_deletes=True)

    def __repr__(self):
        return f"<Session id={self.id} user_id={self.user_id} revoked={self.is_revoked}>"


# ---------------------------------------------------------
# OTP-коды (2FA, подтверждение email)
# ---------------------------------------------------------
class OTP(Base):
    __tablename__ = "otp_codes"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)

    code = Column(String(128), nullable=False)
    purpose = Column(SqlEnum(OTPPurpose, native_enum=False), nullable=False)

    expires_at = Column(DateTime(timezone=True), nullable=False)
    used = Column(Boolean, default=False, nullable=False)

    # Количество попыток ввода кода
    attempts = Column(Integer, default=0, nullable=False)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    # Связь с пользователем
    user = relationship("User", passive_deletes=True)

    __table_args__ = (
        # Индекс для очистки просроченных OTP
        Index("ix_otp_expires_at", "expires_at"),
        # Уникальный индекс: только один активный OTP на (user_id, purpose)
        Index(
            "ix_otp_user_purpose_active",
            "user_id",
            "purpose",
            unique=True,
            postgresql_where=text("used = false AND expires_at > now()"),
        ),
    )

    def __repr__(self):
        return f"<OTP id={self.id} user_id={self.user_id} purpose={self.purpose}>"


# ---------------------------------------------------------
# Попытки логина (для защиты от брутфорса)
# ---------------------------------------------------------
class LoginAttempt(Base):
    __tablename__ = "login_attempts"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime, default=datetime.utcnow, nullable=False)

    email = Column(String(255), index=True, nullable=False)
    ip_address = Column(String(45), index=True, nullable=True)

    user_id = Column(BigInteger, nullable=True)
    success = Column(Boolean, default=False, nullable=False)

    def __repr__(self):
        return f"<LoginAttempt id={self.id} email={self.email} ip={self.ip_address} success={self.success}>"
