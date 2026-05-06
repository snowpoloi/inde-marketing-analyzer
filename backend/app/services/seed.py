from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import hash_password
from app.models import IntegrationSetting, User
from app.services.constants import PROVIDERS


def ensure_default_integrations(db: Session) -> None:
    for provider, display_name in PROVIDERS.items():
        existing = db.scalar(select(IntegrationSetting).where(IntegrationSetting.provider == provider))
        if not existing:
            db.add(IntegrationSetting(provider=provider, display_name=display_name, is_enabled=False, config={}))
    db.commit()


def ensure_admin_user(db: Session) -> None:
    if not settings.admin_email or not settings.admin_password:
        return

    existing = db.scalar(select(User).where(User.email == settings.admin_email))
    if existing:
        return

    db.add(
        User(
            email=settings.admin_email,
            hashed_password=hash_password(settings.admin_password),
            is_active=True,
            is_admin=True,
        )
    )
    db.commit()

