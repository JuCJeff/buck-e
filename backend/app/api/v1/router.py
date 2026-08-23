from fastapi import APIRouter

from app.api.v1.events import router as events_router
from app.api.v1.processed_events import router as processed_events_router

router = APIRouter()


@router.get("/health")
async def health() -> dict:
    return {"status": "ok"}


router.include_router(events_router)
router.include_router(processed_events_router)
