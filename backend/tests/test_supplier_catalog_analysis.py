from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import uuid4

import pytest

from app.models import AADEDocument, ProductCatalog, SupplierCatalogProduct
from app.services.supplier_aade_costs import accept_invoice, invoice_preview
from app.services.supplier_catalog_service import catalog_products
from app.services.supplier_catalog_summary import period_summary
from test_supplier_aade_costs import seed, payload
from test_supplier_api import client as supplier_client


def client(db, admin):
    from app.api.routes import supplier_catalog
    http = supplier_client(db, admin)
    http.app.include_router(supplier_catalog.router, prefix="/api")
    return http


def purchase(db, user, supplier, feed_id, code, price, unit_cost, quantity, name):
    product = ProductCatalog(sku=code, name=name, price=price, raw={"prices_include_vat": True, "vat_rate": 24})
    db.add(product); db.flush()
    item = SupplierCatalogProduct(feed_id=feed_id, supplier_code=code, supplier_sku=code, name=name,
        product_catalog_id=product.id, is_current=True, quantity=quantity,
        match_method="exact_identifiers", last_seen_at=datetime.now(timezone.utc))
    net = Decimal(str(unit_cost)) * quantity
    fiscal = AADEDocument(source_endpoint="RequestDocs", identity_key=code, mark=code,
        issuer_vat=supplier.vat_number, counterpart_vat="802216736", issue_date=date(2026, 9, 2),
        aa=code, series="A", currency="EUR", document_direction="expense", invoice_type="1.1",
        net_value=net, vat_amount=net * Decimal("0.24"), gross_value=net * Decimal("1.24"),
        raw={"record_type": "full_document", "invoiceDetails": [{"lineNumber": 1, "itemCode": code,
            "quantity": quantity, "measurementUnit": 1, "netValue": str(net), "vatAmount": str(net * Decimal("0.24"))}]})
    db.add_all([item, fiscal]); db.commit()
    db.expire_all()
    accept_invoice(db, fiscal.id, payload(invoice_preview(db, fiscal.id, supplier.id)), user)
    return product, item, fiscal


def catalog(db, **options):
    return catalog_products(db, **{ "feed_id": None, "q": "", "match": "all", "availability": "all",
        "category": "", "offset": 0, "limit": 50, **options })


def test_margin_filter_and_sort_cover_the_entire_catalog(db):
    user, supplier, own, item, fiscal = seed(db)
    accept_invoice(db, fiscal.id, payload(invoice_preview(db, fiscal.id, supplier.id)), user)
    for n in range(60):
        db.add(SupplierCatalogProduct(feed_id=item.feed_id, supplier_code=f"filler-{n:02}", name=f"A filler {n:02}",
            is_current=True, quantity=n, last_seen_at=datetime.now(timezone.utc)))
    _, _, high = purchase(db, user, supplier, item.feed_id, "high", 248, 20, 8, "Z high margin")
    purchase(db, user, supplier, item.feed_id, "zero", 124, 100, 1, "Z zero margin")
    purchase(db, user, supplier, item.feed_id, "negative", 124, 120, 1, "Z negative margin")
    filtered = catalog(db, has_margin=True, sort_by="gross_margin_percent", sort_direction="desc", limit=2)
    assert filtered["total"] == 4
    assert [row["supplier_code"] for row in filtered["rows"]] == ["high", "0268292"]
    assert [row["gross_margin_percent"] for row in catalog(db, has_margin=True,
        sort_by="gross_margin_percent", sort_direction="desc", offset=2)["rows"]] == [0, -20]
    assert catalog(db, has_margin=True, q="negative")["total"] == 1
    assert catalog(db, has_margin=True, match="unmatched")["total"] == 0
    assert catalog(db, has_margin=True, feed_id=uuid4())["total"] == 0
    # Missing margins remain last in both directions, never sorted as zero.
    for direction, first in [("asc", "negative"), ("desc", "high")]:
        all_rows = catalog(db, sort_by="gross_margin_percent", sort_direction=direction, limit=100)
        assert all_rows["total"] == 64
        assert all_rows["rows"][0]["supplier_code"] == first
        assert all_rows["rows"][-1]["gross_margin_percent"] is None
    high.is_cancelled = True; db.flush()
    assert catalog(db, has_margin=True)["total"] == 3


def test_numeric_and_text_sorts_and_paging(db):
    user, supplier, _, item, fiscal = seed(db)
    accept_invoice(db, fiscal.id, payload(invoice_preview(db, fiscal.id, supplier.id)), user)
    purchase(db, user, supplier, item.feed_id, "low", 12.4, 5, 10, "A low")
    purchase(db, user, supplier, item.feed_id, "high", 248, 150, 2, "Z high")
    assert [row["aade_cost_net"] for row in catalog(db, sort_by="aade_cost_net")["rows"]] == [5, 70, 150]
    assert catalog(db, sort_by="inde_price", sort_direction="desc", limit=1)["rows"][0]["inde_price"] == 248
    assert catalog(db, sort_by="quantity", sort_direction="desc", limit=1)["rows"][0]["quantity"] == 10
    assert catalog(db, has_margin=True, sort_by="name", sort_direction="desc", limit=1)["rows"][0]["name"] == "Z high"
    ids = [catalog(db, sort_by="name", limit=1, offset=n)["rows"][0]["id"] for n in range(3)]
    assert len(set(ids)) == 3


def test_period_totals_deduplicate_credits_and_weight_margins_by_units(db):
    user, supplier, _, item, fiscal = seed(db)
    accept_invoice(db, fiscal.id, payload(invoice_preview(db, fiscal.id, supplier.id)), user)
    purchase(db, user, supplier, item.feed_id, "second", 248, 150, 8, "Second")
    purchase(db, user, supplier, item.feed_id, "third", 124, 100, 1, "Third")
    def copy(mark, amount, invoice_type="1.1", **extra):
        row = AADEDocument(source_endpoint="RequestDocs", identity_key=str(uuid4()), mark=mark,
            issuer_vat=supplier.vat_number, counterpart_vat="802216736", issue_date=date(2026, 9, 3),
            invoice_type=invoice_type, currency="EUR", document_direction="expense", net_value=amount,
            raw={"record_type": "full_document"}, **extra)
        db.add(row)
        return row
    copy("CREDIT", 20, "5.1"); copy("CREDIT", -20, "5.1")
    # A duplicate invoice is not a second purchase.
    duplicate = copy(fiscal.mark, 145)
    for field in ("issue_date", "aa", "series", "vat_amount", "gross_value", "raw"):
        setattr(duplicate, field, getattr(fiscal, field))
    copy("CANCELLED", 900, is_cancelled=True)
    other = copy("WRONG-RECIPIENT", 1000); other.counterpart_vat = "111111111"
    other = copy("BOOK-ROW", 9999); other.raw = {"record_type": "book_info"}
    other = copy("FOREIGN", 1000); other.currency = "USD"
    db.flush()
    db.expire_all()
    result = period_summary(db, date(2026, 9, 1), date(2026, 9, 30))
    row = result["rows"][0]
    assert row["purchases_net"] == 1445
    assert row["credits_net"] == 20 and row["net_purchases"] == 1425
    assert row["invoices"] == 3 and row["credit_notes"] == 1
    assert row["costed_products_net"] == 1440 and row["priced_units"] == 11
    assert row["catalog_profit_net"] == 460
    assert row["average_profit_per_unit"] == Decimal("41.8182")
    assert row["average_margin_percent"] == Decimal("24.2105")
    assert period_summary(db, date(2026, 9, 2), date(2026, 9, 30), item.feed_id)["rows"][0]["purchases_net"] == 1300
    assert period_summary(db, date(2026, 8, 1), date(2026, 8, 31))["rows"][0]["average_margin_percent"] is None


def test_period_missing_prices_cancellations_and_conflicts_are_not_profit(db):
    user, supplier, own, item, fiscal = seed(db)
    accept_invoice(db, fiscal.id, payload(invoice_preview(db, fiscal.id, supplier.id)), user)
    own.raw = {}; db.flush()
    row = period_summary(db, date(2026, 9, 1), date(2026, 9, 30))["rows"][0]
    assert row["purchases_net"] == 145 and row["costed_units"] == 2
    assert row["priced_units"] == 0 and row["average_profit_per_unit"] is None
    copy = AADEDocument(source_endpoint="RequestTransmittedDocs", identity_key="cancel-copy", mark=fiscal.mark,
        issuer_vat=supplier.vat_number, counterpart_vat="802216736", issue_date=date(2026, 10, 1),
        invoice_type="1.1", document_direction="expense", currency="EUR", net_value=145, is_cancelled=True)
    db.add(copy); db.flush()
    row = period_summary(db, date(2026, 9, 1), date(2026, 9, 30))["rows"][0]
    assert row["purchases_net"] == 0 and row["costed_units"] == 0
    copy.is_cancelled = False; copy.issue_date = fiscal.issue_date; copy.net_value = 999; db.flush()
    row = period_summary(db, date(2026, 9, 1), date(2026, 9, 30))["rows"][0]
    assert row["excluded_conflicts"] == 1 and row["purchases_net"] == 0
    assert row["average_margin_percent"] is None


def test_catalog_analysis_api_validation_and_admin_access(db):
    seed(db)
    with client(db, admin=True) as http:
        assert http.get("/api/supplier-catalog/period-summary?date_from=2026-09-01&date_to=2026-09-30").status_code == 200
        assert http.get("/api/supplier-catalog/period-summary?date_from=2026-09-30&date_to=2026-09-01").status_code == 422
        for query in ["sort_by=arbitrary_sql", "sort_direction=sideways", "has_margin=invalid"]:
            assert http.get("/api/supplier-catalog/products?" + query).status_code == 422
    with client(db, admin=False) as http:
        assert http.get("/api/supplier-catalog/period-summary?date_from=2026-09-01&date_to=2026-09-30").status_code == 403


@pytest.mark.parametrize("adapter,field", [("megapap", "minimum"), ("pakoworld", "sell_step")])
def test_set_prices_costs_global_sort_and_period_profit(db, adapter, field):
    from app.models import SupplierCatalogFeed, SupplierProductCost
    from sqlalchemy import select
    user, supplier, _, first, _ = seed(db)
    db.get(SupplierCatalogFeed, first.feed_id).adapter = adapter
    product, item, _ = purchase(db, user, supplier, first.feed_id, "SET4", 248, 30, 8, "Set of four")
    item.details = {field: "4", "packages_per_item": "6"}
    item.wholesale_price_net = 30; item.retail_price_gross = 62
    db.commit(); db.expire_all()
    row = catalog(db, has_margin=True)["rows"][0]
    assert row["sale_quantity"] == 4
    assert row["inde_price"] == 248 and row["inde_price_net"] == 200
    assert row["aade_cost_net"] == 30 and row["aade_cost_sale_net"] == 120
    assert row["gross_profit_per_sale"] == 80 and row["gross_profit_per_unit"] == 20
    assert row["gross_margin_percent"] == 40
    assert row["wholesale_price_net"] == 120 and row["retail_price_gross"] == 248
    assert row["wholesale_price_per_piece_net"] == 30 and row["retail_price_per_piece_gross"] == 62
    assert catalog(db, sort_by="sale_quantity", sort_direction="desc")["rows"][0]["id"] == str(item.id)
    assert catalog(db, sort_by="wholesale_price_net", sort_direction="desc")["rows"][0]["wholesale_price_net"] == 120
    assert catalog(db, sort_by="aade_cost_sale_net")["rows"][0]["aade_cost_sale_net"] == 120
    period = period_summary(db, date(2026, 9, 1), date(2026, 9, 30))["rows"][0]
    assert period["costed_products_net"] == 240 and period["priced_units"] == 8
    assert period["catalog_sales_net"] == 400 and period["catalog_profit_net"] == 160
    assert period["average_profit_per_unit"] == 20 and period["average_margin_percent"] == 40
    assert db.scalar(select(SupplierProductCost.net_unit_cost)) == 30
    db.refresh(product); assert product.price == 248
    item.details = {field: "0"}; db.commit()
    assert catalog(db, has_margin=True)["total"] == 0
    assert period_summary(db, date(2026, 9, 1), date(2026, 9, 30))["rows"][0]["priced_units"] == 0


@pytest.mark.parametrize("adapter,field", [("megapap", "minimum"), ("pakoworld", "sell_step")])
@pytest.mark.parametrize("quantity", ["1", "2", "4", "6"])
def test_sale_quantity_and_invoice_piece_cost_are_separate(adapter, field, quantity):
    from types import SimpleNamespace
    from app.services.supplier_catalog_pricing import sale_quantity, price_comparison
    step = sale_quantity(adapter, quantity)
    cost = SimpleNamespace(net_unit_cost=Decimal("6.90"), purchase_date=date(2026, 9, 1))
    own = SimpleNamespace(price=Decimal("49.60"), raw={})
    row = price_comparison(own, (cost,"MARK"), sale_quantity=step, confirmed_vat_rate=24)
    assert row["inde_price"] == Decimal("49.60")
    assert row["aade_cost_sale_net"] == Decimal("6.90") * Decimal(quantity)
    assert row["gross_profit_per_sale"] == 40 - Decimal("6.90") * Decimal(quantity)
    assert sale_quantity(adapter, "0") is None
    assert sale_quantity(adapter, "1.5") is None
    assert sale_quantity(adapter, "NaN") is None
    assert sale_quantity(adapter, None) == 1
