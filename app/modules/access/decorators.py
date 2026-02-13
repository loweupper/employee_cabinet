from fastapi import HTTPException, Depends
from modules.access.service import AccessService
from modules.auth.dependencies import get_current_user
from core.database import get_db


def requires_access(resource_type: str, permission: str):
    def wrapper(resource_id_param: str):

        def decorator(func):
            async def inner(*args, **kwargs):
                db = kwargs.get("db")
                user = kwargs.get("current_user")

                resource_id = kwargs.get(resource_id_param)

                if not AccessService.has_access(
                    user=user,
                    resource_type=resource_type,
                    resource_id=resource_id,
                    permission=permission,
                    db=db
                ):
                    raise HTTPException(status_code=403, detail="Access denied")

                return await func(*args, **kwargs)

            return inner

        return decorator

    return wrapper
