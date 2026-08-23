from fastapi import FastAPI

from app.api.v1.router import router as v1_router
from app.core.config import settings

app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    debug=settings.debug,
)

app.include_router(v1_router, prefix="/api/v1")


@app.get("/")
async def root() -> dict:
    return {"message": f"Welcome to {settings.app_name}"}
