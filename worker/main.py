from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from apscheduler.schedulers.blocking import BlockingScheduler

from app.core.config import settings
from app.db.session import SessionLocal
from app.services.constants import PROVIDERS
from app.services.sync_service import run_many
from app.services.supplier_gmail_jobs import process_gmail_jobs
from app.services.supplier_catalog_service import process_supplier_catalog


def supplier_gmail_sync() -> None:
    with SessionLocal() as db:
        process_gmail_jobs(db)


def daily_sync() -> None:
    tz = ZoneInfo(settings.sync_timezone)
    target_day = (datetime.now(tz) - timedelta(days=1)).date()
    with SessionLocal() as db:
        run_many(db, list(PROVIDERS.keys()), target_day, target_day, sync_type="scheduled")


def supplier_catalog_sync() -> None:
    with SessionLocal() as db:
        process_supplier_catalog(db)


def main() -> None:
    scheduler = BlockingScheduler(timezone=settings.sync_timezone)
    scheduler.add_job(daily_sync, "cron", hour=settings.sync_daily_hour, minute=0, id="daily-marketing-sync")
    scheduler.add_job(supplier_gmail_sync, "interval", seconds=45, id="supplier-gmail-readonly",
                      max_instances=1, coalesce=True, next_run_time=datetime.now(ZoneInfo(settings.sync_timezone)))
    scheduler.add_job(supplier_catalog_sync, "interval", seconds=45, id="supplier-catalog-readonly",
                      max_instances=1, coalesce=True, next_run_time=datetime.now(ZoneInfo(settings.sync_timezone)))
    print(
        f"INDE Marketing Analyzer worker started. Daily sync at {settings.sync_daily_hour}:00 {settings.sync_timezone}.",
        flush=True,
    )
    scheduler.start()


if __name__ == "__main__":
    main()
