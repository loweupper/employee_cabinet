from fastapi import APIRouter, Depends, Request, Form, UploadFile, File, HTTPException, Query, status
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session
from pydantic import ValidationError
import logging
import uuid
from pathlib import Path

from core.database import get_db
from core.constants import UserRole  # ✅ импорт из constants
from modules.auth.dependencies import get_current_user_from_cookie
from modules.auth.models import User
from modules.objects.schemas import *
from modules.objects.service import ObjectService
from modules.objects.models import Object, ObjectAccess, ObjectAccessRole
from typing import List, Optional
from modules.documents.models import DocumentCategory, DocumentSubcategory
from datetime import datetime
from modules.objects.schemas import ObjectAccessCreate, ObjectAccessRoleEnum
from core.template_helpers import get_sidebar_context
from modules.access.service import AccessService
from modules.access.models_sql import PermissionType


logger = logging.getLogger("app")

router = APIRouter(tags=["objects"])

from fastapi.templating import Jinja2Templates
templates = Jinja2Templates(directory="templates")


# ===================================
# Список объектов
# ===================================
@router.get("", response_class=HTMLResponse)
async def objects_list(
    request: Request,
    user: User = Depends(get_current_user_from_cookie),
    db: Session = Depends(get_db),
    page: int = Query(1, ge=1),
    search: str = Query(None),
    department: str = Query(None),
    status: str = Query("active")  
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
        status=status 
    )
    
    pages = (total + page_size - 1) // page_size
    
    logger.info({
        "event": "objects_list_view",
        "actor_id": user.id,
        "actor_email": user.email,
        "total_objects": total,
        "status_filter": status,
        "timestamp": datetime.utcnow().isoformat()
    })
    
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
            **sidebar_context
        }
    )


# ===================================
# Форма создания объекта
# ===================================
@router.get("/create", response_class=HTMLResponse)
async def create_object_page(
    request: Request,
    user: User = Depends(get_current_user_from_cookie)
):
    """
    Страница создания объекта
    """
    return templates.TemplateResponse(
        "web/objects/create.html",
        {
            "request": request,
            "user": user
        }
    )


# ===================================
# Создание объекта
# ===================================
@router.post("/create", status_code=status.HTTP_303_SEE_OTHER)
async def create_object(
    request: Request,
    title: str = Form(...),
    address: str = Form(None),
    description: str = Form(None),
    department: str = Form(None),
    location: str = Form(None),
    icon: UploadFile = File(None),
    user: User = Depends(get_current_user_from_cookie),
    db: Session = Depends(get_db)
):
    """
    Создание нового объекта
    """
    try:
        # Валидация
        data = ObjectCreate(
            title=title,
            address=address,
            description=description,
            department=department,
            location=location
        )
        
        # Создаем объект
        obj = ObjectService.create_object(data, user, db)
        
        # Загружаем иконку (если есть)
        if icon and icon.filename:
            icons_dir = Path("static/objects")
            icons_dir.mkdir(parents=True, exist_ok=True)
            
            file_ext = Path(icon.filename).suffix
            filename = f"{obj.id}_{uuid.uuid4().hex[:8]}{file_ext}"
            file_path = icons_dir / filename
            
            contents = await icon.read()
            with open(file_path, "wb") as f:
                f.write(contents)
            
            obj.icon_url = f"/static/objects/{filename}"
            db.commit()
        
        return RedirectResponse(
            url=f"/objects/{obj.id}?success=Объект успешно создан",
            status_code=303
        )
        
    except ValidationError as e:
        error_msg = e.errors()[0]["msg"]
        return RedirectResponse(
            url=f"/objects/create?error={error_msg}",
            status_code=303
        )


# ===================================
# Форма редактирования объекта
# ===================================
@router.get("/{object_id}/edit", response_class=HTMLResponse)
async def edit_object_page(
    object_id: int,
    request: Request,
    user: User = Depends(get_current_user_from_cookie),
    db: Session = Depends(get_db)
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
                status_code=303
            )
        
        return templates.TemplateResponse(
            "web/objects/edit.html",
            {
                "request": request,
                "user": user,
                "object": obj
            }
        )
        
    except HTTPException as e:
        return RedirectResponse(
            url=f"/objects?error={e.detail}",
            status_code=303
        )


# ===================================
# Обновление объекта
# ===================================
@router.post("/{object_id}/edit")
async def update_object(
    object_id: int,
    request: Request,
    title: str = Form(...),
    address: str = Form(None),
    description: str = Form(None),
    department: str = Form(None),
    location: str = Form(None),
    icon: UploadFile = File(None),
    user: User = Depends(get_current_user_from_cookie),
    db: Session = Depends(get_db)
):
    """
    Обновление объекта
    """
    try:
        # Валидация
        data = ObjectUpdate(
            title=title,
            address=address,
            description=description,
            department=department,
            location=location
        )
        
        # Обновляем объект
        obj = ObjectService.update_object(object_id, data, user, db)
        
        # Загружаем новую иконку (если есть)
        if icon and icon.filename:
            icons_dir = Path("static/objects")
            icons_dir.mkdir(parents=True, exist_ok=True)
            
            file_ext = Path(icon.filename).suffix
            filename = f"{obj.id}_{uuid.uuid4().hex[:8]}{file_ext}"
            file_path = icons_dir / filename
            
            contents = await icon.read()
            with open(file_path, "wb") as f:
                f.write(contents)
            
            obj.icon_url = f"/static/objects/{filename}"
            db.commit()
        
        return RedirectResponse(
            url=f"/objects/{object_id}?success=Объект успешно обновлен",
            status_code=303
        )
        
    except ValidationError as e:
        error_msg = e.errors()[0]["msg"]
        return RedirectResponse(
            url=f"/objects/{object_id}/edit?error={error_msg}",
            status_code=303
        )
    except HTTPException as e:
        return RedirectResponse(
            url=f"/objects/{object_id}?error={e.detail}",
            status_code=303
        )

# ===================================
# Карточка объекта
# ===================================
@router.get("/{object_id}")
async def object_detail(
    object_id: int,
    request: Request,
    success: Optional[str] = None,
    error: Optional[str] = None,
    user: User = Depends(get_current_user_from_cookie),
    db: Session = Depends(get_db)
):
    """Детальная страница объекта"""
    try:
        # Получаем объект
        obj = ObjectService.get_object(object_id, user, db)
        
        # Получаем доступы
        accesses = db.query(ObjectAccess).filter(
            ObjectAccess.object_id == object_id
        ).all()
        
        # Получаем документы
        from modules.documents.service import DocumentService
        from modules.documents.models import Document
        from collections import defaultdict
        from sqlalchemy import func
        
        documents = DocumentService.list_documents(object_id, user, db)
        total_documents = len(documents)
        
        # ✅ ГРУППИРОВКА ПО КАТЕГОРИЯМ И ПОДКАТЕГОРИЯМ
        documents_by_category = {}
        
        for category in DocumentCategory:
            category_docs = [doc for doc in documents if doc.category == category]
            if category_docs:
                # Группируем по подкатегориям
                docs_by_subcat = defaultdict(list)
                for doc in category_docs:
                    subcat_id = doc.subcategory_id if doc.subcategory_id else 0
                    docs_by_subcat[subcat_id].append(doc)
                
                # Сортируем: сначала без подкатегории (0), потом остальные
                sorted_subcats = sorted(docs_by_subcat.items(), key=lambda x: (x[0] != 0, x[0]))
                
                documents_by_category[category] = {
                    'docs': category_docs,
                    'by_subcat': sorted_subcats
                }
        
        # ✅ Получаем подкатегории из БД для каждого раздела
        def get_subcategories(cat):
            return db.query(DocumentSubcategory).filter(
                DocumentSubcategory.object_id == object_id,
                DocumentSubcategory.category == cat,
                DocumentSubcategory.deleted_at == None
            ).all()
        
        subcategories_general = get_subcategories(DocumentCategory.GENERAL)
        subcategories_technical = get_subcategories(DocumentCategory.TECHNICAL)
        subcategories_accounting = get_subcategories(DocumentCategory.ACCOUNTING)
        subcategories_safety = get_subcategories(DocumentCategory.SAFETY)
        subcategories_legal = get_subcategories(DocumentCategory.LEGAL)
        subcategories_hr = get_subcategories(DocumentCategory.HR)
        
        # ✅ Преобразуем в словари для JSON
        def subcategories_to_dict(subcats):
            return [
                {"id": s.id, "name": s.name, "description": s.description, "category": s.category.value}
                for s in subcats
            ]
        
        subcategories_general_data = subcategories_to_dict(subcategories_general)
        subcategories_technical_data = subcategories_to_dict(subcategories_technical)
        subcategories_accounting_data = subcategories_to_dict(subcategories_accounting)
        subcategories_safety_data = subcategories_to_dict(subcategories_safety)
        subcategories_legal_data = subcategories_to_dict(subcategories_legal)
        subcategories_hr_data = subcategories_to_dict(subcategories_hr)
        
        # Получаем всех пользователей для автокомплита
        all_users = db.query(User).filter(User.is_active == True).all()

        # ✅ ИСПРАВЛЕНИЕ: Правильный подсчёт сотрудников по отделам
        department_stats = {}
        
        # Маппинг ролей на отделы (используем UserRole из constants)
        role_to_department = {
            UserRole.ENGINEER: 'technical',
            UserRole.LAWYER: 'legal',
            UserRole.ACCOUNTANT: 'accounting',
            UserRole.HR: 'hr'
        }
        
        for access in accesses:
            user_obj = db.query(User).filter(User.id == access.user_id).first()
            if not user_obj:
                continue
            
            # ✅ Проверяем access_departments
            if access.access_departments:
                for dept in access.access_departments:
                    if dept not in department_stats:
                        department_stats[dept] = []
                    if user_obj not in department_stats[dept]:
                        department_stats[dept].append(user_obj)
            
            # ✅ ВАЖНО: Также учитываем роль пользователя
            if user_obj.role in role_to_department:
                dept = role_to_department[user_obj.role]
                if dept not in department_stats:
                    department_stats[dept] = []
                if user_obj not in department_stats[dept]:
                    department_stats[dept].append(user_obj)
        
        # Считаем количество
        department_counts = {dept: len(users) for dept, users in department_stats.items()}
        
        logger.info({
            "event": "object_detail_viewed",
            "user_id": user.id,
            "object_id": object_id,
            "department_stats": department_counts
        })
        
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
                "success": success,
                "error": error,
                **sidebar_context
            }
        )
        
    except HTTPException as e:
        raise e
    except Exception as e:
        logger.error(f"❌ Ошибка при загрузке объекта {object_id}: {str(e)}")
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
    db: Session = Depends(get_db)
):
    """
    Удаление объекта (soft delete)
    """
    try:
        ObjectService.delete_object(object_id, user, db)
        
        return RedirectResponse(
            url="/objects?success=Объект успешно удален",
            status_code=303
        )
        
    except HTTPException as e:
        return RedirectResponse(
            url=f"/objects/{object_id}?error={e.detail}",
            status_code=303
        )


# ===================================
# Админ-панель: Все объекты
# ===================================
@router.get("/admin/all", response_class=HTMLResponse)
async def admin_objects_list(
    request: Request,
    user: User = Depends(get_current_user_from_cookie),
    db: Session = Depends(get_db),
    page: int = Query(1, ge=1),
    search: str = Query(None),
    include_deleted: bool = Query(False)
):
    """
    Админ-панель: список всех объектов
    """
    # Проверка прав
    if user.role != UserRole.ADMIN:  # ✅ исправлено
        return RedirectResponse(
            url="/objects?error=Доступ запрещен",
            status_code=303
        )
    
    page_size = 20
    skip = (page - 1) * page_size
    
    objects, total = ObjectService.list_all_objects_admin(
        db=db,
        skip=skip,
        limit=page_size,
        search=search,
        include_deleted=include_deleted
    )
    
    pages = (total + page_size - 1) // page_size
    
    logger.info({
        "event": "admin_objects_list_view",
        "user_id": user.id,
        "total": total
    })

    # Добавьте sidebar contextдля админ-панели
    from core.template_helpers import get_sidebar_context
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
            **sidebar_context
        }
    )


# ===================================
# Восстановление объекта
# ===================================
@router.post("/{object_id}/restore")
async def restore_object(
    object_id: int,
    request: Request,
    user: User = Depends(get_current_user_from_cookie),
    db: Session = Depends(get_db)
):
    """
    Восстановление удаленного объекта (только админ)
    """
    try:
        ObjectService.restore_object(object_id, user, db)
        
        return RedirectResponse(
            url=f"/objects/admin/all?success=Объект восстановлен",
            status_code=303
        )
        
    except HTTPException as e:
        return RedirectResponse(
            url=f"/objects/admin/all?error={e.detail}",
            status_code=303
        )
    

# ===================================
# Изменение статуса объекта
# ===================================
@router.post("/{object_id}/activate")
async def activate_object(
    object_id: int,
    user: User = Depends(get_current_user_from_cookie),
    db: Session = Depends(get_db)
):
    """Активировать объект"""
    obj = db.query(Object).filter(Object.id == object_id).first()
    
    if not obj:
        return RedirectResponse(url="/objects?error=Объект не найден", status_code=303)
    
    if obj.created_by != user.id and user.role != UserRole.ADMIN:  # ✅ исправлено
        return RedirectResponse(url=f"/objects/{object_id}?error=Недостаточно прав", status_code=303)
    
    obj.is_active = True
    db.commit()
    
    logger.info({"event": "object_activated", "object_id": object_id, "user_id": user.id})
    
    return RedirectResponse(url=f"/objects/{object_id}?success=Объект активирован", status_code=303)

# ===================================
# Деактивация объекта
# ===================================
@router.post("/{object_id}/deactivate")
async def deactivate_object(
    object_id: int,
    user: User = Depends(get_current_user_from_cookie),
    db: Session = Depends(get_db)
):
    """Деактивировать объект"""
    obj = db.query(Object).filter(Object.id == object_id).first()
    
    if not obj:
        return RedirectResponse(url="/objects?error=Объект не найден", status_code=303)
    
    if obj.created_by != user.id and user.role != UserRole.ADMIN:  # ✅ исправлено
        return RedirectResponse(url=f"/objects/{object_id}?error=Недостаточно прав", status_code=303)
    
    obj.is_active = False
    db.commit()
    
    logger.info({"event": "object_deactivated", "object_id": object_id, "user_id": user.id})
    
    return RedirectResponse(url=f"/objects/{object_id}?success=Объект деактивирован", status_code=303)

# ===================================
# Архивация объекта
# ===================================
@router.post("/{object_id}/archive")
async def archive_object(
    object_id: int,
    user: User = Depends(get_current_user_from_cookie),
    db: Session = Depends(get_db)
):
    """Отправить объект в архив"""
    obj = db.query(Object).filter(Object.id == object_id).first()
    
    if not obj:
        return RedirectResponse(url="/objects?error=Объект не найден", status_code=303)
    
    if obj.created_by != user.id and user.role != UserRole.ADMIN:  # ✅ исправлено
        return RedirectResponse(url=f"/objects/{object_id}?error=Недостаточно прав", status_code=303)
    
    obj.is_archived = True
    obj.is_active = False
    db.commit()
    
    logger.info({"event": "object_archived", "object_id": object_id, "user_id": user.id})
    
    return RedirectResponse(url=f"/objects/{object_id}?success=Объект отправлен в архив", status_code=303)

# ===================================
# Разархивация объекта
# ===================================
@router.post("/{object_id}/unarchive")
async def unarchive_object(
    object_id: int,
    user: User = Depends(get_current_user_from_cookie),
    db: Session = Depends(get_db)
):
    """Вернуть объект из архива"""
    obj = db.query(Object).filter(Object.id == object_id).first()
    
    if not obj:
        return RedirectResponse(url="/objects?error=Объект не найден", status_code=303)
    
    if obj.created_by != user.id and user.role != UserRole.ADMIN:  # ✅ исправлено
        return RedirectResponse(url=f"/objects/{object_id}?error=Недостаточно прав", status_code=303)
    
    obj.is_archived = False
    obj.is_active = True
    db.commit()
    
    logger.info({"event": "object_unarchived", "object_id": object_id, "user_id": user.id})
    
    return RedirectResponse(url=f"/objects/{object_id}?success=Объект возвращен из архива", status_code=303)


# ===================================
# Управление доступом к объекту
# ===================================
@router.post("/{object_id}/access/grant")
async def grant_object_access(
    object_id: int,
    user_email: str = Form(...),
    role: str = Form(...),
    sections: List[str] = Form([]),
    current_user: User = Depends(get_current_user_from_cookie),
    db: Session = Depends(get_db)
):
    """Предоставить доступ пользователю к объекту"""
    try:
        # ✅ Проверка прав ДО всех операций
        if not ObjectService.can_manage_access(current_user, object_id, db):
            return RedirectResponse(
                url=f"/objects/{object_id}?error=Недостаточно прав для управления доступом",
                status_code=303
            )

        # Находим пользователя по email
        target_user = db.query(User).filter(User.email == user_email).first()
        
        if not target_user:
            return RedirectResponse(
                url=f"/objects/{object_id}?error=Пользователь с email {user_email} не найден",
                status_code=303
            )
        
        # Проверяем, нет ли уже доступа
        existing = db.query(ObjectAccess).filter(
            ObjectAccess.object_id == object_id,
            ObjectAccess.user_id == target_user.id
        ).first()
        
        if existing:
            return RedirectResponse(
                url=f"/objects/{object_id}?error=У пользователя уже есть доступ к этому объекту",
                status_code=303
            )
        
        # Автоматически добавляем отдел на основе роли
        role_to_department = {
            UserRole.ENGINEER: 'technical',
            UserRole.LAWYER: 'legal',
            UserRole.ACCOUNTANT: 'accounting',
            UserRole.HR: 'hr'
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
            sections_access=sections
        )
        
        ObjectService.grant_access(object_id, access_data, current_user, db)
        
        # ✅ Логируем с новым форматом
        logger.info({
            "event": "access_granted",
            "actor_id": current_user.id,
            "object_id": object_id,
            "target_user_id": target_user.id,
            "target_user_email": target_user.email,
            "role": role,
            "sections": sections
        })
        
        return RedirectResponse(
            url=f"/objects/{object_id}?success=Доступ предоставлен пользователю {target_user.first_name or target_user.email}",
            status_code=303
        )
        
    except HTTPException as e:
        return RedirectResponse(
            url=f"/objects/{object_id}?error={e.detail}",
            status_code=303
        )

def sync_with_acl(object_id: int, user_id: int, role: ObjectAccessRole, db: Session):
    """
    Синхронизировать ObjectAccess с глобальной системой ACL
    """
    try:
        # Определяем права в ACL на основе роли
        if role in [ObjectAccessRole.OWNER, ObjectAccessRole.ADMIN]:
            permissions = [PermissionType.ADMIN, PermissionType.READ, PermissionType.WRITE]
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
                user_id=user_id
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
    db: Session = Depends(get_db)
):
    """
    Отозвать доступ пользователя к объекту
    """
    try:
        ObjectService.revoke_access(object_id, user_id, current_user, db)
        
        return RedirectResponse(
            url=f"/objects/{object_id}?success=Доступ отозван",
            status_code=303
        )
        
    except HTTPException as e:
        return RedirectResponse(
            url=f"/objects/{object_id}?error={e.detail}",
            status_code=303
        )
    

# ===================================
# Предоставить доступ всему отделу
# ===================================
@router.post("/{object_id}/access/grant-department")
async def grant_department_access(
    object_id: int,
    department: str = Form(...),
    role: str = Form(...),
    current_user: User = Depends(get_current_user_from_cookie),
    db: Session = Depends(get_db)
):
    """
    Предоставить доступ всему отделу
    """
    try:
        # Находим всех пользователей отдела
        users_in_department = db.query(User).filter(
            User.department == department,
            User.is_active == True
        ).all()
        
        if not users_in_department:
            return RedirectResponse(
                url=f"/objects/{object_id}?error=В отделе {department} нет пользователей",
                status_code=303
            )
        
        from modules.objects.schemas import ObjectAccessCreate, ObjectAccessRoleEnum
        
        granted_count = 0
        
        for target_user in users_in_department:
            # Проверяем, нет ли уже доступа
            existing = db.query(ObjectAccess).filter(
                ObjectAccess.object_id == object_id,
                ObjectAccess.user_id == target_user.id
            ).first()
            
            if not existing:
                access_data = ObjectAccessCreate(
                    user_id=target_user.id,
                    role=ObjectAccessRoleEnum(role)
                )
                
                ObjectService.grant_access(object_id, access_data, current_user, db)
                granted_count += 1
        
        return RedirectResponse(
            url=f"/objects/{object_id}?success=Доступ предоставлен {granted_count} сотрудникам отдела {department}",
            status_code=303
        )
        
    except HTTPException as e:
        return RedirectResponse(
            url=f"/objects/{object_id}?error={e.detail}",
            status_code=303
        )
    
# ===================================
# Обновление доступа пользователя к объекту
# ===================================   
@router.post("/{object_id}/access/{user_id}/update")
async def update_object_access(
    object_id: int,
    user_id: int,
    role: str = Form(...),
    sections: List[str] = Form([]),
    current_user: User = Depends(get_current_user_from_cookie),
    db: Session = Depends(get_db)
):
    """
    Обновить доступ пользователя к объекту
    """
    try:
        from modules.objects.schemas import ObjectAccessUpdate, ObjectAccessRoleEnum
        
        # Всегда добавляем "general"
        if "general" not in sections:
            sections.append("general")
        
        update_data = ObjectAccessUpdate(
            role=ObjectAccessRoleEnum(role),
            sections_access=sections
        )
        
        ObjectService.update_access(object_id, user_id, update_data, current_user, db)
        
        return RedirectResponse(
            url=f"/objects/{object_id}?success=Доступ успешно обновлён",
            status_code=303
        )
        
    except HTTPException as e:
        return RedirectResponse(
            url=f"/objects/{object_id}?error={e.detail}",
            status_code=303
        )    

# Получить подкатегории для объекта
@router.get("/{object_id}/subcategories")
async def get_object_subcategories(
    object_id: int,
    category: Optional[str] = None,
    current_user: User = Depends(get_current_user_from_cookie),
    db: Session = Depends(get_db)
):
    """
    Получить подкатегории для объекта
    """
    # Проверяем доступ к объекту
    ObjectService.get_object(object_id, current_user, db)
    
    # Получаем подкатегории
    query = db.query(DocumentSubcategory).filter(
        DocumentSubcategory.object_id == object_id,
        DocumentSubcategory.deleted_at == None
    )
    
    if category:
        query = query.filter(DocumentSubcategory.category == category)
    
    subcategories = query.order_by(DocumentSubcategory.order, DocumentSubcategory.created_at).all()
    
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
    name: str = Form(...),
    description: Optional[str] = Form(None),
    category: str = Form(...),
    current_user: User = Depends(get_current_user_from_cookie),
    db: Session = Depends(get_db)
):
    """
    Создать подкатегорию для объекта
    """
    # Проверяем доступ
    obj = db.query(Object).filter(Object.id == object_id).first()
    
    if not obj:
        return RedirectResponse(
            url=f"/objects/{object_id}?error=Объект не найден",
            status_code=303
        )
    
    if obj.created_by != current_user.id and current_user.role != UserRole.ADMIN:  # ✅ исправлено
        return RedirectResponse(
            url=f"/objects/{object_id}?error=Недостаточно прав",
            status_code=303
        )
    
    # Создаём подкатегорию
    from modules.documents.models import DocumentCategory
    
    subcategory = DocumentSubcategory(
        name=name,
        description=description,
        category=DocumentCategory(category),
        object_id=object_id,
        created_by=current_user.id
    )
    
    db.add(subcategory)
    db.commit()
    
    logger.info({
        "event": "subcategory_created",
        "object_id": obj.id,
        "object_title": obj.title,
        "subcategory_id": subcategory.id,
        "subcategory_name": subcategory.name,
        "actor_id": current_user.id,
        "actor_email": current_user.email,
        "timestamp": datetime.utcnow().isoformat()
    })
    
    return RedirectResponse(
        url=f"/objects/{object_id}?success=Подкатегория '{name}' создана",
        status_code=303
    )

#  Удалить подкатегорию
@router.post("/{object_id}/subcategories/{subcategory_id}/delete")
async def delete_subcategory(
    object_id: int,
    subcategory_id: int,
    current_user: User = Depends(get_current_user_from_cookie),
    db: Session = Depends(get_db)
):
    """
    Удалить подкатегорию (только создатель/админ/владелец объекта)
    """
    try:
        from modules.documents.models import DocumentSubcategory
        
        # Проверяем доступ к объекту
        obj = ObjectService.get_object(object_id, current_user, db)
        
        # Получаем подкатегорию
        subcategory = db.query(DocumentSubcategory).filter(
            DocumentSubcategory.id == subcategory_id,
            DocumentSubcategory.object_id == object_id
        ).first()
        
        if not subcategory:
            return RedirectResponse(
                url=f"/objects/{object_id}?error=Подкатегория не найдена",
                status_code=303
            )
        
        # Проверяем права: создатель подкатегории ИЛИ админ ИЛИ владелец объекта
        if (subcategory.created_by != current_user.id and 
            current_user.role != UserRole.ADMIN and  # ✅ исправлено
            obj.created_by != current_user.id):
            return RedirectResponse(
                url=f"/objects/{object_id}?error=Недостаточно прав для удаления",
                status_code=303
            )
        
        # Удаляем подкатегорию (мягкое удаление)
        subcategory.deleted_at = datetime.utcnow()
        db.commit()
        
        logger.info({
            "event": "subcategory_deleted",
            "object_id": obj.id,
            "object_title": obj.title,
            "subcategory_id": subcategory.id,
            "subcategory_name": subcategory.name,
            "actor_id": current_user.id,
            "actor_email": current_user.email,
            "timestamp": datetime.utcnow().isoformat()
        })
        
        return RedirectResponse(
            url=f"/objects/{object_id}?success=Подкатегория удалена",
            status_code=303
        )
        
    except HTTPException as e:
        return RedirectResponse(
            url=f"/objects/{object_id}?error={e.detail}",
            status_code=303
        )


# Редактировать подкатегорию
@router.post("/{object_id}/subcategories/{subcategory_id}/update")
async def update_subcategory(
    object_id: int,
    subcategory_id: int,
    name: str = Form(...),
    description: Optional[str] = Form(None),
    current_user: User = Depends(get_current_user_from_cookie),
    db: Session = Depends(get_db)
):
    """
    Редактировать подкатегорию (только создатель/админ/владелец объекта)
    """
    try:
        from modules.documents.models import DocumentSubcategory
        
        # Проверяем доступ к объекту
        obj = ObjectService.get_object(object_id, current_user, db)
        
        # Получаем подкатегорию
        subcategory = db.query(DocumentSubcategory).filter(
            DocumentSubcategory.id == subcategory_id,
            DocumentSubcategory.object_id == object_id
        ).first()
        
        if not subcategory:
            return RedirectResponse(
                url=f"/objects/{object_id}?error=Подкатегория не найдена",
                status_code=303
            )
        
        # Проверяем права
        if (subcategory.created_by != current_user.id and 
            current_user.role != UserRole.ADMIN and  # ✅ исправлено
            obj.created_by != current_user.id):
            return RedirectResponse(
                url=f"/objects/{object_id}?error=Недостаточно прав для редактирования",
                status_code=303
            )
        
        # Обновляем подкатегорию
        old_name = subcategory.name
        subcategory.name = name
        subcategory.description = description
        db.commit()
        
        logger.info({
            "event": "subcategory_updated",
            "object_id": obj.id,
            "object_title": obj.title,
            "subcategory_id": subcategory.id,
            "old_name": old_name,
            "new_name": name,
            "actor_id": current_user.id,
            "actor_email": current_user.email,
            "timestamp": datetime.utcnow().isoformat()
        })
        
        return RedirectResponse(
            url=f"/objects/{object_id}?success=Подкатегория обновлена",
            status_code=303
        )
        
    except HTTPException as e:
        return RedirectResponse(
            url=f"/objects/{object_id}?error={e.detail}",
            status_code=303
        )