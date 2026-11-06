from datetime import date
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import require_admin
from app.db.session import get_db
from app.models import AdvestiqReport, User

router = APIRouter(prefix="/advestiq", tags=["advestiq"])


class AdvestiqReportInput(BaseModel):
    kind: Literal["daily", "weekly"] = "daily"
    report_date: date
    title: str = Field(min_length=1, max_length=300)
    summary: str = Field(default="", max_length=500)
    markdown: str = Field(min_length=1, max_length=200_000)


def _summary(report: AdvestiqReport) -> dict:
    return {"id": str(report.id), "kind": report.kind, "report_date": report.report_date, "title": report.title,
            "summary": report.summary, "updated_at": report.updated_at}


@router.get("/reports")
def list_reports(kind: Literal["daily", "weekly"] | None = None, limit: int = Query(60, ge=1, le=366),
                 _: User = Depends(require_admin), db: Session = Depends(get_db)):
    query = select(AdvestiqReport)
    if kind:
        query = query.where(AdvestiqReport.kind == kind)
    rows = db.scalars(query.order_by(AdvestiqReport.report_date.desc(), AdvestiqReport.kind).limit(limit)).all()
    return {"data": {"rows": [_summary(row) for row in rows]}}


@router.get("/reports/{report_id}")
def get_report(report_id: UUID, _: User = Depends(require_admin), db: Session = Depends(get_db)):
    report = db.get(AdvestiqReport, report_id)
    if report is None:
        raise HTTPException(status_code=404, detail="Report not found.")
    return {"data": {**_summary(report), "markdown": report.markdown}}


@router.post("/reports")
def save_report(payload: AdvestiqReportInput, _: User = Depends(require_admin), db: Session = Depends(get_db)):
    """Create or replace the report for one kind and date (ADVESTIQ re-runs overwrite the same day)."""
    report = db.scalar(select(AdvestiqReport).where(AdvestiqReport.kind == payload.kind,
                                                    AdvestiqReport.report_date == payload.report_date))
    if report is None:
        report = AdvestiqReport(kind=payload.kind, report_date=payload.report_date)
        db.add(report)
    report.title, report.summary, report.markdown = payload.title, payload.summary, payload.markdown
    db.commit()
    db.refresh(report)
    return {"data": _summary(report)}
