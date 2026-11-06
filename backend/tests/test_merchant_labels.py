from datetime import date
from decimal import Decimal

from app.connectors.merchant_center import MerchantCenterConnector
from app.models import MerchantProductMetric
from app.services.dashboard_service import _product_audit

DAY = date(2031, 3, 12)
CONFIG = {"refresh_token": "test-refresh", "client_id": "test-client", "client_secret": "test-secret",
          "account_id": "123456"}


def performance_view(**fields):
    return {"productPerformanceView": {"date": {"year": 2031, "month": 3, "day": 12}, "offerId": "SKU-1",
                                       "title": "Test sofa", "clicks": "7", "impressions": "300", **fields}}


def connector(monkeypatch, config, performance, health=()):
    queries = []

    def search(self, account_id, query):
        queries.append(query)
        return list(performance) if "product_performance_view" in query else list(health)

    monkeypatch.setattr(MerchantCenterConnector, "_search_report", search)
    return MerchantCenterConnector(config), queries


def test_performance_rows_carry_category_levels_and_custom_labels(monkeypatch):
    merchant, queries = connector(monkeypatch, CONFIG, [performance_view(
        categoryL1="Furniture", categoryL2="Living Room Furniture", categoryL3="Sofas",
        productTypeL1="Living room", productTypeL2="Sofas",
        customLabel0="bestseller", customLabel3="autumn")])
    rows = merchant.fetch_product_metrics(DAY, DAY)
    assert rows[0]["category_levels"] == ["Furniture", "Living Room Furniture", "Sofas"]
    assert rows[0]["product_type_levels"] == ["Living room", "Sofas"]
    assert rows[0]["custom_labels"] == {"custom_label_0": "bestseller", "custom_label_1": None, "custom_label_2": None,
                                        "custom_label_3": "autumn", "custom_label_4": None}
    query = queries[0]
    for field in ["category_l1", "category_l5", "product_type_l5", "custom_label0", "custom_label4"]:
        assert field in query


def test_product_view_merge_keeps_labels_and_never_asks_it_for_custom_labels(monkeypatch):
    health = [
        {"productView": {"offerId": "SKU-1", "availability": "IN_STOCK", "categoryL1": "Furniture", "categoryL2": "Beds"}},
        {"productView": {"offerId": "SKU-2", "availability": "IN_STOCK"}},
    ]
    performance = [
        performance_view(productTypeL1="Bedroom", customLabel0="new"),
        {"productPerformanceView": {**performance_view(categoryL1="Lighting")["productPerformanceView"],
                                    "offerId": "SKU-2"}},
    ]
    merchant, queries = connector(monkeypatch, {**CONFIG, "include_product_health": True}, performance, health)
    first, second = merchant.fetch_product_metrics(DAY, DAY)
    assert first["category_levels"] == ["Furniture", "Beds"] and first["product_type_levels"] == ["Bedroom"]
    assert first["custom_labels"]["custom_label_0"] == "new"
    # Product view without categories must not blank the ones the performance row had.
    assert second["category_levels"] == ["Lighting"]
    health_query = next(query for query in queries if "FROM product_view" in query)
    assert "category_l5" in health_query and "custom_label" not in health_query


def test_audit_feed_rows_show_the_latest_category_and_labels(db):
    for day, labels, levels in [
        (date(2031, 3, 10), {"custom_label_0": "old segment"}, ["Furniture"]),
        (DAY, {"custom_label_0": "zombie", "custom_label_2": None}, ["Furniture", "Sofas"]),
    ]:
        db.add(MerchantProductMetric(metric_date=day, item_id="TEST-LABEL-1", title="Test sofa", clicks=5,
                                     impressions=100, price=Decimal("10"),
                                     raw={"custom_labels": labels, "category_levels": levels}))
    db.add(MerchantProductMetric(metric_date=DAY, item_id="TEST-LABEL-2", title="Older row", clicks=1,
                                 impressions=10, raw={}))
    db.flush()
    _, feed_rows, _ = _product_audit(db, date(2031, 3, 10), DAY)
    row = next(item for item in feed_rows if item["item_id"] == "TEST-LABEL-1")
    assert row["custom_labels"] == {"custom_label_0": "zombie"}
    assert row["category_levels"] == ["Furniture", "Sofas"]
    assert row["clicks"] == 10
    plain = next(item for item in feed_rows if item["item_id"] == "TEST-LABEL-2")
    assert (plain["custom_labels"], plain["category_levels"], plain["product_type_levels"]) == ({}, [], [])
