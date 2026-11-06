"""Detail reports: GA4 purchase funnel, GA4 landing pages and Meta results per ad.

Ratios are null when their denominator is 0, so "no data" never reads as 0%.
"""
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.connectors.ga4 import FUNNEL_EVENTS, LANDING_PAGES_PER_DAY
from app.models import CampaignDailyMetric, GA4DailyMetric, GA4FunnelDailyMetric, GA4LandingPageDailyMetric

FUNNEL_USERS_NOTE = (
    "users is GA4 totalUsers per day, device category and channel group, added up. A person active on two days "
    "or in two channels counts twice, so user rates are approximate. event_count adds up exactly."
)
LANDING_PAGES_NOTE = (
    f"Only the top {LANDING_PAGES_PER_DAY} landing page + channel group rows of each day are stored, ranked by "
    "sessions after click IDs (fbclid, gclid, srsltid and similar) are removed from the query string. totals cover "
    "the stored rows only; session_coverage is their share of all GA4 sessions on the same days."
)
META_REACH_NOTE = (
    "Meta reach counts unique people per day, so it cannot be added across days. Daily rows have the exact reach and "
    "frequency = impressions / reach. Per-ad totals give bounds instead: the period's unique reach is at least "
    "reach_daily_max and at most reach_daily_sum, so its frequency lies between frequency_min "
    "(impressions / reach_daily_sum, the average daily frequency) and frequency_max (impressions / reach_daily_max). "
    "For a one-day window both bounds are exact."
)


def _rate(numerator: Any, denominator: Any, digits: int = 4) -> float | None:
    denominator = float(denominator or 0)
    if not denominator:
        return None
    return round(float(numerator or 0) / denominator, digits)


def _money(value: Any) -> float:
    return round(float(value or 0), 2)


def _count(value: Any) -> int | float:
    """Counts stored as numeric (e.g. Meta purchases) as int when whole, so 3 never prints as 3.0."""
    number = Decimal(str(value or 0))
    return int(number) if number == number.to_integral_value() else float(number)


def _window_days(date_from: date, date_to: date, days_with_data: set[date]) -> dict[str, list[str]]:
    window = [date_from + timedelta(days=offset) for offset in range((date_to - date_from).days + 1)]
    return {
        "days_with_data": [day.isoformat() for day in sorted(days_with_data)],
        "missing_days": [day.isoformat() for day in window if day not in days_with_data],
    }


# ---------------------------------------------------------------- GA4 funnel


def _funnel_bucket() -> dict[str, dict[str, int]]:
    return {"event_count": dict.fromkeys(FUNNEL_EVENTS, 0), "users": dict.fromkeys(FUNNEL_EVENTS, 0)}


def _with_funnel_rates(bucket: dict[str, dict[str, int]]) -> dict[str, Any]:
    users = bucket["users"]
    first = FUNNEL_EVENTS[0]
    return {
        **bucket,
        "user_rate_from_start": {step: _rate(users[step], users[first]) for step in FUNNEL_EVENTS[1:]},
        "user_rate_from_previous": {
            step: _rate(users[step], users[previous]) for previous, step in zip(FUNNEL_EVENTS, FUNNEL_EVENTS[1:])
        },
    }


def _ranked_funnel_groups(groups: dict[str, dict[str, dict[str, int]]], key_name: str) -> list[dict[str, Any]]:
    first = FUNNEL_EVENTS[0]
    ordered = sorted(groups.items(), key=lambda item: (-item[1]["users"][first], item[0]))
    return [{key_name: key, **_with_funnel_rates(bucket)} for key, bucket in ordered]


def funnel_report(db: Session, date_from: date, date_to: date) -> dict[str, Any]:
    rows = db.execute(
        select(
            GA4FunnelDailyMetric.metric_date,
            GA4FunnelDailyMetric.event_name,
            GA4FunnelDailyMetric.device_category,
            GA4FunnelDailyMetric.channel_group,
            GA4FunnelDailyMetric.event_count,
            GA4FunnelDailyMetric.users,
        ).where(
            GA4FunnelDailyMetric.metric_date.between(date_from, date_to),
            GA4FunnelDailyMetric.event_name.in_(FUNNEL_EVENTS),
        )
    ).all()
    totals = _funnel_bucket()
    by_device: dict[str, dict[str, dict[str, int]]] = {}
    by_channel: dict[str, dict[str, dict[str, int]]] = {}
    by_day: dict[date, dict[str, dict[str, int]]] = {}
    for row in rows:
        for bucket in (
            totals,
            by_device.setdefault(row.device_category, _funnel_bucket()),
            by_channel.setdefault(row.channel_group, _funnel_bucket()),
            by_day.setdefault(row.metric_date, _funnel_bucket()),
        ):
            bucket["event_count"][row.event_name] += row.event_count
            bucket["users"][row.event_name] += row.users
    return {
        "date_from": date_from.isoformat(),
        "date_to": date_to.isoformat(),
        "steps": list(FUNNEL_EVENTS),
        **_window_days(date_from, date_to, set(by_day)),
        "totals": _with_funnel_rates(totals),
        "by_device": _ranked_funnel_groups(by_device, "device_category"),
        "by_channel": _ranked_funnel_groups(by_channel, "channel_group"),
        "daily": [{"date": day.isoformat(), **bucket} for day, bucket in sorted(by_day.items())],
        "users_note": FUNNEL_USERS_NOTE,
    }


# ---------------------------------------------------------- GA4 landing pages

_LANDING_FIELDS = ("sessions", "engaged_sessions", "add_to_carts", "purchases")


def _landing_bucket() -> dict[str, Any]:
    return {**dict.fromkeys(_LANDING_FIELDS, 0), "purchase_revenue": Decimal("0")}


def _landing_output(bucket: dict[str, Any]) -> dict[str, Any]:
    sessions = bucket["sessions"]
    return {
        **{field: bucket[field] for field in _LANDING_FIELDS},
        "purchase_revenue": _money(bucket["purchase_revenue"]),
        "engagement_rate": _rate(bucket["engaged_sessions"], sessions),
        "add_to_carts_per_session": _rate(bucket["add_to_carts"], sessions),
        "purchases_per_session": _rate(bucket["purchases"], sessions),
        "revenue_per_session": _rate(bucket["purchase_revenue"], sessions, 2),
    }


def _landing_rank(bucket: dict[str, Any]) -> tuple:
    return (-bucket["sessions"], -bucket["purchase_revenue"], bucket["landing_page"], bucket.get("channel_group", ""))


def landing_page_report(
    db: Session, date_from: date, date_to: date, limit: int = 100, channel_group: str | None = None
) -> dict[str, Any]:
    query = select(
        GA4LandingPageDailyMetric.metric_date,
        GA4LandingPageDailyMetric.landing_page,
        GA4LandingPageDailyMetric.channel_group,
        GA4LandingPageDailyMetric.sessions,
        GA4LandingPageDailyMetric.engaged_sessions,
        GA4LandingPageDailyMetric.add_to_carts,
        GA4LandingPageDailyMetric.purchases,
        GA4LandingPageDailyMetric.purchase_revenue,
    ).where(GA4LandingPageDailyMetric.metric_date.between(date_from, date_to))
    if channel_group:
        query = query.where(GA4LandingPageDailyMetric.channel_group == channel_group)

    totals = _landing_bucket()
    pairs: dict[tuple[str, str], dict[str, Any]] = {}
    pages: dict[str, dict[str, Any]] = {}
    days: set[date] = set()
    for row in db.execute(query).all():
        days.add(row.metric_date)
        pair = pairs.setdefault(
            (row.landing_page, row.channel_group),
            {"landing_page": row.landing_page, "channel_group": row.channel_group, "days": set(), **_landing_bucket()},
        )
        page = pages.setdefault(
            row.landing_page, {"landing_page": row.landing_page, "channel_groups": set(), **_landing_bucket()}
        )
        pair["days"].add(row.metric_date)
        page["channel_groups"].add(row.channel_group)
        for bucket in (totals, pair, page):
            for field in _LANDING_FIELDS:
                bucket[field] += getattr(row, field)
            bucket["purchase_revenue"] += row.purchase_revenue

    ga4_sessions = None
    if days:
        sessions_query = select(func.coalesce(func.sum(GA4DailyMetric.sessions), 0)).where(
            GA4DailyMetric.metric_date.in_(days)
        )
        if channel_group:
            sessions_query = sessions_query.where(GA4DailyMetric.channel_group == channel_group)
        ga4_sessions = int(db.scalar(sessions_query) or 0)

    return {
        "date_from": date_from.isoformat(),
        "date_to": date_to.isoformat(),
        "channel_group": channel_group,
        **_window_days(date_from, date_to, days),
        "stored_rows_per_day": LANDING_PAGES_PER_DAY,
        "totals": _landing_output(totals),
        "ga4_sessions": ga4_sessions,
        "session_coverage": _rate(totals["sessions"], ga4_sessions),
        "rows": [
            {"landing_page": pair["landing_page"], "channel_group": pair["channel_group"], "days": len(pair["days"]),
             **_landing_output(pair)}
            for pair in sorted(pairs.values(), key=_landing_rank)[:limit]
        ],
        "pages": [
            {"landing_page": page["landing_page"], "channel_groups": sorted(page["channel_groups"]),
             **_landing_output(page)}
            for page in sorted(pages.values(), key=_landing_rank)[:limit]
        ],
        "note": LANDING_PAGES_NOTE,
    }


# ------------------------------------------------------------- Meta per ad

_META_COUNTS = ("impressions", "link_clicks", "landing_page_views", "add_to_cart", "initiate_checkout")


def _meta_bucket() -> dict[str, Any]:
    return {
        **dict.fromkeys(_META_COUNTS, 0),
        "spend": Decimal("0"),
        "purchases": Decimal("0"),
        "purchase_value": Decimal("0"),
    }


def _add_meta(bucket: dict[str, Any], row: Any) -> None:
    for field in _META_COUNTS:
        bucket[field] += getattr(row, field) or 0
    bucket["spend"] += row.cost or 0
    bucket["purchases"] += row.purchases or 0
    bucket["purchase_value"] += row.purchase_value or 0


def _meta_output(bucket: dict[str, Any]) -> dict[str, Any]:
    spend, impressions, link_clicks = bucket["spend"], bucket["impressions"], bucket["link_clicks"]
    return {
        "spend": _money(spend),
        **{field: bucket[field] for field in _META_COUNTS},
        "purchases": _count(bucket["purchases"]),
        "purchase_value": _money(bucket["purchase_value"]),
        "ctr": _rate(link_clicks * 100, impressions),
        "cpc": _rate(spend, link_clicks, 2),
        "cpm": _rate(spend * 1000, impressions, 2),
        "roas": _rate(bucket["purchase_value"], spend),
        "cost_per_purchase": _rate(spend, bucket["purchases"], 2),
    }


def meta_ad_report(db: Session, date_from: date, date_to: date) -> dict[str, Any]:
    rows = db.execute(
        select(
            CampaignDailyMetric.metric_date,
            CampaignDailyMetric.campaign_id,
            CampaignDailyMetric.campaign_name,
            CampaignDailyMetric.adset_id,
            CampaignDailyMetric.adset_name,
            CampaignDailyMetric.ad_id,
            CampaignDailyMetric.ad_name,
            CampaignDailyMetric.cost,
            CampaignDailyMetric.impressions,
            CampaignDailyMetric.reach,
            CampaignDailyMetric.link_clicks,
            CampaignDailyMetric.landing_page_views,
            CampaignDailyMetric.add_to_cart,
            CampaignDailyMetric.initiate_checkout,
            CampaignDailyMetric.purchases,
            CampaignDailyMetric.purchase_value,
        )
        .where(
            CampaignDailyMetric.source == "meta_ads",
            CampaignDailyMetric.metric_date.between(date_from, date_to),
        )
        .order_by(CampaignDailyMetric.metric_date)
    ).all()

    totals = _meta_bucket()
    unassigned = {"rows": 0, **_meta_bucket()}
    ads: dict[str, dict[str, Any]] = {}
    daily: dict[tuple[str, date], dict[str, Any]] = {}
    days: set[date] = set()
    for row in rows:
        days.add(row.metric_date)
        _add_meta(totals, row)
        if not row.ad_id:
            unassigned["rows"] += 1
            _add_meta(unassigned, row)
            continue
        ad = ads.setdefault(row.ad_id, {"ad_id": row.ad_id, **_meta_bucket()})
        # Rows are read oldest first, so the latest names win after a rename.
        for field in ("ad_name", "adset_id", "adset_name", "campaign_id", "campaign_name"):
            ad[field] = getattr(row, field) or ad.get(field)
        _add_meta(ad, row)
        day = daily.setdefault((row.ad_id, row.metric_date), {"reach": 0, **_meta_bucket()})
        day["reach"] += row.reach or 0
        _add_meta(day, row)

    reach_by_day: dict[str, dict[date, int]] = {}
    for (ad_id, day), values in daily.items():
        reach_by_day.setdefault(ad_id, {})[day] = values["reach"]

    ad_rows = []
    for ad in sorted(ads.values(), key=lambda item: (-item["spend"], item["ad_id"])):
        reaches = reach_by_day.get(ad["ad_id"], {})
        reach_max, reach_sum = max(reaches.values(), default=0), sum(reaches.values())
        dates = sorted(reaches)
        ad_rows.append(
            {
                **{field: ad.get(field) for field in ("ad_id", "ad_name", "adset_id", "adset_name", "campaign_id", "campaign_name")},
                "first_date": dates[0].isoformat() if dates else None,
                "last_date": dates[-1].isoformat() if dates else None,
                "days": len(dates),
                **_meta_output(ad),
                "reach_daily_max": reach_max,
                "reach_daily_sum": reach_sum,
                "frequency_min": _rate(ad["impressions"], reach_sum),
                "frequency_max": _rate(ad["impressions"], reach_max),
            }
        )

    daily_rows = [
        {
            "date": day.isoformat(),
            "ad_id": ad_id,
            "reach": values["reach"],
            "frequency": _rate(values["impressions"], values["reach"]),
            **_meta_output(values),
        }
        for (ad_id, day), values in sorted(daily.items(), key=lambda item: (item[0][1], -item[1]["spend"], item[0][0]))
    ]

    return {
        "date_from": date_from.isoformat(),
        "date_to": date_to.isoformat(),
        **_window_days(date_from, date_to, days),
        "totals": _meta_output(totals),
        "ads": ad_rows,
        "daily": daily_rows,
        "unassigned": {"rows": unassigned["rows"], **_meta_output(unassigned)} if unassigned["rows"] else None,
        "reach_note": META_REACH_NOTE,
    }
