from datetime import date, timedelta
from typing import Any

import httpx


class MetaAdsApiError(RuntimeError):
    pass


class MetaAdsConnector:
    def __init__(self, config: dict[str, Any]) -> None:
        self.access_token = config.get("access_token")
        account_id = str(config.get("ad_account_id", "")).replace("act_", "")
        self.account_id = account_id
        self.graph_version = config.get("graph_version", "v20.0")
        self.timeout = float(config.get("timeout_seconds", 60))
        self.max_days_per_request = self._positive_int(config.get("max_days_per_request"), 7)

    def _positive_int(self, value: Any, default: int) -> int:
        try:
            return max(1, int(value or default))
        except (TypeError, ValueError):
            return default

    def _request(self, client: httpx.Client, url: str, params: dict[str, Any]) -> dict[str, Any]:
        response = client.get(url, params=params)
        if response.status_code >= 400:
            raise MetaAdsApiError(self._format_error(response))
        return response.json()

    def _format_error(self, response: httpx.Response) -> str:
        message = response.text
        error_type = None
        error_code = None
        error_subcode = None
        fbtrace_id = None
        try:
            payload = response.json()
            error = payload.get("error") if isinstance(payload, dict) else None
            if isinstance(error, dict):
                message = error.get("error_user_msg") or error.get("message") or message
                error_type = error.get("type")
                error_code = error.get("code")
                error_subcode = error.get("error_subcode")
                fbtrace_id = error.get("fbtrace_id")
        except ValueError:
            pass

        parts = [f"Meta Ads API returned {response.status_code}: {message}"]
        details = []
        if error_type:
            details.append(f"type={error_type}")
        if error_code:
            details.append(f"code={error_code}")
        if error_subcode:
            details.append(f"subcode={error_subcode}")
        if fbtrace_id:
            details.append(f"fbtrace_id={fbtrace_id}")
        if details:
            parts.append(f"({', '.join(details)})")
        if response.status_code == 403:
            parts.append(
                "Check that the token has ads_read permission and that the token owner/system user has access "
                f"to ad account act_{self.account_id}."
            )
        return " ".join(parts)

    def _date_windows(self, date_from: date, date_to: date) -> list[tuple[date, date]]:
        windows = []
        cursor = date_from
        while cursor <= date_to:
            window_to = min(cursor + timedelta(days=self.max_days_per_request - 1), date_to)
            windows.append((cursor, window_to))
            cursor = window_to + timedelta(days=1)
        return windows

    def _base_params(self, date_from: date, date_to: date) -> dict[str, Any]:
        return {
            "access_token": self.access_token,
            "time_range": f'{{"since":"{date_from.isoformat()}","until":"{date_to.isoformat()}"}}',
            "time_increment": 1,
            "level": "ad",
            "limit": 500,
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

    def _fetch_window(self, client: httpx.Client, date_from: date, date_to: date) -> list[dict[str, Any]]:
        url = f"https://graph.facebook.com/{self.graph_version}/act_{self.account_id}/insights"
        base_params = self._base_params(date_from, date_to)
        rows: list[dict[str, Any]] = []
        after = None
        while True:
            params = dict(base_params)
            if after:
                params["after"] = after
            payload = self._request(client, url, params)
            rows.extend(payload.get("data", []))
            paging = payload.get("paging", {})
            after = paging.get("cursors", {}).get("after")
            if not paging.get("next") or not after:
                break
        return rows

    def fetch_campaign_metrics(self, date_from: date, date_to: date) -> list[dict[str, Any]]:
        if not self.access_token or not self.account_id:
            raise ValueError("Meta Ads access_token and ad_account_id are required.")

        rows: list[dict[str, Any]] = []
        with httpx.Client(timeout=self.timeout) as client:
            for window_from, window_to in self._date_windows(date_from, date_to):
                rows.extend(self._fetch_window(client, window_from, window_to))
        return rows
