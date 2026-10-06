import base64
from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select, text

from app.connectors.supplier_gmail import GmailReadError, MAILBOX
from app.core.config import settings
from app.models import SupplierDocument, SupplierGmailJob, SupplierGmailSource, SupplierProductCost
from app.schemas.suppliers import SupplierGmailSyncRequest
from app.services.supplier_gmail_jobs import enqueue_gmail, process_gmail_jobs
from test_supplier_gmail import HTML, oauth


@pytest.fixture
def configured(oauth, monkeypatch):
    monkeypatch.setattr(settings, "supplier_gmail_auto_enabled", False)


def request():
    return SupplierGmailSyncRequest(date_from=date(2026, 10, 1), date_to=date(2026, 10, 6))


def test_api_queues_without_google_io_and_deduplicates_active_request(db, configured, monkeypatch):
    from test_supplier_api import client
    monkeypatch.setattr("app.services.supplier_gmail_service.SupplierGmailReader",
                        lambda: pytest.fail("HTTP handler must not connect to Gmail"))
    with client(db, True) as http:
        first = http.post("/api/suppliers/gmail/sync", json=request().model_dump(mode="json"))
        second = http.post("/api/suppliers/gmail/sync", json=request().model_dump(mode="json"))
        assert first.status_code == second.status_code == 202
        assert first.json()["data"]["job"]["id"] == second.json()["data"]["job"]["id"]
        assert first.json()["data"]["job"]["status"] == "queued"
        assert http.get("/api/suppliers/gmail").json()["data"]["job"]["status"] == "queued"
    assert db.scalar(select(func.count()).select_from(SupplierDocument)) == 0


def test_worker_reads_every_page_without_financial_acceptance(db, configured, monkeypatch):
    class FakeReader:
        def authorize(self): pass
        def close(self): pass
        def list_messages(self, start, end, token):
            return {"messages": [{"id": "second" if token else "first"}],
                    **({} if token else {"nextPageToken": "next"})}
        def message(self, message_id):
            return {"payload": {"headers": [{"name": "From", "value": "orders@megapap.com"}],
                    "mimeType": "text/html", "body": {"data": base64.urlsafe_b64encode(HTML).decode()}}}
    monkeypatch.setattr("app.services.supplier_gmail_service.SupplierGmailReader", FakeReader)
    job = enqueue_gmail(db, request())
    process_gmail_jobs(db)
    assert job.status == "running" and job.page_token == "next" and job.pages == 1
    db.expire_all()
    process_gmail_jobs(db)
    assert job.status == "success" and job.pages == 2
    assert job.counts["messages"] == 2 and job.counts["pending"] == job.counts["duplicate"] == 1
    assert db.scalar(select(func.count()).select_from(SupplierGmailSource)) == 2
    assert db.scalar(select(func.count()).select_from(SupplierDocument)) == 0
    assert db.scalar(select(func.count()).select_from(SupplierProductCost)) == 0


def test_partial_page_checkpoints_resume_and_failures_are_bounded(db, configured, monkeypatch):
    now = datetime.now(timezone.utc)
    job = enqueue_gmail(db, request())
    calls = []
    def partial(db, request, *, completed_message_ids, on_message):
        calls.append(completed_message_ids.copy())
        if not completed_message_ids:
            on_message("first", {"messages": 1, "pending": 1})
            db.commit()
        raise GmailReadError("Gmail read time budget reached; retry to continue previously staged messages.")
    monkeypatch.setattr("app.services.supplier_gmail_jobs.sync_supplier_gmail", partial)
    process_gmail_jobs(db, now)
    assert job.completed_message_ids == ["first"] and job.attempts == 0
    for minute in (2, 4, 7):
        process_gmail_jobs(db, now + timedelta(minutes=minute))
    assert job.status == "failed" and job.attempts == 3
    assert job.counts == {"messages": 1, "pending": 1}
    assert calls == [set(), {"first"}, {"first"}, {"first"}]


def test_automatic_window_overlap_and_interval(db, configured, monkeypatch):
    monkeypatch.setattr(settings, "supplier_gmail_auto_enabled", True)
    now = datetime.now(timezone.utc)
    def empty(db, request, **kwargs): return {"next_page_token": None}
    monkeypatch.setattr("app.services.supplier_gmail_jobs.sync_supplier_gmail", empty)
    process_gmail_jobs(db, now)
    first = db.scalar(select(SupplierGmailJob))
    assert first.mode == "automatic" and first.status == "success"
    assert (first.date_to - first.date_from).days == 30
    process_gmail_jobs(db, now + timedelta(minutes=1))
    assert db.scalar(select(func.count()).select_from(SupplierGmailJob)) == 1
    process_gmail_jobs(db, now + timedelta(minutes=16))
    jobs = db.scalars(select(SupplierGmailJob).order_by(SupplierGmailJob.created_at)).all()
    assert len(jobs) == 2 and jobs[1].date_from == first.date_to - timedelta(days=2)


def test_single_worker_lock_and_disabled_credentials(db, configured, monkeypatch):
    engine = db.get_bind().engine
    with engine.connect() as other_worker:
        other_worker.execute(text("SELECT pg_advisory_lock(7419301206)"))
        try:
            process_gmail_jobs(db)
            assert db.scalar(select(func.count()).select_from(SupplierGmailJob)) == 0
        finally:
            other_worker.execute(text("SELECT pg_advisory_unlock(7419301206)"))
    monkeypatch.setattr(settings, "supplier_gmail_enabled", False)
    with pytest.raises(GmailReadError): enqueue_gmail(db, request())
    process_gmail_jobs(db)
    assert db.scalar(select(func.count()).select_from(SupplierGmailJob)) == 0
