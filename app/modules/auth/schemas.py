from pydantic import BaseModel, EmailStr, Field, field_validator, ConfigDict
from typing import Optional, Literal
from datetime import datetime
from enum import Enum


# ===================================
# Enum для ролей
# ===================================
class UserRoleEnum(str, Enum):
    ADMIN = "admin"
    ACCOUNTANT = "accountant"
    HR = "hr"
    ENGINEER = "engineer"
    LAWYER = "lawyer"
    EMPLOYEE = "employee"


# ===================================
# UserCreate — регистрация
# ===================================
class UserCreate(BaseModel):
    email: EmailStr = Field(..., description="Email пользователя")
    password: str = Field(
        ...,
        min_length=8,
        max_length=128,
        description="Пароль (мин. 8 символов, должен содержать заглавную букву, цифру и спец. символ)",
    )

    # Профильные поля
    first_name: Optional[str] = Field(None, max_length=100)
    last_name: Optional[str] = Field(None, max_length=100)
    middle_name: Optional[str] = Field(None, max_length=100)
    phone_number: Optional[str] = Field(None, pattern=r"^\+?[\d\s\-()]+$", max_length=20)
    avatar_url: Optional[str] = Field(None, max_length=500)

    # ABAC-атрибуты (опциональные на регистрацию, заполняются админом позже)
    department_id: Optional[int] = Field(None, ge=1)
    position: Optional[str] = Field(None, max_length=255)
    location: Optional[str] = Field(None, max_length=255)
    object_id: Optional[int] = Field(None, ge=0)

    @field_validator("password")
    @classmethod
    def validate_password_strength(cls, v: str) -> str:
        """Проверка сложности пароля"""
        if not any(c.isupper() for c in v):
            raise ValueError("Пароль должен содержать хотя бы одну заглавную букву")
        if not any(c.isdigit() for c in v):
            raise ValueError("Пароль должен содержать хотя бы одну цифру")
        if not any(c in "@$!%*?&" for c in v):
            raise ValueError("Пароль должен содержать спец. символ (@$!%*?&)")
        return v

    @field_validator("first_name", "last_name", "middle_name", mode="before")
    @classmethod
    def strip_whitespace(cls, v: Optional[str]) -> Optional[str]:
        """Удаляет пробелы в начале/конце"""
        return v.strip() if v else None

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "email": "john@example.com",
                "password": "SecurePass123!@",
                "first_name": "John",
                "last_name": "Doe",
                "phone_number": "+1-234-567-8900",
                "department": "Engineering",
                "position": "Senior Developer",
            }
        }
    )


# ===================================
# UserLogin — вход
# ===================================
class UserLogin(BaseModel):
    email: EmailStr = Field(..., description="Email пользователя")
    password: str = Field(..., description="Пароль пользователя")

    model_config = ConfigDict(
        json_schema_extra={"example": {"email": "john@example.com", "password": "SecurePass123!@"}}
    )


# ===================================
# UserRead — данные пользователя (response)
# ===================================
class UserRead(BaseModel):
    id: int
    email: EmailStr

    role: UserRoleEnum
    is_active: bool

    first_name: Optional[str]
    last_name: Optional[str]
    middle_name: Optional[str]
    phone_number: Optional[str]
    avatar_url: Optional[str]

    # ABAC-атрибуты (если пользователь имеет доступ к ним)
    department_id: Optional[int]
    department_rel: Optional["DepartmentRead"] = None
    position: Optional[str]
    location: Optional[str]
    object_id: Optional[int]

    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


# ===================================
# UserReadPublic — публичные данные пользователя (без sensitive)
# ===================================
class UserReadPublic(BaseModel):
    """Ограниченные данные для публичного доступа"""

    id: int
    first_name: Optional[str]
    last_name: Optional[str]
    avatar_url: Optional[str]
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


# ===================================
# UserUpdate — обновление профиля
# ===================================
class UserUpdate(BaseModel):
    """Пользователь может обновлять свой профиль (не роль/email)"""

    first_name: Optional[str] = Field(None, max_length=100)
    last_name: Optional[str] = Field(None, max_length=100)
    middle_name: Optional[str] = Field(None, max_length=100)
    phone_number: Optional[str] = Field(None, pattern=r"^\+?[\d\s\-()]+$", max_length=20)
    avatar_url: Optional[str] = Field(None, max_length=500)

    @field_validator("first_name", "last_name", "middle_name", mode="before")
    @classmethod
    def strip_whitespace(cls, v: Optional[str]) -> Optional[str]:
        return v.strip() if v else None


# ===================================
# UserUpdateAdmin — обновление админом
# ===================================
class UserUpdateAdmin(BaseModel):
    """Админ может обновлять все поля кроме пароля (через отдельный endpoint)"""

    email: Optional[EmailStr] = None
    first_name: Optional[str] = Field(None, max_length=100)
    last_name: Optional[str] = Field(None, max_length=100)
    middle_name: Optional[str] = Field(None, max_length=100)
    phone_number: Optional[str] = Field(None, pattern=r"^\+?[\d\s\-()]+$", max_length=20)
    avatar_url: Optional[str] = Field(None, max_length=500)

    role: Optional[UserRoleEnum] = None
    is_active: Optional[bool] = None

    department_id: Optional[int] = Field(None, ge=1)
    position: Optional[str] = Field(None, max_length=255)
    location: Optional[str] = Field(None, max_length=255)
    object_id: Optional[int] = Field(None, ge=0)

    @field_validator("first_name", "last_name", "middle_name", mode="before")
    @classmethod
    def strip_whitespace(cls, v: Optional[str]) -> Optional[str]:
        return v.strip() if v else None


# ===================================
# ChangePasswordRequest — смена пароля
# ===================================
class ChangePasswordRequest(BaseModel):
    current_password: str = Field(..., description="Текущий пароль")
    new_password: str = Field(..., min_length=8, max_length=128, description="Новый пароль")
    confirm_password: str = Field(..., description="Подтверждение нового пароля")

    @field_validator("new_password")
    @classmethod
    def validate_new_password(cls, v: str) -> str:
        if not any(c.isupper() for c in v):
            raise ValueError("Пароль должен содержать хотя бы одну заглавную букву")
        if not any(c.isdigit() for c in v):
            raise ValueError("Пароль должен содержать хотя бы одну цифру")
        if not any(c in "@$!%*?&" for c in v):
            raise ValueError("Пароль должен содержать спец. символ (@$!%*?&)")
        return v

    @field_validator("confirm_password")
    @classmethod
    def passwords_match(cls, v: str, info) -> str:
        if "new_password" in info.data and v != info.data["new_password"]:
            raise ValueError("Пароли не совпадают")
        return v


# ===================================
# TokenResponse — ответ после логина
# ===================================
class TokenResponse(BaseModel):
    access_token: str = Field(..., description="JWT access token")
    refresh_token: str = Field(..., description="Refresh token (хэш в БД)")
    token_type: Literal["bearer"] = Field("bearer", description="Тип токена")
    expires_in: int = Field(..., description="Время жизни access token (секунды)")
    user: UserRead = Field(..., description="Данные пользователя")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "access_token": "eyJ0eXAiOiJKV1QiLCJhbGc...",
                "refresh_token": "a1b2c3d4e5f6...",
                "token_type": "bearer",
                "expires_in": 3600,
                "user": {
                    "id": 1,
                    "email": "john@example.com",
                    "role": "employee",
                    "is_active": True,
                    "first_name": "John",
                    "created_at": "2026-02-04T10:00:00Z",
                    "updated_at": "2026-02-04T10:00:00Z",
                },
            }
        }
    )


# ===================================
# RefreshTokenRequest — обновление access token
# ===================================
class RefreshTokenRequest(BaseModel):
    refresh_token: str = Field(..., description="Refresh token")


# ===================================
# LogoutRequest — выход
# ===================================
class LogoutRequest(BaseModel):
    refresh_token: Optional[str] = Field(None, description="Refresh token (опционально)")


# ===================================
# OTPRequest — запрос на отправку OTP
# ===================================
class OTPRequest(BaseModel):
    email: EmailStr = Field(..., description="Email пользователя")
    purpose: Literal["login", "email_verify", "password_reset"] = Field(..., description="Цель OTP")


# ===================================
# OTPVerify — верификация OTP кода
# ===================================
class OTPVerify(BaseModel):
    email: EmailStr = Field(..., description="Email пользователя")
    code: str = Field(..., min_length=4, max_length=128, description="OTP код")


# ===================================
# PasswordResetRequest — запрос на сброс пароля
# ===================================
class PasswordResetRequest(BaseModel):
    email: EmailStr = Field(..., description="Email пользователя")


# ===================================
# PasswordResetConfirm — подтверждение сброса пароля
# ===================================
class PasswordResetConfirm(BaseModel):
    email: EmailStr = Field(..., description="Email пользователя")
    code: str = Field(..., description="OTP код из письма")
    new_password: str = Field(..., min_length=8, max_length=128, description="Новый пароль")
    confirm_password: str = Field(..., description="Подтверждение пароля")

    @field_validator("new_password")
    @classmethod
    def validate_password(cls, v: str) -> str:
        if not any(c.isupper() for c in v):
            raise ValueError("Пароль должен содержать хотя бы одну заглавную букву")
        if not any(c.isdigit() for c in v):
            raise ValueError("Пароль должен содержать хотя бы одну цифру")
        if not any(c in "@$!%*?&" for c in v):
            raise ValueError("Пароль должен содержать спец. символ (@$!%*?&)")
        return v

    @field_validator("confirm_password")
    @classmethod
    def passwords_match(cls, v: str, info) -> str:
        if "new_password" in info.data and v != info.data["new_password"]:
            raise ValueError("Пароли не совпадают")
        return v


# ===================================
# ErrorResponse — стандартный ответ об ошибке
# ===================================
class ErrorResponse(BaseModel):
    detail: str = Field(..., description="Описание ошибки")
    code: Optional[str] = Field(None, description="Код ошибки")
    error_id: Optional[str] = Field(None, description="ID ошибки для трейса")


# ===================================
# SessionRead — информация о сессии
# ===================================
class SessionRead(BaseModel):
    id: int
    user_agent: Optional[str]
    ip_address: Optional[str]
    created_at: datetime
    expires_at: datetime
    is_revoked: bool
    last_used_at: Optional[datetime]

    model_config = ConfigDict(from_attributes=True)


# ===================================
# Department schemas
# ===================================
class DepartmentCreate(BaseModel):
    """Создание отдела"""

    name: str = Field(..., min_length=1, max_length=255, description="Название отдела")
    description: Optional[str] = Field(None, max_length=512, description="Описание отдела")

    model_config = ConfigDict(
        json_schema_extra={"example": {"name": "Бухгалтерия", "description": "Финансовый отдел компании"}}
    )


class DepartmentUpdate(BaseModel):
    """Обновление отдела"""

    name: Optional[str] = Field(None, min_length=1, max_length=255, description="Название отдела")
    description: Optional[str] = Field(None, max_length=512, description="Описание отдела")


class DepartmentRead(BaseModel):
    """Чтение данных отдела"""

    id: int
    name: str
    description: Optional[str]
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
