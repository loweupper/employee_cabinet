from sqlalchemy import Column, BigInteger, String, DateTime, ForeignKey, Enum as SqlEnum, func, Index, Text, Boolean, ARRAY
from sqlalchemy.orm import relationship
from sqlalchemy.dialects.postgresql import JSONB
from enum import Enum
from datetime import datetime
from core.database import Base


# ===================================
# Enum для роли доступа
# ===================================
class ObjectAccessRole(str, Enum):
    OWNER = "owner"           # Владелец объекта
    ADMIN = "admin"           # Администратор объекта
    EDITOR = "editor"         # Редактор объекта
    VIEWER = "viewer"         # Просмотрщик объекта (только чтение)


# ===================================
# Enum для разделов документов
# ===================================
class DocumentSection(str, Enum):
    GENERAL = "general"          # Общие
    TECHNICAL = "technical"      # Технические
    ACCOUNTING = "accounting"    # Бухгалтерия
    SAFETY = "safety"            # Охрана труда
    LEGAL = "legal"              # Юридические
    HR = "hr"                    # Кадровые


# Маппинг: отдел → раздел документов
DEPARTMENT_SECTION_MAP = {
    "Технический отдел": DocumentSection.TECHNICAL,
    "Бухгалтерия": DocumentSection.ACCOUNTING,
    "Охрана труда": DocumentSection.SAFETY,
    "Юридический отдел": DocumentSection.LEGAL,
    "Отдел кадров": DocumentSection.HR,
}


# Человекочитаемые названия
SECTION_LABELS = {
    DocumentSection.GENERAL: "📋 Общие",
    DocumentSection.TECHNICAL: "📐 Технические",
    DocumentSection.ACCOUNTING: "💰 Бухгалтерия",
    DocumentSection.SAFETY: "👷 Охрана труда",
    DocumentSection.LEGAL: "⚖️ Юридические",
    DocumentSection.HR: "👔 Кадровые",
}


# ===================================
# Модель доступа к объекту
# ===================================
class ObjectAccess(Base):
    __tablename__ = "object_accesses"

    id = Column(BigInteger, primary_key=True, index=True, autoincrement=True)
    
    # Связи
    object_id = Column(BigInteger, ForeignKey("objects.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    access_departments = Column(ARRAY(String), default=[], nullable=True)
    
    # Роль доступа
    role = Column(
        SqlEnum(ObjectAccessRole, native_enum=False),
        default=ObjectAccessRole.VIEWER,
        nullable=False
    )
    
    # ✅ НОВОЕ: Доступ к разделам документов
    sections_access = Column(
        JSONB,
        default=["general"],
        nullable=False,
        comment="Список разделов документов, к которым есть доступ"
    )
    
    # Метаданные
    granted_by = Column(BigInteger, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=True)
    
    # Связи
    object = relationship("Object", backref="accesses", lazy="joined")
    user = relationship("User", foreign_keys=[user_id], backref="object_accesses", lazy="joined")
    granter = relationship("User", foreign_keys=[granted_by], lazy="joined")
    
    # Индексы
    __table_args__ = (
        Index("ix_object_accesses_object_user", "object_id", "user_id", unique=True),
        Index("ix_object_accesses_user_id", "user_id"),
    )
    
    def __repr__(self):
        return f"<ObjectAccess object_id={self.object_id} user_id={self.user_id} role={self.role}>"
    
    def has_section_access(self, section: str) -> bool:
        """
        Проверить, есть ли доступ к разделу документов
        """
        if not self.sections_access:
            return section == "general"
        
        # Владелец и админ объекта имеют доступ ко всем разделам
        if self.role in [ObjectAccessRole.OWNER, ObjectAccessRole.ADMIN]:
            return True
        
        return section in self.sections_access


# ===================================
# Модель объекта (без изменений)
# ===================================
class Object(Base):
    __tablename__ = "objects"

    id = Column(BigInteger, primary_key=True, index=True, autoincrement=True)
    
    # Основная информация
    title = Column(String(255), nullable=False, index=True)
    address = Column(String(500), nullable=True)
    description = Column(Text, nullable=True)
    icon_url = Column(String(500), nullable=True)
    
    # Классификация
    department = Column(String(255), nullable=True, index=True)
    location = Column(String(255), nullable=True, index=True)
    
    # Владелец и редактор
    created_by = Column(BigInteger, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    updated_by = Column(BigInteger, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    
    # Статус
    is_active = Column(Boolean, default=True, nullable=False)
    is_archived = Column(Boolean, default=False, nullable=False)
    
    # Временные метки
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    deleted_at = Column(DateTime(timezone=True), nullable=True)
    
    # Связи
    owner = relationship("User", foreign_keys=[created_by], backref="objects_created", lazy="joined")
    editor = relationship("User", foreign_keys=[updated_by], lazy="joined")
    
    # Индексы
    __table_args__ = (
        Index("ix_objects_department_location", "department", "location"),
    )
    
    def __repr__(self):
        return f"<Object id={self.id} title={self.title}>"
    
    @property
    def is_deleted(self) -> bool:
        return self.deleted_at is not None