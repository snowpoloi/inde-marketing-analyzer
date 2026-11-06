from collections.abc import Iterator
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

# Detail reports keep the costliest rows of each day (ties: more impressions first), one query per day.
SEARCH_TERMS_PER_DAY = 500
PRODUCTS_PER_DAY = 2000
# search_term_view covers these campaign types. It has no Performance Max data:
# Performance Max terms come from campaign_search_term_view (Google Ads API v21+).
SEARCH_TERM_CAMPAIGN_TYPES = ("SEARCH", "SHOPPING")
PERFORMANCE_MAX = "PERFORMANCE_MAX"
CUSTOM_LABELS = range(5)

_METRICS = """
              metrics.impressions,
              metrics.clicks,
              metrics.cost_micros,
              metrics.conversions,
              metrics.conversions_value"""
_CAMPAIGN = """
              segments.date,
              campaign.id,
              campaign.name,
              campaign.advertising_channel_type,"""
_COSTLIEST_FIRST = "ORDER BY metrics.cost_micros DESC, metrics.impressions DESC"


def _one_day(day: date) -> str:
    return f"segments.date BETWEEN '{day.isoformat()}' AND '{day.isoformat()}'"


def search_terms_query(day: date, limit: int = SEARCH_TERMS_PER_DAY) -> str:
    """Search and Shopping search terms of one day, per ad group and match type."""
    campaign_types = ", ".join(f"'{value}'" for value in SEARCH_TERM_CAMPAIGN_TYPES)
    return f"""
            SELECT{_CAMPAIGN}
              ad_group.id,
              ad_group.name,
              search_term_view.search_term,
              search_term_view.status,
              segments.search_term_match_type,{_METRICS}
            FROM search_term_view
            WHERE {_one_day(day)}
              AND campaign.advertising_channel_type IN ({campaign_types})
            {_COSTLIEST_FIRST}
            LIMIT {int(limit)}
        """


def pmax_search_terms_query(day: date, limit: int = SEARCH_TERMS_PER_DAY) -> str:
    """Performance Max search terms of one day, per campaign. No keyword segments: they drop Performance Max rows."""
    return f"""
            SELECT{_CAMPAIGN}
              campaign_search_term_view.search_term,
              segments.search_term_match_type,{_METRICS}
            FROM campaign_search_term_view
            WHERE {_one_day(day)}
              AND campaign.advertising_channel_type = '{PERFORMANCE_MAX}'
            {_COSTLIEST_FIRST}
            LIMIT {int(limit)}
        """


def products_query(day: date, limit: int = PRODUCTS_PER_DAY) -> str:
    """Shopping and Performance Max results per product and campaign for one day."""
    labels = "".join(f"\n              segments.product_custom_attribute{index}," for index in CUSTOM_LABELS)
    return f"""
            SELECT{_CAMPAIGN}
              segments.product_item_id,
              segments.product_title,
              segments.product_brand,{labels}{_METRICS}
            FROM shopping_performance_view
            WHERE {_one_day(day)}
            ORDER BY metrics.cost_micros DESC, metrics.clicks DESC, metrics.impressions DESC
            LIMIT {int(limit)}
        """


def asset_groups_query(date_from: date, date_to: date) -> str:
    """Performance Max results per asset group and day."""
    return f"""
            SELECT
              segments.date,
              campaign.id,
              campaign.name,
              asset_group.id,
              asset_group.name,
              asset_group.status,{_METRICS}
            FROM asset_group
            WHERE segments.date BETWEEN '{date_from.isoformat()}' AND '{date_to.isoformat()}'
        """


def _days(date_from: date, date_to: date) -> Iterator[date]:
    day = date_from
    while day <= date_to:
        yield day
        day += timedelta(days=1)


def _money(micros: Any) -> Decimal:
    return Decimal(int(micros or 0)) / Decimal(1_000_000)


def _enum(value: Any) -> str | None:
    name = getattr(value, "name", None)
    return None if not name or name == "UNSPECIFIED" else str(name)


def _text(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _metrics(row: Any) -> dict[str, Any]:
    metrics = row.metrics
    return {
        "impressions": int(metrics.impressions or 0),
        "clicks": int(metrics.clicks or 0),
        "cost": _money(metrics.cost_micros),
        "conversions": Decimal(str(metrics.conversions or 0)),
        "conversion_value": Decimal(str(metrics.conversions_value or 0)),
    }


def _campaign(row: Any) -> dict[str, Any]:
    return {
        "date": str(row.segments.date),
        "campaign_id": str(row.campaign.id),
        "campaign_name": row.campaign.name,
        "campaign_type": _enum(row.campaign.advertising_channel_type),
    }


class GoogleAdsConnector:
    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config
        self._cached_service: tuple[Any, str] | None = None
        # GoogleAdsService search_stream calls; each counts as one operation of the daily API quota.
        self.requests = 0

    def _service(self):
        if self._cached_service is not None:
            return self._cached_service
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
        self._cached_service = (service, customer_id)
        return self._cached_service

    def _stream(self, query: str) -> Iterator[Any]:
        """Run one read-only GAQL query and yield its rows."""
        service, customer_id = self._service()
        self.requests += 1
        for batch in service.search_stream(customer_id=customer_id, query=query):
            yield from batch.results

    def fetch_campaign_metrics(self, date_from: date, date_to: date) -> list[dict[str, Any]]:
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
        for row in self._stream(query):
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

    def fetch_search_terms(
        self, date_from: date, date_to: date, per_day: int = SEARCH_TERMS_PER_DAY
    ) -> list[dict[str, Any]]:
        """The costliest search terms of each day: up to `per_day` Search/Shopping rows (per ad group and
        match type) plus up to `per_day` Performance Max rows (per campaign). Two queries per day."""
        rows: list[dict[str, Any]] = []
        for day in _days(date_from, date_to):
            for row in self._stream(search_terms_query(day, per_day)):
                rows.append({
                    **_campaign(row),
                    "ad_group_id": str(row.ad_group.id or ""),
                    "ad_group_name": row.ad_group.name or None,
                    "search_term": row.search_term_view.search_term,
                    "match_type": _enum(row.segments.search_term_match_type),
                    "status": _enum(row.search_term_view.status),
                    **_metrics(row),
                })
            for row in self._stream(pmax_search_terms_query(day, per_day)):
                rows.append({
                    **_campaign(row),
                    "ad_group_id": "",
                    "ad_group_name": None,
                    "search_term": row.campaign_search_term_view.search_term,
                    "match_type": _enum(row.segments.search_term_match_type),
                    "status": None,
                    **_metrics(row),
                })
        return rows

    def fetch_products(self, date_from: date, date_to: date, per_day: int = PRODUCTS_PER_DAY) -> list[dict[str, Any]]:
        """The costliest product + campaign rows of each day (Shopping and Performance Max). One query per day."""
        rows: list[dict[str, Any]] = []
        for day in _days(date_from, date_to):
            for row in self._stream(products_query(day, per_day)):
                segments = row.segments
                rows.append({
                    **_campaign(row),
                    "item_id": segments.product_item_id,
                    "title": _text(segments.product_title),
                    "brand": _text(segments.product_brand),
                    **{f"custom_label_{index}": _text(getattr(segments, f"product_custom_attribute{index}"))
                       for index in CUSTOM_LABELS},
                    **_metrics(row),
                })
        return rows

    def fetch_asset_groups(self, date_from: date, date_to: date) -> list[dict[str, Any]]:
        """Performance Max asset groups per day. One query for the whole window."""
        return [
            {
                "date": str(row.segments.date),
                "campaign_id": str(row.campaign.id),
                "campaign_name": row.campaign.name,
                "asset_group_id": str(row.asset_group.id),
                "asset_group_name": row.asset_group.name,
                "asset_group_status": _enum(row.asset_group.status),
                **_metrics(row),
            }
            for row in self._stream(asset_groups_query(date_from, date_to))
        ]

    def fetch_changes(self, date_from: date, date_to: date) -> list[dict[str, Any]]:
        from datetime import datetime
        from zoneinfo import ZoneInfo

        today = datetime.now(ZoneInfo("Europe/Athens")).date()
        if date_from < today - timedelta(days=28):
            raise ValueError("Google change events older than 28 days require a Change History export.")
        account_timezone = None
        for row in self._stream("SELECT customer.time_zone FROM customer LIMIT 1"):
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
            for row in self._stream(query):
                daily.append({**type(row.change_event).to_dict(row.change_event, use_integers_for_enums=False),
                              "account_time_zone": account_timezone})
            if len(daily) >= 10000:
                raise ValueError(f"Change-event limit reached on {day}; export required, history is incomplete.")
            rows.extend(daily)
            day += timedelta(days=1)
        return rows
