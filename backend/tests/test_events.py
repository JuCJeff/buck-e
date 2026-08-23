from typing import Optional

from fastapi.testclient import TestClient

from app.db.collections import get_event_repository
from app.main import app
from app.models.event import Event


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


def test_create_and_list_event(client: TestClient) -> None:
    fake_repo = FakeEventRepository()
    app.dependency_overrides[get_event_repository] = lambda: fake_repo

    try:
        create_response = client.post(
            "/api/v1/events/",
            json={
                "sender": "alerts@buck-e.app",
                "sent_on": "2026-08-23T20:50:00Z",
                "email_subject": "Weekly summary",
                "email_content": "Here is your weekly summary.",
            },
        )
        assert create_response.status_code == 201
        created = create_response.json()
        assert created["id"] is not None

        list_response = client.get("/api/v1/events/")
        assert list_response.status_code == 200
        assert len(list_response.json()) == 1

        get_response = client.get(f"/api/v1/events/{created['id']}")
        assert get_response.status_code == 200
        assert get_response.json()["email_subject"] == "Weekly summary"
    finally:
        app.dependency_overrides.pop(get_event_repository, None)


def test_get_missing_event_returns_404(client: TestClient) -> None:
    fake_repo = FakeEventRepository()
    app.dependency_overrides[get_event_repository] = lambda: fake_repo

    try:
        response = client.get("/api/v1/events/does-not-exist")
        assert response.status_code == 404
    finally:
        app.dependency_overrides.pop(get_event_repository, None)
