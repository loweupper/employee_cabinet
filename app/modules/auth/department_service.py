"""
Service for department CRUD operations
"""

from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from fastapi import HTTPException
from typing import List, Optional

from modules.auth.models import Department
from modules.auth.schemas import DepartmentCreate, DepartmentUpdate


def get_departments(db: Session, skip: int = 0, limit: int = 100) -> List[Department]:
    """Get all departments"""
    return db.query(Department).offset(skip).limit(limit).all()


def get_department_by_id(db: Session, department_id: int) -> Optional[Department]:
    """Get department by ID"""
    return db.query(Department).filter(Department.id == department_id).first()


def get_department_by_name(db: Session, name: str) -> Optional[Department]:
    """Get department by name"""
    return db.query(Department).filter(Department.name == name).first()


def create_department(db: Session, department: DepartmentCreate) -> Department:
    """Create a new department"""
    # Check if department with this name already exists
    existing = get_department_by_name(db, department.name)
    if existing:
        raise HTTPException(status_code=400, detail="Department with this name already exists")

    db_department = Department(name=department.name, description=department.description)
    db.add(db_department)
    try:
        db.commit()
        db.refresh(db_department)
        return db_department
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=400, detail="Failed to create department")


def update_department(db: Session, department_id: int, department: DepartmentUpdate) -> Optional[Department]:
    """Update a department"""
    db_department = get_department_by_id(db, department_id)
    if not db_department:
        return None

    # Check if new name conflicts with existing department
    if department.name and department.name != db_department.name:
        existing = get_department_by_name(db, department.name)
        if existing:
            raise HTTPException(status_code=400, detail="Department with this name already exists")

    if department.name is not None:
        db_department.name = department.name
    if department.description is not None:
        db_department.description = department.description

    try:
        db.commit()
        db.refresh(db_department)
        return db_department
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=400, detail="Failed to update department")


def delete_department(db: Session, department_id: int) -> bool:
    """Delete a department"""
    db_department = get_department_by_id(db, department_id)
    if not db_department:
        return False

    # Check if department has users
    if db_department.users:
        raise HTTPException(
            status_code=400, detail=f"Cannot delete department with {len(db_department.users)} assigned users"
        )

    db.delete(db_department)
    db.commit()
    return True
