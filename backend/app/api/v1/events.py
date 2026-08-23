from fastapi import APIRouter, Depends, HTTPException

from app.db.collections import get_event_repository
from app.db.repository import FirestoreRepository
from app.models.event import Event

router = APIRouter(prefix="/events", tags=["events"])


@router.get("/", response_model=list[Event])
async def list_events(
    repo: FirestoreRepository[Event] = Depends(get_event_repository),
) -> list[Event]:
    return repo.list()


@router.get("/{event_id}", response_model=Event)
async def get_event(
    event_id: str,
    repo: FirestoreRepository[Event] = Depends(get_event_repository),
) -> Event:
    event = repo.get(event_id)
    if event is None:
        raise HTTPException(status_code=404, detail="Event not found")
    return event


@router.post("/", response_model=Event, status_code=201)
async def create_event(
    payload: Event,
    repo: FirestoreRepository[Event] = Depends(get_event_repository),
) -> Event:
    return repo.create(payload)
