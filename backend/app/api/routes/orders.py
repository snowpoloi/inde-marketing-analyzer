from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.api.deps import require_admin
from app.db.session import get_db
from app.models import User, OpenCartOrder
from app.services.dashboard_service import _opencart_order_payload
from app.schemas.dashboard import DashboardResponse
from app.schemas.orders import OrderAnalyticsDefaultsRequest, OrderAnalyticsRequest
from app.services.orders_service import (
    order_analytics_options,
    orders_analytics,
    orders_overview,
    save_order_analytics_defaults,
)

router = APIRouter(prefix="/orders", tags=["orders"])


@router.get("/detail/{order_id}", response_model=DashboardResponse)
def detail(order_id: str, _: User = Depends(require_admin), db: Session = Depends(get_db)):
    order = db.scalar(select(OpenCartOrder).options(selectinload(OpenCartOrder.products))
                      .where(OpenCartOrder.order_id == order_id))
    if order is None:
        raise HTTPException(status_code=404, detail="Order not found.")
    return DashboardResponse(data={**_opencart_order_payload(order, "exact_order_id"),
                                   "payment_method": order.payment_method})


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


@router.put("/analytics/defaults", response_model=DashboardResponse)
def analytics_defaults(
    payload: OrderAnalyticsDefaultsRequest,
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> DashboardResponse:
    return DashboardResponse(
        data=save_order_analytics_defaults(
            db,
            payload.statuses,
            payload.aging_statuses,
            payload.processed_statuses,
            payload.completed_statuses,
            payload.cancelled_statuses,
            payload.group_by,
            payload.stale_days,
        )
    )


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
            payload.processed_statuses,
            payload.completed_statuses,
            payload.cancelled_statuses,
            payload.group_by,
            payload.stale_days,
        )
    )
