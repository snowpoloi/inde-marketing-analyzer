from datetime import date, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from google.analytics.data_v1beta.types import (
    DimensionValue,
    MetricValue,
    PropertyQuota,
    QuotaStatus,
    Row,
    RunReportResponse,
)
from sqlalchemy import select

from app.api.deps import get_current_user
from app.api.routes import dashboard
from app.connectors import ga4
from app.connectors.ga4 import FUNNEL_EVENTS, GA4Connector, normalize_landing_page
from app.db.session import get_db
from app.models import GA4DailyMetric, GA4FunnelDailyMetric, GA4LandingPageDailyMetric, IntegrationSetting
from app.services.import_service import import_ga4_funnel_rows, import_ga4_landing_page_rows, import_ga4_rows
from app.services.sync_service import ga4_sync_window, run_provider_sync

DAY = date(2031, 3, 12)
DAYS = [DAY - timedelta(days=2), DAY - timedelta(days=1), DAY]
WINDOW = {"date_from": "2031-03-10", "date_to": "2031-03-12"}


class FakeDataClient:
    def __init__(self, *pages):
        self.pages = list(pages)
        self.requests = []

    def run_report(self, request):
        self.requests.append(request)
        return self.pages.pop(0)


def page(rows, total, tokens=None):
    response = RunReportResponse(
        rows=[
            Row(dimension_values=[DimensionValue(value=value) for value in dimensions],
                metric_values=[MetricValue(value=str(value)) for value in metrics])
            for dimensions, metrics in rows
        ],
        row_count=total,
    )
    if tokens is not None:
        response.property_quota = PropertyQuota(
            tokens_per_day=QuotaStatus(consumed=tokens, remaining=199_000),
            tokens_per_hour=QuotaStatus(consumed=tokens, remaining=39_000),
        )
    return response


def connector_with(*pages):
    connector = GA4Connector({"property_id": "123456"})
    connector._data_client = FakeDataClient(*pages)
    return connector


def dashboard_app(db, user=None):
    application = FastAPI()
    application.include_router(dashboard.router, prefix="/api")
    application.dependency_overrides[get_db] = lambda: db
    if user is not None:
        application.dependency_overrides[get_current_user] = lambda: user
    return application


# ------------------------------------------------------------------ connector


def test_funnel_report_filters_funnel_events_and_reads_every_page(monkeypatch):
    monkeypatch.setattr(ga4, "PAGE_SIZE", 2)
    connector = connector_with(
        page([(["20310310", "session_start", "mobile", "Paid Social"], [120, 100]),
              (["20310310", "add_to_cart", "mobile", "Paid Social"], [9, 7])], total=3, tokens=6),
        page([(["20310310", "purchase", "desktop", "Organic Search"], [2, 2])], total=3, tokens=4),
    )
    rows = connector.fetch_funnel_events(DAYS[0], DAY)
    assert len(rows) == 3
    assert connector.quota == {"requests": 2, "tokens_used": 10, "tokens_per_day_remaining": 199_000,
                               "tokens_per_hour_remaining": 39_000}
    assert rows[-1] == {"date": "20310310", "event_name": "purchase", "device_category": "desktop",
                        "channel_group": "Organic Search", "event_count": 2, "users": 2}
    first, second = connector._data_client.requests
    dimensions = ["date", "eventName", "deviceCategory", "sessionDefaultChannelGroup"]
    assert first.property == "properties/123456"
    assert [dimension.name for dimension in first.dimensions] == dimensions
    assert [metric.name for metric in first.metrics] == ["eventCount", "totalUsers"]
    assert (first.date_ranges[0].start_date, first.date_ranges[0].end_date) == ("2031-03-10", "2031-03-12")
    in_list = first.dimension_filter.filter.in_list_filter
    assert first.dimension_filter.filter.field_name == "eventName"
    assert list(in_list.values) == list(FUNNEL_EVENTS) and in_list.case_sensitive
    assert [order.dimension.dimension_name for order in first.order_bys] == dimensions
    assert (first.offset, second.offset) == (0, 2)
    assert first.return_property_quota


def test_landing_pages_merge_click_ids_and_keep_the_top_rows_per_day():
    connector = connector_with(page([
        (["20310311", "/el/sofas?fbclid=AAA&utm_source=fb", "Paid Social"], [3, 2, 1, 0, "0"]),
        (["20310311", "/el/sofas?fbclid=BBB&utm_source=fb", "Paid Social"], [2, 2, 1, 1, "350.50"]),
        (["20310311", "/el/beds", "Organic Search"], [4, 3, 0, 0, "0"]),
        (["20310311", "/el/lamps", "Direct"], [1, 1, 0, 0, "0"]),
        (["20310312", "/?gclid=CCC", "Paid Search"], [6, 4, 2, 1, "99.90"]),
    ], total=5))
    rows = connector.fetch_landing_pages(DAYS[1], DAY, per_day=2)
    assert [(row["date"], row["landing_page"], row["channel_group"], row["sessions"]) for row in rows] == [
        ("20310311", "/el/sofas?utm_source=fb", "Paid Social", 5),
        ("20310311", "/el/beds", "Organic Search", 4),
        ("20310312", "/", "Paid Search", 6),
    ]
    assert (rows[0]["engaged_sessions"], rows[0]["add_to_carts"], rows[0]["purchases"]) == (4, 2, 1)
    assert rows[0]["purchase_revenue"] == Decimal("350.50")
    request = connector._data_client.requests[0]
    assert [dimension.name for dimension in request.dimensions] == [
        "date", "landingPagePlusQueryString", "sessionDefaultChannelGroup"]
    assert [metric.name for metric in request.metrics] == [
        "sessions", "engagedSessions", "addToCarts", "ecommercePurchases", "purchaseRevenue"]


@pytest.mark.parametrize("raw,expected", [
    ("/el/sofas?fbclid=AbC&utm_source=facebook&utm_content=video", "/el/sofas?utm_source=facebook&utm_content=video"),
    ("/?gclid=x&gad_source=1&gbraid=y", "/"),
    ("/index.php?route=product/product&product_id=42&srsltid=z", "/index.php?route=product/product&product_id=42"),
    ("/index.php?route=account/reset&email=a%40example.com&code=s3cret", "/index.php?route=account/reset"),
    ("/p?FBCLID=1&x=2", "/p?x=2"),
    ("/p?a=1&&b=2", "/p?a=1&b=2"),
    ("", "(not set)"),
    ("(not set)", "(not set)"),
])
def test_landing_pages_drop_click_ids_and_sensitive_parameters(raw, expected):
    assert normalize_landing_page(raw) == expected


def test_landing_pages_are_cut_to_the_stored_length():
    assert len(normalize_landing_page("/" + "a" * 5000)) == ga4.LANDING_PAGE_MAX_LENGTH


def test_daily_metrics_keep_their_stored_row_shape():
    connector = connector_with(page([(["20310312", "Paid Social", "facebook / cpc"], [10, 8, 1, "120.00", 1])], total=1))
    assert connector.fetch_daily_metrics(DAY, DAY) == [{
        "date": "20310312", "channel_group": "Paid Social", "source_medium": "facebook / cpc", "sessions": "10",
        "users": "8", "purchases": "1", "purchase_revenue": "120.00", "conversions": "1",
    }]


def test_reports_stop_at_the_row_cap(monkeypatch):
    monkeypatch.setattr(ga4, "PAGE_SIZE", 1)
    monkeypatch.setattr(ga4, "MAX_REPORT_ROWS", 2)
    row = (["20310312", "Direct", "(direct) / (none)"], [1, 1, 0, "0", 0])
    connector = connector_with(page([row], total=5), page([row], total=5))
    with pytest.raises(RuntimeError, match="more than 2 rows"):
        connector.fetch_daily_metrics(DAY, DAY)


# ------------------------------------------------------------- import + sync


@pytest.mark.parametrize("start,expected_start", [
    (DAY, DAYS[0]), (DAYS[1], DAYS[0]), (DAY - timedelta(days=10), DAY - timedelta(days=10)),
])
def test_ga4_sync_window_covers_at_least_the_last_three_days(start, expected_start):
    assert ga4_sync_window(start, DAY) == (expected_start, DAY)


def test_ga4_resync_replaces_every_day_of_the_window(db):
    before = DAYS[0] - timedelta(days=1)
    for day in [before, *DAYS]:
        db.add(GA4DailyMetric(metric_date=day, channel_group="Unassigned", source_medium="(not set)", sessions=5,
                              users=5, purchases=1, purchase_revenue=100, raw={}))
    db.flush()
    rows = [
        {"date": "20310310", "channel_group": "Paid Social", "source_medium": "facebook / cpc", "sessions": "5",
         "users": "5", "purchases": "1", "purchase_revenue": "100"},
        {"date": "20310311", "channel_group": "Organic Search", "source_medium": "google / organic", "sessions": "5",
         "users": "5", "purchases": "1", "purchase_revenue": "100"},
    ]
    assert import_ga4_rows(db, rows, DAYS[0], DAY) == 2
    stored = db.execute(
        select(GA4DailyMetric.metric_date, GA4DailyMetric.source_medium)
        .where(GA4DailyMetric.metric_date.between(before, DAY))
        .order_by(GA4DailyMetric.metric_date)
    ).all()
    # The day before the window is untouched; the last day, now without rows, loses its stale ones.
    assert [tuple(row) for row in stored] == [(before, "(not set)"), (DAYS[0], "facebook / cpc"),
                                              (DAYS[1], "google / organic")]


def test_funnel_and_landing_imports_replace_the_window_and_merge_duplicates(db):
    db.add(GA4FunnelDailyMetric(metric_date=DAY, event_name="purchase", device_category="mobile",
                                channel_group="Direct", event_count=9, users=9))
    db.add(GA4LandingPageDailyMetric(metric_date=DAYS[0], landing_page="/old", channel_group="Direct", sessions=9))
    db.flush()
    funnel = [
        {"date": "20310312", "event_name": "purchase", "device_category": "mobile", "channel_group": "",
         "event_count": 1, "users": 1},
        {"date": "20310312", "event_name": "purchase", "device_category": "mobile", "channel_group": None,
         "event_count": 2, "users": 2},
    ]
    assert import_ga4_funnel_rows(db, funnel, DAYS[0], DAY) == 1
    stored = db.scalars(select(GA4FunnelDailyMetric).where(GA4FunnelDailyMetric.metric_date.between(DAYS[0], DAY))).all()
    assert [(row.channel_group, row.event_count, row.users) for row in stored] == [("(not set)", 2, 2)]

    pages = [
        {"date": "20310311", "landing_page": "/el/sofas", "channel_group": "Paid Social", "sessions": 2,
         "purchase_revenue": "10.5"},
        {"date": "20310311", "landing_page": "/el/sofas", "channel_group": "Paid Social", "sessions": 3,
         "purchases": 1, "purchase_revenue": Decimal("4.5")},
    ]
    assert import_ga4_landing_page_rows(db, pages, DAYS[0], DAY) == 1
    stored_pages = db.scalars(
        select(GA4LandingPageDailyMetric).where(GA4LandingPageDailyMetric.metric_date.between(DAYS[0], DAY))
    ).all()
    assert [(row.landing_page, row.sessions, row.purchases, row.purchase_revenue) for row in stored_pages] == [
        ("/el/sofas", 5, 1, Decimal("15.0000"))]


def enable_ga4(db):
    setting = db.scalar(select(IntegrationSetting).where(IntegrationSetting.provider == "ga4"))
    if setting is None:
        setting = IntegrationSetting(provider="ga4", display_name="GA4")
        db.add(setting)
    setting.is_enabled = True
    setting.config = {"property_id": "123456"}
    db.commit()


def test_ga4_sync_rereads_three_days_and_keeps_a_failed_report_visible(db, monkeypatch):
    enable_ga4(db)
    db.add(GA4LandingPageDailyMetric(metric_date=DAYS[1], landing_page="/kept", channel_group="Direct", sessions=4))
    db.commit()
    calls = []

    def daily(self, date_from, date_to):
        calls.append(("daily", date_from, date_to))
        return [{"date": "20310311", "channel_group": "Paid Social", "source_medium": "facebook / cpc",
                 "sessions": "3", "users": "3", "purchases": "1", "purchase_revenue": "80"}]

    def funnel(self, date_from, date_to):
        calls.append(("funnel", date_from, date_to))
        return [{"date": "20310311", "event_name": "session_start", "device_category": "mobile",
                 "channel_group": "Paid Social", "event_count": 3, "users": 3}]

    def landing(self, date_from, date_to):
        calls.append(("landing", date_from, date_to))
        raise RuntimeError("Quota exhausted for access_token=abc123")

    monkeypatch.setattr(GA4Connector, "fetch_daily_metrics", daily)
    monkeypatch.setattr(GA4Connector, "fetch_funnel_events", funnel)
    monkeypatch.setattr(GA4Connector, "fetch_landing_pages", landing)

    run = run_provider_sync(db, "ga4", DAY, DAY, sync_type="scheduled")

    assert run.status == "success"
    assert (run.date_from, run.date_to) == (DAYS[0], DAY)
    assert calls == [("daily", DAYS[0], DAY), ("funnel", DAYS[0], DAY), ("landing", DAYS[0], DAY)]
    assert run.records_processed == 2
    assert run.meta["ga4_refresh_days"] == 3 and run.meta["ga4_funnel_rows"] == 1
    assert run.meta["ga4_quota"]["tokens_used"] == 0
    assert "ga4_landing_page_rows" not in run.meta
    assert "landing pages" in run.error_message
    assert "abc123" not in run.error_message and "abc123" not in run.meta["ga4_landing_page_error"]
    kept = db.scalars(select(GA4LandingPageDailyMetric.landing_page).where(
        GA4LandingPageDailyMetric.metric_date == DAYS[1])).all()
    assert kept == ["/kept"]
    funnel_rows = db.scalars(select(GA4FunnelDailyMetric).where(GA4FunnelDailyMetric.metric_date == DAYS[1])).all()
    assert [(row.event_name, row.event_count) for row in funnel_rows] == [("session_start", 3)]


# ------------------------------------------------------------------ endpoints


def test_funnel_endpoint_adds_up_steps_and_reports_missing_days(db):
    for day, event, device, channel, count, users in [
        (DAYS[0], "session_start", "mobile", "Paid Social", 100, 80),
        (DAYS[0], "add_to_cart", "mobile", "Paid Social", 12, 8),
        (DAYS[0], "purchase", "mobile", "Paid Social", 2, 2),
        (DAYS[1], "session_start", "desktop", "Organic Search", 50, 40),
        (DAYS[1], "add_to_cart", "desktop", "Organic Search", 6, 4),
        (DAYS[1], "purchase", "desktop", "Organic Search", 2, 2),
        (DAYS[1], "page_view", "desktop", "Organic Search", 500, 40),
    ]:
        db.add(GA4FunnelDailyMetric(metric_date=day, event_name=event, device_category=device, channel_group=channel,
                                    event_count=count, users=users))
    db.flush()
    application = dashboard_app(db)
    with TestClient(application) as http:
        assert http.get("/api/dashboard/funnel", params=WINDOW).status_code == 401
        application.dependency_overrides[get_current_user] = lambda: SimpleNamespace(is_admin=False)
        reversed_window = {"date_from": "2031-03-12", "date_to": "2031-03-10"}
        assert http.get("/api/dashboard/funnel", params=reversed_window).status_code == 400
        data = http.get("/api/dashboard/funnel", params=WINDOW).json()["data"]

    assert data["steps"] == list(FUNNEL_EVENTS)
    assert data["days_with_data"] == ["2031-03-10", "2031-03-11"]
    assert data["missing_days"] == ["2031-03-12"]
    totals = data["totals"]
    assert set(totals["event_count"]) == set(FUNNEL_EVENTS)
    assert totals["event_count"]["session_start"] == 150 and totals["event_count"]["view_item"] == 0
    assert totals["users"]["add_to_cart"] == 12
    assert totals["user_rate_from_start"]["purchase"] == round(4 / 120, 4)
    assert totals["user_rate_from_previous"]["view_item"] == 0.0
    assert totals["user_rate_from_previous"]["add_to_cart"] is None
    assert [group["device_category"] for group in data["by_device"]] == ["mobile", "desktop"]
    assert data["by_device"][1]["user_rate_from_start"]["add_to_cart"] == 0.1
    assert [group["channel_group"] for group in data["by_channel"]] == ["Paid Social", "Organic Search"]
    assert [day["date"] for day in data["daily"]] == ["2031-03-10", "2031-03-11"]
    assert data["daily"][1]["event_count"]["purchase"] == 2
    assert data["users_note"]


def test_landing_pages_endpoint_ranks_pages_and_reports_session_coverage(db):
    for day, landing_page, channel, sessions, engaged, adds, purchases, revenue in [
        (DAYS[0], "/el/sofas?utm_source=fb", "Paid Social", 40, 20, 4, 1, "450.00"),
        (DAYS[1], "/el/sofas?utm_source=fb", "Paid Social", 20, 10, 2, 0, "0"),
        (DAYS[1], "/el/sofas?utm_source=fb", "Organic Social", 10, 5, 0, 0, "0"),
        (DAYS[1], "/el/beds", "Organic Search", 25, 20, 5, 2, "900.00"),
    ]:
        db.add(GA4LandingPageDailyMetric(metric_date=day, landing_page=landing_page, channel_group=channel,
                                         sessions=sessions, engaged_sessions=engaged, add_to_carts=adds,
                                         purchases=purchases, purchase_revenue=Decimal(revenue)))
    for day, channel, sessions in [(DAYS[0], "Paid Social", 50), (DAYS[1], "Paid Social", 30),
                                   (DAYS[1], "Organic Search", 40), (DAYS[1], "Organic Social", 10)]:
        db.add(GA4DailyMetric(metric_date=day, channel_group=channel, source_medium="example / medium",
                              sessions=sessions, users=sessions, purchases=0, purchase_revenue=0, raw={}))
    db.flush()
    with TestClient(dashboard_app(db, SimpleNamespace(is_admin=True))) as http:
        data = http.get("/api/dashboard/landing-pages", params={**WINDOW, "limit": 2}).json()["data"]
        paid = http.get("/api/dashboard/landing-pages", params={**WINDOW, "channel_group": "Paid Social"}).json()["data"]
        assert http.get("/api/dashboard/landing-pages", params={**WINDOW, "limit": 0}).status_code == 422

    first = data["rows"][0]
    assert (first["landing_page"], first["channel_group"], first["sessions"], first["days"]) == (
        "/el/sofas?utm_source=fb", "Paid Social", 60, 2)
    assert first["engagement_rate"] == 0.5 and first["add_to_carts_per_session"] == 0.1
    assert first["purchase_revenue"] == 450.0 and first["revenue_per_session"] == 7.5
    assert [row["landing_page"] for row in data["rows"]] == ["/el/sofas?utm_source=fb", "/el/beds"]
    assert data["pages"][0]["sessions"] == 70
    assert data["pages"][0]["channel_groups"] == ["Organic Social", "Paid Social"]
    assert data["totals"]["sessions"] == 95 and data["totals"]["purchases"] == 3
    assert data["ga4_sessions"] == 130 and data["session_coverage"] == round(95 / 130, 4)
    assert data["missing_days"] == ["2031-03-12"] and data["stored_rows_per_day"] == 200
    assert paid["channel_group"] == "Paid Social"
    assert (paid["totals"]["sessions"], paid["ga4_sessions"], paid["session_coverage"]) == (60, 80, 0.75)


def test_detail_endpoints_return_empty_reports_without_data(db):
    empty_window = {"date_from": "2031-01-01", "date_to": "2031-01-02"}
    with TestClient(dashboard_app(db, SimpleNamespace(is_admin=True))) as http:
        funnel = http.get("/api/dashboard/funnel", params=empty_window).json()["data"]
        landing = http.get("/api/dashboard/landing-pages", params=empty_window).json()["data"]
    assert funnel["missing_days"] == ["2031-01-01", "2031-01-02"] and funnel["by_device"] == []
    assert funnel["totals"]["user_rate_from_start"]["purchase"] is None
    assert landing["rows"] == [] and landing["ga4_sessions"] is None and landing["session_coverage"] is None
