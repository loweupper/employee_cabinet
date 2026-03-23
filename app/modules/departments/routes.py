from fastapi import APIRouter

from modules.departments.safety.routes import router as safety_router

router = APIRouter(prefix="/departments", tags=["departments"])
router.include_router(safety_router)
