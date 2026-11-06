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
    # Same-day syncs of today, at these hours (sync_timezone) for these providers. Empty or "off" turns them off.
    sync_intraday_hours: str = "8,10,12,14,16,18,20,22"
    sync_intraday_providers: str = "google_ads,meta_ads,tiktok_ads,opencart,ga4"
    promotion_media_dir: str = "promotion-media"
    promotion_ffmpeg_path: str = "ffmpeg"
    supplier_gmail_enabled: bool = False
    supplier_gmail_client_id: str | None = None
    supplier_gmail_client_secret: str | None = None
    supplier_gmail_refresh_token: str | None = None
    supplier_gmail_auto_enabled: bool = True
    supplier_gmail_interval_minutes: int = Field(default=15, ge=5, le=1440)
    # SHA-256 (hex) of the ADVESTIQ access key. The key itself is never stored here.
    advestiq_api_key_sha256: str | None = None

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def sync_intraday_hour_list(self) -> list[int]:
        hours = {int(part) for part in _setting_list(self.sync_intraday_hours) if part.isdigit()}
        return sorted(hour for hour in hours if 0 <= hour <= 23)

    @property
    def sync_intraday_provider_list(self) -> list[str]:
        return list(dict.fromkeys(_setting_list(self.sync_intraday_providers)))


def _setting_list(value: str | None) -> list[str]:
    """Comma-separated setting; empty, "off" or "none" means no items."""
    text = (value or "").strip().lower()
    if text in {"", "off", "none"}:
        return []
    return [part.strip() for part in text.split(",") if part.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
