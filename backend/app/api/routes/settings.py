from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import require_admin
from app.db.session import get_db
from app.models import IntegrationSetting, OpenCartOrder, User
from app.schemas.settings import IntegrationSettingResponse, IntegrationSettingUpdate
from app.services.constants import PROVIDERS
from app.services.seed import ensure_default_integrations

router = APIRouter(prefix="/settings", tags=["settings"])


@router.get("/integrations", response_model=list[IntegrationSettingResponse])
def list_integrations(_: User = Depends(require_admin), db: Session = Depends(get_db)):
    ensure_default_integrations(db)
    integrations = db.scalars(select(IntegrationSetting).order_by(IntegrationSetting.display_name)).all()
    return [
        IntegrationSettingResponse(
            provider=item.provider,
            display_name=item.display_name,
            is_enabled=item.is_enabled,
            config=item.config or {},
        )
        for item in integrations
    ]


@router.put("/integrations/{provider}", response_model=IntegrationSettingResponse)
def update_integration(
    provider: str,
    payload: IntegrationSettingUpdate,
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    if provider not in PROVIDERS:
        raise HTTPException(status_code=404, detail="Unknown provider")
    integration = db.scalar(select(IntegrationSetting).where(IntegrationSetting.provider == provider))
    if not integration:
        integration = IntegrationSetting(provider=provider, display_name=PROVIDERS[provider])
        db.add(integration)
    integration.is_enabled = payload.is_enabled
    integration.config = payload.config
    db.commit()
    db.refresh(integration)
    return IntegrationSettingResponse(
        provider=integration.provider,
        display_name=integration.display_name,
        is_enabled=integration.is_enabled,
        config=integration.config or {},
    )


@router.get("/opencart/order-statuses", response_model=list[str])
def list_opencart_order_statuses(_: User = Depends(require_admin), db: Session = Depends(get_db)):
    statuses = db.scalars(
        select(OpenCartOrder.order_status)
        .where(OpenCartOrder.order_status.is_not(None), OpenCartOrder.order_status != "")
        .distinct()
        .order_by(OpenCartOrder.order_status)
    ).all()
    return [status for status in statuses if status]
