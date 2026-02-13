from pydantic import BaseModel, Field, ConfigDict
from typing import Optional
from datetime import datetime
from enum import Enum


# ===================================
# Enum для категории
# ===================================
class DocumentCategoryEnum(str, Enum):
    GENERAL = "general"
    ACCOUNTING = "accounting"
    SAFETY = "safety"
    TECHNICAL = "technical"
    LEGAL = "legal"
    HR = "hr"


# Человекочитаемые названия
CATEGORY_LABELS = {
    DocumentCategoryEnum.GENERAL: "📋 Общие",
    DocumentCategoryEnum.ACCOUNTING: "💰 Бухгалтерия",
    DocumentCategoryEnum.SAFETY: "👷 Охрана труда",
    DocumentCategoryEnum.TECHNICAL: "📐 Технические",
    DocumentCategoryEnum.LEGAL: "⚖️ Юридические",
    DocumentCategoryEnum.HR: "👔 Кадровые",
}

# ===================================
# DocumentSubcategoryCreate
# ===================================
class DocumentSubcategoryCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    category: DocumentCategoryEnum

# ===================================
# DocumentSubcategoryUpdate
# ===================================
class DocumentSubcategoryUpdate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None

# ===================================
# DocumentSubcategoryRead
# ===================================
class DocumentSubcategoryRead(BaseModel):
    id: int
    name: str
    description: Optional[str]
    category: DocumentCategoryEnum
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

# ===================================
# DocumentCreate
# ===================================
class DocumentCreate(BaseModel):
    title: str = Field(..., min_length=3, max_length=255)
    description: Optional[str] = None
    category: DocumentCategoryEnum = DocumentCategoryEnum.GENERAL
    subcategory_id: Optional[int] = None
    object_id: int


# ===================================
# DocumentRead
# ===================================
class DocumentRead(BaseModel):
    id: int
    title: str
    description: Optional[str]
    category: DocumentCategoryEnum
    subcategory_id: Optional[int]
    file_name: str
    file_size: int
    file_type: Optional[str]
    object_id: int
    created_by: int
    version: int
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
    
    @property
    def category_label(self) -> str:
        return CATEGORY_LABELS.get(self.category, self.category)
    
    @property
    def file_size_mb(self) -> float:
        return round(self.file_size / (1024 * 1024), 2)