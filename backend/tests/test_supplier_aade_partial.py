from datetime import date, datetime, timezone

import pytest
from sqlalchemy import func, select

from app.models import (AADEDocument, IntegrationSetting, ProductCatalog, SupplierCatalogFeed,
                        SupplierCatalogProduct, SupplierDocument, SupplierDocumentLine, SupplierProductCost)
from app.services.supplier_aade_costs import accept_invoice, invoice_preview, validated_cost_rows
from app.services.supplier_aade_jobs import process_aade_costs, process_aade_cost_batch
from app.services.supplier_catalog_settings import queue_cost_refresh
from test_supplier_aade_costs import seed, auto_policy, payload, batch_payload


def mixed_invoice(db):
    user, supplier, own, item, fiscal = seed(db)
    fiscal.raw = {**fiscal.raw, "invoiceDetails": [fiscal.raw["invoiceDetails"][0],
        {"lineNumber": 2, "itemCode": "SECOND", "itemDescr": "Second chair", "quantity": 1,
         "measurementUnit": 1, "netValue": 30, "vatAmount": 7.2},
        {**fiscal.raw["invoiceDetails"][1], "lineNumber": 3}]}
    fiscal.net_value, fiscal.vat_amount, fiscal.gross_value = 175, 42, 217
    db.commit()
    return user, supplier, own, item, fiscal


def resolve_second(db, item):
    product = ProductCatalog(sku="SECOND", name="Second chair", price=50)
    db.add(product)
    db.flush()
    db.add(SupplierCatalogProduct(feed_id=item.feed_id, supplier_code="SECOND", supplier_sku="SECOND",
        product_catalog_id=product.id, name="Second chair", is_current=True, last_seen_at=datetime.now(timezone.utc)))
    db.flush()
    return product


def test_partial_costs_backfill_same_full_invoice_without_duplicates(db):
    user, supplier, own, item, fiscal = mixed_invoice(db)
    preview = invoice_preview(db, fiscal.id, supplier.id)
    assert (preview["ready_lines"], preview["pending_lines"], preview["costed_lines"]) == (1, 1, 0)
    first = accept_invoice(db, fiscal.id, payload(preview), user)
    assert first["costs_created"] == first["pending_lines"] == 1
    document = db.scalar(select(SupplierDocument))
    assert document.net_products_total == 170 and document.net_shipping_total == 5
    assert document.vat_total == 42 and document.gross_total == 217
    assert document.raw_metadata["aade_partial"] is True
    assert db.scalar(select(func.count()).select_from(SupplierDocumentLine)) == 3
    unresolved = db.scalar(select(SupplierDocumentLine).where(SupplierDocumentLine.line_number == "2"))
    assert unresolved.net_line_total == 30 and unresolved.supplier_product_map_id is None
    assert unresolved.raw_metadata["aade_pending_reasons"]
    original = db.scalar(select(SupplierProductCost))
    original_id = original.id
    assert accept_invoice(db, fiscal.id, payload(invoice_preview(db, fiscal.id, supplier.id)), user)["duplicate"]
    product = resolve_second(db, item)
    preview = invoice_preview(db, fiscal.id, supplier.id)
    assert (preview["ready_lines"], preview["pending_lines"], preview["costed_lines"]) == (1, 0, 1)
    assert accept_invoice(db, fiscal.id, payload(preview), user)["costs_created"] == 1
    costs = db.scalars(select(SupplierProductCost)).all()
    assert len(costs) == 2 and original_id in {row.id for row in costs}
    assert sum(row.net_line_total for row in costs) == 170
    assert {row.product_catalog_id for row in costs} == {own.id, product.id}
    assert len(validated_cost_rows(db, costs)) == 2
    assert db.scalar(select(func.count()).select_from(SupplierDocument)) == 1
    assert db.scalar(select(func.count()).select_from(SupplierDocumentLine)) == 3
    assert not db.scalar(select(SupplierDocument)).raw_metadata["aade_partial"]
    assert accept_invoice(db, fiscal.id, payload(invoice_preview(db, fiscal.id, supplier.id)), user)["duplicate"]


@pytest.mark.parametrize("field,value", [("itemCode", None), ("itemCode", "unknown"),
    ("measurementUnit", 2), ("measurementUnit", None), ("quantity", None), ("quantity", 0), ("recType", 1)])
def test_bad_product_does_not_block_safe_product_or_receive_assumed_cost(db, field, value):
    user, supplier, _, item, fiscal = mixed_invoice(db)
    resolve_second(db, item)
    fiscal.raw = {**fiscal.raw, "invoiceDetails": [fiscal.raw["invoiceDetails"][0],
        {**fiscal.raw["invoiceDetails"][1], field: value}, fiscal.raw["invoiceDetails"][2]]}
    db.flush()
    preview = invoice_preview(db, fiscal.id, supplier.id)
    assert preview["can_import"] and preview["pending_lines"] == 1
    assert accept_invoice(db, fiscal.id, payload(preview), user)["costs_created"] == 1
    assert db.scalar(select(SupplierProductCost.net_line_total)) == 140


@pytest.mark.parametrize("problem", ["totals", "cancelled", "recipient", "missing_amount", "negative", "duplicate_line"])
def test_global_fiscal_guards_still_block_partial_import(db, problem):
    user, supplier, _, _, fiscal = mixed_invoice(db)
    if problem == "totals":
        fiscal.net_value = 999
    elif problem == "cancelled":
        fiscal.is_cancelled = True
    elif problem == "recipient":
        fiscal.counterpart_vat = "other"
    else:
        field, value = {"missing_amount": ("vatAmount", None), "negative": ("netValue", -30),
                        "duplicate_line": ("lineNumber", 1)}[problem]
        fiscal.raw = {**fiscal.raw, "invoiceDetails": [fiscal.raw["invoiceDetails"][0],
            {**fiscal.raw["invoiceDetails"][1], field: value}, fiscal.raw["invoiceDetails"][2]]}
    db.flush()
    preview = invoice_preview(db, fiscal.id, supplier.id)
    assert not preview["can_import"]
    with pytest.raises(ValueError, match="needs review"):
        accept_invoice(db, fiscal.id, payload(preview), user)
    assert db.scalar(select(func.count()).select_from(SupplierDocument)) == 0


def test_changed_or_cancelled_source_cannot_backfill_partial_costs(db):
    user, supplier, _, item, fiscal = mixed_invoice(db)
    preview = invoice_preview(db, fiscal.id, supplier.id)
    accept_invoice(db, fiscal.id, payload(preview), user)
    resolve_second(db, item)
    fiscal.raw = {**fiscal.raw, "invoiceDetails": [{**row, "itemDescr": "Changed"}
        for row in fiscal.raw["invoiceDetails"]]}
    db.flush()
    preview = invoice_preview(db, fiscal.id, supplier.id)
    assert not preview["can_import"] and any("source changed" in reason for reason in preview["reasons"])
    with pytest.raises(ValueError, match="needs review"):
        accept_invoice(db, fiscal.id, payload(preview), user)
    assert not validated_cost_rows(db, db.scalars(select(SupplierProductCost)).all())
    assert db.scalar(select(func.count()).select_from(SupplierProductCost)) == 1


@pytest.mark.parametrize("refresh", ["xml", "sync"])
def test_background_partial_retries_after_inputs_change_without_six_hour_wait(db, refresh):
    user, supplier, _, item, fiscal = mixed_invoice(db)
    auto_policy(db, user, supplier)
    assert process_aade_costs(db)["status"] == "partial"
    assert process_aade_costs(db) == {"processed": 0}
    resolve_second(db, item)
    if refresh == "xml":
        db.get(SupplierCatalogFeed, item.feed_id).last_synced_at = datetime.now(timezone.utc)
    else:
        queue_cost_refresh(db)
    db.commit()
    result = process_aade_costs(db)
    assert result["status"] == "imported" and result["costs_created"] == 1
    assert process_aade_costs(db) == {"processed": 0}
    assert db.scalar(select(func.count()).select_from(SupplierProductCost)) == 2


def test_manual_batch_backfills_partial_and_reports_remaining_lines(db):
    from app.services.supplier_aade_costs import import_cost_batch
    user, supplier, _, item, fiscal = mixed_invoice(db)
    result = import_cost_batch(db, batch_payload(supplier), user)
    assert result["rows"][0]["status"] == "partial" and result["costs_created"] == 1
    resolve_second(db, item)
    db.commit()
    assert import_cost_batch(db, batch_payload(supplier), user)["costs_created"] == 1
    assert import_cost_batch(db, batch_payload(supplier), user)["rows"][0]["status"] == "already_imported"


def test_worker_batch_is_bounded(db, monkeypatch):
    calls = []
    monkeypatch.setattr("app.services.supplier_aade_jobs.process_aade_costs",
        lambda db: calls.append(1) or {"processed": 1, "costs_created": 2})
    assert process_aade_cost_batch(db, limit=100) == {"processed": 5, "costs_created": 10}
    assert len(calls) == 5


def test_cost_status_survives_unchanged_aade_resync_but_never_trusts_remote_metadata(db):
    from app.services.import_service import import_aade_payload
    user, supplier, _, _, fiscal = mixed_invoice(db)
    auto_policy(db, user, supplier)
    assert process_aade_costs(db)["status"] == "partial"
    metadata = fiscal.raw["_catalog_cost"]
    row = {key: getattr(fiscal, key) for key in ("source_endpoint", "identity_key", "mark", "uid", "issuer_vat", "counterpart_vat",
        "issue_date", "document_direction", "invoice_type", "series", "aa", "currency", "net_value", "vat_amount", "gross_value",
        "is_cancelled", "cancelled_by_mark")}
    row["raw"] = {**fiscal.raw, "_catalog_cost": {"status": "forged"}}
    import_aade_payload(db, {"documents": [row]}, fiscal.issue_date)
    db.refresh(fiscal)
    assert fiscal.raw["_catalog_cost"] == metadata
    row["raw"] = {**row["raw"], "invoiceDetails": [{**line, "itemDescr": "Changed"} for line in row["raw"]["invoiceDetails"]]}
    import_aade_payload(db, {"documents": [row]}, fiscal.issue_date)
    db.refresh(fiscal)
    assert "_catalog_cost" not in fiscal.raw


def test_retry_from_another_endpoint_copy_cannot_create_second_financial_invoice(db):
    user, supplier, _, item, fiscal = mixed_invoice(db)
    accept_invoice(db, fiscal.id, payload(invoice_preview(db, fiscal.id, supplier.id)), user)
    copy = AADEDocument(source_endpoint="RequestTransmittedDocs", identity_key="copy-partial", mark=fiscal.mark,
        issuer_vat=fiscal.issuer_vat, counterpart_vat=fiscal.counterpart_vat, issue_date=fiscal.issue_date,
        aa=fiscal.aa, series=fiscal.series, currency="EUR", document_direction="expense", invoice_type="1.1",
        net_value=fiscal.net_value, vat_amount=fiscal.vat_amount, gross_value=fiscal.gross_value, raw=fiscal.raw)
    db.add(copy)
    resolve_second(db, item)
    db.commit()
    assert accept_invoice(db, copy.id, payload(invoice_preview(db, copy.id, supplier.id)), user)["costs_created"] == 1
    assert db.scalar(select(func.count()).select_from(SupplierDocument)) == 1
    assert db.scalar(select(func.count()).select_from(SupplierProductCost)) == 2


@pytest.mark.parametrize("sync_type", ["scheduled", "manual"])
@pytest.mark.parametrize("provider", ["opencart", "aade"])
def test_successful_sync_queues_cost_reviews_for_both_sync_types(db, monkeypatch, sync_type, provider):
    from app.services.sync_service import run_provider_sync
    user, supplier, _, item, fiscal = mixed_invoice(db)
    auto_policy(db, user, supplier)
    assert process_aade_costs(db)["status"] == "partial"
    previous = fiscal.raw["_catalog_cost"]["input_revision"]
    resolve_second(db, item)
    if provider == "aade":
        db.get(IntegrationSetting, db.scalar(select(IntegrationSetting.id).where(IntegrationSetting.provider == "aade"))).is_enabled = True
        monkeypatch.setattr("app.services.sync_service.AADEConnector.fetch_documents", lambda *args: {"documents": []})
    else:
        db.add(IntegrationSetting(provider="opencart", display_name="OpenCart", is_enabled=True,
            config={"endpoint_url": "https://example.test/orders"}))
        monkeypatch.setattr("app.services.sync_service.OpenCartConnector.fetch_orders", lambda *args: [])
    db.commit()
    result = run_provider_sync(db, provider, date(2026, 9, 1), date(2026, 9, 30), sync_type=sync_type)
    assert result.status == "success", result.error_message
    assert result.meta["supplier_cost_refresh_queued"]
    if provider == "opencart":
        assert db.get(SupplierCatalogFeed, item.feed_id).status == "queued"
    assert process_aade_costs(db)["costs_created"] == 1
    db.refresh(fiscal)
    assert fiscal.raw["_catalog_cost"]["input_revision"] != previous
