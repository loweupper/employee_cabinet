import asyncio
import logging
import re
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, List, Optional

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    UploadFile,
    status,
)
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from pydantic import ValidationError
from sqlalchemy.orm import Session

from core.database import get_db
from core.constants import UserRole  # ✅ импорт из constants
from core.template_helpers import get_sidebar_context
from modules.auth.dependencies import get_current_user_from_cookie
from modules.auth.models import User
from modules.access.service import AccessService
from modules.access.models_sql import PermissionType
from modules.documents.models import DocumentCategory, DocumentSubcategory
from modules.objects.models import Object, ObjectAccess, ObjectAccessRole
from modules.objects.schemas import (
    ObjectAccessCreate,
    ObjectAccessRoleEnum,
    ObjectAccessUpdate,
    ObjectCreate,
    ObjectUpdate,
)
from modules.objects.service import ObjectService
from modules.permissions.models import UserPermission, RolePermission, Permission


logger = logging.getLogger("app")

router = APIRouter(tags=["objects"])

templates = Jinja2Templates(directory="templates")

OBJECT_NOT_FOUND_REDIRECT_URL = "/objects?error=Объект не найден"


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_file_extension(filename: Optional[str]) -> str:
    suffix = Path(filename or "").suffix.lower()
    if re.fullmatch(r"\.[a-z0-9]{1,10}", suffix):
        return suffix
    return ""


async def _save_icon_file(icon: UploadFile, object_id: int) -> str:
    icons_dir = Path("static/objects")
    icons_dir.mkdir(parents=True, exist_ok=True)

    file_ext = _safe_file_extension(icon.filename)
    filename = f"{object_id}_{uuid.uuid4().hex[:8]}{file_ext}"
    file_path = icons_dir / filename

    contents = await icon.read()
    await asyncio.to_thread(file_path.write_bytes, contents)
    return f"/static/objects/{filename}"


def _get_subcategories(db: Session, object_id: int, category: DocumentCategory):
    return (
        db.query(DocumentSubcategory)
        .filter(
            DocumentSubcategory.object_id == object_id,
            DocumentSubcategory.category == category,
            DocumentSubcategory.deleted_at.is_(None),
        )
        .all()
    )


def _subcategories_to_dict(subcategories):
    return [
        {
            "id": item.id,
            "name": item.name,
            "description": item.description,
            "category": item.category.value,
        }
        for item in subcategories
    ]


def _build_documents_by_category(documents):
    documents_by_category = {}
    for category in DocumentCategory:
        category_docs = [doc for doc in documents if doc.category == category]
        if not category_docs:
            continue

        docs_by_subcat = defaultdict(list)
        for doc in category_docs:
            subcat_id = doc.subcategory_id if doc.subcategory_id else 0
            docs_by_subcat[subcat_id].append(doc)

        sorted_subcats = sorted(
            docs_by_subcat.items(),
            key=lambda item: (item[0] != 0, item[0]),
        )
        documents_by_category[category] = {
            "docs": category_docs,
            "by_subcat": sorted_subcats,
        }

    return documents_by_category


def _append_user_to_section(stats, section: str, user_obj: User):
    users = stats.setdefault(section, [])
    if all(existing.id != user_obj.id for existing in users):
        users.append(user_obj)


def _sections_for_access(access, user_obj: User):
    role_to_department = {
        UserRole.ENGINEER: "technical",
        UserRole.LAWYER: "legal",
        UserRole.ACCOUNTANT: "accounting",
        UserRole.HR: "hr",
    }
    sections = list(access.sections_access or [])
    role_section = role_to_department.get(user_obj.role)
    if role_section:
        sections.append(role_section)
    return sections


def _build_department_stats(db: Session, accesses):
    department_stats = {}
    for access in accesses:
        user_obj = db.query(User).filter(User.id == access.user_id).first()
        if not user_obj:
            continue

        for section in _sections_for_access(access, user_obj):
            _append_user_to_section(department_stats, section, user_obj)

    return department_stats


async def _parse_subcategory_payload(request: Request):
    content_type = request.headers.get("Content-Type", "")
    is_ajax = "application/json" in content_type

    if is_ajax:
        body = await request.json()
        return {
            "is_ajax": True,
            "name": (body.get("name") or "").strip(),
            "description": body.get("description") or None,
            "category": (body.get("category") or "").strip(),
        }

    form_data = await request.form()
    return {
        "is_ajax": False,
        "name": (form_data.get("name") or "").strip(),
        "description": form_data.get("description") or None,
        "category": (form_data.get("category") or "").strip(),
    }


def _subcategory_error_response(is_ajax: bool, object_id: int, detail: str, code: int):
    if is_ajax:
        return JSONResponse(status_code=code, content={"detail": detail})

    return RedirectResponse(
        url=f"/objects/{object_id}?error={detail}",
        status_code=303,
    )


def user_has_permission(user: User, permission_key: str, db: Session) -> bool:
    """
    Проверить имеет ли пользователь разрешение

    Args:
        user: объект пользователя
        permission_key: ключ разрешения (can_create_objects, etc)
        db: сессия БД

    Returns:
        True если пользователь имеет разрешение, иначе False
    """
    # Проверяем явное разрешение пользователю
    user_perm = (
        db.query(UserPermission)
        .join(Permission)
        .filter(UserPermission.user_id == user.id, Permission.key == permission_key)
        .first()
    )

    if user_perm:
        return True

    # Проверяем разрешение через роль
    role_perm = (
        db.query(RolePermission)
        .join(Permission)
        .filter(RolePermission.role_name == user.role, Permission.key == permission_key)
        .first()
    )

    return bool(role_perm)


# ===================================
# Список объектов
# ===================================
@router.get("", response_class=HTMLResponse)
async def objects_list(
    request: Request,
    user: User = Depends(get_current_user_from_cookie),
    db: Session = Depends(get_db),
    page: Annotated[int, Query(ge=1)] = 1,
    search: Annotated[Optional[str], Query()] = None,
    department: Annotated[Optional[str], Query()] = None,
    status: Annotated[str, Query()] = "active",
):
    """
    Страница списка объектов
    """
    page_size = 12
    skip = (page - 1) * page_size

    objects, total = ObjectService.list_objects(
        user=user,
        db=db,
        skip=skip,
        limit=page_size,
        search=search,
        department=department,
        status=status,
    )

    pages = (total + page_size - 1) // page_size

    logger.info("event=objects_list_view")

    sidebar_context = get_sidebar_context(user, db)
    return templates.TemplateResponse(
        "web/objects/list.html",
        {
            "request": request,
            "user": user,
            "current_user": user,
            "objects": objects,
            "total": total,
            "page": page,
            "pages": pages,
            "search": search,
            "department": department,
            "status": status,
            **sidebar_context,
        },
    )


# ===================================
# Форма создания объекта
# ===================================
@router.get("/create", response_class=HTMLResponse)
async def create_object_page(
    request: Request,
    user: User = Depends(get_current_user_from_cookie),
    db: Session = Depends(get_db),
):
    """
    Страница создания объекта
    """
    if not user_has_permission(user, "can_create_objects", db):
        return RedirectResponse(
            url="/objects?error=У вас нет разрешения на создание объектов",
            status_code=303,
        )

    return templates.TemplateResponse(
        "web/objects/create.html",
        {"request": request, "user": user, "current_user": user},
    )


# ===================================
# Создание объекта
# ===================================
@router.post("/create", status_code=status.HTTP_303_SEE_OTHER)
async def create_object(
    request: Request,
    title: Annotated[str, Form(...)],
    address: Annotated[Optional[str], Form()] = None,
    description: Annotated[Optional[str], Form()] = None,
    department: Annotated[Optional[str], Form()] = None,
    location: Annotated[Optional[str], Form()] = None,
    icon: Annotated[Optional[UploadFile], File()] = None,
    user: User = Depends(get_current_user_from_cookie),
    db: Session = Depends(get_db),
):
    """
    Создание нового объекта
    """
    if not user_has_permission(user, "can_create_objects", db):
        return RedirectResponse(
            url="/objects?error=У вас нет разрешения на создание объектов",
            status_code=303,
        )

    try:
        # Валидация
        data = ObjectCreate(
            title=title,
            address=address,
            description=description,
            department=department,
            location=location,
        )

        # Создаем объект
        obj = ObjectService.create_object(data, user, db)

        # Загружаем иконку (если есть)
        if icon and icon.filename:
            obj.icon_url = await _save_icon_file(icon, obj.id)
            db.commit()

        return RedirectResponse(
            url=f"/objects/{obj.id}?success=Объект успешно создан", status_code=303
        )

    except ValidationError as e:
        error_msg = e.errors()[0]["msg"]
        return RedirectResponse(
            url=f"/objects/create?error={error_msg}", status_code=303
        )


# ===================================
# Форма редактирования объекта
# ===================================
@router.get("/{object_id}/edit", response_class=HTMLResponse)
async def edit_object_page(
    object_id: int,
    request: Request,
    user: User = Depends(get_current_user_from_cookie),
    db: Session = Depends(get_db),
):
    """
    Страница редактирования объекта
    """
    try:
        obj = ObjectService.get_object(object_id, user, db)

        # Проверяем права (только владелец или админ)
        if obj.created_by != user.id and user.role != UserRole.ADMIN:  # ✅ исправлено
            return RedirectResponse(
                url=f"/objects/{object_id}?error=Недостаточно прав для редактирования",
                status_code=303,
            )

        # Проверяем разрешение
        if not user_has_permission(user, "can_edit_objects", db):
            return RedirectResponse(
                url=f"/objects/{object_id}?error=У вас нет разрешения на редактирование объектов",
                status_code=303,
            )

        return templates.TemplateResponse(
            "web/objects/edit.html",
            {"request": request, "user": user, "current_user": user, "object": obj},
        )

    except HTTPException as e:
        return RedirectResponse(url=f"/objects?error={e.detail}", status_code=303)


# ===================================
# Обновление объекта
# ===================================
@router.post("/{object_id}/edit")
async def update_object(
    object_id: int,
    request: Request,
    title: Annotated[str, Form(...)],
    address: Annotated[Optional[str], Form()] = None,
    description: Annotated[Optional[str], Form()] = None,
    department: Annotated[Optional[str], Form()] = None,
    location: Annotated[Optional[str], Form()] = None,
    icon: Annotated[Optional[UploadFile], File()] = None,
    user: User = Depends(get_current_user_from_cookie),
    db: Session = Depends(get_db),
):
    """
    Обновление объекта
    """
    if not user_has_permission(user, "can_edit_objects", db):
        return RedirectResponse(
            url=f"/objects/{object_id}?error=У вас нет разрешения на редактирование объектов",
            status_code=303,
        )

    try:
        # Валидация
        data = ObjectUpdate(
            title=title,
            address=address,
            description=description,
            department=department,
            location=location,
        )

        # Обновляем объект
        obj = ObjectService.update_object(object_id, data, user, db)

        # Загружаем новую иконку (если есть)
        if icon and icon.filename:
            obj.icon_url = await _save_icon_file(icon, obj.id)
            db.commit()

        return RedirectResponse(
            url=f"/objects/{object_id}?success=Объект успешно обновлен", status_code=303
        )

    except ValidationError as e:
        error_msg = e.errors()[0]["msg"]
        return RedirectResponse(
            url=f"/objects/{object_id}/edit?error={error_msg}", status_code=303
        )
    except HTTPException as e:
        return RedirectResponse(
            url=f"/objects/{object_id}?error={e.detail}", status_code=303
        )


# ===================================
# Карточка объекта
# ===================================
@router.get(
    "/{object_id}",
    responses={500: {"description": "Ошибка загрузки объекта"}},
)
async def object_detail(
    object_id: int,
    request: Request,
    success: Optional[str] = None,
    error: Optional[str] = None,
    user: User = Depends(get_current_user_from_cookie),
    db: Session = Depends(get_db),
):
    """Детальная страница объекта"""
    try:
        # Получаем объект
        obj = ObjectService.get_object(object_id, user, db)

        # Получаем доступы
        accesses = (
            db.query(ObjectAccess).filter(ObjectAccess.object_id == object_id).all()
        )

        # Получаем документы
        from modules.documents.service import DocumentService

        documents = DocumentService.list_documents(object_id, user, db)
        total_documents = len(documents)

        # Получаем доступные для пользователя категории
        accessible_categories = DocumentService.get_accessible_categories(user, obj, db)
        documents_by_category = _build_documents_by_category(documents)
        subcategories_general_data = _subcategories_to_dict(
            _get_subcategories(db, object_id, DocumentCategory.GENERAL)
        )
        subcategories_technical_data = _subcategories_to_dict(
            _get_subcategories(db, object_id, DocumentCategory.TECHNICAL)
        )
        subcategories_accounting_data = _subcategories_to_dict(
            _get_subcategories(db, object_id, DocumentCategory.ACCOUNTING)
        )
        subcategories_safety_data = _subcategories_to_dict(
            _get_subcategories(db, object_id, DocumentCategory.SAFETY)
        )
        subcategories_legal_data = _subcategories_to_dict(
            _get_subcategories(db, object_id, DocumentCategory.LEGAL)
        )
        subcategories_hr_data = _subcategories_to_dict(
            _get_subcategories(db, object_id, DocumentCategory.HR)
        )

        # Получаем всех пользователей для автокомплита
        all_users = db.query(User).filter(User.is_active.is_(True)).all()
        department_stats = _build_department_stats(db, accesses)

        # Считаем количество
        department_counts = {
            dept: len(users) for dept, users in department_stats.items()
        }

        logger.info(
            {
                "event": "object_detail_viewed",
                "user_id": user.id,
                "object_id": object_id,
                "department_stats": department_counts,
            }
        )

        sidebar_context = get_sidebar_context(user, db)

        return templates.TemplateResponse(
            "web/objects/detail.html",
            {
                "request": request,
                "user": user,
                "current_user": user,
                "object": obj,
                "accesses": accesses,
                "total_users": len(accesses),
                "department_stats": department_stats,
                "department_counts": department_counts,
                "documents": documents,
                "total_documents": total_documents,
                "documents_by_category": documents_by_category,
                "subcategories_general": subcategories_general_data,
                "subcategories_technical": subcategories_technical_data,
                "subcategories_accounting": subcategories_accounting_data,
                "subcategories_safety": subcategories_safety_data,
                "subcategories_legal": subcategories_legal_data,
                "subcategories_hr": subcategories_hr_data,
                "all_users": all_users,
                "csrf_token": request.cookies.get("csrftoken", ""),
                "success": success,
                "error": error,
                "accessible_categories": accessible_categories,
                **sidebar_context,
            },
        )

    except HTTPException as e:
        raise e
    except Exception as e:
        logger.error(
            "❌ Ошибка при загрузке объекта %s (type=%s)",
            object_id,
            type(e).__name__,
        )
        import traceback

        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail="Ошибка загрузки объекта")


# ===================================
# Удаление объекта
# ===================================
@router.post("/{object_id}/delete")
async def delete_object(
    object_id: int,
    request: Request,
    user: User = Depends(get_current_user_from_cookie),
    db: Session = Depends(get_db),
):
    """
    Удаление объекта (soft delete)
    """
    if not user_has_permission(user, "can_delete_objects", db):
        return RedirectResponse(
            url=f"/objects/{object_id}?error=У вас нет разрешения на удаление объектов",
            status_code=303,
        )

    try:
        ObjectService.delete_object(object_id, user, db)

        return RedirectResponse(
            url="/objects?success=Объект успешно удален", status_code=303
        )

    except HTTPException as e:
        return RedirectResponse(
            url=f"/objects/{object_id}?error={e.detail}", status_code=303
        )


# ===================================
# Админ-панель: Все объекты
# ===================================
@router.get("/admin/all", response_class=HTMLResponse)
async def admin_objects_list(
    request: Request,
    user: User = Depends(get_current_user_from_cookie),
    db: Session = Depends(get_db),
    page: Annotated[int, Query(ge=1)] = 1,
    search: Annotated[Optional[str], Query()] = None,
    include_deleted: Annotated[bool, Query()] = False,
):
    """
    Админ-панель: список всех объектов
    """
    # Проверка прав
    if user.role != UserRole.ADMIN:  # ✅ исправлено
        return RedirectResponse(url="/objects?error=Доступ запрещен", status_code=303)

    page_size = 20
    skip = (page - 1) * page_size

    objects, total = ObjectService.list_all_objects_admin(
        db=db,
        skip=skip,
        limit=page_size,
        search=search,
        include_deleted=include_deleted,
    )

    pages = (total + page_size - 1) // page_size

    logger.info(
        {"event": "admin_objects_list_view", "user_id": user.id, "total": total}
    )

    sidebar_context = get_sidebar_context(user, db)

    return templates.TemplateResponse(
        "web/admin/objects.html",
        {
            "request": request,
            "user": user,
            "objects": objects,
            "total": total,
            "page": page,
            "pages": pages,
            "search": search,
            "include_deleted": include_deleted,
            **sidebar_context,
        },
    )


# ===================================
# Восстановление объекта
# ===================================
@router.post("/{object_id}/restore")
async def restore_object(
    object_id: int,
    request: Request,
    user: User = Depends(get_current_user_from_cookie),
    db: Session = Depends(get_db),
):
    """
    Восстановление удаленного объекта (только админ)
    """
    try:
        ObjectService.restore_object(object_id, user, db)

        return RedirectResponse(
            url="/objects/admin/all?success=Объект восстановлен", status_code=303
        )

    except HTTPException as e:
        return RedirectResponse(
            url=f"/objects/admin/all?error={e.detail}", status_code=303
        )


# ===================================
# Изменение статуса объекта
# ===================================
@router.post("/{object_id}/activate")
async def activate_object(
    object_id: int,
    user: User = Depends(get_current_user_from_cookie),
    db: Session = Depends(get_db),
):
    """Активировать объект"""
    obj = db.query(Object).filter(Object.id == object_id).first()

    if not obj:
        return RedirectResponse(url=OBJECT_NOT_FOUND_REDIRECT_URL, status_code=303)

    if obj.created_by != user.id and user.role != UserRole.ADMIN:  # ✅ исправлено
        return RedirectResponse(
            url=f"/objects/{object_id}?error=Недостаточно прав", status_code=303
        )

    obj.is_active = True
    db.commit()

    logger.info(
        {"event": "object_activated", "object_id": object_id, "user_id": user.id}
    )

    return RedirectResponse(
        url=f"/objects/{object_id}?success=Объект активирован", status_code=303
    )


# ===================================
# Деактивация объекта
# ===================================
@router.post("/{object_id}/deactivate")
async def deactivate_object(
    object_id: int,
    user: User = Depends(get_current_user_from_cookie),
    db: Session = Depends(get_db),
):
    """Деактивировать объект"""
    obj = db.query(Object).filter(Object.id == object_id).first()

    if not obj:
        return RedirectResponse(url=OBJECT_NOT_FOUND_REDIRECT_URL, status_code=303)

    if obj.created_by != user.id and user.role != UserRole.ADMIN:  # ✅ исправлено
        return RedirectResponse(
            url=f"/objects/{object_id}?error=Недостаточно прав", status_code=303
        )

    obj.is_active = False
    db.commit()

    logger.info(
        {"event": "object_deactivated", "object_id": object_id, "user_id": user.id}
    )

    return RedirectResponse(
        url=f"/objects/{object_id}?success=Объект деактивирован", status_code=303
    )


# ===================================
# Архивация объекта
# ===================================
@router.post("/{object_id}/archive")
async def archive_object(
    object_id: int,
    user: User = Depends(get_current_user_from_cookie),
    db: Session = Depends(get_db),
):
    """Отправить объект в архив"""
    obj = db.query(Object).filter(Object.id == object_id).first()

    if not obj:
        return RedirectResponse(url=OBJECT_NOT_FOUND_REDIRECT_URL, status_code=303)

    if obj.created_by != user.id and user.role != UserRole.ADMIN:  # ✅ исправлено
        return RedirectResponse(
            url=f"/objects/{object_id}?error=Недостаточно прав", status_code=303
        )

    obj.is_archived = True
    obj.is_active = False
    db.commit()

    logger.info(
        {"event": "object_archived", "object_id": object_id, "user_id": user.id}
    )

    return RedirectResponse(
        url=f"/objects/{object_id}?success=Объект отправлен в архив", status_code=303
    )


# ===================================
# Разархивация объекта
# ===================================
@router.post("/{object_id}/unarchive")
async def unarchive_object(
    object_id: int,
    user: User = Depends(get_current_user_from_cookie),
    db: Session = Depends(get_db),
):
    """Вернуть объект из архива"""
    obj = db.query(Object).filter(Object.id == object_id).first()

    if not obj:
        return RedirectResponse(url=OBJECT_NOT_FOUND_REDIRECT_URL, status_code=303)

    if obj.created_by != user.id and user.role != UserRole.ADMIN:  # ✅ исправлено
        return RedirectResponse(
            url=f"/objects/{object_id}?error=Недостаточно прав", status_code=303
        )

    obj.is_archived = False
    obj.is_active = True
    db.commit()

    logger.info(
        {"event": "object_unarchived", "object_id": object_id, "user_id": user.id}
    )

    return RedirectResponse(
        url=f"/objects/{object_id}?success=Объект возвращен из архива", status_code=303
    )


# ===================================
# Управление доступом к объекту
# ===================================
@router.post("/{object_id}/access/grant")
async def grant_object_access(
    object_id: int,
    user_email: Annotated[str, Form(...)],
    role: Annotated[str, Form(...)],
    sections: Annotated[Optional[List[str]], Form()] = None,
    current_user: User = Depends(get_current_user_from_cookie),
    db: Session = Depends(get_db),
):
    """Предоставить доступ пользователю к объекту"""
    try:
        sections = sections or []
        # ✅ Проверка прав ДО всех операций
        if not ObjectService.can_manage_access(current_user, object_id, db):
            return RedirectResponse(
                url=f"/objects/{object_id}?error=Недостаточно прав для управления доступом",
                status_code=303,
            )

        # Находим пользователя по email
        target_user = db.query(User).filter(User.email == user_email).first()

        if not target_user:
            return RedirectResponse(
                url=f"/objects/{object_id}?error=Пользователь не найден",
                status_code=303,
            )

        # Проверяем, нет ли уже доступа
        existing = (
            db.query(ObjectAccess)
            .filter(
                ObjectAccess.object_id == object_id,
                ObjectAccess.user_id == target_user.id,
            )
            .first()
        )

        if existing:
            return RedirectResponse(
                url=f"/objects/{object_id}?error=У пользователя уже есть доступ к этому объекту",
                status_code=303,
            )

        # Автоматически добавляем отдел на основе роли
        role_to_department = {
            UserRole.ENGINEER: "technical",
            UserRole.LAWYER: "legal",
            UserRole.ACCOUNTANT: "accounting",
            UserRole.HR: "hr",
        }

        # Если роль соответствует отделу, автоматически добавляем
        if target_user.role in role_to_department:
            auto_dept = role_to_department[target_user.role]
            if auto_dept not in sections:
                sections.append(auto_dept)

        # Всегда добавляем general
        if "general" not in sections:
            sections.append("general")

        # Создаём доступ
        access_data = ObjectAccessCreate(
            user_id=target_user.id,
            role=ObjectAccessRoleEnum(role),
            sections_access=sections,
        )

        ObjectService.grant_access(object_id, access_data, current_user, db)

        # ✅ Логируем с новым форматом
        logger.info("event=access_granted")

        return RedirectResponse(
            url=f"/objects/{object_id}?success=Доступ предоставлен",
            status_code=303,
        )

    except HTTPException as e:
        return RedirectResponse(
            url=f"/objects/{object_id}?error={e.detail}", status_code=303
        )


def sync_with_acl(object_id: int, user_id: int, role: ObjectAccessRole, db: Session):
    """
    Синхронизировать ObjectAccess с глобальной системой ACL
    """
    try:
        # Определяем права в ACL на основе роли
        if role in [ObjectAccessRole.OWNER, ObjectAccessRole.ADMIN]:
            permissions = [
                PermissionType.ADMIN,
                PermissionType.READ,
                PermissionType.WRITE,
            ]
        elif role == ObjectAccessRole.EDITOR:
            permissions = [PermissionType.READ, PermissionType.WRITE]
        else:  # VIEWER
            permissions = [PermissionType.READ]

        for perm in permissions:
            AccessService.grant_access(
                resource_type="object",
                resource_id=object_id,
                permission=perm,
                db=db,
                user_id=user_id,
            )
    except ImportError:
        logger.warning("ACL service not available, skipping sync")


# ===================================
# Отзыв доступа пользователя к объекту
# ===================================
@router.post("/{object_id}/access/{user_id}/revoke")
async def revoke_object_access(
    object_id: int,
    user_id: int,
    current_user: User = Depends(get_current_user_from_cookie),
    db: Session = Depends(get_db),
):
    """
    Отозвать доступ пользователя к объекту
    """
    try:
        ObjectService.revoke_access(object_id, user_id, current_user, db)

        return RedirectResponse(
            url=f"/objects/{object_id}?success=Доступ отозван", status_code=303
        )

    except HTTPException as e:
        return RedirectResponse(
            url=f"/objects/{object_id}?error={e.detail}", status_code=303
        )


# ===================================
# Предоставить доступ всему отделу
# ===================================
@router.post("/{object_id}/access/grant-department")
async def grant_department_access(
    object_id: int,
    department: Annotated[str, Form(...)],
    role: Annotated[str, Form(...)],
    current_user: User = Depends(get_current_user_from_cookie),
    db: Session = Depends(get_db),
):
    """
    Предоставить доступ всему отделу
    """
    try:
        # Находим всех пользователей отдела
        users_in_department = (
            db.query(User)
            .filter(
                User.department == department,
                User.is_active.is_(True),
            )
            .all()
        )

        if not users_in_department:
            return RedirectResponse(
                url=f"/objects/{object_id}?error=В отделе {department} нет пользователей",
                status_code=303,
            )

        granted_count = 0

        role_to_section = {
            UserRole.ENGINEER: "technical",
            UserRole.LAWYER: "legal",
            UserRole.ACCOUNTANT: "accounting",
            UserRole.HR: "hr",
        }

        for target_user in users_in_department:
            # Проверяем, нет ли уже доступа
            existing = (
                db.query(ObjectAccess)
                .filter(
                    ObjectAccess.object_id == object_id,
                    ObjectAccess.user_id == target_user.id,
                )
                .first()
            )

            if not existing:
                # Формируем sections на основе роли пользователя
                sections = ["general"]
                if target_user.role in role_to_section:
                    sections.append(role_to_section[target_user.role])

                access_data = ObjectAccessCreate(
                    user_id=target_user.id,
                    role=ObjectAccessRoleEnum(role),
                    sections_access=sections,
                )

                ObjectService.grant_access(object_id, access_data, current_user, db)
                granted_count += 1

        return RedirectResponse(
            url=f"/objects/{object_id}?success=Доступ предоставлен {granted_count} сотрудникам отдела {department}",
            status_code=303,
        )

    except HTTPException as e:
        return RedirectResponse(
            url=f"/objects/{object_id}?error={e.detail}", status_code=303
        )


# ===================================
# Обновление доступа пользователя к объекту
# ===================================
@router.post("/{object_id}/access/{user_id}/update")
async def update_object_access(
    object_id: int,
    user_id: int,
    role: Annotated[str, Form(...)],
    sections: Annotated[Optional[List[str]], Form()] = None,
    current_user: User = Depends(get_current_user_from_cookie),
    db: Session = Depends(get_db),
):
    """
    Обновить доступ пользователя к объекту
    """
    try:
        sections = sections or []

        # Всегда добавляем "general"
        if "general" not in sections:
            sections.append("general")

        update_data = ObjectAccessUpdate(
            role=ObjectAccessRoleEnum(role), sections_access=sections
        )

        ObjectService.update_access(object_id, user_id, update_data, current_user, db)

        return RedirectResponse(
            url=f"/objects/{object_id}?success=Доступ успешно обновлён", status_code=303
        )

    except HTTPException as e:
        return RedirectResponse(
            url=f"/objects/{object_id}?error={e.detail}", status_code=303
        )


# Получить подкатегории для объекта
@router.get("/{object_id}/subcategories")
async def get_object_subcategories(
    object_id: int,
    category: Optional[str] = None,
    current_user: User = Depends(get_current_user_from_cookie),
    db: Session = Depends(get_db),
):
    """
    Получить подкатегории для объекта
    """
    # Проверяем доступ к объекту
    ObjectService.get_object(object_id, current_user, db)

    # Получаем подкатегории
    query = db.query(DocumentSubcategory).filter(
        DocumentSubcategory.object_id == object_id,
        DocumentSubcategory.deleted_at.is_(None),
    )

    if category:
        query = query.filter(DocumentSubcategory.category == category)

    subcategories = query.order_by(
        DocumentSubcategory.order, DocumentSubcategory.created_at
    ).all()

    return [
        {
            "id": s.id,
            "name": s.name,
            "description": s.description,
            "category": s.category.value,
        }
        for s in subcategories
    ]


# Создать подкатегорию
@router.post("/{object_id}/subcategories/create")
async def create_subcategory(
    object_id: int,
    request: Request,
    current_user: User = Depends(get_current_user_from_cookie),
    db: Session = Depends(get_db),
):
    """
    Создать подкатегорию для объекта.
    Поддерживает как обычные form-запросы, так и AJAX (application/json).
    """
    try:
        payload = await _parse_subcategory_payload(request)
    except Exception:
        return JSONResponse(status_code=400, content={"detail": "Некорректный JSON"})

    is_ajax = payload["is_ajax"]
    name = payload["name"]
    description = payload["description"]
    category = payload["category"]

    # Проверяем доступ
    obj = db.query(Object).filter(Object.id == object_id).first()

    if not obj:
        return _subcategory_error_response(is_ajax, object_id, "Объект не найден", 404)

    if (
        obj.created_by != current_user.id and current_user.role != UserRole.ADMIN
    ):  # ✅ исправлено
        return _subcategory_error_response(is_ajax, object_id, "Недостаточно прав", 403)

    if not name:
        return _subcategory_error_response(
            is_ajax,
            object_id,
            "Введите название подкатегории",
            400,
        )

    if not category:
        return _subcategory_error_response(is_ajax, object_id, "Укажите раздел", 400)

    # Создаём подкатегорию
    from modules.documents.models import DocumentCategory

    subcategory = DocumentSubcategory(
        name=name,
        description=description,
        category=DocumentCategory(category),
        object_id=object_id,
        created_by=current_user.id,
    )

    db.add(subcategory)
    db.commit()

    logger.info(
        {
            "event": "subcategory_created",
            "object_id": obj.id,
            "subcategory_id": subcategory.id,
            "actor_id": current_user.id,
            "timestamp": _utcnow_iso(),
        }
    )

    if is_ajax:
        return JSONResponse(
            {
                "id": subcategory.id,
                "name": subcategory.name,
                "category": subcategory.category.value,
            }
        )

    return RedirectResponse(
        url=f"/objects/{object_id}?success=Подкатегория '{name}' создана",
        status_code=303,
    )


#  Удалить подкатегорию
@router.post("/{object_id}/subcategories/{subcategory_id}/delete")
async def delete_subcategory(
    object_id: int,
    subcategory_id: int,
    current_user: User = Depends(get_current_user_from_cookie),
    db: Session = Depends(get_db),
):
    """
    Удалить подкатегорию (только создатель/админ/владелец объекта)
    """
    try:
        # Проверяем доступ к объекту
        obj = ObjectService.get_object(object_id, current_user, db)

        # Получаем подкатегорию
        subcategory = (
            db.query(DocumentSubcategory)
            .filter(
                DocumentSubcategory.id == subcategory_id,
                DocumentSubcategory.object_id == object_id,
            )
            .first()
        )

        if not subcategory:
            return RedirectResponse(
                url=f"/objects/{object_id}?error=Подкатегория не найдена",
                status_code=303,
            )

        # Проверяем права: создатель подкатегории ИЛИ админ ИЛИ владелец объекта
        if (
            subcategory.created_by != current_user.id
            and current_user.role != UserRole.ADMIN  # ✅ исправлено
            and obj.created_by != current_user.id
        ):
            return RedirectResponse(
                url=f"/objects/{object_id}?error=Недостаточно прав для удаления",
                status_code=303,
            )

        # Удаляем подкатегорию (мягкое удаление)
        subcategory.deleted_at = datetime.now(timezone.utc)
        db.commit()

        logger.info(
            {
                "event": "subcategory_deleted",
                "object_id": obj.id,
                "subcategory_id": subcategory.id,
                "actor_id": current_user.id,
                "timestamp": _utcnow_iso(),
            }
        )

        return RedirectResponse(
            url=f"/objects/{object_id}?success=Подкатегория удалена", status_code=303
        )

    except HTTPException as e:
        return RedirectResponse(
            url=f"/objects/{object_id}?error={e.detail}", status_code=303
        )


# Редактировать подкатегорию
@router.post("/{object_id}/subcategories/{subcategory_id}/update")
async def update_subcategory(
    object_id: int,
    subcategory_id: int,
    name: Annotated[str, Form(...)],
    description: Annotated[Optional[str], Form()] = None,
    current_user: User = Depends(get_current_user_from_cookie),
    db: Session = Depends(get_db),
):
    """
    Редактировать подкатегорию (только создатель/админ/владелец объекта)
    """
    try:
        # Проверяем доступ к объекту
        obj = ObjectService.get_object(object_id, current_user, db)

        # Получаем подкатегорию
        subcategory = (
            db.query(DocumentSubcategory)
            .filter(
                DocumentSubcategory.id == subcategory_id,
                DocumentSubcategory.object_id == object_id,
            )
            .first()
        )

        if not subcategory:
            return RedirectResponse(
                url=f"/objects/{object_id}?error=Подкатегория не найдена",
                status_code=303,
            )

        # Проверяем права
        if (
            subcategory.created_by != current_user.id
            and current_user.role != UserRole.ADMIN  # ✅ исправлено
            and obj.created_by != current_user.id
        ):
            return RedirectResponse(
                url=f"/objects/{object_id}?error=Недостаточно прав для редактирования",
                status_code=303,
            )

        # Обновляем подкатегорию
        subcategory.name = name
        subcategory.description = description
        db.commit()

        logger.info("event=subcategory_updated")

        return RedirectResponse(
            url=f"/objects/{object_id}?success=Подкатегория обновлена", status_code=303
        )

    except HTTPException as e:
        return RedirectResponse(
            url=f"/objects/{object_id}?error={e.detail}", status_code=303
        )


