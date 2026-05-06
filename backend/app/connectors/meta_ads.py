from datetime import date
from typing import Any

import httpx


class MetaAdsConnector:
    def __init__(self, config: dict[str, Any]) -> None:
        self.access_token = config.get("access_token")
        account_id = str(config.get("ad_account_id", "")).replace("act_", "")
        self.account_id = account_id
        self.graph_version = config.get("graph_version", "v20.0")
        self.timeout = float(config.get("timeout_seconds", 60))

    def fetch_campaign_metrics(self, date_from: date, date_to: date) -> list[dict[str, Any]]:
        if not self.access_token or not self.account_id:
            raise ValueError("Meta Ads access_token and ad_account_id are required.")

        url = f"https://graph.facebook.com/{self.graph_version}/act_{self.account_id}/insights"
        params = {
            "access_token": self.access_token,
            "time_range": f'{{"since":"{date_from.isoformat()}","until":"{date_to.isoformat()}"}}',
            "time_increment": 1,
            "level": "ad",
            "fields": ",".join(
                [
                    "date_start",
                    "campaign_id",
                    "campaign_name",
                    "adset_id",
                    "adset_name",
                    "ad_id",
                    "ad_name",
                    "spend",
                    "impressions",
                    "reach",
                    "frequency",
                    "cpc",
                    "cpm",
                    "ctr",
                    "actions",
                    "action_values",
                    "inline_link_clicks",
                ]
            ),
        }

        rows: list[dict[str, Any]] = []
        with httpx.Client(timeout=self.timeout) as client:
            while url:
                response = client.get(url, params=params)
                response.raise_for_status()
                payload = response.json()
                rows.extend(payload.get("data", []))
                url = payload.get("paging", {}).get("next")
                params = {}
        return rows

