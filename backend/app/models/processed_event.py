from app.models.base import FirestoreModel


class ProcessedEvent(FirestoreModel):
    event_id: str
    summarized_text: str
