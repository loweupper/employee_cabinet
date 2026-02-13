from sqlalchemy import func
from core.template_helpers import get_sidebar_context
from core.config import settings
from core.validators import (
    sanitize_filename,
    validate_file_extension,
    ALLOWED_DOCUMENT_EXTENSIONS
)
from modules.objects.models import Object, ObjectAccess
from fastapi import APIRouter, Depends, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse
from sqlalchemy.orm import Session
import logging
from typing import Optional
from datetime import datetime
from slowapi import Limiter
from slowapi.util import get_remote_address

from core.database import get_db
from modules.auth.dependencies import get_current_user_from_cookie
from modules.auth.models import User, UserRole
from modules.documents.schemas import *
from modules.documents.service import DocumentService
from modules.documents.models import Document, DocumentCategory, DocumentSubcategory

logger = logging.getLogger("app")

# Initialize rate limiter
limiter = Limiter(key_func=get_remote_address)

router = APIRouter(tags=["documents"])

from fastapi.templating import Jinja2Templates
templates = Jinja2Templates(directory="templates")


# ===================================
# Загрузка документов к объекту (множественная загрузка)
# ===================================
@router.post("/objects/{object_id}/documents/upload")
@limiter.limit("10/hour")
async def upload_documents(
    object_id: int,
    request: Request,
    category: str = Form(...),
    subcategory_id: Optional[int] = Form(None),
    user: User = Depends(get_current_user_from_cookie),
    db: Session = Depends(get_db)
):
    """
    Загрузить множество документов к объекту
    """

    logger.info({
        "event": "upload_documents_start",
        "object_id": object_id,
        "category": category,
        "subcategory_id": subcategory_id,
        "user_id": user.id
    })

    try:
        from modules.objects.service import ObjectService

        # Проверяем доступ
        obj = ObjectService.get_object(object_id, user, db)

        # Получаем файлы
        form = await request.form()
        files = form.getlist("files")

        logger.info({
            "event": "upload_documents_received_files",
            "count": len(files),
            "object_id": object_id,
            "user_id": user.id
        })

        if not files:
            return RedirectResponse(
                url=f"/objects/{object_id}?error=Файлы не выбраны",
                status_code=303
            )

        uploaded_count = 0
        errors = []

        for file in files:
            try:
                # ===== File Upload Security Validation =====
                
                # 1. Check file size - read content to validate actual size
                # Note: Reading entire file into memory is a trade-off between:
                # - Security: Prevents Content-Length header manipulation
                # - Memory: For large files, could use streaming (future improvement)
                # Current limit (10MB) is reasonable for in-memory processing
                file_contents = await file.read()
                actual_size = len(file_contents)
                
                if actual_size > settings.MAX_FILE_SIZE:
                    logger.warning({
                        "event": "file_upload_rejected_size",
                        "filename": file.filename,
                        "size": actual_size,
                        "max_size": settings.MAX_FILE_SIZE,
                        "object_id": object_id,
                        "user_id": user.id
                    })
                    errors.append(f"{file.filename} (слишком большой файл)")
                    continue
                
                # Reset file pointer after reading
                await file.seek(0)
                
                # 2. Validate file extension
                if not validate_file_extension(file.filename, ALLOWED_DOCUMENT_EXTENSIONS):
                    logger.warning({
                        "event": "file_upload_rejected_extension",
                        "filename": file.filename,
                        "object_id": object_id,
                        "user_id": user.id
                    })
                    errors.append(f"{file.filename} (недопустимый тип файла)")
                    continue
                
                # 3. Sanitize filename to prevent directory traversal
                safe_filename = sanitize_filename(file.filename) if file.filename else "unnamed_file"
                
                # ===== End Security Validation =====
                
                # Сохраняем файл (service also does sanitization)
                file_path = await DocumentService.save_file(file, object_id)

                # Название документа - используем os.path.splitext для надежности
                import os
                doc_title, _ = os.path.splitext(safe_filename)
                if not doc_title:
                    doc_title = "Документ"

                # Создаём документ
                document = Document(
                    title=doc_title,
                    description=None,
                    category=DocumentCategory(category),
                    subcategory_id=subcategory_id,
                    file_path=file_path,
                    file_name=safe_filename,  # Use sanitized filename
                    file_size=actual_size,  # Use actual validated size
                    file_type=file.content_type,
                    object_id=object_id,
                    created_by=user.id
                )

                db.add(document)
                uploaded_count += 1

            except Exception as e:
                logger.error({
                    "event": "ошибка_загрузки_документа",
                    "file": file.filename,
                    "object_id": object_id,
                    "user_id": user.id,
                    "error": str(e)
                })
                errors.append(file.filename)

        # Коммитим
        if uploaded_count > 0:
            db.commit()

        # Формируем сообщение
        message = f"Загружено {uploaded_count} документов"
        if errors:
            message += f". Ошибки: {', '.join(errors)}"

        logger.info({
            "event": "documents_uploaded",
            "object_id": object_id,
            "uploaded": uploaded_count,
            "errors": errors,
            "user_id": user.id
        })

        return RedirectResponse(
            url=f"/objects/{object_id}?success={message}",
            status_code=303
        )

    except Exception as e:
        logger.error({
            "event": "upload_documents_fatal_error",
            "object_id": object_id,
            "user_id": user.id,
            "error": str(e)
        })

        return RedirectResponse(
            url=f"/objects/{object_id}?error=Ошибка загрузки: {str(e)}",
            status_code=303
        )

# ===================================
# Обновление документа
# ===================================
@router.post("/objects/{object_id}/documents/{document_id}/update")
async def update_document(
    object_id: int,
    document_id: int,
    title: str = Form(...),
    category: str = Form(...),
    subcategory_id: Optional[int] = Form(None),
    user: User = Depends(get_current_user_from_cookie),
    db: Session = Depends(get_db)
):
    """
    Обновить название, категорию и подкатегорию документа
    """
    try:
        # Получаем документ
        document = db.query(Document).filter(Document.id == document_id).first()
        
        if not document:
            return RedirectResponse(
                url=f"/objects/{object_id}?error=Документ не найден",
                status_code=303
            )
        
        # Проверяем доступ (только владелец объекта или админ)
        from modules.objects.service import ObjectService
        obj = ObjectService.get_object(object_id, user, db)
        
        if obj.created_by != user.id and user.role != "admin":
            return RedirectResponse(
                url=f"/objects/{object_id}?error=Нет прав для редактирования",
                status_code=303
            )
        
        # Обновляем данные
        document.title = title
        document.category = DocumentCategory(category)
        document.subcategory_id = subcategory_id if subcategory_id else None
        
        db.commit()
        
        logger.info({
            "event": "document_updated",
            "document_id": document_id,
            "object_id": object_id,
            "new_category": category,
            "new_subcategory_id": subcategory_id,
            "user_id": user.id
        })
        
        return RedirectResponse(
            url=f"/objects/{object_id}?success=Документ обновлён",
            status_code=303
        )
        
    except Exception as e:
        logger.error(f"❌ Ошибка обновления документа: {str(e)}")
        return RedirectResponse(
            url=f"/objects/{object_id}?error=Ошибка обновления: {str(e)}",
            status_code=303
        )


# ===================================
# Удаление документа
# ===================================
@router.post("/objects/{object_id}/documents/{document_id}/delete")
async def delete_document(
    object_id: int,
    document_id: int,
    user: User = Depends(get_current_user_from_cookie),
    db: Session = Depends(get_db)
):
    """
    Удалить документ (мягкое удаление)
    """
    try:
        # Получаем документ
        document = db.query(Document).filter(Document.id == document_id).first()
        
        if not document:
            return RedirectResponse(
                url=f"/objects/{object_id}?error=Документ не найден",
                status_code=303
            )
        
        # Проверяем доступ (только владелец объекта или админ)
        from modules.objects.service import ObjectService
        obj = ObjectService.get_object(object_id, user, db)
        
        if obj.created_by != user.id and user.role != "admin":
            return RedirectResponse(
                url=f"/objects/{object_id}?error=Нет прав для удаления",
                status_code=303
            )
        
        # Мягкое удаление
        document.deleted_at = datetime.utcnow()
        document.is_active = False
        
        db.commit()
        
        logger.info({
            "event": "document_deleted",
            "document_id": document_id,
            "object_id": object_id,
            "file_name": document.file_name,
            "user_id": user.id
        })
        
        return RedirectResponse(
            url=f"/objects/{object_id}?success=Документ удалён",
            status_code=303
        )
        
    except Exception as e:
        logger.error(f"❌ Ошибка удаления документа: {str(e)}")
        return RedirectResponse(
            url=f"/objects/{object_id}?error=Ошибка удаления: {str(e)}",
            status_code=303
        )

# ===================================
# Скачивание документа
# ===================================
@router.get("/documents/{document_id}/download")
async def download_document(
    document_id: int,
    user: User = Depends(get_current_user_from_cookie),
    db: Session = Depends(get_db)
):
    """
    Скачать документ
    """
    document = db.query(Document).filter(Document.id == document_id).first()
    
    if not document:
        raise HTTPException(status_code=404, detail="Документ не найден")
    
    # Проверяем доступ
    if not document.can_access(user):
        raise HTTPException(status_code=403, detail="Нет доступа к этому документу")
    
    logger.info({
        "event": "document_downloaded",
        "document_id": document_id,
        "user_id": user.id
    })
    
    return FileResponse(
        path=document.file_path,
        filename=document.file_name,
        media_type=document.file_type
    )

# ===================================
# Просмотр списка документов объекта с фильтрацией по категориям
# ===================================
@router.get("", response_class=HTMLResponse)
async def documents_list(
    request: Request,
    object_id: int,
    category: str = None,
    user: User = Depends(get_current_user_from_cookie),
    db: Session = Depends(get_db)
):
    """Список документов объекта с фильтрацией по категориям"""
    
    # Проверяем доступ к объекту
    obj = db.query(Object).filter(Object.id == object_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="Объект не найден")
    
    # ✅ ИСПРАВЛЕНИЕ: Проверка доступа
    if user.role != UserRole.ADMIN:
        access = db.query(ObjectAccess).filter(
            ObjectAccess.user_id == user.id,
            ObjectAccess.object_id == object_id
        ).first()
        
        if not access:
            raise HTTPException(status_code=403, detail="Доступ запрещён")
    
    # ✅ ИСПРАВЛЕНИЕ: Базовый запрос документов
    query = db.query(Document).filter(
        Document.object_id == object_id,
        Document.deleted_at == None
    )
    
    # ✅ ИСПРАВЛЕНИЕ: Фильтрация по категориям с учётом доступов
    allowed_categories = []
    
    if user.role == UserRole.ADMIN:
        # Админ видит всё
        if category:
            # ✅ Фильтруем по Document.category (это enum в самой таблице Document)
            query = query.filter(Document.category == DocumentCategory(category))
    else:
        # Обычный пользователь
        access = db.query(ObjectAccess).filter(
            ObjectAccess.user_id == user.id,
            ObjectAccess.object_id == object_id
        ).first()
        
        # Формируем список разрешённых категорий
        allowed_categories = [DocumentCategory.GENERAL]  # Общие документы доступны всем
        
        # ✅ Добавляем категории на основе access_departments
        if access and access.access_departments:
            dept_mapping = {
                'safety': DocumentCategory.SAFETY,
                'hr': DocumentCategory.HR, 
                'accounting': DocumentCategory.ACCOUNTING,
                'technical': DocumentCategory.TECHNICAL,
                'legal': DocumentCategory.LEGAL
            }
            
            for dept in access.access_departments:
                if dept in dept_mapping:
                    cat = dept_mapping[dept]
                    if cat not in allowed_categories:
                        allowed_categories.append(cat)
        
        # ✅ ВАЖНО: Также добавляем категорию на основе роли пользователя
        role_to_category = {
            UserRole.ENGINEER: DocumentCategory.TECHNICAL,
            UserRole.LAWYER: DocumentCategory.LEGAL,
            UserRole.ACCOUNTANT: DocumentCategory.ACCOUNTING,
            UserRole.HR: DocumentCategory.HR
        }
        
        if user.role in role_to_category:
            cat = role_to_category[user.role]
            if cat not in allowed_categories:
                allowed_categories.append(cat)
        
        # Если указана конкретная категория
        if category:
            category_enum = DocumentCategory(category)
            
            # Проверяем доступ к этой категории
            if category_enum not in allowed_categories:
                raise HTTPException(status_code=403, detail="Доступ к этой категории запрещён")
            
            # ✅ Фильтруем по Document.category
            query = query.filter(Document.category == category_enum)
        else:
            # Показываем только документы из разрешённых категорий
            query = query.filter(Document.category.in_(allowed_categories))
    
    documents = query.order_by(Document.uploaded_at.desc()).all()
    
    # Получаем статистику по категориям (с учётом доступов)
    if user.role == UserRole.ADMIN:
        # Админ видит все категории
        categories_stats = db.query(
            Document.category,
            func.count(Document.id).label('count')
        ).filter(
            Document.object_id == object_id,
            Document.deleted_at == None
        ).group_by(Document.category).all()
    else:
        # Обычный пользователь видит только свои категории
        categories_stats = db.query(
            Document.category,
            func.count(Document.id).label('count')
        ).filter(
            Document.object_id == object_id,
            Document.deleted_at == None,
            Document.category.in_(allowed_categories)
        ).group_by(Document.category).all()
    
    # ✅ Преобразуем enum в строку для шаблона
    categories_dict = {cat.value: count for cat, count in categories_stats}
    
    logger.info({
        "event": "documents_list_viewed",
        "user_id": user.id,
        "object_id": object_id,
        "category": category,
        "total_documents": len(documents),
        "allowed_categories": [c.value for c in allowed_categories] if user.role != UserRole.ADMIN else "all"
    })
    
    sidebar_context = get_sidebar_context(user, db)
    
    return templates.TemplateResponse(
        "web/documents/list.html",
        {
            "request": request,
            "user": user,
            "object": obj,
            "documents": documents,
            "current_category": category,
            "categories_count": categories_dict,
            **sidebar_context
        }
    )