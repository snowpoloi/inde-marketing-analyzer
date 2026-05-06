from datetime import date
from typing import Any


class GA4Connector:
    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config

    def fetch_daily_metrics(self, date_from: date, date_to: date) -> list[dict[str, Any]]:
        try:
            from google.analytics.data_v1beta import BetaAnalyticsDataClient
            from google.analytics.data_v1beta.types import DateRange, Dimension, Metric, RunReportRequest
            from google.oauth2 import service_account
        except ImportError as exc:
            raise RuntimeError("google-analytics-data package is not installed.") from exc

        property_id = self.config.get("property_id")
        service_account_info = self.config.get("service_account_json")
        if not property_id or not service_account_info:
            raise ValueError("GA4 property_id and service_account_json are required.")

        credentials = service_account.Credentials.from_service_account_info(service_account_info)
        client = BetaAnalyticsDataClient(credentials=credentials)
        request = RunReportRequest(
            property=f"properties/{property_id}",
            dimensions=[
                Dimension(name="date"),
                Dimension(name="sessionDefaultChannelGroup"),
                Dimension(name="sessionSourceMedium"),
            ],
            metrics=[
                Metric(name="sessions"),
                Metric(name="totalUsers"),
                Metric(name="purchases"),
                Metric(name="purchaseRevenue"),
                Metric(name="conversions"),
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

