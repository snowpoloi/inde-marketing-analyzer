import base64
import json
from datetime import date
from pathlib import Path
from typing import Any

ANALYTICS_READONLY_SCOPE = "https://www.googleapis.com/auth/analytics.readonly"


class GA4Connector:
    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config

    def _property_name(self) -> str:
        property_id = str(self.config.get("property_id") or self.config.get("property") or "").strip()
        if not property_id:
            raise ValueError("GA4 property_id is required.")
        if property_id.startswith("properties/"):
            return property_id
        return f"properties/{property_id}"

    def _service_account_info(self) -> dict[str, Any]:
        raw_info = self.config.get("service_account_json")
        if not raw_info and self.config.get("service_account_json_base64"):
            raw_info = base64.b64decode(str(self.config["service_account_json_base64"])).decode("utf-8")
        if not raw_info and self.config.get("service_account_file"):
            raw_info = Path(str(self.config["service_account_file"])).read_text(encoding="utf-8")

        if isinstance(raw_info, str):
            try:
                raw_info = json.loads(raw_info)
            except json.JSONDecodeError as exc:
                raise ValueError("GA4 service_account_json must be valid JSON.") from exc

        if not isinstance(raw_info, dict) or not raw_info:
            raise ValueError("GA4 service_account_json is required.")

        private_key = raw_info.get("private_key")
        if isinstance(private_key, str) and "\\n" in private_key:
            raw_info = {**raw_info, "private_key": private_key.replace("\\n", "\n")}
        return raw_info

    def fetch_daily_metrics(self, date_from: date, date_to: date) -> list[dict[str, Any]]:
        try:
            from google.analytics.data_v1beta import BetaAnalyticsDataClient
            from google.analytics.data_v1beta.types import DateRange, Dimension, Metric, RunReportRequest
            from google.oauth2 import service_account
        except ImportError as exc:
            raise RuntimeError("google-analytics-data package is not installed.") from exc

        credentials = service_account.Credentials.from_service_account_info(self._service_account_info()).with_scopes(
            [ANALYTICS_READONLY_SCOPE]
        )
        client = BetaAnalyticsDataClient(credentials=credentials)
        request = RunReportRequest(
            property=self._property_name(),
            dimensions=[
                Dimension(name="date"),
                Dimension(name="sessionDefaultChannelGroup"),
                Dimension(name="sessionSourceMedium"),
            ],
            metrics=[
                Metric(name="sessions"),
                Metric(name="totalUsers"),
                Metric(name="ecommercePurchases"),
                Metric(name="purchaseRevenue"),
                Metric(name="keyEvents"),
            ],
            date_ranges=[DateRange(start_date=date_from.isoformat(), end_date=date_to.isoformat())],
        )
        response = client.run_report(request)
        rows: list[dict[str, Any]] = []
        for row in response.rows:
            rows.append(
                {
                    "date": row.dimension_values[0].value,
                    "channel_group": row.dimension_values[1].value,
                    "source_medium": row.dimension_values[2].value,
                    "sessions": row.metric_values[0].value,
                    "users": row.metric_values[1].value,
                    "purchases": row.metric_values[2].value,
                    "purchase_revenue": row.metric_values[3].value,
                    "conversions": row.metric_values[4].value,
                }
            )
        return rows
