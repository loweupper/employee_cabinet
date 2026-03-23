import re
import uuid
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Annotated, Optional

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    UploadFile,
)
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pydantic import ValidationError
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from core.config import settings
from core.constants import DocumentCategory
from core.database import get_db
from core.template_helpers import get_sidebar_context
from core.validators import ALLOWED_DOCUMENT_EXTENSIONS, validate_file_extension
from modules.auth.dependencies import get_current_user_from_cookie
from modules.auth.models import User
from modules.departments.safety.models import (
    DocumentAccessRule,
    DocumentMetaExtension,
    SafetyDocumentBinding,
    SafetyDocumentSet,
    SafetyDocumentSetUser,
    SafetyProfile,
)
from modules.departments.safety.schemas import (
    SafetyDocumentAccessGrant,
    SafetyDocumentMetadataUpdate,
    SafetyProfileCreate,
    SafetyProfileRead,
    SafetyProfileUpdate,
)
from modules.departments.safety.service import SafetyService
from modules.documents.models import Document
from modules.documents.service import DocumentService
from modules.objects.models import Object

router = APIRouter(prefix="/safety", tags=["departments-safety"])
templates = Jinja2Templates(directory="templates")

PAGE_SIZE = 20


def _safe_url_text(value: Optional[str]) -> str:
    if not value:
        return ""
    return value.replace("&", " ").replace("?", " ").strip()


def _parse_expiry_date(expiry_date: Optional[str]) -> Optional[date]:
    if not expiry_date:
        return None
    return datetime.strptime(expiry_date, "%Y-%m-%d").date()


def _safe_name_part(value: str) -> str:
    clean = re.sub(r"[^a-zA-Z0-9_-]+", "_", value.strip())
    return clean[:120] or "file"


def _safe_suffix(filename: Optional[str]) -> str:
    suffix = Path(filename or "").suffix.lower()
    if re.fullmatch(r"\.[a-z0-9]{1,10}", suffix):
        return suffix
    return ""


# Загрузка нескольких файлов за раз
async def _save_profile_document_file(
    file: UploadFile,
    storage_owner_id: int,
) -> str:
    now = datetime.now()
    relative_path = f"users_documents/{storage_owner_id}/{now.year}"
    target_dir = Path(settings.FILES_PATH) / relative_path
    target_dir.mkdir(parents=True, exist_ok=True)

    suffix = _safe_suffix(file.filename)
    stem = _safe_name_part(Path(file.filename or "document").stem)
    filename = f"{uuid.uuid4().hex[:10]}_{stem}{suffix}"

    final_path = target_dir / filename
    content = await file.read()
    await file.seek(0)
    final_path.write_bytes(content)
    return f"{relative_path}/{filename}"


def _build_pagination(total: int, page: int) -> dict:
    total_pages = max((total + PAGE_SIZE - 1) // PAGE_SIZE, 1)
    current_page = min(max(page, 1), total_pages)
    offset = (current_page - 1) * PAGE_SIZE
    return {
        "page": current_page,
        "total_pages": total_pages,
        "offset": offset,
    }


def _active_safety_users(db: Session) -> list[User]:
    return (
        db.query(User)
        .filter(User.is_active.is_(True), User.deleted_at.is_(None))
        .order_by(User.email.asc())
        .limit(1000)
        .all()
    )


def _active_objects(db: Session) -> list[Object]:
    return (
        db.query(Object)
        .filter(Object.deleted_at.is_(None), Object.is_active.is_(True))
        .order_by(Object.title.asc())
        .limit(1000)
        .all()
    )


def _resolve_default_object_id(db: Session, actor: User) -> int:
    if actor.object_id:
        object_exists = (
            db.query(Object)
            .filter(
                Object.id == actor.object_id,
                Object.deleted_at.is_(None),
                Object.is_active.is_(True),
            )
            .first()
        )
        if object_exists:
            return actor.object_id

    fallback_object = (
        db.query(Object)
        .filter(Object.deleted_at.is_(None), Object.is_active.is_(True))
        .order_by(Object.id.asc())
        .first()
    )
    if fallback_object:
        return fallback_object.id

    raise HTTPException(status_code=400, detail="Нет активного объекта для документов")


def _get_set_or_404(db: Session, set_id: int) -> SafetyDocumentSet:
    document_set = (
        db.query(SafetyDocumentSet)
        .filter(
            SafetyDocumentSet.id == set_id,
            SafetyDocumentSet.archived_at.is_(None),
        )
        .first()
    )
    if not document_set:
        raise HTTPException(status_code=404, detail="Набор документов не найден")
    return document_set


def _set_documents_query(db: Session, set_id: int):
    return (
        db.query(Document)
        .join(DocumentMetaExtension, DocumentMetaExtension.document_id == Document.id)
        .filter(
            DocumentMetaExtension.set_id == set_id,
            DocumentMetaExtension.is_department_common.is_(True),
            Document.category == DocumentCategory.SAFETY,
            Document.deleted_at.is_(None),
            Document.is_active.is_(True),
        )
    )


def _sync_set_users(
    db: Session,
    set_id: int,
    selected_user_ids: list[int],
) -> None:
    db.query(SafetyDocumentSetUser).filter(
        SafetyDocumentSetUser.set_id == set_id
    ).delete(synchronize_session=False)

    for user_id in sorted(set(selected_user_ids)):
        db.add(
            SafetyDocumentSetUser(
                set_id=set_id,
                user_id=user_id,
            )
        )


def _replace_access_rules_for_documents(
    db: Session,
    actor: User,
    document_ids: list[int],
    all_company: bool,
    grant_user_ids: list[int],
) -> None:
    if not document_ids:
        return

    db.query(DocumentAccessRule).filter(
        DocumentAccessRule.document_id.in_(document_ids)
    ).delete(synchronize_session=False)

    if all_company:
        for doc_id in document_ids:
            db.add(
                DocumentAccessRule(
                    document_id=doc_id,
                    subject_type="all_company",
                    subject_value="all",
                    granted_by=actor.id,
                )
            )

    for uid in sorted(set(grant_user_ids)):
        for doc_id in document_ids:
            db.add(
                DocumentAccessRule(
                    document_id=doc_id,
                    subject_type="user",
                    subject_value=str(uid),
                    granted_by=actor.id,
                )
            )


def _set_details(db: Session, set_id: int) -> dict:
    document_set = _get_set_or_404(db=db, set_id=set_id)
    documents = (
        _set_documents_query(db, set_id).order_by(Document.created_at.asc()).all()
    )
    selected_users = (
        db.query(SafetyDocumentSetUser.user_id)
        .filter(SafetyDocumentSetUser.set_id == set_id)
        .all()
    )

    return {
        "document_set": document_set,
        "documents": documents,
        "selected_user_ids": [u[0] for u in selected_users],
    }


@router.get("", response_class=HTMLResponse)
async def safety_index(
    user: Annotated[User, Depends(get_current_user_from_cookie)],
):
    SafetyService.ensure_safety_role(user)
    return RedirectResponse(url="/departments/safety/cards", status_code=303)


@router.get("/cards", response_class=HTMLResponse)
async def safety_cards_list(
    request: Request,
    success: Annotated[Optional[str], Query()] = None,
    error: Annotated[Optional[str], Query()] = None,
    search: Annotated[Optional[str], Query()] = None,
    employee_type: Annotated[str, Query()] = "all",
    sort: Annotated[str, Query()] = "created_desc",
    date_from: Annotated[Optional[str], Query()] = None,
    date_to: Annotated[Optional[str], Query()] = None,
    view: Annotated[str, Query()] = "active",
    page: Annotated[int, Query(ge=1)] = 1,
    user: Annotated[User, Depends(get_current_user_from_cookie)] = None,
    db: Annotated[Session, Depends(get_db)] = None,
):
    SafetyService.ensure_safety_role(user)

    query = db.query(SafetyProfile)
    if view == "archived":
        query = query.filter(SafetyProfile.archived_at.is_not(None))
    else:
        view = "active"
        query = query.filter(SafetyProfile.archived_at.is_(None))

    if search:
        pattern = f"%{search.strip()}%"
        query = query.filter(
            or_(
                SafetyProfile.full_name.ilike(pattern),
                SafetyProfile.department_name.ilike(pattern),
                SafetyProfile.position.ilike(pattern),
                SafetyProfile.phone.ilike(pattern),
            )
        )

    if employee_type == "internal":
        query = query.filter(SafetyProfile.is_external.is_(False))
    elif employee_type == "external":
        query = query.filter(SafetyProfile.is_external.is_(True))

    parsed_from = _parse_expiry_date(date_from)
    parsed_to = _parse_expiry_date(date_to)
    if parsed_from:
        query = query.filter(func.date(SafetyProfile.created_at) >= parsed_from)
    if parsed_to:
        query = query.filter(func.date(SafetyProfile.created_at) <= parsed_to)

    if sort == "created_asc":
        query = query.order_by(SafetyProfile.created_at.asc())
    elif sort == "name_asc":
        query = query.order_by(SafetyProfile.full_name.asc())
    elif sort == "name_desc":
        query = query.order_by(SafetyProfile.full_name.desc())
    else:
        query = query.order_by(SafetyProfile.created_at.desc())

    total = query.count()
    pagination = _build_pagination(total=total, page=page)
    profiles = (
        query.offset(pagination["offset"]).limit(PAGE_SIZE).all() if total else []
    )

    sidebar_context = get_sidebar_context(user, db)
    return templates.TemplateResponse(
        "web/departments/safety/cards_list.html",
        {
            "request": request,
            "current_user": user,
            "profiles": profiles,
            "search": search or "",
            "employee_type": employee_type,
            "sort": sort,
            "date_from": date_from or "",
            "date_to": date_to or "",
            "view": view,
            "success": _safe_url_text(success),
            "error": _safe_url_text(error),
            "page": pagination["page"],
            "total_pages": pagination["total_pages"],
            "total": total,
            **sidebar_context,
        },
    )


@router.get("/cards/create", response_class=HTMLResponse)
async def safety_card_create_page(
    request: Request,
    error: Annotated[Optional[str], Query()] = None,
    user: Annotated[User, Depends(get_current_user_from_cookie)] = None,
    db: Annotated[Session, Depends(get_db)] = None,
):
    SafetyService.ensure_safety_role(user)

    sidebar_context = get_sidebar_context(user, db)
    return templates.TemplateResponse(
        "web/departments/safety/cards_create.html",
        {
            "request": request,
            "current_user": user,
            "users": _active_safety_users(db),
            "objects": _active_objects(db),
            "error": _safe_url_text(error),
            **sidebar_context,
        },
    )


@router.get("/profiles/{profile_id}", response_class=HTMLResponse)
async def safety_profile_detail(
    profile_id: int,
    request: Request,
    user: Annotated[User, Depends(get_current_user_from_cookie)] = None,
    db: Annotated[Session, Depends(get_db)] = None,
):
    profile = SafetyService.get_profile(db=db, actor=user, profile_id=profile_id)

    documents = (
        db.query(Document)
        .join(SafetyDocumentBinding, SafetyDocumentBinding.document_id == Document.id)
        .filter(
            SafetyDocumentBinding.profile_id == profile.id,
            Document.category == DocumentCategory.SAFETY,
            Document.deleted_at.is_(None),
            Document.is_active.is_(True),
        )
        .order_by(Document.created_at.desc())
        .limit(200)
        .all()
    )

    sidebar_context = get_sidebar_context(user, db)
    return templates.TemplateResponse(
        "web/departments/safety/profile_detail.html",
        {
            "request": request,
            "current_user": user,
            "profile": profile,
            "documents": documents,
            **sidebar_context,
        },
    )


@router.get("/cards/{profile_id}/edit", response_class=HTMLResponse)
@router.get("/profiles/{profile_id}/edit", response_class=HTMLResponse)
async def safety_profile_edit_page(
    profile_id: int,
    request: Request,
    user: Annotated[User, Depends(get_current_user_from_cookie)] = None,
    db: Annotated[Session, Depends(get_db)] = None,
):
    profile = SafetyService.get_profile(db=db, actor=user, profile_id=profile_id)

    sidebar_context = get_sidebar_context(user, db)
    return templates.TemplateResponse(
        "web/departments/safety/profile_edit.html",
        {
            "request": request,
            "current_user": user,
            "profile": profile,
            "users": _active_safety_users(db),
            **sidebar_context,
        },
    )


@router.get("/profiles/{profile_id}/documents", response_class=HTMLResponse)
async def safety_profile_documents_page(
    profile_id: int,
    request: Request,
    success: Annotated[Optional[str], Query()] = None,
    error: Annotated[Optional[str], Query()] = None,
    search: Annotated[Optional[str], Query()] = None,
    date_from: Annotated[Optional[str], Query()] = None,
    date_to: Annotated[Optional[str], Query()] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    user: Annotated[User, Depends(get_current_user_from_cookie)] = None,
    db: Annotated[Session, Depends(get_db)] = None,
):
    profile = SafetyService.get_profile(db=db, actor=user, profile_id=profile_id)

    query = (
        db.query(Document)
        .join(SafetyDocumentBinding, SafetyDocumentBinding.document_id == Document.id)
        .join(DocumentMetaExtension, DocumentMetaExtension.document_id == Document.id)
        .filter(
            SafetyDocumentBinding.profile_id == profile.id,
            DocumentMetaExtension.owner_profile_id == profile.id,
            DocumentMetaExtension.is_department_common.is_(False),
            Document.category == DocumentCategory.SAFETY,
            Document.deleted_at.is_(None),
            Document.is_active.is_(True),
        )
    )

    if search:
        pattern = f"%{search.strip()}%"
        query = query.filter(
            or_(
                Document.title.ilike(pattern),
                Document.description.ilike(pattern),
                Document.file_name.ilike(pattern),
            )
        )

    parsed_from = _parse_expiry_date(date_from)
    parsed_to = _parse_expiry_date(date_to)
    if parsed_from:
        query = query.filter(DocumentMetaExtension.expiry_date >= parsed_from)
    if parsed_to:
        query = query.filter(DocumentMetaExtension.expiry_date <= parsed_to)

    query = query.order_by(Document.created_at.desc())
    total = query.count()
    pagination = _build_pagination(total=total, page=page)
    documents = (
        query.offset(pagination["offset"]).limit(PAGE_SIZE).all() if total else []
    )

    expiry_map = {}
    if documents:
        doc_ids = [doc.id for doc in documents]
        meta_rows = (
            db.query(
                DocumentMetaExtension.document_id, DocumentMetaExtension.expiry_date
            )
            .filter(DocumentMetaExtension.document_id.in_(doc_ids))
            .all()
        )
        expiry_map = dict(meta_rows)

    sidebar_context = get_sidebar_context(user, db)
    return templates.TemplateResponse(
        "web/departments/safety/profile_documents.html",
        {
            "request": request,
            "current_user": user,
            "profile": profile,
            "documents": documents,
            "expiry_map": expiry_map,
            "search": search or "",
            "date_from": date_from or "",
            "date_to": date_to or "",
            "page": pagination["page"],
            "total_pages": pagination["total_pages"],
            "total": total,
            "success": _safe_url_text(success),
            "error": _safe_url_text(error),
            **sidebar_context,
        },
    )


@router.post("/profiles", response_model=SafetyProfileRead)
async def create_safety_profile(
    payload: SafetyProfileCreate,
    user: Annotated[User, Depends(get_current_user_from_cookie)],
    db: Annotated[Session, Depends(get_db)],
):
    profile = SafetyService.create_profile(db=db, actor=user, payload=payload)
    return SafetyProfileRead.model_validate(profile)


@router.post("/profiles/create-form", response_model=None)
async def create_safety_profile_form(
    user_id: Annotated[Optional[int], Form()] = None,
    is_external: Annotated[bool, Form()] = False,
    full_name: Annotated[Optional[str], Form()] = None,
    email: Annotated[Optional[str], Form()] = None,
    position: Annotated[Optional[str], Form()] = None,
    department_name: Annotated[Optional[str], Form()] = None,
    phone: Annotated[Optional[str], Form()] = None,
    note: Annotated[Optional[str], Form()] = None,
    object_id: Annotated[Optional[int], Form()] = None,
    user: Annotated[User, Depends(get_current_user_from_cookie)] = None,
    db: Annotated[Session, Depends(get_db)] = None,
):
    try:
        payload = SafetyProfileCreate(
            user_id=user_id,
            is_external=is_external,
            full_name=full_name,
            email=email,
            position=position,
            department_name=department_name,
            phone=phone,
            note=note,
            object_id=object_id,
        )
        SafetyService.create_profile(db=db, actor=user, payload=payload)
        return RedirectResponse(
            url="/departments/safety/cards?success=Карточка создана",
            status_code=303,
        )
    except HTTPException as exc:
        return RedirectResponse(
            url=(
                "/departments/safety/cards/create?error="
                f"{_safe_url_text(str(exc.detail))}"
            ),
            status_code=303,
        )
    except ValidationError:
        return RedirectResponse(
            url="/departments/safety/cards/create?error=Ошибка данных формы",
            status_code=303,
        )


@router.post("/profiles/{profile_id}", response_model=SafetyProfileRead)
async def update_safety_profile(
    profile_id: int,
    payload: SafetyProfileUpdate,
    user: Annotated[User, Depends(get_current_user_from_cookie)],
    db: Annotated[Session, Depends(get_db)],
):
    profile = SafetyService.get_profile(db=db, actor=user, profile_id=profile_id)
    updated = SafetyService.update_profile(
        db=db,
        actor=user,
        profile=profile,
        payload=payload,
    )
    return SafetyProfileRead.model_validate(updated)


@router.post("/profiles/{profile_id}/update-form", response_model=None)
async def update_safety_profile_form(
    profile_id: int,
    user_id: Annotated[Optional[int], Form()] = None,
    full_name: Annotated[Optional[str], Form()] = None,
    email: Annotated[Optional[str], Form()] = None,
    position: Annotated[Optional[str], Form()] = None,
    department_name: Annotated[Optional[str], Form()] = None,
    phone: Annotated[Optional[str], Form()] = None,
    note: Annotated[Optional[str], Form()] = None,
    user: Annotated[User, Depends(get_current_user_from_cookie)] = None,
    db: Annotated[Session, Depends(get_db)] = None,
):
    try:
        profile = SafetyService.get_profile(db=db, actor=user, profile_id=profile_id)
        payload = SafetyProfileUpdate(
            user_id=user_id,
            full_name=full_name,
            email=email,
            position=position,
            department_name=department_name,
            phone=phone,
            note=note,
        )
        SafetyService.update_profile(
            db=db,
            actor=user,
            profile=profile,
            payload=payload,
        )
        return RedirectResponse(
            url=(
                f"/departments/safety/cards/{profile_id}/edit"
                "?success=Карточка обновлена"
            ),
            status_code=303,
        )
    except HTTPException as exc:
        return RedirectResponse(
            url=(
                f"/departments/safety/cards/{profile_id}/edit"
                f"?error={_safe_url_text(str(exc.detail))}"
            ),
            status_code=303,
        )
    except ValidationError:
        return RedirectResponse(
            url=(
                f"/departments/safety/cards/{profile_id}/edit"
                "?error=Ошибка данных формы"
            ),
            status_code=303,
        )


@router.post("/profiles/{profile_id}/delete", response_model=None)
async def delete_safety_profile(
    profile_id: int,
    user: Annotated[User, Depends(get_current_user_from_cookie)],
    db: Annotated[Session, Depends(get_db)],
):
    SafetyService.delete_profile(db=db, actor=user, profile_id=profile_id)
    return RedirectResponse(
        url="/departments/safety/cards?success=Карточка архивирована",
        status_code=303,
    )


@router.post("/profiles/{profile_id}/archive", response_model=None)
async def archive_safety_profile(
    profile_id: int,
    user: Annotated[User, Depends(get_current_user_from_cookie)],
    db: Annotated[Session, Depends(get_db)],
):
    SafetyService.archive_profile(db=db, actor=user, profile_id=profile_id)
    return RedirectResponse(
        url="/departments/safety/cards?success=Карточка архивирована",
        status_code=303,
    )


@router.post("/profiles/{profile_id}/restore", response_model=None)
async def restore_safety_profile(
    profile_id: int,
    user: Annotated[User, Depends(get_current_user_from_cookie)],
    db: Annotated[Session, Depends(get_db)],
):
    SafetyService.restore_profile(db=db, actor=user, profile_id=profile_id)
    return RedirectResponse(
        url="/departments/safety/cards?view=archived&success=Карточка восстановлена",
        status_code=303,
    )


@router.post("/profiles/batch-delete", response_model=None)
async def batch_delete_safety_profiles(
    profile_ids: Annotated[Optional[list[int]], Form()] = None,
    user: Annotated[User, Depends(get_current_user_from_cookie)] = None,
    db: Annotated[Session, Depends(get_db)] = None,
):
    removed = SafetyService.batch_delete_profiles(
        db=db,
        actor=user,
        profile_ids=profile_ids or [],
    )
    return RedirectResponse(
        url=f"/departments/safety/cards?success=Удалено карточек: {removed}",
        status_code=303,
    )


@router.post("/profiles/{profile_id}/bind-document", response_model=None)
async def bind_document_to_profile(
    profile_id: int,
    document_id: int,
    user: Annotated[User, Depends(get_current_user_from_cookie)],
    db: Annotated[Session, Depends(get_db)],
):
    binding = SafetyService.bind_document_to_profile(
        db=db,
        actor=user,
        profile_id=profile_id,
        document_id=document_id,
    )
    return JSONResponse(
        {
            "status": "ok",
            "binding_id": binding.id,
            "profile_id": binding.profile_id,
            "document_id": binding.document_id,
        }
    )


@router.post("/profiles/{profile_id}/documents/upload", response_model=None)
async def upload_profile_document(
    profile_id: int,
    file: Annotated[UploadFile, File(...)],
    title: Annotated[str, Form(...)],
    object_id: Annotated[int, Form(...)],
    expiry_date: Annotated[Optional[str], Form()] = None,
    grant_user_ids: Annotated[Optional[list[int]], Form()] = None,
    user: Annotated[User, Depends(get_current_user_from_cookie)] = None,
    db: Annotated[Session, Depends(get_db)] = None,
):
    profile = SafetyService.get_profile(db=db, actor=user, profile_id=profile_id)

    if not file.filename or not validate_file_extension(
        file.filename,
        ALLOWED_DOCUMENT_EXTENSIONS,
    ):
        return RedirectResponse(
            url=(
                f"/departments/safety/cards/{profile_id}/edit"
                "?error=Недопустимый тип файла"
            ),
            status_code=303,
        )

    file_bytes = await file.read()
    if len(file_bytes) > settings.MAX_FILE_SIZE:
        return RedirectResponse(
            url=(
                f"/departments/safety/cards/{profile_id}/edit"
                "?error=Файл слишком большой"
            ),
            status_code=303,
        )
    await file.seek(0)

    stored_path = await DocumentService.save_file(file, object_id)
    document = Document(
        title=title,
        description=None,
        category=DocumentCategory.SAFETY,
        file_path=stored_path,
        file_name=file.filename,
        file_size=len(file_bytes),
        file_type=file.content_type,
        object_id=object_id,
        created_by=user.id,
    )
    db.add(document)
    db.flush()

    db.add(SafetyDocumentBinding(profile_id=profile.id, document_id=document.id))
    db.add(
        DocumentMetaExtension(
            document_id=document.id,
            owner_profile_id=profile.id,
            expiry_date=_parse_expiry_date(expiry_date),
            is_department_common=False,
            department_code=DocumentCategory.SAFETY.value,
        )
    )

    if profile.user_id:
        db.add(
            DocumentAccessRule(
                document_id=document.id,
                subject_type="user",
                subject_value=str(profile.user_id),
                granted_by=user.id,
            )
        )

    for uid in set(grant_user_ids or []):
        db.add(
            DocumentAccessRule(
                document_id=document.id,
                subject_type="user",
                subject_value=str(uid),
                granted_by=user.id,
            )
        )

    db.commit()
    return RedirectResponse(
        url=f"/departments/safety/profiles/{profile_id}/documents?success=Документ добавлен",
        status_code=303,
    )


@router.post("/profiles/{profile_id}/documents/upload-multiple", response_model=None)
async def upload_profile_documents_multiple(
    profile_id: int,
    files: Annotated[list[UploadFile], File(...)],
    descriptions: Annotated[Optional[list[str]], Form()] = None,
    expiry_dates: Annotated[Optional[list[str]], Form()] = None,
    user: Annotated[User, Depends(get_current_user_from_cookie)] = None,
    db: Annotated[Session, Depends(get_db)] = None,
):
    profile = SafetyService.get_profile(db=db, actor=user, profile_id=profile_id)

    valid_files = [f for f in files if f and f.filename]
    if not valid_files:
        return RedirectResponse(
            url=(
                f"/departments/safety/profiles/{profile_id}/documents"
                "?error=Нужно выбрать хотя бы один файл"
            ),
            status_code=303,
        )

    for file in valid_files:
        if not validate_file_extension(file.filename, ALLOWED_DOCUMENT_EXTENSIONS):
            return RedirectResponse(
                url=(
                    f"/departments/safety/profiles/{profile_id}/documents"
                    "?error=Недопустимый тип файла"
                ),
                status_code=303,
            )
        payload = await file.read()
        if len(payload) > settings.MAX_FILE_SIZE:
            return RedirectResponse(
                url=(
                    f"/departments/safety/profiles/{profile_id}/documents"
                    "?error=Один из файлов слишком большой"
                ),
                status_code=303,
            )
        await file.seek(0)

    storage_owner_id = profile.user_id or profile.id
    linked_user = None
    if profile.user_id:
        linked_user = db.query(User).filter(User.id == profile.user_id).first()

    object_id = None
    if linked_user and linked_user.object_id:
        object_id = linked_user.object_id
    if not object_id:
        object_id = _resolve_default_object_id(db=db, actor=user)

    descriptions = descriptions or []
    expiry_dates = expiry_dates or []

    for idx, file in enumerate(valid_files):
        payload = await file.read()
        await file.seek(0)

        stored_path = await _save_profile_document_file(file, storage_owner_id)
        title = Path(file.filename or "document").stem
        description = (descriptions[idx] if idx < len(descriptions) else "").strip()
        expiry_raw = expiry_dates[idx] if idx < len(expiry_dates) else None

        document = Document(
            title=title,
            description=description or None,
            category=DocumentCategory.SAFETY,
            file_path=stored_path,
            file_name=file.filename or title,
            file_size=len(payload),
            file_type=file.content_type,
            object_id=object_id,
            created_by=user.id,
        )
        db.add(document)
        db.flush()

        db.add(SafetyDocumentBinding(profile_id=profile.id, document_id=document.id))
        db.add(
            DocumentMetaExtension(
                document_id=document.id,
                owner_profile_id=profile.id,
                expiry_date=_parse_expiry_date(expiry_raw),
                is_department_common=False,
                department_code=DocumentCategory.SAFETY.value,
            )
        )

        if profile.user_id:
            db.add(
                DocumentAccessRule(
                    document_id=document.id,
                    subject_type="user",
                    subject_value=str(profile.user_id),
                    granted_by=user.id,
                )
            )

    db.commit()
    return RedirectResponse(
        url=(
            f"/departments/safety/profiles/{profile_id}/documents"
            "?success=Документы добавлены"
        ),
        status_code=303,
    )


@router.post(
    "/profiles/{profile_id}/documents/{document_id}/delete", response_model=None
)
async def delete_profile_document(
    profile_id: int,
    document_id: int,
    user: Annotated[User, Depends(get_current_user_from_cookie)] = None,
    db: Annotated[Session, Depends(get_db)] = None,
):
    profile = SafetyService.get_profile(db=db, actor=user, profile_id=profile_id)

    binding = (
        db.query(SafetyDocumentBinding)
        .filter(
            SafetyDocumentBinding.profile_id == profile.id,
            SafetyDocumentBinding.document_id == document_id,
        )
        .first()
    )
    if not binding:
        return RedirectResponse(
            url=(
                f"/departments/safety/profiles/{profile_id}/documents"
                "?error=Документ не найден"
            ),
            status_code=303,
        )

    document = db.query(Document).filter(Document.id == document_id).first()
    if not document:
        return RedirectResponse(
            url=(
                f"/departments/safety/profiles/{profile_id}/documents"
                "?error=Документ не найден"
            ),
            status_code=303,
        )

    full_path = (Path(settings.FILES_PATH) / document.file_path).resolve()
    files_root = Path(settings.FILES_PATH).resolve()

    document.deleted_at = datetime.now(timezone.utc)
    document.is_active = False
    document.updated_by = user.id

    db.delete(binding)
    db.commit()

    if files_root in full_path.parents and full_path.exists():
        try:
            full_path.unlink()
        except OSError:
            pass

    return RedirectResponse(
        url=(
            f"/departments/safety/profiles/{profile_id}/documents"
            "?success=Документ удален"
        ),
        status_code=303,
    )


@router.get("/common-docs", response_class=HTMLResponse)
async def common_docs_list(
    request: Request,
    success: Annotated[Optional[str], Query()] = None,
    error: Annotated[Optional[str], Query()] = None,
    search: Annotated[Optional[str], Query()] = None,
    sort: Annotated[str, Query()] = "created_desc",
    date_from: Annotated[Optional[str], Query()] = None,
    date_to: Annotated[Optional[str], Query()] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    user: Annotated[User, Depends(get_current_user_from_cookie)] = None,
    db: Annotated[Session, Depends(get_db)] = None,
):
    SafetyService.ensure_safety_role(user)

    query = db.query(SafetyDocumentSet).filter(SafetyDocumentSet.archived_at.is_(None))

    if search:
        query = query.filter(SafetyDocumentSet.title.ilike(f"%{search.strip()}%"))

    parsed_from = _parse_expiry_date(date_from)
    parsed_to = _parse_expiry_date(date_to)
    if parsed_from:
        query = query.filter(func.date(SafetyDocumentSet.created_at) >= parsed_from)
    if parsed_to:
        query = query.filter(func.date(SafetyDocumentSet.created_at) <= parsed_to)

    if sort == "created_asc":
        query = query.order_by(SafetyDocumentSet.created_at.asc())
    elif sort == "name_asc":
        query = query.order_by(SafetyDocumentSet.title.asc())
    elif sort == "name_desc":
        query = query.order_by(SafetyDocumentSet.title.desc())
    else:
        query = query.order_by(SafetyDocumentSet.created_at.desc())

    total = query.count()
    pagination = _build_pagination(total=total, page=page)
    sets = query.offset(pagination["offset"]).limit(PAGE_SIZE).all() if total else []

    set_ids = [item.id for item in sets]
    stats_map = {
        item.id: {"count_files": 0, "latest_created_at": None} for item in sets
    }

    if set_ids:
        stats_rows = (
            db.query(
                DocumentMetaExtension.set_id,
                func.count(Document.id),
                func.max(Document.created_at),
            )
            .join(Document, Document.id == DocumentMetaExtension.document_id)
            .filter(
                DocumentMetaExtension.set_id.in_(set_ids),
                DocumentMetaExtension.is_department_common.is_(True),
                Document.deleted_at.is_(None),
                Document.is_active.is_(True),
            )
            .group_by(DocumentMetaExtension.set_id)
            .all()
        )
        for set_id, count_files, latest_created_at in stats_rows:
            stats_map[set_id] = {
                "count_files": int(count_files),
                "latest_created_at": latest_created_at,
            }

    groups = []
    for item in sets:
        groups.append(
            {
                "id": item.id,
                "title": item.title,
                "expiry_date": item.expiry_date,
                "all_company": item.all_company,
                "count_files": stats_map[item.id]["count_files"],
                "latest_created_at": stats_map[item.id]["latest_created_at"],
            }
        )

    sidebar_context = get_sidebar_context(user, db)
    return templates.TemplateResponse(
        "web/departments/safety/common_docs_list.html",
        {
            "request": request,
            "current_user": user,
            "groups": groups,
            "search": search or "",
            "sort": sort,
            "date_from": date_from or "",
            "date_to": date_to or "",
            "success": _safe_url_text(success),
            "error": _safe_url_text(error),
            "page": pagination["page"],
            "total_pages": pagination["total_pages"],
            "total": total,
            **sidebar_context,
        },
    )


@router.get("/common-docs/create", response_class=HTMLResponse)
async def common_docs_create_page(
    request: Request,
    error: Annotated[Optional[str], Query()] = None,
    selected_user_ids: Annotated[Optional[list[int]], Query()] = None,
    title: Annotated[Optional[str], Query()] = None,
    expiry_date: Annotated[Optional[str], Query()] = None,
    all_company: Annotated[bool, Query()] = False,
    user: Annotated[User, Depends(get_current_user_from_cookie)] = None,
    db: Annotated[Session, Depends(get_db)] = None,
):
    SafetyService.ensure_safety_role(user)

    selected_users = selected_user_ids or []
    users = _active_safety_users(db)
    selected_user_map = {u.id: u for u in users}

    sidebar_context = get_sidebar_context(user, db)
    return templates.TemplateResponse(
        "web/departments/safety/common_docs_form.html",
        {
            "request": request,
            "current_user": user,
            "mode": "create",
            "users": users,
            "error": _safe_url_text(error),
            "selected_user_ids": selected_users,
            "selected_users": [
                selected_user_map[u] for u in selected_users if u in selected_user_map
            ],
            "selected_all_company": all_company,
            "selected_title": title or "",
            "selected_expiry_date": expiry_date or "",
            "existing_documents": [],
            "document_set_id": None,
            **sidebar_context,
        },
    )


@router.get("/common-docs/{set_id}", response_class=HTMLResponse)
async def common_docs_open_page(
    set_id: int,
    request: Request,
    error: Annotated[Optional[str], Query()] = None,
    user: Annotated[User, Depends(get_current_user_from_cookie)] = None,
    db: Annotated[Session, Depends(get_db)] = None,
):
    SafetyService.ensure_safety_role(user)

    details = _set_details(db=db, set_id=set_id)
    users = _active_safety_users(db)
    selected_user_map = {u.id: u for u in users}

    sidebar_context = get_sidebar_context(user, db)
    return templates.TemplateResponse(
        "web/departments/safety/common_docs_form.html",
        {
            "request": request,
            "current_user": user,
            "mode": "edit",
            "users": users,
            "error": _safe_url_text(error),
            "selected_user_ids": details["selected_user_ids"],
            "selected_users": [
                selected_user_map[u]
                for u in details["selected_user_ids"]
                if u in selected_user_map
            ],
            "selected_all_company": details["document_set"].all_company,
            "selected_title": details["document_set"].title,
            "selected_expiry_date": (
                details["document_set"].expiry_date.isoformat()
                if details["document_set"].expiry_date
                else ""
            ),
            "existing_documents": details["documents"],
            "document_set_id": details["document_set"].id,
            **sidebar_context,
        },
    )


@router.post("/documents/upload-common", response_model=None)
async def upload_common_document(
    title: Annotated[str, Form(...)],
    files: Annotated[list[UploadFile], File(...)],
    expiry_date: Annotated[Optional[str], Form()] = None,
    all_company: Annotated[bool, Form()] = False,
    grant_user_ids: Annotated[Optional[list[int]], Form()] = None,
    user: Annotated[User, Depends(get_current_user_from_cookie)] = None,
    db: Annotated[Session, Depends(get_db)] = None,
):
    SafetyService.ensure_safety_role(user)

    valid_files = [f for f in files if f and f.filename]
    if not valid_files:
        return RedirectResponse(
            url="/departments/safety/common-docs/create?error=Нужно выбрать хотя бы один файл",
            status_code=303,
        )

    for file in valid_files:
        if not validate_file_extension(file.filename, ALLOWED_DOCUMENT_EXTENSIONS):
            return RedirectResponse(
                url="/departments/safety/common-docs/create?error=Недопустимый тип файла",
                status_code=303,
            )

        file_bytes = await file.read()
        if len(file_bytes) > settings.MAX_FILE_SIZE:
            return RedirectResponse(
                url="/departments/safety/common-docs/create?error=Файл слишком большой",
                status_code=303,
            )
        await file.seek(0)

    parsed_expiry = _parse_expiry_date(expiry_date)
    selected_users = sorted(set(grant_user_ids or []))

    document_set = SafetyDocumentSet(
        title=title,
        expiry_date=parsed_expiry,
        all_company=all_company,
        created_by=user.id,
        updated_by=user.id,
    )
    db.add(document_set)
    db.flush()

    _sync_set_users(
        db=db,
        set_id=document_set.id,
        selected_user_ids=selected_users,
    )

    default_object_id = _resolve_default_object_id(db=db, actor=user)
    created_document_ids: list[int] = []

    for file in valid_files:
        file_bytes = await file.read()
        await file.seek(0)
        stored_path = await DocumentService.save_file(file, default_object_id)

        document = Document(
            title=title,
            description=None,
            category=DocumentCategory.SAFETY,
            file_path=stored_path,
            file_name=file.filename,
            file_size=len(file_bytes),
            file_type=file.content_type,
            object_id=default_object_id,
            created_by=user.id,
        )
        db.add(document)
        db.flush()
        created_document_ids.append(document.id)

        db.add(
            DocumentMetaExtension(
                document_id=document.id,
                owner_profile_id=None,
                set_id=document_set.id,
                expiry_date=parsed_expiry,
                is_department_common=True,
                department_code=DocumentCategory.SAFETY.value,
            )
        )

    _replace_access_rules_for_documents(
        db=db,
        actor=user,
        document_ids=created_document_ids,
        all_company=all_company,
        grant_user_ids=selected_users,
    )

    db.commit()
    return RedirectResponse(
        url="/departments/safety/common-docs?success=Набор документов создан",
        status_code=303,
    )


@router.post("/documents/common/{set_id}/update", response_model=None)
async def update_common_documents_set(
    set_id: int,
    title: Annotated[str, Form(...)],
    files: Annotated[Optional[list[UploadFile]], File()] = None,
    expiry_date: Annotated[Optional[str], Form()] = None,
    all_company: Annotated[bool, Form()] = False,
    grant_user_ids: Annotated[Optional[list[int]], Form()] = None,
    user: Annotated[User, Depends(get_current_user_from_cookie)] = None,
    db: Annotated[Session, Depends(get_db)] = None,
):
    SafetyService.ensure_safety_role(user)

    document_set = _get_set_or_404(db=db, set_id=set_id)
    parsed_expiry = _parse_expiry_date(expiry_date)
    selected_users = sorted(set(grant_user_ids or []))

    document_set.title = title
    document_set.expiry_date = parsed_expiry
    document_set.all_company = all_company
    document_set.updated_by = user.id

    _sync_set_users(
        db=db,
        set_id=set_id,
        selected_user_ids=selected_users,
    )

    active_docs = _set_documents_query(db, set_id).all()
    active_doc_ids = [doc.id for doc in active_docs]

    replacement_files = [f for f in (files or []) if f and f.filename]
    if replacement_files:
        for file in replacement_files:
            if not validate_file_extension(file.filename, ALLOWED_DOCUMENT_EXTENSIONS):
                return RedirectResponse(
                    url=f"/departments/safety/common-docs/{set_id}?error=Недопустимый тип файла",
                    status_code=303,
                )

            file_bytes = await file.read()
            if len(file_bytes) > settings.MAX_FILE_SIZE:
                return RedirectResponse(
                    url=f"/departments/safety/common-docs/{set_id}?error=Файл слишком большой",
                    status_code=303,
                )
            await file.seek(0)

        now_utc = datetime.now(timezone.utc)
        for doc in active_docs:
            doc.deleted_at = now_utc
            doc.is_active = False
            doc.updated_by = user.id

        default_object_id = _resolve_default_object_id(db=db, actor=user)
        active_doc_ids = []

        for file in replacement_files:
            file_bytes = await file.read()
            await file.seek(0)
            stored_path = await DocumentService.save_file(file, default_object_id)
            document = Document(
                title=title,
                description=None,
                category=DocumentCategory.SAFETY,
                file_path=stored_path,
                file_name=file.filename,
                file_size=len(file_bytes),
                file_type=file.content_type,
                object_id=default_object_id,
                created_by=user.id,
            )
            db.add(document)
            db.flush()
            active_doc_ids.append(document.id)

            db.add(
                DocumentMetaExtension(
                    document_id=document.id,
                    owner_profile_id=None,
                    set_id=document_set.id,
                    expiry_date=parsed_expiry,
                    is_department_common=True,
                    department_code=DocumentCategory.SAFETY.value,
                )
            )
    else:
        if active_doc_ids:
            db.query(Document).filter(Document.id.in_(active_doc_ids)).update(
                {
                    Document.title: title,
                    Document.updated_by: user.id,
                },
                synchronize_session=False,
            )
            db.query(DocumentMetaExtension).filter(
                DocumentMetaExtension.document_id.in_(active_doc_ids)
            ).update(
                {
                    DocumentMetaExtension.expiry_date: parsed_expiry,
                    DocumentMetaExtension.set_id: document_set.id,
                    DocumentMetaExtension.is_department_common: True,
                    DocumentMetaExtension.department_code: DocumentCategory.SAFETY.value,
                },
                synchronize_session=False,
            )

    _replace_access_rules_for_documents(
        db=db,
        actor=user,
        document_ids=active_doc_ids,
        all_company=all_company,
        grant_user_ids=selected_users,
    )

    db.commit()
    return RedirectResponse(
        url="/departments/safety/common-docs?success=Набор документов обновлен",
        status_code=303,
    )


@router.post("/documents/common/{set_id}/delete", response_model=None)
async def delete_common_documents_set(
    set_id: int,
    user: Annotated[User, Depends(get_current_user_from_cookie)] = None,
    db: Annotated[Session, Depends(get_db)] = None,
):
    SafetyService.ensure_safety_role(user)

    document_set = _get_set_or_404(db=db, set_id=set_id)
    active_docs = _set_documents_query(db, set_id).all()

    now_utc = datetime.now(timezone.utc)
    document_set.archived_at = now_utc
    document_set.updated_by = user.id

    for doc in active_docs:
        doc.deleted_at = now_utc
        doc.is_active = False
        doc.updated_by = user.id

    db.commit()
    return RedirectResponse(
        url="/departments/safety/common-docs?success=Набор документов удален",
        status_code=303,
    )


@router.post("/documents/grant-access", response_model=None)
async def grant_document_access(
    payload: SafetyDocumentAccessGrant,
    user: Annotated[User, Depends(get_current_user_from_cookie)],
    db: Annotated[Session, Depends(get_db)],
):
    rule = SafetyService.grant_document_access(db=db, actor=user, payload=payload)
    return JSONResponse(
        {
            "status": "ok",
            "rule_id": rule.id,
            "document_id": rule.document_id,
            "subject_type": rule.subject_type,
            "subject_value": rule.subject_value,
        }
    )


@router.post("/documents/metadata", response_model=None)
async def update_document_metadata(
    payload: SafetyDocumentMetadataUpdate,
    user: Annotated[User, Depends(get_current_user_from_cookie)],
    db: Annotated[Session, Depends(get_db)],
):
    meta = SafetyService.set_document_metadata(db=db, actor=user, payload=payload)
    return JSONResponse(
        {
            "status": "ok",
            "document_id": meta.document_id,
            "expiry_date": meta.expiry_date.isoformat() if meta.expiry_date else None,
            "reminder_days": meta.reminder_days,
            "is_department_common": meta.is_department_common,
        }
    )
