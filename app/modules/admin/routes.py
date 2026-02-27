import csv # Для экспорта данных в CSV формат
from io import StringIO # Для работы с текстовыми потоками (например, при генерации CSV в памяти)
from fastapi import APIRouter, Depends, Request, HTTPException # Зависимости для получения данных из запроса и управления маршрутизацией
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse # Ответы для рендеринга HTML, отправки JSON и потоковой передачи данных (например, для CSV)
from fastapi.templating import Jinja2Templates # Для рендеринга HTML-шаблонов с помощью Jinja2 
from sqlalchemy.orm import Session, joinedload # Зависимость для работы с сессией базы данных
from sqlalchemy import or_ # Для сложных фильтров в запросах к базе данных
import logging # Для логирования событий и ошибок
from datetime import datetime, timezone # Для работы с датой и временем
import json # Для работы с JSON данными
from modules.auth.ip_geo import get_ip_geo # Утилита для получения геолокации по IP адресу
from modules.auth.user_agent_parser import parse_user_agent # Утилита для парсинга User-Agent строки и определения устройства и браузера

from core.constants import get_department_for_role
from core.database import get_db, Base # Зависимости для получения сессии базы данных и базового класса для моделей
from modules.auth.dependencies import get_current_user_from_cookie # Зависимости для получения текущего пользователя и проверки прав администратора
from modules.auth.models import User, UserRole, Department # Модель пользователя и его роли 
from modules.auth.utils import hash_password # Утилита для хеширования паролей 
from modules.admin.models import AuditLog, LogLevel # Модель для логов аудита и уровни логов
from datetime import datetime, timedelta # Для работы с датой и временем
from core.template_helpers import get_sidebar_context # Утилита для получения контекста сайдбара (например, количество ожидающих пользователей)
from modules.auth import department_service # Service for department operations
from modules.auth.models import Session as SessionModel # Модель для сессий пользователей (для управления активными сессиями при удалении или деактивации пользователя)
from core.logging.actions import (
    log_admin_action,
    log_user_action,
    log_system_event,
    log_security_event
) # Унифицированное логирование действий администратора

logger = logging.getLogger("app")
router = APIRouter(prefix="/admin", tags=["admin"])
templates = Jinja2Templates(directory="templates")

MSK = timezone(timedelta(hours=3)) # Московское время (UTC+3) для корректного отображения времени в админке

# ===================================
# Список пользователей
# ===================================
@router.get("/users", response_class=HTMLResponse)
async def users_list(
    request: Request,
    status: str = None,  # all, active, pending, deactivated, deleted
    search: str = None,
    user: User = Depends(get_current_user_from_cookie),
    db: Session = Depends(get_db)
):
    """Админ-панель: список пользователей"""
    
    # Проверка прав админа
    if user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Access denied")
    
    # Базовый запрос с eager loading для department_rel
    query = db.query(User).options(joinedload(User.department_rel))
    
    # Фильтр по статусу
    if status == "active":
        # ✅ Активные: is_active = True
        query = query.filter(User.is_active == True, User.deleted_at == None)
    
    elif status == "pending":
        # ✅ Ожидают активации: is_active = False И activated_at = NULL (никогда не были активированы)
        query = query.filter(
            User.is_active == False,
            User.activated_at == None,
            User.deleted_at == None
        )
    
    elif status == "deactivated":
        # ✅ Деактивированы: is_active = False И activated_at != NULL (были активны, но отключены)
        query = query.filter(
            User.is_active == False,
            User.activated_at != None,
            User.deleted_at == None
        )
    
    elif status == "deleted":
        # ✅ Удалённые: deleted_at != NULL
        query = query.filter(User.deleted_at != None)
    
    else:
        # ✅ "all" — показываем всех, кроме удалённых
        query = query.filter(User.deleted_at == None)
    
    # Поиск
    if search:
        search_pattern = f"%{search}%"
        query = query.filter(
            or_(
                User.email.ilike(search_pattern),
                User.first_name.ilike(search_pattern),
                User.last_name.ilike(search_pattern)
            )
        )
    
    users = query.order_by(User.created_at.desc()).all()
    
    # ===================================
    # Статистика
    # ===================================
    
    # Всего пользователей (без удалённых)
    total_users = db.query(User).filter(User.deleted_at == None).count()
    
    # Активные
    active_users = db.query(User).filter(
        User.is_active == True,
        User.deleted_at == None
    ).count()
    
    # ✅ Ожидают активации (новые, никогда не активированные)
    pending_users = db.query(User).filter(
        User.is_active == False,
        User.activated_at == None,
        User.deleted_at == None
    ).count()
    
    # ✅ Деактивированы вручную (были активны, но отключены)
    deactivated_users = db.query(User).filter(
        User.is_active == False,
        User.activated_at != None,
        User.deleted_at == None
    ).count()
    
    # Удалённые
    deleted_users = db.query(User).filter(User.deleted_at != None).count()
    
    logger.info({
        "event": "admin_users_list",
        "admin_id": user.id,
        "total_users": total_users,
        "active": active_users,
        "pending": pending_users,
        "deactivated": deactivated_users,
        "deleted": deleted_users
    })
    
    # Get all departments for dropdown
    departments = department_service.get_departments(db)
    
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
            "search_query": search or ""
        }
    )


# ===================================
# Активировать пользователя
# ===================================
@router.post("/users/{user_id}/activate")
async def activate_user(
    user_id: int,
    request: Request,
    admin: User = Depends(get_current_user_from_cookie),
    db: Session = Depends(get_db)
):
    """Активировать пользователя"""
    
    if admin.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Доступ запрещён")
    
    target_user = db.query(User).filter(User.id == user_id).first()
    
    if not target_user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    
    target_user.is_active = True

    # Если пользователь активируется впервые, ставим дату активации
    if target_user.activated_at is None:
        target_user.activated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(target_user)
    
    logger.info({
        "event": "user_activated",
        "admin_id": admin.id,
        "user_id": user_id,
        "email": target_user.email
    })
    
    return JSONResponse({"success": True, "message": "Пользователь активирован"})


# ===================================
# Деактивировать пользователя
# ===================================
@router.post("/users/{user_id}/deactivate")
async def deactivate_user(
    user_id: int,
    request: Request,
    admin: User = Depends(get_current_user_from_cookie),
    db: Session = Depends(get_db)
):
    """Деактивировать пользователя"""
    
    if admin.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Доступ запрещён")
    
    target_user = db.query(User).filter(User.id == user_id).first()
    
    if not target_user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    
    if target_user.id == admin.id:
        raise HTTPException(status_code=400, detail="Нельзя деактивировать самого себя")
    
    target_user.is_active = False
    db.commit()
    db.refresh(target_user)

    logger.info({
        "event": "user_deactivated",
        "admin_id": admin.id,
        "user_id": user_id,
        "email": target_user.email
    })
    
    return JSONResponse({"success": True, "message": "Пользователь деактивирован"})


# ===================================
# Изменить роль пользователя
# ===================================
@router.post("/users/{user_id}/role")
async def change_user_role(
    user_id: int,
    request: Request,
    admin: User = Depends(get_current_user_from_cookie),
    db: Session = Depends(get_db)
):
    """Изменить роль пользователя"""
    
    if admin.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Доступ запрещён")
    
    form = await request.form()
    role = form.get("role")
    
    target_user = db.query(User).filter(User.id == user_id).first()
    
    if not target_user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    
    if target_user.id == admin.id:
        raise HTTPException(status_code=400, detail="Нельзя изменить свою собственную роль")
    
    try:
        target_user.role = UserRole(role)
        from modules.documents.service import DocumentService
        DocumentService.sync_user_access_by_role(target_user, db)
        
        dept_name = get_department_for_role(target_user.role)
        if dept_name:
            department = db.query(Department).filter(Department.name == dept_name).first()
            if department:
                target_user.department_id = department.id

        db.commit()
        db.refresh(target_user)
        
        logger.info({
            "event": "user_role_changed",
            "admin_id": admin.id,
            "user_id": user_id,
            "new_role": role
        })
        
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
    admin: User = Depends(get_current_user_from_cookie),
    db: Session = Depends(get_db)
):
    """Удалить пользователя (мягкое удаление)"""
    
    if admin.role != UserRole.ADMIN:
        return JSONResponse({"success": False, "message": "Доступ запрещён"}, status_code=403)
    
    target_user = db.query(User).filter(User.id == user_id).first()
    
    if not target_user:
        return JSONResponse({"success": False, "message": "Пользователь не найден"}, status_code=404)
    
    if target_user.id == admin.id:
        return JSONResponse({"success": False, "message": "Нельзя удалить самого себя"}, status_code=400)
    
    email = target_user.email
    
    try:
        from modules.auth.models import Session as SessionModel
        
        # ✅ Деактивируем пользователя и ставим дату удаления
        target_user.deleted_at = datetime.now(timezone.utc)
        target_user.is_active = False
        
        # ✅ Помечаем email как удалённый (чтобы можно было зарегистрироваться снова с таким же email)
        import time
        target_user.email = f"deleted_{int(time.time())}_{email}"
        
        # ✅ Отзываем все сессии
        db.query(SessionModel).filter(SessionModel.user_id == user_id).update({
            "is_revoked": True
        })
        
        db.commit()
        
        logger.info({
            "event": "user_soft_deleted",
            "admin_id": admin.id,
            "user_id": user_id,
            "original_email": email
        })
        
        return JSONResponse({"success": True, "message": "Пользователь удалён"})
        
    except Exception as e:
        db.rollback()
        logger.error({
            "event": "user_delete_error",
            "admin_id": admin.id,
            "user_id": user_id,
            "error": str(e)
        }, exc_info=True)
        
        return JSONResponse(
            {"success": False, "message": f"Ошибка: {str(e)}"}, 
            status_code=500
        )
    
# ===================================
# Редактирование пользователя
# ===================================
@router.post("/users/{user_id}/edit")
async def edit_user(
    user_id: int,
    request: Request,
    admin: User = Depends(get_current_user_from_cookie),
    db: Session = Depends(get_db)
):
    """Редактировать данные пользователя"""
    
    if admin.role != UserRole.ADMIN:
        return JSONResponse({"success": False, "message": "Доступ запрещён"}, status_code=403)
    
    target_user = db.query(User).filter(User.id == user_id).first()
    
    if not target_user:
        return JSONResponse({"success": False, "message": "Пользователь не найден"}, status_code=404)
    
    try:
        # ✅ Сохраняем старый отдел ДО изменений
        old_department_id = target_user.department_id
        
        # ✅ Читаем данные из формы
        form = await request.form()
        
        # Обновляем только переданные поля
        if form.get("first_name") is not None:
            target_user.first_name = form.get("first_name").strip() or None
        
        if form.get("last_name") is not None:
            target_user.last_name = form.get("last_name").strip() or None
        
        if form.get("middle_name") is not None:
            target_user.middle_name = form.get("middle_name").strip() or None
        
        if form.get("email"):
            new_email = form.get("email").lower().strip()

            # Проверяем, не занят ли email
            existing = db.query(User).filter(
                User.email == new_email,
                User.id != user_id
            ).first()
            if existing:
                return JSONResponse(
                    {"success": False, "message": "Email уже используется другим пользователем"}, 
                    status_code=400
                )
            target_user.email = new_email
        
        if form.get("phone_number") is not None:
            target_user.phone_number = form.get("phone_number").strip() or None
        
        if form.get("department_id") is not None:
            department_id_str = form.get("department_id").strip()
            if department_id_str:
                try:
                    target_user.department_id = int(department_id_str)
                except ValueError:
                    return JSONResponse(
                        {"success": False, "message": "Некорректный ID отдела"}, 
                        status_code=400
                    )
            else:
                target_user.department_id = None
        
        if form.get("position") is not None:
            target_user.position = form.get("position").strip() or None
        
        if form.get("location") is not None:
            target_user.location = form.get("location").strip() or None

        if form.get("role"):
            new_role = form.get("role")
            try:
                target_user.role = UserRole(new_role)
            except ValueError:
                return JSONResponse(
                    {"success": False, "message": f"Недопустимая роль: {new_role}"},
                    status_code=400
                )
        
        # ✅ Сначала коммитим основные изменения
        db.commit()
        db.refresh(target_user)

        # ✅ Если отдел изменился - синхронизируем доступы к объектам
        if old_department_id != target_user.department_id:
            from modules.objects.service import ObjectService
            ObjectService.sync_user_access_by_department(target_user, db)
            # Дополнительный коммит не нужен, sync_user_access_by_department уже коммитит
        
        logger.info({
            "event": "user_edited",
            "admin_id": admin.id,
            "user_id": user_id,
            "email": target_user.email,
            "department_changed": old_department_id != target_user.department_id
        })
        
        return JSONResponse({
            "success": True, 
            "message": "Данные пользователя обновлены",
            "user": {
                "id": target_user.id,
                "first_name": target_user.first_name,
                "last_name": target_user.last_name,
                "middle_name": target_user.middle_name,
                "email": target_user.email,
                "phone_number": target_user.phone_number,
                "department_id": target_user.department_id,
                "position": target_user.position,
                "location": target_user.location
            }
        })
        
    except Exception as e:
        db.rollback()
        logger.error({
            "event": "user_edit_error",
            "admin_id": admin.id,
            "user_id": user_id,
            "error": str(e)
        }, exc_info=True)
        
        return JSONResponse(
            {"success": False, "message": f"Ошибка: {str(e)}"}, 
            status_code=500
        )
    
# ===================================
# Сбросить пароль пользователя
# ===================================
@router.post("/users/{user_id}/reset-password")
async def reset_user_password(
    user_id: int,
    request: Request,
    admin: User = Depends(get_current_user_from_cookie),
    db: Session = Depends(get_db)
):
    """Сбросить пароль пользователя (только для админа)"""
    
    if admin.role != UserRole.ADMIN:
        return JSONResponse({"success": False, "message": "Доступ запрещён"}, status_code=403)
    
    target_user = db.query(User).filter(User.id == user_id).first()
    
    if not target_user:
        return JSONResponse({"success": False, "message": "Пользователь не найден"}, status_code=404)
    
    try:
        # ✅ Читаем новый пароль из формы
        form = await request.form()
        new_password = form.get("new_password")
        
        if not new_password or len(new_password) < 6:
            return JSONResponse(
                {"success": False, "message": "Пароль должен содержать минимум 6 символов"}, 
                status_code=400
            )
        
        # ✅ Хешируем и сохраняем новый пароль
        target_user.hashed_password = hash_password(new_password)
        
        # ✅ Отзываем все активные сессии пользователя (заставляем перелогиниться)
        from modules.auth.models import Session as SessionModel
        db.query(SessionModel).filter(
            SessionModel.user_id == user_id,
            SessionModel.is_revoked == False
        ).update({"is_revoked": True}, synchronize_session=False)
        
        db.commit()
        
        logger.info({
            "event": "user_password_reset_by_admin",
            "admin_id": admin.id,
            "user_id": user_id,
            "email": target_user.email
        })
        
        return JSONResponse({
            "success": True, 
            "message": f"Пароль пользователя {target_user.email} успешно изменён"
        })
        
    except Exception as e:
        db.rollback()
        logger.error({
            "event": "user_password_reset_error",
            "admin_id": admin.id,
            "user_id": user_id,
            "error": str(e)
        }, exc_info=True)
        
        return JSONResponse(
            {"success": False, "message": f"Ошибка: {str(e)}"}, 
            status_code=500
        )
    
# ===================================
# Логи аудита (Admin)
# ===================================
@router.get("/logs", response_class=HTMLResponse)
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
    user: User = Depends(get_current_user_from_cookie),
    db: Session = Depends(get_db)
):
    """Просмотр логов аудита (только для админов)"""
    
    if user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Access denied")
    
    # Базовый запрос
    query = db.query(AuditLog).filter(AuditLog.is_archived == False)
    
    # Фильтр по уровню
    if level:
        query = query.filter(AuditLog.level == level)
    
    # Фильтр по событию
    if event:
        query = query.filter(AuditLog.event == event)
    
    # Фильтр по пользователю
    if user_id:
        query = query.filter(AuditLog.user_id == user_id)
    
    # Фильтр по HTTP методу
    if http_method:
        query = query.filter(AuditLog.http_method == http_method)
    
    # Фильтр по дате
    if date_from:
        try:
            date_from_dt = datetime.strptime(date_from, "%Y-%m-%d")
            query = query.filter(AuditLog.created_at >= date_from_dt)
        except:
            pass
    
    if date_to:
        try:
            date_to_dt = datetime.strptime(date_to, "%Y-%m-%d") + timedelta(days=1)
            query = query.filter(AuditLog.created_at < date_to_dt)
        except:
            pass
    
    # Поиск
    if search:
        search_pattern = f"%{search}%"
        query = query.filter(
            or_(
                AuditLog.event.ilike(search_pattern),
                AuditLog.message.ilike(search_pattern),
                AuditLog.user_email.ilike(search_pattern),
                AuditLog.ip_address.ilike(search_pattern),
                AuditLog.request_id.ilike(search_pattern),
                AuditLog.http_path.ilike(search_pattern)
            )
        )
    
    # Подсчёт общего количества
    total_logs = query.count()
    
    # Пагинация
    offset = (page - 1) * per_page
    logs = query.order_by(AuditLog.created_at.desc()).limit(per_page).offset(offset).all()
    
    # Парсим extra_data для каждого лога
    for log in logs:
        if log.extra_data:
            try:
                log.extra_data_parsed = json.loads(log.extra_data)
            except:
                log.extra_data_parsed = {}
        else:
            log.extra_data_parsed = {}
    
    # Статистика
    total_pages = (total_logs + per_page - 1) // per_page
    
    # Получаем уникальные события для фильтра (топ-50)
    unique_events = db.query(AuditLog.event).distinct().order_by(AuditLog.event).limit(50).all()
    unique_events = [e[0] for e in unique_events]
    
    # Получаем уникальные HTTP методы
    unique_methods = db.query(AuditLog.http_method).filter(AuditLog.http_method != None).distinct().all()
    unique_methods = [m[0] for m in unique_methods if m[0]]
    
    logger.info({
        "event": "admin_logs_viewed",
        "user_id": user.id,
        "filters": {
            "level": level,
            "event": event,
            "user_id": user_id,
            "search": search,
            "http_method": http_method
        }
    })
    
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
            "log_levels": [l.value for l in LogLevel],
            **sidebar_context
        }
    )


# ===================================
# API: Детали лога (JSON)
# ===================================
@router.get("/logs/{log_id}/detail")
async def log_detail_api(
    log_id: int,
    user: User = Depends(get_current_user_from_cookie),
    db: Session = Depends(get_db)
):
    """Получить детали лога по ID (JSON)"""
    
    if user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Access denied")
    
    log = db.query(AuditLog).filter(AuditLog.id == log_id).first()
    
    if not log:
        raise HTTPException(status_code=404, detail="Log not found")
    
    # Парсим extra_data
    extra_data = None
    if log.extra_data:
        try:
            extra_data = json.loads(log.extra_data)
        except:
            extra_data = {"raw": log.extra_data}
    
    # Получаем User-Agent
    user_agent_str = None
    if log.user_agent:
        user_agent_str = log.user_agent.user_agent
    
    return {
        "id": log.id,
        "created_at": log.created_at.strftime('%Y-%m-%d %H:%M:%S'),
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
        "expires_at": log.expires_at.strftime('%Y-%m-%d %H:%M:%S') if log.expires_at else None
    }


# ===================================
# Экспорт логов в CSV
# ===================================
@router.get("/logs/export")
async def logs_export_csv(
    level: str = None,
    event: str = None,
    user_id: int = None,
    date_from: str = None,
    date_to: str = None,
    search: str = None,
    http_method: str = None,
    user: User = Depends(get_current_user_from_cookie),
    db: Session = Depends(get_db)
):
    """Экспорт логов в CSV"""
    
    if user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Access denied")
    
    # Применяем те же фильтры, что и в logs_page
    query = db.query(AuditLog).filter(AuditLog.is_archived == False)
    
    if level:
        query = query.filter(AuditLog.level == level)
    
    if event:
        query = query.filter(AuditLog.event == event)
    
    if user_id:
        query = query.filter(AuditLog.user_id == user_id)
    
    if http_method:
        query = query.filter(AuditLog.http_method == http_method)
    
    if date_from:
        try:
            date_from_dt = datetime.strptime(date_from, "%Y-%m-%d")
            query = query.filter(AuditLog.created_at >= date_from_dt)
        except:
            pass
    
    if date_to:
        try:
            date_to_dt = datetime.strptime(date_to, "%Y-%m-%d") + timedelta(days=1)
            query = query.filter(AuditLog.created_at < date_to_dt)
        except:
            pass
    
    if search:
        search_pattern = f"%{search}%"
        query = query.filter(
            or_(
                AuditLog.event.ilike(search_pattern),
                AuditLog.message.ilike(search_pattern),
                AuditLog.user_email.ilike(search_pattern),
                AuditLog.ip_address.ilike(search_pattern),
                AuditLog.request_id.ilike(search_pattern),
                AuditLog.http_path.ilike(search_pattern)
            )
        )
    
    # Ограничиваем экспорт (максимум 10000 записей)
    logs = query.order_by(AuditLog.created_at.desc()).limit(10000).all()
    
    # Создаём CSV
    output = StringIO()
    writer = csv.writer(output)
    
    # Заголовки
    writer.writerow([
        'ID',
        'Время',
        'Уровень',
        'Событие',
        'Request ID',
        'HTTP Метод',
        'HTTP Путь',
        'HTTP Статус',
        'Длительность (мс)',
        'User ID',
        'Email',
        'IP-адрес',
        'Сообщение',
        'Extra Data'
    ])
    
    # Данные
    for log in logs:
        writer.writerow([
            log.id,
            log.created_at.strftime('%Y-%m-%d %H:%M:%S'),
            log.level.value,
            log.event,
            log.request_id or '',
            log.http_method or '',
            log.http_path or '',
            log.http_status or '',
            log.duration_ms or '',
            log.user_id or '',
            log.user_email or '',
            log.ip_address or '',
            log.message or '',
            log.extra_data or ''
        ])
    
    # Логируем экспорт
    log_admin_action(
        event="logs_exported_csv",
        admin=user,
        extra={
            "total_records": len(logs)
        }
    )
    
    output.seek(0)
    
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={
            "Content-Disposition": f"attachment; filename=logs_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        }
    )


# ===================================
# Экспорт логов в JSON
# ===================================
@router.get("/logs/export/json")
async def logs_export_json(
    level: str = None,
    event: str = None,
    user_id: int = None,
    date_from: str = None,
    date_to: str = None,
    search: str = None,
    http_method: str = None,
    user: User = Depends(get_current_user_from_cookie),
    db: Session = Depends(get_db)
):
    """Экспорт логов в JSON"""
    
    if user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Доступ запрещён")
    
    # Применяем те же фильтры
    query = db.query(AuditLog).filter(AuditLog.is_archived == False)
    
    if level:
        query = query.filter(AuditLog.level == level)
    
    if event:
        query = query.filter(AuditLog.event == event)
    
    if user_id:
        query = query.filter(AuditLog.user_id == user_id)
    
    if http_method:
        query = query.filter(AuditLog.http_method == http_method)
    
    if date_from:
        try:
            date_from_dt = datetime.strptime(date_from, "%Y-%m-%d")
            query = query.filter(AuditLog.created_at >= date_from_dt)
        except:
            pass
    
    if date_to:
        try:
            date_to_dt = datetime.strptime(date_to, "%Y-%m-%d") + timedelta(days=1)
            query = query.filter(AuditLog.created_at < date_to_dt)
        except:
            pass
    
    if search:
        search_pattern = f"%{search}%"
        query = query.filter(
            or_(
                AuditLog.event.ilike(search_pattern),
                AuditLog.message.ilike(search_pattern),
                AuditLog.user_email.ilike(search_pattern),
                AuditLog.ip_address.ilike(search_pattern),
                AuditLog.request_id.ilike(search_pattern),
                AuditLog.http_path.ilike(search_pattern)
            )
        )
    
    # Ограничиваем экспорт
    logs = query.order_by(AuditLog.created_at.desc()).limit(10000).all()
    
    # Формируем JSON
    result = []
    for log in logs:
        extra_data = None
        if log.extra_data:
            try:
                extra_data = json.loads(log.extra_data)
            except:
                extra_data = log.extra_data
        
        result.append({
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
            "extra_data": extra_data
        })
    
    # Логируем экспорт
    log_admin_action(
        event="logs_exported_json",
        admin=user,
        extra={
            "total_records": len(result)
        }
    )
    
    return StreamingResponse(
        iter([json.dumps(result, ensure_ascii=False, indent=2)]),
        media_type="application/json",
        headers={
            "Content-Disposition": f"attachment; filename=logs_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        }
    )


# ===================================
# Статистика логов (Dashboard Widget)
# ===================================
@router.get("/logs/stats")
async def logs_stats(
    user: User = Depends(get_current_user_from_cookie),
    db: Session = Depends(get_db)
):
    """Получить статистику логов за последние 24 часа"""
    
    if user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Доступ запрещён")
    
    # За последние 24 часа
    since = datetime.utcnow() - timedelta(hours=24)
    
    # Общее количество
    total = db.query(AuditLog).filter(
        AuditLog.created_at >= since,
        AuditLog.is_archived == False
    ).count()
    
    # По уровням
    errors = db.query(AuditLog).filter(
        AuditLog.created_at >= since,
        AuditLog.level == LogLevel.ERROR,
        AuditLog.is_archived == False
    ).count()
    
    warnings = db.query(AuditLog).filter(
        AuditLog.created_at >= since,
        AuditLog.level == LogLevel.WARNING,
        AuditLog.is_archived == False
    ).count()
    
    # HTTP запросы
    http_requests = db.query(AuditLog).filter(
        AuditLog.created_at >= since,
        AuditLog.event == 'http_request',
        AuditLog.is_archived == False
    ).count()
    
    # Ошибки HTTP (4xx, 5xx)
    http_errors = db.query(AuditLog).filter(
        AuditLog.created_at >= since,
        AuditLog.http_status >= 400,
        AuditLog.is_archived == False
    ).count()
    
    return {
        "total": total,
        "errors": errors,
        "warnings": warnings,
        "http_requests": http_requests,
        "http_errors": http_errors,
        "period": "24h"
    }


# ===================================
# Department Management Endpoints
# ===================================
@router.get("/departments")
async def get_departments_list(
    admin: User = Depends(get_current_user_from_cookie),
    db: Session = Depends(get_db)
):
    """Get list of all departments"""
    if admin.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Доступ запрещён")
    
    departments = department_service.get_departments(db)
    return {"departments": [{"id": d.id, "name": d.name, "description": d.description, "created_at": d.created_at, "updated_at": d.updated_at} for d in departments]}

# ===================================
# Создание нового отдела
# ===================================
@router.post("/departments")
async def create_department(
    request: Request,
    admin: User = Depends(get_current_user_from_cookie),
    db: Session = Depends(get_db)
):
    """Create a new department"""
    if admin.role != UserRole.ADMIN:
        return JSONResponse({"success": False, "message": "Доступ запрещён"}, status_code=403)
    
    try:
        form = await request.form()
        name = form.get("name", "").strip()
        description = form.get("description", "").strip()
        
        if not name:
            return JSONResponse({"success": False, "message": "Название отдела обязательно"}, status_code=400)
        
        from modules.auth.schemas import DepartmentCreate
        dept_data = DepartmentCreate(name=name, description=description or None)
        department = department_service.create_department(db, dept_data)
        
        log_admin_action(
            event="department_created",
            admin=admin,
            target_user=None,
            request=request,
            extra={
                "department_id": department.id,
                "department_name": department.name
            }
        )
        
        return JSONResponse({
            "success": True,
            "message": "Отдел успешно создан",
            "department": {
                "id": department.id,
                "name": department.name,
                "description": department.description
            }
        })
    except HTTPException as e:
        return JSONResponse({"success": False, "message": e.detail}, status_code=e.status_code)
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
    admin: User = Depends(get_current_user_from_cookie),
    db: Session = Depends(get_db)
):
    """Update a department"""
    if admin.role != UserRole.ADMIN:
        return JSONResponse({"success": False, "message": "Доступ запрещён"}, status_code=403)
    
    try:
        form = await request.form()
        name = form.get("name", "").strip() or None
        description = form.get("description", "").strip() or None
        
        from modules.auth.schemas import DepartmentUpdate
        dept_data = DepartmentUpdate(name=name, description=description)
        department = department_service.update_department(db, department_id, dept_data)
        
        if not department:
            return JSONResponse({"success": False, "message": "Отдел не найден"}, status_code=404)
        
        log_admin_action(
            event="department_updated",
            admin=admin,
            target_user=None,
            request=request,
            extra={
                "department_id": department.id,
                "department_name": department.name
            }
        )
        
        return JSONResponse({
            "success": True,
            "message": "Отдел успешно обновлён",
            "department": {
                "id": department.id,
                "name": department.name,
                "description": department.description
            }
        })
    except HTTPException as e:
        return JSONResponse({"success": False, "message": e.detail}, status_code=e.status_code)
    except Exception as e:
        logger.error(f"Ошибка обновления отдела: {str(e)}", exc_info=True)
        return JSONResponse({"success": False, "message": str(e)}, status_code=500)

# ===================================
# Удаление отдела
# ===================================
@router.delete("/departments/{department_id}")
async def delete_department(
    department_id: int,
    admin: User = Depends(get_current_user_from_cookie),
    db: Session = Depends(get_db)
):
    """Delete a department"""
    if admin.role != UserRole.ADMIN:
        return JSONResponse({"success": False, "message": "Доступ запрещён"}, status_code=403)
    
    try:
        success = department_service.delete_department(db, department_id)
        
        if not success:
            return JSONResponse({"success": False, "message": "Отдел не найден"}, status_code=404)
        
        log_admin_action(
            event="department_deleted",
            admin=admin,
            extra={"department_id": department_id}
        )
        
        return JSONResponse({"success": True, "message": "Отдел успешно удалён"})
    except HTTPException as e:
        return JSONResponse({"success": False, "message": e.detail}, status_code=e.status_code)
    except Exception as e:
        logger.error(f"Ошибка удаления отдела: {str(e)}", exc_info=True)
        return JSONResponse({"success": False, "message": str(e)}, status_code=500)
    
# ===================================
# Просмотр сессий пользователя
# ===================================
@router.get("/users/{user_id}/sessions", response_class=HTMLResponse)
async def user_sessions_page(
    user_id: int,
    request: Request,
    page: int = 1, # номер страницы для пагинации
    per_page: int = 20, # количество сессий на странице
    admin: User = Depends(get_current_user_from_cookie),
    db: Session = Depends(get_db)
):
    # Только админ
    if admin.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Доступ запрещён")

    # Проверяем, что пользователь существует
    target_user = db.query(User).filter(User.id == user_id).first()
    if not target_user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")

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
        s.ua = parse_user_agent(s.user_agent) if s.user_agent else {"device": "_", "browser": "_"}
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
            **sidebar_context
        }
    )


# ===================================
# Отозвать сессию пользователя
# ===================================
@router.post("/sessions/{session_id}/revoke")
async def revoke_session(
    session_id: int,
    request: Request,
    admin: User = Depends(get_current_user_from_cookie),
    db: Session = Depends(get_db)
):
    # Только админ
    if admin.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Доступ запрещён")

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
        extra={
            "session_id": session.id,
            "ip": session.ip_address
        }
    )

    # Возвращаемся обратно на страницу сессий
    return JSONResponse({
        "success": True,
        "message": "Сессия успешно завершена"
    })


# ===================================
# Завершить все сессии пользователя
# ===================================
@router.post("/users/{user_id}/sessions/revoke-all")
async def revoke_all_sessions(
    user_id: int,
    request: Request,
    admin: User = Depends(get_current_user_from_cookie),
    db: Session = Depends(get_db)
):
    # Только админ
    if admin.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Доступ запрещён")

    # Проверяем, что пользователь существует
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")

    # Отзываем все активные сессии
    updated = db.query(SessionModel).filter(
        SessionModel.user_id == user_id,
        SessionModel.is_revoked == False
    ).update({
        SessionModel.is_revoked: True,
        SessionModel.expires_at: datetime.now(MSK)
    }, synchronize_session=False)

    db.commit()

    # Логируем
    log_admin_action(
        event="revoke_all_sessions",
        admin=admin,
        target_user=user,
        request=request,
        extra={
            "revoked_count": updated
        }
    )

    return JSONResponse({
        "success": True,
        "message": f"Все активные сессии пользователя ({updated}) завершены"
    })

# ===================================
# Завершить все сессии пользователя, кроме текущей
# ===================================
@router.post("/users/{user_id}/sessions/revoke-others")
async def revoke_other_sessions(
    user_id: int,
    request: Request,
    admin: User = Depends(get_current_user_from_cookie),
    db: Session = Depends(get_db)
):
    if admin.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Доступ запрещён")
    
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
            SessionModel.is_revoked == False
        )
        .update({"is_revoked": True}, synchronize_session=False)
    )

    db.commit()

    # Логируем
    log_admin_action(
        event="revoke_other_sessions",
        admin=admin,
        request=request,
        extra={
            "target_user": target_user,
            "revoked_count": updated
        }
    )

    return {
        "success": True,
        "message": f"Завершено сессий: {updated}"
    }





# @router.get("/test-logs")
# async def test_logs(request: Request):
#     user = None

#     log_admin_action("admin_test_event", admin=user, request=request)
#     log_user_action("user_test_event", user=user, request=request)
#     log_system_event("system_test_event", {"info": "system ok"})
#     await log_security_event("security_test_event", request=request)

#     return {"status": "ok"}

