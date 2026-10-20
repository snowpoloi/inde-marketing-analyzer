"""Bounded, resumable read-only acquisition. No provider mutation endpoints."""
import hashlib
import json
import re
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select, text, update
from sqlalchemy.dialects.postgresql import insert

from app.connectors.google_ads import GoogleAdsConnector
from app.connectors.meta_ads import MetaAdsConnector
from app.core.redaction import redact_sensitive
from app.models import IntegrationSetting, ReviewEvent, ReviewJob, SyncRun
from app.services.sync_service import run_provider_sync

HISTORICAL_PROVIDERS = ("google_ads", "meta_ads", "tiktok_ads", "ga4", "merchant_center",
                        "search_console", "opencart", "aade")


def today():
    return datetime.now(ZoneInfo("Europe/Athens")).date()


def windows(start, end, days=14):
    while start <= end:
        stop = min(end, start + timedelta(days=days - 1))
        yield start, stop
        start = stop + timedelta(days=1)


def queue_job(db, provider, kind, start, end, *, status="queued", error=None):
    statement = insert(ReviewJob).values(provider=provider, kind=kind, date_from=start,
        date_to=end, status=status, error=error, records=0, attempts=0, meta={})
    return int(db.scalar(statement.on_conflict_do_nothing(
        constraint="uq_review_job_window").returning(ReviewJob.id)) is not None)


def enqueue_history(db, start, end, providers):
    if start > end or (end - start).days > 730 or end > today():
        raise ValueError("Choose a historical range of at most 731 days, ending no later than today.")
    if not providers or set(providers) - set(HISTORICAL_PROVIDERS):
        raise ValueError("Unsupported history provider.")
    created = 0
    for provider in dict.fromkeys(providers):
        for a, b in windows(start, end):
            created += queue_job(db, provider, "metrics", a, b)
        if provider in ("google_ads", "meta_ads"):
            history_start = start
            if provider == "google_ads":
                history_start = max(start, today() - timedelta(days=28))
                if start < history_start:
                    created += queue_job(db, provider, "changes", start, min(end, history_start - timedelta(days=1)),
                        status="unavailable", error="API retention limit. Import Google Ads Change History export for this period.")
            for a, b in windows(history_start, end):
                created += queue_job(db, provider, "changes", a, b)
        if provider == "tiktok_ads":
            created += queue_job(db, provider, "changes", start, end, status="unavailable",
                error="TikTok change-log export required; this connector retrieves reporting metrics only.")
    db.commit()
    return created


def store_event(db, *, source, occurred_at, title, evidence_type, actor=None,
                object_id=None, detail="", reference_url=None, payload=None, external_id=None):
    safe_payload = sanitize_evidence(payload or {})
    identity = external_id or json.dumps([str(occurred_at), title, actor, object_id, detail, safe_payload],
                                        ensure_ascii=False, sort_keys=True)
    key = hashlib.sha256(f"{source}:{evidence_type}:{identity}".encode()).hexdigest()
    return int(db.scalar(insert(ReviewEvent).values(source_key=key, source=source,
        occurred_at=occurred_at, title=sanitize_evidence(title)[:500], evidence_type=evidence_type,
        actor=sanitize_evidence(actor), object_id=object_id, detail=sanitize_evidence(detail),
        reference_url=sanitize_evidence(reference_url), payload=safe_payload).on_conflict_do_nothing(
            index_elements=["source_key"]).returning(ReviewEvent.id)) is not None)


def sanitize_evidence(value):
    if isinstance(value, dict):
        return {k: "[REDACTED]" if any(word in k.lower() for word in
                ("token", "secret", "password", "api_key", "authorization", "developer_token"))
                else sanitize_evidence(v) for k, v in value.items()}
    if isinstance(value, list):
        return [sanitize_evidence(v) for v in value]
    if not isinstance(value, str):
        return value
    value = redact_sensitive(value)
    value = re.sub(r"(https?://)[^/\s:@]+:[^/\s@]+@", r"\1[REDACTED]@", value, flags=re.I)
    return re.sub(r'([?&](?:[^=&\s]*(?:token|secret|password|api_key)[^=&\s]*)=)[^&\s"<>]+',
                  r"\1[REDACTED]", value, flags=re.I)


def collect_changes(db, provider, start, end):
    integration = db.scalar(select(IntegrationSetting).where(IntegrationSetting.provider == provider))
    if not integration or not integration.is_enabled:
        raise ValueError("Integration is disabled; credentials have not been changed.")
    config = integration.config or {}
    rows = (GoogleAdsConnector(config) if provider == "google_ads" else MetaAdsConnector(config)).fetch_changes(start, end)
    count = 0
    for row in rows:
        stamp = row.get("change_date_time") or row.get("event_time")
        occurred = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
        if occurred.tzinfo is None:
            occurred = occurred.replace(tzinfo=ZoneInfo(str(
                row.get("account_time_zone") or config.get("account_timezone") or "Europe/Athens")))
        if not start <= occurred.date() <= end:
            continue
        count += store_event(db, source=provider, occurred_at=occurred,
            title=str(row.get("resource_change_operation") or row.get("event_type") or "Change"),
            evidence_type="api", actor=row.get("user_email") or row.get("actor_name"),
            object_id=str(row.get("campaign") or row.get("change_resource_name") or row.get("object_id") or ""),
            detail=str(row.get("changed_fields") or row.get("object_name") or ""),
            payload=row, external_id=row.get("resource_name"))
    return count


def schedule_recent_history(db):
    for provider in ("google_ads", "meta_ads"):
        setting = db.scalar(select(IntegrationSetting).where(IntegrationSetting.provider == provider))
        if setting and setting.is_enabled:
            # Re-read recent days because API events can arrive with a delay.
            queue_job(db, provider, "changes", today() - timedelta(days=3), today())
    db.commit()


def process_review_job(db):
    # A separate connection keeps the session-level lock across importer commits.
    with db.get_bind().engine.connect() as lock:
        if not lock.scalar(text("SELECT pg_try_advisory_lock(80102026)")):
            return
        try:
            now = datetime.now(timezone.utc)
            db.execute(update(ReviewJob).where(ReviewJob.status == "running",
                ReviewJob.started_at < now - timedelta(hours=2)).values(status="failed",
                    error="Worker interrupted. Retry this window.", finished_at=now))
            db.commit()
            # Do not compete with the normal application sync or retry providers in tight loops.
            if db.scalar(select(SyncRun.id).where(SyncRun.status == "running",
                SyncRun.started_at > now - timedelta(hours=2)).limit(1)):
                return
            job = db.scalar(select(ReviewJob).where(ReviewJob.status == "queued")
                .order_by((ReviewJob.kind == "changes").desc(), ReviewJob.date_from.desc(),
                          ReviewJob.created_at).limit(1).with_for_update(skip_locked=True))
            if not job:
                return
            job.status, job.started_at, job.error = "running", now, None
            job.attempts += 1
            db.commit()
            try:
                if job.kind == "changes":
                    job.records = collect_changes(db, job.provider, job.date_from, job.date_to)
                    job.status = "success"
                    job.meta = {"coverage": "API-returned events only; retention/permissions may limit history."}
                else:
                    run = run_provider_sync(db, job.provider, job.date_from, job.date_to, sync_type="backfill")
                    job.status, job.records, job.error = run.status, run.records_processed, run.error_message
                    job.meta = {"sync_run_id": str(run.id), **(run.meta or {})}
                job.finished_at = datetime.now(timezone.utc)
                db.commit()
            except Exception as exc:
                db.rollback()
                job.status, job.error = "failed", redact_sensitive(str(exc))[:2000]
                job.finished_at = datetime.now(timezone.utc)
                db.commit()
        finally:
            lock.execute(text("SELECT pg_advisory_unlock(80102026)"))
