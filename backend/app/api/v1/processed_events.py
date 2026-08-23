from fastapi import APIRouter, Depends, HTTPException

from app.db.collections import get_event_repository, get_processed_event_repository
from app.db.repository import FirestoreRepository
from app.models.event import Event
from app.models.processed_event import ProcessedEvent

router = APIRouter(prefix="/processed-events", tags=["processed-events"])


@router.get("/", response_model=list[ProcessedEvent])
async def list_processed_events(
    repo: FirestoreRepository[ProcessedEvent] = Depends(get_processed_event_repository),
) -> list[ProcessedEvent]:
    return repo.list()


@router.get("/{processed_event_id}", response_model=ProcessedEvent)
async def get_processed_event(
    processed_event_id: str,
    repo: FirestoreRepository[ProcessedEvent] = Depends(get_processed_event_repository),
) -> ProcessedEvent:
    processed_event = repo.get(processed_event_id)
    if processed_event is None:
        raise HTTPException(status_code=404, detail="Processed event not found")
    return processed_event


@router.post("/", response_model=ProcessedEvent, status_code=201)
async def create_processed_event(
    payload: ProcessedEvent,
    repo: FirestoreRepository[ProcessedEvent] = Depends(get_processed_event_repository),
    event_repo: FirestoreRepository[Event] = Depends(get_event_repository),
) -> ProcessedEvent:
    if event_repo.get(payload.event_id) is None:
        raise HTTPException(status_code=400, detail="Referenced event does not exist")
    return repo.create(payload)
