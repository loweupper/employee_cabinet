from fastapi import HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import or_, and_
from typing import List, Tuple, Optional
import logging

from modules.objects.models import Object, ObjectAccess, ObjectAccessRole
from modules.objects.schemas import ObjectAccessUpdate, ObjectCreate, ObjectUpdate, ObjectAccessCreate
from modules.auth.models import User
from core.constants import UserRole  # ✅ Добавить импорт

logger = logging.getLogger("app")


class ObjectService:
    """Бизнес-логика для работы с объектами"""
    
    # =================================== Создание объекта ============================================
    @staticmethod
    def create_object(data: ObjectCreate, user: User, db: Session) -> Object:
        """
        Создать новый объект
        """
        # Создаем объект
        obj = Object(
            title=data.title,
            address=data.address,
            description=data.description,
            department=data.department,
            location=data.location,
            created_by=user.id
        )
        
        db.add(obj)
        db.commit()
        db.refresh(obj)
        
        # Создаем доступ для владельца
        access = ObjectAccess(
            object_id=obj.id,
            user_id=user.id,
            role=ObjectAccessRole.OWNER,
            sections_access=["general", "technical", "accounting", "safety", "legal", "hr"],
            granted_by=user.id
        )
        
        db.add(access)
        db.commit()
        
        logger.info({
            "event": "object_created",
            "object_id": obj.id,
            "title": obj.title,
            "created_by": user.id
        })
        
        return obj
    
    # =================================== Получение списка объектов ============================================
    @staticmethod
    def list_objects(
        user: User,
        db: Session,
        skip: int = 0,
        limit: int = 20,
        search: Optional[str] = None,
        department: Optional[str] = None,
        status: Optional[str] = None
    ) -> Tuple[List[Object], int]:
        """
        Получить список объектов доступных пользователю
        """
        # Базовый запрос
        query = db.query(Object).join(
            ObjectAccess,
            and_(
                ObjectAccess.object_id == Object.id,
                ObjectAccess.user_id == user.id
            )
        ).filter(
            Object.deleted_at == None
        )
        
        # Фильтр по статусу
        if status == "active":
            query = query.filter(
                Object.is_active == True,
                Object.is_archived == False
            )
        elif status == "inactive":
            if user.role == UserRole.ADMIN:  # ✅ используем Enum
                query = db.query(Object).filter(
                    Object.is_active == False,
                    Object.is_archived == False,
                    Object.deleted_at == None
                )
            else:
                query = db.query(Object).filter(
                    Object.created_by == user.id,
                    Object.is_active == False,
                    Object.is_archived == False,
                    Object.deleted_at == None
                )
        elif status == "archived":
            query = query.filter(
                Object.is_archived == True
            )
        else:
            query = query.filter(
                Object.is_active == True,
                Object.is_archived == False
            )
        
        # Фильтр по поиску
        if search:
            query = query.filter(
                or_(
                    Object.title.ilike(f"%{search}%"),
                    Object.address.ilike(f"%{search}%"),
                    Object.description.ilike(f"%{search}%")
                )
            )
        
        # Фильтр по отделу
        if department:
            query = query.filter(Object.department == department)
        
        # Общее количество
        total = query.count()
        
        # Получаем с пагинацией
        objects = query.order_by(Object.created_at.desc()).offset(skip).limit(limit).all()
        
        return objects, total
    
    # =================================== Проверка прав управления ============================================
    @staticmethod
    def can_manage_access(user: User, object_id: int, db: Session) -> bool:
        """
        Проверить, может ли пользователь управлять доступом к объекту
        """
        obj = db.query(Object).filter(Object.id == object_id).first()
        if not obj:
            return False
    
        # 1. Создатель объекта
        if obj.created_by == user.id:
            return True
    
        # 2. Глобальный админ
        if user.role == UserRole.ADMIN:
            return True
    
        # 3. Проверка через ObjectAccess
        admin_access = db.query(ObjectAccess).filter(
            ObjectAccess.object_id == object_id,
            ObjectAccess.user_id == user.id,
            ObjectAccess.role.in_([ObjectAccessRole.OWNER, ObjectAccessRole.ADMIN])
        ).first()
    
        if admin_access:
            return True
    
        # 4. Проверка через ACL
        try:
            from modules.access.service import AccessService
            from modules.access.models import PermissionType
        
            return AccessService.has_access(
                user=user,
                resource_type="object",
                resource_id=object_id,
                permission=PermissionType.ADMIN,
                db=db
            )
        except ImportError:
            return False

    # =================================== Получение объекта ============================================
    @staticmethod
    def get_object(object_id: int, user: User, db: Session) -> Object:
        """
        Получить объект по ID (с проверкой доступа)
        """
        obj = db.query(Object).filter(Object.id == object_id).first()
        
        if not obj or obj.deleted_at:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Объект не найден"
            )
        
        # Неактивные — только владелец + админ
        if not obj.is_active and not obj.is_archived:
            if obj.created_by != user.id and user.role != UserRole.ADMIN:  # ✅ используем Enum
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Объект неактивен. Доступ только для владельца и администратора."
                )
        
        # Проверяем доступ через ObjectAccess
        access = db.query(ObjectAccess).filter(
            ObjectAccess.object_id == object_id,
            ObjectAccess.user_id == user.id
        ).first()
        
        if not access and user.role != UserRole.ADMIN:  # ✅ используем Enum
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Нет доступа к этому объекту"
            )
        
        return obj
    
    # =================================== Редактирование объекта ============================================
    @staticmethod
    def update_object(
        object_id: int,
        data: ObjectUpdate,
        user: User,
        db: Session
    ) -> Object:
        """
        Обновить объект
        """
        access = db.query(ObjectAccess).filter(
            ObjectAccess.object_id == object_id,
            ObjectAccess.user_id == user.id,
            ObjectAccess.role.in_([ObjectAccessRole.EDITOR, ObjectAccessRole.ADMIN, ObjectAccessRole.OWNER])
        ).first()
        
        if not access and user.role != UserRole.ADMIN:  # ✅ используем Enum
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Недостаточно прав для редактирования"
            )
        
        obj = db.query(Object).filter(Object.id == object_id).first()
        
        if not obj:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Объект не найден"
            )
        
        for field, value in data.dict(exclude_unset=True).items():
            setattr(obj, field, value)
        
        obj.updated_by = user.id
        
        db.commit()
        db.refresh(obj)
        
        logger.info({
            "event": "object_updated",
            "object_id": obj.id,
            "updated_by": user.id
        })
        
        return obj
    
    # =================================== Предоставление доступа ============================================
    @staticmethod
    def grant_access(
        object_id: int,
        data: ObjectAccessCreate,
        user: User,
        db: Session
    ) -> ObjectAccess:
        """
        Предоставить доступ пользователю к объекту
        """
        obj = db.query(Object).filter(Object.id == object_id).first()
        
        if not obj:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Объект не найден"
            )
        
        # ✅ УНИВЕРСАЛЬНАЯ ПРОВЕРКА ПРАВ (одна!)
        if not ObjectService.can_manage_access(user, object_id, db):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Недостаточно прав для управления доступом"
            )
        
        # Проверяем, нет ли уже доступа
        existing = db.query(ObjectAccess).filter(
            ObjectAccess.object_id == object_id,
            ObjectAccess.user_id == data.user_id
        ).first()
        
        if existing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="У пользователя уже есть доступ к этому объекту"
            )
        
        # Получаем пользователя
        target_user = db.query(User).filter(User.id == data.user_id).first()
        
        if not target_user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Пользователь не найден"
            )
        
        # Добавляем автоматический доступ к разделу по отделу
        sections = list(data.sections_access)
        
        if target_user.department_rel and target_user.department_rel.name:
            from modules.objects.models import DEPARTMENT_SECTION_MAP
            # ✅ Используем название отдела, а не ID
            auto_section = DEPARTMENT_SECTION_MAP.get(target_user.department_rel.name)
            if auto_section and auto_section.value not in sections:
                sections.append(auto_section.value)
        
        # Создаём доступ
        access = ObjectAccess(
            object_id=object_id,
            user_id=data.user_id,
            role=data.role,
            sections_access=sections,
            granted_by=user.id
        )
        
        db.add(access)
        db.commit()
        db.refresh(access)
        
        logger.info({
            "event": "access_granted",
            "object_id": object_id,
            "user_id": data.user_id,
            "role": data.role.value,
            "sections": sections,
            "granted_by": user.id
        })
        
        return access
    
    # =================================== Обновление доступа ============================================
    @staticmethod
    def update_access(
        object_id: int,
        user_id: int,
        data: ObjectAccessUpdate,
        current_user: User,
        db: Session
    ) -> ObjectAccess:
        """
        Обновить доступ пользователя к объекту
        """
        obj = db.query(Object).filter(Object.id == object_id).first()
        
        if not obj:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Объект не найден"
            )
        
        # Проверяем права
        if obj.created_by != current_user.id and current_user.role != UserRole.ADMIN:  # ✅ используем Enum
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Недостаточно прав"
            )
        
        # Находим доступ
        access = db.query(ObjectAccess).filter(
            ObjectAccess.object_id == object_id,
            ObjectAccess.user_id == user_id
        ).first()
        
        if not access:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Доступ не найден"
            )
        
        # Нельзя изменить доступ владельца
        if access.role == ObjectAccessRole.OWNER:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Нельзя изменить доступ владельца"
            )
        
        # Обновляем
        if data.role:
            access.role = data.role
        
        if data.sections_access:
            access.sections_access = data.sections_access
        
        db.commit()
        db.refresh(access)
        
        logger.info({
            "event": "access_updated",
            "object_id": object_id,
            "user_id": user_id,
            "updated_by": current_user.id
        })
        
        return access
    
    # =================================== Отзыв доступа ============================================
    @staticmethod
    def revoke_access(
        object_id: int,
        user_id: int,
        current_user: User,
        db: Session
    ):
        """
        Отозвать доступ пользователя к объекту
        """
        access = db.query(ObjectAccess).filter(
            ObjectAccess.object_id == object_id,
            ObjectAccess.user_id == current_user.id,
            ObjectAccess.role.in_([ObjectAccessRole.ADMIN, ObjectAccessRole.OWNER])
        ).first()
        
        if not access and current_user.role != UserRole.ADMIN:  # ✅ используем Enum
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Недостаточно прав для управления доступом"
            )
        
        target_access = db.query(ObjectAccess).filter(
            ObjectAccess.object_id == object_id,
            ObjectAccess.user_id == user_id
        ).first()
        
        if not target_access:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Доступ не найден"
            )
        
        if target_access.role == ObjectAccessRole.OWNER:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Нельзя отозвать доступ у владельца"
            )
        
        db.delete(target_access)
        db.commit()
        
        logger.info({
            "event": "object_access_revoked",
            "object_id": object_id,
            "user_id": user_id,
            "revoked_by": current_user.id
        })
        
        return {"message": "Доступ отозван"}
    
    # =================================== Удаление объекта ============================================
    @staticmethod
    def delete_object(
        object_id: int,
        user: User,
        db: Session
    ):
        """
        Удалить объект (soft delete)
        """
        obj = db.query(Object).filter(Object.id == object_id).first()
        
        if not obj:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Объект не найден"
            )
        
        if obj.created_by != user.id and user.role != UserRole.ADMIN:  # ✅ используем Enum
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Недостаточно прав для удаления"
            )
        
        from datetime import datetime
        obj.deleted_at = datetime.utcnow()
        obj.is_active = False
        
        db.commit()
        
        logger.info({
            "event": "object_deleted",
            "object_id": object_id,
            "deleted_by": user.id
        })
        
        return {"message": "Объект удален"}
    
    # =================================== Восстановление объекта ============================================
    @staticmethod
    def restore_object(
        object_id: int,
        user: User,
        db: Session
    ) -> Object:
        """
        Восстановить удаленный объект (только админ)
        """
        if user.role != UserRole.ADMIN:  # ✅ используем Enum
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Только администратор может восстанавливать объекты"
            )
        
        obj = db.query(Object).filter(Object.id == object_id).first()
        
        if not obj:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Объект не найден"
            )
        
        obj.deleted_at = None
        obj.is_active = True
        
        db.commit()
        db.refresh(obj)
        
        logger.info({
            "event": "object_restored",
            "object_id": object_id,
            "restored_by": user.id
        })
        
        return obj
    
    # =================================== Список всех объектов (админ) ============================================
    @staticmethod
    def list_all_objects_admin(
        db: Session,
        skip: int = 0,
        limit: int = 50,
        search: Optional[str] = None,
        include_deleted: bool = False
    ) -> Tuple[List[Object], int]:
        """
        Получить список ВСЕХ объектов (только для админа)
        """
        query = db.query(Object)
        
        if not include_deleted:
            query = query.filter(Object.deleted_at == None)
        
        if search:
            query = query.filter(
                or_(
                    Object.title.ilike(f"%{search}%"),
                    Object.address.ilike(f"%{search}%")
                )
            )
        
        total = query.count()
        objects = query.order_by(Object.created_at.desc()).offset(skip).limit(limit).all()
        
        return objects, total
    
    # =================================== Список доступов к объекту ============================================
    @staticmethod
    def list_object_accesses(
        object_id: int,
        user: User,
        db: Session
    ) -> List[ObjectAccess]:
        """
        Получить список доступов к объекту
        """
        # Проверяем доступ к объекту
        obj = ObjectService.get_object(object_id, user, db)
        
        # Получаем все доступы к объекту
        accesses = db.query(ObjectAccess).filter(
            ObjectAccess.object_id == object_id
        ).order_by(ObjectAccess.created_at.desc()).all()
        
        return accesses
    

    @staticmethod
    def sync_user_access_by_role(user: User, db: Session):
        """
        Обновить доступы пользователя ко всем объектам на основе его роли
        """
        # Маппинг роли на раздел документов
        role_to_section = {
            UserRole.ACCOUNTANT: "accounting",
            UserRole.HR: "hr",
            UserRole.ENGINEER: "technical",
            UserRole.LAWYER: "legal",
            # UserRole.SAFETY: "safety"  # если добавите
        }
    
        # Если у роли нет соответствующего раздела - ничего не делаем
        if user.role not in role_to_section:
            return
    
        new_section = role_to_section[user.role]
    
        # Получаем все доступы пользователя к объектам
        accesses = db.query(ObjectAccess).filter(
            ObjectAccess.user_id == user.id
        ).all()
    
        updated_count = 0
        for access in accesses:
            current_sections = access.sections_access or ["general"]
        
            # Добавляем новый раздел, если его ещё нет
            if new_section not in current_sections:
                current_sections.append(new_section)
                access.sections_access = current_sections
                updated_count += 1
    
        db.commit()
    
        logger.info({
            "event": "user_access_synced_by_role",
            "user_id": user.id,
            "user_role": user.role.value,
            "new_section": new_section,
            "updated_accesses": updated_count
        })

    @staticmethod
    def sync_user_access_by_department(user: User, db: Session):
        """
        Обновить доступы пользователя ко всем объектам на основе его отдела
        """
        if not user.department_rel:
            return
    
        # Маппинг названия отдела на раздел документов
        department_to_section = {
            "Бухгалтерия": "accounting",
            "Отдел кадров": "hr",
            "Технический отдел": "technical",
            "Юридический": "legal",
            "Охрана труда": "safety"
        }
    
        dept_name = user.department_rel.name
        if dept_name not in department_to_section:
            return
    
        new_section = department_to_section[dept_name]
    
        # Получаем все доступы пользователя к объектам
        accesses = db.query(ObjectAccess).filter(
            ObjectAccess.user_id == user.id
        ).all()
    
        updated_count = 0
        for access in accesses:
            current_sections = access.sections_access or ["general"]
        
            # Добавляем новый раздел, если его ещё нет
            if new_section not in current_sections:
                current_sections.append(new_section)
                access.sections_access = current_sections
                updated_count += 1
    
        db.commit()
    
        logger.info({
            "event": "user_access_synced_by_department",
            "user_id": user.id,
            "department": dept_name,
            "new_section": new_section,
            "updated_accesses": updated_count
        })