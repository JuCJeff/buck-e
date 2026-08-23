from fastapi import APIRouter

from app.api.v1.events import router as events_router

router = APIRouter()


@router.get("/health")
async def health() -> dict:
    return {"status": "ok"}


router.include_router(events_router)
