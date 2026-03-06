from fastapi import HTTPException, status, UploadFile
from sqlalchemy.orm import Session
from typing import List, Optional
import logging
from pathlib import Path
from datetime import datetime

from modules.documents.models import Document, DocumentCategory
from modules.documents.schemas import DocumentCreate
from modules.documents.service_mappings import CategoryMappingService
from modules.auth.models import User
from core.validators import sanitize_filename, get_file_extension
from core.config import settings
import uuid
from modules.objects.models import Object, ObjectAccess
from modules.auth.models import UserRole


logger = logging.getLogger("app")


class DocumentService:
    """Бизнес-логика для работы с документами"""

    @staticmethod
    async def save_file(file: UploadFile, object_id: int) -> str:
        """
        Сохранить загруженный файл на диск с структурой: YYYY/MM/ObjectID/uuid-filename
        Возвращает относительный путь для сохранения в БД
        """
        now = datetime.now()
        year = f"{now.year}"
        month = f"{now.month:02d}"

        # Относительный путь в БД
        relative_path = f"{year}/{month}/{object_id}"

        # Полный путь на диске
        upload_dir = Path(settings.FILES_PATH) / relative_path
        upload_dir.mkdir(parents=True, exist_ok=True)

        # Определяем расширение из оригинального имени (ДО sanitize)
        original_filename = file.filename if file.filename else "unnamed_file"
        file_extension = get_file_extension(original_filename)

        # Генерируем уникальное имя файла с правильным расширением
        unique_filename = f"{uuid.uuid4().hex[:12]}{file_extension}"
        file_path = upload_dir / unique_filename

        # Сохраняем файл
        file_contents = await file.read()
        with open(file_path, "wb") as f:
            f.write(file_contents)

        logger.info(f"✅ File saved: {file_path}")

        # Возвращаем относительный путь для сохранения в БД
        return f"{relative_path}/{unique_filename}"

    @staticmethod
    async def create_document(
        data: DocumentCreate,
        file: UploadFile,
        user: User,
        db: Session
    ) -> Document:
        """
        Создать документ и загрузить файл
        """
        # Проверяем доступ к объекту
        access = db.query(ObjectAccess).filter(
            ObjectAccess.object_id == data.object_id,
            ObjectAccess.user_id == user.id
        ).first()
        
        if not access and user.role != "admin":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Нет доступа к этому объекту"
            )
        
        # Создаем директорию для файлов объекта (YYYY/MM/ObjectID)
        now = datetime.now()
        relative_path = f"{now.year}/{now.month:02d}/{data.object_id}"
        upload_dir = Path(settings.FILES_PATH) / relative_path
        upload_dir.mkdir(parents=True, exist_ok=True)

        # Сохраняем файл
        file_contents = await file.read()
        # Определяем расширение из оригинального имени (ДО sanitize)
        original_filename = file.filename if file.filename else "unnamed_file"
        file_extension = get_file_extension(original_filename)
        unique_filename = f"{uuid.uuid4().hex[:12]}{file_extension}"
        file_path = upload_dir / unique_filename

        with open(file_path, "wb") as f:
            f.write(file_contents)

        # Создаем запись в БД (сохраняем относительный путь)
        document = Document(
            title=data.title,
            description=data.description,
            category=data.category,
            object_id=data.object_id,
            file_path=f"{relative_path}/{unique_filename}",
            file_name=original_filename,
            file_size=len(file_contents),
            file_type=file.content_type,
            created_by=user.id
        )
        
        db.add(document)
        db.commit()
        db.refresh(document)
        
        logger.info({
            "event": "document_created",
            "document_id": document.id,
            "object_id": data.object_id,
            "category": data.category,
            "user_id": user.id
        })
        
        return document
    
    @staticmethod
    def list_documents(
        object_id: int,
        user: User,
        db: Session,
        category: Optional[DocumentCategory] = None
    ) -> List[Document]:
        """
        Получить список документов объекта (с учетом прав доступа к разделам)
        """
     # Базовый запрос
        query = db.query(Document).filter(
            Document.object_id == object_id,
            Document.deleted_at == None,
            Document.is_active == True
        )
    
        # Фильтр по категории
        if category:
            query = query.filter(Document.category == category)
    
        # Получаем все документы
        all_documents = query.order_by(Document.created_at.desc()).all()
    
        # Получаем объект для проверки владельца
        obj = db.query(Object).filter(Object.id == object_id).first()
    
        # Админ и владелец объекта видят всё
        if user.role == "admin" or (obj and obj.created_by == user.id):
            return all_documents
    
        # Получаем доступ пользователя к объекту
        access = db.query(ObjectAccess).filter(
            ObjectAccess.object_id == object_id,
            ObjectAccess.user_id == user.id
        ).first()
    
        if not access:
            return []  # Нет доступа - нет документов
    
        # ✅ ФИЛЬТРАЦИЯ ПО РАЗДЕЛАМ ДОСТУПА
        accessible_documents = []
        mapping_dict = CategoryMappingService.get_mapping_dict(db)

        for doc in all_documents:
            # Общие документы доступны всем, у кого есть доступ к объекту
            if doc.category == DocumentCategory.GENERAL:
                accessible_documents.append(doc)
                continue
        
            # Проверяем, есть ли у пользователя доступ к категории документа
            if access.has_section_access(doc.category.value):
                accessible_documents.append(doc)
                continue
        
            # Проверка по отделу через БД (с fallback на статический маппинг)
            required_dept_id = mapping_dict.get(doc.category.value)
            if required_dept_id and user.department_id == required_dept_id:
                accessible_documents.append(doc)
                continue
    
        return accessible_documents
    
    @staticmethod
    def get_documents_by_category(
        object_id: int,
        user: User,
        db: Session
    ) -> dict:
        """
        Получить документы, сгруппированные по категориям
        """
        all_docs = DocumentService.list_documents(object_id, user, db)
        
        result = {}
        for category in DocumentCategory:
            category_docs = [
                doc for doc in all_docs 
                if doc.category == category
            ]
            if category_docs:
                result[category] = category_docs
        
        return result
    
    @staticmethod
    def can_upload_document(user: User, obj: Object, db: Session) -> bool:
        """
        Проверить может ли пользователь загружать документы в объект.

        Может загружать ЕСЛИ:
        - Админ системы ИЛИ
        - Создал объект ИЛИ
        - Добавлен в объект с правом редактирования ИЛИ
        - Бухгалтер в категории "Бухгалтерия" (через отдел)
        """
        # 1. Админ системы
        if user.role == UserRole.ADMIN:
            return True

        # 2. Создатель объекта
        if obj.created_by == user.id:
            return True

        # 3. Добавлен в объект с правом редактирования
        access = db.query(ObjectAccess).filter(
            ObjectAccess.object_id == obj.id,
            ObjectAccess.user_id == user.id,
            ObjectAccess.role.in_(['admin', 'editor'])
        ).first()

        if access:
            return True

        # 4. Бухгалтер в категории "Бухгалтерия" через отдел
        if user.role == UserRole.ACCOUNTANT:
            mapping = CategoryMappingService.get_mapping_dict(db)
            if mapping.get('accounting') == user.department_id:
                return True

        return False

    @staticmethod
    def can_update_document(user: User, document: "Document", db: Session) -> bool:
        """
        Проверить может ли пользователь обновить документ.

        Может обновить ЕСЛИ:
        - Создал документ ИЛИ
        - Владелец объекта ИЛИ
        - Админ системы
        """
        # Админ системы
        if user.role == UserRole.ADMIN:
            return True

        # Создатель документа
        if document.created_by == user.id:
            return True

        # Владелец объекта
        if document.object and document.object.created_by == user.id:
            return True

        return False

    @staticmethod
    def can_delete_document(user: User, document: "Document", db: Session) -> bool:
        """
        Проверить может ли пользователь удалить документ
        (такие же права как и обновление)
        """
        return DocumentService.can_update_document(user, document, db)

    @staticmethod
    def get_accessible_categories(user: User, obj: Object, db: Session) -> list:
        """
        Получить список категорий, доступных пользователю для загрузки.

        Доступны ЕСЛИ:
        - Админ системы - все категории ИЛИ
        - Владелец объекта - все категории ИЛИ
        - Есть доступ к объекту и разрешения на раздел ИЛИ
        - Роль соответствует категории (бухгалтер → бухгалтерия)
        """
        all_categories = [
            DocumentCategory.GENERAL,
            DocumentCategory.TECHNICAL,
            DocumentCategory.ACCOUNTING,
            DocumentCategory.SAFETY,
            DocumentCategory.LEGAL,
            DocumentCategory.HR,
        ]

        # Админ и владелец видят всё
        if user.role == UserRole.ADMIN or obj.created_by == user.id:
            return all_categories

        # Получаем доступ к объекту
        access = db.query(ObjectAccess).filter(
            ObjectAccess.object_id == obj.id,
            ObjectAccess.user_id == user.id
        ).first()

        if not access:
            return []  # Нет доступа к объекту - нет категорий

        accessible = []
        mapping = CategoryMappingService.get_mapping_dict(db)

        # Общие документы всегда доступны
        accessible.append(DocumentCategory.GENERAL)

        # Проверяем доступ к остальным категориям
        for category in all_categories:
            if category == DocumentCategory.GENERAL:
                continue

            # Если у доступа указана категория - добавляем
            if access.has_section_access(category.value):
                accessible.append(category)
                continue

            # Проверяем по отделу (бухгалтер в отделе бухгалтерии → доступ к accounting)
            required_dept_id = mapping.get(category.value)
            if required_dept_id and user.department_id == required_dept_id:
                accessible.append(category)

        return accessible

    @staticmethod
    def sync_user_access_by_role(user: User, db: Session):
        """
        Синхронизировать доступ пользователя к документам на основе его роли
        """
        # Маппинг роли на раздел документов
        role_to_section = {
            UserRole.ENGINEER: "technical",
            UserRole.ACCOUNTANT: "accounting",
            UserRole.LAWYER: "legal",
            UserRole.HR: "hr",
        }
    
        # Получаем все доступы пользователя к объектам
        accesses = db.query(ObjectAccess).filter(ObjectAccess.user_id == user.id).all()
    
        for access in accesses:
            current_sections = access.sections_access or ["general"]
        
            # Добавляем раздел на основе роли
            if user.role in role_to_section:
                section = role_to_section[user.role]
                if section not in current_sections:
                    current_sections.append(section)
        
            access.sections_access = current_sections
    
        db.commit()