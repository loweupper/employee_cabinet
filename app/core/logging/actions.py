import logging
from typing import Optional, Dict, Any
from fastapi import Request
from modules.auth.models import User
from core.logging.geoip_resolver import resolve_geo
from core.database import SessionLocal
from modules.monitoring.service_alerts import AlertService
from modules.monitoring.models import AlertSeverity, AlertType
from core.config import APP_TIMEZONE, now, format_timestamp, TIMEZONE_NAME

# ============================
#  Единые логгеры
# ============================
app_logger = logging.getLogger("app")
security_logger = logging.getLogger("security")
system_logger = logging.getLogger("system")

# ============================
#  Автоматическая категоризация
# ============================
CATEGORY_KEYWORDS = {
    "security": {
        "unauthorized", "forbidden", "denied", "bruteforce", "failed_login",
        "login_failure", "xss", "sql_injection", "csrf", "security_alert",
        "token_mismatch", "suspicious", "blocked_ip", "invalid_token"
    },
    "admin": {
        "revoke", "delete", "update_role", "disable_user", "enable_user",
        "reset_password", "create_user", "modify_permissions", "admin_action",
        "role_changed", "user_deleted", "user_created"
    },
    "system": {
        "cron", "scheduler", "cleanup", "system_event", "background_task",
        "maintenance", "startup", "shutdown", "health_check", "migration"
    }
}

def categorize_event(event: str) -> str:
    """Определяет категорию события по ключевым словам"""
    event_lower = event.lower()
    
    for category, keywords in CATEGORY_KEYWORDS.items():
        if any(k in event_lower for k in keywords):
            return category
    
    return "user"

# ============================
#  Базовая функция сбора данных
# ============================
def _build_log_data(
    event: str,
    actor: Optional[User] = None,
    target_user: Optional[User] = None,
    request: Optional[Request] = None,
    extra: Optional[Dict] = None
) -> Dict[str, Any]:
    """Единый строитель данных для всех логов"""
    
    # Request ID
    request_id = None
    if request and hasattr(request, "state") and hasattr(request.state, "request_id"):
        request_id = request.state.request_id
    
    # ✅ Используем нашу функцию now() из config
    current_time = now()
    
    # Базовые данные
    data = {
        "event": event,
        "category": categorize_event(event),
        "timestamp": format_timestamp(current_time, format="iso"),     # ISO с таймзоной
        "timestamp_display": format_timestamp(current_time, format="msk"),  # для отображения
        "timestamp_utc": format_timestamp(current_time, format="utc"),      # для сортировки
        "timezone": TIMEZONE_NAME,
        "request_id": request_id,
    }
    
    # IP и User-Agent
    if request:
        data["ip"] = request.client.host if request.client else None
        data["user_agent"] = request.headers.get("user-agent")
    
    # Актёр (кто совершает действие)
    if actor:
        data.update({
            "actor_id": actor.id,
            "actor_email": actor.email,
            "actor_role": actor.role.value if hasattr(actor.role, 'value') else actor.role,
        })
    else:
        data["actor_id"] = None
    
    # Целевой пользователь (над кем действие)
    if target_user:
        data.update({
            "target_user_id": target_user.id,
            "target_user_email": target_user.email,
            "target_user_role": target_user.role.value if hasattr(target_user.role, 'value') else target_user.role,
            "target_user_first_name": target_user.first_name,
        })
    
    # Дополнительные данные
    if extra:
        for k, v in extra.items():
            if k not in data:
                data[k] = v
    
    return data

# ============================
#  ЕДИНАЯ ФУНКЦИЯ ДЛЯ ВСЕХ СОБЫТИЙ
# ============================
async def log_event(
    event: str,
    actor: Optional[User] = None,
    target_user: Optional[User] = None,
    request: Optional[Request] = None,
    level: str = "INFO",
    create_alert: bool = False,
    **extra
):
    """
    Универсальная функция логирования
    
    Примеры:
    await log_event("user_login", actor=user, request=request)
    await log_event("admin_delete_user", actor=admin, target_user=user, request=request)
    await log_event("failed_login", level="WARNING", create_alert=True, email="test@mail.com")
    """
    
    # Собираем данные
    data = _build_log_data(event, actor, target_user, request, extra)
    
    # Определяем логгер и уровень
    category = data["category"]
    
    # Гео-данные только для security
    if category == "security" or create_alert:
        ip = data.get("ip")
        if ip:
            geo = await resolve_geo(ip)
            data.update(geo)
    
    # Логируем в соответствующий логгер
    if category == "security" or level == "WARNING":
        security_logger.warning(data)
    elif category == "system":
        system_logger.info(data)
    else:
        app_logger.info(data)
    
    # Создаём алерт в БД если нужно
    if create_alert or category == "security":
        db = SessionLocal()
        try:
            AlertService.create_alert(
                db=db,
                severity=AlertSeverity.HIGH if level == "WARNING" else AlertSeverity.MEDIUM,
                type=AlertType.SECURITY_EVENT,
                message=event,
                user_id=actor.id if actor else None,
                ip_address=data.get("ip"),
                details=data
            )
        finally:
            db.close()

# ============================
#  Функции-обёртки для обратной совместимости
# ============================

async def log_security_event(event: str, request=None, user=None, extra=None):
    await log_event(
        event=event,
        actor=user,
        request=request,
        level="WARNING",
        create_alert=True,
        **(extra or {})
    )

def log_admin_action(event: str, admin: User | None, request: Request, extra: dict | None = None):
    import asyncio
    asyncio.create_task(log_event(
        event=event,
        actor=admin,
        request=request,
        **(extra or {})
    ))

def log_user_action(event: str, user: User | None, request: Request, extra: dict | None = None):
    import asyncio
    asyncio.create_task(log_event(
        event=event,
        actor=user,
        request=request,
        **(extra or {})
    ))

def log_system_event(event: str, extra: dict | None = None):
    import asyncio
    asyncio.create_task(log_event(
        event=event,
        level="INFO",
        **(extra or {})
    ))