from datetime import date, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models import User
from app.schemas.dashboard import DashboardResponse
from app.services.dashboard_service import (
    attribution_comparison,
    brand_category_performance,
    campaign_recommendations,
    executive_summary,
    marketing_audit,
    opencart_sales,
    product_profitability_hints,
    product_performance,
    source_performance,
)

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


def _window(date_from: date | None, date_to: date | None) -> tuple[date, date]:
    end = date_to or date.today()
    start = date_from or end - timedelta(days=30)
    return start, end


@router.get("/summary", response_model=DashboardResponse)
def summary(date_from: date | None = None, date_to: date | None = None, _: User = Depends(get_current_user), db: Session = Depends(get_db)):
    start, end = _window(date_from, date_to)
    return DashboardResponse(data=executive_summary(db, start, end))


@router.get("/meta-performance", response_model=DashboardResponse)
def meta_performance(date_from: date | None = None, date_to: date | None = None, _: User = Depends(get_current_user), db: Session = Depends(get_db)):
    start, end = _window(date_from, date_to)
    return DashboardResponse(data={"rows": source_performance(db, "meta_ads", start, end)})


@router.get("/google-performance", response_model=DashboardResponse)
def google_performance(date_from: date | None = None, date_to: date | None = None, _: User = Depends(get_current_user), db: Session = Depends(get_db)):
    start, end = _window(date_from, date_to)
    return DashboardResponse(data={"rows": source_performance(db, "google_ads", start, end)})


@router.get("/opencart-sales", response_model=DashboardResponse)
def opencart(date_from: date | None = None, date_to: date | None = None, _: User = Depends(get_current_user), db: Session = Depends(get_db)):
    start, end = _window(date_from, date_to)
    return DashboardResponse(data=opencart_sales(db, start, end))


@router.get("/attribution", response_model=DashboardResponse)
def attribution(date_from: date | None = None, date_to: date | None = None, _: User = Depends(get_current_user), db: Session = Depends(get_db)):
    start, end = _window(date_from, date_to)
    return DashboardResponse(data=attribution_comparison(db, start, end))


@router.get("/recommendations", response_model=DashboardResponse)
def recommendations(date_from: date | None = None, date_to: date | None = None, _: User = Depends(get_current_user), db: Session = Depends(get_db)):
    start, end = _window(date_from, date_to)
    return DashboardResponse(data={"rows": campaign_recommendations(db, start, end)})


@router.get("/brand-category", response_model=DashboardResponse)
def brand_category(date_from: date | None = None, date_to: date | None = None, _: User = Depends(get_current_user), db: Session = Depends(get_db)):
    start, end = _window(date_from, date_to)
    return DashboardResponse(data=brand_category_performance(db, start, end))


@router.get("/product-profitability", response_model=DashboardResponse)
def product_profitability(date_from: date | None = None, date_to: date | None = None, _: User = Depends(get_current_user), db: Session = Depends(get_db)):
    start, end = _window(date_from, date_to)
    return DashboardResponse(data={"rows": product_profitability_hints(db, start, end)})


@router.get("/products", response_model=DashboardResponse)
def products(date_from: date | None = None, date_to: date | None = None, _: User = Depends(get_current_user), db: Session = Depends(get_db)):
    start, end = _window(date_from, date_to)
    return DashboardResponse(data={"rows": product_performance(db, start, end)})


@router.get("/audit", response_model=DashboardResponse)
def audit(date_from: date | None = None, date_to: date | None = None, _: User = Depends(get_current_user), db: Session = Depends(get_db)):
    start, end = _window(date_from, date_to)
    return DashboardResponse(data=marketing_audit(db, start, end))
