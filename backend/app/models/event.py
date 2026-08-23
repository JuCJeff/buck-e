from datetime import datetime

from app.models.base import FirestoreModel


class Event(FirestoreModel):
    sender: str
    sent_on: datetime
    email_subject: str
    email_content: str
