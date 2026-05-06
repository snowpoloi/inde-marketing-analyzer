import csv
import io
from datetime import date

from fastapi import APIRouter, Body, Depends, File, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import require_admin
from app.db.session import get_db
from app.models import SyncRun, User
from app.schemas.sync import SyncRunResponse, SyncTriggerRequest
from app.services.import_service import (
    import_google_ads_csv,
    import_merchant_rows,
    import_meta_ads_csv,
    import_opencart_orders,
    import_shoply_sales,
)
from app.services.sync_service import finish_run, run_many, start_run

router = APIRouter(prefix="/sync", tags=["sync"])


def _serialize_run(run: SyncRun) -> SyncRunResponse:
    return SyncRunResponse(
        id=str(run.id),
        provider=run.provider,
        sync_type=run.sync_type,
        status=run.status,
        date_from=run.date_from,
        date_to=run.date_to,
        started_at=run.started_at,
        finished_at=run.finished_at,
        records_processed=run.records_processed,
        error_message=run.error_message,
        meta=run.meta or {},
    )


@router.get("/runs", response_model=list[SyncRunResponse])
def list_runs(_: User = Depends(require_admin), db: Session = Depends(get_db), limit: int = 100):
    runs = db.scalars(select(SyncRun).order_by(SyncRun.started_at.desc()).limit(limit)).all()
    return [_serialize_run(run) for run in runs]


@router.post("/run", response_model=list[SyncRunResponse])
def trigger_sync(payload: SyncTriggerRequest, _: User = Depends(require_admin), db: Session = Depends(get_db)):
    try:
        runs = run_many(db, payload.providers, payload.date_from, payload.date_to, sync_type="manual")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return [_serialize_run(run) for run in runs]


@router.post("/import/google-ads-csv", response_model=SyncRunResponse)
async def import_google_ads(
    report_date: date,
    file: UploadFile = File(...),
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    run = start_run(db, "google_ads", "csv_import", report_date, report_date)
    try:
        text = (await file.read()).decode("utf-8-sig")
        count = import_google_ads_csv(db, text, report_date)
        run = finish_run(db, run, "success", count, meta={"filename": file.filename})
    except Exception as exc:
        db.rollback()
        run = finish_run(db, run, "failed", 0, error=str(exc), meta={"filename": file.filename})
    return _serialize_run(run)


@router.post("/import/meta-ads-csv", response_model=SyncRunResponse)
async def import_meta_ads(
    fallback_date: date,
    file: UploadFile = File(...),
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    run = start_run(db, "meta_ads", "csv_import", fallback_date, fallback_date)
    try:
        text = (await file.read()).decode("utf-8-sig")
        count = import_meta_ads_csv(db, text, fallback_date)
        run = finish_run(db, run, "success", count, meta={"filename": file.filename})
    except Exception as exc:
        db.rollback()
        run = finish_run(db, run, "failed", 0, error=str(exc), meta={"filename": file.filename})
    return _serialize_run(run)


@router.post("/import/merchant-csv", response_model=SyncRunResponse)
async def import_merchant_csv(
    report_date: date,
    file: UploadFile = File(...),
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    run = start_run(db, "merchant_center", "csv_import", report_date, report_date)
    try:
        text = (await file.read()).decode("utf-8-sig")
        rows = list(csv.DictReader(io.StringIO(text)))
        count = import_merchant_rows(db, rows, report_date)
        run = finish_run(db, run, "success", count, meta={"filename": file.filename})
    except Exception as exc:
        db.rollback()
        run = finish_run(db, run, "failed", 0, error=str(exc), meta={"filename": file.filename})
    return _serialize_run(run)


@router.post("/import/opencart-json", response_model=SyncRunResponse)
def import_opencart_json(
    payload: list[dict] | dict = Body(...),
    report_date: date | None = None,
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    sync_date = report_date or date.today()
    run = start_run(db, "opencart", "json_import", sync_date, sync_date)
    try:
        if isinstance(payload, list):
            rows = payload
        else:
            rows = payload.get("orders") or payload.get("data") or []
        if not isinstance(rows, list):
            raise ValueError("OpenCart JSON must be a list or an object with orders/data list.")
        count = import_opencart_orders(db, rows)
        run = finish_run(db, run, "success", count)
    except Exception as exc:
        db.rollback()
        run = finish_run(db, run, "failed", 0, error=str(exc))
    return _serialize_run(run)


@router.post("/import/shoply-json", response_model=SyncRunResponse)
def import_shoply_json(
    payload: list[dict] | dict = Body(...),
    report_date: date | None = None,
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    sync_date = report_date or date.today()
    run = start_run(db, "shoply", "json_import", sync_date, sync_date)
    try:
        if isinstance(payload, list):
            rows = payload
        else:
            rows = payload.get("sales") or payload.get("orders") or payload.get("data") or []
        if not isinstance(rows, list):
            raise ValueError("Shoply JSON must be a list or an object with sales/orders/data list.")
        count = import_shoply_sales(db, rows)
        run = finish_run(db, run, "success", count)
    except Exception as exc:
        db.rollback()
        run = finish_run(db, run, "failed", 0, error=str(exc))
    return _serialize_run(run)
