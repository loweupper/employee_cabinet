from sqlalchemy import func
from core.template_helpers import get_sidebar_context
from core.config import settings
from core.constants import UserRole  # ✅ импорт из constants
from core.validators import (
    validate_file_extension,
    ALLOWED_DOCUMENT_EXTENSIONS
)
from modules.objects.models import Object, ObjectAccess
from fastapi import APIRouter, Depends, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse, JSONResponse
from pathlib import Path
from sqlalchemy.orm import Session
import logging
import os
from typing import Optional
from datetime import datetime
from slowapi import Limiter
from slowapi.util import get_remote_address

from core.database import get_db
from modules.auth.dependencies import get_current_user_from_cookie
from modules.auth.models import User
from modules.documents.schemas import *
from modules.documents.service import DocumentService
from modules.documents.models import Document, DocumentCategory, DocumentSubcategory

logger = logging.getLogger("app")

# Initialize rate limiter
limiter = Limiter(key_func=get_remote_address)

router = APIRouter(tags=["documents"])

from fastapi.templating import Jinja2Templates
templates = Jinja2Templates(directory="templates")


def _is_ajax_request(request: Request) -> bool:
    """Detect if the request was made via AJAX/fetch expecting a JSON response."""
    return (
        request.headers.get("X-Requested-With") == "XMLHttpRequest"
        or "application/json" in request.headers.get("Accept", "")
    )


# ===================================
# Загрузка документов к объекту (множественная загрузка)
# ===================================
@router.post("/objects/{object_id}/upload")
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
            if _is_ajax_request(request):
                return JSONResponse(
                    status_code=400,
                    content={"detail": "Файлы не выбраны"}
                )
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
                
                # ===== End Security Validation =====
                
                # Сохраняем файл (service also does sanitization)
                file_path = await DocumentService.save_file(file, object_id)

                # Используем ОРИГИНАЛЬНОЕ имя для БД
                original_filename = file.filename if file.filename else "unnamed_file"

                # Название документа из оригинального имени
                doc_title, _ = os.path.splitext(original_filename)
                if not doc_title:
                    doc_title = "Документ"

                # Создаём документ
                document = Document(
                    title=doc_title,
                    description=None,
                    category=DocumentCategory(category),
                    subcategory_id=subcategory_id,
                    file_path=file_path,
                    file_name=original_filename,  # Use original filename for display/download
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
            message += f". Ошибки: {', '.join(errors[:3])}"  # Показываем максимум 3 ошибки

        logger.info({
            "event": "documents_uploaded",
            "object_id": object_id,
            "uploaded": uploaded_count,
            "error_count": len(errors),
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

        if _is_ajax_request(request):
            return JSONResponse(
                status_code=500,
                content={"detail": f"Ошибка загрузки: {str(e)}"}
            )
        return RedirectResponse(
            url=f"/objects/{object_id}?error=Ошибка загрузки: {str(e)}",
            status_code=303
        )

# ===================================
# Обновление документа
# ===================================
@router.post("/objects/{object_id}/{document_id}/update")
async def update_document(
    object_id: int,
    document_id: int,
    request: Request,
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
            if _is_ajax_request(request):
                return JSONResponse(status_code=404, content={"detail": "Документ не найден"})
            return RedirectResponse(
                url=f"/objects/{object_id}?error=Документ не найден",
                status_code=303
            )

        # Проверяем доступ (только владелец объекта или админ)
        from modules.objects.service import ObjectService
        obj = ObjectService.get_object(object_id, user, db)

        if obj.created_by != user.id and user.role != UserRole.ADMIN:  # ✅ исправлено
            if _is_ajax_request(request):
                return JSONResponse(status_code=403, content={"detail": "Нет прав для редактирования"})
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
@router.post("/objects/{object_id}/{document_id}/delete")
async def delete_document(
    object_id: int,
    document_id: int,
    request: Request,
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
            if _is_ajax_request(request):
                return JSONResponse(status_code=404, content={"detail": "Документ не найден"})
            return RedirectResponse(
                url=f"/objects/{object_id}?error=Документ не найден",
                status_code=303
            )

        # Проверяем доступ (только владелец объекта или админ)
        from modules.objects.service import ObjectService
        obj = ObjectService.get_object(object_id, user, db)

        if obj.created_by != user.id and user.role != UserRole.ADMIN:  # ✅ исправлено
            if _is_ajax_request(request):
                return JSONResponse(status_code=403, content={"detail": "Нет прав для удаления"})
            return RedirectResponse(
                url=f"/objects/{object_id}?error=Нет прав для удаления",
                status_code=303
            )
        
        # ✅ Удаляем файл с диска
        file_path = Path(settings.FILES_PATH) / document.file_path
        if file_path.exists():
            try:
                file_path.unlink()
                logger.info(f"✅ File deleted: {file_path}")
            except Exception as e:
                logger.error(f"Could not delete file {file_path}: {e}")
        
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
@router.get("/{document_id}/download")
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
    if not document.can_access(user, db):
        raise HTTPException(status_code=403, detail="Нет доступа к этому документу")

    # Полный путь = FILES_PATH + relative_path_from_db
    files_base = Path(settings.FILES_PATH).resolve()
    file_path = (files_base / document.file_path).resolve()

    # Защита от path traversal: убедиться, что путь находится внутри FILES_PATH
    if not str(file_path).startswith(str(files_base)):
        raise HTTPException(status_code=400, detail="Недопустимый путь к файлу")

    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Файл не найден на диске")

    logger.info({
        "event": "document_downloaded",
        "document_id": document_id,
        "user_id": user.id
    })

    return FileResponse(
        path=file_path,
        filename=document.file_name,
        media_type=document.file_type
    )

# ===================================
# Просмотр списка документов объекта с фильтрацией по категориям
# ===================================
@router.get("/objects", response_class=HTMLResponse)
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
    if user.role != UserRole.ADMIN:  # ✅ используем Enum
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
    
    if user.role == UserRole.ADMIN:  # ✅ используем Enum
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
        
        # ✅ Добавляем категории на основе sections_access
        if access and access.sections_access:
            dept_mapping = {
                'safety': DocumentCategory.SAFETY,
                'hr': DocumentCategory.HR, 
                'accounting': DocumentCategory.ACCOUNTING,
                'technical': DocumentCategory.TECHNICAL,
                'legal': DocumentCategory.LEGAL
            }
            
            for section in access.sections_access:
                if section in dept_mapping:
                    cat = dept_mapping[section]
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
    
    documents = query.order_by(Document.created_at.desc()).all()
    
    # Получаем статистику по категориям (с учётом доступов)
    if user.role == UserRole.ADMIN:  # ✅ используем Enum
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


# ===================================
# Обновление файла документа (версионирование)
# ===================================
@router.post("/{document_id}/update")
async def update_document_file(
    document_id: int,
    request: Request,
    user: User = Depends(get_current_user_from_cookie),
    db: Session = Depends(get_db)
):
    """Обновить содержимое документа (новая версия)"""
    document = db.query(Document).filter(
        Document.id == document_id,
        Document.is_active == True,
        Document.deleted_at == None
    ).first()

    if not document:
        return JSONResponse(status_code=404, content={"detail": "Документ не найден"})

    # Проверяем права
    if not DocumentService.can_update_document(user, document, db):
        return JSONResponse(status_code=403, content={"detail": "Нет прав для обновления"})

    try:
        form = await request.form()
        file = form.get("file")

        if not file or not file.filename:
            return JSONResponse(status_code=400, content={"detail": "Файл не выбран"})

        # Валидация расширения
        if not validate_file_extension(file.filename, ALLOWED_DOCUMENT_EXTENSIONS):
            return JSONResponse(status_code=400, content={"detail": "Недопустимый тип файла"})

        # Валидация размера
        file_contents = await file.read()
        actual_size = len(file_contents)
        if actual_size > settings.MAX_FILE_SIZE:
            return JSONResponse(status_code=400, content={"detail": "Файл слишком большой"})

        await file.seek(0)

        # Удаляем старый файл
        old_file_path = Path(settings.FILES_PATH) / document.file_path
        if old_file_path.exists():
            try:
                old_file_path.unlink()
            except Exception as e:
                logger.warning(f"Не удалось удалить старый файл {old_file_path}: {e}")

        # Сохраняем новый файл
        new_file_path = await DocumentService.save_file(file, document.object_id)

        # Обновляем запись документа
        original_filename = file.filename if file.filename else document.file_name
        document.file_path = new_file_path
        document.file_name = original_filename
        document.file_size = actual_size
        document.file_type = file.content_type
        document.version = (document.version or 1) + 1
        document.updated_by = user.id
        document.updated_at = datetime.utcnow()

        db.commit()

        logger.info({
            "event": "document_file_updated",
            "document_id": document_id,
            "version": document.version,
            "user_id": user.id
        })

        return JSONResponse({"status": "ok", "version": document.version})

    except Exception as e:
        logger.error(f"Ошибка обновления файла документа: {str(e)}")
        return JSONResponse(status_code=500, content={"detail": str(e)})


# ===================================
# Массовое удаление документов
# ===================================
@router.post("/batch-delete")
async def batch_delete_documents(
    request: Request,
    user: User = Depends(get_current_user_from_cookie),
    db: Session = Depends(get_db)
):
    """Удалить несколько документов одновременно"""
    try:
        data = await request.json()
    except Exception:
        return JSONResponse(status_code=400, content={"detail": "Некорректный JSON"})

    document_ids = data.get("document_ids", [])

    if not document_ids:
        return JSONResponse(status_code=400, content={"detail": "Не указаны документы"})

    try:
        deleted_count = 0

        for doc_id in document_ids:
            doc = db.query(Document).filter(
                Document.id == doc_id,
                Document.is_active == True,
                Document.deleted_at == None
            ).first()

            if not doc:
                continue

            # Проверяем права
            if not DocumentService.can_delete_document(user, doc, db):
                continue

            # Удаляем файл с диска
            file_path = Path(settings.FILES_PATH) / doc.file_path
            if file_path.exists():
                try:
                    file_path.unlink()
                except Exception as e:
                    logger.warning(f"Не удалось удалить файл {file_path}: {e}")

            # Мягкое удаление в БД
            doc.deleted_at = datetime.utcnow()
            doc.is_active = False
            deleted_count += 1

        db.commit()

        logger.info({
            "event": "documents_batch_deleted",
            "count": deleted_count,
            "user_id": user.id
        })

        return JSONResponse({"status": "ok", "deleted": deleted_count})

    except Exception as e:
        logger.error(f"Ошибка массового удаления: {str(e)}")
        return JSONResponse(status_code=500, content={"detail": str(e)})