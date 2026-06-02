from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.api.routes import auth, banks, dashboard, settings, sync
from app.core.config import settings as app_settings
from app.db.session import SessionLocal
from app.services.seed import ensure_admin_user, ensure_default_integrations

app = FastAPI(
    title=app_settings.app_name,
    version="0.1.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=app_settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router, prefix="/api")
app.include_router(settings.router, prefix="/api")
app.include_router(sync.router, prefix="/api")
app.include_router(dashboard.router, prefix="/api")
app.include_router(banks.router, prefix="/api")


@app.on_event("startup")
def startup() -> None:
    with SessionLocal() as db:
        ensure_default_integrations(db)
        ensure_admin_user(db)


@app.get("/health")
def health() -> dict[str, str]:
    with SessionLocal() as db:
        db.execute(text("SELECT 1"))
    return {"status": "ok", "app": app_settings.app_name}
