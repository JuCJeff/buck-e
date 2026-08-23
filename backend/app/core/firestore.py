import os
from functools import lru_cache

from google.cloud import firestore
from google.oauth2 import service_account

from app.core.config import settings


@lru_cache
def get_firestore_client() -> firestore.Client:
    """Lazily construct and cache a Firestore client.

    When settings.firestore_emulator_host is set, points the client at the
    local Firestore emulator (no real credentials needed). Otherwise uses
    explicit service-account credentials from
    settings.google_application_credentials when set (local dev against a
    real project), or falls back to Application Default Credentials (prod).
    """
    if settings.firestore_emulator_host:
        os.environ.setdefault("FIRESTORE_EMULATOR_HOST", settings.firestore_emulator_host)
        return firestore.Client(
            project=settings.gcp_project_id or "buck-e-emulator",
            database=settings.firestore_database_id,
        )

    credentials = None
    if settings.google_application_credentials:
        credentials = service_account.Credentials.from_service_account_file(
            settings.google_application_credentials
        )

    return firestore.Client(
        project=settings.gcp_project_id,
        credentials=credentials,
        database=settings.firestore_database_id,
    )
