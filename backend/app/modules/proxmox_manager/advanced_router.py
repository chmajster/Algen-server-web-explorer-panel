from fastapi import APIRouter

from .advanced import router as advanced_router


router = APIRouter()
router.include_router(advanced_router, include_in_schema=False)
