from typing import Any

from pydantic import BaseModel, Field


class IntegrationSettingResponse(BaseModel):
    provider: str
    display_name: str
    is_enabled: bool
    config: dict[str, Any]


class IntegrationSettingUpdate(BaseModel):
    is_enabled: bool = False
    config: dict[str, Any] = Field(default_factory=dict)

