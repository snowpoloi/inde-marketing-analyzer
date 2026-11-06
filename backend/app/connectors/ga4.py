import base64
import json
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any
from urllib.parse import unquote_plus

from app.services.parsing import as_decimal, as_int

ANALYTICS_READONLY_SCOPE = "https://www.googleapis.com/auth/analytics.readonly"

# GA4 finishes source attribution 24-48 hours late, so every sync re-reads the last days of its window.
REFRESH_DAYS = 3
# Rows per runReport page, and a safety cap per report.
PAGE_SIZE = 10_000
MAX_REPORT_ROWS = 250_000

FUNNEL_EVENTS = (
    "session_start",
    "view_item",
    "add_to_cart",
    "view_cart",
    "begin_checkout",
    "add_shipping_info",
    "add_payment_info",
    "place_an_order",
    "purchase",
)
LANDING_PAGES_PER_DAY = 200
LANDING_PAGE_MAX_LENGTH = 1000
NOT_SET = "(not set)"

# Dropped from landing page query strings before pages are ranked and stored.
# Click IDs are unique per visit: they would split one page into thousands of one-session rows.
# The rest are personal data or secrets that must not be stored even if a link carries them.
DROPPED_QUERY_PARAMETERS = frozenset(
    {
        "fbclid", "gclid", "gbraid", "wbraid", "dclid", "gclsrc", "gad_source", "gad_campaignid", "srsltid",
        "msclkid", "ttclid", "twclid", "li_fat_id", "yclid", "epik", "igshid", "rdt_cid", "irclickid",
        "mc_eid", "_gl", "_ga", "_kx", "sccid",
        "email", "e-mail", "token", "code", "key", "password", "hash",
    }
)


def normalize_landing_page(value: Any) -> str:
    """Return the landing page path and query string without click IDs or sensitive parameters."""
    text = str(value or "").strip()
    if not text:
        return NOT_SET
    path, separator, query = text.partition("?")
    if separator:
        kept = [part for part in query.split("&") if part and _query_key(part) not in DROPPED_QUERY_PARAMETERS]
        text = f"{path}?{'&'.join(kept)}" if kept else path
    return (text or "/")[:LANDING_PAGE_MAX_LENGTH]


def _query_key(part: str) -> str:
    return unquote_plus(part.split("=", 1)[0]).strip().lower()


def _label(value: Any, max_length: int) -> str:
    return (str(value or "").strip() or NOT_SET)[:max_length]


class GA4Connector:
    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config
        self._data_client: Any = None
        # GA4 Data API quota use of this connector's requests, as reported by GA4 (returnPropertyQuota).
        self.quota: dict[str, int | None] = {
            "requests": 0,
            "tokens_used": 0,
            "tokens_per_day_remaining": None,
            "tokens_per_hour_remaining": None,
        }

    def _property_name(self) -> str:
        property_id = str(self.config.get("property_id") or self.config.get("property") or "").strip()
        if not property_id:
            raise ValueError("GA4 property_id is required.")
        if property_id.startswith("properties/"):
            return property_id
        return f"properties/{property_id}"

    def _credentials_info(self) -> dict[str, Any]:
        raw_info = self.config.get("credentials_json") or self.config.get("service_account_json")
        if not raw_info and self.config.get("credentials_json_base64"):
            raw_info = base64.b64decode(str(self.config["credentials_json_base64"])).decode("utf-8")
        if not raw_info and self.config.get("service_account_json_base64"):
            raw_info = base64.b64decode(str(self.config["service_account_json_base64"])).decode("utf-8")
        if not raw_info and self.config.get("credentials_file"):
            raw_info = Path(str(self.config["credentials_file"])).read_text(encoding="utf-8")
        if not raw_info and self.config.get("service_account_file"):
            raw_info = Path(str(self.config["service_account_file"])).read_text(encoding="utf-8")

        if isinstance(raw_info, str):
            try:
                raw_info = json.loads(raw_info)
            except json.JSONDecodeError as exc:
                raise ValueError("GA4 credentials JSON must be valid JSON.") from exc

        if not isinstance(raw_info, dict) or not raw_info:
            refresh_token = self.config.get("refresh_token")
            client_id = self.config.get("client_id")
            client_secret = self.config.get("client_secret")
            if refresh_token and client_id and client_secret:
                raw_info = {
                    "type": "authorized_user",
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "refresh_token": refresh_token,
                }
            else:
                raise ValueError("GA4 credentials JSON is required.")

        private_key = raw_info.get("private_key")
        if isinstance(private_key, str) and "\\n" in private_key:
            raw_info = {**raw_info, "private_key": private_key.replace("\\n", "\n")}
        return raw_info

    def _credentials(self) -> Any:
        try:
            from google.oauth2 import credentials as user_credentials
            from google.oauth2 import service_account
        except ImportError as exc:
            raise RuntimeError("google-auth package is not installed.") from exc

        info = self._credentials_info()
        credential_type = str(info.get("type") or "").strip()
        if credential_type == "service_account":
            return service_account.Credentials.from_service_account_info(info).with_scopes([ANALYTICS_READONLY_SCOPE])
        if credential_type == "authorized_user" or {"client_id", "client_secret", "refresh_token"}.issubset(info):
            return user_credentials.Credentials.from_authorized_user_info(info, scopes=[ANALYTICS_READONLY_SCOPE])
        raise ValueError("GA4 credentials must be a service_account JSON or authorized_user OAuth JSON.")

    def _client(self) -> Any:
        if self._data_client is None:
            try:
                from google.analytics.data_v1beta import BetaAnalyticsDataClient
            except ImportError as exc:
                raise RuntimeError("google-analytics-data package is not installed.") from exc
            self._data_client = BetaAnalyticsDataClient(credentials=self._credentials())
        return self._data_client

    def _run_report(
        self,
        date_from: date,
        date_to: date,
        dimensions: list[str],
        metrics: list[str],
        dimension_filter: Any = None,
    ) -> list[dict[str, str]]:
        """Run one GA4 report and read every page. Rows are ordered by all dimensions, so pages never overlap."""
        try:
            from google.analytics.data_v1beta.types import DateRange, Dimension, Metric, OrderBy, RunReportRequest
        except ImportError as exc:
            raise RuntimeError("google-analytics-data package is not installed.") from exc

        client = self._client()
        rows: list[dict[str, str]] = []
        while True:
            request = RunReportRequest(
                property=self._property_name(),
                dimensions=[Dimension(name=name) for name in dimensions],
                metrics=[Metric(name=name) for name in metrics],
                date_ranges=[DateRange(start_date=date_from.isoformat(), end_date=date_to.isoformat())],
                dimension_filter=dimension_filter,
                order_bys=[OrderBy(dimension=OrderBy.DimensionOrderBy(dimension_name=name)) for name in dimensions],
                limit=PAGE_SIZE,
                offset=len(rows),
                return_property_quota=True,
            )
            response = client.run_report(request)
            self._track_quota(response)
            for row in response.rows:
                values = {name: value.value for name, value in zip(dimensions, row.dimension_values)}
                values.update({name: value.value for name, value in zip(metrics, row.metric_values)})
                rows.append(values)
            if not response.rows or len(rows) >= response.row_count:
                return rows
            if len(rows) >= MAX_REPORT_ROWS:
                raise RuntimeError(f"GA4 report has more than {MAX_REPORT_ROWS} rows. Sync a shorter date range.")

    def _track_quota(self, response: Any) -> None:
        self.quota["requests"] += 1
        if "property_quota" not in response:
            return
        quota = response.property_quota
        self.quota["tokens_used"] += quota.tokens_per_day.consumed
        self.quota["tokens_per_day_remaining"] = quota.tokens_per_day.remaining
        self.quota["tokens_per_hour_remaining"] = quota.tokens_per_hour.remaining

    def fetch_daily_metrics(self, date_from: date, date_to: date) -> list[dict[str, Any]]:
        rows = self._run_report(
            date_from,
            date_to,
            ["date", "sessionDefaultChannelGroup", "sessionSourceMedium"],
            ["sessions", "totalUsers", "ecommercePurchases", "purchaseRevenue", "keyEvents"],
        )
        return [
            {
                "date": row["date"],
                "channel_group": row["sessionDefaultChannelGroup"],
                "source_medium": row["sessionSourceMedium"],
                "sessions": row["sessions"],
                "users": row["totalUsers"],
                "purchases": row["ecommercePurchases"],
                "purchase_revenue": row["purchaseRevenue"],
                "conversions": row["keyEvents"],
            }
            for row in rows
        ]

    def fetch_funnel_events(self, date_from: date, date_to: date) -> list[dict[str, Any]]:
        """Daily counts of the purchase-funnel events per device category and channel group."""
        try:
            from google.analytics.data_v1beta.types import Filter, FilterExpression
        except ImportError as exc:
            raise RuntimeError("google-analytics-data package is not installed.") from exc

        event_filter = FilterExpression(
            filter=Filter(
                field_name="eventName",
                in_list_filter=Filter.InListFilter(values=list(FUNNEL_EVENTS), case_sensitive=True),
            )
        )
        rows = self._run_report(
            date_from,
            date_to,
            ["date", "eventName", "deviceCategory", "sessionDefaultChannelGroup"],
            ["eventCount", "totalUsers"],
            dimension_filter=event_filter,
        )
        return [
            {
                "date": row["date"],
                "event_name": row["eventName"],
                "device_category": row["deviceCategory"],
                "channel_group": row["sessionDefaultChannelGroup"],
                "event_count": as_int(row["eventCount"]),
                "users": as_int(row["totalUsers"]),
            }
            for row in rows
        ]

    def fetch_landing_pages(
        self, date_from: date, date_to: date, per_day: int = LANDING_PAGES_PER_DAY
    ) -> list[dict[str, Any]]:
        """Top landing page + channel group rows per day, by sessions.

        Pages are merged after click IDs are removed from the query string, then the top `per_day`
        rows of each day are kept. All metrics are per session, so merged rows add up exactly.
        """
        rows = self._run_report(
            date_from,
            date_to,
            ["date", "landingPagePlusQueryString", "sessionDefaultChannelGroup"],
            ["sessions", "engagedSessions", "addToCarts", "ecommercePurchases", "purchaseRevenue"],
        )
        merged: dict[tuple[str, str, str], dict[str, Any]] = {}
        for row in rows:
            key = (
                row["date"],
                normalize_landing_page(row["landingPagePlusQueryString"]),
                _label(row["sessionDefaultChannelGroup"], 160),
            )
            item = merged.setdefault(
                key,
                {
                    "date": key[0],
                    "landing_page": key[1],
                    "channel_group": key[2],
                    "sessions": 0,
                    "engaged_sessions": 0,
                    "add_to_carts": 0,
                    "purchases": 0,
                    "purchase_revenue": Decimal("0"),
                },
            )
            item["sessions"] += as_int(row["sessions"])
            item["engaged_sessions"] += as_int(row["engagedSessions"])
            item["add_to_carts"] += as_int(row["addToCarts"])
            item["purchases"] += as_int(row["ecommercePurchases"])
            item["purchase_revenue"] += as_decimal(row["purchaseRevenue"])

        by_day: dict[str, list[dict[str, Any]]] = {}
        for item in merged.values():
            by_day.setdefault(item["date"], []).append(item)
        top_rows: list[dict[str, Any]] = []
        for day in sorted(by_day):
            ranked = sorted(
                by_day[day],
                key=lambda item: (-item["sessions"], -item["purchase_revenue"], item["landing_page"], item["channel_group"]),
            )
            top_rows.extend(ranked[:per_day])
        return top_rows
