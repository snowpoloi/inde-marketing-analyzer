import json
from datetime import date
from decimal import Decimal as D
from pathlib import Path

import pytest

from app.services.product_sales_costing import net_product_sale
from app.services.supplier_costing import CostOption, margin_metrics, select_cost_as_of


FIXTURE = json.loads((Path(__file__).parent / "fixtures/megapap_acceptance.json").read_text())


def test_real_megapap_financial_acceptance():
    f = FIXTURE
    sale = net_product_sale({"prices_include_vat": True, "vat_rate": f["vat_rate"]}, f["selling_price_gross"], 1)
    result = margin_metrics(sale.net_sales, sale.quantity, f["purchase_unit_cost_net"])
    assert result["net_sales"] == D("12.8226")
    assert result["gross_profit"] == D("4.0926")
    assert result["margin_percent"] == D("31.92")
    ratio = D(f["supplier_freight_net"]) / D(f["supplier_order_net_products"]) * 100
    assert ratio.quantize(D("0.01")) == D("5.72")


@pytest.mark.parametrize("sold,expected", [("2026-08-15", "8.20"), ("2026-09-15", "8.50"), ("2026-10-02", "8.73")])
def test_real_megapap_historical_acceptance(sold, expected):
    costs = [CostOption(r["date"], date.fromisoformat(r["date"]), "invoice", D(r["cost"])) for r in FIXTURE["historical_costs"]]
    assert select_cost_as_of(costs, date.fromisoformat(sold)).net_unit_cost == D(expected)
    assert select_cost_as_of(costs, date(2026, 6, 30)) is None


def test_real_megapap_ledger_acceptance(db):
    from test_supplier_integration import payload, seed, sale
    from app.services.supplier_service import import_supplier_documents, product_profitability, supplier_performance

    seed(db)
    for row in FIXTURE["historical_costs"]:
        import_supplier_documents(db, payload(row["date"], row["date"], row["cost"]))
    sale(db, day="2026-10-02")
    result = product_profitability(db, date(2026, 10, 2), date(2026, 10, 2), ["completed"])[0]
    assert result["cogs"] == 8.73
    assert result["margin_percent"] == 31.92
    logistics = payload("LOGISTICS", "2026-10-03", "85.68")
    import_supplier_documents(db, logistics)
    row = supplier_performance(db, date(2026, 10, 3), date(2026, 10, 3))[0]
    assert row["purchases"] == 85.68
    assert row["freight"] == 4.9
    assert row["freight_ratio"] == pytest.approx(5.719, abs=0.001)
    assert product_profitability(db, date(2026, 10, 2), date(2026, 10, 2), ["completed"])[0]["margin_percent"] == 31.92
