from sqlalchemy.orm import Session

from core.constants import UserRole
from modules.auth.models import User
from modules.auth.service import AuthService
from modules.monitoring.models import Alert


def get_sidebar_context(user: User, db: Session) -> dict:
    """
    Возвращает контекст для sidebar (количество ожидающих пользователей и т.д.)
    """
    context = {
        "pending_users_count": 0,
        "active_alerts_count": 0,
        "can_access_safety": False,
    }

    context["can_access_safety"] = user.role in (
        UserRole.ADMIN,
        UserRole.SAFETY,
    ) or AuthService.user_has_permission(user, "can_access_safety", db)

    # Только для админов показываем badge
    if user.role.value == "admin":
        context["pending_users_count"] = (
            db.query(User)
            .filter(
                User.is_active.is_(False),
                User.activated_at.is_(None),
                User.deleted_at.is_(None),
            )
            .count()
        )

        # Активные алерты  (не разрешённые)
        context["active_alerts_count"] = (
            db.query(Alert)
            .filter(
                Alert.resolved.is_(False),
            )
            .count()
        )

    return context
