from pydantic import BaseModel, Field, ConfigDict, field_validator
from typing import Optional, List
from datetime import datetime
from enum import Enum


# ===================================
# Enum для роли доступа
# ===================================
class ObjectAccessRoleEnum(str, Enum):
    OWNER = "owner"     # Владелец объекта
    ADMIN = "admin"     # Администратор объекта 
    EDITOR = "editor"   # Редактор объекта
    VIEWER = "viewer"   # Просмотрщик объекта (только чтение)


# ===================================
# Enum для разделов документов
# ===================================
class DocumentSectionEnum(str, Enum):
    GENERAL = "general"        # Общие
    TECHNICAL = "technical"    # Технические
    ACCOUNTING = "accounting"  # Бухгалтерия
    SAFETY = "safety"          # Охрана труда
    LEGAL = "legal"            # Юридические
    HR = "hr"                  # Кадровые


# ===================================
# ObjectAccessCreate (обновлено)
# ===================================
class ObjectAccessCreate(BaseModel):
    user_id: int
    role: ObjectAccessRoleEnum = ObjectAccessRoleEnum.VIEWER
    sections_access: List[str] = Field(default=["general"]) 
    
    @field_validator('sections_access')
    @classmethod
    def validate_sections(cls, v):
        """Проверяем, что general всегда включен"""
        if "general" not in v:
            v.append("general")
        return v


# ===================================
# ObjectAccessUpdate (новое)
# ===================================
class ObjectAccessUpdate(BaseModel):
    role: Optional[ObjectAccessRoleEnum] = None
    sections_access: Optional[List[str]] = None
    
    @field_validator('sections_access')
    @classmethod
    def validate_sections(cls, v):
        """Проверяем, что general всегда включен"""
        if v and "general" not in v:
            v.append("general")
        return v


# ===================================
# ObjectAccessRead
# ===================================
class ObjectAccessRead(BaseModel):
    id: int
    object_id: int
    user_id: int
    role: ObjectAccessRoleEnum
    sections_access: List[str]
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


# ===================================
# ObjectCreate (без изменений)
# ===================================
class ObjectCreate(BaseModel):
    title: str = Field(..., min_length=3, max_length=255)
    address: Optional[str] = Field(None, max_length=500)
    description: Optional[str] = None
    icon_url: Optional[str] = Field(None, max_length=500)
    department: Optional[str] = Field(None, max_length=255)
    location: Optional[str] = Field(None, max_length=255)


# ===================================
# ObjectUpdate
# ===================================
class ObjectUpdate(BaseModel):
    title: Optional[str] = Field(None, min_length=3, max_length=255)
    address: Optional[str] = Field(None, max_length=500)
    description: Optional[str] = None
    icon_url: Optional[str] = Field(None, max_length=500)
    department: Optional[str] = Field(None, max_length=255)
    location: Optional[str] = Field(None, max_length=255)
    is_active: Optional[bool] = None
    is_archived: Optional[bool] = None


# ===================================
# ObjectRead
# ===================================
class ObjectRead(BaseModel):
    id: int
    title: str
    address: Optional[str]
    description: Optional[str]
    icon_url: Optional[str]
    department: Optional[str]
    location: Optional[str]
    created_by: int
    is_active: bool
    is_archived: bool
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)