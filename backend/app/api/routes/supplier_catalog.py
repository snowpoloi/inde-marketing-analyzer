from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import require_admin
from app.db.session import get_db
from app.models import SupplierCatalogFeed, SupplierCatalogProduct, User
from app.schemas.supplier_catalog import SupplierCatalogFeedInput, SupplierCatalogPricingInput
from app.services.supplier_catalog_settings import public_pricing_settings, save_pricing_settings, package_metrics
from app.services.supplier_catalog_service import catalog_products, feed_response, queue_feed, save_feed

router = APIRouter(prefix="/supplier-catalog", tags=["supplier-catalog"])


@router.get("/pricing-settings")
def pricing(_: User = Depends(require_admin), db: Session = Depends(get_db)):
    return public_pricing_settings(db)


@router.put("/pricing-settings")
def save_pricing(payload: SupplierCatalogPricingInput, user: User = Depends(require_admin), db: Session = Depends(get_db)):
    try:
        return save_pricing_settings(db, payload, user)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/feeds")
def feeds(_: User = Depends(require_admin), db: Session = Depends(get_db)):
    return [feed_response(feed) for feed in db.scalars(select(SupplierCatalogFeed).order_by(SupplierCatalogFeed.name))]


@router.post("/feeds")
@router.put("/feeds/{feed_id}")
def save(payload: SupplierCatalogFeedInput, feed_id: UUID | None = None,
         _: User = Depends(require_admin), db: Session = Depends(get_db)):
    try:
        return feed_response(save_feed(db, payload, feed_id))
    except (ValueError, LookupError) as exc:
        db.rollback()
        raise HTTPException(status_code=404 if isinstance(exc, LookupError) else 400, detail=str(exc)) from exc


@router.post("/feeds/{feed_id}/sync")
def sync(feed_id: UUID, _: User = Depends(require_admin), db: Session = Depends(get_db)):
    try:
        return feed_response(queue_feed(db, feed_id))
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/products")
def products(feed_id: UUID | None = None, q: str = Query(default="", max_length=200),
             match: str = Query(default="all", pattern="^(all|matched|unmatched)$"),
             availability: str = Query(default="all", pattern="^(all|in_stock|out_of_stock)$"),
             category: str = Query(default="", max_length=1000), offset: int = Query(default=0, ge=0),
             limit: int = Query(default=50, ge=1, le=100), _: User = Depends(require_admin), db: Session = Depends(get_db)):
    return catalog_products(db, feed_id=feed_id, q=q.strip(), match=match, availability=availability,
                            category=category, offset=offset, limit=limit)


@router.get("/products/{product_id}")
def product(product_id: UUID, _: User = Depends(require_admin), db: Session = Depends(get_db)):
    row = db.get(SupplierCatalogProduct, product_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Supplier product not found.")
    return {"id": str(row.id), "name": row.name, "details": row.details, "is_current": row.is_current,
            **package_metrics(row.details or {}, public_pricing_settings(db)["volumetric_divisor"])}
