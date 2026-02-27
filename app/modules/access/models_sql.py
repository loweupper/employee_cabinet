from sqlalchemy import Column, Integer, String, Enum, ForeignKey, Text
from sqlalchemy.orm import relationship
from core.database import Base
import enum
from core.constants import UserRole

class ACLEffect(str, enum.Enum):
    ALLOW = "allow"
    DENY = "deny"

class PermissionType(str, enum.Enum):
    READ = "read"
    WRITE = "write"
    DELETE = "delete"
    CREATE = "create"
    ADMIN = "admin"

class ACL(Base):
    __tablename__ = "acls"
    
    id = Column(Integer, primary_key=True)
    resource_type = Column(String(50), nullable=False, index=True)
    resource_id = Column(Integer, nullable=False, index=True)
    
    # Subject (кто получает доступ)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    role = Column(Enum(UserRole), nullable=True, index=True)
    department = Column(String(100), nullable=True)
    position = Column(String(100), nullable=True)
    location = Column(String(100), nullable=True)
    object_id = Column(Integer, nullable=True)
    
    permission = Column(Enum(PermissionType), nullable=False)
    effect = Column(Enum(ACLEffect), nullable=False, default=ACLEffect.ALLOW)
    
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    description = Column(Text, nullable=True)
    
    # Relationships
    user = relationship("User", foreign_keys=[user_id])
    creator = relationship("User", foreign_keys=[created_by])