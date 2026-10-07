"""Small, leased background batches; financial records are never accepted here."""

from datetime import datetime, timedelta, timezone
from uuid import uuid4
from urllib.parse import urlsplit

from sqlalchemy import func, or_, select

from app.connectors.aade_detail import DetailError, META_KEY, fetch_detail, source_fingerprint, validate_invoice
from app.models import AADEDocument, IntegrationSetting


def process_aade_details(db, *, batch_size=3, document_ids=None):
    now = datetime.now(timezone.utc)
    integration = db.scalar(select(IntegrationSetting).where(IntegrationSetting.provider == "aade"))
    own_vat = (integration.config or {}).get("vat_number") if integration else None
    if not own_vat or not integration.is_enabled:
        return {"processed": 0}
    processed = verified = 0
    for _ in range(min(max(batch_size, 1), 5)):
        meta = AADEDocument.raw[META_KEY]
        document = db.scalar(select(AADEDocument).where(
            AADEDocument.document_direction == "expense", AADEDocument.counterpart_vat == own_vat,
            *([AADEDocument.id.in_(document_ids)] if document_ids is not None else []),
            AADEDocument.is_cancelled.is_(False), AADEDocument.cancelled_by_mark.is_(None),
            func.coalesce(AADEDocument.raw["record_type"].astext, "full_document") == "full_document",
            AADEDocument.raw["downloadingInvoiceUrl"].astext.is_not(None),
            or_(meta["status"].astext.is_(None), meta["status"].astext.in_(["pending", "running", "retry"])),
            or_(meta["next_attempt_at"].astext.is_(None), meta["next_attempt_at"].astext <= now.isoformat()),
        ).order_by(AADEDocument.issue_date.desc(), AADEDocument.id).with_for_update(skip_locked=True).limit(1))
        if document is None:
            db.rollback()
            break
        raw = document.raw or {}
        old = raw.get(META_KEY) or {}
        source_hash, lease = source_fingerprint(raw), str(uuid4())
        attempts = int(old.get("attempts") or 0) + 1
        claim = {"status": "running", "source_hash": source_hash, "lease": lease, "attempts": attempts,
                 "next_attempt_at": (now + timedelta(minutes=5)).isoformat()}
        document.raw = {**raw, META_KEY: claim}
        document_id = document.id
        url = raw["downloadingInvoiceUrl"]
        db.commit()
        try:
            invoice = validate_invoice(document, fetch_detail(url))
            result = {**claim, "status": "verified", "invoice": invoice, "host": urlsplit(url).hostname,
                      "checked_at": datetime.now(timezone.utc).isoformat()}
        except DetailError as exc:
            result = {**claim, "status": "retry" if exc.retryable and attempts < 4 else "unavailable",
                      "reason": str(exc), "checked_at": datetime.now(timezone.utc).isoformat(),
                      "next_attempt_at": (datetime.now(timezone.utc) + timedelta(hours=attempts)).isoformat()}
        except Exception:
            result = {**claim, "status": "unavailable", "reason": "Provider detail could not be verified."}
        db.rollback()
        current = db.scalar(select(AADEDocument).where(AADEDocument.id == document_id).with_for_update())
        if (current and (current.raw.get(META_KEY) or {}).get("lease") == lease
                and source_fingerprint(current.raw) == source_hash and not current.is_cancelled and not current.cancelled_by_mark):
            current.raw = {**current.raw, META_KEY: result}
            verified += result["status"] == "verified"
        db.commit()
        processed += 1
    return {"processed": processed, "verified": verified}
