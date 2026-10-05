import json
from datetime import date, datetime, timedelta, timezone
from uuid import UUID
from decimal import Decimal

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import require_admin
from app.db.session import get_db
from app.models import User
from app.schemas.suppliers import ManualSupplierCostRequest, SupplierImportRequest, VerifySupplierMappingRequest, SupplierSettingsRequest
from app.services.supplier_service import (
    add_manual_cost,
    import_supplier_documents,
    supplier_performance,
    supplier_products,
    supplier_summary,
    unmatched_products,
    verify_supplier_mapping,
    search_supplier_catalog,
    supplier_cost_history,
    supplier_shipping_simulation,
)
from app.supplier_parsers import NormalizedJsonParser
from app.models import Supplier
from app.core.config import settings
from app.connectors.supplier_gmail import GmailReadError, MAILBOX
from app.schemas.suppliers import SupplierGmailSyncRequest, SupplierGmailReviewRequest
from app.services.supplier_gmail_service import sync_supplier_gmail, gmail_source_rows, review_gmail_source


router = APIRouter(prefix="/suppliers", tags=["suppliers"])


def _dates(date_from: date | None, date_to: date | None) -> tuple[date, date]:
    end = date_to or date.today()
    start = date_from or end - timedelta(days=30)
    if end < start:
        raise HTTPException(status_code=400, detail="date_to must be on or after date_from")
    return start, end


@router.get("/summary")
def summary(
    date_from: date | None = None,
    date_to: date | None = None,
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    start, end = _dates(date_from, date_to)
    return {"data": supplier_summary(db, start, end)}


@router.get("/products")
def products(
    as_of: date | None = None,
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    return {"data": {"rows": supplier_products(db, as_of or date.today())}}


@router.get("/unmatched")
def unmatched(_: User = Depends(require_admin), db: Session = Depends(get_db)):
    return {"data": {"rows": unmatched_products(db)}}


@router.get("/performance")
def performance(
    date_from: date | None = None,
    date_to: date | None = None,
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    start, end = _dates(date_from, date_to)
    return {"data": {"rows": supplier_performance(db, start, end)}}


@router.get("/gmail")
def gmail_sources(offset: int = Query(default=0, ge=0), limit: int = Query(default=100, ge=1, le=100),
                  _: User = Depends(require_admin), db: Session = Depends(get_db)):
    configured = settings.supplier_gmail_enabled and all((settings.supplier_gmail_client_id,
        settings.supplier_gmail_client_secret, settings.supplier_gmail_refresh_token))
    return {"data": {"mailbox": MAILBOX, "configured": bool(configured),
                     "rows": gmail_source_rows(db, offset=offset, limit=limit)}}


@router.post("/gmail/sync")
def gmail_sync(payload: SupplierGmailSyncRequest, _: User = Depends(require_admin), db: Session = Depends(get_db)):
    try:
        return {"data": sync_supplier_gmail(db, payload)}
    except GmailReadError as exc:
        db.rollback()
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ValueError:
        db.rollback()
        raise HTTPException(status_code=400, detail="Gmail document could not be staged; review the source.") from None


@router.put("/gmail/{source_id}/review")
def gmail_review(source_id: UUID, payload: SupplierGmailReviewRequest,
                 user: User = Depends(require_admin), db: Session = Depends(get_db)):
    try:
        return {"data": review_gmail_source(db, source_id, payload, user)}
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Document conflicts with existing financial evidence; manual review required.") from None


@router.post("/imports")
def import_normalized(
    payload: SupplierImportRequest,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    try:
        return {"data": import_supplier_documents(db, payload, user.id)}
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Import conflicts with an existing document or mapping; review the source identifiers.") from exc


@router.post("/imports/json")
async def import_normalized_json(
    file: UploadFile = File(...),
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    if not file.filename or not file.filename.lower().endswith(".json"):
        raise HTTPException(status_code=400, detail="Upload a normalized supplier JSON file.")
    body = await file.read(10 * 1024 * 1024 + 1)
    if len(body) > 10 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Supplier import files are limited to 10 MB.")
    try:
        raw = json.loads(body.decode("utf-8-sig"))
        payload = NormalizedJsonParser().parse(raw, filename=file.filename)
        return {"data": import_supplier_documents(db, payload, user.id)}
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=f"Invalid supplier JSON: {exc}") from exc
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Import conflicts with an existing document or mapping.") from exc


@router.put("/mappings/{mapping_id}/verify")
def verify_mapping(
    mapping_id: UUID,
    payload: VerifySupplierMappingRequest,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    try:
        return {"data": verify_supplier_mapping(db, mapping_id, payload, user)}
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/costs/manual")
def manual_cost(
    payload: ManualSupplierCostRequest,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    try:
        return {"data": add_manual_cost(db, payload, user.id)}
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/catalog-search")
def catalog_search(q: str = Query(min_length=2, max_length=200), _: User = Depends(require_admin), db: Session = Depends(get_db)):
    return {"data": {"rows": search_supplier_catalog(db, q)}}


@router.get("/mappings/{mapping_id}/cost-history")
def cost_history(mapping_id: UUID, _: User = Depends(require_admin), db: Session = Depends(get_db)):
    return {"data": {"rows": supplier_cost_history(db, mapping_id)}}


@router.put("/{supplier_id}/settings")
def supplier_settings(supplier_id: UUID, payload: SupplierSettingsRequest, user: User = Depends(require_admin), db: Session = Depends(get_db)):
    supplier = db.get(Supplier, supplier_id, with_for_update=True)
    if supplier is None:
        raise HTTPException(status_code=404, detail="Supplier not found.")
    audit = list((supplier.raw_metadata or {}).get("settings_audit", []))
    audit.append({"user_id": str(user.id), "at": datetime.now(timezone.utc).isoformat(),
                  "previous_threshold": str(supplier.free_shipping_threshold), "threshold": str(payload.free_shipping_threshold)})
    supplier.raw_metadata = {**(supplier.raw_metadata or {}), "settings_audit": audit}
    supplier.free_shipping_threshold = payload.free_shipping_threshold
    db.commit()
    return {"data": {"saved": True}}


@router.get("/{supplier_id}/shipping-simulation")
def shipping_simulation(supplier_id: UUID, threshold: Decimal = Query(ge=0, allow_inf_nan=False), date_from: date | None = None, date_to: date | None = None,
                        _: User = Depends(require_admin), db: Session = Depends(get_db)):
    start, end = _dates(date_from, date_to)
    if db.get(Supplier, supplier_id) is None:
        raise HTTPException(status_code=404, detail="Supplier not found.")
    return {"data": supplier_shipping_simulation(db, supplier_id, start, end, threshold)}
