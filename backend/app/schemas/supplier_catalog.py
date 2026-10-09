from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.connectors.supplier_catalog import ADAPTER_HOSTS, validate_feed_url
from decimal import Decimal
from uuid import UUID


class SupplierCatalogPricingInput(BaseModel):
    sale_vat_rate: Decimal | None = Field(default=None, ge=0, le=100)
    volumetric_divisor: int = Field(default=5000, ge=1000, le=10000)
    automatic_costs: bool = False
    piece_supplier_ids: list[UUID] = Field(default_factory=list, max_length=100)


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
        if value not in ADAPTER_HOSTS:
            raise ValueError("This supplier XML format is not yet supported.")
        return value

    @model_validator(mode="after")
    def safe_url(self):
        self.url = validate_feed_url(self.url, self.adapter) if self.url and self.url.strip() else None
        return self

    @field_validator("name")
    @classmethod
    def nonempty_name(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Supplier name is required.")
        return value.strip()
