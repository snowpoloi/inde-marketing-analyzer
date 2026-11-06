from datetime import date, timedelta
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models import User
from app.schemas.dashboard import DashboardResponse
from app.services.detail_reports import funnel_report, landing_page_report, meta_ad_report
from app.services.google_ads_reports import asset_group_report, product_report, search_term_report
from app.services.merchant_issues import merchant_issue_report
from app.services.sync_service import sync_freshness
from app.services.dashboard_service import (
    aade_document_ledger,
    aade_report,
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


def _checked_window(date_from: date | None, date_to: date | None) -> tuple[date, date]:
    start, end = _window(date_from, date_to)
    if start > end:
        raise HTTPException(status_code=400, detail="date_from must be on or before date_to.")
    return start, end


@router.get("/funnel", response_model=DashboardResponse)
def funnel(date_from: date | None = None, date_to: date | None = None, _: User = Depends(get_current_user), db: Session = Depends(get_db)):
    start, end = _checked_window(date_from, date_to)
    return DashboardResponse(data=funnel_report(db, start, end))


@router.get("/landing-pages", response_model=DashboardResponse)
def landing_pages(
    date_from: date | None = None,
    date_to: date | None = None,
    limit: int = Query(100, ge=1, le=1000),
    channel_group: str | None = Query(None, max_length=160),
    _: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    start, end = _checked_window(date_from, date_to)
    return DashboardResponse(data=landing_page_report(db, start, end, limit=limit, channel_group=channel_group))


@router.get("/meta-ads", response_model=DashboardResponse)
def meta_ads(date_from: date | None = None, date_to: date | None = None, _: User = Depends(get_current_user), db: Session = Depends(get_db)):
    start, end = _checked_window(date_from, date_to)
    return DashboardResponse(data=meta_ad_report(db, start, end))


@router.get("/google-search-terms", response_model=DashboardResponse)
def google_search_terms(
    date_from: date | None = None,
    date_to: date | None = None,
    campaign: str | None = Query(None, max_length=255, description="Campaign ID or exact campaign name"),
    limit: int = Query(100, ge=1, le=1000),
    no_conversions: bool = Query(False, description="Only terms with cost and no conversions"),
    _: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    start, end = _checked_window(date_from, date_to)
    return DashboardResponse(data=search_term_report(
        db, start, end, campaign=campaign, limit=limit, no_conversions_only=no_conversions))


@router.get("/google-products", response_model=DashboardResponse)
def google_products(
    date_from: date | None = None,
    date_to: date | None = None,
    limit: int = Query(100, ge=1, le=1000),
    no_conversions: bool = Query(False, description="Only products with cost and no conversions"),
    _: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    start, end = _checked_window(date_from, date_to)
    return DashboardResponse(data=product_report(db, start, end, limit=limit, no_conversions_only=no_conversions))


@router.get("/google-asset-groups", response_model=DashboardResponse)
def google_asset_groups(date_from: date | None = None, date_to: date | None = None, _: User = Depends(get_current_user), db: Session = Depends(get_db)):
    start, end = _checked_window(date_from, date_to)
    return DashboardResponse(data=asset_group_report(db, start, end))


@router.get("/merchant-issues", response_model=DashboardResponse)
def merchant_issues(
    severity: Literal["DISAPPROVED", "DEMOTED", "NOT_IMPACTED"] | None = None,
    reporting_context: str | None = Query(None, max_length=64, description="e.g. SHOPPING_ADS"),
    limit: int = Query(500, ge=1, le=5000),
    _: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """The latest Merchant Center status snapshot. It has no date window: the daily sync replaces it."""
    return DashboardResponse(data=merchant_issue_report(
        db, severity=severity, reporting_context=reporting_context, limit=limit))


@router.get("/freshness", response_model=DashboardResponse)
def freshness(_: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """When each provider was last synced. Read-only, and without error text or run meta."""
    return DashboardResponse(data=sync_freshness(db))


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


@router.get("/tiktok-performance", response_model=DashboardResponse)
def tiktok_performance(date_from: date | None = None, date_to: date | None = None, _: User = Depends(get_current_user), db: Session = Depends(get_db)):
    start, end = _window(date_from, date_to)
    return DashboardResponse(data={"rows": source_performance(db, "tiktok_ads", start, end)})


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
    if not _.is_admin:
        return DashboardResponse(data={"rows": []})
    return DashboardResponse(data={"rows": product_profitability_hints(db, start, end)})


@router.get("/products", response_model=DashboardResponse)
def products(date_from: date | None = None, date_to: date | None = None, _: User = Depends(get_current_user), db: Session = Depends(get_db)):
    start, end = _window(date_from, date_to)
    return DashboardResponse(data={"rows": product_performance(db, start, end, include_costs=_.is_admin)})


@router.get("/audit", response_model=DashboardResponse)
def audit(date_from: date | None = None, date_to: date | None = None, _: User = Depends(get_current_user), db: Session = Depends(get_db)):
    start, end = _window(date_from, date_to)
    return DashboardResponse(data=marketing_audit(db, start, end))


@router.get("/aade-documents", response_model=DashboardResponse)
def aade_documents(date_from: date | None = None, date_to: date | None = None, _: User = Depends(get_current_user), db: Session = Depends(get_db)):
    start, end = _window(date_from, date_to)
    return DashboardResponse(data=aade_document_ledger(db, start, end))


@router.get("/aade-report", response_model=DashboardResponse)
def fiscal_report(date_from: date | None = None, date_to: date | None = None, _: User = Depends(get_current_user), db: Session = Depends(get_db)):
    start, end = _window(date_from, date_to)
    return DashboardResponse(data=aade_report(db, start, end))


@router.get("/aade-documents/{document_id}", response_model=DashboardResponse)
def aade_document(document_id: UUID, _: User = Depends(get_current_user), db: Session = Depends(get_db)):
    result = aade_document_ledger(db, date.today(), date.today(), document_id=document_id)
    if not result["rows"]:
        raise HTTPException(status_code=404, detail="AADE document not found.")
    return DashboardResponse(data=result["rows"][0])
