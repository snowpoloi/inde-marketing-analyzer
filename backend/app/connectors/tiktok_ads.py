import json
from datetime import date, timedelta
from typing import Any

import httpx


class TikTokAdsApiError(RuntimeError):
    pass


class TikTokAdsConnector:
    """Read-only TikTok Marketing API reporting connector."""

    DEFAULT_METRICS = [
        "campaign_name",
        "spend",
        "impressions",
        "clicks",
        "ctr",
        "cpc",
        "cpm",
        "onsite_total_purchase",
        "onsite_total_purchase_value_day29",
    ]

    def __init__(self, config: dict[str, Any]) -> None:
        self.access_token = str(config.get("access_token") or "").strip()
        self.advertiser_id = str(config.get("advertiser_id") or "").strip()
        self.base_url = str(config.get("base_url") or "https://business-api.tiktok.com/open_api").rstrip("/")
        self.api_version = str(config.get("api_version") or "v1.3").strip("/")
        self.timeout = float(config.get("timeout_seconds") or 60)
        self.page_size = min(max(self._positive_int(config.get("page_size"), 1000), 1), 1000)
        self.max_days_per_request = min(max(self._positive_int(config.get("max_days_per_request"), 30), 1), 30)
        self.currency = str(config.get("currency") or "EUR").upper()
        configured_metrics = config.get("metrics")
        self.metrics = [str(metric).strip() for metric in configured_metrics if str(metric).strip()] if isinstance(configured_metrics, list) else self.DEFAULT_METRICS

    @staticmethod
    def _positive_int(value: Any, default: int) -> int:
        try:
            return max(1, int(value or default))
        except (TypeError, ValueError):
            return default

    def _date_windows(self, date_from: date, date_to: date) -> list[tuple[date, date]]:
        windows = []
        cursor = date_from
        while cursor <= date_to:
            window_to = min(cursor + timedelta(days=self.max_days_per_request - 1), date_to)
            windows.append((cursor, window_to))
            cursor = window_to + timedelta(days=1)
        return windows

    def _request(self, client: httpx.Client, params: dict[str, Any]) -> dict[str, Any]:
        response = client.get(
            f"{self.base_url}/{self.api_version}/report/integrated/get/",
            params=params,
            headers={"Access-Token": self.access_token},
        )
        if response.status_code >= 400:
            raise TikTokAdsApiError(f"TikTok Ads API returned {response.status_code}: {self._message(response)}")
        try:
            payload = response.json()
        except ValueError as exc:
            raise TikTokAdsApiError("TikTok Ads API returned an invalid JSON response.") from exc
        if str(payload.get("code")) not in {"0", "None"}:
            raise TikTokAdsApiError(f"TikTok Ads API error {payload.get('code')}: {payload.get('message') or 'Unknown error'}")
        return payload

    @classmethod
    def exchange_authorization_code(cls, config: dict[str, Any], auth_code: str) -> dict[str, Any]:
        app_id = str(config.get("app_id") or "").strip()
        app_secret = str(config.get("app_secret") or "").strip()
        base_url = str(config.get("base_url") or "https://business-api.tiktok.com/open_api").rstrip("/")
        api_version = str(config.get("api_version") or "v1.3").strip("/")
        timeout = float(config.get("timeout_seconds") or 60)
        if not app_id or not app_secret:
            raise ValueError("TikTok Ads app_id and app_secret are required before authorization.")

        response = httpx.post(
            f"{base_url}/{api_version}/oauth2/access_token/",
            json={"app_id": app_id, "secret": app_secret, "auth_code": auth_code},
            timeout=timeout,
        )
        if response.status_code >= 400:
            raise TikTokAdsApiError(f"TikTok Ads authorization returned {response.status_code}: {cls._message(response)}")
        try:
            payload = response.json()
        except ValueError as exc:
            raise TikTokAdsApiError("TikTok Ads authorization returned an invalid JSON response.") from exc
        if str(payload.get("code")) != "0":
            raise TikTokAdsApiError(f"TikTok Ads authorization error {payload.get('code')}: {payload.get('message') or 'Unknown error'}")
        data = payload.get("data")
        if not isinstance(data, dict) or not str(data.get("access_token") or "").strip():
            raise TikTokAdsApiError("TikTok Ads authorization did not return an access token.")
        return data

    @staticmethod
    def _message(response: httpx.Response) -> str:
        try:
            payload = response.json()
            if isinstance(payload, dict):
                return str(payload.get("message") or payload.get("msg") or response.text)
        except ValueError:
            pass
        return response.text[:1000]

    def _base_params(self, date_from: date, date_to: date) -> dict[str, Any]:
        return {
            "advertiser_id": self.advertiser_id,
            "report_type": "BASIC",
            "data_level": "AUCTION_CAMPAIGN",
            "dimensions": json.dumps(["campaign_id", "stat_time_day"]),
            "metrics": json.dumps(self.metrics),
            "start_date": date_from.isoformat(),
            "end_date": date_to.isoformat(),
            "page_size": self.page_size,
        }

    def _fetch_window(self, client: httpx.Client, date_from: date, date_to: date) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        page = 1
        while True:
            payload = self._request(client, {**self._base_params(date_from, date_to), "page": page})
            data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
            report_rows = data.get("list") or []
            if not isinstance(report_rows, list):
                raise TikTokAdsApiError("TikTok Ads API report data is not a list.")
            rows.extend(self._normalise_row(row, date_from) for row in report_rows if isinstance(row, dict))
            page_info = data.get("page_info") or data.get("pageInfo") or {}
            total_pages = self._positive_int(page_info.get("total_page") or page_info.get("totalPage"), 1)
            if page >= total_pages or not report_rows:
                return rows
            page += 1

    @staticmethod
    def _normalise_row(row: dict[str, Any], fallback_date: date) -> dict[str, Any]:
        dimensions = row.get("dimensions") if isinstance(row.get("dimensions"), dict) else {}
        metrics = row.get("metrics") if isinstance(row.get("metrics"), dict) else {}

        def value(*keys: str) -> Any:
            for key in keys:
                if key in metrics:
                    return metrics[key]
                if key in dimensions:
                    return dimensions[key]
                if key in row:
                    return row[key]
            return None

        purchases = value("onsite_total_purchase", "conversion", "total_purchase")
        purchase_value = value("onsite_total_purchase_value_day29", "conversion_value", "total_purchase_value")
        return {
            "date": value("stat_time_day") or fallback_date.isoformat(),
            "campaign_id": value("campaign_id"),
            "campaign_name": value("campaign_name") or "Unknown campaign",
            "campaign_type": value("objective_type"),
            "cost": value("spend"),
            "clicks": value("clicks"),
            "impressions": value("impressions"),
            "conversions": purchases,
            "conversion_value": purchase_value,
            "purchases": purchases,
            "purchase_value": purchase_value,
            "cpc": value("cpc"),
            "cpm": value("cpm"),
            "ctr": value("ctr"),
            "raw": row,
        }

    def fetch_campaign_metrics(self, date_from: date, date_to: date) -> list[dict[str, Any]]:
        if not self.access_token or not self.advertiser_id:
            raise ValueError("TikTok Ads access_token and advertiser_id are required.")
        if self.currency != "EUR":
            raise ValueError("TikTok Ads currency must be EUR before its spend can be included in the EUR ad spend total.")

        rows: list[dict[str, Any]] = []
        with httpx.Client(timeout=self.timeout) as client:
            for window_from, window_to in self._date_windows(date_from, date_to):
                rows.extend(self._fetch_window(client, window_from, window_to))
        return rows
