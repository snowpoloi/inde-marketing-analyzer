from datetime import date
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Amount = Annotated[Decimal, Field(ge=0, le=100000, allow_inf_nan=False)]
Dimension = Annotated[Decimal, Field(gt=0, le=10000, allow_inf_nan=False)]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ShippingZone(StrictModel):
    code: str = Field(min_length=1, max_length=80)
    label: str = Field(min_length=1, max_length=160)
    minimum: Amount = Decimal(0)
    small_parcel: Amount = Decimal(0)
    medium_parcel: Amount = Decimal(0)
    per_m3: Amount = Decimal(0)
    extra_kg: Amount = Decimal(0)
    sea: Amount = Decimal(0)


class ShippingDestinationRule(StrictModel):
    zone_code: str = Field(min_length=1, max_length=80)
    regions: list[str] = Field(default_factory=list, max_length=100)
    localities: list[str] = Field(default_factory=list, max_length=100)
    postcodes: list[str] = Field(default_factory=list, max_length=100)
    local_cod: bool | None = None
    remote_extra_net: Amount | None = None
    cod_allowed: bool | None = None

    @model_validator(mode="after")
    def require_selector(self):
        if not any((self.regions, self.localities, self.postcodes)):
            raise ValueError("Destination rules require at least one address selector.")
        if any(not value.strip() or len(value) > 200 for value in self.regions + self.localities):
            raise ValueError("Invalid destination rule name.")
        if any(len(value) != 5 or not value.isascii() or not value.isdigit() for value in self.postcodes):
            raise ValueError("Destination rule postcodes must have five digits.")
        return self


class CarrierTariff(StrictModel):
    version: str = Field(min_length=1, max_length=100)
    valid_from: date
    valid_to: date | None = None
    zones: list[ShippingZone] = Field(min_length=1, max_length=20)
    base_10kg: Amount = Decimal(0)
    base_20kg: Amount = Decimal(0)
    waybill: Amount = Decimal(0)
    small_pickup: Amount = Decimal(0)
    cod_local: Amount = Decimal(0)
    cod_minimum: Amount = Decimal(0)
    cod_percent: Amount = Decimal(0)
    remote: Amount = Decimal(0)
    saturday: Amount = Decimal(0)
    timed: Amount = Decimal(0)
    fuel_percent: dict[str, Amount] = Field(default_factory=dict, max_length=120)
    max_side_cm: Dimension | None = None
    max_sum_cm: Dimension | None = None
    destination_rules: list[ShippingDestinationRule] = Field(default_factory=list, max_length=500)

    @model_validator(mode="after")
    def valid_dates_and_zones(self):
        if self.valid_to and self.valid_to < self.valid_from:
            raise ValueError("Invalid tariff validity dates.")
        if len({zone.code for zone in self.zones}) != len(self.zones):
            raise ValueError("Duplicate shipping zones.")
        if any(rule.zone_code not in {zone.code for zone in self.zones} for rule in self.destination_rules):
            raise ValueError("Destination rule references an unknown tariff zone.")
        for month, percentage in self.fuel_percent.items():
            try:
                date.fromisoformat(f"{month}-01")
            except ValueError as exc:
                raise ValueError("Fuel surcharge keys must use YYYY-MM.") from exc
            if len(month) != 7 or percentage > 100:
                raise ValueError("Invalid monthly fuel surcharge.")
        return self


class ShippingArea(StrictModel):
    postcode: str = Field(pattern=r"^\d{5}$")
    locality: str = Field(min_length=1, max_length=200)
    municipality: str = Field(default="", max_length=200)
    status: Literal["active", "remote", "no_cod", "remote_rate"]
    extra_net: Amount | None = None


class ShippingSettings(StrictModel):
    origin: Literal["Athens"] = "Athens"
    vat_percent: Amount
    volumetric_divisor: int = Field(default=5000, ge=1, le=100000)
    mytrans: CarrierTariff
    speedex: CarrierTariff
    mytrans_areas: list[ShippingArea] = Field(default_factory=list, max_length=15000)
    speedex_areas: list[ShippingArea] = Field(default_factory=list, max_length=20000)
    mytrans_area_source: str = Field(default="", max_length=300)
    speedex_area_source: str = Field(default="", max_length=300)

    @model_validator(mode="after")
    def verify_rates(self):
        if self.vat_percent > 100:
            raise ValueError("VAT percentage cannot exceed 100.")
        if any(min(zone.minimum, zone.small_parcel, zone.medium_parcel, zone.per_m3) <= 0 for zone in self.mytrans.zones):
            raise ValueError("All Mytrans destination tiers must have positive rates.")
        if min(self.speedex.base_10kg, self.speedex.base_20kg) <= 0 or any(zone.extra_kg <= 0 for zone in self.speedex.zones):
            raise ValueError("All Speedex weight tiers must have positive rates.")
        if any(row.status == "remote_rate" and row.extra_net is None for row in self.mytrans_areas):
            raise ValueError("Remote rate records require an additional net charge.")
        if any(row.status not in {"active", "remote"} for row in self.speedex_areas):
            raise ValueError("Speedex area records must be active or remote.")
        return self


class ShippingParcel(StrictModel):
    key: str = Field(min_length=1, max_length=160)
    label: str = Field(min_length=1, max_length=500)
    width_cm: Dimension | None = None
    length_cm: Dimension | None = None
    height_cm: Dimension | None = None
    weight_kg: Dimension | None = None


class ShippingEstimateRequest(StrictModel):
    shipping_date: date
    parcels: list[ShippingParcel] = Field(min_length=1, max_length=200)
    manifest_confirmed: bool = False
    mytrans_zone: str = Field(default="", max_length=80)
    speedex_zone: str = Field(default="", max_length=80)
    mytrans_area_confirmed: bool = False
    mytrans_remote_extra: Amount | None = None
    mytrans_cod_allowed: bool | None = None
    mytrans_local_cod: bool | None = None
    small_pickup: Literal[False] = False
    speedex_remote: bool | None = None
    saturday: bool = False
    timed: bool = False
    cod: bool | None = None
    cod_amount: Amount | None = None
    speedex_cod_parcels: int | None = Field(default=None, ge=1, le=200)
    # The stored OpenCart shipping tax basis has not been established.
    customer_shipping_net: Amount | None = None

    @model_validator(mode="after")
    def unique_parcels(self):
        if len({parcel.key for parcel in self.parcels}) != len(self.parcels):
            raise ValueError("Parcel identifiers must be unique.")
        if self.speedex_cod_parcels and self.speedex_cod_parcels > len(self.parcels):
            raise ValueError("COD parcel count exceeds shipment parcel count.")
        return self
