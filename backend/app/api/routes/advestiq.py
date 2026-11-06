import re
from datetime import date, datetime, timezone
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import case, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.api.deps import is_advestiq_key, require_admin, require_owner
from app.db.session import get_db
from app.models import AdvestiqProposal, AdvestiqProposalNote, AdvestiqReport, User

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


# Proposals. ADVESTIQ publishes the content with PUT; the owner decides the status and both add notes.
ProposalStatus = Literal["discussion", "approved", "sent", "done", "not_done", "rejected"]
ProposalPlatform = Literal["google_ads", "meta_ads", "tiktok_ads", "merchant_center", "tracking", "site", "other"]
ProposalExecutor = Literal["agency", "owner", "site"]
PROPOSAL_STATUSES = ("discussion", "approved", "sent", "done", "not_done", "rejected")
OPEN_STATUSES = ("discussion", "approved", "sent")
PROPOSAL_CODE = re.compile(r"[A-Z]{1,6}-[0-9]{1,6}")
CONTENT_FIELDS = ("title", "platform", "executor", "what", "why", "expected", "rollback", "check_7_on", "check_14_on",
                  "message_subject", "message_body", "created_on", "advestiq_status")


class ProposalContentInput(BaseModel):
    """What ADVESTIQ writes. The owner's status and notes are not part of it, so a PUT can never change them."""

    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=300)
    platform: ProposalPlatform
    executor: ProposalExecutor
    what: str = Field(default="", max_length=20_000)
    why: str = Field(default="", max_length=20_000)
    expected: str = Field(default="", max_length=20_000)
    rollback: str = Field(default="", max_length=20_000)
    check_7_on: date | None = None
    check_14_on: date | None = None
    message_subject: str = Field(default="", max_length=300)
    message_body: str = Field(default="", max_length=20_000)
    created_on: date
    advestiq_status: str = Field(default="", max_length=300)


class ProposalNoteInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    text: str = Field(min_length=1, max_length=10_000)
    # Optional. The author always follows who is calling: the key writes `advestiq`, a logged-in owner `owner`.
    author: Literal["owner", "advestiq"] | None = None


class ProposalStatusInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    status: ProposalStatus
    note: str = Field(default="", max_length=10_000)


def _proposal_code(code: str) -> str:
    normalized = code.strip().upper()
    if not PROPOSAL_CODE.fullmatch(normalized):
        raise HTTPException(status_code=422, detail="Use a proposal code like P-009 or D-03.")
    return normalized


def _proposal(db: Session, code: str, *, lock: bool = False) -> AdvestiqProposal:
    query = select(AdvestiqProposal).where(AdvestiqProposal.code == _proposal_code(code))
    proposal = db.scalar(query.with_for_update() if lock else query)
    if proposal is None:
        raise HTTPException(status_code=404, detail="Proposal not found.")
    return proposal


def _proposal_summary(proposal: AdvestiqProposal, activity: tuple[int, datetime | None] = (0, None)) -> dict:
    return {"code": proposal.code, "title": proposal.title, "platform": proposal.platform,
            "executor": proposal.executor, "created_on": proposal.created_on, "status": proposal.status,
            "status_changed_at": proposal.status_changed_at, "advestiq_status": proposal.advestiq_status,
            "check_7_on": proposal.check_7_on, "check_14_on": proposal.check_14_on,
            "updated_at": proposal.updated_at, "notes_count": activity[0], "last_note_at": activity[1]}


def _note(note: AdvestiqProposalNote) -> dict:
    return {"id": str(note.id), "author": note.author, "text": note.text, "status": note.status,
            "created_at": note.created_at}


def _notes(db: Session, proposal_ids: list[UUID]) -> dict[UUID, list[dict]]:
    grouped: dict[UUID, list[dict]] = {proposal_id: [] for proposal_id in proposal_ids}
    if proposal_ids:
        rows = db.scalars(select(AdvestiqProposalNote).where(AdvestiqProposalNote.proposal_id.in_(proposal_ids))
                          .order_by(AdvestiqProposalNote.created_at, AdvestiqProposalNote.id))
        for note in rows:
            grouped[note.proposal_id].append(_note(note))
    return grouped


def _proposal_full(proposal: AdvestiqProposal, notes: list[dict]) -> dict:
    last = max((note["created_at"] for note in notes), default=None)
    return {**_proposal_summary(proposal, (len(notes), last)), "what": proposal.what, "why": proposal.why,
            "expected": proposal.expected, "rollback": proposal.rollback,
            "message_subject": proposal.message_subject, "message_body": proposal.message_body,
            "created_at": proposal.created_at, "notes": notes}


@router.get("/proposals")
def list_proposals(status: Literal[ProposalStatus, "open", "closed"] | None = None,
                   platform: ProposalPlatform | None = None, full: bool = False,
                   _: User = Depends(require_admin), db: Session = Depends(get_db)):
    """Open proposals first (for discussion, approved, sent), newest first. `full=true` adds every field and the notes."""
    query = select(AdvestiqProposal)
    if status == "open":
        query = query.where(AdvestiqProposal.status.in_(OPEN_STATUSES))
    elif status == "closed":
        query = query.where(AdvestiqProposal.status.not_in(OPEN_STATUSES))
    elif status:
        query = query.where(AdvestiqProposal.status == status)
    if platform:
        query = query.where(AdvestiqProposal.platform == platform)
    open_first = case((AdvestiqProposal.status.in_(OPEN_STATUSES), 0), else_=1)
    rows = db.scalars(query.order_by(open_first, AdvestiqProposal.created_on.desc(), AdvestiqProposal.code.desc())
                      .limit(2000)).all()
    counts = dict(db.execute(select(AdvestiqProposal.status, func.count()).group_by(AdvestiqProposal.status)).all())
    if full:
        notes = _notes(db, [row.id for row in rows])
        data = [_proposal_full(row, notes[row.id]) for row in rows]
    else:
        activity = {proposal_id: (count, last) for proposal_id, count, last in db.execute(
            select(AdvestiqProposalNote.proposal_id, func.count(), func.max(AdvestiqProposalNote.created_at))
            .where(AdvestiqProposalNote.proposal_id.in_([row.id for row in rows]))
            .group_by(AdvestiqProposalNote.proposal_id))} if rows else {}
        data = [_proposal_summary(row, activity.get(row.id, (0, None))) for row in rows]
    return {"data": {"rows": data, "counts": {key: counts.get(key, 0) for key in PROPOSAL_STATUSES}}}


@router.get("/proposals/{code}")
def get_proposal(code: str, _: User = Depends(require_admin), db: Session = Depends(get_db)):
    proposal = _proposal(db, code)
    return {"data": _proposal_full(proposal, _notes(db, [proposal.id])[proposal.id])}


@router.put("/proposals/{code}")
def save_proposal(code: str, payload: ProposalContentInput, _: User = Depends(require_admin),
                  db: Session = Depends(get_db)):
    """Create or update the content of one proposal. The owner's status and all notes stay as they are."""
    code = _proposal_code(code)
    content = payload.model_dump()
    # Insert-if-absent first, so two publishes of a new code cannot both create it.
    created = db.scalar(insert(AdvestiqProposal).values(code=code, status="discussion", **content)
                        .on_conflict_do_nothing(constraint="uq_advestiq_proposal_code")
                        .returning(AdvestiqProposal.id)) is not None
    proposal = _proposal(db, code, lock=True)
    changed = created
    for field in CONTENT_FIELDS:
        if getattr(proposal, field) != content[field]:
            setattr(proposal, field, content[field])
            changed = True
    db.commit()
    db.refresh(proposal)
    return {"data": {**_proposal_full(proposal, _notes(db, [proposal.id])[proposal.id]),
                     "created": created, "changed": changed}}


@router.post("/proposals/{code}/notes")
def add_proposal_note(code: str, payload: ProposalNoteInput, user: User = Depends(require_admin),
                      db: Session = Depends(get_db)):
    author = "advestiq" if is_advestiq_key(user) else "owner"
    if payload.author and payload.author != author:
        raise HTTPException(status_code=403, detail=f"This login can only add notes as {author}.")
    proposal = _proposal(db, code)
    note = AdvestiqProposalNote(proposal_id=proposal.id, author=author, text=payload.text)
    db.add(note)
    db.commit()
    db.refresh(note)
    return {"data": _note(note)}


@router.patch("/proposals/{code}/status")
def set_proposal_status(code: str, payload: ProposalStatusInput, _: User = Depends(require_owner),
                        db: Session = Depends(get_db)):
    """Owner only. A new status is recorded as a note too, with the optional comment."""
    proposal = _proposal(db, code, lock=True)
    if payload.status != proposal.status:
        proposal.status, proposal.status_changed_at = payload.status, datetime.now(timezone.utc)
        db.add(AdvestiqProposalNote(proposal_id=proposal.id, author="owner", text=payload.note, status=payload.status))
    elif payload.note:
        db.add(AdvestiqProposalNote(proposal_id=proposal.id, author="owner", text=payload.note))
    db.commit()
    db.refresh(proposal)
    return {"data": _proposal_full(proposal, _notes(db, [proposal.id])[proposal.id])}
