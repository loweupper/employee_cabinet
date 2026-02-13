# Migration Guide: User Role Fix and Department System

## Overview
This guide explains the changes made to fix the Pydantic validation error and implement the department system.

> **🐳 Running in Docker?** See [DOCKER_MIGRATION_GUIDE.md](./DOCKER_MIGRATION_GUIDE.md) for Docker-specific instructions and the migration helper script.

## Problem Fixed
Previously, `UserRoleEnum` in schemas only had 2 roles (employee, admin) while the `UserRole` model had 6 roles, causing validation errors when users with roles like "accountant", "hr", "engineer", or "lawyer" tried to authenticate.

## Changes Made

### 1. Fixed User Roles
Updated `UserRoleEnum` in `app/modules/auth/schemas.py` to include all 6 roles:
- admin
- accountant
- hr
- engineer
- lawyer
- employee

### 2. Department System
Replaced the text-based `department` field with a proper relational database model:

**New Model**: `Department` with:
- `id` (BigInteger, primary key)
- `name` (String, unique, indexed)
- `description` (String, optional)
- `created_at`, `updated_at` timestamps

**Updated Model**: `User` now has:
- `department_id` (foreign key to departments table)
- `department_rel` (relationship to Department model)

### 3. Database Migration
Location: `app/migrations/versions/001_add_department_model.py`

The migration script:
1. Creates the `departments` table
2. Adds `department_id` foreign key column to `users` table
3. Seeds 6 standard departments:
   - Бухгалтерия (Accounting)
   - Кадры (HR)
   - Инженерия (Engineering)
   - Юридический (Legal)
   - Администрация (Administration)
   - Общий (General)
4. Migrates existing users to "Общий" department
5. Removes the old `department` text column

### 4. Admin UI Updates
The admin panel (`/admin/users`) now features:
- Dropdown select for department assignment
- Shows department name in user list
- New department management endpoints

## Running the Migration

> **🐳 Docker users**: Use `./migrate.sh upgrade` or see [DOCKER_MIGRATION_GUIDE.md](./DOCKER_MIGRATION_GUIDE.md)

### Prerequisites
Ensure you have:
- PostgreSQL database running
- Environment variables configured in `.env` file
- Alembic installed (already in requirements.txt)

### Steps

1. **Backup your database** (important!)
   ```bash
   pg_dump -U your_user -d your_database > backup_before_migration.sql
   ```

2. **Navigate to the app directory**
   ```bash
   cd app
   ```

3. **Run the migration**
   ```bash
   alembic upgrade head
   ```

4. **Verify the migration**
   ```sql
   -- Check departments table
   SELECT * FROM departments;
   
   -- Check users have department_id
   SELECT id, email, department_id FROM users LIMIT 5;
   ```

### Rolling Back (if needed)
If you need to rollback the migration:
```bash
alembic downgrade -1
```

This will:
- Restore the old `department` text column
- Migrate data from `department_id` back to `department` text
- Remove the `departments` table

## Using the Department System

### In Code

**Get user with department:**
```python
from sqlalchemy.orm import joinedload

user = db.query(User).options(joinedload(User.department_rel)).filter(User.id == user_id).first()
department_name = user.department_rel.name if user.department_rel else None
```

**Create a new department:**
```python
from modules.auth.department_service import create_department
from modules.auth.schemas import DepartmentCreate

dept_data = DepartmentCreate(name="New Department", description="Description")
department = create_department(db, dept_data)
```

**Assign department to user:**
```python
user.department_id = department.id
db.commit()
```

### Admin API Endpoints

**List departments:**
```
GET /admin/departments
```

**Create department:**
```
POST /admin/departments
Body: { "name": "Department Name", "description": "Optional description" }
```

**Update department:**
```
PUT /admin/departments/{department_id}
Body: { "name": "New Name", "description": "New description" }
```

**Delete department:**
```
DELETE /admin/departments/{department_id}
```

Note: Cannot delete departments that have users assigned.

## Testing

### Verify Role Validation
Test that all role types can now authenticate without validation errors:
```python
# This should now work without ValidationError
user = User(email="test@example.com", role=UserRole.ACCOUNTANT)
user_read = UserRead.from_orm(user)  # No validation error
```

### Verify Department Dropdown
1. Login as admin
2. Navigate to `/admin/users`
3. Click edit on any user
4. Verify that "Отдел" field is now a dropdown with 6 departments
5. Select a department and save
6. Verify the user's department is updated correctly

## Troubleshooting

### Issue: Migration fails with "column already exists"
**Solution**: The database might already have been modified. Check with:
```sql
\d users  -- PostgreSQL command to describe table
```
If `department_id` already exists, you may need to adjust the migration.

### Issue: Users can't login after migration
**Solution**: Check that UserRoleEnum includes all role values:
```python
from modules.auth.schemas import UserRoleEnum
print(list(UserRoleEnum))  # Should show all 6 roles
```

### Issue: Department dropdown is empty
**Solution**: Verify departments were seeded:
```sql
SELECT COUNT(*) FROM departments;  -- Should return 6
```

If no departments exist, manually run:
```sql
INSERT INTO departments (name, description) VALUES
('Бухгалтерия', 'Финансовый отдел компании'),
('Кадры', 'Отдел по управлению персоналом'),
('Инженерия', 'Технический отдел'),
('Юридический', 'Юридический отдел'),
('Администрация', 'Административный отдел'),
('Общий', 'Общий отдел для сотрудников');
```

## Additional Notes

- The department system uses `ondelete='SET NULL'` for the foreign key, so deleting a department will set users' `department_id` to NULL rather than failing or cascading.
- All departments must have unique names.
- The old `department` text field has been completely removed from the User model.
- Department names and descriptions can be updated through the admin API.

## Support

For issues or questions, refer to:
- Migration script: `app/migrations/versions/001_add_department_model.py`
- Department service: `app/modules/auth/department_service.py`
- Models: `app/modules/auth/models.py`
- Schemas: `app/modules/auth/schemas.py`
