from datetime import date, timedelta

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.api.deps import require_admin
from app.db.session import get_db
from app.models import User
from app.schemas.dashboard import DashboardResponse
from app.services.bank_service import bank_dashboard, import_bank_transactions

router = APIRouter(prefix="/banks", tags=["banks"])


@router.get("/transactions", response_model=DashboardResponse)
def transactions(
    date_from: date | None = None,
    date_to: date | None = None,
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> DashboardResponse:
    end = date_to or date.today()
    start = date_from or end - timedelta(days=29)
    return DashboardResponse(data=bank_dashboard(db, start, end))


@router.post("/import")
async def import_bank_file(
    file: UploadFile = File(...),
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict[str, int | str]:
    filename = file.filename or "bank-export"
    content = await file.read()
    try:
        return import_bank_transactions(db, filename, content)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
