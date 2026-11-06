import hashlib
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app.api import deps
from app.api.deps import get_current_user, require_admin
from app.api.routes import advestiq, business_review, sync
from app.api.routes.settings import MASK_PREFIX, mask_config, merge_masked_config
from app.db.session import get_db
from app.models import ReviewEvent

KEY = "test-advestiq-key-123"


def key_app(monkeypatch, expected=hashlib.sha256(KEY.encode()).hexdigest()):
    monkeypatch.setattr(deps.settings, "advestiq_api_key_sha256", expected)
    application = FastAPI()

    @application.get("/api/dashboard/summary")
    def summary(user=Depends(require_admin)):
        return {"email": user.email}

    @application.post("/api/dashboard/summary")
    def write_summary(_=Depends(require_admin)):
        return {"ok": True}

    @application.get("/api/settings/integrations")
    def integrations(_=Depends(require_admin)):
        return {"secret": True}

    @application.post("/api/sync/run")
    def sync(_=Depends(require_admin)):
        return {"ok": True}

    @application.post("/api/advestiq/reports")
    def report(_=Depends(require_admin)):
        return {"ok": True}

    application.dependency_overrides[get_db] = lambda: None
    return TestClient(application)


def test_advestiq_key_reads_but_never_writes_or_sees_secrets(monkeypatch):
    http = key_app(monkeypatch)
    good, bad = {deps.ADVESTIQ_KEY_HEADER: KEY}, {deps.ADVESTIQ_KEY_HEADER: "wrong"}
    assert http.get("/api/dashboard/summary", headers=good).json() == {"email": deps.ADVESTIQ_EMAIL}
    assert http.get("/api/dashboard/summary").status_code == 401
    assert http.get("/api/dashboard/summary", headers=bad).status_code == 401
    assert http.post("/api/dashboard/summary", headers=good).status_code == 403
    assert http.get("/api/settings/integrations", headers=good).status_code == 403
    assert http.post("/api/sync/run", headers=good).status_code == 403
    assert http.post("/api/advestiq/reports", headers=good).status_code == 200


def test_advestiq_key_is_disabled_without_a_configured_hash(monkeypatch):
    http = key_app(monkeypatch, expected=None)
    assert http.get("/api/dashboard/summary", headers={deps.ADVESTIQ_KEY_HEADER: KEY}).status_code == 401


def test_integration_secrets_are_masked_and_kept_on_save():
    stored = {"developer_token": "dev-token-1234567890", "client_id": "client-1", "api_key": "short",
              "service_account_json": {"private_key": "x"}, "refresh_token": "", "property_id": "123"}
    masked = mask_config(stored)
    assert masked["developer_token"] == MASK_PREFIX + "7890"
    assert masked["api_key"] == MASK_PREFIX
    assert masked["service_account_json"] == MASK_PREFIX
    assert masked["client_id"] == "client-1" and masked["property_id"] == "123" and masked["refresh_token"] == ""
    assert merge_masked_config(masked, stored) == stored
    edited = {**masked, "api_key": "new-key", "property_id": "456"}
    assert merge_masked_config(edited, stored) == {**stored, "api_key": "new-key", "property_id": "456"}


def admin_client(db):
    application = FastAPI()
    application.include_router(advestiq.router, prefix="/api")
    application.include_router(business_review.router, prefix="/api")
    application.dependency_overrides[get_db] = lambda: db
    application.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=uuid4(), is_admin=True)
    return TestClient(application)


def test_event_summary_folds_bulk_changes(db):
    at = datetime(2026, 11, 5, 2, 53, tzinfo=timezone.utc)
    for index in range(60):
        db.add(ReviewEvent(source_key=f"bulk-{uuid4()}", source="google_ads", occurred_at=at, evidence_type="api",
                           actor="Bulk Actions", title="REMOVE", detail="asset", payload={}))
    db.add(ReviewEvent(source_key=f"one-{uuid4()}", source="google_ads", occurred_at=at, evidence_type="api",
                       actor="manager@example.com", title="UPDATE", detail="campaign budget", payload={}))
    db.flush()
    with admin_client(db) as http:
        body = http.get("/api/business-review/events/summary?date_from=2026-11-05&date_to=2026-11-05").json()
        assert body["total"] >= 61
        bulk = [g for g in body["groups"] if g["actor"] == "Bulk Actions" and g["title"] == "REMOVE"]
        assert bulk and bulk[0]["bulk"] and bulk[0]["count"] >= 60
        assert any(e["actor"] == "manager@example.com" for e in body["events"])
        assert all(e["actor"] != "Bulk Actions" or e["title"] != "REMOVE" for e in body["events"])
        assert http.get("/api/business-review/events/summary?date_from=2026-11-06&date_to=2026-11-05").status_code == 400
        rows = http.get("/api/business-review/events?date_from=2026-11-05&date_to=2026-11-05&limit=5").json()["rows"]
        assert len(rows) == 5


def test_advestiq_reports_are_replaced_per_day(db):
    with admin_client(db) as http:
        first = {"kind": "daily", "report_date": "2026-11-06", "title": "Πρωινή αναφορά", "markdown": "# Α"}
        created = http.post("/api/advestiq/reports", json=first).json()["data"]
        updated = http.post("/api/advestiq/reports", json={**first, "markdown": "# Β", "summary": "νέα"}).json()["data"]
        assert created["id"] == updated["id"]
        listed = http.get("/api/advestiq/reports?kind=daily").json()["data"]["rows"]
        assert any(row["id"] == created["id"] and row["summary"] == "νέα" for row in listed)
        assert http.get(f"/api/advestiq/reports/{created['id']}").json()["data"]["markdown"] == "# Β"
        assert http.get(f"/api/advestiq/reports/{uuid4()}").status_code == 404
        assert http.post("/api/advestiq/reports", json={**first, "markdown": ""}).status_code == 422


# The key may write on exactly three routes. Everything it could not write before stays forbidden.
@pytest.mark.parametrize(("method", "path", "allowed"), [
    ("POST", "/api/advestiq/reports", True),
    ("PUT", "/api/advestiq/proposals/P-009", True),
    ("PUT", "/api/advestiq/proposals/d-03", True),
    ("POST", "/api/advestiq/proposals/P-009/notes", True),
    ("PUT", "/api/advestiq/reports", False),
    ("DELETE", "/api/advestiq/reports", False),
    ("PATCH", "/api/advestiq/proposals/P-009/status", False),
    ("PUT", "/api/advestiq/proposals/P-009/status", False),
    ("POST", "/api/advestiq/proposals/P-009/status", False),
    ("POST", "/api/advestiq/proposals/P-009", False),
    ("PATCH", "/api/advestiq/proposals/P-009", False),
    ("DELETE", "/api/advestiq/proposals/P-009", False),
    ("POST", "/api/advestiq/proposals", False),
    ("PUT", "/api/advestiq/proposals", False),
    ("PUT", "/api/advestiq/proposals/P-009/notes", False),
    ("DELETE", "/api/advestiq/proposals/P-009/notes", False),
    ("POST", "/api/advestiq/proposals/P-009/notes/1", False),
    ("PUT", "/api/advestiq/proposals/P-009/", False),
    ("PUT", "/api/advestiq/proposals/P-009/../../../sync/run", False),
    ("PUT", "/api/advestiq/proposals/P%2F009", False),
    ("PUT", "/api/advestiq/proposals/" + "P" * 21, False),
    ("POST", "/api/advestiq/reports/extra", False),
    ("POST", "/api/dashboard/summary", False),
    ("POST", "/api/business-review/events", False),
    ("POST", "/api/business-review/history", False),
    ("PUT", "/api/settings/integrations/google_ads", False),
    ("POST", "/api/sync/run", False),
])
def test_advestiq_write_rules(method, path, allowed):
    assert deps.advestiq_may_write(method, path) is allowed


def real_routes_with_key(monkeypatch):
    monkeypatch.setattr(deps.settings, "advestiq_api_key_sha256", hashlib.sha256(KEY.encode()).hexdigest())
    application = FastAPI()
    for module in (advestiq, business_review, sync):
        application.include_router(module.router, prefix="/api")
    application.dependency_overrides[get_db] = lambda: None
    http = TestClient(application)
    http.headers[deps.ADVESTIQ_KEY_HEADER] = KEY
    return http


@pytest.mark.parametrize(("method", "path"), [
    ("PATCH", "/api/advestiq/proposals/P-009/status"),
    ("POST", "/api/business-review/events"),
    ("POST", "/api/business-review/history"),
    ("POST", "/api/business-review/jobs/retry"),
    ("POST", "/api/business-review/jobs/pause"),
    ("POST", "/api/business-review/reports"),
    ("POST", "/api/business-review/compare"),
    ("POST", "/api/sync/run"),
    ("GET", "/api/sync/runs"),
])
def test_advestiq_key_is_refused_on_the_real_routes(monkeypatch, method, path):
    http = real_routes_with_key(monkeypatch)
    assert http.request(method, path, json={"status": "done"}).status_code == 403
