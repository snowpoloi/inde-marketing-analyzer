from datetime import date
from typing import Any


class MerchantCenterConnector:
    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config

    def fetch_product_metrics(self, date_from: date, date_to: date) -> list[dict[str, Any]]:
        csv_url = self.config.get("csv_url")
        if not csv_url:
            raise ValueError("Merchant Center csv_url is missing. Configure a scheduled report export URL.")

        import csv
        import io

        import httpx

        response = httpx.get(csv_url, timeout=float(self.config.get("timeout_seconds", 60)))
        response.raise_for_status()
        return list(csv.DictReader(io.StringIO(response.text)))

