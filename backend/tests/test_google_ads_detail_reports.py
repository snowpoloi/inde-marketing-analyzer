import hashlib
import importlib
import re
from datetime import date, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from google.ads.googleads.client import _DEFAULT_VERSION
from sqlalchemy import inspect, select

from app.api import deps
from app.api.deps import get_current_user
from app.api.routes import dashboard
from app.connectors import google_ads
from app.connectors.google_ads import GoogleAdsConnector
from app.db.session import get_db
from app.models import (
    Base,
    CampaignDailyMetric,
    GoogleAdsAssetGroupDailyMetric,
    GoogleAdsProductDailyMetric,
    GoogleAdsSearchTermDailyMetric,
    IntegrationSetting,
    ProductCatalog,
)
from app.services.google_ads_reports import import_product_rows, import_search_term_rows
from app.services.sync_service import run_provider_sync

GoogleAdsRow = importlib.import_module(
    f"google.ads.googleads.{_DEFAULT_VERSION}.services.types.google_ads_service").GoogleAdsRow

DAY = date(2031, 3, 12)
DAYS = [DAY - timedelta(days=2), DAY - timedelta(days=1), DAY]
WINDOW = {"date_from": "2031-03-10", "date_to": "2031-03-12"}
QUERIES = {
    "search_term_view": google_ads.search_terms_query(DAY),
    "campaign_search_term_view": google_ads.pmax_search_terms_query(DAY),
    "shopping_performance_view": google_ads.products_query(DAY),
    "asset_group": google_ads.asset_groups_query(DAYS[0], DAY),
}


def ads_row(**values):
    """A real GoogleAdsRow of the library's default API version; keys are field paths with "__" for "."."""
    row = GoogleAdsRow()
    for path, value in values.items():
        *parents, leaf = path.split("__")
        target = row
        for part in parents:
            target = getattr(target, part)
        setattr(target, leaf, value)
    return row


class FakeService:
    def __init__(self, respond):
        self.respond = respond
        self.queries = []

    def search_stream(self, customer_id, query):
        self.queries.append((customer_id, query))
        return [SimpleNamespace(results=self.respond(query))]


def connector_with(respond):
    connector = GoogleAdsConnector({})
    connector._cached_service = (FakeService(respond), "1112223334")
    return connector


def dashboard_app(db, user=None):
    application = FastAPI()
    application.include_router(dashboard.router, prefix="/api")
    application.dependency_overrides[get_db] = lambda: db
    if user is not None:
        application.dependency_overrides[get_current_user] = lambda: user
    return application


def metrics(impressions=0, clicks=0, cost="0", conversions="0", value="0"):
    return {"impressions": impressions, "clicks": clicks, "cost": Decimal(cost), "conversions": Decimal(conversions),
            "conversion_value": Decimal(value)}


# ------------------------------------------------------------------ connector


@pytest.mark.parametrize("resource", QUERIES)
def test_every_selected_field_exists_in_the_default_api_version(resource):
    query = QUERIES[resource]
    assert re.search(r"FROM (\w+)", query).group(1) == resource
    fields = [field.strip() for field in re.search(r"SELECT(.*?)FROM", query, re.S).group(1).split(",")]
    row = GoogleAdsRow()
    for field in fields:
        target = row
        for part in field.split("."):
            target = getattr(target, part)  # AttributeError if the field does not exist
    assert "metrics.cost_micros" in fields and "segments.date" in fields


def test_search_terms_read_search_and_pmax_terms_per_day_with_the_daily_limit():
    def respond(query):
        if "FROM search_term_view" in query:
            return [ads_row(segments__date="2031-03-11", campaign__id=11, campaign__name="Search Generic",
                            campaign__advertising_channel_type="SEARCH", ad_group__id=21, ad_group__name="Sofas",
                            search_term_view__search_term="corner sofa grey", search_term_view__status="NONE",
                            segments__search_term_match_type="PHRASE", metrics__impressions=40, metrics__clicks=4,
                            metrics__cost_micros=2_345_678, metrics__conversions=0.5,
                            metrics__conversions_value=150.25)]
        return [ads_row(segments__date="2031-03-11", campaign__id=12, campaign__name="PMax All",
                        campaign__advertising_channel_type="PERFORMANCE_MAX",
                        campaign_search_term_view__search_term="bed frame",
                        segments__search_term_match_type="PERFORMANCE_MAX", metrics__impressions=90,
                        metrics__clicks=3, metrics__cost_micros=900_000)]

    connector = connector_with(respond)
    rows = connector.fetch_search_terms(DAYS[1], DAY, per_day=7)

    service = connector._cached_service[0]
    assert connector.requests == 4 and len(service.queries) == 4
    assert {customer_id for customer_id, _ in service.queries} == {"1112223334"}
    first_day, pmax_first_day, second_day, _ = (query for _, query in service.queries)
    assert "FROM search_term_view" in first_day and "BETWEEN '2031-03-11' AND '2031-03-11'" in first_day
    assert "IN ('SEARCH', 'SHOPPING')" in first_day and "LIMIT 7" in first_day
    assert "ORDER BY metrics.cost_micros DESC" in first_day
    assert "FROM campaign_search_term_view" in pmax_first_day and "'PERFORMANCE_MAX'" in pmax_first_day
    assert "segments.keyword" not in pmax_first_day
    assert "BETWEEN '2031-03-12' AND '2031-03-12'" in second_day
    assert rows[0] == {
        "date": "2031-03-11", "campaign_id": "11", "campaign_name": "Search Generic", "campaign_type": "SEARCH",
        "ad_group_id": "21", "ad_group_name": "Sofas", "search_term": "corner sofa grey", "match_type": "PHRASE",
        "status": "NONE", "impressions": 40, "clicks": 4, "cost": Decimal("2.345678"),
        "conversions": Decimal("0.5"), "conversion_value": Decimal("150.25"),
    }
    pmax = rows[1]
    assert (pmax["campaign_type"], pmax["ad_group_id"], pmax["ad_group_name"], pmax["status"]) == (
        "PERFORMANCE_MAX", "", None, None)
    assert (pmax["match_type"], pmax["cost"], pmax["conversions"]) == ("PERFORMANCE_MAX", Decimal("0.9"), Decimal("0"))


def test_products_and_asset_groups_are_parsed():
    def respond(query):
        if "FROM shopping_performance_view" in query:
            return [ads_row(segments__date="2031-03-12", campaign__id=31, campaign__name="Shopping",
                            campaign__advertising_channel_type="SHOPPING", segments__product_item_id="test-sku-1",
                            segments__product_title="Test Chair", segments__product_brand="Testbrand",
                            segments__product_custom_attribute0="bestseller",
                            segments__product_custom_attribute3="autumn", metrics__impressions=500,
                            metrics__clicks=12, metrics__cost_micros=3_000_000, metrics__conversions=1,
                            metrics__conversions_value=89.9)]
        return [ads_row(segments__date="2031-03-11", campaign__id=12, campaign__name="PMax All",
                        asset_group__id=41, asset_group__name="Beds", asset_group__status="ENABLED",
                        metrics__impressions=1000, metrics__clicks=20, metrics__cost_micros=8_500_000)]

    connector = connector_with(respond)
    [product] = connector.fetch_products(DAY, DAY, per_day=3)
    assert product["item_id"] == "test-sku-1" and product["title"] == "Test Chair" and product["brand"] == "Testbrand"
    assert [product[f"custom_label_{index}"] for index in range(5)] == ["bestseller", None, None, "autumn", None]
    assert (product["campaign_type"], product["cost"], product["conversion_value"]) == (
        "SHOPPING", Decimal("3"), Decimal("89.9"))
    assert "LIMIT 3" in connector._cached_service[0].queries[0][1]
    [group] = connector.fetch_asset_groups(DAYS[0], DAY)
    assert group == {"date": "2031-03-11", "campaign_id": "12", "campaign_name": "PMax All", "asset_group_id": "41",
                     "asset_group_name": "Beds", "asset_group_status": "ENABLED", **metrics(1000, 20, "8.5")}
    assert connector.requests == 2
    assert "BETWEEN '2031-03-10' AND '2031-03-12'" in connector._cached_service[0].queries[1][1]


# ------------------------------------------------------------- import + sync


def term(day, campaign_id, term_text, cost, conversions="0", ad_group_id="21", match_type="BROAD", status="NONE",
         campaign_type="SEARCH", campaign_name=None, clicks=1, impressions=10, value="0"):
    return {"date": day.isoformat(), "campaign_id": campaign_id, "campaign_name": campaign_name or f"Campaign {campaign_id}",
            "campaign_type": campaign_type, "ad_group_id": ad_group_id, "ad_group_name": "Group", "search_term": term_text,
            "match_type": match_type, "status": status,
            **metrics(impressions, clicks, cost, conversions, value)}


def test_search_term_import_replaces_the_window_and_merges_duplicates(db):
    before = DAYS[0] - timedelta(days=1)
    for day in (before, DAY):
        db.add(GoogleAdsSearchTermDailyMetric(metric_date=day, campaign_id="11", campaign_name="Old", ad_group_id="21",
                                              search_term="stale term", match_type="BROAD", cost=Decimal("1")))
    db.flush()
    long_term = "x" * 600
    rows = [
        term(DAYS[0], "11", "corner sofa", "2.5"),
        term(DAYS[0], "11", "corner sofa", "1.5", conversions="1"),
        term(DAYS[1], "11", long_term, "1"),
        term(DAYS[1], "11", "  ", "9"),
    ]
    assert import_search_term_rows(db, rows, DAYS[0], DAY) == 2
    stored = db.execute(
        select(GoogleAdsSearchTermDailyMetric.metric_date, GoogleAdsSearchTermDailyMetric.search_term,
               GoogleAdsSearchTermDailyMetric.cost, GoogleAdsSearchTermDailyMetric.conversions)
        .where(GoogleAdsSearchTermDailyMetric.metric_date.between(before, DAY))
        .order_by(GoogleAdsSearchTermDailyMetric.metric_date)
    ).all()
    # The day before the window is untouched; the window's last day, now without rows, loses its stale one.
    assert [tuple(row) for row in stored] == [
        (before, "stale term", Decimal("1.0000"), Decimal("0.0000")),
        (DAYS[0], "corner sofa", Decimal("4.0000"), Decimal("1.0000")),
        (DAYS[1], "x" * 500, Decimal("1.0000"), Decimal("0.0000")),
    ]


def test_product_import_keeps_the_attributes_of_the_largest_row(db):
    rows = [
        {"date": "2031-03-12", "campaign_id": "31", "campaign_name": "Shopping", "campaign_type": "SHOPPING",
         "item_id": "test-sku-1", "title": "Old title", "custom_label_0": "old", **metrics(10, 1, "0.5")},
        {"date": "2031-03-12", "campaign_id": "31", "campaign_name": "Shopping", "campaign_type": "SHOPPING",
         "item_id": "test-sku-1", "title": "New title", "custom_label_0": "new", **metrics(90, 2, "1.5", "1", "50")},
        {"date": "2031-03-12", "campaign_id": "31", "item_id": "", **metrics(5, 1, "9")},
    ]
    assert import_product_rows(db, rows, DAY, DAY) == 1
    [stored] = db.scalars(select(GoogleAdsProductDailyMetric).where(GoogleAdsProductDailyMetric.metric_date == DAY)).all()
    assert (stored.title, stored.custom_label_0, stored.impressions, stored.clicks, stored.cost) == (
        "New title", "new", 100, 3, Decimal("2.0000"))


def enable_google_ads(db):
    setting = db.scalar(select(IntegrationSetting).where(IntegrationSetting.provider == "google_ads"))
    if setting is None:
        setting = IntegrationSetting(provider="google_ads", display_name="Google Ads")
        db.add(setting)
    setting.is_enabled, setting.config = True, {}
    db.commit()


def fake_google(monkeypatch, calls, fail_products=False):
    def campaigns(self, date_from, date_to):
        calls.append(("campaigns", date_from, date_to))
        return [{"date": "2031-03-12", "campaign_id": "11", "campaign_name": "Search Generic",
                 "campaign_type": "SEARCH", "cost": "10", "clicks": "5", "impressions": "100"}]

    def search_terms(self, date_from, date_to):
        calls.append(("search_terms", date_from, date_to))
        self.requests += 2
        return [term(DAY, "11", "corner sofa", "4")]

    def products(self, date_from, date_to):
        calls.append(("products", date_from, date_to))
        if fail_products:
            raise RuntimeError("Quota exhausted for access_token=abc123")
        return [{"date": "2031-03-12", "campaign_id": "31", "campaign_name": "Shopping", "campaign_type": "SHOPPING",
                 "item_id": "test-sku-1", **metrics(10, 1, "0.5")}]

    def asset_groups(self, date_from, date_to):
        calls.append(("asset_groups", date_from, date_to))
        return [{"date": "2031-03-12", "campaign_id": "12", "campaign_name": "PMax All", "asset_group_id": "41",
                 "asset_group_name": "Beds", "asset_group_status": "ENABLED", **metrics(100, 2, "3")}]

    monkeypatch.setattr(GoogleAdsConnector, "fetch_campaign_metrics", campaigns)
    monkeypatch.setattr(GoogleAdsConnector, "fetch_search_terms", search_terms)
    monkeypatch.setattr(GoogleAdsConnector, "fetch_products", products)
    monkeypatch.setattr(GoogleAdsConnector, "fetch_asset_groups", asset_groups)


def stored_detail_rows(db):
    return {
        model.__tablename__: db.scalar(select(model.campaign_id).where(model.metric_date == DAY))
        for model in (GoogleAdsSearchTermDailyMetric, GoogleAdsProductDailyMetric, GoogleAdsAssetGroupDailyMetric)
    }


def test_daily_sync_stores_the_detail_reports_and_keeps_a_failed_one_visible(db, monkeypatch):
    enable_google_ads(db)
    calls = []
    fake_google(monkeypatch, calls)
    run = run_provider_sync(db, "google_ads", DAY, DAY, sync_type="scheduled")
    assert run.status == "success" and run.error_message is None
    assert [name for name, *_ in calls] == ["campaigns", "search_terms", "products", "asset_groups"]
    assert all((date_from, date_to) == (DAY, DAY) for _, date_from, date_to in calls)
    assert run.records_processed == 4
    assert {key: run.meta[key] for key in ("google_ads_search_terms_rows", "google_ads_products_rows",
                                           "google_ads_asset_groups_rows", "google_ads_api_requests")} == {
        "google_ads_search_terms_rows": 1, "google_ads_products_rows": 1, "google_ads_asset_groups_rows": 1,
        "google_ads_api_requests": 2}
    assert stored_detail_rows(db) == {"google_ads_search_term_daily_metrics": "11",
                                      "google_ads_product_daily_metrics": "31",
                                      "google_ads_asset_group_daily_metrics": "12"}

    calls.clear()
    fake_google(monkeypatch, calls, fail_products=True)
    failed = run_provider_sync(db, "google_ads", DAY, DAY, sync_type="manual")
    assert failed.status == "success"
    assert "Google Ads products report failed" in failed.error_message
    assert "abc123" not in failed.error_message and "abc123" not in failed.meta["google_ads_products_error"]
    assert "google_ads_products_rows" not in failed.meta and failed.meta["google_ads_asset_groups_rows"] == 1
    # The failed report keeps its stored day; the others were replaced.
    assert stored_detail_rows(db)["google_ads_product_daily_metrics"] == "31"


def test_intraday_sync_reads_campaign_metrics_only(db, monkeypatch):
    enable_google_ads(db)
    calls = []
    fake_google(monkeypatch, calls)
    run = run_provider_sync(db, "google_ads", DAY, DAY, sync_type="intraday")
    assert run.status == "success" and [name for name, *_ in calls] == ["campaigns"]
    assert run.meta["google_ads_detail_reports"].startswith("skipped")
    assert set(stored_detail_rows(db).values()) == {None}


# ------------------------------------------------------------------ endpoints


def stored_term(day, campaign_id, campaign_type, search_term, cost, conversions="0", value="0", clicks=2,
                impressions=20, ad_group_id="21", match_type="BROAD", status="NONE", campaign_name=None):
    return GoogleAdsSearchTermDailyMetric(
        metric_date=day, campaign_id=campaign_id, campaign_name=campaign_name or f"Campaign {campaign_id}",
        campaign_type=campaign_type, ad_group_id=ad_group_id, ad_group_name="Group" if ad_group_id else None,
        search_term=search_term, match_type=match_type, status=status, impressions=impressions, clicks=clicks,
        cost=Decimal(cost), conversions=Decimal(conversions), conversion_value=Decimal(value))


def campaign_cost(day, campaign_id, campaign_type, cost, name=None):
    return CampaignDailyMetric(source="google_ads", metric_date=day, campaign_id=campaign_id,
                               campaign_name=name or f"Campaign {campaign_id}", campaign_type=campaign_type,
                               cost=Decimal(cost), raw={})


def test_search_terms_endpoint_totals_each_term_flags_waste_and_reports_coverage(db):
    db.add_all([
        stored_term(DAYS[0], "11", "SEARCH", "corner sofa", "10", conversions="1", value="300", status="ADDED",
                    match_type="EXACT"),
        stored_term(DAYS[1], "11", "SEARCH", "corner sofa", "6", clicks=3),
        stored_term(DAYS[1], "12", "PERFORMANCE_MAX", "corner sofa", "5", ad_group_id="", match_type="PERFORMANCE_MAX",
                    status=None, campaign_name="PMax All"),
        stored_term(DAYS[1], "11", "SEARCH", "free sofa", "8", clicks=8, impressions=40),
        stored_term(DAYS[1], "11", "SEARCH", "sofa repair", "0", clicks=0, impressions=5),
        campaign_cost(DAYS[0], "11", "SEARCH", "20"),
        campaign_cost(DAYS[1], "11", "SEARCH", "20"),
        campaign_cost(DAYS[1], "12", "PERFORMANCE_MAX", "40", name="PMax All"),
        campaign_cost(DAYS[1], "13", "DISPLAY", "99"),
        campaign_cost(DAY, "11", "SEARCH", "50"),
    ])
    db.flush()
    application = dashboard_app(db)
    with TestClient(application) as http:
        assert http.get("/api/dashboard/google-search-terms", params=WINDOW).status_code == 401
        application.dependency_overrides[get_current_user] = lambda: SimpleNamespace(is_admin=False)
        data = http.get("/api/dashboard/google-search-terms", params=WINDOW).json()["data"]
        limited = http.get("/api/dashboard/google-search-terms", params={**WINDOW, "limit": 1}).json()["data"]
        wasted = http.get("/api/dashboard/google-search-terms", params={**WINDOW, "no_conversions": True}).json()["data"]
        by_name = http.get("/api/dashboard/google-search-terms", params={**WINDOW, "campaign": "pmax all"}).json()["data"]
        by_id = http.get("/api/dashboard/google-search-terms", params={**WINDOW, "campaign": "11"}).json()["data"]
        assert http.get("/api/dashboard/google-search-terms", params={**WINDOW, "limit": 0}).status_code == 422
        reversed_window = {"date_from": "2031-03-12", "date_to": "2031-03-10"}
        assert http.get("/api/dashboard/google-search-terms", params=reversed_window).status_code == 400

    assert data["days_with_data"] == ["2031-03-10", "2031-03-11"] and data["missing_days"] == ["2031-03-12"]
    assert data["stored_rows_per_day"] == {"search_and_shopping": 500, "performance_max": 500}
    assert [item["search_term"] for item in data["terms"]] == ["corner sofa", "free sofa", "sofa repair"]
    sofa = data["terms"][0]
    assert (sofa["cost"], sofa["clicks"], sofa["conversions"], sofa["conversion_value"]) == (21.0, 7, 1, 300.0)
    assert (sofa["cost_per_conversion"], sofa["conversion_value_per_cost"], sofa["cpc"]) == (21.0, round(300 / 21, 4), 3.0)
    assert sofa["days"] == 2 and sofa["no_conversions"] is False
    assert sofa["match_types"] == ["BROAD", "EXACT", "PERFORMANCE_MAX"] and sofa["statuses"] == ["ADDED", "NONE"]
    assert sofa["campaign_types"] == ["PERFORMANCE_MAX", "SEARCH"]
    assert [(item["campaign_id"], item["cost"], item["no_conversions"]) for item in sofa["campaigns"]] == [
        ("11", 16.0, False), ("12", 5.0, True)]
    free = data["terms"][1]
    assert free["no_conversions"] is True and free["cost_per_conversion"] is None and free["ctr"] == 20.0
    assert data["terms"][2]["no_conversions"] is False and data["terms"][2]["cpc"] is None
    totals = data["totals"]
    assert (totals["terms"], totals["cost"], totals["no_conversion_terms"], totals["no_conversion_cost"]) == (
        3, 29.0, 1, 8.0)
    # Campaign cost of Search, Shopping and Performance Max campaigns on the days with stored terms.
    assert data["campaign_cost"] == 80.0 and data["cost_coverage"] == round(29 / 80, 4)
    search, pmax = data["by_campaign"]
    assert (search["campaign_id"], search["terms"], search["cost"], search["no_conversion_cost"]) == ("11", 3, 24.0, 8.0)
    assert (search["campaign_cost"], search["cost_coverage"]) == (40.0, 0.6)
    assert (pmax["campaign_id"], pmax["campaign_name"], pmax["no_conversion_cost"], pmax["cost_coverage"]) == (
        "12", "PMax All", 5.0, 0.125)
    assert [item["search_term"] for item in limited["terms"]] == ["corner sofa"] and limited["totals"]["terms"] == 3
    assert [item["search_term"] for item in wasted["terms"]] == ["free sofa"] and wasted["no_conversions_only"]
    assert [item["search_term"] for item in by_name["terms"]] == ["corner sofa"]
    assert by_name["terms"][0]["no_conversions"] is True and by_name["campaign_cost"] == 40.0
    assert by_id["totals"]["cost"] == 24.0 and by_id["campaign_cost"] == 40.0
    assert "hides search terms" in data["note"]


def test_products_endpoint_joins_the_catalog_and_reports_the_match_rate(db):
    db.add_all([
        ProductCatalog(sku="TEST-SKU-1", product_id="9001", model="TM-1", name="Test chair", brand="Testbrand",
                       price=Decimal("89.90"), quantity=4, raw={}),
        ProductCatalog(sku="TEST-SKU-2", product_id="9002", model="TM-2", name="Test table", raw={}),
        ProductCatalog(sku="TEST-SKU-3", product_id="9003", model="tm-shared", name="Test lamp", raw={}),
    ])
    for day, campaign_id, campaign_type, item_id, title, label, cost, conversions, value, impressions in [
        (DAYS[0], "31", "SHOPPING", "test-sku-1", "Old chair", "slow", "6", "1", "89.9", 300),
        (DAYS[1], "31", "SHOPPING", "test-sku-1", "Test chair", "bestseller", "4", "0", "0", 200),
        (DAYS[1], "12", "PERFORMANCE_MAX", "test-sku-1", "Test chair", "bestseller", "2", "0", "0", 100),
        (DAYS[1], "12", "PERFORMANCE_MAX", "9002", "Test table", None, "7", "0", "0", 400),
        (DAYS[1], "12", "PERFORMANCE_MAX", "TM-SHARED", "Test lamp", None, "1", "0", "0", 50),
        (DAYS[1], "31", "SHOPPING", "unknown-item", "Unknown", None, "5", "0", "0", 80),
    ]:
        db.add(GoogleAdsProductDailyMetric(
            metric_date=day, campaign_id=campaign_id, campaign_name=f"Campaign {campaign_id}",
            campaign_type=campaign_type, item_id=item_id, title=title, brand="Testbrand", custom_label_0=label,
            impressions=impressions, clicks=impressions // 50, cost=Decimal(cost), conversions=Decimal(conversions),
            conversion_value=Decimal(value)))
    db.add_all([campaign_cost(DAYS[0], "31", "SHOPPING", "10"), campaign_cost(DAYS[1], "31", "SHOPPING", "15"),
                campaign_cost(DAYS[1], "12", "PERFORMANCE_MAX", "25"), campaign_cost(DAYS[1], "11", "SEARCH", "70")])
    db.flush()
    with TestClient(dashboard_app(db, SimpleNamespace(is_admin=True))) as http:
        data = http.get("/api/dashboard/google-products", params=WINDOW).json()["data"]
        wasted = http.get("/api/dashboard/google-products", params={**WINDOW, "no_conversions": "true"}).json()["data"]
        assert http.get("/api/dashboard/google-products", params={**WINDOW, "limit": 1001}).status_code == 422

    assert [item["item_id"] for item in data["products"]] == ["test-sku-1", "9002", "unknown-item", "TM-SHARED"]
    chair = data["products"][0]
    assert (chair["title"], chair["custom_labels"], chair["days"]) == ("Test chair", {"custom_label_0": "bestseller"}, 2)
    assert (chair["cost"], chair["conversions"], chair["conversion_value_per_cost"]) == (12.0, 1, round(89.9 / 12, 4))
    assert chair["campaign_types"] == ["PERFORMANCE_MAX", "SHOPPING"] and chair["no_conversions"] is False
    assert [(item["campaign_id"], item["cost"]) for item in chair["campaigns"]] == [("31", 10.0), ("12", 2.0)]
    assert chair["catalog"]["matched_by"] == "sku" and chair["catalog"]["sku"] == "TEST-SKU-1"
    assert (chair["catalog"]["name"], chair["catalog"]["price"], chair["catalog"]["quantity"]) == ("Test chair", 89.9, 4)
    assert data["products"][1]["catalog"]["matched_by"] == "product_id"
    assert data["products"][2]["catalog"] is None and data["products"][2]["no_conversions"] is True
    assert data["products"][3]["catalog"]["matched_by"] == "model"
    match = data["catalog_match"]
    assert (match["products"], match["matched"], match["match_rate"]) == (4, 3, 0.75)
    assert match["matched_by"] == {"sku": 1, "product_id": 1, "model": 1}
    assert (match["cost"], match["matched_cost"], match["cost_match_rate"]) == (25.0, 20.0, 0.8)
    assert (data["totals"]["no_conversion_products"], data["totals"]["no_conversion_cost"]) == (3, 13.0)
    # Shopping and Performance Max campaign cost only.
    assert data["campaign_cost"] == 50.0 and data["cost_coverage"] == 0.5
    assert [row["campaign_id"] for row in data["by_campaign"]] == ["31", "12"]
    assert data["by_campaign"][0]["products"] == 2 and data["by_campaign"][0]["cost_coverage"] == 0.6
    assert [item["item_id"] for item in wasted["products"]] == ["9002", "unknown-item", "TM-SHARED"]


def test_asset_groups_endpoint_totals_each_group(db):
    for day, group_id, name, status, cost, conversions, value in [
        (DAYS[0], "41", "Beds", "ENABLED", "8", "1", "400"),
        (DAYS[1], "41", "Beds 2", "PAUSED", "4", "0", "0"),
        (DAYS[1], "42", "Sofas", "ENABLED", "6", "0", "0"),
    ]:
        db.add(GoogleAdsAssetGroupDailyMetric(
            metric_date=day, campaign_id="12", campaign_name="PMax All", asset_group_id=group_id,
            asset_group_name=name, asset_group_status=status, impressions=100, clicks=10, cost=Decimal(cost),
            conversions=Decimal(conversions), conversion_value=Decimal(value)))
    db.add_all([campaign_cost(DAYS[0], "12", "PERFORMANCE_MAX", "10"),
                campaign_cost(DAYS[1], "12", "PERFORMANCE_MAX", "14")])
    db.flush()
    with TestClient(dashboard_app(db, SimpleNamespace(is_admin=True))) as http:
        data = http.get("/api/dashboard/google-asset-groups", params=WINDOW).json()["data"]
        empty = http.get("/api/dashboard/google-asset-groups",
                         params={"date_from": "2031-01-01", "date_to": "2031-01-01"}).json()["data"]

    beds, sofas = data["asset_groups"]
    assert (beds["asset_group_name"], beds["asset_group_status"], beds["days"]) == ("Beds 2", "PAUSED", 2)
    assert (beds["first_date"], beds["last_date"], beds["cost"], beds["conversion_value_per_cost"]) == (
        "2031-03-10", "2031-03-11", 12.0, round(400 / 12, 4))
    assert sofas["cost_per_conversion"] is None
    assert data["totals"]["asset_groups"] == 2 and data["totals"]["cost"] == 18.0
    assert (data["campaign_cost"], data["cost_coverage"]) == (24.0, 0.75)
    assert [(row["date"], row["asset_group_id"]) for row in data["daily"]] == [
        ("2031-03-10", "41"), ("2031-03-11", "42"), ("2031-03-11", "41")]
    assert empty["asset_groups"] == [] and empty["campaign_cost"] is None and empty["cost_coverage"] is None


def test_empty_detail_reports(db):
    window = {"date_from": "2031-01-01", "date_to": "2031-01-02"}
    with TestClient(dashboard_app(db, SimpleNamespace(is_admin=True))) as http:
        terms = http.get("/api/dashboard/google-search-terms", params=window).json()["data"]
        products = http.get("/api/dashboard/google-products", params=window).json()["data"]
    assert terms["terms"] == [] and terms["by_campaign"] == [] and terms["missing_days"] == ["2031-01-01", "2031-01-02"]
    assert terms["totals"]["cost"] == 0.0 and terms["totals"]["ctr"] is None and terms["cost_coverage"] is None
    assert products["products"] == [] and products["catalog_match"]["match_rate"] is None


def test_new_endpoints_are_readable_with_the_advestiq_key_and_get_only(db, monkeypatch):
    key = "test-key-for-detail-reports"
    monkeypatch.setattr(deps.settings, "advestiq_api_key_sha256", hashlib.sha256(key.encode()).hexdigest())
    paths = ["/api/dashboard/google-search-terms", "/api/dashboard/google-products",
             "/api/dashboard/google-asset-groups", "/api/dashboard/merchant-issues"]
    with TestClient(dashboard_app(db)) as http:
        for path in paths:
            assert http.get(path).status_code == 401
            assert http.get(path, headers={deps.ADVESTIQ_KEY_HEADER: key}).status_code == 200
            assert http.post(path, headers={deps.ADVESTIQ_KEY_HEADER: key}).status_code == 405
    methods = {method for route in dashboard.router.routes if route.path in {path.removeprefix("/api") for path in paths}
               for method in route.methods}
    assert methods == {"GET"}


def test_detail_report_migrations_match_the_models(db):
    inspector = inspect(db.get_bind())
    for name in ("google_ads_search_term_daily_metrics", "google_ads_product_daily_metrics",
                 "google_ads_asset_group_daily_metrics", "merchant_product_statuses", "merchant_product_issues"):
        table = Base.metadata.tables[name]
        assert {column["name"] for column in inspector.get_columns(name)} == set(table.columns.keys())
        unique = {constraint["name"]: constraint["column_names"] for constraint in inspector.get_unique_constraints(name)}
        expected = {constraint.name: [column.name for column in constraint.columns]
                    for constraint in table.constraints if constraint.__class__.__name__ == "UniqueConstraint"}
        assert unique == expected
