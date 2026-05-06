from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


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

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
