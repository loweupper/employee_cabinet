from sqlalchemy.orm import Session
from modules.auth.models import User
from modules.monitoring.models import Alert

def get_sidebar_context(user: User, db: Session) -> dict:
    """
    Возвращает контекст для sidebar (количество ожидающих пользователей и т.д.)
    """
    context = {
        "pending_users_count": 0,
        "active_alerts_count": 0
    }
    
    # Только для админов показываем badge
    if user.role.value == "admin":
        context["pending_users_count"] = db.query(User).filter(
        User.is_active == False,
        User.activated_at == None,
        User.deleted_at == None
    ).count()
        
        # Активные алерты  (не разрешённые)
        context["active_alerts_count"] = db.query(Alert).filter(
            Alert.resolved == False
        ).count()

    
    return context