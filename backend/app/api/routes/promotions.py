import hashlib
import io
import os
from datetime import date, datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import require_admin
from app.core.config import settings
from app.db.session import get_db
from app.models import PromotionAsset, PromotionCampaign, User
from app.schemas.promotions import Aspect, PromotionInput, PromotionReview
from app.services.promotion_service import candidates, export_package, make_brief, serialize_campaign

router = APIRouter(prefix="/promotions", tags=["promotions"])
MAX_VIDEO_BYTES = 64 * 1024 * 1024


def owned_campaign(db, campaign_id, user, *, lock=False):
    query = select(PromotionCampaign).where(PromotionCampaign.id == campaign_id, PromotionCampaign.owner_id == user.id)
    row = db.scalar(query.with_for_update() if lock else query)
    if not row:
        raise HTTPException(404, detail="Η καμπάνια δεν βρέθηκε.")
    return row


@router.get("/products")
def products(date_from: date, date_to: date, search: str = "", minimum_margin: float = 18,
             only_eligible: bool = True, _: User = Depends(require_admin), db: Session = Depends(get_db)):
    if len(search) > 150 or not 0 <= minimum_margin <= 100:
        raise HTTPException(422, detail="Invalid product filters.")
    try:
        return candidates(db, date_from, date_to, search, minimum_margin, only_eligible)
    except ValueError as exc:
        raise HTTPException(422, detail=str(exc)) from exc


@router.get("/campaigns")
def campaigns(user: User = Depends(require_admin), db: Session = Depends(get_db)):
    rows = db.scalars(select(PromotionCampaign).where(PromotionCampaign.owner_id == user.id)
                      .order_by(PromotionCampaign.created_at.desc()).limit(100)).all()
    return {"rows": [{"id": str(r.id), "title": r.title, "status": r.status,
                     "created_at": r.created_at} for r in rows]}


@router.post("/campaigns", status_code=201)
def create(payload: PromotionInput, user: User = Depends(require_admin), db: Session = Depends(get_db)):
    try:
        brief = make_brief(db, payload)
    except ValueError as exc:
        raise HTTPException(422, detail=str(exc)) from exc
    row = PromotionCampaign(owner_id=user.id, title=payload.title.strip(), status="draft", brief=brief)
    db.add(row)
    db.commit()
    return serialize_campaign(db, row)


@router.get("/campaigns/{campaign_id}")
def detail(campaign_id: UUID, user: User = Depends(require_admin), db: Session = Depends(get_db)):
    return serialize_campaign(db, owned_campaign(db, campaign_id, user))


@router.get("/campaigns/{campaign_id}/package")
def package(campaign_id: UUID, user: User = Depends(require_admin), db: Session = Depends(get_db)):
    row = owned_campaign(db, campaign_id, user)
    try:
        content = export_package(row.brief)
    except ValueError as exc:
        raise HTTPException(503, detail=str(exc)) from exc
    return StreamingResponse(io.BytesIO(content), media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="inde-promotion-{row.id}.zip"',
                 "Cache-Control": "no-store"})


@router.post("/campaigns/{campaign_id}/assets", status_code=201)
async def upload(campaign_id: UUID, aspect_ratio: Aspect = Form(...), file: UploadFile = File(...),
                 user: User = Depends(require_admin), db: Session = Depends(get_db)):
    campaign = owned_campaign(db, campaign_id, user, lock=True)
    if aspect_ratio not in campaign.brief["parameters"]["formats"]:
        raise HTTPException(422, detail="Το format δεν υπάρχει στην καμπάνια.")
    root = Path(settings.promotion_media_dir).resolve()
    root.mkdir(parents=True, exist_ok=True)
    asset_id = uuid4()
    temporary, target = root / f"{asset_id}.upload", root / f"{asset_id}.mp4"
    size, digest = 0, hashlib.sha256()
    try:
        with temporary.open("xb") as output:
            first = True
            while chunk := await file.read(1024 * 1024):
                if first and (len(chunk) < 12 or chunk[4:8] != b"ftyp"):
                    raise HTTPException(422, detail="Απαιτείται αρχείο MP4.")
                first = False
                size += len(chunk)
                if size > MAX_VIDEO_BYTES:
                    raise HTTPException(413, detail="Μέγιστο μέγεθος MP4: 64 MB.")
                digest.update(chunk)
                output.write(chunk)
        if not size:
            raise HTTPException(422, detail="Το αρχείο είναι κενό.")
        duplicate = db.scalar(select(PromotionAsset).where(PromotionAsset.campaign_id == campaign_id,
            PromotionAsset.aspect_ratio == aspect_ratio, PromotionAsset.sha256 == digest.hexdigest()))
        if duplicate:
            return serialize_campaign(db, campaign)
        os.replace(temporary, target)
        db.add(PromotionAsset(id=asset_id, campaign_id=campaign_id, aspect_ratio=aspect_ratio,
            filename=Path(file.filename or "video.mp4").name[:180], byte_size=size, sha256=digest.hexdigest(),
            status="needs_review", review={}))
        campaign.status = "needs_review"
        db.commit()
        return serialize_campaign(db, campaign)
    except Exception:
        db.rollback()
        target.unlink(missing_ok=True)
        raise
    finally:
        temporary.unlink(missing_ok=True)
        await file.close()


def owned_asset(db, asset_id, user, *, lock=False):
    asset = db.get(PromotionAsset, asset_id)
    if not asset:
        raise HTTPException(404, detail="Το βίντεο δεν βρέθηκε.")
    campaign = owned_campaign(db, asset.campaign_id, user, lock=lock)
    return campaign, asset


@router.get("/assets/{asset_id}/content")
def content(asset_id: UUID, user: User = Depends(require_admin), db: Session = Depends(get_db)):
    _, asset = owned_asset(db, asset_id, user)
    path = Path(settings.promotion_media_dir).resolve() / f"{asset.id}.mp4"
    if not path.is_file():
        raise HTTPException(404, detail="Το αρχείο βίντεο δεν είναι διαθέσιμο στον αποθηκευτικό χώρο.")
    return FileResponse(path, media_type="video/mp4", filename=f"inde-{asset.aspect_ratio.replace(':', 'x')}-{asset.id}.mp4",
                        headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"})


@router.post("/assets/{asset_id}/approve")
def approve(asset_id: UUID, payload: PromotionReview, user: User = Depends(require_admin), db: Session = Depends(get_db)):
    campaign, asset = owned_asset(db, asset_id, user, lock=True)
    asset.status = "approved"
    asset.review = {**payload.model_dump(), "reviewed_by": str(user.id), "reviewed_at": datetime.now(timezone.utc).isoformat()}
    db.flush()
    assets = db.scalars(select(PromotionAsset).where(PromotionAsset.campaign_id == campaign.id)
                        .order_by(PromotionAsset.created_at.desc(), PromotionAsset.id)).all()
    latest = {}
    for item in assets:
        latest.setdefault(item.aspect_ratio, item)
    campaign.status = "approved" if all(latest.get(ratio) and latest[ratio].status == "approved"
        for ratio in campaign.brief["parameters"]["formats"]) else "needs_review"
    db.commit()
    return serialize_campaign(db, campaign)
