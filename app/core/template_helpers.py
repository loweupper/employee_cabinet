from sqlalchemy.orm import Session
from modules.auth.models import User

def get_sidebar_context(user: User, db: Session) -> dict:
    """
    Возвращает контекст для sidebar (количество ожидающих пользователей и т.д.)
    """
    context = {
        "pending_users_count": 0
    }
    
    # Только для админов показываем badge
    if user.role.value == "admin":
        context["pending_users_count"] = db.query(User).filter(
            User.is_active == False,
            User.deleted_at == None
        ).count()
    
    return context