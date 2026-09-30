from datetime import date
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class OrderAnalyticsPeriod(BaseModel):
    key: str = Field(min_length=1, max_length=40)
    label: str = Field(min_length=1, max_length=80)
    date_from: date
    date_to: date

    @model_validator(mode="after")
    def validate_dates(self):
        if self.date_to < self.date_from:
            raise ValueError("Period end date must be on or after its start date.")
        return self


class OrderAnalyticsRequest(BaseModel):
    periods: list[OrderAnalyticsPeriod] = Field(min_length=2, max_length=4)
    statuses: list[str] = Field(default_factory=list)
    aging_statuses: list[str] = Field(default_factory=list)
    completed_statuses: list[str] = Field(default_factory=list)
    cancelled_statuses: list[str] = Field(default_factory=list)
    group_by: Literal["day", "month"] = "day"
    stale_days: int = Field(default=3, ge=0, le=3650)


class OrderAnalyticsDefaultsRequest(BaseModel):
    statuses: list[str] = Field(default_factory=list, max_length=500)
    aging_statuses: list[str] = Field(default_factory=list, max_length=500)
    completed_statuses: list[str] = Field(default_factory=list, max_length=500)
    cancelled_statuses: list[str] = Field(default_factory=list, max_length=500)
    group_by: Literal["day", "month"] = "day"
    stale_days: int = Field(default=3, ge=0, le=3650)
