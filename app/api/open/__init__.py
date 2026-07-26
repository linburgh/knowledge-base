from fastapi import APIRouter

from app.api.open import routes
from app.api.open.dependencies import rate_limit

router = APIRouter(prefix="/open", tags=["Open API"], dependencies=[])
router.include_router(routes.router)

__all__ = ("router",)
