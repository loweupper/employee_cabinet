# core/constants.py
"""
Единый справочник констант для всего проекта
"""

from enum import Enum
from typing import Optional, Dict, Any


# ===================================
# Роли пользователей
# ===================================
class UserRole(str, Enum):
    """Роли пользователей в системе"""
    ADMIN = "admin"
    ACCOUNTANT = "accountant"
    HR = "hr"
    ENGINEER = "engineer"
    LAWYER = "lawyer"
    SAFETY = "safety"
    EMPLOYEE = "employee"

    @classmethod
    def has_role(cls, role: str) -> bool:
        """Проверка существования роли"""
        return role in cls._value2member_map_


# ===================================
# Категории документов
# ===================================
class DocumentCategory(str, Enum):
    """Категории документов (соответствуют разделам)"""
    GENERAL = "general"
    ACCOUNTING = "accounting"
    SAFETY = "safety"
    TECHNICAL = "technical"
    LEGAL = "legal"
    HR = "hr"

    @property
    def emoji(self) -> str:
        """Эмодзи для категории"""
        return CATEGORY_DISPLAY.get(self.value, {}).get("emoji", "📄")

    @property
    def display_name(self) -> str:
        """Отображаемое название"""
        return CATEGORY_DISPLAY.get(self.value, {}).get("name", self.value.capitalize())


# ===================================
# Отделы (названия в БД)
# ===================================
class DepartmentName(str, Enum):
    """Названия отделов в системе (хранятся в БД)"""
    ACCOUNTING = "Бухгалтерия"
    HR = "Отдел кадров"
    TECHNICAL = "Технический отдел"
    LEGAL = "Юридический"
    SAFETY = "Охрана труда"
    # Отделы без специального доступа
    GENERAL = "Общий отдел"
    ADMIN = "Администрация"


# ===================================
# МАППИНГИ (единые справочники)
# ===================================

# 1. Маппинг: роль → соответствующий отдел
ROLE_TO_DEPARTMENT: Dict[UserRole, Optional[DepartmentName]] = {
    UserRole.ACCOUNTANT: DepartmentName.ACCOUNTING,
    UserRole.HR: DepartmentName.HR,
    UserRole.ENGINEER: DepartmentName.TECHNICAL,
    UserRole.LAWYER: DepartmentName.LEGAL,
    UserRole.SAFETY: DepartmentName.SAFETY,
    UserRole.ADMIN: None,  # Админ может быть без отдела
    UserRole.EMPLOYEE: None,  # Обычный сотрудник без специального отдела
}

# 2. Маппинг: категория документа → соответствующий отдел
CATEGORY_TO_DEPARTMENT: Dict[DocumentCategory, Optional[DepartmentName]] = {
    DocumentCategory.GENERAL: None,  # Доступно всем
    DocumentCategory.ACCOUNTING: DepartmentName.ACCOUNTING,
    DocumentCategory.SAFETY: DepartmentName.SAFETY,
    DocumentCategory.TECHNICAL: DepartmentName.TECHNICAL,
    DocumentCategory.LEGAL: DepartmentName.LEGAL,
    DocumentCategory.HR: DepartmentName.HR,
}

# 3. Обратный маппинг: отдел → категория документа
DEPARTMENT_TO_CATEGORY: Dict[DepartmentName, DocumentCategory] = {
    DepartmentName.ACCOUNTING: DocumentCategory.ACCOUNTING,
    DepartmentName.HR: DocumentCategory.HR,
    DepartmentName.TECHNICAL: DocumentCategory.TECHNICAL,
    DepartmentName.LEGAL: DocumentCategory.LEGAL,
    DepartmentName.SAFETY: DocumentCategory.SAFETY,
}


# ===================================
# Отображение для UI
# ===================================

# Информация для отображения категорий
CATEGORY_DISPLAY: Dict[str, Dict[str, str]] = {
    "general": {"emoji": "📋", "name": "Общие"},
    "technical": {"emoji": "📐", "name": "Технические"},
    "accounting": {"emoji": "💰", "name": "Бухгалтерия"},
    "safety": {"emoji": "👷", "name": "Охрана труда"},
    "legal": {"emoji": "⚖️", "name": "Юридические"},
    "hr": {"emoji": "👔", "name": "Кадровые"},
}

# Информация для отображения ролей
ROLE_DISPLAY: Dict[str, Dict[str, str]] = {
    "admin": {"emoji": "👑", "name": "Администратор"},
    "accountant": {"emoji": "💰", "name": "Бухгалтер"},
    "hr": {"emoji": "👔", "name": "HR-специалист"},
    "engineer": {"emoji": "🔧", "name": "Инженер"},
    "lawyer": {"emoji": "⚖️", "name": "Юрист"},
    "safety": {"emoji": "👷", "name": "Специалист по охране труда"},
    "employee": {"emoji": "👤", "name": "Сотрудник"},
}


# ===================================
# Вспомогательные функции
# ===================================

def get_department_for_role(role: UserRole) -> Optional[str]:
    """
    Получить название отдела для роли
    """
    dept = ROLE_TO_DEPARTMENT.get(role)
    return dept.value if dept else None


def get_category_for_department(dept_name: str) -> Optional[DocumentCategory]:
    """
    Получить категорию документа по названию отдела
    """
    try:
        dept = DepartmentName(dept_name)
        return DEPARTMENT_TO_CATEGORY.get(dept)
    except ValueError:
        return None


def get_role_display(role: str) -> Dict[str, str]:
    """
    Получить отображаемые данные для роли
    """
    return ROLE_DISPLAY.get(role, {"emoji": "❓", "name": role})


def get_category_display(category: str) -> Dict[str, str]:
    """
    Получить отображаемые данные для категории
    """
    return CATEGORY_DISPLAY.get(category, {"emoji": "📄", "name": category})