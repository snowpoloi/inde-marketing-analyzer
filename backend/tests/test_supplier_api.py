from datetime import date
from types import SimpleNamespace
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import inspect

from app.api.deps import get_current_user
from app.api.routes import suppliers
from app.db.session import get_db
from app.models import Base, SupplierProductMap
from app.services.supplier_service import import_supplier_documents
from test_supplier_integration import payload, seed


def client(db, admin):
    application = FastAPI()
    application.include_router(suppliers.router, prefix="/api")
    application.dependency_overrides[get_db] = lambda: db
    application.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=uuid4(), is_admin=admin)
    return TestClient(application)


def test_supplier_apis_and_no_non_admin_access(db):
    seed(db)
    with client(db, True) as http:
        body = payload().model_dump(mode="json")
        assert http.post("/api/suppliers/imports", json=body).status_code == 200
        assert http.post("/api/suppliers/imports", json=body).json()["data"]["duplicate"]
        assert http.get("/api/suppliers/catalog-search?q=GP041").json()["data"]["rows"][0]["sku"] == "INDE-1"
        response = http.get("/api/suppliers/performance?date_from=2026-07-01&date_to=2026-07-31")
        assert response.status_code == 200
        supplier_id = response.json()["data"]["rows"][0]["supplier_id"]
        assert http.put(f"/api/suppliers/{supplier_id}/settings", json={"free_shipping_threshold": 100}).status_code == 200
        row = http.get("/api/suppliers/performance?date_from=2026-07-01&date_to=2026-07-31").json()["data"]["rows"][0]
        assert row["threshold_gap"] == 91.8
        assert row["shipping_trend"] == [{"month": "2026-07", "freight": 4.9}]
        simulation = http.get(f"/api/suppliers/{supplier_id}/shipping-simulation?threshold=8&date_from=2026-07-01&date_to=2026-07-31").json()["data"]
        assert simulation["potential_savings"] == 4.9
        assert simulation["eligible_orders"] == 1
        assert http.get(f"/api/suppliers/{supplier_id}/shipping-simulation?threshold=-1").status_code == 422
        assert http.get("/api/suppliers/summary?date_from=2026-08-01&date_to=2026-07-01").status_code == 400
        assert http.post("/api/suppliers/imports/json", files={"file": ("data.json", b"{}", "application/json")}).status_code == 400
    with client(db, False) as http:
        assert http.get("/api/suppliers/products").status_code == 403
        assert http.post("/api/suppliers/imports", json=body).status_code == 403
        assert http.get("/api/suppliers/catalog-search?q=GP041").status_code == 403


def test_supplier_migration_matches_model_columns_and_indexes(db):
    inspector = inspect(db.get_bind())
    for table_name, table in Base.metadata.tables.items():
        if not table_name.startswith("supplier") and table_name != "suppliers":
            continue
        columns = {column["name"]: column for column in inspector.get_columns(table_name)}
        assert set(columns) == set(table.columns.keys())
        for column in table.columns:
            assert columns[column.name]["nullable"] == column.nullable
            assert str(columns[column.name]["type"].compile(dialect=db.get_bind().dialect)) == str(column.type.compile(dialect=db.get_bind().dialect))
        actual = {index["name"] for index in inspector.get_indexes(table_name)}
        assert {index.name for index in table.indexes} <= actual


def test_supplier_config_is_not_erased_by_reimport(db):
    from app.models import Supplier
    from sqlalchemy import select
    seed(db)
    import_supplier_documents(db, payload())
    supplier = db.scalar(select(Supplier))
    supplier.free_shipping_threshold = 100
    db.commit()
    import_supplier_documents(db, payload(number="INV2"))
    assert supplier.free_shipping_threshold == 100
