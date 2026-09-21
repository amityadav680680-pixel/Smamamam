from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    host: str = "0.0.0.0"
    port: int = 8000
    public_base_url: str = "http://localhost:8000"

    webhook_api_key: str = "change-me-to-a-long-random-secret"
    admin_api_key: str = "change-me-admin-secret"

    telegram_bot_token: str = ""
    telegram_allowed_user_ids: str = ""
    telegram_push_new_sms: bool = True

    database_url: str = "sqlite+aiosqlite:///./data/sms_monitor.db"

    # Optional Firebase Realtime Database — /a attaches device here too
    # Example: https://my-project-default-rtdb.firebaseio.com
    firebase_rtdb_url: str = ""
    firebase_auth_token: str = ""

    @property
    def allowed_user_ids(self) -> set[int]:
        if not self.telegram_allowed_user_ids.strip():
            return set()
        return {
            int(part.strip())
            for part in self.telegram_allowed_user_ids.split(",")
            if part.strip()
        }

    @property
    def firebase_enabled(self) -> bool:
        return bool(self.firebase_rtdb_url.strip())


@lru_cache
def get_settings() -> Settings:
    return Settings()
