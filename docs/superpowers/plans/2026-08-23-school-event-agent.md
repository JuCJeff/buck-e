# School Event Agent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the Gmail→triage→catalog→RSVP→Calendar pipeline described in the spec, deployed on Cloud Run + Vercel, for the Collaborative Partner track.

**Architecture:** FastAPI backend on Cloud Run receives Gmail push notifications via Pub/Sub, runs an ADK+Gemini triage/summarizer call per new email, stores results in Firestore, and serves a catalog API. A second ADK+Gemini call (the "RSVP agent") resolves which Google Form fields are already known about the user vs. need asking, driven by a plain-Python orchestration loop — not a stateful ADK session — so the agent stays a simple, testable structured-output call invoked once per HTTP round trip. Next.js frontend on Vercel renders the catalog and the attend/Q&A flow.

**Tech Stack:** FastAPI, google-adk, google-genai (via ADK), google-cloud-firestore, google-api-python-client (Gmail/Calendar/Forms/OAuth), Next.js (App Router), shadcn/ui.

**Spec:** [docs/superpowers/specs/2026-08-23-school-event-agent-design.md](../specs/2026-08-23-school-event-agent-design.md)

## Global Constraints

- Gemini model: 3.5 or newer, via Gemini API or Vertex AI — this plan uses `gemini-flash-latest` as a placeholder alias; **confirm at build time it resolves to ≥3.5** and pin an explicit model ID before the demo.
- Agent framework: Google ADK (both the triage agent and the RSVP agent).
- GCP infra used: Cloud Pub/Sub (Gmail push) + Firestore (data store) — both required, per spec.
- Single demo user only — one Google account, OAuth'd once server-side. No frontend login flow.
- RSVP signup automation is scoped to Google Forms only (prefilled-link + one user click — no unofficial form-submission POST).
- Collaboration point is RSVP time only — triage is a fully automatic classifier, no user-in-the-loop there.
- Backend package is `app` (installed via `uv sync`, `[tool.uv] package = true` in `backend/pyproject.toml`). Add dependencies with `uv add <pkg>` from `backend/`, run tests with `uv run pytest`.

---

## Reconciliation note (read before Task 1)

A teammate independently built a Firestore data layer on `main` while this
plan was being written — `backend/app/models/` (a `FirestoreModel` base +
`Event` + `ProcessedEvent`), `backend/app/db/` (a generic
`FirestoreRepository[T]` with get/list/create/update/delete), Firestore
client setup in `backend/app/core/firestore.py`, and
`GET`/`POST /api/v1/events` + `/api/v1/processed-events` with sender-domain
allowlist validation. Tasks below have been rewritten to build on that
foundation instead of duplicating it:

- **No `backend/app/models.py` gets created.** `EventStatus` and the new
  `ProcessedEvent` fields live in the existing `backend/app/models/processed_event.py`.
  `TriageResult` and `FieldResolution` are defined locally where they're
  used (`agents/triage_agent.py`, `agents/rsvp_agent.py`) since they're
  transient agent I/O, never persisted directly.
- **No `backend/app/services/firestore_client.py` gets created.** Everything
  reuses the existing `app.core.firestore.get_firestore_client`.
- **The catalog and RSVP APIs operate on `ProcessedEvent`, not a flat
  `EventRecord`.** Routes live under `/api/v1/processed-events/...`, not
  `/api/v1/events/...` — `/events` stays the raw-email endpoint the
  teammate built.
- **All new `ProcessedEvent` fields default** so the teammate's existing
  tests (which `POST` only `event_id` + `summarized_text`) keep passing
  unmodified.
- Task numbering is unchanged from the original plan; only task bodies
  changed. Tasks 2, 4, 8, 9, 15, 16 are unaffected by this reconciliation.

---

## Implementation note (read before Task 11)

The spec describes the RSVP agent as having "tools + persistent memory." In this
plan, the persistent memory is the Firestore `user_profile` doc (Task 10), not
ADK's internal session/state machinery. The agent itself is a single
structured-output call — given the form's fields and the known profile, it
returns which fields are already resolved and which need asking — invoked once
per HTTP request (on `/attend` and again on `/rsvp-answer`) rather than run as
a long-lived stateful session. This is functionally identical to the spec (the
user is asked only what's missing, and answers persist across events) but far
simpler to implement and test. Flag this to the user as a one-line heads-up
when you reach Task 11, don't silently re-interpret the spec.

---

### Task 1: Config additions & ProcessedEvent triage fields

Builds on the existing `backend/app/models/processed_event.py` and
`backend/app/core/config.py` — see the Reconciliation note above.

**Files:**
- Modify: `backend/app/core/config.py`
- Modify: `backend/app/models/processed_event.py`
- Test: `backend/tests/test_processed_event_model.py`

**Interfaces:**
- Produces: `app.core.config.settings` (extended with Gemini/Pub-Sub/Calendar/OAuth
  fields), `app.models.processed_event.EventStatus`, `ProcessedEvent` (extended)

- [ ] **Step 1: Confirm pytest config exists**

Check `backend/pyproject.toml` for a `[tool.pytest.ini_options]` section with
`testpaths = ["tests"]`. If missing, append it. (It may already be present —
verify before adding, don't duplicate the section.)

- [ ] **Step 2: Write the failing test**

Create `backend/tests/test_processed_event_model.py`:

```python
from app.models.processed_event import EventStatus, ProcessedEvent


def test_processed_event_new_fields_default_for_backward_compatibility():
    """The teammate's existing POST /processed-events/ only sends event_id
    and summarized_text — every new field here must default so that keeps
    working unmodified."""
    processed = ProcessedEvent(event_id="e1", summarized_text="summary")

    assert processed.is_event is True
    assert processed.confidence == 1.0
    assert processed.title == ""
    assert processed.when == ""
    assert processed.where == ""
    assert processed.signup_type == "none"
    assert processed.form_url is None
    assert processed.status == EventStatus.NEW
    assert processed.calendar_event_id is None


def test_event_status_values():
    assert EventStatus.NEW == "new"
    assert EventStatus.NEEDS_REVIEW == "needs_review"
    assert EventStatus.ATTENDING == "attending"
    assert EventStatus.DECLINED == "declined"
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/test_processed_event_model.py -v`
Expected: FAIL with `ImportError: cannot import name 'EventStatus'`

- [ ] **Step 4: Extend config**

In `backend/app/core/config.py`, add these fields inside `Settings` (after
the existing `allowed_email_domains`/`allowed_email_domains_list` block —
do not touch or rename any existing field):

```python
    # Gemini / ADK
    gemini_model: str = "gemini-flash-latest"

    # Gmail push ingestion
    gmail_pubsub_topic: str = ""

    # Calendar
    calendar_id: str = "primary"

    # Gmail/Calendar/Forms end-user OAuth (separate from the
    # google_application_credentials service account above, which is
    # Firestore-only)
    google_client_secrets_path: str = "credentials.json"
    google_token_path: str = "token.json"
```

- [ ] **Step 5: Extend `backend/app/models/processed_event.py`**

Replace the file's full contents with:

```python
from enum import StrEnum
from typing import Literal, Optional

from app.models.base import FirestoreModel

SignupType = Literal["none", "form", "reply"]


class EventStatus(StrEnum):
    NEW = "new"
    NEEDS_REVIEW = "needs_review"
    ATTENDING = "attending"
    DECLINED = "declined"


class ProcessedEvent(FirestoreModel):
    event_id: str
    summarized_text: str
    is_event: bool = True
    confidence: float = 1.0
    title: str = ""
    when: str = ""
    where: str = ""
    signup_type: SignupType = "none"
    form_url: Optional[str] = None
    status: EventStatus = EventStatus.NEW
    calendar_event_id: Optional[str] = None
```

- [ ] **Step 6: Run the new test, then the full suite, to verify nothing broke**

Run: `cd backend && uv run pytest tests/test_processed_event_model.py -v`
Expected: PASS

Run: `cd backend && uv run pytest -v`
Expected: all PASS, including the teammate's existing `test_events.py` and
`test_processed_events.py` unmodified — this is the backward-compatibility
check for Step 5's new defaults.

- [ ] **Step 7: Commit**

```bash
git add backend/pyproject.toml backend/app/core/config.py backend/app/models/processed_event.py backend/tests/test_processed_event_model.py
git commit -m "feat: add triage fields to ProcessedEvent and extend settings

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 2: Google OAuth credential helper

**Files:**
- Create: `backend/app/core/google_auth.py`
- Test: `backend/tests/test_google_auth.py`

**Interfaces:**
- Consumes: `app.core.config.settings.google_client_secrets_path`, `.google_token_path`
- Produces: `app.core.google_auth.get_credentials(scopes: list[str]) -> google.oauth2.credentials.Credentials`
  — every later task that talks to Gmail/Calendar/Forms calls this with the scopes it needs.

- [ ] **Step 1: Add the auth dependencies**

```bash
cd backend && uv add google-auth-oauthlib google-auth google-api-python-client
```

- [ ] **Step 2: Write the failing test**

Create `backend/tests/test_google_auth.py`:

```python
import json
from unittest.mock import MagicMock, patch

from app.core.google_auth import get_credentials


def test_get_credentials_returns_cached_valid_token(tmp_path, monkeypatch):
    token_path = tmp_path / "token.json"
    token_path.write_text(json.dumps({
        "token": "abc", "refresh_token": "def",
        "client_id": "x", "client_secret": "y",
        "scopes": ["https://www.googleapis.com/auth/gmail.readonly"],
    }))
    monkeypatch.setattr(
        "app.core.google_auth.settings.google_token_path", str(token_path)
    )

    fake_creds = MagicMock(valid=True)
    with patch(
        "app.core.google_auth.Credentials.from_authorized_user_file",
        return_value=fake_creds,
    ) as from_file:
        creds = get_credentials(["https://www.googleapis.com/auth/gmail.readonly"])

    from_file.assert_called_once()
    assert creds is fake_creds
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/test_google_auth.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.core.google_auth'`

- [ ] **Step 4: Write `backend/app/core/google_auth.py`**

```python
import os

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

from app.core.config import settings


def get_credentials(scopes: list[str]) -> Credentials:
    """Single-demo-user OAuth: cache the token on disk, refresh or
    re-consent as needed. Not safe for multi-user use — see spec §7."""
    creds: Credentials | None = None
    token_path = settings.google_token_path

    if os.path.exists(token_path):
        creds = Credentials.from_authorized_user_file(token_path, scopes)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                settings.google_client_secrets_path, scopes
            )
            creds = flow.run_local_server(port=0)
        with open(token_path, "w") as token_file:
            token_file.write(creds.to_json())

    return creds
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/test_google_auth.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/pyproject.toml backend/uv.lock backend/app/core/google_auth.py backend/tests/test_google_auth.py
git commit -m "feat: add cached Google OAuth credential helper

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

**Manual note for this task:** you still need a real `credentials.json` (OAuth
client) from a GCP project's "APIs & Services > Credentials" page, and to run
the helper once interactively (`uv run python -c "from app.core.google_auth import get_credentials; get_credentials(['https://www.googleapis.com/auth/gmail.readonly','https://www.googleapis.com/auth/calendar','https://www.googleapis.com/auth/forms.body.readonly'])"`)
to produce the first `token.json` before the webhook/agent tasks can hit live APIs.

---

### Task 3: Dedupe service

Reuses the existing `app.core.firestore.get_firestore_client` (already
added by the teammate's Firestore work — `google-cloud-firestore` is
already a dependency, no need to re-add it) rather than creating a
duplicate Firestore client.

**Files:**
- Create: `backend/app/services/dedupe.py`
- Test: `backend/tests/test_dedupe.py`

**Interfaces:**
- Consumes: `app.core.firestore.get_firestore_client`
- Produces: `app.services.dedupe.is_processed(db, message_id: str) -> bool`,
  `app.services.dedupe.mark_processed(db, message_id: str) -> None`
  — both take `db` as an explicit param so tests can pass a fake.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_dedupe.py`:

```python
from app.services.dedupe import is_processed, mark_processed


class FakeDoc:
    def __init__(self, store, key):
        self._store, self._key = store, key

    @property
    def exists(self):
        return self._key in self._store

    def set(self, data):
        self._store[self._key] = data


class FakeCollection:
    def __init__(self, store):
        self._store = store

    def document(self, key):
        return FakeDocRef(self._store, key)


class FakeDocRef:
    def __init__(self, store, key):
        self._store, self._key = store, key

    def get(self):
        return FakeDoc(self._store, self._key)

    def set(self, data):
        self._store[self._key] = data


class FakeFirestore:
    def __init__(self):
        self._collections = {}

    def collection(self, name):
        return FakeCollection(self._collections.setdefault(name, {}))


def test_dedupe_marks_and_detects_processed_messages():
    db = FakeFirestore()

    assert is_processed(db, "msg-1") is False

    mark_processed(db, "msg-1")

    assert is_processed(db, "msg-1") is True
    assert is_processed(db, "msg-2") is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/test_dedupe.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.services.dedupe'`

- [ ] **Step 3: Write `backend/app/services/dedupe.py`**

```python
PROCESSED_COLLECTION = "processed_message_ids"


def is_processed(db, message_id: str) -> bool:
    doc = db.collection(PROCESSED_COLLECTION).document(message_id).get()
    return doc.exists


def mark_processed(db, message_id: str) -> None:
    db.collection(PROCESSED_COLLECTION).document(message_id).set(
        {"message_id": message_id}
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/test_dedupe.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/dedupe.py backend/tests/test_dedupe.py
git commit -m "feat: add gmail message dedupe guard

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 4: Gmail service wrapper

**Files:**
- Create: `backend/app/services/gmail_service.py`
- Test: `backend/tests/test_gmail_service.py`

**Interfaces:**
- Consumes: `app.core.google_auth.get_credentials`
- Produces: `app.services.gmail_service.build_gmail_service(creds) -> Resource`,
  `app.services.gmail_service.list_new_message_ids(service, start_history_id: str) -> list[str]`,
  `app.services.gmail_service.get_message_content(service, message_id: str) -> dict`
  (dict keys: `message_id`, `subject`, `sender`, `body_text`)

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_gmail_service.py`:

```python
import base64
from unittest.mock import MagicMock

from app.services.gmail_service import get_message_content, list_new_message_ids


def test_list_new_message_ids_extracts_ids_from_history():
    service = MagicMock()
    service.users().history().list().execute.return_value = {
        "history": [
            {"messagesAdded": [{"message": {"id": "m1"}}]},
            {"messagesAdded": [{"message": {"id": "m2"}}]},
        ]
    }

    ids = list_new_message_ids(service, start_history_id="100")

    assert ids == ["m1", "m2"]


def test_get_message_content_parses_headers_and_decodes_body():
    body_text = "Come to the club fair!"
    encoded_body = base64.urlsafe_b64encode(body_text.encode()).decode()

    service = MagicMock()
    service.users().messages().get().execute.return_value = {
        "id": "m1",
        "payload": {
            "headers": [
                {"name": "Subject", "value": "Club Fair"},
                {"name": "From", "value": "clubs@school.edu"},
            ],
            "body": {"data": encoded_body},
        },
    }

    message = get_message_content(service, "m1")

    assert message == {
        "message_id": "m1",
        "subject": "Club Fair",
        "sender": "clubs@school.edu",
        "body_text": body_text,
    }
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/test_gmail_service.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.services.gmail_service'`

- [ ] **Step 3: Write `backend/app/services/gmail_service.py`**

```python
import base64

from googleapiclient.discovery import Resource, build


def build_gmail_service(creds) -> Resource:
    return build("gmail", "v1", credentials=creds)


def list_new_message_ids(service, start_history_id: str) -> list[str]:
    response = (
        service.users()
        .history()
        .list(userId="me", startHistoryId=start_history_id)
        .execute()
    )
    ids: list[str] = []
    for record in response.get("history", []):
        for added in record.get("messagesAdded", []):
            ids.append(added["message"]["id"])
    return ids


def _header(headers: list[dict], name: str) -> str:
    for header in headers:
        if header["name"].lower() == name.lower():
            return header["value"]
    return ""


def get_message_content(service, message_id: str) -> dict:
    message = (
        service.users().messages().get(userId="me", id=message_id).execute()
    )
    payload = message["payload"]
    headers = payload.get("headers", [])
    body_data = payload.get("body", {}).get("data", "")
    body_text = (
        base64.urlsafe_b64decode(body_data.encode()).decode() if body_data else ""
    )
    return {
        "message_id": message["id"],
        "subject": _header(headers, "Subject"),
        "sender": _header(headers, "From"),
        "body_text": body_text,
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/test_gmail_service.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/gmail_service.py backend/tests/test_gmail_service.py
git commit -m "feat: add Gmail history/message parsing service

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

**Note:** this task only handles the plain-text body case. If a demo email
turns out to be multipart/HTML-only, extend `get_message_content` to walk
`payload["parts"]` for a `text/plain` part — not needed until you hit a real
email that requires it (YAGNI).

---

### Task 5: Triage/summarizer agent (ADK)

`TriageResult` is defined locally in this task's file — it's transient agent
output, never persisted directly (Task 6 maps its fields onto the existing
`ProcessedEvent` model instead). Do not create `app/models.py`.

**Files:**
- Create: `backend/app/agents/runner.py`
- Create: `backend/app/agents/triage_agent.py`
- Test: `backend/tests/test_triage_agent.py`

**Interfaces:**
- Consumes: `app.core.config.settings.gemini_model`
- Produces: `app.agents.runner.run_structured_agent(agent, output_schema, user_id, message_text) -> BaseModel`,
  `app.agents.triage_agent.TriageResult` (fields: `is_event: bool`,
  `confidence: float`, `title: str`, `description: str`, `when: str`,
  `where: str`, `signup_type: Literal["none","form","reply"]`,
  `form_url: str | None`),
  `app.agents.triage_agent.build_triage_agent() -> Agent`,
  `app.agents.triage_agent.run_triage(subject: str, sender: str, body_text: str) -> TriageResult`

- [ ] **Step 1: Add the ADK dependency**

```bash
cd backend && uv add google-adk
```

- [ ] **Step 2: Write the failing test**

Create `backend/tests/test_triage_agent.py`:

```python
from unittest.mock import patch

from app.agents.triage_agent import TriageResult, run_triage


def test_run_triage_returns_parsed_result():
    fake_result = TriageResult(
        is_event=True,
        confidence=0.95,
        title="Club Fair",
        description="Annual club fair on the quad.",
        when="2026-09-02 12:00",
        where="Main Quad",
        signup_type="form",
        form_url="https://forms.gle/abc123",
    )

    with patch(
        "app.agents.triage_agent.run_structured_agent", return_value=fake_result
    ) as run_mock:
        result = run_triage(
            subject="Club Fair!",
            sender="clubs@school.edu",
            body_text="Come to the quad on Sept 2nd at noon. Sign up: https://forms.gle/abc123",
        )

    assert result == fake_result
    run_mock.assert_called_once()
    _, kwargs = run_mock.call_args
    assert kwargs["output_schema"] is TriageResult
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/test_triage_agent.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.agents'`

- [ ] **Step 4: Write `backend/app/agents/runner.py`**

This isolates the actual Gemini/ADK call behind one function, so every agent
task after this one can be unit-tested by mocking `run_structured_agent`
instead of hitting the network.

```python
import uuid

from google.adk.agents import LlmAgent
from google.adk.runners import InMemoryRunner
from google.genai import types
from pydantic import BaseModel


def run_structured_agent(
    agent: LlmAgent, output_schema: type[BaseModel], user_id: str, message_text: str
) -> BaseModel:
    runner = InMemoryRunner(agent=agent, app_name=agent.name)
    session_id = str(uuid.uuid4())
    runner.session_service.create_session_sync(
        app_name=agent.name, user_id=user_id, session_id=session_id
    )

    message = types.Content(role="user", parts=[types.Part(text=message_text)])
    final_text = ""
    for event in runner.run(user_id=user_id, session_id=session_id, new_message=message):
        if event.is_final_response() and event.content and event.content.parts:
            final_text = event.content.parts[0].text or final_text

    return output_schema.model_validate_json(final_text)
```

- [ ] **Step 5: Write `backend/app/agents/triage_agent.py`**

```python
from typing import Literal

from google.adk.agents import LlmAgent
from pydantic import BaseModel

from app.agents.runner import run_structured_agent
from app.core.config import settings


class TriageResult(BaseModel):
    is_event: bool
    confidence: float
    title: str = ""
    description: str = ""
    when: str = ""
    where: str = ""
    signup_type: Literal["none", "form", "reply"] = "none"
    form_url: str | None = None


TRIAGE_INSTRUCTION = """You triage school emails. Given a subject, sender, and
body, decide whether this email is announcing a real-life event (an info
session, a club meeting, a fair, a hackathon, etc. — not a newsletter,
grade notification, or administrative notice).

If it is an event, extract: title, a one-sentence description, when it is,
where it is, and how to sign up:
- signup_type "form" + form_url if the body contains a Google Form link
  (a URL containing "forms.gle" or "docs.google.com/forms")
- signup_type "reply" if it asks the reader to reply to RSVP
- signup_type "none" otherwise

If it is not an event, set is_event to false and leave the other fields blank.
Always set confidence between 0 and 1."""


def build_triage_agent() -> LlmAgent:
    return LlmAgent(
        model=settings.gemini_model,
        name="triage_agent",
        instruction=TRIAGE_INSTRUCTION,
        output_schema=TriageResult,
    )


def run_triage(subject: str, sender: str, body_text: str) -> TriageResult:
    agent = build_triage_agent()
    message_text = f"Subject: {subject}\nFrom: {sender}\n\n{body_text}"
    result = run_structured_agent(
        agent=agent,
        output_schema=TriageResult,
        user_id="demo-user",
        message_text=message_text,
    )
    assert isinstance(result, TriageResult)
    return result
```

- [ ] **Step 6: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/test_triage_agent.py -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add backend/pyproject.toml backend/uv.lock backend/app/agents/runner.py backend/app/agents/triage_agent.py backend/tests/test_triage_agent.py
git commit -m "feat: add ADK triage/summarizer agent

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

**Manual verification (not covered by the mocked test):** once you have real
Gemini access configured, run
`uv run python -c "from app.agents.triage_agent import run_triage; print(run_triage('Club Fair!', 'clubs@school.edu', 'Come to the quad Sept 2 at noon.'))"`
and confirm it returns a sensible `TriageResult` — this is the first point
where `run_structured_agent`'s exact parsing of ADK's event stream gets
proven against the real library, since the mocked test only proves your
calling code, not ADK's actual response shape.

---

### Task 6: Gmail webhook (ingestion end-to-end)

Uses the existing `FirestoreRepository[Event]`/`FirestoreRepository[ProcessedEvent]`
(via FastAPI `Depends`, same pattern as `app/api/v1/events.py`) instead of
raw Firestore writes. The dedupe guard (Task 3) is the one piece that still
takes a raw `firestore.Client`, since `processed_message_ids` isn't a domain
model.

**Files:**
- Create: `backend/app/services/events_store.py`
- Create: `backend/app/api/v1/webhooks.py`
- Modify: `backend/app/api/v1/router.py`
- Test: `backend/tests/test_webhook_gmail.py`

**Interfaces:**
- Consumes: `dedupe.is_processed/mark_processed`,
  `gmail_service.list_new_message_ids/get_message_content`,
  `triage_agent.run_triage`, `app.core.firestore.get_firestore_client`,
  `app.db.collections.get_event_repository/get_processed_event_repository`
- Produces:
  `app.services.events_store.ingest_triaged_email(event_repo, processed_event_repo, *, sender, sent_on, subject, body_text, triage) -> ProcessedEvent`,
  `POST /api/v1/webhooks/gmail`

- [ ] **Step 1: Write `backend/app/services/events_store.py`**

```python
from datetime import datetime

from app.agents.triage_agent import TriageResult
from app.db.repository import FirestoreRepository
from app.models.event import Event
from app.models.processed_event import EventStatus, ProcessedEvent


def ingest_triaged_email(
    event_repo: FirestoreRepository[Event],
    processed_event_repo: FirestoreRepository[ProcessedEvent],
    *,
    sender: str,
    sent_on: datetime,
    subject: str,
    body_text: str,
    triage: TriageResult,
) -> ProcessedEvent:
    event = event_repo.create(
        Event(sender=sender, sent_on=sent_on, email_subject=subject, email_content=body_text)
    )

    status = EventStatus.NEW if triage.is_event else EventStatus.DECLINED
    if triage.is_event and triage.confidence < 0.5:
        status = EventStatus.NEEDS_REVIEW

    return processed_event_repo.create(
        ProcessedEvent(
            event_id=event.id,
            summarized_text=triage.description or "(no summary)",
            is_event=triage.is_event,
            confidence=triage.confidence,
            title=triage.title,
            when=triage.when,
            where=triage.where,
            signup_type=triage.signup_type,
            form_url=triage.form_url,
            status=status,
        )
    )
```

- [ ] **Step 2: Write the failing test**

Create `backend/tests/test_webhook_gmail.py`. The `FakeEventRepository`/
`FakeProcessedEventRepository` classes below intentionally mirror the ones
already in `test_events.py`/`test_processed_events.py` rather than
centralizing them — that duplication is the existing convention in this
test suite, follow it rather than refactoring it as part of this task.

```python
import base64
import json
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from app.agents.triage_agent import TriageResult
from app.core.config import settings
from app.core.firestore import get_firestore_client
from app.db.collections import get_event_repository, get_processed_event_repository
from app.main import app
from app.models.event import Event
from app.models.processed_event import ProcessedEvent
from tests.fakes import FakeFirestore

client = TestClient(app)


class FakeEventRepository:
    def __init__(self) -> None:
        self._items: dict[str, Event] = {}

    def get(self, doc_id):
        return self._items.get(doc_id)

    def list(self, limit: int = 50):
        return list(self._items.values())[:limit]

    def create(self, item: Event) -> Event:
        item.id = str(len(self._items) + 1)
        self._items[item.id] = item
        return item


class FakeProcessedEventRepository:
    def __init__(self) -> None:
        self._items: dict[str, ProcessedEvent] = {}

    def get(self, doc_id):
        return self._items.get(doc_id)

    def list(self, limit: int = 50):
        return list(self._items.values())[:limit]

    def create(self, item: ProcessedEvent) -> ProcessedEvent:
        item.id = str(len(self._items) + 1)
        self._items[item.id] = item
        return item


def _push_body(history_id: str) -> dict:
    data = json.dumps({"emailAddress": "me@school.edu", "historyId": history_id})
    encoded = base64.urlsafe_b64encode(data.encode()).decode()
    return {"message": {"data": encoded, "messageId": "pubsub-1"}, "subscription": "sub"}


@patch("app.api.v1.webhooks.run_triage")
@patch("app.api.v1.webhooks.get_message_content")
@patch("app.api.v1.webhooks.list_new_message_ids", return_value=["m1"])
@patch("app.api.v1.webhooks.build_gmail_service", return_value=MagicMock())
@patch("app.api.v1.webhooks.get_credentials", return_value=MagicMock())
def test_duplicate_push_only_creates_one_event(
    _creds, _service, _list_ids, get_content, run_triage_mock, monkeypatch
):
    monkeypatch.setattr(settings, "allowed_email_domains", "school.edu")

    fake_db = FakeFirestore()
    fake_event_repo = FakeEventRepository()
    fake_processed_repo = FakeProcessedEventRepository()
    app.dependency_overrides[get_firestore_client] = lambda: fake_db
    app.dependency_overrides[get_event_repository] = lambda: fake_event_repo
    app.dependency_overrides[get_processed_event_repository] = lambda: fake_processed_repo

    get_content.return_value = {
        "message_id": "m1",
        "subject": "Club Fair!",
        "sender": "clubs@school.edu",
        "body_text": "Come to the quad Sept 2.",
    }
    run_triage_mock.return_value = TriageResult(is_event=True, confidence=0.9, title="Club Fair")

    try:
        body = _push_body("100")
        r1 = client.post("/api/v1/webhooks/gmail", json=body)
        r2 = client.post("/api/v1/webhooks/gmail", json=body)

        assert r1.status_code == 204
        assert r2.status_code == 204
        assert len(fake_event_repo.list()) == 1
        assert len(fake_processed_repo.list()) == 1
    finally:
        app.dependency_overrides.pop(get_firestore_client, None)
        app.dependency_overrides.pop(get_event_repository, None)
        app.dependency_overrides.pop(get_processed_event_repository, None)
```

- [ ] **Step 3: Create the shared test fake**

Create `backend/tests/fakes.py` (promoting the fake used in Task 3 so other
tests can reuse it instead of redefining it):

```python
class FakeDoc:
    def __init__(self, store, key):
        self._store, self._key = store, key

    @property
    def exists(self):
        return self._key in self._store

    def to_dict(self):
        return self._store.get(self._key)


class FakeDocRef:
    def __init__(self, store, key):
        self._store, self._key = store, key

    def get(self):
        return FakeDoc(self._store, self._key)

    def set(self, data):
        self._store[self._key] = data


class FakeCollection:
    def __init__(self, store):
        self._store = store

    def document(self, key):
        return FakeDocRef(self._store, key)

    def stream(self):
        return [FakeDoc(self._store, key) for key in self._store]


class FakeFirestore:
    def __init__(self):
        self._collections: dict[str, dict] = {}

    def collection(self, name):
        return FakeCollection(self._collections.setdefault(name, {}))
```

- [ ] **Step 4: Update `backend/tests/test_dedupe.py` to use the shared fake**

Replace the inline `FakeDoc`/`FakeCollection`/`FakeDocRef`/`FakeFirestore`
classes at the top of `backend/tests/test_dedupe.py` with:

```python
from tests.fakes import FakeFirestore
```

- [ ] **Step 5: Run the webhook test to verify it fails**

Run: `cd backend && uv run pytest tests/test_webhook_gmail.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.api.v1.webhooks'`

- [ ] **Step 6: Write `backend/app/api/v1/webhooks.py`**

```python
import base64
import json
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Response
from google.cloud import firestore

from app.agents.triage_agent import run_triage
from app.core.config import settings
from app.core.firestore import get_firestore_client
from app.core.google_auth import get_credentials
from app.db.collections import get_event_repository, get_processed_event_repository
from app.db.repository import FirestoreRepository
from app.models.event import Event
from app.models.processed_event import ProcessedEvent
from app.services.dedupe import is_processed, mark_processed
from app.services.events_store import ingest_triaged_email
from app.services.gmail_service import (
    build_gmail_service,
    get_message_content,
    list_new_message_ids,
)

router = APIRouter()

GMAIL_SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]


def _sender_domain_allowed(sender: str) -> bool:
    sender_lower = sender.lower()
    return any(
        sender_lower.endswith(f"@{domain}") for domain in settings.allowed_email_domains_list
    )


@router.post("/webhooks/gmail", status_code=204)
def handle_gmail_push(
    payload: dict,
    db: firestore.Client = Depends(get_firestore_client),
    event_repo: FirestoreRepository[Event] = Depends(get_event_repository),
    processed_event_repo: FirestoreRepository[ProcessedEvent] = Depends(
        get_processed_event_repository
    ),
) -> Response:
    data = json.loads(base64.urlsafe_b64decode(payload["message"]["data"]))
    history_id = data["historyId"]

    creds = get_credentials(GMAIL_SCOPES)
    service = build_gmail_service(creds)

    message_ids = list_new_message_ids(service, start_history_id=history_id)
    for message_id in message_ids:
        if is_processed(db, message_id):
            continue

        message = get_message_content(service, message_id)
        if not _sender_domain_allowed(message["sender"]):
            mark_processed(db, message_id)
            continue

        triage = run_triage(
            subject=message["subject"],
            sender=message["sender"],
            body_text=message["body_text"],
        )
        ingest_triaged_email(
            event_repo,
            processed_event_repo,
            sender=message["sender"],
            # Arrival time stands in for the email's real Date header — good
            # enough for the MVP; add real header parsing if precise send
            # times matter later (YAGNI).
            sent_on=datetime.now(UTC),
            subject=message["subject"],
            body_text=message["body_text"],
            triage=triage,
        )
        mark_processed(db, message_id)

    return Response(status_code=204)
```

- [ ] **Step 7: Mount the router**

In `backend/app/api/v1/router.py`, add:

```python
from app.api.v1.webhooks import router as webhooks_router

router.include_router(webhooks_router)
```

- [ ] **Step 8: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/ -v`
Expected: All PASS (including the updated `test_dedupe.py`)

- [ ] **Step 9: Commit**

```bash
git add backend/app/services/events_store.py backend/app/api/v1/webhooks.py backend/app/api/v1/router.py backend/tests/test_webhook_gmail.py backend/tests/test_dedupe.py backend/tests/fakes.py
git commit -m "feat: add Gmail push webhook with idempotent ingestion

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 7: Catalog API — already built, verify only

The teammate's `GET`/`POST /api/v1/processed-events` (and `/events`) already
exist and are already tested (`backend/tests/test_processed_events.py`).
Task 1 extended `ProcessedEvent` with `title`/`when`/`where`/`status`/etc.,
and those fields flow through the existing `list`/`get` handlers automatically
(they just serialize the model) — no new endpoint code is needed. This task
is a verification pass, not a build.

**Files:** none created or modified.

- [ ] **Step 1: Confirm the extended fields serialize correctly**

Run: `cd backend && uv run pytest tests/test_processed_events.py -v`
Expected: PASS (unchanged — confirms Task 1's new `ProcessedEvent` fields
didn't break the existing endpoint tests).

- [ ] **Step 2: Manually confirm the response shape includes the new fields**

```bash
cd backend && uv run python -c "
from app.models.processed_event import ProcessedEvent
p = ProcessedEvent(event_id='e1', summarized_text='s', title='Club Fair', status='new')
print(p.model_dump())
"
```

Expected: the printed dict includes `title`, `when`, `where`, `signup_type`,
`form_url`, `status`, `calendar_event_id` alongside the original
`event_id`/`summarized_text` — confirming `GET /api/v1/processed-events`
already returns everything the catalog page (Task 14) needs.

No commit — nothing changed in this task.

---

### Task 8: Calendar service

**Files:**
- Create: `backend/app/services/calendar_service.py`
- Test: `backend/tests/test_calendar_service.py`

**Interfaces:**
- Produces: `app.services.calendar_service.create_event(creds, *, title, description, when) -> str` (returns the Calendar event ID)

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_calendar_service.py`:

```python
from unittest.mock import MagicMock

from app.services.calendar_service import create_event


def test_create_event_returns_calendar_event_id():
    service = MagicMock()
    service.events().insert().execute.return_value = {"id": "cal-event-1"}

    event_id = create_event(
        service, title="Club Fair", description="Annual fair", when="2026-09-02 12:00"
    )

    assert event_id == "cal-event-1"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/test_calendar_service.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.services.calendar_service'`

- [ ] **Step 3: Write `backend/app/services/calendar_service.py`**

```python
from googleapiclient.discovery import Resource, build

from app.core.config import settings


def build_calendar_service(creds) -> Resource:
    return build("calendar", "v3", credentials=creds)


def create_event(service, *, title: str, description: str, when: str) -> str:
    """`when` is the free-text string the triage agent extracted. For the
    MVP this is stored as an all-day-style text note in the description
    rather than parsed into a strict start/end datetime — parsing arbitrary
    natural-language dates reliably is a bigger problem than this timeline
    affords; add real date parsing only if a demo event needs an exact
    calendar slot."""
    body = {
        "summary": title,
        "description": f"{description}\n\nWhen: {when}",
    }
    result = service.events().insert(calendarId=settings.calendar_id, body=body).execute()
    return result["id"]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/test_calendar_service.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/calendar_service.py backend/tests/test_calendar_service.py
git commit -m "feat: add Google Calendar event creation service

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 9: Forms service

**Files:**
- Create: `backend/app/services/forms_service.py`
- Test: `backend/tests/test_forms_service.py`

**Interfaces:**
- Produces: `app.services.forms_service.extract_form_id(form_url: str) -> str | None`,
  `app.services.forms_service.get_form_fields(service, form_id: str) -> list[dict]`
  (each dict: `{"id": str, "label": str, "required": bool}`),
  `app.services.forms_service.build_prefill_link(form_url: str, form_id: str, answers: dict[str, str]) -> str`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_forms_service.py`:

```python
from unittest.mock import MagicMock

from app.services.forms_service import (
    build_prefill_link,
    extract_form_id,
    get_form_fields,
)


def test_extract_form_id_from_forms_gle_and_docs_url():
    assert extract_form_id("https://docs.google.com/forms/d/1AbCdEf/viewform") == "1AbCdEf"
    assert extract_form_id("https://forms.gle/xyz789") is None


def test_get_form_fields_parses_text_questions():
    service = MagicMock()
    service.forms().get().execute.return_value = {
        "items": [
            {
                "itemId": "q1",
                "title": "Full name",
                "questionItem": {"question": {"questionId": "q1", "required": True}},
            },
            {
                "itemId": "q2",
                "title": "Dietary restrictions",
                "questionItem": {"question": {"questionId": "q2", "required": False}},
            },
        ]
    }

    fields = get_form_fields(service, "1AbCdEf")

    assert fields == [
        {"id": "q1", "label": "Full name", "required": True},
        {"id": "q2", "label": "Dietary restrictions", "required": False},
    ]


def test_build_prefill_link_adds_entry_params():
    link = build_prefill_link(
        "https://docs.google.com/forms/d/1AbCdEf/viewform",
        "1AbCdEf",
        {"q1": "Ada Lovelace"},
    )

    assert link.startswith("https://docs.google.com/forms/d/1AbCdEf/viewform?usp=pp_url")
    assert "entry.q1=Ada+Lovelace" in link
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/test_forms_service.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.services.forms_service'`

- [ ] **Step 3: Write `backend/app/services/forms_service.py`**

```python
import re
from urllib.parse import urlencode

from googleapiclient.discovery import Resource, build

FORM_ID_PATTERN = re.compile(r"/forms/d/([a-zA-Z0-9_-]+)")


def build_forms_service(creds) -> Resource:
    return build("forms", "v1", credentials=creds)


def extract_form_id(form_url: str) -> str | None:
    """Only handles the `docs.google.com/forms/d/<id>/...` shape. A
    `forms.gle/<code>` short link resolves to that shape after a redirect,
    which the caller must follow before calling this — not implemented here
    since the MVP only needs the direct-link case (spec §Signup pattern)."""
    match = FORM_ID_PATTERN.search(form_url)
    return match.group(1) if match else None


def get_form_fields(service, form_id: str) -> list[dict]:
    form = service.forms().get(formId=form_id).execute()
    fields = []
    for item in form.get("items", []):
        question = item.get("questionItem", {}).get("question")
        if not question:
            continue
        fields.append(
            {
                "id": question["questionId"],
                "label": item["title"],
                "required": question.get("required", False),
            }
        )
    return fields


def build_prefill_link(form_url: str, form_id: str, answers: dict[str, str]) -> str:
    base = form_url.split("?")[0]
    params = {"usp": "pp_url"}
    for field_id, value in answers.items():
        params[f"entry.{field_id}"] = value
    return f"{base}?{urlencode(params)}"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/test_forms_service.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/forms_service.py backend/tests/test_forms_service.py
git commit -m "feat: add Google Forms field reading and prefill link builder

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 10: User profile store

Kept as plain functions taking `db` explicitly (not a `FirestoreRepository[T]`)
— that abstraction assumes a collection of many documents with generated
IDs, and this is one fixed-ID singleton doc. Depends on `tests/fakes.py`
(from Task 6) for its test, not on any Task 3 file.

**Files:**
- Create: `backend/app/services/profile_service.py`
- Test: `backend/tests/test_profile_service.py`

**Interfaces:**
- Consumes: `app.core.firestore.get_firestore_client` (the real caller in
  Task 13 passes its result as `db`; this task's test passes a `FakeFirestore`)
- Produces: `app.services.profile_service.get_profile(db) -> dict[str, str]`,
  `app.services.profile_service.save_profile_fields(db, answers: dict[str, str]) -> None`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_profile_service.py`:

```python
from app.services.profile_service import get_profile, save_profile_fields
from tests.fakes import FakeFirestore


def test_profile_starts_empty_and_accumulates_answers():
    db = FakeFirestore()

    assert get_profile(db) == {}

    save_profile_fields(db, {"full_name": "Ada Lovelace"})
    assert get_profile(db) == {"full_name": "Ada Lovelace"}

    save_profile_fields(db, {"dietary": "vegetarian"})
    assert get_profile(db) == {"full_name": "Ada Lovelace", "dietary": "vegetarian"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/test_profile_service.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.services.profile_service'`

- [ ] **Step 3: Write `backend/app/services/profile_service.py`**

```python
PROFILE_COLLECTION = "user_profile"
PROFILE_DOC_ID = "demo-user"


def get_profile(db) -> dict[str, str]:
    doc = db.collection(PROFILE_COLLECTION).document(PROFILE_DOC_ID).get()
    return doc.to_dict() or {} if doc.exists else {}


def save_profile_fields(db, answers: dict[str, str]) -> None:
    current = get_profile(db)
    current.update(answers)
    db.collection(PROFILE_COLLECTION).document(PROFILE_DOC_ID).set(current)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/test_profile_service.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/profile_service.py backend/tests/test_profile_service.py
git commit -m "feat: add persistent user profile store

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 11: RSVP field-resolution agent (ADK)

> **Heads up for whoever executes this task:** per the implementation note at
> the top of this plan, this agent is a single structured-output call (given
> form fields + known profile, return what's resolved vs. what to ask), not a
> stateful ADK session. Mention this to the user once when you reach this
> task, since it's a simplification of how the spec phrased "agent with
> memory" — the memory is Firestore, not ADK session state.

**Files:**
- Create: `backend/app/agents/rsvp_agent.py`
- Test: `backend/tests/test_rsvp_agent.py`

**Interfaces:**
- Consumes: `app.agents.runner.run_structured_agent`
- Produces: `app.agents.rsvp_agent.FieldResolution` (fields: `field_id: str`,
  `label: str`, `resolved: bool`, `value: str | None`, `question: str | None`
  — defined locally here, not in a shared `app/models.py`),
  `app.agents.rsvp_agent.resolve_form_fields(form_fields: list[dict], known_profile: dict[str, str]) -> list[FieldResolution]`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_rsvp_agent.py`:

```python
from unittest.mock import patch

from app.agents.rsvp_agent import FieldResolution, resolve_form_fields


def test_resolve_form_fields_only_asks_for_missing_ones():
    form_fields = [
        {"id": "q1", "label": "Full name", "required": True},
        {"id": "q2", "label": "Dietary restrictions", "required": False},
    ]
    known_profile = {"full_name": "Ada Lovelace"}

    fake_resolution = [
        FieldResolution(field_id="q1", label="Full name", resolved=True, value="Ada Lovelace"),
        FieldResolution(
            field_id="q2",
            label="Dietary restrictions",
            resolved=False,
            question="Any dietary restrictions?",
        ),
    ]

    with patch(
        "app.agents.rsvp_agent.run_structured_agent", return_value=fake_resolution
    ) as run_mock:
        resolutions = resolve_form_fields(form_fields, known_profile)

    assert resolutions == fake_resolution
    assert run_mock.call_count == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/test_rsvp_agent.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.agents.rsvp_agent'`

- [ ] **Step 3: Write `backend/app/agents/rsvp_agent.py`**

```python
import json

from google.adk.agents import LlmAgent
from pydantic import BaseModel, RootModel

from app.agents.runner import run_structured_agent
from app.core.config import settings


class FieldResolution(BaseModel):
    field_id: str
    label: str
    resolved: bool
    value: str | None = None
    question: str | None = None


RSVP_INSTRUCTION = """You match a Google Form's questions against a known
user profile. For each form field, decide whether the profile already
answers it (match by meaning, not just exact wording — e.g. a profile key
"full_name" answers a field labeled "Your name"). If resolved, set `value`
to the profile's value and leave `question` empty. If not resolved, set
`resolved` to false and write a short, friendly clarifying question for
that field, and leave `value` empty."""


class FieldResolutionList(RootModel[list[FieldResolution]]):
    pass


def build_rsvp_agent() -> LlmAgent:
    return LlmAgent(
        model=settings.gemini_model,
        name="rsvp_field_resolver",
        instruction=RSVP_INSTRUCTION,
        output_schema=FieldResolutionList,
    )


def resolve_form_fields(
    form_fields: list[dict], known_profile: dict[str, str]
) -> list[FieldResolution]:
    agent = build_rsvp_agent()
    message_text = json.dumps({"form_fields": form_fields, "known_profile": known_profile})
    result = run_structured_agent(
        agent=agent,
        output_schema=FieldResolutionList,
        user_id="demo-user",
        message_text=message_text,
    )
    resolutions = result.root if isinstance(result, FieldResolutionList) else result
    assert isinstance(resolutions, list)
    return resolutions
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/test_rsvp_agent.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/agents/rsvp_agent.py backend/tests/test_rsvp_agent.py
git commit -m "feat: add ADK form-field resolution agent for RSVP

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 12: RSVP orchestration service

Operates on `ProcessedEvent` through `FirestoreRepository[ProcessedEvent]`
(get/update) instead of raw `db.collection()` calls. Still takes the raw
`db` client separately for `profile_service` (Task 10, not a repository
citizen — see its note).

**Files:**
- Create: `backend/app/services/rsvp_service.py`
- Test: `backend/tests/test_rsvp_service.py`

**Interfaces:**
- Consumes: `profile_service.get_profile/save_profile_fields`, `forms_service.*`,
  `calendar_service.create_event`, `rsvp_agent.resolve_form_fields`,
  `app.db.repository.FirestoreRepository`, `app.models.processed_event.ProcessedEvent`
- Produces:
  `app.services.rsvp_service.attend_event(repo, db, creds, processed_event_id: str) -> dict`,
  `app.services.rsvp_service.answer_rsvp(repo, db, creds, processed_event_id: str, answers: dict[str, str]) -> dict`
  (`repo` is a `FirestoreRepository[ProcessedEvent]`; both return
  `{"done": bool, "questions": list[dict], "calendar_event_id": str | None, "form_link": str | None}`)

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_rsvp_service.py`. `FakeProcessedEventRepository`
here adds an `update` method the teammate's own fakes don't need yet —
that's expected, this task is the first consumer of `update`.

```python
from typing import Optional
from unittest.mock import MagicMock, patch

from app.agents.rsvp_agent import FieldResolution
from app.models.processed_event import ProcessedEvent
from app.services.rsvp_service import answer_rsvp, attend_event


class FakeProcessedEventRepository:
    def __init__(self) -> None:
        self._items: dict[str, ProcessedEvent] = {}

    def get(self, doc_id: str) -> Optional[ProcessedEvent]:
        return self._items.get(doc_id)

    def create(self, item: ProcessedEvent) -> ProcessedEvent:
        item.id = str(len(self._items) + 1)
        self._items[item.id] = item
        return item

    def update(self, doc_id: str, item: ProcessedEvent) -> ProcessedEvent:
        item.id = doc_id
        self._items[doc_id] = item
        return item


def _seed(repo, **overrides) -> ProcessedEvent:
    processed = ProcessedEvent(
        event_id="raw-e1",
        summarized_text="Fun fair",
        title="Club Fair",
        when="2026-09-02",
        signup_type="form",
        form_url="https://docs.google.com/forms/d/1AbCdEf/viewform",
        status="new",
        **overrides,
    )
    return repo.create(processed)


@patch("app.services.rsvp_service.create_event", return_value="cal-1")
@patch("app.services.rsvp_service.build_calendar_service", return_value=MagicMock())
@patch("app.services.rsvp_service.build_prefill_link", return_value="https://forms/prefilled")
@patch("app.services.rsvp_service.get_form_fields")
@patch("app.services.rsvp_service.build_forms_service", return_value=MagicMock())
@patch("app.services.rsvp_service.resolve_form_fields")
def test_attend_asks_only_for_missing_fields(
    resolve_mock, _forms_svc, get_fields, _prefill, _cal_svc, _create_event
):
    repo = FakeProcessedEventRepository()
    processed = _seed(repo)
    get_fields.return_value = [{"id": "q1", "label": "Full name", "required": True}]
    resolve_mock.return_value = [
        FieldResolution(field_id="q1", label="Full name", resolved=False, question="What's your name?")
    ]

    result = attend_event(repo, db=MagicMock(), creds=MagicMock(), processed_event_id=processed.id)

    assert result["done"] is False
    assert result["questions"] == [{"field_id": "q1", "label": "Full name", "question": "What's your name?"}]


@patch("app.services.rsvp_service.create_event", return_value="cal-1")
@patch("app.services.rsvp_service.build_calendar_service", return_value=MagicMock())
@patch("app.services.rsvp_service.build_prefill_link", return_value="https://forms/prefilled")
@patch("app.services.rsvp_service.get_form_fields")
@patch("app.services.rsvp_service.build_forms_service", return_value=MagicMock())
@patch("app.services.rsvp_service.resolve_form_fields")
def test_answer_rsvp_finalizes_once_all_fields_resolved(
    resolve_mock, _forms_svc, get_fields, _prefill, _cal_svc, _create_event
):
    repo = FakeProcessedEventRepository()
    processed = _seed(repo)
    get_fields.return_value = [{"id": "q1", "label": "Full name", "required": True}]
    resolve_mock.return_value = [
        FieldResolution(field_id="q1", label="Full name", resolved=True, value="Ada Lovelace")
    ]

    result = answer_rsvp(
        repo,
        db=MagicMock(),
        creds=MagicMock(),
        processed_event_id=processed.id,
        answers={"q1": "Ada Lovelace"},
    )

    assert result["done"] is True
    assert result["calendar_event_id"] == "cal-1"
    assert result["form_link"] == "https://forms/prefilled"
    updated = repo.get(processed.id)
    assert updated.status == "attending"
    assert updated.calendar_event_id == "cal-1"


def test_attend_skips_form_step_when_event_has_no_signup():
    repo = FakeProcessedEventRepository()
    processed = _seed(repo, signup_type="none", form_url=None)

    with patch("app.services.rsvp_service.build_calendar_service", return_value=MagicMock()), \
         patch("app.services.rsvp_service.create_event", return_value="cal-2"):
        result = attend_event(repo, db=MagicMock(), creds=MagicMock(), processed_event_id=processed.id)

    assert result == {
        "done": True,
        "questions": [],
        "calendar_event_id": "cal-2",
        "form_link": None,
    }
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/test_rsvp_service.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.services.rsvp_service'`

- [ ] **Step 3: Write `backend/app/services/rsvp_service.py`**

```python
from app.agents.rsvp_agent import resolve_form_fields
from app.models.processed_event import ProcessedEvent
from app.services.calendar_service import build_calendar_service, create_event
from app.services.forms_service import (
    build_forms_service,
    build_prefill_link,
    extract_form_id,
    get_form_fields,
)
from app.services.profile_service import get_profile, save_profile_fields


def _finalize(repo, creds, processed: ProcessedEvent, form_link: str | None) -> dict:
    calendar_service = build_calendar_service(creds)
    calendar_event_id = create_event(
        calendar_service,
        title=processed.title,
        description=processed.summarized_text,
        when=processed.when,
    )
    processed.status = "attending"
    processed.calendar_event_id = calendar_event_id
    repo.update(processed.id, processed)
    return {
        "done": True,
        "questions": [],
        "calendar_event_id": calendar_event_id,
        "form_link": form_link,
    }


def _resolve_pending_questions(repo, db, creds, processed: ProcessedEvent) -> dict:
    form_id = extract_form_id(processed.form_url)
    try:
        forms_service = build_forms_service(creds)
        form_fields = get_form_fields(forms_service, form_id)
    except Exception:
        # Spec error-handling rule: a Forms read failure falls back to
        # "no form" rather than blocking the RSVP — Calendar add still happens.
        return _finalize(repo, creds, processed, form_link=None)
    profile = get_profile(db)

    resolutions = resolve_form_fields(form_fields, profile)
    unresolved = [r for r in resolutions if not r.resolved]
    if unresolved:
        return {
            "done": False,
            "questions": [
                {"field_id": r.field_id, "label": r.label, "question": r.question}
                for r in unresolved
            ],
            "calendar_event_id": None,
            "form_link": None,
        }

    answers = {r.field_id: r.value for r in resolutions if r.value}
    form_link = build_prefill_link(processed.form_url, form_id, answers)
    return _finalize(repo, creds, processed, form_link)


def attend_event(repo, db, creds, processed_event_id: str) -> dict:
    processed = repo.get(processed_event_id)
    if processed.signup_type != "form" or not processed.form_url:
        return _finalize(repo, creds, processed, form_link=None)
    return _resolve_pending_questions(repo, db, creds, processed)


def answer_rsvp(repo, db, creds, processed_event_id: str, answers: dict[str, str]) -> dict:
    save_profile_fields(db, answers)
    processed = repo.get(processed_event_id)
    return _resolve_pending_questions(repo, db, creds, processed)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/test_rsvp_service.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/rsvp_service.py backend/tests/test_rsvp_service.py
git commit -m "feat: add RSVP orchestration (attend + answer flow)

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 13: RSVP API endpoints

Routes live under `/processed-events/...` — that's the model the catalog
lists and the one `attend`/`rsvp-answer` act on, not the raw `/events/...`
the teammate built for ingestion.

**Files:**
- Create: `backend/app/api/v1/rsvp.py`
- Modify: `backend/app/api/v1/router.py`
- Test: `backend/tests/test_rsvp_api.py`

**Interfaces:**
- Produces: `POST /api/v1/processed-events/{processed_event_id}/attend`,
  `POST /api/v1/processed-events/{processed_event_id}/rsvp-answer`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_rsvp_api.py`. `get_firestore_client` and
`get_processed_event_repository` are injected via FastAPI `Depends()` in
the route signature — the reference is bound at import time, so a plain
`@patch` on the module attribute won't reach it; use
`app.dependency_overrides` for those two, the same mechanism the
teammate's own `test_events.py`/`test_processed_events.py` already use.
`get_credentials` is a plain function call inside the route body, so
`@patch` works fine for it.

```python
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from app.core.firestore import get_firestore_client
from app.db.collections import get_processed_event_repository
from app.main import app

client = TestClient(app)


@patch("app.api.v1.rsvp.get_credentials")
@patch("app.api.v1.rsvp.attend_event")
def test_attend_endpoint_returns_service_result(attend_mock, _creds):
    attend_mock.return_value = {
        "done": False,
        "questions": [{"field_id": "q1", "label": "Full name", "question": "What's your name?"}],
        "calendar_event_id": None,
        "form_link": None,
    }
    app.dependency_overrides[get_firestore_client] = lambda: MagicMock()
    app.dependency_overrides[get_processed_event_repository] = lambda: MagicMock()

    try:
        response = client.post("/api/v1/processed-events/pe1/attend")
    finally:
        app.dependency_overrides.pop(get_firestore_client, None)
        app.dependency_overrides.pop(get_processed_event_repository, None)

    assert response.status_code == 200
    assert response.json()["done"] is False


@patch("app.api.v1.rsvp.get_credentials")
@patch("app.api.v1.rsvp.answer_rsvp")
def test_rsvp_answer_endpoint_passes_through_answers(answer_mock, _creds):
    answer_mock.return_value = {
        "done": True,
        "questions": [],
        "calendar_event_id": "cal-1",
        "form_link": "https://forms/prefilled",
    }
    app.dependency_overrides[get_firestore_client] = lambda: MagicMock()
    app.dependency_overrides[get_processed_event_repository] = lambda: MagicMock()

    try:
        response = client.post(
            "/api/v1/processed-events/pe1/rsvp-answer", json={"answers": {"q1": "Ada"}}
        )
    finally:
        app.dependency_overrides.pop(get_firestore_client, None)
        app.dependency_overrides.pop(get_processed_event_repository, None)

    assert response.status_code == 200
    assert response.json()["done"] is True
    answer_mock.assert_called_once()
    assert answer_mock.call_args.kwargs["answers"] == {"q1": "Ada"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/test_rsvp_api.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.api.v1.rsvp'`

- [ ] **Step 3: Write `backend/app/api/v1/rsvp.py`**

```python
from fastapi import APIRouter, Depends
from google.cloud import firestore
from pydantic import BaseModel

from app.core.firestore import get_firestore_client
from app.core.google_auth import get_credentials
from app.db.collections import get_processed_event_repository
from app.db.repository import FirestoreRepository
from app.models.processed_event import ProcessedEvent
from app.services.rsvp_service import answer_rsvp, attend_event

router = APIRouter(prefix="/processed-events")

RSVP_SCOPES = [
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/forms.body.readonly",
]


class RsvpAnswerRequest(BaseModel):
    answers: dict[str, str]


@router.post("/{processed_event_id}/attend")
def attend(
    processed_event_id: str,
    db: firestore.Client = Depends(get_firestore_client),
    repo: FirestoreRepository[ProcessedEvent] = Depends(get_processed_event_repository),
) -> dict:
    creds = get_credentials(RSVP_SCOPES)
    return attend_event(repo, db, creds=creds, processed_event_id=processed_event_id)


@router.post("/{processed_event_id}/rsvp-answer")
def rsvp_answer(
    processed_event_id: str,
    body: RsvpAnswerRequest,
    db: firestore.Client = Depends(get_firestore_client),
    repo: FirestoreRepository[ProcessedEvent] = Depends(get_processed_event_repository),
) -> dict:
    creds = get_credentials(RSVP_SCOPES)
    return answer_rsvp(
        repo, db, creds=creds, processed_event_id=processed_event_id, answers=body.answers
    )
```

- [ ] **Step 4: Mount the router**

In `backend/app/api/v1/router.py`, add:

```python
from app.api.v1.rsvp import router as rsvp_router

router.include_router(rsvp_router)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/ -v`
Expected: All PASS

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/v1/rsvp.py backend/app/api/v1/router.py backend/tests/test_rsvp_api.py
git commit -m "feat: add RSVP attend/answer API endpoints

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 14: Frontend API client + catalog page

`EventRecord` here mirrors the backend's `ProcessedEvent` (Task 1), not the
raw `Event` — the catalog lists and acts on processed events. All API calls
hit `/api/v1/processed-events/...`, not `/api/v1/events/...`.

**Files:**
- Create: `frontend/lib/api.ts`
- Modify: `frontend/app/page.tsx`
- Create: `frontend/components/event-card.tsx`

**Interfaces:**
- Produces: `getEvents(): Promise<EventRecord[]>`, `getEvent(id): Promise<EventRecord>`,
  `attendEvent(id): Promise<RsvpResult>`, `answerRsvp(id, answers): Promise<RsvpResult>`
  (types match the backend's `ProcessedEvent`/`rsvp_service` response shapes above)

This task has no backend-style unit test — it's UI wiring against an API
already covered by backend tests. Verify it by running the dev servers and
loading the page (Task 16 covers end-to-end verification against the real
backend).

- [ ] **Step 1: Add a `NEXT_PUBLIC_API_URL` env var**

Add to `frontend/.env`:

```
NEXT_PUBLIC_API_URL=http://localhost:8000/api/v1
```

- [ ] **Step 2: Write `frontend/lib/api.ts`**

```typescript
export type EventStatus = "new" | "needs_review" | "attending" | "declined";

export interface EventRecord {
  id: string;
  event_id: string;
  summarized_text: string;
  is_event: boolean;
  confidence: number;
  title: string;
  when: string;
  where: string;
  signup_type: "none" | "form" | "reply";
  form_url: string | null;
  status: EventStatus;
  calendar_event_id: string | null;
}

export interface RsvpQuestion {
  field_id: string;
  label: string;
  question: string;
}

export interface RsvpResult {
  done: boolean;
  questions: RsvpQuestion[];
  calendar_event_id: string | null;
  form_link: string | null;
}

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api/v1";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_URL}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!response.ok) {
    throw new Error(`Request to ${path} failed: ${response.status}`);
  }
  return response.json() as Promise<T>;
}

export const getEvents = () => request<EventRecord[]>("/processed-events/");
export const getEvent = (id: string) => request<EventRecord>(`/processed-events/${id}`);
export const attendEvent = (id: string) =>
  request<RsvpResult>(`/processed-events/${id}/attend`, { method: "POST" });
export const answerRsvp = (id: string, answers: Record<string, string>) =>
  request<RsvpResult>(`/processed-events/${id}/rsvp-answer`, {
    method: "POST",
    body: JSON.stringify({ answers }),
  });
```

- [ ] **Step 3: Write `frontend/components/event-card.tsx`**

```tsx
import { Button } from "@/components/ui/button";
import type { EventRecord } from "@/lib/api";

interface EventCardProps {
  event: EventRecord;
  onAttend: (event: EventRecord) => void;
}

export function EventCard({ event, onAttend }: EventCardProps) {
  return (
    <div className="rounded-lg border p-4 flex flex-col gap-2">
      <h3 className="font-semibold">{event.title || event.summarized_text}</h3>
      <p className="text-sm text-muted-foreground">{event.summarized_text}</p>
      <p className="text-sm">
        {event.when} {event.where && `· ${event.where}`}
      </p>
      {event.status === "new" && (
        <Button onClick={() => onAttend(event)}>Attend</Button>
      )}
      {event.status === "attending" && (
        <span className="text-sm text-green-600">Attending — added to calendar</span>
      )}
    </div>
  );
}
```

- [ ] **Step 4: Rewrite `frontend/app/page.tsx`**

```tsx
"use client";

import { useEffect, useState } from "react";

import { AttendFlow } from "@/components/attend-flow";
import { EventCard } from "@/components/event-card";
import { type EventRecord, getEvents } from "@/lib/api";

export default function Home() {
  const [events, setEvents] = useState<EventRecord[]>([]);
  const [activeEvent, setActiveEvent] = useState<EventRecord | null>(null);

  useEffect(() => {
    getEvents().then(setEvents).catch(console.error);
  }, []);

  return (
    <main className="max-w-2xl mx-auto p-6 flex flex-col gap-4">
      <h1 className="text-2xl font-bold">Your events</h1>
      {events
        .filter((event) => event.status !== "declined")
        .map((event) => (
          <EventCard key={event.id} event={event} onAttend={setActiveEvent} />
        ))}
      {activeEvent && (
        <AttendFlow event={activeEvent} onClose={() => setActiveEvent(null)} />
      )}
    </main>
  );
}
```

(`AttendFlow` is written in Task 15 — this file won't compile until then;
that's expected, it's the next task in the same feature.)

- [ ] **Step 5: Commit**

```bash
git add frontend/.env frontend/lib/api.ts frontend/components/event-card.tsx frontend/app/page.tsx
git commit -m "feat: add frontend API client and event catalog

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 15: Frontend attend flow (clarifying-Q&A + confirmation)

**Files:**
- Create: `frontend/components/attend-flow.tsx`

**Interfaces:**
- Consumes: `attendEvent`, `answerRsvp` from `frontend/lib/api.ts` (Task 14)

- [ ] **Step 1: Add the shadcn dialog component**

```bash
cd frontend && npx shadcn@latest add dialog input label
```

- [ ] **Step 2: Write `frontend/components/attend-flow.tsx`**

```tsx
"use client";

import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  answerRsvp,
  attendEvent,
  type EventRecord,
  type RsvpQuestion,
} from "@/lib/api";

interface AttendFlowProps {
  event: EventRecord;
  onClose: () => void;
}

export function AttendFlow({ event, onClose }: AttendFlowProps) {
  const [loading, setLoading] = useState(true);
  const [questions, setQuestions] = useState<RsvpQuestion[]>([]);
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [result, setResult] = useState<{
    calendarEventId: string | null;
    formLink: string | null;
  } | null>(null);

  useEffect(() => {
    attendEvent(event.id)
      .then((res) => {
        if (res.done) {
          setResult({ calendarEventId: res.calendar_event_id, formLink: res.form_link });
        } else {
          setQuestions(res.questions);
        }
      })
      .finally(() => setLoading(false));
  }, [event.id]);

  async function submitAnswers() {
    setLoading(true);
    const res = await answerRsvp(event.id, answers);
    if (res.done) {
      setResult({ calendarEventId: res.calendar_event_id, formLink: res.form_link });
      setQuestions([]);
    } else {
      setQuestions(res.questions);
    }
    setLoading(false);
  }

  return (
    <Dialog open onOpenChange={onClose}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{event.title}</DialogTitle>
        </DialogHeader>

        {loading && <p>Working on it…</p>}

        {!loading && result && (
          <div className="flex flex-col gap-2">
            <p>Added to your calendar.</p>
            {result.formLink && (
              <a
                className="underline text-blue-600"
                href={result.formLink}
                target="_blank"
                rel="noreferrer"
              >
                Finish signing up (one click)
              </a>
            )}
          </div>
        )}

        {!loading && !result && questions.length > 0 && (
          <div className="flex flex-col gap-3">
            {questions.map((question) => (
              <div key={question.field_id} className="flex flex-col gap-1">
                <Label htmlFor={question.field_id}>{question.question}</Label>
                <Input
                  id={question.field_id}
                  value={answers[question.field_id] ?? ""}
                  onChange={(e) =>
                    setAnswers((prev) => ({ ...prev, [question.field_id]: e.target.value }))
                  }
                />
              </div>
            ))}
            <DialogFooter>
              <Button onClick={submitAnswers}>Continue</Button>
            </DialogFooter>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}
```

- [ ] **Step 3: Run the frontend dev server and confirm it compiles**

Run: `cd frontend && pnpm dev`
Expected: no TypeScript/build errors on `/` (backend does not need to be
running yet for this check — a fetch failure at runtime is fine here, a
compile error is not).

- [ ] **Step 4: Commit**

```bash
git add frontend/components/attend-flow.tsx frontend/package.json frontend/pnpm-lock.yaml frontend/components.json
git commit -m "feat: add RSVP clarifying-Q&A dialog and confirmation

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 16: GCP infra + deployment (manual/scripted, final integration)

This task is checklist-style, not TDD — it wires up real Google Cloud
resources and proves the whole pipeline end-to-end. Do this last, once Tasks
1–15 pass locally with mocks.

- [ ] **Step 1: Create the GCP project resources**

```bash
gcloud config set project <your-project-id>
gcloud services enable gmail.googleapis.com pubsub.googleapis.com \
  firestore.googleapis.com calendar-json.googleapis.com forms.googleapis.com \
  run.googleapis.com
gcloud firestore databases create --location=<your-region>
gcloud pubsub topics create gmail-events
gcloud pubsub subscriptions create gmail-events-push \
  --topic=gmail-events \
  --push-endpoint=https://<your-cloud-run-url>/api/v1/webhooks/gmail
```

- [ ] **Step 2: Grant the Gmail push service account publish rights**

```bash
gcloud pubsub topics add-iam-policy-binding gmail-events \
  --member="serviceAccount:gmail-api-push@system.gserviceaccount.com" \
  --role="roles/pubsub.publisher"
```

- [ ] **Step 3: Create an OAuth client and download `credentials.json`**

In GCP Console → APIs & Services → Credentials → Create OAuth client ID
(Desktop app type is simplest for the single-demo-user `InstalledAppFlow`
from Task 2). Save the downloaded file as `backend/credentials.json` (already
gitignored — do not commit it).

- [ ] **Step 4: Generate the first `token.json` locally**

```bash
cd backend && uv run python -c "
from app.core.google_auth import get_credentials
get_credentials([
    'https://www.googleapis.com/auth/gmail.readonly',
    'https://www.googleapis.com/auth/calendar',
    'https://www.googleapis.com/auth/forms.body.readonly',
])
"
```

This opens a browser consent flow once; `token.json` is written to
`backend/` for reuse (add both `credentials.json` and `token.json` to
`backend/.gitignore` if they aren't already covered by the existing `.env`-style ignore rules).

- [ ] **Step 5: Register the Gmail watch**

```bash
cd backend && uv run python -c "
from app.core.google_auth import get_credentials
from app.services.gmail_service import build_gmail_service

creds = get_credentials(['https://www.googleapis.com/auth/gmail.readonly'])
service = build_gmail_service(creds)
result = service.users().watch(userId='me', body={
    'topicName': 'projects/<your-project-id>/topics/gmail-events',
    'labelIds': ['INBOX'],
    'labelFilterBehavior': 'INCLUDE',
}).execute()
print(result)
"
```

Note the response includes an `expiration` timestamp — **watches expire
after 7 days**. For the demo window this is a non-issue; re-run this step if
the hackathon submission slips past a week.

- [ ] **Step 6: Add a `Dockerfile` for Cloud Run**

Create `backend/Dockerfile`:

```dockerfile
FROM python:3.11-slim
WORKDIR /app
RUN pip install uv
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev
COPY . .
CMD ["uv", "run", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
```

- [ ] **Step 7: Deploy the backend to Cloud Run**

```bash
cd backend && gcloud run deploy school-event-agent-backend \
  --source . \
  --region=<your-region> \
  --allow-unauthenticated \
  --set-env-vars=GOOGLE_CLOUD_PROJECT=<your-project-id>
```

Take the deployed URL and re-run Step 1's `gcloud pubsub subscriptions
create` (or `update`) with the real `--push-endpoint`, and re-run Step 5's
`watch()` call so the topic name matches.

- [ ] **Step 8: Deploy the frontend to Vercel**

```bash
cd frontend && vercel --prod
```

Set `NEXT_PUBLIC_API_URL` in the Vercel project settings to the Cloud Run
URL + `/api/v1`.

- [ ] **Step 9: End-to-end smoke test**

Send yourself a test email from a `@<school_email_domain>` address describing
a fake event with a Google Form link, and confirm: it shows up in the
deployed frontend's catalog within ~10 seconds, clicking "Attend" surfaces
only the form fields your profile doesn't already answer, and completing them
adds a Calendar event and returns a working prefilled Forms link.

- [ ] **Step 10: Commit the Dockerfile and any deploy config**

```bash
git add backend/Dockerfile
git commit -m "feat: add Cloud Run Dockerfile

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```
