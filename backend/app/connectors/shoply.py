from datetime import date
from typing import Any

import httpx


class ShoplyConnector:
    def __init__(self, config: dict[str, Any]) -> None:
        self.api_url = config.get("api_url")
        self.api_key = config.get("api_key")
        self.timeout = float(config.get("timeout_seconds", 30))

    def fetch_sales(self, date_from: date, date_to: date) -> list[dict[str, Any]]:
        if not self.api_url:
            raise ValueError("Shoply api_url is missing. If Shoply only exports CSV, use the CSV import endpoint.")

        headers = {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        response = httpx.get(
            self.api_url,
            params={"date_from": date_from.isoformat(), "date_to": date_to.isoformat()},
            headers=headers,
            timeout=self.timeout,
        )
        response.raise_for_status()
        payload = response.json()
        if isinstance(payload, list):
            return payload
        if isinstance(payload, dict):
            sales = payload.get("sales", payload.get("orders", payload.get("data", [])))
            if isinstance(sales, list):
                return sales
        raise ValueError("Shoply API must return a list or an object with sales/orders/data list.")

