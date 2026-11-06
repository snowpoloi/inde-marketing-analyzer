import hashlib
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import deps
from app.api.deps import get_current_user
from app.api.routes import dashboard
from app.db.session import get_db
from app.models import CampaignDailyMetric

FIRST, SECOND = date(2031, 3, 10), date(2031, 3, 11)
WINDOW = {"date_from": "2031-03-10", "date_to": "2031-03-12"}


def meta_row(db, day, ad_id, ad_name, spend, impressions, reach, link_clicks, purchases=0, value="0", carts=0):
    db.add(CampaignDailyMetric(
        source="meta_ads", metric_date=day, campaign_id="cmp-1", campaign_name="Sales", adset_id="set-1",
        adset_name="Broad", ad_id=ad_id, ad_name=ad_name, cost=Decimal(spend), impressions=impressions, reach=reach,
        frequency=0, clicks=link_clicks, link_clicks=link_clicks, add_to_cart=carts, initiate_checkout=0,
        purchases=Decimal(purchases), purchase_value=Decimal(value), raw={},
    ))


def dashboard_app(db):
    application = FastAPI()
    application.include_router(dashboard.router, prefix="/api")
    application.dependency_overrides[get_db] = lambda: db
    return application


def test_meta_ads_endpoint_totals_each_ad_and_bounds_its_reach(db):
    meta_row(db, FIRST, "ad-1", "Sofa video", "20", 2000, 1000, 30, purchases=1, value="300", carts=3)
    meta_row(db, SECOND, "ad-1", "Sofa video v2", "30", 3000, 1500, 30, carts=2)
    meta_row(db, SECOND, "ad-2", "Bed carousel", "10", 500, 400, 5)
    meta_row(db, SECOND, None, None, "5", 100, 90, 1)
    db.add(CampaignDailyMetric(source="google_ads", metric_date=SECOND, campaign_name="Shopping", cost=Decimal("99"),
                               impressions=10, raw={}))
    db.flush()
    application = dashboard_app(db)
    with TestClient(application) as http:
        assert http.get("/api/dashboard/meta-ads", params=WINDOW).status_code == 401
        application.dependency_overrides[get_current_user] = lambda: SimpleNamespace(is_admin=True)
        data = http.get("/api/dashboard/meta-ads", params=WINDOW).json()["data"]

    assert [ad["ad_id"] for ad in data["ads"]] == ["ad-1", "ad-2"]
    ad = data["ads"][0]
    assert (ad["ad_name"], ad["adset_name"], ad["campaign_name"]) == ("Sofa video v2", "Broad", "Sales")
    assert (ad["first_date"], ad["last_date"], ad["days"]) == ("2031-03-10", "2031-03-11", 2)
    assert (ad["spend"], ad["impressions"], ad["link_clicks"], ad["add_to_cart"]) == (50.0, 5000, 60, 5)
    assert (ad["purchases"], ad["purchase_value"], ad["roas"], ad["cost_per_purchase"]) == (1, 300.0, 6.0, 50.0)
    assert (ad["ctr"], ad["cpm"], ad["cpc"]) == (1.2, 10.0, round(50 / 60, 2))
    assert (ad["reach_daily_max"], ad["reach_daily_sum"]) == (1500, 2500)
    assert (ad["frequency_min"], ad["frequency_max"]) == (2.0, round(5000 / 1500, 4))
    no_sales = data["ads"][1]
    assert (no_sales["purchases"], no_sales["roas"], no_sales["cost_per_purchase"]) == (0, 0.0, None)
    assert no_sales["frequency_min"] == no_sales["frequency_max"] == 1.25

    first_day = next(row for row in data["daily"] if row["ad_id"] == "ad-1" and row["date"] == "2031-03-10")
    assert (first_day["reach"], first_day["frequency"], first_day["purchase_value"]) == (1000, 2.0, 300.0)
    assert [(row["date"], row["ad_id"]) for row in data["daily"]] == [
        ("2031-03-10", "ad-1"), ("2031-03-11", "ad-1"), ("2031-03-11", "ad-2")]
    assert data["unassigned"]["rows"] == 1 and data["unassigned"]["spend"] == 5.0
    assert data["totals"]["spend"] == 65.0 and data["totals"]["impressions"] == 5600
    assert data["days_with_data"] == ["2031-03-10", "2031-03-11"] and data["missing_days"] == ["2031-03-12"]
    assert "reach_daily_max" in data["reach_note"]


def test_meta_ads_endpoint_without_rows(db):
    application = dashboard_app(db)
    application.dependency_overrides[get_current_user] = lambda: SimpleNamespace(is_admin=True)
    with TestClient(application) as http:
        data = http.get("/api/dashboard/meta-ads", params={"date_from": "2031-01-01", "date_to": "2031-01-01"}).json()["data"]
    assert data["ads"] == [] and data["daily"] == [] and data["unassigned"] is None
    assert data["totals"]["spend"] == 0.0 and data["totals"]["ctr"] is None


def test_advestiq_key_can_read_the_detail_reports(db, monkeypatch):
    key = "test-key-for-detail-reports"
    monkeypatch.setattr(deps.settings, "advestiq_api_key_sha256", hashlib.sha256(key.encode()).hexdigest())
    with TestClient(dashboard_app(db)) as http:
        for path in ("/api/dashboard/funnel", "/api/dashboard/landing-pages", "/api/dashboard/meta-ads"):
            assert http.get(path, params=WINDOW, headers={deps.ADVESTIQ_KEY_HEADER: key}).status_code == 200
            assert http.get(path, params=WINDOW, headers={deps.ADVESTIQ_KEY_HEADER: "wrong"}).status_code == 401
            assert http.get(path, params=WINDOW).status_code == 401
