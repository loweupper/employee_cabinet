DEPARTMENTS = [
    {"name": "Бухгалтерия", "code": "accounting", "icon": "💰"},
    {"name": "Отдел кадров", "code": "hr", "icon": "👔"},
    {"name": "Технический отдел", "code": "technical", "icon": "🔧"},
    {"name": "Юридический отдел", "code": "legal", "icon": "⚖️"},
    {"name": "Без отдела", "code": "general", "icon": "👤"},
]

def init_departments(db: Session):
    for dept_data in DEPARTMENTS:
        existing = db.query(Department).filter(Department.code == dept_data["code"]).first()
        if not existing:
            db.add(Department(**dept_data))
    db.commit()