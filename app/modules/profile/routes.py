import asyncio
import logging
import uuid
from io import BytesIO
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from PIL import Image, ImageOps, UnidentifiedImageError
from pydantic import ValidationError
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy import update
from sqlalchemy.orm import Session

from core.database import get_db
from core.template_helpers import get_sidebar_context
from modules.auth.dependencies import get_current_user_from_cookie
from modules.auth.models import Department, User
from modules.auth.schemas import ChangePasswordRequest, UserUpdate
from modules.auth.service import AuthService
from modules.departments.safety.models import SafetyProfile

logger = logging.getLogger("app")

# Initialize rate limiter
limiter = Limiter(key_func=get_remote_address)

router = APIRouter(tags=["profile"])
templates = Jinja2Templates(directory="templates")


def _avatar_path_from_url(avatar_url: str | None) -> Path | None:
    if not avatar_url or not avatar_url.startswith("/static/"):
        return None

    candidate = Path(".") / avatar_url.lstrip("/")
    try:
        static_root = Path("static").resolve()
        resolved = candidate.resolve()
    except OSError:
        return None

    if static_root in resolved.parents or resolved == static_root:
        return resolved
    return None


def _optimize_avatar_to_webp(contents: bytes) -> bytes:
    with Image.open(BytesIO(contents)) as src:
        optimized = ImageOps.fit(
            src.convert("RGB"),
            (400, 400),
            method=Image.Resampling.LANCZOS,
            centering=(0.5, 0.5),
        )

        output = BytesIO()
        optimized.save(
            output,
            format="WEBP",
            quality=85,
            optimize=True,
            method=6,
        )
        return output.getvalue()


# ===================================
# Просмотр профиля
# ===================================
@router.get("", response_class=HTMLResponse)
async def profile_page(
    request: Request,
    user: Annotated[User, Depends(get_current_user_from_cookie)],
    success: str = None,
    error: str = None,
    db: Annotated[Session, Depends(get_db)] = None,
):
    """
    Страница профиля пользователя
    """

    sidebar_context = get_sidebar_context(user, db)

    from modules.permissions.models import (
        Permission,
        UserPermission,
        UserSubsectionAccess,
    )

    user_permissions = (
        db.query(Permission)
        .join(UserPermission)
        .filter(UserPermission.user_id == user.id)
        .all()
    )
    user_subsection_access = (
        db.query(UserSubsectionAccess)
        .filter(UserSubsectionAccess.user_id == user.id)
        .all()
    )

    department_name = None
    if user.department_id:
        department_name = (
            db.query(Department.name)
            .filter(Department.id == user.department_id)
            .scalar()
        )

    role_labels = {
        "employee": "👤 Сотрудник",
        "admin": "👑 Администратор",
        "accountant": "💰 Бухгалтер",
        "hr": "👔 Отдел кадров",
        "safety": "👷 Специалист по охране труда",
        "engineer": "🔧 Инженер",
        "lawyer": "⚖️ Юрист",
    }

    role_value = None
    if user.role:
        role_value = (
            user.role.value
            if hasattr(user.role, "value")
            else str(user.role).split(".")[-1].lower()
        )

    user_role = role_labels.get(role_value, role_value)

    return templates.TemplateResponse(
        "web/profile/index.html",
        {
            "request": request,
            "user": user,
            "department_name": department_name,
            "user_role": user_role,
            "current_user": user,
            "success": success,
            "error": error,
            "user_permissions": user_permissions,
            "user_subsection_access": user_subsection_access,
            **sidebar_context,
        },
    )


# ===================================
# Обновление профиля
# ===================================
@router.post("/update")
@limiter.limit("30/minute")
async def update_profile(
    request: Request,
    first_name: Annotated[str | None, Form()] = None,
    last_name: Annotated[str | None, Form()] = None,
    middle_name: Annotated[str | None, Form()] = None,
    phone_number: Annotated[str | None, Form()] = None,
    user: Annotated[User, Depends(get_current_user_from_cookie)] = None,
    db: Annotated[Session, Depends(get_db)] = None,
):
    """
    Обновление данных профиля
    """
    logger.info(
        {"event": "profile_update_attempt", "user_id": user.id, "email": user.email}
    )

    try:
        # Валидация через Pydantic
        data = UserUpdate(
            first_name=first_name,
            last_name=last_name,
            middle_name=middle_name,
            phone_number=phone_number,
        )

        # Обновляем пользователя
        AuthService.update_user(user, data, db)

        logger.info(
            {"event": "profile_updated", "user_id": user.id, "email": user.email}
        )

        return RedirectResponse(
            url="/profile?success=Профиль успешно обновлен", status_code=303
        )

    except ValidationError as e:
        error_msg = e.errors()[0]["msg"]
        logger.warning(
            {
                "event": "profile_update_validation_failed",
                "user_id": user.id,
                "error": error_msg,
            }
        )

        return RedirectResponse(url=f"/profile?error={error_msg}", status_code=303)

    except Exception as e:
        logger.error(
            {
                "event": "profile_update_error",
                "user_id": user.id,
                "error": str(e),
                "error_type": type(e).__name__,
            },
            exc_info=True,
        )

        return RedirectResponse(
            url="/profile?error=Произошла ошибка при обновлении", status_code=303
        )


# ===================================
# Загрузка аватара
# ===================================
@router.post("/upload-avatar")
async def upload_avatar(
    request: Request,
    avatar: Annotated[UploadFile, File(...)],
    user: Annotated[User, Depends(get_current_user_from_cookie)] = None,
    db: Annotated[Session, Depends(get_db)] = None,
):
    """
    Загрузка аватара пользователя
    """
    logger.info("event=avatar_upload_attempt")

    try:
        # Проверка типа файла
        allowed_types = {"image/jpeg", "image/png", "image/webp"}
        allowed_ext = {".jpg", ".jpeg", ".png", ".webp"}
        file_ext = Path(avatar.filename or "").suffix.lower()

        if avatar.content_type not in allowed_types or file_ext not in allowed_ext:
            raise HTTPException(
                status_code=400,
                detail="Неподдерживаемый формат. Разрешены: JPG, JPEG, PNG, WEBP",
            )

        # Проверка размера (макс 2MB)
        max_size = 2 * 1024 * 1024
        contents = await avatar.read()
        if len(contents) > max_size:
            raise HTTPException(
                status_code=400, detail="Файл слишком большой. Максимум 2MB"
            )

        try:
            optimized_bytes = await asyncio.to_thread(
                _optimize_avatar_to_webp, contents
            )
        except UnidentifiedImageError as exc:
            raise HTTPException(
                status_code=400,
                detail="Файл не является корректным изображением",
            ) from exc

        # Создаем папку для аватаров пользователя
        avatars_dir = Path("static/avatars") / str(user.id)
        avatars_dir.mkdir(parents=True, exist_ok=True)

        # Генерируем имя оптимизированного файла
        filename = f"{user.id}_{uuid.uuid4().hex[:10]}_optimized.webp"
        file_path = avatars_dir / filename

        old_avatar_url = user.avatar_url

        # Сохраняем оптимизированный WebP
        await asyncio.to_thread(file_path.write_bytes, optimized_bytes)

        # Обновляем URL аватара в БД
        avatar_url = f"/static/avatars/{user.id}/{filename}"
        db.execute(update(User).where(User.id == user.id).values(avatar_url=avatar_url))
        db.execute(
            update(SafetyProfile)
            .where(SafetyProfile.user_id == user.id)
            .values(avatar_url=avatar_url)
        )
        db.commit()
        user.avatar_url = avatar_url

        # Удаляем старый файл только после успешного сохранения и обновления БД
        old_avatar_path = _avatar_path_from_url(old_avatar_url)
        if (
            old_avatar_path
            and old_avatar_path != file_path
            and old_avatar_path.exists()
        ):
            try:
                await asyncio.to_thread(old_avatar_path.unlink)
            except OSError:
                logger.warning("event=old_avatar_delete_failed")

        logger.info("event=avatar_uploaded")

        return RedirectResponse(
            url="/profile?success=Аватар успешно загружен", status_code=303
        )

    except HTTPException as e:
        return RedirectResponse(url=f"/profile?error={e.detail}", status_code=303)

    except Exception as e:
        logger.error(
            {
                "event": "avatar_upload_error",
                "user_id": user.id,
                "error_type": type(e).__name__,
            },
            exc_info=True,
        )

        return RedirectResponse(
            url="/profile?error=Ошибка при загрузке аватара", status_code=303
        )


# ===================================
# Изменение пароля
# ===================================
@router.post("/change-password")
async def change_password(
    request: Request,
    current_password: Annotated[str, Form(...)],
    new_password: Annotated[str, Form(...)],
    confirm_password: Annotated[str, Form(...)],
    user: Annotated[User, Depends(get_current_user_from_cookie)] = None,
    db: Annotated[Session, Depends(get_db)] = None,
):
    """
    Изменение пароля
    """
    logger.info(
        {"event": "password_change_attempt", "user_id": user.id, "email": user.email}
    )

    try:
        # Валидация через Pydantic
        data = ChangePasswordRequest(
            current_password=current_password,
            new_password=new_password,
            confirm_password=confirm_password,
        )

        # Меняем пароль через сервис
        AuthService.change_password(user, data, db)

        logger.info(
            {"event": "password_changed", "user_id": user.id, "email": user.email}
        )

        return RedirectResponse(
            url="/profile?success=Пароль успешно изменен", status_code=303
        )

    except ValidationError as e:
        error_msg = e.errors()[0]["msg"]
        logger.warning(
            {
                "event": "password_change_validation_failed",
                "user_id": user.id,
                "error": error_msg,
            }
        )

        return RedirectResponse(url=f"/profile?error={error_msg}", status_code=303)

    except HTTPException as e:
        logger.warning(
            {"event": "password_change_failed", "user_id": user.id, "error": e.detail}
        )

        return RedirectResponse(url=f"/profile?error={e.detail}", status_code=303)

    except Exception as e:
        logger.error(
            {"event": "password_change_error", "user_id": user.id, "error": str(e)},
            exc_info=True,
        )

        return RedirectResponse(
            url="/profile?error=Ошибка при смене пароля", status_code=303
        )
