from datetime import date
from typing import Any

import httpx


class OpenCartConnector:
    def __init__(self, config: dict[str, Any]) -> None:
        self.endpoint_url = config.get("endpoint_url")
        self.api_key = config.get("api_key")
        self.timeout = float(config.get("timeout_seconds", 30))

    def fetch_orders(self, date_from: date, date_to: date) -> list[dict[str, Any]]:
        if not self.endpoint_url:
            raise ValueError("OpenCart endpoint_url is missing in integration settings.")

        headers = {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        response = httpx.get(
            self.endpoint_url,
            params={"date_from": date_from.isoformat(), "date_to": date_to.isoformat()},
            headers=headers,
            timeout=self.timeout,
        )
        response.raise_for_status()
        payload = response.json()
        if isinstance(payload, list):
            return payload
        if isinstance(payload, dict):
            orders = payload.get("orders", payload.get("data", []))
            if isinstance(orders, list):
                return orders
        raise ValueError("OpenCart endpoint must return a list or an object with orders/data list.")

