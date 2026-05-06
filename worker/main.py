from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from apscheduler.schedulers.blocking import BlockingScheduler

from app.core.config import settings
from app.db.session import SessionLocal
from app.services.constants import PROVIDERS
from app.services.sync_service import run_many


def daily_sync() -> None:
    tz = ZoneInfo(settings.sync_timezone)
    target_day = (datetime.now(tz) - timedelta(days=1)).date()
    with SessionLocal() as db:
        run_many(db, list(PROVIDERS.keys()), target_day, target_day, sync_type="scheduled")


def main() -> None:
    scheduler = BlockingScheduler(timezone=settings.sync_timezone)
    scheduler.add_job(daily_sync, "cron", hour=settings.sync_daily_hour, minute=0, id="daily-marketing-sync")
    print(
        f"INDE Marketing Analyzer worker started. Daily sync at {settings.sync_daily_hour}:00 {settings.sync_timezone}.",
        flush=True,
    )
    scheduler.start()


if __name__ == "__main__":
    main()

