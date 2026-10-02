from datetime import date
from decimal import Decimal as D

import pytest
from pydantic import ValidationError

from app.schemas.suppliers import SupplierDocumentLineInput
from app.services.product_sales_costing import allocate_coupon, net_product_sale
from app.services.supplier_costing import (
    CatalogIdentity, CostOption, calculate_purchase_line, exact_catalog_matches,
    fuzzy_catalog_candidates, margin_metrics, select_cost_as_of,
)


def catalog(key="one", sku="INDE-1", model="GP041-0025,4", name="Chair", ean=None):
    return CatalogIdentity(key, sku, model, key, ean, None, None, name)


@pytest.mark.parametrize("sale,expected", [(date(2026, 6, 30), None), (date(2026, 7, 1), "8.20"),
    (date(2026, 8, 15), "8.20"), (date(2026, 9, 15), "8.50"), (date(2026, 10, 2), "8.73")])
def test_historical_boundaries(sale, expected):
    costs = [CostOption(str(day), date(2026, month, day), "invoice", D(cost))
             for month, day, cost in [(7, 1, "8.20"), (9, 1, "8.50"), (10, 2, "8.73")]]
    chosen = select_cost_as_of(costs, sale)
    assert (chosen.net_unit_cost if chosen else None) == (D(expected) if expected else None)


def test_invoice_priority_and_inactive_costs():
    costs = [CostOption("invoice", date(2026, 7, 1), "invoice", D("8.2")),
             CostOption("price", date(2026, 9, 1), "pricelist", D("9")),
             CostOption("void", date(2026, 9, 2), "invoice", D("2"), status="superseded"),
             CostOption("credit", date(2026, 9, 3), "credit_note", D("-8"), status="credit")]
    assert select_cost_as_of(costs, date(2026, 10, 2)).key == "invoice"


def test_megapap_ignores_internal_code_and_fuzzy_never_matches():
    catalogs = [catalog(), catalog("two", sku="0212605", model=None)]
    result = exact_catalog_matches(catalogs, supplier="MEGAPAP", supplier_sku="GP041-0025,4", supplier_code="0212605")
    assert [candidate.catalog.key for candidate in result] == ["one"]
    assert not exact_catalog_matches(catalogs, supplier="MEGAPAP", supplier_code="0212605")
    assert fuzzy_catalog_candidates(catalogs, description="Chair")[0].method == "name_candidate_only"


def test_exact_priority_and_ambiguous_ties():
    catalogs = [catalog("sku", sku="A", model="B"), catalog("model", sku="C", model="A")]
    assert exact_catalog_matches(catalogs, supplier="supplier", supplier_sku="A")[0].catalog.key == "sku"
    assert len(exact_catalog_matches([catalog(), catalog("two")], supplier="MEGAPAP", supplier_sku="GP041-0025,4")) == 2
    assert not exact_catalog_matches([catalog(sku="AB", model=None)], supplier="supplier", supplier_sku="A B")


def test_purchase_discount_conversion_and_zero_quantity_shipping():
    assert calculate_purchase_line(quantity=2, unit_price_before_discount=10, discount_percent=10, conversion_factor=2) == (D("18"), D("4.5"))
    assert calculate_purchase_line(quantity=0, unit_price_before_discount=0, net_line_total="4.90") == (D("4.9"), D("0"))


def test_megapap_margin_excludes_shipping():
    sale = net_product_sale({"prices_include_vat": True, "vat_rate": 24}, "15.90", 1)
    metrics = margin_metrics(sale.net_sales, sale.quantity, "8.73")
    assert sale.net_sales == D("12.8226")
    assert metrics["gross_profit"] == D("4.0926")
    assert metrics["margin_percent"] == D("31.92")


@pytest.mark.parametrize("raw,price,qty,coupon,expected,remaining", [
    ({"subtotal": 100, "discount": 10}, 100, 1, -5, "85", 1),
    ({"net_total": 0}, 100, 1, 0, "0", 1),
    ({"total": 90, "discount": 10}, 100, 1, 0, "90", 1),
    ({"net_total": 80, "includes_order_discount": True}, 100, 1, -5, "80", 1),
    ({"gross_total": 124, "tax_amount": 24}, 124, 1, 0, "100", 1),
    ({"returned_quantity": 1}, 10, 2, -2, "9", 1),
    ({"refund_net": 5}, 10, 2, 0, "15", 2),
    ({"returned_quantity": 2}, 10, 2, 0, "0", 0),
    ({"net_total": 100, "coupon_share": 5}, 100, 1, -5, "95", 1),
    ({"net_total": 95, "coupon_share": 5, "includes_order_discount": True}, 100, 1, -5, "95", 1),
])
def test_net_sales(raw, price, qty, coupon, expected, remaining):
    sale = net_product_sale(raw, price, qty, coupon)
    assert sale.net_sales == D(expected)
    assert sale.quantity == remaining


def test_unknown_vat_and_coupon_rounding():
    assert net_product_sale({"gross_total": 124}, 124, 1).net_sales is None
    assert sum(allocate_coupon([D("1")] * 3, D("-1"))) == D("-1")
    assert net_product_sale({"net_total": "NaN"}, 10, 1).net_sales is None
    assert net_product_sale({"returned_quantity": 1}, 10, 2, apply_refunds=False).net_sales == 20


@pytest.mark.parametrize("changes", [{"quantity": 0}, {"unit_price_before_discount": "NaN"}, {"conversion_factor": 0}])
def test_invalid_import_values(changes):
    with pytest.raises(ValidationError):
        SupplierDocumentLineInput.model_validate({"supplier_sku": "A", "quantity": 1, **changes})
