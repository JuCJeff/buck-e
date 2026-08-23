from datetime import datetime
from typing import Any, Optional, Self

from pydantic import BaseModel, ConfigDict


class FirestoreModel(BaseModel):
    """Base class for models stored as Firestore documents.

    `id` mirrors the Firestore document ID and is never written into
    the document body itself. `created_at`/`updated_at` are stored as
    Firestore native timestamps.
    """

    model_config = ConfigDict(populate_by_name=True)

    id: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    def to_firestore(self) -> dict[str, Any]:
        """Serialize to a dict suitable for Firestore's set()/update()."""
        return self.model_dump(exclude={"id"}, exclude_none=True)

    @classmethod
    def from_firestore(cls, doc_id: str, data: dict[str, Any]) -> Self:
        """Build a model instance from a Firestore DocumentSnapshot's
        (id, to_dict()) pair."""
        return cls(id=doc_id, **data)
