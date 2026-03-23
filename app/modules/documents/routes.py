import asyncio
import io
import logging
import os
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Optional

import slowapi.util as slowapi_util
from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    JSONResponse,
    RedirectResponse,
    StreamingResponse,
)
from fastapi.templating import Jinja2Templates
from slowapi import Limiter
from sqlalchemy import func
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from core.config import settings
from core.constants import UserRole  # ✅ импорт из constants
from core.database import get_db
from core.template_helpers import get_sidebar_context
from core.validators import (
    ALLOWED_DOCUMENT_EXTENSIONS,
    validate_file_extension,
)
from modules.auth.dependencies import get_current_user_from_cookie
from modules.auth.models import User
from modules.documents.models import Document, DocumentCategory
from modules.documents.service import DocumentService
from modules.objects.models import Object, ObjectAccess

logger = logging.getLogger("app")

# Initialize rate limiter
limiter = Limiter(key_func=slowapi_util.get_remote_address)

router = APIRouter(tags=["documents"])

templates = Jinja2Templates(directory="templates")

DOCUMENT_NOT_FOUND = "Документ не найден"


def _is_ajax_request(request: Request) -> bool:
    """Detect if request expects JSON (AJAX/fetch)."""
    accept_header = request.headers.get("Accept", "")
    return (
        request.headers.get("X-Requested-With") == "XMLHttpRequest"
        or "application/json" in accept_header
    )


def _resolve_document_file_path(stored_path: str) -> Path:
    """Resolve a DB path safely for relative and legacy absolute entries."""
    files_base = Path(settings.FILES_PATH).resolve()
    raw_path = Path(stored_path)

    # Relative paths are expected; absolute paths are legacy-compatible.
    resolved_path = (
        raw_path.resolve()
        if raw_path.is_absolute()
        else (files_base / raw_path).resolve()
    )

    # Cross-platform safe check (Windows drive letter case, etc.)
    base_norm = os.path.normcase(str(files_base))
    path_norm = os.path.normcase(str(resolved_path))

    try:
        is_inside_base = os.path.commonpath([path_norm, base_norm]) == base_norm
    except ValueError:
        is_inside_base = False

    if not is_inside_base:
        raise ValueError("Недопустимый путь к файлу")

    return resolved_path


def _get_object_access(
    db: Session,
    user_id: int,
    object_id: int,
) -> Optional[ObjectAccess]:
    return (
        db.query(ObjectAccess)
        .filter(
            ObjectAccess.user_id == user_id,
            ObjectAccess.object_id == object_id,
        )
        .first()
    )


def _get_allowed_categories_for_user(
    user: User,
    access: Optional[ObjectAccess],
) -> Optional[list[DocumentCategory]]:
    if user.role == UserRole.ADMIN:
        return None

    allowed_categories: list[DocumentCategory] = [DocumentCategory.GENERAL]
    dept_mapping = {
        "safety": DocumentCategory.SAFETY,
        "hr": DocumentCategory.HR,
        "accounting": DocumentCategory.ACCOUNTING,
        "technical": DocumentCategory.TECHNICAL,
        "legal": DocumentCategory.LEGAL,
    }

    if access and access.sections_access:
        for section in access.sections_access:
            category = dept_mapping.get(section)
            if category and category not in allowed_categories:
                allowed_categories.append(category)

    return allowed_categories


def _validate_requested_category(
    category: Optional[str],
    allowed_categories: Optional[list[DocumentCategory]],
) -> Optional[DocumentCategory]:
    if not category:
        return None

    category_enum = DocumentCategory(category)
    if allowed_categories is not None and category_enum not in allowed_categories:
        raise HTTPException(
            status_code=403,
            detail="Доступ к этой категории запрещён",
        )

    return category_enum


def _apply_documents_category_filter(
    query,
    category_enum: Optional[DocumentCategory],
    allowed_categories: Optional[list[DocumentCategory]],
):
    if category_enum is not None:
        return query.filter(Document.category == category_enum)
    if allowed_categories is not None:
        return query.filter(Document.category.in_(allowed_categories))
    return query


def _build_categories_stats(
    db: Session,
    object_id: int,
    allowed_categories: Optional[list[DocumentCategory]],
):
    stats_query = db.query(
        Document.category,
        func.count(Document.id).label("count"),
    )
    stats_query = stats_query.filter(
        Document.object_id == object_id,
        Document.deleted_at.is_(None),
    )
    if allowed_categories is not None:
        stats_query = stats_query.filter(Document.category.in_(allowed_categories))
    return stats_query.group_by(Document.category).all()


async def _validate_upload_file(
    file,
    object_id: int,
    user_id: int,
) -> tuple[bool, int, Optional[str]]:
    file_contents = await file.read()
    actual_size = len(file_contents)

    if actual_size > settings.MAX_FILE_SIZE:
        logger.warning(
            {
                "event": "file_upload_rejected_size",
                "filename": file.filename,
                "size": actual_size,
                "max_size": settings.MAX_FILE_SIZE,
                "object_id": object_id,
                "user_id": user_id,
            }
        )
        return False, actual_size, f"{file.filename} (слишком большой файл)"

    await file.seek(0)

    if not validate_file_extension(file.filename, ALLOWED_DOCUMENT_EXTENSIONS):
        logger.warning(
            {
                "event": "file_upload_rejected_extension",
                "filename": file.filename,
                "object_id": object_id,
                "user_id": user_id,
            }
        )
        return False, actual_size, f"{file.filename} (недопустимый тип файла)"

    return True, actual_size, None


def _find_existing_document(
    db: Session,
    object_id: int,
    original_filename: str,
    category: str,
    subcategory_id: Optional[int],
) -> Optional[Document]:
    return (
        db.query(Document)
        .filter(
            Document.object_id == object_id,
            Document.file_name == original_filename,
            Document.category == DocumentCategory(category),
            Document.subcategory_id == subcategory_id,
            Document.is_active.is_(True),
            Document.deleted_at.is_(None),
        )
        .first()
    )


def _replace_existing_document(
    existing_doc: Document,
    file_path: str,
    actual_size: int,
    file_content_type: Optional[str],
    user_id: int,
) -> None:
    old_file_path = Path(settings.FILES_PATH) / existing_doc.file_path
    if old_file_path.exists():
        try:
            old_file_path.unlink()
        except OSError as del_err:
            logger.warning(
                {
                    "event": "old_file_delete_failed",
                    "path": str(old_file_path),
                    "error": str(del_err),
                    "user_id": user_id,
                }
            )

    existing_doc.file_path = file_path
    existing_doc.file_size = actual_size
    existing_doc.file_type = file_content_type
    existing_doc.updated_by = user_id
    existing_doc.updated_at = datetime.now(timezone.utc)
    existing_doc.version = (existing_doc.version or 1) + 1


def _create_new_document(
    db: Session,
    object_id: int,
    original_filename: str,
    file_path: str,
    actual_size: int,
    file_content_type: Optional[str],
    category: str,
    subcategory_id: Optional[int],
    user_id: int,
) -> None:
    doc_title, _ = os.path.splitext(original_filename)
    if not doc_title:
        doc_title = "Документ"

    document = Document(
        title=doc_title,
        description=None,
        category=DocumentCategory(category),
        subcategory_id=subcategory_id,
        file_path=file_path,
        file_name=original_filename,
        file_size=actual_size,
        file_type=file_content_type,
        object_id=object_id,
        created_by=user_id,
    )
    db.add(document)


async def _process_upload_files(
    files,
    db: Session,
    object_id: int,
    category: str,
    subcategory_id: Optional[int],
    user_id: int,
) -> tuple[int, int, list[str]]:
    uploaded_count = 0
    updated_count = 0
    errors: list[str] = []

    for file in files:
        status, error_message = await _process_single_upload_file(
            file=file,
            db=db,
            object_id=object_id,
            category=category,
            subcategory_id=subcategory_id,
            user_id=user_id,
        )

        if status == "uploaded":
            uploaded_count += 1
        elif status == "updated":
            updated_count += 1
        elif error_message:
            errors.append(error_message)

    return uploaded_count, updated_count, errors


async def _process_single_upload_file(
    file,
    db: Session,
    object_id: int,
    category: str,
    subcategory_id: Optional[int],
    user_id: int,
) -> tuple[str, Optional[str]]:
    try:
        is_valid, actual_size, validation_error = await _validate_upload_file(
            file=file,
            object_id=object_id,
            user_id=user_id,
        )
        if not is_valid:
            return "invalid", validation_error

        original_filename = file.filename if file.filename else "unnamed_file"
        existing_doc = _find_existing_document(
            db=db,
            object_id=object_id,
            original_filename=original_filename,
            category=category,
            subcategory_id=subcategory_id,
        )
        file_path = await DocumentService.save_file(file, object_id)

        if existing_doc:
            _replace_existing_document(
                existing_doc=existing_doc,
                file_path=file_path,
                actual_size=actual_size,
                file_content_type=file.content_type,
                user_id=user_id,
            )
            logger.info(
                {
                    "event": "document_replaced",
                    "document_id": existing_doc.id,
                    "object_id": object_id,
                    "file_name": original_filename,
                    "new_version": existing_doc.version,
                    "user_id": user_id,
                }
            )
            return "updated", None

        _create_new_document(
            db=db,
            object_id=object_id,
            original_filename=original_filename,
            file_path=file_path,
            actual_size=actual_size,
            file_content_type=file.content_type,
            category=category,
            subcategory_id=subcategory_id,
            user_id=user_id,
        )
        return "uploaded", None

    except (OSError, ValueError, TypeError, SQLAlchemyError) as exc:
        logger.error(
            {
                "event": "ошибка_загрузки_документа",
                "file": file.filename,
                "object_id": object_id,
                "user_id": user_id,
                "error": str(exc),
            }
        )
        return "error", file.filename


def _build_upload_result_message(
    uploaded_count: int,
    updated_count: int,
    errors: list[str],
) -> str:
    parts = []
    if uploaded_count:
        parts.append(f"Загружено {uploaded_count} новых")
    if updated_count:
        parts.append(f"Обновлено {updated_count} существующих")

    message = ", ".join(parts) if parts else "Изменений нет"
    if errors:
        message += f". Ошибки: {', '.join(errors[:3])}"
    return message


# ===================================
# Загрузка документов к объекту (множественная загрузка)
# ===================================
@router.post("/objects/{object_id}/upload")
@limiter.limit("10/hour")
async def upload_documents(
    object_id: int,
    request: Request,
    category: Annotated[str, Form(...)],
    subcategory_id: Annotated[Optional[int], Form()] = None,
    user: User = Depends(get_current_user_from_cookie),
    db: Session = Depends(get_db),
):
    """
    Загрузить множество документов к объекту
    """

    # ✅ Сохраняем user.id до try-блока, чтобы избежать PendingRollbackError
    user_id = user.id

    logger.info("event=upload_documents_start")

    try:
        from modules.objects.service import ObjectService

        # Проверяем доступ
        ObjectService.get_object(object_id, user, db)

        # Получаем файлы
        form = await request.form()
        files = form.getlist("files")

        logger.info(
            {
                "event": "upload_documents_received_files",
                "count": len(files),
                "object_id": object_id,
                "user_id": user_id,
            }
        )

        if not files:
            if _is_ajax_request(request):
                return JSONResponse(
                    status_code=400, content={"detail": "Файлы не выбраны"}
                )
            return RedirectResponse(
                url=f"/objects/{object_id}?error=Файлы не выбраны",
                status_code=303,
            )

        uploaded_count, updated_count, errors = await _process_upload_files(
            files=files,
            db=db,
            object_id=object_id,
            category=category,
            subcategory_id=subcategory_id,
            user_id=user_id,
        )

        # Коммитим
        if uploaded_count > 0 or updated_count > 0:
            db.commit()

        message = _build_upload_result_message(
            uploaded_count=uploaded_count,
            updated_count=updated_count,
            errors=errors,
        )

        logger.info(
            {
                "event": "documents_uploaded",
                "object_id": object_id,
                "uploaded": uploaded_count,
                "updated": updated_count,
                "error_count": len(errors),
                "user_id": user_id,
            }
        )

        return RedirectResponse(
            url=f"/objects/{object_id}?success={message}", status_code=303
        )

    except (OSError, ValueError, TypeError, SQLAlchemyError) as e:
        logger.error(
            {
                "event": "upload_documents_fatal_error",
                "object_id": object_id,
                "user_id": user_id,
                "error": str(e),
            }
        )

        # ✅ Откатываем сессию при ошибке
        db.rollback()

        if _is_ajax_request(request):
            return JSONResponse(
                status_code=500,
                content={"detail": f"Ошибка загрузки: {str(e)}"},
            )
        return RedirectResponse(
            url=f"/objects/{object_id}?error=Ошибка загрузки: {str(e)}",
            status_code=303,
        )


# ===================================
# Обновление документа
# ===================================
@router.post("/objects/{object_id}/{document_id}/update")
async def update_document(
    object_id: int,
    document_id: int,
    request: Request,
    title: Annotated[str, Form(...)],
    category: Annotated[str, Form(...)],
    subcategory_id: Annotated[Optional[int], Form()] = None,
    user: User = Depends(get_current_user_from_cookie),
    db: Session = Depends(get_db),
):
    """
    Обновить название, категорию и подкатегорию документа
    """
    try:
        # Получаем документ
        document = db.query(Document).filter(Document.id == document_id).first()

        if not document:
            if _is_ajax_request(request):
                return JSONResponse(
                    status_code=404, content={"detail": DOCUMENT_NOT_FOUND}
                )
            return RedirectResponse(
                url=f"/objects/{object_id}?error={DOCUMENT_NOT_FOUND}",
                status_code=303,
            )

        # Проверяем доступ (только владелец объекта или админ)
        from modules.objects.service import ObjectService

        obj = ObjectService.get_object(object_id, user, db)

        if obj.created_by != user.id and user.role != UserRole.ADMIN:
            if _is_ajax_request(request):
                return JSONResponse(
                    status_code=403,
                    content={"detail": "Нет прав для редактирования"},
                )
            return RedirectResponse(
                url=f"/objects/{object_id}?error=Нет прав для редактирования",
                status_code=303,
            )

        # Обновляем данные
        document.title = title
        document.category = DocumentCategory(category)
        document.subcategory_id = subcategory_id if subcategory_id else None

        db.commit()

        logger.info("event=document_updated")

        return RedirectResponse(
            url=f"/objects/{object_id}?success=Документ обновлён",
            status_code=303,
        )

    except (SQLAlchemyError, ValueError, TypeError) as exc:
        logger.error("Ошибка обновления документа: %s", exc)
        return RedirectResponse(
            url=f"/objects/{object_id}?error=Ошибка обновления: {str(exc)}",
            status_code=303,
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
    db: Session = Depends(get_db),
):
    """
    Удалить документ (мягкое удаление)
    """
    try:
        # Получаем документ
        document = db.query(Document).filter(Document.id == document_id).first()

        if not document:
            if _is_ajax_request(request):
                return JSONResponse(
                    status_code=404, content={"detail": DOCUMENT_NOT_FOUND}
                )
            return RedirectResponse(
                url=f"/objects/{object_id}?error={DOCUMENT_NOT_FOUND}",
                status_code=303,
            )

        # Проверяем доступ (только владелец объекта или админ)
        from modules.objects.service import ObjectService

        obj = ObjectService.get_object(object_id, user, db)

        if obj.created_by != user.id and user.role != UserRole.ADMIN:
            if _is_ajax_request(request):
                return JSONResponse(
                    status_code=403,
                    content={"detail": "Нет прав для удаления"},
                )
            return RedirectResponse(
                url=f"/objects/{object_id}?error=Нет прав для удаления",
                status_code=303,
            )

        # ✅ Удаляем файл с диска
        file_path = Path(settings.FILES_PATH) / document.file_path
        if file_path.exists():
            try:
                file_path.unlink()
                logger.info("File deleted: %s", file_path)
            except OSError as exc:
                logger.error("Could not delete file %s: %s", file_path, exc)

        # Мягкое удаление
        document.deleted_at = datetime.now(timezone.utc)
        document.is_active = False

        db.commit()

        logger.info(
            {
                "event": "document_deleted",
                "document_id": document_id,
                "object_id": object_id,
                "file_name": document.file_name,
                "user_id": user.id,
            }
        )

        return RedirectResponse(
            url=f"/objects/{object_id}?success=Документ удалён",
            status_code=303,
        )

    except (SQLAlchemyError, ValueError, TypeError) as exc:
        logger.error("Ошибка удаления документа: %s", exc)
        return RedirectResponse(
            url=f"/objects/{object_id}?error=Ошибка удаления: {str(exc)}",
            status_code=303,
        )


# ===================================
# Скачивание документа
# ===================================
@router.get(
    "/{document_id}/open",
    responses={
        400: {"description": "Недопустимый путь к файлу"},
        403: {"description": "Нет доступа к этому документу"},
        404: {"description": "Документ или файл не найден"},
    },
)
async def open_document(
    document_id: int,
    user: User = Depends(get_current_user_from_cookie),
    db: Session = Depends(get_db),
):
    """Открыть документ в браузере (inline preview where possible)."""
    document = db.query(Document).filter(Document.id == document_id).first()

    if not document:
        raise HTTPException(status_code=404, detail=DOCUMENT_NOT_FOUND)

    if not document.can_access(user, db):
        raise HTTPException(
            status_code=403,
            detail="Нет доступа к этому документу",
        )

    try:
        file_path = _resolve_document_file_path(document.file_path)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Файл не найден на диске")

    logger.info(
        {
            "event": "document_opened",
            "document_id": document_id,
            "user_id": user.id,
        }
    )

    # Do not set filename to avoid forcing download disposition.
    return FileResponse(
        path=file_path,
        media_type=document.file_type,
    )


@router.get(
    "/{document_id}/download",
    responses={
        400: {"description": "Недопустимый путь к файлу"},
        403: {"description": "Нет доступа к этому документу"},
        404: {"description": "Документ или файл не найден"},
    },
)
async def download_document(
    document_id: int,
    user: User = Depends(get_current_user_from_cookie),
    db: Session = Depends(get_db),
):
    """
    Скачать документ
    """
    document = db.query(Document).filter(Document.id == document_id).first()

    if not document:
        raise HTTPException(status_code=404, detail=DOCUMENT_NOT_FOUND)

    # Проверяем доступ
    if not document.can_access(user, db):
        raise HTTPException(
            status_code=403,
            detail="Нет доступа к этому документу",
        )

    # Полный путь = FILES_PATH + path из БД (с поддержкой legacy absolute path)
    try:
        file_path = _resolve_document_file_path(document.file_path)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Файл не найден на диске")

    logger.info(
        {
            "event": "document_downloaded",
            "document_id": document_id,
            "user_id": user.id,
        }
    )

    return FileResponse(
        path=file_path,
        filename=document.file_name,
        media_type=document.file_type,
    )


# ===================================
# Просмотр списка документов объекта с фильтрацией по категориям
# ===================================
@router.get(
    "/objects",
    response_class=HTMLResponse,
    responses={
        403: {"description": "Доступ запрещён"},
        404: {"description": "Объект не найден"},
    },
)
async def documents_list(
    request: Request,
    object_id: int,
    user: User = Depends(get_current_user_from_cookie),
    db: Session = Depends(get_db),
    category: Optional[str] = None,
):
    """Список документов объекта с фильтрацией по категориям"""

    # Проверяем доступ к объекту
    obj = db.query(Object).filter(Object.id == object_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="Объект не найден")

    access = _get_object_access(db=db, user_id=user.id, object_id=object_id)
    if user.role != UserRole.ADMIN and not access:
        raise HTTPException(status_code=403, detail="Доступ запрещён")

    query = db.query(Document).filter(
        Document.object_id == object_id,
        Document.deleted_at.is_(None),
    )

    allowed_categories = _get_allowed_categories_for_user(
        user=user,
        access=access,
    )
    category_enum = _validate_requested_category(
        category=category,
        allowed_categories=allowed_categories,
    )
    query = _apply_documents_category_filter(
        query=query,
        category_enum=category_enum,
        allowed_categories=allowed_categories,
    )

    documents = query.order_by(Document.created_at.desc()).all()
    categories_stats = _build_categories_stats(
        db=db,
        object_id=object_id,
        allowed_categories=allowed_categories,
    )

    categories_dict = {cat.value: count for cat, count in categories_stats}

    logger.info("event=documents_list_viewed")

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
            **sidebar_context,
        },
    )


# ===================================
# Обновление файла документа (версионирование)
# ===================================
@router.post("/{document_id}/update")
async def update_document_file(
    document_id: int,
    request: Request,
    user: User = Depends(get_current_user_from_cookie),
    db: Session = Depends(get_db),
):
    """Обновить содержимое документа (новая версия)"""
    document = (
        db.query(Document)
        .filter(
            Document.id == document_id,
            Document.is_active.is_(True),
            Document.deleted_at.is_(None),
        )
        .first()
    )

    if not document:
        return JSONResponse(
            status_code=404,
            content={"detail": DOCUMENT_NOT_FOUND},
        )

    # Проверяем права
    if not DocumentService.can_update_document(user, document, db):
        return JSONResponse(
            status_code=403, content={"detail": "Нет прав для обновления"}
        )

    try:
        form = await request.form()
        file = form.get("file")

        if not file or not file.filename:
            return JSONResponse(
                status_code=400,
                content={"detail": "Файл не выбран"},
            )

        # Валидация расширения
        if not validate_file_extension(
            file.filename,
            ALLOWED_DOCUMENT_EXTENSIONS,
        ):
            return JSONResponse(
                status_code=400, content={"detail": "Недопустимый тип файла"}
            )

        # Валидация размера
        file_contents = await file.read()
        actual_size = len(file_contents)
        if actual_size > settings.MAX_FILE_SIZE:
            return JSONResponse(
                status_code=400, content={"detail": "Файл слишком большой"}
            )

        await file.seek(0)

        # Удаляем старый файл
        old_file_path = Path(settings.FILES_PATH) / document.file_path
        if old_file_path.exists():
            try:
                old_file_path.unlink()
            except OSError as exc:
                logger.warning(
                    "Не удалось удалить старый файл %s: %s",
                    old_file_path,
                    exc,
                )

        # Сохраняем новый файл
        new_file_path = await DocumentService.save_file(
            file,
            document.object_id,
        )

        # Обновляем запись документа
        original_filename = file.filename if file.filename else document.file_name
        document.file_path = new_file_path
        document.file_name = original_filename
        document.file_size = actual_size
        document.file_type = file.content_type
        document.version = (document.version or 1) + 1
        document.updated_by = user.id
        document.updated_at = datetime.now(timezone.utc)

        db.commit()

        logger.info(
            {
                "event": "document_file_updated",
                "document_id": document_id,
                "version": document.version,
                "user_id": user.id,
            }
        )

        return JSONResponse({"status": "ok", "version": document.version})

    except (OSError, SQLAlchemyError, ValueError, TypeError) as exc:
        logger.error("Ошибка обновления файла документа: %s", exc)
        return JSONResponse(status_code=500, content={"detail": str(exc)})


# ===================================
# Массовое удаление документов
# ===================================
@router.post("/batch-delete")
async def batch_delete_documents(
    request: Request,
    user: User = Depends(get_current_user_from_cookie),
    db: Session = Depends(get_db),
):
    """Удалить несколько документов одновременно"""
    try:
        data = await request.json()
    except (ValueError, TypeError):
        return JSONResponse(
            status_code=400,
            content={"detail": "Некорректный JSON"},
        )

    document_ids = data.get("document_ids", [])

    if not document_ids:
        return JSONResponse(
            status_code=400,
            content={"detail": "Не указаны документы"},
        )

    try:
        deleted_count = 0

        for doc_id in document_ids:
            doc = (
                db.query(Document)
                .filter(
                    Document.id == doc_id,
                    Document.is_active.is_(True),
                    Document.deleted_at.is_(None),
                )
                .first()
            )

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
                except OSError as exc:
                    logger.warning(
                        "Не удалось удалить файл %s: %s",
                        file_path,
                        exc,
                    )

            # Мягкое удаление в БД
            doc.deleted_at = datetime.now(timezone.utc)
            doc.is_active = False
            deleted_count += 1

        db.commit()

        logger.info(
            {
                "event": "documents_batch_deleted",
                "count": deleted_count,
                "user_id": user.id,
            }
        )

        return JSONResponse({"status": "ok", "deleted": deleted_count})

    except (OSError, SQLAlchemyError, ValueError, TypeError) as exc:
        logger.error("Ошибка массового удаления: %s", exc)
        return JSONResponse(status_code=500, content={"detail": str(exc)})


# ===================================
# Скачивание нескольких документов как ZIP
# ===================================
@router.post("/batch-download")
async def batch_download_documents(
    request: Request,
    user: User = Depends(get_current_user_from_cookie),
    db: Session = Depends(get_db),
):
    """Скачать несколько документов как ZIP архив"""
    try:
        data = await request.json()
    except (ValueError, TypeError):
        return JSONResponse(
            status_code=400,
            content={"detail": "Некорректный JSON"},
        )

    document_ids = data.get("document_ids", [])

    if not document_ids:
        return JSONResponse(
            status_code=400,
            content={"detail": "Не указаны документы"},
        )

    try:
        zip_buffer = io.BytesIO()

        added_count = 0

        with zipfile.ZipFile(
            zip_buffer,
            "w",
            zipfile.ZIP_DEFLATED,
        ) as zip_file:
            for doc_id in document_ids:
                doc = (
                    db.query(Document)
                    .filter(
                        Document.id == doc_id,
                        Document.is_active.is_(True),
                        Document.deleted_at.is_(None),
                    )
                    .first()
                )

                if not doc or not doc.can_access(user, db):
                    logger.warning(
                        {
                            "event": "batch_download_document_skipped",
                            "doc_id": doc_id,
                            "reason": "not found or no access",
                            "user_id": user.id,
                        }
                    )
                    continue

                try:
                    file_path = _resolve_document_file_path(doc.file_path)
                except ValueError:
                    logger.warning(
                        {
                            "event": "batch_download_path_traversal",
                            "doc_id": doc_id,
                            "user_id": user.id,
                        }
                    )
                    continue

                if not file_path.exists():
                    logger.warning(
                        {
                            "event": "batch_download_file_missing",
                            "doc_id": doc_id,
                            "file_path": str(file_path),
                            "user_id": user.id,
                        }
                    )
                    continue

                # Префикс doc_id предотвращает коллизии имён файлов
                archive_name = f"{doc.id}_{doc.file_name}"
                file_bytes = await asyncio.to_thread(file_path.read_bytes)
                zip_file.writestr(archive_name, file_bytes)
                added_count += 1

        if added_count == 0:
            return JSONResponse(
                status_code=404,
                content={
                    "detail": (
                        "Не удалось добавить файлы в архив. "
                        "Проверьте доступ и наличие файлов на диске."
                    )
                },
            )

        zip_buffer.seek(0)

        logger.info(
            {
                "event": "documents_batch_downloaded",
                "requested": len(document_ids),
                "added": added_count,
                "user_id": user.id,
            }
        )

        return StreamingResponse(
            iter([zip_buffer.getvalue()]),
            media_type="application/zip",
            headers={"Content-Disposition": "attachment; filename=documents.zip"},
        )

    except (OSError, SQLAlchemyError, ValueError, TypeError) as exc:
        logger.error("Ошибка скачивания: %s", exc)
        return JSONResponse(status_code=500, content={"detail": str(exc)})
