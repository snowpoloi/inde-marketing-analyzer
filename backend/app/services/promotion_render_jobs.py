"""Keep encoding off the API request path and serialize local renders."""
import hashlib
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from sqlalchemy import select, text, update

from app.core.config import settings
from app.models import PromotionAsset, PromotionCampaign, PromotionRenderJob
from app.services.promotion_render import RenderError, inde_client, live_products, render_video

ACTIVE_RENDER = ("queued", "running")
LOCK_ID = 80102027
log = logging.getLogger(__name__)


def process_render_job(db):
    with db.get_bind().engine.connect() as lock:
        if not lock.scalar(text("SELECT pg_try_advisory_lock(:id)"), {"id": LOCK_ID}):
            return
        try:
            _process_locked(db)
        finally:
            lock.execute(text("SELECT pg_advisory_unlock(:id)"), {"id": LOCK_ID})


def _process_locked(db):
    now = datetime.now(timezone.utc)
    db.execute(update(PromotionRenderJob).where(PromotionRenderJob.status == "running")
               .values(status="failed", error="Η δημιουργία διακόπηκε. Δοκίμασε ξανά.", finished_at=now))
    job = db.scalar(select(PromotionRenderJob).where(PromotionRenderJob.status == "queued")
                    .order_by(PromotionRenderJob.created_at, PromotionRenderJob.id).limit(1))
    if not job:
        db.commit()
        return
    job.status, job.started_at = "running", now
    job_id, campaign_id, ratio, prices = job.id, job.campaign_id, job.aspect_ratio, job.prices
    campaign = db.get(PromotionCampaign, campaign_id)
    brief, queued_at = campaign.brief, job.created_at
    db.commit()
    root = Path(settings.promotion_media_dir).resolve()
    target = root / f"{job_id}.mp4"
    moved = False
    try:
        if now - queued_at > timedelta(minutes=10):
            raise RenderError("Η επιβεβαίωση τιμής έληξε. Έλεγξε ξανά τις τιμές.")
        root.mkdir(parents=True, exist_ok=True)
        with inde_client() as client, TemporaryDirectory(prefix=".render-", dir=root) as work:
            products = live_products(client, brief)
            if {p["sku"]: p["price_gross"] for p in products} != prices:
                raise RenderError("Η τιμή άλλαξε στην INDE. Έλεγξε ξανά την τιμή πριν τη δημιουργία.")
            video = render_video(client, brief, products, ratio, Path(work))
            with video.open("rb") as stream:
                digest = hashlib.file_digest(stream, "sha256").hexdigest()
            size = video.stat().st_size
            campaign = db.scalar(select(PromotionCampaign).where(PromotionCampaign.id == campaign_id).with_for_update())
            os.replace(video, target)
            moved = True
            db.add(PromotionAsset(id=job_id, campaign_id=campaign_id, aspect_ratio=ratio, byte_size=size,
                                  filename=f"inde-{ratio.replace(':', 'x')}.mp4", sha256=digest,
                                  status="needs_review", review={}))
            campaign.status = "needs_review"
            job.status, job.finished_at = "success", datetime.now(timezone.utc)
        db.commit()
    except Exception as exc:
        db.rollback()
        if moved:
            target.unlink(missing_ok=True)
        job = db.get(PromotionRenderJob, job_id)
        if job:
            job.status, job.finished_at = "failed", datetime.now(timezone.utc)
            job.error = str(exc) if isinstance(exc, RenderError) else "Η δημιουργία βίντεο απέτυχε. Δοκίμασε ξανά."
            db.commit()
        if not isinstance(exc, RenderError):
            log.error("Unexpected promotion render failure %s (%s)", job_id, type(exc).__name__)
