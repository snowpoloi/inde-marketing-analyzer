import hashlib
import hmac

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import decode_access_token
from app.db.session import get_db
from app.models import User

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login", auto_error=False)

# ADVESTIQ (the read-only ad-agency assistant) authenticates with its own key instead of a login.
ADVESTIQ_KEY_HEADER = "X-ADVESTIQ-Key"
# Never available to the key, even for reading: secrets, syncs (they write) and logins.
ADVESTIQ_BLOCKED_PREFIXES = ("/api/settings/integrations", "/api/sync", "/api/auth")
# The only paths where the key may write.
ADVESTIQ_WRITE_PATHS = frozenset({"/api/advestiq/reports"})
ADVESTIQ_EMAIL = "advestiq@read-only.local"


def advestiq_key_matches(supplied: str | None, expected_sha256: str | None) -> bool:
    if not supplied or not expected_sha256:
        return False
    digest = hashlib.sha256(supplied.encode("utf-8")).hexdigest()
    return hmac.compare_digest(digest, expected_sha256.strip().lower())


def advestiq_user(request: Request) -> User | None:
    supplied = request.headers.get(ADVESTIQ_KEY_HEADER)
    if not supplied:
        return None
    if not advestiq_key_matches(supplied, settings.advestiq_api_key_sha256):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid ADVESTIQ key")
    path = request.url.path
    if path.startswith(ADVESTIQ_BLOCKED_PREFIXES):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="This endpoint is not available to the ADVESTIQ key")
    if request.method not in ("GET", "HEAD") and path not in ADVESTIQ_WRITE_PATHS:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="The ADVESTIQ key is read-only")
    # Transient principal: it is never added to a session, so it can never be saved.
    return User(email=ADVESTIQ_EMAIL, hashed_password="!", is_admin=True, is_active=True)


def get_current_user(request: Request, token: str | None = Depends(oauth2_scheme), db: Session = Depends(get_db)) -> User:
    if not token:
        user = advestiq_user(request)
        if user is not None:
            return user
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )

    subject = decode_access_token(token)
    if not subject:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user = db.scalar(select(User).where(User.email == subject))
    if not user or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Inactive or missing user")
    return user


def require_admin(user: User = Depends(get_current_user)) -> User:
    if not user.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")
    return user
