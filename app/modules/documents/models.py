# Модели для работы с документами app\modules\documents\models.py
from datetime import datetime
from enum import Enum
from sqlalchemy import (
    Column, BigInteger, String, Text, DateTime,
    ForeignKey, Enum as SqlEnum, func, Index, Integer, Boolean
)
from sqlalchemy.orm import relationship
from core.database import Base
from core.constants import DocumentCategory, CATEGORY_TO_DEPARTMENT, CATEGORY_DISPLAY
from sqlalchemy.orm import Session as OrmSession


# ===================================
# Иконки и названия категорий
# ===================================
CATEGORY_INFO = CATEGORY_DISPLAY

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
# Маппинг категорий на отделы (статический fallback)
# ===================================
CATEGORY_DEPARTMENT_MAP = {
    cat: dept.value if dept else None
    for cat, dept in CATEGORY_TO_DEPARTMENT.items()
}


# ===================================
# Модель маппинга категорий документов на отделы
# ===================================
class DocumentCategoryMapping(Base):
    __tablename__ = "document_category_mappings"

    id = Column(Integer, primary_key=True)
    category = Column(String(50), unique=True, nullable=False, index=True)
    department_id = Column(BigInteger, ForeignKey("departments.id"), nullable=True)
    description = Column(String(500))
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)

    department = relationship("Department", backref="category_mappings")

    def __repr__(self):
        return f"<DocumentCategoryMapping category={self.category} dept={self.department_id}>"


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

    # Файл - ОТНОСИТЕЛЬНЫЙ путь для удобства миграции
    # Пример: "2026/01/15/uuid-abc123.pdf"
    # Полный путь: Path(settings.FILES_PATH) / file_path
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

    def can_access(self, user, db: OrmSession = None) -> bool:
        """
        Проверить, может ли пользователь видеть этот документ
        с учетом прав доступа к объекту и разделам (sections_access)
        """
        from modules.objects.models import ObjectAccess

        # 1. Админы видят всё
        if user.role == "admin":
            return True

        # 2. Создатель документа видит всё
        if self.created_by == user.id:
            return True

        # 3. Проверяем доступ к объекту один раз
        access = db.query(ObjectAccess).filter(
            ObjectAccess.object_id == self.object_id,
            ObjectAccess.user_id == user.id
        ).first()

        # 4. Общие документы доступны всем, у кого есть доступ к объекту
        if self.category == DocumentCategory.GENERAL:
            return access is not None

        # 4. Проверка по отделу через БД (если передана сессия)
        if db is not None:
            from modules.documents.service_mappings import CategoryMappingService
            mapping = CategoryMappingService.get_mapping(db, self.category.value)
            if mapping and mapping.department_id and user.department_rel:
                if user.department_rel.id == mapping.department_id:
                    return True
        else:
            # Fallback на статический маппинг
            required_department_name = CATEGORY_DEPARTMENT_MAP.get(self.category)
            if required_department_name and user.department_rel:
                if user.department_rel.name == required_department_name:
                    return True

        return False