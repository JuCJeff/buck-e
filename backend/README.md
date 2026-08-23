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

Settings live in `app/core/config.py` (via `pydantic-settings`). Override any of `app_name`,
`app_version`, `debug` by creating a `.env` file in `backend/`, e.g.:

```env
debug=true
```

## Tests

```bash
uv run pytest
```
