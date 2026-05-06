from typing import Any

from pydantic import BaseModel


class DashboardResponse(BaseModel):
    data: dict[str, Any]

