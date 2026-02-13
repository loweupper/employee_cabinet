from pydantic import BaseModel, EmailStr, Field, field_validator, ConfigDict
from typing import Optional, Literal, TypeVar, Generic
from datetime import datetime
from enum import Enum


# ===================================
# Enum для ролей (соответствует UserRole из моделей)
# ===================================
class UserRoleEnum(str, Enum):
    ADMIN = "admin"
    ACCOUNTANT = "accountant"
    HR = "hr"
    ENGINEER = "engineer"
    LAWYER = "lawyer"
    EMPLOYEE = "employee"


# ===================================
# Enum для OTP целей
# ===================================
class OTPPurposeEnum(str, Enum):
    LOGIN = "login"
    EMAIL_VERIFY = "email_verify"
    PASSWORD_RESET = "password_reset"


# ===================================
# UserCreate — регистрация
# ===================================
class UserCreate(BaseModel):
    email: EmailStr = Field(..., description="Email пользователя")
    password: str = Field(
        ...,
        min_length=8,
        max_length=128,
        description="Пароль (мин. 8 символов: заглавная буква, цифра, спец. символ)"
    )

    # Профильные поля
    first_name: Optional[str] = Field(None, max_length=255)
    last_name: Optional[str] = Field(None, max_length=255)
    middle_name: Optional[str] = Field(None, max_length=255)
    phone_number: Optional[str] = Field(
        None,
        max_length=20,
        regex=r"^\+?[\d\s\-()]+$",
        description="Номер телефона в международном формате"
    )
    avatar_url: Optional[str] = Field(None, max_length=512)

    # ABAC-атрибуты (опциональные на регистрацию, заполняются админом позже)
    department: Optional[str] = Field(None, max_length=255)
    position: Optional[str] = Field(None, max_length=255)
    location: Optional[str] = Field(None, max_length=255)
    object_id: Optional[int] = Field(None, ge=0)

    @field_validator('password')
    @classmethod
    def validate_password_strength(cls, v: str) -> str:
        """Проверка сложности пароля"""
        if not any(c.isupper() for c in v):
            raise ValueError('Пароль должен содержать хотя бы одну заглавную букву')
        if not any(c.isdigit() for c in v):
            raise ValueError('Пароль должен содержать хотя бы одну цифру')
        if not any(c in '@$!%*?&' for c in v):
            raise ValueError('Пароль должен содержать спец. символ (@$!%*?&)')
        return v

    @field_validator('first_name', 'last_name', 'middle_name', mode='before')
    @classmethod
    def strip_whitespace(cls, v: Optional[str]) -> Optional[str]:
        """Удаляет пробелы в начале/конце"""
        return v.strip() if v else None

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "email": "john.doe@example.com",
                "password": "SecurePass123!@",
                "first_name": "John",
                "last_name": "Doe",
                "phone_number": "+1-234-567-8900",
                "department": "Engineering",
                "position": "Senior Software Engineer"
            }
        }
    )


# ===================================
# UserLogin — вход в систему
# ===================================
class UserLogin(BaseModel):
    email: EmailStr = Field(..., description="Email пользователя")
    password: str = Field(..., description="Пароль пользователя")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "email": "john.doe@example.com",
                "password": "SecurePass123!@"
            }
        }
    )


# ===================================
# UserRead — полные данные пользователя (response)
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

    # ABAC-атрибуты
    department: Optional[str]
    position: Optional[str]
    location: Optional[str]
    object_id: Optional[int]

    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)

    @property
    def full_name(self) -> str:
        """Полное имя пользователя"""
        parts = [self.first_name, self.middle_name, self.last_name]
        return " ".join(p for p in parts if p).strip() or "Unknown"


# ===================================
# UserReadPublic — публичные да��ные пользователя (без sensitive)
# ===================================
class UserReadPublic(BaseModel):
    """Ограниченные данные для публичного доступа"""
    id: int
    first_name: Optional[str]
    last_name: Optional[str]
    avatar_url: Optional[str]
    department: Optional[str]
    position: Optional[str]
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

    @property
    def full_name(self) -> str:
        """Полное имя пользователя"""
        parts = [self.first_name, self.last_name]
        return " ".join(p for p in parts if p).strip() or "Unknown"


# ===================================
# UserUpdate — обновление своего профиля (не роль/email)
# ===================================
class UserUpdate(BaseModel):
    """Пользователь может обновлять свой профиль"""
    first_name: Optional[str] = Field(None, max_length=255)
    last_name: Optional[str] = Field(None, max_length=255)
    middle_name: Optional[str] = Field(None, max_length=255)
    phone_number: Optional[str] = Field(None, max_length=20, regex=r"^\+?[\d\s\-()]+$")
    avatar_url: Optional[str] = Field(None, max_length=512)

    @field_validator('first_name', 'last_name', 'middle_name', mode='before')
    @classmethod
    def strip_whitespace(cls, v: Optional[str]) -> Optional[str]:
        return v.strip() if v else None


# ===================================
# UserUpdateAdmin — обновление админом (всех полей)
# ===================================
class UserUpdateAdmin(BaseModel):
    """Админ может обновлять все поля кроме пароля"""
    email: Optional[EmailStr] = None
    first_name: Optional[str] = Field(None, max_length=255)
    last_name: Optional[str] = Field(None, max_length=255)
    middle_name: Optional[str] = Field(None, max_length=255)
    phone_number: Optional[str] = Field(None, max_length=20, regex=r"^\+?[\d\s\-()]+$")
    avatar_url: Optional[str] = Field(None, max_length=512)

    role: Optional[UserRoleEnum] = None
    is_active: Optional[bool] = None

    # ABAC-атрибуты
    department: Optional[str] = Field(None, max_length=255)
    position: Optional[str] = Field(None, max_length=255)
    location: Optional[str] = Field(None, max_length=255)
    object_id: Optional[int] = Field(None, ge=0)

    @field_validator('first_name', 'last_name', 'middle_name', mode='before')
    @classmethod
    def strip_whitespace(cls, v: Optional[str]) -> Optional[str]:
        return v.strip() if v else None


# ===================================
# ChangePasswordRequest — смена пароля
# ===================================
class ChangePasswordRequest(BaseModel):
    current_password: str = Field(..., description="Текущий пароль")
    new_password: str = Field(
        ...,
        min_length=8,
        max_length=128,
        description="Новый пароль"
    )
    confirm_password: str = Field(..., description="Подтверждение нового пароля")

    @field_validator('new_password')
    @classmethod
    def validate_new_password(cls, v: str) -> str:
        if not any(c.isupper() for c in v):
            raise ValueError('Пароль должен содержать хотя бы одну заглавную букву')
        if not any(c.isdigit() for c in v):
            raise ValueError('Пароль должен содержать хотя бы одну цифру')
        if not any(c in '@$!%*?&' for c in v):
            raise ValueError('Пароль должен содержать спец. символ (@$!%*?&)')
        return v

    @field_validator('confirm_password')
    @classmethod
    def passwords_match(cls, v: str, values) -> str:
        if 'new_password' in values and v != values['new_password']:
            raise ValueError('Пароли не совпадают')
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
                    "email": "john.doe@example.com",
                    "role": "engineer",
                    "is_active": True,
                    "first_name": "John",
                    "last_name": "Doe",
                    "department": "Engineering",
                    "position": "Senior Software Engineer",
                    "created_at": "2026-02-04T10:00:00Z",
                    "updated_at": "2026-02-04T10:00:00Z"
                }
            }
        }
    )


# ===================================
# RefreshTokenRequest — обновление access token
# ===================================
class RefreshTokenRequest(BaseModel):
    refresh_token: str = Field(..., description="Refresh token")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "refresh_token": "a1b2c3d4e5f6..."
            }
        }
    )


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
    purpose: OTPPurposeEnum = Field(..., description="Цель OTP")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "email": "john.doe@example.com",
                "purpose": "login"
            }
        }
    )


# ===================================
# OTPVerify — верификация OTP кода
# ===================================
class OTPVerify(BaseModel):
    email: EmailStr = Field(..., description="Email пользователя")
    code: str = Field(..., min_length=4, max_length=128, description="OTP код")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "email": "john.doe@example.com",
                "code": "123456"
            }
        }
    )


# ===================================
# PasswordResetRequest — запрос на сброс пароля
# ===================================
class PasswordResetRequest(BaseModel):
    email: EmailStr = Field(..., description="Email пользователя")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "email": "john.doe@example.com"
            }
        }
    )


# ===================================
# PasswordResetConfirm — подтверждение сброса п��роля
# ===================================
class PasswordResetConfirm(BaseModel):
    email: EmailStr = Field(..., description="Email пользователя")
    code: str = Field(..., description="OTP код из письма")
    new_password: str = Field(
        ...,
        min_length=8,
        max_length=128,
        description="Новый пароль"
    )
    confirm_password: str = Field(..., description="Подтверждение пароля")

    @field_validator('new_password')
    @classmethod
    def validate_password(cls, v: str) -> str:
        if not any(c.isupper() for c in v):
            raise ValueError('Пароль должен содержать хотя бы одну заглавную букву')
        if not any(c.isdigit() for c in v):
            raise ValueError('Пароль должен содержать хотя бы одну цифру')
        if not any(c in '@$!%*?&' for c in v):
            raise ValueError('Пароль должен содержать спец. символ (@$!%*?&)')
        return v

    @field_validator('confirm_password')
    @classmethod
    def passwords_match(cls, v: str, values) -> str:
        if 'new_password' in values and v != values['new_password']:
            raise ValueError('Пароли не совпадают')
        return v


# ===================================
# SessionRead — информация о сессии
# ===================================
class SessionRead(BaseModel):
    id: int
    user_id: int
    user_agent: Optional[str]
    ip_address: Optional[str]
    created_at: datetime
    updated_at: datetime
    expires_at: datetime
    is_revoked: bool
    last_used_at: Optional[datetime]

    model_config = ConfigDict(from_attributes=True)


# ===================================
# SessionCreate — создание сессии
# ===================================
class SessionCreate(BaseModel):
    user_agent: Optional[str] = None
    ip_address: Optional[str] = None


# ===================================
# ErrorResponse — стандартный ответ об ошибке
# ===================================
class ErrorResponse(BaseModel):
    detail: str = Field(..., description="Описание ошибки")
    code: Optional[str] = Field(None, description="Код ошибки")
    error_id: Optional[str] = Field(None, description="ID ошибки для трейса")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "detail": "Invalid credentials",
                "code": "INVALID_CREDENTIALS",
                "error_id": "err_123456789"
            }
        }
    )


# ===================================
# PaginatedResponse — пагинированный ответ
# ===================================
T = TypeVar("T")
class PaginatedResponse[T](BaseModel, Generic[T]):
    data: list[T] = Field(..., description="Список элементов")
    total: int = Field(..., description="Общее количество элементов")
    page: int = Field(..., description="Номер текущей страницы")
    page_size: int = Field(..., description="Размер страницы")
    pages: int = Field(..., description="Общее количество страниц")

    @property
    def has_next(self) -> bool:
        return self.page < self.pages

    @property
    def has_prev(self) -> bool:
        return self.page > 1