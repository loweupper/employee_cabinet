from sqlalchemy.orm import Session
from modules.documents.models import DocumentCategoryMapping
import logging

logger = logging.getLogger(__name__)


class CategoryMappingService:
    """Сервис для управления маппингами категорий документов на отделы"""

    @staticmethod
    def get_mapping(db: Session, category: str) -> DocumentCategoryMapping:
        """Получить маппинг категории"""
        return db.query(DocumentCategoryMapping).filter(
            DocumentCategoryMapping.category == category
        ).first()

    @staticmethod
    def get_all_mappings(db: Session) -> list:
        """Получить все маппинги"""
        return db.query(DocumentCategoryMapping).all()

    @staticmethod
    def create_mapping(db: Session, category: str, department_id: int = None, description: str = None):
        """Создать маппинг"""
        mapping = DocumentCategoryMapping(
            category=category,
            department_id=department_id,
            description=description
        )
        db.add(mapping)
        db.commit()
        return mapping

    @staticmethod
    def update_mapping(db: Session, category: str, department_id: int = None, description: str = None):
        """Обновить маппинг"""
        mapping = db.query(DocumentCategoryMapping).filter(
            DocumentCategoryMapping.category == category
        ).first()

        if mapping:
            mapping.department_id = department_id
            if description is not None:
                mapping.description = description
            db.commit()
        return mapping

    @staticmethod
    def get_mapping_dict(db: Session) -> dict:
        """Получить маппинги в виде словаря для совместимости со старым кодом"""
        mappings = db.query(DocumentCategoryMapping).all()
        return {m.category: m.department_id for m in mappings if m.department_id}
