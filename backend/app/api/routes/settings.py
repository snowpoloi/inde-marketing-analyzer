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

# Secrets never leave the server: responses carry a masked placeholder, and a placeholder sent back
# on save keeps the stored value.
SECRET_KEY_PARTS = (
    "token", "secret", "password", "api_key", "apikey", "subscription_key",
    "credentials_json", "service_account_json", "private_key",
)
MASK_PREFIX = "••••"


def is_secret_config_key(name: str) -> bool:
    lowered = name.lower()
    return any(part in lowered for part in SECRET_KEY_PARTS)


def _masked(value):
    if value in (None, "") or value == {} or value == []:
        return value
    if isinstance(value, str) and len(value) > 12:
        return MASK_PREFIX + value[-4:]
    return MASK_PREFIX


def mask_config(config: dict | None) -> dict:
    return {key: (_masked(value) if is_secret_config_key(key) else value) for key, value in (config or {}).items()}


def merge_masked_config(incoming: dict | None, stored: dict | None) -> dict:
    merged = dict(incoming or {})
    stored = stored or {}
    for key, value in merged.items():
        if key in stored and is_secret_config_key(key) and isinstance(value, str) and value.startswith(MASK_PREFIX):
            merged[key] = stored[key]
    return merged


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
    integrations = db.scalars(select(IntegrationSetting).where(IntegrationSetting.provider.notin_(["supplier_catalog", "order_shipping"]))
                             .order_by(IntegrationSetting.display_name)).all()
    return [
        IntegrationSettingResponse(
            provider=item.provider,
            display_name=item.display_name,
            is_enabled=item.is_enabled,
            config=mask_config(item.config),
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
    integration.config = merge_masked_config(payload.config, integration.config)
    db.commit()
    db.refresh(integration)
    return IntegrationSettingResponse(
        provider=integration.provider,
        display_name=integration.display_name,
        is_enabled=integration.is_enabled,
        config=mask_config(integration.config),
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
