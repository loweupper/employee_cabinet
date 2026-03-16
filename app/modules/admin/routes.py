import csv
import json
import logging
from datetime import datetime, timedelta, timezone
from io import StringIO
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import or_
from sqlalchemy.orm import Session, joinedload

from modules.auth.ip_geo import get_ip_geo
from modules.auth.user_agent_parser import parse_user_agent

from core.constants import get_department_for_role
from core.database import get_db
from core.template_helpers import get_sidebar_context
from modules.admin.models import AuditLog, LogLevel
from modules.auth.dependencies import get_current_user_from_cookie
from modules.auth.models import Department, User, UserRole
from modules.auth.models import Session as SessionModel
from modules.auth.utils import hash_password
from modules.auth import department_service
from core.logging.actions import (
    log_admin_action,
)
from modules.documents.service_mappings import CategoryMappingService

logger = logging.getLogger("app")
router = APIRouter(
    prefix="/admin",
    tags=["admin"],
    responses={
        400: {"description": "Некорректный запрос"},
        403: {"description": "Доступ запрещён"},
        404: {"description": "Ресурс не найден"},
    },
)
templates = Jinja2Templates(directory="templates")

MSK = timezone(timedelta(hours=3))

ERROR_ACCESS_DENIED_EN = "Access denied"
ERROR_ACCESS_DENIED_RU = "Доступ запрещён"
ERROR_USER_NOT_FOUND = "Пользователь не найден"
ERROR_LOG_NOT_FOUND = "Log not found"


def _apply_user_status_filter(query, status: str):
    if status == "active":
        return query.filter(User.is_active.is_(True), User.deleted_at.is_(None))

    if status == "pending":
        return query.filter(
            User.is_active.is_(False),
            User.activated_at.is_(None),
            User.deleted_at.is_(None),
        )

    if status == "deactivated":
        return query.filter(
            User.is_active.is_(False),
            User.activated_at.is_not(None),
            User.deleted_at.is_(None),
        )

    if status == "deleted":
        return query.filter(User.deleted_at.is_not(None))

    return query.filter(User.deleted_at.is_(None))


def _collect_users_stats(db: Session):
    total_users = db.query(User).filter(User.deleted_at.is_(None)).count()
    active_users = (
        db.query(User)
        .filter(User.is_active.is_(True), User.deleted_at.is_(None))
        .count()
    )
    pending_users = (
        db.query(User)
        .filter(
            User.is_active.is_(False),
            User.activated_at.is_(None),
            User.deleted_at.is_(None),
        )
        .count()
    )
    deactivated_users = (
        db.query(User)
        .filter(
            User.is_active.is_(False),
            User.activated_at.is_not(None),
            User.deleted_at.is_(None),
        )
        .count()
    )
    deleted_users = db.query(User).filter(User.deleted_at.is_not(None)).count()
    return {
        "total_users": total_users,
        "active_users": active_users,
        "pending_users": pending_users,
        "deactivated_users": deactivated_users,
        "deleted_users": deleted_users,
    }


def _set_optional_text_field(target_user: User, form_data, form_key: str):
    value = form_data.get(form_key)
    if value is not None:
        setattr(target_user, form_key, value.strip() or None)


def _apply_editable_profile_fields(target_user: User, form_data):
    for field_name in [
        "first_name",
        "last_name",
        "middle_name",
        "phone_number",
        "position",
        "location",
    ]:
        _set_optional_text_field(target_user, form_data, field_name)


def _update_user_email(db: Session, target_user: User, user_id: int, form_data):
    email_raw = form_data.get("email")
    if not email_raw:
        return None

    new_email = email_raw.lower().strip()
    existing = (
        db.query(User).filter(User.email == new_email, User.id != user_id).first()
    )
    if existing:
        return JSONResponse(
            {
                "success": False,
                "message": "Email уже используется другим пользователем",
            },
            status_code=400,
        )

    target_user.email = new_email
    return None


def _update_user_department(target_user: User, form_data):
    department_id_raw = form_data.get("department_id")
    if department_id_raw is None:
        return None

    department_id_str = department_id_raw.strip()
    if not department_id_str:
        target_user.department_id = None
        return None

    try:
        target_user.department_id = int(department_id_str)
    except ValueError:
        return JSONResponse(
            {"success": False, "message": "Некорректный ID отдела"},
            status_code=400,
        )

    return None


def _update_user_role_from_form(target_user: User, form_data):
    new_role = form_data.get("role")
    if not new_role:
        return None

    try:
        target_user.role = UserRole(new_role)
    except ValueError:
        return JSONResponse(
            {"success": False, "message": f"Недопустимая роль: {new_role}"},
            status_code=400,
        )

    return None


def _apply_user_edit_form(db: Session, target_user: User, user_id: int, form_data):
    _apply_editable_profile_fields(target_user, form_data)

    email_error = _update_user_email(db, target_user, user_id, form_data)
    if email_error:
        return email_error

    department_error = _update_user_department(target_user, form_data)
    if department_error:
        return department_error

    return _update_user_role_from_form(target_user, form_data)


def _build_user_response_payload(target_user: User):
    return {
        "id": target_user.id,
        "first_name": target_user.first_name,
        "last_name": target_user.last_name,
        "middle_name": target_user.middle_name,
        "email": target_user.email,
        "phone_number": target_user.phone_number,
        "department_id": target_user.department_id,
        "position": target_user.position,
        "location": target_user.location,
    }


def _apply_audit_scalar_filters(
    query, level: str, event: str, user_id: int, http_method: str
):
    if level:
        query = query.filter(AuditLog.level == level)
    if event:
        query = query.filter(AuditLog.event == event)
    if user_id:
        query = query.filter(AuditLog.user_id == user_id)
    if http_method:
        query = query.filter(AuditLog.http_method == http_method)
    return query


def _apply_audit_date_range_filter(query, date_from: str, date_to: str):
    if date_from:
        try:
            date_from_dt = datetime.strptime(date_from, "%Y-%m-%d")
            query = query.filter(AuditLog.created_at >= date_from_dt)
        except ValueError:
            pass

    if date_to:
        try:
            date_to_dt = datetime.strptime(date_to, "%Y-%m-%d") + timedelta(days=1)
            query = query.filter(AuditLog.created_at < date_to_dt)
        except ValueError:
            pass

    return query


def _apply_audit_search_filter(query, search: str):
    if not search:
        return query

    search_pattern = f"%{search}%"
    return query.filter(
        or_(
            AuditLog.event.ilike(search_pattern),
            AuditLog.message.ilike(search_pattern),
            AuditLog.user_email.ilike(search_pattern),
            AuditLog.ip_address.ilike(search_pattern),
            AuditLog.request_id.ilike(search_pattern),
            AuditLog.http_path.ilike(search_pattern),
        )
    )


def _serialize_log_detail(log: AuditLog):
    user_agent_str = log.user_agent.user_agent if log.user_agent else None
    extra_data = None
    if log.extra_data:
        try:
            extra_data = json.loads(log.extra_data)
        except json.JSONDecodeError:
            extra_data = {"raw": log.extra_data}

    return {
        "id": log.id,
        "created_at": log.created_at.strftime("%Y-%m-%d %H:%M:%S"),
        "level": log.level.value,
        "event": log.event,
        "message": log.message,
        "request_id": log.request_id,
        "trace_id": log.trace_id,
        "user_id": log.user_id,
        "user_email": log.user_email,
        "ip_address": log.ip_address,
        "user_agent": user_agent_str,
        "http_method": log.http_method,
        "http_path": log.http_path,
        "http_status": log.http_status,
        "duration_ms": log.duration_ms,
        "extra_data": extra_data,
        "expires_at": (
            log.expires_at.strftime("%Y-%m-%d %H:%M:%S") if log.expires_at else None
        ),
    }


def _serialize_log_for_json_export(log: AuditLog):
    return {
        "id": log.id,
        "created_at": log.created_at.isoformat(),
        "level": log.level.value,
        "event": log.event,
        "message": log.message,
        "request_id": log.request_id,
        "trace_id": log.trace_id,
        "user_id": log.user_id,
        "user_email": log.user_email,
        "ip_address": log.ip_address,
        "http_method": log.http_method,
        "http_path": log.http_path,
        "http_status": log.http_status,
        "duration_ms": log.duration_ms,
        "extra_data": _parse_extra_data(log.extra_data),
    }


# ===================================
# Список пользователей
# ===================================
@router.get(
    "/users",
    response_class=HTMLResponse,
    responses={403: {"description": "Access denied"}},
)
async def users_list(
    request: Request,
    status: str = None,  # all, active, pending, deactivated, deleted
    search: str = None,
    user: Annotated[User, Depends(get_current_user_from_cookie)] = Depends(
        get_current_user_from_cookie
    ),
    db: Annotated[Session, Depends(get_db)] = Depends(get_db),
):
    """Админ-панель: список пользователей"""

    # Проверка прав админа
    if user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail=ERROR_ACCESS_DENIED_EN)

    # Базовый запрос с eager loading для department_rel
    query = db.query(User).options(joinedload(User.department_rel))

    query = _apply_user_status_filter(query, status)

    # Поиск
    if search:
        search_pattern = f"%{search}%"
        query = query.filter(
            or_(
                User.email.ilike(search_pattern),
                User.first_name.ilike(search_pattern),
                User.last_name.ilike(search_pattern),
            )
        )

    users = query.order_by(User.created_at.desc()).all()

    # ===================================
    # Статистика
    # ===================================

    users_stats = _collect_users_stats(db)
    total_users = users_stats["total_users"]
    active_users = users_stats["active_users"]
    pending_users = users_stats["pending_users"]
    deactivated_users = users_stats["deactivated_users"]
    deleted_users = users_stats["deleted_users"]

    logger.info(
        {
            "event": "admin_users_list",
            "admin_id": user.id,
            "total_users": total_users,
            "active": active_users,
            "pending": pending_users,
            "deactivated": deactivated_users,
            "deleted": deleted_users,
        }
    )

    # Get all departments for dropdown
    departments = department_service.get_departments(db)

    from modules.permissions.models import Permission

    permissions = db.query(Permission).all()
    # user_subsections заполняются по AJAX при открытии модального окна.
    user_subsections = []

    return templates.TemplateResponse(
        "web/admin/users.html",
        {
            "request": request,
            "current_user": user,
            "user": user,
            "users": users,
            "departments": departments,
            "total_users": total_users,
            "active_users": active_users,
            "pending_users": pending_users,
            "deactivated_users": deactivated_users,
            "deleted_users": deleted_users,
            "pending_users_count": pending_users,
            "current_status": status or "all",
            "search_query": search or "",
            "permissions": permissions,
            "user_subsections": user_subsections,
        },
    )


# ===================================
# Активировать пользователя
# ===================================
@router.post(
    "/users/{user_id}/activate",
    responses={
        403: {"description": "Доступ запрещён"},
        404: {"description": "Пользователь не найден"},
    },
)
async def activate_user(
    user_id: int,
    request: Request,
    admin: Annotated[User, Depends(get_current_user_from_cookie)] = Depends(
        get_current_user_from_cookie
    ),
    db: Annotated[Session, Depends(get_db)] = Depends(get_db),
):
    """Активировать пользователя"""

    if admin.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail=ERROR_ACCESS_DENIED_RU)

    target_user = db.query(User).filter(User.id == user_id).first()

    if not target_user:
        raise HTTPException(status_code=404, detail=ERROR_USER_NOT_FOUND)

    target_user.is_active = True

    # Если пользователь активируется впервые, ставим дату активации
    if target_user.activated_at is None:
        target_user.activated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(target_user)

    logger.info(
        {
            "event": "user_activated",
            "admin_id": admin.id,
            "user_id": user_id,
            "email": target_user.email,
        }
    )

    return JSONResponse({"success": True, "message": "Пользователь активирован"})


# ===================================
# Деактивировать пользователя
# ===================================
@router.post(
    "/users/{user_id}/deactivate",
    responses={
        400: {"description": "Нельзя деактивировать самого себя"},
        403: {"description": "Доступ запрещён"},
        404: {"description": "Пользователь не найден"},
    },
)
async def deactivate_user(
    user_id: int,
    request: Request,
    admin: Annotated[User, Depends(get_current_user_from_cookie)] = Depends(
        get_current_user_from_cookie
    ),
    db: Annotated[Session, Depends(get_db)] = Depends(get_db),
):
    """Деактивировать пользователя"""

    if admin.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail=ERROR_ACCESS_DENIED_RU)

    target_user = db.query(User).filter(User.id == user_id).first()

    if not target_user:
        raise HTTPException(status_code=404, detail=ERROR_USER_NOT_FOUND)

    if target_user.id == admin.id:
        raise HTTPException(
            status_code=400,
            detail="Нельзя деактивировать самого себя",
        )

    target_user.is_active = False
    db.commit()
    db.refresh(target_user)

    logger.info(
        {
            "event": "user_deactivated",
            "admin_id": admin.id,
            "user_id": user_id,
            "email": target_user.email,
        }
    )

    return JSONResponse({"success": True, "message": "Пользователь деактивирован"})


# ===================================
# Изменить роль пользователя
# ===================================
@router.post(
    "/users/{user_id}/role",
    responses={
        400: {"description": "Недопустимая роль"},
        403: {"description": "Доступ запрещён"},
        404: {"description": "Пользователь не найден"},
    },
)
async def change_user_role(
    user_id: int,
    request: Request,
    admin: Annotated[User, Depends(get_current_user_from_cookie)] = Depends(
        get_current_user_from_cookie
    ),
    db: Annotated[Session, Depends(get_db)] = Depends(get_db),
):
    """Изменить роль пользователя"""

    if admin.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail=ERROR_ACCESS_DENIED_RU)

    form = await request.form()
    role = form.get("role")

    target_user = db.query(User).filter(User.id == user_id).first()

    if not target_user:
        raise HTTPException(status_code=404, detail=ERROR_USER_NOT_FOUND)

    if target_user.id == admin.id:
        raise HTTPException(
            status_code=400, detail="Нельзя изменить свою собственную роль"
        )

    try:
        target_user.role = UserRole(role)
        from modules.documents.service import DocumentService

        DocumentService.sync_user_access_by_role(target_user, db)

        dept_name = get_department_for_role(target_user.role)
        if dept_name:
            department = (
                db.query(Department).filter(Department.name == dept_name).first()
            )
            if department:
                target_user.department_id = department.id

        db.commit()
        db.refresh(target_user)

        logger.info(
            {
                "event": "user_role_changed",
                "admin_id": admin.id,
                "user_id": user_id,
                "new_role": role,
            }
        )

        return JSONResponse({"success": True, "message": f"Роль изменена на {role}"})
    except ValueError:
        raise HTTPException(status_code=400, detail="Недопустимая роль")


# ===================================
# Удалить пользователя
# ===================================
@router.delete("/users/{user_id}")
async def delete_user(
    user_id: int,
    request: Request,
    admin: Annotated[User, Depends(get_current_user_from_cookie)] = Depends(
        get_current_user_from_cookie
    ),
    db: Annotated[Session, Depends(get_db)] = Depends(get_db),
):
    """Удалить пользователя (мягкое удаление)"""

    if admin.role != UserRole.ADMIN:
        return JSONResponse(
            {"success": False, "message": ERROR_ACCESS_DENIED_RU}, status_code=403
        )

    target_user = db.query(User).filter(User.id == user_id).first()

    if not target_user:
        return JSONResponse(
            {"success": False, "message": ERROR_USER_NOT_FOUND}, status_code=404
        )

    if target_user.id == admin.id:
        return JSONResponse(
            {"success": False, "message": "Нельзя удалить самого себя"},
            status_code=400,
        )

    email = target_user.email

    try:
        from modules.auth.models import Session as SessionModel

        # ✅ Деактивируем пользователя и ставим дату удаления
        target_user.deleted_at = datetime.now(timezone.utc)
        target_user.is_active = False

        # Помечаем email как удалённый, чтобы освободить исходный email.
        import time

        target_user.email = f"deleted_{int(time.time())}_{email}"

        # ✅ Отзываем все сессии
        db.query(SessionModel).filter(SessionModel.user_id == user_id).update(
            {"is_revoked": True}
        )

        db.commit()

        logger.info(
            {
                "event": "user_soft_deleted",
                "admin_id": admin.id,
                "user_id": user_id,
                "original_email": email,
            }
        )

        return JSONResponse({"success": True, "message": "Пользователь удалён"})

    except Exception as e:
        db.rollback()
        logger.error(
            {
                "event": "user_delete_error",
                "admin_id": admin.id,
                "user_id": user_id,
                "error": str(e),
            },
            exc_info=True,
        )

        return JSONResponse(
            {"success": False, "message": f"Ошибка: {str(e)}"}, status_code=500
        )


# ===================================
# Редактирование пользователя
# ===================================
@router.post("/users/{user_id}/edit")
async def edit_user(
    user_id: int,
    request: Request,
    admin: Annotated[User, Depends(get_current_user_from_cookie)] = Depends(
        get_current_user_from_cookie
    ),
    db: Annotated[Session, Depends(get_db)] = Depends(get_db),
):
    """Редактировать данные пользователя"""

    if admin.role != UserRole.ADMIN:
        return JSONResponse(
            {"success": False, "message": ERROR_ACCESS_DENIED_RU}, status_code=403
        )

    target_user = db.query(User).filter(User.id == user_id).first()

    if not target_user:
        return JSONResponse(
            {"success": False, "message": ERROR_USER_NOT_FOUND}, status_code=404
        )

    try:
        old_department_id = target_user.department_id
        form = await request.form()

        error_response = _apply_user_edit_form(db, target_user, user_id, form)
        if error_response:
            return error_response

        db.commit()
        db.refresh(target_user)

        if old_department_id != target_user.department_id:
            from modules.objects.service import ObjectService

            ObjectService.sync_user_access_by_department(target_user, db)

        logger.info(
            {
                "event": "user_edited",
                "admin_id": admin.id,
                "user_id": user_id,
                "email": target_user.email,
                "department_changed": (old_department_id != target_user.department_id),
            }
        )

        return JSONResponse(
            {
                "success": True,
                "message": "Данные пользователя обновлены",
                "user": _build_user_response_payload(target_user),
            }
        )

    except Exception as e:
        db.rollback()
        logger.error(
            {
                "event": "user_edit_error",
                "admin_id": admin.id,
                "user_id": user_id,
                "error": str(e),
            },
            exc_info=True,
        )

        return JSONResponse(
            {"success": False, "message": f"Ошибка: {str(e)}"}, status_code=500
        )


# ===================================
# Сбросить пароль пользователя
# ===================================
@router.post("/users/{user_id}/reset-password")
async def reset_user_password(
    user_id: int,
    request: Request,
    admin: Annotated[User, Depends(get_current_user_from_cookie)] = Depends(
        get_current_user_from_cookie
    ),
    db: Annotated[Session, Depends(get_db)] = Depends(get_db),
):
    """Сбросить пароль пользователя (только для админа)"""

    if admin.role != UserRole.ADMIN:
        return JSONResponse(
            {"success": False, "message": ERROR_ACCESS_DENIED_RU}, status_code=403
        )

    target_user = db.query(User).filter(User.id == user_id).first()

    if not target_user:
        return JSONResponse(
            {"success": False, "message": ERROR_USER_NOT_FOUND}, status_code=404
        )

    try:
        # ✅ Читаем новый пароль из формы
        form = await request.form()
        new_password = form.get("new_password")

        if not new_password or len(new_password) < 6:
            return JSONResponse(
                {
                    "success": False,
                    "message": "Пароль должен содержать минимум 6 символов",
                },
                status_code=400,
            )

        # ✅ Хешируем и сохраняем новый пароль
        target_user.hashed_password = hash_password(new_password)

        # ✅ Отзываем все активные сессии пользователя (заставляем перелогиниться)
        from modules.auth.models import Session as SessionModel

        db.query(SessionModel).filter(
            SessionModel.user_id == user_id,
            SessionModel.is_revoked.is_(False),
        ).update({"is_revoked": True}, synchronize_session=False)

        db.commit()

        logger.info(
            {
                "event": "user_password_reset_by_admin",
                "admin_id": admin.id,
                "user_id": user_id,
                "email": target_user.email,
            }
        )

        return JSONResponse(
            {
                "success": True,
                "message": f"Пароль пользователя {target_user.email} успешно изменён",
            }
        )

    except Exception as e:
        db.rollback()
        logger.error(
            {
                "event": "user_password_reset_error",
                "admin_id": admin.id,
                "user_id": user_id,
                "error": str(e),
            },
            exc_info=True,
        )

        return JSONResponse(
            {"success": False, "message": f"Ошибка: {str(e)}"}, status_code=500
        )


def _apply_audit_log_filters(
    query,
    level: str = None,
    event: str = None,
    user_id: int = None,
    date_from: str = None,
    date_to: str = None,
    search: str = None,
    http_method: str = None,
):
    query = _apply_audit_scalar_filters(query, level, event, user_id, http_method)
    query = _apply_audit_date_range_filter(query, date_from, date_to)
    return _apply_audit_search_filter(query, search)


def _parse_extra_data(extra_data: str):
    if not extra_data:
        return {}
    try:
        return json.loads(extra_data)
    except json.JSONDecodeError:
        return {}


# ===================================
# Логи аудита (Admin)
# ===================================
@router.get(
    "/logs",
    response_class=HTMLResponse,
    responses={403: {"description": "Access denied"}},
)
async def logs_page(
    request: Request,
    level: str = None,
    event: str = None,
    user_id: int = None,
    date_from: str = None,
    date_to: str = None,
    search: str = None,
    http_method: str = None,
    page: int = 1,
    per_page: int = 50,
    user: Annotated[User, Depends(get_current_user_from_cookie)] = Depends(
        get_current_user_from_cookie
    ),
    db: Annotated[Session, Depends(get_db)] = Depends(get_db),
):
    """Просмотр логов аудита (только для админов)"""

    if user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail=ERROR_ACCESS_DENIED_EN)

    query = db.query(AuditLog).filter(AuditLog.is_archived.is_(False))
    query = _apply_audit_log_filters(
        query=query,
        level=level,
        event=event,
        user_id=user_id,
        date_from=date_from,
        date_to=date_to,
        search=search,
        http_method=http_method,
    )

    # Подсчёт общего количества
    total_logs = query.count()

    # Пагинация
    offset = (page - 1) * per_page
    logs = (
        query.order_by(AuditLog.created_at.desc()).limit(per_page).offset(offset).all()
    )

    # Парсим extra_data для каждого лога
    for log in logs:
        log.extra_data_parsed = _parse_extra_data(log.extra_data)

    # Статистика
    total_pages = (total_logs + per_page - 1) // per_page

    # Получаем уникальные события для фильтра (топ-50)
    unique_events = (
        db.query(AuditLog.event).distinct().order_by(AuditLog.event).limit(50).all()
    )
    unique_events = [e[0] for e in unique_events]

    # Получаем уникальные HTTP методы
    unique_methods = (
        db.query(AuditLog.http_method)
        .filter(AuditLog.http_method.is_not(None))
        .distinct()
        .all()
    )
    unique_methods = [m[0] for m in unique_methods if m[0]]

    logger.info(
        {
            "event": "admin_logs_viewed",
            "user_id": user.id,
            "filters": {
                "level": level,
                "event": event,
                "user_id": user_id,
                "search": search,
                "http_method": http_method,
            },
        }
    )

    sidebar_context = get_sidebar_context(user, db)

    # Конвертируем даты в локальное время (по Москве)
    for s in logs:
        s.created_at_local = s.created_at.astimezone(MSK)
        s.expires_at_local = s.expires_at.astimezone(MSK)

    return templates.TemplateResponse(
        "web/admin/logs.html",
        {
            "request": request,
            "user": user,
            "current_user": user,
            "logs": logs,
            "total_logs": total_logs,
            "page": page,
            "per_page": per_page,
            "total_pages": total_pages,
            "current_level": level,
            "current_event": event,
            "current_user_id": user_id,
            "current_http_method": http_method,
            "date_from": date_from,
            "date_to": date_to,
            "search_query": search or "",
            "unique_events": unique_events,
            "unique_methods": unique_methods,
            "now": datetime.now(MSK),
            "log_levels": [level_item.value for level_item in LogLevel],
            **sidebar_context,
        },
    )


# ===================================
# API: Детали лога (JSON)
# ===================================
@router.get(
    "/logs/{log_id}/detail",
    responses={
        403: {"description": "Access denied"},
        404: {"description": "Log not found"},
    },
)
async def log_detail_api(
    log_id: int,
    user: Annotated[User, Depends(get_current_user_from_cookie)] = Depends(
        get_current_user_from_cookie
    ),
    db: Annotated[Session, Depends(get_db)] = Depends(get_db),
):
    """Получить детали лога по ID (JSON)"""

    if user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail=ERROR_ACCESS_DENIED_EN)

    log = db.query(AuditLog).filter(AuditLog.id == log_id).first()

    if not log:
        raise HTTPException(status_code=404, detail=ERROR_LOG_NOT_FOUND)

    return _serialize_log_detail(log)


# ===================================
# Экспорт логов в CSV
# ===================================
@router.get(
    "/logs/export",
    responses={403: {"description": "Access denied"}},
)
async def logs_export_csv(
    level: str = None,
    event: str = None,
    user_id: int = None,
    date_from: str = None,
    date_to: str = None,
    search: str = None,
    http_method: str = None,
    user: Annotated[User, Depends(get_current_user_from_cookie)] = Depends(
        get_current_user_from_cookie
    ),
    db: Annotated[Session, Depends(get_db)] = Depends(get_db),
):
    """Экспорт логов в CSV"""

    if user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail=ERROR_ACCESS_DENIED_EN)

    query = db.query(AuditLog).filter(AuditLog.is_archived.is_(False))
    query = _apply_audit_log_filters(
        query=query,
        level=level,
        event=event,
        user_id=user_id,
        date_from=date_from,
        date_to=date_to,
        search=search,
        http_method=http_method,
    )

    # Ограничиваем экспорт (максимум 10000 записей)
    logs = query.order_by(AuditLog.created_at.desc()).limit(10000).all()

    # Создаём CSV
    output = StringIO()
    writer = csv.writer(output)

    # Заголовки
    writer.writerow(
        [
            "ID",
            "Время",
            "Уровень",
            "Событие",
            "Request ID",
            "HTTP Метод",
            "HTTP Путь",
            "HTTP Статус",
            "Длительность (мс)",
            "User ID",
            "Email",
            "IP-адрес",
            "Сообщение",
            "Extra Data",
        ]
    )

    # Данные
    for log in logs:
        writer.writerow(
            [
                log.id,
                log.created_at.strftime("%Y-%m-%d %H:%M:%S"),
                log.level.value,
                log.event,
                log.request_id or "",
                log.http_method or "",
                log.http_path or "",
                log.http_status or "",
                log.duration_ms or "",
                log.user_id or "",
                log.user_email or "",
                log.ip_address or "",
                log.message or "",
                log.extra_data or "",
            ]
        )

    # Логируем экспорт
    log_admin_action(
        event="logs_exported_csv", admin=user, extra={"total_records": len(logs)}
    )

    output.seek(0)

    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={
            "Content-Disposition": f"attachment; filename=logs_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        },
    )


# ===================================
# Экспорт логов в JSON
# ===================================
@router.get(
    "/logs/export/json",
    responses={403: {"description": "Доступ запрещён"}},
)
async def logs_export_json(
    level: str = None,
    event: str = None,
    user_id: int = None,
    date_from: str = None,
    date_to: str = None,
    search: str = None,
    http_method: str = None,
    user: Annotated[User, Depends(get_current_user_from_cookie)] = Depends(
        get_current_user_from_cookie
    ),
    db: Annotated[Session, Depends(get_db)] = Depends(get_db),
):
    """Экспорт логов в JSON"""

    if user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail=ERROR_ACCESS_DENIED_RU)

    query = db.query(AuditLog).filter(AuditLog.is_archived.is_(False))
    query = _apply_audit_log_filters(
        query=query,
        level=level,
        event=event,
        user_id=user_id,
        date_from=date_from,
        date_to=date_to,
        search=search,
        http_method=http_method,
    )

    # Ограничиваем экспорт
    logs = query.order_by(AuditLog.created_at.desc()).limit(10000).all()

    result = [_serialize_log_for_json_export(log) for log in logs]

    # Логируем экспорт
    log_admin_action(
        event="logs_exported_json", admin=user, extra={"total_records": len(result)}
    )

    return StreamingResponse(
        iter([json.dumps(result, ensure_ascii=False, indent=2)]),
        media_type="application/json",
        headers={
            "Content-Disposition": f"attachment; filename=logs_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        },
    )


# ===================================
# Статистика логов (Dashboard Widget)
# ===================================
@router.get(
    "/logs/stats",
    responses={403: {"description": "Доступ запрещён"}},
)
async def logs_stats(
    user: Annotated[User, Depends(get_current_user_from_cookie)] = Depends(
        get_current_user_from_cookie
    ),
    db: Annotated[Session, Depends(get_db)] = Depends(get_db),
):
    """Получить статистику логов за последние 24 часа"""

    if user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail=ERROR_ACCESS_DENIED_RU)

    # За последние 24 часа
    since = datetime.now(timezone.utc) - timedelta(hours=24)

    # Общее количество
    total = (
        db.query(AuditLog)
        .filter(AuditLog.created_at >= since, AuditLog.is_archived.is_(False))
        .count()
    )

    # По уровням
    errors = (
        db.query(AuditLog)
        .filter(
            AuditLog.created_at >= since,
            AuditLog.level == LogLevel.ERROR,
            AuditLog.is_archived.is_(False),
        )
        .count()
    )

    warnings = (
        db.query(AuditLog)
        .filter(
            AuditLog.created_at >= since,
            AuditLog.level == LogLevel.WARNING,
            AuditLog.is_archived.is_(False),
        )
        .count()
    )

    # HTTP запросы
    http_requests = (
        db.query(AuditLog)
        .filter(
            AuditLog.created_at >= since,
            AuditLog.event == "http_request",
            AuditLog.is_archived.is_(False),
        )
        .count()
    )

    # Ошибки HTTP (4xx, 5xx)
    http_errors = (
        db.query(AuditLog)
        .filter(
            AuditLog.created_at >= since,
            AuditLog.http_status >= 400,
            AuditLog.is_archived.is_(False),
        )
        .count()
    )

    return {
        "total": total,
        "errors": errors,
        "warnings": warnings,
        "http_requests": http_requests,
        "http_errors": http_errors,
        "period": "24h",
    }


# ===================================
# Department Management Endpoints
# ===================================
@router.get(
    "/departments",
    responses={403: {"description": "Доступ запрещён"}},
)
async def get_departments_list(
    admin: Annotated[User, Depends(get_current_user_from_cookie)] = Depends(
        get_current_user_from_cookie
    ),
    db: Annotated[Session, Depends(get_db)] = Depends(get_db),
):
    """Get list of all departments"""
    if admin.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail=ERROR_ACCESS_DENIED_RU)

    departments = department_service.get_departments(db)
    return {
        "departments": [
            {
                "id": d.id,
                "name": d.name,
                "description": d.description,
                "created_at": d.created_at,
                "updated_at": d.updated_at,
            }
            for d in departments
        ]
    }


# ===================================
# Создание нового отдела
# ===================================
@router.post("/departments")
async def create_department(
    request: Request,
    admin: Annotated[User, Depends(get_current_user_from_cookie)] = Depends(
        get_current_user_from_cookie
    ),
    db: Annotated[Session, Depends(get_db)] = Depends(get_db),
):
    """Create a new department"""
    if admin.role != UserRole.ADMIN:
        return JSONResponse(
            {"success": False, "message": ERROR_ACCESS_DENIED_RU}, status_code=403
        )

    try:
        form = await request.form()
        name = form.get("name", "").strip()
        description = form.get("description", "").strip()

        if not name:
            return JSONResponse(
                {"success": False, "message": "Название отдела обязательно"},
                status_code=400,
            )

        from modules.auth.schemas import DepartmentCreate

        dept_data = DepartmentCreate(name=name, description=description or None)
        department = department_service.create_department(db, dept_data)

        log_admin_action(
            event="department_created",
            admin=admin,
            target_user=None,
            request=request,
            extra={"department_id": department.id, "department_name": department.name},
        )

        return JSONResponse(
            {
                "success": True,
                "message": "Отдел успешно создан",
                "department": {
                    "id": department.id,
                    "name": department.name,
                    "description": department.description,
                },
            }
        )
    except HTTPException as e:
        return JSONResponse(
            {"success": False, "message": e.detail}, status_code=e.status_code
        )
    except Exception as e:
        logger.error(f"Ошибка создания отдела: {str(e)}", exc_info=True)
        return JSONResponse({"success": False, "message": str(e)}, status_code=500)


# ===================================
# Обновление отдела
# ===================================
@router.put("/departments/{department_id}")
async def update_department(
    department_id: int,
    request: Request,
    admin: Annotated[User, Depends(get_current_user_from_cookie)] = Depends(
        get_current_user_from_cookie
    ),
    db: Annotated[Session, Depends(get_db)] = Depends(get_db),
):
    """Update a department"""
    if admin.role != UserRole.ADMIN:
        return JSONResponse(
            {"success": False, "message": ERROR_ACCESS_DENIED_RU}, status_code=403
        )

    try:
        form = await request.form()
        name = form.get("name", "").strip() or None
        description = form.get("description", "").strip() or None

        from modules.auth.schemas import DepartmentUpdate

        dept_data = DepartmentUpdate(name=name, description=description)
        department = department_service.update_department(db, department_id, dept_data)

        if not department:
            return JSONResponse(
                {"success": False, "message": "Отдел не найден"}, status_code=404
            )

        log_admin_action(
            event="department_updated",
            admin=admin,
            target_user=None,
            request=request,
            extra={"department_id": department.id, "department_name": department.name},
        )

        return JSONResponse(
            {
                "success": True,
                "message": "Отдел успешно обновлён",
                "department": {
                    "id": department.id,
                    "name": department.name,
                    "description": department.description,
                },
            }
        )
    except HTTPException as e:
        return JSONResponse(
            {"success": False, "message": e.detail}, status_code=e.status_code
        )
    except Exception as e:
        logger.error(f"Ошибка обновления отдела: {str(e)}", exc_info=True)
        return JSONResponse({"success": False, "message": str(e)}, status_code=500)


# ===================================
# Удаление отдела
# ===================================
@router.delete("/departments/{department_id}")
async def delete_department(
    department_id: int,
    admin: Annotated[User, Depends(get_current_user_from_cookie)] = Depends(
        get_current_user_from_cookie
    ),
    db: Annotated[Session, Depends(get_db)] = Depends(get_db),
):
    """Delete a department"""
    if admin.role != UserRole.ADMIN:
        return JSONResponse(
            {"success": False, "message": ERROR_ACCESS_DENIED_RU}, status_code=403
        )

    try:
        success = department_service.delete_department(db, department_id)

        if not success:
            return JSONResponse(
                {"success": False, "message": "Отдел не найден"}, status_code=404
            )

        log_admin_action(
            event="department_deleted",
            admin=admin,
            extra={"department_id": department_id},
        )

        return JSONResponse({"success": True, "message": "Отдел успешно удалён"})
    except HTTPException as e:
        return JSONResponse(
            {"success": False, "message": e.detail}, status_code=e.status_code
        )
    except Exception as e:
        logger.error(f"Ошибка удаления отдела: {str(e)}", exc_info=True)
        return JSONResponse({"success": False, "message": str(e)}, status_code=500)


# ===================================
# Просмотр сессий пользователя
# ===================================
@router.get(
    "/users/{user_id}/sessions",
    response_class=HTMLResponse,
    responses={
        403: {"description": "Доступ запрещён"},
        404: {"description": "Пользователь не найден"},
    },
)
async def user_sessions_page(
    user_id: int,
    request: Request,
    page: int = 1,  # номер страницы для пагинации
    per_page: int = 20,  # количество сессий на странице
    admin: Annotated[User, Depends(get_current_user_from_cookie)] = Depends(
        get_current_user_from_cookie
    ),
    db: Annotated[Session, Depends(get_db)] = Depends(get_db),
):
    # Только админ
    if admin.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail=ERROR_ACCESS_DENIED_RU)

    # Проверяем, что пользователь существует
    target_user = db.query(User).filter(User.id == user_id).first()
    if not target_user:
        raise HTTPException(status_code=404, detail=ERROR_USER_NOT_FOUND)

    # Базовый запрос
    query = (
        db.query(SessionModel)
        .filter(SessionModel.user_id == user_id)
        .order_by(SessionModel.expires_at.desc())
    )

    # Пагинация
    total = query.count()
    total_pages = (total + per_page - 1) // per_page
    offset = (page - 1) * per_page

    sessions = query.limit(per_page).offset(offset).all()

    # Обработка данных
    for s in sessions:
        s.geo = get_ip_geo(s.ip_address)
        s.ua = (
            parse_user_agent(s.user_agent)
            if s.user_agent
            else {"device": "_", "browser": "_"}
        )
        s.created_at_local = s.created_at.astimezone(MSK)
        s.expires_at_local = s.expires_at.astimezone(MSK)

    sidebar_context = get_sidebar_context(admin, db)

    return templates.TemplateResponse(
        "web/admin/user_sessions.html",
        {
            "request": request,
            "user": target_user,
            "admin": admin,
            "current_user": admin,
            "sessions": sessions,
            "page": page,
            "per_page": per_page,
            "total": total,
            "total_pages": total_pages,
            "now": datetime.now(MSK),
            **sidebar_context,
        },
    )


# ===================================
# Отозвать сессию пользователя
# ===================================
@router.post(
    "/sessions/{session_id}/revoke",
    responses={
        403: {"description": "Доступ запрещён"},
        404: {"description": "Сессия не найдена"},
    },
)
async def revoke_session(
    session_id: int,
    request: Request,
    admin: Annotated[User, Depends(get_current_user_from_cookie)] = Depends(
        get_current_user_from_cookie
    ),
    db: Annotated[Session, Depends(get_db)] = Depends(get_db),
):
    # Только админ
    if admin.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail=ERROR_ACCESS_DENIED_RU)

    # Ищем сессию
    session = db.query(SessionModel).filter(SessionModel.id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Сессия не найдена")

    # Если уже отозвана — ничего не делаем
    if session.is_revoked:
        return JSONResponse({"success": True, "message": "Сессия уже завершена"})

    # Отзываем
    session.is_revoked = True
    session.expires_at = datetime.now(MSK)  # фиксируем момент завершения
    db.commit()

    # Логируем
    log_admin_action(
        event="revoke_session",
        admin=admin,
        target_user=db.query(User).filter(User.id == session.user_id).first(),
        request=request,
        extra={"session_id": session.id, "ip": session.ip_address},
    )

    # Возвращаемся обратно на страницу сессий
    return JSONResponse({"success": True, "message": "Сессия успешно завершена"})


# ===================================
# Завершить все сессии пользователя
# ===================================
@router.post(
    "/users/{user_id}/sessions/revoke-all",
    responses={
        403: {"description": "Доступ запрещён"},
        404: {"description": "Пользователь не найден"},
    },
)
async def revoke_all_sessions(
    user_id: int,
    request: Request,
    admin: Annotated[User, Depends(get_current_user_from_cookie)] = Depends(
        get_current_user_from_cookie
    ),
    db: Annotated[Session, Depends(get_db)] = Depends(get_db),
):
    # Только админ
    if admin.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail=ERROR_ACCESS_DENIED_RU)

    # Проверяем, что пользователь существует
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail=ERROR_USER_NOT_FOUND)

    # Отзываем все активные сессии
    updated = (
        db.query(SessionModel)
        .filter(
            SessionModel.user_id == user_id,
            SessionModel.is_revoked.is_(False),
        )
        .update(
            {SessionModel.is_revoked: True, SessionModel.expires_at: datetime.now(MSK)},
            synchronize_session=False,
        )
    )

    db.commit()

    # Логируем
    log_admin_action(
        event="revoke_all_sessions",
        admin=admin,
        target_user=user,
        request=request,
        extra={"revoked_count": updated},
    )

    return JSONResponse(
        {
            "success": True,
            "message": f"Все активные сессии пользователя ({updated}) завершены",
        }
    )


# ===================================
# Завершить все сессии пользователя, кроме текущей
# ===================================
@router.post(
    "/users/{user_id}/sessions/revoke-others",
    responses={
        400: {"description": "Нет refresh-токена"},
        403: {"description": "Доступ запрещён"},
    },
)
async def revoke_other_sessions(
    user_id: int,
    request: Request,
    admin: Annotated[User, Depends(get_current_user_from_cookie)] = Depends(
        get_current_user_from_cookie
    ),
    db: Annotated[Session, Depends(get_db)] = Depends(get_db),
):
    if admin.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail=ERROR_ACCESS_DENIED_RU)

    target_user = db.query(User).filter(User.id == user_id).first()

    # refresh-токен текущей сессии
    refresh_token = request.cookies.get("refresh_token")
    if not refresh_token:
        raise HTTPException(status_code=400, detail="Нет refresh-токена")

    from modules.auth.utils import hash_refresh_token

    # Хэшируем его так же, как при создании
    current_hash = hash_refresh_token(refresh_token)

    # Завершаем все сессии, кроме текущей
    updated = (
        db.query(SessionModel)
        .filter(
            SessionModel.user_id == user_id,
            SessionModel.token_hash != current_hash,
            SessionModel.is_revoked.is_(False),
        )
        .update({"is_revoked": True}, synchronize_session=False)
    )

    db.commit()

    # Логируем
    log_admin_action(
        event="revoke_other_sessions",
        admin=admin,
        request=request,
        extra={"target_user": target_user, "revoked_count": updated},
    )

    return {"success": True, "message": f"Завершено сессий: {updated}"}


# ===================================
# Управление маппингами категорий документов
# ===================================


@router.get(
    "/category-mappings",
    response_class=HTMLResponse,
    responses={403: {"description": "Доступ запрещён"}},
)
async def category_mappings_page(
    request: Request,
    user: Annotated[User, Depends(get_current_user_from_cookie)] = Depends(
        get_current_user_from_cookie
    ),
    db: Annotated[Session, Depends(get_db)] = Depends(get_db),
):
    """Страница управления маппингами категорий"""
    if user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail=ERROR_ACCESS_DENIED_RU)

    mappings = CategoryMappingService.get_all_mappings(db)
    departments = db.query(Department).all()
    pending_users = (
        db.query(User)
        .filter(
            User.is_active.is_(False),
            User.activated_at.is_(None),
            User.deleted_at.is_(None),
        )
        .count()
    )

    return templates.TemplateResponse(
        "web/admin/category_mappings.html",
        {
            "request": request,
            "user": user,
            "current_user": user,
            "mappings": mappings,
            "departments": departments,
            "pending_users_count": pending_users,
        },
    )


@router.put(
    "/category-mappings/{category}",
    responses={
        403: {"description": "Доступ запрещён"},
        404: {"description": "Маппинг не найден"},
    },
)
async def update_category_mapping(
    category: str,
    request: Request,
    user: Annotated[User, Depends(get_current_user_from_cookie)] = Depends(
        get_current_user_from_cookie
    ),
    db: Annotated[Session, Depends(get_db)] = Depends(get_db),
):
    """Обновить маппинг категории"""
    if user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail=ERROR_ACCESS_DENIED_RU)

    data = await request.json()
    department_id = data.get("department_id")
    # Convert empty string to None
    if department_id == "":
        department_id = None
    elif department_id is not None:
        try:
            department_id = int(department_id)
        except (ValueError, TypeError):
            department_id = None

    mapping = CategoryMappingService.update_mapping(
        db,
        category=category,
        department_id=department_id,
        description=data.get("description"),
    )

    if not mapping:
        raise HTTPException(status_code=404, detail="Маппинг не найден")

    log_admin_action(
        event="category_mapping_updated",
        admin=user,
        extra={"category": category, "department_id": department_id},
    )

    return {
        "success": True,
        "mapping": {
            "category": mapping.category,
            "department_id": mapping.department_id,
            "description": mapping.description,
        },
    }


# ===================================
# Permissions API
# ===================================


@router.get(
    "/permissions",
    responses={403: {"description": "Access denied"}},
)
async def get_permissions(
    user: Annotated[User, Depends(get_current_user_from_cookie)] = Depends(
        get_current_user_from_cookie
    ),
    db: Annotated[Session, Depends(get_db)] = Depends(get_db),
):
    """Получить все разрешения"""
    if user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail=ERROR_ACCESS_DENIED_EN)

    from modules.permissions.models import Permission

    permissions = (
        db.query(Permission).order_by(Permission.category, Permission.key).all()
    )
    return [
        {
            "id": p.id,
            "key": p.key,
            "description": p.description,
            "category": p.category,
        }
        for p in permissions
    ]


@router.get(
    "/users/{user_id}/permissions",
    responses={
        403: {"description": "Access denied"},
        404: {"description": "Пользователь не найден"},
    },
)
async def get_user_permissions(
    user_id: int,
    user: Annotated[User, Depends(get_current_user_from_cookie)] = Depends(
        get_current_user_from_cookie
    ),
    db: Annotated[Session, Depends(get_db)] = Depends(get_db),
):
    """Получить разрешения пользователя"""
    if user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail=ERROR_ACCESS_DENIED_EN)

    target = db.query(User).filter(User.id == user_id).first()
    if not target:
        raise HTTPException(status_code=404, detail=ERROR_USER_NOT_FOUND)

    from modules.permissions.models import Permission, UserPermission

    user_perms = (
        db.query(Permission)
        .join(UserPermission)
        .filter(UserPermission.user_id == user_id)
        .all()
    )
    return [
        {"id": p.id, "key": p.key, "description": p.description, "category": p.category}
        for p in user_perms
    ]


@router.put(
    "/users/{user_id}/permissions",
    responses={
        403: {"description": "Access denied"},
        404: {"description": "Пользователь не найден"},
    },
)
async def update_user_permissions(
    user_id: int,
    request: Request,
    user: Annotated[User, Depends(get_current_user_from_cookie)] = Depends(
        get_current_user_from_cookie
    ),
    db: Annotated[Session, Depends(get_db)] = Depends(get_db),
):
    """Обновить разрешения пользователя"""
    if user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail=ERROR_ACCESS_DENIED_EN)

    target = db.query(User).filter(User.id == user_id).first()
    if not target:
        raise HTTPException(status_code=404, detail=ERROR_USER_NOT_FOUND)

    data = await request.json()
    permission_ids = data.get("permission_ids", [])

    from modules.permissions.models import Permission, UserPermission

    # Remove existing permissions
    db.query(UserPermission).filter(UserPermission.user_id == user_id).delete()

    # Add new permissions
    for perm_id in permission_ids:
        perm = db.query(Permission).filter(Permission.id == perm_id).first()
        if perm:
            db.add(UserPermission(user_id=user_id, permission_id=perm_id))

    db.commit()

    log_admin_action(
        event="user_permissions_updated",
        admin=user,
        extra={"user_id": user_id, "permission_ids": permission_ids},
    )

    return {"success": True, "permission_ids": permission_ids}


@router.get(
    "/users/{user_id}/subsection-access",
    responses={
        403: {"description": "Access denied"},
        404: {"description": "Пользователь не найден"},
    },
)
async def get_user_subsection_access(
    user_id: int,
    user: Annotated[User, Depends(get_current_user_from_cookie)] = Depends(
        get_current_user_from_cookie
    ),
    db: Annotated[Session, Depends(get_db)] = Depends(get_db),
):
    """Получить доступ пользователя к подразделам"""
    if user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail=ERROR_ACCESS_DENIED_EN)

    target = db.query(User).filter(User.id == user_id).first()
    if not target:
        raise HTTPException(status_code=404, detail=ERROR_USER_NOT_FOUND)

    from modules.permissions.models import UserSubsectionAccess, Subsection

    accesses = (
        db.query(UserSubsectionAccess)
        .filter(UserSubsectionAccess.user_id == user_id)
        .all()
    )
    return [
        {
            "id": a.id,
            "subsection_id": a.subsection_id,
            "subsection_name": a.subsection.name if a.subsection else None,
            "can_read": a.can_read,
            "can_write": a.can_write,
            "can_delete": a.can_delete,
        }
        for a in accesses
    ]


@router.put(
    "/users/{user_id}/subsection-access/{subsection_id}",
    responses={
        403: {"description": "Access denied"},
        404: {"description": "Пользователь или подраздел не найден"},
    },
)
async def update_user_subsection_access(
    user_id: int,
    subsection_id: int,
    request: Request,
    user: Annotated[User, Depends(get_current_user_from_cookie)] = Depends(
        get_current_user_from_cookie
    ),
    db: Annotated[Session, Depends(get_db)] = Depends(get_db),
):
    """Обновить доступ к подразделу"""
    if user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail=ERROR_ACCESS_DENIED_EN)

    target = db.query(User).filter(User.id == user_id).first()
    if not target:
        raise HTTPException(status_code=404, detail=ERROR_USER_NOT_FOUND)

    from modules.permissions.models import UserSubsectionAccess, Subsection

    subsection = db.query(Subsection).filter(Subsection.id == subsection_id).first()
    if not subsection:
        raise HTTPException(status_code=404, detail="Подраздел не найден")

    data = await request.json()
    access = (
        db.query(UserSubsectionAccess)
        .filter(
            UserSubsectionAccess.user_id == user_id,
            UserSubsectionAccess.subsection_id == subsection_id,
        )
        .first()
    )
    if access:
        access.can_read = data.get("can_read", access.can_read)
        access.can_write = data.get("can_write", access.can_write)
        access.can_delete = data.get("can_delete", access.can_delete)
    else:
        access = UserSubsectionAccess(
            user_id=user_id,
            subsection_id=subsection_id,
            can_read=data.get("can_read", True),
            can_write=data.get("can_write", False),
            can_delete=data.get("can_delete", False),
        )
        db.add(access)

    db.commit()
    db.refresh(access)

    log_admin_action(
        event="user_subsection_access_updated",
        admin=user,
        extra={
            "user_id": user_id,
            "subsection_id": subsection_id,
            "can_read": access.can_read,
            "can_write": access.can_write,
            "can_delete": access.can_delete,
        },
    )

    return {
        "success": True,
        "subsection_id": subsection_id,
        "can_read": access.can_read,
        "can_write": access.can_write,
        "can_delete": access.can_delete,
    }


@router.get(
    "/subsections",
    responses={403: {"description": "Access denied"}},
)
async def get_subsections(
    user: Annotated[User, Depends(get_current_user_from_cookie)] = Depends(
        get_current_user_from_cookie
    ),
    db: Annotated[Session, Depends(get_db)] = Depends(get_db),
):
    """Получить все подразделы"""
    if user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail=ERROR_ACCESS_DENIED_EN)

    from modules.permissions.models import Subsection

    subsections = (
        db.query(Subsection).order_by(Subsection.section_id, Subsection.order).all()
    )
    return [
        {
            "id": s.id,
            "name": s.name,
            "section_id": s.section_id,
            "description": s.description,
            "icon": s.icon,
            "order": s.order,
        }
        for s in subsections
    ]


@router.get(
    "/sections/{section_id}/subsections",
    responses={403: {"description": "Access denied"}},
)
async def get_section_subsections(
    section_id: int,
    user: Annotated[User, Depends(get_current_user_from_cookie)] = Depends(
        get_current_user_from_cookie
    ),
    db: Annotated[Session, Depends(get_db)] = Depends(get_db),
):
    """Получить подразделы раздела"""
    if user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail=ERROR_ACCESS_DENIED_EN)

    from modules.permissions.models import Subsection

    subsections = (
        db.query(Subsection)
        .filter(Subsection.section_id == section_id)
        .order_by(Subsection.order)
        .all()
    )
    return [
        {
            "id": s.id,
            "name": s.name,
            "section_id": s.section_id,
            "description": s.description,
            "icon": s.icon,
            "order": s.order,
        }
        for s in subsections
    ]
