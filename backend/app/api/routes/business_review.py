import csv
import io
from datetime import date, datetime
from typing import Literal
from urllib.parse import parse_qs, urlsplit
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel, Field, ValidationError, field_validator
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.api.deps import require_admin
from app.db.session import get_db
from app.models import ReviewEvent, ReviewJob, ReviewReport, User
from app.services.business_review_jobs import HISTORICAL_PROVIDERS, enqueue_history, store_event
from app.services.business_review_service import build_review, serialize_event

router = APIRouter(prefix="/business-review", tags=["business-review"])


class ReviewInput(BaseModel):
    date_from: date
    date_to: date
    baseline_from: date
    baseline_to: date
    with_costs: bool = False


class HistoryInput(BaseModel):
    date_from: date
    date_to: date
    providers: list[str] = Field(default_factory=lambda: list(HISTORICAL_PROVIDERS), max_length=8)


class EvidenceInput(BaseModel):
    source: Literal["google_ads", "meta_ads", "tiktok_ads", "shoply", "merchant_center", "tracking", "catalog", "business"]
    occurred_at: datetime
    title: str = Field(min_length=1, max_length=500)
    detail: str = Field(default="", max_length=12000)
    actor: str | None = Field(default=None, max_length=255)
    object_id: str | None = Field(default=None, max_length=255)
    reference_url: str | None = Field(default=None, max_length=2000)
    evidence_type: Literal["manual", "email", "export"] = "manual"

    @field_validator("occurred_at")
    @classmethod
    def local_time(cls, value):
        return value if value.tzinfo else value.replace(tzinfo=ZoneInfo("Europe/Athens"))

    @field_validator("reference_url")
    @classmethod
    def public_reference(cls, value):
        if not value:
            return None
        parts = urlsplit(value)
        if parts.scheme != "https" or not parts.hostname or parts.username or parts.password:
            raise ValueError("Use an HTTPS evidence link without embedded credentials.")
        if any(any(word in key.lower() for word in ("token", "secret", "password", "api_key"))
               for key in parse_qs(parts.query)):
            raise ValueError("Evidence links must not contain tokens or secrets.")
        return value


@router.post("/compare")
def compare(payload: ReviewInput, _: User = Depends(require_admin), db: Session = Depends(get_db)):
    try:
        return build_review(db, payload.date_from, payload.date_to, payload.baseline_from,
                            payload.baseline_to, with_costs=payload.with_costs)
    except ValueError as exc:
        raise HTTPException(422, detail=str(exc)) from exc


@router.post("/history")
def history(payload: HistoryInput, _: User = Depends(require_admin), db: Session = Depends(get_db)):
    try:
        return {"queued": enqueue_history(db, payload.date_from, payload.date_to, payload.providers)}
    except ValueError as exc:
        raise HTTPException(422, detail=str(exc)) from exc


@router.get("/jobs")
def jobs(_: User = Depends(require_admin), db: Session = Depends(get_db)):
    rows = db.scalars(select(ReviewJob).order_by(ReviewJob.created_at.desc()).limit(1000)).all()
    counts = dict(db.execute(select(ReviewJob.status, func.count()).group_by(ReviewJob.status)).all())
    return {"counts": counts, "rows": [{"id": str(r.id), "provider": r.provider, "kind": r.kind,
        "date_from": r.date_from, "date_to": r.date_to, "status": r.status, "records": r.records,
        "attempts": r.attempts, "error": r.error, "meta": r.meta, "started_at": r.started_at,
        "finished_at": r.finished_at} for r in rows]}


@router.post("/jobs/retry")
def retry(_: User = Depends(require_admin), db: Session = Depends(get_db)):
    count = db.execute(update(ReviewJob).where(ReviewJob.status.in_(["failed", "skipped", "cancelled"]))
        .values(status="queued", error=None)).rowcount
    db.commit()
    return {"queued": count}


@router.post("/jobs/pause")
def pause(_: User = Depends(require_admin), db: Session = Depends(get_db)):
    count = db.execute(update(ReviewJob).where(ReviewJob.status == "queued").values(status="cancelled")).rowcount
    db.commit()
    return {"paused": count}


@router.get("/events")
def events(_: User = Depends(require_admin), db: Session = Depends(get_db)):
    return {"rows": [serialize_event(r) for r in db.scalars(
        select(ReviewEvent).order_by(ReviewEvent.occurred_at.desc()).limit(1000))]}


@router.post("/events")
def add_event(payload: EvidenceInput, _: User = Depends(require_admin), db: Session = Depends(get_db)):
    created = store_event(db, **payload.model_dump())
    db.commit()
    return {"created": created}


@router.post("/events/import")
async def import_events(file: UploadFile = File(...), _: User = Depends(require_admin), db: Session = Depends(get_db)):
    content = await file.read(5_000_001)
    if len(content) > 5_000_000:
        raise HTTPException(413, detail="Maximum file size is 5 MB.")
    try:
        reader = csv.DictReader(io.StringIO(content.decode("utf-8-sig")))
        if not {"source", "occurred_at", "title"}.issubset(reader.fieldnames or []):
            raise ValueError("CSV requires source, occurred_at (ISO date/time), title. Optional: detail, actor, object_id, reference_url.")
        validated = []
        for index, row in enumerate(reader, 2):
            if index > 10001:
                raise ValueError("Maximum 10,000 events per file.")
            validated.append(EvidenceInput(**{"evidence_type": "export", **{k: v for k, v in row.items() if v}}))
        count = sum(store_event(db, **row.model_dump()) for row in validated)
        db.commit()
        return {"created": count, "duplicates": len(validated) - count}
    except ValidationError as exc:
        db.rollback()
        fields = ", ".join(".".join(map(str, e["loc"])) for e in exc.errors(include_input=False))
        raise HTTPException(422, detail=f"Invalid evidence at CSV row {index}: {fields}.") from exc
    except (ValueError, UnicodeError) as exc:
        db.rollback()
        raise HTTPException(422, detail=str(exc)[:1000]) from exc


@router.post("/reports")
def save_report(payload: ReviewInput, _: User = Depends(require_admin), db: Session = Depends(get_db)):
    try:
        result = build_review(db, payload.date_from, payload.date_to, payload.baseline_from,
                              payload.baseline_to, with_costs=payload.with_costs)
    except ValueError as exc:
        raise HTTPException(422, detail=str(exc)) from exc
    report = ReviewReport(title=f"{payload.date_from} / {payload.date_to} vs {payload.baseline_from} / {payload.baseline_to}",
                          parameters=payload.model_dump(mode="json"), result=result)
    db.add(report)
    db.commit()
    return {"id": str(report.id)}


@router.get("/reports")
def reports(_: User = Depends(require_admin), db: Session = Depends(get_db)):
    return {"rows": [{"id": str(r.id), "title": r.title, "created_at": r.created_at}
        for r in db.execute(select(ReviewReport.id, ReviewReport.title, ReviewReport.created_at)
                            .order_by(ReviewReport.created_at.desc()).limit(100))]}


@router.get("/reports/{report_id}")
def saved_report(report_id: UUID, _: User = Depends(require_admin), db: Session = Depends(get_db)):
    row = db.get(ReviewReport, report_id)
    if not row:
        raise HTTPException(404, detail="Report not found.")
    return row.result
