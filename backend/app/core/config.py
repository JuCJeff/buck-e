from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    app_name: str = "buck-e"
    app_version: str = "0.1.0"
    debug: bool = False

    # Firestore / GCP
    gcp_project_id: Optional[str] = None
    google_application_credentials: Optional[str] = None
    firestore_database_id: str = "(default)"
    firestore_emulator_host: Optional[str] = None


settings = Settings()
