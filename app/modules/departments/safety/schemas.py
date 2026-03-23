from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


class SafetyProfileCreate(BaseModel):
    user_id: Optional[int] = None
    is_external: bool = False

    first_name: Optional[str] = Field(default=None, max_length=255)
    last_name: Optional[str] = Field(default=None, max_length=255)
    middle_name: Optional[str] = Field(default=None, max_length=255)
    full_name: Optional[str] = Field(default=None, min_length=2, max_length=255)
    email: Optional[str] = Field(default=None, max_length=255)
    position: Optional[str] = Field(default=None, max_length=255)
    department_name: Optional[str] = Field(default=None, max_length=255)
    phone: Optional[str] = Field(default=None, max_length=20)
    avatar_url: Optional[str] = Field(default=None, max_length=512)
    note: Optional[str] = None

    object_id: Optional[int] = None

    @field_validator("full_name")
    @classmethod
    def strip_full_name(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class SafetyProfileUpdate(BaseModel):
    user_id: Optional[int] = None
    full_name: Optional[str] = Field(default=None, min_length=2, max_length=255)
    email: Optional[str] = Field(default=None, max_length=255)
    position: Optional[str] = Field(default=None, max_length=255)
    department_name: Optional[str] = Field(default=None, max_length=255)
    phone: Optional[str] = Field(default=None, max_length=20)
    avatar_url: Optional[str] = Field(default=None, max_length=512)
    note: Optional[str] = None

    @field_validator("full_name")
    @classmethod
    def strip_full_name_update(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class SafetyProfileRead(BaseModel):
    id: int
    user_id: Optional[int] = None
    is_external: bool

    first_name: Optional[str] = None
    last_name: Optional[str] = None
    middle_name: Optional[str] = None
    full_name: str
    email: Optional[str] = None
    position: Optional[str] = None
    department_name: Optional[str] = None
    phone: Optional[str] = None
    avatar_url: Optional[str] = None
    note: Optional[str] = None

    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class SafetyDocumentAccessGrant(BaseModel):
    document_id: int
    user_id: Optional[int] = None
    department_id: Optional[int] = None
    role: Optional[str] = None
    object_id: Optional[int] = None
    all_company: bool = False


class SafetyDocumentMetadataUpdate(BaseModel):
    document_id: int
    expiry_date: Optional[date] = None
    reminder_days: Optional[int] = Field(default=None, ge=1, le=365)
    is_department_common: bool = False
