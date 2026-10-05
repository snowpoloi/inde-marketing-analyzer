from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.connectors.supplier_gmail import MAILBOX, MAX_BYTES, SupplierGmailReader, decode_body, eligible_sender, message_parts
from app.models import SupplierGmailSource, User
from app.schemas.suppliers import SupplierGmailReviewRequest, SupplierGmailSyncRequest, SupplierImportRequest
from app.services.supplier_service import import_supplier_documents
from app.supplier_parsers.megapap import MegapapParser


def _lock(db: Session):
    key = int.from_bytes(hashlib.sha256((MAILBOX + ":supplier-gmail").encode()).digest()[:8], "big", signed=True)
    db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": key})


def stage_source(db: Session, *, message_id: str, part_id: str, content: bytes,
                 filename: str | None = None, attachment_id: str | None = None,
                 html: bool = False, failure: str | None = None) -> SupplierGmailSource:
    _lock(db)
    source_key = hashlib.sha256(json.dumps([MAILBOX, message_id, part_id]).encode()).hexdigest()
    existing = db.scalar(select(SupplierGmailSource).where(SupplierGmailSource.source_key == source_key))
    if existing:
        return existing
    digest = hashlib.sha256(content).hexdigest()
    row = SupplierGmailSource(mailbox=MAILBOX, message_id=message_id, part_id=part_id,
        attachment_id=attachment_id, filename=filename, source_key=source_key,
        content_hash=digest, status="pending", normalized_payload={})
    if failure:
        row.status, row.reason = "review", failure
    else:
        duplicate = db.scalar(select(SupplierGmailSource).where(
            SupplierGmailSource.content_hash == digest, SupplierGmailSource.duplicate_of_id.is_(None),
            SupplierGmailSource.status.in_(["pending", "imported", "rejected"])).order_by(SupplierGmailSource.created_at))
        if duplicate:
            row.status, row.duplicate_of_id = "duplicate", duplicate.id
            row.reason = "Identical attachment/body already received."
        else:
            try:
                normalized = MegapapParser().parse(content.decode("utf-8") if html else content, filename=filename)
                # Transport IDs/hashes belong to the receipt, not the immutable financial document.
                semantic = hashlib.sha256(json.dumps([d.model_dump(mode="json") for d in normalized.documents],
                    sort_keys=True, ensure_ascii=True).encode()).hexdigest()
                duplicate = db.scalar(select(SupplierGmailSource).where(
                    SupplierGmailSource.semantic_hash == semantic, SupplierGmailSource.duplicate_of_id.is_(None),
                    SupplierGmailSource.status.in_(["pending", "imported", "rejected"])).order_by(SupplierGmailSource.created_at))
                row.semantic_hash = semantic
                if duplicate:
                    row.status, row.duplicate_of_id = "duplicate", duplicate.id
                    row.reason = "Same normalized document already received, including forwarded/renamed copies."
                else:
                    row.normalized_payload = normalized.model_dump(mode="json")
                    row.reason = "Confirm supplier order (not fiscal invoice) and freight net/VAT before financial import."
            except (ValueError, UnicodeDecodeError) as exc:
                row.status, row.reason = "review", str(exc)[:500]
    db.add(row)
    db.flush()
    return row


def sync_supplier_gmail(db: Session, request: SupplierGmailSyncRequest) -> dict:
    reader = SupplierGmailReader()
    counts = {"pending": 0, "duplicate": 0, "review": 0, "existing": 0}
    try:
        reader.authorize()
        page = reader.list_messages(request.date_from, request.date_to, request.page_token)
        for ref in page.get("messages", [])[:10]:
            message = reader.message(ref["id"])
            if not eligible_sender(message):
                continue
            parts = list(message_parts(message.get("payload", {})))
            files = [p for p in parts if p.get("filename") and not (
                p.get("mimeType", "").startswith("image/") and any(
                    h.get("name", "").casefold() == "content-disposition" and
                    h.get("value", "").casefold().startswith("inline") for h in p.get("headers", [])))]
            if len(files) > 10:
                row = stage_source(db, message_id=ref["id"], part_id="limit", content=b"",
                    failure="More than 10 attachments; manual document review required.")
                counts[row.status] = counts.get(row.status, 0) + 1
                db.commit()
                continue
            selected = files or [p for p in parts if p.get("mimeType") == "text/html"][:1] or [p for p in parts if p.get("mimeType") == "text/plain"][:1]
            for index, part in enumerate(selected):
                filename = str(part["filename"])[:500] if part.get("filename") else None
                fallback_id = hashlib.sha256(str(part.get("body", {}).get("attachmentId", index)).encode()).hexdigest()
                part_id = str(part.get("partId") or ("body" if not filename else fallback_id))[:128]
                source_key = hashlib.sha256(json.dumps([MAILBOX, ref["id"], part_id]).encode()).hexdigest()
                if db.scalar(select(SupplierGmailSource.id).where(SupplierGmailSource.source_key == source_key)):
                    counts["existing"] += 1
                    continue
                body = part.get("body", {})
                failure = None
                if int(body.get("size", 0)) > MAX_BYTES:
                    failure = "Attachment exceeds 10 MB; manual review required."
                elif filename and not filename.lower().endswith(".pdf"):
                    failure = "Only text-based MEGAPAP PDF attachments are supported in this phase."
                content = b""
                if not failure:
                    content = reader.attachment(ref["id"], body["attachmentId"]) if body.get("attachmentId") else decode_body(body.get("data", ""))
                    if not filename and b"SKU" not in content:
                        continue
                row = stage_source(db, message_id=ref["id"], part_id=part_id, content=content,
                    filename=filename, attachment_id=body.get("attachmentId"), html=not bool(filename), failure=failure)
                counts[row.status] = counts.get(row.status, 0) + 1
            # Preserve completed messages on a later timeout; immutable IDs make retries safe.
            db.commit()
        db.commit()
        return {"mailbox": MAILBOX, "supplier": "MEGAPAP", "next_page_token": page.get("nextPageToken"), **counts}
    finally:
        reader.close()


def gmail_source_rows(db: Session, *, offset: int = 0, limit: int = 100) -> list[dict]:
    sources = db.scalars(select(SupplierGmailSource).order_by(SupplierGmailSource.created_at.desc(), SupplierGmailSource.id)
        .offset(offset).limit(limit)).all()
    return [{"id": str(row.id), "mailbox": row.mailbox, "message_id": row.message_id,
        "filename": row.filename, "status": row.status, "reason": row.reason,
        "duplicate_of_id": str(row.duplicate_of_id) if row.duplicate_of_id else None,
        "created_at": row.created_at.isoformat(), "payload": row.normalized_payload} for row in sources]


def review_gmail_source(db: Session, source_id: UUID, request: SupplierGmailReviewRequest, user: User) -> dict:
    _lock(db)
    row = db.get(SupplierGmailSource, source_id, with_for_update=True, populate_existing=True)
    if row is None:
        raise ValueError("Gmail source not found.")
    if row.status == "imported":
        return {"duplicate": True, "documents_imported": 0}
    if row.status not in {"pending", "review"}:
        raise ValueError("This Gmail source is no longer pending.")
    row.reviewed_by, row.reviewed_at = user.id, datetime.now(timezone.utc)
    if request.action == "reject":
        row.status = "rejected"
        db.commit()
        return {"rejected": True}
    if not row.normalized_payload:
        raise ValueError("Unsupported/invalid document cannot be approved. Use a corrected normalized import.")
    if not request.confirm_supplier_order or request.shipping_net is None or request.shipping_vat is None:
        raise ValueError("Explicitly confirm supplier-order cost evidence and freight net/VAT.")
    payload = SupplierImportRequest.model_validate(row.normalized_payload)
    for document in payload.documents:
        freight = next(line for line in document.lines if line.line_type == "shipping")
        displayed = Decimal(freight.raw_metadata["displayed_amount"])
        if abs(request.shipping_net + request.shipping_vat - displayed) > Decimal("0.02"):
            raise ValueError("Confirmed freight net plus VAT must equal the displayed freight amount.")
        freight.net_line_total, freight.vat_amount = request.shipping_net, request.shipping_vat
        freight.vat_rate = request.shipping_vat / request.shipping_net * 100 if request.shipping_net else 0
        freight.raw_metadata = {"displayed_amount": str(displayed), "tax_basis_confirmed": True}
        document.net_shipping_total = request.shipping_net
        document.raw_metadata = {"parser": "megapap_order_v1", "supplier_order_confirmed": True}
    payload.source_reference = f"gmail:{MAILBOX}:{row.message_id}:{row.part_id}"
    payload.raw_metadata = {"gmail_source_id": str(row.id), "attachment_id": row.attachment_id,
                            "content_hash": row.content_hash}
    # Financial rows and receipt acceptance commit together, even if the process crashes.
    with db.begin_nested():
        result = import_supplier_documents(db, payload, user.id, commit=False)
        row.status = "imported"
        row.import_batch_id = UUID(result["batch_id"])
        row.reason = None
    db.commit()
    return result
