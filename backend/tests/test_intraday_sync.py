import hashlib
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.api import deps
from app.api.routes import dashboard
from app.connectors.ga4 import GA4Connector
from app.connectors.google_ads import GoogleAdsConnector
from app.connectors.meta_ads import MetaAdsConnector
from app.connectors.opencart import OpenCartConnector
from app.connectors.tiktok_ads import TikTokAdsConnector
from app.core.config import Settings, settings
from app.db.session import get_db
from app.models import (
    CampaignDailyMetric,
    GA4DailyMetric,
    GA4FunnelDailyMetric,
    GA4LandingPageDailyMetric,
    IntegrationSetting,
    OpenCartOrder,
    OpenCartOrderChange,
    OpenCartOrderProduct,
    ReviewJob,
    SupplierCatalogFeed,
    SyncRun,
)
from app.services import business_review_jobs
from app.services.business_review_jobs import schedule_recent_history
from app.services.constants import PROVIDERS
from app.services.import_service import import_opencart_orders
from app.services.sync_service import next_intraday_run, run_intraday_sync

DAY = date(2031, 3, 12)
INTRADAY = ["google_ads", "meta_ads", "tiktok_ads", "opencart", "ga4"]
ORDER_ID = "TEST-INTRADAY-1"


def enable(db, provider, config=None, enabled=True):
    setting = db.scalar(select(IntegrationSetting).where(IntegrationSetting.provider == provider))
    if setting is None:
        setting = IntegrationSetting(provider=provider, display_name=provider)
        db.add(setting)
    setting.is_enabled = enabled
    setting.config = config or {}
    db.commit()
    return setting


def fake_sources(monkeypatch):
    monkeypatch.setattr(GoogleAdsConnector, "fetch_campaign_metrics", lambda self, a, b: [
        {"date": "2031-03-12", "campaign_id": "g-1", "campaign_name": "Search", "cost": "10", "clicks": "5",
         "impressions": "100", "conversions": "1", "conversion_value": "50"}])
    monkeypatch.setattr(MetaAdsConnector, "fetch_campaign_metrics", lambda self, a, b: [
        {"date_start": "2031-03-12", "campaign_id": "m-1", "campaign_name": "Sales", "ad_id": "ad-1",
         "ad_name": "Video", "spend": "7", "impressions": "300", "reach": "200", "inline_link_clicks": "4"}])
    monkeypatch.setattr(TikTokAdsConnector, "fetch_campaign_metrics", lambda self, a, b: [
        {"stat_time_day": "2031-03-12", "campaign_id": "t-1", "campaign_name": "Sales", "cost": "3", "clicks": "2",
         "impressions": "50", "complete_payment": "0", "total_complete_payment_rate": "0"}])
    monkeypatch.setattr(OpenCartConnector, "fetch_orders", lambda self, a, b: [
        {"order_id": ORDER_ID, "date_added": "2031-03-12 10:00:00", "order_status": "Pending", "total": "120.00",
         "products": [{"product_id": "1", "name": "Test chair", "quantity": 1, "price": "120"}]}])

    def no_product_feed(self):
        raise AssertionError("Intraday runs must not read the full product feed.")

    monkeypatch.setattr(OpenCartConnector, "fetch_product_catalog", no_product_feed)
    monkeypatch.setattr(GA4Connector, "fetch_daily_metrics", lambda self, a, b: [
        {"date": "20310312", "channel_group": "Paid Social", "source_medium": "facebook / cpc", "sessions": "5",
         "users": "4", "purchases": "1", "purchase_revenue": "120"}])
    monkeypatch.setattr(GA4Connector, "fetch_funnel_events", lambda self, a, b: [
        {"date": "20310312", "event_name": "session_start", "device_category": "mobile",
         "channel_group": "Paid Social", "event_count": 5, "users": 4}])
    monkeypatch.setattr(GA4Connector, "fetch_landing_pages", lambda self, a, b: [
        {"date": "20310312", "landing_page": "/el/chairs", "channel_group": "Paid Social", "sessions": 5,
         "purchase_revenue": "120"}])


def stored_counts(db):
    def count(model, *conditions):
        return db.scalar(select(func.count()).select_from(model).where(*conditions))

    ads = dict(db.execute(select(CampaignDailyMetric.source, func.count())
                          .where(CampaignDailyMetric.metric_date == DAY)
                          .group_by(CampaignDailyMetric.source)).all())
    order = db.scalar(select(OpenCartOrder).where(OpenCartOrder.order_id == ORDER_ID))
    return {
        **ads,
        "orders": count(OpenCartOrder, OpenCartOrder.order_id == ORDER_ID),
        "order_products": count(OpenCartOrderProduct, OpenCartOrderProduct.order_pk == order.id) if order else 0,
        "order_changes": count(OpenCartOrderChange, OpenCartOrderChange.order_id == ORDER_ID),
        "ga4": count(GA4DailyMetric, GA4DailyMetric.metric_date == DAY),
        "funnel": count(GA4FunnelDailyMetric, GA4FunnelDailyMetric.metric_date == DAY),
        "landing": count(GA4LandingPageDailyMetric, GA4LandingPageDailyMetric.metric_date == DAY),
    }


def test_two_intraday_runs_of_the_same_day_leave_no_duplicates(db, monkeypatch):
    for provider in INTRADAY:
        enable(db, provider, {"endpoint_url": "https://example.test/orders",
                              "product_feed_url": "https://example.test/feed.xml"} if provider == "opencart" else {})
    feed = SupplierCatalogFeed(code="test-intraday-feed", name="Test feed", adapter="test",
                               encrypted_url="not-a-real-url", status="idle")
    db.add(feed)
    db.commit()
    fake_sources(monkeypatch)

    first = run_intraday_sync(db, DAY, providers=INTRADAY)
    after_first = stored_counts(db)
    second = run_intraday_sync(db, DAY, providers=INTRADAY)

    assert stored_counts(db) == after_first == {
        "google_ads": 1, "meta_ads": 1, "tiktok_ads": 1, "orders": 1, "order_products": 1, "order_changes": 0,
        "ga4": 1, "funnel": 1, "landing": 1,
    }
    for runs in (first, second):
        assert [run.provider for run in runs] == INTRADAY
        assert all(run.status == "success" and run.sync_type == "intraday" for run in runs), [
            (run.provider, run.status, run.error_message) for run in runs]
    by_provider = {run.provider: run for run in second}
    assert (by_provider["google_ads"].date_from, by_provider["google_ads"].date_to) == (DAY, DAY)
    assert (by_provider["ga4"].date_from, by_provider["ga4"].date_to) == (DAY - timedelta(days=2), DAY)
    db.refresh(feed)
    assert feed.status == "idle"


def test_order_reimport_logs_a_date_change_only_when_the_moment_changes(db):
    order = {"order_id": "TEST-INTRADAY-2", "order_status": "Pending", "total": "80.00", "products": []}
    import_opencart_orders(db, [{**order, "date_added": "2031-03-12 10:00:00"}])
    import_opencart_orders(db, [{**order, "date_added": "2031-03-12T12:00:00+02:00"}])
    changes = select(OpenCartOrderChange.field_name).where(OpenCartOrderChange.order_id == "TEST-INTRADAY-2")
    assert db.scalars(changes).all() == []
    import_opencart_orders(db, [{**order, "date_added": "2031-03-12T13:00:00+02:00"}])
    assert db.scalars(changes).all() == ["date_added"]


def test_intraday_sync_leaves_out_disabled_providers_and_never_runs_everything(db, monkeypatch):
    enable(db, "tiktok_ads", enabled=False)
    before = db.scalar(select(func.count()).select_from(SyncRun).where(SyncRun.sync_type == "intraday"))
    assert run_intraday_sync(db, DAY, providers=["tiktok_ads", "not_a_provider"]) == []
    monkeypatch.setattr(settings, "sync_intraday_providers", "tiktok_ads")
    assert run_intraday_sync(db, DAY) == []
    assert db.scalar(select(func.count()).select_from(SyncRun).where(SyncRun.sync_type == "intraday")) == before


@pytest.mark.parametrize("value,expected", [
    ("8,10,12,14,16,18,20,22", [8, 10, 12, 14, 16, 18, 20, 22]),
    (" 22, 8,8 ,x,24", [8, 22]),
    ("", []),
    ("off", []),
    ("None", []),
])
def test_intraday_hours_setting(value, expected):
    assert Settings(sync_intraday_hours=value).sync_intraday_hour_list == expected


def test_intraday_providers_setting():
    assert Settings(sync_intraday_providers=" Meta_Ads,ga4,meta_ads ").sync_intraday_provider_list == ["meta_ads", "ga4"]
    assert Settings(sync_intraday_providers="").sync_intraday_provider_list == []


@pytest.mark.parametrize("clock,expected", [
    ("07:59", "2031-03-12T08:00:00+02:00"),
    ("10:00", "2031-03-12T12:00:00+02:00"),
    ("22:30", "2031-03-13T08:00:00+02:00"),
])
def test_next_intraday_run(clock, expected):
    now = datetime.fromisoformat(f"2031-03-12T{clock}").replace(tzinfo=ZoneInfo("Europe/Athens"))
    assert next_intraday_run(now, [8, 10, 12, 14, 16, 18, 20, 22]).isoformat() == expected
    assert next_intraday_run(now, []) is None


def test_freshness_shows_runs_without_error_text_and_is_readable_with_the_key(db, monkeypatch):
    key = "test-key-for-freshness"
    monkeypatch.setattr(deps.settings, "advestiq_api_key_sha256", hashlib.sha256(key.encode()).hexdigest())
    monkeypatch.setattr(settings, "sync_intraday_hours", "8,10,12")
    monkeypatch.setattr(settings, "sync_intraday_providers", "google_ads,meta_ads")
    enable(db, "google_ads")
    now = datetime.now(timezone.utc)
    today = now.astimezone(ZoneInfo(settings.sync_timezone)).date()
    yesterday = today - timedelta(days=1)
    db.add_all([
        SyncRun(provider="google_ads", sync_type="intraday", status="success", date_from=today, date_to=today,
                started_at=now - timedelta(hours=2), finished_at=now - timedelta(hours=2) + timedelta(minutes=1),
                records_processed=12, meta={}),
        SyncRun(provider="google_ads", sync_type="intraday", status="failed", date_from=today, date_to=today,
                started_at=now - timedelta(minutes=10), finished_at=now - timedelta(minutes=9),
                error_message="Google Ads API error: customer 1234567890 token=very-secret", meta={"detail": "x"}),
        SyncRun(provider="meta_ads", sync_type="scheduled", status="success", date_from=yesterday, date_to=yesterday,
                started_at=now - timedelta(hours=8), finished_at=now - timedelta(hours=8) + timedelta(minutes=2),
                records_processed=40, meta={}),
    ])
    db.flush()
    application = FastAPI()
    application.include_router(dashboard.router, prefix="/api")
    application.dependency_overrides[get_db] = lambda: db
    with TestClient(application) as http:
        assert http.get("/api/dashboard/freshness").status_code == 401
        response = http.get("/api/dashboard/freshness", headers={deps.ADVESTIQ_KEY_HEADER: key})
    assert response.status_code == 200
    assert "very-secret" not in response.text and "1234567890" not in response.text
    assert "error_message" not in response.text and '"detail"' not in response.text
    data = response.json()["data"]
    assert data["today"] == today.isoformat() and data["timezone"] == "Europe/Athens"
    assert data["intraday"]["hours"] == [8, 10, 12] and data["intraday"]["providers"] == ["google_ads", "meta_ads"]
    assert [row["provider"] for row in data["providers"]] == list(PROVIDERS)
    google = next(row for row in data["providers"] if row["provider"] == "google_ads")
    assert google["enabled"] is True and google["intraday"] is True
    assert google["latest_run"]["status"] == "failed" and google["latest_run"]["has_error"] is True
    assert google["last_success"]["status"] == "success" and google["last_success"]["records_processed"] == 12
    assert google["last_success"]["has_error"] is False
    assert google["today_synced_at"] == google["last_success"]["finished_at"]
    meta = next(row for row in data["providers"] if row["provider"] == "meta_ads")
    assert meta["today_synced_at"] is None and meta["last_success"]["date_from"] == yesterday.isoformat()
    tiktok = next(row for row in data["providers"] if row["provider"] == "tiktok_ads")
    assert tiktok["intraday"] is False


def test_recent_history_is_requeued_once_its_last_run_finished(db, monkeypatch):
    monkeypatch.setattr(business_review_jobs, "today", lambda: DAY)
    enable(db, "google_ads")
    enable(db, "meta_ads")

    def jobs():
        return {job.provider: job for job in db.scalars(select(ReviewJob).where(
            ReviewJob.kind == "changes", ReviewJob.date_from == DAY - timedelta(days=3), ReviewJob.date_to == DAY))}

    schedule_recent_history(db)
    first = jobs()
    assert {provider: job.status for provider, job in first.items()} == {"google_ads": "queued", "meta_ads": "queued"}
    first["google_ads"].status, first["google_ads"].error = "failed", "temporary"
    first["meta_ads"].status = "running"
    db.commit()

    schedule_recent_history(db)
    db.expire_all()
    again = jobs()
    assert {provider: job.status for provider, job in again.items()} == {"google_ads": "queued", "meta_ads": "running"}
    assert again["google_ads"].error is None
    assert {provider: job.id for provider, job in again.items()} == {provider: job.id for provider, job in first.items()}


def worker_module():
    root = str(Path(__file__).resolve().parents[2])
    if root not in sys.path:
        sys.path.insert(0, root)
    import worker.main as worker_main
    return worker_main


def test_worker_schedules_the_intraday_sync_only_when_configured(monkeypatch):
    worker_main = worker_module()
    jobs = {}

    class FakeScheduler:
        def __init__(self, timezone):
            self.timezone = timezone

        def add_job(self, func, trigger, **options):
            jobs[options["id"]] = (func, trigger, options)

        def start(self):
            pass

    monkeypatch.setattr(worker_main, "BlockingScheduler", FakeScheduler)
    monkeypatch.setattr(settings, "sync_intraday_hours", "8,10,22")
    monkeypatch.setattr(settings, "sync_intraday_providers", "google_ads,opencart")
    worker_main.main()
    func, trigger, options = jobs["intraday-marketing-sync"]
    assert func is worker_main.intraday_sync and trigger == "cron"
    assert (options["hour"], options["minute"], options["max_instances"], options["coalesce"]) == ("8,10,22", 0, 1, True)
    assert jobs["daily-marketing-sync"][2]["hour"] == settings.sync_daily_hour

    jobs.clear()
    monkeypatch.setattr(settings, "sync_intraday_hours", "")
    worker_main.main()
    assert "intraday-marketing-sync" not in jobs and "daily-marketing-sync" in jobs


def test_worker_intraday_job_syncs_today_and_refreshes_change_history(monkeypatch):
    worker_main = worker_module()
    calls = []

    class FakeSession:
        def __enter__(self):
            return "session"

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr(worker_main, "SessionLocal", FakeSession)
    monkeypatch.setattr(worker_main, "schedule_recent_history", lambda db: calls.append(("history", db)))
    monkeypatch.setattr(worker_main, "run_intraday_sync", lambda db, day: calls.append(("sync", db, day)))
    monkeypatch.setattr(settings, "sync_intraday_providers", "google_ads,opencart")
    worker_main.intraday_sync()
    today = datetime.now(ZoneInfo(settings.sync_timezone)).date()
    assert calls == [("history", "session"), ("sync", "session", today)]

    calls.clear()
    monkeypatch.setattr(settings, "sync_intraday_providers", "opencart,ga4")
    worker_main.intraday_sync()
    assert calls == [("sync", "session", today)]
