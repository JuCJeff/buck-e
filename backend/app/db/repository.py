from datetime import datetime, timezone
from typing import Generic, Optional, TypeVar

from google.cloud import firestore

from app.models.base import FirestoreModel

ModelT = TypeVar("ModelT", bound=FirestoreModel)


class FirestoreRepository(Generic[ModelT]):
    """Thin generic CRUD access layer over a single Firestore collection."""

    def __init__(self, client: firestore.Client, collection: str, model: type[ModelT]):
        self._collection = client.collection(collection)
        self._model = model

    def get(self, doc_id: str) -> Optional[ModelT]:
        snap = self._collection.document(doc_id).get()
        if not snap.exists:
            return None
        return self._model.from_firestore(snap.id, snap.to_dict())

    def list(self, limit: int = 50) -> list[ModelT]:
        docs = self._collection.limit(limit).stream()
        return [self._model.from_firestore(d.id, d.to_dict()) for d in docs]

    def create(self, item: ModelT) -> ModelT:
        now = datetime.now(timezone.utc)
        item.created_at = now
        item.updated_at = now
        doc_ref = self._collection.document()
        doc_ref.set(item.to_firestore())
        item.id = doc_ref.id
        return item

    def update(self, doc_id: str, item: ModelT) -> ModelT:
        item.updated_at = datetime.now(timezone.utc)
        self._collection.document(doc_id).update(item.to_firestore())
        item.id = doc_id
        return item

    def delete(self, doc_id: str) -> None:
        self._collection.document(doc_id).delete()
