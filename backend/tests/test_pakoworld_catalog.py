import io
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from defusedxml.common import DefusedXmlException
from sqlalchemy import func, select

from app.connectors import supplier_catalog as connector
from app.models import ProductCatalog, SupplierCatalogProduct, SupplierProductCost
from app.schemas.supplier_catalog import SupplierCatalogFeedInput
from app.services import supplier_catalog_service as service


URL = "https://www.pakoworld.com/?route=feed&token=fixture-private-token"


def xml(model="123-000001", extra=""):
    return f"""<pakoworld><products><product id="55"><model>{model}</model>
    <ean>5207351018882</ean><name>Garden cabinet</name><quantity>102</quantity>
    <net_price>57.1</net_price><stock_price>57.1</stock_price><has_net_price>0</has_net_price>
    <retail_price_with_vat>90.00</retail_price_with_vat><sell_step>2</sell_step>
    <main_image>https://www.pakoworld.com/image/cabinet.jpg</main_image>
    <width>37</width><length>80</length><height>123</height><volume>0.089</volume>
    <attributes><attribute id="4">Package: 123x40x18</attribute></attributes>
    <categories><category id="145">Storage</category></categories>
    <component_1>001-000002</component_1><pieces_1>2</pieces_1>{extra}
    </product></products></pakoworld>""".encode()


def rows():
    return connector.parse_pakoworld_catalog(io.BytesIO(xml()))


def test_pakoworld_fields_do_not_infer_costs_tax_or_shipping():
    row = rows()[0]
    assert row["supplier_code"] == "123-000001" and row["supplier_sku"] is None
    assert row["ean"] == "5207351018882" and row["quantity"] == 102
    assert row["retail_price_gross"] == "90.00" and row["wholesale_price_net"] is None
    assert row["details"]["net_price"] == "57.1" and row["details"]["has_net_price"] == "0"
    assert row["details"]["sell_step"] == "2"
    assert row["details"]["comb_width_cm"] is None
    assert row["details"]["attributes"] == [{"id": "4", "value": "Package: 123x40x18"}]
    assert row["details"]["components"] == [{"model": "001-000002", "pieces": "2"}]
    assert row["details"]["categories"] == [{"id": "145", "name": "Storage"}]
    assert "net_unit_cost" not in row and "shipping_net" not in row


@pytest.mark.parametrize("adapter, url", [
    ("megapap", URL), ("pakoworld", "https://www.megapap.com/feed"),
    ("pakoworld", "http://pakoworld.com/feed"), ("pakoworld", "https://pakoworld.com.evil.test/"),
    ("pakoworld", "https://user:secret@pakoworld.com/"), ("pakoworld", "https://127.0.0.1/"),
    ("pakoworld", "https://pakoworld.com:9000/"), ("pakoworld", "https://pakoworld.com/feed#fragment"),
])
def test_schema_binds_url_to_adapter(adapter, url):
    with pytest.raises(ValueError):
        SupplierCatalogFeedInput(code="PAKOWORLD", name="Pakketo", adapter=adapter, url=url)


def test_pakoworld_schema_and_optional_url():
    payload = SupplierCatalogFeedInput(code="AADE_800749270", name="Pakketo", url=URL, adapter="pakoworld")
    assert payload.url == URL
    assert SupplierCatalogFeedInput(code="PAKOWORLD", name="Pakketo", adapter="pakoworld", url=" ").url is None
    with pytest.raises(ValueError):
        SupplierCatalogFeedInput(code="OTHER", name="Other", adapter="arbitrary", url=URL)


def test_wrong_roots_empty_duplicate_and_entities_are_rejected():
    with pytest.raises(ValueError, match="PAKOWORLD"):
        connector.parse_pakoworld_catalog(io.BytesIO(b"<megapap/>"))
    with pytest.raises(ValueError, match="MEGAPAP"):
        connector.parse_megapap_catalog(io.BytesIO(xml()))
    with pytest.raises(ValueError, match="no products"):
        connector.parse_pakoworld_catalog(io.BytesIO(b"<pakoworld/>"))
    product = xml().decode().split("<products>")[1].split("</products>")[0]
    with pytest.raises(ValueError, match="Duplicate"):
        connector.parse_pakoworld_catalog(io.BytesIO(f"<pakoworld><products>{product}{product}</products></pakoworld>".encode()))
    with pytest.raises(DefusedXmlException):
        connector.parse_pakoworld_catalog(io.BytesIO(b'<!DOCTYPE x [<!ENTITY y "data">]><pakoworld>&y;</pakoworld>'))


def test_media_cannot_point_to_other_suppliers_or_token_urls():
    row = connector.parse_pakoworld_catalog(io.BytesIO(xml(extra="""<images>
        <image>https://www.megapap.com/image.jpg</image><image>https://www.pakoworld.com/image.jpg?token=private</image>
        <image>https://www.pakoworld.com/safe.jpg</image></images>""")))[0]
    assert row["details"]["images"] == ["https://www.pakoworld.com/safe.jpg"]


def test_pakoworld_model_checks_own_sku_but_conflicts_never_choose_arbitrarily():
    first, second = uuid4(), uuid4()
    def own(id, sku, ean=None):
        return SimpleNamespace(id=id, sku=sku, model=None, mpn=None, ean=ean, upc=None)
    index = service.build_catalog_index([own(first, "123-000001")])
    assert service.match_supplier_product(rows()[0], index, "pakoworld") == (first, "exact_identifiers")
    assert service.match_supplier_product(rows()[0], index, "megapap") == (None, "unmatched")
    index = service.build_catalog_index([own(first, "123-000001"), own(second, "Other", "5207351018882")])
    assert service.match_supplier_product(rows()[0], index, "pakoworld") == (None, "ambiguous")


def test_fetch_get_only_streaming_size_limit_and_cross_supplier_redirect(monkeypatch):
    client_class = httpx.Client
    calls = []
    def handler(request):
        calls.append(request.method)
        return httpx.Response(200, content=xml())
    monkeypatch.setattr(connector.httpx, "Client", lambda **kwargs: client_class(transport=httpx.MockTransport(handler), **kwargs))
    assert connector.fetch_pakoworld_catalog(URL)[0]["supplier_code"] == "123-000001"
    assert calls == ["GET"]
    monkeypatch.setattr(connector, "PAKOWORLD_MAX_FEED_BYTES", 32)
    with pytest.raises(ValueError, match="size or time"):
        connector.fetch_pakoworld_catalog(URL)
    def redirect(request):
        return httpx.Response(302, headers={"Location": "https://www.megapap.com/feed"})
    monkeypatch.setattr(connector.httpx, "Client", lambda **kwargs: client_class(transport=httpx.MockTransport(redirect), **kwargs))
    with pytest.raises(ValueError, match="HTTPS"):
        connector.fetch_pakoworld_catalog(URL)


def test_worker_dispatch_encryption_and_no_financial_mutations(db, monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings, "secret_key", "isolated-pakoworld-test-key")
    own = ProductCatalog(sku="123-000001", name="Our cabinet", quantity=7, price=99)
    db.add(own); db.flush()
    saved = service.save_feed(db, SupplierCatalogFeedInput(code="AADE_800749270", name="Pakketo",
                                                         adapter="pakoworld", url=URL))
    assert "fixture-private-token" not in saved.encrypted_url
    assert "fixture-private-token" not in str(service.feed_response(saved))
    def wrong_fetch(url):
        pytest.fail("Pakoworld must not use the MEGAPAP adapter")
    monkeypatch.setattr(service, "fetch_megapap_catalog", wrong_fetch)
    monkeypatch.setattr(service, "fetch_pakoworld_catalog", lambda url: rows())
    assert service.process_supplier_catalog(db)["matched"] == 1
    assert db.scalar(select(func.count()).select_from(SupplierCatalogProduct)) == 1
    assert db.scalar(select(func.count()).select_from(SupplierProductCost)) == 0
    db.refresh(own)
    assert own.price == 99 and own.quantity == 7 and own.name == "Our cabinet"
    service.save_feed(db, SupplierCatalogFeedInput(code=saved.code, name="Pakketo", adapter="pakoworld"), saved.id)
    with pytest.raises(ValueError, match="megapap"):
        service.save_feed(db, SupplierCatalogFeedInput(code=saved.code, name="Pakketo", adapter="megapap"), saved.id)
    service.queue_feed(db, saved.id)
    monkeypatch.setattr(service, "fetch_pakoworld_catalog", lambda url: (_ for _ in ()).throw(RuntimeError(url)))
    assert service.process_supplier_catalog(db) == {"failed": True}
    assert "fixture-private-token" not in saved.error
    assert db.scalar(select(func.count()).select_from(SupplierCatalogProduct).where(SupplierCatalogProduct.is_current)) == 1
