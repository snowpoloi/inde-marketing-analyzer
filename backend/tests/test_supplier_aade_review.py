from copy import deepcopy
from datetime import date
from uuid import uuid4
import hashlib
import json

import pytest
from sqlalchemy import func, select

from app.models import (AADEDocument, ProductCatalog, Supplier, SupplierCatalogFeed,
                        SupplierDocument, SupplierProductCost, SupplierProductMap)
from app.schemas.suppliers import SupplierAADEConfirmLineRequest
from app.services.supplier_aade_costs import accept_invoice, invoice_preview, validated_cost_rows
from app.services.supplier_aade_review import confirm_line, pending_costs
from app.services.supplier_catalog_service import apply_catalog
from app.services.supplier_aade_jobs import process_aade_costs
from test_supplier_aade_costs import seed, payload, auto_policy
from test_supplier_aade_partial import mixed_invoice
from test_supplier_api import client


def request(preview, product, line="1", **kwargs):
    return SupplierAADEConfirmLineRequest(supplier_id=preview["supplier_id"], line_number=line,
        product_catalog_id=product.id, fingerprint=preview["fingerprint"], source_digest=preview["source_digest"],
        preview_confirm_missing_units=preview["confirm_missing_units"], confirm_products_and_units=True, **kwargs)


def another_invoice(db, fiscal, **changes):
    values = {field: deepcopy(getattr(fiscal, field)) for field in ("source_endpoint", "issuer_vat", "counterpart_vat",
        "issue_date", "aa", "series", "currency", "document_direction", "invoice_type", "net_value", "vat_amount", "gross_value", "raw")}
    values.update(identity_key=f"next-invoice-{uuid4()}", mark=f"next-mark-{uuid4()}", aa="NEXT")
    values.update(changes)
    second = AADEDocument(**values)
    db.add(second); db.flush()
    return second


def test_manual_link_creates_aade_cost_and_survives_xml_sync(db):
    user, supplier, own, item, fiscal = seed(db)
    item.product_catalog_id = None
    db.flush()
    preview = invoice_preview(db, fiscal.id, supplier.id)
    result = confirm_line(db, fiscal.id, request(preview, own), user)
    assert result["costs_created"] == 1 and result["pending_lines"] == 0
    assert fiscal.raw["_catalog_cost"]["status"] == "imported"
    cost = db.scalar(select(SupplierProductCost))
    assert cost.source_type == "aade_invoice" and cost.net_unit_cost == 70
    assert validated_cost_rows(db, [cost]) == [cost]
    mapping = db.get(SupplierProductMap, cost.supplier_product_map_id)
    assert mapping.match_method == "aade_manual_reviewed" and mapping.verified_by == user.id
    assert mapping.raw_metadata["aade_review"]["source_digest"] == preview["source_digest"]
    assert item.product_catalog_id == own.id
    assert confirm_line(db, fiscal.id, request(preview, own), user)["duplicate"]
    feed = db.get(SupplierCatalogFeed, item.feed_id)
    # An intentionally reviewed bridge wins over otherwise ambiguous XML IDs.
    db.add(ProductCatalog(sku="OTHER-SKU", model=item.supplier_code, name="Duplicate identifier")); db.flush()
    apply_catalog(db, feed, [{"supplier_code": item.supplier_code, "supplier_sku": item.supplier_sku,
        "ean": item.ean, "name": "Updated title"}])
    db.expire(item)
    assert item.product_catalog_id == own.id and item.match_method == "manual_aade"
    second = another_invoice(db, fiscal)
    assert invoice_preview(db, second.id, supplier.id)["can_import"]
    auto_policy(db, user, supplier)
    assert process_aade_costs(db)["costs_created"] == 1
    assert db.scalar(select(func.count()).select_from(SupplierProductCost)) == 2


def test_only_selected_line_is_accepted_and_other_lines_stay_pending(db):
    user, supplier, own, _, fiscal = mixed_invoice(db)
    second = ProductCatalog(sku="SECOND-INDE", name="Second chair", price=50)
    db.add(second); db.flush()
    before = invoice_preview(db, fiscal.id, supplier.id)
    result = confirm_line(db, fiscal.id, request(before, second, "2"), user)
    assert result["costs_created"] == result["pending_lines"] == 1
    assert fiscal.raw["_catalog_cost"]["status"] == "partial"
    assert db.scalar(select(SupplierProductCost.product_catalog_id)) == second.id
    assert db.scalar(select(SupplierProductCost.net_unit_cost)) == 30
    document = db.scalar(select(SupplierDocument))
    assert document.net_products_total == 170 and document.raw_metadata["aade_partial"]
    review = pending_costs(db, date(2026,9,1), date(2026,9,1))
    assert review["total"] == 1 and [row["line_number"] for row in review["invoices"][0]["lines"]] == ["1"]
    accept_invoice(db, fiscal.id, payload(invoice_preview(db, fiscal.id, supplier.id)), user)
    assert pending_costs(db, date(2026,9,1), date(2026,9,1))["total"] == 0


@pytest.mark.parametrize("remember", [True, False])
def test_future_code_rule_is_scoped_to_supplier_and_optional(db, remember):
    user, supplier, own, item, fiscal = seed(db)
    fiscal.raw = {**fiscal.raw, "invoiceDetails": [{**fiscal.raw["invoiceDetails"][0], "itemCode": "UNKNOWN"}, fiscal.raw["invoiceDetails"][1]]}
    db.flush()
    confirm_line(db, fiscal.id, request(invoice_preview(db, fiscal.id, supplier.id), own, remember_match=remember), user)
    second = another_invoice(db, fiscal)
    assert invoice_preview(db, second.id, supplier.id)["can_import"] is remember
    other = Supplier(code="OTHER", name="Other", vat_number="111111111")
    db.add(other); db.flush()
    second.issuer_vat = other.vat_number
    db.flush()
    assert not invoice_preview(db, second.id, other.id)["can_import"]


def test_missing_code_requires_invoice_only_review(db):
    user, supplier, own, _, fiscal = seed(db)
    fiscal.raw = {**fiscal.raw, "invoiceDetails": [{**fiscal.raw["invoiceDetails"][0], "itemCode": None}, fiscal.raw["invoiceDetails"][1]]}
    db.flush()
    before = invoice_preview(db, fiscal.id, supplier.id)
    with pytest.raises(ValueError, match="missing invoice code"):
        confirm_line(db, fiscal.id, request(before, own), user)
    assert confirm_line(db, fiscal.id, request(before, own, remember_match=False), user)["costs_created"] == 1
    assert not invoice_preview(db, another_invoice(db, fiscal).id, supplier.id)["can_import"]


def test_piece_confirmation_does_not_authorize_other_missing_unit_lines(db):
    user, supplier, own, _, fiscal = mixed_invoice(db)
    fiscal.raw = {**fiscal.raw, "invoiceDetails": [{**row, "measurementUnit": None} for row in fiscal.raw["invoiceDetails"]]}
    db.flush()
    confirm_line(db, fiscal.id, request(invoice_preview(db, fiscal.id, supplier.id), own, confirm_missing_units=True), user)
    preview = invoice_preview(db, fiscal.id, supplier.id)
    assert preview["lines"][0]["costed"] and not preview["lines"][0]["reasons"]
    assert not preview["lines"][1]["ready"] and any("pieces" in reason for reason in preview["lines"][1]["reasons"])
    assert not db.scalar(select(SupplierDocument)).raw_metadata["aade_confirm_missing_units"]


@pytest.mark.parametrize("problem", ["totals", "cancelled", "recipient", "missing_amount", "negative", "duplicate_line", "quantity", "kg", "book"])
def test_human_review_never_bypasses_fiscal_or_unit_guards(db, problem):
    user, supplier, own, _, fiscal = seed(db)
    if problem == "totals": fiscal.net_value = 999
    elif problem == "cancelled": fiscal.is_cancelled = True
    elif problem == "recipient": fiscal.counterpart_vat = "other"
    elif problem == "book": fiscal.raw = {**fiscal.raw, "record_type": "book_info"}
    else:
        key, value = {"missing_amount": ("vatAmount", None), "negative": ("netValue", -140),
            "duplicate_line": ("lineNumber", 2), "quantity": ("quantity", 0), "kg": ("measurementUnit", 2)}[problem]
        fiscal.raw = {**fiscal.raw, "invoiceDetails": [{**fiscal.raw["invoiceDetails"][0], key:value}, fiscal.raw["invoiceDetails"][1]]}
    db.flush()
    with pytest.raises(ValueError):
        confirm_line(db, fiscal.id, request(invoice_preview(db, fiscal.id, supplier.id), own, confirm_missing_units=True), user)
    assert not db.scalar(select(SupplierProductCost.id))


@pytest.mark.parametrize("change", ["source", "mapping", "xml_running"])
def test_stale_preview_cannot_be_approved(db, change):
    user, supplier, own, item, fiscal = seed(db)
    before = invoice_preview(db, fiscal.id, supplier.id)
    if change == "source": fiscal.aa = "changed"
    elif change == "mapping": item.product_catalog_id = None
    else: db.get(SupplierCatalogFeed, item.feed_id).status = "running"
    db.flush()
    with pytest.raises(ValueError): confirm_line(db, fiscal.id, request(before, own), user)
    assert not db.scalar(select(SupplierProductCost.id))


def test_reviewed_identity_drift_requires_new_review_and_cannot_reassign_cost(db):
    user, supplier, own, item, fiscal = seed(db)
    confirm_line(db, fiscal.id, request(invoice_preview(db, fiscal.id, supplier.id), own), user)
    second = another_invoice(db, fiscal)
    item.ean = "changed"
    db.flush()
    preview = invoice_preview(db, second.id, supplier.id)
    assert not preview["can_import"] and any("identifiers changed" in reason for reason in preview["lines"][0]["reasons"])
    other = ProductCatalog(sku="OTHER", name="Other")
    db.add(other); db.flush()
    with pytest.raises(ValueError, match="already used"):
        confirm_line(db, second.id, request(preview, other), user)
    with pytest.raises(ValueError, match="cannot be reassigned"):
        confirm_line(db, fiscal.id, request(invoice_preview(db, fiscal.id, supplier.id), other), user)


def test_pending_period_supplier_dedup_and_paging(db):
    _, supplier, _, _, fiscal = seed(db)
    second = another_invoice(db, fiscal, issue_date=date(2026,10,1))
    duplicate = another_invoice(db, fiscal, issue_date=date(2026,10,1))
    duplicate.identity_key, duplicate.mark = "duplicate", second.mark
    duplicate.raw = {**duplicate.raw, "record_type":"book_info"}
    db.flush()
    result = pending_costs(db, date(2026,10,1), date(2026,10,1), supplier.id, 0, 1)
    assert result["total"] == 1 and result["invoices"][0]["id"] == str(second.id)
    assert result["invoices"][0]["lines"][0]["invoice_unit_cost_net"] == 70
    assert not pending_costs(db, date(2026,10,2), date(2026,10,2))["invoices"]
    assert not pending_costs(db, date(2026,10,1), date(2026,10,1), supplier.id, 1, 1)["invoices"]


def test_pending_api_admin_date_limit_and_forbidden_financial_inputs(db):
    _, supplier, own, _, fiscal = seed(db)
    query = "/api/suppliers/aade/pending-costs?date_from=2026-09-01&date_to=2026-09-01"
    body = request(invoice_preview(db, fiscal.id, supplier.id), own).model_dump(mode="json")
    with client(db, True) as http:
        assert http.get(query).json()["data"]["total"] == 1
        assert http.get(query + "&limit=11").status_code == 422
        assert http.get(query.replace("2026-09-01", "2024-09-01", 1)).status_code == 400
        assert http.post(f"/api/suppliers/aade/invoices/{fiscal.id}/confirm-line", json={**body,"net_unit_cost":0}).status_code == 422
    with client(db, False) as http:
        assert http.get(query).status_code == 403
        assert http.post(f"/api/suppliers/aade/invoices/{fiscal.id}/confirm-line", json=body).status_code == 403


def test_confirmation_api_atomic_rollback_and_success(db):
    from app.api.deps import get_current_user
    user, supplier, own, _, fiscal = seed(db)
    fiscal.raw = {**fiscal.raw,"invoiceDetails":[{**fiscal.raw["invoiceDetails"][0],"measurementUnit":2},fiscal.raw["invoiceDetails"][1]]}
    db.commit()
    body = request(invoice_preview(db, fiscal.id, supplier.id), own, confirm_missing_units=True).model_dump(mode="json")
    with client(db, True) as http:
        http.app.dependency_overrides[get_current_user] = lambda:user
        assert http.post(f"/api/suppliers/aade/invoices/{fiscal.id}/confirm-line", json=body).status_code == 409
        assert not db.scalar(select(SupplierProductMap.id))
        assert not db.scalar(select(SupplierProductCost.id))
        fiscal.raw = {**fiscal.raw,"invoiceDetails":[{**fiscal.raw["invoiceDetails"][0],"measurementUnit":1},fiscal.raw["invoiceDetails"][1]]}
        db.commit()
        body = request(invoice_preview(db, fiscal.id, supplier.id), own).model_dump(mode="json")
        response = http.post(f"/api/suppliers/aade/invoices/{fiscal.id}/confirm-line", json=body)
        assert response.status_code == 200 and response.json()["data"]["costs_created"] == 1
        assert http.post(f"/api/suppliers/aade/invoices/{fiscal.id}/confirm-line", json=body).json()["data"]["duplicate"]


def test_xml_identity_drift_does_not_silently_reuse_review(db):
    user, supplier, own, item, fiscal = seed(db)
    confirm_line(db, fiscal.id, request(invoice_preview(db, fiscal.id, supplier.id), own), user)
    apply_catalog(db, db.get(SupplierCatalogFeed,item.feed_id), [{"supplier_code":item.supplier_code,
        "supplier_sku":"changed-sku","ean":item.ean,"name":"Changed item"}])
    db.expire(item)
    assert item.product_catalog_id is None and item.match_method == "ambiguous"
    assert not invoice_preview(db, another_invoice(db,fiscal).id,supplier.id)["can_import"]


@pytest.mark.parametrize("legacy_hash", [False, True])
def test_manual_confirmation_preserves_verified_provider_lines(db, legacy_hash):
    from app.connectors.aade_detail import META_KEY, detail_info, source_fingerprint
    user, supplier, own, _, fiscal = seed(db)
    detail = deepcopy(fiscal.raw)
    raw = {"record_type":"full_document", "downloadingInvoiceUrl":"https://invoiceportal.gr/fixture",
        "_catalog_cost":{"status":"review"}}
    digest = hashlib.sha256(json.dumps(raw,sort_keys=True,default=str).encode()).hexdigest() if legacy_hash else source_fingerprint(raw)
    fiscal.raw = {**raw,META_KEY:{"status":"verified","source_hash":digest,"invoice":detail}}
    db.flush()
    preview = invoice_preview(db,fiscal.id,supplier.id)
    assert preview["can_import"]
    confirm_line(db,fiscal.id,request(preview,own),user)
    assert detail_info(fiscal.raw)["status"] == "verified"
    assert db.scalar(select(SupplierProductCost.net_unit_cost)) == 70
    assert validated_cost_rows(db,db.scalars(select(SupplierProductCost)).all())
