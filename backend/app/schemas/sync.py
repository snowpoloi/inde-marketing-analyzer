from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, Field


class SyncTriggerRequest(BaseModel):
    providers: list[str] = Field(default_factory=list)
    date_from: date | None = None
    date_to: date | None = None


class SyncRunResponse(BaseModel):
    id: str
    provider: str
    sync_type: str
    status: str
    date_from: date | None
    date_to: date | None
    started_at: datetime
    finished_at: datetime | None
    records_processed: int
    error_message: str | None
    meta: dict[str, Any]

