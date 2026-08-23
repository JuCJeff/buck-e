from typing import Optional

from fastapi.testclient import TestClient

from app.db.collections import get_event_repository, get_processed_event_repository
from app.main import app
from app.models.event import Event
from app.models.processed_event import ProcessedEvent


class FakeEventRepository:
    def __init__(self) -> None:
        self._items: dict[str, Event] = {}

    def get(self, doc_id: str) -> Optional[Event]:
        return self._items.get(doc_id)

    def list(self, limit: int = 50) -> list[Event]:
        return list(self._items.values())[:limit]

    def create(self, item: Event) -> Event:
        item.id = str(len(self._items) + 1)
        self._items[item.id] = item
        return item


class FakeProcessedEventRepository:
    def __init__(self) -> None:
        self._items: dict[str, ProcessedEvent] = {}

    def get(self, doc_id: str) -> Optional[ProcessedEvent]:
        return self._items.get(doc_id)

    def list(self, limit: int = 50) -> list[ProcessedEvent]:
        return list(self._items.values())[:limit]

    def create(self, item: ProcessedEvent) -> ProcessedEvent:
        item.id = str(len(self._items) + 1)
        self._items[item.id] = item
        return item


def test_create_and_list_processed_event(client: TestClient) -> None:
    fake_event_repo = FakeEventRepository()
    fake_repo = FakeProcessedEventRepository()
    app.dependency_overrides[get_event_repository] = lambda: fake_event_repo
    app.dependency_overrides[get_processed_event_repository] = lambda: fake_repo

    try:
        event = fake_event_repo.create(
            Event(
                sender="alerts@buck-e.app",
                sent_on="2026-08-23T20:50:00Z",
                email_subject="Weekly summary",
                email_content="Here is your weekly summary.",
            )
        )

        create_response = client.post(
            "/api/v1/processed-events/",
            json={
                "event_id": event.id,
                "summarized_text": "Weekly summary: nothing notable.",
            },
        )
        assert create_response.status_code == 201
        created = create_response.json()
        assert created["id"] is not None
        assert created["event_id"] == event.id

        list_response = client.get("/api/v1/processed-events/")
        assert list_response.status_code == 200
        assert len(list_response.json()) == 1

        get_response = client.get(f"/api/v1/processed-events/{created['id']}")
        assert get_response.status_code == 200
        assert get_response.json()["summarized_text"] == "Weekly summary: nothing notable."
    finally:
        app.dependency_overrides.pop(get_event_repository, None)
        app.dependency_overrides.pop(get_processed_event_repository, None)


def test_create_processed_event_rejects_missing_event(client: TestClient) -> None:
    fake_event_repo = FakeEventRepository()
    fake_repo = FakeProcessedEventRepository()
    app.dependency_overrides[get_event_repository] = lambda: fake_event_repo
    app.dependency_overrides[get_processed_event_repository] = lambda: fake_repo

    try:
        response = client.post(
            "/api/v1/processed-events/",
            json={
                "event_id": "does-not-exist",
                "summarized_text": "Weekly summary: nothing notable.",
            },
        )
        assert response.status_code == 400
        assert len(fake_repo.list()) == 0
    finally:
        app.dependency_overrides.pop(get_event_repository, None)
        app.dependency_overrides.pop(get_processed_event_repository, None)


def test_get_missing_processed_event_returns_404(client: TestClient) -> None:
    fake_repo = FakeProcessedEventRepository()
    app.dependency_overrides[get_processed_event_repository] = lambda: fake_repo

    try:
        response = client.get("/api/v1/processed-events/does-not-exist")
        assert response.status_code == 404
    finally:
        app.dependency_overrides.pop(get_processed_event_repository, None)
