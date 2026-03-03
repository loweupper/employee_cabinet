from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import relationship

from core.database import Base


class Permission(Base):
    __tablename__ = "permissions"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    key = Column(String(100), unique=True, nullable=False, index=True)
    description = Column(String(255), nullable=False)
    category = Column(String(50), nullable=False)  # object_management, section_access, user_management
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    role_permissions = relationship("RolePermission", back_populates="permission")
    user_permissions = relationship("UserPermission", back_populates="permission")


class RolePermission(Base):
    __tablename__ = "role_permissions"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    # Uses role name string (e.g. 'admin', 'accountant') matching UserRole enum values
    role_name = Column(String(50), nullable=False, index=True)
    permission_id = Column(BigInteger, ForeignKey("permissions.id"), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (UniqueConstraint("role_name", "permission_id"),)

    permission = relationship("Permission", back_populates="role_permissions")


class UserPermission(Base):
    __tablename__ = "user_permissions"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, ForeignKey("users.id"), nullable=False)
    permission_id = Column(BigInteger, ForeignKey("permissions.id"), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (UniqueConstraint("user_id", "permission_id"),)

    user = relationship("User", back_populates="user_permissions")
    permission = relationship("Permission", back_populates="user_permissions")


class Subsection(Base):
    __tablename__ = "subsections"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    name = Column(String(255), nullable=False)
    section_id = Column(BigInteger, ForeignKey("departments.id"), nullable=False)
    description = Column(String(512), nullable=True)
    icon = Column(String(100), nullable=True)
    order = Column(Integer, default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (UniqueConstraint("section_id", "name"),)

    section = relationship("Department")
    user_accesses = relationship("UserSubsectionAccess", back_populates="subsection", cascade="all, delete-orphan")


class UserSubsectionAccess(Base):
    __tablename__ = "user_subsection_access"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, ForeignKey("users.id"), nullable=False)
    subsection_id = Column(BigInteger, ForeignKey("subsections.id"), nullable=False)
    can_read = Column(Boolean, default=True)
    can_write = Column(Boolean, default=False)
    can_delete = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (UniqueConstraint("user_id", "subsection_id"),)

    user = relationship("User", back_populates="subsection_accesses")
    subsection = relationship("Subsection", back_populates="user_accesses")
