import os
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

from sqlalchemy import create_engine, delete, func, select
from sqlalchemy.orm import Session

from app.models import Supplier, SupplierDocument, SupplierImportBatch, SupplierProductCost, SupplierProductMap, SupplierShippingCost
from app.schemas.suppliers import SupplierImportRequest
from app.services.supplier_service import import_supplier_documents


def test_concurrent_imports_are_serialized(db):
    # Use independent committed sessions, then remove only this test's unique supplier.
    engine = create_engine(os.environ["SUPPLIER_TEST_DATABASE_URL"])
    code = "TEST_" + uuid4().hex.upper()
    payload = SupplierImportRequest.model_validate({"supplier": {"code": code, "name": "Concurrency test"}, "documents": [
        {"document_type": "invoice", "document_number": "ONE", "document_date": "2026-07-01", "lines": [
            {"supplier_sku": uuid4().hex, "quantity": 1, "unit_price_before_discount": 8}]}]})

    def run_import(_):
        with Session(engine, autoflush=False) as session:
            return import_supplier_documents(session, payload)

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(run_import, range(2)))
        assert sum(row["documents_imported"] for row in results) == 1
        assert sum(row["duplicate"] for row in results) == 1
        with Session(engine) as session:
            supplier = session.scalar(select(Supplier).where(Supplier.code == code))
            assert session.scalar(select(func.count()).select_from(SupplierDocument).where(SupplierDocument.supplier_id == supplier.id)) == 1
    finally:
        with engine.begin() as connection:
            supplier_id = connection.scalar(select(Supplier.id).where(Supplier.code == code))
            if supplier_id:
                for model in (SupplierProductCost, SupplierShippingCost, SupplierDocument, SupplierImportBatch, SupplierProductMap):
                    connection.execute(delete(model).where(model.supplier_id == supplier_id))
                connection.execute(delete(Supplier).where(Supplier.id == supplier_id))
        engine.dispose()
