# /app/modules/departments/safety/models.py
"""Модели данных для управления безопасностью в департаментах."""
from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import relationship

from core.database import Base

FK_USERS = "users.id"
FK_SAFETY_PROFILES = "safety_profiles.id"
FK_SAFETY_DOCUMENT_SETS = "safety_document_sets.id"
FK_DOCUMENTS = "documents.id"
FK_OBJECTS = "objects.id"

ON_DELETE_SET_NULL = "SET NULL"
ON_DELETE_CASCADE = "CASCADE"
ON_DELETE_RESTRICT = "RESTRICT"


class SafetyProfile(Base):
    __tablename__ = "safety_profiles"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    user_id = Column(
        BigInteger,
        ForeignKey(FK_USERS, ondelete=ON_DELETE_SET_NULL),
        nullable=True,
        index=True,
    )

    is_external = Column(Boolean, default=False, nullable=False)

    first_name = Column(String(255), nullable=True) # Имя
    last_name = Column(String(255), nullable=True) # Фамилия
    middle_name = Column(String(255), nullable=True) # Отчество
    full_name = Column(String(255), nullable=False) # Полное имя (для внешних профилей или в случае отсутствия данных для разбиения на части)
    email = Column(String(255), nullable=True)  # Электронная почта (может быть связана с пользователем или указана для внешнего профиля)
    position = Column(String(255), nullable=True) # Должность
    department_name = Column(String(255), nullable=True) # Название отдела (может быть указано для внешнего профиля или для внутреннего, если пользователь не связан)
    phone = Column(String(20), nullable=True) # Телефонный номер
    avatar_url = Column(String(512), nullable=True) # URL аватара (может быть связан с пользователем или указан для внешнего профиля)
    note = Column(Text, nullable=True) # Дополнительная информация или примечания по профилю

    created_by = Column(
        BigInteger,
        ForeignKey(FK_USERS, ondelete=ON_DELETE_RESTRICT),
        nullable=False,
    )
    updated_by = Column(
        BigInteger,
        ForeignKey(FK_USERS, ondelete=ON_DELETE_SET_NULL),
        nullable=True,
    )

    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
    archived_at = Column(DateTime(timezone=True), nullable=True) # Дата архивации профиля (для мягкого удаления)

    linked_user = relationship("User", foreign_keys=[user_id], lazy="joined")
    creator = relationship("User", foreign_keys=[created_by], lazy="joined")
    editor = relationship("User", foreign_keys=[updated_by], lazy="joined")

    objects = relationship(
        "SafetyProfileObject",
        back_populates="profile",
        cascade="all, delete-orphan",
    )
    document_bindings = relationship(
        "SafetyDocumentBinding",
        back_populates="profile",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        Index("ix_safety_profiles_full_name", "full_name"),
        Index("ix_safety_profiles_is_external", "is_external"),
    )


class SafetyProfileObject(Base):
    __tablename__ = "safety_profile_objects"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    profile_id = Column(
        BigInteger,
        ForeignKey(FK_SAFETY_PROFILES, ondelete=ON_DELETE_CASCADE),
        nullable=False,
    )
    object_id = Column(
        BigInteger,
        ForeignKey(FK_OBJECTS, ondelete=ON_DELETE_CASCADE),
        nullable=False,
    )
    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    profile = relationship(
        "SafetyProfile",
        back_populates="objects",
        lazy="joined",
    )
    object = relationship("Object", lazy="joined")

    __table_args__ = (
        UniqueConstraint(
            "profile_id",
            "object_id",
            name="uq_safety_profile_object",
        ),
        Index("ix_safety_profile_objects_profile", "profile_id"),
        Index("ix_safety_profile_objects_object", "object_id"),
    )


class DocumentMetaExtension(Base):
    __tablename__ = "document_meta_extensions"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    document_id = Column(
        BigInteger,
        ForeignKey(FK_DOCUMENTS, ondelete=ON_DELETE_CASCADE),
        nullable=False,
        unique=True,
    )

    owner_profile_id = Column(
        BigInteger,
        ForeignKey(FK_SAFETY_PROFILES, ondelete=ON_DELETE_SET_NULL),
        nullable=True,
    )
    set_id = Column(
        BigInteger,
        ForeignKey(FK_SAFETY_DOCUMENT_SETS, ondelete=ON_DELETE_SET_NULL),
        nullable=True,
        index=True,
    )
    expiry_date = Column(Date, nullable=True)
    reminder_days = Column(BigInteger, nullable=True)

    is_department_common = Column(Boolean, default=False, nullable=False)
    department_code = Column(String(50), nullable=True, index=True)

    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    document = relationship("Document", lazy="joined")
    owner_profile = relationship("SafetyProfile", lazy="joined")
    document_set = relationship("SafetyDocumentSet", lazy="joined")


class SafetyDocumentSet(Base):
    __tablename__ = "safety_document_sets"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    title = Column(String(255), nullable=False, index=True)
    expiry_date = Column(Date, nullable=True)
    all_company = Column(Boolean, default=False, nullable=False)

    created_by = Column(
        BigInteger,
        ForeignKey(FK_USERS, ondelete=ON_DELETE_RESTRICT),
        nullable=False,
    )
    updated_by = Column(
        BigInteger,
        ForeignKey(FK_USERS, ondelete=ON_DELETE_SET_NULL),
        nullable=True,
    )
    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
    archived_at = Column(DateTime(timezone=True), nullable=True)

    users = relationship(
        "SafetyDocumentSetUser",
        back_populates="document_set",
        cascade="all, delete-orphan",
    )


class SafetyDocumentSetUser(Base):
    __tablename__ = "safety_document_set_users"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    set_id = Column(
        BigInteger,
        ForeignKey(FK_SAFETY_DOCUMENT_SETS, ondelete=ON_DELETE_CASCADE),
        nullable=False,
    )
    user_id = Column(
        BigInteger,
        ForeignKey(FK_USERS, ondelete=ON_DELETE_CASCADE),
        nullable=False,
    )
    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    document_set = relationship(
        "SafetyDocumentSet", back_populates="users", lazy="joined"
    )
    user = relationship("User", lazy="joined")

    __table_args__ = (
        UniqueConstraint("set_id", "user_id", name="uq_safety_document_set_user"),
        Index("ix_safety_document_set_users_set", "set_id"),
        Index("ix_safety_document_set_users_user", "user_id"),
    )


class SafetyDocumentBinding(Base):
    __tablename__ = "safety_document_bindings"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    profile_id = Column(
        BigInteger,
        ForeignKey(FK_SAFETY_PROFILES, ondelete=ON_DELETE_CASCADE),
        nullable=False,
    )
    document_id = Column(
        BigInteger,
        ForeignKey(FK_DOCUMENTS, ondelete=ON_DELETE_CASCADE),
        nullable=False,
    )

    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    profile = relationship(
        "SafetyProfile",
        back_populates="document_bindings",
        lazy="joined",
    )
    document = relationship("Document", lazy="joined")

    __table_args__ = (
        UniqueConstraint(
            "profile_id",
            "document_id",
            name="uq_safety_profile_document",
        ),
        Index("ix_safety_document_bindings_profile", "profile_id"),
        Index("ix_safety_document_bindings_document", "document_id"),
    )


class DocumentAccessRule(Base):
    __tablename__ = "document_access_rules"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    document_id = Column(
        BigInteger,
        ForeignKey(FK_DOCUMENTS, ondelete=ON_DELETE_CASCADE),
        nullable=False,
    )

    subject_type = Column(String(30), nullable=False, index=True)
    subject_value = Column(String(255), nullable=False, index=True)

    granted_by = Column(
        BigInteger,
        ForeignKey(FK_USERS, ondelete=ON_DELETE_SET_NULL),
        nullable=True,
    )
    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    document = relationship("Document", lazy="joined")
    granter = relationship("User", lazy="joined")

    __table_args__ = (
        UniqueConstraint(
            "document_id",
            "subject_type",
            "subject_value",
            name="uq_document_access_rule",
        ),
        Index("ix_document_access_rules_document", "document_id"),
    )
