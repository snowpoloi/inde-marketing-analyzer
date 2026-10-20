from datetime import date
from typing import Any


class GoogleAdsConnector:
    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config

    def _service(self):
        try:
            from google.ads.googleads.client import GoogleAdsClient
        except ImportError as exc:
            raise RuntimeError("google-ads package is not installed.") from exc

        required = ["developer_token", "client_id", "client_secret", "refresh_token", "customer_id"]
        missing = [key for key in required if not self.config.get(key)]
        if missing:
            raise ValueError(f"Google Ads missing settings: {', '.join(missing)}")

        client_config = {
            "developer_token": self.config["developer_token"],
            "client_id": self.config["client_id"],
            "client_secret": self.config["client_secret"],
            "refresh_token": self.config["refresh_token"],
            "use_proto_plus": True,
        }
        if self.config.get("login_customer_id"):
            client_config["login_customer_id"] = str(self.config["login_customer_id"])

        client = GoogleAdsClient.load_from_dict(client_config)
        service = client.get_service("GoogleAdsService")
        customer_id = str(self.config["customer_id"]).replace("-", "")
        return service, customer_id

    def fetch_campaign_metrics(self, date_from: date, date_to: date) -> list[dict[str, Any]]:
        service, customer_id = self._service()
        query = f"""
            SELECT
              segments.date,
              campaign.id,
              campaign.name,
              campaign.advertising_channel_type,
              metrics.cost_micros,
              metrics.clicks,
              metrics.impressions,
              metrics.conversions,
              metrics.conversions_value,
              metrics.average_cpc,
              metrics.cost_per_conversion
            FROM campaign
            WHERE segments.date BETWEEN '{date_from.isoformat()}' AND '{date_to.isoformat()}'
        """

        rows: list[dict[str, Any]] = []
        response = service.search_stream(customer_id=customer_id, query=query)
        for batch in response:
            for row in batch.results:
                cost = float(row.metrics.cost_micros or 0) / 1_000_000
                rows.append(
                    {
                        "date": str(row.segments.date),
                        "campaign_id": str(row.campaign.id),
                        "campaign_name": row.campaign.name,
                        "campaign_type": row.campaign.advertising_channel_type.name,
                        "cost": cost,
                        "clicks": row.metrics.clicks,
                        "impressions": row.metrics.impressions,
                        "conversions": float(row.metrics.conversions or 0),
                        "conversion_value": float(row.metrics.conversions_value or 0),
                        "avg_cpc": float(row.metrics.average_cpc or 0) / 1_000_000,
                        "cost_per_conversion": float(row.metrics.cost_per_conversion or 0) / 1_000_000,
                    }
                )
        return rows

    def fetch_changes(self, date_from: date, date_to: date) -> list[dict[str, Any]]:
        from datetime import datetime, timedelta
        from zoneinfo import ZoneInfo

        today = datetime.now(ZoneInfo("Europe/Athens")).date()
        if date_from < today - timedelta(days=28):
            raise ValueError("Google change events older than 28 days require a Change History export.")
        service, customer_id = self._service()
        account_timezone = None
        for batch in service.search_stream(customer_id=customer_id, query="SELECT customer.time_zone FROM customer LIMIT 1"):
            for row in batch.results:
                account_timezone = row.customer.time_zone
        if not account_timezone:
            raise ValueError("Google Ads account timezone unavailable; change times cannot be interpreted safely.")
        rows = []
        # Daily slices avoid a silent truncation at the API's 10,000-event limit.
        day = date_from
        while day <= date_to:
            query = f"""
                SELECT change_event.resource_name, change_event.change_date_time,
                  change_event.change_resource_name, change_event.user_email,
                  change_event.client_type, change_event.change_resource_type,
                  change_event.old_resource, change_event.new_resource,
                  change_event.resource_change_operation, change_event.changed_fields,
                  change_event.campaign
                FROM change_event
                WHERE change_event.change_date_time >= '{day.isoformat()} 00:00:00'
                  AND change_event.change_date_time <= '{day.isoformat()} 23:59:59'
                ORDER BY change_event.change_date_time ASC LIMIT 10000
            """
            daily = []
            for batch in service.search_stream(customer_id=customer_id, query=query):
                for row in batch.results:
                    daily.append({**type(row.change_event).to_dict(row.change_event, use_integers_for_enums=False),
                                  "account_time_zone": account_timezone})
            if len(daily) >= 10000:
                raise ValueError(f"Change-event limit reached on {day}; export required, history is incomplete.")
            rows.extend(daily)
            day += timedelta(days=1)
        return rows

