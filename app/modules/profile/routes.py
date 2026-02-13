from core.template_helpers import get_sidebar_context
from fastapi import APIRouter, Depends, Request, Form, UploadFile, File, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from pydantic import ValidationError
import logging
import os
import uuid
from pathlib import Path

from core.database import get_db
from core.config import settings
from modules.auth.dependencies import get_current_user_from_cookie
from modules.auth.models import User
from modules.auth.schemas import UserUpdate, ChangePasswordRequest
from modules.auth.service import AuthService
from modules.auth.utils import verify_password, hash_password

logger = logging.getLogger("app")

router = APIRouter(tags=["profile"])

from fastapi.templating import Jinja2Templates
templates = Jinja2Templates(directory="templates")


# ===================================
# Просмотр профиля
# ===================================
@router.get("", response_class=HTMLResponse)
async def profile_page(
    request: Request,
    user: User = Depends(get_current_user_from_cookie),
    success: str = None,
    error: str = None,
    db: Session = Depends(get_db)
):
    """
    Страница профиля пользователя
    """
    logger.info({
        "event": "profile_view",
        "user_id": user.id,
        "email": user.email
    })

    sidebar_context = get_sidebar_context(user, db)
    
    return templates.TemplateResponse(
        "web/profile/index.html",
        {
            "request": request,
            "user": user,
            "success": success,
            "error": error,
            **sidebar_context
        }
    )


# ===================================
# Обновление профиля
# ===================================
@router.post("/update")
async def update_profile(
    request: Request,
    first_name: str = Form(None),
    last_name: str = Form(None),
    middle_name: str = Form(None),
    phone_number: str = Form(None),
    user: User = Depends(get_current_user_from_cookie),
    db: Session = Depends(get_db)
):
    """
    Обновление данных профиля
    """
    logger.info({
        "event": "profile_update_attempt",
        "user_id": user.id,
        "email": user.email
    })
    
    try:
        # Валидация через Pydantic
        data = UserUpdate(
            first_name=first_name,
            last_name=last_name,
            middle_name=middle_name,
            phone_number=phone_number
        )
        
        # Обновляем пользователя
        updated_user = AuthService.update_user(user, data, db)
        
        logger.info({
            "event": "profile_updated",
            "user_id": user.id,
            "email": user.email
        })
        
        return RedirectResponse(
            url="/profile?success=Профиль успешно обновлен",
            status_code=303
        )
        
    except ValidationError as e:
        error_msg = e.errors()[0]["msg"]
        logger.warning({
            "event": "profile_update_validation_failed",
            "user_id": user.id,
            "error": error_msg
        })
        
        return RedirectResponse(
            url=f"/profile?error={error_msg}",
            status_code=303
        )
        
    except Exception as e:
        logger.error({
            "event": "profile_update_error",
            "user_id": user.id,
            "error": str(e),
            "error_type": type(e).__name__
        }, exc_info=True)
        
        return RedirectResponse(
            url="/profile?error=Произошла ошибка при обновлении",
            status_code=303
        )


# ===================================
# Загрузка аватара
# ===================================
@router.post("/upload-avatar")
async def upload_avatar(
    request: Request,
    avatar: UploadFile = File(...),
    user: User = Depends(get_current_user_from_cookie),
    db: Session = Depends(get_db)
):
    """
    Загрузка аватара пользователя
    """
    logger.info({
        "event": "avatar_upload_attempt",
        "user_id": user.id,
        "filename": avatar.filename
    })
    
    try:
        # Проверка типа файла
        allowed_types = ["image/jpeg", "image/png", "image/gif", "image/webp"]
        if avatar.content_type not in allowed_types:
            raise HTTPException(
                status_code=400,
                detail="Неподдерживаемый формат. Разрешены: JPG, PNG, GIF, WEBP"
            )
        
        # Проверка размера (макс 5MB)
        max_size = 5 * 1024 * 1024  # 5MB
        contents = await avatar.read()
        if len(contents) > max_size:
            raise HTTPException(
                status_code=400,
                detail="Файл слишком большой. Максимум 5MB"
            )
        
        # Создаем папку для аватаров
        avatars_dir = Path("static/avatars")
        avatars_dir.mkdir(parents=True, exist_ok=True)
        
        # Генерируем уникальное имя файла
        file_ext = Path(avatar.filename).suffix
        filename = f"{user.id}_{uuid.uuid4().hex[:8]}{file_ext}"
        file_path = avatars_dir / filename
        
        # Сохраняем файл
        with open(file_path, "wb") as f:
            f.write(contents)
        
        # Обновляем URL аватара в БД
        user.avatar_url = f"/static/avatars/{filename}"
        db.commit()
        
        logger.info({
            "event": "avatar_uploaded",
            "user_id": user.id,
            "filename": filename
        })
        
        return RedirectResponse(
            url="/profile?success=Аватар успешно загружен",
            status_code=303
        )
        
    except HTTPException as e:
        return RedirectResponse(
            url=f"/profile?error={e.detail}",
            status_code=303
        )
        
    except Exception as e:
        logger.error({
            "event": "avatar_upload_error",
            "user_id": user.id,
            "error": str(e)
        }, exc_info=True)
        
        return RedirectResponse(
            url="/profile?error=Ошибка при загрузке аватара",
            status_code=303
        )


# ===================================
# Изменение пароля
# ===================================
@router.post("/change-password")
async def change_password(
    request: Request,
    current_password: str = Form(...),
    new_password: str = Form(...),
    confirm_password: str = Form(...),
    user: User = Depends(get_current_user_from_cookie),
    db: Session = Depends(get_db)
):
    """
    Изменение пароля
    """
    logger.info({
        "event": "password_change_attempt",
        "user_id": user.id,
        "email": user.email
    })
    
    try:
        # Валидация через Pydantic
        data = ChangePasswordRequest(
            current_password=current_password,
            new_password=new_password,
            confirm_password=confirm_password
        )
        
        # Меняем пароль через сервис
        AuthService.change_password(user, data, db)
        
        logger.info({
            "event": "password_changed",
            "user_id": user.id,
            "email": user.email
        })
        
        return RedirectResponse(
            url="/profile?success=Пароль успешно изменен",
            status_code=303
        )
        
    except ValidationError as e:
        error_msg = e.errors()[0]["msg"]
        logger.warning({
            "event": "password_change_validation_failed",
            "user_id": user.id,
            "error": error_msg
        })
        
        return RedirectResponse(
            url=f"/profile?error={error_msg}",
            status_code=303
        )
        
    except HTTPException as e:
        logger.warning({
            "event": "password_change_failed",
            "user_id": user.id,
            "error": e.detail
        })
        
        return RedirectResponse(
            url=f"/profile?error={e.detail}",
            status_code=303
        )
        
    except Exception as e:
        logger.error({
            "event": "password_change_error",
            "user_id": user.id,
            "error": str(e)
        }, exc_info=True)
        
        return RedirectResponse(
            url="/profile?error=Ошибка при смене пароля",
            status_code=303
        )