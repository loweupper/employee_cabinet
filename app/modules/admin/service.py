from typing import List, Optional
import logging
from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError
from modules.admin.models import CategoryDepartmentMapping

logger = logging.getLogger("app")


class CategoryMappingService:
    """Сервис для управления маппингом категорий на отделы"""

    @staticmethod
    def get_mapping(category: str, db: Session) -> Optional[CategoryDepartmentMapping]:
        """Получить маппинг для конкретной категории"""
        return db.query(CategoryDepartmentMapping).filter(
            CategoryDepartmentMapping.category == category
        ).first()

    @staticmethod
    def get_all_mappings(db: Session) -> List[CategoryDepartmentMapping]:
        """Получить все маппинги категорий"""
        return db.query(CategoryDepartmentMapping).all()

    @staticmethod
    def update_mapping(
        category: str, departments: List[str], db: Session
    ) -> Optional[CategoryDepartmentMapping]:
        """Обновить маппинг категории на отделы"""
        mapping = db.query(CategoryDepartmentMapping).filter(
            CategoryDepartmentMapping.category == category
        ).first()
        if mapping:
            try:
                mapping.departments = departments
                db.commit()
                db.refresh(mapping)
            except SQLAlchemyError as e:
                db.rollback()
                logger.error(f"Failed to update category mapping for '{category}': {e}")
                raise
        return mapping
