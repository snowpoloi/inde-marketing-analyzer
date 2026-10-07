from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.connectors.supplier_catalog import validate_feed_url


class SupplierCatalogFeedInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str = Field(min_length=1, max_length=120, pattern=r"^[A-Za-z0-9_-]+$")
    name: str = Field(min_length=1, max_length=255)
    adapter: str = "megapap"
    url: str | None = Field(default=None, max_length=4000)
    is_enabled: bool = True
    refresh_hours: int = Field(default=24, ge=6, le=168)

    @field_validator("adapter")
    @classmethod
    def supported_adapter(cls, value: str) -> str:
        if value != "megapap":
            raise ValueError("This supplier XML format is not yet supported.")
        return value

    @field_validator("url")
    @classmethod
    def safe_url(cls, value: str | None) -> str | None:
        return validate_feed_url(value) if value and value.strip() else None

    @field_validator("name")
    @classmethod
    def nonempty_name(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Supplier name is required.")
        return value.strip()
