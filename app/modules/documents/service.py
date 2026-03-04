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

        # Sanitize the filename
        safe_name = sanitize_filename(file.filename) if file.filename else "unnamed_file"

        # Генерируем уникальное имя файла с оригинальным расширением
        file_extension = get_file_extension(safe_name)
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
        safe_name = sanitize_filename(file.filename) if file.filename else "unnamed_file"
        file_extension = get_file_extension(safe_name)
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
            file_name=safe_name,
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