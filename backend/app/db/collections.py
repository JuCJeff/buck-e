from fastapi import Depends
from google.cloud import firestore

from app.core.firestore import get_firestore_client
from app.db.repository import FirestoreRepository
from app.models.event import Event
from app.models.processed_event import ProcessedEvent


def get_event_repository(
    client: firestore.Client = Depends(get_firestore_client),
) -> FirestoreRepository[Event]:
    return FirestoreRepository(client, collection="events", model=Event)


def get_processed_event_repository(
    client: firestore.Client = Depends(get_firestore_client),
) -> FirestoreRepository[ProcessedEvent]:
    return FirestoreRepository(client, collection="processed_events", model=ProcessedEvent)
