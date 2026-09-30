from datetime import date, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import require_admin
from app.db.session import get_db
from app.models import User
from app.schemas.dashboard import DashboardResponse
from app.schemas.orders import OrderAnalyticsRequest
from app.services.orders_service import order_analytics_options, orders_analytics, orders_overview

router = APIRouter(prefix="/orders", tags=["orders"])


@router.get("/overview", response_model=DashboardResponse)
def overview(
    date_from: date | None = None,
    date_to: date | None = None,
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> DashboardResponse:
    end = date_to or date.today()
    start = date_from or end - timedelta(days=29)
    return DashboardResponse(data=orders_overview(db, start, end))


@router.get("/analytics/options", response_model=DashboardResponse)
def analytics_options(
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> DashboardResponse:
    return DashboardResponse(data=order_analytics_options(db))


@router.post("/analytics", response_model=DashboardResponse)
def analytics(
    payload: OrderAnalyticsRequest,
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> DashboardResponse:
    return DashboardResponse(
        data=orders_analytics(
            db,
            [period.model_dump() for period in payload.periods],
            payload.statuses,
            payload.aging_statuses,
            payload.completed_statuses,
            payload.cancelled_statuses,
            payload.group_by,
            payload.stale_days,
        )
    )
