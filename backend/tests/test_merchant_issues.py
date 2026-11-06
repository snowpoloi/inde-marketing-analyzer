from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.api.deps import get_current_user
from app.api.routes import dashboard
from app.connectors import merchant_center
from app.connectors.merchant_center import MerchantCenterConnector
from app.db.session import get_db
from app.models import IntegrationSetting, MerchantProductIssue, MerchantProductStatus
from app.services.merchant_issues import destination_status, import_product_statuses
from app.services.sync_service import run_provider_sync

DAY = date(2031, 3, 12)
FIRST = datetime(2031, 3, 11, 2, 0, tzinfo=timezone.utc)
SECOND = FIRST + timedelta(days=1)
ATHENS = ZoneInfo("Europe/Athens")
CONFIG = {"refresh_token": "test-refresh", "client_id": "test-client", "client_secret": "test-secret",
          "account_id": "123456"}


def api_product(offer_id, title, destinations=(), issues=(), feed_label="GR", language="el"):
    return {
        "name": f"accounts/123456/products/{language}~{feed_label}~{offer_id}",
        "offerId": offer_id, "feedLabel": feed_label, "contentLanguage": language,
        "productAttributes": {"title": title, "price": {"amountMicros": "99000000", "currencyCode": "EUR"}},
        "productStatus": {"destinationStatuses": list(destinations), "itemLevelIssues": list(issues)},
    }


def destination(context, approved=(), pending=(), disapproved=()):
    return {"reportingContext": context, "approvedCountries": list(approved), "pendingCountries": list(pending),
            "disapprovedCountries": list(disapproved)}


def issue(code, severity, attribute=None, context="SHOPPING_ADS", countries=("GR",)):
    return {"code": code, "severity": severity, "resolution": "MERCHANT_ACTION", "attribute": attribute,
            "reportingContext": context, "description": f"Test issue {code}", "detail": "Fix the test value.",
            "documentation": "https://support.example.test/issue", "applicableCountries": list(countries)}


def snapshot(*products):
    return [merchant_center.product_status(product) for product in products]


# ------------------------------------------------------------------ connector


def test_product_statuses_read_every_page_with_get_only(monkeypatch):
    connector = MerchantCenterConnector(CONFIG)
    calls = []
    pages = [
        {"products": [api_product("TEST-1", "Test sofa", [destination("SHOPPING_ADS", approved=["GR"])])],
         "nextPageToken": "page/2+token"},
        {"products": [api_product("TEST-2", "Test bed", issues=[issue("image_link_broken", "DISAPPROVED",
                                                                       "image_link")])]},
    ]

    def request(method, path, *, json=None, params=None):
        calls.append((method, path, json, dict(params or {})))
        return pages[len(calls) - 1]

    monkeypatch.setattr(connector, "_request", request)
    products = connector.fetch_product_statuses()
    assert [(method, path, body) for method, path, body, _ in calls] == [
        ("GET", "/products/v1/accounts/123456/products", None)] * 2
    assert calls[0][3] == {"pageSize": 1000} and calls[1][3] == {"pageSize": 1000, "pageToken": "page/2+token"}
    first, second = products
    assert first == {"offer_id": "TEST-1", "feed_label": "GR", "content_language": "el", "title": "Test sofa",
                     "destinations": [{"reporting_context": "SHOPPING_ADS", "approved_countries": ["GR"],
                                       "pending_countries": [], "disapproved_countries": []}],
                     "issues": []}
    assert second["issues"][0]["code"] == "image_link_broken" and second["issues"][0]["attribute"] == "image_link"
    assert second["destinations"] == []


def test_product_statuses_stop_at_the_page_cap(monkeypatch):
    monkeypatch.setattr(merchant_center, "MAX_PRODUCT_PAGES", 2)
    connector = MerchantCenterConnector(CONFIG)
    monkeypatch.setattr(connector, "_request", lambda *args, **kwargs: {"products": [], "nextPageToken": "again"})
    with pytest.raises(RuntimeError, match="more than 2 pages"):
        connector.fetch_product_statuses()


@pytest.mark.parametrize("countries,expected", [
    ({"approved_countries": ["GR"]}, "approved"),
    ({"approved_countries": ["GR"], "pending_countries": ["CY"]}, "approved"),
    ({"pending_countries": ["GR"]}, "pending"),
    ({"disapproved_countries": ["GR"]}, "disapproved"),
    ({"disapproved_countries": ["CY"], "approved_countries": ["GR"]}, "partly_disapproved"),
    ({}, "unknown"),
])
def test_destination_status(countries, expected):
    assert destination_status(countries) == expected


# ------------------------------------------------------------------ snapshot


def stored(db, model, *columns):
    return sorted(tuple(row) for row in db.execute(select(*(getattr(model, column) for column in columns))).all())


def test_snapshot_replaces_rows_and_keeps_first_seen_and_status_since(db):
    first = snapshot(
        api_product("TEST-1", "Test sofa", [destination("SHOPPING_ADS", disapproved=["GR"]),
                                            destination("FREE_LISTINGS", approved=["GR"])],
                    [issue("image_link_broken", "DISAPPROVED", "image_link"),
                     issue("missing_gtin", "NOT_IMPACTED", "gtin", context="FREE_LISTINGS")]),
        api_product("TEST-2", "Test bed", [destination("SHOPPING_ADS", approved=["GR"])]),
    )
    assert import_product_statuses(db, first, FIRST) == {
        "merchant_status_products": 2, "merchant_status_rows": 3, "merchant_issue_rows": 2}

    second = snapshot(
        api_product("TEST-1", "Test sofa v2", [destination("SHOPPING_ADS", disapproved=["GR"]),
                                               destination("FREE_LISTINGS", pending=["GR"])],
                    [issue("image_link_broken", "DISAPPROVED", "image_link"),
                     issue("image_link_broken", "DISAPPROVED", "image_link", countries=("CY",)),
                     issue("price_mismatch", "DEMOTED", "price")]),
        api_product("TEST-2", "Test bed", [destination("SHOPPING_ADS", approved=["GR"])]),
        api_product("TEST-3", "Test lamp"),
        {"offerId": "", "productStatus": {}},
    )
    assert import_product_statuses(db, second, SECOND) == {
        "merchant_status_products": 3, "merchant_status_rows": 4, "merchant_issue_rows": 2}

    assert stored(db, MerchantProductStatus, "offer_id", "reporting_context", "status", "status_since", "title") == [
        ("TEST-1", "FREE_LISTINGS", "pending", SECOND, "Test sofa v2"),
        ("TEST-1", "SHOPPING_ADS", "disapproved", FIRST, "Test sofa v2"),
        ("TEST-2", "SHOPPING_ADS", "approved", FIRST, "Test bed"),
        ("TEST-3", "", "unknown", SECOND, "Test lamp"),
    ]
    # The resolved missing_gtin issue is gone; the duplicate image issue is merged.
    assert stored(db, MerchantProductIssue, "offer_id", "code", "severity", "first_seen_at", "applicable_countries") == [
        ("TEST-1", "image_link_broken", "DISAPPROVED", FIRST, ["CY", "GR"]),
        ("TEST-1", "price_mismatch", "DEMOTED", SECOND, ["GR"]),
    ]
    assert set(db.scalars(select(MerchantProductStatus.synced_at)).all()) == {SECOND}


# ------------------------------------------------------------------ endpoint


def dashboard_app(db):
    application = FastAPI()
    application.include_router(dashboard.router, prefix="/api")
    application.dependency_overrides[get_db] = lambda: db
    application.dependency_overrides[get_current_user] = lambda: SimpleNamespace(is_admin=False)
    return application


def test_merchant_issues_endpoint_counts_statuses_and_issues(db):
    import_product_statuses(db, snapshot(
        api_product("TEST-1", "Test sofa", [destination("SHOPPING_ADS", approved=["GR"])],
                    [issue("price_mismatch", "DEMOTED", "price")]),
        api_product("TEST-4", "Test desk", [destination("SHOPPING_ADS", approved=["GR"])],
                    [issue("missing_gtin", "NOT_IMPACTED", "gtin")]),
    ), FIRST)
    import_product_statuses(db, snapshot(
        api_product("TEST-1", "Test sofa", [destination("SHOPPING_ADS", approved=["GR"]),
                                            destination("FREE_LISTINGS", approved=["GR"])],
                    [issue("price_mismatch", "DEMOTED", "price"),
                     issue("missing_gtin", "NOT_IMPACTED", "gtin", context="FREE_LISTINGS")]),
        api_product("TEST-2", "Test bed", [destination("SHOPPING_ADS", disapproved=["GR"]),
                                           destination("FREE_LISTINGS", disapproved=["GR"])],
                    [issue("image_link_broken", "DISAPPROVED", "image_link"),
                     issue("image_link_broken", "DISAPPROVED", "image_link", context="FREE_LISTINGS")]),
        api_product("TEST-3", "Test lamp", [destination("SHOPPING_ADS", disapproved=["GR"])]),
        api_product("TEST-4", "Test desk", [destination("SHOPPING_ADS", pending=["GR"])],
                    [issue("missing_gtin", "NOT_IMPACTED", "gtin")]),
    ), SECOND)

    with TestClient(dashboard_app(db)) as http:
        data = http.get("/api/dashboard/merchant-issues").json()["data"]
        advice = http.get("/api/dashboard/merchant-issues", params={"severity": "NOT_IMPACTED"}).json()["data"]
        shopping = http.get("/api/dashboard/merchant-issues", params={"reporting_context": "SHOPPING_ADS",
                                                                      "limit": 1}).json()["data"]
        assert http.get("/api/dashboard/merchant-issues", params={"severity": "BAD"}).status_code == 422
        assert http.get("/api/dashboard/merchant-issues", params={"limit": 0}).status_code == 422

    assert data["synced_at"] == SECOND.astimezone(ATHENS).isoformat() == "2031-03-12T04:00:00+02:00"
    assert data["products"] == 4
    assert data["status_counts"] == [
        {"reporting_context": "FREE_LISTINGS", "disapproved": 1, "partly_disapproved": 0, "pending": 0, "approved": 1,
         "unknown": 0, "total": 2},
        {"reporting_context": "SHOPPING_ADS", "disapproved": 2, "partly_disapproved": 0, "pending": 1, "approved": 1,
         "unknown": 0, "total": 4},
    ]
    assert data["severity_counts"] == {"DISAPPROVED": 1, "DEMOTED": 1, "NOT_IMPACTED": 2}
    assert [(row["code"], row["severity"], row["products"], row["new_products"]) for row in data["issue_counts"]] == [
        ("image_link_broken", "DISAPPROVED", 1, 1), ("price_mismatch", "DEMOTED", 1, 0),
        ("missing_gtin", "NOT_IMPACTED", 2, 1)]
    assert data["issue_counts"][0]["reporting_contexts"] == ["FREE_LISTINGS", "SHOPPING_ADS"]
    assert data["new_issue_rows"] == 3
    assert data["affected_severities"] == ["DISAPPROVED", "DEMOTED"] and data["affected_product_count"] == 3
    bed, lamp, sofa = data["affected_products"]
    assert (bed["offer_id"], bed["title"], len(bed["issues"])) == ("TEST-2", "Test bed", 2)
    assert {item["reporting_context"] for item in bed["disapproved_destinations"]} == {"SHOPPING_ADS", "FREE_LISTINGS"}
    assert bed["issues"][0]["is_new"] is True and bed["issues"][0]["description"] == "Test issue image_link_broken"
    # Disapproved for a destination without an item-level issue.
    assert (lamp["offer_id"], lamp["issues"], lamp["disapproved_destinations"][0]["status"]) == (
        "TEST-3", [], "disapproved")
    assert (sofa["offer_id"], [item["code"] for item in sofa["issues"]]) == ("TEST-1", ["price_mismatch"])
    assert sofa["issues"][0]["is_new"] is False and sofa["issues"][0]["first_seen_at"] == FIRST.astimezone(ATHENS).isoformat()
    assert [product["offer_id"] for product in advice["affected_products"]] == ["TEST-1", "TEST-4"]
    assert shopping["status_counts"][0]["reporting_context"] == "SHOPPING_ADS" and len(shopping["status_counts"]) == 1
    assert shopping["affected_product_count"] == 3 and [p["offer_id"] for p in shopping["affected_products"]] == ["TEST-2"]
    assert shopping["affected_products"][0]["issues"][0]["reporting_context"] == "SHOPPING_ADS"


def test_merchant_issues_endpoint_without_a_snapshot(db):
    db.execute(MerchantProductIssue.__table__.delete())
    db.execute(MerchantProductStatus.__table__.delete())
    with TestClient(dashboard_app(db)) as http:
        data = http.get("/api/dashboard/merchant-issues").json()["data"]
    assert data["synced_at"] is None and data["products"] == 0 and data["status_counts"] == []
    assert data["affected_products"] == [] and data["new_issue_rows"] == 0


# ------------------------------------------------------------------ sync


def enable_merchant(db, config):
    setting = db.scalar(select(IntegrationSetting).where(IntegrationSetting.provider == "merchant_center"))
    if setting is None:
        setting = IntegrationSetting(provider="merchant_center", display_name="Merchant Center")
        db.add(setting)
    setting.is_enabled, setting.config = True, config
    db.commit()


def fake_merchant(monkeypatch, calls, statuses=None):
    def metrics(self, date_from, date_to):
        calls.append("metrics")
        return [{"date": "2031-03-12", "item_id": "TEST-1", "title": "Test sofa", "clicks": 3, "impressions": 90}]

    def product_statuses(self):
        calls.append("statuses")
        self.requests += 1
        if isinstance(statuses, Exception):
            raise statuses
        return statuses or snapshot(api_product("TEST-1", "Test sofa", [destination("SHOPPING_ADS", approved=["GR"])],
                                                [issue("price_mismatch", "DEMOTED", "price")]))

    monkeypatch.setattr(MerchantCenterConnector, "fetch_product_metrics", metrics)
    monkeypatch.setattr(MerchantCenterConnector, "fetch_product_statuses", product_statuses)


def test_daily_merchant_sync_stores_the_status_snapshot(db, monkeypatch):
    enable_merchant(db, CONFIG)
    calls = []
    fake_merchant(monkeypatch, calls)
    run = run_provider_sync(db, "merchant_center", DAY, DAY, sync_type="scheduled")
    assert run.status == "success" and run.error_message is None and calls == ["metrics", "statuses"]
    assert (run.meta["merchant_status_products"], run.meta["merchant_issue_rows"], run.meta["merchant_api_requests"]) == (
        1, 1, 1)
    assert run.records_processed == 2
    assert db.scalars(select(MerchantProductIssue.code)).all() == ["price_mismatch"]

    calls.clear()
    fake_merchant(monkeypatch, calls, statuses=RuntimeError("Merchant API 500 Bearer abc.def-123"))
    failed = run_provider_sync(db, "merchant_center", DAY, DAY, sync_type="manual")
    assert failed.status == "success" and "Merchant product statuses failed" in failed.error_message
    assert "abc.def-123" not in failed.error_message and "abc.def-123" not in failed.meta["merchant_statuses_error"]
    # The previous snapshot stays.
    assert db.scalars(select(MerchantProductIssue.code)).all() == ["price_mismatch"]


@pytest.mark.parametrize("sync_type", ["backfill", "intraday"])
def test_backfill_and_intraday_merchant_syncs_keep_the_snapshot(db, monkeypatch, sync_type):
    enable_merchant(db, CONFIG)
    calls = []
    fake_merchant(monkeypatch, calls)
    run = run_provider_sync(db, "merchant_center", DAY, DAY, sync_type=sync_type)
    assert run.status == "success" and calls == ["metrics"]
    assert run.meta["merchant_statuses"].startswith("skipped")


def test_csv_merchant_sync_has_no_statuses(db, monkeypatch):
    enable_merchant(db, {"csv_url": "https://example.test/merchant.csv"})
    calls = []
    fake_merchant(monkeypatch, calls)
    run = run_provider_sync(db, "merchant_center", DAY, DAY, sync_type="scheduled")
    assert run.status == "success" and calls == ["metrics"]
    assert "CSV" in run.meta["merchant_statuses"]
