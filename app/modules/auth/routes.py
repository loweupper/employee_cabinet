from datetime import timezone
from core.logging.actions import log_event
from fastapi import APIRouter, Depends, HTTPException, status, Query, Request, Form, Response
from fastapi.responses import RedirectResponse, HTMLResponse
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
import logging
from pydantic import ValidationError
from slowapi import Limiter
from slowapi.util import get_remote_address
from modules.auth.ip_geo import get_ip_geo



from core.database import get_db
from modules.auth.schemas import *
from modules.auth.dependencies import get_current_user
from modules.auth.models import User, Session as SessionModel
from modules.auth.service import AuthService

# logger = logging.getLogger("app")

# Initialize rate limiter
limiter = Limiter(key_func=get_remote_address)

from fastapi.templating import Jinja2Templates

templates = Jinja2Templates(directory="templates")

router = APIRouter(
    prefix="/auth",
    tags=["🔐 Аутентификация"],  # ✅ Красивая иконка в Swagger
)

#===================================
# Веб-страницы для логина и регистрации
#===================================
@router.get("/login-page", response_class=HTMLResponse, include_in_schema=False)
async def login_page(
    request: Request,
    registered: bool = None,
    error: str = None
):
    """
    Страница логина с опциональным success message после регистрации
    """
    success_message = None
    if registered:
        success_message = "Регистрация отправлена на модерацию. После активации вы сможете войти в систему."
    
    return templates.TemplateResponse(
        "web/auth/login.html",
        {
            "request": request,
            "success": success_message,
            "error": error
        }
    )

@router.get("/register-page", summary="📝 Страница регистрации", description="Страница для регистрации нового пользователя", response_class=HTMLResponse)
def register_page(request: Request):
    return templates.TemplateResponse("web/auth/register.html", {"request": request})


def get_client_ip(request: Request) -> str:
    """Получить IP адрес клиента"""
    # Проверяем X-Forwarded-For заголовок (для прокси/load balancer)
    if request.headers.get("x-forwarded-for"):
        return request.headers["x-forwarded-for"].split(",")[0].strip()
    # Иначе берём IP из подключения
    return request.client.host if request.client else "unknown"


def get_user_agent(request: Request) -> str:
    """Получить User-Agent"""
    return request.headers.get("user-agent", "unknown")


# ===================================
# Регистрация и вход
# ===================================
@router.post("/register", summary="📝 Регистрация нового пользователя", description="Регистрация нового пользователя через веб-форму")
@limiter.limit("3/minute")
async def register(
    email: str = Form(...),
    password: str = Form(...),
    first_name: str = Form(None),
    last_name: str = Form(None),
    request: Request = None,
    db: Session = Depends(get_db)
):
    """
    Регистрация нового пользователя через веб-форму
    """
    client_ip = get_client_ip(request)
    request_id = getattr(request.state, "request_id", "unknown")
    
    # Логируем попытку регистрации
    await log_event(
        event="registration_attempt",
        request=request,
        client_ip=client_ip,
        request_id=request_id,
        extra={
            "email": email,
            "client_ip": client_ip,
            "request_id": request_id,
         }
    )
    
    # Валидация данных через Pydantic
    try:
        data = UserCreate(
            email=email,
            password=password,
            first_name=first_name,
            last_name=last_name,
        )

    except ValidationError as e:
        error_msg = e.errors()[0]["msg"]
        
        await log_event(
            event="registration_validation_failed",
            request=request,
            level="WARNING",
            client_ip=client_ip,
            request_id=request_id,
            extra={
                "email": email,
                "error": error_msg,
                "client_ip": client_ip,
                "request_id": request_id,
            }
        )


        return templates.TemplateResponse(
            "web/auth/register.html",
            {
                "request": request,
                "error": error_msg,
                "email": email,
                "first_name": first_name,
                "last_name": last_name
            },
            status_code=400
        )
    
    # Попытка регистрации
    try:
        user = AuthService.register(data, db, client_ip)
        
        # Получаем пользователя
        user = db.query(User).filter(User.email == email).first()

        # ✅ Логируем успешную регистрацию
        await log_event(
            event="registration_success",
            request=request,
            actor=user,
            extra={
                "client_ip": client_ip,
                "request_id": request_id,
            }
        )
        
        # Редирект на страницу логина с success message
        return RedirectResponse(
            url="/api/v1/auth/login-page?registered=true",
            status_code=303  # POST -> GET редирект
        )

    except IntegrityError:
        # Email уже существует
        db.rollback()

        # ✅ Логируем ошибку (email уже существует)
        await log_event(
            event="registration_failed",
            request=request,
            level="WARNING",
            client_ip=client_ip,
            request_id=request_id,
            extra={
                "reason": "email_exists",
                "email": email,
                "client_ip": client_ip,
                "request_id": request_id,
            }
        )

        return templates.TemplateResponse(
            "web/auth/register.html",
            {
                "request": request,
                "error": "Пользователь с таким email уже существует",
                "email": email,
                "first_name": first_name,
                "last_name": last_name
            },
            status_code=400
        )

    except Exception as e:
        # ✅ Логируем неожиданную ошибку
        await log_event(
            event="registration_error",
            request=request,
            level="ERROR",
            create_alert=True,  # 👈 создаём алерт в БД
            client_ip=client_ip,
            request_id=request_id,
            extra={
                "error": str(e),
                "error_type": type(e).__name__,
                "email": email,
                "client_ip": client_ip,
                "request_id": request_id,
            }
        )

        return templates.TemplateResponse(
            "web/auth/register.html",
            {
                "request": request,
                "error": "Произошла ошибка при регистрации. Попробуйте позже.",
                "email": email,
                "first_name": first_name,
                "last_name": last_name
            },
            status_code=500
        )


# ===================================
# Логин
# ===================================
@router.post("/login", summary="🔑 Логин пользователя", description="Логин пользователя через веб-форму с email и паролем")
@limiter.limit("5/minute")
async def login(
    email: str = Form(...),
    password: str = Form(...),
    request: Request = None,
    response: Response = None,
    db: Session = Depends(get_db)
):
    """
    Логин через веб-форму
    """

    # Очистка истёкших сессий 
    db.query(SessionModel).filter( 
        SessionModel.expires_at < datetime.now(timezone.utc)
    ).delete() 
    db.commit()

    client_ip = get_client_ip(request)
    user_agent = get_user_agent(request)
    request_id = getattr(request.state, "request_id", "unknown")
    
    # ✅ Логируем попытку входа
    await log_event(
        event="login_attempt",
        request=request,
        extra={
            "email": email,
            "client_ip": client_ip,
            "user_agent": user_agent,
            "request_id": request_id,
        }
    )

    try:
        # Преобразуем в Pydantic схему
        data = UserLogin(email=email, password=password)
        
        # Логин через сервис (возвращает TokenResponse — Pydantic модель)
        token_response = AuthService.login(data, db, user_agent, client_ip)
        
        # Получаем пользователя
        user = db.query(User).filter(User.email == email).first()

        # ✅ Логируем успешный вход
        await log_event(
            event="login_success",
            request=request,
            actor=user,
            extra={
                "client_ip": client_ip,
                "user_agent": user_agent,
                "request_id": request_id,
            }
        )

        # Record successful login attempt
        try:
            from core.monitoring.detector import get_login_tracker
            tracker = get_login_tracker()
            # Get user ID from token
            user = db.query(User).filter(User.email == email).first()
            await tracker.record_attempt(email, client_ip, True, user.id if user else None)
        except Exception as tracker_error:
            
            # ✅ Логируем ошибку трекера
            await log_event(
                event="login_failed_tracker",
                request=request,
                level="WARNING",
                extra={
                    "error": str(tracker_error),
                    "email": email,
                    "client_ip": client_ip,
                    "request_id": request_id,
                }
            )
        
        # Устанавливаем cookies
        redirect = RedirectResponse(
            url="/dashboard",
            status_code=303
        )
        
        redirect.set_cookie(
            key="access_token",
            value=token_response.access_token,  # ✅ Не ["access_token"]
            httponly=True,
            secure=False,  # В production должно быть True (для HTTPS)
            samesite="lax",
            max_age=3600  # 1 час
        )
        
        redirect.set_cookie(
            key="refresh_token",
            value=token_response.refresh_token,  # ✅ Не ["refresh_token"]
            httponly=True,
            secure=False,
            samesite="lax",
            max_age=60 * 60 * 24 * 7  # 7 дней
        )
        
        return redirect
        
    except HTTPException as e:
        # Неверный логин/пароль - record failed attempt
        try:
            from core.monitoring.detector import get_login_tracker
            tracker = get_login_tracker()
            await tracker.record_attempt(email, client_ip, False, None)
        except Exception as tracker_error:
            pass

        # ✅ Логируем неудачную попытку входа (создаём алерт)
        await log_event(
            event="login_failed",
            request=request,
            level="WARNING",
            create_alert=True,  # 👈 создаём алерт в БД
            extra={
                "email": email,
                "client_ip": client_ip,
                "request_id": request_id,
                "error": e.detail
            }
        )
        
        return templates.TemplateResponse(
            "web/auth/login.html",
            {
                "request": request,
                "error": e.detail,
                "email": email
            },
            status_code=401
        )
        
    except Exception as e:
        # ✅ Логируем неожиданную ошибку входа
        await log_event(
            event="login_error",
            request=request,
            level="ERROR",
            create_alert=True,  # 👈 создаём алерт в БД
            extra={
                "error": str(e),
                "error_type": type(e).__name__,
                "email": email,
                "client_ip": client_ip,
                "request_id": request_id,
            }
        )
        
        return templates.TemplateResponse(
            "web/auth/login.html",
            {
                "request": request,
                "error": "Произошла ошибка. Попробуйте позже.",
                "email": email
            },
            status_code=500
        )


# ===================================
# Токены
# ===================================

@router.post(
    "/refresh",
    response_model=TokenResponse,
    summary="Обновить access token",
    responses={
        401: {"model": ErrorResponse, "description": "Невалиден или истёк refresh token"}
    }
)
def refresh_token(data: RefreshTokenRequest, db: Session = Depends(get_db)):
    """
    Обновить access token по refresh токену.
    """
    return AuthService.refresh_token(data.refresh_token, db)


@router.get("/logout")
async def logout_web(request: Request):
    """
    Выход из системы (веб)
    """
    response = RedirectResponse(url="/api/v1/auth/login-page", status_code=303)
    
    # Удаляем cookies
    response.delete_cookie("access_token")
    response.delete_cookie("refresh_token")
    
    await log_event(
        event="user_logout",
        request=request,
        user=None,
        extra={
            "client_ip": request.client.host if request.client else "unknown"
        }
    )
    
    return response


# ===================================
# Профиль пользователя
# ===================================

@router.get(
    "/me",
    response_model=UserRead,
    summary="Получить профиль текущего пользователя"
)
def get_current_user_info(user: User = Depends(get_current_user)):
    """
    Получить полную информацию текущего пользователя.
    """
    return user


@router.patch(
    "/me",
    response_model=UserRead,
    summary="Обновить свой профиль"
)
def update_current_user(
    data: UserUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Обновить свой профиль (имя, телефон, аватар и т.д.).
    """
    return AuthService.update_user(user, data, db)


# ===================================
# Пароль
# ===================================

@router.post(
    "/change-password",
    summary="Смена пароля",
    responses={
        400: {"model": ErrorResponse, "description": "Текущий пароль неверен"}
    }
)
def change_password(
    data: ChangePasswordRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Смена пароля текущим пользователем.
    
    Требует текущий пароль и новый пароль.
    """
    return AuthService.change_password(user, data, db)


@router.post(
    "/password-reset/request",
    summary="Запрос на сброс пароля",
    responses={
        200: {"description": "OTP отправлен на email"},
        429: {"model": ErrorResponse, "description": "Слишком много запросов"}
    }
)
def password_reset_request(data: PasswordResetRequest, db: Session = Depends(get_db)):
    """
    Запрос на сброс пароля.
    
    OTP код будет отправлен на email.
    
    Защита от брутфорса: максимум 3 запроса на email в час.
    """
    return AuthService.password_reset_request(data, db)


@router.post(
    "/password-reset/confirm",
    summary="Подтвердить сброс пароля",
    responses={
        400: {"model": ErrorResponse, "description": "Невалиден или истёк OTP код"},
        429: {"model": ErrorResponse, "description": "Слишком много попыток"}
    }
)
def password_reset_confirm(data: PasswordResetConfirm, db: Session = Depends(get_db)):
    """
    Подтвердить сброс пароля с помощью OTP кода.
    
    Защита от брутфорса: максимум 5 неудачных попыток в 15 минут.
    """
    return AuthService.password_reset_confirm(data, db)


# ===================================
# OTP (2FA)
# ===================================

@router.post(
    "/otp/request",
    summary="Запрос OTP кода",
    responses={
        200: {"description": "OTP отправлен на email"},
        429: {"model": ErrorResponse, "description": "Слишком много запросов OTP"}
    }
)
def request_otp(data: OTPRequest, db: Session = Depends(get_db)):
    """
    Запрос OTP кода.
    
    - **email**: Email пользователя
    - **purpose**: Цель OTP (login, email_verify, password_reset)
    
    Защита от брутфорса: максимум 3 запроса на email+purpose в час.
    """
    return AuthService.request_otp(data, db)


@router.post(
    "/otp/verify",
    response_model=TokenResponse,
    summary="Верификация OTP кода",
    responses={
        400: {"model": ErrorResponse, "description": "Невалиден или истёк OTP код"},
        429: {"model": ErrorResponse, "description": "Слишком много попыток ввода OTP"}
    }
)
def verify_otp(data: OTPVerify, db: Session = Depends(get_db)):
    """
    Верификация OTP кода.
    
    Возвращает access_token и refresh_token при успешной верификации.
    
    Защита от брутфорса: максимум 5 неудачных попыток в 15 минут.
    """
    return AuthService.verify_otp(data, db)


# ===================================
# Сессии
# ===================================

@router.get(
    "/sessions",
    response_model=list[SessionRead],
    summary="Получить все активные сессии"
)
def get_sessions(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Получить список всех активных сессий текущего пользователя.
    """
    sessions = db.query(SessionModel).filter(
        SessionModel.user_id == user.id,
        SessionModel.is_revoked == False
    ).all()
    return sessions


@router.delete(
    "/sessions/{session_id}",
    summary="Отозвать сессию",
    responses={
        404: {"model": ErrorResponse, "description": "Сессия не найдена"}
    }
)
def revoke_session(
    session_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Отозвать (выйти) из конкретной сессии.
    """
    return AuthService.revoke_session(user.id, session_id, db)