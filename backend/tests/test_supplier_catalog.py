import io
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from defusedxml.common import DefusedXmlException
from sqlalchemy import func, select

from app.connectors import supplier_catalog as connector
from app.core.config import settings
from app.models import ProductCatalog, SupplierCatalogFeed, SupplierCatalogProduct, SupplierProductCost
from app.schemas.supplier_catalog import SupplierCatalogFeedInput
from app.services import supplier_catalog_service as service

URL = "https://www.megapap.com/?route=feed&token=fixture-private-token"


def xml(code="0268292", sku="CH-N5080-GR", extra=""):
    return f"""<megapap><products><product id="14840"><model>{code}</model><sku>{sku}</sku>
    <ean>5203266100377</ean><name>Garden chair</name><quantity>168</quantity>
    <wholesale_price_without_vat>20.97</wholesale_price_without_vat><retail_price_with_vat>26</retail_price_with_vat>
    <main_image>https://www.megapap.com/image/chair.jpg</main_image><comb_width_cm>0</comb_width_cm>
    <filters><filter><group>Color</group><value>Grey</value></filter></filters>{extra}</product></products></megapap>""".encode()


def rows(**kwargs):
    return connector.parse_megapap_catalog(io.BytesIO(xml(**kwargs)))


@pytest.fixture
def private_key(monkeypatch):
    monkeypatch.setattr(settings, "secret_key", "isolated-supplier-catalog-test-key")


def feed(db):
    return service.save_feed(db, SupplierCatalogFeedInput(code="MEGAPAP", name="MEGAPAP", url=URL))


def test_parser_identifiers_prices_stock_and_zero_dimensions():
    product = rows()[0]
    assert product["supplier_code"] == "0268292"
    assert product["supplier_sku"] == "CH-N5080-GR"
    assert product["wholesale_price_net"] == "20.97"
    assert product["quantity"] == 168
    assert product["details"]["comb_width_cm"] == "0"
    assert product["details"]["filters"] == [{"group": "Color", "value": "Grey"}]
    assert "net_unit_cost" not in product


@pytest.mark.parametrize("url", ["http://megapap.com/", "https://127.0.0.1/", "https://megapap.com.evil.test/", "https://user:secret@megapap.com/", "https://megapap.com:9000/"])
def test_private_or_unaudited_destinations_are_rejected(url):
    with pytest.raises(ValueError):
        connector.validate_feed_url(url)


def test_parser_rejects_empty_duplicate_models_and_entities():
    with pytest.raises(ValueError, match="no products"):
        connector.parse_megapap_catalog(io.BytesIO(b"<megapap><products/></megapap>"))
    product = xml().decode().split("<products>")[1].split("</products>")[0]
    with pytest.raises(ValueError, match="Duplicate"):
        connector.parse_megapap_catalog(io.BytesIO(f"<megapap><products>{product}{product}</products></megapap>".encode()))
    with pytest.raises(DefusedXmlException):
        connector.parse_megapap_catalog(io.BytesIO(b'<!DOCTYPE x [<!ENTITY y "data">]><megapap>&y;</megapap>'))


def test_conflicting_identifiers_are_not_matched():
    first, second = uuid4(), uuid4()
    index = service.build_catalog_index([
        SimpleNamespace(id=first, sku="CH-N5080-GR", model=None, ean=None, upc=None, mpn=None),
        SimpleNamespace(id=second, sku="other", model=None, ean="5203266100377", upc=None, mpn=None),
    ])
    assert service.match_supplier_product(rows()[0], index) == (None, "ambiguous")


def test_fetch_uses_get_only_and_rejects_unsafe_redirect(monkeypatch):
    calls = []
    def handler(request):
        calls.append(request.method)
        return httpx.Response(200, content=xml())
    client_class = httpx.Client
    monkeypatch.setattr(connector.httpx, "Client", lambda **kwargs: client_class(transport=httpx.MockTransport(handler), **kwargs))
    assert connector.fetch_megapap_catalog(URL)[0]["supplier_code"] == "0268292"
    assert calls == ["GET"]
    def redirect(request):
        return httpx.Response(302, headers={"Location": "http://127.0.0.1/private"})
    monkeypatch.setattr(connector.httpx, "Client", lambda **kwargs: client_class(transport=httpx.MockTransport(redirect), **kwargs))
    with pytest.raises(ValueError, match="HTTPS"):
        connector.fetch_megapap_catalog(URL)


def test_feed_is_encrypted_and_edit_preserves_url(db, private_key):
    saved = feed(db)
    encrypted = saved.encrypted_url
    assert "fixture-private-token" not in encrypted
    assert service._cipher().decrypt(encrypted.encode()).decode() == URL
    assert "token" not in str(service.feed_response(saved))
    service.save_feed(db, SupplierCatalogFeedInput(code="MEGAPAP", name="MEGAPAP", refresh_hours=48), saved.id)
    assert saved.encrypted_url == encrypted
    assert saved.refresh_hours == 48


def test_atomic_catalog_upserts_and_no_financial_or_shop_changes(db, private_key):
    own = ProductCatalog(sku="CH-N5080-GR", name="Our chair", quantity=7, price=99)
    db.add(own); db.flush()
    saved = feed(db)
    counts = service.apply_catalog(db, saved, rows())
    db.commit()
    assert counts["matched"] == 1
    service.apply_catalog(db, saved, rows())
    db.commit()
    assert db.scalar(select(func.count()).select_from(SupplierCatalogProduct)) == 1
    assert db.scalar(select(func.count()).select_from(SupplierProductCost)) == 0
    db.refresh(own)
    assert own.price == 99 and own.quantity == 7 and own.name == "Our chair"
    result = service.catalog_products(db, feed_id=saved.id, q="0268292", match="matched", availability="in_stock", category="", offset=0, limit=50)
    assert result["rows"][0]["opencart_sku"] == "CH-N5080-GR"
    assert result["summary"] == {"products": 1, "matched": 1, "unmatched": 0}
    service.apply_catalog(db, saved, rows(code="000NEW", sku="NEW")); db.commit()
    assert db.scalar(select(func.count()).select_from(SupplierCatalogProduct).where(SupplierCatalogProduct.is_current)) == 1
    assert db.scalar(select(func.count()).select_from(SupplierCatalogProduct)) == 2


def test_worker_failure_retains_last_snapshot_and_hides_secrets(db, private_key, monkeypatch):
    saved = feed(db)
    monkeypatch.setattr(service, "fetch_megapap_catalog", lambda url: rows())
    assert service.process_supplier_catalog(db)["products"] == 1
    success_at = saved.last_synced_at
    service.queue_feed(db, saved.id)
    def fail(url):
        raise RuntimeError(url)
    monkeypatch.setattr(service, "fetch_megapap_catalog", fail)
    assert service.process_supplier_catalog(db) == {"failed": True}
    assert saved.status == "failed" and saved.last_synced_at == success_at
    assert "fixture-private-token" not in saved.error
    assert db.scalar(select(func.count()).select_from(SupplierCatalogProduct).where(SupplierCatalogProduct.is_current)) == 1
    assert service.process_supplier_catalog(db) is None


def test_worker_recovers_stale_job_and_disable_stops_automatic_reads(db, private_key, monkeypatch):
    saved = feed(db)
    saved.is_enabled = False; db.commit()
    calls = []
    monkeypatch.setattr(service, "fetch_megapap_catalog", lambda url: calls.append(url) or rows())
    assert service.process_supplier_catalog(db) is None
    service.queue_feed(db, saved.id)
    saved.status = "running"
    saved.started_at = datetime.now(timezone.utc) - timedelta(minutes=31); db.commit()
    assert service.process_supplier_catalog(db)["products"] == 1
    assert len(calls) == 1


def test_api_admin_only_and_paginated_without_url_leaks(db, private_key):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.api.deps import get_current_user
    from app.api.routes import supplier_catalog
    from app.db.session import get_db
    app = FastAPI(); app.include_router(supplier_catalog.router, prefix="/api")
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(is_admin=True)
    with TestClient(app) as client:
        response = client.post("/api/supplier-catalog/feeds", json={"code": "MEGAPAP", "name": "MEGAPAP", "url": URL})
        assert response.status_code == 200
        assert "fixture-private-token" not in response.text
        saved = db.get(SupplierCatalogFeed, response.json()["id"])
        service.apply_catalog(db, saved, rows()); db.commit()
        data = client.get("/api/supplier-catalog/products?limit=1").json()
        assert len(data["rows"]) == 1 and data["total"] == 1
        assert client.get(f'/api/supplier-catalog/products/{data["rows"][0]["id"]}').status_code == 200
        assert client.post(f"/api/supplier-catalog/feeds/{saved.id}/sync").json()["status"] == "queued"
        assert client.get("/api/supplier-catalog/products?limit=1001").status_code == 422
        app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(is_admin=False)
        assert client.get("/api/supplier-catalog/products").status_code == 403
        assert client.get("/api/supplier-catalog/feeds").status_code == 403
        assert client.post(f"/api/supplier-catalog/feeds/{saved.id}/sync").status_code == 403
