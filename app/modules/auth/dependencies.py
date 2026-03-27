"""Dependencies for user authentication and role checks."""

import logging

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPBearer
from jose import JWTError
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from core.constants import UserRole
from core.database import get_db
from modules.auth.models import User
from modules.auth.utils import decode_token

logger = logging.getLogger("app")
LOGIN_PAGE_URL = "/api/v1/auth/login-page"


def _reset_session_state(
    db: Session,
    log_event: str,
    extra: dict | None = None,
) -> None:
    """Best-effort session reset after transient DB/protocol failures."""
    payload = {"event": log_event}
    if extra:
        payload.update(extra)

    try:
        db.rollback()
    except (SQLAlchemyError, IndexError) as rollback_error:
        logger.error(
            {
                **payload,
                "stage": "rollback",
                "error_type": type(rollback_error).__name__,
            }
        )

    try:
        db.invalidate()
    except SQLAlchemyError as invalidate_error:
        logger.error(
            {
                **payload,
                "stage": "invalidate",
                "error_type": type(invalidate_error).__name__,
            }
        )


def _load_user_snapshot_resilient(
    db: Session,
    user_id: int,
    log_event: str,
    extra: dict | None = None,
) -> User | None:
    """Load user snapshot with one reconnect attempt on DB failures."""
    try:
        return _load_user_snapshot(db, user_id)
    except (SQLAlchemyError, IndexError) as first_error:
        logger.error(
            {
                "event": log_event,
                "stage": "first_attempt",
                "error_type": type(first_error).__name__,
                **(extra or {}),
            }
        )
        _reset_session_state(db, log_event, extra)

    return _load_user_snapshot(db, user_id)


def _load_user_snapshot(db: Session, user_id: int) -> User | None:
    """Load a minimal user snapshot without ORM entity row processing."""
    row = db.execute(
        select(
            User.id,
            User.email,
            User.role,
            User.is_active,
            User.first_name,
            User.last_name,
            User.middle_name,
            User.phone_number,
            User.avatar_url,
            User.position,
            User.location,
            User.created_at,
            User.department_id,
            User.hashed_password,
        ).where(User.id == user_id)
    ).first()
    if not row:
        return None

    return User(
        id=row.id,
        email=row.email,
        role=row.role,
        is_active=row.is_active,
        first_name=row.first_name,
        last_name=row.last_name,
        middle_name=row.middle_name,
        phone_number=row.phone_number,
        avatar_url=row.avatar_url,
        position=row.position,
        location=row.location,
        created_at=row.created_at,
        department_id=row.department_id,
        hashed_password=row.hashed_password,
    )


# ===================================
# HTTP Bearer схема для JWT
# ===================================
security = HTTPBearer()


# ===================================
# Зависимость для получения текущего пользователя из JWT (API)
# ===================================
def get_current_user(
    credentials=Depends(security), db: Session = Depends(get_db)
) -> User:
    """
    Получить текущего пользователя из JWT токена (для API endpoints).

    Raises:
        HTTPException 401: если токен невалиден или пользователь не найден
    """
    token = credentials.credentials

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
        ) from e

    # Получаем пользователя из БД
    user = _load_user_snapshot_resilient(
        db,
        int(user_id),
        "current_user_query_failed",
    )

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Пользователь не найден",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Пользователь неактивен. Обратитесь к администратору.",
        )

    return user


# ===================================
# Зависимость для получения текущего пользователя из Cookie (WEB)
# ===================================
def get_current_user_from_cookie(
    request: Request, db: Session = Depends(get_db)
) -> User:
    """
    Получить текущего пользователя из Cookie (для веб-страниц).

    Raises:
        HTTPException 401: если токен невалиден или пользователь не найден
    """
    # Получаем токен из cookie
    token = request.cookies.get("access_token")

    if not token:
        logger.warning(
            {
                "event": "unauthorized_access",
                "path": str(request.url.path),
                "client_ip": (request.client.host if request.client else "unknown"),
            }
        )
        # Редирект на страницу логина вместо 401
        raise HTTPException(
            status_code=status.HTTP_307_TEMPORARY_REDIRECT,
            detail="Необходима авторизация",
            headers={"Location": LOGIN_PAGE_URL},
        )

    try:
        # Декодируем JWT
        payload = decode_token(token)
        user_id: str = payload.get("sub")

        if user_id is None:
            raise HTTPException(
                status_code=status.HTTP_307_TEMPORARY_REDIRECT,
                detail="Неверный токен: отсутствует ID пользователя",
                headers={"Location": LOGIN_PAGE_URL},
            )

    except JWTError as e:
        logger.warning(
            {
                "event": "invalid_token",
                "error": str(e),
                "path": str(request.url.path),
                "client_ip": (request.client.host if request.client else "unknown"),
            }
        )
        raise HTTPException(
            status_code=status.HTTP_307_TEMPORARY_REDIRECT,
            detail="Неверный токен",
            headers={"Location": LOGIN_PAGE_URL},
        ) from e

    # Получаем пользователя из БД
    user = _load_user_snapshot_resilient(
        db,
        int(user_id),
        "current_user_cookie_query_failed",
        extra={"path": str(request.url.path)},
    )

    if not user:
        raise HTTPException(
            status_code=status.HTTP_307_TEMPORARY_REDIRECT,
            detail="Пользователь не найден",
            headers={"Location": LOGIN_PAGE_URL},
        )

    if not user.is_active:
        logger.warning(
            {
                "event": "inactive_user_access",
                "user_id": user.id,
                "email": user.email,
                "path": str(request.url.path),
            }
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Пользователь неактивен. Обратитесь к администратору.",
        )

    return user


# ===================================
# Опциональная зависимость (для страниц, где авторизация не обязательна)
# ===================================
def get_current_user_optional(
    request: Request, db: Session = Depends(get_db)
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

        user = _load_user_snapshot_resilient(
            db,
            int(user_id),
            "current_user_optional_query_failed",
            extra={"path": str(request.url.path)},
        )

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

    def check_role(user: User = Depends(get_current_user)) -> User:
        # Получаем значение роли пользователя (если это Enum)
        user_role = user.role.value if hasattr(user.role, "value") else user.role

        if user_role not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Доступ запрещён. Требуемые роли: {', '.join(roles)}",
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

    def check_role(user: User = Depends(get_current_user_from_cookie)) -> User:
        # Получаем значение роли пользователя (если это Enum)
        user_role = user.role.value if hasattr(user.role, "value") else user.role

        if user_role not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Доступ запрещён. Требуемые роли: {', '.join(roles)}",
            )
        return user

    return check_role


# ===================================
# Зависимость для проверки admin-а
# ===================================
def require_admin(
    user: User = Depends(require_role(UserRole.ADMIN.value)),
) -> User:
    """Проверка что пользователь admin (для API)"""
    return user


def require_admin_web(
    user: User = Depends(require_role_web(UserRole.ADMIN.value)),
) -> User:
    """Проверка что пользователь admin (для веб-страниц)"""
    return user
