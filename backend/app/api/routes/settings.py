from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import require_admin
from app.connectors.tiktok_ads import TikTokAdsApiError, TikTokAdsConnector
from app.core.security import create_oauth_state, decode_oauth_state
from app.db.session import get_db
from app.models import IntegrationSetting, OpenCartOrder, User
from app.schemas.settings import (
    IntegrationSettingResponse,
    IntegrationSettingUpdate,
    TikTokAuthorizationCallback,
    TikTokAuthorizationUrlResponse,
)
from app.services.constants import PROVIDERS
from app.services.seed import ensure_default_integrations

router = APIRouter(prefix="/settings", tags=["settings"])


def _tiktok_integration(db: Session) -> IntegrationSetting:
    integration = db.scalar(select(IntegrationSetting).where(IntegrationSetting.provider == "tiktok_ads"))
    if not integration:
        integration = IntegrationSetting(provider="tiktok_ads", display_name=PROVIDERS["tiktok_ads"])
        db.add(integration)
        db.commit()
        db.refresh(integration)
    return integration


@router.get("/integrations/tiktok_ads/authorization-url", response_model=TikTokAuthorizationUrlResponse)
def tiktok_authorization_url(_: User = Depends(require_admin), db: Session = Depends(get_db)):
    config = _tiktok_integration(db).config or {}
    app_id = str(config.get("app_id") or "").strip()
    redirect_uri = str(config.get("redirect_uri") or "").strip()
    if not app_id or not redirect_uri:
        raise HTTPException(status_code=400, detail="TikTok Ads app_id and redirect_uri must be saved before connecting.")

    state = create_oauth_state(_.email, "tiktok_ads")
    query = urlencode({"app_id": app_id, "state": state, "redirect_uri": redirect_uri})
    return TikTokAuthorizationUrlResponse(authorization_url=f"https://ads.tiktok.com/marketing_api/auth?{query}")


@router.post("/integrations/tiktok_ads/authorization")
def complete_tiktok_authorization(
    payload: TikTokAuthorizationCallback,
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    if decode_oauth_state(payload.state, "tiktok_ads") != _.email:
        raise HTTPException(status_code=400, detail="TikTok authorization state is invalid or expired. Start the connection again.")

    integration = _tiktok_integration(db)
    config = dict(integration.config or {})
    try:
        data = TikTokAdsConnector.exchange_authorization_code(config, payload.auth_code)
    except (TikTokAdsApiError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    config["access_token"] = str(data["access_token"])
    config["oauth_authorized"] = True
    integration.config = config
    db.commit()
    return {"connected": True}


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
