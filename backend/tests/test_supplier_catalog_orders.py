from datetime import date, datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.deps import get_current_user
from app.api.routes.supplier_catalog import router
from app.db.session import get_db
from app.models import OpenCartOrder, OpenCartOrderProduct, ProductCatalog, SupplierCatalogFeed, SupplierCatalogProduct
from app.services.supplier_catalog_orders import product_orders

START, END = date(2026, 1, 1), date(2026, 1, 31)


def catalog(db, *, own_id="42", own_model="INDE-MODEL"):
    own = ProductCatalog(sku="INDE-SKU", product_id=own_id, model=own_model, name="Our product")
    feed = SupplierCatalogFeed(code="ORDER-TEST", name="Supplier", adapter="megapap", encrypted_url="unused")
    db.add_all([own, feed]); db.flush()
    supplier = SupplierCatalogProduct(feed_id=feed.id, supplier_code="SUPPLIER-42", name="Same name",
                                      product_catalog_id=own.id, match_method="sku", last_seen_at=datetime.now(timezone.utc))
    db.add(supplier); db.flush()
    return supplier, own


def order(db, number, *, product_id="42", sku=None, model=None, day=15, month=1, quantity=1, status="Completed"):
    result = OpenCartOrder(order_id=number, date_added=datetime(2026, month, day, 12, tzinfo=timezone.utc), order_status=status)
    result.products.append(OpenCartOrderProduct(product_id=product_id, sku=sku, model=model, name="Same name", quantity=quantity))
    db.add(result); db.flush()
    return result


def test_orders_exact_identity_dates_all_statuses_and_one_row_per_order(db):
    supplier, _ = catalog(db)
    first = order(db, "100", day=1, quantity=2)
    first.products.append(OpenCartOrderProduct(product_id="42", name="Option two", quantity=3))
    order(db, "101", day=31, status="Cancelled")
    order(db, "102", month=2)
    order(db, "103", product_id="other", sku="INDE-SKU")
    order(db, "104", product_id=None, sku="SUPPLIER-42", model="different")
    db.flush()
    result = product_orders(db, supplier.id, START, END, limit=1)
    assert result["total"] == 2 and result["rows"][0]["order_id"] == "101"
    assert result["rows"][0]["order_status"] == "Cancelled"
    second = product_orders(db, supplier.id, START, END, offset=1, limit=1)
    assert second["rows"][0]["order_id"] == "100" and second["rows"][0]["quantity"] == 5
    assert set(second["rows"][0]) == {"order_id", "date_added", "order_status", "quantity"}


def test_missing_order_id_uses_inde_sku_or_unique_model_not_supplier_code(db):
    supplier, _ = catalog(db)
    order(db, "100", product_id=None, sku="INDE-SKU")
    order(db, "101", product_id="", model="INDE-MODEL")
    order(db, "102", product_id=None, sku="foreign", model="INDE-MODEL")
    result = product_orders(db, supplier.id, START, END)
    assert result["total"] == 2


def test_ambiguous_model_is_not_used(db):
    supplier, _ = catalog(db)
    db.add(ProductCatalog(sku="OTHER", model="INDE-MODEL", name="Other product")); db.flush()
    order(db, "100", product_id=None, model="INDE-MODEL")
    assert product_orders(db, supplier.id, START, END)["total"] == 0


def test_missing_catalog_id_can_use_sku_without_stealing_known_product_id(db):
    supplier, _ = catalog(db, own_id=None)
    db.add(ProductCatalog(sku="OTHER", product_id="99", name="Other product")); db.flush()
    order(db, "100", product_id="42", sku="INDE-SKU")
    order(db, "101", product_id="99", sku="INDE-SKU")
    result = product_orders(db, supplier.id, START, END)
    assert [row["order_id"] for row in result["rows"]] == ["100"]


def test_no_name_fallback_and_unmatched_supplier(db):
    supplier, _ = catalog(db)
    order(db, "100", product_id="other")
    assert product_orders(db, supplier.id, START, END)["total"] == 0
    supplier.product_catalog_id = None; db.flush()
    assert product_orders(db, supplier.id, START, END)["match_status"] == "unmatched"
    with pytest.raises(LookupError):
        product_orders(db, uuid4(), START, END)
    with pytest.raises(ValueError):
        product_orders(db, supplier.id, END, START)


def test_api_admin_only_validation_and_pagination(db):
    supplier, _ = catalog(db)
    order(db, "100")
    app = FastAPI(); app.include_router(router, prefix="/api")
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(is_admin=True)
    url = f"/api/supplier-catalog/products/{supplier.id}/orders"
    with TestClient(app) as client:
        params = {"date_from": str(START), "date_to": str(END), "limit": 1}
        response = client.get(url, params=params)
        assert response.status_code == 200 and response.json()["rows"][0]["order_id"] == "100"
        assert client.get(url, params={**params, "offset": 1}).json()["rows"] == []
        assert client.get(url, params={**params, "limit": 101}).status_code == 422
        assert client.get(url, params={**params, "offset": -1}).status_code == 422
        assert client.get(url, params={**params, "date_from": str(END), "date_to": str(START)}).status_code == 422
        assert client.get(f"/api/supplier-catalog/products/{uuid4()}/orders", params=params).status_code == 404
        app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(is_admin=False)
        assert client.get(url, params=params).status_code == 403
