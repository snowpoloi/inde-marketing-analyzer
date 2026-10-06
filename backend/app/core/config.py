from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field


class Settings(BaseSettings):
    app_name: str = "INDE Marketing Analyzer"
    environment: str = "production"
    database_url: str = "postgresql+psycopg://inde:inde@db:5432/inde_marketing"
    secret_key: str = "change-me"
    access_token_expire_minutes: int = 60 * 24
    cors_origins: str = "https://analyzer.inde.gr,http://localhost:3000,http://localhost:5173"
    admin_email: str | None = None
    admin_password: str | None = None
    sync_daily_hour: int = 4
    sync_timezone: str = "Europe/Athens"
    supplier_gmail_enabled: bool = False
    supplier_gmail_client_id: str | None = None
    supplier_gmail_client_secret: str | None = None
    supplier_gmail_refresh_token: str | None = None
    supplier_gmail_auto_enabled: bool = True
    supplier_gmail_interval_minutes: int = Field(default=15, ge=5, le=1440)

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
