from typing import Optional, List
from functools import lru_cache
from sqlalchemy import and_, or_
from sqlalchemy.orm import Session
from modules.access.models_sql import ACL, ACLEffect, PermissionType  
from modules.auth.models import User, UserRole
import redis
import json


class AccessService:
    """
    Сервис проверки доступа с поддержкой RBAC + ABAC + ACL.
    Использует иерархию ролей, кэширование и оптимизированные запросы.
    """
    
    # Role hierarchy: более высокие роли наследуют права нижних
    ROLE_HIERARCHY = {
        UserRole.EMPLOYEE: [UserRole.EMPLOYEE],
        UserRole.ADMIN: [UserRole.ADMIN, UserRole.EMPLOYEE],
    }
    
    # Кэш (Redis или in-memory)
    def __init__(self, redis_client: Optional[redis.Redis] = None):
        self.redis = redis_client
    
    def _get_cache_key(self, user_id: int, resource_type: str, resource_id: int, permission: str) -> str:
        """Генерирует ключ для кэша"""
        return f"acl:{user_id}:{resource_type}:{resource_id}:{permission}"
    
    def _check_from_cache(self, cache_key: str) -> Optional[bool]:
        """Проверяет результат в кэше"""
        if not self.redis:
            return None
        try:
            result = self.redis.get(cache_key)
            return result == b"true" if result else None
        except Exception:
            return None  # Если Redis недоступен, пропускаем кэш
    
    def _set_cache(self, cache_key: str, result: bool, ttl: int = 3600):
        """Сохраняет результат в кэш (TTL 1 час по умолчанию)"""
        if not self.redis:
            return
        try:
            self.redis.setex(cache_key, ttl, "true" if result else "false")
        except Exception:
            pass  # Логировать в production
    
    def _invalidate_cache(self, user_id: int, resource_type: str = "*", resource_id: Optional[int] = None):
        """Инвалидирует кэш для пользователя"""
        if not self.redis:
            return
        try:
            if resource_id:
                pattern = f"acl:{user_id}:{resource_type}:{resource_id}:*"
            else:
                pattern = f"acl:{user_id}:{resource_type}:*:*"
            keys = self.redis.keys(pattern)
            if keys:
                self.redis.delete(*keys)
        except Exception:
            pass
    
    @staticmethod
    def has_access(
        user: User,
        resource_type: str,
        resource_id: int,
        permission: PermissionType,
        db: Session,
        redis_client: Optional[redis.Redis] = None
    ) -> bool:
        """
        Проверка доступа с оптимизацией и кэшированием.
        Порядок проверки:
        1. DENY правила (если есть — сразу False)
        2. ALLOW правила по иерархии (User → Role → Attributes)
        """
        
        service = AccessService(redis_client)
        cache_key = service._get_cache_key(user.id, resource_type, resource_id, permission.value)
        
        # Проверяем кэш
        cached_result = service._check_from_cache(cache_key)
        if cached_result is not None:
            return cached_result
        
        # Проверяем DENY правила в первую очередь
        deny_rule = db.query(ACL).filter(
            and_(
                ACL.resource_type == resource_type,
                ACL.resource_id == resource_id,
                ACL.permission == permission,
                ACL.effect == ACLEffect.DENY,
                or_(
                    ACL.user_id == user.id,
                    ACL.role.in_([r.value for r in service.ROLE_HIERARCHY.get(user.role, [user.role])]),
                    ACL.department == getattr(user, 'department', None),
                    ACL.position == getattr(user, 'position', None),
                    ACL.location == getattr(user, 'location', None),
                    ACL.object_id == getattr(user, 'object_id', None),
                )
            )
        ).first()
        
        if deny_rule:
            service._set_cache(cache_key, False)
            return False
        
        # Проверяем ALLOW правила (оптимизированный запрос)
        allow_rule = db.query(ACL).filter(
            and_(
                ACL.resource_type == resource_type,
                ACL.resource_id == resource_id,
                ACL.permission == permission,
                ACL.effect == ACLEffect.ALLOW,
                or_(
                    # 1. Конкретный пользователь
                    ACL.user_id == user.id,
                    # 2. Роль с учетом иерархии
                    ACL.role.in_([r.value for r in service.ROLE_HIERARCHY.get(user.role, [user.role])]),
                    # 3. ABAC атрибуты
                    ACL.department == getattr(user, 'department', None),
                    ACL.position == getattr(user, 'position', None),
                    ACL.location == getattr(user, 'location', None),
                    ACL.object_id == getattr(user, 'object_id', None),
                )
            )
        ).first()
        
        result = allow_rule is not None
        service._set_cache(cache_key, result)
        return result
    
    @staticmethod
    def grant_access(
        resource_type: str,
        resource_id: int,
        permission: PermissionType,
        db: Session,
        user_id: Optional[int] = None,
        role: Optional[UserRole] = None,
        department: Optional[str] = None,
        position: Optional[str] = None,
        location: Optional[str] = None,
        object_id: Optional[int] = None,
        created_by: Optional[int] = None,
        description: Optional[str] = None,
        redis_client: Optional[redis.Redis] = None,
    ) -> ACL:
        """Создать ALLOW правило"""
        
        acl_rule = ACL(
            resource_type=resource_type,
            resource_id=resource_id,
            user_id=user_id,
            role=role.value if role else None,
            department=department,
            position=position,
            location=location,
            object_id=object_id,
            permission=permission,
            effect=ACLEffect.ALLOW,
            created_by=created_by,
            description=description,
        )
        db.add(acl_rule)
        db.commit()
        
        # Инвалидируем кэш для затронутых пользователей
        if user_id:
            AccessService(redis_client)._invalidate_cache(user_id, resource_type, resource_id)
        
        return acl_rule
    
    @staticmethod
    def revoke_access(
        resource_type: str,
        resource_id: int,
        permission: PermissionType,
        db: Session,
        user_id: Optional[int] = None,
        role: Optional[UserRole] = None,
        redis_client: Optional[redis.Redis] = None,
    ) -> bool:
        """Удалить правило доступа"""
        
        filters = [
            ACL.resource_type == resource_type,
            ACL.resource_id == resource_id,
            ACL.permission == permission,
        ]
        
        if user_id is not None:
            filters.append(ACL.user_id == user_id)
        if role is not None:
            filters.append(ACL.role == role.value)
        
        rule = db.query(ACL).filter(*filters).first()
        if rule:
            db.delete(rule)
            db.commit()
            
            # Инвалидируем кэш
            if user_id is not None:
                AccessService(redis_client)._invalidate_cache(user_id, resource_type, resource_id)
            
            return True
        return False
    
    @staticmethod
    def get_user_permissions(
        user_id: int,
        resource_type: str,
        resource_id: int,
        db: Session,
    ) -> List[str]:
        """Получить все разрешения пользователя для ресурса"""
        
        # Получаем пользователя для проверки атрибутов
        user = db.query(User).filter_by(id=user_id).first()
        if not user:
            return []
        
        # Получаем все ALLOW правила (без DENY)
        permissions = set()
        
        allow_rules = db.query(ACL.permission).filter(
            and_(
                ACL.resource_type == resource_type,
                ACL.resource_id == resource_id,
                ACL.effect == ACLEffect.ALLOW,
                or_(
                    ACL.user_id == user_id,
                    ACL.role.in_([r.value for r in AccessService.ROLE_HIERARCHY.get(user.role, [user.role])]),
                    ACL.department == getattr(user, 'department', None),
                    ACL.position == getattr(user, 'position', None),
                    ACL.location == getattr(user, 'location', None),
                    ACL.object_id == getattr(user, 'object_id', None),
                )
            )
        ).all()
        
        for rule in allow_rules:
            permissions.add(rule.permission.value)
        
        # Удаляем те, которые запрещены DENY правилами
        deny_rules = db.query(ACL.permission).filter(
            and_(
                ACL.resource_type == resource_type,
                ACL.resource_id == resource_id,
                ACL.effect == ACLEffect.DENY,
                or_(
                    ACL.user_id == user_id,
                    ACL.role.in_([r.value for r in AccessService.ROLE_HIERARCHY.get(user.role, [user.role])]),
                    ACL.department == getattr(user, 'department', None),
                    ACL.position == getattr(user, 'position', None),
                    ACL.location == getattr(user, 'location', None),
                    ACL.object_id == getattr(user, 'object_id', None),
                )
            )
        ).all()
        
        for rule in deny_rules:
            permissions.discard(rule.permission.value)
        
        return list(permissions)