# Модели для работы с документами app\modules\documents\models.py
from datetime import datetime
from enum import Enum
from sqlalchemy import (
    Column, BigInteger, String, Text, DateTime,
    ForeignKey, Enum as SqlEnum, func, Index, Integer, Boolean
)
from sqlalchemy.orm import relationship
from core.database import Base



# ===================================
# Enum для категории документа
# ===================================
class DocumentCategory(str, Enum):
    GENERAL = "general"              # Общие
    ACCOUNTING = "accounting"        # Бухгалтерия
    SAFETY = "safety"                # Охрана труда
    TECHNICAL = "technical"          # Технические
    LEGAL = "legal"                  # Юридические
    HR = "hr"                        # Кадровые

# ===================================
# Иконки и названия категорий
# ===================================
CATEGORY_INFO = {
    "general": {"emoji": "📋", "name": "Общие"},
    "technical": {"emoji": "📐", "name": "Технические"},
    "accounting": {"emoji": "💰", "name": "Бухгалтерия"},
    "safety": {"emoji": "👷", "name": "Охрана труда"},
    "legal": {"emoji": "⚖️", "name": "Юридические"},
    "hr": {"emoji": "👔", "name": "Кадровые"},
}


# ===================================
# Модель подкатегории документа
# ===================================
class DocumentSubcategory(Base):
    __tablename__ = "document_subcategories"

    id = Column(BigInteger, primary_key=True, index=True, autoincrement=True)
    
    # Основная информация
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    
    # Категория (к какому разделу относится)
    category = Column(
        SqlEnum(DocumentCategory, native_enum=False),
        nullable=False,
        index=True
    )
    
    # Объект (подкатегория привязана к конкретному объекту)
    object_id = Column(BigInteger, ForeignKey("objects.id", ondelete="CASCADE"), nullable=False)
    
    # Заказчик
    created_by = Column(BigInteger, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    
    # Статус
    is_active = Column(Boolean, default=True, nullable=False)
    order = Column(Integer, default=0)  # Порядок отображения
    
    # Временные метки
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    deleted_at = Column(DateTime(timezone=True), nullable=True)
    
    # Связи
    object = relationship("Object", backref="document_subcategories", lazy="joined")
    creator = relationship("User", backref="document_subcategories_created", lazy="joined")
    documents = relationship("Document", backref="subcategory_ref", lazy="joined")
    
    # Индексы
    __table_args__ = (
        Index("ix_subcategory_object_category", "object_id", "category"),
        Index("ix_subcategory_object", "object_id"),
    )
    
    def __repr__(self):
        return f"<DocumentSubcategory id={self.id} name={self.name} category={self.category}>"

# ===================================
# Маппинг категорий на отделы
# ===================================
CATEGORY_DEPARTMENT_MAP = {
    DocumentCategory.GENERAL: None,  # Доступно всем
    DocumentCategory.ACCOUNTING: "Бухгалтерия",
    DocumentCategory.SAFETY: "Охрана труда",
    DocumentCategory.TECHNICAL: "Технический отдел",
    DocumentCategory.LEGAL: "Юридический",
    DocumentCategory.HR: "Отдел кадров",
}


# ===================================
# Модель документа 
# ===================================
class Document(Base):
    __tablename__ = "documents"

    id = Column(BigInteger, primary_key=True, index=True, autoincrement=True)
    
    # Основная информация
    title = Column(String(255), nullable=False, index=True)
    description = Column(Text, nullable=True)
    
    # Категория
    category = Column(
        SqlEnum(DocumentCategory, native_enum=False),
        default=DocumentCategory.GENERAL,
        nullable=False,
        index=True
    )
    
    # ✅ Подкатегория (связь с подкатегорией)
    subcategory_id = Column(BigInteger, ForeignKey("document_subcategories.id", ondelete="SET NULL"), nullable=True)
    
    # Файл
    file_path = Column(String(500), nullable=False)
    file_name = Column(String(255), nullable=False)
    file_size = Column(BigInteger, nullable=False)
    file_type = Column(String(100), nullable=True)
    
    # Связь с объектом
    object_id = Column(BigInteger, ForeignKey("objects.id", ondelete="CASCADE"), nullable=False)
    
    # Владелец и редактор
    created_by = Column(BigInteger, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    updated_by = Column(BigInteger, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    
    # Версионирование
    version = Column(Integer, default=1, nullable=False)
    
    # Статус
    is_active = Column(Boolean, default=True, nullable=False)
    
    # Временные метки
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    deleted_at = Column(DateTime(timezone=True), nullable=True)
    
    # Связи
    object = relationship("Object", backref="documents", lazy="joined")
    creator = relationship("User", foreign_keys=[created_by], backref="documents_created", lazy="joined")
    editor = relationship("User", foreign_keys=[updated_by], lazy="joined")
    
    # Индексы
    __table_args__ = (
        Index("ix_documents_object_id", "object_id"),
        Index("ix_documents_category", "category"),
        Index("ix_documents_object_category", "object_id", "category"),
        Index("ix_documents_subcategory_id", "subcategory_id"),
    )
    
    def __repr__(self):
        return f"<Document id={self.id} title={self.title}>"
    
    @property
    def is_deleted(self) -> bool:
        return self.deleted_at is not None
    
    def can_access(self, user) -> bool:
        """
        Проверить, может ли пользователь видеть этот документ
        """
        # Общие документы — доступны всем с доступом к объекту
        if self.category == DocumentCategory.GENERAL:
            return True
        
        # Документы отдела — только для пользователей этого отдела
        required_department = CATEGORY_DEPARTMENT_MAP.get(self.category)
        if required_department and user.department_id == required_department:
            return True
        
        # Админы видят всё
        if user.role == "admin":
            return True
        
        # Создатель документа видит всё
        if self.created_by == user.id:
            return True
        
        return False