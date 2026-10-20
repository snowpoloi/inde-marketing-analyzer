import json
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import func, inspect, select, text

from app.api.deps import get_current_user
from app.api.routes.business_review import router
from app.connectors.google_ads import GoogleAdsConnector
from app.connectors.meta_ads import MetaAdsConnector
from app.db.session import get_db
from app.models import (AADEDocument, Base, CampaignDailyMetric, IntegrationSetting,
                        OpenCartOrder, OpenCartOrderProduct, ReviewEvent, ReviewJob, SyncRun)
from app.services import business_review_jobs as jobs
from app.services import sync_service
from app.services.business_review_service import build_review, change, covered_days

BEFORE = date(2026, 9, 1)
AFTER = date(2026, 10, 1)


def http_client(db, admin=True):
    app = FastAPI()
    app.include_router(router, prefix="/api")
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=uuid4(), is_admin=admin)
    return TestClient(app)


def params():
    return dict(date_from=str(AFTER), date_to=str(AFTER),
                baseline_from=str(BEFORE), baseline_to=str(BEFORE))


def seed(db):
    for day, value, name in [(BEFORE, 100, "Before name"), (AFTER, 200, "Renamed")]:
        order = OpenCartOrder(order_id=f"review-{day}", date_added=datetime.combine(day, datetime.min.time(), timezone.utc),
                              total=value, currency_code="EUR")
        order.products = [OpenCartOrderProduct(product_id="shared", sku="SKU-1", name="Product",
                           quantity=2, price=value / 2, brand="Brand", category="Category")]
        db.add(order)
        db.add(CampaignDailyMetric(source="meta_ads", metric_date=day, campaign_id="same-id",
               campaign_name=name, cost=50, conversion_value=value, conversions=2, link_clicks=10, clicks=0))
    db.flush()


def test_growth_uses_stable_ids_meta_clicks_and_does_not_sum_revenues(db):
    seed(db)
    result = build_review(db, AFTER, AFTER, BEFORE, BEFORE)
    assert result["metrics"]["order_value"]["current"] == 200
    assert result["metrics"]["order_value"]["percent"] == 100
    assert result["metrics"]["blended_ratio"]["current"] == 4
    assert len(result["comparisons"]["campaigns"]) == 1
    campaign = result["comparisons"]["campaigns"][0]
    assert campaign["state"] == "both"
    assert campaign["metrics"]["clicks"]["current"] == 10
    assert result["comparisons"]["products"][0]["metrics"]["value"]["delta"] == 100
    assert result["sources"][0]["cost"]["current"] is None
    assert result["metrics"]["bank_credits"]["current"] is None


def test_missing_source_is_not_zero_or_a_false_decline(db):
    db.add(CampaignDailyMetric(source="google_ads", metric_date=BEFORE, campaign_id="id",
                              campaign_name="Search", cost=100, conversion_value=300))
    db.flush()
    result = build_review(db, AFTER, AFTER, BEFORE, BEFORE)
    row = result["comparisons"]["campaigns"][0]
    assert row["state"] == "source_not_loaded"
    assert row["metrics"]["cost"]["current"] is None
    assert row["metrics"]["cost"]["percent"] is None
    assert result["metrics"]["order_value"]["current"] is None
    assert result["metrics"]["blended_ratio"]["previous"] is None


def test_successful_zero_activity_is_distinct_from_not_loaded(db):
    db.add(SyncRun(provider="google_ads", status="success", sync_type="backfill",
                   date_from=AFTER, date_to=AFTER))
    db.flush()
    result = build_review(db, AFTER, AFTER, BEFORE, BEFORE)
    assert result["sources"][0]["cost"]["current"] == 0
    assert result["sources"][0]["cost"]["previous"] is None
    assert result["current"]["coverage"][0]["status"] == "synced"


def test_fiscal_credit_notes_cancelled_and_duplicate_books(db):
    for i, value, kind, raw, cancelled, currency in [
        (1, 100, "1.1", {}, False, "EUR"), (2, 20, "5.1", {}, False, "EUR"),
        (3, 100, "1.1", {"record_type": "book_info"}, False, "EUR"),
        (4, 500, "1.1", {}, True, "EUR"), (5, 500, "1.1", {}, False, "USD"),
    ]:
        db.add(AADEDocument(identity_key=f"review-{i}", source_endpoint="test", issue_date=AFTER,
                           document_direction="expense", invoice_type=kind, net_value=value, raw=raw,
                           is_cancelled=cancelled, currency=currency))
    db.flush()
    report = build_review(db, AFTER, AFTER, BEFORE, BEFORE)
    assert report["metrics"]["aade_expense_net"]["current"] == 80
    assert report["metrics"]["aade_expense_net"]["previous"] is None


def test_book_only_fiscal_data_does_not_claim_zero_expenses(db):
    db.add(AADEDocument(identity_key="book", source_endpoint="test", issue_date=AFTER,
                       document_direction="expense", net_value=100, raw={"record_type": "book_info"}))
    db.flush()
    assert build_review(db, AFTER, AFTER, BEFORE, BEFORE)["metrics"]["aade_expense_net"]["current"] is None


@pytest.mark.parametrize("kind", ["5.1", "5.2", "11.4", "13.31", "14.31"])
def test_all_fiscal_credit_types_are_deducted(db, kind):
    db.add(AADEDocument(identity_key="credit", source_endpoint="test", issue_date=AFTER,
                       invoice_type=kind, document_direction="income", net_value=25))
    db.flush()
    assert build_review(db, AFTER, AFTER, BEFORE, BEFORE)["metrics"]["aade_income_net"]["current"] == -25


def test_local_event_midnight_and_idempotence(db):
    kwargs = dict(source="shoply", occurred_at=datetime(2026, 9, 30, 22, tzinfo=timezone.utc),
                  title="Reported feed fix", evidence_type="email")
    assert jobs.store_event(db, **kwargs) == 1
    assert jobs.store_event(db, **kwargs) == 0
    assert len(build_review(db, AFTER, AFTER, BEFORE, BEFORE)["events"]) == 1


def test_payload_redaction_recurses_without_disclosing_feed_credentials():
    payload = {"refresh_token": "SECRET1", "nested": [
        {"url": "https://supplier.test/feed?token=SECRET2&lang=el"},
        "https://name:SECRET3@supplier.test/feed"]}
    value = json.dumps(jobs.sanitize_evidence(payload))
    assert all(s not in value for s in ["SECRET1", "SECRET2", "SECRET3"])
    assert "lang=el" in value


def test_history_windows_retain_old_google_gap_and_dedupe(db, monkeypatch):
    monkeypatch.setattr(jobs, "today", lambda: date(2026, 10, 20))
    count = jobs.enqueue_history(db, date(2025, 12, 1), date(2026, 10, 20), ["google_ads"])
    assert count > 20
    assert jobs.enqueue_history(db, date(2025, 12, 1), date(2026, 10, 20), ["google_ads"]) == 0
    unavailable = db.scalars(select(ReviewJob).where(ReviewJob.status == "unavailable")).one()
    assert unavailable.date_from == date(2025, 12, 1)
    assert unavailable.date_to == date(2026, 9, 21)
    assert "export" in unavailable.error
    for row in db.scalars(select(ReviewJob).where(ReviewJob.kind == "metrics")):
        assert (row.date_to - row.date_from).days < 14


def test_worker_runs_one_window_and_preserves_provider_errors(db, monkeypatch):
    jobs.queue_job(db, "ga4", "metrics", BEFORE, BEFORE)
    jobs.queue_job(db, "meta_ads", "metrics", AFTER, AFTER)
    db.commit()
    calls = []
    def run(db, provider, a, b, sync_type):
        calls.append((provider, a, b, sync_type))
        return SimpleNamespace(id=uuid4(), status="failed", records_processed=0,
                               error_message="No historical access", meta={})
    monkeypatch.setattr(jobs, "run_provider_sync", run)
    jobs.process_review_job(db)
    assert calls == [("meta_ads", AFTER, AFTER, "backfill")]
    assert db.scalar(select(func.count()).select_from(ReviewJob).where(ReviewJob.status == "queued")) == 1
    assert db.scalar(select(ReviewJob).where(ReviewJob.status == "failed")).error == "No historical access"


def test_worker_defers_to_active_regular_sync(db, monkeypatch):
    jobs.queue_job(db, "ga4", "metrics", AFTER, AFTER)
    db.add(SyncRun(provider="opencart", status="running", started_at=datetime.now(timezone.utc)))
    db.commit()
    monkeypatch.setattr(jobs, "run_provider_sync", lambda *a, **kw: pytest.fail("Must defer"))
    jobs.process_review_job(db)
    assert db.scalar(select(ReviewJob)).status == "queued"


def test_provider_lock_prevents_overlapping_import(db):
    key = 80103000 + sorted(sync_service.PROVIDERS).index("ga4")
    with db.get_bind().engine.connect() as lock:
        lock.execute(text("SELECT pg_advisory_lock(:key)"), {"key": key})
        try:
            result = sync_service.run_provider_sync(db, "ga4", AFTER, AFTER, "backfill")
            assert result.status == "skipped"
            assert result.meta["reason"] == "provider_busy"
        finally:
            lock.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": key})


def test_api_admin_snapshots_and_atomic_csv_validation(db):
    seed(db)
    with http_client(db) as http:
        report_id = http.post("/api/business-review/reports", json=params()).json()["id"]
        original = http.get(f"/api/business-review/reports/{report_id}").json()
        db.add(OpenCartOrder(order_id="later", date_added=datetime(2026,10,1,12,tzinfo=timezone.utc), total=99))
        db.flush()
        assert http.get(f"/api/business-review/reports/{report_id}").json() == original
        assert http.post("/api/business-review/compare", json=params()).json()["metrics"]["order_value"]["current"] == 299
        content = ("source,occurred_at,title,reference_url\nshoply,2026-10-01T12:00:00,Valid,\n"
                   "shoply,2026-10-01T12:00:00,Invalid,https://test.example/?token=DO_NOT_ECHO\n")
        response = http.post("/api/business-review/events/import",
                             files={"file": ("events.csv", content.encode(), "text/csv")})
        assert response.status_code == 422
        assert "DO_NOT_ECHO" not in response.text
        assert db.scalar(select(func.count()).select_from(ReviewEvent)) == 0
        assert http.post("/api/business-review/events", json={
            "source":"google_ads", "occurred_at":"2026-10-01T12:00:00", "title":"Claim",
            "evidence_type":"api"}).status_code == 422
    with http_client(db, False) as http:
        assert http.get("/api/business-review/jobs").status_code == 403
        assert http.post("/api/business-review/compare", json=params()).status_code == 403
        assert http.post("/api/business-review/history", json={**params(), "providers":["ga4"]}).status_code == 403


def test_review_migration_matches_model(db):
    inspector = inspect(db.get_bind())
    for name, table in Base.metadata.tables.items():
        if name.startswith("review_"):
            assert {c["name"] for c in inspector.get_columns(name)} == set(table.columns.keys())
            assert {i.name for i in table.indexes} <= {i["name"] for i in inspector.get_indexes(name)}


def test_period_math_handles_zero_and_overlapping_sync_windows():
    assert change(20, 0)["percent"] is None
    assert change(None, 100)["delta"] is None
    assert covered_days(AFTER, AFTER + timedelta(days=2), [
        (AFTER, AFTER + timedelta(days=1)), (AFTER, AFTER + timedelta(days=2))]) == 3
    assert list(jobs.windows(AFTER, AFTER + timedelta(days=14))) == [
        (AFTER, AFTER + timedelta(days=13)), (AFTER + timedelta(days=14), AFTER + timedelta(days=14))]


def test_meta_change_history_uses_only_get_and_rejects_broken_pagination(monkeypatch):
    calls = []
    connector = MetaAdsConnector({"access_token": "test-only", "ad_account_id": "123"})
    def request(client, url, parameters):
        calls.append((url, parameters.copy()))
        return {"data": [{"event_type": "budget_change"}], "paging": {"next":"https://ignored", "cursors":{"after":"same"}}}
    monkeypatch.setattr(connector, "_request", request)
    with pytest.raises(ValueError, match="pagination incomplete"):
        connector.fetch_changes(BEFORE, BEFORE)
    assert len(calls) == 2
    assert calls[0][0].endswith("/act_123/activities")
    assert calls[1][1]["after"] == "same"


def test_google_old_history_fails_before_api_access():
    with pytest.raises(ValueError, match="export"):
        GoogleAdsConnector({}).fetch_changes(date(2020, 1, 1), date(2020, 1, 2))
