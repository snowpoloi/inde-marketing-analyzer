import io
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from defusedxml.common import DefusedXmlException
from sqlalchemy import func, select

from app.connectors import supplier_catalog as connector
from app.core.config import settings
from app.models import (AADEDocument, IntegrationSetting, ProductCatalog, Supplier, SupplierCatalogFeed, SupplierCatalogProduct,
                        SupplierDocument, SupplierDocumentLine, SupplierProductCost, SupplierProductMap)
from app.schemas.supplier_catalog import SupplierCatalogFeedInput
from app.services import supplier_catalog_service as service
from app.services.supplier_catalog_pricing import catalog_sale_price, latest_aade_costs, price_comparison

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


@pytest.mark.parametrize("count", range(1, 11))
def test_package_dimensions_are_matched_by_label(count):
    from app.services.supplier_catalog_settings import package_metrics
    labels = [chr(65 + i) for i in range(count)]
    dimensions = {"width_cm": " ".join(f"BOX {label}: 40,5" for label in labels),
                  "length_cm": " ".join(f"BOX {label}: 100" for label in reversed(labels)),
                  "height_cm": " ".join(f"BOX {label}: 10" for label in labels)}
    packages = connector.parse_packages(dimensions, str(count))
    assert len(packages) == count
    assert packages[0]["width_cm"] == "40.5"
    metrics = package_metrics({"packages": packages}, 5000)
    assert metrics["packages"][0]["volume_m3"] == Decimal("0.0405")
    assert metrics["packages"][0]["volumetric_kg"] == Decimal("8.1")
    assert metrics["volume_total_m3"] == Decimal("0.0405") * count
    assert package_metrics({"packages": packages}, 6000)["packages"][0]["volumetric_kg"] == Decimal("6.75")


def test_missing_package_dimensions_are_never_invented_or_split():
    from app.services.supplier_catalog_settings import package_metrics
    packages = connector.parse_packages({"width_cm": "BOX A: 40 BOX B: 50", "length_cm": "BOX A: 100", "height_cm": "BOX A: 10 BOX B: 12"}, "2")
    metrics = package_metrics({"packages": packages}, 5000)
    assert metrics["packages"][1]["volume_m3"] is None
    assert metrics["volume_total_m3"] is None
    assert package_metrics({"packages": [metrics["packages"][0]], "packages_per_item":"2"}, 5000)["volume_total_m3"] is None
    assert connector.parse_packages({"width_cm":"40", "length_cm":"100", "height_cm":"10"}, "2")[1]["width_cm"] is None
    assert connector.parse_packages({"width_cm":"BOX A: 40 BOX A: 60", "length_cm":"BOX A: 100", "height_cm":"BOX A: 10"}, "1")[0]["width_cm"] is None


def test_parser_preserves_box_text_and_extracts_package_dimensions():
    product = rows(extra="<packages_per_item>2</packages_per_item><comb_length_cm>BOX A: 100 BOX B: 90</comb_length_cm><comb_height_cm>BOX A: 10 BOX B: 12</comb_height_cm>")[0]
    assert product["details"]["package_dimensions_raw"]["length_cm"] == "BOX A: 100 BOX B: 90"
    assert product["details"]["packages"][1]["length_cm"] == "90"


def test_confirmed_vat_inclusive_inde_price():
    own = SimpleNamespace(price=Decimal("99"), raw={})
    cost = SimpleNamespace(net_unit_cost=Decimal("59.36"), purchase_date=date(2026, 9, 25))
    row = price_comparison(own, (cost, "MARK"), confirmed_vat_rate="24")
    assert row["inde_price"] == 99 and row["inde_price_net"] == Decimal("79.8387")
    assert row["gross_profit_per_unit"] == Decimal("20.4787")
    assert row["gross_margin_percent"] == Decimal("25.65")
    own.raw = {"vat_rate": 13}
    assert catalog_sale_price(own, confirmed_vat_rate=24)["inde_price_net"] == Decimal("87.6106")
    own.raw = {"currency":"USD"}
    assert catalog_sale_price(own, confirmed_vat_rate=24)["inde_price_net"] is None


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
    assert result["rows"][0]["inde_price"] == 99
    assert result["rows"][0]["aade_cost_net"] is None
    assert result["rows"][0]["gross_margin_percent"] is None
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
        assert client.get("/api/supplier-catalog/pricing-settings").json()["automatic_costs"] is False
        assert client.put("/api/supplier-catalog/pricing-settings", json={"volumetric_divisor":0}).status_code == 422
        app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(is_admin=True, id=uuid4())
        assert client.put("/api/supplier-catalog/pricing-settings", json={"piece_supplier_ids":[str(uuid4())]}).status_code == 400
        pricing = client.put("/api/supplier-catalog/pricing-settings", json={"sale_vat_rate":24,"volumetric_divisor":6000})
        assert pricing.status_code == 200 and pricing.json()["volumetric_divisor"] == 6000
        assert "authorized_by" not in pricing.json()
        assert client.get("/api/supplier-catalog/pricing-settings").json()["sale_vat_rate"] == "24"
        assert client.get("/api/supplier-catalog/products?limit=1001").status_code == 422
        app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(is_admin=False)
        assert client.get("/api/supplier-catalog/products").status_code == 403
        assert client.get("/api/supplier-catalog/feeds").status_code == 403
        assert client.get("/api/supplier-catalog/pricing-settings").status_code == 403
        assert client.put("/api/supplier-catalog/pricing-settings", json={}).status_code == 403
        assert client.post(f"/api/supplier-catalog/feeds/{saved.id}/sync").status_code == 403


def test_net_margin_requires_confirmed_sale_tax_basis_and_aade_cost():
    own = SimpleNamespace(price=Decimal("124"), raw={"prices_include_vat": True, "vat_rate": 24})
    cost = SimpleNamespace(net_unit_cost=Decimal("70"), purchase_date=date(2026, 1, 2))
    result = price_comparison(own, (cost, "MARK-1"))
    assert result["inde_price"] == 124 and result["inde_price_net"] == 100
    assert result["gross_profit_per_unit"] == 30 and result["gross_margin_percent"] == 30
    assert result["aade_mark"] == "MARK-1" and result["margin_status"] == "available"
    own.raw = {}
    assert price_comparison(own, (cost, "MARK-1"))["gross_margin_percent"] is None
    own.raw = {"prices_include_vat": False}
    own.price = Decimal("50")
    assert price_comparison(own, (cost, "MARK-1"))["gross_margin_percent"] == -40
    own.price = Decimal("0")
    assert price_comparison(own, (cost, "MARK-1"))["margin_status"] == "zero_sale_price"
    assert price_comparison(own, None)["gross_profit_per_unit"] is None
    assert price_comparison(None, None)["inde_price"] is None
    own.raw = {"price": None}
    assert catalog_sale_price(own)["inde_price"] is None


@pytest.mark.parametrize("raw, expected", [
    ({"prices_include_vat": True}, None),
    ({"prices_include_vat": True, "vat_rate": "bad"}, None),
    ({"prices_include_vat": True, "vat_rate": -1}, None),
    ({"prices_include_vat": True, "vat_rate": 0}, Decimal("124")),
    ({"price_net": "100"}, Decimal("100")),
    ({"prices_include_vat": False, "currency": "USD"}, None),
    ({"raw_fields": {"prices_include_vat": "true", "vat_rate": "24"}}, Decimal("100")),
])
def test_catalog_price_never_guesses_vat(raw, expected):
    assert catalog_sale_price(SimpleNamespace(price=Decimal("124"), raw=raw))["inde_price_net"] == expected


def test_only_verified_aade_purchase_costs_qualify(db):
    own = ProductCatalog(sku="pricing-chair", name="Chair", price=124, raw={"prices_include_vat": True, "vat_rate": 24})
    supplier = Supplier(code="MEGAPAP", name="MEGAPAP", vat_number="123456789")
    db.add_all([own, supplier]); db.flush()
    mapping = SupplierProductMap(supplier_id=supplier.id, product_catalog_id=own.id, identity_key="test",
                                 status="matched", verified=True)
    fiscal = AADEDocument(source_endpoint="RequestDocs", identity_key="fiscal-pricing", mark="MARK-1",
                          issuer_vat=supplier.vat_number, counterpart_vat="802216736", issue_date=date(2026, 1, 2), currency="EUR",
                          document_direction="expense", invoice_type="1.1")
    db.add_all([mapping, fiscal]); db.flush()
    document = SupplierDocument(supplier_id=supplier.id, aade_document_id=fiscal.id, identity_key="cost-pricing",
                                document_type="invoice", document_date=fiscal.issue_date, currency="EUR")
    from app.services.supplier_aade_costs import _source_digest
    document.raw_metadata = {"aade_source_digest": _source_digest(fiscal)}
    db.add(IntegrationSetting(provider="aade", display_name="AADE", config={"vat_number": "802216736"}))
    db.add(document); db.flush()
    line = SupplierDocumentLine(document_id=document.id, supplier_product_map_id=mapping.id, line_number="1", line_type="product", quantity=2)
    db.add(line); db.flush()
    cost = SupplierProductCost(supplier_id=supplier.id, supplier_product_map_id=mapping.id, product_catalog_id=own.id,
                               source_line_id=line.id, source_type="aade_invoice", source_key="pricing", purchase_date=fiscal.issue_date,
                               net_unit_cost=70, quantity=2, currency="EUR", status="active", source_confidence=1)
    db.add(cost); db.flush()
    def lookup():
        db.flush()
        return latest_aade_costs(db, {own.id}, {"MEGAPAP"})
    assert lookup()[("MEGAPAP", own.id)][0].net_unit_cost == 70
    for field, bad, good in [("source_type", "invoice", "aade_invoice"), ("currency", "USD", "EUR"),
                             ("quantity", 0, 2), ("source_confidence", Decimal("0.8"), 1), ("status", "void", "active")]:
        setattr(cost, field, bad)
        assert not lookup()
        setattr(cost, field, good)
    for target, field, bad, good in [(mapping, "verified", False, True), (line, "line_type", "shipping", "product"),
                                    (fiscal, "is_cancelled", True, False), (fiscal, "cancelled_by_mark", "CANCEL", None),
                                    (fiscal, "invoice_type", "5.1", "1.1"), (fiscal, "issuer_vat", "other", supplier.vat_number)]:
        setattr(target, field, bad)
        assert not lookup()
        setattr(target, field, good)
    assert not latest_aade_costs(db, {own.id}, {"OTHER"})
    another = SupplierProductCost(supplier_id=supplier.id, supplier_product_map_id=mapping.id, product_catalog_id=own.id,
                                  source_line_id=line.id, source_type="aade_invoice", source_key="pricing-conflict",
                                  purchase_date=fiscal.issue_date, net_unit_cost=80, quantity=1, currency="EUR", status="active")
    db.add(another)
    assert lookup()[("MEGAPAP", own.id)] is None
    another.net_unit_cost = 70
    assert lookup()[("MEGAPAP", own.id)] is not None
