import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from core.constants import DocumentCategory, UserRole
from modules.auth.models import Department, User
from modules.departments.safety.models import (
    DocumentAccessRule,
    DocumentMetaExtension,
    SafetyDocumentBinding,
    SafetyProfile,
    SafetyProfileObject,
)
from modules.documents.models import Document
from modules.objects.models import Object

logger = logging.getLogger("app")

DOCUMENT_NOT_FOUND = "Документ не найден"
PROFILE_NOT_FOUND = "Карточка сотрудника ОТ не найдена"


class SafetyService:
    @staticmethod
    def _is_safety_admin(user: User) -> bool:
        return user.role in (UserRole.ADMIN, UserRole.SAFETY)

    @staticmethod
    def _has_permission(user: User, db: Session, permission_key: str) -> bool:
        from modules.auth.service import AuthService

        return AuthService.user_has_permission(user, permission_key, db)

    @staticmethod
    def ensure_safety_role(user: User, db: Session | None = None) -> None:
        if SafetyService._is_safety_admin(user):
            return

        if db is not None and SafetyService._has_permission(
            user,
            db,
            "can_access_safety",
        ):
            return

        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Нет доступа к разделу Охрана труда",
        )

    @staticmethod
    def ensure_safety_permission(
        user: User,
        db: Session,
        permission_key: str,
        denied_detail: str,
    ) -> None:
        if SafetyService._is_safety_admin(user):
            return

        if not SafetyService._has_permission(user, db, "can_access_safety"):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Нет доступа к разделу Охрана труда",
            )

        if not SafetyService._has_permission(user, db, permission_key):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=denied_detail,
            )

    @staticmethod
    def _compose_full_name(user: User) -> str:
        parts = [user.last_name, user.first_name, user.middle_name]
        full_name = " ".join(part.strip() for part in parts if part and part.strip())
        return full_name or user.email

    @staticmethod
    def create_profile(db: Session, actor: User, payload) -> SafetyProfile:
        SafetyService.ensure_safety_permission(
            actor,
            db,
            "can_create_safety_profiles",
            "Недостаточно прав для создания карточек ОТ",
        )

        linked_user = None
        if payload.user_id is not None:
            linked_user = (
                db.query(User)
                .filter(
                    User.id == payload.user_id,
                    User.deleted_at.is_(None),
                )
                .first()
            )
            if not linked_user:
                raise HTTPException(status_code=404, detail="Пользователь не найден")

        if linked_user:
            profile = SafetyProfile(
                user_id=linked_user.id,
                is_external=False,
                first_name=linked_user.first_name,
                last_name=linked_user.last_name,
                middle_name=linked_user.middle_name,
                full_name=SafetyService._compose_full_name(linked_user),
                email=linked_user.email,
                position=linked_user.position,
                department_name=(
                    linked_user.department_rel.name
                    if linked_user.department_rel
                    else None
                ),
                object_name=payload.object_name,
                phone=linked_user.phone_number,
                avatar_url=linked_user.avatar_url,
                note=payload.note,
                created_by=actor.id,
                updated_by=actor.id,
            )
        else:
            if not payload.full_name:
                raise HTTPException(
                    status_code=400,
                    detail="Для внешнего сотрудника заполните ФИО",
                )
            profile = SafetyProfile(
                user_id=None,
                is_external=payload.is_external or True,
                first_name=payload.first_name,
                last_name=payload.last_name,
                middle_name=payload.middle_name,
                full_name=payload.full_name,
                email=payload.email,
                position=payload.position,
                department_name=payload.department_name,
                object_name=payload.object_name,
                phone=payload.phone,
                avatar_url=payload.avatar_url,
                note=payload.note,
                created_by=actor.id,
                updated_by=actor.id,
            )

        db.add(profile)
        db.flush()

        if payload.object_id:
            obj = (
                db.query(Object)
                .filter(
                    Object.id == payload.object_id,
                    Object.deleted_at.is_(None),
                )
                .first()
            )
            if obj:
                db.add(
                    SafetyProfileObject(
                        profile_id=profile.id,
                        object_id=obj.id,
                    )
                )

        db.commit()
        db.refresh(profile)

        logger.info(
            {
                "event": "safety_profile_created",
                "profile_id": profile.id,
                "linked_user_id": profile.user_id,
                "actor_id": actor.id,
            }
        )
        return profile

    @staticmethod
    def list_profiles(
        db: Session,
        actor: User,
        search: Optional[str] = None,
    ) -> list[SafetyProfile]:
        SafetyService.ensure_safety_role(actor, db)

        query = db.query(SafetyProfile).filter(SafetyProfile.archived_at.is_(None))
        if search:
            search_pattern = f"%{search}%"
            query = query.filter(
                (SafetyProfile.full_name.ilike(search_pattern))
                | (SafetyProfile.department_name.ilike(search_pattern))
                | (SafetyProfile.position.ilike(search_pattern))
            )

        return query.order_by(SafetyProfile.created_at.desc()).all()

    @staticmethod
    def delete_profile(db: Session, actor: User, profile_id: int) -> None:
        SafetyService.archive_profile(db=db, actor=actor, profile_id=profile_id)

    @staticmethod
    def archive_profile(db: Session, actor: User, profile_id: int) -> SafetyProfile:
        SafetyService.ensure_safety_permission(
            actor,
            db,
            "can_archive_safety_profiles",
            "Недостаточно прав для архивирования карточек ОТ",
        )
        profile = SafetyService.get_profile(db=db, actor=actor, profile_id=profile_id)
        profile.archived_at = datetime.now(timezone.utc)
        profile.updated_by = actor.id
        db.commit()
        db.refresh(profile)

        logger.info(
            {
                "event": "safety_profile_archived",
                "profile_id": profile.id,
                "actor_id": actor.id,
            }
        )
        return profile

    @staticmethod
    def restore_profile(db: Session, actor: User, profile_id: int) -> SafetyProfile:
        SafetyService.ensure_safety_permission(
            actor,
            db,
            "can_archive_safety_profiles",
            "Недостаточно прав для восстановления карточек ОТ",
        )
        profile = db.query(SafetyProfile).filter(SafetyProfile.id == profile_id).first()
        if not profile:
            raise HTTPException(status_code=404, detail=PROFILE_NOT_FOUND)

        profile.archived_at = None
        profile.updated_by = actor.id
        db.commit()
        db.refresh(profile)

        logger.info(
            {
                "event": "safety_profile_restored",
                "profile_id": profile.id,
                "actor_id": actor.id,
            }
        )
        return profile

    @staticmethod
    def batch_delete_profiles(
        db: Session,
        actor: User,
        profile_ids: list[int],
    ) -> int:
        SafetyService.ensure_safety_permission(
            actor,
            db,
            "can_archive_safety_profiles",
            "Недостаточно прав для массового архивирования карточек ОТ",
        )

        if not profile_ids:
            return 0

        profiles = (
            db.query(SafetyProfile)
            .filter(
                SafetyProfile.id.in_(profile_ids),
                SafetyProfile.archived_at.is_(None),
            )
            .all()
        )

        now_utc = datetime.now(timezone.utc)
        for profile in profiles:
            profile.archived_at = now_utc
            profile.updated_by = actor.id

        db.commit()

        logger.info(
            {
                "event": "safety_profiles_batch_deleted",
                "count": len(profiles),
                "actor_id": actor.id,
            }
        )
        return len(profiles)

    @staticmethod
    def get_profile(db: Session, actor: User, profile_id: int) -> SafetyProfile:
        SafetyService.ensure_safety_role(actor, db)

        profile = (
            db.query(SafetyProfile)
            .filter(
                SafetyProfile.id == profile_id,
                SafetyProfile.archived_at.is_(None),
            )
            .first()
        )
        if not profile:
            raise HTTPException(status_code=404, detail=PROFILE_NOT_FOUND)
        return profile

    @staticmethod
    def update_profile(
        db: Session,
        actor: User,
        profile: SafetyProfile,
        payload,
    ) -> SafetyProfile:
        SafetyService.ensure_safety_permission(
            actor,
            db,
            "can_edit_safety_profiles",
            "Недостаточно прав для редактирования карточек ОТ",
        )

        if payload.user_id is not None:
            linked_user = (
                db.query(User)
                .filter(
                    User.id == payload.user_id,
                    User.deleted_at.is_(None),
                    User.is_active.is_(True),
                )
                .first()
            )
            if not linked_user:
                raise HTTPException(status_code=404, detail="Пользователь не найден")

            profile.user_id = linked_user.id
            profile.is_external = False
            profile.first_name = linked_user.first_name
            profile.last_name = linked_user.last_name
            profile.middle_name = linked_user.middle_name
            profile.full_name = SafetyService._compose_full_name(linked_user)
            profile.email = linked_user.email
            profile.position = linked_user.position
            profile.department_name = (
                linked_user.department_rel.name if linked_user.department_rel else None
            )
            profile.phone = linked_user.phone_number
            profile.avatar_url = linked_user.avatar_url
            profile.object_name = payload.object_name
            profile.note = payload.note
            profile.updated_by = actor.id

            db.commit()
            db.refresh(profile)
            logger.info(
                {
                    "event": "safety_profile_linked_user",
                    "profile_id": profile.id,
                    "linked_user_id": linked_user.id,
                    "actor_id": actor.id,
                }
            )
            return profile

        if profile.user_id:
            # Связанный профиль синхронизируется из user и не редактируется вручную.
            profile.object_name = payload.object_name
            profile.note = payload.note
        else:
            if payload.full_name:
                profile.full_name = payload.full_name
            profile.email = payload.email
            profile.position = payload.position
            profile.department_name = payload.department_name
            profile.object_name = payload.object_name
            profile.phone = payload.phone
            profile.avatar_url = payload.avatar_url
            profile.note = payload.note

        profile.updated_by = actor.id
        db.commit()
        db.refresh(profile)

        logger.info(
            {
                "event": "safety_profile_updated",
                "profile_id": profile.id,
                "actor_id": actor.id,
            }
        )
        return profile

    @staticmethod
    def unlink_profile_user(
        db: Session,
        actor: User,
        profile: SafetyProfile,
    ) -> SafetyProfile:
        SafetyService.ensure_safety_permission(
            actor,
            db,
            "can_edit_safety_profiles",
            "Недостаточно прав для изменения связей карточек ОТ",
        )

        if not profile.user_id:
            return profile

        profile.user_id = None
        profile.is_external = True
        profile.updated_by = actor.id

        db.commit()
        db.refresh(profile)

        logger.info(
            {
                "event": "safety_profile_user_unlinked",
                "profile_id": profile.id,
                "actor_id": actor.id,
            }
        )
        return profile

    @staticmethod
    def _subject_value_for_grant(db: Session, payload) -> tuple[str, str]:
        if payload.all_company:
            return "all_company", "all"
        if payload.user_id:
            return "user", str(payload.user_id)
        if payload.department_id:
            dept = (
                db.query(Department)
                .filter(Department.id == payload.department_id)
                .first()
            )
            if not dept:
                raise HTTPException(status_code=404, detail="Отдел не найден")
            return "department", str(payload.department_id)
        if payload.role:
            return "role", payload.role
        if payload.object_id:
            return "object", str(payload.object_id)

        raise HTTPException(status_code=400, detail="Не указан субъект доступа")

    @staticmethod
    def grant_document_access(
        db: Session,
        actor: User,
        payload,
    ) -> DocumentAccessRule:
        SafetyService.ensure_safety_permission(
            actor,
            db,
            "can_manage_safety_documents",
            "Недостаточно прав для управления доступом к документам ОТ",
        )

        document = (
            db.query(Document)
            .filter(
                Document.id == payload.document_id,
                Document.deleted_at.is_(None),
                Document.is_active.is_(True),
            )
            .first()
        )
        if not document:
            raise HTTPException(status_code=404, detail=DOCUMENT_NOT_FOUND)

        if document.category != DocumentCategory.SAFETY:
            raise HTTPException(
                status_code=400,
                detail="Можно управлять доступом только документов ОТ",
            )

        subject_type, subject_value = SafetyService._subject_value_for_grant(
            db,
            payload,
        )

        exists = (
            db.query(DocumentAccessRule)
            .filter(
                DocumentAccessRule.document_id == document.id,
                DocumentAccessRule.subject_type == subject_type,
                DocumentAccessRule.subject_value == subject_value,
            )
            .first()
        )
        if exists:
            return exists

        rule = DocumentAccessRule(
            document_id=document.id,
            subject_type=subject_type,
            subject_value=subject_value,
            granted_by=actor.id,
        )
        db.add(rule)
        db.commit()
        db.refresh(rule)

        logger.info(
            {
                "event": "safety_document_access_granted",
                "document_id": document.id,
                "subject_type": subject_type,
                "actor_id": actor.id,
            }
        )
        return rule

    @staticmethod
    def set_document_metadata(
        db: Session,
        actor: User,
        payload,
    ) -> DocumentMetaExtension:
        SafetyService.ensure_safety_permission(
            actor,
            db,
            "can_manage_safety_documents",
            "Недостаточно прав для изменения метаданных документов ОТ",
        )

        document = (
            db.query(Document)
            .filter(
                Document.id == payload.document_id,
                Document.deleted_at.is_(None),
                Document.is_active.is_(True),
            )
            .first()
        )
        if not document:
            raise HTTPException(status_code=404, detail=DOCUMENT_NOT_FOUND)

        if document.category != DocumentCategory.SAFETY:
            raise HTTPException(
                status_code=400,
                detail="Метаданные доступны только для документов ОТ",
            )

        meta = (
            db.query(DocumentMetaExtension)
            .filter(DocumentMetaExtension.document_id == document.id)
            .first()
        )
        if not meta:
            meta = DocumentMetaExtension(document_id=document.id)
            db.add(meta)

        meta.expiry_date = payload.expiry_date
        meta.reminder_days = payload.reminder_days
        meta.is_department_common = payload.is_department_common
        meta.department_code = DocumentCategory.SAFETY.value

        db.commit()
        db.refresh(meta)

        logger.info(
            {
                "event": "safety_document_meta_updated",
                "document_id": document.id,
                "expiry_date": str(meta.expiry_date) if meta.expiry_date else None,
                "actor_id": actor.id,
            }
        )
        return meta

    @staticmethod
    def bind_document_to_profile(
        db: Session,
        actor: User,
        profile_id: int,
        document_id: int,
    ) -> SafetyDocumentBinding:
        SafetyService.ensure_safety_permission(
            actor,
            db,
            "can_manage_safety_documents",
            "Недостаточно прав для привязки документов ОТ",
        )

        profile = SafetyService.get_profile(db, actor, profile_id)
        document = (
            db.query(Document)
            .filter(
                Document.id == document_id,
                Document.deleted_at.is_(None),
                Document.is_active.is_(True),
            )
            .first()
        )
        if not document:
            raise HTTPException(status_code=404, detail=DOCUMENT_NOT_FOUND)

        if document.category != DocumentCategory.SAFETY:
            raise HTTPException(
                status_code=400,
                detail="В карточку ОТ можно привязывать только документы ОТ",
            )

        existing = (
            db.query(SafetyDocumentBinding)
            .filter(
                SafetyDocumentBinding.profile_id == profile.id,
                SafetyDocumentBinding.document_id == document.id,
            )
            .first()
        )
        if existing:
            return existing

        binding = SafetyDocumentBinding(
            profile_id=profile.id,
            document_id=document.id,
        )
        db.add(binding)

        if profile.user_id:
            user_rule = (
                db.query(DocumentAccessRule)
                .filter(
                    DocumentAccessRule.document_id == document.id,
                    DocumentAccessRule.subject_type == "user",
                    DocumentAccessRule.subject_value == str(profile.user_id),
                )
                .first()
            )
            if not user_rule:
                db.add(
                    DocumentAccessRule(
                        document_id=document.id,
                        subject_type="user",
                        subject_value=str(profile.user_id),
                        granted_by=actor.id,
                    )
                )

        db.commit()
        db.refresh(binding)

        logger.info(
            {
                "event": "safety_document_bound_to_profile",
                "profile_id": profile.id,
                "document_id": document.id,
                "actor_id": actor.id,
            }
        )
        return binding
