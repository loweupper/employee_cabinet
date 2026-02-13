from fastapi import HTTPException, status, UploadFile
from sqlalchemy.orm import Session
from typing import List, Optional
import logging
import os
from pathlib import Path

from modules.documents.models import Document, DocumentCategory, CATEGORY_DEPARTMENT_MAP
from modules.documents.schemas import DocumentCreate
from modules.auth.models import User
from modules.objects.models import ObjectAccess
from core.validators import sanitize_filename
import uuid
import shutil

logger = logging.getLogger("app")


class DocumentService:
    """Бизнес-логика для работы с документами"""

    @staticmethod
    async def save_file(file: UploadFile, object_id: int) -> str:
        """
        Сохранить загруженный файл на диск
        Возвращает путь к сохранённому файлу
        """
        # Создаём папку для загрузок если её нет
        upload_dir = Path(f"files/objects/{object_id}")
        upload_dir.mkdir(parents=True, exist_ok=True)
        
        # Sanitize the filename
        safe_name = sanitize_filename(file.filename) if file.filename else "unnamed_file"
        
        # Генерируем уникальное имя файла с оригинальным расширением
        file_extension = Path(safe_name).suffix
        unique_filename = f"{uuid.uuid4()}{file_extension}"
        file_path = upload_dir / unique_filename
        
        # Сохраняем файл
        file_contents = await file.read()
        with open(file_path, "wb") as f:
            f.write(file_contents)
        
        logger.info(f"✅ Файл сохранён: {file_path}")
        
        return str(file_path)

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
        
        # Создаем директорию для файлов объекта
        upload_dir = Path(f"files/objects/{data.object_id}")
        upload_dir.mkdir(parents=True, exist_ok=True)
        
        # Сохраняем файл
        file_contents = await file.read()
        file_path = upload_dir / file.filename
        
        with open(file_path, "wb") as f:
            f.write(file_contents)
        
        # Создаем запись в БД
        document = Document(
            title=data.title,
            description=data.description,
            category=data.category,
            object_id=data.object_id,
            file_path=str(file_path),
            file_name=file.filename,
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
        Получить список документов объекта (с учетом прав доступа)
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
        
        # Фильтруем по правам доступа
        accessible_documents = [
            doc for doc in all_documents 
            if doc.can_access(user)
        ]
        
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
    
    