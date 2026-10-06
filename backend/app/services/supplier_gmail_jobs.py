from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.connectors.supplier_gmail import GmailReadError
from app.core.config import settings
from app.models import SupplierGmailJob
from app.schemas.suppliers import SupplierGmailSyncRequest
from app.services.supplier_gmail_service import _lock, sync_supplier_gmail


def gmail_configured() -> bool:
    return bool(settings.supplier_gmail_enabled and settings.supplier_gmail_client_id
                and settings.supplier_gmail_client_secret and settings.supplier_gmail_refresh_token)


def job_data(job: SupplierGmailJob | None) -> dict | None:
    if job is None:
        return None
    return {"id": str(job.id), "mode": job.mode, "status": job.status,
            "date_from": job.date_from.isoformat(), "date_to": job.date_to.isoformat(),
            "pages": job.pages, "counts": job.counts, "error": job.error,
            "created_at": job.created_at.isoformat(),
            "finished_at": job.finished_at.isoformat() if job.finished_at else None}


def latest_job(db: Session) -> SupplierGmailJob | None:
    return db.scalar(select(SupplierGmailJob).order_by(SupplierGmailJob.created_at.desc()).limit(1))


def enqueue_gmail(db: Session, request: SupplierGmailSyncRequest, *, mode: str = "manual") -> SupplierGmailJob:
    if not gmail_configured():
        raise GmailReadError("Read-only Gmail credentials are not configured on the server.")
    _lock(db)
    job = db.scalar(select(SupplierGmailJob).where(
        SupplierGmailJob.status.in_(["queued", "running"]),
        SupplierGmailJob.date_from == request.date_from, SupplierGmailJob.date_to == request.date_to))
    if not job:
        job = SupplierGmailJob(mode=mode, date_from=request.date_from, date_to=request.date_to,
                               page_token=request.page_token, status="queued")
        db.add(job)
    db.commit()
    return job


def _enqueue_automatic(db: Session, now: datetime):
    if not settings.supplier_gmail_auto_enabled:
        return
    _lock(db)
    if db.scalar(select(SupplierGmailJob.id).where(SupplierGmailJob.status.in_(["queued", "running"]))):
        db.commit()
        return
    previous = db.scalar(select(SupplierGmailJob).where(SupplierGmailJob.mode == "automatic")
                         .order_by(SupplierGmailJob.created_at.desc()).limit(1))
    if previous and (previous.finished_at or previous.created_at) > now - timedelta(minutes=settings.supplier_gmail_interval_minutes):
        db.commit()
        return
    today = now.astimezone(ZoneInfo("Europe/Athens")).date()
    completed = db.scalar(select(SupplierGmailJob).where(
        SupplierGmailJob.mode == "automatic", SupplierGmailJob.status == "success")
        .order_by(SupplierGmailJob.date_to.desc()).limit(1))
    start = min(today, completed.date_to - timedelta(days=2)) if completed else today - timedelta(days=30)
    end = min(today, start + timedelta(days=90))
    db.add(SupplierGmailJob(mode="automatic", status="queued", date_from=start, date_to=end))
    db.commit()


def process_gmail_jobs(db: Session, now: datetime | None = None):
    """One bounded page per tick; a session lock also protects multi-worker deployments."""
    if not gmail_configured():
        return
    now = now or datetime.now(timezone.utc)
    # Separate connection keeps this lock through the per-message database commits.
    with db.get_bind().engine.connect() as guard:
        acquired = guard.scalar(text("SELECT pg_try_advisory_lock(7419301206)"))
        try:
            if not acquired:
                return
            _enqueue_automatic(db, now)
            job = db.scalar(select(SupplierGmailJob).where(
                SupplierGmailJob.status.in_(["queued", "running"]),
                (SupplierGmailJob.next_attempt_at.is_(None)) | (SupplierGmailJob.next_attempt_at <= now))
                .order_by(SupplierGmailJob.created_at).limit(1))
            if job is None:
                return
            job.status, job.error = "running", None
            db.commit()
            previous_progress = len(job.completed_message_ids)
            def checkpoint(message_id: str, delta: dict):
                job.completed_message_ids = [*job.completed_message_ids, message_id]
                job.counts = {key: job.counts.get(key, 0) + value for key, value in delta.items()}
            try:
                result = sync_supplier_gmail(db, SupplierGmailSyncRequest(
                    date_from=job.date_from, date_to=job.date_to, page_token=job.page_token),
                    completed_message_ids=set(job.completed_message_ids), on_message=checkpoint)
                job.pages += 1
                job.page_token = result["next_page_token"]
                job.completed_message_ids = []
                job.attempts, job.next_attempt_at = 0, None
                if not job.page_token:
                    job.status, job.finished_at = "success", now
                db.commit()
            except Exception as exc:
                db.rollback()
                db.refresh(job)
                # Time-budget exhaustion with progress is resumable, not a failed read.
                progress = len(job.completed_message_ids) > previous_progress
                budget = isinstance(exc, GmailReadError) and "time budget" in str(exc)
                job.attempts += 0 if budget and progress else 1
                job.error = str(exc) if isinstance(exc, GmailReadError) else "Document staging failed; manual review required."
                if job.attempts >= 3:
                    job.status, job.finished_at = "failed", now
                else:
                    job.next_attempt_at = now + timedelta(seconds=60 * max(1, job.attempts))
                db.commit()
        finally:
            if acquired:
                guard.execute(text("SELECT pg_advisory_unlock(7419301206)"))
