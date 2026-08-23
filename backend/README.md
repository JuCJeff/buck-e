# buck-e backend

FastAPI backend, managed with [uv](https://docs.astral.sh/uv/).

## Setup

```bash
cd backend
uv sync
```

## Run

```bash
uv run dev
```

Or directly:

```bash
uv run main.py
```

Server runs at <http://localhost:8000> with auto-reload. Docs at <http://localhost:8000/docs>.

## Config

Settings live in `app/core/config.py` (via `pydantic-settings`). Copy `.env.example` to `.env`
in `backend/` and fill in the values, e.g.:

```env
debug=true

gcp_project_id=your-gcp-project-id
google_application_credentials=/absolute/path/to/service-account.json
firestore_database_id=(default)
```

`gcp_project_id` and `google_application_credentials` point at an existing GCP/Firebase project
and service-account key — this project does not set those up for you. If
`google_application_credentials` is unset, the backend falls back to Application Default
Credentials (used in deployed environments with an attached service account).

### Firestore emulator (local dev)

To develop against a local Firestore emulator instead of real GCP, no service account or
project is required.

1. Install the emulator once (needs the JDK, which `gcloud` will check for):

   ```bash
   gcloud components install cloud-firestore-emulator
   ```

2. Start it in one terminal:

   ```bash
   gcloud emulators firestore start --host-port=localhost:8080
   ```

3. In `backend/.env`, set:

   ```env
   firestore_emulator_host=localhost:8080
   ```

4. Run the backend as usual (`uv run dev`). All Firestore reads/writes go to the emulator; data
   resets when the emulator process stops.

### Email domain allow-list

`POST /api/v1/events/` only accepts events whose `sender` email address ends with one of the
domains in `allowed_email_domains`, a comma-separated list in `.env`:

```env
allowed_email_domains=example.com,example.org
```

If `allowed_email_domains` is unset or empty, every `POST` is rejected with `400` — the list is
an allow-list, not an optional filter.

## Tests

```bash
uv run pytest
```
