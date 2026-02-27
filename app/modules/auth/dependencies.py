from fastapi import Depends, HTTPException, status, Request
from fastapi.security import HTTPBearer
from sqlalchemy.orm import Session
from jose import JWTError
import logging

from core.database import get_db
from core.config import settings
from core.constants import UserRole  # ✅ импорт Enum
from modules.auth.models import User
from modules.auth.utils import decode_token, get_error_id

logger = logging.getLogger("app")

# ===================================
# HTTP Bearer схема для JWT
# ===================================
security = HTTPBearer()


# ===================================
# Зависимость для получения текущего пользователя из JWT (API)
# ===================================
async def get_current_user(
    credentials = Depends(security),
    db: Session = Depends(get_db)
) -> User:
    """
    Получить текущего пользователя из JWT токена (для API endpoints).
    
    Raises:
        HTTPException 401: если токен невалиден или пользователь не найден
    """
    token = credentials.credentials
    error_id = get_error_id()
    
    try:
        payload = decode_token(token)
        user_id: str = payload.get("sub")
        
        if user_id is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Неверный токен: отсутствует ID пользователя",
                headers={"WWW-Authenticate": "Bearer"},
            )
    except JWTError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Неверный токен: {str(e)}",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # Получаем пользователя из БД
    user = db.query(User).filter(User.id == int(user_id)).first()
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Пользователь не найден",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Пользователь неактивен. Обратитесь к администратору."
        )
    
    return user


# ===================================
# Зависимость для получения текущего пользователя из Cookie (WEB)
# ===================================
async def get_current_user_from_cookie(
    request: Request,
    db: Session = Depends(get_db)
) -> User:
    """
    Получить текущего пользователя из Cookie (для веб-страниц).
    
    Raises:
        HTTPException 401: если токен невалиден или пользователь не найден
    """
    # Получаем токен из cookie
    token = request.cookies.get("access_token")
    
    if not token:
        logger.warning({
            "event": "unauthorized_access",
            "path": str(request.url.path),
            "client_ip": request.client.host if request.client else "unknown"
        })
        # Редирект на страницу логина вместо 401
        raise HTTPException(
            status_code=status.HTTP_307_TEMPORARY_REDIRECT,
            detail="Необходима авторизация",
            headers={"Location": "/api/v1/auth/login-page"}
        )
    
    try:
        # Декодируем JWT
        payload = decode_token(token)
        user_id: str = payload.get("sub")
        
        if user_id is None:
            raise HTTPException(
                status_code=status.HTTP_307_TEMPORARY_REDIRECT,
                detail="Неверный токен: отсутствует ID пользователя",
                headers={"Location": "/api/v1/auth/login-page"}
            )
        
    except JWTError as e:
        logger.warning({
            "event": "invalid_token",
            "error": str(e),
            "path": str(request.url.path),
            "client_ip": request.client.host if request.client else "unknown"
        })
        raise HTTPException(
            status_code=status.HTTP_307_TEMPORARY_REDIRECT,
            detail="Неверный токен",
            headers={"Location": "/api/v1/auth/login-page"}
        )
    
    # Получаем пользователя из БД
    user = db.query(User).filter(User.id == int(user_id)).first()
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_307_TEMPORARY_REDIRECT,
            detail="Пользователь не найден",
            headers={"Location": "/api/v1/auth/login-page"}
        )
    
    if not user.is_active:
        logger.warning({
            "event": "inactive_user_access",
            "user_id": user.id,
            "email": user.email,
            "path": str(request.url.path)
        })
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Пользователь неактивен. Обратитесь к администратору."
        )
    
    return user


# ===================================
# Опциональная зависимость (для страниц, где авторизация не обязательна)
# ===================================
async def get_current_user_optional(
    request: Request,
    db: Session = Depends(get_db)
) -> User | None:
    """
    Получить текущего пользователя из Cookie, если есть.
    Возвращает None, если не авторизован.
    """
    token = request.cookies.get("access_token")
    
    if not token:
        return None
    
    try:
        payload = decode_token(token)
        user_id: str = payload.get("sub")
        
        if user_id is None:
            return None
        
        user = db.query(User).filter(User.id == int(user_id)).first()
        
        if user and user.is_active:
            return user
            
    except JWTError:
        pass
    
    return None


# ===================================
# Зависимость для проверки роли
# ===================================
def require_role(*roles: str):
    """
    Декоратор для проверки роли пользователя.
    
    Usage:
        @router.get("/admin")
        async def admin_endpoint(user: User = Depends(require_role("admin"))):
            ...
    """
    async def check_role(user: User = Depends(get_current_user)) -> User:
        # Получаем значение роли пользователя (если это Enum)
        user_role = user.role.value if hasattr(user.role, 'value') else user.role
        
        if user_role not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Доступ запрещён. Требуемые роли: {', '.join(roles)}"
            )
        return user
    
    return check_role


# ===================================
# Зависимость для проверки роли (WEB версия)
# ===================================
def require_role_web(*roles: str):
    """
    Декоратор для проверки роли пользователя (для веб-страниц).
    """
    async def check_role(user: User = Depends(get_current_user_from_cookie)) -> User:
        # Получаем значение роли пользователя (если это Enum)
        user_role = user.role.value if hasattr(user.role, 'value') else user.role
        
        if user_role not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Доступ запрещён. Требуемые роли: {', '.join(roles)}"
            )
        return user
    
    return check_role


# ===================================
# Зависимость для проверки admin-а
# ===================================
async def require_admin(user: User = Depends(require_role(UserRole.ADMIN.value))) -> User:
    """Проверка что пользователь admin (для API)"""
    return user


async def require_admin_web(user: User = Depends(require_role_web(UserRole.ADMIN.value))) -> User:
    """Проверка что пользователь admin (для веб-страниц)"""
    return user