import logging 
from typing import Optional, Dict 
from fastapi import Request 
from modules.auth.models import User
from core.logging.geoip_resolver import resolve_geo

from core.database import SessionLocal
from modules.monitoring.service_alerts import AlertService
from modules.monitoring.models import AlertSeverity, AlertType


# Логеры (уже настроены в handlers.py)
app_logger = logging.getLogger("app") # для общих событий например, "user_logged_in", "file_uploaded"
audit_logger = logging.getLogger("audit") # для событий, связанных с действиями пользователей и админов, например, "admin_deleted_user", "user_changed_password"
security_logger = logging.getLogger("security") # для событий безопасности, например, "failed_login", "xss_attempt", "sql_injection"
system_logger = logging.getLogger("system") # для системных событий, например, "cron_job_started", "maintenance_mode_enabled"


# ============================
#  Автоматическая категоризация
# ============================

SECURITY_KEYWORDS = {
    "unauthorized", "forbidden", "denied",
    "bruteforce", "failed_login", "login_failure",
    "xss", "sql_injection", "csrf", "security_alert",
    "token_mismatch", "suspicious", "blocked_ip"
}

ADMIN_KEYWORDS = {
    "revoke", "delete", "update_role", "disable_user",
    "enable_user", "reset_password", "create_user",
    "modify_permissions", "admin_action"
}

USER_KEYWORDS = {
    "profile_update", "user_action", "change_password",
    "upload_file", "download_file", "login", "logout"
}

SYSTEM_KEYWORDS = {
    "cron", "scheduler", "cleanup", "system_event",
    "background_task", "maintenance"
}


def categorize_event(event: str) -> str:
    event_lower = event.lower()

    if any(k in event_lower for k in SECURITY_KEYWORDS):
        return "security"

    if any(k in event_lower for k in ADMIN_KEYWORDS):
        return "admin"

    if any(k in event_lower for k in USER_KEYWORDS):
        return "user"

    if any(k in event_lower for k in SYSTEM_KEYWORDS):
        return "system"

    return "app"  # fallback
    


# ============================
#  Базовая функция логирования
# ============================

def _build_log_data(
    event: str,
    actor: Optional[User],
    target_user: Optional[User],
    request: Optional[Request],
    extra: Optional[Dict]
):
    # Безопасный request_id
    request_id = None
    if request and hasattr(request, "state") and hasattr(request.state, "request_id"):
        request_id = request.state.request_id

    data = {
        "event": event,
        "user_id": actor.id if actor else None,
        "ip": request.client.host if request and request.client else None,
        "user_agent": request.headers.get("user-agent") if request else None,
        "request_id": request_id,
    }

    if actor:
        data.update({
            "actor_id": actor.id,
            "actor_role": actor.role.value,
            "actor_email": actor.email,
        })

    if target_user:
        data.update({
            "target_user_id": target_user.id,
            "target_user_role": target_user.role.value,
            "target_user_first_name": target_user.first_name,
            "target_user_email": target_user.email,
        })

    if request:
        data.update({
            "ip": request.client.host if request.client else None,
            "user_agent": request.headers.get("User-Agent"),
            "request_id": request_id,
        })

    if extra:
        data.update(extra)

    return data



# ============================
#  Логирование действий админа
# ============================

def log_admin_action(event: str, admin: User | None, request: Request, extra: dict | None = None):
    data = {
        "event": event,
        "actor_id": admin.id if admin else None,
        "actor_role": admin.role.value if admin else None,
        "ip": request.client.host if request.client else None,
        "target_user": extra.get("target_user") if extra else None,
        "user_agent": request.headers.get("user-agent"),
    }
    if extra:
        data.update(extra)
    audit_logger.info(data)




# ============================
#  Логирование действий пользователя
# ============================

def log_user_action(event: str, user: User | None, request: Request, extra: dict | None = None):
    data = {
        "event": event,
        "user_id": user.id if user else None,
        "ip": request.client.host if request.client else None,
        "user_agent": request.headers.get("user-agent"),
    }
    if extra:
        data.update(extra)
    audit_logger.info(data)




# ============================
#  Логирование системных событий
# ============================

def log_system_event(event: str, extra: dict | None = None):
    data = {"event": event}
    if extra:
        data.update(extra)
    system_logger.info(data)



# ============================
#  Логирование событий безопасности
# ============================
async def log_security_event(event: str, request=None, user=None, extra=None):
    ip = request.client.host if request else None
    geo = await resolve_geo(ip) if ip else {}

    data = _build_log_data(event, user, None, request, extra)
    data.update(geo)

    security_logger.warning(data)

    # Создаём alert в БД
    db = SessionLocal()
    AlertService.create_alert(
        db=db,
        severity=AlertSeverity.HIGH,
        type=AlertType.SECURITY_EVENT,
        message=event,
        user_id=user.id if user else None,
        ip_address=ip,
        details=data
    )
    db.close()




